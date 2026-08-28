"""Answer streaming: the SSE transport that turns a question into named
retrieval steps, tokens and citations. `M1-ASK-API-038`.

Answers stream over server-sent events rather than a socket — one direction
covers everything through voice (`M6`), and the ticket's own scope says so.
The property that shapes everything below is not the transport, it is that
generation does not live inside the HTTP request that started it: a browser
tab closed mid-answer, a dropped Wi-Fi interface, a reconnecting
`EventSource` must all find the same turn still in progress or already
finished, never restarted. So a question starts a background task the moment
it is asked (`POST /ask`), and every stream a browser watches — the one
returned from that call and any later reconnect (`GET
/ask/{message_id}/stream`) — only ever tails it. Closing a connection stops
the *watching*; `askwell.ingest`'s own progress stream already established
that distinction for the queue, and this module makes it for one answer.

A tailer needs no lock over the turn it reads: everything here runs on one
asyncio event loop, and appending to a list is not interrupted by an `await`
inside it, so a background task and any number of tailers can share a `_Turn`
by reference alone.

**A reconnect replays the turn's own history before continuing live.** Every
event a turn has ever emitted is kept in memory for its lifetime, so a fresh
connection — the ordinary `POST /ask` response, or a browser's `EventSource`
reattaching after a drop — starts at the beginning of that turn's own events
rather than needing to know what a *previous* connection already delivered.
That is simpler than resuming mid-stream and correct for what this product
is: one browser, one turn at a time, and an answer short enough that
replaying it costs nothing worth optimising away.

Citations are resolved from the model's own `[index]` references into the
`<retrieved-content index="…">` blocks `askwell.agent.compose` built — the
same index the prompt asks the model to cite by — and persisted to the real
`citations` table (`docs/architecture.md` §7), never only to `messages.trace`.

**Since `M1-CITE-BE-042`, a citation is tied to a claim, not just an index.**
`askwell.agent.claims.segment_claims` reads the growing answer text as
sentences, and a sentence only becomes a claim if it carries a marker — a
restatement of the question has none and is never counted, matching C5's own
"abstention over invention" spirit at sentence granularity: no marker means
nothing was asserted to be cited. A claim naming two indices produces two
citation rows sharing one `claim_ordinal`. Each row also carries
`quoted_span` — the claim's own words, if they occur verbatim in the source
chunk, `None` otherwise — resolved with `askwell.agent.claims.locate_quoted_span`
rather than dropped, per the ticket's own edge case.

**Since `M1-CITE-FE-043`, the `citation` event also carries what the margin
card renders.** `documents.filename` and `documents.anchor_kind` are joined in
by `askwell.retrieve` alongside the chunk (`Candidate.filename`,
`Candidate.anchor_kind`), and the event adds `filename`, `anchor_kind`,
`heading` and `passage` (the chunk's full `content`) — the citations table
itself is unchanged, this is display data the browser would otherwise have no
route to.

**Since `M1-ASK-BE-040`, the answer's row exists before there is an answer.**
`POST /ask` writes the assistant `messages` row as `running`, empty, in the
same request that starts the background task — not once generation finishes.
That is what lets a restart be told apart from a turn genuinely still in
progress: nothing in `_turns` survives a process exit, so a `running` row a
fresh process finds at startup can only belong to the process before it.
`reconcile_interrupted` fails every one of those before the first request is
served, so a message can never sit `running` with nothing left generating it.
`_semaphore` bounds how many turns retrieve-and-generate at once
(`Settings.generation_max_concurrent`) — several tabs abandoned at once queue
behind it rather than each starting a full inference pass immediately.
"""

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from askwell.agent.claims import Claim, locate_quoted_span, segment_claims
from askwell.agent.compose import compose
from askwell.audit import Store, record
from askwell.config import Settings
from askwell.db.engine import session_scope
from askwell.inference.client import InferenceClient, InferenceFailed, InferenceUnavailable
from askwell.logging import get_logger
from askwell.retrieve import Candidate, retrieve

log = get_logger(__name__)

ASK_ASKED = "ask_asked"

# How often a tailer re-checks a turn that has nothing new yet. Matches
# `askwell.ingest`'s own idle interval — fast enough that a token feels live,
# slow enough that watching an answer does not become the expensive part of
# answering it.
STREAM_INTERVAL_SECONDS = 0.1

# How many finished turns the registry keeps so a reconnect shortly after
# completion still finds the live object rather than falling back to the
# database. Bounded because this is memory, not a table — a machine left
# running for days must not grow this without limit.
MAX_FINISHED = 200

