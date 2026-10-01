"""`askwell.sheet_citations` — the pure half: which table rows a result
returned, and which of a sheet's rows a table row is. `M11-FIX-BE-231`.

Everything that reads a database is `test_sheet_citations_db.py`.
"""

from datetime import date, datetime
from decimal import Decimal

from askwell.sheet_citations import returned_table_rows, row_matches_anchor

# --- which table rows a result returned (C4: never one it did not) ---------


def test_each_returned_row_is_the_one_table_row_with_its_values() -> None:
    returned = [(19,)]
    provenance = [
        (19, "Logistics", 215000, 19, Decimal("2.7")),
    ]
    assert returned_table_rows(returned, 1, provenance) == [
        ("Logistics", 215000, 19, Decimal("2.7"))
    ]


def test_a_tie_the_limit_cut_is_not_resolved_to_either_row() -> None:
    """#896: `SELECT headcount FROM t ORDER BY headcount LIMIT 1` with two
    departments at 19. Either could be the row returned, so neither is."""
    returned = [(19,)]
    provenance = [
        (19, "Logistics", 215000, 19),
        (19, "Design", 76000, 19),
    ]
    assert returned_table_rows(returned, 1, provenance) is None


def test_two_returned_rows_with_the_same_values_are_both_rows_when_both_were_returned() -> None:
    returned = [(19,), (19,)]
    provenance = [
        (19, "Logistics", 215000, 19),
        (19, "Design", 76000, 19),
    ]
    assert returned_table_rows(returned, 1, provenance) == [
        ("Logistics", 215000, 19),
        ("Design", 76000, 19),
    ]


def test_a_returned_row_the_rerun_cannot_find_is_not_resolved() -> None:
    """The table changed between the two reads: nothing is cited rather than
    a row that may not be the one shown."""
    assert returned_table_rows([(19,)], 1, [(20, "Logistics", 20)]) is None


def test_an_empty_result_returns_no_rows() -> None:
    assert returned_table_rows([], 1, [(19, "Logistics", 19)]) == []


# --- which of a sheet's rows a table row is --------------------------------


def test_a_table_row_matches_its_sheet_row_as_extraction_wrote_it() -> None:
    assert row_matches_anchor(
        ("Logistics", 215000, 19, Decimal("2.7")), "Logistics | 215000 | 19 | 2.7"
    )


def test_a_different_row_does_not_match() -> None:
    assert not row_matches_anchor(
        ("Logistics", 215000, 19, Decimal("2.7")), "Design | 76000 | 12 | 2.7"
    )


def test_numbers_match_by_value_not_spelling() -> None:
    assert row_matches_anchor(("Retail", Decimal("118000.0"), 41), "Retail | 118000 | 41")
    assert row_matches_anchor(("Retail", 118000, Decimal("1.90")), "Retail | 118000 | 1.9")


def test_an_empty_cell_is_absent_from_both() -> None:
    """Extraction leaves an empty cell out of the row's text; a `NULL` is
    left out of the comparison the same way."""
    assert row_matches_anchor(("Retail", None, 41), "Retail | 41")
    assert not row_matches_anchor(("Retail", None, 41), "Retail | 0 | 41")


def test_a_date_matches_the_datetime_a_workbook_stores() -> None:
    assert row_matches_anchor(("Launch", date(2026, 3, 1)), "Launch | 2026-03-01 00:00:00")
    assert row_matches_anchor(
        ("Launch", datetime(2026, 3, 1, 9, 30)), "Launch | 2026-03-01 09:30:00"
    )
    assert not row_matches_anchor(("Launch", date(2026, 3, 1)), "Launch | 2026-03-02 00:00:00")


def test_a_boolean_matches_the_spelling_it_was_loaded_from() -> None:
    assert row_matches_anchor(("Active", True), "Active | True")
    assert row_matches_anchor(("Active", False), "Active | no")
    assert not row_matches_anchor(("Active", True), "Active | no")


def test_a_row_with_a_cell_the_table_does_not_have_does_not_match() -> None:
    """A value past the header's columns is in the sheet's row, not the
    table's: the rows are not the same."""
    assert not row_matches_anchor(("Retail", 41), "Retail | 41 | see note")


def test_surrounding_whitespace_is_not_a_difference() -> None:
    assert row_matches_anchor(("  Retail ", 41), "Retail | 41")
