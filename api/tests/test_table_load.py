"""Loading an inferred table into the sandbox. `M4-CSV-ING-094`.

Pure-function tests only — identifier normalisation, type/cast decisions, and
date parsing, all against literals with no database. Everything that depends
on the real sandbox instance (`_load_inferences` end to end, the reload path,
the caps) is `requires_db` and lives in `test_table_load_db.py`, the same
split `test_table_infer.py`/`test_table_infer_db.py` and
`test_dump_import.py` already use.
"""

from datetime import date

import pytest

from askwell.table_infer import (
    ColumnInference,
    DateFormatDetection,
    DateFormatVerdict,
    infer_csv,
)
from askwell.table_load import (
    RowFailure,
    cast_value,
    normalise_columns,
    normalise_identifier,
    sql_type_for,
)

# --- identifier normalisation -------------------------------------------------


def test_a_valid_identifier_is_only_lowercased() -> None:
    assert normalise_identifier("amount", set()) == "amount"


def test_spaces_and_punctuation_become_underscores() -> None:
    assert normalise_identifier("Reference #", set()) == "reference"
    assert normalise_identifier("Unit Price", set()) == "unit_price"


def test_a_name_starting_with_a_digit_is_prefixed() -> None:
    assert normalise_identifier("2026 total", set()) == "c_2026_total"


def test_an_empty_or_all_punctuation_name_falls_back_to_column() -> None:
    assert normalise_identifier("!!!", set()) == "column"


def test_two_names_that_normalise_the_same_way_are_deduplicated() -> None:
    seen: set[str] = set()
    first = normalise_identifier("Amount", seen)
    second = normalise_identifier("amount!", seen)
    assert first == "amount"
    assert second == "amount_2"


def test_normalise_columns_applies_one_shared_seen_set_in_order() -> None:
    assert normalise_columns(["Name", "name", "Name "]) == ["name", "name_2", "name_3"]


# --- sql_type_for --------------------------------------------------------------


def _column(
    inferred_type: str = "string",
    *,
    ambiguous: bool = False,
    date_format: DateFormatDetection | None = None,
) -> ColumnInference:
    return ColumnInference(
        name="col",
        inferred_type=inferred_type,
        confidence=1.0,
        sample_values=["x"],
        ambiguous=ambiguous,
        date_format=date_format,
    )


def test_an_ambiguous_column_always_loads_as_text() -> None:
    column = _column("decimal", ambiguous=True)
    assert sql_type_for(column, day_first_override=None) == ("text", None)


def test_a_confident_integer_column_maps_to_bigint() -> None:
    column = _column("integer")
    assert sql_type_for(column, day_first_override=None) == ("bigint", None)


def test_a_confident_decimal_column_maps_to_numeric() -> None:
    column = _column("decimal")
    assert sql_type_for(column, day_first_override=None) == ("numeric", None)


def test_a_confident_boolean_column_maps_to_boolean() -> None:
    column = _column("boolean")
    assert sql_type_for(column, day_first_override=None) == ("boolean", None)


def test_a_disambiguated_day_first_date_column_loads_as_date() -> None:
    column = _column(
        "date", date_format=DateFormatDetection(DateFormatVerdict.DAY_FIRST, "13/01/2026", "...")
    )
    assert sql_type_for(column, day_first_override=None) == ("date", True)


def test_a_disambiguated_month_first_date_column_loads_as_date() -> None:
    column = _column(
        "date",
        date_format=DateFormatDetection(DateFormatVerdict.MONTH_FIRST, "01/13/2026", "..."),
    )
    assert sql_type_for(column, day_first_override=None) == ("date", False)


def test_an_iso_only_date_column_needs_no_day_first_decision() -> None:
    column = _column("date", date_format=DateFormatDetection(DateFormatVerdict.NOT_APPLICABLE))
    assert sql_type_for(column, day_first_override=None) == ("date", None)


def test_an_undecided_date_column_loads_as_text_until_an_override_resolves_it() -> None:
    column = _column(
        "date",
        ambiguous=True,
        date_format=DateFormatDetection(DateFormatVerdict.AMBIGUOUS),
    )
    assert sql_type_for(column, day_first_override=None) == ("text", None)
    assert sql_type_for(column, day_first_override=True) == ("date", True)
    assert sql_type_for(column, day_first_override=False) == ("date", False)


# --- cast_value ------------------------------------------------------------


def test_a_blank_cell_casts_to_none_regardless_of_type() -> None:
    assert cast_value("  ", "bigint", None) is None
    assert cast_value("", "text", None) is None


def test_bigint_and_numeric_cast() -> None:
    assert cast_value("42", "bigint", None) == 42
    assert cast_value("1,200.50", "numeric", None) == 1200.5


def test_an_unparseable_integer_raises_value_error() -> None:
    with pytest.raises(ValueError, match=r"not a number|invalid literal"):
        cast_value("abc", "bigint", None)


def test_boolean_recognises_the_documented_spellings() -> None:
    assert cast_value("Yes", "boolean", None) is True
    assert cast_value("0", "boolean", None) is False


def test_an_unrecognised_boolean_raises() -> None:
    with pytest.raises(ValueError, match="not a recognised boolean"):
        cast_value("maybe", "boolean", None)


def test_iso_date_casts_without_a_day_first_decision() -> None:
    assert cast_value("2026-01-13", "date", None) == date(2026, 1, 13)


def test_named_month_date_casts() -> None:
    assert cast_value("4 January 2026", "date", None) == date(2026, 1, 4)


def test_numeric_date_casts_day_first() -> None:
    assert cast_value("13/01/2026", "date", True) == date(2026, 1, 13)


def test_numeric_date_casts_month_first() -> None:
    assert cast_value("01/13/2026", "date", False) == date(2026, 1, 13)


def test_a_numeric_date_with_no_day_first_decision_raises() -> None:
    with pytest.raises(ValueError, match="day/month order was never decided"):
        cast_value("03/04/2026", "date", None)


def test_text_cast_returns_the_value_unchanged() -> None:
    assert cast_value("  Anna  ", "text", None) == "Anna"


# --- row numbering, shared vocabulary with table_infer ------------------------


def test_row_failure_is_a_plain_row_number_and_reason() -> None:
    failure = RowFailure(3, "'abc' is not a number")
    assert failure.row_number == 3
    assert "not a number" in failure.reason


def test_infer_csv_carries_the_data_rows_for_loading_to_use() -> None:
    inference = infer_csv("people.csv", b"name,amount\nAnna,10\nBen,20\n")
    assert inference.rows == [["Anna", "10"], ["Ben", "20"]]
