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

**The moved/deleted distinction (`M1-VIEW-BE-049`) lives here too.**
`_availability` is the open-time check, shared by `document_metadata` and
`document_file` so the two cannot disagree about whether a document is there,
moved, or unreachable because its whole root is. `askwell.ingest.sweep_missing`
is the same decision (`roots.source_availability` first, a per-file check only
once that says the root itself is fine) run on a timer instead of a click —
kept in `askwell.ingest` rather than imported from here, since `_availability`
already depends on `askwell.ingest.refresh_source` and the reverse import
would be a cycle.
"""

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from askwell.audit import Store, record
from askwell.config import Settings
from askwell.db.engine import session_scope
from askwell.ingest import refresh_source
from askwell.logging import get_logger
from askwell.roots import SourceState, covering, source_availability
from askwell.roots import listing as roots_listing
from askwell.roots import tombstoned as roots_tombstoned
from askwell.sources import FileUnsettled, fingerprint

log = get_logger(__name__)

DOCUMENT_OPENED = "document_opened"
DOCUMENT_RELOCATED = "document_relocated"


async def _find(
    session: AsyncSession, document_id: uuid.UUID, *, include_deleted: bool = False
) -> dict[str, object] | None:
    clause = "d.id = :id" if include_deleted else "d.id = :id AND d.deleted_at IS NULL"
    result = await session.execute(
        text(
            "SELECT d.id, d.filename, d.path, d.mime, d.page_count, d.anchor_kind, "
            "d.status, d.superseded_by, d.source_id, d.sha256, d.missing_since, "
            "d.added_at, d.deleted_at, d.deleted_reason, s.root_path "
            f"FROM documents d JOIN sources s ON s.id = d.source_id WHERE {clause}"
        ),
        {"id": document_id},
    )
    row = result.mappings().first()
    return dict(row) if row is not None else None


@dataclass(frozen=True, slots=True)
class Availability:
    """Whether a document's bytes can actually be read right now, and why not
    when they cannot. `M1-VIEW-BE-049`.

    **Moved and root-unavailable are different facts and must stay different
    ones.** A file gone from under an otherwise-reachable root is `moved`: the
    user renamed or relocated one file, and Askwell says so and offers to fix
    it. A root that cannot be reached at all — unmounted, removed, unreadable
    — is `root_unavailable`: none of its documents are individually missing,
    the whole folder is, and reporting each of them as moved would be as many
    wrong questions as it has files in it. The distinction comes from
    `roots.source_availability`, not from anything guessed here.
    """

    exists: bool
    moved: bool
    missing_since: str | None
    root_unavailable: bool
    root_reason: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "available": self.exists,
            "moved": self.moved,
            "missing_since": self.missing_since,
            "root_unavailable": self.root_unavailable,
            "root_reason": self.root_reason,
        }


def _isoformat(value: object) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


async def _availability(
    factory: async_sessionmaker[AsyncSession], settings: Settings, found: dict[str, object]
) -> Availability:
    """Check `found["path"]` against disk and reconcile `missing_since` with
    what is actually true, right now.

    The write happens here rather than only in the periodic sweep
    (`askwell.ingest.sweep_missing`) so a moved file is caught the moment
    someone clicks its citation, not only on the next timer tick — and so a
    file that quietly came back clears its own flag on the next open rather
    than waiting for the sweep to notice.
    """
    path = Path(str(found["path"]))
    exists = await asyncio.to_thread(path.is_file)
    missing_since = found["missing_since"]

    if exists:
        if missing_since is not None:
            async with session_scope(factory) as db:
                await db.execute(
                    text("UPDATE documents SET missing_since = NULL WHERE id = :id"),
                    {"id": found["id"]},
                )
                await refresh_source(
                    db, uuid.UUID(str(found["source_id"])), settings.ocr_confidence_threshold
                )
        return Availability(
            exists=True, moved=False, missing_since=None, root_unavailable=False, root_reason=None
        )

    root_path = found["root_path"]
    if root_path is None:
        state, reason = (
            SourceState.NO_ROOT,
            "No nominated folder covers this source's own folder.",
        )
    else:
        async with factory() as db:
            live = await roots_listing(db, settings)
            removed = await roots_tombstoned(db)
        state, reason = source_availability(str(root_path), live, removed)

    if state is not SourceState.READABLE:
        return Availability(
            exists=False,
            moved=False,
            missing_since=_isoformat(missing_since),
            root_unavailable=True,
            root_reason=reason,
        )

    if missing_since is None:
        async with session_scope(factory) as db:
            await db.execute(
                text("UPDATE documents SET missing_since = now() WHERE id = :id"),
                {"id": found["id"]},
            )
            stamped = (
                await db.execute(
                    text("SELECT missing_since FROM documents WHERE id = :id"),
                    {"id": found["id"]},
                )
            ).first()
            missing_since = stamped[0] if stamped is not None else None
            await refresh_source(
                db, uuid.UUID(str(found["source_id"])), settings.ocr_confidence_threshold
            )

    return Availability(
        exists=False,
        moved=True,
        missing_since=_isoformat(missing_since),
        root_unavailable=False,
        root_reason=None,
    )


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


class RelocateRequest(BaseModel):
    """A typed or picker-provided path to where a moved file now lives."""

    path: str


def register_documents(
    app: FastAPI, settings: Settings, factory: async_sessionmaker[AsyncSession]
) -> None:
    """Attach the document-viewing surface. Register before the interface catch-all."""

    @app.get("/documents/{document_id}")
    async def document_metadata(document_id: uuid.UUID) -> JSONResponse:
        async with factory() as db:
            found = await _find(db, document_id, include_deleted=True)
        if found is None:
            return JSONResponse({"error": "No such document."}, status_code=404)

        # #231: a tombstoned row still answers here, honestly, rather than
        # 404ing the same as an id that never existed — the row survives
        # specifically so an old citation can resolve to a deletion date
        # instead of breaking (`docs/ux/source-viewer.md` §4). Short-circuits
        # before `_availability`, which assumes a live document and would
        # otherwise report a cleared row as "moved".
        if found["deleted_at"] is not None:
            return JSONResponse(
                {
                    "id": str(found["id"]),
                    "filename": found["filename"],
                    "deleted": True,
                    "deleted_at": _isoformat(found["deleted_at"]),
                    "deleted_reason": found["deleted_reason"],
                    "added_at": _isoformat(found["added_at"]),
                    "source_id": str(found["source_id"]),
                }
            )

        availability = await _availability(factory, settings, found)

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
                "path": found["path"],
                "mime": found["mime"],
                "page_count": found["page_count"],
                "anchor_kind": found["anchor_kind"],
                "status": found["status"],
                "superseded_by": str(superseded_by) if superseded_by is not None else None,
                "superseded_at": superseded_at,
                "deleted": False,
                # `M2-PARTIAL-FE-058`: the conflicting-sources card needs a
                # date to show beside each position, and `added_at` — already
                # on every row — is the only one that exists yet (no
                # ingestion-metadata or filename-derived date is extracted
                # anywhere in this codebase). The ticket's own fallback rule
                # ("where neither exists, the added date is used and
                # labelled as such") is met by always sending this one and
                # letting the caller label it "Added".
                "added_at": _isoformat(found["added_at"]),
                "source_id": str(found["source_id"]),
                **availability.as_dict(),
            }
        )

    @app.get("/documents/{document_id}/file", response_model=None)
    async def document_file(document_id: uuid.UUID) -> Response:
        async with factory() as db:
            found = await _find(db, document_id)
        if found is None:
            return JSONResponse({"error": "No such document."}, status_code=404)

        availability = await _availability(factory, settings, found)
        if not availability.exists:
            if availability.root_unavailable:
                return JSONResponse(
                    {
                        "error": f"Askwell cannot reach the folder that holds "
                        f"{found['filename']} right now.",
                        "reason": "root_unavailable",
                        "detail": availability.root_reason,
                    },
                    status_code=404,
                )
            return JSONResponse(
                {
                    "error": f"{found['filename']} is no longer at {found['path']}.",
                    "reason": "moved",
                    "path": found["path"],
                    "missing_since": availability.missing_since,
                },
                status_code=404,
            )

        return FileResponse(
            Path(str(found["path"])),
            media_type=str(found["mime"]) if found["mime"] else "application/octet-stream",
            filename=str(found["filename"]),
            content_disposition_type="inline",
        )

    @app.post("/documents/{document_id}/relocate")
    async def relocate_document(document_id: uuid.UUID, body: RelocateRequest) -> JSONResponse:
        """Repair a moved document's recorded path. `M1-VIEW-BE-049`.

        `RelocateRequest` carries one field, the same seam
        `roots.NominateRequest` uses for exactly the same reason —
        `M7-TAURI-FE-182` substitutes the platform's own file dialog for
        whatever produced this string without this handler, or the
        verification below it, changing at all.
        """
        async with factory() as db:
            found = await _find(db, document_id)
        if found is None:
            return JSONResponse({"error": "No such document."}, status_code=404)

        still_there = await asyncio.to_thread(Path(str(found["path"])).is_file)
        if still_there and found["missing_since"] is None:
            return JSONResponse(
                {"error": f"{found['filename']} is not missing — there is nothing to relocate."},
                status_code=400,
            )

        requested = body.path.strip()
        if not requested:
            return JSONResponse({"error": "No file was given."}, status_code=400)

        async with factory() as db:
            root = await covering(db, requested)
        if root is None:
            return JSONResponse(
                {
                    "error": f"{requested} is outside every folder Askwell may read. "
                    "Nominate the folder that now holds it before relocating to it."
                },
                status_code=400,
            )

        new_path = Path(requested)
        if not await asyncio.to_thread(new_path.is_file):
            return JSONResponse({"error": f"There is no file at {requested}."}, status_code=400)

        try:
            stamp = await asyncio.to_thread(fingerprint, str(new_path))
        except FileUnsettled as error:
            return JSONResponse({"error": str(error)}, status_code=409)

        if stamp.sha256 != found["sha256"]:
            # The ticket's own edge case: moved *and* modified is a hash
            # mismatch, not a relocation — offered as a new version instead,
            # through the ordinary add flow's own version detection rather
            # than a second copy of that logic built here.
            return JSONResponse(
                {
                    "error": f"{new_path.name} is not the same file as {found['filename']} — "
                    "its content does not match.",
                    "reason": "hash_mismatch",
                    "suggestion": "If this is an updated version rather than the same file "
                    "moved, add it to Askwell as a new file instead of relocating to it.",
                },
                status_code=409,
            )

        old_path = str(found["path"])
        async with session_scope(factory) as db:
            await db.execute(
                text("UPDATE documents SET path = :path, missing_since = NULL WHERE id = :id"),
                {"path": str(new_path), "id": document_id},
            )
            # A decisions record naming both paths — what actually changed,
            # not just that something did.
            await record(
                db,
                Store.DECISIONS,
                DOCUMENT_RELOCATED,
                {
                    "document_id": str(document_id),
                    "filename": found["filename"],
                    "from_path": old_path,
                    "to_path": str(new_path),
                },
            )
            await refresh_source(
                db, uuid.UUID(str(found["source_id"])), settings.ocr_confidence_threshold
            )

        return JSONResponse({"relocated": True, "path": str(new_path)})

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
