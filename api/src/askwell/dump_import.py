"""Load a PostgreSQL dump into its own sandbox database. `M4-DUMP-ING-088`.

`docs/data-sources.md` §3: a `.sql` dump is a program, and importing it means
executing arbitrary DDL and DML from a file the user probably did not read.
`askwell.sandbox` (`M4-DUMP-DEPLOY-087`) is the isolation this depends on — a
separate Postgres instance, one database per source, a restricted role with
no superuser, no `CREATE DATABASE`, no large-object access. This module is
what actually runs a dump against that isolation and reports what happened.

**`psql`, not `psycopg` statement-by-statement.** A `pg_dump` plain-format
file's `COPY ... FROM stdin` blocks are not SQL statements a parser can split
correctly, and splitting one wrong either mis-loads a legitimate dump or,
worse, treats part of somebody's data as the next statement. Piping the whole
file to one `psql` process, `--set ON_ERROR_STOP=1`, is what every operator
does by hand — and it is exactly as safe here as it is for them, because what
actually contains the risk is the role the process runs as (`sandbox.OWNER_ROLE`,
C3), not how the file is fed in. `ON_ERROR_STOP=1` is also what makes the
"creates a role or tablespace" edge case (`docs/backlog` acceptance criteria)
resolve correctly without special-casing it: the owner role cannot do either,
Postgres refuses the statement, `psql` exits non-zero, and the caller drops
the whole database and reports why — a dump is never left half-loaded.

**Introspection here is structural, not semantic.** `import_dump` returns the
loaded database's table names so a successful import can say something
concrete about what it produced. Types, keys, relationships, and indexing any
of it for retrieval, is `M4-SCHEMA-ING-100` — this module hands off to that
by leaving a `ready` source with a real database behind it, not by building
the same thing twice under a different name.

**The owner role is sealed, not regenerated, once a load succeeds** —
`askwell.sandbox.seal_owner`, resolving issue #330. See that function's
docstring for why revoking `CONNECT` per database was chosen over a
generated credential pair per source.

**This module trusts `dump_path`.** The same way `askwell.ingest.process`
trusts a document's stored path once `askwell.sources.add` has already
checked it against a nominated root, whatever adds a dump source is
responsible for that check before calling `import_dump` — repeating it here
would be a second, divergent copy of `askwell.roots`.
"""

import asyncio
import subprocess
import tempfile
import time
import uuid
from collections.abc import Callable
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from askwell import audit, sandbox
from askwell.audit import Store
from askwell.config import Settings
from askwell.db.engine import session_scope
from askwell.logging import get_logger

log = get_logger(__name__)

# Decisions records (AGENTS.md §8, `docs/audit-log.md` §2): import start and
# outcome. `askwell.sandbox` already logs its own database-creation and
# database-drop decisions, so those are not repeated here.
IMPORT_STARTED = "dump_import_started"
IMPORT_SUCCEEDED = "dump_import_succeeded"
IMPORT_FAILED = "dump_import_failed"

# Bytes fed to `psql` between progress checks. The same figure as
# `sources.READ_CHUNK`, for the same reason: large enough that a multi-
# gigabyte dump is not a million syscalls, small enough that progress still
# moves visibly.
CHUNK_SIZE = 1024 * 1024

# How often a progress report actually lands, wall-clock. `ingest.py`'s own
# `PROGRESS_INTERVAL_SECONDS` (0.5s) is tuned for a request someone is
# watching load a single file; a dump import runs for minutes at best, so a
# slower cadence here is not felt and is a quarter of the log volume.
PROGRESS_INTERVAL_SECONDS = 2.0

Report = Callable[[int, int], None]


class DumpImportFailed(RuntimeError):
    """The dump did not load. `str(exc)` is the reason — shown to the user and
    recorded as the sandbox database's drop reason."""


