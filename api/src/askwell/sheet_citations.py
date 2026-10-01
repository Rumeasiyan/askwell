"""A SQL answer from a workbook's sheet cites the workbook. `M11-FIX-BE-231`.

Since `M11-FIX-ING-224` a folder's workbooks are both passages and tables,
and a question the passages could not answer reaches the sheet's table. That
answer showed its query and rows and cited nothing, which is the C4 gap
#857 names: the citation is the only check the person has. The workbook is
also a document, and its `sheet_row` anchors already say which sheet and
which row each line of text came from, so the answer cites those.

**A row is cited only when it is a row the query returned (C4).** A result
row carries only what the query projected, so the rows behind it are read
again with `askwell.sql.provenance`: the same filter, the table's whole row
after the projected columns, every row the filter admits. A returned row is
resolved to table rows only when the number of rows with its projected
values equals the number returned with them. Then all of them were
returned, whatever `ORDER BY` and `LIMIT` did. A tie the limit cut has more,
and is not resolved (#896). Each resolved table row is then found among the
sheet's anchors by its cell values, the way extraction wrote them.

**Otherwise the sheet is cited, never a row.** An aggregate, a join, a
`DISTINCT`, a tie, or more than `MAX_CITED_ROWS` rows: the answer came from
the sheet, and the citation says that much and no more. Its passage is the
one holding the sheet's header row.

**Only what the document says now.** Anchors are read from the workbook's
live document, and passages from its live chunks: a passage a re-index
retired is never cited (`chunks.superseded_at`). A cited passage must contain
the anchor's text, so a passage whose page range covers a row it no longer
says is not cited either. A resolved row the live sheet no longer has means
the table and the document disagree, and then nothing is cited: a sheet
citation would show a passage contradicting the answer.

Everything here reads; the provenance query goes through `validate_query`,
the row limit and the read-only role like any other (C2, C3). Retrieved
content stays data (C7): a citation carries a passage to display, and
nothing here puts it in a prompt.
"""

import uuid
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from askwell import crypto, passphrase
from askwell.config import Settings
from askwell.extract_xlsx import ANCHOR_KIND
from askwell.logging import get_logger
from askwell.retrieve import Candidate
from askwell.sql import execute as sql_execute_checked
from askwell.sql.limit import inject_limit
from askwell.sql.provenance import plan_provenance, referenced_tables
from askwell.sql.validate import validate_query
from askwell.table_load import live_workbook, sheet_of_table, workbook_tables

log = get_logger(__name__)

# Above this many returned rows the sheet is cited instead: a citation per
# row of a long list is a margin nobody reads, and each costs a lookup.
MAX_CITED_ROWS = 10

# How `extract_xlsx` joins a row's cells into its anchor's text.
_CELL_SEPARATOR = " | "

# The spellings `table_load.cast_value` loads as a boolean. Duplicated, as
# `table_load` duplicates them from `table_infer`: this side reads back what
# that side wrote, and both agree on the same fixed vocabulary.
_TRUE_VALUES = frozenset({"true", "t", "yes", "y", "1"})
_FALSE_VALUES = frozenset({"false", "f", "no", "n", "0"})


@dataclass(frozen=True, slots=True)
class SheetCitation:
    """One passage of the workbook a SQL answer is cited to, with what the
    margin shows: `heading` is the row's anchor label (`Sheet, row 3`) for a
    row, the sheet's name for the sheet. `page_from`/`page_to` are the
    row's own anchor for a row, so the viewer opens on it."""

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    anchor_kind: str
    heading: str
    page_from: int | None
    page_to: int | None
    passage: str
    quoted_span: str | None

    def as_candidate(self) -> Candidate:
        """The same passage as a retrieval candidate, for what counts the
        sources an answer cited (`agent.summarize.summarize_turn`)."""
        return Candidate(
            chunk_id=self.chunk_id,
            document_id=self.document_id,
            filename=self.filename,
            anchor_kind=self.anchor_kind,
            content=self.passage,
            heading=self.heading,
            page_from=self.page_from,
            page_to=self.page_to,
            score=0.0,
            dense_score=None,
            lexical_score=None,
        )


@dataclass(frozen=True, slots=True)
class _Sheet:
    document_id: uuid.UUID
    filename: str
    name: str


@dataclass(frozen=True, slots=True)
class _Anchor:
    page_number: int
    text: str
    label: str


@dataclass(frozen=True, slots=True)
class _Passage:
    chunk_id: uuid.UUID
    content: str
    page_from: int | None
    page_to: int | None


class _Stale(Exception):
    """A row the query returned is not in the workbook's live passages."""


