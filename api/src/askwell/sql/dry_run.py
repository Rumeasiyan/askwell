"""Plan a validated, limited query without executing it. `M4-SQL-VAL-106`.

The last safety layer before a generated query reaches a real database
(`docs/data-sources.md` §4's own query path: validation → limit injection →
`EXPLAIN` dry run → execution). A query that parses and passes `sqlglot`
(C2, `M4-SQL-VAL-104`) can still be broken in a way only the target
database's own planner can catch — a column dropped last week, a table
renamed, a type mismatch — and that check must happen without running the
query, against a database somebody else depends on
(`docs/build-plan.md`'s own user story: "someone whose database is slow and
busy").

**Plan-only, never execute.** Postgres and MySQL/MariaDB `EXPLAIN` a
statement without running it — the planner builds a plan, never opens a row.
SQL Server has no bare `EXPLAIN`; `SET SHOWPLAN_ALL ON` puts the *session*
into plan-only mode so the next statement returns its plan instead of
running, which is why turning that mode on is its own step, checked apart
from the query itself below.

**Planning failure is recorded distinctly from a validation rejection** —
the ticket's own Acceptance Criteria. `validate.py` answers "is this
syntactically a safe read"; this module answers "does the target database's
own planner accept it against its actual, current schema" — two different
questions, so `SQL_DRY_RUN` is its own `audit_interactions` kind, never
folded into `validate.SQL_QUERY`.

**Connection failure during a dry run is recorded as a planning failure,
not classified into `askwell.sql_execute`'s `ConnectionUnreachable`/
`CredentialsRejected`.** Issue #382: an earlier version of this module
re-raised only `OSError` around the connect call, so every real driver's own
operational-error class (`psycopg.OperationalError`,
`pymysql.err.OperationalError`, `pytds.tds_base.LoginError`/
`OperationalError`) propagated unhandled instead of producing a
`DryRunResult`. A `.FAILED` dry run with a raw connect-failure detail is the
honest, if less polished, outcome — duplicating `sql_execute`'s full
three-way classification here would give this module a second job
(distinguishing *why* a connection failed) it does not need: a dry run that
cannot even connect is never executed either way, and `execute_*_query`
still runs its own classification independently once this step has passed.

**A database that cannot plan at all is `UNSUPPORTED`, not `PLANNING_FAILED`**
— the ticket's own edge case: "a database that does not support plan-only
execution — the step is skipped with that recorded, rather than silently
treated as passed." For SQL Server this is the one place that distinction is
real: turning `SHOWPLAN_ALL` on can itself be refused (a restricted edition,
a permission the credential lacks) before the query is even considered, and
that is a capability problem, not a fact about this particular query.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncSession

from askwell import audit
from askwell.audit import Store
from askwell.config import Settings
from askwell.connections import Engine
from askwell.logging import get_logger
from askwell.sandbox import readonly_url

log = get_logger(__name__)

# `M4-SQL-OBS-108`'s own shape, applied here: a planning failure is a
# per-question fact (`docs/audit-log.md` §7), not a Decisions one.
SQL_DRY_RUN = "sql_dry_run"


class DryRunReason(StrEnum):
    """Why a dry run did not pass. `None` only when `passed` is `True`."""

    PLANNING_FAILED = "planning_failed"
    TIMEOUT = "timeout"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class DryRunResult:
    """What dry-running one already-validated, already-limited query
    produced. `reason`/`detail` are `None` only when `passed` is `True` —
    the same shape `askwell.sql.validate.ValidationResult` already
    established, so a caller renders `detail` the same way regardless of
    which stage rejected the query.
    """

    passed: bool
    reason: DryRunReason | None
    detail: str | None


def _ok() -> DryRunResult:
    return DryRunResult(passed=True, reason=None, detail=None)


def _fail(reason: DryRunReason, detail: str) -> DryRunResult:
    return DryRunResult(passed=False, reason=reason, detail=detail)


def _dry_run_postgresql_blocking(dsn: str, query: str, timeout_seconds: float) -> DryRunResult:
    import psycopg

    try:
        conn = psycopg.connect(dsn, autocommit=True)
    except (OSError, psycopg.OperationalError) as error:
        return _fail(DryRunReason.PLANNING_FAILED, f"Could not connect to plan: {error}")

    with conn:
        conn.read_only = True
        with conn.cursor() as cur:
            # A literal, not a bound parameter: `SET` does not accept one,
            # and `timeout_seconds` is `Settings`, never user input — the
            # same reasoning `sql_execute._execute_postgresql_blocking`
            # already carries for its own identical line.
            cur.execute(f"SET statement_timeout = {int(timeout_seconds * 1000)}")
            try:
                cur.execute(f"EXPLAIN {query}")
            except psycopg.errors.QueryCanceled:
                return _fail(DryRunReason.TIMEOUT, "Planning this statement took too long.")
            except psycopg.Error as error:
                return _fail(DryRunReason.PLANNING_FAILED, str(error))
    return _ok()


def _dry_run_mysql_blocking(
    engine: str,
    host: str,
    port: int,
    database: str,
    user: str,
    password: str,
    query: str,
    timeout_seconds: float,
) -> DryRunResult:
    import pymysql
    from pymysql.constants import ER

    try:
        conn = pymysql.connect(
            host=host,
            port=port,
            database=database,
            user=user,
            password=password,
            connect_timeout=max(1, int(timeout_seconds)),
        )
    except (OSError, pymysql.err.OperationalError) as error:
        return _fail(DryRunReason.PLANNING_FAILED, f"Could not connect to plan: {error}")

    try:
        with conn.cursor() as cur:
            if engine == "mariadb":
                cur.execute(f"SET SESSION max_statement_time = {timeout_seconds:g}")
            else:
                cur.execute(f"SET SESSION MAX_EXECUTION_TIME = {int(timeout_seconds * 1000)}")
            try:
                cur.execute(f"EXPLAIN {query}")
            except pymysql.err.OperationalError as error:
                code = error.args[0] if error.args else None
                if code in (ER.QUERY_TIMEOUT, ER.STATEMENT_TIMEOUT):
                    return _fail(DryRunReason.TIMEOUT, "Planning this statement took too long.")
                return _fail(DryRunReason.PLANNING_FAILED, str(error))
            except pymysql.err.ProgrammingError as error:
                return _fail(DryRunReason.PLANNING_FAILED, str(error))
    finally:
        conn.close()
    return _ok()


def _dry_run_sqlserver_blocking(
    host: str,
    port: int,
    database: str,
    user: str,
    password: str,
    query: str,
    timeout_seconds: float,
) -> DryRunResult:
    import pytds
    from pytds.tds_base import LoginError, OperationalError

    try:
        conn = pytds.connect(
            server=host,
            port=port,
            database=database,
            user=user,
            password=password,
            login_timeout=max(1, int(timeout_seconds)),
            timeout=timeout_seconds,
        )
    except (OSError, LoginError, OperationalError) as error:
        return _fail(DryRunReason.PLANNING_FAILED, f"Could not connect to plan: {error}")

    try:
        with conn.cursor() as cur:
            try:
                # Must be the only statement in its own batch — a separate
                # `cursor.execute` call, never concatenated with the query
                # itself. The session-level toggle is the capability check;
                # the query that follows is the query check.
                cur.execute("SET SHOWPLAN_ALL ON")
            except pytds.Error as error:
                return _fail(DryRunReason.UNSUPPORTED, str(error))
            try:
                try:
                    cur.execute(query)
                except pytds.TimeoutError:
                    return _fail(DryRunReason.TIMEOUT, "Planning this statement took too long.")
                except pytds.Error as error:
                    return _fail(DryRunReason.PLANNING_FAILED, str(error))
            finally:
                import contextlib

                with contextlib.suppress(pytds.Error):
                    cur.execute("SET SHOWPLAN_ALL OFF")
    finally:
        conn.close()
    return _ok()


async def _record_failure(
    session: AsyncSession,
    *,
    engine: Engine,
    source_id: uuid.UUID | None,
    query: str,
    result: DryRunResult,
) -> None:
    assert result.reason is not None
    await audit.record(
        session,
        Store.INTERACTIONS,
        SQL_DRY_RUN,
        {
            "engine": engine,
            "source_id": str(source_id) if source_id is not None else None,
            "query": query,
            "reason": result.reason.value,
            "detail": result.detail,
        },
    )
    log.warning("sql_dry_run_failed", engine=engine, reason=result.reason.value)


async def dry_run_sandbox_query(
    session: AsyncSession, settings: Settings, *, database: str, query: str
) -> DryRunResult:
    """Plan `query` against a sandbox database as `askwell_sandbox_readonly`
    — never the owner (C3) — the same role and connection shape
    `askwell.sql_execute.execute_sandbox_query` uses to actually run it.
    """
    admin_url = settings.sandbox_database_url.get_secret_value()
    password = settings.sandbox_readonly_password.get_secret_value()
    dsn = readonly_url(admin_url, database, password)
    timeout_seconds = float(settings.sql_statement_timeout_seconds)
    result = await asyncio.to_thread(_dry_run_postgresql_blocking, dsn, query, timeout_seconds)
    if not result.passed:
        await _record_failure(
            session, engine="postgresql", source_id=None, query=query, result=result
        )
    return result


def _connection_dsn(host: str, port: int, database: str, user: str, password: str) -> str:
    from urllib.parse import quote

    user_part = quote(user, safe="")
    password_part = quote(password, safe="")
    return f"postgresql://{user_part}:{password_part}@{host}:{port}/{database}"


async def dry_run_connection_query(
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
) -> DryRunResult:
    """Plan `query` against a live connection, as the same read-only
    credential `askwell.sql_execute.execute_connection_query` uses to
    actually run it — the ticket's own Validation Rule, "planning runs as
    the read-only role, like execution."
    """
    timeout_seconds = float(settings.sql_statement_timeout_seconds)
    if engine == "postgresql":
        dsn = _connection_dsn(host, port, database, user, password)
        result = await asyncio.to_thread(_dry_run_postgresql_blocking, dsn, query, timeout_seconds)
    elif engine in ("mysql", "mariadb"):
        result = await asyncio.to_thread(
            _dry_run_mysql_blocking,
            engine,
            host,
            port,
            database,
            user,
            password,
            query,
            timeout_seconds,
        )
    elif engine == "sqlserver":
        result = await asyncio.to_thread(
            _dry_run_sqlserver_blocking,
            host,
            port,
            database,
            user,
            password,
            query,
            timeout_seconds,
        )
    else:
        raise ValueError(f"Askwell does not support {engine!r}.")

    if not result.passed:
        await _record_failure(
            session, engine=engine, source_id=source_id, query=query, result=result
        )
    return result
