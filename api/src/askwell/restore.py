"""Restore: read a backup artefact back onto a machine. `M7-BACKUP-BE-158`.

`docs/build-plan.md`, `docs/ux/settings.md` §6 and §9, ticket `M7-BACKUP-BE-158`.

**Why this exists at all.** `askwell.backup` (`M7-BACKUP-BE-157`) produces a
portable artefact; this module is the other half of the acceptance
criterion the phase was actually sized around — "a backup taken on one
machine restores onto another with corpus and memory intact." A backup
nobody can read back is not a backup.

**Same table list as the job that made the artefact.** `TABLES` is imported
from `askwell.backup`, not duplicated — the two modules have to agree on
what "every table" means, in the same order (FK-safe: parents before the
children that reference them), or a second copy is how that drifts.

**Schema currency is checked, not fixed, before anything is restored.**
`askwell_app` — what the API and worker processes connect as
(`compose.yaml`) — owns nothing and holds no DDL grant; only the `askwell`
owner role can run a migration (`docs/decisions.md`, "the database has three
roles"), and this process never holds those credentials, the same boundary
that keeps C6's audit grants meaningful. So restore cannot call `alembic
upgrade head` itself — `_check_schema_current` instead compares the target's
`alembic_version` row to the migration chain's own head and refuses plainly,
naming the exact command (`scripts/dev.sh db upgrade head`,
`AGENTS.md` §5's own documented operator step) if they differ, rather than
discovering a schema mismatch three tables into a restore as an opaque
Postgres error. This is the resolution to issue #570: the ticket's
Acceptance Criteria text ("applies migrations if the version differs") reads
as restore performing the migration; the actual, credential-honest shape is
restore *requiring* it be current and saying so if it is not.

**A backup newer than this install is refused by name, not partially
applied.** `_check_version` compares the manifest's `askwell_version`
against `__version__` before a single row is touched — an artefact from a
future release may carry columns or a manifest shape this build has never
seen, and discovering that three tables into a restore is a worse failure
than refusing up front.

**A passphrase-protected backup needs the passphrase for two different
reasons, both up front.** First, to unwrap `install_secret_wrapped`
(`askwell.backup`'s own docstring) and write the *source* machine's install
secret back to `Settings.install_secret_path` — without it, the restored
`chunks.content`/`sources.config_encrypted` ciphertext is undecryptable
forever, because the key it was encrypted under depended on an install
secret this machine never had. Second, to unlock this process
(`askwell.passphrase.unlock`) so re-embedding — which must read
plaintext to embed it — can decrypt content as it goes. Both happen before
any table is restored; a wrong passphrase is refused before writing
anything, the same posture `askwell.passphrase` already established for
every other passphrase-gated operation in this codebase.

**The passphrase itself is never persisted.** It travels from the `/restore`
request to the `restore_job` arq call and no further — never written to
`restore_jobs`, never logged. This means a worker restart mid-restore loses
it: `resume` returns a passphrase-protected job to `queued` but does not
redispatch it (`askwell.worker.startup`'s job, not this module's) — the
user re-enters the passphrase through `/restore/{id}/resume`, which is the
same "no recovery without re-entering the secret" honesty
`askwell.passphrase`'s own module docstring already commits to, applied
here rather than invented fresh.

**Never merged, for corpus and memory — the audit stores are a deliberate
exception.** `enqueue` refuses outright when any of `TABLES` other than
`audit_decisions`/`audit_interactions` already holds a row, unless the
caller passes `replace_existing` — the ticket's own Validation Rule.
`replace_existing` then `DELETE`s every row from every other table, once,
gated by the job's own `truncated` flag so a retried job never re-clears
data an earlier attempt of itself already restored. `DELETE`, not
`TRUNCATE`: `askwell_app` (`compose.yaml`) has no `TRUNCATE` grant on
anything at all (`docs/decisions.md`, "the database has three roles").

The two audit tables are excluded from both the refusal check and the
clear, and always restored by appending: `askwell_app` has no `UPDATE`,
`DELETE` or `TRUNCATE` grant on either, by the same C6 design that makes
the log's own tamper-evidence real, so there is no credential this process
holds that could ever empty them. `enqueue` deliberately writes no
decisions record of its own — see "never merged" above and `run_job`'s own
comment at the call site — precisely so a genuinely fresh install's audit
tables really are empty until the historical rows land in them. A machine
with any *other* prior local audit activity is a different case restore
does not get to paper over: its rows sit in the table before the historical
ones restore regardless of what this module does. Restoring a backup's
historical audit rows on top of whatever local rows already exist is
therefore not a design choice restore gets to make; `log_verify`
running at the end reports honestly on whatever the result is — a clean
machine's fresh audit rows chain cleanly after nothing, and a machine with
genuine prior local activity may legitimately show a broken chain, which is
correct: two independently-chained histories were just concatenated, and
C6 exists precisely to make that detectable rather than silent. Nothing
here explains that to a user yet — issue #574, filed for whichever ticket
builds the restore settings surface.

**Resumable per table, not per row.** Each table restores inside its own
transaction; `tables_done` only increments once that transaction commits, so
a crash mid-table leaves nothing committed for it — `run_job` restarts a
resumed job by skipping every table index below `tables_done` and re-running
the rest, which is always either "never started" or "fully committed" for
any table, never "half inserted". This is the fix for a real gap
(`replace_existing=False` retrying a whole-table re-insert used to raise a
unique-violation on the first already-restored row, permanently) — see
`docs/decisions.md`, this ticket's date.

**Re-embedding resumes for free.** `_reembed_corpus` selects
`WHERE embedding IS NULL`, the same cursor-free resume
`askwell.content_encryption.migrate_chunk_content` and `askwell.embed.run`
already rely on — a chunk that got a vector before a crash is simply not
selected again.

**Two self-referential columns need a second pass.** `documents.superseded_by`
and `schema_notes.superseded_by` reference a row in the *same* table, and
Postgres foreign keys here are not `DEFERRABLE` — a row whose `superseded_by`
points at a not-yet-inserted later row would fail its own `INSERT`.
`_SELF_REFERENTIAL_COLUMNS` restores those tables with the column left `NULL`
on the first pass and reapplies the real values in a second pass once every
row in the table exists.

**Column casts come from `information_schema`, not from `askwell.db.models`.**
An ORM-metadata-driven restore was tried first and broke on `sources.deleted_at`
(issue #569, fixed separately by declaring the two missing columns on
`Source`) — but the deeper fix is that restore should not need the ORM to
agree with the schema at all. Querying `information_schema.columns` for each
table's real `udt_name` and casting every bind parameter against it is
authoritative by construction: it reads the schema restore is about to write
into, not a Python class that can drift from it.
"""