# --- pure: which table rows, which sheet row -------------------------------


def returned_table_rows(
    returned: Sequence[Sequence[Any]], projected: int, provenance: Sequence[Sequence[Any]]
) -> list[tuple[Any, ...]] | None:
    """The table rows behind `returned`, or `None` when that cannot be known.

    `provenance` rows are the projected columns, then the table's row. For
    every distinct returned row, the table rows with the same projected
    values must be exactly as many as were returned: then every one of them
    was returned. More is a tie a limit cut, fewer means the table changed
    between the reads; either way no row is claimed."""
    try:
        wanted = Counter(tuple(row) for row in returned)
        candidates: dict[tuple[Any, ...], list[tuple[Any, ...]]] = {}
        for row in provenance:
            candidates.setdefault(tuple(row[:projected]), []).append(tuple(row[projected:]))
    except TypeError:
        # An unhashable value (an array, a JSON document) is not compared.
        return None
    rows: list[tuple[Any, ...]] = []
    for key, count in wanted.items():
        found = candidates.get(key, [])
        if len(found) != count:
            return None
        rows.extend(found)
    return rows


def _empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _cell_equals(value: Any, cell: str) -> bool:
    if isinstance(value, bool):
        return cell.lower() in (_TRUE_VALUES if value else _FALSE_VALUES)
    if isinstance(value, datetime):
        return cell == str(value)
    if isinstance(value, date):
        return cell in (value.isoformat(), f"{value.isoformat()} 00:00:00")
    if isinstance(value, (int, float, Decimal)):
        try:
            return Decimal(cell) == Decimal(str(value))
        except InvalidOperation:
            return False
    return str(value).strip() == cell


def row_matches_anchor(values: Sequence[Any], anchor_text: str) -> bool:
    """Whether a table row is the sheet row whose anchor reads `anchor_text`.

    Extraction writes a row as its non-empty cells, stripped, joined by
    `" | "`; loading casts each cell to its column's type. So the row's
    non-empty values, in column order, must equal the anchor's cells one for
    one, compared as the type they were loaded as."""
    rendered = [value for value in values if not _empty(value)]
    cells = [cell.strip() for cell in anchor_text.split(_CELL_SEPARATOR)]
    return len(rendered) == len(cells) and all(
        _cell_equals(value, cell) for value, cell in zip(rendered, cells, strict=True)
    )


# --- reading the workbook's live document ----------------------------------


async def _sheets(
    session: AsyncSession, settings: Settings, source_id: uuid.UUID, database: str
) -> dict[str, _Sheet]:
    """Every sheet table in the folder's database whose workbook is a live
    document, by table name."""
    sheets: dict[str, _Sheet] = {}
    for table, relative in (await workbook_tables(settings, database)).items():
        name = await sheet_of_table(session, source_id, relative, table)
        document_id = await live_workbook(session, source_id, relative)
        if name is None or document_id is None:
            continue
        filename = (
            await session.execute(
                text("SELECT filename FROM documents WHERE id = :id"), {"id": document_id}
            )
        ).scalar_one()
        sheets[table] = _Sheet(document_id, str(filename), name)
    return sheets


async def _anchors(
    session: AsyncSession, sheet: _Sheet, *, first_only: bool = False
) -> list[_Anchor]:
    """The sheet's rows as the live document's anchors, in sheet order. A
    page number past the document's page count is left over from an earlier
    extraction and is not read."""
    prefix = f"{sheet.name}, row "
    rows = await session.execute(
        text(
            "SELECT p.page_number, p.text, p.anchor_label FROM document_pages p "
            "JOIN documents d ON d.id = p.document_id "
            "WHERE p.document_id = :id AND p.has_text AND p.page_number <= d.page_count "
            "AND left(p.anchor_label, length(:prefix)) = :prefix "
            "ORDER BY p.page_number" + (" LIMIT 1" if first_only else "")
        ),
        {"id": sheet.document_id, "prefix": prefix},
    )
    return [
        _Anchor(int(number), str(row_text), str(label))
        for number, row_text, label in rows
        if row_text is not None and str(label)[len(prefix) :].isdigit()
    ]


async def _passage(
    session: AsyncSession, settings: Settings, document_id: uuid.UUID, anchor: _Anchor
) -> _Passage | None:
    """The live passage holding `anchor`, or `None` if none still says it."""
    row = (
        await session.execute(
            text(
                "SELECT id, content, content_encrypted, page_from, page_to FROM chunks "
                "WHERE document_id = :id AND superseded_at IS NULL AND content IS NOT NULL "
                "AND page_from <= :page AND page_to >= :page ORDER BY ordinal LIMIT 1"
            ),
            {"id": document_id, "page": anchor.page_number},
        )
    ).first()
    if row is None:
        return None
    chunk_id, content, encrypted, page_from, page_to = row
    if encrypted:
        key = await passphrase.current_key(session, settings)
        content = crypto.decrypt(str(content).encode("ascii"), key).decode("utf-8")
    if anchor.text not in content:
        return None
    return _Passage(uuid.UUID(str(chunk_id)), str(content), page_from, page_to)