def _load_blocking(dsn: str, dump_path: Path, report: Report | None) -> int:
    """Stream `dump_path` into `psql` and return the bytes fed.

    Streamed in `CHUNK_SIZE` pieces rather than handed to `psql -f` in one
    call purely so progress has something to measure — `psql` gives no
    progress of its own over a plain-format load. `stderr` goes to a spooled
    temp file rather than a pipe: a pipe fills and deadlocks against a
    process that is also waiting on us to keep feeding `stdin`, and a broken
    dump can produce enough `NOTICE`/`ERROR` output to hit that.
    """
    total = dump_path.stat().st_size
    last_report = 0.0

    def maybe_report(done: int) -> None:
        nonlocal last_report
        if report is None:
            return
        now = time.monotonic()
        if last_report and now - last_report < PROGRESS_INTERVAL_SECONDS and done < total:
            return
        last_report = now
        report(done, total)

    with tempfile.TemporaryFile() as stderr_file:
        proc = subprocess.Popen(
            ["psql", dsn, "--set", "ON_ERROR_STOP=1", "--no-psqlrc", "--quiet"],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=stderr_file,
        )
        assert proc.stdin is not None
        done = 0
        try:
            with dump_path.open("rb") as handle:
                while True:
                    block = handle.read(CHUNK_SIZE)
                    if not block:
                        break
                    try:
                        proc.stdin.write(block)
                    except BrokenPipeError:
                        # psql has already exited (ON_ERROR_STOP=1 hit
                        # something) — stop feeding it and let `wait()` below
                        # report the real failure.
                        break
                    done += len(block)
                    maybe_report(done)
        finally:
            try:
                proc.stdin.close()
            except (BrokenPipeError, OSError):
                pass

        returncode = proc.wait()
        if returncode != 0:
            stderr_file.seek(0)
            reason = stderr_file.read().decode("utf-8", errors="replace").strip()
            raise DumpImportFailed(reason or f"psql exited with status {returncode}")

    maybe_report(total)
    return done


def _introspect_blocking(dsn: str) -> list[str]:
    """The table inventory a fresh load produced. Names only — see the module
    docstring on why full introspection is `M4-SCHEMA-ING-100`, not here."""
    import psycopg

    with psycopg.connect(dsn, autocommit=True) as conn:
        rows = conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' ORDER BY table_name"
        ).fetchall()
    return [str(row[0]) for row in rows]


async def create_dump_source(session: AsyncSession, name: str, dump_path: str) -> uuid.UUID:
    """Register a dump source ahead of importing it.

    `root_path` carries the dump file's own path. It is not a folder Askwell
    indexes in place from the way a `file` source's is, but it is the same
    column and the same question — where this source's material actually is
    — so a second, dump-specific column would say nothing `root_path` does
    not already.
    """
    result = await session.execute(
        text(
            "INSERT INTO sources (kind, name, root_path, status) "
            "VALUES ('dump', :name, :root_path, 'queued') RETURNING id"
        ),
        {"name": name, "root_path": dump_path},
    )
    source_id = result.scalar_one()
    await audit.record(
        session,
        Store.DECISIONS,
        "source_added",
        {"source_id": str(source_id), "name": name, "kind": "dump"},
    )
    log.info("dump_source_added", source_id=str(source_id), name=name)
    return uuid.UUID(str(source_id))


