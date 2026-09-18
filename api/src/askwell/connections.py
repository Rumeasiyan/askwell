"""Connect Askwell to a database the user already runs. `M4-CONN-FE-096`.

`docs/data-sources.md` §4: host, port, database, user, password, then connect,
probe for write access, introspect the schema, raise clarifications for
unguessable columns. This module builds the first two of those four steps —
connect and a minimal read check — and the table-name inventory that lets a
successful connection say something concrete about what it found. The write
probe (`M4-CONN-SEC-097`) and credential encryption (`M4-CONN-SEC-098`) are
this ticket's own named "Out of Scope"; full schema introspection — types,
keys, relationships — is `M4-SCHEMA-ING-100`, the same split `dump_import.py`
already draws for a loaded dump.

**Four distinguishable failures, not three.** `docs/data-sources.md` §4's
edge cases name a host that does not resolve, a host that refuses, wrong
credentials, and a network the egress proxy blocks — because they are four
different fixes: a typo, a database that is not running, a wrong password,
and a machine the user cannot do anything about from this wizard at all. A
fifth, "connects but cannot read", is its own case because the corrective
action (grant a privilege) is different again.

**Every one of these outcomes is checked against the driver's own error, not
guessed from a support matrix.** `psycopg` (PostgreSQL) reports failures as
message text from libpq, which this module pattern-matches; `pymysql`
(MySQL/MariaDB) and `python-tds` (SQL Server) are pure-Python and let the
underlying `socket` exception — `socket.gaierror`, `ConnectionRefusedError`,
`OSError` with `ENETUNREACH` — through unwrapped, which this module classifies
directly by type and `errno`.

**Read this before assuming a live connection actually works today.**
`docs/architecture.md` §5.1: every container except the egress proxy sits on
a Compose network declared `internal`, which has no route off the machine at
all — not "blocked by policy", genuinely absent. The proxy itself refuses
everything unconditionally; there is no mechanism, anywhere in this codebase,
that permits a specific outbound destination. A live database connection
needs exactly that — a per-source, user-authorised exception, the third one
this architecture has ever needed after online AI and web search — and
building it is a change to C1's sole enforcement point, not a line in a
wizard. It is out of scope here on purpose (`docs/decisions.md`, this
ticket's date) and is filed as its own issue rather than built informally
under a `frontend`-labelled ticket. Until it lands, `probe_connection` below
is honest about what actually happens: any external host reached by name
fails DNS resolution inside the `internal` network (indistinguishable from a
genuine typo, which is `host_unresolved`), and any external host reached by a
literal IP address fails at the socket with `ENETUNREACH` — which this module
*can* and does classify as `network_blocked` distinctly, because that signal
is real regardless of whether the missing piece is a permit mechanism or a
bad route.
"""

import asyncio
import errno
import socket
import uuid
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from askwell import audit
from askwell.audit import Store
from askwell.logging import get_logger

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from askwell.config import Settings

log = get_logger(__name__)

Engine = Literal["postgresql", "mysql", "mariadb", "sqlserver"]
ENGINES: tuple[Engine, ...] = ("postgresql", "mysql", "mariadb", "sqlserver")

ENGINE_LABELS: dict[str, str] = {
    "postgresql": "PostgreSQL",
    "mysql": "MySQL",
    "mariadb": "MariaDB",
    "sqlserver": "SQL Server",
}

# Decisions record (AGENTS.md §8, `docs/audit-log.md` §2). Never the
# credential — `docs/decisions.md`'s own rule for this ticket. No
# `connection_reconfigured` kind yet: nothing in this ticket's scope edits an
# existing connection, only creates one.
CONNECTION_ADDED = "connection_added"

ReasonCode = Literal[
    "unsupported_engine",
    "invalid_host",
    "invalid_port",
    "invalid_database",
    "invalid_user",
    "host_unresolved",
    "connection_refused",
    "network_blocked",
    "timeout",
    "auth_failed",
    "permission_denied",
    "unknown",
]

