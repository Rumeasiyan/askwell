"""The clarifications API: what the review screens read and write.

`docs/backlog/M3-it-learns-my-material.md` ticket `M3-REVIEW-BE-072a`.

`M3-RAISE-BE-068` through `-070` write rows into `clarifications`, but
nothing exposed them over HTTP — `M3-REVIEW-FE-072` names `clarifications`
as its only API touchpoint and had no endpoint to call. This is that
surface: a grouped read (`GET /clarifications`) and two writes
(`POST .../answer`, `POST .../skip`).

**Grouping happens in SQL, not in the browser.** `docs/ux/clarifications.md`
§2's own shape is "counts before items" — fetching everything to count it
client-side defeats that, so one query orders by source recency and rank,
and Python folds adjacent rows into groups (cheap, since the SQL already
guarantees rows for the same source arrive together).

**Answering and skipping share one lock-and-check shape.** Both start with
`SELECT ... FOR UPDATE` on the single row so two concurrent requests for the
same item cannot both see `pending` and both act — unlikely for one person
on one machine, but the check is one clause and the alternative is a second
memory fact for one answer, which is exactly what `-072a`'s own Validation
Rule forbids.
"""

import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from askwell.audit import Store, record
from askwell.db.engine import session_scope
from askwell.logging import get_logger

log = get_logger(__name__)

CLARIFICATION_ANSWERED = "clarification_answered"
CLARIFICATION_SKIPPED = "clarification_skipped"
CLARIFICATION_DISMISSED = "clarification_dismissed"
CLARIFICATION_ANSWER_UNDONE = "clarification_answer_undone"

# A user-given answer is not a guess — full confidence, unlike the
# low-confidence inferences `askwell.clarify` writes for anything nobody was
# asked about (`LOW_CONFIDENCE` there). This is the one place a `memory` row
# is written with the user's own word behind it.
ANSWER_CONFIDENCE = 1.0


class ClarificationNotFound(Exception):
    """No clarification with that id."""


class AlreadyAnswered(Exception):
    """Refused by name, not a second fact: `-072a`'s own Edge Case."""


class CannotUndo(Exception):
    """The memory fact an answer wrote has since been built upon.

    A correction (or another answer) may already supersede it by the time
    the undo window fires; reversing the original write at that point would
    silently discard whatever came after it, which is a second, unrelated
    loss of information the user never asked for.
    """


async def list_pending(session: AsyncSession) -> dict[str, Any]:
    """Pending clarifications, grouped by source, newest source first.

    A source with `status = 'deleted'` (`askwell.sources.delete_source`, a
    soft delete — the row and its clarifications both survive) is excluded:
    `-072a`'s own Edge Case, "an item whose source was deleted does not
    appear". A source with nothing pending never produces an empty group,
    because the query has no row for it to begin with.
    """
    rows = (
        await session.execute(
            text(
                "SELECT c.id, c.subject, c.question, c.options, c.evidence, "
                "c.source_id, s.name "
                "FROM clarifications c "
                "JOIN sources s ON s.id = c.source_id "
                "WHERE c.status = 'pending' AND s.status <> 'deleted' "
                "ORDER BY s.added_at DESC, c.rank ASC NULLS LAST, c.asked_at ASC"
            )
        )
    ).all()

    groups: list[dict[str, Any]] = []
    by_source: dict[uuid.UUID, dict[str, Any]] = {}
    for clarification_id, subject, question, options, evidence, source_id, source_name in rows:
        group = by_source.get(source_id)
        if group is None:
            group = {
                "source_id": str(source_id),
                "source_name": source_name,
                "count": 0,
                "items": [],
            }
            by_source[source_id] = group
            groups.append(group)
        group["count"] += 1
        group["items"].append(
            {
                "id": str(clarification_id),
                "subject": subject,
                "question": question,
                "options": options,
                "evidence": evidence,
            }
        )

    return {"groups": groups, "total": len(rows)}


@dataclass(frozen=True, slots=True)
class Reprocessing:
    """What `M3-REVIEW-FE-074`'s confirmation names: not a generic toast, the
    actual material the answer just marked for re-reading. Re-reading itself
    is `M3-APPLY-ING-080`'s own territory — this only counts and names it, so
    the confirmation is honest even while that ticket's queue is a no-op.
    """

    count: int
    label: str


@dataclass(frozen=True, slots=True)
class AnswerOutcome:
    clarification_id: uuid.UUID
    memory_id: uuid.UUID
    reprocessing: Reprocessing


def _documents_named_in_evidence(evidence: dict[str, Any] | None) -> list[str]:
    """The document names a `-071` evidence blob already carries — a passage's
    or a contradiction's samples were pulled from real documents at raise
    time, so naming them back needs no new query. Sampling is bounded
    (`EVIDENCE_MAX_SAMPLES` in `askwell.clarify`), so this can undercount a
    subject that occurs in more documents than were sampled; `_reprocessing_summary`
    falls back to a source-wide count rather than ever asserting a specific
    list it cannot back up.
    """
    if not evidence:
        return []
    kind = evidence.get("kind")
    if kind == "passage":
        rows = evidence.get("samples", [])
    elif kind == "contradiction":
        rows = evidence.get("passages", [])
    else:
        return []
    return [row["document"] for row in rows if isinstance(row, dict) and row.get("document")]


