"""Extraction stage dispatch, by the media type `askwell.filetypes` decided
at add time. `M1-EXTRACT-ING-027`.

`M1-EXTRACT-ING-026` built one extractor for one format and wired it straight
into `askwell.ingest.STAGES` as `extract`'s `run`. A second format makes that
wiring wrong: `extract` is one pipeline stage that now has to cover seven
media types, and something has to choose which module actually reads a given
file. This is that choice, made once here rather than once per caller, from
`Work.mime` — the value the server decided from the file's own bytes, never
re-derived.

**Legacy binary Office (`.doc`, `.xls`, `.ppt`) is a known gap, not a crash.**
`askwell.filetypes` already routes them to `files` as `supported` — the
signature check happened first, before this ticket existed to read them —
and none of `python-docx`, `python-pptx` or `openpyxl` opens the pre-2007
binary container at all. Raising a named exception here means a document in
one of these formats fails with a reason a person can read
(`docs/data-sources.md` §6: "never silently dropped"), rather than an
`AttributeError` three frames into a library that was never going to work.
Filed as a follow-up: issue #121.

**A document's own date is recorded here for every format but PDF.**
`M7-FIX-BE-170a`: OOXML core properties live in the same zip every Office
format shares, so they are read once here (`askwell.document_date.from_ooxml`)
rather than three times in three extractors; text-like formats carry no
metadata date, and get the filename's or none. PDF records its own, from the
`/Info` dictionary of the document `extract_pdf` already has open — reading it
here would open the file twice.
"""

import asyncio
from typing import TYPE_CHECKING

from askwell import (
    document_date,
    extract_docx,
    extract_pdf,
    extract_pptx,
    extract_text,
    extract_xlsx,
)
from askwell.extract_common import check_readable
from askwell.logging import get_logger

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from askwell.config import Settings
    from askwell.ingest import Report, Work

log = get_logger(__name__)

_PDF = "application/pdf"
_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_HTML = "text/html"
_MARKDOWN = "text/markdown"
_PLAIN = "text/plain"

_TEXT_LIKE = frozenset({_HTML, _MARKDOWN, _PLAIN})
_OOXML = frozenset({_DOCX, _PPTX, _XLSX})

_LEGACY_OFFICE = {
    "application/msword": "an older .doc Word file",
    "application/vnd.ms-excel": "an older .xls workbook",
    "application/vnd.ms-powerpoint": "an older .ppt deck",
}


class UnsupportedForExtraction(Exception):
    """No extractor reads this media type, whether known-legacy or unknown.

    Not caught specially — `askwell.ingest.process`'s generic `except
    Exception` is exactly the failure path this belongs to, and this
    exception's message is what a person reads as the reason.
    """


async def run(
    work: "Work",
    report: "Report",
    factory: "async_sessionmaker[AsyncSession]",
    _settings: "Settings",
) -> None:
    check_readable(work)
    if work.mime == _PDF:
        await extract_pdf.run(work, report, factory)
        return
    if work.mime == _DOCX:
        await extract_docx.run(work, report, factory)
    elif work.mime == _PPTX:
        await extract_pptx.run(work, report, factory)
    elif work.mime == _XLSX:
        await extract_xlsx.run(work, report, factory)
    elif work.mime in _TEXT_LIKE:
        await extract_text.run(work, report, factory)
    elif work.mime in _LEGACY_OFFICE:
        raise UnsupportedForExtraction(
            f"{work.filename} is {_LEGACY_OFFICE[work.mime]}. Askwell does not "
            "read the older binary Office formats yet — re-save it in the "
            "modern format, or track progress on issue #121."
        )
    else:
        raise UnsupportedForExtraction(
            f"Askwell has no extractor for {work.mime!r} ({work.filename})."
        )
    metadata = (
        await asyncio.to_thread(document_date.from_ooxml, work.path)
        if work.mime in _OOXML
        else None
    )
    await document_date.record(factory, work, metadata)