from __future__ import annotations

import asyncio
import base64
import json
import shutil
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from askwell import __version__, crypto, passphrase
from askwell.audit import Store, record
from askwell.backup import TABLES
from askwell.config import Settings
from askwell.db.engine import session_scope
from askwell.logging import get_logger

log = get_logger(__name__)

RESTORE_JOB_ENQUEUED = "restore_job_enqueued"
RESTORE_COMPLETED = "restore_completed"

_INSERT_BATCH_SIZE = 2000

# table -> self-referencing column that must be restored in a second pass,
# after every row of the table exists — see the module docstring.
_SELF_REFERENTIAL_COLUMNS: dict[str, str] = {
    "documents": "superseded_by",
    "schema_notes": "superseded_by",
    "memory": "superseded_by",
}

# `askwell_app` has no UPDATE/DELETE/TRUNCATE grant on either audit table
# (`docs/decisions.md`, "the database has three roles" — C6), and `enqueue`/
# `run_job` write to `audit_decisions` before any clearing could happen
# anyway. Excluded from `_existing_data_present` and `_clear_existing` —
# see the module docstring's "the audit stores are a deliberate exception".
_APPEND_ONLY_TABLES = frozenset({"audit_decisions", "audit_interactions"})

_STATUS_QUEUED = "queued"
_STATUS_RESTORING_TABLES = "restoring_tables"
_STATUS_REEMBEDDING = "reembedding"
_STATUS_DONE = "done"
_STATUS_FAILED = "failed"


class ArtefactInvalid(Exception):
    """Not a zip, or missing `manifest.json` — not a backup this can read."""