async def import_dump(
    factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    source_id: uuid.UUID,
    dump_path: Path,
    *,
    report: Report | None = None,
) -> list[str]:
    """Create a sandbox database, load `dump_path` as the owner role, and hand
    off to schema introspection on success.

    A short-lived session per stage (`session_scope`), not one held across
    the whole load: the load itself runs for minutes under `asyncio.to_thread`
    and holding a transaction open for that long would sit on a pool
    connection nothing else could use for the same minutes.

    Every path through this function — success and failure alike — leaves the
    sandbox database either sealed (`askwell.sandbox.seal_owner`) or dropped
    (`askwell.sandbox.drop_database`); it is never left half-loaded and
    reachable, and it is never left claimed by `sources.sandbox_db` with
    nothing behind it.
    """
    admin_url = settings.sandbox_database_url.get_secret_value()
    owner_password = settings.sandbox_owner_password.get_secret_value()
    name = sandbox.generate_name()

    async with session_scope(factory) as session:
        await sandbox.create_database(session, admin_url, name)
        await session.execute(
            text("UPDATE sources SET sandbox_db = :db, status = 'indexing' WHERE id = :id"),
            {"db": name, "id": source_id},
        )
        await audit.record(
            session,
            Store.DECISIONS,
            IMPORT_STARTED,
            {"source_id": str(source_id), "database": name},
        )
    log.info("dump_import_started", source_id=str(source_id), database=name)

    dsn = sandbox.owner_url(admin_url, name, owner_password)

    try:
        await asyncio.to_thread(_load_blocking, dsn, dump_path, report)
        tables = await asyncio.to_thread(_introspect_blocking, dsn)
    except Exception as error:
        if isinstance(error, DumpImportFailed):
            reason = str(error)
        else:
            reason = f"{type(error).__name__}: {error}"
        async with session_scope(factory) as session:
            await sandbox.drop_database(session, admin_url, name, reason=reason)
            await session.execute(
                text(
                    "UPDATE sources SET sandbox_db = NULL, status = 'attention', "
                    "last_error = :error WHERE id = :id"
                ),
                {"error": reason, "id": source_id},
            )
            await audit.record(
                session,
                Store.DECISIONS,
                IMPORT_FAILED,
                {"source_id": str(source_id), "database": name, "reason": reason},
            )
        log.warning("dump_import_failed", source_id=str(source_id), database=name, reason=reason)
        raise DumpImportFailed(reason) from error

    async with session_scope(factory) as session:
        await sandbox.seal_owner(session, admin_url, name)
        await session.execute(
            text("UPDATE sources SET status = 'ready', last_indexed_at = now() WHERE id = :id"),
            {"id": source_id},
        )
        await audit.record(
            session,
            Store.DECISIONS,
            IMPORT_SUCCEEDED,
            {"source_id": str(source_id), "database": name, "tables": tables},
        )
    log.info("dump_import_succeeded", source_id=str(source_id), database=name, tables=len(tables))
    return tables


async def reclaim_interrupted(session: AsyncSession, admin_url: str) -> list[uuid.UUID]:
    """Drop a sandbox database an import was still loading when the process
    that ran it stopped, and mark its source for attention.

    Run at worker startup, alongside `askwell.sandbox.reclaim_orphans` — but
    this is a different case, not the same one under a different name.
    `reclaim_orphans` finds a database no `sources` row references at all
    (the crash landed between `sandbox.create_database` committing and the
    row committing, which cannot happen here: `import_dump` commits both in
    the same transaction). What this finds is a database a source *does*
    still claim, with `status = 'indexing'` — a load `import_dump` started
    and never got to finish, because the process is gone. There is no resume
    (`docs/backlog` — an import is a single attempt), so the only honest
    outcome is the one a fresh attempt would produce from scratch: the
    partial database dropped, the source told why, ready to be retried.
    """
    result = await session.execute(
        text(
            "SELECT id, sandbox_db FROM sources "
            "WHERE kind = 'dump' AND status = 'indexing' AND sandbox_db IS NOT NULL"
        )
    )
    rows = result.all()
    reclaimed: list[uuid.UUID] = []
    for source_id, database in rows:
        await sandbox.drop_database(session, admin_url, database, reason="interrupted_at_startup")
        await session.execute(
            text(
                "UPDATE sources SET sandbox_db = NULL, status = 'attention', "
                "last_error = 'Import was interrupted and needs to be retried.' "
                "WHERE id = :id"
            ),
            {"id": source_id},
        )
        await audit.record(
            session,
            Store.DECISIONS,
            IMPORT_FAILED,
            {"source_id": str(source_id), "database": database, "reason": "interrupted_at_startup"},
        )
        reclaimed.append(source_id)

    if reclaimed:
        log.warning(
            "dump_imports_reclaimed", count=len(reclaimed), sources=[str(s) for s in reclaimed]
        )
    return reclaimed
