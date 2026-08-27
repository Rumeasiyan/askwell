"""Structure-aware chunking. `M1-INDEX-ING-031`.

`document_pages.text` already carries the structure the extractors found —
Markdown-style `#` headings, `[TABLE]`/`[/TABLE]` markers with `|`-separated
rows, `-`/`1.` list items (`extract_docx`, `extract_pptx`, `extract_text`) —
or nothing at all beyond raw prose (`extract_pdf`, OCR). This module reads
that structure rather than re-discovering it, and never cuts a table row
away from the header it needs to mean anything: **a chunk that splits a
table row from its header is a defect**, per the ticket's own framing.

**Blocks are atomic, and merged rather than resliced.** A page's text is
first parsed into headings, tables, list runs and paragraphs; anything
individually larger than the hard maximum is pre-split *within its own
kind* — a table by row (repeating the header on every part), a list by
item, a paragraph by sentence with overlap — so the merge pass afterwards
only ever has to decide whether a whole, already-sized fragment fits in the
chunk it is building. That keeps a table row from ever being cut through by
a size-driven boundary that knows nothing about what a row is.

**A heading is metadata, not a duplicated line of content.** Encountering
one closes whatever chunk was open and becomes every following chunk's
`heading` column until the next one — `chunks.heading` is where "which
section is this passage from" lives, not a repeated string burned into
`content` on every fragment beneath it.

**A slide is its own chunk, not a size bucket.** `documents.anchor_kind =
'slide'` never merges two slides into one chunk — one slide is one chunk
unless it alone is long enough to need splitting, matching the ticket's own
edge case. Every other kind (`page`, `heading`, `sheet_row`) merges freely
across anchors up to the target, which is what turns a heading-free PDF
into sentence-bounded chunks instead of one per page.

**The hard maximum is guaranteed by construction, not by intention alone.**
`_enforce_max` is a last, dumb whitespace-boundary split applied to every
finished chunk regardless of how it was built — the one path that lets
`No chunk may exceed the hard maximum` hold even against a pathological
input none of the structural logic anticipated (a single sentence with no
punctuation for ten thousand characters, say).

Sizes are plain module constants, matching `askwell.ingest`'s own
`PROGRESS_INTERVAL_SECONDS`-style tunables, rather than `Settings` fields:
`StageFn` (`askwell.ingest`) hands a stage the file, a progress callback and
a session factory — nothing here needs the rest of configuration, and
adding a `Settings` parameter to every stage for one tunable would be a
wider change than this ticket's own scope.
"""

import re
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import text

from askwell.db.engine import session_scope
from askwell.logging import get_logger

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from askwell.ingest import Report, Work

log = get_logger(__name__)

# The size a chunk aims for, and the size it may never cross. 1,600/2,400
# characters is a plain-prose estimate (~400/~600 tokens at ~4 characters a
# token) rather than a measured figure — nothing has been evaluated yet
# (`AGENTS.md` §4: eval arrives with M2) — chosen to sit comfortably inside
# both the embedding model's context and a retrieved passage a person can
# still read in a source card without it dominating the provenance margin.
CHUNK_TARGET_CHARS = 1600
CHUNK_HARD_MAX_CHARS = 2400

# How much of a chunk's tail is repeated at the start of the next one when a
# single paragraph has to be split by sentence — the ticket's own edge case,
# "split with overlap so a sentence is never orphaned". Only paragraph
# splitting uses this; a table or list split repeats its header or nothing,
# never a content tail, because there is no sentence to protect.
CHUNK_OVERLAP_CHARS = 200

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_LIST_ITEM = re.compile(r"^(?:[-*]\s+|\d+\.\s+)")
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")
_TABLE_OPEN = "[TABLE]"
_TABLE_CLOSE = "[/TABLE]"

# `documents.anchor_kind` values that mean "one structural unit per anchor,
# never merge two of them into one chunk" — today just slides
# (`extract_pptx`'s own edge case). `page`, `heading` and `sheet_row` merge
# freely; a PDF or a prose document is exactly the case that needs several
# pages folded into one chunk to reach a useful size at all.
_ISOLATED_ANCHOR_KINDS = frozenset({"slide"})


class NoChunkableText(Exception):
    """Every page extraction found text in produced nothing a chunker could
    turn into a passage — content that was pure whitespace once assembled,
    for instance. Distinct from `extract_common.EmptyDocument`: extraction
    already found and recorded text, so this is a chunking-time surprise,
    not a re-statement of an emptier document."""


@dataclass(frozen=True, slots=True)
class _Fragment:
    """One already-sized piece ready for the merge pass: a heading (metadata
    only, no content of its own) or a content piece guaranteed to fit within
    `CHUNK_HARD_MAX_CHARS` on its own."""

    kind: str  # "heading" | "content"
    page: int
    text: str


