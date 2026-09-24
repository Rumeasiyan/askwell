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

**Not here, deliberately:** dropping sandbox databases left by dump imports,
clearing in-process passphrase state, and the preview the settings screen
shows before confirming. Those are the surface's (`M7-DATA-FE-160`).
"""

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from askwell.audit import Store, record
from askwell.db.engine import session_scope
from askwell.logging import get_logger

log = get_logger(__name__)

RESET_REQUESTED = "reset_requested"
RESET_PERFORMED = "reset_performed"

AUDIT_TABLES: tuple[str, ...] = ("audit_decisions", "audit_interactions")

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


async def perform(session: AsyncSession) -> dict[str, int]:
    """Empty every table in one transaction, committed by the caller.

    Returns the counts from just before. Raises, and removes nothing, if any
    step is refused.
    """
    await session.execute(text(f"LOCK TABLE {', '.join(TABLES)} IN EXCLUSIVE MODE"))
    before = await counts(session)
    await record(session, Store.DECISIONS, RESET_REQUESTED, {"counts": before})

    for table in TABLES:
        await session.execute(text(f"DELETE FROM {table}"))
    await session.execute(text("SELECT askwell_reset_audit()"))

    await record(session, Store.DECISIONS, RESET_PERFORMED, {"counts": before})
    log.info("reset_performed", total_rows=sum(before.values()))
    return before


# --- HTTP --------------------------------------------------------------


def register_reset(app: FastAPI, factory: async_sessionmaker[AsyncSession]) -> None:
    """`POST /reset` performs it. The confirmation is the surface's job."""

    @app.post("/reset")
    async def reset_route() -> JSONResponse:
        async with session_scope(factory) as db:
            before = await perform(db)
        return JSONResponse({"counts": before, "total": sum(before.values())})