SSE_HEADERS = {
    "Cache-Control": "no-store",
    "Connection": "keep-alive",
    # Nothing proxies this today. Said anyway, matching `askwell.ingest`: the
    # first thing anyone puts in front of a stream buffers it, and a buffered
    # answer is one that arrives all at once when it is already over.
    "X-Accel-Buffering": "no",
}

Status = Literal["running", "completed", "stopped", "failed"]


@dataclass(frozen=True, slots=True)
class _Event:
    kind: Literal["step", "token", "citation", "done"]
    data: dict[str, Any]


@dataclass(slots=True)
class _Turn:
    """One question's generation, independent of any HTTP connection."""

    message_id: uuid.UUID
    conversation_id: uuid.UUID
    events: list[_Event] = field(default_factory=list)
    text: str = ""
    status: Status = "running"
    stop_requested: bool = False

    def emit(
        self, kind: Literal["step", "token", "citation", "done"], data: dict[str, Any]
    ) -> None:
        self.events.append(_Event(kind, {**data, "message_id": str(self.message_id)}))


_turns: dict[uuid.UUID, _Turn] = {}
_finished_order: list[uuid.UUID] = []

# Bounds how many turns actually retrieve-and-generate at once. Resized
# whenever the configured figure changes rather than fixed at first use —
# one process serves one machine for its whole life so this never happens in
# production, but a test process building several `Settings` in a row must
# not have the first one it saw stick for every test after it.
_generation_semaphore: asyncio.Semaphore | None = None
_generation_semaphore_size: int | None = None


def _semaphore(settings: Settings) -> asyncio.Semaphore:
    global _generation_semaphore, _generation_semaphore_size
    limit = settings.generation_max_concurrent
    if _generation_semaphore is None or _generation_semaphore_size != limit:
        _generation_semaphore = asyncio.Semaphore(limit)
        _generation_semaphore_size = limit
    return _generation_semaphore


def _retire(message_id: uuid.UUID) -> None:
    _finished_order.append(message_id)
    while len(_finished_order) > MAX_FINISHED:
        _turns.pop(_finished_order.pop(0), None)


def _sse(kind: str, data: dict[str, Any]) -> str:
    return f"event: {kind}\ndata: {json.dumps(data, sort_keys=True)}\n\n"


async def _tail(turn: _Turn, request: Request) -> AsyncIterator[str]:
    """Send everything on `turn` so far, then whatever arrives next, until the
    browser leaves or the turn ends.

    Starting at 0 every time — rather than trying to resume mid-stream —
    means a reconnect never has to special-case a turn that finished between
    the drop and the reconnect: it gets the same events a tailer attached
    from the start would have, in one burst, and then continues live if the
    turn is still running. Cheap for one conversation's answer; the
    alternative, tracking exactly what a given browser has already seen, buys
    nothing a single user needs.
    """
    cursor = 0
    while True:
        if await request.is_disconnected():
            return
        pending = turn.events[cursor:]
        cursor = len(turn.events)
        for event in pending:
            yield _sse(event.kind, event.data)
            if event.kind == "done":
                return
        if turn.status != "running" and cursor >= len(turn.events):
            return
        await asyncio.sleep(STREAM_INTERVAL_SECONDS)


async def _load_finished(
    factory: async_sessionmaker[AsyncSession], message_id: uuid.UUID
) -> tuple[str, str] | None:
    """The stored answer for a turn no longer in memory — finished long
    enough ago to have been retired, or from before this process started."""
    async with session_scope(factory) as db:
        row = (
            await db.execute(
                text("SELECT content, trace FROM messages WHERE id = :id AND role = 'assistant'"),
                {"id": message_id},
            )
        ).first()
    if row is None:
        return None
    content, trace = row
    status = trace.get("status", "completed") if isinstance(trace, dict) else "completed"
    return str(content), str(status)


async def reconcile_interrupted(factory: async_sessionmaker[AsyncSession]) -> int:
    """Fail every turn this process finds still `running` at startup.

    Nothing in `_turns` survives a restart — that registry is memory, not a
    table — so any assistant row still marked `running` when a fresh process
    starts is, by definition, one the last process died in the middle of:
    there is one worker on one machine, and this function itself only runs
    once, before `register_ask`'s routes take their first request, so no
    turn genuinely in flight can be caught by it. Left alone, that row would
    satisfy no query for "finished" or "in progress" — `GET
    /ask/{id}/stream` would tail it forever, since nothing will ever append
    to a `_Turn` object that no longer exists. Marked `failed` instead, with
    `interrupted: true` so `/ask/counts` can report it as an abandoned
    generation distinct from an ordinary inference failure.

    Returns the number reconciled, so the caller can log it rather than the
    reconciliation being invisible when it matters.
    """
    async with session_scope(factory) as db:
        result = await db.execute(
            text(
                "UPDATE messages SET trace = trace"
                ' || \'{"status": "failed", "stopped_early": true,'
                ' "interrupted": true,'
                ' "reason": "Askwell restarted before this answer finished."}\'::jsonb'
                " WHERE role = 'assistant' AND trace ->> 'status' = 'running'"
            )
        )
        return int(result.rowcount)  # type: ignore[attr-defined]


