"""Scoring fixed-length audio frames for speech with Silero VAD. `M6-STT-BE-128`.

Runs inside the `voice` container against the ONNX session `askwell.voice.models`
already loads at startup — `api` never imports `onnxruntime` itself, the same
boundary `askwell.voice.transcribe` already keeps for Whisper.

**Stateless per call.** Silero's own streaming example carries a recurrent
state (`h`, `c`) between successive frames of the *same* utterance; this
module resets it to zero on every frame instead, in exchange for keeping no
per-turn or per-connection state in this container at all — the same "nothing
kept" posture `askwell.voice.transcribe` takes for the whole turn, and
`askwell.voice_turn_detection` (in `api`) needs anyway, since it is what
tracks turn-level state (has speech started, how much silence has piled up
since) across many calls to `/vad`. The cost is per-frame precision; the
mitigation is that `askwell.voice_turn_detection` never acts on one frame —
it accumulates several consecutive low-probability frames before treating
that as a pause, so a single noisy frame does not flip the decision.

Input/output contract verified against `snakers4/silero-vad`'s documented
ONNX graph, 2026-09-20: `input` float32 `[batch, samples]` (512 samples at
16 kHz — the model's fixed window at this sample rate), `sr` int64 scalar,
`h`/`c` float32 `[2, 1, 64]`; outputs `output` `[batch, 1]` (speech
probability), `hn`, `cn` (the updated state, unused here since every call
starts from zero).
"""

from __future__ import annotations

from typing import Any

import numpy as np

SAMPLE_RATE = 16_000
FRAME_SAMPLES = 512  # 32 ms at 16 kHz — Silero's fixed window for this rate.
FRAME_BYTES = FRAME_SAMPLES * 2  # PCM16, 2 bytes per sample.

_ZERO_STATE = np.zeros((2, 1, 64), dtype=np.float32)
_SAMPLE_RATE_INPUT = np.array(SAMPLE_RATE, dtype=np.int64)


def score_frames(session: Any, audio: bytes) -> list[float]:
    """Score each complete `FRAME_SAMPLES`-sample frame in `audio` for speech
    probability. Trailing bytes short of one full frame are dropped — the
    caller is responsible for carrying them into its next call rather than
    losing them here (`askwell.voice_turn_detection._VadTurnDetector` does
    exactly that)."""
    usable = len(audio) - (len(audio) % FRAME_BYTES)
    if usable == 0:
        return []
    samples = np.frombuffer(audio[:usable], dtype="<i2").astype(np.float32) / 32768.0

    probabilities: list[float] = []
    for start in range(0, samples.size, FRAME_SAMPLES):
        frame = samples[start : start + FRAME_SAMPLES].reshape(1, FRAME_SAMPLES)
        outputs = session.run(
            None,
            {"input": frame, "sr": _SAMPLE_RATE_INPUT, "h": _ZERO_STATE, "c": _ZERO_STATE},
        )
        probabilities.append(float(np.asarray(outputs[0]).reshape(-1)[0]))
    return probabilities