NETWORK_BLOCKED_MESSAGE = (
    "Askwell's network policy blocked this connection. Local mode has no "
    "outbound route to any destination by default (C1) — a live database "
    "needs its own, explicitly permitted route, which does not exist yet in "
    "this build. This is not a wrong host or a wrong password; nothing you "
    "change here will fix it."
)


@dataclass(frozen=True, slots=True)
class FieldError:
    """A reason a connection was never attempted. `validate_fields`."""

    field: str
    reason_code: ReasonCode
    message: str


@dataclass(frozen=True, slots=True)
class ConnectOutcome:
    """What came of attempting to reach a database. `probe_connection`."""

    ok: bool
    reason_code: ReasonCode | None
    message: str
    tables: tuple[str, ...] = field(default_factory=tuple)


def validate_fields(
    engine: str, host: str, port: int, database: str, user: str
) -> FieldError | None:
    """Catch a bad request before a socket is ever opened.

    `docs/data-sources.md` §4: "Port and host validated before attempting."
    Every reason here is a request the user typed wrong, not a database that
    refused — the boundary this ticket's AC draws between "invalid input" and
    "invalid credentials".
    """
    if engine not in ENGINES:
        supported = ", ".join(ENGINE_LABELS[value] for value in ENGINES)
        return FieldError(
            "engine", "unsupported_engine", f"Askwell connects to {supported}, not '{engine}'."
        )
    host = host.strip()
    if not host:
        return FieldError("host", "invalid_host", "A host is required.")
    if len(host) > 255 or any(character.isspace() for character in host):
        return FieldError("host", "invalid_host", "That does not look like a host name or address.")
    if not 1 <= port <= 65535:
        return FieldError("port", "invalid_port", "Port must be between 1 and 65535.")
    if not database.strip():
        return FieldError("database", "invalid_database", "A database name is required.")
    if not user.strip():
        return FieldError("user", "invalid_user", "A user name is required.")
    return None


def _classify_network_error(error: OSError) -> ConnectOutcome:
    """Turn a raw socket failure into one of the four distinguishable reasons.

    Order matters: `socket.gaierror` and `ConnectionRefusedError` are both
    `OSError` subclasses, so they are checked before the generic `errno`
    branch that follows.
    """
    if isinstance(error, socket.gaierror):
        return ConnectOutcome(
            False,
            "host_unresolved",
            "Askwell could not resolve that host name. Check it for a typo.",
        )
    if isinstance(error, TimeoutError | socket.timeout):
        return ConnectOutcome(
            False,
            "timeout",
            "The database did not answer in time. Check that it is running and reachable "
            "from this machine.",
        )
    if isinstance(error, ConnectionRefusedError):
        return ConnectOutcome(
            False,
            "connection_refused",
            "The connection was refused. Check the port, and that the database is accepting "
            "connections.",
        )
    if error.errno in (errno.ENETUNREACH, errno.EHOSTUNREACH, errno.ENETDOWN):
        return ConnectOutcome(False, "network_blocked", NETWORK_BLOCKED_MESSAGE)
    reachability = error.strerror or error
    return ConnectOutcome(
        False, "connection_refused", f"Askwell could not reach that host: {reachability}."
    )


def _classify_postgresql_message(message: str) -> ConnectOutcome:
    """`psycopg`/libpq report connection failures as text, not distinct
    exception types — this is the same classification `_classify_network_error`
    does for a raw socket, matched against libpq's own wording instead."""
    lowered = message.lower()
    if "could not translate host name" in lowered or "name or service not known" in lowered:
        return ConnectOutcome(
            False,
            "host_unresolved",
            "Askwell could not resolve that host name. Check it for a typo.",
        )
    if "timeout expired" in lowered or "timed out" in lowered:
        return ConnectOutcome(
            False,
            "timeout",
            "The database did not answer in time. Check that it is running and reachable "
            "from this machine.",
        )
    if "network is unreachable" in lowered or "no route to host" in lowered:
        return ConnectOutcome(False, "network_blocked", NETWORK_BLOCKED_MESSAGE)
    if "connection refused" in lowered:
        return ConnectOutcome(
            False,
            "connection_refused",
            "The connection was refused. Check the port, and that the database is accepting "
            "connections.",
        )
    if "password authentication failed" in lowered or "authentication failed" in lowered:
        return ConnectOutcome(False, "auth_failed", "That user name or password was not accepted.")
    return ConnectOutcome(False, "unknown", f"Askwell could not connect: {message.strip()}.")


