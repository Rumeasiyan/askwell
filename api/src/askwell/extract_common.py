"""What every non-PDF extractor shares. `M1-EXTRACT-ING-027`.

`M1-EXTRACT-ING-026` wrote `document_pages` once, for PDF. Six more formats
need the same table, and duplicating the write in six modules is how the
`ON CONFLICT` clause drifts out of sync with itself the first time one of them
is touched without the others. `Anchor` and `write_anchors` are that one write,
generalised: `page_number` stays the ordinal `document_pages` was already
keyed on, and `label` is the human-facing pointer a bare ordinal cannot carry
— a slide number needs none, a spreadsheet row and a heading do.

**Empty is a failure with a reason, never a document that reaches `ready`
with nothing in it.** `EmptyDocument` is raised, not swallowed, when not one
anchor came back with text — C5's abstention promise starts here: a document
`chunk` can find nothing in later is the same lie whether it came from a
missing text layer or from extraction skipping the check.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import text

from askwell.db.engine import session_scope

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from askwell.ingest import Work


class EmptyDocument(Exception):
    """Every anchor this extractor produced came back with no text.

    Caught nowhere special — `askwell.ingest.process`'s generic `except
    Exception` is exactly the failure path this belongs to, with this
    exception's own message as the reason a person reads.
    """


@dataclass(frozen=True, slots=True)
class Anchor:
    """One addressable unit of a document: a page, a slide, a spreadsheet
    row, or a heading-delimited section of text."""

    page_number: int
    label: str | None
    text: str | None
    has_text: bool


async def write_anchors(
    factory: "async_sessionmaker[AsyncSession]",
    work: "Work",
    anchors: Sequence[Anchor],
    anchor_kind: str,
) -> None:
    if not any(anchor.has_text for anchor in anchors):
        raise EmptyDocument(
            "Askwell could not find any text in this document. It may be empty, "
            "corrupted, or in a form nothing here reads yet."
        )

    async with session_scope(factory) as session:
        await session.execute(
            text(
                "UPDATE documents SET page_count = :page_count, anchor_kind = :anchor_kind "
                "WHERE id = :id"
            ),
            {"page_count": len(anchors), "anchor_kind": anchor_kind, "id": work.document_id},
        )
        for anchor in anchors:
            await session.execute(
                text(
                    "INSERT INTO document_pages "
                    "(document_id, page_number, text, has_text, anchor_label) "
                    "VALUES (:document_id, :page_number, :text, :has_text, :anchor_label) "
                    "ON CONFLICT (document_id, page_number) "
                    "DO UPDATE SET text = EXCLUDED.text, has_text = EXCLUDED.has_text, "
                    "anchor_label = EXCLUDED.anchor_label"
                ),
                {
                    "document_id": work.document_id,
                    "page_number": anchor.page_number,
                    "text": anchor.text,
                    "has_text": anchor.has_text,
                    "anchor_label": anchor.label,
                },
            )
