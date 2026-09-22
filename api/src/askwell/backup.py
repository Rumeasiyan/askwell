"""Backup: one portable artefact that excludes what can be regenerated.
`docs/build-plan.md`, `docs/ux/settings.md` §6, ticket `M7-BACKUP-BE-157`.

**Why this exists at all.** Someone replacing their laptop needs to carry six
months of memory, clarifications and conversations onto the new machine —
but not the model weights (a redistributable download, not this user's data)
and not the vector index, which is the single largest thing in the database
and is fully regenerable from `chunks.content` by re-embedding. Shipping
those two in the backup would turn "copy this onto a drive" into "wait for a
multi-gigabyte transfer", which is exactly the friction that stops anyone
from ever taking a backup at all — the ticket's own Business Value.

**What is excluded, and why each is safe to drop:**
- Model weights: never in the database at all — nothing to exclude here,
  they live under `Settings.inference_model_path` and are re-downloaded.
- The trace ring buffer: files under `Settings.trace_dir`, not a table this
  module ever queries — excluded by construction, not by a filter.
- The vector index: `chunks.embedding` and `schema_notes.embedding` only,
  explicitly dropped column-by-column (`_TABLES` below) — regenerable by
  re-embedding `chunks.content`, which the backup *does* carry. `chunks.
  content_tsv` (full-text search, a different index entirely) is *not*
  excluded — since `b7e91a4c3f65` it is a plain application-maintained
  column, not a `GENERATED` one, and it is text-sized, not vector-sized, so
  none of the "tens of gigabytes" reasoning that justifies excluding the
  embedding applies to it.

**The user's own files are never copied**, and were never copied by any
earlier ticket either — `sources.root_path` and `documents.path` are the
only record of where they live. `_USER_FILES_STATEMENT` and the
`user_files_included: False` field on every response this module returns
exist so every caller states that plainly rather than each inventing its
own wording.

**Consistency without refusing.** The ticket's own edge case allows either
refusing a backup mid-ingestion or taking it at a consistent point. This
module takes the second option: `run_job` opens one `REPEATABLE READ`
transaction and reads every table inside it. Postgres fixes the snapshot at
that transaction's first statement, so a document finishing ingestion three
tables into the dump is invisible to the rest of it — no torn snapshot,
and nothing to refuse. The first statement inside that transaction is
`content_encryption.assert_not_migrating` — a passphrase migration changes
what `chunks.content` *means* (plaintext vs Fernet token) row by row while
it runs, which a snapshot cannot paper over, so that one case *is* refused
rather than silently included half-migrated.

**A passphrase-protected backup carries a passphrase-wrapped copy of the
install secret.** `chunks.content` (when encrypted) and `sources.config_encrypted`
are both ciphertext under `crypto.derive_key(install_secret, passphrase)` —
tied to *this* install's secret, which is 32 random bytes that live outside
the database (`Settings.install_secret_path`, C8) and are deliberately never
included in the dump. Restoring those rows onto a machine with a different
(freshly generated) install secret would make them permanently undecryptable
even with the correct passphrase — the key that made them would simply not
exist anywhere. `docs/ux/settings.md` §9's settled decision — "a backup taken
from a passphrase-protected install is encrypted with that passphrase, and
restore refuses clearly without it" — is only true if the passphrase is
enough on its own, so `enqueue` requires it when the corpus is protected and
`run_job` wraps the install secret with `crypto.derive_key(b"", passphrase)`
(a key that depends on nothing install-specific) and writes it to the
manifest as `install_secret_wrapped`. Restore unwraps it with the same
passphrase, writes the *original* install secret back to its own
`install_secret_path`, and the existing content/credential ciphertext
decrypts exactly as it did on the source machine — no re-encryption of
either at backup or restore time. `docs/decisions.md`, this ticket's date.

**The re-embed cost is a stated estimate, not a measurement.**
`ESTIMATED_CHUNKS_PER_SECOND` is a deliberately conservative, unmeasured
constant — no native inference process is available in this environment to
benchmark against, the same gap earlier tickets already recorded
(`docs/BRAIN.md`, `M1-INDEX-ING-032` onward). Stating an unmeasured number
plainly follows the precedent `Settings.retrieval_score_threshold` already
set (`docs/BRAIN.md`, `M2-ABSTAIN-RET-053`) rather than hiding the gap
behind a number that looks more precise than it is.

Same shape as `askwell.log_export`: a durable row (`backup_jobs`) is the
record of what happened, `arq` is only the transport that wakes a worker to
act on it, and anything still `running` when the process starts is, on one
worker on one machine, unfinished work from last time rather than something
to trust. A run always starts by clearing any previous attempt's output
directory and writing every file to `<name>.tmp` before renaming it into
place, for the same reason `log_export` does: a crash must never leave a
half-written table sitting under the name a finished one would have.
"""

