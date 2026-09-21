"""The voice WebSocket channel's transport guarantees: audio in, audio out,
transcript and text on one connection; backpressure; and a reconnect that
recovers a completed turn without replaying audio from the start.

Real transcription and synthesis exist now (`M6-STT-BE-127`, `M6-TTS-BE-130`
— `askwell.voice_stt`, `askwell.voice_tts`), but every test here still
supplies its own fake `driver` — proving the channel itself, exactly what
this ticket owns, independent of whatever pipeline sits behind it.
"""

import asyncio
import json
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from askwell.config import Settings
from askwell.voice_channel import VoiceTurn, register_voice_channel


def _app(settings: Settings, driver=None, turn_detector=None) -> FastAPI:
    app = FastAPI()
    register_voice_channel(app, settings, driver=driver, turn_detector=turn_detector)
    return app


async def _echo_driver(turn: VoiceTurn) -> None:
    """Collects every audio-in chunk, then answers with a fixed transcript,
    text and two audio-out chunks — standing in for real STT/TTS."""
    chunks: list[bytes] = []
    while True:
        chunk = await turn.audio_in.get()
        if chunk is None:
            break
        chunks.append(chunk)
    turn.emit_transcript(f"heard {len(chunks)} chunks")
    turn.emit_text("the answer")
    await turn.audio_out.put(b"chunk-1")
    await turn.audio_out.put(b"chunk-2")
    turn.status = "completed"
    await turn.audio_out.put(None)


def test_connecting_returns_a_turn_id(settings: Settings) -> None:
    with TestClient(_app(settings)).websocket_connect("/voice/ws") as ws:
        first = ws.receive_json()
    assert first["type"] == "turn"
    assert uuid.UUID(first["turn_id"])


def test_unknown_turn_id_starts_a_fresh_turn_rather_than_erroring(settings: Settings) -> None:
    stray = uuid.uuid4()
    with TestClient(_app(settings)).websocket_connect(f"/voice/ws?turn_id={stray}") as ws:
        first = ws.receive_json()
    assert first["type"] == "turn"
    assert first["turn_id"] != str(stray)


def test_audio_in_transcript_text_and_audio_out_all_arrive_on_one_connection(
    settings: Settings,
) -> None:
    with TestClient(_app(settings, driver=_echo_driver)).websocket_connect("/voice/ws") as ws:
        ws.receive_json()  # turn
        ws.send_bytes(b"frame-1")
        ws.send_bytes(b"frame-2")
        ws.send_bytes(b"frame-3")
        ws.send_text(json.dumps({"type": "end"}))

        transcript = ws.receive_json()
        text = ws.receive_json()
        audio_1 = ws.receive_bytes()
        audio_2 = ws.receive_bytes()
        status = ws.receive_json()

    assert transcript == {"type": "transcript", "text": "heard 3 chunks"}
    assert text == {"type": "text", "text": "the answer"}
    assert audio_1 == b"chunk-1"
    assert audio_2 == b"chunk-2"
    assert status == {"type": "status", "status": "completed"}


def test_long_input_streams_as_separate_chunks_not_one_buffered_blob(
    settings: Settings,
) -> None:
    """The ticket's edge case: a very long spoken question streams rather
    than being buffered whole. Asserted at the point that actually matters —
    the driver sees each frame as it arrives, not one concatenated blob."""
    seen: list[bytes] = []

    async def _counting_driver(turn: VoiceTurn) -> None:
        while True:
            chunk = await turn.audio_in.get()
            if chunk is None:
                break
            seen.append(chunk)
        turn.status = "completed"
        await turn.audio_out.put(None)

    frames = [f"frame-{i}".encode() for i in range(20)]
    with TestClient(_app(settings, driver=_counting_driver)).websocket_connect("/voice/ws") as ws:
        ws.receive_json()  # turn
        for frame in frames:
            ws.send_bytes(frame)
        ws.send_text(json.dumps({"type": "end"}))
        ws.receive_json()  # status

    assert seen == frames


def test_a_detected_pause_closes_the_turn_without_an_explicit_end(settings: Settings) -> None:
    """`M6-STT-BE-128`: a `TurnDetector` reporting a pause closes `audio_in`
    itself, the same as the client's own `end` — no `end`/`stop` message is
    ever sent here."""

    class _CloseAfterTwo:
        def __init__(self) -> None:
            self.calls = 0

        async def feed(self, _chunk: bytes) -> bool:
            self.calls += 1
            return self.calls >= 2

        async def aclose(self) -> None:
            return None

    detector = _CloseAfterTwo()
    with TestClient(
        _app(settings, driver=_echo_driver, turn_detector=lambda: detector)
    ).websocket_connect("/voice/ws") as ws:
        ws.receive_json()  # turn
        ws.send_bytes(b"frame-1")
        ws.send_bytes(b"frame-2")
        ws.send_bytes(b"frame-3")  # dropped: the turn already closed after frame-2

        transcript = ws.receive_json()
        ws.receive_json()  # text
        ws.receive_bytes()
        ws.receive_bytes()
        status = ws.receive_json()

    assert transcript == {"type": "transcript", "text": "heard 2 chunks"}
    assert status == {"type": "status", "status": "completed"}


