"""`askwell.sql.validate` — the C2 gate. `M4-SQL-VAL-104`.

Pure: `_validate_sync` does no I/O, so every hostile statement shape the
ticket names is exercised here with no database and no event loop.
`validate_query` itself — the bounded wait and the decisions-store
recording — needs a real session, so that half is `test_sql_validate_db.py`.
"""

import re
from pathlib import Path

import pytest

from askwell.sql.validate import RejectionReason, ValidationResult, _validate_sync

_VALIDATE_SOURCE = Path(__file__).parent.parent / "src" / "askwell" / "sql" / "validate.py"


def _accepted(engine: str, query: str) -> ValidationResult:
    result = _validate_sync(engine, query)  # type: ignore[arg-type]
    assert result.accepted, f"expected accepted, got {result.reason}: {result.detail}"
    return result


def _rejected(engine: str, query: str, reason: RejectionReason) -> ValidationResult:
    result = _validate_sync(engine, query)  # type: ignore[arg-type]
    assert not result.accepted, f"expected rejection ({reason}), got accepted"
    assert result.reason == reason, f"expected {reason}, got {result.reason}: {result.detail}"
    assert result.detail
    return result


# --- No regex anywhere in the path. C2's own hard requirement. -------------


def test_no_regex_based_filtering_exists() -> None:
    source = _VALIDATE_SOURCE.read_text(encoding="utf-8")
    for forbidden in ("import re\n", "re.compile(", "re.match(", "re.search(", "re.fullmatch("):
        assert forbidden not in source, (
            f"{forbidden!r} found in askwell/sql/validate.py — C2 requires sqlglot "
            "parsing as the gate, never regex filtering, not even temporarily."
        )


# --- A single read passes. --------------------------------------------------


def test_single_select_passes() -> None:
    _accepted("postgresql", "SELECT id, status FROM orders WHERE status = 'open'")


def test_with_cte_passes() -> None:
    _accepted(
        "postgresql",
        "WITH recent AS (SELECT id FROM orders WHERE created_at > '2026-01-01') "
        "SELECT * FROM recent",
    )


def test_union_of_selects_passes() -> None:
    _accepted("postgresql", "SELECT id FROM orders UNION SELECT id FROM archived_orders")


@pytest.mark.parametrize(
    ("engine", "query"),
    [
        ("postgresql", "SELECT 1"),
        ("mysql", "SELECT 1"),
        ("mariadb", "SELECT 1"),
        ("sqlserver", "SELECT TOP 10 * FROM orders"),
    ],
)
def test_every_supported_engine_dialect_parses_a_plain_select(engine: str, query: str) -> None:
    _accepted(engine, query)


# --- Multiple statements: always rejected. ----------------------------------


def test_two_statements_rejected() -> None:
    _rejected(
        "postgresql",
        "SELECT id FROM orders; DELETE FROM orders",
        RejectionReason.MULTIPLE_STATEMENTS,
    )


def test_read_with_trailing_modification_rejected() -> None:
    _rejected(
        "postgresql",
        "SELECT * FROM orders WHERE id = 1; UPDATE orders SET status = 'x'",
        RejectionReason.MULTIPLE_STATEMENTS,
    )


def test_two_reads_still_rejected_as_multiple_statements() -> None:
    # Neither half is a write — the rule is "exactly one statement", not
    # "no write among several".
    _rejected("postgresql", "SELECT 1; SELECT 2", RejectionReason.MULTIPLE_STATEMENTS)


# --- Data-modifying statements: always rejected. ----------------------------


@pytest.mark.parametrize(
    "query",
    [
        "DELETE FROM orders",
        "DELETE FROM orders WHERE id = 1",
        "INSERT INTO orders (id) VALUES (1)",
        "UPDATE orders SET status = 'closed'",
        "MERGE INTO orders USING staging ON orders.id = staging.id "
        "WHEN MATCHED THEN UPDATE SET status = staging.status",
    ],
)
def test_data_modifying_statement_rejected(query: str) -> None:
    _rejected("postgresql", query, RejectionReason.NOT_A_SINGLE_READ)


# --- Definition statements: always rejected. --------------------------------