class AskRequest(BaseModel):
    """One question. `source_id` scopes retrieval the same way `retrieve()`
    already allows; omitted, the whole live corpus is searched."""

    question: str = Field(min_length=1, max_length=8000)
    conversation_id: uuid.UUID | None = None
    source_id: uuid.UUID | None = None


class _ConversationNotFound(Exception):
    pass


async def _resolve_conversation(db: AsyncSession, conversation_id: uuid.UUID | None) -> uuid.UUID:
    if conversation_id is not None:
        found = await db.execute(
            text("SELECT id FROM conversations WHERE id = :id"), {"id": conversation_id}
        )
        if found.first() is None:
            raise _ConversationNotFound(str(conversation_id))
        return conversation_id

    new_id = uuid.uuid4()
    await db.execute(text("INSERT INTO conversations (id) VALUES (:id)"), {"id": new_id})
    return new_id


def _cite_claim(
    turn: _Turn,
    claim: Claim,
    candidates: list[Candidate],
    citation_rows: list[dict[str, Any]],
) -> None:
    """Turn one completed claim into a citation row per index it named,
    sharing `claim.ordinal` — the ticket's own "two passages, one claim,
    two rows" edge case. An index outside the candidate list is silently
    skipped rather than raising: the model hallucinating a reference number
    is a grounding problem `M2`'s eval suite measures, not a reason to fail
    the whole turn.
    """
    for index in claim.indices:
        if not (1 <= index <= len(candidates)):
            continue
        candidate = candidates[index - 1]
        quoted_span = locate_quoted_span(claim.text, candidate.content)
        citation_rows.append(
            {
                "ordinal": claim.ordinal,
                "chunk_id": candidate.chunk_id,
                "quoted_span": quoted_span,
            }
        )
        turn.emit(
            "citation",
            {
                "claim_ordinal": claim.ordinal,
                "index": index,
                "chunk_id": str(candidate.chunk_id),
                "document_id": str(candidate.document_id),
                "filename": candidate.filename,
                "anchor_kind": candidate.anchor_kind,
                "heading": candidate.heading,
                "page_from": candidate.page_from,
                "page_to": candidate.page_to,
                "passage": candidate.content,
                "quoted_span": quoted_span,
            },
        )


def _label_for_sources(document_count: int) -> str:
    if document_count == 0:
        return "Found nothing in your files for this."
    if document_count == 1:
        return "Reading 1 source."
    return f"Reading {document_count} sources."


async def _generate(
    settings: Settings,
    factory: async_sessionmaker[AsyncSession],
    turn: _Turn,
    question: str,
    source_id: uuid.UUID | None,
) -> None:
    """Retrieve, compose and stream one answer. Runs independently of every
    HTTP connection — see the module docstring.

    Bounded by `_semaphore`: beyond `Settings.generation_max_concurrent`
    turns already retrieving-and-generating, a newly started one waits here
    before doing anything expensive. The pending `messages` row `ask()`
    already wrote is what makes that wait safe to observe from outside —
    the turn is on the record as `running` whether or not it has started
    the actual work yet.
    """
    async with _semaphore(settings):
        await _run_generation(settings, factory, turn, question, source_id)


