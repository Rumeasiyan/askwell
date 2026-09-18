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

**Size and time caps, `M4-DUMP-VAL-089`.** Both are enforced inside
`_load_blocking` while the dump is still streaming, not checked once at the
end — the whole point is that a 200 GB dump never finishes writing to disk in
the first place. The size cap is measured against `pg_database_size` of the
sandbox database itself, not `dump_path`'s size on disk: a dump that is small
as a file but expands once loaded (generated rows, a wide `COPY`) is exactly
the case a file-size check would miss. Measuring it means a real connection
to the sandbox instance, so it is polled on a cadence (`CAP_POLL_SECONDS`)
rather than after every chunk fed to `psql` — a database-size query per
megabyte would make the cap itself the slow part of every import. The time
cap has no such cost and is checked every chunk from a monotonic clock. When
a poll finds both caps already exceeded, the size cap is reported: it can
only ever be noticed at the polling cadence, so by the time it is seen it may
already have been true for up to `CAP_POLL_SECONDS` — the time cap, checked
continuously, is never stale by more than one chunk. `DumpCapExceeded` reuses
`DumpImportFailed`'s whole existing path (drop the database, mark the source
`attention`, record `IMPORT_FAILED`) rather than a parallel one, with `cap`
threaded onto that same audit payload so "how many imports were aborted for
a cap, not a bad dump" stays a query over `audit_decisions` — the same shape
every other local counter in this codebase already takes (`ingest.py`'s
`documents_flagged`, `roots.py`'s rejection count), not a maintained integer
nothing else reads.
"""

import asyncio
import subprocess
import tempfile
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path

import psycopg
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from askwell import audit, sandbox
from askwell.audit import Store
from askwell.config import Settings
from askwell.db.engine import session_scope
from askwell.logging import get_logger
from askwell.settings_store import get_setting, set_setting

log = get_logger(__name__)

# Decisions records (AGENTS.md §8, `docs/audit-log.md` §2): import start and
# outcome. `askwell.sandbox` already logs its own database-creation and
# database-drop decisions, so those are not repeated here.
IMPORT_STARTED = "dump_import_started"
IMPORT_SUCCEEDED = "dump_import_succeeded"
IMPORT_FAILED = "dump_import_failed"
CAP_CHANGED = "dump_cap_changed"

# `docs/data-sources.md` §3: "Sandbox caps: 5 GB and 10 minutes per import.
# Beyond either, the import aborts and the sandbox database is dropped. Both
# user-adjustable." Stored in the `settings` key/value table, the same
# mechanism `askwell.clarify`'s cap already uses — not on `Settings`, which is
# environment configuration fixed at process start, not something a user
# changes from a settings screen between imports.
DUMP_SIZE_CAP_KEY = "dump_size_cap_bytes"
DUMP_TIME_CAP_KEY = "dump_time_cap_seconds"
DEFAULT_DUMP_SIZE_CAP_BYTES = 5 * 1024**3
DEFAULT_DUMP_TIME_CAP_SECONDS = 600.0

# How often the sandbox database's own size is polled during a load. Not the
# same figure as `PROGRESS_INTERVAL_SECONDS` below — that one paces a status
# line for someone watching; this one bounds how stale the size cap check can
# be, and is deliberately answered on its own.
CAP_POLL_SECONDS = 2.0

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


class DumpCapExceeded(DumpImportFailed):
    """The import was aborted for crossing a configured cap, not for a bad
    dump. `cap` is `"size"` or `"time"`; `limit` is the setting in force at
    the moment of the abort, so a later cap change cannot make an old record
    say something that was never actually checked."""

    def __init__(self, cap: str, limit: float, message: str) -> None:
        super().__init__(message)
        self.cap = cap
        self.limit = limit


def _format_bytes(count: float) -> str:
    value = float(count)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def _format_seconds(count: float) -> str:
    """`10 minutes`, matching `docs/data-sources.md` §3's own wording for the
    default. Below a minute, one decimal place — otherwise an abort at 1.3s
    against a 1s cap reads as the nonsensical "1s, over the time cap of 1s"."""
    if count < 60:
        return f"{count:.1f}s"
    minutes, seconds = divmod(round(count), 60)
    if minutes and seconds:
        return f"{minutes} minute{'s' if minutes != 1 else ''} {seconds}s"
    return f"{minutes} minute{'s' if minutes != 1 else ''}"


async def get_dump_size_cap_bytes(session: AsyncSession) -> int:
    value = await get_setting(session, DUMP_SIZE_CAP_KEY)
    return DEFAULT_DUMP_SIZE_CAP_BYTES if value is None else int(value)


async def set_dump_size_cap_bytes(session: AsyncSession, cap_bytes: int) -> None:
    """The only way the size cap is changed — always a decision record
    (`docs/data-sources.md` §3: both caps are "user-adjustable"), same shape
    as `askwell.clarify.set_clarification_cap`."""
    if cap_bytes < 1:
        raise ValueError("dump size cap must be at least 1 byte")
    previous = await get_dump_size_cap_bytes(session)
    await set_setting(session, DUMP_SIZE_CAP_KEY, str(cap_bytes))
    await audit.record(
        session,
        Store.DECISIONS,
        CAP_CHANGED,
        {"cap": "size", "previous": previous, "new": cap_bytes},
    )


async def get_dump_time_cap_seconds(session: AsyncSession) -> float:
    value = await get_setting(session, DUMP_TIME_CAP_KEY)
    return DEFAULT_DUMP_TIME_CAP_SECONDS if value is None else float(value)


async def set_dump_time_cap_seconds(session: AsyncSession, cap_seconds: float) -> None:
    """The only way the time cap is changed — see `set_dump_size_cap_bytes`.

    `previous`/`new` go into the audit payload as strings, not the `float`
    this function's own signature carries: `audit.compute_hash` refuses a
    `float` outright (`docs/audit-log.md` — a float does not round-trip
    identically through jsonb, so a later verification would report
    tampering that never happened), the same reason `retrieval_score_threshold`
    is never itself written into a payload elsewhere in this codebase.
    """
    if cap_seconds <= 0:
        raise ValueError("dump time cap must be greater than zero")
    previous = await get_dump_time_cap_seconds(session)
    await set_setting(session, DUMP_TIME_CAP_KEY, str(cap_seconds))
    await audit.record(
        session,
        Store.DECISIONS,
        CAP_CHANGED,
        {"cap": "time", "previous": str(previous), "new": str(cap_seconds)},
    )


def _database_size_blocking(admin_url: str, database: str) -> int:
    """The sandbox database's own loaded size, in bytes — connected to
    `admin_url`'s maintenance database, the same way `sandbox.known_databases`
    is, so this needs no connection to the database being measured (which the
    owner role loading it already holds exclusively enough as it is)."""
    with psycopg.connect(admin_url, autocommit=True) as admin:
        row = admin.execute("SELECT pg_database_size(%s)", (database,)).fetchone()
    assert row is not None
    return int(row[0])


def _load_blocking(
    dsn: str,
    dump_path: Path,
    report: Report | None,
    *,
    admin_url: str,
    database: str,
    size_cap_bytes: int,
    time_cap_seconds: float,
) -> int:
    """Stream `dump_path` into `psql` and return the bytes fed.

    Streamed in `CHUNK_SIZE` pieces rather than handed to `psql -f` in one
    call purely so progress has something to measure — `psql` gives no
    progress of its own over a plain-format load. `stderr` goes to a spooled
    temp file rather than a pipe: a pipe fills and deadlocks against a
    process that is also waiting on us to keep feeding `stdin`, and a broken
    dump can produce enough `NOTICE`/`ERROR` output to hit that.

    `M4-DUMP-VAL-089`: a watchdog thread, not a check between chunks, is what
    enforces both caps. Most of a real dump's wall-clock time is spent
    *inside* a single `proc.stdin.write` (blocked once the OS pipe buffer
    fills, waiting for `psql` to drain it by running the next statement) or
    inside the final `proc.wait()` once every byte has already been fed and
    `psql` is still executing — a long `CREATE INDEX` or the edge case's own
    `pg_sleep` is exactly this shape. A check placed only between reads of
    `dump_path` would never run while blocked there, which is the one moment
    "the statement is terminated rather than waited on" actually has to fire.
    The watchdog polls independently of whatever the main thread is doing and
    calls `proc.kill()` itself the instant a cap is crossed — SIGKILL ends the
    *client*, which is enough to unblock a stuck `write()`/`wait()`; ending
    the *statement* still running server-side is `import_dump`'s job, via
    `sandbox.drop_database(..., WITH (FORCE))` once this raises.
    """
    total = dump_path.stat().st_size
    start = time.monotonic()
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

        def check_once(measure_size: bool) -> DumpCapExceeded | None:
            """One evaluation of both caps. `measure_size` gates the real
            database-size query behind the poll cadence; the elapsed-time
            check is free and always runs, so a call from the watchdog's own
            loop and a call from the final backstop below share one place
            that decides what "exceeded" means for each cap."""
            if measure_size:
                try:
                    loaded = _database_size_blocking(admin_url, database)
                except Exception:
                    # The sandbox database may already be gone (a normal
                    # finish racing this check); a cap check that crashes
                    # here would surface as an unrelated, misleading
                    # traceback instead of the real outcome.
                    loaded = None
                if loaded is not None and loaded > size_cap_bytes:
                    return DumpCapExceeded(
                        "size",
                        size_cap_bytes,
                        f"Import aborted: loaded data reached {_format_bytes(loaded)}, "
                        f"over the size cap of {_format_bytes(size_cap_bytes)}.",
                    )
            elapsed = time.monotonic() - start
            if elapsed > time_cap_seconds:
                return DumpCapExceeded(
                    "time",
                    time_cap_seconds,
                    f"Import aborted: running for {_format_seconds(elapsed)}, "
                    f"over the time cap of {_format_seconds(time_cap_seconds)}.",
                )
            return None

        cap_error: list[DumpCapExceeded] = []
        stop_watchdog = threading.Event()

        def watchdog() -> None:
            last_size_poll = 0.0
            while not stop_watchdog.wait(min(0.2, CAP_POLL_SECONDS)):
                now = time.monotonic()
                due = not last_size_poll or now - last_size_poll >= CAP_POLL_SECONDS
                if due:
                    last_size_poll = now
                error = check_once(due)
                if error is not None:
                    cap_error.append(error)
                    proc.kill()
                    return

        watchdog_thread = threading.Thread(target=watchdog, daemon=True)
        watchdog_thread.start()

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
                        # something, or the watchdog killed it) — stop
                        # feeding it and let what follows report why.
                        break
                    done += len(block)
                    maybe_report(done)
        finally:
            try:
                proc.stdin.close()
            except (BrokenPipeError, OSError):
                pass

        returncode = proc.wait()
        stop_watchdog.set()
        watchdog_thread.join()

        if not cap_error:
            # The watchdog polls on an interval and may never have gotten a
            # turn before a fast load already finished — an empty sandbox
            # database's own catalog overhead can already be over a small
            # size cap before a single byte of the dump is fed in, and that
            # must still abort rather than pass because psql happened to
            # exit first. One authoritative check, right when the load ends,
            # closes that race without changing what "exceeded" means.
            final_error = check_once(True)
            if final_error is not None:
                cap_error.append(final_error)

        if cap_error:
            raise cap_error[0]

        if returncode != 0:
            stderr_file.seek(0)
            reason = stderr_file.read().decode("utf-8", errors="replace").strip()
            raise DumpImportFailed(reason or f"psql exited with status {returncode}")

    maybe_report(total)
    return done


def _introspect_blocking(dsn: str) -> list[str]:
    """The table inventory a fresh load produced. Names only — see the module
    docstring on why full introspection is `M4-SCHEMA-ING-100`, not here."""
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
        size_cap_bytes = await get_dump_size_cap_bytes(session)
        time_cap_seconds = await get_dump_time_cap_seconds(session)
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
        await asyncio.to_thread(
            _load_blocking,
            dsn,
            dump_path,
            report,
            admin_url=admin_url,
            database=name,
            size_cap_bytes=size_cap_bytes,
            time_cap_seconds=time_cap_seconds,
        )
        tables = await asyncio.to_thread(_introspect_blocking, dsn)
    except Exception as error:
        if isinstance(error, DumpImportFailed):
            reason = str(error)
        else:
            reason = f"{type(error).__name__}: {error}"
        payload: dict[str, object] = {
            "source_id": str(source_id),
            "database": name,
            "reason": reason,
        }
        if isinstance(error, DumpCapExceeded):
            # The "local counter of aborted imports" the ticket's own
            # Analytics Events line asks for: a count over `audit_decisions`
            # where `payload->>'cap'` is set, never a maintained integer —
            # the same shape every other local counter in this codebase uses.
            payload["cap"] = error.cap
        async with session_scope(factory) as session:
            await sandbox.drop_database(session, admin_url, name, reason=reason)
            await session.execute(
                text(
                    "UPDATE sources SET sandbox_db = NULL, status = 'attention', "
                    "last_error = :error WHERE id = :id"
                ),
                {"error": reason, "id": source_id},
            )
            await audit.record(session, Store.DECISIONS, IMPORT_FAILED, payload)
        log.warning(
            "dump_import_failed",
            source_id=str(source_id),
            database=name,
            reason=reason,
            cap=getattr(error, "cap", None),
        )
        if isinstance(error, DumpImportFailed):
            raise
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