@dataclass(frozen=True, slots=True)
class _ChunkDraft:
    content: str
    page_from: int
    page_to: int
    heading: str | None


def _split_table(header: str | None, body_rows: list[str], hard_max: int) -> list[str]:
    """Split a table by row, repeating the header on every part.

    The ticket's own edge case: "a table longer than the maximum chunk
    size — split with the header repeated on each part."
    """

    def render(rows: list[str]) -> str:
        lines = [_TABLE_OPEN]
        if header is not None:
            lines.append(header)
        lines.extend(rows)
        lines.append(_TABLE_CLOSE)
        return "\n".join(lines)

    if not body_rows:
        return [render([])]

    parts: list[str] = []
    current: list[str] = []
    for row in body_rows:
        candidate = render([*current, row])
        if current and len(candidate) > hard_max:
            parts.append(render(current))
            current = [row]
        else:
            current.append(row)
    if current:
        parts.append(render(current))
    return parts


def _split_list(items: list[str], hard_max: int) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    for item in items:
        candidate = "\n".join([*current, item])
        if current and len(candidate) > hard_max:
            parts.append("\n".join(current))
            current = [item]
        else:
            current.append(item)
    if current:
        parts.append("\n".join(current))
    return parts


def _split_paragraph(paragraph: str, target: int, hard_max: int, overlap: int) -> list[str]:
    """Sentence-bounded split with overlap — the ticket's edge case for "a
    single paragraph longer than the maximum"."""
    sentences = [piece.strip() for piece in _SENTENCE_BOUNDARY.split(paragraph) if piece.strip()]
    if not sentences:
        return []

    parts: list[str] = []
    current = ""
    for sentence in sentences:
        candidate = f"{current} {sentence}".strip() if current else sentence
        if current and len(candidate) > hard_max:
            parts.append(current)
            tail = current[-overlap:].strip() if overlap else ""
            current = f"{tail} {sentence}".strip() if tail else sentence
        elif current and len(candidate) > target:
            parts.append(candidate)
            current = candidate[-overlap:].strip() if overlap else ""
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts


def _enforce_max(content: str, hard_max: int) -> list[str]:
    """The last word: whatever the structural logic produced, no piece
    leaves this function longer than `hard_max`. A whitespace-boundary
    split, applied only when something upstream still overshot — the
    guarantee behind `No chunk may exceed the hard maximum`, held even
    against input none of the structural rules anticipated."""
    if len(content) <= hard_max:
        return [content]

    words = content.split(" ")
    parts: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip() if current else word
        if current and len(candidate) > hard_max:
            parts.append(current)
            current = word
        else:
            current = candidate
    if current:
        parts.append(current)

    final: list[str] = []
    for part in parts:
        if len(part) <= hard_max:
            final.append(part)
        else:
            final.extend(part[index : index + hard_max] for index in range(0, len(part), hard_max))
    return final


def _page_fragments(page: int, content: str, hard_max: int) -> list[_Fragment]:
    """Parse one page's text into headings and already-sized content pieces,
    in document order."""
    fragments: list[_Fragment] = []
    lines = content.splitlines()
    paragraph: list[str] = []

    def flush_paragraph() -> None:
        if not paragraph:
            return
        body = "\n".join(paragraph).strip()
        paragraph.clear()
        if not body:
            return
        if len(body) <= hard_max:
            fragments.append(_Fragment("content", page, body))
        else:
            for part in _split_paragraph(body, CHUNK_TARGET_CHARS, hard_max, CHUNK_OVERLAP_CHARS):
                fragments.append(_Fragment("content", page, part))

    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if not stripped:
            flush_paragraph()
            index += 1
            continue

        heading = _HEADING.match(stripped)
        if heading:
            flush_paragraph()
            fragments.append(_Fragment("heading", page, heading.group(2).strip()))
            index += 1
            continue

        if stripped == _TABLE_OPEN:
            flush_paragraph()
            index += 1
            rows: list[str] = []
            while index < len(lines) and lines[index].strip() != _TABLE_CLOSE:
                rows.append(lines[index])
                index += 1
            index += 1  # past the closing marker, if the table was well-formed
            header = rows[0] if len(rows) > 1 else None
            body_rows = rows[1:] if header is not None else rows
            wrapped = "\n".join([_TABLE_OPEN, *rows, _TABLE_CLOSE])
            if len(wrapped) <= hard_max:
                fragments.append(_Fragment("content", page, wrapped))
            else:
                for part in _split_table(header, body_rows, hard_max):
                    fragments.append(_Fragment("content", page, part))
            continue

        if _LIST_ITEM.match(stripped):
            flush_paragraph()
            items = [stripped]
            index += 1
            while index < len(lines) and _LIST_ITEM.match(lines[index].strip()):
                items.append(lines[index].strip())
                index += 1
            wrapped = "\n".join(items)
            if len(wrapped) <= hard_max:
                fragments.append(_Fragment("content", page, wrapped))
            else:
                for part in _split_list(items, hard_max):
                    fragments.append(_Fragment("content", page, part))
            continue

        paragraph.append(line)
        index += 1

    flush_paragraph()
    return fragments