def _probe_postgresql_blocking(
    host: str, port: int, database: str, user: str, password: str, timeout: float
) -> ConnectOutcome:
    import psycopg

    try:
        with psycopg.connect(
            host=host,
            port=port,
            dbname=database,
            user=user,
            password=password,
            connect_timeout=max(1, int(timeout)),
        ) as conn:
            conn.read_only = True
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema NOT IN ('pg_catalog', 'information_schema') "
                    "ORDER BY table_name"
                )
                tables = tuple(str(row[0]) for row in cur.fetchall())

                selectable: set[str] = set()
                if tables:
                    cur.execute(
                        "SELECT DISTINCT table_name FROM information_schema.table_privileges "
                        "WHERE grantee = current_user AND privilege_type = 'SELECT'"
                    )
                    selectable = {str(row[0]) for row in cur.fetchall()}
        if tables and not selectable:
            return ConnectOutcome(
                False,
                "permission_denied",
                f"Connected, but {user!r} has no SELECT privilege on any table in this "
                "database. Grant SELECT on the tables Askwell should read.",
            )
        return ConnectOutcome(True, None, "Connected.", tables)
    except psycopg.OperationalError as error:
        return _classify_postgresql_message(str(error))
    except OSError as error:
        return _classify_network_error(error)


def _probe_mysql_blocking(
    engine: str, host: str, port: int, database: str, user: str, password: str, timeout: float
) -> ConnectOutcome:
    import pymysql
    from pymysql.constants import CR, ER

    try:
        conn = pymysql.connect(
            host=host,
            port=port,
            database=database,
            user=user,
            password=password,
            connect_timeout=max(1, int(timeout)),
        )
    except OSError as error:
        return _classify_network_error(error)
    except pymysql.err.OperationalError as error:
        code = error.args[0] if error.args else None
        message = str(error.args[1]) if len(error.args) > 1 else str(error)
        if code in (ER.ACCESS_DENIED_ERROR, ER.DBACCESS_DENIED_ERROR):
            return ConnectOutcome(
                False, "auth_failed", "That user name or password was not accepted."
            )
        if code in (CR.CR_CONN_HOST_ERROR, CR.CR_CONNECTION_ERROR):
            return ConnectOutcome(
                False,
                "connection_refused",
                "The connection was refused. Check the port, and that the database is "
                "accepting connections.",
            )
        if code == CR.CR_UNKNOWN_HOST:
            return ConnectOutcome(
                False,
                "host_unresolved",
                "Askwell could not resolve that host name. Check it for a typo.",
            )
        return ConnectOutcome(False, "unknown", f"Askwell could not connect: {message}.")

    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = %s "
                "ORDER BY table_name",
                (database,),
            )
            tables = tuple(str(row[0]) for row in cur.fetchall())

            grants: list[str] = []
            try:
                cur.execute("SHOW GRANTS FOR CURRENT_USER()")
                grants = [str(row[0]) for row in cur.fetchall()]
            except pymysql.err.MySQLError:
                grants = []
        can_select = any(
            "ALL PRIVILEGES" in grant or "SELECT" in grant.split("ON", 1)[0] for grant in grants
        )
        if tables and grants and not can_select:
            return ConnectOutcome(
                False,
                "permission_denied",
                f"Connected, but {user!r} has no SELECT privilege on this database's tables. "
                "Grant SELECT on the tables Askwell should read.",
            )
        return ConnectOutcome(True, None, "Connected.", tables)
    finally:
        conn.close()


