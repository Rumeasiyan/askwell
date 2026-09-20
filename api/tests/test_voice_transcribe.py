"""`askwell.voice.transcribe`: turning a Whisper result into a transcript, a
confidence measure, or a no-speech/unsupported-language verdict.
`M6-STT-BE-127`.

No network, no Postgres — a fake stands in for `faster_whisper.WhisperModel`,
shaped exactly like the real `transcribe()`: a lazy segment generator plus an
`info` object available before it is ever iterated.
"""

import math
from dataclasses import dataclass, field

from askwell.voice.transcribe import transcribe


@dataclass
class _Segment:
    text: str
    start: float
    end: float
    avg_logprob: float


@dataclass
class _Info:
    language: str
    language_probability: float


@dataclass
class _FakeWhisper:
    segments: list[_Segment]
    info: _Info
    iterated: bool = field(default=False, init=False)

    def transcribe(self, _audio, **_kwargs):
        def generator():
            self.iterated = True
            yield from self.segments

        return generator(), self.info


def _pcm(seconds: float = 1.0) -> bytes:
    return b"\x01\x00" * int(16_000 * seconds)


def test_empty_audio_is_no_speech_without_calling_whisper_at_all() -> None:
    whisper = _FakeWhisper(segments=[], info=_Info("en", 1.0))
    result = transcribe(whisper, b"")
    assert result.status == "no_speech"
    assert result.transcript == ""


def test_non_english_language_is_reported_without_transcribing_it() -> None:
    whisper = _FakeWhisper(
        segments=[_Segment(text=" Bonjour", start=0.0, end=1.0, avg_logprob=-0.1)],
        info=_Info("fr", 0.93),
    )
    result = transcribe(whisper, _pcm())
    assert result.status == "unsupported_language"
    assert result.language == "fr"
    assert result.language_probability == 0.93
    assert result.transcript == ""
    # The whole point of checking `info` first: the French segment above was
    # never decoded because the generator was never touched.
    assert whisper.iterated is False


def test_english_with_no_segments_is_no_speech() -> None:
    """Whisper's own `no_speech_threshold` already dropped every candidate —
    background noise, not a transcription that came out empty."""
    whisper = _FakeWhisper(segments=[], info=_Info("en", 1.0))
    result = transcribe(whisper, _pcm())
    assert result.status == "no_speech"


def test_english_speech_produces_a_transcript_and_a_weighted_confidence() -> None:
    segments = [
        _Segment(text=" what is the", start=0.0, end=1.0, avg_logprob=-0.05),
        _Segment(text=" notice period", start=1.0, end=3.0, avg_logprob=-0.5),
    ]
    whisper = _FakeWhisper(segments=segments, info=_Info("en", 0.99))

    result = transcribe(whisper, _pcm())

    assert result.status == "ok"
    assert result.transcript == "what is the notice period"
    assert result.language == "en"
    assert result.language_probability == 0.99

    expected = (math.exp(-0.05) * 1.0 + math.exp(-0.5) * 2.0) / 3.0
    assert result.confidence is not None
    assert math.isclose(result.confidence, expected, rel_tol=1e-9)


def test_a_very_quiet_but_real_segment_is_transcribed_with_low_confidence_not_discarded() -> None:
    """The ticket's own edge case: quiet speech gets a low-confidence
    transcript, never silence."""
    whisper = _FakeWhisper(
        segments=[_Segment(text=" reference four two", start=0.0, end=1.0, avg_logprob=-2.5)],
        info=_Info("en", 0.8),
    )
    result = transcribe(whisper, _pcm())
    assert result.status == "ok"
    assert result.transcript == "reference four two"
    assert result.confidence is not None
    assert result.confidence < 0.2


def test_confidence_is_never_reported_outside_zero_to_one() -> None:
    whisper = _FakeWhisper(
        segments=[_Segment(text=" hi", start=0.0, end=1.0, avg_logprob=5.0)],
        info=_Info("en", 1.0),
    )
    result = transcribe(whisper, _pcm())
    assert result.confidence is not None
    assert 0.0 <= result.confidence <= 1.0