# --- citing ------------------------------------------------------------------


async def _cite_sheet(
    session: AsyncSession, settings: Settings, sheet: _Sheet
) -> SheetCitation | None:
    """The passage holding the sheet's header row, labelled with the sheet."""
    anchors = await _anchors(session, sheet, first_only=True)
    if not anchors:
        return None
    passage = await _passage(session, settings, sheet.document_id, anchors[0])
    if passage is None:
        return None
    return SheetCitation(
        chunk_id=passage.chunk_id,
        document_id=sheet.document_id,
        filename=sheet.filename,
        anchor_kind=ANCHOR_KIND,
        heading=sheet.name,
        page_from=passage.page_from,
        page_to=passage.page_to,
        passage=passage.content,
        quoted_span=None,
    )


async def _provenance_rows(
    session: AsyncSession,
    settings: Settings,
    *,
    source_id: uuid.UUID,
    database: str,
    query: str,
) -> Sequence[Sequence[Any]] | None:
    """Run the provenance read through the same checks as any query. `None`
    when it is refused or capped: a capped read may be missing a tied row."""
    validation = await validate_query(
        session, settings, engine="postgresql", query=query, source_id=source_id
    )
    if not validation.accepted:
        return None
    limited = await inject_limit(session, settings, engine="postgresql", query=query)
    result = await sql_execute_checked.execute_checked_sandbox_query(
        session, settings, database=database, query=limited.query, row_limit=limited.limit
    )
    return None if result.truncated else result.rows


async def _cite_rows(
    session: AsyncSession, settings: Settings, sheet: _Sheet, table_rows: list[tuple[Any, ...]]
) -> list[SheetCitation]:
    """A citation per sheet row behind `table_rows`. Raises `_Stale` when a
    row is not in the sheet's live passages."""
    anchors = await _anchors(session, sheet)
    cited: dict[int, SheetCitation] = {}
    for values in table_rows:
        matches = [anchor for anchor in anchors if row_matches_anchor(values, anchor.text)]
        if not matches:
            raise _Stale
        for anchor in matches:
            if anchor.page_number in cited:
                continue
            passage = await _passage(session, settings, sheet.document_id, anchor)
            if passage is None:
                raise _Stale
            cited[anchor.page_number] = SheetCitation(
                chunk_id=passage.chunk_id,
                document_id=sheet.document_id,
                filename=sheet.filename,
                anchor_kind=ANCHOR_KIND,
                heading=anchor.label,
                page_from=anchor.page_number,
                page_to=anchor.page_number,
                passage=passage.content,
                quoted_span=anchor.text,
            )
    return [cited[page] for page in sorted(cited)]


async def cite_sheet_result(
    session: AsyncSession,
    settings: Settings,
    *,
    source_id: uuid.UUID,
    database: str,
    query: str,
    rows: Sequence[Sequence[Any]],
    truncated: bool,
) -> list[SheetCitation]:
    """The workbook passages a SQL answer over a folder's sheet tables is
    cited to: its rows when they can be named, its sheets otherwise, and
    nothing for an empty result or a table whose workbook is gone.

    `query` is the executed query, `rows` what it returned."""
    if not rows:
        return []
    tables = referenced_tables("postgresql", query)
    if not tables:
        return []
    sheets = await _sheets(session, settings, source_id, database)
    if not any(table in sheets for table in tables):
        return []

    plan = plan_provenance("postgresql", query)
    if plan is not None and plan.table in sheets and not truncated and len(rows) <= MAX_CITED_ROWS:
        provenance = await _provenance_rows(
            session, settings, source_id=source_id, database=database, query=plan.query
        )
        width = len(rows[0])
        table_rows = (
            returned_table_rows(rows, width, provenance) if provenance is not None else None
        )
        if table_rows:
            try:
                return await _cite_rows(session, settings, sheets[plan.table], table_rows)
            except _Stale:
                log.info("sheet_citation_stale", source_id=str(source_id), table=plan.table)
                return []

    citations: list[SheetCitation] = []
    for table in tables:
        if table in sheets:
            citation = await _cite_sheet(session, settings, sheets[table])
            if citation is not None:
                citations.append(citation)
    return citations
