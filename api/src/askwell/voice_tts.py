"""The real driver behind spoken answers: generation and speech. `M6-TTS-BE-130`.

`build_tts_driver` is `askwell.voice_stt.build_stt_driver` with an
`on_transcript` hook attached — transcription still happens exactly as
`M6-STT-BE-127` built it; this module is what a successful transcript now
continues into, instead of ending the turn.

**Generation reuses `askwell.ask`'s own engine directly.** `_generate` builds
its own `_Turn`, independent of any HTTP connection, and streams tokens and
citations onto it as it runs — `ask.py`'s own comment on the ON CONFLICT
insert notes that "a caller driving `_generate` directly against a turn it
built itself" is already how every stop/disconnection test in
`test_ask_api.py` works. This module is a second such caller, not a new
pattern: it builds a `_Turn`, starts `_generate` as a background task, and
polls `_Turn.events`/`_Turn.text` the same way `askwell.ask._tail` does for
SSE — except instead of sending server-sent events, three things happen as
new events arrive:

- Every `token` delta is forwarded verbatim onto the `VoiceTurn` as a `text`
  event. The screen renders exactly the text a typed answer would, markers
  and all — voice changes what is heard, never what is shown
  (`docs/ux/voice.md` §2, and this ticket's own Validation Rule).
- Every `citation`/`fact_citation` event is forwarded verbatim too, so a
  voice-mode screen (once one exists) can render the same source cards a
  typed answer's screen does. C4 is satisfied by the screen, never by the
  audio, in both modes identically.
- Once `askwell.agent.claims.segment_sentences` reports a newly completed
  sentence, that sentence — markers stripped, never read aloud — is sent to
  the `voice` container's `/synthesize` and the resulting audio is queued on
  `VoiceTurn.audio_out`, so speech starts on the first sentence rather than
  waiting for the whole answer.

**Stopping is cooperative, not a cancellation.** `VoiceTurn.stop_requested`
(set by `askwell.voice_channel._receive_loop` on a `stop` control message) is
mirrored onto the `_Turn.stop_requested` the same request would set through
`POST /ask/{id}/stop` — `_run_generation`'s own token loop already checks
that flag on every chunk and breaks promptly, exactly the behaviour a typed
answer gets. Once stop is seen, no further sentence is sent for synthesis,
even one already sitting complete in the buffered text — "stops promptly
rather than finishing the buffered sentence" is this ticket's own edge case,
and the alternative (queuing whatever was already complete) is exactly the
behaviour it rules out.

**Citations are read as a natural mention of the source, once, not read
aloud.** A sentence's marker is never spoken — "supplier-agreement-2024.pdf,
page fourteen" read aloud is unbearable (`docs/ux/voice.md` §6) — and the
first sentence that cites a given document instead names it in passing,
`_natural_reference` deriving the phrase from the candidate's own filename
(no document title field exists anywhere in the schema to draw a nicer one
from). Deliberately mechanical rather than a second, voice-only prompt
variant asking the model to phrase it — `answer_composition.v1.md` is shared
by every mode, and having the model name sources in prose would leak into
the typed, on-screen answer too, which this ticket's own Validation Rule
says must stay unchanged. Only document citations get a natural mention: a
memory-fact or schema-note citation has no filename to build one from, and
the ticket's own example (`docs/ux/voice.md` §6) is document-shaped. Recorded
as a decision, not just this comment (`docs/decisions.md`, this date).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
import uuid
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from askwell.agent.claims import Sentence, segment_sentences
from askwell.ask import _generate as ask_generate
from askwell.ask import _Turn as AskTurn
from askwell.config import Settings
from askwell.db.engine import session_scope
from askwell.logging import get_logger
from askwell.voice_channel import VoiceTurn
from askwell.voice_stt import ClientFactory, build_stt_driver

log = get_logger(__name__)

# Same figures `askwell.voice_stt` uses for `/transcribe` — one sentence's
# worth of CPU-bound synthesis is the same order of work as one turn's
# transcription, and there is no reason for the two hops to disagree.
CONNECT_TIMEOUT_SECONDS = 5.0
READ_TIMEOUT_SECONDS = 60.0

# How often the poll loop re-checks `_Turn.events`/`.text` while generation
# is still running — the same figure and reasoning as
# `askwell.voice_channel.STREAM_INTERVAL_SECONDS`.
POLL_INTERVAL_SECONDS = 0.1

GenerateFn = Callable[
    [Settings, async_sessionmaker[AsyncSession], AskTurn, str, uuid.UUID | None, uuid.UUID | None],
    Coroutine[Any, Any, None],
]

_FILENAME_WORD_RE = re.compile(r"[A-Za-z0-9]+")


class SynthesisUnavailable(RuntimeError):
    """The voice service has no usable synthesis model right now."""


class SynthesisFailed(RuntimeError):
    """The voice service is reachable but this request did not succeed."""


def _natural_reference(filename: str) -> str:
    """A spoken-friendly phrase for a filename — the words in it, lower-cased
    by nothing (Kokoro handles casing itself), extension and punctuation
    dropped. `"supplier-agreement-2024.pdf"` becomes `"supplier agreement
    2024"`. No document title exists anywhere in the schema to draw a nicer
    phrase from; this is the closest natural reference available without one.
    """
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    words = _FILENAME_WORD_RE.findall(stem)
    return " ".join(words) if words else filename


def _spoken_form(sentence: Sentence, filename_by_index: dict[int, str], mentioned: set[str]) -> str:
    """The sentence as spoken: marker gone, and — the first time this answer
    cites a given document — a natural mention of it in the marker's place."""
    for index in sentence.indices:
        filename = filename_by_index.get(index)
        if filename is None or filename in mentioned:
            continue
        mentioned.add(filename)
        return f"{sentence.text}, from the {_natural_reference(filename)}."
    return f"{sentence.text}."