def _probe_sqlserver_blocking(
    host: str, port: int, database: str, user: str, password: str, timeout: float
) -> ConnectOutcome:
    import pytds
    from pytds.tds_base import LoginError, OperationalError

    try:
        conn = pytds.connect(
            server=host,
            port=port,
            database=database,
            user=user,
            password=password,
            login_timeout=max(1, int(timeout)),
        )
    except OSError as error:
        return _classify_network_error(error)
    except LoginError:
        return ConnectOutcome(False, "auth_failed", "That user name or password was not accepted.")
    except OperationalError as error:
        return ConnectOutcome(False, "connection_refused", f"Askwell could not connect: {error}.")

    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_type = "
                "'BASE TABLE' ORDER BY table_name"
            )
            tables = tuple(str(row[0]) for row in cur.fetchall())

            can_select = True
            try:
                cur.execute("SELECT permission_name FROM sys.fn_my_permissions(NULL, 'DATABASE')")
                permissions = {str(row[0]) for row in cur.fetchall()}
                can_select = "SELECT" in permissions or not permissions
            except pytds.Error:
                pass
        if tables and not can_select:
            return ConnectOutcome(
                False,
                "permission_denied",
                f"Connected, but {user!r} has no SELECT permission on this database. Grant "
                "SELECT on the tables Askwell should read.",
            )
        return ConnectOutcome(True, None, "Connected.", tables)
    finally:
        conn.close()


async def probe_connection(
    engine: str,
    host: str,
    port: int,
    database: str,
    user: str,
    password: str,
    timeout_seconds: float,
) -> ConnectOutcome:
    """Attempt a real connection and a minimal read check.

    Every driver call is blocking — `psycopg`'s async support is native, but
    `pymysql` and `python-tds` have none, and running the one engine that
    could be async separately from the other two would buy nothing here; the
    call this makes is a few hundred milliseconds against a reachable
    database and bounded by `timeout_seconds` against one that is not, either
    way it belongs off the event loop (AGENTS.md §6).
    """
    if engine == "postgresql":
        return await asyncio.to_thread(
            _probe_postgresql_blocking, host, port, database, user, password, timeout_seconds
        )
    if engine in ("mysql", "mariadb"):
        return await asyncio.to_thread(
            _probe_mysql_blocking, engine, host, port, database, user, password, timeout_seconds
        )
    if engine == "sqlserver":
        return await asyncio.to_thread(
            _probe_sqlserver_blocking, host, port, database, user, password, timeout_seconds
        )
    return ConnectOutcome(False, "unsupported_engine", f"Askwell does not support '{engine}'.")


async def create_connection_source(
    session: AsyncSession,
    *,
    engine: str,
    host: str,
    port: int,
    database: str,
    user: str,
    password: str,
) -> uuid.UUID:
    """Register a live connection as a `sources` row.

    `config_encrypted` holds the connection configuration as JSON bytes —
    genuinely encrypted only once `M4-CONN-SEC-098` lands, this ticket's own
    named "Out of Scope". Never logged and never in a decisions payload: the
    record below names the destination, not the credential.
    """
    import json

    config = json.dumps(
        {
            "engine": engine,
            "host": host,
            "port": port,
            "database": database,
            "user": user,
            "password": password,
        }
    ).encode("utf-8")
    name = f"{database} on {host}"

    result = await session.execute(
        text(
            "INSERT INTO sources (kind, name, config_encrypted, status) "
            "VALUES ('connection', :name, :config, 'queued') RETURNING id"
        ),
        {"name": name, "config": config},
    )
    source_id = result.scalar_one()
    await audit.record(
        session,
        Store.DECISIONS,
        CONNECTION_ADDED,
        {
            "source_id": str(source_id),
            "engine": engine,
            "host": host,
            "port": port,
            "database": database,
            "user": user,
        },
    )
    log.info("connection_added", source_id=str(source_id), engine=engine, host=host, port=port)
    return uuid.UUID(str(source_id))


