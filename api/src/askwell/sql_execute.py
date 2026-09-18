"""Execute a validated, read-only query under a statement timeout. `M4-SQL-DB-107`.

`docs/data-sources.md` §4, layers 1 and 4: the database role itself is
read-only (layer 1 — the sandbox's own `askwell_sandbox_readonly`,
`askwell.sandbox.verify_readonly_role`; a live connection's own stored
credential, already refused at the wizard if it can write, `M4-CONN-SEC-097`)
and every session carries a 30-second `statement_timeout` (layer 4),
independently of whatever `sqlglot` validation (C2, layer 2, `M4-SQL-VAL-104`)
does to the query text before it ever reaches here. Two independent layers,
by design (the ticket's own business case) — a parser bug is not the only
thing standing between a generated query and the user's data.

**What this module does not do.** It does not validate SQL (`M4-SQL-VAL-104`),
inject a `LIMIT` (`M4-SQL-VAL-105`), dry-run with `EXPLAIN` (`M4-SQL-VAL-106`),
or format a result for display (`M4-SQL-RESULT-FE-109`/`110`) — those are
later, dependent tickets. This module executes a query string it is handed,
as a role that cannot write, and turns a Postgres/MySQL/MariaDB/SQL Server
cancellation into one named, recorded failure rather than a driver traceback.
"""

import asyncio
import contextlib
import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from askwell import audit
from askwell.audit import Store
from askwell.config import Settings
from askwell.logging import get_logger
from askwell.sandbox import readonly_url

log = get_logger(__name__)

# A local counter nothing ever transmits (C1) — the same shape as
# `connections.WRITE_PROBE_REFUSED_COUNTER_KEY`, for the same reason: it is
# best-effort and must never turn a real timeout into an exception the caller
# has to recover from on top of the timeout itself.
STATEMENT_TIMEOUT_COUNTER_KEY = "askwell:sql:statement_timeouts"

SQL_STATEMENT_TIMEOUT = "sql_statement_timeout"


@dataclass(frozen=True)
class QueryResult:
    """What executing a query, successfully, produced."""

    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]
    duration_seconds: float


class StatementTimedOut(RuntimeError):
    """The query ran longer than `Settings.sql_statement_timeout_seconds` and
    Postgres/MySQL/MariaDB/SQL Server cancelled it.

    Carries the query and how long it ran so the caller can show both,
    `docs/states-and-edge-cases.md` §4's own requirement — a number you
    cannot trace, or a failure you cannot see the cause of, is not worth much
    (the same reasoning `data-sources.md` §4 states for the shown SQL itself).
    """

    def __init__(self, query: str, timeout_seconds: float, duration_seconds: float):
        self.query = query
        self.timeout_seconds = timeout_seconds
        self.duration_seconds = duration_seconds
        super().__init__(
            f"This query took longer than {timeout_seconds:g}s and was stopped. Try "
            f"narrowing it — a smaller date range or an added filter usually helps. "
            f"The timeout is adjustable in settings "
            f"(ASKWELL_SQL_STATEMENT_TIMEOUT_SECONDS) if this legitimately needs more "
            f"time.\nQuery: {query}"
        )


def _execute_postgresql_blocking(dsn: str, query: str, timeout_seconds: float) -> QueryResult:
    import psycopg

    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.read_only = True
        with conn.cursor() as cur:
            # A literal, not a bound parameter: `SET` does not accept one, and
            # `timeout_seconds` is `Settings`, never user input.
            cur.execute(f"SET statement_timeout = {int(timeout_seconds * 1000)}")
            started = time.monotonic()
            try:
                cur.execute(query)
            except psycopg.errors.QueryCanceled:
                raise StatementTimedOut(
                    query, timeout_seconds, time.monotonic() - started
                ) from None
            rows = tuple(tuple(row) for row in cur.fetchall()) if cur.description else ()
            columns = tuple(d.name for d in cur.description) if cur.description else ()
    return QueryResult(columns, rows, time.monotonic() - started)


def _execute_mysql_blocking(
    engine: str,
    host: str,
    port: int,
    database: str,
    user: str,
    password: str,
    query: str,
    timeout_seconds: float,
) -> QueryResult:
    import pymysql
    from pymysql.constants import ER

    conn = pymysql.connect(
        host=host,
        port=port,
        database=database,
        user=user,
        password=password,
        connect_timeout=max(1, int(timeout_seconds)),
    )
    try:
        with conn.cursor() as cur:
            # MariaDB's session variable takes seconds (a float); MySQL's
            # takes milliseconds and, unlike MariaDB's, only ever bounds a
            # `SELECT` — the one statement shape a read-only role can run
            # anyway (`sqlglot` validation, M4-SQL-VAL-104, guarantees that
            # upstream of this module).
            if engine == "mariadb":
                cur.execute(f"SET SESSION max_statement_time = {timeout_seconds:g}")
            else:
                cur.execute(f"SET SESSION MAX_EXECUTION_TIME = {int(timeout_seconds * 1000)}")
            started = time.monotonic()
            try:
                cur.execute(query)
            except pymysql.err.OperationalError as error:
                code = error.args[0] if error.args else None
                if code in (ER.QUERY_TIMEOUT, ER.STATEMENT_TIMEOUT):
                    raise StatementTimedOut(
                        query, timeout_seconds, time.monotonic() - started
                    ) from None
                raise
            rows = tuple(tuple(row) for row in cur.fetchall()) if cur.description else ()
            columns = tuple(d[0] for d in cur.description) if cur.description else ()
    finally:
        conn.close()
    return QueryResult(columns, rows, time.monotonic() - started)


