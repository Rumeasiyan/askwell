import json
from datetime import datetime
from pathlib import Path

from eval.results import RunResult, SuiteRunReport, TaskResult, format_summary, write_report


def _report(*, pass_bar: float = 0.85, strict: bool = False) -> SuiteRunReport:
    task = TaskResult(
        task_id="t1",
        prompt="p",
        runs=(
            RunResult(score=1.0, output="a", error=None),
            RunResult(score=0.0, output=None, error="timeout"),
            RunResult(score=1.0, output="a", error=None),
        ),
    )
    return SuiteRunReport(
        suite_name="fixture",
        category="fixture",
        pass_bar=pass_bar,
        strict=strict,
        model="qwen3.5-4b",
        profile="balanced",
        prompt_versions={"answer_composition": "v1"},
        started_at=datetime(2026, 8, 28, 12, 0, 0),
        finished_at=datetime(2026, 8, 28, 12, 0, 5),
        runs_per_task=3,
        task_results=(task,),
    )


def test_task_mean_and_worst() -> None:
    report = _report()
    task = report.task_results[0]
    assert task.mean == 2 / 3
    assert task.worst == 0.0


def test_category_aggregates_across_tasks() -> None:
    report = _report()
    assert report.category_mean == 2 / 3
    assert report.category_worst == 0.0


def test_passed_is_none_when_not_strict() -> None:
    assert _report(strict=False).passed is None


def test_passed_is_false_when_any_run_is_imperfect() -> None:
    assert _report(strict=True).passed is False


def test_write_report_round_trips_to_json(tmp_path: Path) -> None:
    report = _report()
    out_path = write_report(report, tmp_path)

    assert out_path.exists()
    payload = json.loads(out_path.read_text())
    assert payload["suite"] == "fixture"
    assert payload["model"] == "qwen3.5-4b"
    assert payload["runs_per_task"] == 3
    assert len(payload["tasks"][0]["runs"]) == 3
    assert payload["tasks"][0]["runs"][1]["error"] == "timeout"


def test_format_summary_shows_pass_fail_for_strict_suite() -> None:
    text = format_summary(_report(strict=True, pass_bar=1.0))
    assert "FAIL" in text
    assert "strict" in text
