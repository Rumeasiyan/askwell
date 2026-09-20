"""`askwell.voice.vad`: scoring fixed-length frames for speech probability.
`M6-STT-BE-128`.

No network, no onnxruntime — a fake session stands in, shaped exactly like
`InferenceSession.run`: takes the output names and the input mapping,
returns a list of arrays. `askwell.voice.transcribe`'s own tests use the same
fake-model pattern for Whisper.
"""

import numpy as np
import pytest

from askwell.voice.vad import FRAME_BYTES, FRAME_SAMPLES, score_frames


class _FakeVadSession:
    def __init__(self, probability_by_call: list[float]) -> None:
        self._probabilities = iter(probability_by_call)
        self.inputs_seen: list[dict[str, np.ndarray]] = []

    def run(self, _output_names, inputs):
        self.inputs_seen.append(inputs)
        probability = next(self._probabilities)
        return [np.array([[probability]], dtype="float32")]


def _silence(frames: int) -> bytes:
    return b"\x00\x00" * FRAME_SAMPLES * frames


def test_empty_audio_scores_nothing_and_never_calls_the_session() -> None:
    session = _FakeVadSession([])
    assert score_frames(session, b"") == []
    assert session.inputs_seen == []


def test_one_frame_returns_one_probability() -> None:
    session = _FakeVadSession([0.87])
    result = score_frames(session, _silence(1))
    assert result == pytest.approx([0.87], abs=1e-6)


def test_three_frames_returns_three_probabilities_in_order() -> None:
    session = _FakeVadSession([0.1, 0.9, 0.2])
    result = score_frames(session, _silence(3))
    assert result == pytest.approx([0.1, 0.9, 0.2], abs=1e-6)


def test_a_trailing_partial_frame_is_dropped_not_padded() -> None:
    """Half a frame's worth of extra bytes must not trigger a fourth call —
    `askwell.voice_turn_detection` is what carries a partial frame into its
    next call; this function only ever scores whole ones."""
    session = _FakeVadSession([0.5])
    audio = _silence(1) + b"\x00\x00" * (FRAME_SAMPLES // 2)
    result = score_frames(session, audio)
    assert result == [0.5]
    assert len(session.inputs_seen) == 1


def test_frame_input_has_the_documented_shape_and_dtype() -> None:
    session = _FakeVadSession([0.5])
    score_frames(session, _silence(1))

    inputs = session.inputs_seen[0]
    assert inputs["input"].shape == (1, FRAME_SAMPLES)
    assert inputs["input"].dtype == np.float32
    assert inputs["sr"] == 16_000
    assert inputs["h"].shape == (2, 1, 64)
    assert inputs["c"].shape == (2, 1, 64)


def test_frame_bytes_matches_frame_samples_at_pcm16() -> None:
    assert FRAME_BYTES == FRAME_SAMPLES * 2