@pytest.mark.parametrize(
    "query",
    [
        "DROP TABLE orders",
        "CREATE TABLE t (id int)",
        "ALTER TABLE orders ADD COLUMN x int",
        "TRUNCATE TABLE orders",
    ],
)
def test_definition_statement_rejected(query: str) -> None:
    _rejected("postgresql", query, RejectionReason.NOT_A_SINGLE_READ)


# --- Nesting used to disguise a modification. -------------------------------


def test_data_modifying_cte_rejected_despite_select_at_top_level() -> None:
    # PostgreSQL genuinely allows this — a CTE with RETURNING deletes every
    # row when run, even though the top-level node is a SELECT. Top-level
    # type alone would wrongly accept this; the whole-tree scan below does
    # not.
    result = _validate_sync(
        "postgresql",
        "WITH d AS (DELETE FROM orders RETURNING *) SELECT * FROM d",
    )
    assert not result.accepted
    assert result.reason == RejectionReason.WRITE_DETECTED


def test_select_into_rejected_as_a_write() -> None:
    # `SELECT ... INTO` is syntactically a SELECT and creates a table.
    _rejected(
        "postgresql",
        "SELECT * INTO new_table FROM orders",
        RejectionReason.WRITE_DETECTED,
    )


# --- Comments cannot hide a second statement from the parser. --------------


def test_line_comment_does_not_disguise_a_real_statement() -> None:
    # A line comment is genuinely a comment to both sqlglot and the
    # database — it cannot smuggle a second statement past either. This
    # stays a single accepted read.
    _accepted("postgresql", "SELECT * FROM orders WHERE 1 = 1 -- ; DROP TABLE orders")


def test_block_comment_around_a_real_second_statement_still_two_statements() -> None:
    # The comment is decoration; the semicolon-separated DELETE after it is
    # still a genuine second statement and is rejected the same way any
    # other multi-statement input is — not because of the comment.
    _rejected(
        "postgresql",
        "SELECT 1 /* looks harmless */; DELETE FROM orders",
        RejectionReason.MULTIPLE_STATEMENTS,
    )


# --- Locking reads and side-effecting functions. ----------------------------


def test_locking_read_rejected() -> None:
    _rejected("postgresql", "SELECT * FROM orders FOR UPDATE", RejectionReason.LOCKING_READ)


def test_side_effect_function_rejected() -> None:
    _rejected(
        "postgresql",
        "SELECT pg_terminate_backend(123)",
        RejectionReason.SIDE_EFFECT_FUNCTION,
    )


def test_ordinary_aggregate_function_is_not_flagged_as_a_side_effect() -> None:
    # `COUNT` is a named sqlglot node, never `exp.Anonymous` — the
    # side-effect denylist only ever matches functions sqlglot cannot
    # otherwise classify, never an ordinary aggregate or scalar function.
    _accepted("postgresql", "SELECT COUNT(*) FROM orders")


# --- Unparseable input: rejected, not passed through. -----------------------


def test_unparseable_statement_rejected() -> None:
    _rejected("postgresql", "SELECT * FROM WHERE", RejectionReason.UNPARSEABLE)


def test_engine_specific_construct_sqlglot_cannot_read_is_rejected() -> None:
    # `SELECT ... INTO OUTFILE` is MySQL-specific and not a construct this
    # sqlglot version's `mysql` dialect can parse at all — an unparseable
    # statement is not a safe one, so it is rejected rather than silently
    # treated as some other shape.
    _rejected(
        "mysql",
        "SELECT * FROM orders INTO OUTFILE '/tmp/dump.csv'",
        RejectionReason.UNPARSEABLE,
    )


def test_explain_is_rejected_not_executed() -> None:
    # sqlglot cannot model EXPLAIN as a query at all — it falls back to a
    # generic Command node, which this module never accepts.
    _rejected("postgresql", "EXPLAIN SELECT * FROM orders", RejectionReason.NOT_A_SINGLE_READ)


# --- Empty input. ------------------------------------------------------------


@pytest.mark.parametrize("query", ["", "   ", "\n\t"])
def test_empty_query_rejected(query: str) -> None:
    _rejected("postgresql", query, RejectionReason.EMPTY)


# --- Sanity: the module really has no compiled regex pattern anywhere. -----


def test_module_source_has_no_compiled_pattern_object() -> None:
    source = _VALIDATE_SOURCE.read_text(encoding="utf-8")
    assert re.search(r"\bPattern\b", source) is None
