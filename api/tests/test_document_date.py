"""A document's own date, without a database. `M7-FIX-BE-170a`.

Every acceptance criterion and edge case the ticket names that is decided by
parsing alone: metadata before filename, precision carried rather than
padded, implausible and future dates ignored, two equally specific filename
dates refusing to guess, and a corrupt metadata block falling through rather
than failing. The write itself, and the extractors calling it, are covered
against a real Postgres in `test_document_date_records.py`.
"""

import zipfile
from datetime import date
from pathlib import Path

import pytest

from askwell.db.models import DOCUMENT_DATE_PRECISIONS, DOCUMENT_DATE_SOURCES
from askwell.document_date import (
    PRECISIONS,
    SOURCES,
    DocumentDate,
    from_filename,
    from_ooxml,
    from_pdf_metadata,
    resolve,
)

TODAY = date(2026, 9, 24)


def test_the_model_and_the_module_agree_on_the_allowed_values() -> None:
    assert set(PRECISIONS) == set(DOCUMENT_DATE_PRECISIONS)
    assert set(SOURCES) == set(DOCUMENT_DATE_SOURCES)


# --- filename ---------------------------------------------------------------


def test_the_fixture_store_hours_files_are_a_year_each_from_the_filename() -> None:
    """The ticket's own walkthrough: both years, both from the filename."""
    assert from_filename("store_hours_2025.pdf", today=TODAY) == DocumentDate(
        date(2025, 1, 1), "year", "filename"
    )
    assert from_filename("store_hours_2026.pdf", today=TODAY) == DocumentDate(
        date(2026, 1, 1), "year", "filename"
    )


def test_a_year_is_never_padded_into_a_full_date() -> None:
    found = from_filename("store_hours_2026.pdf", today=TODAY)
    assert found is not None
    assert found.as_iso() == "2026"


@pytest.mark.parametrize(
    ("filename", "iso", "precision"),
    [
        ("minutes_2026-03.docx", "2026-03", "month"),
        ("minutes_2026_03.docx", "2026-03", "month"),
        ("minutes 2026-03-15 final.docx", "2026-03-15", "day"),
        ("minutes_2026_03_15.docx", "2026-03-15", "day"),
        ("FY2024 budget.xlsx", "2024", "year"),
        ("scan_1965.pdf", "1965", "year"),
    ],
)
def test_the_three_filename_shapes(filename: str, iso: str, precision: str) -> None:
    found = from_filename(filename, today=TODAY)
    assert found is not None
    assert (found.as_iso(), found.precision, found.source) == (iso, precision, "filename")


@pytest.mark.parametrize(
    "filename",
    [
        "report_1234.pdf",  # not a plausible year
        "invoice_20500.pdf",  # five digits is a number, not a year
        "invoice_20260315.pdf",  # compact dates are not one of the three shapes
        "plan_2025-26.pdf",  # a span, not a month
        "minutes_2026-13.pdf",  # no thirteenth month
        "minutes_2026-02-30.pdf",  # no thirtieth of February
        "minutes_2026-03_15.pdf",  # separators used inconsistently
        "Handbook.pdf",
        "roadmap_2031.pdf",  # later than today
    ],
)
def test_numbers_that_are_not_dates_are_ignored(filename: str) -> None:
    assert from_filename(filename, today=TODAY) is None


def test_with_two_dates_the_more_specific_wins() -> None:
    found = from_filename("handbook_2025_revised_2026-03-01.pdf", today=TODAY)
    assert found == DocumentDate(date(2026, 3, 1), "day", "filename")


def test_with_two_equally_specific_dates_there_is_no_guess() -> None:
    assert from_filename("handbook_2025_to_2026.pdf", today=TODAY) is None


def test_the_same_date_twice_is_not_ambiguous() -> None:
    assert from_filename("2026_handbook_2026.pdf", today=TODAY) == DocumentDate(
        date(2026, 1, 1), "year", "filename"
    )


def test_this_month_and_this_year_are_not_the_future() -> None:
    assert from_filename("notes_2026.pdf", today=TODAY) is not None
    assert from_filename("notes_2026-09.pdf", today=TODAY) is not None
    assert from_filename("notes_2026-09-24.pdf", today=TODAY) is not None
    assert from_filename("notes_2026-09-25.pdf", today=TODAY) is None
    assert from_filename("notes_2026-10.pdf", today=TODAY) is None


# --- PDF /Info --------------------------------------------------------------


def test_a_pdf_mod_date_is_used_before_its_creation_date() -> None:
    """A second version is usually the first one re-saved: created stays,
    modified moves."""
    found = from_pdf_metadata(
        {"CreationDate": "D:20250110090000Z", "ModDate": "D:20260302101500+05'30'"}, today=TODAY
    )
    assert found == DocumentDate(date(2026, 3, 2), "day", "metadata")


def test_a_pdf_creation_date_alone_is_enough() -> None:
    found = from_pdf_metadata({"CreationDate": "D:20240615", "ModDate": ""}, today=TODAY)
    assert found == DocumentDate(date(2024, 6, 15), "day", "metadata")


