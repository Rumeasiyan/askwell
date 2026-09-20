"""Turning one unit of answer text into speech. `M6-TTS-BE-130`.

Runs inside the `voice` container, against the Kokoro handle
`askwell.voice.models` already loaded at startup. `api` never imports
`kokoro_onnx` itself — it only ever sees the raw PCM bytes this module's
caller (`voice/service.py`'s `/synthesize`) returns, over the internal
network (`askwell.voice_tts`, in `api`), the same shape `voice/transcribe.py`
established for `/transcribe`.

**Wire format: PCM16 little-endian, mono, at whatever sample rate Kokoro
itself produced** — 24 kHz for the bundled v1.0 model, but never hardcoded
here: the rate travels back with every response instead, so a future model
swap cannot silently desync the two sides. Resampling to the 16 kHz the
input side fixed on would need a resampling dependency this container has no
other reason to carry — the same reasoning `voice/transcribe.py`'s own
docstring gives for never decoding compressed audio here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass(frozen=True, slots=True)
class SynthesisResult:
    audio: bytes  # PCM16 little-endian, mono
    sample_rate: int


def _float32_to_pcm16(samples: np.ndarray) -> bytes:
    clipped = np.clip(samples, -1.0, 1.0)
    return bytes((clipped * 32767.0).astype("<i2").tobytes())


def synthesize(kokoro: Any, text: str, voice: str, speed: float = 1.0) -> SynthesisResult:
    """Synthesize one unit of text — a sentence, or a whole short answer — into
    audio. `kokoro` is a loaded `kokoro_onnx.Kokoro`; the caller
    (`voice/service.py`) is responsible for checking it loaded at all before
    calling this."""
    audio, sample_rate = kokoro.create(text, voice=voice, speed=speed, lang="en-us")
    return SynthesisResult(audio=_float32_to_pcm16(audio), sample_rate=sample_rate)
