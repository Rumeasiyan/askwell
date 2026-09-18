"""CSV/spreadsheet parsing, type and header inference. `M4-CSV-ING-092`.

Pure-function tests only — no database. `raise_table_inference`'s own tests,
which write `schema_notes` and `clarifications`, live in
`test_table_infer_db.py` so the `requires_db` mark stays off this file.
"""

import openpyxl
import pytest

from askwell.table_infer import (
    DateFormatVerdict,
    HeaderVerdict,
    MalformedTable,
    build_candidates,
    detect_date_format,
    detect_header,
    infer_column_types,
    infer_csv,
    infer_xlsx,
    parse_rows,
    sniff_delimiter,
    sniff_encoding,
)

# --- encoding ----------------------------------------------------------------


def test_utf8_bom_is_detected_with_full_confidence() -> None:
    result = sniff_encoding("name,amount\nAnna,10\n".encode("utf-8-sig"))
    assert result.encoding == "utf-8-sig"
    assert result.confidence == 1.0


def test_plain_ascii_reads_as_utf8() -> None:
    result = sniff_encoding(b"name,amount\nAnna,10\n")
    assert result.encoding == "utf-8"
    assert result.confidence == 1.0


def test_windows_1252_is_named_rather_than_reported_as_latin1() -> None:
    # 0x93/0x94 are curly quotes in windows-1252 and undefined in strict utf-8.
    raw = "name,note\nAnna,“paid”\n".encode("windows-1252")
    result = sniff_encoding(raw)
    assert result.encoding == "windows-1252"
    assert result.confidence < 1.0


# --- delimiter -----------------------------------------------------------


def test_comma_delimited_is_detected() -> None:
    result = sniff_delimiter("name,amount,date\nAnna,10,2026-01-01\n")
    assert result.delimiter == ","


def test_semicolon_delimited_is_detected() -> None:
    result = sniff_delimiter("name;amount;date\nAnna;10;2026-01-01\n")
    assert result.delimiter == ";"


def test_tab_delimited_is_detected() -> None:
    result = sniff_delimiter("name\tamount\tdate\nAnna\t10\t2026-01-01\n")
    assert result.delimiter == "\t"


# --- malformed rows --------------------------------------------------------


def test_inconsistent_column_counts_raise_with_row_numbers() -> None:
    text_content = "name,amount\nAnna,10\nBen,20,extra\nCleo,30\n"
    with pytest.raises(MalformedTable) as excinfo:
        parse_rows(text_content, ",")
    assert excinfo.value.row_numbers == [3]
    assert excinfo.value.expected == 2


def test_well_formed_rows_parse_without_error() -> None:
    rows = parse_rows("name,amount\nAnna,10\nBen,20\n", ",")
    assert rows == [["name", "amount"], ["Anna", "10"], ["Ben", "20"]]


# --- header detection --------------------------------------------------------


def test_header_present_is_detected_from_typed_data_beneath_it() -> None:
    rows = [
        ["name", "amount", "date"],
        ["Anna", "10", "2026-01-01"],
        ["Ben", "20", "2026-01-02"],
        ["Cleo", "30", "2026-01-03"],
    ]
    result = detect_header(rows)
    assert result.verdict is HeaderVerdict.PRESENT
    assert result.names == ["name", "amount", "date"]


def test_header_absent_is_detected_rather_than_treated_as_names() -> None:
    rows = [
        ["Anna", "10", "2026-01-01"],
        ["Ben", "20", "2026-01-02"],
        ["Cleo", "30", "2026-01-03"],
    ]
    result = detect_header(rows)
    assert result.verdict is HeaderVerdict.ABSENT
    assert result.names == ["Column 1", "Column 2", "Column 3"]


def test_empty_file_has_no_header() -> None:
    result = detect_header([])
    assert result.verdict is HeaderVerdict.ABSENT


# --- column type inference ----------------------------------------------


def test_integer_column_is_inferred_with_high_confidence() -> None:
    rows = [["10"], ["20"], ["30"]]
    columns = infer_column_types(rows, ["amount"])
    assert columns[0].inferred_type == "integer"
    assert columns[0].confidence == 1.0
    assert not columns[0].ambiguous


def test_mixed_thousands_and_plain_decimal_is_flagged_ambiguous() -> None:
    rows = [["1,200.00"], ["1200.5"], ["980.25"]]
    columns = infer_column_types(rows, ["amount"])
    assert columns[0].ambiguous
    assert "thousands" in (columns[0].ambiguity_reason or "")