def test_a_pdf_date_keeps_the_precision_it_was_written_with() -> None:
    assert from_pdf_metadata({"CreationDate": "D:2024"}, today=TODAY) == DocumentDate(
        date(2024, 1, 1), "year", "metadata"
    )
    assert from_pdf_metadata({"CreationDate": "D:202406"}, today=TODAY) == DocumentDate(
        date(2024, 6, 1), "month", "metadata"
    )


def test_a_future_pdf_date_is_ignored_and_the_other_one_used() -> None:
    found = from_pdf_metadata(
        {"CreationDate": "D:20240615", "ModDate": "D:20310101000000Z"}, today=TODAY
    )
    assert found == DocumentDate(date(2024, 6, 15), "day", "metadata")


def test_a_future_pdf_date_alone_is_no_date() -> None:
    assert from_pdf_metadata({"CreationDate": "D:20310101000000Z"}, today=TODAY) is None


@pytest.mark.parametrize("raw", ["garbage", "D:19800101", "D:20261399", "", "D:"])
def test_an_unreadable_or_implausible_pdf_date_is_no_date(raw: str) -> None:
    assert from_pdf_metadata({"CreationDate": raw, "ModDate": raw}, today=TODAY) is None


# --- OOXML core properties -----------------------------------------------------

_CORE = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/'
    'metadata/core-properties" xmlns:dcterms="http://purl.org/dc/terms/" '
    'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">{body}</cp:coreProperties>'
)


def _package(path: Path, core: str | None) -> str:
    with zipfile.ZipFile(path, "w") as package:
        package.writestr("[Content_Types].xml", "<Types/>")
        if core is not None:
            package.writestr("docProps/core.xml", core)
    return str(path)


def test_ooxml_modified_is_used_before_created(tmp_path: Path) -> None:
    core = _CORE.format(
        body='<dcterms:created xsi:type="dcterms:W3CDTF">2025-01-10T09:00:00Z</dcterms:created>'
        '<dcterms:modified xsi:type="dcterms:W3CDTF">2026-03-02T10:15:00Z</dcterms:modified>'
    )
    found = from_ooxml(_package(tmp_path / "a.docx", core), today=TODAY)
    assert found == DocumentDate(date(2026, 3, 2), "day", "metadata")


def test_ooxml_created_alone_is_enough(tmp_path: Path) -> None:
    core = _CORE.format(body="<dcterms:created>2024-06-15T00:00:00Z</dcterms:created>")
    found = from_ooxml(_package(tmp_path / "a.xlsx", core), today=TODAY)
    assert found == DocumentDate(date(2024, 6, 15), "day", "metadata")


def test_ooxml_with_no_core_properties_is_no_date(tmp_path: Path) -> None:
    assert from_ooxml(_package(tmp_path / "a.pptx", None), today=TODAY) is None


def test_ooxml_future_dates_are_ignored(tmp_path: Path) -> None:
    core = _CORE.format(body="<dcterms:created>2031-01-01T00:00:00Z</dcterms:created>")
    assert from_ooxml(_package(tmp_path / "a.docx", core), today=TODAY) is None


@pytest.mark.parametrize(
    "core", ["<not xml", _CORE.format(body="<dcterms:created>soon</dcterms:created>")]
)
def test_corrupt_ooxml_core_properties_are_no_date_not_a_failure(tmp_path: Path, core: str) -> None:
    assert from_ooxml(_package(tmp_path / "a.docx", core), today=TODAY) is None


def test_a_file_that_is_not_a_zip_is_no_date_not_a_failure(tmp_path: Path) -> None:
    path = tmp_path / "a.docx"
    path.write_bytes(b"not a zip")
    assert from_ooxml(str(path), today=TODAY) is None


def test_an_entity_expansion_bomb_is_refused_not_expanded(tmp_path: Path) -> None:
    bomb = (
        '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaaaaaaaa">'
        '<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;"><!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">'
        '<!ENTITY d "&c;&c;&c;&c;&c;&c;&c;&c;&c;&c;"><!ENTITY e "&d;&d;&d;&d;&d;&d;&d;&d;&d;&d;">'
        '<!ENTITY f "&e;&e;&e;&e;&e;&e;&e;&e;&e;&e;"><!ENTITY g "&f;&f;&f;&f;&f;&f;&f;&f;&f;&f;">'
        '<!ENTITY h "&g;&g;&g;&g;&g;&g;&g;&g;&g;&g;">]><x>&h;</x>'
    )
    assert from_ooxml(_package(tmp_path / "a.docx", bomb), today=TODAY) is None


# --- precedence ---------------------------------------------------------------


def test_metadata_wins_over_the_filename() -> None:
    metadata = DocumentDate(date(2026, 3, 2), "day", "metadata")
    assert resolve(metadata, "store_hours_2025.pdf", today=TODAY) == metadata


def test_no_metadata_falls_through_to_the_filename() -> None:
    assert resolve(None, "store_hours_2025.pdf", today=TODAY) == DocumentDate(
        date(2025, 1, 1), "year", "filename"
    )


def test_neither_is_null() -> None:
    assert resolve(None, "Handbook.pdf", today=TODAY) is None