def test_no_turn_detector_given_behaves_exactly_as_before_this_ticket(
    settings: Settings,
) -> None:
    """`register_voice_channel`'s default (`turn_detector=None`) must not
    close a turn on its own — only `end`/`stop` do, unchanged."""
    with TestClient(_app(settings, driver=_echo_driver)).websocket_connect("/voice/ws") as ws:
        ws.receive_json()  # turn
        ws.send_bytes(b"frame-1")
        ws.send_bytes(b"frame-2")
        ws.send_text(json.dumps({"type": "end"}))

        transcript = ws.receive_json()
        ws.receive_json()  # text
        ws.receive_bytes()
        ws.receive_bytes()
        status = ws.receive_json()

    assert transcript == {"type": "transcript", "text": "heard 2 chunks"}
    assert status == {"type": "status", "status": "completed"}


async def _confirm_driver(turn: VoiceTurn) -> None:
    """Stands in for `askwell.voice_stt`'s low-confidence gate: drains audio,
    asks for confirmation, then answers with whatever text it was released
    with — proving the channel's `confirmation`/`confirm`/`edit` wiring
    (`M6-STT-FE-129`) independent of real transcription."""
    while True:
        chunk = await turn.audio_in.get()
        if chunk is None:
            break
    turn.emit_transcript("heard something unclear")
    final = await turn.request_confirmation()
    turn.emit_text(f"answering: {final}")
    turn.status = "completed"
    await turn.audio_out.put(None)


def test_confirm_releases_the_held_turn_with_the_transcript_as_is(settings: Settings) -> None:
    with TestClient(_app(settings, driver=_confirm_driver)).websocket_connect("/voice/ws") as ws:
        ws.receive_json()  # turn
        ws.send_text(json.dumps({"type": "end"}))

        transcript = ws.receive_json()
        confirmation = ws.receive_json()
        ws.send_text(json.dumps({"type": "confirm"}))
        text = ws.receive_json()
        status = ws.receive_json()

    assert transcript == {"type": "transcript", "text": "heard something unclear"}
    assert confirmation == {"type": "confirmation", "required": True}
    assert text == {"type": "text", "text": "answering: heard something unclear"}
    assert status == {"type": "status", "status": "completed"}


def test_edit_releases_the_held_turn_with_the_replacement_text(settings: Settings) -> None:
    with TestClient(_app(settings, driver=_confirm_driver)).websocket_connect("/voice/ws") as ws:
        ws.receive_json()  # turn
        ws.send_text(json.dumps({"type": "end"}))

        ws.receive_json()  # transcript
        ws.receive_json()  # confirmation
        ws.send_text(json.dumps({"type": "edit", "text": "invoice INV-2024-0917"}))
        text = ws.receive_json()
        status = ws.receive_json()

    assert text == {"type": "text", "text": "answering: invoice INV-2024-0917"}
    assert status == {"type": "status", "status": "completed"}


def test_edit_with_blank_text_is_ignored_rather_than_resolving_with_nothing(
    settings: Settings,
) -> None:
    with TestClient(_app(settings, driver=_confirm_driver)).websocket_connect("/voice/ws") as ws:
        ws.receive_json()  # turn
        ws.send_text(json.dumps({"type": "end"}))

        ws.receive_json()  # transcript
        ws.receive_json()  # confirmation
        ws.send_text(json.dumps({"type": "edit", "text": "   "}))
        # The blank edit changed nothing — a real `confirm` still releases it.
        ws.send_text(json.dumps({"type": "confirm"}))
        text = ws.receive_json()
        status = ws.receive_json()

    assert text == {"type": "text", "text": "answering: heard something unclear"}
    assert status == {"type": "status", "status": "completed"}


def test_reconnect_while_confirmation_pending_resends_the_confirmation_event(
    settings: Settings,
) -> None:
    app = _app(settings, driver=_confirm_driver)
    with TestClient(app) as client:
        with client.websocket_connect("/voice/ws") as ws:
            turn_id = ws.receive_json()["turn_id"]
            ws.send_text(json.dumps({"type": "end"}))
            ws.receive_json()  # transcript
            ws.receive_json()  # confirmation

        with client.websocket_connect(f"/voice/ws?turn_id={turn_id}") as ws:
            first = ws.receive_json()
            assert first["type"] == "turn"
            transcript = ws.receive_json()
            confirmation = ws.receive_json()
            ws.send_text(json.dumps({"type": "confirm"}))
            text = ws.receive_json()
            status = ws.receive_json()

    assert transcript == {"type": "transcript", "text": "heard something unclear"}
    assert confirmation == {"type": "confirmation", "required": True}
    assert text == {"type": "text", "text": "answering: heard something unclear"}
    assert status == {"type": "status", "status": "completed"}


