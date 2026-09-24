"""Log export: a background job that turns the two audit stores into an open,
independently verifiable file. `docs/audit-log.md` §5, ticket `M7-LOG-BE-155`.

**Why this exists at all.** A consultant who has to show a client what was
asked of their confidential corpus needs more than a screenshot of the log —
they need something the client's own technical person can check without
taking Askwell's word for it. `askwell.audit.verify` already proves the
chain to Askwell itself; this module is what makes that proof portable, by
writing the same records out plainly and shipping a standalone copy of the
check alongside them (`askwell.log_export_verifier`).

Same shape as `askwell.reapply` and `askwell.ingest`: a durable row
(`export_jobs`) is the record of what happened, `arq` is only the transport
that wakes a worker to act on it, and anything still `running` when the
process starts is, on one worker on one machine, unfinished work from last
time rather than something to trust.

**A run always starts by deleting whatever partial output exists and
rewriting from scratch**, rather than resuming mid-file. Two stores at
export retention (§8: twelve months by default) are kilobytes to low tens of
megabytes — cheap enough to redo whole that the correctness a restart-from-
scratch design gets for free is worth more than the write-avoidance a
resumable byte offset would add. What a crash must never do is leave a
half-written `decisions.jsonl` sitting under the name a finished one would
have: every file this module writes lands at `<name>.tmp` and is renamed
into place only once it is complete, so "the file exists under its real
name" and "the file is complete" are the same fact.

**The export snapshots itself at the moment it starts**, not at the moment
it finishes. An unbounded `until` is resolved to the job's own start time
before either store is queried, so a question answered while a multi-hour
export is running lands after the file rather than corrupting a progress
count that was fixed before that answer existed.

**`scope = 'everything'` is the settings screen's "Export everything"**
(`docs/ux/settings.md` §6, `M7-DATA-FE-160`): the same job, the same chain
and the same verifier, plus the rest of what Askwell holds under `data/` —
one JSON Lines file per table, read inside one `REPEATABLE READ` snapshot,
and a `README.txt` that documents every file so none of it needs Askwell to
read. What is left out, and why, is `_EVERYTHING_EXCLUDED` below and is
stated in that README rather than silently dropped. Everything is plaintext:
a passphrase-protected library is warned before it is written, through the
same acknowledgement the log export already requires.
"""

import asyncio
import json
import shutil
import uuid
import zipfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from askwell import __version__, passphrase
from askwell.audit import Store, record
from askwell.backup import _dump_table
from askwell.config import Settings
from askwell.db.engine import session_scope
from askwell.log_export_verifier import SOURCE as VERIFIER_SOURCE
from askwell.logging import get_logger
from askwell.traces import TraceRing

log = get_logger(__name__)

EXPORT_JOB_ENQUEUED = "log_export_enqueued"
EXPORT_EVERYTHING_ENQUEUED = "export_everything_enqueued"

SCOPE_LOG = "log"
SCOPE_EVERYTHING = "everything"
SCOPES = (SCOPE_LOG, SCOPE_EVERYTHING)

# table -> (primary key, columns left out). The tables a person means by
# "sources, memory, conversations": what they added, what Askwell learned or
# was told, and what was said. `sources.config_encrypted` is a connection's
# credentials — an export is plaintext, and a password in it would be the one
# thing in the file the user never asked to carry around. The embedding is a
# vector, not something a person reads.
_EVERYTHING_TABLES: dict[str, tuple[str, tuple[str, ...]]] = {
    "roots": ("id", ()),
    "sources": ("id", ("config_encrypted",)),
    "documents": ("id", ()),
    "memory": ("id", ()),
    "schema_notes": ("id", ("embedding",)),
    "clarifications": ("id", ()),
    "fact_usage": ("id", ()),
    "conversations": ("id", ()),
    "messages": ("id", ()),
    "citations": ("id", ()),
    "web_citations": ("id", ()),
}

