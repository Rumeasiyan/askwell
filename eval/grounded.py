"""Runs a `mode: "grounded"` suite: seeds the fixture corpus through the real
add -> ingest pipeline once, then drives one turn of `askwell.ask`'s real
retrieve-and-cite path per task, scored on both the answer text and the
passage it cited.

`eval.runner` calls `InferenceClient.generate()` directly — one isolated
completion, no retrieval, no citations. That is right for a suite that grades
raw model output, but "Citation correctness is scored, not only answer text"
(`M2-EVAL-TEST-064`'s acceptance criteria) needs the retrieval and citation
machinery in `askwell.ask` itself, so this module drives that instead.

Reuses `askwell.ask`'s private `_Turn`/`_generate` the same way
`api/tests/test_ask_api.py` already does — there is no public,
non-streaming "ask and get the answer back" function, and adding one only
for this harness would be a second answer path to keep in sync with the
real one.
"""

import asyncio
import json
import uuid
from pathlib import Path

from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from askwell import ask as ask_module
from askwell import ingest
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory, session_scope
from askwell.inference.client import InferenceFailed, InferenceUnavailable
from askwell.sources import Outcome
from askwell.sources import add as add_source
from eval import prompt_versions
from eval.results import RunResult, SuiteRunReport, TaskResult, now
from eval.runner import RUNS_PER_TASK, HarnessError, current_model_name
from eval.scoring import score
from eval.suite import Suite, Task

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "corpus"


async def _ensure_root(db: AsyncSession, path: str) -> None:
    """Same effect as `roots.active()` + an insert, without a duplicate-key
    error on a second run against a development database that already has
    this root — `roots.path` is only unique while `removed_at IS NULL`, so a
    plain `ON CONFLICT DO NOTHING` needs a matching partial index and adds
    nothing a plain existence check does not already give here."""
    existing = await db.execute(
        sql_text("SELECT 1 FROM roots WHERE path = :path AND removed_at IS NULL"),
        {"path": path},
    )
    if existing.first() is None:
        await db.execute(sql_text("INSERT INTO roots (path) VALUES (:path)"), {"path": path})


async def seed_corpus(factory: async_sessionmaker[AsyncSession], settings: Settings) -> None:
    """Index every file in `eval/fixtures/corpus/` through the real `add()`
    -> `ingest.process()` path — the ticket's own "index the fixture corpus
    through the normal add flow rather than a shortcut" walkthrough. A
    hand-seeded `chunks` row would test the scoring code, not grounding.

    Safe to call against a database that already has this corpus indexed:
    files already recorded come back `DUPLICATE` and are left alone.
    """
    filenames = sorted(p.name for p in FIXTURES_DIR.iterdir() if p.is_file())
    if not filenames:
        raise HarnessError(
            f"no fixture corpus at {FIXTURES_DIR} — run "
            "eval/fixtures/generate_corpus.py to build it"
        )

    async with session_scope(factory) as db:
        await _ensure_root(db, str(FIXTURES_DIR))
        result = await add_source(db, str(FIXTURES_DIR), filenames)

    for file in result.files:
        if file.outcome == Outcome.ADDED:
            if file.document_id is None:  # pragma: no cover - add()'s own invariant
                raise HarnessError(f"fixture {file.relative_path} was added with no document id")
            outcome = await ingest.process(factory, settings, file.document_id)
            if outcome != "done":
                raise HarnessError(f"fixture {file.relative_path} failed to ingest: {outcome}")
        elif file.outcome == Outcome.DUPLICATE:
            continue
        else:
            raise HarnessError(
                f"fixture {file.relative_path}: unexpected add() outcome {file.outcome!r} "
                f"({file.reason})"
            )


async def _ask_one(
    factory: async_sessionmaker[AsyncSession], settings: Settings, question: str
) -> tuple[str, list[dict[str, object]]]:
    """One turn, start to finish, against the fixture corpus — the same
    conversation/message bookkeeping `POST /ask` does before handing off to
    `_generate` (`askwell/ask.py`'s own handler), minus the streaming
    response nothing here reads."""
    conversation_id = uuid.uuid4()
    message_id = uuid.uuid4()
    async with session_scope(factory) as db:
        await db.execute(
            sql_text("INSERT INTO conversations (id) VALUES (:id)"), {"id": conversation_id}
        )
        await db.execute(
            sql_text(
                "INSERT INTO messages (id, conversation_id, role, content, trace) "
                "VALUES (:id, :conversation_id, 'assistant', '', CAST(:trace AS jsonb))"
            ),
            {
                "id": message_id,
                "conversation_id": conversation_id,
                "trace": json.dumps({"status": "running", "steps": []}),
            },
        )

    turn = ask_module._Turn(message_id=message_id, conversation_id=conversation_id)
    await ask_module._generate(settings, factory, turn, question, None)

    citations = [event.data for event in turn.events if event.kind == "citation"]
    return turn.text, citations


def _citation_score(task: Task, citations: list[dict[str, object]]) -> float:
    """1.0 if any citation the turn emitted names one of the task's expected
    documents and quotes one of its expected passages, else 0.0. Checked
    against every citation the turn produced, not only the first — a claim
    can cite more than one passage, and the right one need not be first
    (`ask.py`'s `_cite_claim`, one citation event per `[n]` a claim named)."""
    for citation in citations:
        filename = str(citation.get("filename") or "")
        passage = str(citation.get("passage") or "").lower()
        if filename in task.expected_documents and any(
            needle.lower() in passage for needle in task.expected_passages
        ):
            return 1.0
    return 0.0


async def _run_grounded_task(
    factory: async_sessionmaker[AsyncSession], settings: Settings, task: Task
) -> TaskResult:
    runs: list[RunResult] = []
    for _ in range(RUNS_PER_TASK):
        try:
            answer, citations = await _ask_one(factory, settings, task.prompt)
        except (InferenceUnavailable, InferenceFailed) as error:
            runs.append(RunResult(score=0.0, output=None, error=str(error)))
            continue
        try:
            answer_score = score(task.scorer, answer, task.expected)
        except ValueError as error:
            runs.append(RunResult(score=0.0, output=answer, error=str(error)))
            continue
        # Weighted evenly: a fluent answer citing the wrong passage and a
        # correct passage cited for a wrong answer are both half-grounded,
        # not a pass — the ticket's own "scored on both" requirement.
        combined = 0.5 * answer_score + 0.5 * _citation_score(task, citations)
        runs.append(RunResult(score=combined, output=answer, error=None))
    return TaskResult(task_id=task.id, prompt=task.prompt, runs=tuple(runs))


async def run_grounded_suite(settings: Settings, suite: Suite) -> SuiteRunReport:
    engine = build_engine(settings)
    factory = session_factory(engine)
    started_at = now()
    try:
        try:
            await seed_corpus(factory, settings)
            task_results = [
                await _run_grounded_task(factory, settings, task) for task in suite.tasks
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


def run_grounded_suite_sync(settings: Settings, suite: Suite) -> SuiteRunReport:
    return asyncio.run(run_grounded_suite(settings, suite))
