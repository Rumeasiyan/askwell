"""Connect Askwell to a database the user already runs. `M4-CONN-FE-096`.

`docs/data-sources.md` §4: host, port, database, user, password, then connect,
probe for write access, introspect the schema, raise clarifications for
unguessable columns. This module builds the first two of those four steps —
connect and a minimal read check — and the table-name inventory that lets a
successful connection say something concrete about what it found.

**Full schema introspection — types, keys, relationships — is
`askwell.schema_introspect`, `M4-SCHEMA-ING-100`.** `run_introspection`
below calls it right after the shallow table list marks a source `ready`,
using the same credential the write-permission probe already verified is
read-only — there is no second, more-privileged credential to reach for
here the way `dump_import.py` has to reach for the sandbox readonly role
instead of the owner. A deep-introspection failure is logged and recorded
but never flips a `ready` source back to `attention`: the shallow pass
already proved the connection works, and a richer description failing to
build is a worse answer, not a broken source.

**Credential encryption (`M4-CONN-SEC-098`).** `config_encrypted` is written
and read through `askwell.crypto`, never as plain JSON. A lost or changed
per-install secret makes a stored credential undecryptable rather than
readable-but-wrong; that is reported as `credentials_locked` and the source
moves to `attention` asking for re-entry, the same shape as any other
introspection failure, never as a misleading `host_unresolved` or similar.

**The write-permission probe (`M4-CONN-SEC-097`) refuses before either read
check runs.** `docs/data-sources.md` §4 layer 1: the database role itself
must be read-only, independently of `sqlglot` validating generated SQL later
— one credential that can write defeats that layer regardless of what the
query layer does. Detection is privilege introspection, never a write
attempt: `pg_roles.rolsuper` / `has_database_privilege(..., 'CREATE')` /
`information_schema.table_privileges` for PostgreSQL, `SHOW GRANTS FOR
CURRENT_USER()` for MySQL/MariaDB, `IS_SRVROLEMEMBER('sysadmin')` / database
role membership / `sys.fn_my_permissions` for SQL Server. A query that cannot
even be asked — the introspection call itself raising — is refused as
`probe_unreliable` rather than treated as a pass; an unverifiable credential
is not an accepted one. There is no override path anywhere in this module.

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
import contextlib
import errno
import functools
import socket
import uuid
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from askwell import audit, crypto, passphrase, redis_client
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

# `M4-CONN-SEC-097`'s own AC: "The refusal and the detected permission are
# decisions records." Never the credential, same rule as `CONNECTION_ADDED`.
CONNECTION_WRITE_REFUSED = "connection_write_refused"

# `M4-CONN-BE-099`. Written only on a `ready`↔`attention` transition, never on
# a repeat of the same state — issue #360's own lesson, learned before this
# function existed rather than after: a health check that fires every
# `connection_health_check_seconds` forever must not turn into a decisions
# row every single cycle, or the "forever, never pruned" store
# (`docs/audit-log.md` §2) grows unbounded for no reason an auditor would
# ever want. `_record_health_transition` is the one place either kind is
# written, shared by the periodic cron and a query-time failure alike, so
# there is exactly one rule to keep rather than two call sites to keep in
# sync.
CONNECTION_HEALTH_LOST = "connection_health_lost"
CONNECTION_HEALTH_RECOVERED = "connection_health_recovered"

# Local-only (C1) — never transmitted. Read by nothing yet; this ticket's own
# AC asks only for the counter to exist, not for a surface that displays it.
WRITE_PROBE_REFUSED_COUNTER_KEY = "askwell:connections:write_probe_refused"

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
    "write_capable",
    "probe_unreliable",
    "credentials_locked",
    "unknown",
]

CREDENTIALS_LOCKED_MESSAGE = (
    "Askwell cannot decrypt this connection's stored credentials. The key "
    "they were encrypted with is missing or has changed — re-enter the "
    "password to reconnect. This is not the same as an unreachable host: "
    "the database was never contacted."
)

NETWORK_BLOCKED_MESSAGE = (
    "Askwell's network policy blocked this connection. Local mode has no "
    "outbound route to any destination by default (C1) — a live database "
    "needs its own, explicitly permitted route, which does not exist yet in "
    "this build. This is not a wrong host or a wrong password; nothing you "
    "change here will fix it."
)

PROBE_UNRELIABLE_MESSAGE = (
    "Askwell connected, but could not verify whether this user can write. An "
    "unverifiable credential is not an acceptable one, so the connection is "
    "refused rather than assumed read-only."
)

# Table-level SQL privileges that mean the role can change data or structure,
# for the engines that expose them as discrete grant names.
_MYSQL_WRITE_PRIVILEGES = (
    "ALL PRIVILEGES",
    "INSERT",
    "UPDATE",
    "DELETE",
    "CREATE",
    "DROP",
    "ALTER",
    "TRUNCATE",
    "REFERENCES",
    "INDEX",
)
_SQLSERVER_WRITE_PERMISSIONS = frozenset(
    {"INSERT", "UPDATE", "DELETE", "ALTER", "CONTROL", "REFERENCES"}
)
_SQLSERVER_WRITE_ROLES = frozenset({"db_owner", "db_datawriter", "db_ddladmin"})


def read_only_user_sql(engine: str, database: str) -> str:
    """Copyable statements for the read-only user `docs/ux/add-source.md` §4
    promises on every refusal: "Telling someone to create a read-only user
    without showing how is where the flow dies for anyone who is not a DBA."
    The password is a placeholder the user fills in themselves — Askwell
    never creates this user or holds its credential (this ticket's own
    "Out of Scope")."""
    if engine == "postgresql":
        return (
            "CREATE ROLE askwell_reader LOGIN PASSWORD 'choose-a-password';\n"
            f"GRANT CONNECT ON DATABASE {database} TO askwell_reader;\n"
            "GRANT USAGE ON SCHEMA public TO askwell_reader;\n"
            "GRANT SELECT ON ALL TABLES IN SCHEMA public TO askwell_reader;\n"
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO askwell_reader;"
        )
    if engine in ("mysql", "mariadb"):
        return (
            "CREATE USER 'askwell_reader'@'%' IDENTIFIED BY 'choose-a-password';\n"
            f"GRANT SELECT ON {database}.* TO 'askwell_reader'@'%';\n"
            "FLUSH PRIVILEGES;"
        )
    if engine == "sqlserver":
        return (
            "CREATE LOGIN askwell_reader WITH PASSWORD = 'choose-a-password';\n"
            "CREATE USER askwell_reader FOR LOGIN askwell_reader;\n"
            "ALTER ROLE db_datareader ADD MEMBER askwell_reader;"
        )
    raise ValueError(f"No read-only user guidance for engine {engine!r}.")


def _write_capable_outcome(
    engine: str, database: str, permission: str, object_phrase: str
) -> "ConnectOutcome":
    message = (
        f"These credentials have {permission} on {object_phrase}. Askwell only connects "
        "with read-only access. Create a read-only user and try again — here is the SQL "
        "for it."
    )
    return ConnectOutcome(
        False, "write_capable", message, remediation=read_only_user_sql(engine, database)
    )


def _probe_unreliable_outcome() -> "ConnectOutcome":
    return ConnectOutcome(False, "probe_unreliable", PROBE_UNRELIABLE_MESSAGE)


def _find_sqlserver_write_permission(
    database: str, *, is_sysadmin: bool, role_memberships: set[str], permissions: set[str]
) -> tuple[str, str] | None:
    """The strongest write-capable signal found, and the object it names —
    `sysadmin` outranks a database role, which outranks a bare permission,
    because a sysadmin refusal naming "the server" is a truer answer than one
    naming "the database" even though both are found true."""
    if is_sysadmin:
        return "sysadmin", "the server"
    write_roles = role_memberships & _SQLSERVER_WRITE_ROLES
    if write_roles:
        return sorted(write_roles)[0], f"the `{database}` database"
    write_permissions = permissions & _SQLSERVER_WRITE_PERMISSIONS
    if write_permissions:
        return sorted(write_permissions)[0], f"the `{database}` database"
    return None


def _find_mysql_write_grant(grants: list[str]) -> tuple[str, str] | None:
    """The first write-capable privilege in a `SHOW GRANTS FOR CURRENT_USER()`
    result, and the object it is scoped to (`*.*`, `db.*`, or `db.table`).

    A grant line looks like `GRANT SELECT, INSERT ON \\`orders\\`.* TO ...` or
    `GRANT ALL PRIVILEGES ON *.* TO ...` — parsed rather than assumed, because
    the object a privilege applies to is exactly what the refusal has to name.
    """
    import re

    for grant in grants:
        match = re.match(r"GRANT\s+(.+?)\s+ON\s+(\S+)\s+TO", grant, re.IGNORECASE)
        if match is None:
            continue
        privileges_text, object_name = match.groups()
        if "ALL PRIVILEGES" in privileges_text.upper():
            return "ALL PRIVILEGES", object_name
        for privilege in (item.strip().upper() for item in privileges_text.split(",")):
            if privilege in _MYSQL_WRITE_PRIVILEGES:
                return privilege, object_name
    return None


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
    remediation: str | None = None


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
                try:
                    cur.execute("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
                    superuser_row = cur.fetchone()
                    is_superuser = bool(superuser_row[0]) if superuser_row else False
                    cur.execute(
                        "SELECT has_database_privilege(current_user, current_database(), 'CREATE')"
                    )
                    create_row = cur.fetchone()
                    can_create = bool(create_row[0]) if create_row else False
                    cur.execute(
                        "SELECT table_schema, table_name, privilege_type FROM "
                        "information_schema.table_privileges WHERE grantee = current_user "
                        "AND privilege_type IN ('INSERT', 'UPDATE', 'DELETE', 'TRUNCATE') "
                        "ORDER BY table_schema, table_name LIMIT 1"
                    )
                    write_row = cur.fetchone()
                except psycopg.Error:
                    return _probe_unreliable_outcome()

                if is_superuser:
                    return _write_capable_outcome(
                        "postgresql", database, "superuser", f"the `{database}` database"
                    )
                if can_create:
                    return _write_capable_outcome(
                        "postgresql", database, "CREATE", f"the `{database}` database"
                    )
                if write_row is not None:
                    schema = str(write_row[0])
                    table_name = str(write_row[1])
                    privilege = str(write_row[2])
                    object_name = table_name if schema == "public" else f"{schema}.{table_name}"
                    return _write_capable_outcome(
                        "postgresql", database, privilege, f"`{object_name}`"
                    )

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
            try:
                cur.execute("SHOW GRANTS FOR CURRENT_USER()")
                grants = [str(row[0]) for row in cur.fetchall()]
            except pymysql.err.MySQLError:
                return _probe_unreliable_outcome()

            write_found = _find_mysql_write_grant(grants)
            if write_found is not None:
                permission, object_name = write_found
                return _write_capable_outcome(engine, database, permission, f"`{object_name}`")

            cur.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = %s "
                "ORDER BY table_name",
                (database,),
            )
            tables = tuple(str(row[0]) for row in cur.fetchall())
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
            try:
                cur.execute("SELECT IS_SRVROLEMEMBER('sysadmin')")
                sysadmin_row = cur.fetchone()
                is_sysadmin = bool(sysadmin_row[0]) if sysadmin_row else False
                cur.execute(
                    "SELECT DP1.name FROM sys.database_role_members DRM "
                    "JOIN sys.database_principals DP1 "
                    "ON DRM.role_principal_id = DP1.principal_id "
                    "JOIN sys.database_principals DP2 "
                    "ON DRM.member_principal_id = DP2.principal_id "
                    "WHERE DP2.name = USER_NAME()"
                )
                role_memberships = {str(row[0]) for row in cur.fetchall()}
                cur.execute("SELECT permission_name FROM sys.fn_my_permissions(NULL, 'DATABASE')")
                permissions = {str(row[0]) for row in cur.fetchall()}
            except pytds.Error:
                return _probe_unreliable_outcome()

            write_found = _find_sqlserver_write_permission(
                database,
                is_sysadmin=is_sysadmin,
                role_memberships=role_memberships,
                permissions=permissions,
            )
            if write_found is not None:
                permission, object_phrase = write_found
                return _write_capable_outcome("sqlserver", database, permission, object_phrase)

            cur.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_type = "
                "'BASE TABLE' ORDER BY table_name"
            )
            tables = tuple(str(row[0]) for row in cur.fetchall())

            can_select = "SELECT" in permissions or not permissions
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


async def record_write_probe_refusal(
    session: AsyncSession, settings: "Settings", *, engine: str, host: str, message: str
) -> None:
    """Record a write-capable refusal: a decisions row naming the detected
    permission (`message` already names it — `_write_capable_outcome`'s own
    text), and a local counter nothing ever transmits (C1).

    The counter increment is best-effort, mirroring `egress._record`: a Redis
    hiccup must not turn a refusal into an exception the wizard has to
    recover from — the refusal itself already happened and already committed
    as a decisions row before this is ever called.
    """
    await audit.record(
        session,
        Store.DECISIONS,
        CONNECTION_WRITE_REFUSED,
        {"engine": engine, "host": host, "message": message},
    )
    log.info("connection_write_refused", engine=engine, host=host)

    client = redis_client.connect(settings, timeout=1.0)
    try:
        await client.incr(WRITE_PROBE_REFUSED_COUNTER_KEY)
    except Exception as error:
        log.warning(
            "connection_write_refused_count_failed", error=f"{type(error).__name__}: {error}"
        )
    finally:
        with contextlib.suppress(Exception):
            await client.aclose()


async def create_connection_source(
    session: AsyncSession,
    settings: "Settings",
    *,
    engine: str,
    host: str,
    port: int,
    database: str,
    user: str,
    password: str,
) -> uuid.UUID:
    """Register a live connection as a `sources` row.

    `config_encrypted` holds the connection configuration encrypted with a
    key derived from the per-install secret (`askwell.crypto`, C8) — never
    plain JSON. Never logged and never in a decisions payload: the record
    below names the destination, not the credential.
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
    key = await passphrase.current_key(session, settings)
    config_encrypted = crypto.encrypt(config, key)
    name = f"{database} on {host}"

    result = await session.execute(
        text(
            "INSERT INTO sources (kind, name, config_encrypted, status) "
            "VALUES ('connection', :name, :config, 'queued') RETURNING id"
        ),
        {"name": name, "config": config_encrypted},
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
    types, keys and relationships are `askwell.schema_introspect`'s job
    (`run_introspection` below calls it separately), not reimplemented here
    under a different name.

    **Idempotent on repeat calls.** `M4-SCHEMA-ING-100` made `run_introspection`
    (and therefore this function) callable again against an already-`ready`
    source — on-demand re-introspection. A table already carrying *any*
    active note, at any origin, is left alone here: a user note must never be
    touched (`write_schema_note` already refuses that), and an active
    inferred note is the deep pass's own job to enrich or replace, not a
    second, competing placeholder this function would otherwise insert
    alongside it every single call.
    """
    from askwell.memory import get_active_schema_notes, write_schema_note

    already_noted = {
        note.table_name
        for note in await get_active_schema_notes(session, source_id=source_id)
        if note.column_name is None
    }
    for table_name in tables:
        if table_name in already_noted:
            continue
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


async def _load_connection_config(
    factory: "async_sessionmaker[AsyncSession]", settings: "Settings", source_id: uuid.UUID
) -> dict[str, Any]:
    """The stored configuration for a live connection, decrypted.

    Shared by `run_introspection` and `check_connection_health` — both
    reconnect with the same stored credential, and duplicating the decrypt
    step would duplicate its two failure modes (`ValueError` for no
    configuration at all, `crypto.CredentialsLocked`/`OSError` for one that
    cannot be read with today's key) instead of leaving exactly one.
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

    async with session_scope(factory) as session:
        key = await passphrase.current_key(session, settings)
    config: dict[str, Any] = json.loads(crypto.decrypt(bytes(row[0]), key).decode("utf-8"))
    return config


async def _record_health_transition(
    session: AsyncSession,
    source_id: uuid.UUID,
    *,
    ok: bool,
    message: str,
    reason_code: str | None,
) -> None:
    """Apply one health probe's result to `sources`, and write a decisions
    record only when the probe actually changed the source's status.

    `last_healthy_at` and `last_error` are plain mutable columns, updated on
    every call regardless of whether anything changed — that is what lets the
    library show "the last successful check" (`docs/ux/library.md` §5)
    without reading the audit log at all, and what keeps "the state reflects
    the latest check rather than flapping" true for intermittent
    connectivity (this ticket's own edge case) without a decisions row for
    every flap. The decisions record — `CONNECTION_HEALTH_LOST` or
    `CONNECTION_HEALTH_RECOVERED` — is the one write gated on a real
    `ready`↔`attention` transition, never on a repeat of the same state
    (issue #360).

    Shared by the periodic health check and a query-time failure
    (`askwell.sql_execute.execute_connection_query`) alike — both are "this
    is what the connection just did", and the transition rule must be the
    same regardless of what triggered the check.
    """
    row = (
        await session.execute(
            text("SELECT status FROM sources WHERE id = :id AND kind = 'connection'"),
            {"id": source_id},
        )
    ).first()
    if row is None:
        return
    current_status = row[0]

    if ok:
        await session.execute(
            text("UPDATE sources SET last_healthy_at = now() WHERE id = :id"), {"id": source_id}
        )
        if current_status != "attention":
            return
        await session.execute(
            text("UPDATE sources SET status = 'ready', last_error = NULL WHERE id = :id"),
            {"id": source_id},
        )
        await audit.record(
            session, Store.DECISIONS, CONNECTION_HEALTH_RECOVERED, {"source_id": str(source_id)}
        )
        log.info("connection_health_recovered", source_id=str(source_id))
        return

    await session.execute(
        text("UPDATE sources SET last_error = :error WHERE id = :id"),
        {"error": message, "id": source_id},
    )
    if current_status == "attention":
        return
    await session.execute(
        text("UPDATE sources SET status = 'attention' WHERE id = :id"), {"id": source_id}
    )
    await audit.record(
        session,
        Store.DECISIONS,
        CONNECTION_HEALTH_LOST,
        {"source_id": str(source_id), "reason_code": reason_code or "unknown", "message": message},
    )
    log.warning("connection_health_lost", source_id=str(source_id), reason_code=reason_code)


async def check_connection_health(
    factory: "async_sessionmaker[AsyncSession]", settings: "Settings", source_id: uuid.UUID
) -> ConnectOutcome:
    """One probe against a live connection, and the state transition it causes.

    Shared by the periodic cron (`askwell.worker.check_connections_health`)
    and the library's on-demand reconnect action — both are "check this
    connection now", differing only in what triggered it, so both go through
    this one function rather than one reimplementing the other.

    Metadata-only, the same probe the wizard itself runs (`probe_connection`):
    a write-permission check and a table listing from system catalogs, never
    a query over the user's own data — what makes running it every
    `connection_health_check_seconds` acceptable on somebody's laptop (this
    ticket's own Assumption).

    A lost install secret and an ordinary connection failure both end up
    `attention`, through the same transition path — `_record_health_transition`
    does not need to know *why* a probe failed, only whether it did, and the
    distinguishing message (`CREDENTIALS_LOCKED_MESSAGE` vs whatever
    `probe_connection` classified) is what a person reads to tell them apart.
    """
    from askwell.db.engine import session_scope

    try:
        config = await _load_connection_config(factory, settings, source_id)
    except (crypto.CredentialsLocked, OSError):
        outcome = ConnectOutcome(False, "credentials_locked", CREDENTIALS_LOCKED_MESSAGE)
    else:
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
        await _record_health_transition(
            session,
            source_id,
            ok=outcome.ok,
            message=outcome.message,
            reason_code=outcome.reason_code,
        )

    return outcome


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
    stopped answering, or if the stored credentials can no longer be
    decrypted (`credentials_locked`, `M4-CONN-SEC-098`) — checked before any
    socket opens, since there is no credential to connect with at all.

    Also **the re-introspection entrypoint on demand or on reconnect**
    (`M4-SCHEMA-ING-100`): this function reconnects with the stored
    configuration regardless of whether the source has just been added or
    has been `ready` for months, so calling it again against an existing
    source is exactly what "re-introspect" means for a live connection —
    there is no separate function to keep in sync with this one.
    """
    from askwell.db.engine import session_scope

    try:
        config = await _load_connection_config(factory, settings, source_id)
    except (crypto.CredentialsLocked, OSError):
        async with session_scope(factory) as session:
            await session.execute(
                text("UPDATE sources SET status = 'attention', last_error = :error WHERE id = :id"),
                {"error": CREDENTIALS_LOCKED_MESSAGE, "id": source_id},
            )
        log.warning("connection_introspect_locked", source_id=str(source_id))
        return ()

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

    await _run_deep_introspection(factory, settings, source_id, config)
    return outcome.tables


def _postgresql_dsn(host: str, port: int, database: str, user: str, password: str) -> str:
    """A libpq connection URL built from discrete fields, the same shape
    `askwell.sandbox.readonly_url` builds for a sandbox database — the
    deep-introspection query is a plain `psycopg.connect(dsn)`, so this is
    the only difference between a live connection and a sandbox source.
    """
    from urllib.parse import quote

    user_part = quote(user, safe="")
    password_part = quote(password, safe="")
    return f"postgresql://{user_part}:{password_part}@{host}:{port}/{database}"


async def _run_deep_introspection(
    factory: "async_sessionmaker[AsyncSession]",
    settings: "Settings",
    source_id: uuid.UUID,
    config: dict[str, object],
) -> None:
    """Types, keys and relationships, on top of the table names
    `record_introspection` already wrote. `M4-SCHEMA-ING-100`.

    Runs with the same credential `probe_connection` already verified is
    read-only — never a second, more-privileged one. Failure here is logged
    and recorded but never moves a `ready` source back to `attention`: the
    shallow pass already proved the connection itself works, so a richer
    description failing to build is a worse answer, not a broken source
    (this module's own docstring has the full reasoning).
    """
    from askwell import schema_introspect
    from askwell.db.engine import session_scope

    engine = str(config["engine"])
    dsn: str | None = None
    try:
        if engine == "postgresql":
            dsn = _postgresql_dsn(
                str(config["host"]),
                int(config["port"]),  # type: ignore[call-overload]
                str(config["database"]),
                str(config["user"]),
                str(config["password"]),
            )
            inventory = await asyncio.to_thread(
                schema_introspect._introspect_postgresql_blocking, dsn
            )
        else:
            inventory = await asyncio.to_thread(
                schema_introspect.introspect_blocking,
                engine,
                str(config["host"]),
                port=config["port"],
                database=config["database"],
                user=config["user"],
                password=config["password"],
            )
    except Exception as error:
        async with session_scope(factory) as session:
            await audit.record(
                session,
                Store.DECISIONS,
                "schema_introspection_failed",
                {"source_id": str(source_id), "reason": f"{type(error).__name__}: {error}"},
            )
        log.warning("schema_introspection_failed", source_id=str(source_id), error=str(error))
        return

    async with session_scope(factory) as session:
        await schema_introspect.write_schema_inventory(session, source_id, inventory)
        # `M4-SCHEMA-BE-102`: same session as the write above — no window
        # where `schema_notes` and `sources.status` disagree about whether
        # this source needs attention for schema drift.
        await schema_introspect.refresh_schema_attention(session, source_id)
    await schema_introspect.record_introspection_run(settings)

    # `M4-SCHEMA-ING-101`: unguessable columns raise clarifications, with a
    # bounded value distribution as evidence — only wired up for PostgreSQL
    # today (`raise_unguessable_column_clarifications`'s own docstring has
    # the MySQL/SQL Server gap and the issue it is filed under).
    sample = (
        functools.partial(schema_introspect._sample_postgresql_column_distribution, dsn)
        if dsn is not None
        else None
    )
    async with session_scope(factory) as session:
        await schema_introspect.raise_unguessable_column_clarifications(
            session, source_id, inventory, sample
        )