async def _reprocessing_summary(
    session: AsyncSession,
    source_id: str,
    evidence: dict[str, Any] | None,
    options: list[str] | None,
) -> Reprocessing:
    """Specific where the evidence already names documents (a passage, a
    contradiction, or `document_identity`'s own `options`); otherwise every
    live document in the source — always true, even where it overstates,
    which honestly-inflated beats a fabricated specific count.
    """
    named = sorted({*(options or []), *_documents_named_in_evidence(evidence)})
    if named:
        count = len(named)
        return Reprocessing(count=count, label=f"{count} document{'' if count == 1 else 's'}")

    result = await session.execute(
        text(
            "SELECT count(*) FROM documents WHERE source_id = CAST(:source_id AS uuid) "
            "AND deleted_at IS NULL AND superseded_by IS NULL AND status = 'ready'"
        ),
        {"source_id": source_id},
    )
    count = int(result.scalar_one())
    return Reprocessing(
        count=count, label=f"{count} document{'' if count == 1 else 's'} in this source"
    )


async def _lock_clarification(
    session: AsyncSession, clarification_id: uuid.UUID
) -> tuple[str, str, str | None, dict[str, Any] | None, list[str] | None] | None:
    found = await session.execute(
        text(
            "SELECT status, subject, source_id::text, evidence, options "
            "FROM clarifications WHERE id = :id FOR UPDATE"
        ),
        {"id": clarification_id},
    )
    row = found.first()
    return None if row is None else (row[0], row[1], row[2], row[3], row[4])


async def answer_clarification(
    session: AsyncSession, clarification_id: uuid.UUID, answer: str
) -> AnswerOutcome:
    """Record an answer: `memory` and the decisions record, one transaction.

    `docs/decisions.md`-worthy only in that it is the one ticket-mandated
    invariant here — the two writes below share this function's session and
    neither commits on its own; `session_scope` (the caller) commits both or
    neither.
    """
    locked = await _lock_clarification(session, clarification_id)
    if locked is None:
        raise ClarificationNotFound(str(clarification_id))
    status, subject, source_id, evidence, options = locked
    if status == "answered":
        raise AlreadyAnswered(str(clarification_id))
    assert source_id is not None, "clarifications.source_id is NOT NULL"

    await session.execute(
        text(
            "UPDATE clarifications SET status = 'answered', answer = :answer, "
            "answered_at = now() WHERE id = :id"
        ),
        {"id": clarification_id, "answer": answer},
    )

    reprocessing = await _reprocessing_summary(session, source_id, evidence, options)

    memory_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO memory (id, subject, fact, origin, confidence) "
            "VALUES (:id, :subject, :fact, 'clarification', :confidence)"
        ),
        {
            "id": memory_id,
            "subject": subject,
            "fact": answer,
            "confidence": ANSWER_CONFIDENCE,
        },
    )

    await record(
        session,
        Store.DECISIONS,
        CLARIFICATION_ANSWERED,
        {
            "clarification_id": str(clarification_id),
            "subject": subject,
            "memory_id": str(memory_id),
        },
    )

    return AnswerOutcome(
        clarification_id=clarification_id, memory_id=memory_id, reprocessing=reprocessing
    )


async def skip_clarification(session: AsyncSession, clarification_id: uuid.UUID) -> None:
    """Mark skipped. No `memory` row — a skip is not an answer.

    Idempotent for an already-skipped item. Refused for an already-answered
    one: silently downgrading a real answer back to skipped would discard a
    fact nobody asked to discard, and undo is `M3-REVIEW-FE-074`'s own
    territory, not this route's.
    """
    locked = await _lock_clarification(session, clarification_id)
    if locked is None:
        raise ClarificationNotFound(str(clarification_id))
    status, subject, source_id, _evidence, _options = locked
    if status == "answered":
        raise AlreadyAnswered(str(clarification_id))
    if status == "skipped":
        return

    await session.execute(
        text("UPDATE clarifications SET status = 'skipped' WHERE id = :id"),
        {"id": clarification_id},
    )
    await record(
        session,
        Store.DECISIONS,
        CLARIFICATION_SKIPPED,
        {"clarification_id": str(clarification_id), "subject": subject, "source_id": source_id},
    )