def test_a_column_with_no_agreeing_type_is_reported_as_string_and_ambiguous() -> None:
    rows = [["10"], ["banana"], ["2026-01-01"], ["true"]]
    columns = infer_column_types(rows, ["mixed"])
    assert columns[0].inferred_type == "string"
    assert columns[0].ambiguous


def test_an_entirely_empty_column_is_reported_rather_than_guessed() -> None:
    rows = [[""], [""], [""]]
    columns = infer_column_types(rows, ["blank"])
    assert columns[0].ambiguous
    assert columns[0].confidence == 0.0


# --- date format ambiguity (M4-CSV-ING-093) -----------------------------


def test_ambiguous_numeric_dates_are_not_inferred() -> None:
    values = ["01/02/2026", "03/04/2026", "05/06/2026"]
    result = detect_date_format(values)
    assert result.verdict is DateFormatVerdict.AMBIGUOUS


def test_a_day_value_above_twelve_disambiguates_day_first() -> None:
    values = ["01/02/2026", "25/12/2026", "03/04/2026"]
    result = detect_date_format(values)
    assert result.verdict is DateFormatVerdict.DAY_FIRST
    assert result.evidence_value == "25/12/2026"


def test_a_day_value_above_twelve_in_the_second_slot_disambiguates_month_first() -> None:
    values = ["01/02/2026", "12/25/2026", "03/04/2026"]
    result = detect_date_format(values)
    assert result.verdict is DateFormatVerdict.MONTH_FIRST
    assert result.evidence_value == "12/25/2026"


def test_conflicting_disambiguation_within_a_column_is_mixed() -> None:
    values = ["25/12/2026", "12/25/2026"]
    result = detect_date_format(values)
    assert result.verdict is DateFormatVerdict.MIXED


def test_iso_dates_have_nothing_to_disambiguate() -> None:
    values = ["2026-01-01", "2026-02-14"]
    result = detect_date_format(values)
    assert result.verdict is DateFormatVerdict.NOT_APPLICABLE


def test_ambiguous_date_column_raises_a_two_option_question() -> None:
    header_row = ["dt_reg"]
    data = [["01/02/2026"], ["03/04/2026"], ["05/06/2026"]]
    rows = [header_row, *data]
    header = detect_header(rows)
    from askwell.table_infer import HeaderDetection

    header = HeaderDetection(HeaderVerdict.PRESENT, 1.0, header_row, "forced for the test")
    columns = infer_column_types(data, header.names)
    assert columns[0].ambiguous
    assert columns[0].date_format is not None
    assert columns[0].date_format.verdict is DateFormatVerdict.AMBIGUOUS

    candidates = build_candidates("t.csv", header, columns, data)
    date_candidates = [c for c in candidates if c.trigger == "date_format"]
    assert len(date_candidates) == 1
    assert date_candidates[0].options == ["DD/MM/YYYY (day first)", "MM/DD/YYYY (month first)"]


def test_disambiguating_date_column_raises_no_question() -> None:
    header_row = ["dt_reg"]
    data = [["25/12/2026"], ["03/04/2026"], ["05/06/2026"]]
    rows = [header_row, *data]
    header = detect_header(rows)
    from askwell.table_infer import HeaderDetection

    header = HeaderDetection(HeaderVerdict.PRESENT, 1.0, header_row, "forced for the test")
    columns = infer_column_types(data, header.names)
    assert not columns[0].ambiguous
    assert columns[0].date_format is not None
    assert columns[0].date_format.verdict is DateFormatVerdict.DAY_FIRST

    candidates = build_candidates("t.csv", header, columns, data)
    assert not any(c.trigger == "date_format" for c in candidates)
    assert not any("dt_reg" in c.question for c in candidates)


def test_mixed_date_formats_are_reported_as_malformed_not_asked() -> None:
    header_row = ["dt_reg"]
    data = [["25/12/2026"], ["12/25/2026"], ["03/04/2026"]]
    rows = [header_row, *data]
    header = detect_header(rows)
    from askwell.table_infer import HeaderDetection

    header = HeaderDetection(HeaderVerdict.PRESENT, 1.0, header_row, "forced for the test")
    columns = infer_column_types(data, header.names)
    assert columns[0].ambiguous
    assert columns[0].inferred_type == "string"
    assert "malformed" in (columns[0].ambiguity_reason or "")

    candidates = build_candidates("t.csv", header, columns, data)
    assert not any(c.trigger == "date_format" for c in candidates)
    malformed = [c for c in candidates if "dt_reg" in c.question]
    assert malformed and malformed[0].options is None


