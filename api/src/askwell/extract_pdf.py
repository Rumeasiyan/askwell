"""PDF text-layer extraction. `M1-EXTRACT-ING-026`.

**pypdfium2, not PyMuPDF.** PyMuPDF is AGPL and would force Askwell off
Apache-2.0; pypdfium2 is BSD-3/Apache-2.0 dual-licensed. The accepted cost is
recorded in `docs/decisions.md`: passage-level coordinates are harder to get
at, which is why scanned-page highlighting starts at page level rather than a
pixel region.

**Every page becomes a row, whether or not it has text.** `document_pages`
holds one per page — `has_text = false` and `text = NULL` are as much a result
as a page full of prose. Skipping a blank page instead of recording it would
mean the OCR ticket (`M1-EXTRACT-ING-028`) has no way to find it, and a
document that is half scans and half text layer is the ordinary case, not the
exception — the ticket's own edge case is "mixed handling per page, not per
document".

**Rotation needs no code here.** `page.get_rotation()` reports `/Rotate`,
which pdfium's own text extraction already accounts for — a page written
upside-down and marked so extracts in reading order without this module doing
anything about it, which was checked against a page built with `/Rotate 90`
before writing this module, not assumed.

**Reading order is best-effort, and that limit is stated rather than solved.**
`get_text_range()` walks pdfium's text object stream, which is reading order
for the ordinary single-column case and is not guaranteed for multi-column
layouts — a real per-column reconstruction needs the character boxes
(`get_charbox`) clustered into columns, which is real work this ticket's
granularity ("one format, one extractor") does not include. Known gap, not a
silent one.

**A document with no usable text anywhere raises `NeedsOCR` rather than
finishing.** Chunking an empty document is C5's failure wearing a different
hat: it would tell retrieval a document has nothing to say, when the truth is
that nothing has read it yet. A *partly* usable document is not this case —
see the module's per-page recording above — only a document where every page
came back empty routes here.
"""

import asyncio
from typing import TYPE_CHECKING

import pypdfium2 as pdfium
from sqlalchemy import text

from askwell.db.engine import session_scope
from askwell.logging import get_logger

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from askwell.ingest import Report, Work

log = get_logger(__name__)

# A character is "junk" if it is the Unicode replacement character — pdfium's
# stand-in for a glyph it could not map back to text, which is exactly what an
# embedded subset font with no usable encoding produces — or a control
# character other than the whitespace pdfium legitimately inserts between
# lines. A page that is mostly junk is functionally unreadable even though
# `get_text_range` returned a non-empty string, and the ticket's edge case
# ("embedded fonts that produce unusable characters") asks for exactly that to
# be treated as no usable text.
_JUNK = "�"
JUNK_RATIO_THRESHOLD = 0.3


class NeedsOCR(Exception):
    """This file has no usable text layer at all; only OCR can read it.

    Not a failure — nothing is wrong with the PDF. Caught by
    `askwell.ingest.process`, which parks the document naming
    `M1-EXTRACT-ING-028` rather than marking it failed or, worse, `ready` with
    nothing chunkable in it.
    """


def _page_text(document: pdfium.PdfDocument, index: int) -> str:  # type: ignore[no-any-unimported]
    """The blocking half: open one page's text page and read it.

    Kept to one page at a time, run through `asyncio.to_thread`, rather than
    one call over the whole document — a 900-page file is "extracted with
    progress rather than one long silence" only if control returns to the
    event loop, and therefore to `report`, between pages.
    """
    page = document.get_page(index)
    try:
        text_page = page.get_textpage()
        try:
            return str(text_page.get_text_range())
        finally:
            text_page.close()
    finally:
        page.close()


def _usable(page_text: str) -> bool:
    stripped = page_text.strip()
    if not stripped:
        return False
    junk = sum(1 for ch in stripped if ch == _JUNK or (ord(ch) < 32 and ch not in "\n\t\r"))
    return (junk / len(stripped)) < JUNK_RATIO_THRESHOLD


async def run(work: "Work", report: "Report", factory: "async_sessionmaker[AsyncSession]") -> None:
    document = await asyncio.to_thread(pdfium.PdfDocument, work.path)
    try:
        page_count = len(document)
        pages: list[tuple[int, str | None, bool]] = []

        for index in range(page_count):
            raw = await asyncio.to_thread(_page_text, document, index)
            usable = _usable(raw)
            pages.append((index + 1, raw if raw.strip() else None, usable))
            await report(index + 1, page_count)
    finally:
        document.close()

    usable_pages = sum(1 for _, _, has_text in pages if has_text)

    async with session_scope(factory) as session:
        await session.execute(
            text(
                "UPDATE documents SET page_count = :page_count, anchor_kind = 'page' WHERE id = :id"
            ),
            {"page_count": page_count, "id": work.document_id},
        )
        for page_number, page_text, has_text in pages:
            await session.execute(
                text(
                    "INSERT INTO document_pages (document_id, page_number, text, has_text) "
                    "VALUES (:document_id, :page_number, :text, :has_text) "
                    "ON CONFLICT (document_id, page_number) "
                    "DO UPDATE SET text = EXCLUDED.text, has_text = EXCLUDED.has_text"
                ),
                {
                    "document_id": work.document_id,
                    "page_number": page_number,
                    "text": page_text,
                    "has_text": has_text,
                },
            )

    log.info(
        "extract_pdf_completed",
        document_id=str(work.document_id),
        filename=work.filename,
        pages=page_count,
        pages_with_text=usable_pages,
    )

    if page_count == 0 or usable_pages == 0:
        raise NeedsOCR
