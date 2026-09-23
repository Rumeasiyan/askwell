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
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal, NamedTuple, cast

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from askwell import crypto, passphrase
from askwell.agent.abstain import AbstainReason, compose_abstention
from askwell.agent.claims import Claim, locate_quoted_span, segment_claims
from askwell.agent.conflict import compose_conflict, split_conflict_answer
from askwell.agent.loop import LoopContinuation, LoopResult, ToolCallEvent, run_tool_loop
from askwell.agent.partial import split_partial_answer
from askwell.agent.sql_generate import (
    GenerationReason,
    generate_candidate_query,
    list_database_sources,
)
from askwell.agent.summarize import fallback_summary, summarize_turn
from askwell.agent.think import ThinkStripper
from askwell.audit import AuditError, Store, record
from askwell.config import Settings
from askwell.connections import Engine
from askwell.db.engine import session_scope
from askwell.inference.client import InferenceClient, InferenceFailed, InferenceUnavailable
from askwell.ingest import coverage
from askwell.inline_clarify import default_assumption, find_blocking
from askwell.logging import get_logger
from askwell.memory import MemoryFact, SchemaNote, retrieve_relevant_facts
from askwell.model_select import active_model_identity
from askwell.retrieve import Candidate, candidate_score, retrieve
from askwell.sql import execute as sql_execute_checked
from askwell.sql.dry_run import DryRunReason, dry_run_connection_query, dry_run_sandbox_query
from askwell.sql.limit import inject_limit
from askwell.sql.validate import validate_query
from askwell.sql_execute import (
    ConnectionUnreachable,
    CredentialsRejected,
    QueryRejected,
    StatementTimedOut,
)
from askwell.traces import TraceRing

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
    kind: Literal[
        "step",
        "token",
        "citation",
        "fact_citation",
        "clarification",
        "clarification_resolved",
        "done",
    ]
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
    # `M7-SET-FE-146a`: captured once, at question time (`ask()`'s own
    # `active_model_identity` call), and carried unchanged through every
    # `done` event this turn emits — never recomputed mid-generation, so a
    # swap that lands while this turn is still running does not relabel an
    # answer it never touched.
    model_identity: dict[str, Any] | None = None
    # `M3-INLINE-FE-085`: set while this turn is paused on an inline
    # clarification, `None` the rest of the time. `clarify_event` is what
    # `POST /ask/{id}/clarify/resolve` sets once the browser has answered or
    # skipped it through the ordinary `askwell.review` endpoints — a plain
    # `asyncio.Event` rather than a `Future`, since a turn only ever pauses
    # on one clarification and the same object can be waited on more than
    # once without the "already retrieved" `InvalidStateError` a `Future`
    # would raise on a second `await`.
    clarify_id: uuid.UUID | None = None
    clarify_event: asyncio.Event = field(default_factory=asyncio.Event)
    clarify_result: dict[str, Any] | None = None
    # `M5-TRACE-BE-125`: the same list `_run_generation` builds `messages.trace`
    # from, shared by reference rather than copied — so `GET
    # /ask/{message_id}/trace` can read a running turn's steps as they are
    # appended, before the row that will eventually hold them exists at all.
    trace_steps: list[dict[str, Any]] = field(default_factory=list)

    def emit(
        self,
        kind: Literal[
            "step",
            "token",
            "citation",
            "fact_citation",
            "clarification",
            "clarification_resolved",
            "done",
        ],
        data: dict[str, Any],
    ) -> None:
        # Both ids on every event, for the same reason: the browser cannot know
        # either one until the server says so. `conversation_id` is resolved or
        # created server-side and was never returned, so the screen had nothing
        # to send back and every question started a fresh conversation — a
        # product built around asking follow-ups where no follow-up could reach
        # the turn before it.
        self.events.append(
            _Event(
                kind,
                {
                    **data,
                    "message_id": str(self.message_id),
                    "conversation_id": str(self.conversation_id),
                },
            )
        )


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


def generation_semaphore(settings: Settings) -> asyncio.Semaphore:
    """The same semaphore `_generate` bounds itself with, for a caller outside
    this module that needs to wait for every in-flight turn to finish rather
    than just the next one.

    `askwell.model_select` is that caller: a model swap acquires every permit
    before touching the inference process, which is what "queued until the
    turn finishes" (`M7-SET-BE-145a`'s own edge case) means in practice — a
    turn already generating keeps its permit until it is done, and a new one
    cannot start until the swap releases them all.
    """
    return _semaphore(settings)


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


# content, status, summary, source_count, conversation_id, sql_result, sql_query,
# model_identity
_FinishedTurn = tuple[
    str,
    str,
    str | None,
    int | None,
    str,
    dict[str, Any] | None,
    dict[str, Any] | None,
    dict[str, Any] | None,
]


async def _load_finished(
    factory: async_sessionmaker[AsyncSession], message_id: uuid.UUID
) -> _FinishedTurn | None:
    """The stored answer for a turn no longer in memory — finished long
    enough ago to have been retired, or from before this process started."""
    async with session_scope(factory) as db:
        row = (
            await db.execute(
                text(
                    "SELECT content, trace, summary, source_count, conversation_id, sql_result, "
                    "model_identity "
                    "FROM messages WHERE id = :id AND role = 'assistant'"
                ),
                {"id": message_id},
            )
        ).first()
    if row is None:
        return None
    content, trace, summary, source_count, conversation_id, sql_result, model_identity = row
    status = trace.get("status", "completed") if isinstance(trace, dict) else "completed"
    # The conversation id comes back with it: a browser reconnecting to a
    # finished turn needs it as much as one watching a live turn, and after a
    # reload it has no other way to learn which conversation it is in.
    # `sql_result` (`M4-SQL-BE-108a`): the same snapshot a database-answered
    # turn's live `done` event carried, read back rather than re-run — the
    # ticket's own Assumption that a stored result never changes under a
    # reopened conversation. `sql_query` (`M4-RESULT-FE-110`): the same
    # disclosure a live `done` event carries for a branch `sql_result` never
    # does, reconstructed from the sql step already sitting in this same
    # stored `trace` rather than a second column.
    sql_query = _sql_query_from_trace(trace) if sql_result is None else None
    return (
        str(content),
        str(status),
        summary,
        source_count,
        str(conversation_id),
        sql_result,
        sql_query,
        model_identity,
    )


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
                ' "reason": "Askwell restarted before this answer finished."}\'::jsonb, '
                "summary = COALESCE(summary, "
                "'Could not answer: Askwell restarted before this answer finished.'), "
                "source_count = NULL "
                "WHERE role = 'assistant' AND trace ->> 'status' = 'running'"
            )
        )
        return int(result.rowcount)  # type: ignore[attr-defined]


class AskRequest(BaseModel):
    """One question. `source_id` scopes retrieval the same way `retrieve()`
    already allows; omitted, the whole live corpus is searched.

    `continue_from` (`M5-LOOP-BE-116`) is the **Continue** action's own
    field: the id of a turn that stopped at the tool-call ceiling, so this
    new turn can pick up its gathered `<tool-result>` history rather than
    starting over. `question` is still required and should be resent
    unchanged — this is a new turn, not a resumed HTTP request, and the
    server has no other way to know what it is continuing to answer.
    """

    question: str = Field(min_length=1, max_length=8000)
    conversation_id: uuid.UUID | None = None
    source_id: uuid.UUID | None = None
    continue_from: uuid.UUID | None = None


class ClarifyResolveRequest(BaseModel):
    """`POST /ask/{message_id}/clarify/resolve`'s only body: which pending
    clarification to check for, so a stale or mismatched id is refused by
    name rather than silently resuming the wrong turn."""

    clarification_id: uuid.UUID


class _ConversationNotFound(Exception):
    pass


class _ClarificationAbandoned(Exception):
    """The browser stopped this turn while it was paused on an inline
    clarification (`_await_clarification`) — a `Stop` click, not a failure,
    so it is handled where `InferenceUnavailable`/`InferenceFailed` are,
    never by the generic "hit an error it did not expect" branch."""


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
    facts: Sequence[MemoryFact],
    notes: Sequence[SchemaNote],
    fact_usage_rows: list[dict[str, Any]],
) -> None:
    """Turn one completed claim into a citation row per index it named,
    sharing `claim.ordinal` — the ticket's own "two passages, one claim,
    two rows" edge case. An index outside every known range is silently
    skipped rather than raising: the model hallucinating a reference number
    is a grounding problem `M2`'s eval suite measures, not a reason to fail
    the whole turn.

    Indices `1..len(candidates)` are documents, same as before `M3-APPLY-
    BE-079`. `compose_conflict` numbers `facts` and then `notes` straight on
    from there (`conflict.py`'s `facts_start`/`notes_start`) — an index past
    the candidates resolves against whichever of those two ranges it falls
    in, and writes to `fact_usage` instead of `citations`. `fact_usage` has
    no `claim_ordinal` column (it is "was this fact used in this answer at
    all", not "which sentence"), so a fact cited by two claims in one answer
    still produces one row — the caller de-duplicates before the insert.
    """
    doc_count = len(candidates)
    facts_start = doc_count + 1
    notes_start = facts_start + len(facts)
    for index in claim.indices:
        if 1 <= index <= doc_count:
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
        elif facts_start <= index < notes_start:
            fact = facts[index - facts_start]
            fact_usage_rows.append({"fact_kind": "memory", "fact_id": fact.id})
            turn.emit(
                "fact_citation",
                {
                    "claim_ordinal": claim.ordinal,
                    "index": index,
                    "fact_kind": "memory",
                    "fact_id": str(fact.id),
                    "subject": fact.subject,
                    "fact": fact.fact,
                    "origin": fact.origin,
                    "confidence": fact.confidence,
                    "supplied_at": fact.created_at.isoformat()
                    if fact.created_at is not None
                    else None,
                },
            )
        elif notes_start <= index < notes_start + len(notes):
            note = notes[index - notes_start]
            fact_usage_rows.append({"fact_kind": "schema_note", "fact_id": note.id})
            turn.emit(
                "fact_citation",
                {
                    "claim_ordinal": claim.ordinal,
                    "index": index,
                    "fact_kind": "schema_note",
                    "fact_id": str(note.id),
                    "subject": (
                        f"{note.table_name}.{note.column_name}"
                        if note.column_name
                        else note.table_name
                    ),
                    "fact": note.description,
                    "origin": note.origin,
                    "confidence": note.confidence,
                    "stale": note.stale,
                    "supplied_at": note.created_at.isoformat()
                    if note.created_at is not None
                    else None,
                },
            )


