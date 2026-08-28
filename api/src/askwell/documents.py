"""The source viewer's read side: a document's own metadata, bytes and pages.

`docs/backlog/M1-it-answers-from-my-documents.md` ticket `M1-VIEW-FE-046`.

**The byte-serving route exists because nothing else does.** `M1-VIEW-FE-048`'s
own ticket lists Context rail and citation stepping as its scope, not a
document endpoint — and no other backlog ticket names one either
(`M1-VIEW-BE-049` is the moved/deleted-file *state*, not the ordinary read
path). A viewer that lands on a page has to fetch the page from somewhere, so
this ticket's own "Document bytes from the registered root" touchpoint is
built here rather than left for a ticket that does not claim it.

**`documents.path` is opened directly, exactly as `extract_common.check_readable`
already does.** It is not user input — it came out of the database, written at
add time from a path `askwell.roots` had already checked against a nominated
root (`askwell.sources`) — so there is no second containment check to make
here; the containment already happened once, at write time, and re-deriving it
from a mount prefix would be the second hand-maintained copy `AGENTS.md` §5
warns a build number away from.

**Range requests, not a custom chunked stream.** `FileResponse` (Starlette
1.6) already serves `Range: bytes=...` as `206 Partial Content` with
`Accept-Ranges: bytes`. pdf.js's own default loader issues range requests for
exactly this reason — it reads the cross-reference table first, then only the
pages it needs — so "the cited page loads first and the rest streams" is
satisfied by a correct `Accept-Ranges` response, not by any code in this
module deciding what order to send bytes in.
"""

import asyncio
import uuid
from pathlib import Path

from fastapi import FastAPI, Response
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from askwell.audit import Store, record
from askwell.config import Settings
from askwell.db.engine import session_scope
from askwell.logging import get_logger

log = get_logger(__name__)

DOCUMENT_OPENED = "document_opened"


async def _find(session: AsyncSession, document_id: uuid.UUID) -> dict[str, object] | None:
    result = await session.execute(
        text(
            "SELECT id, filename, path, mime, page_count, anchor_kind, status, "
            "superseded_by FROM documents WHERE id = :id AND deleted_at IS NULL"
        ),
        {"id": document_id},
    )
    row = result.mappings().first()
    return dict(row) if row is not None else None


async def _superseded_at(session: AsyncSession, new_document_id: uuid.UUID) -> str | None:
    """The date the superseding version was added — `sources.py`'s own
    `supersede()` sets the old row's `superseded_by` in the same transaction
    it inserts the new one, so the new row's `added_at` *is* the date the old
    version stopped being current, with nothing new to store for it."""
    result = await session.execute(
        text("SELECT added_at FROM documents WHERE id = :id"),
        {"id": new_document_id},
    )
    row = result.first()
    return row[0].isoformat() if row is not None else None


def register_documents(
    app: FastAPI, settings: Settings, factory: async_sessionmaker[AsyncSession]
) -> None:
    """Attach the document-viewing surface. Register before the interface catch-all."""

    @app.get("/documents/{document_id}")
    async def document_metadata(document_id: uuid.UUID) -> JSONResponse:
        async with factory() as db:
            found = await _find(db, document_id)
        if found is None:
            return JSONResponse({"error": "No such document."}, status_code=404)

        available = await asyncio.to_thread(Path(str(found["path"])).is_file)

        superseded_by = found["superseded_by"]
        superseded_at: str | None = None
        if superseded_by is not None:
            async with factory() as db:
                superseded_at = await _superseded_at(db, uuid.UUID(str(superseded_by)))

        async with session_scope(factory) as db:
            # Interaction-adjacent, not a decision: opening a source is
            # something that happened, never something Askwell chose
            # (`AGENTS.md`'s own line for this ticket). `request.headers` is
            # never read into the payload — only what document was opened.
            await record(
                db,
                Store.INTERACTIONS,
                DOCUMENT_OPENED,
                {"document_id": str(document_id), "filename": found["filename"]},
            )

        return JSONResponse(
            {
                "id": str(found["id"]),
                "filename": found["filename"],
                "mime": found["mime"],
                "page_count": found["page_count"],
                "anchor_kind": found["anchor_kind"],
                "status": found["status"],
                "available": available,
                "superseded_by": str(superseded_by) if superseded_by is not None else None,
                "superseded_at": superseded_at,
            }
        )

    @app.get("/documents/{document_id}/file", response_model=None)
    async def document_file(document_id: uuid.UUID) -> Response:
        async with factory() as db:
            found = await _find(db, document_id)
        if found is None:
            return JSONResponse({"error": "No such document."}, status_code=404)

        path = Path(str(found["path"]))
        if not await asyncio.to_thread(path.is_file):
            # The moved/deleted distinction is `M1-VIEW-BE-049`'s job. This
            # is the honest fallback until that ticket lands: not a crash,
            # not a silent empty body.
            return JSONResponse(
                {"error": f"{found['filename']} is no longer at its recorded path."},
                status_code=404,
            )

        return FileResponse(
            path,
            media_type=str(found["mime"]) if found["mime"] else "application/octet-stream",
            filename=str(found["filename"]),
            content_disposition_type="inline",
        )

    @app.get("/documents/{document_id}/pages/{page_number}")
    async def document_page(document_id: uuid.UUID, page_number: int) -> JSONResponse:
        """One page's (or slide's, or section's, or scanned page's) own
        extracted text.

        Used for the unrenderable-PDF fallback, `M1-VIEW-FE-047`'s converted-text
        renderers (Word, PowerPoint, text, Markdown, HTML), and the OCR-text-
        alongside panel for a scanned PDF page — not for search, which reads the
        rendered PDF's own text layer client-side.

        `low_confidence` is computed here, against `settings.ocr_confidence_threshold`
        — the same cut line `askwell.ingest.refresh_source` flags a source's OCR
        with — rather than shipping the threshold to the browser for it to compare
        itself, which would be a second copy of the cut line to keep in sync.
        """
        async with factory() as db:
            result = await db.execute(
                text(
                    "SELECT text, has_text, anchor_label, ocr_confidence FROM document_pages "
                    "WHERE document_id = :id AND page_number = :page"
                ),
                {"id": document_id, "page": page_number},
            )
            row = result.first()
        if row is None:
            return JSONResponse({"error": "No such page."}, status_code=404)
        confidence = row[3]
        return JSONResponse(
            {
                "text": row[0],
                "has_text": row[1],
                "anchor_label": row[2],
                "ocr_confidence": float(confidence) if confidence is not None else None,
                "low_confidence": confidence is not None
                and float(confidence) < settings.ocr_confidence_threshold,
            }
        )

    @app.get("/documents/{document_id}/pages")
    async def document_pages(document_id: uuid.UUID) -> JSONResponse:
        """Every page's anchor label and text, in order.

        The spreadsheet renderer's own data source (`M1-VIEW-FE-047`): a row
        highlighted in isolation is not a table, so the viewer needs every row
        to scroll and virtualise against, not the one row a citation names. Kept
        to one query rather than one request per row — a workbook citation
        landing on row 4,000 must not cost 4,000 round trips to render the rows
        around it.
        """
        async with factory() as db:
            result = await db.execute(
                text(
                    "SELECT page_number, anchor_label, text, has_text FROM document_pages "
                    "WHERE document_id = :id ORDER BY page_number"
                ),
                {"id": document_id},
            )
            rows = result.all()
        return JSONResponse(
            [
                {
                    "page_number": row[0],
                    "anchor_label": row[1],
                    "text": row[2],
                    "has_text": row[3],
                }
                for row in rows
            ]
        )
