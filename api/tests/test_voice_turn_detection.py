"""`askwell.voice_turn_detection`: closing a turn on a pause, driven by the
`voice` container's `/vad`. `M6-STT-BE-128`.

`voice`'s HTTP response is faked with `httpx.MockTransport`, same pattern
`test_voice_stt.py` uses for `/transcribe` — the model logic behind a real
`/vad` is `test_voice_vad.py`'s job.
"""

import httpx

from askwell.config import Settings
from askwell.voice.vad import FRAME_BYTES
from askwell.voice_turn_detection import build_vad_turn_detector, null_turn_detector_factory


def _frame(count: int = 1) -> bytes:
    return b"\x00\x01" * (FRAME_BYTES // 2) * count


def _client_factory(probabilities_by_call: list[list[float]]):
    calls = iter(probabilities_by_call)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"speech_probabilities": next(calls)})

    def make_client() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://voice")

    return make_client


def _pause_frames(settings: Settings) -> int:
    # Enough consecutive silent frames to cross `voice_vad_pause_ms`.
    return int(settings.voice_vad_pause_ms // 32) + 1


async def test_null_detector_never_fires() -> None:
    detector = null_turn_detector_factory()
    for _ in range(10):
        assert await detector.feed(_frame()) is False
    await detector.aclose()


async def test_silence_with_no_speech_yet_never_closes_the_turn(settings: Settings) -> None:
    """The 'releasing push-to-talk before speaking' edge case
    (`docs/ux/voice.md` §5): a pause before any speech is not a pause worth
    closing on."""
    pause_frames = _pause_frames(settings)
    factory = build_vad_turn_detector(
        settings, client_factory=_client_factory([[0.1]] * pause_frames)
    )
    detector = factory()
    for _ in range(pause_frames):
        assert await detector.feed(_frame()) is False
    await detector.aclose()


async def test_speech_then_enough_silence_closes_the_turn(settings: Settings) -> None:
    pause_frames = _pause_frames(settings)
    calls = [[0.9]] + [[0.1]] * pause_frames
    factory = build_vad_turn_detector(settings, client_factory=_client_factory(calls))
    detector = factory()

    assert await detector.feed(_frame()) is False  # the speech frame itself
    closed = False
    for _ in range(pause_frames):
        closed = await detector.feed(_frame())
        if closed:
            break
    assert closed is True
    await detector.aclose()


async def test_speech_resets_the_silence_counter(settings: Settings) -> None:
    """A brief dip below threshold mid-sentence must not count toward the
    pause once speech resumes — otherwise a normal in-sentence breath would
    quietly erode the threshold rather than a real trailing pause closing it."""
    short_silence = max(1, _pause_frames(settings) - 2)
    calls = [[0.9]] + [[0.1]] * short_silence + [[0.9]] + [[0.1]] * short_silence
    factory = build_vad_turn_detector(settings, client_factory=_client_factory(calls))
    detector = factory()

    closed = False
    for _ in range(len(calls)):
        closed = await detector.feed(_frame())
        if closed:
            break
    assert closed is False
    await detector.aclose()


async def test_partial_frame_is_buffered_not_sent(settings: Settings) -> None:
    """Less than one full frame's worth of bytes must not reach `/vad` at
    all — `askwell.voice.vad.score_frames` only ever scores whole frames."""

    def handler(_request: httpx.Request) -> None:
        raise AssertionError("a partial frame should never be posted")

    def make_client() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://voice")

    factory = build_vad_turn_detector(settings, client_factory=make_client)
    detector = factory()

    result = await detector.feed(b"\x00\x01" * ((FRAME_BYTES // 2) // 2))
    assert result is False
    await detector.aclose()


async def test_a_short_tail_is_carried_into_the_next_call(settings: Settings) -> None:
    """A remainder short of one full frame is buffered rather than scored —
    only one `/vad` call happens here even though `feed` is called twice,
    because the two remainders together still fall short of a second frame."""
    quarter = FRAME_BYTES // 4
    calls = [[0.9]]  # exactly one call expected, for the first full frame
    factory = build_vad_turn_detector(settings, client_factory=_client_factory(calls))
    detector = factory()

    # First call: one full frame plus a quarter-frame remainder.
    assert await detector.feed(_frame(1) + b"\x00\x01" * (quarter // 2)) is False
    # Second call: another quarter frame — the buffered remainder plus this
    # is still only half a frame, so no second `/vad` call is made at all.
    result = await detector.feed(b"\x00\x01" * (quarter // 2))
    assert result is False
    await detector.aclose()


async def test_vad_service_unreachable_never_closes_the_turn(settings: Settings) -> None:
    """VAD is an optimisation on top of the client's own end/stop, not a
    requirement — an unreachable `voice` container must not fail the turn,
    only leave it to close the way it always could."""

    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    def make_client() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://voice")

    factory = build_vad_turn_detector(settings, client_factory=make_client)
    detector = factory()

    assert await detector.feed(_frame()) is False
    await detector.aclose()


async def test_vad_service_error_status_never_closes_the_turn(settings: Settings) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"reason": "no vad file"})

    def make_client() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://voice")

    factory = build_vad_turn_detector(settings, client_factory=make_client)
    detector = factory()

    assert await detector.feed(_frame()) is False
    await detector.aclose()