async def _synthesize_and_queue(
    turn: VoiceTurn, spoken_text: str, client_factory: ClientFactory
) -> None:
    stripped = spoken_text.strip()
    if not stripped:
        return
    async with client_factory() as client:
        try:
            response = await client.post("/synthesize", json={"text": stripped})
        except httpx.HTTPError as error:
            raise SynthesisUnavailable(str(error)) from error
    if response.status_code == 503:
        raise SynthesisUnavailable(response.json().get("reason", response.text))
    if response.status_code != 200:
        raise SynthesisFailed(f"{response.status_code}: {response.text}")
    await turn.audio_out.put(response.content)


async def _insert_pending_answer(
    factory: async_sessionmaker[AsyncSession], ask_turn: AskTurn
) -> None:
    # Same shape as `askwell.ask`'s own `/ask` endpoint: a `running` row
    # exists before generation starts, so a process that dies mid-turn
    # leaves something `askwell.ask.reconcile_interrupted` can find and fail
    # on the next startup, rather than a turn with no record at all.
    async with session_scope(factory) as db:
        await db.execute(
            text(
                "INSERT INTO messages (id, conversation_id, role, content, trace) "
                "VALUES (:id, :conversation_id, 'assistant', '', CAST(:trace AS jsonb))"
            ),
            {
                "id": ask_turn.message_id,
                "conversation_id": ask_turn.conversation_id,
                "trace": json.dumps({"status": "running", "steps": []}),
            },
        )


