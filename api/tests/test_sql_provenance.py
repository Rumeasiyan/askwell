"""`askwell.sql.provenance` — which rows a validated read came from.
`M11-FIX-BE-231`.

Pure: the rewrite parses and renders with `sqlglot` and does no I/O. Running
the rewritten query, and mapping what it returns back to a workbook's rows,
is `test_sheet_citations_db.py`.
"""

import pytest

from askwell.sql.provenance import plan_provenance, referenced_tables


def test_a_filtered_read_of_one_table_projects_its_rows_after_the_original_columns() -> None:
    plan = plan_provenance(
        "postgresql",
        "SELECT headcount FROM figures_xlsx_data WHERE department = 'Logistics' LIMIT 1000",
    )
    assert plan is not None
    assert plan.table == "figures_xlsx_data"
    assert plan.query == (
        "SELECT headcount, figures_xlsx_data.* FROM figures_xlsx_data "
        "WHERE department = 'Logistics'"
    )


def test_an_aliased_table_is_projected_through_its_alias() -> None:
    plan = plan_provenance(
        "postgresql",
        "SELECT f.headcount AS h, f.department FROM figures AS f WHERE f.headcount > 10",
    )
    assert plan is not None
    assert plan.query == (
        "SELECT f.headcount AS h, f.department, f.* FROM figures AS f WHERE f.headcount > 10"
    )


def test_order_limit_and_offset_are_dropped_so_every_tied_row_is_seen() -> None:
    """A row cut by `LIMIT` is exactly the one a re-run could pick instead.
    Seeing every row the filter admits is what lets the caller tell a tie
    from a single row (#896)."""
    plan = plan_provenance(
        "postgresql", "SELECT headcount FROM figures ORDER BY headcount DESC LIMIT 1 OFFSET 2"
    )
    assert plan is not None
    assert "ORDER" not in plan.query
    assert "LIMIT" not in plan.query
    assert "OFFSET" not in plan.query


def test_a_fetch_first_cap_is_dropped_too() -> None:
    plan = plan_provenance(
        "postgresql", "SELECT headcount FROM figures ORDER BY headcount FETCH FIRST 1 ROWS ONLY"
    )
    assert plan is not None
    assert "FETCH" not in plan.query


@pytest.mark.parametrize(
    "query",
    [
        "SELECT sum(headcount) FROM figures",
        "SELECT department, count(*) FROM figures GROUP BY department",
        "SELECT DISTINCT department FROM figures",
        "SELECT a.department FROM figures a JOIN other b ON a.department = b.department",
        "WITH t AS (SELECT * FROM figures) SELECT department FROM t",
        "SELECT department FROM figures UNION SELECT department FROM other",
        "SELECT department FROM (SELECT * FROM figures) AS t",
        "SELECT department, row_number() OVER (ORDER BY headcount) FROM figures",
        "SELECT 1",
    ],
)
def test_a_read_whose_rows_are_not_one_tables_rows_has_no_plan(query: str) -> None:
    """An aggregate, a join, a set operation and the rest each return rows
    that are not rows of one table: the caller cites the sheet instead."""
    assert plan_provenance("postgresql", query) is None


def test_an_unparseable_query_has_no_plan() -> None:
    assert plan_provenance("postgresql", "SELEC headcount FRM") is None


def test_a_star_projection_still_has_a_plan() -> None:
    plan = plan_provenance("postgresql", "SELECT * FROM figures WHERE headcount = 19")
    assert plan is not None
    assert plan.query == "SELECT *, figures.* FROM figures WHERE headcount = 19"


def test_referenced_tables_names_every_table_read_and_no_cte() -> None:
    tables = referenced_tables(
        "postgresql",
        "WITH t AS (SELECT * FROM figures) "
        "SELECT t.department FROM t JOIN regions r ON r.name = t.department",
    )
    assert tables == ["figures", "regions"]


def test_referenced_tables_of_an_unparseable_query_is_empty() -> None:
    assert referenced_tables("postgresql", "SELEC") == []
