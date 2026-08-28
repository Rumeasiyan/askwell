"""The results format: what a run produces, and how two runs get compared.

Recorded per `AGENTS.md` §4 ("any prompt change requires an eval run, record
before/after in `docs/BRAIN.md`") and this ticket's acceptance criteria: model,
prompt version and date travel with every run so a result found later can be
trusted without re-running it.
"""

import json
import statistics
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RunResult:
    """One of the three executions of one task."""

    score: float
    output: str | None
    error: str | None
    """Set, never silently empty, when the run did not score cleanly —

    a timeout, an inference failure, or a scorer rejecting the output. A run
    that failed and a run that scored 0.0 on a well-formed answer must not
    look the same in the record.
    """


@dataclass(frozen=True, slots=True)
class TaskResult:
    task_id: str
    prompt: str
    runs: tuple[RunResult, ...]

    @property
    def mean(self) -> float:
        return statistics.mean(run.score for run in self.runs)

    @property
    def worst(self) -> float:
        return min(run.score for run in self.runs)


@dataclass(frozen=True, slots=True)
class SuiteRunReport:
    suite_name: str
    category: str
    pass_bar: float
    strict: bool
    model: str | None
    """The model actually loaded when the run happened, read from the
    inference supervisor's own state — never a name written into this code
    (`AGENTS.md` §4)."""
    profile: str
    prompt_versions: dict[str, str]
    started_at: datetime
    finished_at: datetime
    runs_per_task: int
    task_results: tuple[TaskResult, ...]

    @property
    def category_mean(self) -> float:
        return statistics.mean(task.mean for task in self.task_results)

    @property
    def category_worst(self) -> float:
        return statistics.mean(task.worst for task in self.task_results)

    @property
    def passed(self) -> bool | None:
        """`None` for a scored suite — mean/worst is the report, not a verdict.

        For a `pass_bar == 1.0` suite, `True` only if every single run, of
        every task, scored 1.0. One run below that is a failure, reported as
        one, never folded into a mean that reads as nearly fine.
        """
        if not self.strict:
            return None
        return all(run.score >= 1.0 for task in self.task_results for run in task.runs)

    def to_dict(self) -> dict[str, object]:
        return {
            "suite": self.suite_name,
            "category": self.category,
            "pass_bar": self.pass_bar,
            "strict": self.strict,
            "model": self.model,
            "profile": self.profile,
            "prompt_versions": self.prompt_versions,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "runs_per_task": self.runs_per_task,
            "category_mean": None if self.strict else self.category_mean,
            "category_worst": None if self.strict else self.category_worst,
            "passed": self.passed,
            "tasks": [
                {
                    "id": task.task_id,
                    "prompt": task.prompt,
                    "mean": task.mean,
                    "worst": task.worst,
                    "runs": [asdict(run) for run in task.runs],
                }
                for task in self.task_results
            ],
        }


def write_report(report: SuiteRunReport, results_dir: Path) -> Path:
    results_dir.mkdir(parents=True, exist_ok=True)
    stamp = report.started_at.strftime("%Y%m%dT%H%M%SZ")
    out_path = results_dir / f"{report.suite_name}-{stamp}.json"
    out_path.write_text(json.dumps(report.to_dict(), indent=2) + "\n")
    return out_path


def format_summary(report: SuiteRunReport) -> str:
    lines = [
        f"suite: {report.suite_name} ({report.category})",
        f"model: {report.model or 'unknown'}  profile: {report.profile}",
        f"runs per task: {report.runs_per_task}",
    ]
    if report.strict:
        verdict = "PASS" if report.passed else "FAIL"
        lines.append(f"pass_bar: 1.00 (strict)  result: {verdict}")
    else:
        lines.append(
            f"pass_bar: {report.pass_bar:.2f}  "
            f"mean: {report.category_mean:.2f}  worst-of-3: {report.category_worst:.2f}"
        )
    for task in report.task_results:
        errors = [run.error for run in task.runs if run.error]
        error_note = f"  errors: {errors}" if errors else ""
        lines.append(f"  {task.task_id}: mean={task.mean:.2f} worst={task.worst:.2f}{error_note}")
    return "\n".join(lines)


def now() -> datetime:
    return datetime.now(UTC)


def suite_default_results_dir() -> Path:
    return Path(__file__).resolve().parent / "results"


__all__ = [
    "RunResult",
    "SuiteRunReport",
    "TaskResult",
    "format_summary",
    "now",
    "suite_default_results_dir",
    "write_report",
]