def _execute_sqlserver_blocking(
    host: str,
    port: int,
    database: str,
    user: str,
    password: str,
    query: str,
    timeout_seconds: float,
) -> QueryResult:
    import pytds

    # SQL Server has no session-level `SET` for an arbitrary statement's
    # timeout the way Postgres and MySQL/MariaDB do — `timeout` here is
    # `python-tds`'s own per-query timeout, applied to every statement this
    # connection runs, which is the closest equivalent "per session" has for
    # this engine.
    conn = pytds.connect(
        server=host,
        port=port,
        database=database,
        user=user,
        password=password,
        login_timeout=max(1, int(timeout_seconds)),
        timeout=timeout_seconds,
    )
    try:
        with conn.cursor() as cur:
            started = time.monotonic()
            try:
                cur.execute(query)
            except pytds.TimeoutError:
                raise StatementTimedOut(
                    query, timeout_seconds, time.monotonic() - started
                ) from None
            rows = tuple(tuple(row) for row in cur.fetchall()) if cur.description else ()
            columns = tuple(d[0] for d in cur.description) if cur.description else ()
    finally:
        conn.close()
    return QueryResult(columns, rows, time.monotonic() - started)


def _postgresql_dsn(host: str, port: int, database: str, user: str, password: str) -> str:
    from urllib.parse import quote

    user_part = quote(user, safe="")
    password_part = quote(password, safe="")
    return f"postgresql://{user_part}:{password_part}@{host}:{port}/{database}"


async def _record_timeout(
    session: AsyncSession,
    settings: Settings,
    *,
    source_kind: str,
    query: str,
    failure: "StatementTimedOut",
) -> None:
    """A decisions record naming the query and how long it ran, and a local
    counter nothing ever transmits (C1) — mirroring
    `connections.record_write_probe_refusal`, for the same reason: a Redis
    hiccup must not turn a timeout into a second failure on top of the one
    that already happened and already committed as a decisions row.
    """
    # Integers, in a fixed unit, never the raw floats: `audit.canonical_payload`
    # refuses a float outright (`askwell.audit`'s own docstring) — Postgres's
    # `jsonb` does not preserve a float's representation round-trip-identically,
    # and a hash computed before that round trip would disagree with one
    # recomputed after it, which verification would read as tampering that
    # never happened.
    await audit.record(
        session,
        Store.DECISIONS,
        SQL_STATEMENT_TIMEOUT,
        {
            "source_kind": source_kind,
            "query": query,
            "timeout_seconds": int(failure.timeout_seconds),
            "duration_ms": round(failure.duration_seconds * 1000),
        },
    )
    log.warning(
        "sql_statement_timeout",
        source_kind=source_kind,
        timeout_seconds=failure.timeout_seconds,
        duration_seconds=failure.duration_seconds,
    )

    import redis.asyncio as redis

    client = redis.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        socket_connect_timeout=1.0,
        socket_timeout=1.0,
    )
    try:
        await client.incr(STATEMENT_TIMEOUT_COUNTER_KEY)
    except Exception as error:
        log.warning("sql_statement_timeout_count_failed", error=f"{type(error).__name__}: {error}")
    finally:
        with contextlib.suppress(Exception):
            await client.aclose()


async def execute_sandbox_query(
    session: AsyncSession, settings: Settings, *, database: str, query: str
) -> QueryResult:
    """Run `query` against a sandbox database as `askwell_sandbox_readonly` —
    never the owner (C3, `askwell.sandbox.OWNER_ROLE`) — with the configured
    statement timeout applied for this session alone.
    """
    admin_url = settings.sandbox_database_url.get_secret_value()
    password = settings.sandbox_readonly_password.get_secret_value()
    dsn = readonly_url(admin_url, database, password)
    timeout_seconds = float(settings.sql_statement_timeout_seconds)
    try:
        return await asyncio.to_thread(_execute_postgresql_blocking, dsn, query, timeout_seconds)
    except StatementTimedOut as failure:
        await _record_timeout(
            session, settings, source_kind="sandbox", query=query, failure=failure
        )
        raise


async def execute_connection_query(
    session: AsyncSession,
    settings: Settings,
    *,
    engine: str,
    host: str,
    port: int,
    database: str,
    user: str,
    password: str,
    query: str,
) -> QueryResult:
    """Run `query` against a live connection, as the credential
    `M4-CONN-SEC-097`'s write-permission probe already verified is read-only
    — there is no second, more-privileged credential to reach for here — with
    the configured statement timeout applied for this session alone.
    """
    timeout_seconds = float(settings.sql_statement_timeout_seconds)
    try:
        if engine == "postgresql":
            dsn = _postgresql_dsn(host, port, database, user, password)
            result = await asyncio.to_thread(
                _execute_postgresql_blocking, dsn, query, timeout_seconds
            )
        elif engine in ("mysql", "mariadb"):
            result = await asyncio.to_thread(
                _execute_mysql_blocking,
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
                _execute_sqlserver_blocking,
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
    except StatementTimedOut as failure:
        await _record_timeout(session, settings, source_kind=engine, query=query, failure=failure)
        raise
    return result
