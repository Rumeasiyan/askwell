"""Reset: empty every table Askwell's own database holds, audit stores included.

Ticket `M7-DATA-BE-159a`, issue #523. `docs/ux/settings.md` §6 is the surface;
`M7-DATA-FE-160` builds it on top of this.

**Why the audit stores need a path of their own.** `askwell_app` holds no
`UPDATE`, `DELETE` or `TRUNCATE` on `audit_decisions` or `audit_interactions`
(C6, `docs/decisions.md` "the database has three roles"), and holds no
`TRUNCATE` on anything at all. A single `TRUNCATE` naming every table is
therefore refused whole, and a reset built that way clears nothing. The
ordinary tables are emptied here with `DELETE`, which `askwell_app` already
has; the audit tables are emptied by `askwell_reset_audit()`, a `SECURITY
DEFINER` function migration `b5d09e3c71a8` defines, which refuses unless the
newest decisions record is a `reset_requested` written in the *same
transaction*. No other code path writes that kind, so no other code path can
use the function — and the database, not this module, enforces it.

**One transaction.** Request record, deletes, audit truncate and the closing
record commit together or not at all, so a reset that fails partway leaves
everything exactly as it was — nothing half-cleared.

**Recorded before, and still recorded after.** `reset_requested` is written
before anything is removed, because the function will not run otherwise.
It is then destroyed with the rest of the audit table — that is what "reset
deletes the audit stores" means. So `reset_performed`, carrying the same
counts, is appended once the tables are empty: it is the genesis record of
the new decisions chain, and the act of resetting is the one thing that
survives the reset rather than the one thing that vanishes without trace.

**No ingestion refusal, because the table locks make one unnecessary.**
Reset first takes `EXCLUSIVE` on every ordinary table, which waits for any
in-flight worker write to commit and blocks new ones until reset commits;
`askwell_reset_audit()`'s `TRUNCATE` takes `ACCESS EXCLUSIVE` on the audit
tables to the same effect. The locks are not optional: a `DELETE` neither
sees nor waits for a row another transaction has inserted but not committed,
so without them a worker's insert committing mid-reset survives a reset that
reported success. Every later write in `askwell.ingest` is an
`UPDATE ... WHERE id = :id`, which matches zero rows once the row is gone
rather than erroring. A worker that deadlocks against the locks is aborted by
Postgres; if reset is the one aborted, it raises and removes nothing.

**After the commit, what a transaction cannot hold** (`M7-DATA-FE-160`,
issue #683). Trace files, finished export and backup artefacts, and every
sandbox database a dump import created are Askwell's data too, but deleting
a file or dropping a database cannot be rolled back — doing either inside
`perform` would make a reset that fails partway no longer all-or-nothing.
So `register_reset`'s route removes them only once `perform` has committed,
and both reset records name the files that are about to go. A file that
cannot be removed is reported in the response, not hidden. The sandbox is
best-effort, the same as `askwell.worker`'s startup reclaim: an instance that
is down is not a reason to fail a reset of Askwell's own database, and once
`sources` is empty every sandbox database that exists is an orphan the next
worker start reclaims anyway.

**The user's own files are never touched.** Nothing here opens, moves or
deletes anything under a registered root; `roots` is only the list of
folders Askwell may read, and forgetting that list is the whole of what
reset does to them. `ORIGINAL_FILES_STATEMENT` is the one wording every
response carries, so the screen never has to invent it.
"""

import asyncio
import shutil
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from askwell import online, passphrase, sandbox
from askwell.audit import Store, record
from askwell.config import Settings
from askwell.db.engine import session_scope
from askwell.logging import get_logger
from askwell.traces import TraceRing

log = get_logger(__name__)

RESET_REQUESTED = "reset_requested"
RESET_PERFORMED = "reset_performed"

AUDIT_TABLES: tuple[str, ...] = ("audit_decisions", "audit_interactions")

ORIGINAL_FILES_STATEMENT = (
    "Your original files are never touched. Askwell forgets the folders you registered "
    "and everything it learned from them; the files themselves stay exactly where they "
    "are, unchanged."
)

# Every other table in the schema, children before the parents they reference,
# so each `DELETE` runs without leaning on which foreign keys happen to
# cascade. `test_reset.py` asserts this plus `AUDIT_TABLES` is the whole
# schema, so a table added later cannot silently survive a reset.
TABLES: tuple[str, ...] = (
    "reapply_items",
    "reapply_jobs",
    "citations",
    "web_citations",
    "fact_usage",
    "messages",
    "conversations",
    "ingest_jobs",
    "document_pages",
    "chunks",
    "documents",
    "clarifications",
    "memory",
    "schema_notes",
    "sources",
    "roots",
    "settings",
    "export_jobs",
    "backup_jobs",
    "restore_jobs",
    "prune_jobs",
)