# What "everything" does not carry, each with the reason — written into the
# manifest and the README so the omission is stated, not discovered.
_EVERYTHING_EXCLUDED: dict[str, str] = {
    "your_files": (
        "Your own files are not copied. Askwell never moves or changes them; "
        "documents.jsonl records where each one is."
    ),
    "chunks": (
        "The indexed passages and the per-page text extracted from your own files, which "
        "you already have; with a passphrase set passages are ciphertext, which is not "
        "readable anyway."
    ),
    "connection_credentials": (
        "sources.config_encrypted, a connected database's password, is left out so an "
        "export never carries a credential."
    ),
    "settings": (
        "Askwell's own configuration, including the passphrase check value and your "
        "online provider key."
    ),
    "vector_index": "Embeddings are numbers derived from text; they are not readable.",
    "job_bookkeeping": "Ingest, re-processing, export, backup, restore and prune job rows.",
}

_README = """Askwell export
==============

Everything in this folder is plain text. No Askwell is needed to read it.

decisions.jsonl, interactions.jsonl
    The two audit logs, one JSON object per line, oldest first. Each record
    carries "prev_hash" and "hash": the hash of a record covers the record
    before it, so an edited, removed or reordered line breaks the chain.

verify.py
    Checks that chain. Needs only Python 3, nothing else:
        python3 verify.py .

manifest.json
    When this export was written, by which version, and how many records
    each file holds.

data/<table>.jsonl
    The rest of what Askwell holds, one JSON object per line, one file per
    table. Keys are column names. Ids are UUIDs; "*_id" keys point at the
    "id" of a row in another file. Times carry their UTC offset, for
    example 2026-09-24 02:24:26+00:00.

    roots.jsonl           folders you allowed Askwell to read
    sources.jsonl         each source you added: folder, file, CSV, dump or
                          database connection
    documents.jsonl       each file indexed, with its path on your disk
    memory.jsonl          facts Askwell was told or inferred; "superseded_by"
                          links a corrected fact to its replacement
    schema_notes.jsonl    what columns in your databases mean
    clarifications.jsonl  questions Askwell asked you, and your answers
    fact_usage.jsonl      which answers used which memory facts
    conversations.jsonl   one row per conversation
    messages.jsonl        every question and answer; "conversation_id"
                          groups them, "trace" records how an answer was made
    citations.jsonl       which document and page each claim came from
    web_citations.jsonl   web results, only for searches you asked for

traces/<message id>.trace.json
    The third log: the full working behind recent answers — prompts, tool
    calls, timings. A capped buffer, so only the most recent are held; it
    is not hash-chained. The file name is the "id" in messages.jsonl.

Not included:
{excluded}
"""


def _readme() -> str:
    lines = "\n".join(f"    {key}: {reason}" for key, reason in _EVERYTHING_EXCLUDED.items())
    return _README.format(excluded=lines)


# Kept well under Postgres's own row/packet limits and small enough that one
# batch's `json.dumps` output is never more than a few megabytes even for the
# widest interaction payload — streamed to disk, never assembled whole.
_BATCH_SIZE = 2000

_STORE_FILES = {Store.DECISIONS: "decisions.jsonl", Store.INTERACTIONS: "interactions.jsonl"}


class ExportNotAcknowledged(Exception):
    """A passphrase is set and the caller did not acknowledge the export
    leaves the library's protection."""


class InvalidRange(ValueError):
    """`since` is after `until`."""


@dataclass(frozen=True, slots=True)
class ExportJob:
    id: uuid.UUID
    status: str
    scope: str
    since: datetime | None
    until: datetime | None
    decisions_total: int
    decisions_done: int
    interactions_total: int
    interactions_done: int
    file_bytes: int | None
    error: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "status": self.status,
            "scope": self.scope,
            "since": self.since.isoformat() if self.since else None,
            "until": self.until.isoformat() if self.until else None,
            "decisions_total": self.decisions_total,
            "decisions_done": self.decisions_done,
            "interactions_total": self.interactions_total,
            "interactions_done": self.interactions_done,
            "file_bytes": self.file_bytes,
            "error": self.error,
        }


# --- enqueue, dispatch, resume ----------------------------------------------