async def dismiss_group(session: AsyncSession, source_id: uuid.UUID) -> list[uuid.UUID]:
    """Skip-all for one source's group: `-074`'s own Edge Case, "one record
    each, so the dismissal signal is countable."

    Only pending items move — an already-answered or already-skipped item in
    the same group is left exactly as it is, since dismissal is a verdict on
    the questions nobody has acted on yet, not a way to relabel one that has
    already been decided. Idempotent: a group with nothing pending dismisses
    nothing and returns an empty list.
    """
    rows = await session.execute(
        text(
            "SELECT id, subject FROM clarifications "
            "WHERE source_id = :source_id AND status = 'pending' FOR UPDATE"
        ),
        {"source_id": source_id},
    )
    pending = rows.all()
    if not pending:
        return []

    ids = [row[0] for row in pending]
    await session.execute(
        text("UPDATE clarifications SET status = 'dismissed' WHERE id = ANY(:ids)"),
        {"ids": ids},
    )
    for clarification_id, subject in pending:
        await record(
            session,
            Store.DECISIONS,
            CLARIFICATION_DISMISSED,
            {
                "clarification_id": str(clarification_id),
                "subject": subject,
                "source_id": str(source_id),
            },
        )
    return list(ids)


async def undo_answer(
    session: AsyncSession, clarification_id: uuid.UUID, memory_id: uuid.UUID
) -> None:
    """Reverse an answer within its undo window.

    Recorded as its own decision rather than by deleting `CLARIFICATION_ANSWERED`
    — the original record stays exactly as written; this adds a second record
    that says the answer was later undone. The memory fact itself is deleted
    (`askwell.memory.delete_memory_fact`'s own shape), and the clarification
    goes back to `pending` so it can be answered again.
    """
    locked = await _lock_clarification(session, clarification_id)
    if locked is None:
        raise ClarificationNotFound(str(clarification_id))
    status, subject, _source_id, _evidence, _options = locked
    if status != "answered":
        raise CannotUndo(str(clarification_id))

    active = await session.execute(
        text(
            "SELECT origin FROM memory WHERE id = :id AND superseded_by IS NULL "
            "AND subject = :subject FOR UPDATE"
        ),
        {"id": memory_id, "subject": subject},
    )
    row = active.first()
    if row is None or row[0] != "clarification":
        raise CannotUndo(str(clarification_id))

    await session.execute(text("DELETE FROM memory WHERE id = :id"), {"id": memory_id})
    await session.execute(
        text(
            "UPDATE clarifications SET status = 'pending', answer = NULL, answered_at = NULL "
            "WHERE id = :id"
        ),
        {"id": clarification_id},
    )
    await record(
        session,
        Store.DECISIONS,
        CLARIFICATION_ANSWER_UNDONE,
        {
            "clarification_id": str(clarification_id),
            "memory_id": str(memory_id),
            "subject": subject,
        },
    )


class AnswerRequest(BaseModel):
    answer: str = Field(min_length=1, max_length=4096)


class UndoRequest(BaseModel):
    memory_id: uuid.UUID


def register_review(app: FastAPI, factory: async_sessionmaker[AsyncSession]) -> None:
    """Attach the clarifications surface. Register before the interface catch-all."""

    @app.get("/clarifications")
    async def get_clarifications() -> JSONResponse:
        async with session_scope(factory) as db:
            return JSONResponse(await list_pending(db))

    @app.post("/clarifications/{clarification_id}/answer")
    async def answer_route(clarification_id: uuid.UUID, body: AnswerRequest) -> JSONResponse:
        try:
            async with session_scope(factory) as db:
                outcome = await answer_clarification(db, clarification_id, body.answer)
        except ClarificationNotFound:
            return JSONResponse({"error": "No such clarification."}, status_code=404)
        except AlreadyAnswered:
            return JSONResponse({"error": "This question was already answered."}, status_code=409)
        return JSONResponse(
            {
                "id": str(outcome.clarification_id),
                "status": "answered",
                "memory_id": str(outcome.memory_id),
                "reprocessing": {
                    "count": outcome.reprocessing.count,
                    "label": outcome.reprocessing.label,
                },
            }
        )

    @app.post("/clarifications/{clarification_id}/skip")
    async def skip_route(clarification_id: uuid.UUID) -> JSONResponse:
        try:
            async with session_scope(factory) as db:
                await skip_clarification(db, clarification_id)
        except ClarificationNotFound:
            return JSONResponse({"error": "No such clarification."}, status_code=404)
        except AlreadyAnswered:
            return JSONResponse({"error": "This question was already answered."}, status_code=409)
        return JSONResponse({"id": str(clarification_id), "status": "skipped"})

    @app.post("/sources/{source_id}/clarifications/dismiss")
    async def dismiss_route(source_id: uuid.UUID) -> JSONResponse:
        async with session_scope(factory) as db:
            dismissed = await dismiss_group(db, source_id)
        return JSONResponse({"dismissed": [str(item) for item in dismissed]})

    @app.post("/clarifications/{clarification_id}/undo")
    async def undo_route(clarification_id: uuid.UUID, body: UndoRequest) -> JSONResponse:
        try:
            async with session_scope(factory) as db:
                await undo_answer(db, clarification_id, body.memory_id)
        except ClarificationNotFound:
            return JSONResponse({"error": "No such clarification."}, status_code=404)
        except CannotUndo:
            return JSONResponse({"error": "This answer can no longer be undone."}, status_code=409)
        return JSONResponse({"id": str(clarification_id), "status": "pending"})
