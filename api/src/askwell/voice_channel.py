"""The voice WebSocket channel: audio in, audio out, transcript and text, all
on one connection. `M6-AUDIO-API-126`.

Mounted on `api` — the only container reachable at all (`docs/architecture.md`
§2 locks that down) — never on the `voice` container directly, which has no
route out to the host. Every other stream in this product is one-way SSE
(`askwell.ask`, `askwell.ingest`); this is the one place that does not work,
because speech has to flow both ways over the same turn, and the ticket's own
scope is to keep that exception contained here rather than let it leak into
the answer or ingestion streams.

**There is no transcription or synthesis behind this channel yet.** Turning
incoming audio into a transcript is `M6-STT-BE-127`; turning an answer into
speech is `M6-TTS-BE-130`. Until they land, `_default_driver` has nothing to
hand the audio to, so it does the only honest thing available to it: prove
the transport by accepting audio, applying backpressure, and ending the turn
the moment the client signals the end of speech — never inventing a
transcript or an answer this ticket has no way to produce. `register_voice_channel`
takes a `driver` override so those later tickets, and this one's own tests,
can supply the real (or a fake) pipeline without changing the transport.

**Reconnection is a delivery problem, not a generation one** (the ticket's own
Assumption, leaning on `M1-ASK-BE-040`'s "generation continues server-side"):
a `VoiceTurn` lives independently of any one connection, keyed by `turn_id`,
the same shape `askwell.ask`'s `_Turn`/`_turns` already use for text. A
reconnect names the `turn_id` it was given on the first message and gets:

- `transcript` and `text` **resent in full** — they are short strings, kept
  as the running totals a driver builds through `emit_transcript`/`emit_text`,
  so "the text is complete regardless" (`docs/ux/voice.md` §5) costs nothing
  to satisfy.
- `audio` **never replayed from the start.** Audio is not kept as history at
  all — it moves through `audio_out`, a bounded queue shared by the turn
  rather than the connection, so a chunk already dequeued by a connection
  that then dropped is simply gone, and a new connection just keeps
  consuming the same queue from wherever it is. That is what makes "the
  remaining audio, not from the start" true without any bookkeeping.

A completed turn's queue has already had its closing `None` sentinel
consumed by the connection that was there when it finished; a reconnect after
that sees `audio_out_closed` already set and gets the final `status` with no
further wait, which is how "if generation completed server-side, the answer
appears in the conversation" holds even with no audio left to send.

Audio itself is never persisted (`docs/ux/voice.md` §7: "audio is not kept")
— nothing here writes to `conversations` or `messages`. Those tables are the
next tickets' concern, once there is a real transcript and a real answer to
put in them; recorded as a follow-up rather than built against invented
content (`docs/decisions.md`, this date).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Literal

from fastapi import FastAPI, WebSocket

from askwell.config import Settings
from askwell.logging import get_logger

log = get_logger(__name__)

# How often the send loop re-checks `events` while it is otherwise waiting on
# `audio_out` — the same figure and the same reasoning as `askwell.ask`'s own
# `STREAM_INTERVAL_SECONDS`: cheap enough to poll, short enough that nobody
# notices the gap.
STREAM_INTERVAL_SECONDS = 0.1

# How many finished turns stay resumable in memory before the oldest is
# dropped. `askwell.ask` calls the identical figure `MAX_FINISHED` for the
# identical reason: one user, one turn at a time, so this is generous rather
# than tuned.
MAX_FINISHED_TURNS = 50

Status = Literal["listening", "completed", "failed"]


@dataclass(frozen=True, slots=True)
class _Event:
    """One `transcript` or `text` delta. Never `audio` — audio has no
    history, only `VoiceTurn.audio_out` (see module docstring)."""

    kind: Literal["transcript", "text"]
    text: str


@dataclass(slots=True)
class VoiceTurn:
    """One spoken question's audio and generation, independent of any one
    WebSocket connection — the audio analogue of `askwell.ask._Turn`."""

    turn_id: uuid.UUID
    audio_in: asyncio.Queue[bytes | None]
    audio_out: asyncio.Queue[bytes | None]
    events: list[_Event] = field(default_factory=list)
    transcript: str = ""
    text: str = ""
    status: Status = "listening"
    stop_requested: bool = False
    audio_in_closed: bool = False
    audio_out_closed: bool = False

    def emit_transcript(self, delta: str) -> None:
        self.transcript += delta
        self.events.append(_Event("transcript", delta))

    def emit_text(self, delta: str) -> None:
        self.text += delta
        self.events.append(_Event("text", delta))


TurnDriver = Callable[[VoiceTurn], Awaitable[None]]


_turns: dict[uuid.UUID, VoiceTurn] = {}
_finished_order: list[uuid.UUID] = []


def _retire(turn_id: uuid.UUID) -> None:
    _finished_order.append(turn_id)
    while len(_finished_order) > MAX_FINISHED_TURNS:
        _turns.pop(_finished_order.pop(0), None)


async def _default_driver(turn: VoiceTurn) -> None:
    """Drain incoming audio; produce nothing, because nothing downstream of
    this ticket exists yet to produce it from. See module docstring."""
    while True:
        chunk = await turn.audio_in.get()
        if chunk is None:
            break
    turn.status = "failed" if turn.stop_requested else "completed"
    await turn.audio_out.put(None)


async def _run_driver(turn: VoiceTurn, driver: TurnDriver) -> None:
    try:
        await driver(turn)
    except Exception:
        log.exception("voice_turn_driver_failed", turn_id=str(turn.turn_id))
        turn.status = "failed"
        if not turn.audio_out_closed:
            await turn.audio_out.put(None)
    finally:
        _retire(turn.turn_id)
        log.info("voice_turn_finished", turn_id=str(turn.turn_id), status=turn.status)


def _attach(turn_id: uuid.UUID | None, queue_size: int, driver: TurnDriver) -> VoiceTurn:
    if turn_id is not None:
        existing = _turns.get(turn_id)
        if existing is not None:
            return existing
    # Always minted here, never the client's requested id, even when that id
    # was not found — `askwell.ask` never lets a client name its own
    # `message_id` either, and a stray or expired id silently becoming the
    # new turn's real id would make "connect with a random UUID" and
    # "connect with an id that just aged out of `_turns`" indistinguishable
    # from the outside, which is not a distinction worth losing for the sake
    # of honouring an id nothing asked to reuse.
    new_id = uuid.uuid4()
    turn = VoiceTurn(
        turn_id=new_id,
        audio_in=asyncio.Queue(maxsize=queue_size),
        audio_out=asyncio.Queue(maxsize=queue_size),
    )
    _turns[new_id] = turn
    log.info("voice_turn_started", turn_id=str(new_id))
    asyncio.create_task(  # noqa: RUF006 — deliberately outlives this connection
        _run_driver(turn, driver)
    )
    return turn


async def _receive_loop(websocket: WebSocket, turn: VoiceTurn) -> None:
    """Forward binary frames into `audio_in` as they arrive — never buffered
    whole, so a long spoken question streams rather than accumulating into
    one blob (`docs/ux/voice.md` §5's "very long answer" edge case, applied
    to input). `await turn.audio_in.put(...)` is the backpressure: it blocks
    before the next frame is read whenever the queue is full, so a consumer
    that falls behind stalls this loop rather than memory growing."""
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return
        raw_bytes = message.get("bytes")
        if raw_bytes is not None:
            await turn.audio_in.put(raw_bytes)
            continue
        raw_text = message.get("text")
        if raw_text is None:
            continue
        try:
            control = json.loads(raw_text)
        except json.JSONDecodeError:
            continue
        kind = control.get("type")
        if kind == "end":
            if not turn.audio_in_closed:
                turn.audio_in_closed = True
                await turn.audio_in.put(None)
        elif kind == "stop":
            turn.stop_requested = True
            if not turn.audio_in_closed:
                turn.audio_in_closed = True
                await turn.audio_in.put(None)


async def _send_loop(websocket: WebSocket, turn: VoiceTurn, cursor: int) -> None:
    """Tail `events` from `cursor` (skips any backlog on a reattach — the
    caller already sent the current `transcript`/`text` totals once) and
    drain `audio_out` as it fills, until the turn's own closing sentinel is
    seen. See module docstring for why audio has no equivalent backlog to
    skip: it was never kept."""

    async def _flush_events() -> None:
        nonlocal cursor
        pending = turn.events[cursor:]
        cursor = len(turn.events)
        for event in pending:
            await websocket.send_json({"type": event.kind, "text": event.text})

    while True:
        await _flush_events()

        if turn.audio_out_closed:
            await websocket.send_json({"type": "status", "status": turn.status})
            return

        try:
            chunk = await asyncio.wait_for(turn.audio_out.get(), timeout=STREAM_INTERVAL_SECONDS)
        except TimeoutError:
            continue

        # A driver appends an event and then queues the audio it describes
        # in that order (`emit_text` before `put`) — flushing again here,
        # before forwarding the chunk just dequeued, is what keeps that
        # order intact on the wire rather than the chunk racing ahead of the
        # text it was queued behind, which is what letting the loop's next
        # iteration flush it would do instead.
        await _flush_events()

        if chunk is None:
            turn.audio_out_closed = True
            await websocket.send_json({"type": "status", "status": turn.status})
            return
        await websocket.send_bytes(chunk)


def register_voice_channel(
    app: FastAPI, settings: Settings, driver: TurnDriver | None = None
) -> None:
    """Attach the voice channel. `driver` is the injection point for a real
    (or, in tests, fake) transcription/synthesis pipeline; production runs
    with `_default_driver` until `M6-STT-BE-127`/`M6-TTS-BE-130` supply one."""
    turn_driver = driver if driver is not None else _default_driver
    queue_size = settings.voice_audio_queue_size

    @app.websocket("/voice/ws")
    async def voice_ws(websocket: WebSocket) -> None:
        await websocket.accept()

        raw_turn_id = websocket.query_params.get("turn_id")
        requested_turn_id: uuid.UUID | None = None
        if raw_turn_id:
            with contextlib.suppress(ValueError):
                requested_turn_id = uuid.UUID(raw_turn_id)

        turn = _attach(requested_turn_id, queue_size, turn_driver)

        await websocket.send_json({"type": "turn", "turn_id": str(turn.turn_id)})
        if turn.transcript:
            await websocket.send_json({"type": "transcript", "text": turn.transcript})
        if turn.text:
            await websocket.send_json({"type": "text", "text": turn.text})

        sender = asyncio.create_task(_send_loop(websocket, turn, len(turn.events)))
        try:
            await _receive_loop(websocket, turn)
        finally:
            sender.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await sender