import asyncio
import base64
import json
import shutil
import uuid
import zipfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from askwell import __version__, content_encryption, crypto, passphrase
from askwell.audit import Store, record
from askwell.config import Settings
from askwell.db.engine import session_scope
from askwell.logging import get_logger

log = get_logger(__name__)

BACKUP_JOB_ENQUEUED = "backup_job_enqueued"

_BATCH_SIZE = 2000

# Deliberately conservative and unmeasured — see the module docstring.
# Picked low enough to state an upper bound on the wait rather than promise
# a number nobody has verified on real hardware.
ESTIMATED_CHUNKS_PER_SECOND = 5.0

# table -> (primary key column, columns to drop). Order matters only for
# readability of the artefact — this ticket does not restore, so foreign-key
# dependency order is the next ticket's concern, not this one's.
_TABLES: dict[str, tuple[str, tuple[str, ...]]] = {
    "roots": ("id", ()),
    "sources": ("id", ()),
    "documents": ("id", ()),
    "document_pages": ("id", ()),
    "chunks": ("id", ("embedding",)),
    "memory": ("id", ()),
    "schema_notes": ("id", ("embedding",)),
    "clarifications": ("id", ()),
    "conversations": ("id", ()),
    "messages": ("id", ()),
    "fact_usage": ("id", ()),
    "citations": ("id", ()),
    "web_citations": ("id", ()),
    "settings": ("key", ()),
    "audit_decisions": ("id", ()),
    "audit_interactions": ("id", ()),
}

# The two vector columns, named once so the size estimate and the manifest
# agree on what "the vector index" means without repeating the pair.
_VECTOR_COLUMNS = (("chunks", "embedding"), ("schema_notes", "embedding"))

_USER_FILES_STATEMENT = (
    "Your own files are not included. Askwell never copies them — this backup "
    "carries what it learned from them, not the files themselves."
)

# The FK-safe table order `run_job`/`_dump_table` dump in and `askwell.restore`
# restores in — exposed for that module to import rather than duplicate, the
# same cross-module private-name reuse `askwell.voice_tts` already does for
# `askwell.ask`. Restore is a companion job to this one; the two must agree on
# what "every table" means, and a second copy of this dict is how that drifts.
TABLES = _TABLES


def _wrap_install_secret(install_secret: bytes, backup_passphrase: str) -> str:
    """The install secret, encrypted with a key derived from the passphrase
    alone — see the module docstring's "passphrase-wrapped install secret"
    section for why this, and not the passphrase-plus-install-secret key
    everything else in the corpus already uses, is what makes restore onto a
    different install possible at all."""
    portable_key = crypto.derive_key(b"", backup_passphrase)
    return base64.urlsafe_b64encode(crypto.encrypt(install_secret, portable_key)).decode("ascii")


class PassphraseRequired(Exception):
    """The corpus is passphrase-protected and no passphrase was given.

    Raised by `enqueue`, before anything is written — a backup without the
    wrapped install secret would be one `restore` could never decrypt, which
    is worse than refusing plainly up front.
    """


class InsufficientSpace(Exception):
    def __init__(self, needed_bytes: int, free_bytes: int) -> None:
        self.needed_bytes = needed_bytes
        self.free_bytes = free_bytes
        super().__init__(f"Needs approximately {needed_bytes} bytes, {free_bytes} free.")


@dataclass(frozen=True, slots=True)
class BackupEstimate:
    chunk_count: int
    estimated_reembed_seconds: float
    estimated_size_bytes: int
    passphrase_protected: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "chunk_count": self.chunk_count,
            "estimated_reembed_seconds": self.estimated_reembed_seconds,
            "estimated_size_bytes": self.estimated_size_bytes,
            "passphrase_protected": self.passphrase_protected,
            "user_files_included": False,
            "user_files_statement": _USER_FILES_STATEMENT,
        }


