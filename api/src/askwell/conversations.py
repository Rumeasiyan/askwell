"""Past conversations, read back. Issue #199.

Every question and answer has always been stored (`messages`, with its
citations in `citations`); nothing could read them back, so a reload lost the
conversation on screen and no screen listed earlier ones. Two read-only
routes:

- `GET /conversations` — the list the History screen shows, newest activity
  first, twenty at a time (`conversation.md` §7's page size). A conversation
  created ahead of its first question (`POST /conversations`, for the online
  disclosure) and never asked anything is not history and is left out.
- `GET /conversations/{id}/turns` — every turn of one conversation, in the
  shape the Ask screen's own live turn carries, **with its citations**. An old
  answer shown without its sources would be an uncited claim on screen (C4),
  so a passage that can no longer be shown says why instead: its document was
  deleted (`deleted`), or Askwell is locked and the passage is encrypted
  (`locked`), or its stored token no longer decrypts (`unreadable`). Never an
empty card that reads as "no source".

**Pairing.** A question and its answer are written in one transaction
(`ask.py`'s `POST /ask`) and so share `created_at`; nothing links them by key.
Turns are paired in `(created_at, role)` order — `user` sorts before
`assistant` — which is deterministic for that reason, and robust to a turn
whose answer row is missing (the question is kept, marked `failed`).

Reads only. Nothing here writes, and nothing here decides online or local:
reopening a conversation that used online AI is switched back to local by the
interface through `DELETE /conversations/{id}/online` before it is shown (C1:
online is a deliberate act, never inherited).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from sqlalchemy import text

from askwell import passphrase, retrieve
from askwell.crypto import CredentialsLocked
from askwell.db.engine import session_scope
from askwell.logging import get_logger

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from askwell.config import Settings

log = get_logger(__name__)

PAGE_SIZE = 20
# Long enough to recognise a question, short enough for one line in a list.
TITLE_LENGTH = 120


def _title(question: str) -> str:
    flat = " ".join(question.split())
    return flat if len(flat) <= TITLE_LENGTH else flat[: TITLE_LENGTH - 1].rstrip() + "…"


async def list_conversations(
    db: AsyncSession, *, before: datetime | None, limit: int = PAGE_SIZE
) -> dict[str, Any]:
    rows = (
        await db.execute(
            text(
                "SELECT c.id, c.created_at, c.ai_backend, "
                "  count(*) FILTER (WHERE m.role = 'user') AS questions, "
                "  max(m.created_at) AS last_activity, "
                "  (SELECT q.content FROM messages q WHERE q.conversation_id = c.id "
                "     AND q.role = 'user' ORDER BY q.created_at, q.id LIMIT 1) AS first_question "
                "FROM conversations c JOIN messages m ON m.conversation_id = c.id "
                "GROUP BY c.id "
                "HAVING count(*) FILTER (WHERE m.role = 'user') > 0 "
                "  AND (CAST(:before AS timestamptz) IS NULL "
                "       OR max(m.created_at) < CAST(:before AS timestamptz)) "
                "ORDER BY last_activity DESC, c.id "
                "LIMIT :limit"
            ),
            {"before": before, "limit": limit + 1},
        )
    ).all()
    page = rows[:limit]
    return {
        "conversations": [
            {
                "id": str(row.id),
                "title": _title(row.first_question or ""),
                "created_at": row.created_at.isoformat(),
                "last_activity_at": row.last_activity.isoformat(),
                "question_count": int(row.questions),
                "ai_backend": row.ai_backend,
            }
            for row in page
        ],
        # The cursor is the last row's own activity time, so a conversation
        # that gains a turn while the user scrolls moves to the top rather
        # than appearing twice.
        "next_before": page[-1].last_activity.isoformat() if len(rows) > limit else None,
    }


async def _citations(
    db: AsyncSession, settings: Settings, message_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[dict[str, Any]]]:
    if not message_ids:
        return {}
    rows = (
        await db.execute(
            text(
                "SELECT ci.message_id, ci.claim_ordinal, ci.quoted_span, ch.id AS chunk_id, "
                "  ch.content, ch.content_encrypted, ch.heading, ch.page_from, ch.page_to, "
                "  d.id AS document_id, d.filename, d.anchor_kind, d.deleted_at "
                "FROM citations ci "
                "JOIN chunks ch ON ch.id = ci.chunk_id "
                "JOIN documents d ON d.id = ch.document_id "
                "WHERE ci.message_id = ANY(:ids) "
                "ORDER BY ci.message_id, ci.claim_ordinal, ch.id"
            ),
            {"ids": message_ids},
        )
    ).all()
    by_message: dict[uuid.UUID, list[dict[str, Any]]] = {}
    for row in rows:
        passage: str | None = None
        unavailable: str | None = None
        if row.deleted_at is not None or row.content is None:
            unavailable = "deleted"
        else:
            try:
                passage = await retrieve._decrypt(
                    db, settings, row.content, bool(row.content_encrypted)
                )
            except passphrase.Locked:
                # A passphrase is set and this process is not unlocked yet.
                unavailable = "locked"
            except CredentialsLocked:
                # The stored token does not decrypt with the current key.
                unavailable = "unreadable"
        by_message.setdefault(row.message_id, []).append(
            {
                "claim_ordinal": row.claim_ordinal,
                "chunk_id": str(row.chunk_id),
                "document_id": str(row.document_id),
                "filename": row.filename,
                "anchor_kind": row.anchor_kind,
                "heading": row.heading,
                "page_from": row.page_from,
                "page_to": row.page_to,
                "passage": passage,
                "quoted_span": row.quoted_span,
                "passage_unavailable": unavailable,
            }
        )
    return by_message


async def conversation_turns(
    db: AsyncSession, settings: Settings, conversation_id: uuid.UUID
) -> dict[str, Any] | None:
    conversation = (
        await db.execute(
            text("SELECT id, created_at, ai_backend FROM conversations WHERE id = :id"),
            {"id": conversation_id},
        )
    ).first()
    if conversation is None:
        return None

    messages = (
        await db.execute(
            text(
                "SELECT id, role, content, trace, summary, source_count, sql_result, "
                "  model_identity, created_at "
                "FROM messages WHERE conversation_id = :id AND role IN ('user', 'assistant') "
                "ORDER BY created_at, CASE role WHEN 'user' THEN 0 ELSE 1 END, id"
            ),
            {"id": conversation_id},
        )
    ).all()

    turns: list[dict[str, Any]] = []
    for message in messages:
        if message.role == "user":
            turns.append(
                {
                    "question_id": str(message.id),
                    "message_id": None,
                    "question": message.content,
                    "asked_at": message.created_at.isoformat(),
                    "answer": "",
                    # A question whose answer row never landed is shown as
                    # failed, with a reason, rather than dropped.
                    "status": "failed",
                    "reason": "This question has no recorded answer.",
                    "db_state": None,
                    "summary": None,
                    "source_count": None,
                    "sql_result": None,
                    "model_identity": None,
                    "citations": [],
                }
            )
            continue
        if not turns or turns[-1]["message_id"] is not None:
            # An answer with no question before it is not a turn the screen
            # can show; it is logged, never invented a question for.
            log.warning("conversation_orphan_answer", message_id=str(message.id))
            continue
        trace = message.trace or {}
        status = str(trace.get("status") or ("completed" if message.content else "failed"))
        reason = trace.get("reason")
        if status == "running":
            # Still being written, or interrupted before it finished: either
            # way not an answer yet, and said so.
            status, reason = "stopped", "This answer had not finished when it was opened."
        turns[-1].update(
            {
                "message_id": str(message.id),
                "answer": message.content,
                "status": status,
                "reason": reason if isinstance(reason, str) else None,
                "db_state": trace.get("db_state"),
                "summary": message.summary,
                "source_count": message.source_count,
                "sql_result": message.sql_result,
                "model_identity": message.model_identity,
            }
        )

    answered = [uuid.UUID(turn["message_id"]) for turn in turns if turn["message_id"]]
    citations = await _citations(db, settings, answered)
    for turn in turns:
        if turn["message_id"]:
            turn["citations"] = citations.get(uuid.UUID(turn["message_id"]), [])

    return {
        "conversation": {
            "id": str(conversation.id),
            "created_at": conversation.created_at.isoformat(),
            "ai_backend": conversation.ai_backend,
        },
        "turns": turns,
    }


def register_conversations(
    app: FastAPI, settings: Settings, factory: async_sessionmaker[AsyncSession]
) -> None:
    @app.get("/conversations")
    async def conversations(
        before: datetime | None = None, limit: int = Query(PAGE_SIZE, ge=1, le=100)
    ) -> JSONResponse:
        async with session_scope(factory) as db:
            return JSONResponse(await list_conversations(db, before=before, limit=limit))

    @app.get("/conversations/{conversation_id}/turns")
    async def turns(conversation_id: uuid.UUID) -> JSONResponse:
        async with session_scope(factory) as db:
            body = await conversation_turns(db, settings, conversation_id)
        if body is None:
            return JSONResponse(
                {"error": "Askwell has no conversation with that id."}, status_code=404
            )
        return JSONResponse(body)
