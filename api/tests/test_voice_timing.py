"""Per-stage voice latency timing: `VoiceTurn.mark`/`stage_timings` and the
pure `stage_breakdown_ms` computation. `M6-PERF-TEST-136`.

Deliberately network- and DB-free — every case here builds a plain
`stage_timings` dict or a bare `VoiceTurn` directly, the same way
`eval.voice_latency`'s harness and `askwell.voice_tts` both consume this
module, so a regression here is caught before it needs the stack up.
"""

import asyncio
import uuid

import pytest

from askwell.voice_channel import VoiceTurn, stage_breakdown_ms


def _turn() -> VoiceTurn:
    return VoiceTurn(turn_id=uuid.uuid4(), audio_in=asyncio.Queue(), audio_out=asyncio.Queue())


def test_mark_is_first_write_wins() -> None:
    turn = _turn()
    turn.mark("first_audio_ready")
    first = turn.stage_timings["first_audio_ready"]
    turn.mark("first_audio_ready")
    assert turn.stage_timings["first_audio_ready"] == first


def test_stage_breakdown_computes_each_named_interval() -> None:
    marks = {
        "speech_ended": 0.0,
        "transcription_done": 0.5,
        "retrieval_started": 0.5,
        "generation_started": 0.8,
        "first_sentence_ready": 1.6,
        "first_audio_ready": 2.1,
    }
    breakdown = stage_breakdown_ms(marks)
    assert breakdown["transcription_ms"] == pytest.approx(500.0)
    assert breakdown["retrieval_ms"] == pytest.approx(300.0)
    assert breakdown["generation_ms"] == pytest.approx(800.0)
    assert breakdown["synthesis_ms"] == pytest.approx(500.0)
    assert breakdown["first_audio_ms"] == pytest.approx(2100.0)
    # The four attributable stages must sum to the total the user actually
    # experienced — a breakdown that does not add up would misattribute a
    # miss to the wrong stage, exactly the failure this ticket exists to rule
    # out.
    attributable = sum(
        breakdown[key]
        for key in ("transcription_ms", "retrieval_ms", "generation_ms", "synthesis_ms")
    )
    assert attributable == pytest.approx(breakdown["first_audio_ms"])


def test_a_stage_never_reached_reports_none_not_a_wrong_number() -> None:
    # A turn that failed before generation ever started: no
    # `generation_started`/`first_sentence_ready`/`first_audio_ready` marks.
    marks = {"speech_ended": 0.0, "transcription_done": 0.4, "retrieval_started": 0.4}
    breakdown = stage_breakdown_ms(marks)
    assert breakdown["transcription_ms"] == 400.0
    assert breakdown["retrieval_ms"] is None
    assert breakdown["generation_ms"] is None
    assert breakdown["synthesis_ms"] is None
    assert breakdown["first_audio_ms"] is None


def test_empty_marks_report_every_stage_as_none() -> None:
    assert stage_breakdown_ms({}) == {
        "transcription_ms": None,
        "retrieval_ms": None,
        "generation_ms": None,
        "synthesis_ms": None,
        "first_audio_ms": None,
    }
