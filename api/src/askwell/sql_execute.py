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

**Three distinguishable query-time failures on a live connection,
`M4-CONN-BE-099`.** A customer's database goes down independently of
Askwell (`docs/states-and-edge-cases.md` §4), and a generic "something went
wrong" sends the person to reinstall Askwell instead of restarting their
database. `execute_connection_query` classifies every driver failure into
one of `ConnectionUnreachable` (the database did not answer at all —
distinct from a zero-row `QueryResult`, which means it answered),
`CredentialsRejected` (it answered but the stored credential was refused —
distinct from a query being rejected, since re-entering a password fixes
this and nothing else) or `QueryRejected` (it accepted the connection but
refused this query — a permissions problem, the ticket's own named edge
case). Every one of these also runs `connections._record_health_transition`
so the library's connection-dead state (`docs/ux/library.md` §5) updates
immediately, without waiting for the next periodic health check.
"""

import asyncio
import contextlib
import time
import uuid
from dataclasses import dataclass
from typing import Any, NoReturn

from sqlalchemy.ext.asyncio import AsyncSession

from askwell import audit, connections, redis_client
from askwell.audit import Store
from askwell.config import Settings
from askwell.logging import get_logger
from askwell.sandbox import readonly_url

log = get_logger(__name__)

UNREACHABLE_MESSAGE = (
    "The database is unreachable. It may be down, or the network between here and it may "
    "be down. This is not the same as a query returning no rows — Askwell could not reach "
    "the database at all."
)

CREDENTIALS_REJECTED_MESSAGE = (
    "The database refused these credentials. They may have been changed or revoked since "
    "this connection was set up — re-enter them to reconnect."
)


def _query_rejected_message(detail: str) -> str:
    return (
        "The database accepted the connection but refused this query. This is a "
        f"permissions problem, not a connectivity one: {detail.strip()}."
    )


class ConnectionUnreachable(RuntimeError):
    """The database itself did not answer — a dead host, a refused socket, a
    timeout, or the network being blocked. Distinct from `QueryResult` with
    zero rows (the database answered) and from `QueryRejected` (it answered
    but declined this specific query)."""

    def __init__(self, reason_code: str | None):
        self.reason_code = reason_code
        super().__init__(UNREACHABLE_MESSAGE)


class CredentialsRejected(RuntimeError):
    """The database answered but rejected the stored credential. The fix is
    re-entering the password, never "wait and retry" — the edge case this
    ticket names directly: "a connection whose credentials were revoked"."""

    def __init__(self) -> None:
        super().__init__(CREDENTIALS_REJECTED_MESSAGE)


class QueryRejected(RuntimeError):
    """The connection is live — the credential was accepted — but this
    specific query was refused, most often a revoked or never-granted
    privilege on the object it reads. The ticket's own edge case: "a database
    that accepts connections but refuses queries — reported as a permissions
    problem"."""

    def __init__(self, detail: str) -> None:
        super().__init__(_query_rejected_message(detail))


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


def _raise_from_os_error(error: OSError) -> NoReturn:
    """A raw socket failure during connect, for the same reasons
    `connections._classify_network_error` names four of them — but this is a
    query-time connection, not the wizard's, so the outcome collapses to the
    one distinction the AC asks for: unreachable, not which flavour."""
    from askwell.connections import _classify_network_error

    outcome = _classify_network_error(error)
    raise ConnectionUnreachable(outcome.reason_code) from None


def _execute_connection_postgresql_blocking(
    dsn: str, query: str, timeout_seconds: float
) -> QueryResult:
    import psycopg

    from askwell.connections import _classify_postgresql_message

    try:
        conn = psycopg.connect(dsn, autocommit=True)
    except psycopg.OperationalError as error:
        outcome = _classify_postgresql_message(str(error))
        if outcome.reason_code == "auth_failed":
            raise CredentialsRejected() from None
        raise ConnectionUnreachable(outcome.reason_code) from None
    except OSError as error:
        _raise_from_os_error(error)

    with conn:
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
            except psycopg.Error as error:
                # `docs/states-and-edge-cases.md` §4's own edge case: "a
                # database that accepts connections but refuses queries" —
                # reached the database, but this query specifically was
                # refused, most often `InsufficientPrivilege` on an object a
                # since-revoked grant used to cover.
                raise QueryRejected(str(error)) from None
            rows = tuple(tuple(row) for row in cur.fetchall()) if cur.description else ()
            columns = tuple(d.name for d in cur.description) if cur.description else ()
    return QueryResult(columns, rows, time.monotonic() - started)


