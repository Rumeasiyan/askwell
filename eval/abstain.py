"""Runs a `mode: "abstain"` suite: unanswerable questions over the seeded
fixture corpus, scored on whether the turn actually abstains and whether the
abstention proves the search happened — C5's "abstention over invention",
made measurable rather than trusted (`M2-EVAL-TEST-065`).

Reuses `eval.grounded`'s `seed_corpus`/`_ask_one`: indexing the corpus and
driving one real `askwell.ask` turn is identical work to the grounded suite,
only the scoring differs. A near-miss task (relevant material exists but
does not answer the question) is not a separate code path — it is an
ordinary task whose retrieval scores just under threshold, so the existing
`below_threshold` abstain path (`askwell.agent.abstain.compose_abstention`)
already produces the proof sentence this module checks for. The
`empty_corpus`/`source_indexing` variants are asserted separately, per the
ticket's own edge cases, and never reached here because the fixture corpus
this suite runs against is always fully indexed first.
"""

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory
from askwell.inference.client import InferenceFailed, InferenceUnavailable
from eval import prompt_versions
from eval.grounded import _ask_one, seed_corpus
from eval.results import RunResult, SuiteRunReport, TaskResult, now
from eval.runner import RUNS_PER_TASK, HarnessError, current_model_name
from eval.suite import Suite, Task

ABSTAIN_PREFIX = "Nothing in your files answers this"
"""Every variant of `compose_abstention`'s output starts with this sentence —
the one string a scorer can check without re-implementing the template."""

SEARCH_EVIDENCE = "I searched"
"""Only the `below_threshold` variant includes the proof sentence this names
(`compose_abstention`'s `proof` string) — the fixture corpus is always fully
indexed and non-empty before this suite runs, so every task here is expected
to take that variant. A task that abstains without it has abstained for the
wrong reason, or the copy has regressed, either of which is a real failure."""


def abstain_score(answer: str) -> float:
    """1.0 only if the turn both abstained and named what it searched.

    A hedged partial answer ("I couldn't find much, but it might be...")
    does not start with `ABSTAIN_PREFIX` and scores 0 — the ticket's own
    "a hedged answer counts as a hallucination for scoring purposes" rule.
    There is no partial credit for abstaining without proof: against this
    corpus that is a regression in the abstention copy itself, not a
    tolerable variant.
    """
    if not answer.startswith(ABSTAIN_PREFIX):
        return 0.0
    return 1.0 if SEARCH_EVIDENCE in answer else 0.0


async def _run_abstain_task(
    factory: async_sessionmaker[AsyncSession], settings: Settings, task: Task
) -> TaskResult:
    runs: list[RunResult] = []
    for _ in range(RUNS_PER_TASK):
        try:
            answer, _citations = await _ask_one(factory, settings, task.prompt)
        except (InferenceUnavailable, InferenceFailed) as error:
            runs.append(RunResult(score=0.0, output=None, error=str(error)))
            continue
        runs.append(RunResult(score=abstain_score(answer), output=answer, error=None))
    return TaskResult(task_id=task.id, prompt=task.prompt, runs=tuple(runs))


async def run_abstain_suite(settings: Settings, suite: Suite) -> SuiteRunReport:
    engine = build_engine(settings)
    factory = session_factory(engine)
    started_at = now()
    try:
        try:
            await seed_corpus(factory, settings)
            task_results = [
                await _run_abstain_task(factory, settings, task) for task in suite.tasks
            ]
        except InferenceUnavailable as error:
            raise HarnessError(f"model unavailable: {error}") from error
    finally:
        await engine.dispose()
    finished_at = now()

    return SuiteRunReport(
        suite_name=suite.name,
        category=suite.category,
        pass_bar=suite.pass_bar,
        strict=suite.strict,
        model=current_model_name(settings),
        profile=settings.profile.value,
        prompt_versions=prompt_versions.read_prompt_versions(prompt_versions.default_prompts_dir()),
        started_at=started_at,
        finished_at=finished_at,
        runs_per_task=RUNS_PER_TASK,
        task_results=tuple(task_results),
    )


def run_abstain_suite_sync(settings: Settings, suite: Suite) -> SuiteRunReport:
    return asyncio.run(run_abstain_suite(settings, suite))
