"""`StatementTimedOut`'s message. `M4-SQL-DB-107`.

Pure: no network, no database — `askwell.sql_execute.execute_sandbox_query`/
`execute_connection_query` themselves can only be proven against a real
Postgres/MySQL/SQL Server instance, so those are `test_sql_execute_db.py`,
`requires_db`.
"""

from askwell.sql_execute import StatementTimedOut


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
