"""`StatementTimedOut`'s message, and the three distinguishable query-time
failures on a live connection. `M4-SQL-DB-107`, `M4-CONN-BE-099`.

Pure: no network, no database — `askwell.sql_execute.execute_sandbox_query`/
`execute_connection_query` themselves can only be proven against a real
Postgres/MySQL/SQL Server instance, so those are `test_sql_execute_db.py` and
`test_sql_execute_connection_db.py`, both `requires_db`.
"""

from askwell.sql_execute import (
    ConnectionUnreachable,
    CredentialsRejected,
    QueryRejected,
    StatementTimedOut,
)


def test_statement_timed_out_names_the_query() -> None:
    error = StatementTimedOut("SELECT * FROM orders", 30.0, 30.4)
    assert "SELECT * FROM orders" in str(error)


def test_statement_timed_out_names_the_timeout() -> None:
    error = StatementTimedOut("SELECT 1", 30.0, 30.1)
    assert "30" in str(error)


def test_statement_timed_out_suggests_narrowing() -> None:
    error = StatementTimedOut("SELECT 1", 30.0, 30.1)
    assert "narrow" in str(error).lower()


def test_statement_timed_out_says_the_timeout_is_adjustable() -> None:
    error = StatementTimedOut("SELECT 1", 30.0, 30.1)
    assert "ASKWELL_SQL_STATEMENT_TIMEOUT_SECONDS" in str(error)


def test_statement_timed_out_carries_the_fields_for_a_caller_to_format_differently() -> None:
    error = StatementTimedOut("SELECT 1", 30.0, 30.4)
    assert error.query == "SELECT 1"
    assert error.timeout_seconds == 30.0
    assert error.duration_seconds == 30.4


# --- the three distinguishable query-time failures --------------------------
# `docs/states-and-edge-cases.md` §4's own validation rule: "Unreachable and
# empty must never share a message." These three, and a zero-row
# `QueryResult`, must all read differently from each other.


def test_connection_unreachable_says_unreachable_not_empty() -> None:
    error = ConnectionUnreachable("connection_refused")
    assert "unreachable" in str(error).lower()
    assert "no matching records" not in str(error).lower()


def test_connection_unreachable_carries_its_reason_code() -> None:
    assert ConnectionUnreachable("host_unresolved").reason_code == "host_unresolved"
    assert ConnectionUnreachable(None).reason_code is None


def test_credentials_rejected_names_re_entering_the_credential() -> None:
    error = CredentialsRejected()
    assert "re-enter" in str(error).lower()


def test_credentials_rejected_and_connection_unreachable_are_different_messages() -> None:
    """The edge case this ticket names directly: "a connection whose
    credentials were revoked — reported as a credential problem with a path
    to re-enter", distinct from the database simply being down."""
    assert str(CredentialsRejected()) != str(ConnectionUnreachable("timeout"))


def test_query_rejected_names_it_a_permissions_problem() -> None:
    error = QueryRejected("permission denied for table sources")
    assert "permission" in str(error).lower()
    assert "permission denied for table sources" in str(error)


def test_query_rejected_is_distinct_from_the_other_two() -> None:
    """The edge case this ticket names directly: "a database that accepts
    connections but refuses queries — reported as a permissions problem",
    not as unreachable and not as a bad credential."""
    rejected = str(QueryRejected("permission denied"))
    assert rejected != str(ConnectionUnreachable("connection_refused"))
    assert rejected != str(CredentialsRejected())