async def _run_generation(
    settings: Settings,
    factory: async_sessionmaker[AsyncSession],
    turn: _Turn,
    question: str,
    source_id: uuid.UUID | None,
) -> None:
    client = InferenceClient(settings)
    status: Status = "running"
    reason: str | None = None
    candidates: list[Candidate] = []
    citation_rows: list[dict[str, Any]] = []
    claims_emitted = 0
    trace_steps: list[dict[str, Any]] = []
    injection_flagged = False
    injection_patterns: tuple[str, ...] = ()

    turn.emit("step", {"label": "Searching your files.", "kind": "retrieve"})

    try:
        retrieve_started = time.monotonic()
        async with session_scope(factory) as db:
            result = await retrieve(db, client, settings, question, source_id=source_id)
        candidates = result.candidates
        trace_steps.append(
            {
                "kind": "retrieve",
                "ms": (time.monotonic() - retrieve_started) * 1000,
                "query": question,
                "threshold": result.threshold,
                "hits": [{"chunk_id": str(c.chunk_id), "score": c.score} for c in candidates],
            }
        )

        document_count = len({candidate.document_id for candidate in candidates})
        turn.emit("step", {"label": _label_for_sources(document_count), "kind": "read"})

        composed = compose(question, candidates)
        injection_flagged = composed.injection_flagged
        injection_patterns = composed.injection_patterns

        turn.emit("step", {"label": "Writing your answer.", "kind": "compose"})

        prompt = f"{composed.system_prompt}\n\n{composed.user_content}"
        compose_started = time.monotonic()
        truncated = False
        stream = client.stream_generate(prompt, max_tokens=settings.generation_max_tokens)
        async for chunk in stream:
            if turn.stop_requested:
                await stream.aclose()
                status = "stopped"
                break
            if chunk.text:
                turn.text += chunk.text
                turn.emit("token", {"text": chunk.text})
                claims = segment_claims(turn.text)
                for claim in claims[claims_emitted:]:
                    _cite_claim(turn, claim, candidates, citation_rows)
                claims_emitted = len(claims)
            if chunk.done:
                truncated = chunk.truncated

        trace_steps.append(
            {
                "kind": "compose",
                "ms": (time.monotonic() - compose_started) * 1000,
                "claims": claims_emitted,
                "citations": len(citation_rows),
            }
        )

        if status == "running":
            status = "completed"
        if truncated and status == "completed":
            reason = "Reached the answer length limit."
    except (InferenceUnavailable, InferenceFailed) as error:
        status = "failed"
        reason = str(error)
    except Exception:
        status = "failed"
        reason = "Askwell hit an error it did not expect while answering."
        log.exception("ask_generation_failed", message_id=str(turn.message_id))

    trace = {
        "steps": trace_steps,
        "backend": {"mode": "local"},
        "stopped_early": status != "completed",
        "injection_flagged": injection_flagged,
        "injection_patterns": list(injection_patterns),
        "status": status,
        "reason": reason,
    }

    async with session_scope(factory) as db:
        # `ON CONFLICT` rather than a plain `UPDATE`: `ask()` always inserts
        # the pending row ahead of this, but a caller driving `_generate`
        # directly against a turn it built itself — every test in
        # `test_ask_api.py` that isolates stopping or disconnection from the
        # HTTP layer does exactly this — has not, and a message finishing
        # with nowhere to write is a worse bug than the one this ticket
        # exists to close.
        await db.execute(
            text(
                "INSERT INTO messages (id, conversation_id, role, content, trace) "
                "VALUES (:id, :conversation_id, 'assistant', :content, CAST(:trace AS jsonb)) "
                "ON CONFLICT (id) DO UPDATE SET content = :content, trace = CAST(:trace AS jsonb)"
            ),
            {
                "id": turn.message_id,
                "conversation_id": turn.conversation_id,
                "content": turn.text,
                "trace": json.dumps(trace),
            },
        )
        for row in citation_rows:
            await db.execute(
                text(
                    "INSERT INTO citations (id, message_id, chunk_id, claim_ordinal, quoted_span) "
                    "VALUES (:id, :message_id, :chunk_id, :ordinal, :quoted_span)"
                ),
                {
                    "id": uuid.uuid4(),
                    "message_id": turn.message_id,
                    "chunk_id": row["chunk_id"],
                    "ordinal": row["ordinal"],
                    "quoted_span": row["quoted_span"],
                },
            )
        await record(
            db,
            Store.INTERACTIONS,
            ASK_ASKED,
            {
                "conversation_id": str(turn.conversation_id),
                "message_id": str(turn.message_id),
                "question": question,
                "answer": turn.text,
                "status": status,
                "source_id": str(source_id) if source_id else None,
                "claim_count": claims_emitted,
                "citation_count": len(citation_rows),
            },
        )

    turn.emit("done", {"status": status, "reason": reason})
    turn.status = status
    _retire(turn.message_id)