async def _speak_answer(
    turn: VoiceTurn,
    *,
    settings: Settings,
    factory: async_sessionmaker[AsyncSession],
    question: str,
    tts_client_factory: ClientFactory,
    generate: GenerateFn,
) -> None:
    assert turn.conversation_id is not None  # set by the STT driver before this hook runs
    ask_turn = AskTurn(message_id=uuid.uuid4(), conversation_id=turn.conversation_id)
    await _insert_pending_answer(factory, ask_turn)

    gen_task: asyncio.Task[None] = asyncio.create_task(
        generate(settings, factory, ask_turn, question, None, None)
    )

    events_cursor = 0
    sentences_spoken = 0
    filename_by_index: dict[int, str] = {}
    mentioned_filenames: set[str] = set()
    stopped = False

    def _drain_events() -> None:
        nonlocal events_cursor
        for event in ask_turn.events[events_cursor:]:
            if event.kind == "token":
                delta = event.data.get("text")
                if delta:
                    turn.emit_text(delta)
            elif event.kind == "citation":
                index = event.data.get("index")
                filename = event.data.get("filename")
                if isinstance(index, int) and isinstance(filename, str):
                    filename_by_index.setdefault(index, filename)
                turn.emit_citation(event.data)
            elif event.kind == "fact_citation":
                turn.emit_fact_citation(event.data)
        events_cursor = len(ask_turn.events)

    async def _speak_new_sentences() -> None:
        nonlocal sentences_spoken
        sentences = segment_sentences(ask_turn.text)
        for sentence in sentences[sentences_spoken:]:
            spoken = _spoken_form(sentence, filename_by_index, mentioned_filenames)
            await _synthesize_and_queue(turn, spoken, tts_client_factory)
        sentences_spoken = len(sentences)

    try:
        while True:
            _drain_events()
            if turn.stop_requested and not stopped:
                stopped = True
                ask_turn.stop_requested = True
            if not stopped:
                await _speak_new_sentences()
            if gen_task.done():
                break
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

        await gen_task
        _drain_events()
        if not stopped:
            await _speak_new_sentences()
            # A final sentence with no terminating punctuation (the model
            # ran out of tokens mid-sentence) never matches
            # `segment_sentences` at all — spoken as a last, best-effort
            # unit rather than silently dropped, the ticket's own "spoken as
            # best it can be" edge case applied to the tail of the answer
            # rather than to one long identifier within it.
            consumed = segment_sentences(ask_turn.text)
            tail_start = consumed[-1].end if consumed else 0
            leftover = ask_turn.text[tail_start:].strip()
            if leftover:
                await _synthesize_and_queue(turn, leftover, tts_client_factory)
    finally:
        if not gen_task.done():
            gen_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await gen_task

    turn.status = "failed" if ask_turn.status == "failed" else "completed"
    await turn.audio_out.put(None)


def build_tts_driver(
    settings: Settings,
    factory: async_sessionmaker[AsyncSession],
    stt_client_factory: ClientFactory | None = None,
    tts_client_factory: ClientFactory | None = None,
    generate: GenerateFn | None = None,
) -> Callable[[VoiceTurn], Awaitable[None]]:
    """Build the production `TurnDriver`: transcription, then generation and
    sentence-streamed speech. `stt_client_factory` fakes the `voice`
    container's `/transcribe`, `tts_client_factory` fakes its `/synthesize`,
    and `generate` fakes `askwell.ask`'s own generation engine — the three
    injection points tests use in place of a real inference server and a
    real `voice` container."""

    def _default_tts_client() -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=f"http://{settings.voice_service_host}:{settings.voice_port}",
            timeout=httpx.Timeout(
                connect=CONNECT_TIMEOUT_SECONDS, read=READ_TIMEOUT_SECONDS, write=30.0, pool=None
            ),
        )

    make_tts_client = tts_client_factory if tts_client_factory is not None else _default_tts_client
    run_generation = generate if generate is not None else ask_generate

    async def on_transcript(turn: VoiceTurn, transcript: str) -> None:
        await _speak_answer(
            turn,
            settings=settings,
            factory=factory,
            question=transcript,
            tts_client_factory=make_tts_client,
            generate=run_generation,
        )

    return build_stt_driver(settings, factory, stt_client_factory, on_transcript)
