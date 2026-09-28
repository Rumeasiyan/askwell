"""Remembering which of two conflicting documents is current. `M9-FIX-FE-204`,
issue #728.

`docs/ux/ask.md` §5: a conflicting-sources answer "offers to resolve, which
writes a memory fact". The offer is the Ask screen's "Which one is current?";
this is the write behind it. Until this ticket the choice lived in the tab's
React state and was lost when the tab closed, while memory had shipped in M3.

The fact is an ordinary `memory` row written through
`askwell.memory.write_memory_fact`, `origin='clarification'` — the user
answered a question Askwell asked, which is what that origin means, and it
is the same row an answered clarification produces. Nothing about it is a
second kind of memory: the Memory screen lists it, `retrieve_relevant_facts`
finds it for the next question on the topic, and correcting or deleting it
is the Memory screen's ordinary path.

The browser names only the turn and the document. The subject and the
fact's text are built here from what the database already holds — the
conflict line in the stored answer and the filenames the turn cited — so the
written fact can only ever name documents the answer actually cited (C4),
and a client cannot write arbitrary text into memory through this route.

Choosing again for the same subject supersedes rather than duplicates:
`write_memory_fact` retires every active fact for the subject when a
user-origin fact is written. Choosing the same document twice writes
nothing the second time.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from askwell.agent.conflict import split_conflict_answer
from askwell.db.engine import session_scope
from askwell.memory import write_memory_fact

# The longest subject `memory` accepts through the manual route
# (`ManualFactRequest.subject`); a question used as the subject is cut to it.
_SUBJECT_MAX = 256


class TurnNotFound(LookupError):
    """No assistant turn with that id."""


class NotAConflict(ValueError):
    """The turn's answer presents no conflict, so there is nothing to resolve."""


class DocumentNotCited(ValueError):
    """The chosen document is not one the turn cited."""


@dataclass(frozen=True, slots=True)
class ConflictResolution:
    fact_id: uuid.UUID
    subject: str
    fact: str
    # `False` when the same document was already the remembered choice and
    # nothing was written.
    written: bool


def _fact_text(subject: str, chosen: str, others: list[str]) -> str:
    fact = f"{chosen} is the current document for {subject}"
    if others:
        fact += f", not {' or '.join(others)}"
    return fact + "."


async def resolve_conflict(
    session: AsyncSession, *, message_id: uuid.UUID, document_id: uuid.UUID
) -> ConflictResolution:
    """Write "`document_id` is current" for the conflict `message_id` presented.

    The subject is the topic on the answer's "Conflicting sources on ...:"
    line. A line left naming nothing (a stripped placeholder,
    `askwell.agent.placeholders`) falls back to the question that was asked,
    so the fact still carries the words the next such question will be
    matched on.
    """
    row = (
        await session.execute(
            text(
                "SELECT content, conversation_id, created_at FROM messages "
                "WHERE id = :id AND role = 'assistant'"
            ),
            {"id": message_id},
        )
    ).first()
    if row is None:
        raise TurnNotFound(str(message_id))
    content, conversation_id, created_at = row

    topic = split_conflict_answer(content).topic
    if topic is None:
        raise NotAConflict(str(message_id))
    if topic == "":
        question = (
            await session.execute(
                text(
                    "SELECT content FROM messages WHERE conversation_id = :conversation_id "
                    "AND role = 'user' AND created_at <= :created_at "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"conversation_id": conversation_id, "created_at": created_at},
            )
        ).scalar_one_or_none()
        topic = " ".join((question or "").split())[:_SUBJECT_MAX] or "this question"
    subject = topic

    cited = (
        await session.execute(
            text(
                "SELECT DISTINCT d.id, d.filename FROM citations c "
                "JOIN chunks ch ON ch.id = c.chunk_id "
                "JOIN documents d ON d.id = ch.document_id "
                "WHERE c.message_id = :message_id ORDER BY d.filename"
            ),
            {"message_id": message_id},
        )
    ).all()
    chosen = next((entry for entry in cited if entry[0] == document_id), None)
    if chosen is None:
        raise DocumentNotCited(str(document_id))
    others = sorted({entry[1] for entry in cited if entry[0] != document_id} - {chosen[1]})
    fact = _fact_text(subject, chosen[1], others)

    # Two tabs choosing at once would otherwise each insert before either
    # retires the other, leaving two active facts for one subject. The
    # two-key form never collides with `askwell.audit`'s one-key locks.
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext('memory_subject'), hashtext(:subject))"),
        {"subject": subject},
    )
    current = (
        await session.execute(
            text(
                "SELECT id FROM memory WHERE subject = :subject AND fact = :fact "
                "AND origin != 'inferred' AND superseded_by IS NULL LIMIT 1"
            ),
            {"subject": subject, "fact": fact},
        )
    ).scalar_one_or_none()
    if current is not None:
        return ConflictResolution(fact_id=current, subject=subject, fact=fact, written=False)

    # No `source_id`: the fact is read when a question is asked, never at
    # ingest, and a source on it would make correcting or deleting it on the
    # Memory screen re-read that whole source (`memory._reprocess_subject`).
    fact_id = await write_memory_fact(session, subject=subject, fact=fact, origin="clarification")
    assert fact_id is not None, "a user-origin write is never discarded"
    return ConflictResolution(fact_id=fact_id, subject=subject, fact=fact, written=True)


class ResolveConflictRequest(BaseModel):
    document_id: uuid.UUID


def register_conflict_resolution(app: FastAPI, factory: async_sessionmaker[AsyncSession]) -> None:
    """Register before the interface catch-all, same as every other route module."""

    @app.post("/ask/{message_id}/resolve-conflict")
    async def resolve_conflict_route(
        message_id: uuid.UUID, body: ResolveConflictRequest
    ) -> JSONResponse:
        try:
            async with session_scope(factory) as db:
                outcome = await resolve_conflict(
                    db, message_id=message_id, document_id=body.document_id
                )
        except TurnNotFound:
            return JSONResponse({"error": "Askwell has no answer with that id."}, status_code=404)
        except NotAConflict:
            return JSONResponse(
                {"error": "That answer presents no conflict to resolve."}, status_code=409
            )
        except DocumentNotCited:
            return JSONResponse(
                {"error": "That document is not one this answer cited."}, status_code=400
            )
        return JSONResponse(
            {
                "fact_id": str(outcome.fact_id),
                "subject": outcome.subject,
                "fact": outcome.fact,
                "written": outcome.written,
            }
        )