class VersionRefused(Exception):
    """The artefact's `askwell_version` is newer than this install's.

    Refused by name rather than partially applied — see the module
    docstring.
    """


class PassphraseRequired(Exception):
    """The backup is passphrase-protected and no passphrase was given."""


class IncorrectPassphrase(Exception):
    """The passphrase given does not unwrap this backup's install secret.

    Deliberately the same message `askwell.passphrase.IncorrectPassphrase`
    uses — a wrong passphrase is a wrong passphrase, whichever operation
    it was given to.
    """


class ExistingDataPresent(Exception):
    """The target already holds data and `replace_existing` was not set.

    Restore never merges silently — the ticket's own Validation Rule.
    """


def _parse_version(value: str) -> tuple[int, int, int]:
    major, minor, patch = value.split(".")
    return (int(major), int(minor), int(patch))


def _check_version(source_version: str) -> None:
    if _parse_version(source_version) > _parse_version(__version__):
        raise VersionRefused(
            f"This backup was made with Askwell {source_version}, newer than this "
            f"install ({__version__}). Refused rather than partially applied — "
            f"update Askwell to at least {source_version} before restoring it."
        )


@dataclass(frozen=True, slots=True)
class RestoreManifest:
    askwell_version: str
    chunk_count: int
    estimated_reembed_seconds: float
    passphrase_protected: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "askwell_version": self.askwell_version,
            "chunk_count": self.chunk_count,
            "estimated_reembed_seconds": self.estimated_reembed_seconds,
            "passphrase_protected": self.passphrase_protected,
        }


@dataclass(frozen=True, slots=True)
class RestoreJob:
    id: uuid.UUID
    status: str
    file_path: str
    source_version: str
    replace_existing: bool
    passphrase_protected: bool
    chunk_count: int | None
    estimated_reembed_seconds: float | None
    tables_total: int
    tables_done: int
    rows_total: int
    rows_done: int
    chunks_total: int
    chunks_done: int
    chain_verified: bool | None
    chain_detail: str | None
    error: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "status": self.status,
            "source_version": self.source_version,
            "replace_existing": self.replace_existing,
            "passphrase_protected": self.passphrase_protected,
            "chunk_count": self.chunk_count,
            "estimated_reembed_seconds": self.estimated_reembed_seconds,
            "tables_total": self.tables_total,
            "tables_done": self.tables_done,
            "rows_total": self.rows_total,
            "rows_done": self.rows_done,
            "chunks_total": self.chunks_total,
            "chunks_done": self.chunks_done,
            "chain_verified": self.chain_verified,
            "chain_detail": self.chain_detail,
            "error": self.error,
        }


# --- inspect, before anything commits --------------------------------------


def inspect_artefact(path: Path) -> RestoreManifest:
    """Read `manifest.json` out of the zip without extracting it — what
    `/restore/inspect` shows before the user commits, and what `enqueue`
    re-derives under its own read rather than trusting a stale client value.
    """
    if not path.is_file():
        raise ArtefactInvalid(f"No file at {path}.")
    try:
        with zipfile.ZipFile(path) as archive:
            manifest = json.loads(archive.read("manifest.json"))
    except (zipfile.BadZipFile, KeyError) as error:
        raise ArtefactInvalid(f"{path} is not a readable Askwell backup: {error}") from error

    _check_version(manifest["askwell_version"])
    return RestoreManifest(
        askwell_version=manifest["askwell_version"],
        chunk_count=manifest["chunk_count"],
        estimated_reembed_seconds=manifest["estimated_reembed_seconds"],
        passphrase_protected=manifest["passphrase_protected"],
    )


# --- enqueue, dispatch, resume ----------------------------------------------


async def _existing_data_present(session: AsyncSession) -> bool:
    """Whether the target already holds corpus/memory data worth refusing
    to merge into. The audit tables are excluded — see the module
    docstring's "the audit stores are a deliberate exception": `enqueue`
    itself writes a decisions record before this check's caller ever
    returns to a fresh-install caller, so "does `audit_decisions` have a
    row" is never a meaningful signal for "is this machine actually new".
    """
    for table in TABLES:
        if table in _APPEND_ONLY_TABLES:
            continue
        exists = (await session.execute(text(f"SELECT EXISTS(SELECT 1 FROM {table})"))).scalar_one()
        if exists:
            return True
    return False