def _execute_connection_mysql_blocking(
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
    from pymysql.constants import CR, ER

    try:
        conn = pymysql.connect(
            host=host,
            port=port,
            database=database,
            user=user,
            password=password,
            connect_timeout=max(1, int(timeout_seconds)),
        )
    except OSError as error:
        _raise_from_os_error(error)
    except pymysql.err.OperationalError as error:
        code = error.args[0] if error.args else None
        if code in (ER.ACCESS_DENIED_ERROR, ER.DBACCESS_DENIED_ERROR):
            raise CredentialsRejected() from None
        if code == CR.CR_UNKNOWN_HOST:
            raise ConnectionUnreachable("host_unresolved") from None
        raise ConnectionUnreachable("connection_refused") from None

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
                raise QueryRejected(str(error)) from None
            except pymysql.err.ProgrammingError as error:
                raise QueryRejected(str(error)) from None
            rows = tuple(tuple(row) for row in cur.fetchall()) if cur.description else ()
            columns = tuple(d[0] for d in cur.description) if cur.description else ()
    finally:
        conn.close()
    return QueryResult(columns, rows, time.monotonic() - started)


def _execute_connection_sqlserver_blocking(
    host: str,
    port: int,
    database: str,
    user: str,
    password: str,
    query: str,
    timeout_seconds: float,
) -> QueryResult:
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
    except OSError as error:
        _raise_from_os_error(error)
    except LoginError:
        raise CredentialsRejected() from None
    except OperationalError:
        raise ConnectionUnreachable(None) from None

    try:
        with conn.cursor() as cur:
            started = time.monotonic()
            try:
                cur.execute(query)
            except pytds.TimeoutError:
                raise StatementTimedOut(
                    query, timeout_seconds, time.monotonic() - started
                ) from None
            except pytds.Error as error:
                raise QueryRejected(str(error)) from None
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

    client = redis_client.connect(settings, timeout=1.0)
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
    source_id: uuid.UUID,
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

    `source_id` names the `sources` row this connection is, and every
    outcome — success or one of the three distinguishable failures below —
    runs through `connections._record_health_transition`, `M4-CONN-BE-099`.
    Query-time is a health signal too: without this, "the database is
    unreachable" here and "needs attention" in the library could disagree
    for up to `connection_health_check_seconds` after this call already knew
    better.
    """
    timeout_seconds = float(settings.sql_statement_timeout_seconds)
    try:
        if engine == "postgresql":
            dsn = _postgresql_dsn(host, port, database, user, password)
            result = await asyncio.to_thread(
                _execute_connection_postgresql_blocking, dsn, query, timeout_seconds
            )
        elif engine in ("mysql", "mariadb"):
            result = await asyncio.to_thread(
                _execute_connection_mysql_blocking,
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
                _execute_connection_sqlserver_blocking,
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
    except ConnectionUnreachable as failure:
        await connections._record_health_transition(
            session, source_id, ok=False, message=str(failure), reason_code=failure.reason_code
        )
        raise
    except CredentialsRejected as failure:
        await connections._record_health_transition(
            session, source_id, ok=False, message=str(failure), reason_code="auth_failed"
        )
        raise
    except QueryRejected as failure:
        await connections._record_health_transition(
            session, source_id, ok=False, message=str(failure), reason_code="permission_denied"
        )
        raise
    await connections._record_health_transition(
        session, source_id, ok=True, message="Connected.", reason_code=None
    )
    return result