def register_ask(
    app: FastAPI, settings: Settings, factory: async_sessionmaker[AsyncSession]
) -> None:
    """Attach the answer surface. Register before the interface catch-all."""

    @app.get("/ask/counts")
    async def ask_counts() -> JSONResponse:
        """How many answers were started, completed and stopped on this machine.

        The ticket's Analytics Events line, and C1 decides its whole shape:
        these are read out of this machine's own database by this machine's own
        browser, on demand. Nothing is transmitted, nothing is aggregated
        anywhere, and there is no collector to turn off.

        Derived from `messages` rather than counted in memory. A counter held in
        the process resets when the container restarts, which would make
        "answers started" mean "answers started since the last deploy" — a
        number that looks like a total and is not. The rows are the record; the
        count is a question asked of them.

        `started` is every assistant turn, because a turn that was recorded was
        started. `running` is carried separately rather than folded into
        started-minus-the-rest, so a turn that died with the process is visible
        as itself rather than silently inflating any of the other three.

        `abandoned` is the ticket's own local counter (`M1-ASK-BE-040`): a
        turn `reconcile_interrupted` found still `running` at some earlier
        startup and failed on the machine's behalf, not one that failed
        because the assistant itself errored. A subset of `failed`, kept
        separate so "the model keeps erroring" and "the machine keeps
        getting restarted mid-answer" read as the different facts they are.
        """
        async with session_scope(factory) as db:
            result = await db.execute(
                text(
                    "SELECT count(*) AS started, "
                    "count(*) FILTER (WHERE trace ->> 'status' = 'completed') AS completed, "
                    "count(*) FILTER (WHERE trace ->> 'status' = 'stopped') AS stopped, "
                    "count(*) FILTER (WHERE trace ->> 'status' = 'failed') AS failed, "
                    "count(*) FILTER (WHERE trace ->> 'status' = 'running') AS running, "
                    "count(*) FILTER (WHERE (trace ->> 'interrupted')::boolean) AS abandoned "
                    "FROM messages WHERE role = 'assistant'"
                )
            )
            row = result.one()
        return JSONResponse(
            {
                "started": row[0],
                "completed": row[1],
                "stopped": row[2],
                "failed": row[3],
                "running": row[4],
                "abandoned": row[5],
            }
        )

    @app.post("/ask", response_model=None)
    async def ask(body: AskRequest, request: Request) -> StreamingResponse | JSONResponse:
        async with session_scope(factory) as db:
            try:
                conversation_id = await _resolve_conversation(db, body.conversation_id)
            except _ConversationNotFound:
                return JSONResponse(
                    {"error": "Askwell has no conversation with that id."}, status_code=404
                )

            question_id = uuid.uuid4()
            await db.execute(
                text(
                    "INSERT INTO messages (id, conversation_id, role, content) "
                    "VALUES (:id, :conversation_id, 'user', :content)"
                ),
                {"id": question_id, "conversation_id": conversation_id, "content": body.question},
            )

            # A pending row goes in before the background task is even
            # created, not after it finishes — a turn a client never sees
            # started must still be a row `reconcile_interrupted` can find
            # and fail on the next startup, rather than nothing at all.
            message_id = uuid.uuid4()
            await db.execute(
                text(
                    "INSERT INTO messages (id, conversation_id, role, content, trace) "
                    "VALUES (:id, :conversation_id, 'assistant', '', "
                    "CAST(:trace AS jsonb))"
                ),
                {
                    "id": message_id,
                    "conversation_id": conversation_id,
                    "trace": json.dumps({"status": "running", "steps": []}),
                },
            )

        turn = _Turn(message_id=message_id, conversation_id=conversation_id)
        _turns[turn.message_id] = turn
        asyncio.create_task(  # noqa: RUF006 — deliberately outlives this request; see module docstring
            _generate(settings, factory, turn, body.question, body.source_id)
        )

        return StreamingResponse(
            _tail(turn, request), media_type="text/event-stream", headers=SSE_HEADERS
        )

    @app.get("/ask/{message_id}/stream", response_model=None)
    async def ask_stream(
        message_id: uuid.UUID, request: Request
    ) -> StreamingResponse | JSONResponse:
        turn = _turns.get(message_id)
        if turn is not None:
            return StreamingResponse(
                _tail(turn, request), media_type="text/event-stream", headers=SSE_HEADERS
            )

        stored = await _load_finished(factory, message_id)
        if stored is None:
            return JSONResponse({"error": "Askwell has no turn with that id."}, status_code=404)
        content, status = stored

        async def replay() -> AsyncIterator[str]:
            if content:
                yield _sse("token", {"text": content, "message_id": str(message_id)})
            yield _sse("done", {"status": status, "reason": None, "message_id": str(message_id)})

        return StreamingResponse(replay(), media_type="text/event-stream", headers=SSE_HEADERS)

    @app.post("/ask/{message_id}/stop")
    async def ask_stop(message_id: uuid.UUID) -> JSONResponse:
        turn = _turns.get(message_id)
        if turn is None or turn.status != "running":
            return JSONResponse(
                {"error": "Askwell has no turn in progress with that id."}, status_code=404
            )
        turn.stop_requested = True
        return JSONResponse({"message_id": str(message_id), "status": "stopping"}, status_code=202)