async def _clear_existing(session: AsyncSession) -> None:
    """Empty every table in `TABLES` except the two audit tables, before a
    `replace_existing` restore.

    `DELETE`, not `TRUNCATE`: `askwell_app` holds no `TRUNCATE` grant on
    anything (`docs/decisions.md`, "the database has three roles") — only
    `SELECT, INSERT, UPDATE, DELETE` on ordinary tables. Deletes run in
    reverse of `TABLES`' own FK-safe order (children before the parents
    they reference) rather than relying on `ON DELETE CASCADE` to sort it
    out, so this works identically regardless of which relationships happen
    to cascade. The audit tables are skipped entirely, never cleared and
    never refused on — module docstring.
    """
    for table in reversed(list(TABLES)):
        if table in _APPEND_ONLY_TABLES:
            continue
        await session.execute(text(f"DELETE FROM {table}"))


async def enqueue(
    session: AsyncSession,
    settings: Settings,
    *,
    path: Path,
    restore_passphrase: str | None,
    replace_existing: bool,
) -> uuid.UUID:
    """Record the intent to restore. No decisions record here — `run_job`'s
    `RESTORE_COMPLETED` is what satisfies the ticket's Audit Requirement;
    see the module docstring for why writing one this early would corrupt
    the very chain a clean restore is about to bring in.
    """
    manifest = await asyncio.to_thread(inspect_artefact, path)
    if manifest.passphrase_protected and restore_passphrase is None:
        raise PassphraseRequired(
            "This backup is passphrase-protected. Its passphrase — the one set on "
            "the machine it came from — is required, and there is no recovery "
            "without it."
        )
    if not replace_existing and await _existing_data_present(session):
        raise ExistingDataPresent(
            "This machine already has data. Restore refuses to merge silently — "
            "confirm replacing it to continue."
        )

    job_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO restore_jobs "
            "(id, file_path, source_version, replace_existing, passphrase_protected, "
            "chunk_count, estimated_reembed_seconds, tables_total, chunks_total) "
            "VALUES (:id, :path, :version, :replace, :protected, :chunk_count, :reembed, "
            ":tables_total, :chunks_total)"
        ),
        {
            "id": job_id,
            "path": str(path),
            "version": manifest.askwell_version,
            "replace": replace_existing,
            "protected": manifest.passphrase_protected,
            "chunk_count": manifest.chunk_count,
            "reembed": manifest.estimated_reembed_seconds,
            "tables_total": len(TABLES),
            "chunks_total": manifest.chunk_count,
        },
    )
    # Deliberately no `record(...)` here, unlike `askwell.backup.enqueue` —
    # see the module docstring's "the audit stores are a deliberate
    # exception". Writing one now would give a clean target's
    # `audit_decisions` a second `prev_hash IS NULL` root before the
    # historical chain this job is about to restore, breaking the very
    # verification the ticket's own golden path expects to pass.
    # `RESTORE_COMPLETED` covers the Audit Requirement once the restored
    # chain is the only thing anything has been written next to.
    log.info(RESTORE_JOB_ENQUEUED, job_id=str(job_id))
    return job_id


async def dispatch(settings: Settings, jobs: list[tuple[uuid.UUID, str | None]]) -> int:
    """Ask a worker to pick these up now. `jobs` pairs a job id with the
    passphrase to run it with (`None` for an unprotected backup) — the
    passphrase travels only as far as this one arq call and is never written
    to Postgres, the same reasoning the module docstring gives in full.
    """
    if not jobs:
        return 0

    from arq import create_pool
    from redis.exceptions import RedisError

    from askwell.worker import redis_settings

    queue = redis_settings(settings)
    try:
        pool = await create_pool(queue)
    except (OSError, RedisError) as error:
        log.warning("restore_dispatch_unavailable", error=str(error), jobs=len(jobs))
        return 0

    sent = 0
    try:
        for job_id, job_passphrase in jobs:
            job = await pool.enqueue_job(
                "restore_job", str(job_id), job_passphrase, _job_id=f"restore:{job_id}"
            )
            if job is not None:
                sent += 1
    except (OSError, RedisError) as error:  # pragma: no cover - needs a mid-flight failure
        log.warning("restore_dispatch_failed", error=str(error))
    finally:
        await pool.aclose()
    return sent


