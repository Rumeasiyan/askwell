"""Turning captured audio into a transcript. `M6-STT-BE-127`.

Runs inside the `voice` container, against the Whisper handle
`askwell.voice.models` already loaded at startup. `api` never imports
`faster_whisper` itself — it only ever sees the JSON this module's caller
(`voice/service.py`'s `/transcribe`) returns, over the internal network
(`askwell.voice_stt`, in `api`).

**Wire format: 16 kHz mono, 16-bit signed PCM, little-endian.** Decided here
rather than left open, because nothing else in the repository has fixed it
yet — the WebSocket transport (`M6-AUDIO-API-126`) carries opaque bytes, and
no frontend capture code exists before `M6-VUI-FE-132`. This is also exactly
what Silero VAD's own model wants (`M6-STT-BE-128`), so one format serves
capture, VAD and Whisper with no resampling step at any boundary. Never
compressed audio: decoding webm/opus server-side would need ffmpeg or a codec
library, a fourth dependency in a container whose whole justification
(`docs/decisions.md`, `M6-AUDIO-DEPLOY-125`) was reusing the existing image
for three ML libraries and nothing else. Recorded as a decision, not just this
comment (`docs/decisions.md`, this date).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np

SAMPLE_RATE = 16_000

Status = Literal["ok", "no_speech", "unsupported_language"]


@dataclass(frozen=True, slots=True)
class TranscriptionResult:
    status: Status
    transcript: str = ""
    confidence: float | None = None
    language: str | None = None
    language_probability: float | None = None


def _pcm16_to_float32(audio: bytes) -> np.ndarray:
    if not audio:
        return np.zeros(0, dtype=np.float32)
    samples = np.frombuffer(audio, dtype="<i2")
    return samples.astype(np.float32) / 32768.0


def _segment_confidence(segment: Any) -> float:
    # faster-whisper reports `avg_logprob` — a log probability, not a
    # confidence. `exp` turns it back into one. This is the coarsest signal
    # available (`word_timestamps=False`, so there is no per-word score to
    # aggregate instead), which matches what the ticket asks for: "a
    # confidence measure", not a per-word one.
    return math.exp(segment.avg_logprob)


def transcribe(whisper: Any, audio: bytes) -> TranscriptionResult:
    """Transcribe one complete spoken turn. `whisper` is a loaded
    `faster_whisper.WhisperModel`; the caller (`voice/service.py`) is
    responsible for checking it loaded at all before calling this."""
    pcm = _pcm16_to_float32(audio)
    if pcm.size == 0:
        return TranscriptionResult(status="no_speech")

    segments, info = whisper.transcribe(
        pcm,
        language=None,
        task="transcribe",
        # Silero gating is `M6-STT-BE-128`, not this ticket — this ticket
        # transcribes exactly the audio it was handed, whatever closed the
        # turn (today, only the client's own `end`/`stop` signal).
        vad_filter=False,
        without_timestamps=True,
    )

    if info.language != "en":
        # `info` is ready before the segment generator is ever touched —
        # faster-whisper runs language identification as a separate, cheap
        # pass ahead of decoding. "No attempt at another language" holds
        # literally: `segments` is never iterated for one.
        return TranscriptionResult(
            status="unsupported_language",
            language=info.language,
            language_probability=info.language_probability,
        )

    collected = list(segments)
    if not collected:
        # Whisper's own `no_speech_threshold`/`log_prob_threshold` already
        # dropped every candidate segment — quiet background noise, not a
        # transcription that happened to come out empty.
        return TranscriptionResult(status="no_speech")

    transcript = "".join(segment.text for segment in collected).strip()
    if not transcript:
        return TranscriptionResult(status="no_speech")

    total_duration = sum(max(segment.end - segment.start, 0.0) for segment in collected)
    if total_duration > 0:
        confidence = (
            sum(
                _segment_confidence(segment) * max(segment.end - segment.start, 0.0)
                for segment in collected
            )
            / total_duration
        )
    else:
        confidence = sum(_segment_confidence(segment) for segment in collected) / len(collected)

    return TranscriptionResult(
        status="ok",
        transcript=transcript,
        confidence=min(max(confidence, 0.0), 1.0),
        language=info.language,
        language_probability=info.language_probability,
    )
