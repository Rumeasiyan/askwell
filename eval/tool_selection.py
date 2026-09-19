"""Runs `mode: "tool_selection"` suites against the real multi-step tool
loop -- `askwell.agent.loop.run_tool_loop` -- over both the fixture document
corpus (`eval.grounded.seed_corpus`) and the fixture sandbox database
(`eval.sql_fixture.seed_sql_fixture`), seeded together so a task can need
either, both, or neither. `M5-EVAL-TEST-124`.

**Tool choice and the final answer are scored separately, then combined.**
`tool_choice_score` compares the distinct tools the loop actually called
(`LoopResult.tool_names_called` -- already deduplicated by the loop itself)
against a task's `expected_tool_routes`: more than one accepted route is the
ticket's own "two acceptable tool routes" edge case, and an empty route is
the "correct behaviour is no tool at all" edge case. A task whose accepted
route requires more than one tool can also set `require_parallel`, checked
by `parallel_achieved` against `LoopStep.iteration` -- two fresh (not
deduplicated) calls sharing one iteration is exactly what
`asyncio.gather`-based dispatch in `askwell.agent.loop` produces, and is the
one thing a regression to one-call-per-iteration could not fake. The final
answer is scored the ordinary way, through `eval.scoring.score`. Each run's
score is the two combined evenly, same as `eval.grounded`'s own "half a
right answer by the wrong route is not a pass" weighting, so a right answer
reached by the wrong tool -- or a wrong answer despite the right tool -- is
visible rather than folded into a single number that reads as fine either
way.
"""

import asyncio
from collections import Counter

from askwell.agent.loop import LoopStep, run_tool_loop
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory, session_scope
from askwell.inference.client import InferenceClient, InferenceFailed, InferenceUnavailable
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from eval import prompt_versions
from eval.grounded import seed_corpus
from eval.results import RunResult, SuiteRunReport, TaskResult, now
from eval.runner import RUNS_PER_TASK, HarnessError, current_model_name
from eval.scoring import score
from eval.sql_fixture import seed_sql_fixture
from eval.suite import Suite, Task


def tool_choice_score(
    actual_tools: frozenset[str], accepted_routes: tuple[tuple[str, ...], ...]
) -> float:
    """1.0 if the distinct tools actually called match one accepted route
    exactly -- not a subset or superset. Calling an extra, unneeded tool
    (the "tempted by an unnecessary database call" edge case) fails this the
    same way missing a needed one does: the accepted routes name what
    correct looks like, not a floor.
    """
    accepted_sets = {frozenset(route) for route in accepted_routes}
    return 1.0 if actual_tools in accepted_sets else 0.0


def parallel_achieved(steps: tuple[LoopStep, ...]) -> bool:
    """True if at least two distinct, freshly-dispatched (not deduplicated)
    tool calls share one iteration -- the trace signature of
    `askwell.agent.loop`'s `asyncio.gather` batch, the only way two
    independent calls the model emitted together could land in the same
    iteration. A loop that dispatched them one iteration at a time, even if
    it eventually made both calls, did not do this.
    """
    counts = Counter(step.iteration for step in steps if not step.deduplicated)
    return any(count >= 2 for count in counts.values())


def combined_tool_score(
    actual_tools: frozenset[str],
    accepted_routes: tuple[tuple[str, ...], ...],
    *,
    require_parallel: bool,
    achieved_parallel: bool,
) -> float:
    """`tool_choice_score`, zeroed out if this task required parallel
    dispatch and did not get it -- calling the right two tools sequentially
    is not the behaviour this task exists to measure, however correct the
    resulting answer looks.
    """
    base = tool_choice_score(actual_tools, accepted_routes)
    if require_parallel and not achieved_parallel:
        return 0.0
    return base


async def _run_tool_task(
    factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    client: InferenceClient,
    task: Task,
) -> TaskResult:
    runs: list[RunResult] = []
    for _ in range(RUNS_PER_TASK):
        async with session_scope(factory) as db:
            try:
                loop_result = await run_tool_loop(db, settings, client, question=task.prompt)
            except InferenceFailed as error:
                runs.append(RunResult(score=0.0, output=None, error=str(error)))
                continue

        actual_tools = frozenset(loop_result.tool_names_called)
        achieved_parallel = parallel_achieved(loop_result.steps)
        tool_score = combined_tool_score(
            actual_tools,
            task.expected_tool_routes,
            require_parallel=task.require_parallel,
            achieved_parallel=achieved_parallel,
        )

        try:
            answer_score = score(task.scorer, loop_result.text, task.expected)
        except ValueError as error:
            runs.append(RunResult(score=0.0, output=loop_result.text, error=str(error)))
            continue

        combined = 0.5 * tool_score + 0.5 * answer_score
        note = None
        if combined < 1.0:
            detail = (
                f"tool_score={tool_score:.2f} (called: {sorted(actual_tools)}) "
                f"answer_score={answer_score:.2f}"
            )
            if task.require_parallel and not achieved_parallel:
                detail += " -- parallel dispatch required but not observed"
            note = detail
        runs.append(RunResult(score=combined, output=loop_result.text, error=note))
    return TaskResult(task_id=task.id, prompt=task.prompt, runs=tuple(runs))


async def run_tool_selection_suite(settings: Settings, suite: Suite) -> SuiteRunReport:
    engine = build_engine(settings)
    factory = session_factory(engine)
    client = InferenceClient(settings)
    started_at = now()
    try:
        try:
            await seed_corpus(factory, settings)
            await seed_sql_fixture(factory, settings)
            task_results = [
                await _run_tool_task(factory, settings, client, task) for task in suite.tasks
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


def run_tool_selection_suite_sync(settings: Settings, suite: Suite) -> SuiteRunReport:
    return asyncio.run(run_tool_selection_suite(settings, suite))
