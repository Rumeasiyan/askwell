"""Run a validated, limited, dry-run-passed query and record what it
returned. `M4-SQL-BE-108a`.

The last step of `docs/data-sources.md` §4's own query path: generation
(`M4-SQL-BE-103`) → validation (C2, `M4-SQL-VAL-104`) → limit injection
(`-105`) → dry run (`-106`) → this. `askwell.sql_execute` already runs a
query as the read-only role under the statement timeout (`M4-SQL-DB-107`) —
this module does not re-implement that, it wraps it: takes the identical
already-checked query text every stage above has now looked at, calls
straight through to `askwell.sql_execute.execute_sandbox_query`/
`execute_connection_query`, and adds the two things a caller answering a
question actually needs that the execution layer itself has no reason to
know — whether the row limit `-105` injected actually bit (`askwell.sql.
limit.result_was_truncated`, the same function the disclosed `LIMIT` clause
already used to decide that) and one `audit_interactions` record naming the
row count and duration for *this* stage, distinct from `sql_query`
(validation) and `sql_dry_run` (planning) the same way those two are already
distinct from each other.

**Nothing here parses or rewrites SQL.** That is C2's enforcement point and
it stays in `askwell.sql.validate` alone — this module's only job is running
a string it is handed, exactly as `askwell.sql_execute`'s own module
docstring already says of itself.

**A failed execution records nothing here.** `askwell.sql_execute` already
records a timeout to `audit_decisions` and a connection failure through
`connections._record_health_transition`; duplicating that under a third
name would just be a second audit trail for the same event. This module's
own `sql_execute` interaction record is written only for a query that
actually returned a result — the caller decides what a failure means for
the turn (`askwell.ask._run_sql_turn`), the same "only the interesting
outcome is recorded" split `askwell.sql.limit.inject_limit` already draws
between an injected limit and one left alone.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from askwell import audit, sql_execute
from askwell.audit import Store
from askwell.config import Settings
from askwell.connections import Engine
from askwell.logging import get_logger
from askwell.sql.limit import result_was_truncated

log = get_logger(__name__)

# `Store.INTERACTIONS`, not `Store.DECISIONS`: a per-question fact, the same
# home `validate.SQL_QUERY` and `dry_run.SQL_DRY_RUN` already use for the
# stages before this one.
SQL_EXECUTE = "sql_execute"


@dataclass(frozen=True, slots=True)
class ExecuteResult:
    """What running one already-checked query, successfully, produced."""

    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]
    row_count: int
    truncated: bool
    duration_ms: int


async def _record(
    session: AsyncSession,
    *,
    engine: str,
    source_id: uuid.UUID | None,
    query: str,
    result: ExecuteResult,
) -> None:
    await audit.record(
        session,
        Store.INTERACTIONS,
        SQL_EXECUTE,
        {
            "engine": engine,
            "source_id": str(source_id) if source_id is not None else None,
            "query": query,
            "rows": result.row_count,
            "truncated": result.truncated,
            "duration_ms": result.duration_ms,
        },
    )
    log.info("sql_executed", engine=engine, rows=result.row_count, truncated=result.truncated)


def _to_result(raw: sql_execute.QueryResult, *, row_limit: int | None) -> ExecuteResult:
    row_count = len(raw.rows)
    return ExecuteResult(
        columns=raw.columns,
        rows=raw.rows,
        row_count=row_count,
        truncated=result_was_truncated(row_count, row_limit),
        duration_ms=round(raw.duration_seconds * 1000),
    )


async def execute_checked_sandbox_query(
    session: AsyncSession, settings: Settings, *, database: str, query: str, row_limit: int | None
) -> ExecuteResult:
    """Run `query` — already validated, limited and dry-run-checked — against
    a sandbox database as `askwell_sandbox_readonly` (C3), the same call
    `askwell.sql.dry_run.dry_run_sandbox_query` made to plan it.
    """
    raw = await sql_execute.execute_sandbox_query(session, settings, database=database, query=query)
    result = _to_result(raw, row_limit=row_limit)
    await _record(session, engine="postgresql", source_id=None, query=query, result=result)
    return result


async def execute_checked_connection_query(
    session: AsyncSession,
    settings: Settings,
    *,
    source_id: uuid.UUID,
    engine: Engine,
    host: str,
    port: int,
    database: str,
    user: str,
    password: str,
    query: str,
    row_limit: int | None,
) -> ExecuteResult:
    """Run `query` — already validated, limited and dry-run-checked — against
    a live connection, as the same read-only credential `askwell.sql.
    dry_run.dry_run_connection_query` used to plan it.

    Raises whichever of `askwell.sql_execute`'s three query-time failures
    (`ConnectionUnreachable`, `CredentialsRejected`, `QueryRejected`) or
    `StatementTimedOut` occurred — each already recorded by that module
    (a health transition, or a decisions row for a timeout) before it
    reaches here, so this module adds nothing on that path and simply lets
    the exception propagate to the caller.
    """
    raw = await sql_execute.execute_connection_query(
        session,
        settings,
        source_id=source_id,
        engine=engine,
        host=host,
        port=port,
        database=database,
        user=user,
        password=password,
        query=query,
    )
    result = _to_result(raw, row_limit=row_limit)
    await _record(session, engine=engine, source_id=source_id, query=query, result=result)
    return result