@dataclass(frozen=True, slots=True)
class BackupJob:
    id: uuid.UUID
    status: str
    tables_total: int
    tables_done: int
    rows_total: int
    rows_done: int
    chunk_count: int | None
    estimated_reembed_seconds: float | None
    passphrase_protected: bool | None
    file_bytes: int | None
    error: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "status": self.status,
            "tables_total": self.tables_total,
            "tables_done": self.tables_done,
            "rows_total": self.rows_total,
            "rows_done": self.rows_done,
            "chunk_count": self.chunk_count,
            "estimated_reembed_seconds": self.estimated_reembed_seconds,
            "passphrase_protected": self.passphrase_protected,
            "file_bytes": self.file_bytes,
            "error": self.error,
            "user_files_included": False,
            "user_files_statement": _USER_FILES_STATEMENT,
        }


# --- estimate ------------------------------------------------------------


async def estimate(session: AsyncSession, settings: Settings) -> BackupEstimate:
    """What the settings screen shows before the user commits, and what a
    fresh `run_job` recomputes under its own snapshot — see the module
    docstring for why the two numbers can differ slightly and why that is
    fine (this one is a preflight, not a promise).
    """
    chunk_count = (
        await session.execute(text("SELECT count(*) FROM chunks WHERE content IS NOT NULL"))
    ).scalar_one()
    passphrase_protected = await passphrase.is_enabled(session)

    table_sizes = (
        await session.execute(
            text(
                "SELECT coalesce(sum(pg_total_relation_size(quote_ident(t))), 0) "
                "FROM unnest(CAST(:tables AS text[])) AS t"
            ),
            {"tables": list(_TABLES)},
        )
    ).scalar_one()

    vector_bytes = 0
    for table, column in _VECTOR_COLUMNS:
        vector_rows = (
            await session.execute(text(f"SELECT count(*) FROM {table} WHERE {column} IS NOT NULL"))
        ).scalar_one()
        vector_bytes += vector_rows * settings.embedding_dimensions * 4  # one float4 per lane

    # `pg_total_relation_size` includes indexes and TOAST, which makes this
    # a generous over-estimate rather than an exact figure — the right
    # direction to be wrong in for a disk-space check (module docstring:
    # refuse early, never run out mid-write).
    estimated_size_bytes = max(int(table_sizes) - vector_bytes, 0)

    return BackupEstimate(
        chunk_count=int(chunk_count),
        estimated_reembed_seconds=chunk_count / ESTIMATED_CHUNKS_PER_SECOND,
        estimated_size_bytes=estimated_size_bytes,
        passphrase_protected=passphrase_protected,
    )


# --- enqueue, dispatch, resume --------------------------------------------


async def enqueue(
    session: AsyncSession, settings: Settings, backup_passphrase: str | None = None
) -> uuid.UUID:
    """Record the intent to back up. Always a decisions record naming the
    job and what it estimated — the ticket's own Audit Requirement — written
    in the same transaction as the job row.

    `backup_passphrase` is required exactly when the corpus is
    passphrase-protected — see the module docstring's "passphrase-wrapped
    install secret" section. It is used once, here, to compute
    `install_secret_wrapped` and is never itself stored.
    """
    await content_encryption.assert_not_migrating(session)

    preflight = await estimate(session, settings)
    if preflight.passphrase_protected and backup_passphrase is None:
        raise PassphraseRequired(
            "This corpus is passphrase-protected. Its passphrase is required to take "
            "a backup that can ever be restored."
        )
    install_secret_wrapped = None
    if preflight.passphrase_protected:
        assert backup_passphrase is not None  # narrowed by the check above
        install_secret = crypto.load_or_create_install_secret(settings.install_secret_path)
        install_secret_wrapped = _wrap_install_secret(install_secret, backup_passphrase)

    settings.backup_dir.mkdir(parents=True, exist_ok=True)
    free_bytes = shutil.disk_usage(settings.backup_dir).free
    # A generous margin: the run writes JSONL under `backup_dir` and then a
    # zip of the same data, both present briefly before the JSONL directory
    # is removed (`run_job`) — twice the estimate covers that overlap.
    needed_bytes = preflight.estimated_size_bytes * 2
    if free_bytes < needed_bytes:
        raise InsufficientSpace(needed_bytes, free_bytes)

    job_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO backup_jobs "
            "(id, tables_total, chunk_count, estimated_reembed_seconds, passphrase_protected, "
            "install_secret_wrapped) "
            "VALUES (:id, :tables_total, :chunk_count, :reembed, :passphrase_protected, "
            ":install_secret_wrapped)"
        ),
        {
            "id": job_id,
            "tables_total": len(_TABLES),
            "chunk_count": preflight.chunk_count,
            "reembed": preflight.estimated_reembed_seconds,
            "passphrase_protected": preflight.passphrase_protected,
            "install_secret_wrapped": install_secret_wrapped,
        },
    )
    await record(
        session,
        Store.DECISIONS,
        BACKUP_JOB_ENQUEUED,
        {
            "job_id": str(job_id),
            "chunk_count": preflight.chunk_count,
            # Milliseconds, not seconds: `askwell.audit.canonical_payload`
            # refuses a float, since it does not survive the jsonb round
            # trip identically — the same fixed-unit-integer rule the
            # module's own error message names.
            "estimated_reembed_ms": round(preflight.estimated_reembed_seconds * 1000),
            "estimated_size_bytes": preflight.estimated_size_bytes,
            "passphrase_protected": preflight.passphrase_protected,
        },
    )
    log.info("backup_job_enqueued", job_id=str(job_id))
    return job_id