async def enqueue(
    session: AsyncSession,
    *,
    since: datetime | None,
    until: datetime | None,
    acknowledged_decrypted_export: bool,
    scope: str = SCOPE_LOG,
) -> uuid.UUID:
    """Record the intent to export. Always a decisions record naming the
    range — the ticket's own Audit Requirement — written in the same
    transaction as the job row, so a job nobody can prove was ever asked for
    does not exist either. Exporting everything is its own record kind, so
    "did I ever export all of it" is one query.
    """
    if scope not in SCOPES:
        raise ValueError(f"unknown export scope {scope!r}")
    if since is not None and until is not None and since > until:
        raise InvalidRange("`since` must not be after `until`.")
    if await passphrase.is_enabled(session) and not acknowledged_decrypted_export:
        raise ExportNotAcknowledged(
            "A passphrase is set. The export is written in the open, unencrypted — outside "
            "the protection a passphrase gives the library — and must be acknowledged before "
            "it is written."
        )

    job_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO export_jobs (id, scope, since, until) VALUES (:id, :scope, :since, :until)"
        ),
        {"id": job_id, "scope": scope, "since": since, "until": until},
    )
    await record(
        session,
        Store.DECISIONS,
        EXPORT_EVERYTHING_ENQUEUED if scope == SCOPE_EVERYTHING else EXPORT_JOB_ENQUEUED,
        {
            "job_id": str(job_id),
            "since": since.isoformat() if since else None,
            "until": until.isoformat() if until else None,
        },
    )
    log.info("log_export_enqueued", job_id=str(job_id))
    return job_id


async def dispatch(settings: Settings, job_ids: list[uuid.UUID]) -> int:
    """Ask a worker to pick these up now. Best-effort, the same reasoning as
    `askwell.reapply.dispatch` — the job row is already committed, so a slow
    or absent Redis costs a delay, never the export itself."""
    if not job_ids:
        return 0

    from arq import create_pool
    from redis.exceptions import RedisError

    from askwell.worker import redis_settings

    queue = redis_settings(settings)
    try:
        pool = await create_pool(queue)
    except (OSError, RedisError) as error:
        log.warning("log_export_dispatch_unavailable", error=str(error), jobs=len(job_ids))
        return 0

    sent = 0
    try:
        for job_id in job_ids:
            job = await pool.enqueue_job("export_job", str(job_id), _job_id=f"export:{job_id}")
            if job is not None:
                sent += 1
    except (OSError, RedisError) as error:  # pragma: no cover - needs a mid-flight failure
        log.warning("log_export_dispatch_failed", error=str(error))
    finally:
        await pool.aclose()
    return sent


async def resume(session: AsyncSession) -> list[uuid.UUID]:
    """Return a job a dead worker was holding back to `queued`. One worker,
    one machine — anything still `running` at startup is unfinished work
    from the previous process, the same reasoning `askwell.reapply.resume`
    applies."""
    result = await session.execute(
        text(
            "UPDATE export_jobs SET status = 'queued', started_at = NULL "
            "WHERE status = 'running' RETURNING id"
        )
    )
    return [row[0] for row in result.all()]


async def get_job(session: AsyncSession, job_id: uuid.UUID) -> ExportJob | None:
    row = (
        await session.execute(
            text(
                "SELECT id, status, scope, since, until, decisions_total, decisions_done, "
                "interactions_total, interactions_done, file_bytes, error "
                "FROM export_jobs WHERE id = :id"
            ),
            {"id": job_id},
        )
    ).first()
    if row is None:
        return None
    return ExportJob(*row)


async def _file_path(session: AsyncSession, job_id: uuid.UUID) -> str | None:
    row = (
        await session.execute(
            text("SELECT file_path FROM export_jobs WHERE id = :id AND status = 'done'"),
            {"id": job_id},
        )
    ).first()
    return None if row is None else row[0]


# --- running one job ---------------------------------------------------


def _where(store: Store, since: datetime | None, until: datetime) -> tuple[str, dict[str, Any]]:
    clauses = ["occurred_at <= :until"]
    params: dict[str, Any] = {"until": until}
    if since is not None:
        clauses.append("occurred_at >= :since")
        params["since"] = since
    return " AND ".join(clauses), params


