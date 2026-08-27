"""Word extraction. `M1-EXTRACT-ING-027`.

**`python-docx`, MIT-licensed.** Reads the OOXML `.docx` format directly;
legacy binary `.doc` is a separate container it cannot open at all — tracked
as a known gap rather than guessed at, filed as a follow-up (issue #121).

**Tracked changes: the accepted text, by construction.** `python-docx` builds
`paragraph.text` from `<w:t>` runs only. An accepted insertion (`<w:ins>`)
wraps ordinary runs and is included; a deletion (`<w:del>`) wraps `<w:delText>`
instead, a different tag `python-docx` never reads — so nothing here has to
choose which text is "the" text. Their *presence* is a separate fact the
ticket's edge case asks be noted, and is logged rather than injected into the
extracted text, which would put an editorial mark where the document has none.

**Page anchors are honest about being approximate.** Nothing renders this
document, so there is no true page break — only the ones an author inserted
explicitly (`<w:br w:type="page"/>`). A document with none of those is one
page; the label says "approximate" rather than claiming a page number Word
itself would only produce by opening the file.

**Table boundaries survive as markers, not as a table.** `document_pages.text`
is read back as passages by chunking (`M1-INDEX-ING-031`, not yet built) —
markers a chunker can still see as structure without needing a table type of
its own.
"""

import asyncio
from typing import TYPE_CHECKING

from docx import Document as open_document
from docx.document import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from askwell.extract_common import Anchor, write_anchors
from askwell.logging import get_logger

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from askwell.ingest import Report, Work

log = get_logger(__name__)

ANCHOR_KIND = "page"

_PAGE_BREAK_TYPE = "page"


def _iter_block_items(document: Document) -> list[Paragraph | Table]:
    """Paragraphs and tables, in the order they appear in the body.

    `document.paragraphs` and `document.tables` are two separate lists in
    `python-docx` and lose that order entirely; walking `document.element.body`
    directly is the documented way to get it back.
    """
    items: list[Paragraph | Table] = []
    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            items.append(Paragraph(child, document))
        elif child.tag == qn("w:tbl"):
            items.append(Table(child, document))
    return items


def _has_page_break(paragraph: Paragraph) -> bool:
    for run in paragraph.runs:
        for br in run._element.findall(qn("w:br")):
            if br.get(qn("w:type")) == _PAGE_BREAK_TYPE:
                return True
    return False


def _paragraph_text(paragraph: Paragraph) -> str:
    style_name = paragraph.style.name if paragraph.style is not None else None
    body = paragraph.text
    if not body.strip():
        return ""
    if style_name and style_name.startswith("Heading"):
        digits = "".join(ch for ch in style_name if ch.isdigit())
        level = min(int(digits), 6) if digits else 1
        return f"{'#' * level} {body}"
    if style_name and style_name.startswith("List Bullet"):
        return f"- {body}"
    if style_name and style_name.startswith("List Number"):
        return f"1. {body}"
    return body


def _table_text(table: Table) -> str:
    lines = ["[TABLE]"]
    for row in table.rows:
        lines.append(" | ".join(cell.text.strip() for cell in row.cells))
    lines.append("[/TABLE]")
    return "\n".join(lines)


def _has_revisions(document: Document) -> bool:
    body = document.element.body
    return next(body.iter(qn("w:ins")), None) is not None or (
        next(body.iter(qn("w:del")), None) is not None
    )


def _load(path: str) -> Document:
    return open_document(path)


async def run(work: "Work", report: "Report", factory: "async_sessionmaker[AsyncSession]") -> None:
    document = await asyncio.to_thread(_load, work.path)
    has_revisions = _has_revisions(document)

    sections: list[list[str]] = [[]]
    for block in _iter_block_items(document):
        if isinstance(block, Table):
            sections[-1].append(_table_text(block))
            continue
        piece = _paragraph_text(block)
        if piece:
            sections[-1].append(piece)
        if _has_page_break(block):
            sections.append([])

    if len(sections) > 1 and not sections[-1]:
        sections.pop()

    approximate = len(sections) > 1
    anchors: list[Anchor] = []
    for index, lines in enumerate(sections, start=1):
        body = "\n\n".join(lines).strip()
        anchors.append(
            Anchor(
                page_number=index,
                label=f"page {index} (approximate)" if approximate else None,
                text=body or None,
                has_text=bool(body),
            )
        )
        await report(index, len(sections))

    await write_anchors(factory, work, anchors, ANCHOR_KIND)

    log.info(
        "extract_docx_completed",
        document_id=str(work.document_id),
        filename=work.filename,
        sections=len(sections),
        has_revisions=has_revisions,
    )