async def _await_clarification(turn: _Turn) -> dict[str, Any] | None:
    """Wait for `POST /ask/{id}/clarify/resolve` to answer or skip the
    clarification just emitted, or for the browser to stop this turn while
    it waits — `None` on the latter.

    Polled rather than a bare `await turn.clarify_event.wait()` so `Stop`
    (`docs/ux/clarifications.md` §5's own rule: this never becomes a second
    place the user is stuck waiting) still works while paused here, the same
    way the token-streaming loop below already checks `stop_requested` on
    every chunk. There is no chunk to check between here and an answer that
    may never come — a user who navigates away and never returns leaves the
    clarification sitting `pending` in the ordinary queue (never lost, never
    re-asked) and this turn paused indefinitely, which is the accepted cost
    of "never bounce the user mid-question" rather than a timeout inventing
    an answer nobody gave.
    """
    while not turn.clarify_event.is_set():
        if turn.stop_requested:
            return None
        try:
            await asyncio.wait_for(turn.clarify_event.wait(), timeout=0.2)
        except TimeoutError:
            continue
    return turn.clarify_result


def _label_for_sources(document_count: int) -> str:
    if document_count == 0:
        return "Found nothing in your files for this."
    if document_count == 1:
        return "Reading 1 source."
    return f"Reading {document_count} sources."


# `M5-LOOP-FE-118`: one line per tool naming the real operation, never the
# raw tool name `M5-LOOP-BE-117a` shipped as a placeholder (`Called
# document_search.`) until this ticket's frontend could tell a `start` from
# an `end`. Source-scoped wording (`querying sales-2024`) is deferred —
# `ToolCallEvent.arguments` carries only a `source_id` UUID, and resolving it
# to a name needs a database read this observer, called synchronously from
# inside `run_tool_loop`, cannot make without either an async signature
# change to `ToolCallObserver` (`M5-LOOP-BE-117a`'s own explicit scope
# boundary) or a second query per call — filed as issue #422 rather than
# guessed at here.
_TOOL_STEP_LABELS: dict[str, tuple[str, str]] = {
    "document_search": ("Searching your files.", "Searched your files."),
    "database_query": ("Querying your database.", "Queried your database."),
    "schema_lookup": ("Looking up your database schema.", "Looked up your database schema."),
    "document_listing": ("Listing your documents.", "Listed your documents."),
    "current_date": ("Checking today's date.", "Checked today's date."),
}


def _tool_call_step(event: ToolCallEvent) -> dict[str, Any]:
    """One `step` payload for a live per-call event. `call_id` and `phase`
    travel on every event so `web/lib/ask.ts::applyAskEvent` can update a
    call's own entry in place rather than appending a second line for the
    same call — which is also what lets two calls dispatched in the same
    batch render as two concurrent entries instead of a queue, since each
    keeps its own `call_id`.
    """
    starting, finished = _TOOL_STEP_LABELS.get(
        event.tool, (f"Calling {event.tool}.", f"Called {event.tool}.")
    )
    if event.phase == "start":
        label = starting
    elif event.outcome == "ok":
        label = finished
    else:
        # Edge case named in the ticket itself: a failed call names the
        # change of approach rather than freezing on the attempt that just
        # failed.
        label = f"{starting} That didn't work — trying another way."
    return {
        "label": label,
        "kind": "tool",
        "tool": event.tool,
        "call_id": event.call_id,
        "phase": event.phase,
    }


class _AbstainContext(NamedTuple):
    """Why this turn abstained, plus what `askwell.agent.abstain.compose_abstention`
    needs to prove the search happened: real counts, not the top-K
    `candidates` list already in memory, which is capped at
    `Settings.retrieval_candidate_count` and would under-report a large
    corpus (`docs/ux/ask.md` §6's own "very large corpus" edge case).
    """

    reason_code: AbstainReason
    passage_count: int
    document_count: int
    database_count: int


# `sources.kind` (`ck_sources_kind`): `file`/`csv` are documents, `dump`/
# `connection` are the ticket's own "databases" — a source imported or
# connected, never a document the ingest pipeline extracted text from.
_DOCUMENT_SOURCE_KINDS = ("file", "csv")
_DATABASE_SOURCE_KINDS = ("dump", "connection")

# The same join and `WHERE` `askwell.retrieve`'s own dense/lexical searches
# use (`_dense_search`/`_lexical_search`), scoped identically by
# `source_id` — the count this proves searched must be provably the same
# population `retrieve()` actually queried, not a related-but-different one.
_SEARCH_EXTENT_SQL = text(
    "SELECT count(c.id) AS passages, "
    "count(DISTINCT CASE WHEN s.kind = ANY(:document_kinds) THEN d.id END) AS documents, "
    "count(DISTINCT CASE WHEN s.kind = ANY(:database_kinds) THEN s.id END) AS databases "
    "FROM chunks c "
    "JOIN documents d ON d.id = c.document_id "
    "JOIN sources s ON s.id = d.source_id "
    "WHERE d.deleted_at IS NULL AND d.superseded_by IS NULL "
    "AND (CAST(:source_id AS uuid) IS NULL OR d.source_id = CAST(:source_id AS uuid))"
)


async def _abstain_reason(
    factory: async_sessionmaker[AsyncSession], settings: Settings, source_id: uuid.UUID | None
) -> _AbstainContext:
    """Why this turn abstained, distinct from "nothing scored high enough" —
    the ticket's own edge cases: an empty corpus has nothing to match
    against at all, and a source scoped question against a source still
    indexing is missing content, not merely unmatched by what exists.

    `M2-ABSTAIN-RET-053` left `reason_code` as a placeholder for this
    ticket's copy; the counts alongside it are what let
    `askwell.agent.abstain.compose_abstention` prove the search happened
    rather than merely assert it happened.
    """
    async with session_scope(factory) as db:
        reason_code: AbstainReason
        if source_id is not None:
            cov = await coverage(db, source_id, settings.ocr_confidence_threshold)
            if cov.total == 0:
                reason_code = "empty_corpus"
            elif cov.ready < cov.total:
                reason_code = "source_indexing"
            else:
                reason_code = "below_threshold"
        else:
            # Chunk existence, not `documents.status = 'ready'`:
            # `askwell.retrieve` searches every live document's chunks
            # regardless of where that document's own pipeline stage is (its
            # dense and lexical queries filter only
            # `deleted_at`/`superseded_by`), so "empty" has to mean the same
            # thing here or a corpus mid-indexing with something already
            # searchable would be misreported as having nothing at all.
            indexed = (
                await db.execute(
                    text(
                        "SELECT count(*) FROM chunks c JOIN documents d ON d.id = c.document_id "
                        "WHERE d.deleted_at IS NULL AND d.superseded_by IS NULL"
                    )
                )
            ).scalar_one()
            reason_code = "empty_corpus" if indexed == 0 else "below_threshold"

        extent = (
            await db.execute(
                _SEARCH_EXTENT_SQL,
                {
                    "document_kinds": list(_DOCUMENT_SOURCE_KINDS),
                    "database_kinds": list(_DATABASE_SOURCE_KINDS),
                    "source_id": str(source_id) if source_id else None,
                },
            )
        ).one()

    return _AbstainContext(
        reason_code=reason_code,
        passage_count=int(extent[0]),
        document_count=int(extent[1]),
        database_count=int(extent[2]),
    )


@dataclass(frozen=True, slots=True)
class _SqlAnswer:
    """What answering a question from a connected database produced. Every
    branch `_run_sql_turn` can take — ambiguous source, a rejected query, a
    failed dry run, a query-time failure, or an executed result — collapses
    to one of these, so `_run_generation` treats a database turn identically
    regardless of which stage decided the outcome. `sql_result` is `None`
    on every branch except a query that actually executed."""

    text: str
    status: Status
    sql_result: dict[str, Any] | None
    trace_step: dict[str, Any]
    # `M5-LOOP-BE-117`: its own "schema" step (`docs/architecture.md` §7.1),
    # `None` on every branch that never got as far as selecting a source and
    # looking up its schema notes (`no_connections`/`source_attention`/
    # `source_importing`/`ambiguous`).
    schema_step: dict[str, Any] | None = None


def _json_safe(value: Any) -> Any:
    """One raw row value, made `json.dumps`-able. `messages.sql_result` is
    an ordinary `jsonb` column, not an audited payload — `audit.
    canonical_payload`'s ban on floats does not apply here — but a driver's
    own row values (`Decimal`, `date`/`datetime`, `UUID`, raw bytes) are not
    JSON types as they come back from `psycopg`/`pymysql`/`pytds`.
    """
    if isinstance(value, (Decimal, uuid.UUID)):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()
    return value


async def _connection_credentials(
    session: AsyncSession, settings: Settings, config_encrypted: bytes
) -> dict[str, Any]:
    """Decrypt a live connection's stored configuration for one query-time
    call. The same key `askwell.connections._load_connection_config` reads
    (`askwell.passphrase.current_key`, honouring a set-and-locked passphrase)
    — done inline here, since `_run_sql_turn` already holds an open session
    and that function insists on opening its own via a `factory` this call
    site does not have a reason to thread through.
    """
    key = await passphrase.current_key(session, settings)
    config: dict[str, Any] = json.loads(crypto.decrypt(config_encrypted, key).decode("utf-8"))
    return config


def _dry_run_failure_text(reason: DryRunReason, detail: str | None) -> str:
    if reason == DryRunReason.TIMEOUT:
        return "Planning this query against your database took too long."
    if reason == DryRunReason.UNSUPPORTED:
        return "Your database does not support checking a query before running it."
    return f"Askwell could not run this query against your database: {detail}"


def _sql_query_disclosure(trace_step: dict[str, Any]) -> dict[str, Any] | None:
    """The query and outcome to disclose for a database turn that never
    reached `sql_result` — a rejection, a failed dry run, a timeout, a
    query-time failure, or the source vanishing mid-turn. `M4-RESULT-FE-110`:
    disclosure is unconditional (C2), so the query that a check refused has
    to reach the browser exactly as much as one that executed — `sql_result`
    itself deliberately stays `None` on every one of those branches
    (`_run_sql_turn`'s own docstring, and the C2 test locking that
    behaviour in), so this is the one other channel a `done` event carries
    it on. `None` only for `ambiguous` — several candidate databases, no
    single query to show — and for the document-grounded path, which never
    ran `_run_sql_turn` far enough to produce a step with a `query` key at
    all."""
    query = trace_step.get("query")
    if query is None:
        return None
    return {"query": query, "outcome": trace_step["outcome"]}


