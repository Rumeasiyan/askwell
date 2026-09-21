"""Pure logic in `eval.voice_latency`: budget selection, per-stage
median/worst summarization, and the dominant-stage call. `M6-PERF-TEST-136`.

No WebSocket, no fixture audio, no running stack — the harness's network
half is exercised by hand against the real stack (recorded in the ticket's
own closing comment), not here.
"""

import wave
from pathlib import Path

from eval.voice_latency import (
    SAMPLE_RATE,
    TurnResult,
    budget_ms,
    dominant_stage,
    load_fixture,
    summarize,
)


def test_accelerated_gets_the_35_second_budget() -> None:
    assert budget_ms("accelerated") == 3500.0


def test_every_other_profile_gets_the_8_second_budget() -> None:
    # Matches `web/lib/voice.ts`'s own `voiceLatencyBudgetMs` mapping —
    # `workstation` included deliberately, not just `standard`/`light`.
    for profile in ("standard", "light", "workstation", "unknown"):
        assert budget_ms(profile) == 8000.0


def _ok(breakdown: dict[str, float | None]) -> TurnResult:
    return TurnResult(ok=True, status="completed", breakdown=breakdown, error=None)


def _failed(error: str) -> TurnResult:
    return TurnResult(ok=False, status="failed", breakdown=None, error=error)


def test_summarize_reports_median_and_worst_per_stage() -> None:
    results = [
        _ok(
            {
                "transcription_ms": 100.0,
                "retrieval_ms": 200.0,
                "generation_ms": 300.0,
                "synthesis_ms": 400.0,
                "first_audio_ms": 1000.0,
            }
        ),
        _ok(
            {
                "transcription_ms": 300.0,
                "retrieval_ms": 200.0,
                "generation_ms": 300.0,
                "synthesis_ms": 400.0,
                "first_audio_ms": 1200.0,
            }
        ),
    ]
    summary = summarize(results)
    assert summary["transcription_ms"]["median_ms"] == 200.0
    assert summary["transcription_ms"]["worst_ms"] == 300.0
    assert summary["transcription_ms"]["n"] == 2
    assert summary["first_audio_ms"]["worst_ms"] == 1200.0


def test_a_failed_turn_is_excluded_rather_than_treated_as_a_zero() -> None:
    results = [
        _ok(
            {
                "transcription_ms": 100.0,
                "retrieval_ms": None,
                "generation_ms": None,
                "synthesis_ms": None,
                "first_audio_ms": None,
            }
        ),
        _failed("connection refused"),
    ]
    summary = summarize(results)
    assert summary["transcription_ms"]["n"] == 1
    assert summary["transcription_ms"]["median_ms"] == 100.0
    assert summary["retrieval_ms"] == {"median_ms": None, "worst_ms": None, "n": 0}


def test_dominant_stage_is_the_attributable_stage_with_the_largest_median() -> None:
    results = [
        _ok(
            {
                "transcription_ms": 6000.0,
                "retrieval_ms": 100.0,
                "generation_ms": 200.0,
                "synthesis_ms": 300.0,
                "first_audio_ms": 6600.0,
            }
        )
    ]
    summary = summarize(results)
    assert dominant_stage(summary) == "transcription_ms"


def test_dominant_stage_is_none_when_nothing_was_measured() -> None:
    assert dominant_stage(summarize([_failed("timeout")])) is None


def test_load_fixture_reads_a_16k_mono_wav(tmp_path: Path) -> None:
    path = tmp_path / "sample.wav"
    frames = b"\x00\x01" * SAMPLE_RATE  # one second, arbitrary content
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(SAMPLE_RATE)
        wav_file.writeframes(frames)

    assert load_fixture(path) == frames


def test_load_fixture_rejects_the_wrong_sample_rate(tmp_path: Path) -> None:
    path = tmp_path / "sample.wav"
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(44_100)
        wav_file.writeframes(b"\x00\x01" * 1000)

    try:
        load_fixture(path)
        raised = False
    except ValueError:
        raised = True
    assert raised, "expected a ValueError for a non-16kHz fixture"


def test_load_fixture_reads_a_headerless_pcm_file(tmp_path: Path) -> None:
    path = tmp_path / "sample.pcm"
    raw = b"\x01\x02\x03\x04"
    path.write_bytes(raw)
    assert load_fixture(path) == raw
