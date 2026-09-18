"""Connecting to a live database, and classifying why it failed.
`M4-CONN-FE-096`.

Every driver call opens a real socket, so these tests never let one reach
one — C1 applies to the test suite the same as the product (AGENTS.md §6:
"no network at all" for an unmarked test). Each driver's `connect` is
monkeypatched to raise the exact exception its own source raises for a given
failure, and the assertion is that `connections.py` maps it to the right
distinguishable reason — never that a real database was reached.
"""

import socket

import pytest

from askwell import connections
from askwell.connections import ConnectOutcome, validate_fields

# --- field validation --------------------------------------------------------


def test_an_unsupported_engine_is_refused_before_anything_is_attempted() -> None:
    error = validate_fields("oracle", "db.example.com", 5432, "prod", "reader")
    assert error is not None
    assert error.field == "engine"
    assert error.reason_code == "unsupported_engine"


def test_an_empty_host_is_refused() -> None:
    error = validate_fields("postgresql", "  ", 5432, "prod", "reader")
    assert error is not None
    assert error.reason_code == "invalid_host"


def test_a_host_with_whitespace_in_it_is_refused() -> None:
    error = validate_fields("postgresql", "db example.com", 5432, "prod", "reader")
    assert error is not None
    assert error.reason_code == "invalid_host"


@pytest.mark.parametrize("port", [0, -1, 65536, 100000])
def test_a_port_outside_the_valid_range_is_refused(port: int) -> None:
    error = validate_fields("postgresql", "db.example.com", port, "prod", "reader")
    assert error is not None
    assert error.reason_code == "invalid_port"


def test_an_empty_database_name_is_refused() -> None:
    error = validate_fields("postgresql", "db.example.com", 5432, "  ", "reader")
    assert error is not None
    assert error.reason_code == "invalid_database"


def test_an_empty_user_is_refused() -> None:
    error = validate_fields("postgresql", "db.example.com", 5432, "prod", " ")
    assert error is not None
    assert error.reason_code == "invalid_user"


def test_valid_fields_pass() -> None:
    assert validate_fields("postgresql", "db.example.com", 5432, "prod", "reader") is None


# --- raw socket classification, shared by every pure-Python driver ----------


def test_dns_failure_is_host_unresolved() -> None:
    outcome = connections._classify_network_error(socket.gaierror("Name or service not known"))
    assert outcome.reason_code == "host_unresolved"


def test_connection_refused_is_distinguished_from_host_unresolved() -> None:
    outcome = connections._classify_network_error(ConnectionRefusedError(111, "Connection refused"))
    assert outcome.reason_code == "connection_refused"


def test_socket_timeout_is_its_own_reason() -> None:
    outcome = connections._classify_network_error(TimeoutError("timed out"))
    assert outcome.reason_code == "timeout"


def test_network_unreachable_is_distinguished_from_a_bad_host() -> None:
    """The edge case `docs/data-sources.md` §4 names explicitly: a network the
    egress proxy blocks must not read as a wrong host. `ENETUNREACH` is the
    one signal this module can classify without the permit mechanism that
    does not exist yet (see `connections.py`'s own module docstring)."""
    import errno

    error = OSError()
    error.errno = errno.ENETUNREACH
    outcome = connections._classify_network_error(error)
    assert outcome.reason_code == "network_blocked"
    assert (
        outcome.message
        != connections._classify_network_error(
            socket.gaierror("nodename nor servname provided")
        ).message
    )


def test_host_unreachable_is_also_network_blocked() -> None:
    import errno

    error = OSError()
    error.errno = errno.EHOSTUNREACH
    assert connections._classify_network_error(error).reason_code == "network_blocked"


def test_an_unrecognised_os_error_falls_back_to_connection_refused() -> None:
    error = OSError()
    error.errno = 9999
    error.strerror = "something else"
    assert connections._classify_network_error(error).reason_code == "connection_refused"


# --- PostgreSQL message classification ---------------------------------------


@pytest.mark.parametrize(
    ("message", "reason_code"),
    [
        (
            'could not translate host name "bad" to address: nodename nor servname',
            "host_unresolved",
        ),
        (
            'connection to server at "1.2.3.4", port 5432 failed: Connection refused',
            "connection_refused",
        ),
        ("connection to server timed out", "timeout"),
        ("connection to server failed: Network is unreachable", "network_blocked"),
        ('password authentication failed for user "reader"', "auth_failed"),
        ("something entirely unexpected happened", "unknown"),
    ],
)
def test_postgresql_error_text_is_classified_correctly(message: str, reason_code: str) -> None:
    assert connections._classify_postgresql_message(message).reason_code == reason_code


def test_host_unresolved_and_network_blocked_are_different_messages() -> None:
    """The actual assertion behind the edge case: two reasons that will often
    be triggered by the same underlying condition today (no route out of the
    `internal` network at all) must still carry different, correct copy for
    the day a route exists and the two become genuinely distinct again."""
    unresolved = connections._classify_postgresql_message("could not translate host name")
    blocked = connections._classify_postgresql_message("Network is unreachable")
    assert unresolved.reason_code != blocked.reason_code
    assert unresolved.message != blocked.message


# --- probe_connection dispatch -----------------------------------------------


@pytest.mark.asyncio
async def test_an_unsupported_engine_reaching_probe_connection_is_refused() -> None:
    outcome = await connections.probe_connection(
        "oracle", "db.example.com", 1521, "prod", "reader", "secret", 5.0
    )
    assert outcome.ok is False
    assert outcome.reason_code == "unsupported_engine"