async def resume(session: AsyncSession) -> list[tuple[uuid.UUID, bool]]:
    """Return every job a dead worker was holding to `queued`, as
    `(job_id, passphrase_protected)` pairs. Does not redispatch — see the
    module docstring on why a passphrase-protected job cannot redispatch
    itself.
    """
    result = await session.execute(
        text(
            "UPDATE restore_jobs SET status = 'queued', started_at = NULL "
            f"WHERE status IN ('{_STATUS_RESTORING_TABLES}', '{_STATUS_REEMBEDDING}') "
            "RETURNING id, passphrase_protected"
        )
    )
    return [(row[0], row[1]) for row in result.all()]


async def get_job(session: AsyncSession, job_id: uuid.UUID) -> RestoreJob | None:
    row = (
        await session.execute(
            text(
                "SELECT id, status, file_path, source_version, replace_existing, "
                "passphrase_protected, chunk_count, estimated_reembed_seconds, tables_total, "
                "tables_done, rows_total, rows_done, chunks_total, chunks_done, chain_verified, "
                "chain_detail, error FROM restore_jobs WHERE id = :id"
            ),
            {"id": job_id},
        )
    ).first()
    if row is None:
        return None
    return RestoreJob(*row)


# --- running one job ---------------------------------------------------


class SchemaNotCurrent(Exception):
    """The target database is not at Alembic head.

    Restore cannot fix this itself — see `_check_schema_current`'s
    docstring for why running the migration here is not an option at all,
    not merely undesirable.
    """


