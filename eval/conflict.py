"""Runs a `mode: "conflict"` suite: questions over the seeded fixture corpus
where retrieval genuinely returns two disagreeing passages, scored on
whether the turn presents both positions, cites both, and prefers neither —
never silently resolves to one (`M2-EVAL-TEST-066`, C7's conflict handling
made measurable, following `M2-PARTIAL-BE-059`'s `askwell.agent.conflict`).

Reuses `eval.grounded`'s `seed_corpus`/`_ask_one` exactly as `eval.abstain`
does: driving one real `askwell.ask` turn is identical work, only the
scoring and one extra seeding step differ. That extra step,
`_ensure_superseded`, marks the `store_hours_2025.pdf` fixture as superseded
by `store_hours_2026.pdf` directly in the database — the same relationship
`sources.add()`'s own version-detection path would establish, set here by
hand because building it through that path needs a same-path re-add the
fixture corpus has no reason to model. Once set, `askwell.retrieve` already
excludes the superseded document from every candidate query
(`d.superseded_by IS NULL`), so the corresponding task never has two live
candidates to conflict between — it is a single-document answer by
construction, and the task's job is only to confirm that.
"""

import asyncio

from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from askwell.agent.conflict import split_conflict_answer
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory, session_scope
from askwell.inference.client import InferenceFailed, InferenceUnavailable
from eval import prompt_versions
from eval.grounded import _ask_one, seed_corpus
from eval.results import RunResult, SuiteRunReport, TaskResult, now
from eval.runner import RUNS_PER_TASK, HarnessError, current_model_name
from eval.suite import Suite, Task


async def _document_id(db: AsyncSession, filename: str) -> str | None:
    result = await db.execute(
        sql_text(
            "SELECT id FROM documents WHERE filename = :filename AND deleted_at IS NULL "
            "ORDER BY added_at DESC LIMIT 1"
        ),
        {"filename": filename},
    )
    row = result.first()
    return str(row[0]) if row is not None else None


async def _ensure_superseded(db: AsyncSession, *, old: str, new: str) -> None:
    """Idempotent: a second run against a database that already has this
    relationship set leaves it untouched, the same reasoning `_ensure_root`
    (`eval.grounded`) applies to the root row."""
    old_id = await _document_id(db, old)
    new_id = await _document_id(db, new)
    if old_id is None or new_id is None:
        raise HarnessError(
            f"conflict fixture {old!r}/{new!r} did not ingest — cannot set supersession"
        )
    await db.execute(
        sql_text(
            "UPDATE documents SET superseded_by = :new_id "
            "WHERE id = :old_id AND superseded_by IS NULL"
        ),
        {"new_id": new_id, "old_id": old_id},
    )


async def _seed_conflict_corpus(
    factory: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    await seed_corpus(factory, settings)
    async with session_scope(factory) as db:
        await _ensure_superseded(db, old="store_hours_2025.pdf", new="store_hours_2026.pdf")


def conflict_score(task: Task, answer: str, citations: list[dict[str, object]]) -> float:
    """1.0 only if the turn's conflict handling matched what the task
    expects, per the ticket's own scoring rules:

    - a genuine conflict (`expect_conflict`) must be presented as a
      conflict (`Conflicting sources on ...:`), name every expected
      position value, and cite every expected document — the "both
      presented, both cited, no silent preference" acceptance criterion;
    - a false conflict or a superseded pair (`not expect_conflict`) must
      *not* be presented as one — presenting it anyway is over-detection,
      scored as a failure, not partial credit.
    """
    conflict = split_conflict_answer(answer)
    lowered = answer.lower()
    values_present = all(value.lower() in lowered for value in task.position_values)

    if task.expect_conflict:
        if not conflict.is_conflict or not values_present:
            return 0.0
        cited_filenames = {str(c.get("filename") or "") for c in citations}
        if not all(doc in cited_filenames for doc in task.expected_documents):
            return 0.0
        return 1.0

    if conflict.is_conflict or not values_present:
        return 0.0
    return 1.0


async def _run_conflict_task(
    factory: async_sessionmaker[AsyncSession], settings: Settings, task: Task
) -> TaskResult:
    runs: list[RunResult] = []
    for _ in range(RUNS_PER_TASK):
        try:
            answer, citations = await _ask_one(factory, settings, task.prompt)
        except (InferenceUnavailable, InferenceFailed) as error:
            runs.append(RunResult(score=0.0, output=None, error=str(error)))
            continue
        runs.append(
            RunResult(score=conflict_score(task, answer, citations), output=answer, error=None)
        )
    return TaskResult(task_id=task.id, prompt=task.prompt, runs=tuple(runs))


async def run_conflict_suite(settings: Settings, suite: Suite) -> SuiteRunReport:
    engine = build_engine(settings)
    factory = session_factory(engine)
    started_at = now()
    try:
        try:
            await _seed_conflict_corpus(factory, settings)
            task_results = [
                await _run_conflict_task(factory, settings, task) for task in suite.tasks
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


def run_conflict_suite_sync(settings: Settings, suite: Suite) -> SuiteRunReport:
    return asyncio.run(run_conflict_suite(settings, suite))