def _merge(
    pages: list[tuple[int, list[_Fragment]]],
    anchor_kind: str | None,
    target: int,
    hard_max: int,
) -> list[_ChunkDraft]:
    """Greedily pack fragments into chunks up to `target`, never crossing
    `hard_max` for a single append, resetting between anchors that must
    never share a chunk (slides) and on every heading."""
    drafts: list[str] = []
    draft_len = 0
    page_from: int | None = None
    page_to: int | None = None
    active_heading: str | None = None
    results: list[_ChunkDraft] = []

    def flush() -> None:
        nonlocal drafts, draft_len, page_from, page_to
        if drafts and page_from is not None and page_to is not None:
            content = "\n\n".join(drafts).strip()
            if content:
                results.append(_ChunkDraft(content, page_from, page_to, active_heading))
        drafts = []
        draft_len = 0
        page_from = page_to = None

    for _page_number, fragments in pages:
        if anchor_kind in _ISOLATED_ANCHOR_KINDS and drafts:
            flush()

        for fragment in fragments:
            if fragment.kind == "heading":
                flush()
                active_heading = fragment.text
                continue

            separator = 2 if drafts else 0
            addition = len(fragment.text) + separator
            if drafts and draft_len + addition > hard_max:
                flush()
                separator = 0
                addition = len(fragment.text)

            drafts.append(fragment.text)
            draft_len += addition
            page_from = fragment.page if page_from is None else min(page_from, fragment.page)
            page_to = fragment.page if page_to is None else max(page_to, fragment.page)

            if draft_len >= target:
                flush()

    flush()
    return results


def _finalize(drafts: list[_ChunkDraft], hard_max: int) -> list[_ChunkDraft]:
    finalized: list[_ChunkDraft] = []
    for draft in drafts:
        for part in _enforce_max(draft.content, hard_max):
            stripped = part.strip()
            if stripped:
                finalized.append(
                    _ChunkDraft(stripped, draft.page_from, draft.page_to, draft.heading)
                )
    return finalized


async def run(work: "Work", report: "Report", factory: "async_sessionmaker[AsyncSession]") -> None:
    async with session_scope(factory) as session:
        anchor_kind = (
            await session.execute(
                text("SELECT anchor_kind FROM documents WHERE id = :id"),
                {"id": work.document_id},
            )
        ).scalar_one()
        page_rows = (
            await session.execute(
                text(
                    "SELECT page_number, text FROM document_pages "
                    "WHERE document_id = :id AND has_text = true ORDER BY page_number"
                ),
                {"id": work.document_id},
            )
        ).all()

    total_pages = len(page_rows)
    pages: list[tuple[int, list[_Fragment]]] = []
    for index, (page_number, page_text) in enumerate(page_rows, start=1):
        fragments = _page_fragments(int(page_number), page_text or "", CHUNK_HARD_MAX_CHARS)
        pages.append((int(page_number), fragments))
        await report(index, total_pages)

    merged = _merge(pages, anchor_kind, CHUNK_TARGET_CHARS, CHUNK_HARD_MAX_CHARS)
    chunks = _finalize(merged, CHUNK_HARD_MAX_CHARS)

    if not chunks:
        raise NoChunkableText(
            f"Askwell extracted text from {work.filename} but could not split it into any "
            "passages to index."
        )

    async with session_scope(factory) as session:
        await session.execute(
            text("DELETE FROM chunks WHERE document_id = :id"), {"id": work.document_id}
        )
        for ordinal, chunk in enumerate(chunks):
            await session.execute(
                text(
                    "INSERT INTO chunks "
                    "(id, document_id, ordinal, page_from, page_to, heading, content) "
                    "VALUES (:id, :document_id, :ordinal, :page_from, :page_to, :heading, :content)"
                ),
                {
                    "id": uuid.uuid4(),
                    "document_id": work.document_id,
                    "ordinal": ordinal,
                    "page_from": chunk.page_from,
                    "page_to": chunk.page_to,
                    "heading": chunk.heading,
                    "content": chunk.content,
                },
            )

    # Local counter only, per the ticket's own analytics line — a log line
    # nothing transmits (C1), matching every other per-document count this
    # pipeline already writes (`extract_pdf_completed pages=…`, and so on).
    log.info(
        "chunk_completed",
        document_id=str(work.document_id),
        filename=work.filename,
        chunks=len(chunks),
    )