def _alembic_head() -> str:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    api_dir = Path(__file__).resolve().parents[2]
    cfg = Config(str(api_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(api_dir / "src" / "askwell" / "db" / "migrations"))
    head = ScriptDirectory.from_config(cfg).get_current_head()
    assert head is not None  # the migration chain is never empty
    return head


async def _check_schema_current(session: AsyncSession) -> None:
    """Refuse rather than migrate. `askwell_app` — what this process
    connects as (`compose.yaml`, `docs/decisions.md` "three roles") — owns
    nothing and has no DDL grant at all; only the `askwell` owner role can
    run a migration, and nothing in this process ever holds those
    credentials, by the same design that keeps C6's audit grants real. This
    is the correct resolution to issue #570, not merely the cheaper one:
    `AGENTS.md` §5 already documents `scripts/dev.sh db upgrade head` as an
    operator's manual step, and restore inventing a second, automatic path
    to the same command — one it cannot even authenticate to perform —
    would be a capability this process does not have, attempted anyway.
    """
    head = await asyncio.to_thread(_alembic_head)
    row = (await session.execute(text("SELECT version_num FROM alembic_version"))).first()
    current = None if row is None else row[0]
    if current != head:
        raise SchemaNotCurrent(
            f"This database is at migration {current!r}, not head ({head!r}). Run "
            "`scripts/dev.sh db upgrade head` before restoring — restore reads and "
            "writes rows, it does not have the credentials to change the schema."
        )


def _write_install_secret(path: Path, install_secret: bytes) -> None:
    """Overwrite this install's secret with the one the backup was made
    under — the only way the restored ciphertext (`chunks.content`,
    `sources.config_encrypted`) is ever decryptable again. Same
    write-then-rename, owner-only-permissions pattern
    `crypto.load_or_create_install_secret` already uses."""
    import os
    import stat

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    tmp_path.write_bytes(install_secret)
    tmp_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    tmp_path.replace(path)


async def _table_column_types(session: AsyncSession, table: str) -> dict[str, str]:
    rows = (
        await session.execute(
            text(
                "SELECT column_name, udt_name FROM information_schema.columns "
                "WHERE table_name = :table"
            ),
            {"table": table},
        )
    ).all()
    return {name: udt for name, udt in rows}


async def _restore_table(session: AsyncSession, table: str, job_dir: Path) -> int:
    """Restore one table from its JSONL, inside the caller's transaction.

    Casts every column against `information_schema` (module docstring), and
    defers `_SELF_REFERENTIAL_COLUMNS[table]` to a second pass once every row
    exists.
    """
    path = job_dir / f"{table}.jsonl"
    if not path.exists():
        # Present in `TABLES` but absent from an older artefact that predates
        # this table — nothing to restore, and `_check_schema_current`
        # already confirmed the (empty) table itself exists.
        return 0

    column_types = await _table_column_types(session, table)
    deferred_column = _SELF_REFERENTIAL_COLUMNS.get(table)
    pk_column = TABLES[table][0]
    json_columns = {name for name, udt in column_types.items() if udt in ("json", "jsonb")}

    deferred: list[tuple[Any, Any]] = []
    count = 0
    batch: list[dict[str, Any]] = []

    async def flush() -> None:
        nonlocal batch
        if not batch:
            return
        columns = list(batch[0].keys())
        values_sql = ", ".join(
            f"CAST(:{column} AS {column_types.get(column, 'text')})" for column in columns
        )
        stmt = text(f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({values_sql})")
        for row in batch:
            await session.execute(stmt, row)
        batch = []

    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            row: dict[str, Any] = json.loads(line)
            for column in json_columns & row.keys():
                if row[column] is not None:
                    row[column] = json.dumps(row[column])
            if deferred_column is not None and row.get(deferred_column) is not None:
                deferred.append((row[pk_column], row[deferred_column]))
                row[deferred_column] = None
            batch.append(row)
            count += 1
            if len(batch) >= _INSERT_BATCH_SIZE:
                await flush()
    await flush()

    if deferred_column is not None and deferred:
        pk_type = column_types.get(pk_column, "uuid")
        col_type = column_types.get(deferred_column, "uuid")
        for pk_value, ref_value in deferred:
            await session.execute(
                text(
                    f"UPDATE {table} SET {deferred_column} = CAST(:val AS {col_type}) "
                    f"WHERE {pk_column} = CAST(:pk AS {pk_type})"
                ),
                {"val": ref_value, "pk": pk_value},
            )
    return count


async def _reembed_corpus(
    sessions: async_sessionmaker[AsyncSession], settings: Settings, job_id: uuid.UUID
) -> None:
    """Re-embed every chunk the backup excluded. `WHERE embedding IS NULL`
    is the whole resume story — module docstring."""
    from askwell.embed import _embed_batch
    from askwell.inference.client import InferenceClient

    client = InferenceClient(settings)
    while True:
        async with session_scope(sessions) as session:
            rows = (
                await session.execute(
                    text(
                        "SELECT id, content, content_encrypted FROM chunks "
                        "WHERE content IS NOT NULL AND embedding IS NULL "
                        "ORDER BY id LIMIT :batch"
                    ),
                    {"batch": settings.embedding_batch_size},
                )
            ).all()
        if not rows:
            return

        key: bytes | None = None
        if any(content_encrypted for _id, _content, content_encrypted in rows):
            async with session_scope(sessions) as session:
                key = await passphrase.current_key(session, settings)

        pending: list[tuple[uuid.UUID, str]] = []
        for chunk_id, content, content_encrypted in rows:
            if content is not None and content_encrypted:
                assert key is not None
                content = crypto.decrypt(content.encode("ascii"), key).decode("utf-8")
            pending.append((chunk_id, content))

        # One inference call per fetched page — `settings.embedding_batch_size`
        # already bounds `rows` above, so there is nothing further to chunk.
        vectors = await _embed_batch(client, [content for _chunk_id, content in pending])
        async with session_scope(sessions) as session:
            for (chunk_id, _content), vector in zip(pending, vectors, strict=True):
                await session.execute(
                    text("UPDATE chunks SET embedding = :embedding WHERE id = :id"),
                    {"embedding": str(vector), "id": chunk_id},
                )
            await session.execute(
                text("UPDATE restore_jobs SET chunks_done = chunks_done + :n WHERE id = :id"),
                {"n": len(pending), "id": job_id},
            )


async def run_job(
    sessions: async_sessionmaker[AsyncSession],
    settings: Settings,
    job_id: uuid.UUID,
    restore_passphrase: str | None = None,
) -> None:
    """Restore one job end to end: migrate, unwrap the install secret if
    needed, truncate if asked, restore every table, re-embed, verify the
    chain. See the module docstring for the reasoning behind each step.
    """
    async with session_scope(sessions) as session:
        job = await get_job(session, job_id)
    if job is None:
        return

    async with session_scope(sessions) as session:
        await session.execute(
            text(
                "UPDATE restore_jobs SET status = :status, "
                "started_at = COALESCE(started_at, now()) WHERE id = :id"
            ),
            {"status": _STATUS_RESTORING_TABLES, "id": job_id},
        )

    job_dir = settings.backup_dir / "restore" / str(job_id)
    try:
        if job.passphrase_protected and restore_passphrase is None:
            raise PassphraseRequired(
                "This backup is passphrase-protected. Its passphrase is required to "
                "continue restoring it."
            )

        async with session_scope(sessions) as session:
            await _check_schema_current(session)

        if job_dir.exists():
            shutil.rmtree(job_dir)
        job_dir.mkdir(parents=True)

        def _extract() -> dict[str, Any]:
            with zipfile.ZipFile(job.file_path) as archive:
                for member in archive.namelist():
                    target = (job_dir / member).resolve()
                    if job_dir.resolve() not in target.parents and target != job_dir.resolve():
                        raise ArtefactInvalid(f"Unsafe path in backup artefact: {member!r}.")
                archive.extractall(job_dir)
            data: dict[str, Any] = json.loads(
                (job_dir / "manifest.json").read_text(encoding="utf-8")
            )
            return data

        manifest = await asyncio.to_thread(_extract)
        _check_version(manifest["askwell_version"])

        if manifest["passphrase_protected"]:
            assert restore_passphrase is not None
            wrapped = manifest["install_secret_wrapped"]
            portable_key = crypto.derive_key(b"", restore_passphrase)
            try:
                install_secret = crypto.decrypt(base64.urlsafe_b64decode(wrapped), portable_key)
            except crypto.CredentialsLocked as error:
                raise IncorrectPassphrase("Incorrect passphrase.") from error
            await asyncio.to_thread(
                _write_install_secret, settings.install_secret_path, install_secret
            )

        if job.replace_existing:
            async with session_scope(sessions) as session:
                already_cleared = (
                    await session.execute(
                        text("SELECT truncated FROM restore_jobs WHERE id = :id"), {"id": job_id}
                    )
                ).scalar_one()
                if not already_cleared:
                    await _clear_existing(session)
                    await session.execute(
                        text("UPDATE restore_jobs SET truncated = true WHERE id = :id"),
                        {"id": job_id},
                    )

        table_names = list(TABLES)
        async with session_scope(sessions) as session:
            tables_done = (
                await session.execute(
                    text("SELECT tables_done FROM restore_jobs WHERE id = :id"), {"id": job_id}
                )
            ).scalar_one()

        for index, table in enumerate(table_names):
            if index < tables_done:
                continue
            async with session_scope(sessions) as session:
                count = await _restore_table(session, table, job_dir)
                await session.execute(
                    text(
                        "UPDATE restore_jobs SET tables_done = tables_done + 1, "
                        "rows_done = rows_done + :count WHERE id = :id"
                    ),
                    {"count": count, "id": job_id},
                )

        if manifest["passphrase_protected"]:
            assert restore_passphrase is not None
            async with session_scope(sessions) as session:
                await passphrase.unlock(session, settings, restore_passphrase)

        async with session_scope(sessions) as session:
            await session.execute(
                text("UPDATE restore_jobs SET status = :status WHERE id = :id"),
                {"status": _STATUS_REEMBEDDING, "id": job_id},
            )

        await _reembed_corpus(sessions, settings, job_id)

        from askwell.log_verify import run as verify_chains

        async with session_scope(sessions) as session:
            chain_result = await verify_chains(session)
        chain_verified = bool(chain_result["intact"])

        async with session_scope(sessions) as session:
            await session.execute(
                text(
                    "UPDATE restore_jobs SET status = :status, finished_at = now(), "
                    "chain_verified = :verified, chain_detail = :detail WHERE id = :id"
                ),
                {
                    "status": _STATUS_DONE,
                    "verified": chain_verified,
                    "detail": json.dumps(chain_result),
                    "id": job_id,
                },
            )
            await record(
                session,
                Store.DECISIONS,
                RESTORE_COMPLETED,
                {
                    "job_id": str(job_id),
                    "source_version": job.source_version,
                    "chain_verified": chain_verified,
                },
            )
        shutil.rmtree(job_dir, ignore_errors=True)
        log.info("restore_done", job_id=str(job_id), chain_verified=chain_verified)
    except Exception as error:
        log.warning("restore_failed", job_id=str(job_id), error=f"{type(error).__name__}: {error}")
        async with session_scope(sessions) as session:
            await session.execute(
                text(
                    "UPDATE restore_jobs SET status = 'failed', finished_at = now(), "
                    "error = :error WHERE id = :id"
                ),
                {"id": job_id, "error": f"{type(error).__name__}: {error}"},
            )
        raise


# --- HTTP --------------------------------------------------------------


class InspectRestoreRequest(BaseModel):
    path: str


class CreateRestoreRequest(BaseModel):
    path: str
    passphrase: str | None = None
    replace_existing: bool = False


class ResumeRestoreRequest(BaseModel):
    passphrase: str | None = None


def register_restore(
    app: FastAPI, settings: Settings, factory: async_sessionmaker[AsyncSession]
) -> None:
    """`POST /restore/inspect` states the version, chunk count and re-embed
    cost before the user commits; `POST /restore` enqueues and dispatches a
    job; `GET /restore/{id}` reads its progress; `POST /restore/{id}/resume`
    redispatches a job stalled on a passphrase a worker restart lost.
    """

    @app.post("/restore/inspect")
    async def inspect_route(body: InspectRestoreRequest) -> JSONResponse:
        try:
            manifest = await asyncio.to_thread(inspect_artefact, Path(body.path))
        except ArtefactInvalid as error:
            return JSONResponse({"error": str(error)}, status_code=422)
        except VersionRefused as error:
            return JSONResponse({"error": str(error)}, status_code=409)
        return JSONResponse(manifest.as_dict())

    @app.post("/restore")
    async def create_restore(body: CreateRestoreRequest) -> JSONResponse:
        try:
            async with session_scope(factory) as db:
                job_id = await enqueue(
                    db,
                    settings,
                    path=Path(body.path),
                    restore_passphrase=body.passphrase,
                    replace_existing=body.replace_existing,
                )
        except ArtefactInvalid as error:
            return JSONResponse({"error": str(error)}, status_code=422)
        except VersionRefused as error:
            return JSONResponse({"error": str(error)}, status_code=409)
        except PassphraseRequired as error:
            return JSONResponse({"error": str(error)}, status_code=422)
        except ExistingDataPresent as error:
            return JSONResponse({"error": str(error)}, status_code=409)

        await dispatch(settings, [(job_id, body.passphrase)])
        async with session_scope(factory) as db:
            job = await get_job(db, job_id)
        assert job is not None
        return JSONResponse(job.as_dict(), status_code=201)

    @app.get("/restore/{job_id}")
    async def read_restore(job_id: uuid.UUID) -> JSONResponse:
        async with session_scope(factory) as db:
            job = await get_job(db, job_id)
        if job is None:
            return JSONResponse({"error": "No such restore."}, status_code=404)
        return JSONResponse(job.as_dict())

    @app.post("/restore/{job_id}/resume")
    async def resume_restore(job_id: uuid.UUID, body: ResumeRestoreRequest) -> JSONResponse:
        async with session_scope(factory) as db:
            job = await get_job(db, job_id)
        if job is None:
            return JSONResponse({"error": "No such restore."}, status_code=404)
        if job.status not in (_STATUS_QUEUED,):
            return JSONResponse({"error": f"Restore is {job.status}, not queued."}, status_code=409)
        if job.passphrase_protected and body.passphrase is None:
            return JSONResponse(
                {"error": "This restore is passphrase-protected. Its passphrase is required."},
                status_code=422,
            )
        await dispatch(settings, [(job_id, body.passphrase)])
        async with session_scope(factory) as db:
            job = await get_job(db, job_id)
        assert job is not None
        return JSONResponse(job.as_dict())