def test_stop_control_ends_the_turn_as_failed(settings: Settings) -> None:
    with TestClient(_app(settings)).websocket_connect("/voice/ws") as ws:
        ws.receive_json()  # turn
        ws.send_text(json.dumps({"type": "stop"}))
        status = ws.receive_json()
    assert status == {"type": "status", "status": "failed"}


def test_reconnect_after_completion_gets_full_text_with_no_audio_replay(
    settings: Settings,
) -> None:
    app = _app(settings, driver=_echo_driver)

    # `with client:` — one portal, one event loop, for both connections:
    # the driver task the first connection starts must still be the one the
    # second one resumes, exactly as it would on one long-lived process.
    # Two separate bare `TestClient(app).websocket_connect(...)` calls each
    # get their own throwaway event loop, which would tear down the "still
    # running" driver task the moment the first connection's `with` block
    # exits — a `TestClient` artefact, not anything a real reconnect faces.
    with TestClient(app) as client:
        with client.websocket_connect("/voice/ws") as ws:
            turn_id = ws.receive_json()["turn_id"]
            ws.send_text(json.dumps({"type": "end"}))
            ws.receive_json()  # transcript
            ws.receive_json()  # text
            ws.receive_bytes()  # chunk-1
            ws.receive_bytes()  # chunk-2
            ws.receive_json()  # status: completed

        # A fresh connection, well after the turn finished and its own audio
        # queue was fully drained by the first one.
        with client.websocket_connect(f"/voice/ws?turn_id={turn_id}") as ws:
            first = ws.receive_json()
            assert first == {"type": "turn", "turn_id": turn_id}
            transcript = ws.receive_json()
            text = ws.receive_json()
            status = ws.receive_json()

    assert transcript == {"type": "transcript", "text": "heard 0 chunks"}
    assert text == {"type": "text", "text": "the answer"}
    assert status == {"type": "status", "status": "completed"}


def test_reconnect_mid_synthesis_continues_rather_than_replaying_from_start(
    settings: Settings,
) -> None:
    """The ticket's other edge case: a drop mid-synthesis must not resend
    audio the first connection already received."""

    async def _slow_driver(turn: VoiceTurn) -> None:
        while True:
            chunk = await turn.audio_in.get()
            if chunk is None:
                break
        turn.emit_text("the answer")
        await turn.audio_out.put(b"one")
        for label in (b"two", b"three"):
            # Generation keeps going whether or not anyone is still
            # connected (`M1-ASK-BE-040`'s continuation applied to audio) —
            # paced so the test can disconnect after "one" and reconnect
            # before "two" exists, rather than racing a driver fast enough
            # to finish before the first connection ever drops.
            await asyncio.sleep(0.05)
            await turn.audio_out.put(label)
        turn.status = "completed"
        await turn.audio_out.put(None)

    app = _app(settings, driver=_slow_driver)

    with TestClient(app) as client:  # one portal for both connections — see above
        with client.websocket_connect("/voice/ws") as ws:
            turn_id = ws.receive_json()["turn_id"]
            ws.send_text(json.dumps({"type": "end"}))
            ws.receive_json()  # text
            assert ws.receive_bytes() == b"one"
            # Drop right here — "two" and "three" are still queued, unseen.

        with client.websocket_connect(f"/voice/ws?turn_id={turn_id}") as ws:
            ws.receive_json()  # turn
            ws.receive_json()  # text, resent in full
            assert ws.receive_bytes() == b"two"
            assert ws.receive_bytes() == b"three"
            status = ws.receive_json()

    assert status == {"type": "status", "status": "completed"}


@pytest.mark.asyncio
async def test_audio_out_backpressure_blocks_the_producer_rather_than_growing_memory() -> None:
    """Direct on the queue, not through a socket: the producer's `put`
    genuinely suspends once the bound is reached, and resumes the moment
    something is dequeued — never buffering past the configured size."""
    turn = VoiceTurn(
        turn_id=uuid.uuid4(),
        audio_in=asyncio.Queue(maxsize=1),
        audio_out=asyncio.Queue(maxsize=1),
    )
    await turn.audio_out.put(b"first")

    blocked = asyncio.ensure_future(turn.audio_out.put(b"second"))
    await asyncio.sleep(0)
    assert not blocked.done()

    assert await turn.audio_out.get() == b"first"
    await blocked
    assert await turn.audio_out.get() == b"second"


@pytest.mark.asyncio
async def test_audio_in_backpressure_blocks_the_producer_rather_than_growing_memory() -> None:
    turn = VoiceTurn(
        turn_id=uuid.uuid4(),
        audio_in=asyncio.Queue(maxsize=1),
        audio_out=asyncio.Queue(maxsize=1),
    )
    await turn.audio_in.put(b"first")

    blocked = asyncio.ensure_future(turn.audio_in.put(b"second"))
    await asyncio.sleep(0)
    assert not blocked.done()

    assert await turn.audio_in.get() == b"first"
    await blocked
    assert await turn.audio_in.get() == b"second"