async def record_introspection(
    session: AsyncSession, source_id: uuid.UUID, tables: tuple[str, ...]
) -> None:
    """Record a connected source's table inventory and mark it ready.

    Names only, the same split `dump_import._introspect_blocking` draws:
    types, keys and relationships are `M4-SCHEMA-ING-100`'s job, not
    reimplemented here under a different name.
    """
    from askwell.memory import write_schema_note

    for table_name in tables:
        await write_schema_note(
            session,
            source_id=source_id,
            table_name=table_name,
            column_name=None,
            description=f"Table {table_name}.",
            origin="inferred",
        )
    await session.execute(
        text("UPDATE sources SET status = 'ready', last_indexed_at = now() WHERE id = :id"),
        {"id": source_id},
    )
    await audit.record(
        session,
        Store.DECISIONS,
        "connection_introspected",
        {"source_id": str(source_id), "tables": list(tables)},
    )
    log.info("connection_introspected", source_id=str(source_id), tables=len(tables))


async def dispatch_introspection(settings: "Settings", source_id: uuid.UUID) -> bool:
    """Ask a worker to introspect this connection now, mirroring
    `dump_import.dispatch_import`: one attempt, swallowed and logged rather
    than raised, because `create_connection_source` has already committed the
    `sources` row and this is only a nudge. Same known gap as that function's
    own docstring — no reconcile sweep exists for a `connection` source stuck
    `queued` (issue #340 already tracks this for `dump`/`table`; a
    `connection` source joins the same gap rather than a new one).
    """
    from arq import create_pool
    from redis.exceptions import RedisError

    from askwell.worker import redis_settings

    queue = replace(redis_settings(settings), conn_retries=1, conn_retry_delay=0)

    try:
        pool = await create_pool(queue)
    except (OSError, RedisError) as error:
        log.warning(
            "connection_introspect_dispatch_unavailable", error=str(error), source_id=str(source_id)
        )
        return False

    try:
        job = await pool.enqueue_job(
            "introspect_connection_job",
            str(source_id),
            _job_id=f"connection-introspect:{source_id}",
        )
    except (OSError, RedisError) as error:  # pragma: no cover - needs a mid-flight failure
        log.warning(
            "connection_introspect_dispatch_failed", error=str(error), source_id=str(source_id)
        )
        return False
    finally:
        await pool.aclose()

    return job is not None


async def run_introspection(
    factory: "async_sessionmaker[AsyncSession]", settings: "Settings", source_id: uuid.UUID
) -> tuple[str, ...]:
    """The worker side of `dispatch_introspection`: reconnect with the stored
    configuration, list tables, and record the result — or mark the source
    `attention` if the database that just accepted a connection has since
    stopped answering.
    """
    import json

    from askwell.db.engine import session_scope

    async with session_scope(factory) as session:
        row = (
            await session.execute(
                text("SELECT config_encrypted FROM sources WHERE id = :id"), {"id": source_id}
            )
        ).first()
    if row is None or row[0] is None:
        raise ValueError(f"No connection configuration for source {source_id}.")
    config = json.loads(bytes(row[0]).decode("utf-8"))

    outcome = await probe_connection(
        config["engine"],
        config["host"],
        config["port"],
        config["database"],
        config["user"],
        config["password"],
        settings.connection_probe_timeout_seconds,
    )

    async with session_scope(factory) as session:
        if not outcome.ok:
            await session.execute(
                text("UPDATE sources SET status = 'attention', last_error = :error WHERE id = :id"),
                {"error": outcome.message, "id": source_id},
            )
            log.warning(
                "connection_introspect_failed",
                source_id=str(source_id),
                reason=outcome.reason_code,
            )
            return ()
        await record_introspection(session, source_id, outcome.tables)
    return outcome.tables
