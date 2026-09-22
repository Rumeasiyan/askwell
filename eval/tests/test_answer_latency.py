"""Pure logic in `eval.answer_latency`: SSE event-kind pairing, per-metric
percentile summarization, stage-breakdown attribution and the budget
verdict. `M7-PERF-TEST-167`.

No running stack, no httpx stream, no database — the harness's network and
ingestion halves are exercised by hand against the real stack (recorded in
the ticket's own closing comment), matching `eval/tests/test_voice_latency.py`'s
own split.
"""

from eval.answer_latency import (
    BUDGETED_PROFILE,
    TurnResult,
    budget_verdict,
    dominant_stage,
    iter_sse_event_kinds,
    stage_breakdown,
    summarize_metric,
)


def test_iter_sse_event_kinds_pairs_event_and_data_lines_in_order() -> None:
    lines = [
        "event: step",
        'data: {"label": "Searching your files."}',
        "",
        "event: token",
        'data: {"text": "Hello"}',
        "event: token",
        'data: {"text": " world"}',
        "",
        "event: done",
        'data: {"status": "completed"}',
    ]
    assert iter_sse_event_kinds(lines) == ["step", "token", "token", "done"]


def test_iter_sse_event_kinds_ignores_an_event_line_with_no_data() -> None:
    # A heartbeat or a dropped line, never a scored event.
    lines = ["event: step", "event: token", 'data: {"text": "hi"}']
    assert iter_sse_event_kinds(lines) == ["token"]


def test_iter_sse_event_kinds_ignores_a_data_line_with_no_preceding_event() -> None:
    lines = ['data: {"stray": true}', "event: done", 'data: {"status": "completed"}']
    assert iter_sse_event_kinds(lines) == ["done"]


def _ok(first_step: float, first_token: float, total: float) -> TurnResult:
    return TurnResult(True, "q", first_step, first_token, total, None, None)


def _failed(error: str) -> TurnResult:
    return TurnResult(False, "q", None, None, None, None, error)


def test_summarize_metric_reports_p50_and_p95_over_ok_turns_only() -> None:
    results = [
        _ok(100.0, 500.0, 5_000.0),
        _ok(200.0, 600.0, 6_000.0),
        _failed("timeout"),
    ]
    summary = summarize_metric(results, "first_step_ms")
    assert summary["p50_ms"] == 150.0
    assert summary["n"] == 2


def test_summarize_metric_is_none_when_nothing_measured() -> None:
    summary = summarize_metric([_failed("timeout")], "total_ms")
    assert summary == {"p50_ms": None, "p95_ms": None, "n": 0}


def test_stage_breakdown_excludes_turns_missing_that_stage() -> None:
    results = [
        TurnResult(True, "q", 1.0, 2.0, 3.0, {"retrieve": 100.0, "compose": 200.0}, None),
        TurnResult(True, "q", 1.0, 2.0, 3.0, {"retrieve": 300.0}, None),
    ]
    breakdown = stage_breakdown(results)
    assert breakdown["retrieve"]["median_ms"] == 200.0
    assert breakdown["retrieve"]["n"] == 2
    assert breakdown["compose"]["median_ms"] == 200.0
    assert breakdown["compose"]["n"] == 1


def test_dominant_stage_is_the_largest_median() -> None:
    results = [
        TurnResult(True, "q", 1.0, 2.0, 3.0, {"retrieve": 9000.0, "compose": 100.0}, None)
    ]
    assert dominant_stage(stage_breakdown(results)) == "retrieve"


def test_dominant_stage_is_none_when_nothing_measured() -> None:
    assert dominant_stage(stage_breakdown([_failed("timeout")])) is None


def test_budget_verdict_is_inapplicable_off_the_standard_profile() -> None:
    empty = {"p50_ms": None, "p95_ms": None, "n": 0}
    verdict = budget_verdict("accelerated", empty, empty, empty)
    assert verdict["applicable"] is False


def test_budget_verdict_passes_when_every_check_is_within_budget() -> None:
    assert BUDGETED_PROFILE == "standard"
    first_step = {"p50_ms": 100.0, "p95_ms": 350.0, "n": 5}
    first_token = {"p50_ms": 1200.0, "p95_ms": 2500.0, "n": 5}
    full_answer = {"p50_ms": 12_000.0, "p95_ms": 45_000.0, "n": 5}
    verdict = budget_verdict("standard", first_step, first_token, full_answer)
    assert verdict["applicable"] is True
    assert verdict["passed"] is True
    assert all(verdict["checks"].values())


def test_budget_verdict_names_the_missed_check() -> None:
    first_step = {"p50_ms": 100.0, "p95_ms": 350.0, "n": 5}
    first_token = {"p50_ms": 1200.0, "p95_ms": 2500.0, "n": 5}
    slow_full_answer = {"p50_ms": 25_000.0, "p95_ms": 70_000.0, "n": 5}
    verdict = budget_verdict("standard", first_step, first_token, slow_full_answer)
    assert verdict["passed"] is False
    assert verdict["checks"]["full_answer_p50_lte_20000ms"] is False
    assert verdict["checks"]["full_answer_p95_lte_60000ms"] is False
    assert verdict["checks"]["first_step_label_p95_lte_400ms"] is True


def test_budget_verdict_is_a_miss_when_nothing_reached_a_stage() -> None:
    empty = {"p50_ms": None, "p95_ms": None, "n": 0}
    verdict = budget_verdict("standard", empty, empty, empty)
    assert verdict["applicable"] is True
    assert verdict["passed"] is False
    assert not any(verdict["checks"].values())