@pytest.mark.asyncio
async def test_postgresql_dispatches_to_the_postgresql_prober(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = {}

    def fake(
        host: str, port: int, database: str, user: str, password: str, timeout: float
    ) -> ConnectOutcome:
        called["args"] = (host, port, database, user, password, timeout)
        return ConnectOutcome(True, None, "Connected.", ("orders",))

    monkeypatch.setattr(connections, "_probe_postgresql_blocking", fake)
    outcome = await connections.probe_connection(
        "postgresql", "db.example.com", 5432, "prod", "reader", "secret", 5.0
    )
    assert outcome.ok is True
    assert outcome.tables == ("orders",)
    assert called["args"] == ("db.example.com", 5432, "prod", "reader", "secret", 5.0)


@pytest.mark.asyncio
async def test_mariadb_and_mysql_both_dispatch_to_the_mysql_prober(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engines_seen = []

    def fake(
        engine: str, host: str, port: int, database: str, user: str, password: str, timeout: float
    ) -> ConnectOutcome:
        engines_seen.append(engine)
        return ConnectOutcome(True, None, "Connected.", ())

    monkeypatch.setattr(connections, "_probe_mysql_blocking", fake)
    for engine in ("mysql", "mariadb"):
        outcome = await connections.probe_connection(
            engine, "db.example.com", 3306, "prod", "reader", "secret", 5.0
        )
        assert outcome.ok is True
    assert engines_seen == ["mysql", "mariadb"]


@pytest.mark.asyncio
async def test_a_probe_failure_propagates_its_reason_code(monkeypatch: pytest.MonkeyPatch) -> None:
    refusal = ConnectOutcome(False, "auth_failed", "That user name or password was not accepted.")
    monkeypatch.setattr(connections, "_probe_sqlserver_blocking", lambda *args: refusal)
    outcome = await connections.probe_connection(
        "sqlserver", "db.example.com", 1433, "prod", "reader", "wrong", 5.0
    )
    assert outcome.ok is False
    assert outcome.reason_code == "auth_failed"


# --- write-permission probe: refusal, naming the permission and object ------
# `M4-CONN-SEC-097`. The database role is the C2 layer that does not depend on
# `sqlglot` ever running: these tests are about what gets *named*, since the
# refusal is only useful to a non-DBA if it says what to fix.


def test_write_capable_outcome_names_the_permission_and_the_object() -> None:
    outcome = connections._write_capable_outcome("postgresql", "orders", "INSERT", "`orders`")
    assert outcome.ok is False
    assert outcome.reason_code == "write_capable"
    assert "INSERT" in outcome.message
    assert "`orders`" in outcome.message
    assert "read-only" in outcome.message
    assert outcome.remediation is not None
    assert "askwell_reader" in outcome.remediation


def test_probe_unreliable_outcome_is_a_refusal_not_a_warning() -> None:
    outcome = connections._probe_unreliable_outcome()
    assert outcome.ok is False
    assert outcome.reason_code == "probe_unreliable"


@pytest.mark.parametrize("engine", ["postgresql", "mysql", "mariadb", "sqlserver"])
def test_every_supported_engine_has_read_only_user_guidance(engine: str) -> None:
    sql = connections.read_only_user_sql(engine, "orders")
    assert sql.strip()
    assert "orders" in sql or engine == "sqlserver"


def test_an_unsupported_engine_has_no_read_only_guidance() -> None:
    with pytest.raises(ValueError):
        connections.read_only_user_sql("oracle", "orders")


# --- MySQL/MariaDB grant parsing ---------------------------------------------


def test_all_privileges_on_every_database_is_caught_as_write_capable() -> None:
    found = connections._find_mysql_write_grant(["GRANT ALL PRIVILEGES ON *.* TO `admin`@`%`"])
    assert found == ("ALL PRIVILEGES", "*.*")


def test_insert_on_a_specific_table_is_caught() -> None:
    found = connections._find_mysql_write_grant(
        ["GRANT SELECT, INSERT ON `orders`.* TO `reader`@`%`"]
    )
    assert found == ("INSERT", "`orders`.*")


def test_select_only_grant_is_not_write_capable() -> None:
    found = connections._find_mysql_write_grant(
        ["GRANT SELECT ON `orders`.* TO `reader`@`%`", "GRANT USAGE ON *.* TO `reader`@`%`"]
    )
    assert found is None


def test_no_grants_is_not_write_capable() -> None:
    assert connections._find_mysql_write_grant([]) is None


def test_an_unparseable_grant_line_is_ignored_rather_than_crashing() -> None:
    assert connections._find_mysql_write_grant(["not a grant line"]) is None


# --- SQL Server permission/role classification -------------------------------


def test_sysadmin_membership_names_the_server_not_the_database() -> None:
    found = connections._find_sqlserver_write_permission(
        "orders", is_sysadmin=True, role_memberships=set(), permissions=set()
    )
    assert found == ("sysadmin", "the server")


def test_db_datawriter_membership_is_write_capable() -> None:
    found = connections._find_sqlserver_write_permission(
        "orders", is_sysadmin=False, role_memberships={"db_datawriter"}, permissions=set()
    )
    assert found == ("db_datawriter", "the `orders` database")


def test_a_bare_insert_permission_is_write_capable() -> None:
    found = connections._find_sqlserver_write_permission(
        "orders", is_sysadmin=False, role_memberships=set(), permissions={"SELECT", "INSERT"}
    )
    assert found == ("INSERT", "the `orders` database")


def test_db_datareader_alone_is_not_write_capable() -> None:
    found = connections._find_sqlserver_write_permission(
        "orders", is_sysadmin=False, role_memberships={"db_datareader"}, permissions={"SELECT"}
    )
    assert found is None