def _sql_query_from_trace(trace: Any) -> dict[str, Any] | None:
    """The same disclosure, reconstructed from a stored `messages.trace`
    row rather than a live `_SqlAnswer` — what `/ask/{id}/stream` replays
    once a finished turn has aged out of the in-memory `_turns` registry.
    `trace` is read back as an ordinary Python `dict` (the driver already
    decoded the `jsonb` column), so this walks it exactly the shape
    `_generate` wrote."""
    if not isinstance(trace, dict):
        return None
    for step in trace.get("steps", []):
        if isinstance(step, dict) and step.get("kind") == "sql":
            return _sql_query_disclosure(step)
    return None


# `M5-LOOP-BE-117`'s own edge case: "a trace larger than the per-turn bound
# — truncated with the truncation stated inside the trace." The tool-call
# ceiling (`askwell.agent.loop.CALL_CEILING`) already keeps an ordinary loop
# turn well under this; this bound exists for what that guard does not
# cover — a turn built from many small non-tool steps.
TRACE_STEP_BOUND = 50


def _bound_trace_steps(steps: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
    """Cap how many steps one turn's trace carries. Never drops a step
    silently — the caller states `steps_truncated` on the trace itself
    rather than a reader having to notice a suspiciously round count."""
    if len(steps) <= TRACE_STEP_BOUND:
        return steps, False
    return steps[:TRACE_STEP_BOUND], True


async def _trim_rotated_traces(db: AsyncSession, dropped: tuple[uuid.UUID, ...]) -> None:
    """Trim `messages.trace` for every message whose trace file just rotated
    out of `TraceRing` (`docs/architecture.md` §7.1: "`messages.trace` is
    trimmed with them" — them being the file ring buffer). `steps` is the
    detail the ring buffer actually caps; every other trace field is left
    alone since a reopened turn still needs its `status`, `backend` and the
    rest to render at all. Citations and fact usage live in their own
    tables and are untouched — an old answer keeps its sources long after
    its debugging detail is gone (`M5-LOOP-BE-117`'s own acceptance
    criterion). Best-effort like the rest of `askwell.traces`: a message row
    that no longer exists, or a `trace` that somehow is not a JSON object, is
    simply skipped rather than raised — this never gates the answer that
    triggered it.
    """
    if not dropped:
        return
    await db.execute(
        text(
            "UPDATE messages SET trace = jsonb_set(trace, '{steps}', '[]'::jsonb) "
            "|| jsonb_build_object('trace_rotated', true) "
            "WHERE id = ANY(:ids) AND jsonb_typeof(trace -> 'steps') = 'array'"
        ),
        {"ids": list(dropped)},
    )


def _sql_result_text(row_count: int, truncated: bool) -> str:
    if row_count == 0:
        return "No matching records."
    label = f"Found {row_count} row{'' if row_count == 1 else 's'}."
    if truncated:
        label += " This may not be all of them — the result was capped."
    return label


# `askwell.agent.sql_generate._DATABASE_SOURCE_KINDS` (private there): the
# kinds a question can actually be answered against with SQL. Deliberately
# not `_DATABASE_SOURCE_KINDS` above, which excludes `csv` for the abstain
# extent count's own different purpose (`_abstain_reason`'s "documents vs
# databases" split) — a loaded CSV is SQL-queryable exactly like a dump.
_SQL_SOURCE_KINDS = ("dump", "csv", "connection")

# `M4-RESULT-FE-111`: deliberately narrow. Issue #400 found that a wide word
# list ("table", "records", "total", "count of", ...) matches ordinary
# prose about the user's own documents — and, just as dangerous, matches
# the abstention eval's own near-miss questions ("total revenue",
# "headcount"), which must never be diagnosed as a missing database
# connection. This only ever *replaces the wording of an abstention that
# was already going to happen* (see `_no_database_answer`'s own call site,
# after document retrieval has already abstained) — a missed match here
# still abstains correctly with the ordinary message; a false match would
# either mislabel a real "not in your documents" case or corrupt the
# abstention eval's own exact-prefix scoring (`eval.abstain.ABSTAIN_PREFIX`).
# Recall is deliberately sacrificed for precision on both counts.
_DATABASE_SHAPED_PATTERNS = ("database", "sql")


def _looks_database_shaped(question: str) -> bool:
    lowered = question.lower()
    return any(pattern in lowered for pattern in _DATABASE_SHAPED_PATTERNS)


async def _non_ready_sql_sources(db: AsyncSession) -> list[tuple[str, str, str | None]]:
    """Every database-backed source that is not `ready` — name, status,
    last error. `askwell.agent.sql_generate.list_database_sources` only
    ever returns `ready` sources, so a source still importing or needing
    attention looks identical to "nothing connected at all" unless this is
    checked separately. Called only once no `ready` database source exists
    at all (`_no_database_answer`)."""
    rows = (
        await db.execute(
            text(
                "SELECT name, status, last_error FROM sources "
                "WHERE kind = ANY(:kinds) AND status NOT IN ('ready', 'deleted') "
                "ORDER BY name"
            ),
            {"kinds": list(_SQL_SOURCE_KINDS)},
        )
    ).all()
    return [(name, status, last_error) for name, status, last_error in rows]


def _join_names(names: list[str]) -> str:
    return ", ".join(names)


async def _no_database_answer(
    db: AsyncSession, settings: Settings, question: str
) -> tuple[str, dict[str, Any]] | None:
    """The "no connections configured" state, plus its own two named edge
    cases — a source that exists but is still importing, and several
    connections where one needs attention (`docs/states-and-edge-cases.md`
    §4). Called only from the document turn's own abstention branch, after
    document retrieval has already found nothing (issue #400's own
    recommended fix, option 3): a database-shaped question is answered from
    the user's documents whenever they actually cover it, and is only ever
    reported as unconnected once that has genuinely failed — this never
    runs ahead of document retrieval and so can never suppress a real
    document answer, unlike the keyword short-circuit #400 found.

    `None` when there is nothing database-specific to say — the ordinary
    document abstention text stands unchanged.
    """
    if not _looks_database_shaped(question):
        return None
    ready = await list_database_sources(db, settings)
    if ready:
        # A database is connected and none of it matched this question at
        # all — a genuine "not about your data" case, not a connection
        # problem to report.
        return None
    pending = await _non_ready_sql_sources(db)
    if not pending:
        return (
            "No database is connected. Connect one to answer questions like this "
            "from your own data, not just your documents.",
            {"kind": "sql", "outcome": "no_connections"},
        )
    attention = [name for name, status, _ in pending if status == "attention"]
    importing = [name for name, status, _ in pending if status == "indexing"]
    if attention:
        verb = "needs" if len(attention) == 1 else "need"
        return (
            f"{_join_names(attention)} {verb} attention and can't answer questions right "
            "now. Check its connection in the library.",
            {"kind": "sql", "outcome": "source_attention", "sources": attention},
        )
    if importing:
        verb = "is" if len(importing) == 1 else "are"
        return (
            f"{_join_names(importing)} {verb} still importing. Try again once it finishes.",
            {"kind": "sql", "outcome": "source_importing", "sources": importing},
        )
    return None


async def _run_sql_turn(
    settings: Settings,
    db: AsyncSession,
    client: InferenceClient,
    *,
    question: str,
    source_id: uuid.UUID | None,
) -> _SqlAnswer | None:
    """Attempt to answer `question` from a connected database, running the
    full checked path `docs/data-sources.md` §4 describes: generation
    (`M4-SQL-BE-103`) → validation (C2, `-104`) → limit injection (`-105`)
    → dry run (`-106`) → execution (`M4-SQL-DB-107`, wrapped by `askwell.sql.
    execute`). `None` means this was not a database question at all —
    `NO_DATABASES`/`NOT_A_DATABASE_QUESTION` — and the caller falls through
    to document retrieval exactly as it did before this ticket wired
    anything in here.

    Every other outcome is answered, never raised: a rejected query, a
    failed dry run and a query-time failure are all things a person asking
    a question needs told in plain language, not a 500 — the same "answer
    it, don't crash it" shape `_run_generation`'s own abstention branch
    already follows for a document turn that found nothing.
    """
    generation = await generate_candidate_query(
        db, settings, client, question=question, source_id=source_id
    )
    if generation.reason in (
        GenerationReason.NO_DATABASES,
        GenerationReason.NOT_A_DATABASE_QUESTION,
    ):
        return None
    if generation.reason == GenerationReason.AMBIGUOUS:
        names = [source.name for source in generation.candidates]
        return _SqlAnswer(
            text=(
                "More than one connected database could answer this: "
                f"{', '.join(names)}. Ask again naming which one."
            ),
            status="completed",
            sql_result=None,
            trace_step={"kind": "sql", "outcome": "ambiguous", "candidates": names},
        )

    generated = generation.query
    assert generated is not None
    # `DatabaseSource.engine` is a plain `str` (`askwell.agent.sql_generate`'s
    # own choice — it reads the engine back out of stored, already-validated
    # configuration rather than re-deriving a `Literal`), but everything
    # downstream from here narrows on `askwell.connections.Engine`.
    engine = cast(Engine, generated.engine)

    # `M5-LOOP-BE-117`: its own "schema" step (`docs/architecture.md` §7.1) —
    # attached to every `_SqlAnswer` returned from here on, since every one
    # of them reflects a turn that got this far.
    schema_step = {
        "kind": "schema",
        "ms": generated.schema_lookup_ms,
        "source_id": str(generated.source_id),
    }

    validation = await validate_query(
        db, settings, engine=engine, query=generated.query, source_id=generated.source_id
    )
    if not validation.accepted:
        assert validation.reason is not None
        return _SqlAnswer(
            text=(
                "Askwell could not safely run the query it generated for your "
                f"database: {validation.detail}"
            ),
            status="completed",
            sql_result=None,
            schema_step=schema_step,
            trace_step={
                "kind": "sql",
                "outcome": "rejected",
                "reason": validation.reason.value,
                "query": generated.query,
            },
        )

    limited = await inject_limit(db, settings, engine=engine, query=generated.query)

    source_row = (
        await db.execute(
            text("SELECT kind, sandbox_db, config_encrypted FROM sources WHERE id = :id"),
            {"id": generated.source_id},
        )
    ).first()
    if source_row is None:
        # Deleted between source selection, a few lines up, and here —
        # vanishingly rare on one machine with one user, but not impossible
        # mid-turn.
        return _SqlAnswer(
            text="The database this question would have used is no longer connected.",
            status="completed",
            sql_result=None,
            schema_step=schema_step,
            trace_step={"kind": "sql", "outcome": "source_gone", "query": limited.query},
        )
    kind, sandbox_db, config_encrypted = source_row
    config: dict[str, Any] | None = None

    if kind == "connection":
        config = await _connection_credentials(db, settings, bytes(config_encrypted))
        dry_run = await dry_run_connection_query(
            db,
            settings,
            source_id=generated.source_id,
            engine=engine,
            host=config["host"],
            port=config["port"],
            database=config["database"],
            user=config["user"],
            password=config["password"],
            query=limited.query,
        )
    else:
        assert sandbox_db is not None
        dry_run = await dry_run_sandbox_query(
            db, settings, database=sandbox_db, query=limited.query
        )

    if not dry_run.passed:
        assert dry_run.reason is not None
        return _SqlAnswer(
            text=_dry_run_failure_text(dry_run.reason, dry_run.detail),
            status="completed",
            sql_result=None,
            schema_step=schema_step,
            trace_step={
                "kind": "sql",
                "outcome": "dry_run_failed",
                "reason": dry_run.reason.value,
                "query": limited.query,
            },
        )

    try:
        if kind == "connection":
            assert config is not None
            checked = await sql_execute_checked.execute_checked_connection_query(
                db,
                settings,
                source_id=generated.source_id,
                engine=engine,
                host=config["host"],
                port=config["port"],
                database=config["database"],
                user=config["user"],
                password=config["password"],
                query=limited.query,
                row_limit=limited.limit,
            )
        else:
            assert sandbox_db is not None
            checked = await sql_execute_checked.execute_checked_sandbox_query(
                db, settings, database=sandbox_db, query=limited.query, row_limit=limited.limit
            )
    except StatementTimedOut as error:
        return _SqlAnswer(
            text=str(error),
            status="completed",
            sql_result=None,
            schema_step=schema_step,
            trace_step={"kind": "sql", "outcome": "timeout", "query": limited.query},
        )
    except (ConnectionUnreachable, CredentialsRejected, QueryRejected) as error:
        return _SqlAnswer(
            text=str(error),
            status="completed",
            sql_result=None,
            schema_step=schema_step,
            trace_step={
                "kind": "sql",
                "outcome": type(error).__name__,
                "query": limited.query,
            },
        )

    sql_result = {
        "engine": engine,
        "source_id": str(generated.source_id),
        "query": limited.query,
        "columns": list(checked.columns),
        "rows": [[_json_safe(v) for v in row] for row in checked.rows],
        "row_count": checked.row_count,
        "truncated": checked.truncated,
        "duration_ms": checked.duration_ms,
    }
    return _SqlAnswer(
        text=_sql_result_text(checked.row_count, checked.truncated),
        status="completed",
        sql_result=sql_result,
        schema_step=schema_step,
        trace_step={
            "kind": "sql",
            "outcome": "executed",
            "rows": checked.row_count,
            "truncated": checked.truncated,
            "duration_ms": checked.duration_ms,
            "limit_injected": limited.limit,
            "query": limited.query,
        },
    )


async def _has_hybrid_sources(db: AsyncSession, settings: Settings) -> bool:
    """Whether this corpus could need both a document lookup and a database
    query in the same turn — `run_tool_loop`'s (`M5-LOOP-BE-115`) whole
    reason to exist, per the ticket's own worked example. Deliberately
    conservative: a corpus that is only documents or only a database already
    has a fully-featured path (`_run_sql_turn`, then single-shot document
    retrieval below) with memory, partial-coverage and conflict detection
    the loop does not yet do for itself (tracked, not silently dropped —
    issue #409). Trying the loop only when neither alone could be the whole
    answer means an ordinary, single-kind-corpus turn is never routed
    through it and never loses those features by construction, rather than
    by tuning a heuristic to avoid it.
    """
    ready_documents = (
        await db.execute(
            text("SELECT count(*) FROM documents WHERE status = 'ready' AND deleted_at IS NULL")
        )
    ).scalar_one()
    if not ready_documents:
        return False
    database_sources = await list_database_sources(db, settings)
    return bool(database_sources)


async def _generate(
    settings: Settings,
    factory: async_sessionmaker[AsyncSession],
    turn: _Turn,
    question: str,
    source_id: uuid.UUID | None,
    continue_from: uuid.UUID | None = None,
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
        await _run_generation(settings, factory, turn, question, source_id, continue_from)


class _LoopContinuationState(NamedTuple):
    """What `continue_from` resolved to, or `None` if it did not name a turn
    that actually stopped at the ceiling — a stale, wrong, or ordinary
    message id falls back to answering as an ordinary new question rather
    than failing the turn (`M5-LOOP-BE-116`)."""

    continuation: LoopContinuation
    continuation_count: int


async def _load_loop_continuation(
    db: AsyncSession, continue_from: uuid.UUID
) -> _LoopContinuationState | None:
    row = (
        await db.execute(
            text("SELECT trace FROM messages WHERE id = :id AND role = 'assistant'"),
            {"id": continue_from},
        )
    ).first()
    if row is None or not isinstance(row[0], dict):
        return None
    trace = row[0]
    stored = trace.get("loop_continuation")
    if not isinstance(stored, dict):
        return None
    return _LoopContinuationState(
        continuation=LoopContinuation.from_dict(stored),
        continuation_count=int(trace.get("loop_continuation_count", 0)),
    )


async def _run_generation(
    settings: Settings,
    factory: async_sessionmaker[AsyncSession],
    turn: _Turn,
    question: str,
    source_id: uuid.UUID | None,
    continue_from: uuid.UUID | None = None,
) -> None:
    client = InferenceClient(settings)
    status: Status = "running"
    reason: str | None = None
    candidates: list[Candidate] = []
    citation_rows: list[dict[str, Any]] = []
    fact_usage_rows: list[dict[str, Any]] = []
    claims_emitted = 0
    abstained = False
    retrieval_threshold: float | None = None
    scored_candidates: list[tuple[Candidate, float]] = []
    injection_flagged = False
    injection_patterns: tuple[str, ...] = ()
    truncated = False
    partial_coverage = False
    uncovered_aspects: tuple[str, ...] = ()
    conflict_detected = False
    conflict_topic: str | None = None
    memory_fact_ids: list[uuid.UUID] = []
    schema_note_ids: list[uuid.UUID] = []
    sql_result: dict[str, Any] | None = None
    # Aliased, not copied: every `trace_steps.append`/`.extend` below is
    # also an append to `turn.trace_steps`, which is what makes a running
    # turn's steps readable (`M5-TRACE-BE-125`) before this function ever
    # writes `messages.trace`.
    trace_steps = turn.trace_steps
    # `M4-RESULT-FE-111`: which of the database-routing states, if any,
    # overrode this turn's abstention text — `None` for every ordinary
    # document abstention. Carried onto the `done` event and the trace so
    # the FE can render the right next action without re-parsing prose.
    db_state: str | None = None
    # The model file's own name, not its full path — read from configuration
    # (never hardcoded, `AGENTS.md` §4) so this ticket's "backend and model
    # used" survives a deployment-profile change with no code edit.
    model_name = settings.inference_model_path.stem
    turn_started = time.monotonic()

    # `M5-LOOP-BE-116`: a `Continue` click names the turn it picks up from.
    # A stale, wrong, or ordinary (non-loop) id resolves to `None` and this
    # turn answers as an ordinary new question instead of failing outright.
    resume_state: LoopContinuation | None = None
    continuation_count = 0
    if continue_from is not None:
        async with session_scope(factory) as db:
            loaded = await _load_loop_continuation(db, continue_from)
        if loaded is not None:
            resume_state = loaded.continuation
            # Already the count to hand `run_tool_loop` directly — stored as
            # such at the previous stop (see the `loop_continuation_count`
            # trace field below), not a raw stop tally to increment again.
            continuation_count = loaded.continuation_count

    sql_answer: _SqlAnswer | None = None
    if resume_state is None:
        try:
            # `M4-SQL-BE-108a`: tried first, on every ordinary turn —
            # `_run_sql_turn` itself decides whether this is a database
            # question at all (`GenerationReason.NOT_A_DATABASE_QUESTION`/
            # `NO_DATABASES` both come back as `None`) and falls through to
            # the document path below exactly as if this ticket had never
            # wired anything in. Skipped entirely once a turn is known to be
            # continuing a stopped loop — it is already answering with
            # `run_tool_loop`, which can reach a database itself.
            turn.emit("step", {"label": "Checking your connected databases.", "kind": "sql"})
            async with session_scope(factory) as db:
                sql_answer = await _run_sql_turn(
                    settings, db, client, question=question, source_id=source_id
                )
        except Exception:
            sql_answer = None
            log.exception("ask_sql_turn_failed", message_id=str(turn.message_id))

    if sql_answer is not None:
        turn.text = sql_answer.text
        turn.emit("token", {"text": sql_answer.text})
        sql_result = sql_answer.sql_result
        status = sql_answer.status
        if sql_answer.schema_step is not None:
            trace_steps.append(sql_answer.schema_step)
        trace_steps.append(sql_answer.trace_step)
        turn.emit("step", {"label": "Answered from your database.", "kind": "sql"})
        duration_ms = int((time.monotonic() - turn_started) * 1000)
        bounded_steps, steps_truncated = _bound_trace_steps(trace_steps)
        trace = {
            "steps": bounded_steps,
            "steps_truncated": steps_truncated,
            "backend": {"mode": "local", "model": model_name},
            "stopped_early": status != "completed",
            "injection_flagged": False,
            "injection_patterns": [],
            "status": status,
            "reason": reason,
            "partial_coverage": False,
            "uncovered_aspects": [],
            "conflict_detected": False,
            "conflict_topic": None,
            "memory_fact_ids": [],
            "schema_note_ids": [],
            "memory_used": 0,
        }
        try:
            turn_summary = summarize_turn(
                question=question,
                answer_text=turn.text,
                status=status,
                reason=reason,
                partial=False,
                citation_rows=[],
                candidates=[],
            )
        except Exception:
            log.error("ask_summary_failed", message_id=str(turn.message_id))
            turn_summary = fallback_summary(question)
        rotated = (
            TraceRing(settings.trace_dir, settings.trace_max_bytes)
            .write(turn.message_id, trace)
            .dropped
        )
        try:
            async with session_scope(factory) as db:
                await _trim_rotated_traces(db, rotated)
                await db.execute(
                    text(
                        "INSERT INTO messages "
                        "(id, conversation_id, role, content, trace, summary, source_count, "
                        "sql_result) "
                        "VALUES (:id, :conversation_id, 'assistant', :content, "
                        "CAST(:trace AS jsonb), :summary, :source_count, "
                        "CAST(:sql_result AS jsonb)) "
                        "ON CONFLICT (id) DO UPDATE SET "
                        "content = :content, trace = CAST(:trace AS jsonb), "
                        "summary = :summary, source_count = :source_count, "
                        "sql_result = CAST(:sql_result AS jsonb)"
                    ),
                    {
                        "id": turn.message_id,
                        "conversation_id": turn.conversation_id,
                        "content": turn.text,
                        "trace": json.dumps(trace),
                        "summary": turn_summary.summary,
                        "source_count": turn_summary.source_count,
                        "sql_result": json.dumps(sql_result) if sql_result is not None else None,
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
                        "abstained": False,
                        "partial": False,
                        "uncovered_aspects": [],
                        "conflict_detected": False,
                        "conflict_topic": None,
                        "memory_fact_ids": [],
                        "schema_note_ids": [],
                        "threshold": None,
                        "source_id": str(source_id) if source_id else None,
                        "citation_count": 0,
                        "duration_ms": duration_ms,
                        "backend": "local",
                        "model": model_name,
                        "retrieved_chunks": [],
                    },
                )
        except (AuditError, SQLAlchemyError) as error:
            # Same failure shape `_run_generation`'s document-turn path
            # handles below: the whole transaction above rolled back, so
            # `sql_result` — real rows, already computed — must not be
            # shipped on the live `done` event either (issue #390's own
            # bug in miniature, avoided here by never letting a rolled-back
            # value survive past this point).
            status = "failed"
            reason = f"Askwell could not save this answer: {error}"
            sql_result = None
            log.error(
                "ask_sql_audit_write_failed", message_id=str(turn.message_id), error=str(error)
            )
            failure_trace = {**trace, "status": status, "reason": reason}
            try:
                async with session_scope(factory) as db:
                    await db.execute(
                        text(
                            "UPDATE messages SET content = :content, "
                            "trace = CAST(:trace AS jsonb), summary = :summary, "
                            "source_count = :source_count, sql_result = NULL WHERE id = :id"
                        ),
                        {
                            "id": turn.message_id,
                            "content": "",
                            "trace": json.dumps(failure_trace),
                            "summary": turn_summary.summary,
                            "source_count": turn_summary.source_count,
                        },
                    )
            except Exception:
                log.exception("ask_sql_failure_write_failed", message_id=str(turn.message_id))

        turn.emit(
            "done",
            {
                "status": status,
                "reason": reason,
                "summary": turn_summary.summary,
                "source_count": turn_summary.source_count,
                "sql_result": sql_result,
                # `M4-RESULT-FE-110`: disclosure on the branches `sql_result`
                # deliberately never carries — mutually exclusive with it,
                # never both, since an executed query already discloses
                # itself through `sql_result.query`.
                "sql_query": (
                    None if sql_result is not None else _sql_query_disclosure(sql_answer.trace_step)
                ),
                # `M4-RESULT-FE-111`: always `None` here — the routing
                # override this field exists for only ever fires from the
                # document turn's own abstention branch below, never from a
                # turn `_run_sql_turn` itself answered.
                "db_state": None,
                # `M7-SET-FE-146a`: the persistent per-answer marker's own
                # data, present on every `done` event regardless of branch —
                # same "never absent" contract as `sql_result`/`db_state`.
                "model_identity": turn.model_identity,
            },
        )
        turn.status = status
        _retire(turn.message_id)
        return

    # `M5-LOOP-BE-115`: tried only for a corpus that is genuinely both
    # documents and a database — `_has_hybrid_sources` — never for the
    # ordinary single-kind case, which keeps every path below (abstention,
    # partial coverage, conflict detection, citations) exactly as tested
    # for every turn that was already exercising it. Citations for a
    # loop-answered turn are its own follow-up (issue #407); this turn's
    # `[index]` markers reach `messages.content` as the model wrote them,
    # uncited in `citations`, same as `_run_sql_turn`'s canned text already
    # is for the SQL epic.
    def _emit_tool_call_step(event: ToolCallEvent) -> None:
        # `M5-LOOP-BE-117a` shipped `"end"`-only, generic `Called {tool}.`
        # labels — issue #420's deliberate stopgap until the frontend could
        # tell a `start` from an `end` on the same call. `M5-LOOP-FE-118`
        # is that ticket: `web/lib/ask.ts::applyAskEvent` now keys on
        # `call_id`, so both phases are forwarded, each named for its real
        # operation by `_tool_call_step`.
        turn.emit("step", _tool_call_step(event))

    loop_answer: LoopResult | None = None
    if resume_state is not None:
        # `M5-LOOP-BE-116`: a `Continue` turn is already known to be a loop
        # turn — go straight there rather than re-running `_has_hybrid_
        # sources`, which only exists to decide whether to try the loop at
        # all for an *ordinary* question.
        try:
            turn.emit("step", {"label": "Continuing where it left off.", "kind": "tool"})
            async with session_scope(factory) as db:
                loop_answer = await run_tool_loop(
                    db,
                    settings,
                    client,
                    question=question,
                    source_id=source_id,
                    resume=resume_state,
                    continuation_count=continuation_count,
                    on_tool_call=_emit_tool_call_step,
                )
        except Exception:
            loop_answer = None
            log.exception("ask_tool_loop_continue_failed", message_id=str(turn.message_id))
    elif source_id is None:
        try:
            async with session_scope(factory) as db:
                hybrid = await _has_hybrid_sources(db, settings)
            if hybrid:
                turn.emit("step", {"label": "Working through this in steps.", "kind": "tool"})
                async with session_scope(factory) as db:
                    loop_answer = await run_tool_loop(
                        db,
                        settings,
                        client,
                        question=question,
                        source_id=source_id,
                        on_tool_call=_emit_tool_call_step,
                    )
        except Exception:
            loop_answer = None
            log.exception("ask_tool_loop_failed", message_id=str(turn.message_id))

    if loop_answer is not None and loop_answer.tool_names_called:
        tool_ceiling = loop_answer.stopped_reason == "tool_ceiling"
        if tool_ceiling:
            # `M5-LOOP-BE-116`: named plainly as its own step, not left to be
            # inferred from the answer text — `docs/ux/ask.md` §5's own
            # "Tool ceiling hit" state.
            turn.emit(
                "step",
                {"label": "Stopped after 8 steps for this question.", "kind": "tool"},
            )
        turn.text = loop_answer.text
        turn.emit("token", {"text": loop_answer.text})
        status = "completed"
        trace_steps.extend(step.as_dict() for step in loop_answer.steps)
        injection_flagged = any(step.injection_flagged for step in loop_answer.steps)
        injection_patterns = tuple(
            sorted({p for step in loop_answer.steps for p in step.injection_patterns})
        )
        duration_ms = int((time.monotonic() - turn_started) * 1000)
        bounded_steps, steps_truncated = _bound_trace_steps(trace_steps)
        trace = {
            "steps": bounded_steps,
            "steps_truncated": steps_truncated,
            "backend": {"mode": "local", "model": model_name},
            "stopped_early": loop_answer.stopped_reason != "answered",
            "injection_flagged": injection_flagged,
            "injection_patterns": list(injection_patterns),
            "status": status,
            "reason": reason,
            "partial_coverage": False,
            "uncovered_aspects": [],
            "conflict_detected": False,
            "conflict_topic": None,
            "memory_fact_ids": [],
            "schema_note_ids": [],
            "memory_used": 0,
            "loop_iterations": loop_answer.iterations,
            "loop_stopped_reason": loop_answer.stopped_reason,
            # `M5-LOOP-BE-116`: what the turn was about to do when the
            # ceiling cut it off (`docs/ux/trace.md` §5), and what a
            # `Continue` click needs — `None`/`[]` on every ordinary,
            # non-ceiling loop turn, same as before this ticket.
            "loop_pending_calls": list(loop_answer.pending_calls),
            "loop_continuation_count": loop_answer.continuation_count + (1 if tool_ceiling else 0),
            "loop_continuation": (
                loop_answer.continuation.as_dict() if loop_answer.continuation is not None else None
            ),
        }
        try:
            turn_summary = summarize_turn(
                question=question,
                answer_text=turn.text,
                status=status,
                reason=reason,
                partial=False,
                citation_rows=[],
                candidates=[],
            )
        except Exception:
            log.error("ask_summary_failed", message_id=str(turn.message_id))
            turn_summary = fallback_summary(question)
        rotated = (
            TraceRing(settings.trace_dir, settings.trace_max_bytes)
            .write(turn.message_id, trace)
            .dropped
        )
        try:
            async with session_scope(factory) as db:
                await _trim_rotated_traces(db, rotated)
                await db.execute(
                    text(
                        "INSERT INTO messages "
                        "(id, conversation_id, role, content, trace, summary, source_count) "
                        "VALUES (:id, :conversation_id, 'assistant', :content, "
                        "CAST(:trace AS jsonb), :summary, :source_count) "
                        "ON CONFLICT (id) DO UPDATE SET "
                        "content = :content, trace = CAST(:trace AS jsonb), "
                        "summary = :summary, source_count = :source_count"
                    ),
                    {
                        "id": turn.message_id,
                        "conversation_id": turn.conversation_id,
                        "content": turn.text,
                        "trace": json.dumps(trace),
                        "summary": turn_summary.summary,
                        "source_count": turn_summary.source_count,
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
                        "abstained": False,
                        "partial": False,
                        "uncovered_aspects": [],
                        "conflict_detected": False,
                        "conflict_topic": None,
                        "memory_fact_ids": [],
                        "schema_note_ids": [],
                        "threshold": None,
                        "source_id": str(source_id) if source_id else None,
                        "citation_count": 0,
                        "duration_ms": duration_ms,
                        "backend": "local",
                        "model": model_name,
                        "retrieved_chunks": [],
                        # `M5-LOOP-BE-116`'s own Audit / Logging Requirement:
                        # a tool-ceiling stop recorded in the interaction
                        # log, not only in the trace ring buffer that
                        # rotates.
                        "tool_ceiling": tool_ceiling,
                    },
                )
        except (AuditError, SQLAlchemyError) as error:
            status = "failed"
            reason = f"Askwell could not save this answer: {error}"
            log.error(
                "ask_loop_audit_write_failed", message_id=str(turn.message_id), error=str(error)
            )
            failure_trace = {**trace, "status": status, "reason": reason}
            try:
                async with session_scope(factory) as db:
                    await db.execute(
                        text(
                            "UPDATE messages SET content = :content, "
                            "trace = CAST(:trace AS jsonb), summary = :summary, "
                            "source_count = :source_count WHERE id = :id"
                        ),
                        {
                            "id": turn.message_id,
                            "content": "",
                            "trace": json.dumps(failure_trace),
                            "summary": turn_summary.summary,
                            "source_count": turn_summary.source_count,
                        },
                    )
            except Exception:
                log.exception("ask_loop_failure_write_failed", message_id=str(turn.message_id))

        turn.emit(
            "done",
            {
                "status": status,
                "reason": reason,
                "summary": turn_summary.summary,
                "source_count": turn_summary.source_count,
                "sql_result": None,
                "sql_query": None,
                "db_state": None,
                "model_identity": turn.model_identity,
                # `M5-LOOP-BE-116`: the browser's own signal to render the
                # "stopped after 8 steps" state and, when `can_continue`, a
                # **Continue** action posting `continue_from` back as this
                # turn's own `message_id` (`docs/ux/ask.md` §5).
                "tool_ceiling": tool_ceiling,
                "can_continue": tool_ceiling and trace["loop_continuation"] is not None,
            },
        )
        turn.status = status
        _retire(turn.message_id)
        return

    turn.emit("step", {"label": "Searching your files.", "kind": "retrieve"})

    try:
        retrieve_started = time.monotonic()
        async with session_scope(factory) as db:
            result = await retrieve(db, client, settings, question, source_id=source_id)
        candidates = result.candidates
        retrieval_threshold = result.threshold
        # `candidate_score()`, not `c.score` (the fused RRF value): the
        # abstention decision below and the near-miss this trace exists to
        # show both need the one score that is actually comparable to
        # `result.threshold` — see its own docstring in `askwell.retrieve`.
        scored_candidates = [(c, candidate_score(c)) for c in candidates]
        trace_steps.append(
            {
                "kind": "retrieve",
                "ms": (time.monotonic() - retrieve_started) * 1000,
                "query": question,
                "threshold": result.threshold,
                "hits": [
                    {"chunk_id": str(c.chunk_id), "score": score} for c, score in scored_candidates
                ],
            }
        )

        best_score = max((score for _, score in scored_candidates), default=None)
        abstained = best_score is None or best_score < result.threshold

        if abstained:
            # C5's abstention branch, taken before composition: nothing
            # retrieved clears the threshold in force, so there is no path
            # from a below-threshold retrieval to a document-grounded
            # answer. `citation_rows` stays empty, which is what already
            # makes `summarize_turn` (below) treat this turn as abstained —
            # `source_count = None`, never `0`.
            abstain_context = await _abstain_reason(factory, settings, source_id)
            # The nearest miss, not the fused `.score`: the same comparable
            # score the threshold decision above was made against, so
            # "closest" here means the same thing it meant to that decision.
            # `None` when nothing was retrieved at all — `compose_abstention`
            # renders that as "found nothing close" rather than a topic.
            nearest = max(scored_candidates, key=lambda pair: pair[1], default=None)
            nearest_heading = (nearest[0].heading or nearest[0].filename) if nearest else None
            reason = compose_abstention(
                reason_code=abstain_context.reason_code,
                passage_count=abstain_context.passage_count,
                document_count=abstain_context.document_count,
                database_count=abstain_context.database_count,
                nearest_heading=nearest_heading,
            )
            # `M4-RESULT-FE-111`: only for an unscoped question — scoping to
            # a source (`docs/decisions.md`'s own precedent for
            # `test_scoping_to_a_document_source_never_reports_no_connection`)
            # already means the person picked a specific source themselves,
            # so there is nothing for this override to add.
            db_override = None
            if source_id is None:
                async with session_scope(factory) as db:
                    db_override = await _no_database_answer(db, settings, question)
            if db_override is not None:
                reason, sql_trace_step = db_override
                db_state = sql_trace_step["outcome"]
                trace_steps.append(sql_trace_step)
            else:
                trace_steps.append({"kind": "abstain", "reason_code": abstain_context.reason_code})
            turn.emit("step", {"label": "Nothing in your files answers this.", "kind": "read"})
            # `messages.content` and the audit record's own `answer`
            # (below) carry the composed copy — streamed as a `token` event
            # is `M2-ABSTAIN-FE-055`'s call to make, not this ticket's; the
            # composition and its persistence are what this one owns.
            turn.text = reason
        else:
            document_count = len({candidate.document_id for candidate in candidates})
            turn.emit("step", {"label": _label_for_sources(document_count), "kind": "read"})

            # `M3-APPLY-RET-078`: only reached once a document has already
            # cleared the abstention threshold above — memory never bypasses
            # grounding, it only adds labelled context to an answer that was
            # already going to be grounded in the user's own material.
            async with session_scope(factory) as db:
                relevant_memory = await retrieve_relevant_facts(
                    db, question=question, source_id=source_id
                )
            memory_fact_ids = [fact.id for fact in relevant_memory.facts]
            schema_note_ids = [note.id for note in relevant_memory.notes]
            if memory_fact_ids or schema_note_ids:
                trace_steps.append(
                    {
                        "kind": "memory_retrieve",
                        "memory_fact_ids": [str(i) for i in memory_fact_ids],
                        "schema_note_ids": [str(i) for i in schema_note_ids],
                    }
                )

            # `M3-INLINE-FE-085`: determined before composition, per the
            # ticket's own Assumption — never discovered mid-answer. Only a
            # contradiction or document-identity ambiguity relevant to *this*
            # question and still `pending` can interrupt; anything else
            # (nothing pending, or nothing relevant) leaves this turn
            # composing exactly as it would have before this ticket existed.
            memory_fact: str | None = None
            appended_note: str | None = None
            async with session_scope(factory) as db:
                blocking, deferred = await find_blocking(db, question, candidates)
            if blocking is not None:
                turn.clarify_id = blocking.id
                turn.emit(
                    "clarification",
                    {
                        "clarification_id": str(blocking.id),
                        "subject": blocking.subject,
                        "question": blocking.question,
                        "options": blocking.options,
                        "evidence": blocking.evidence,
                        "deferred_count": deferred,
                    },
                )
                resolution = await _await_clarification(turn)
                if resolution is None:
                    raise _ClarificationAbandoned
                turn.clarify_id = None
                turn.emit(
                    "clarification_resolved",
                    {"clarification_id": str(blocking.id), "skipped": resolution["skipped"]},
                )
                if resolution["skipped"]:
                    assumption = default_assumption(blocking)
                    appended_note = (
                        f'\n\nSkipped the question about "{blocking.subject}" — this answer '
                        f"assumes {assumption}. Answer it anytime in Clarifications."
                    )
                else:
                    memory_fact = f"{blocking.subject}: {resolution['answer']}"
                if deferred > 0:
                    appended_note = (appended_note or "") + (
                        f"\n\n{deferred} more unresolved question"
                        f"{'' if deferred == 1 else 's'} about your files "
                        f"{'is' if deferred == 1 else 'are'} waiting in Clarifications."
                    )
                trace_steps.append(
                    {
                        "kind": "inline_clarification",
                        "clarification_id": str(blocking.id),
                        "subject": blocking.subject,
                        "skipped": resolution["skipped"],
                        "deferred": deferred,
                    }
                )

            # `compose_conflict`, not `compose`: a question can ask about
            # more than one thing, and only some of it may be covered by what
            # cleared the threshold above (`M2-PARTIAL-BE-057`); what cleared
            # it can also disagree with itself across years of superseding
            # material (`M2-PARTIAL-BE-059`). The prompt this loads
            # (`agent/prompts/conflicting_sources.v1.md`) answers, with
            # citations, exactly what is supported, names anything uncovered
            # plainly, and presents both sides of a genuine conflict rather
            # than choosing one — an ordinary single-aspect, single-position
            # question comes back with neither and composes identically to
            # before either ticket. `memory_fact`, when this turn was just
            # resolved inline, is the same hook `M2-PARTIAL-BE-059` built and
            # left inert — the model settles the conflict with it and writes
            # "Resolved by memory: ..." rather than presenting both sides.
            composed = compose_conflict(
                question,
                candidates,
                memory_fact=memory_fact,
                retrieved_facts=relevant_memory.facts,
                retrieved_notes=relevant_memory.notes,
            )
            injection_flagged = composed.injection_flagged
            injection_patterns = composed.injection_patterns

            turn.emit("step", {"label": "Writing your answer.", "kind": "compose"})

            prompt = f"{composed.system_prompt}\n\n{composed.user_content}"
            # No separator: the directive is a prefill that has to sit
            # exactly where the model's own output would begin.
            prompt = f"{prompt}{settings.generation_thinking_directive}"
            compose_started = time.monotonic()
            stream = client.stream_generate(prompt, max_tokens=settings.generation_max_tokens)
            # The shipped model reasons in a `<think>` block before writing
            # anything. Strip it here, at the one point tokens are consumed,
            # so the stored answer, the reader and `segment_claims` all see
            # the same text — issue #220, where a rehearsed line inside the
            # reasoning was counted as a real claim.
            stripper = ThinkStripper()
            async for chunk in stream:
                if turn.stop_requested:
                    await stream.aclose()
                    status = "stopped"
                    break
                visible = stripper.feed(chunk.text) if chunk.text else ""
                if visible:
                    turn.text += visible
                    turn.emit("token", {"text": visible})
                    claims = segment_claims(turn.text)
                    for claim in claims[claims_emitted:]:
                        _cite_claim(
                            turn,
                            claim,
                            candidates,
                            citation_rows,
                            relevant_memory.facts,
                            relevant_memory.notes,
                            fact_usage_rows,
                        )
                    claims_emitted = len(claims)
                if chunk.done:
                    truncated = chunk.truncated

            tail = stripper.flush()
            if tail:
                turn.text += tail
                turn.emit("token", {"text": tail})
                claims = segment_claims(turn.text)
                for claim in claims[claims_emitted:]:
                    _cite_claim(
                        turn,
                        claim,
                        candidates,
                        citation_rows,
                        relevant_memory.facts,
                        relevant_memory.notes,
                        fact_usage_rows,
                    )
                claims_emitted = len(claims)
            elif stripper.thinking:
                # The whole budget went on reasoning and no answer followed.
                # Treat it as the truncation it is rather than storing a
                # draft as the answer.
                truncated = True

            if appended_note is not None:
                turn.text += appended_note
                turn.emit("token", {"text": appended_note})

            # C4 and C5 both apply to the same answer here: the grounded part
            # already carries citations from the loop above, and this reads
            # back the `Not covered: <aspect>.` lines the prompt asks the
            # model to write for the rest, rather than inventing or smoothing
            # over them. A fully-covered answer parses to nothing here and
            # `partial_coverage` stays `False`, same as before `M2-PARTIAL-BE-057`.
            uncovered_aspects = split_partial_answer(turn.text).uncovered
            partial_coverage = bool(uncovered_aspects)

            # `M2-PARTIAL-BE-059`: the "Conflicting sources on ...:" line is
            # the same kind of explicit, parseable convention — read back
            # rather than re-detected, so a conflict is never silently
            # smoothed into fluent prose here either. A single consistent
            # answer parses to nothing and `conflict_detected` stays `False`.
            conflict = split_conflict_answer(turn.text)
            conflict_detected = conflict.is_conflict
            conflict_topic = conflict.topic

            trace_steps.append(
                {
                    "kind": "compose",
                    "ms": (time.monotonic() - compose_started) * 1000,
                    "claims": claims_emitted,
                    "citations": len(citation_rows),
                    "fact_citations": len(
                        {(r["fact_kind"], r["fact_id"]) for r in fact_usage_rows}
                    ),
                    "partial_coverage": partial_coverage,
                    "uncovered_aspects": list(uncovered_aspects),
                    "conflict_detected": conflict_detected,
                    "conflict_topic": conflict_topic,
                }
            )

        if status == "running":
            status = "completed"
        if truncated and status == "completed":
            reason = "Reached the answer length limit."
    except _ClarificationAbandoned:
        status = "stopped"
        reason = "Stopped while waiting on a clarification."
    except (InferenceUnavailable, InferenceFailed) as error:
        status = "failed"
        reason = str(error)
    except Exception:
        status = "failed"
        reason = "Askwell hit an error it did not expect while answering."
        log.exception("ask_generation_failed", message_id=str(turn.message_id))

    duration_ms = int((time.monotonic() - turn_started) * 1000)

    bounded_steps, steps_truncated = _bound_trace_steps(trace_steps)
    trace = {
        "steps": bounded_steps,
        "steps_truncated": steps_truncated,
        "backend": {"mode": "local", "model": model_name},
        "stopped_early": status != "completed",
        "injection_flagged": injection_flagged,
        "injection_patterns": list(injection_patterns),
        "status": status,
        "reason": reason,
        # `M2-PARTIAL-BE-057`: what the FE ticket (`M2-PARTIAL-FE-058`) and the
        # eval suite both need to tell a partial answer apart from an ordinary
        # one or a full abstention, without re-parsing the answer's own prose.
        "partial_coverage": partial_coverage,
        "uncovered_aspects": list(uncovered_aspects),
        # `M2-PARTIAL-BE-059`: whether the conflict branch was taken and the
        # fact it named, so the FE and the conflicting-source eval subset can
        # both tell a conflict answer apart from an ordinary one without
        # re-parsing the answer's own prose.
        "conflict_detected": conflict_detected,
        "conflict_topic": conflict_topic,
        # `M3-APPLY-RET-078`: which memory facts and schema notes were
        # retrieved for this turn — "facts retrieved for a turn are recorded
        # on the interaction" is the ticket's own Audit/Logging Requirement.
        # Retrieved, not merely cited: citation-level tracking is
        # `M3-APPLY-BE-079`'s `fact_usage` write, a narrower and later thing.
        "memory_fact_ids": [str(i) for i in memory_fact_ids],
        "schema_note_ids": [str(i) for i in schema_note_ids],
        "memory_used": len(memory_fact_ids) + len(schema_note_ids),
        "db_state": db_state,
    }

    # `M1-CONV-BE-177`: the summary and source count a collapsed past turn
    # renders (`docs/ux/conversation.md` §2), produced once here and never
    # recomputed on read. `summarize_turn` itself does not raise, but the
    # ticket's own edge case — summary generation failing — must still not
    # block the answer, so this is defensive against a future bug in it
    # rather than a path exercised today.
    try:
        turn_summary = summarize_turn(
            question=question,
            answer_text=turn.text,
            status=status,
            reason=reason,
            partial=status == "stopped" or truncated,
            citation_rows=citation_rows,
            candidates=candidates,
        )
    except Exception:
        log.error("ask_summary_failed", message_id=str(turn.message_id))
        turn_summary = fallback_summary(question)

    # Traces are the ring buffer's own concern and never gate the answer —
    # `TraceRing.write` cannot raise, matching `askwell.traces`'s own "fails
    # open" guarantee. Written ahead of the audited write below so a trace
    # written but a failed audit record still leaves the full detail on disk.
    rotated = (
        TraceRing(settings.trace_dir, settings.trace_max_bytes)
        .write(turn.message_id, trace)
        .dropped
    )

    try:
        async with session_scope(factory) as db:
            # `M5-LOOP-BE-117`: trim `messages.trace` for whatever just
            # rotated out of the file ring buffer, in the same step as this
            # turn's own write — see `_trim_rotated_traces`.
            await _trim_rotated_traces(db, rotated)
            # `ON CONFLICT` rather than a plain `UPDATE`: `ask()` always
            # inserts the pending row ahead of this, but a caller driving
            # `_generate` directly against a turn it built itself — every
            # test in `test_ask_api.py` that isolates stopping or
            # disconnection from the HTTP layer does exactly this — has not,
            # and a message finishing with nowhere to write is a worse bug
            # than the one this ticket exists to close.
            await db.execute(
                text(
                    "INSERT INTO messages "
                    "(id, conversation_id, role, content, trace, summary, source_count) "
                    "VALUES (:id, :conversation_id, 'assistant', :content, CAST(:trace AS jsonb), "
                    ":summary, :source_count) "
                    "ON CONFLICT (id) DO UPDATE SET "
                    "content = :content, trace = CAST(:trace AS jsonb), "
                    "summary = :summary, source_count = :source_count"
                ),
                {
                    "id": turn.message_id,
                    "conversation_id": turn.conversation_id,
                    "content": turn.text,
                    "trace": json.dumps(trace),
                    "summary": turn_summary.summary,
                    "source_count": turn_summary.source_count,
                },
            )
            for row in citation_rows:
                await db.execute(
                    text(
                        "INSERT INTO citations "
                        "(id, message_id, chunk_id, claim_ordinal, quoted_span) "
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
            # `M3-APPLY-BE-079`: one row per fact per message, however many
            # claims cited it — `fact_usage` answers "was this used in this
            # answer", not "which sentence", so de-duplicate in Python ahead
            # of the unique constraint (`message_id_fact_kind_fact_id`)
            # rather than relying on it to swallow a duplicate insert.
            for fact_kind, fact_id in {(r["fact_kind"], r["fact_id"]) for r in fact_usage_rows}:
                await db.execute(
                    text(
                        "INSERT INTO fact_usage (id, message_id, fact_kind, fact_id) "
                        "VALUES (:id, :message_id, :fact_kind, :fact_id) "
                        "ON CONFLICT ON CONSTRAINT message_id_fact_kind_fact_id DO NOTHING"
                    ),
                    {
                        "id": uuid.uuid4(),
                        "message_id": turn.message_id,
                        "fact_kind": fact_kind,
                        "fact_id": fact_id,
                    },
                )
            # C6/`M1-ASK-OBS-041`: question, answer, retrieved chunk
            # identifiers and scores, duration, backend and model — one
            # interaction record, in the same transaction as the answer
            # itself. `Store.INTERACTIONS` has no update/delete grant and
            # chains to the previous record (`askwell.audit`); scores are
            # stringified because `canonical_payload` refuses floats — a
            # value that must hash identically after a jsonb round trip.
            # `abstained`/`threshold` (`M2-ABSTAIN-RET-053`) make an
            # abstention queryable from this log directly, per
            # `docs/audit-log.md` §7, rather than only inferable from
            # `citation_count == 0`.
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
                    "abstained": abstained,
                    "partial": partial_coverage,
                    "uncovered_aspects": list(uncovered_aspects),
                    "conflict_detected": conflict_detected,
                    "conflict_topic": conflict_topic,
                    "memory_fact_ids": [str(i) for i in memory_fact_ids],
                    "schema_note_ids": [str(i) for i in schema_note_ids],
                    "threshold": (
                        str(retrieval_threshold) if retrieval_threshold is not None else None
                    ),
                    "source_id": str(source_id) if source_id else None,
                    "citation_count": len(citation_rows),
                    "duration_ms": duration_ms,
                    "backend": "local",
                    "model": model_name,
                    "retrieved_chunks": [
                        {"chunk_id": str(candidate.chunk_id), "score": str(score)}
                        for candidate, score in scored_candidates
                    ],
                },
            )
    except (AuditError, SQLAlchemyError) as error:
        # Both, because `AuditError` alone does not cover the case this ticket
        # names. `record()` raises it only for a payload that will not hash; a
        # genuinely unwritable `audit_interactions` — a revoked INSERT grant,
        # which is precisely how C6 is enforced, a missing table, a full disk —
        # raises SQLAlchemy's own error instead. Catching only the first meant
        # the ticket's own scenario, "make the interaction table unwritable",
        # escaped this handler entirely: the turn ended with an unhandled
        # exception, the client saw the stream stop with no `done` event, and
        # the row stayed `running` forever.
        # The transaction above rolled back in full — `session_scope`'s own
        # guarantee — so the answer this turn produced was never persisted,
        # matching this ticket's own acceptance criterion: a write failure
        # here must not leave an unlogged answer sitting in `messages`. What
        # is still true is that a client is watching this turn live and the
        # pending `running` row `ask()` wrote is still there; both are
        # updated, best-effort, in a fresh transaction so the failure is
        # visible rather than a turn that silently hangs at `running`
        # forever. If this second write also fails, `reconcile_interrupted`
        # is the backstop the next startup already provides for exactly a
        # row stuck `running` with nothing left generating it.
        status = "failed"
        reason = f"Askwell could not save this answer: {error}"
        log.error("ask_audit_write_failed", message_id=str(turn.message_id), error=str(error))
        failure_trace = {**trace, "status": status, "reason": reason}
        # The answer this turn produced was rolled back whole (see the
        # comment above), so the summary describing that answer no longer
        # matches what `content` is about to become — recomputed for the
        # failure itself rather than left describing text that no longer
        # exists.
        try:
            failure_summary = summarize_turn(
                question=question,
                answer_text="",
                status=status,
                reason=reason,
                partial=False,
                citation_rows=[],
                candidates=[],
            )
        except Exception:
            failure_summary = fallback_summary(question)
        turn_summary = failure_summary
        try:
            async with session_scope(factory) as db:
                await db.execute(
                    text(
                        "UPDATE messages SET content = :content, trace = CAST(:trace AS jsonb), "
                        "summary = :summary, source_count = :source_count "
                        "WHERE id = :id"
                    ),
                    {
                        "id": turn.message_id,
                        "content": "",
                        "trace": json.dumps(failure_trace),
                        "summary": failure_summary.summary,
                        "source_count": failure_summary.source_count,
                    },
                )
        except Exception:
            log.exception("ask_failure_write_failed", message_id=str(turn.message_id))

    # `M1-CONV-FE-178` collapses this turn the moment the next question is
    # asked, and has no route back to `messages.summary` /
    # `messages.source_count` other than this event — there is no
    # conversation-history endpoint yet (`docs/BRAIN.md`), and re-running the
    # turn to derive its own summary is exactly what `conversation.md` §6
    # rules out. Carrying the same `turn_summary` already written to the row
    # above, rather than a second computation, is what keeps the two
    # guaranteed to agree.
    turn.emit(
        "done",
        {
            "status": status,
            "reason": reason,
            "summary": turn_summary.summary,
            "source_count": turn_summary.source_count,
            # `M4-SQL-BE-108a`: always `None` on this, the document-grounded
            # path — a database-answered turn returns from `_run_sql_turn`'s
            # own branch above and never reaches here. Present on every
            # `done` event regardless, so a client never has to treat the
            # key's absence as meaningful.
            "sql_result": None,
            "sql_query": None,
            # `M4-RESULT-FE-111`: which database-routing state, if any,
            # overrode this abstention's wording — `None` for an ordinary
            # document abstention. Present on every `done` event regardless,
            # matching `sql_result`/`sql_query`'s own "never absent" contract.
            "db_state": db_state,
            "model_identity": turn.model_identity,
        },
    )
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

        `tool_ceiling_stops` is `M5-LOOP-BE-116`'s own local counter — the
        ticket's Analytics Events line, and C1 governs it the same way as
        every other figure here: read from this machine's own rows, on
        demand, transmitted nowhere.
        """
        async with session_scope(factory) as db:
            result = await db.execute(
                text(
                    "SELECT count(*) AS started, "
                    "count(*) FILTER (WHERE trace ->> 'status' = 'completed') AS completed, "
                    "count(*) FILTER (WHERE trace ->> 'status' = 'stopped') AS stopped, "
                    "count(*) FILTER (WHERE trace ->> 'status' = 'failed') AS failed, "
                    "count(*) FILTER (WHERE trace ->> 'status' = 'running') AS running, "
                    "count(*) FILTER (WHERE (trace ->> 'interrupted')::boolean) AS abandoned, "
                    "count(*) FILTER "
                    "(WHERE trace ->> 'loop_stopped_reason' = 'tool_ceiling') "
                    "AS tool_ceiling_stops "
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
                "tool_ceiling_stops": row[6],
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
            #
            # The model identity is captured in the same step (`M7-SET-BE-
            # 145a`): `askwell.model_select.select_user_model` holds every
            # `generation_semaphore` permit for the duration of a swap, and
            # this insert runs before the background task ever requests one
            # — a swap racing the exact instant a question is asked is a
            # narrower window than this ticket's own scope covers, and this
            # is still a real reading of what is configured right now rather
            # than a guess.
            message_id = uuid.uuid4()
            model_identity = await active_model_identity(db, settings)
            await db.execute(
                text(
                    "INSERT INTO messages (id, conversation_id, role, content, trace, "
                    "model_identity) "
                    "VALUES (:id, :conversation_id, 'assistant', '', "
                    "CAST(:trace AS jsonb), CAST(:model_identity AS jsonb))"
                ),
                {
                    "id": message_id,
                    "conversation_id": conversation_id,
                    "trace": json.dumps({"status": "running", "steps": []}),
                    "model_identity": json.dumps(model_identity),
                },
            )

        turn = _Turn(
            message_id=message_id, conversation_id=conversation_id, model_identity=model_identity
        )
        _turns[turn.message_id] = turn
        asyncio.create_task(  # noqa: RUF006 — deliberately outlives this request; see module docstring
            _generate(settings, factory, turn, body.question, body.source_id, body.continue_from)
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
        (
            content,
            status,
            summary,
            source_count,
            conversation_id,
            sql_result,
            sql_query,
            model_identity,
        ) = stored

        async def replay() -> AsyncIterator[str]:
            if content:
                yield _sse(
                    "token",
                    {
                        "text": content,
                        "message_id": str(message_id),
                        "conversation_id": str(conversation_id),
                    },
                )
            yield _sse(
                "done",
                {
                    "status": status,
                    "reason": None,
                    "message_id": str(message_id),
                    "conversation_id": conversation_id,
                    "summary": summary,
                    "source_count": source_count,
                    "sql_result": sql_result,
                    "sql_query": sql_query,
                    "model_identity": model_identity,
                },
            )

        return StreamingResponse(replay(), media_type="text/event-stream", headers=SSE_HEADERS)

    @app.get("/ask/{message_id}/trace")
    async def ask_trace(message_id: uuid.UUID) -> JSONResponse:
        """The stored trace for one turn (`M5-TRACE-BE-125`) — the step
        sequence `docs/ux/trace.md` renders, returned exactly as stored (C4:
        a trace that disagrees with the answer it explains is worse than no
        trace, so nothing here is recomputed).

        A turn still in `_turns` and still `running` has no trustworthy row
        yet — `_run_generation` writes `messages.trace` only once the turn
        ends — so it is served from `_Turn.trace_steps` instead, the same
        list that write will eventually persist. Everything else reads the
        database, which is authoritative the moment a turn is no longer
        `running` in the registry, matching the order `_run_generation`
        itself writes in: the database row lands before `turn.status` stops
        being `"running"`.
        """
        turn = _turns.get(message_id)
        if turn is not None and turn.status == "running":
            bounded_steps, steps_truncated = _bound_trace_steps(turn.trace_steps)
            return JSONResponse(
                {
                    "steps": bounded_steps,
                    "steps_truncated": steps_truncated,
                    "trace_rotated": False,
                    "status": "running",
                }
            )

        async with session_scope(factory) as db:
            row = (
                await db.execute(
                    text("SELECT trace FROM messages WHERE id = :id AND role = 'assistant'"),
                    {"id": message_id},
                )
            ).first()
        if row is None:
            return JSONResponse({"error": "Askwell has no turn with that id."}, status_code=404)

        trace = row[0]
        if not isinstance(trace, dict):
            # A turn that failed before `_run_generation` ever wrote a trace
            # — the ticket's own edge case. A valid empty-step trace, not a
            # 404: the message exists, it simply has nothing to show yet.
            return JSONResponse({"steps": [], "steps_truncated": False, "trace_rotated": False})

        return JSONResponse(
            {
                **trace,
                "steps": trace.get("steps", []),
                "steps_truncated": trace.get("steps_truncated", False),
                "trace_rotated": trace.get("trace_rotated", False),
            }
        )

    @app.post("/ask/{message_id}/stop")
    async def ask_stop(message_id: uuid.UUID) -> JSONResponse:
        turn = _turns.get(message_id)
        if turn is None or turn.status != "running":
            return JSONResponse(
                {"error": "Askwell has no turn in progress with that id."}, status_code=404
            )
        turn.stop_requested = True
        return JSONResponse({"message_id": str(message_id), "status": "stopping"}, status_code=202)

    @app.post("/ask/{message_id}/clarify/resolve")
    async def ask_clarify_resolve(
        message_id: uuid.UUID, body: ClarifyResolveRequest
    ) -> JSONResponse:
        """Wakes a turn paused on an inline clarification (`M3-INLINE-FE-085`).

        Deliberately does not write the answer or the skip itself — the
        browser has already called the ordinary `POST /clarifications/{id}/answer`
        or `.../skip` (`askwell.review`) before this, the same endpoints the
        queue screen uses, so "answered inline" and "answered from the
        queue" write through exactly one path. This only reads back what
        that call just committed and lets the paused generation continue
        with it — never a second way to write a `memory` row.
        """
        turn = _turns.get(message_id)
        if turn is None or turn.clarify_id != body.clarification_id or turn.clarify_event.is_set():
            return JSONResponse(
                {"error": "Askwell has no pending clarification for that turn."}, status_code=404
            )
        async with session_scope(factory) as db:
            row = (
                await db.execute(
                    text("SELECT status, answer FROM clarifications WHERE id = :id"),
                    {"id": body.clarification_id},
                )
            ).first()
        if row is None:
            return JSONResponse({"error": "Askwell has no such clarification."}, status_code=404)
        status, answer = row
        if status not in ("answered", "skipped"):
            return JSONResponse(
                {"error": "That clarification has not been answered or skipped yet."},
                status_code=409,
            )
        turn.clarify_result = {"skipped": status == "skipped", "answer": answer}
        turn.clarify_event.set()
        return JSONResponse({"message_id": str(message_id), "status": "resumed"}, status_code=202)
