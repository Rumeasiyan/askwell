"""Excel extraction's own rules, without a database. `M1-EXTRACT-ING-027`."""

from askwell.extract_xlsx import _row_text


def test_a_row_joins_its_non_empty_cells() -> None:
    assert _row_text(("Widget", 9.99, None)) == "Widget | 9.99"


def test_a_row_of_only_none_is_empty() -> None:
    assert _row_text((None, None)) == ""


def test_whitespace_only_cells_are_dropped() -> None:
    assert _row_text(("  ", "Value", None)) == "Value"
