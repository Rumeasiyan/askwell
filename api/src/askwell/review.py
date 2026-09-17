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

# A user-given answer is not a guess — full confidence, unlike the
# low-confidence inferences `askwell.clarify` writes for anything nobody was
# asked about (`LOW_CONFIDENCE` there). This is the one place a `memory` row
# is written with the user's own word behind it.
ANSWER_CONFIDENCE = 1.0


class ClarificationNotFound(Exception):
    """No clarification with that id."""


class AlreadyAnswered(Exception):
    """Refused by name, not a second fact: `-072a`'s own Edge Case."""


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
class AnswerOutcome:
    clarification_id: uuid.UUID
    memory_id: uuid.UUID


async def _lock_clarification(
    session: AsyncSession, clarification_id: uuid.UUID
) -> tuple[str, str, str | None] | None:
    found = await session.execute(
        text(
            "SELECT status, subject, source_id::text FROM clarifications WHERE id = :id FOR UPDATE"
        ),
        {"id": clarification_id},
    )
    row = found.first()
    return None if row is None else (row[0], row[1], row[2])


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
    status, subject, _source_id = locked
    if status == "answered":
        raise AlreadyAnswered(str(clarification_id))

    await session.execute(
        text(
            "UPDATE clarifications SET status = 'answered', answer = :answer, "
            "answered_at = now() WHERE id = :id"
        ),
        {"id": clarification_id, "answer": answer},
    )

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

    return AnswerOutcome(clarification_id=clarification_id, memory_id=memory_id)


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
    status, subject, source_id = locked
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


class AnswerRequest(BaseModel):
    answer: str = Field(min_length=1, max_length=4096)


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