async def dispatch(settings: Settings, job_ids: list[uuid.UUID]) -> int:
    """Ask a worker to pick these up now. Best-effort, the same reasoning as
    `askwell.log_export.dispatch` — the job row is already committed, so a
    slow or absent Redis costs a delay, never the backup itself."""
    if not job_ids:
        return 0

    from arq import create_pool
    from redis.exceptions import RedisError

    from askwell.worker import redis_settings

    queue = redis_settings(settings)
    try:
        pool = await create_pool(queue)
    except (OSError, RedisError) as error:
        log.warning("backup_dispatch_unavailable", error=str(error), jobs=len(job_ids))
        return 0

    sent = 0
    try:
        for job_id in job_ids:
            job = await pool.enqueue_job("backup_job", str(job_id), _job_id=f"backup:{job_id}")
            if job is not None:
                sent += 1
    except (OSError, RedisError) as error:  # pragma: no cover - needs a mid-flight failure
        log.warning("backup_dispatch_failed", error=str(error))
    finally:
        await pool.aclose()
    return sent


async def resume(session: AsyncSession) -> list[uuid.UUID]:
    """Return a job a dead worker was holding back to `queued`. One worker,
    one machine — anything still `running` at startup is unfinished work
    from the previous process, the same reasoning `askwell.log_export.resume`
    applies."""
    result = await session.execute(
        text(
            "UPDATE backup_jobs SET status = 'queued', started_at = NULL "
            "WHERE status = 'running' RETURNING id"
        )
    )
    return [row[0] for row in result.all()]


async def get_job(session: AsyncSession, job_id: uuid.UUID) -> BackupJob | None:
    row = (
        await session.execute(
            text(
                "SELECT id, status, tables_total, tables_done, rows_total, rows_done, "
                "chunk_count, estimated_reembed_seconds, passphrase_protected, "
                "file_bytes, error FROM backup_jobs WHERE id = :id"
            ),
            {"id": job_id},
        )
    ).first()
    if row is None:
        return None
    return BackupJob(*row)


async def _file_path(session: AsyncSession, job_id: uuid.UUID) -> str | None:
    row = (
        await session.execute(
            text("SELECT file_path FROM backup_jobs WHERE id = :id AND status = 'done'"),
            {"id": job_id},
        )
    ).first()
    return None if row is None else row[0]


# --- running one job -------------------------------------------------


def _json_default(value: Any) -> str:
    """Everything `json.dumps` cannot serialise natively here is a UUID, a
    `datetime` or a `Decimal` — all three round-trip cleanly through `str`,
    and none of them need more than that for a table this ticket does not
    itself restore."""
    return str(value)


async def _dump_table(
    session: AsyncSession,
    table: str,
    pk: str,
    exclude: tuple[str, ...],
    out_dir: Path,
    on_progress: Callable[[str, int], Awaitable[None]],
) -> int:
    tmp_path = out_dir / f"{table}.jsonl.tmp"
    final_path = out_dir / f"{table}.jsonl"

    written = 0
    cursor: Any = None
    with tmp_path.open("w", encoding="utf-8") as handle:
        while True:
            if cursor is None:
                rows = (
                    (
                        await session.execute(
                            text(f"SELECT * FROM {table} ORDER BY {pk} ASC LIMIT :batch"),
                            {"batch": _BATCH_SIZE},
                        )
                    )
                    .mappings()
                    .all()
                )
            else:
                rows = (
                    (
                        await session.execute(
                            text(
                                f"SELECT * FROM {table} WHERE {pk} > :cursor "
                                f"ORDER BY {pk} ASC LIMIT :batch"
                            ),
                            {"cursor": cursor, "batch": _BATCH_SIZE},
                        )
                    )
                    .mappings()
                    .all()
                )
            if not rows:
                break
            for row in rows:
                handle.write(
                    json.dumps(
                        {key: value for key, value in row.items() if key not in exclude},
                        ensure_ascii=False,
                        default=_json_default,
                    )
                    + "\n"
                )
                written += 1
                cursor = row[pk]
            await on_progress(table, written)
    tmp_path.rename(final_path)
    return written


