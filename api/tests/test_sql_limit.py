"""`askwell.sql.limit` — the row-limit injection rule. `M4-SQL-VAL-105`.

Pure: `_inject_limit_sync` does no I/O, so every shape the ticket names is
exercised here with no database and no event loop. `inject_limit` itself —
recording an injection to the interactions store — needs a real session, so
that half is `test_sql_limit_db.py`.
"""

from askwell.config import Settings
from askwell.sql.limit import (
    INJECTED_LIMIT_COMMENT,
    LimitResult,
    _inject_limit_sync,
    result_was_truncated,
)


def _inject(settings: Settings, engine: str, query: str, row_limit: int = 1000) -> LimitResult:
    scoped = settings.model_copy(update={"sql_row_limit": row_limit})
    return _inject_limit_sync(scoped, engine=engine, query=query)  # type: ignore[arg-type]


# --- A plain read with no limit and no aggregate gets one. ------------------


def test_plain_select_gets_the_default_limit(settings: Settings) -> None:
    result = _inject(settings, "postgresql", "SELECT id, status FROM orders")
    assert result.injected
    assert result.limit == 1000
    assert "LIMIT 1000" in result.query


def test_injected_limit_is_marked_as_added_by_askwell(settings: Settings) -> None:
    result = _inject(settings, "postgresql", "SELECT id FROM orders")
    assert result.injected
    assert INJECTED_LIMIT_COMMENT in result.query


def test_configured_row_limit_is_used(settings: Settings) -> None:
    result = _inject(settings, "postgresql", "SELECT id FROM orders", row_limit=50)
    assert result.limit == 50
    assert "LIMIT 50" in result.query


# --- A top-level aggregate is exempt. ---------------------------------------


def test_top_level_count_is_not_limited(settings: Settings) -> None:
    result = _inject(settings, "postgresql", "SELECT COUNT(*) FROM orders")
    assert not result.injected
    assert result.limit is None
    assert result.query == "SELECT COUNT(*) FROM orders"


def test_top_level_aggregate_with_group_by_is_not_limited(settings: Settings) -> None:
    result = _inject(settings, "postgresql", "SELECT status, COUNT(*) FROM orders GROUP BY status")
    assert not result.injected
    assert result.limit is None


def test_aggregate_in_a_subquery_is_still_limited(settings: Settings) -> None:
    """The ticket's own edge case: an aggregate nested inside a subquery does
    not exempt the outer query, since the top-level result is still a row
    set, not a single aggregated row.
    """
    result = _inject(
        settings,
        "postgresql",
        "SELECT * FROM (SELECT status, COUNT(*) AS n FROM orders GROUP BY status) sub",
    )
    assert result.injected
    assert result.limit == 1000


def test_scalar_aggregate_subquery_in_projection_is_still_limited(settings: Settings) -> None:
    result = _inject(
        settings,
        "postgresql",
        "SELECT id, (SELECT COUNT(*) FROM line_items li WHERE li.order_id = o.id) AS n "
        "FROM orders o",
    )
    assert result.injected


def test_window_aggregate_does_not_count_as_a_top_level_aggregate(settings: Settings) -> None:
    """A window function does not collapse the row set, unlike a plain
    aggregate, so it is limited like any other row-returning query.
    """
    result = _inject(
        settings,
        "postgresql",
        "SELECT id, SUM(amount) OVER (PARTITION BY customer_id) AS running FROM orders",
    )
    assert result.injected
    assert result.limit == 1000


# --- An explicit limit is left alone. ---------------------------------------


def test_explicit_limit_smaller_than_default_is_left_alone(settings: Settings) -> None:
    result = _inject(settings, "postgresql", "SELECT id FROM orders LIMIT 10")
    assert not result.injected
    assert result.limit == 10
    assert result.query == "SELECT id FROM orders LIMIT 10"


def test_explicit_limit_larger_than_default_is_left_alone(settings: Settings) -> None:
    result = _inject(settings, "postgresql", "SELECT id FROM orders LIMIT 5000")
    assert not result.injected
    assert result.limit == 5000


# --- SQL:2008 FETCH FIRST/NEXT is an existing limit too, not "no limit". ---
# Issue #371: an earlier version only recognised `exp.Limit`, so a `FETCH
# FIRST/NEXT ... ROWS ONLY` clause parsed as no limit at all and got
# silently overwritten with the default, dropping the model's own `OFFSET`.


def test_postgres_fetch_first_is_left_alone(settings: Settings) -> None:
    result = _inject(
        settings,
        "postgresql",
        "SELECT id FROM orders ORDER BY id FETCH FIRST 10 ROWS ONLY",
    )
    assert not result.injected
    assert result.limit == 10
    assert "1000" not in result.query


def test_sqlserver_offset_fetch_next_is_left_alone_and_offset_preserved(
    settings: Settings,
) -> None:
    result = _inject(
        settings,
        "sqlserver",
        "SELECT id FROM orders ORDER BY id OFFSET 20 ROWS FETCH NEXT 10 ROWS ONLY",
    )
    assert not result.injected
    assert result.limit == 10
    assert "OFFSET 20 ROWS" in result.query
    assert "1000" not in result.query


# --- Set operations are never exempt, even when every branch aggregates. ---


def test_union_of_selects_with_no_limit_is_limited(settings: Settings) -> None:
    result = _inject(
        settings, "postgresql", "SELECT id FROM orders UNION SELECT id FROM archived_orders"
    )
    assert result.injected
    assert result.limit == 1000


def test_union_of_aggregates_is_still_limited(settings: Settings) -> None:
    result = _inject(
        settings,
        "postgresql",
        "SELECT COUNT(*) FROM orders UNION SELECT COUNT(*) FROM archived_orders",
    )
    assert result.injected


def test_union_with_its_own_limit_is_left_alone(settings: Settings) -> None:
    result = _inject(
        settings,
        "postgresql",
        "SELECT id FROM orders UNION SELECT id FROM archived_orders LIMIT 20",
    )
    assert not result.injected
    assert result.limit == 20


# --- CTEs: the outer select's own list governs, not the CTE body. ----------


def test_cte_with_aggregate_inside_but_row_set_outside_is_limited(settings: Settings) -> None:
    result = _inject(
        settings,
        "postgresql",
        "WITH totals AS (SELECT status, COUNT(*) AS n FROM orders GROUP BY status) "
        "SELECT * FROM totals",
    )
    assert result.injected


def test_cte_whose_outer_select_aggregates_is_not_limited(settings: Settings) -> None:
    result = _inject(
        settings,
        "postgresql",
        "WITH recent AS (SELECT id FROM orders WHERE created_at > '2026-01-01') "
        "SELECT COUNT(*) FROM recent",
    )
    assert not result.injected


# --- Result labelling. -------------------------------------------------------


def test_result_at_exactly_the_limit_is_labelled_truncated() -> None:
    """Exactly at the limit is indistinguishable from truncation, the
    ticket's own edge case — labelled either way.
    """
    assert result_was_truncated(row_count=1000, limit=1000)


def test_result_under_the_limit_is_not_labelled_truncated() -> None:
    assert not result_was_truncated(row_count=7, limit=1000)


def test_result_with_no_limit_is_never_labelled_truncated() -> None:
    assert not result_was_truncated(row_count=100_000, limit=None)
