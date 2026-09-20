"""Turn detection: closing a voice turn on a pause, via `voice`'s Silero VAD.
`M6-STT-BE-128`.

`askwell.voice_channel._receive_loop` feeds every audio frame it gets from
the client into a `TurnDetector` built here, alongside its existing
`turn.audio_in.put(...)` — this is an addition to the transport, never a
replacement: the client's own `end`/`stop` still closes a turn instantly (the
manual stop control's whole reason to exist, `docs/ux/voice.md` §3 point 6),
and this only gives the same close a second, automatic trigger.

One detector instance per turn, built fresh by the factory
`build_vad_turn_detector` returns for every new connection —
`askwell.voice.vad.score_frames` is stateless per call, but *this* class
tracks the two things a single frame's probability cannot: whether speech
has been heard at all yet this turn (a pause before any speech is not a
pause worth closing on — the "releasing push-to-talk before speaking" edge
case, `docs/ux/voice.md` §5, is exactly this: no speech ever started, so
`feed` never returns `True`, and the turn only ends the way it already does,
on the client's own release), and how much trailing silence has piled up
since the last frame that looked like speech.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

import httpx

from askwell.config import Settings
from askwell.logging import get_logger
from askwell.voice.vad import FRAME_BYTES

log = get_logger(__name__)

# A frame is 32ms of audio at 16kHz (`askwell.voice.vad.FRAME_SAMPLES`).
FRAME_MS = 32.0
SPEECH_THRESHOLD = 0.5

ClientFactory = Callable[[], httpx.AsyncClient]


class TurnDetector(Protocol):
    async def feed(self, chunk: bytes) -> bool:
        """Feed one incoming audio chunk. Returns `True` the moment this
        call's audio pushes accumulated trailing silence past the pause
        threshold, having heard speech earlier in the turn. Never `True`
        before speech has been heard at all."""
        ...

    async def aclose(self) -> None:
        """Release anything this detector opened (a connection to `voice`,
        for the real implementation). Safe to call more than once."""
        ...


TurnDetectorFactory = Callable[[], TurnDetector]


class _NullTurnDetector:
    """Detects nothing. `register_voice_channel`'s fallback when no VAD
    detector is wired up — a turn only ever closes on the client's own
    `end`/`stop`, exactly the behaviour before this ticket."""

    async def feed(self, chunk: bytes) -> bool:
        return False

    async def aclose(self) -> None:
        return None


def null_turn_detector_factory() -> TurnDetector:
    """`register_voice_channel`'s fallback factory when no `turn_detector` is
    given at all — public because that fallback lives in `voice_channel`,
    not here."""
    return _NullTurnDetector()


class _VadTurnDetector:
    def __init__(self, make_client: ClientFactory, pause_ms: int) -> None:
        self._client = make_client()
        self._pause_ms = pause_ms
        self._buffer = b""
        self._heard_speech = False
        self._silence_ms = 0.0

    async def feed(self, chunk: bytes) -> bool:
        self._buffer += chunk
        usable = len(self._buffer) - (len(self._buffer) % FRAME_BYTES)
        if usable == 0:
            # Not enough audio yet for one full frame — carried into the
            # next call rather than scored short, same reasoning
            # `askwell.voice.vad.score_frames` gives for dropping a trailing
            # partial frame rather than padding it.
            return False
        frame_bytes, self._buffer = self._buffer[:usable], self._buffer[usable:]

        try:
            response = await self._client.post(
                "/vad", content=frame_bytes, headers={"content-type": "application/octet-stream"}
            )
        except httpx.HTTPError:
            # VAD is an optimisation on top of the client's own end/stop, not
            # a requirement — losing it for a turn just means that turn waits
            # for an explicit close, the same as before this ticket, rather
            # than failing the turn over a detector that could not be reached.
            log.warning("voice_vad_unavailable")
            return False
        if response.status_code != 200:
            log.warning("voice_vad_unavailable", status=response.status_code)
            return False

        for probability in response.json()["speech_probabilities"]:
            if probability >= SPEECH_THRESHOLD:
                self._heard_speech = True
                self._silence_ms = 0.0
            elif self._heard_speech:
                self._silence_ms += FRAME_MS
                if self._silence_ms >= self._pause_ms:
                    return True
        return False

    async def aclose(self) -> None:
        await self._client.aclose()


def build_vad_turn_detector(
    settings: Settings, client_factory: ClientFactory | None = None
) -> TurnDetectorFactory:
    """Build the production `TurnDetectorFactory`. `client_factory` is the
    injection point tests use to fake the `voice` container's `/vad` without
    a real HTTP call — the same pattern `askwell.voice_stt.build_stt_driver`
    already uses for `/transcribe`."""

    def _default_client() -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=f"http://{settings.voice_service_host}:{settings.voice_port}",
            timeout=httpx.Timeout(connect=2.0, read=5.0, write=5.0, pool=None),
        )

    make_client = client_factory if client_factory is not None else _default_client
    pause_ms = settings.voice_vad_pause_ms

    def factory() -> TurnDetector:
        return _VadTurnDetector(make_client, pause_ms)

    return factory


__all__ = [
    "TurnDetector",
    "TurnDetectorFactory",
    "build_vad_turn_detector",
    "null_turn_detector_factory",
]
