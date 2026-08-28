import inspect
import json
from datetime import datetime
from pathlib import Path

from eval.results import (
    RunResult,
    SuiteRunReport,
    TaskResult,
    format_mean_worst,
    format_summary,
    write_report,
)


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


def test_format_summary_never_prints_a_mean_without_its_worst_case() -> None:
    """`M2-EVAL-TEST-066`'s reporting-discipline requirement, checked the
    only way it can be from outside: every summary line naming a mean also
    names a worst-of-3, for the category line and every per-task line."""
    text = format_summary(_report(strict=False))
    lines_with_mean = [line for line in text.splitlines() if "mean" in line]
    assert lines_with_mean
    assert all("worst-of-3" in line for line in lines_with_mean)


def test_format_mean_worst_pairs_mean_and_worst_in_one_string() -> None:
    assert format_mean_worst(0.9, 0.55) == "mean: 0.90  worst-of-3: 0.55"


def test_format_mean_worst_has_no_way_to_omit_worst_case() -> None:
    """The harness has no code path that can print a mean-only summary: the
    only rendering function has two required positional parameters, with no
    default that would let a caller supply one and skip the other."""
    parameters = inspect.signature(format_mean_worst).parameters
    assert all(parameter.default is inspect.Parameter.empty for parameter in parameters.values())