async def run_job(
    sessions: async_sessionmaker[AsyncSession], settings: Settings, job_id: uuid.UUID
) -> None:
    """Produce one backup end to end: one `REPEATABLE READ` snapshot across
    every table, streamed to disk, manifested, zipped, and recorded. See the
    module docstring for the consistency argument and the exclusion list.
    """
    job_dir = settings.backup_dir / str(job_id)

    async with session_scope(sessions) as session:
        await session.execute(
            text(
                "UPDATE backup_jobs SET status = 'running', "
                "started_at = COALESCE(started_at, now()) WHERE id = :id"
            ),
            {"id": job_id},
        )

    try:
        if job_dir.exists():
            shutil.rmtree(job_dir)
        job_dir.mkdir(parents=True)

        rows_done_by_table: dict[str, int] = {}

        async def _progress(table: str, count: int) -> None:
            delta = count - rows_done_by_table.get(table, 0)
            rows_done_by_table[table] = count
            async with session_scope(sessions) as progress_session:
                await progress_session.execute(
                    text("UPDATE backup_jobs SET rows_done = rows_done + :delta WHERE id = :id"),
                    {"delta": delta, "id": job_id},
                )

        tables_manifest: dict[str, Any] = {}
        async with sessions() as session:
            # A read-only snapshot, fixed at this transaction's first
            # statement (module docstring). `assert_not_migrating` is that
            # first statement deliberately — a passphrase migration starting
            # after this point is invisible to the snapshot and therefore
            # cannot produce a half-migrated dump.
            await session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            await content_encryption.assert_not_migrating(session)

            rows_total = 0
            for table in _TABLES:
                count = (await session.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()
                rows_total += count
            async with session_scope(sessions) as progress_session:
                await progress_session.execute(
                    text("UPDATE backup_jobs SET rows_total = :total WHERE id = :id"),
                    {"total": rows_total, "id": job_id},
                )

            chunk_count = (
                await session.execute(text("SELECT count(*) FROM chunks WHERE content IS NOT NULL"))
            ).scalar_one()
            passphrase_protected = await passphrase.is_enabled(session)
            # Computed once, at `enqueue` time, from the passphrase the caller
            # gave then — never re-derived here, since this transaction has
            # no passphrase to derive it from.
            install_secret_wrapped = (
                await session.execute(
                    text("SELECT install_secret_wrapped FROM backup_jobs WHERE id = :id"),
                    {"id": job_id},
                )
            ).scalar_one()

            tables_done = 0
            for table, (pk, exclude) in _TABLES.items():
                count = await _dump_table(session, table, pk, exclude, job_dir, _progress)
                tables_manifest[table] = {"record_count": count, "excluded_columns": list(exclude)}
                tables_done += 1
                async with session_scope(sessions) as progress_session:
                    await progress_session.execute(
                        text("UPDATE backup_jobs SET tables_done = :done WHERE id = :id"),
                        {"done": tables_done, "id": job_id},
                    )
            await session.rollback()  # read-only; nothing to commit

        manifest = {
            "askwell_version": __version__,
            "generated_at": datetime.now(UTC).isoformat(),
            "tables": tables_manifest,
            "excluded": {
                "model_weights": "Never stored in the database; re-downloaded on the new machine.",
                "trace_ring_buffer": "Files, not database rows; not carried by this artefact.",
                "vector_index": (
                    "chunks.embedding and schema_notes.embedding — regenerated by "
                    "re-embedding chunks.content on restore."
                ),
            },
            "chunk_count": int(chunk_count),
            "estimated_reembed_seconds": chunk_count / ESTIMATED_CHUNKS_PER_SECOND,
            "passphrase_protected": passphrase_protected,
            "install_secret_wrapped": install_secret_wrapped,
            "user_files_included": False,
            "user_files_statement": _USER_FILES_STATEMENT,
        }
        manifest_tmp = job_dir / "manifest.json.tmp"
        manifest_tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        manifest_tmp.rename(job_dir / "manifest.json")

        zip_final = settings.backup_dir / f"askwell-backup-{job_id}.zip"
        zip_tmp = settings.backup_dir / f"askwell-backup-{job_id}.zip.tmp"
        with zipfile.ZipFile(zip_tmp, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(job_dir.iterdir()):
                archive.write(path, arcname=path.name)
        zip_tmp.rename(zip_final)
        shutil.rmtree(job_dir)

        async with session_scope(sessions) as session:
            await session.execute(
                text(
                    "UPDATE backup_jobs SET status = 'done', finished_at = now(), "
                    "file_path = :path, file_bytes = :size, chunk_count = :chunk_count, "
                    "estimated_reembed_seconds = :reembed, "
                    "passphrase_protected = :passphrase_protected WHERE id = :id"
                ),
                {
                    "id": job_id,
                    "path": str(zip_final),
                    "size": zip_final.stat().st_size,
                    "chunk_count": int(chunk_count),
                    "reembed": chunk_count / ESTIMATED_CHUNKS_PER_SECOND,
                    "passphrase_protected": passphrase_protected,
                },
            )
        log.info("backup_done", job_id=str(job_id), tables=len(tables_manifest))
    except Exception as error:
        log.warning("backup_failed", job_id=str(job_id), error=f"{type(error).__name__}: {error}")
        async with session_scope(sessions) as session:
            await session.execute(
                text(
                    "UPDATE backup_jobs SET status = 'failed', finished_at = now(), "
                    "error = :error WHERE id = :id"
                ),
                {"id": job_id, "error": f"{type(error).__name__}: {error}"},
            )
        raise


class CreateBackupRequest(BaseModel):
    passphrase: str | None = None


# --- HTTP --------------------------------------------------------------


def register_backup(
    app: FastAPI, settings: Settings, factory: async_sessionmaker[AsyncSession]
) -> None:
    """`GET /backup/estimate` states the re-embed cost and size before the
    user commits; `POST /backup` enqueues and dispatches a job;
    `GET /backup/{id}` reads its progress; `GET /backup/{id}/download`
    streams the finished file.
    """

    @app.get("/backup/estimate")
    async def estimate_route() -> JSONResponse:
        async with factory() as db:
            preflight = await estimate(db, settings)
        return JSONResponse(preflight.as_dict())

    @app.post("/backup")
    async def create_backup(body: CreateBackupRequest | None = None) -> JSONResponse:
        body = body or CreateBackupRequest()
        try:
            async with session_scope(factory) as db:
                job_id = await enqueue(db, settings, body.passphrase)
        except content_encryption.MigrationInProgress as error:
            return JSONResponse({"error": str(error)}, status_code=409)
        except PassphraseRequired as error:
            return JSONResponse({"error": str(error)}, status_code=422)
        except InsufficientSpace as error:
            return JSONResponse(
                {
                    "error": "Not enough disk space for the backup.",
                    "needed_bytes": error.needed_bytes,
                    "free_bytes": error.free_bytes,
                },
                status_code=409,
            )

        await dispatch(settings, [job_id])
        async with session_scope(factory) as db:
            job = await get_job(db, job_id)
        assert job is not None  # just inserted, in the same request
        return JSONResponse(job.as_dict(), status_code=201)

    @app.get("/backup/{job_id}")
    async def read_backup(job_id: uuid.UUID) -> JSONResponse:
        async with session_scope(factory) as db:
            job = await get_job(db, job_id)
        if job is None:
            return JSONResponse({"error": "No such backup."}, status_code=404)
        return JSONResponse(job.as_dict())

    @app.get("/backup/{job_id}/download", response_model=None)
    async def download_backup(job_id: uuid.UUID) -> FileResponse | JSONResponse:
        async with session_scope(factory) as db:
            path = await _file_path(db, job_id)
        if path is None:
            return JSONResponse(
                {"error": "Backup is not finished, or does not exist."}, status_code=404
            )
        file_path = Path(path)
        if not await asyncio.to_thread(file_path.exists):
            return JSONResponse(
                {"error": "The backup file no longer exists on disk."}, status_code=410
            )
        return FileResponse(file_path, filename=file_path.name, media_type="application/zip")