def test_a_handful_of_ambiguous_rows_is_still_asked() -> None:
    result = detect_date_format(["01/02/2026", "03/04/2026"])
    assert result.verdict is DateFormatVerdict.AMBIGUOUS


# --- candidate clarifications ------------------------------------------------


def test_no_header_raises_a_question_naming_the_column_count() -> None:
    rows = [["Anna", "10"], ["Ben", "20"]]
    header = detect_header(rows)
    columns = infer_column_types(rows, header.names)
    candidates = build_candidates("t.csv", header, columns, rows)
    assert any(c.trigger == "table_header" for c in candidates)


def test_blank_header_cell_raises_a_question_with_value_distribution_evidence() -> None:
    header_row = ["name", "", "date"]
    data = [["Anna", "10", "2026-01-01"], ["Ben", "20", "2026-01-02"]]
    rows = [header_row, *data]
    header = detect_header(rows)
    # Force the present case regardless of the heuristic outcome, since this
    # test is about the blank-cell path specifically.
    from askwell.table_infer import HeaderDetection

    header = HeaderDetection(HeaderVerdict.PRESENT, 1.0, header_row, "forced for the test")
    columns = infer_column_types(data, header.names)
    candidates = build_candidates("t.csv", header, columns, data)
    blank = [c for c in candidates if "Column 2" in c.question]
    assert blank
    assert blank[0].evidence["kind"] == "column_distribution"


def test_mixed_number_format_raises_a_units_and_currency_question() -> None:
    header_row = ["amount"]
    data = [["1,200.00"], ["1200.5"], ["980.25"]]
    rows = [header_row, *data]
    header = detect_header(rows)
    from askwell.table_infer import HeaderDetection

    header = HeaderDetection(HeaderVerdict.PRESENT, 1.0, header_row, "forced for the test")
    columns = infer_column_types(data, header.names)
    candidates = build_candidates("t.csv", header, columns, data)
    assert any("currency" in c.question for c in candidates)


# --- end-to-end CSV parsing ---------------------------------------------


def test_infer_csv_end_to_end_with_header_and_typed_columns() -> None:
    raw = b"name,amount,date\nAnna,10,2026-01-01\nBen,20,2026-01-02\nCleo,30,2026-01-03\n"
    inference = infer_csv("people.csv", raw)
    assert inference.header.verdict is HeaderVerdict.PRESENT
    assert inference.encoding is not None and inference.encoding.encoding == "utf-8"
    assert inference.delimiter is not None and inference.delimiter.delimiter == ","
    assert [c.name for c in inference.columns] == ["name", "amount", "date"]
    assert inference.columns[1].inferred_type == "integer"
    assert inference.row_count == 3


def test_infer_csv_raises_malformed_table_for_ragged_rows() -> None:
    raw = b"name,amount\nAnna,10\nBen,20,extra\n"
    with pytest.raises(MalformedTable):
        infer_csv("bad.csv", raw)


# --- xlsx --------------------------------------------------------------


def _workbook_bytes(rows: list[list[object]], *, merge: str | None = None) -> bytes:
    import io

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    assert sheet is not None
    for row in rows:
        sheet.append(row)
    if merge:
        sheet.merge_cells(merge)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_infer_xlsx_produces_one_table_per_sheet() -> None:
    raw = _workbook_bytes([["name", "amount"], ["Anna", 10], ["Ben", 20]])
    results = infer_xlsx("data.xlsx", raw)
    assert len(results) == 1
    assert results[0].sheet is not None
    assert [c.name for c in results[0].columns] == ["name", "amount"]


def test_a_merged_header_cell_raises_a_clarification_rather_than_a_guess() -> None:
    raw = _workbook_bytes(
        [["group", "", "amount"], ["Anna", "x", 10], ["Ben", "y", 20]], merge="A1:B1"
    )
    results = infer_xlsx("data.xlsx", raw)
    assert results[0].merged_header
    assert any(
        c.trigger == "table_header" and "merged" in c.question for c in results[0].candidates
    )
