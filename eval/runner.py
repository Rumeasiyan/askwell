"""Runs one suite against the configured model and produces a `SuiteRunReport`.

Talks to the model exactly the way the product does — `InferenceClient`, over
the Unix socket the native inference process listens on (`docs/decisions.md`,
`api/src/askwell/inference/client.py`) — so a result here says something about
the real answer path, and needs no network to do it (C1).
"""

import asyncio

from askwell.config import Settings
from askwell.inference.client import (
    Completion,
    InferenceClient,
    InferenceFailed,
    InferenceUnavailable,
)
from askwell.inference.state import read as read_inference_state
from eval import prompt_versions
from eval.results import RunResult, SuiteRunReport, TaskResult, now
from eval.scoring import score
from eval.suite import Suite, Task

RUNS_PER_TASK = 3
"""Fixed, not a CLI option. AGENTS.md-derived rule: a suite may never be run
once and reported as if run three times — the only way to guarantee that is
to not expose a way to ask for fewer."""


class HarnessError(RuntimeError):
    """The suite could not be measured at all — never reported as a score."""


async def _run_task(client: InferenceClient, task: Task) -> TaskResult:
    runs: list[RunResult] = []
    for _ in range(RUNS_PER_TASK):
        try:
            completion: Completion = await client.generate(
                task.prompt, timeout_seconds=task.timeout_seconds
            )
        except InferenceFailed as error:
            # A malformed output, a timeout, a refused request: this run
            # failed and the reason is kept, but the task itself continues —
            # exactly the "single malformed output" case the worst-of-3
            # design exists to catch rather than paper over.
            runs.append(RunResult(score=0.0, output=None, error=str(error)))
            continue
        try:
            run_score = score(task.scorer, completion.text, task.expected)
        except ValueError as error:
            runs.append(RunResult(score=0.0, output=completion.text, error=str(error)))
            continue
        runs.append(RunResult(score=run_score, output=completion.text, error=None))
    return TaskResult(task_id=task.id, prompt=task.prompt, runs=tuple(runs))


async def run_suite(settings: Settings, suite: Suite) -> SuiteRunReport:
    client = InferenceClient(settings)
    started_at = now()

    try:
        task_results = [await _run_task(client, task) for task in suite.tasks]
    except InferenceUnavailable as error:
        # Mid-run or before the first task: the model itself is not there, not
        # a single task failing. Reporting scores for the tasks that happened
        # to run before it went away would look like a measurement; it is not
        # one, so nothing is reported at all — this propagates and the CLI
        # exits non-zero with the reason.
        raise HarnessError(f"model unavailable: {error}") from error

    finished_at = now()

    return SuiteRunReport(
        suite_name=suite.name,
        category=suite.category,
        pass_bar=suite.pass_bar,
        strict=suite.strict,
        model=_current_model_name(settings),
        profile=settings.profile.value,
        prompt_versions=prompt_versions.read_prompt_versions(prompt_versions.default_prompts_dir()),
        started_at=started_at,
        finished_at=finished_at,
        runs_per_task=RUNS_PER_TASK,
        task_results=tuple(task_results),
    )


def _current_model_name(settings: Settings) -> str | None:
    """The model actually loaded, per the supervisor's own state file.

    Never the configured path or a name written in this code (AGENTS.md §4):
    the state file is what the supervisor observed llama.cpp report after
    loading, so a mismatch between configuration and reality shows up here
    rather than being asserted away.
    """
    state_path = settings.inference_socket.parent / "state.json"
    return read_inference_state(state_path).model


def run_suite_sync(settings: Settings, suite: Suite) -> SuiteRunReport:
    return asyncio.run(run_suite(settings, suite))
