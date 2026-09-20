"""The voice WebSocket channel's transport guarantees: audio in, audio out,
transcript and text on one connection; backpressure; and a reconnect that
recovers a completed turn without replaying audio from the start.

No transcription or synthesis exists yet (`M6-STT-BE-127`/`M6-TTS-BE-130`),
so every test here supplies its own fake `driver` — proving the channel
itself, exactly what this ticket owns, in place of a real pipeline that does
not exist yet.
"""

import asyncio
import json
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from askwell.config import Settings
from askwell.voice_channel import VoiceTurn, register_voice_channel


def _app(settings: Settings, driver=None) -> FastAPI:
    app = FastAPI()
    register_voice_channel(app, settings, driver=driver)
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
