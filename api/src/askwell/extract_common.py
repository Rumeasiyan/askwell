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

**A document a person cannot even open gets classified before extraction
sees its bytes.** `M1-EXTRACT-VAL-030`: "extraction failed" is not one fact,
it is four — corrupt, encrypted, password-protected, or gone from disk — and
`docs/states-and-edge-cases.md` §3 asks each to read distinctly, by file
name, rather than as one grey "failed". `check_readable` is the one check
every extractor shares (a file that vanished between add and extraction is
the same fact whether it was going to be read by pdfium or by
`python-docx`); the encrypted/password-protected split is PDF-specific
(`extract_pdf`), because that is the only format the sandboxed libraries here
can even ask the question of.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
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


class MissingSource(Exception):
    """The file this document pointed to is no longer at its recorded path.

    Distinct from `CorruptDocument` on purpose — `docs/states-and-edge-cases.md`
    §3's own edge case: a file deleted between add and extraction is "missing
    at the recorded path", not a document that opened and turned out broken.
    """


class UnreadableSource(Exception):
    """The file exists but the filesystem refused to read it (permissions,
    a bad SELinux label, a device that went away mid-read)."""


class CorruptDocument(Exception):
    """The bytes at this path do not form a valid document of the kind its
    signature declared."""


class PasswordProtected(Exception):
    """This document is encrypted and needs a password before it can be
    read. No password was supplied for this attempt."""


class WrongPassword(Exception):
    """A password was supplied for this document and did not open it."""


def check_readable(work: "Work") -> None:
    """The one filesystem check every extractor needs before its own parser
    ever sees the bytes, so "missing" and "unreadable" read the same way
    regardless of which format failed.
    """
    try:
        with Path(work.path).open("rb"):
            pass
    except FileNotFoundError as error:
        raise MissingSource(
            f"{work.filename} is no longer at {work.path}. It may have been "
            "moved or deleted since it was added."
        ) from error
    except OSError as error:
        detail = error.strerror or str(error)
        raise UnreadableSource(f"{work.filename} could not be read from disk: {detail}.") from error


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