async def _count(
    session: AsyncSession, store: Store, since: datetime | None, until: datetime
) -> int:
    where_sql, params = _where(store, since, until)
    result = await session.execute(
        text(f"SELECT count(*) FROM {store.value} WHERE {where_sql}"), params
    )
    return int(result.scalar_one())


async def _write_store_file(
    session: AsyncSession,
    store: Store,
    since: datetime | None,
    until: datetime,
    out_dir: Path,
    on_progress: Callable[[Store, int], Awaitable[None]],
) -> tuple[int, str | None]:
    """Stream every matching record to `<store>.jsonl.tmp` in ascending order,
    in batches, then rename into place. Returns the count written and the
    `prev_hash` the very first record chains to — the export's own starting
    point, which `askwell.log_export_verifier` walks from instead of
    expecting the universal genesis value when `since` narrows the window.
    """
    where_sql, base_params = _where(store, since, until)
    tmp_path = out_dir / f"{_STORE_FILES[store]}.tmp"
    final_path = out_dir / _STORE_FILES[store]

    written = 0
    first_prev_hash: str | None = None
    cursor_at: datetime | None = None
    cursor_id: uuid.UUID | None = None

    with tmp_path.open("w", encoding="utf-8") as handle:
        while True:
            params = dict(base_params)
            keyset = ""
            if cursor_at is not None:
                keyset = " AND (occurred_at, id) > (:cursor_at, :cursor_id)"
                params["cursor_at"] = cursor_at
                params["cursor_id"] = cursor_id
            rows = (
                await session.execute(
                    text(
                        f"SELECT id, kind, payload, prev_hash, hash, occurred_at "
                        f"FROM {store.value} WHERE {where_sql}{keyset} "
                        f"ORDER BY occurred_at ASC, id ASC LIMIT :batch"
                    ),
                    {**params, "batch": _BATCH_SIZE},
                )
            ).all()
            if not rows:
                break
            for row_id, kind, payload, prev_hash, digest, occurred_at in rows:
                if first_prev_hash is None:
                    first_prev_hash = prev_hash
                handle.write(
                    json.dumps(
                        {
                            "id": str(row_id),
                            "kind": kind,
                            "payload": payload,
                            "prev_hash": prev_hash,
                            "hash": digest,
                            "occurred_at": occurred_at.astimezone(UTC).isoformat(),
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                written += 1
                cursor_at, cursor_id = occurred_at, row_id
            await on_progress(store, written)
    tmp_path.rename(final_path)
    return written, first_prev_hash


async def run_job(
    sessions: async_sessionmaker[AsyncSession], settings: Settings, job_id: uuid.UUID
) -> None:
    """Produce one export end to end: count, stream both stores to disk,
    write the manifest and verifier, zip, and record the result. A run
    always starts by clearing any previous attempt's output directory —
    see the module docstring for why redoing the write is cheaper here than
    resuming it.
    """
    job_dir = settings.export_dir / str(job_id)
    started_at = datetime.now(UTC)

    async with session_scope(sessions) as session:
        row = (
            await session.execute(
                text("SELECT scope, since, until FROM export_jobs WHERE id = :id"),
                {"id": job_id},
            )
        ).first()
        if row is None:
            return
        scope, since, requested_until = row
        # The snapshot boundary: an unbounded `until` is pinned to this run's
        # own start, so a record written mid-export never changes a total
        # this run already counted (module docstring).
        until = requested_until if requested_until is not None else started_at

        decisions_total = await _count(session, Store.DECISIONS, since, until)
        interactions_total = await _count(session, Store.INTERACTIONS, since, until)
        await session.execute(
            text(
                "UPDATE export_jobs SET status = 'running', "
                "started_at = COALESCE(started_at, now()), "
                "decisions_total = :dt, decisions_done = 0, "
                "interactions_total = :it, interactions_done = 0, "
                "error = NULL WHERE id = :id"
            ),
            {"id": job_id, "dt": decisions_total, "it": interactions_total},
        )

    try:
        if job_dir.exists():
            shutil.rmtree(job_dir)
        job_dir.mkdir(parents=True)

        async def _progress(store: Store, count: int) -> None:
            column = "decisions_done" if store is Store.DECISIONS else "interactions_done"
            async with session_scope(sessions) as progress_session:
                await progress_session.execute(
                    text(f"UPDATE export_jobs SET {column} = :count WHERE id = :id"),
                    {"count": count, "id": job_id},
                )

        stores_manifest: dict[str, Any] = {}
        async with session_scope(sessions) as session:
            for store in (Store.DECISIONS, Store.INTERACTIONS):
                count, first_prev_hash = await _write_store_file(
                    session, store, since, until, job_dir, _progress
                )
                stores_manifest[store.value.removeprefix("audit_")] = {
                    "record_count": count,
                    "first_prev_hash": first_prev_hash,
                }

        manifest: dict[str, Any] = {
            "askwell_version": __version__,
            "generated_at": datetime.now(UTC).isoformat(),
            "scope": scope,
            "since": since.astimezone(UTC).isoformat() if since else None,
            "until": requested_until.astimezone(UTC).isoformat() if requested_until else None,
            "stores": stores_manifest,
        }
        if scope == SCOPE_EVERYTHING:
            manifest["data"] = await _write_data_files(sessions, job_dir / "data")
            manifest["traces"] = await asyncio.to_thread(
                _copy_traces, settings.trace_dir, job_dir / "traces"
            )
            manifest["excluded"] = _EVERYTHING_EXCLUDED
            readme_tmp = job_dir / "README.txt.tmp"
            readme_tmp.write_text(_readme(), encoding="utf-8")
            readme_tmp.rename(job_dir / "README.txt")
        manifest_tmp = job_dir / "manifest.json.tmp"
        manifest_tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        manifest_tmp.rename(job_dir / "manifest.json")

        verifier_tmp = job_dir / "verify.py.tmp"
        verifier_tmp.write_text(VERIFIER_SOURCE, encoding="utf-8")
        verifier_tmp.rename(job_dir / "verify.py")

        stem = "askwell-export" if scope == SCOPE_EVERYTHING else "askwell-log-export"
        zip_final = settings.export_dir / f"{stem}-{job_id}.zip"
        zip_tmp = settings.export_dir / f"{stem}-{job_id}.zip.tmp"
        with zipfile.ZipFile(zip_tmp, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(job_dir.rglob("*")):
                if path.is_file():
                    archive.write(path, arcname=path.relative_to(job_dir).as_posix())
        zip_tmp.rename(zip_final)
        shutil.rmtree(job_dir)

        async with session_scope(sessions) as session:
            await session.execute(
                text(
                    "UPDATE export_jobs SET status = 'done', finished_at = now(), "
                    "file_path = :path, file_bytes = :size WHERE id = :id"
                ),
                {"id": job_id, "path": str(zip_final), "size": zip_final.stat().st_size},
            )
        log.info(
            "log_export_done",
            job_id=str(job_id),
            decisions=stores_manifest["decisions"]["record_count"],
            interactions=stores_manifest["interactions"]["record_count"],
        )
    except Exception as error:
        log.warning(
            "log_export_failed", job_id=str(job_id), error=f"{type(error).__name__}: {error}"
        )
        async with session_scope(sessions) as session:
            await session.execute(
                text(
                    "UPDATE export_jobs SET status = 'failed', finished_at = now(), "
                    "error = :error WHERE id = :id"
                ),
                {"id": job_id, "error": f"{type(error).__name__}: {error}"},
            )
        raise


def _copy_traces(trace_dir: Path, out_dir: Path) -> dict[str, Any]:
    """The trace ring buffer as it stands now. A trace pruned mid-copy is
    skipped, not an error: the buffer drops its oldest by design, and
    losing one there is what `docs/audit-log.md` §2 already accepts."""
    out_dir.mkdir(parents=True, exist_ok=True)
    copied = 0
    for path in sorted(TraceRing(trace_dir, 0).files()):
        try:
            shutil.copy2(path, out_dir / path.name)
        except FileNotFoundError:
            continue
        copied += 1
    return {"directory": "traces/", "file_count": copied}


async def _write_data_files(
    sessions: async_sessionmaker[AsyncSession], out_dir: Path
) -> dict[str, Any]:
    """Every `_EVERYTHING_TABLES` table as `<table>.jsonl`, all read inside
    one `REPEATABLE READ` snapshot so a conversation and its messages cannot
    disagree — the same consistency argument `askwell.backup.run_job` makes,
    and the same row writer, reused rather than copied."""
    await asyncio.to_thread(out_dir.mkdir, parents=True, exist_ok=True)

    async def _no_progress(_table: str, _count: int) -> None:
        return None

    tables: dict[str, Any] = {}
    async with sessions() as session:
        await session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        for table, (pk, exclude) in _EVERYTHING_TABLES.items():
            count = await _dump_table(session, table, pk, exclude, out_dir, _no_progress)
            tables[table] = {
                "file": f"data/{table}.jsonl",
                "record_count": count,
                "excluded_columns": list(exclude),
            }
        await session.rollback()  # read-only; nothing to commit
    return tables


# --- HTTP --------------------------------------------------------------


class CreateExportRequest(BaseModel):
    scope: Literal["log", "everything"] = "log"
    since: datetime | None = None
    until: datetime | None = None
    acknowledged_decrypted_export: bool = False


def register_log_export(
    app: FastAPI, settings: Settings, factory: async_sessionmaker[AsyncSession]
) -> None:
    """`POST /log-export` enqueues and dispatches a job; `GET /log-export/{id}`
    reads its progress; `GET /log-export/{id}/download` streams the finished
    file. No delete or list route — the ticket's own scope is the job, the
    format and the verifier, and a history view belongs to whichever settings
    ticket first needs one.
    """

    @app.post("/log-export")
    async def create_export(body: CreateExportRequest) -> JSONResponse:
        try:
            async with session_scope(factory) as db:
                job_id = await enqueue(
                    db,
                    since=body.since,
                    until=body.until,
                    acknowledged_decrypted_export=body.acknowledged_decrypted_export,
                    scope=body.scope,
                )
        except InvalidRange as error:
            return JSONResponse({"error": str(error)}, status_code=400)
        except ExportNotAcknowledged as error:
            # 400, not 403: nothing about the request is forbidden, a required
            # field was left unset — the same shape `set_passphrase`'s own
            # `NoRecoveryNotAcknowledged` uses for the same reason.
            return JSONResponse({"error": str(error), "passphrase_enabled": True}, status_code=400)

        await dispatch(settings, [job_id])
        async with session_scope(factory) as db:
            job = await get_job(db, job_id)
        assert job is not None  # just inserted, in the same request
        return JSONResponse(job.as_dict(), status_code=201)

    @app.get("/log-export/{job_id}")
    async def read_export(job_id: uuid.UUID) -> JSONResponse:
        async with session_scope(factory) as db:
            job = await get_job(db, job_id)
        if job is None:
            return JSONResponse({"error": "No such export."}, status_code=404)
        return JSONResponse(job.as_dict())

    @app.get("/log-export/{job_id}/download", response_model=None)
    async def download_export(job_id: uuid.UUID) -> FileResponse | JSONResponse:
        async with session_scope(factory) as db:
            path = await _file_path(db, job_id)
        if path is None:
            return JSONResponse(
                {"error": "Export is not finished, or does not exist."}, status_code=404
            )
        file_path = Path(path)
        if not await asyncio.to_thread(file_path.exists):
            # The job row says `done` but the file it points at is gone — a
            # user deleting it by hand, most plausibly. Distinct from 404 so
            # the settings screen can tell "never existed" from "existed,
            # and is no longer there" apart.
            return JSONResponse(
                {"error": "The export file no longer exists on disk."}, status_code=410
            )
        return FileResponse(file_path, filename=file_path.name, media_type="application/zip")