async def counts(session: AsyncSession) -> dict[str, int]:
    """Rows per table — what a reset is about to remove."""
    result: dict[str, int] = {}
    for table in (*TABLES, *AUDIT_TABLES):
        result[table] = (await session.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()
    return result


async def perform(session: AsyncSession, *, files: dict[str, int] | None = None) -> dict[str, int]:
    """Empty every table in one transaction, committed by the caller.

    Returns the counts from just before. Raises, and removes nothing, if any
    step is refused. `files` is what the caller will remove once this has
    committed (module docstring) — named in both records, so the new chain's
    genesis says those went too.
    """
    await session.execute(text(f"LOCK TABLE {', '.join(TABLES)} IN EXCLUSIVE MODE"))
    before = await counts(session)
    payload: dict[str, Any] = {"counts": before}
    if files is not None:
        payload["files_to_remove"] = files
    await record(session, Store.DECISIONS, RESET_REQUESTED, payload)

    for table in TABLES:
        await session.execute(text(f"DELETE FROM {table}"))
    await session.execute(text("SELECT askwell_reset_audit()"))

    await record(session, Store.DECISIONS, RESET_PERFORMED, payload)
    log.info("reset_performed", total_rows=sum(before.values()))
    return before


# --- what a transaction cannot hold --------------------------------------


def _artefacts(settings: Settings) -> dict[str, list[Path]]:
    """Trace files, and whatever sits under the export and backup
    directories — finished zips, and a crashed run's leftovers."""

    def _children(directory: Path) -> list[Path]:
        try:
            return sorted(directory.iterdir())
        except OSError:
            return []

    return {
        "traces": TraceRing(settings.trace_dir, 0).files(),
        "exports": _children(settings.export_dir),
        "backups": _children(settings.backup_dir),
    }


def file_counts(settings: Settings) -> dict[str, int]:
    return {kind: len(paths) for kind, paths in _artefacts(settings).items()}


def remove_files(settings: Settings) -> dict[str, Any]:
    """Delete every artefact `_artefacts` names. Returns what was removed and
    anything that could not be, by path — never silently partial."""
    removed: dict[str, int] = {}
    failed: list[str] = []
    for kind, paths in _artefacts(settings).items():
        removed[kind] = 0
        for path in paths:
            try:
                if path.is_dir() and not path.is_symlink():
                    shutil.rmtree(path)
                else:
                    path.unlink(missing_ok=True)
            except OSError as error:
                log.warning("reset_file_not_removed", path=str(path), error=str(error))
                failed.append(str(path))
                continue
            removed[kind] += 1
    return {"removed": removed, "failed": failed}


async def _drop_sandbox_databases(
    factory: async_sessionmaker[AsyncSession], settings: Settings
) -> list[str] | None:
    """Every sandbox database, now that no source claims any. `None` when
    the sandbox instance could not be reached (module docstring)."""
    try:
        async with session_scope(factory) as session:
            dropped = await sandbox.reclaim_orphans(
                session, settings.sandbox_database_url.get_secret_value()
            )
    except Exception as error:  # the sandbox instance may not be up
        log.warning("reset_sandbox_drop_deferred", error=f"{type(error).__name__}: {error}")
        return None
    return list(dropped)


# --- HTTP --------------------------------------------------------------


def register_reset(
    app: FastAPI, settings: Settings, factory: async_sessionmaker[AsyncSession]
) -> None:
    """`GET /reset/preview` names what a reset would destroy and changes
    nothing; `POST /reset` performs it. The confirmation is the surface's."""

    @app.get("/reset/preview")
    async def preview_route() -> JSONResponse:
        async with session_scope(factory) as db:
            before = await counts(db)
        files = await asyncio.to_thread(file_counts, settings)
        return JSONResponse(
            {
                "counts": before,
                "total": sum(before.values()),
                "files": files,
                "original_files_statement": ORIGINAL_FILES_STATEMENT,
            }
        )

    @app.post("/reset")
    async def reset_route() -> JSONResponse:
        files = await asyncio.to_thread(file_counts, settings)
        async with session_scope(factory) as db:
            before = await perform(db, files=files)
        # Committed. Only now what cannot be rolled back (module docstring).
        passphrase.forget_unlocked_key()
        # The conversations are gone, so are their online-AI authorisations
        # (`M8-ONLINE-SEC-169`). Nothing to record — the audit tables were
        # just emptied with them. Credentials are forgotten before Redis is
        # touched, so a grant Redis would not let us close is already unusable.
        try:
            await online.revoke_all(settings)
        except Exception as error:
            log.warning("reset_online_grants_not_closed", error=f"{type(error).__name__}: {error}")
        removal = await asyncio.to_thread(remove_files, settings)
        dropped = await _drop_sandbox_databases(factory, settings)
        return JSONResponse(
            {
                "counts": before,
                "total": sum(before.values()),
                "files_removed": removal["removed"],
                "files_not_removed": removal["failed"],
                "sandbox_databases_dropped": dropped,
                "original_files_statement": ORIGINAL_FILES_STATEMENT,
            }
        )
