"""Runs a `mode: "memory"` suite: fifteen tasks proving that
`M3-APPLY-BE-079`'s memory retrieval actually changes what a later answer
says — a stored fact applies, a superseded fact stops applying, memory is
cited when it is used, and memory never licenses inventing a claim the
retrieved documents do not support (`M3-EVAL-TEST-086`, C4, C5).

Reuses `eval.grounded`'s `seed_corpus` for the fixture documents. The memory
facts themselves are seeded here, once, through the same write paths the
product exposes rather than a hand-inserted `memory` row:

- **"apply" tasks** go through `askwell.review.answer_clarification` — a
  fixture `clarifications` row is inserted directly (not raised by
  `askwell.clarify`'s own detectors, which have no reason to fire on
  invented "which figure is currently in force" content), but the *answer*
  path from there on is the real one every clarification answer takes.
- **"supersede" tasks** answer the same way, then immediately call
  `askwell.memory.correct_memory_fact` — the same correction a chip or the
  memory screen would call — so the fixture's final state is "corrected
  once", not "written once with the corrected value", matching what the
  ticket's own walkthrough describes ("supersede a fixture fact and confirm
  the supersession tasks now pass").
- **"no_invent"/"irrelevant" tasks** write a free-standing fact directly
  with `askwell.memory.write_memory_fact(origin="manual")`, the same
  function `askwell.memory.add_manual_fact` calls for a fact volunteered
  before being asked.

Idempotent: every seed checks whether its subject already has a `memory`
row (active or superseded) and skips if so — the same guard
`eval.grounded.seed_corpus`'s `_ensure_root` uses for the corpus, so a
second run against a database that already has this fixture leaves it
untouched rather than layering a second, redundant correction on top.
"""

import asyncio
import json
import uuid

from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from askwell import ask as ask_module
from askwell import memory, review
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory, session_scope
from askwell.inference.client import InferenceFailed, InferenceUnavailable
from eval import prompt_versions
from eval.abstain import ABSTAIN_PREFIX, SEARCH_EVIDENCE
from eval.grounded import seed_corpus
from eval.results import RunResult, SuiteRunReport, TaskResult, now
from eval.runner import RUNS_PER_TASK, HarnessError, current_model_name
from eval.suite import Suite, Task

# --- fixture facts, seeded once per database -------------------------------
#
# Every value here is deliberately drawn from `eval/fixtures/generate_corpus.py`'s
# `CONFLICT_2025_PAGES`/`CONFLICT_2026_PAGES` — two documents that stay live and
# genuinely disagree, exactly `conflicting_sources.v1.json`'s own fixtures.
# A memory fact naming which year is "currently in force" is the documented
# resolution path (`agent/prompts/conflicting_sources.v1.md`'s "When a memory
# fact resolves the conflict"), not an invented mechanism for this suite.

# (subject, clarification question, answer written to memory)
_APPLY_SEEDS: tuple[tuple[str, str, str], ...] = (
    (
        "return-window-policy",
        "Which return-window figure is currently in force — the March 2025 or "
        "the January 2026 one?",
        "Meridian Loom's current, in-force return window is the January 2026 "
        "figure of forty-five days; the March 2025 figure of thirty days is "
        "out of date.",
    ),
    (
        "shipping-fee-policy",
        "Which express shipping fee is currently in force — the March 2025 or "
        "the January 2026 one?",
        "Meridian Loom's current express shipping fee is the January 2026 "
        "figure of eighteen dollars per order; the twelve-dollar 2025 figure "
        "no longer applies.",
    ),
    (
        "loyalty-points-policy",
        "Which loyalty-point rate is currently in force?",
        "Meridian Loom's current loyalty program awards one point per eight "
        "dollars spent (January 2026); the one-point-per-ten-dollars 2025 "
        "rate no longer applies.",
    ),
    (
        "trade-in-credit-policy",
        "Which trade-in credit figure is currently in force?",
        "Meridian Loom's current maximum trade-in credit for a Loomwear "
        "Sensor is seventy-five dollars (January 2026); the fifty-dollar "
        "2025 figure no longer applies.",
    ),
    (
        "support-response-policy",
        "Which support first-response commitment is currently in force?",
        "Meridian Loom's current customer support first-response commitment "
        "is twelve hours (January 2026); the twenty-four-hour 2025 "
        "commitment no longer applies.",
    ),
)

# (subject, clarification question, initial answer, corrected answer)
_SUPERSEDE_SEEDS: tuple[tuple[str, str, str, str], ...] = (
    (
        "affiliate-rate-policy",
        "What is Meridian Loom's affiliate commission rate?",
        "Meridian Loom's affiliate commission rate is currently eight percent (March 2025).",
        "Meridian Loom's affiliate commission rate is currently eleven "
        "percent (January 2026); this supersedes the eight percent figure.",
    ),
    (
        "restock-day-policy",
        "Which day does Meridian Loom restock warehouse inventory?",
        "Meridian Loom currently restocks warehouse inventory every Tuesday (March 2025).",
        "Meridian Loom currently restocks warehouse inventory every "
        "Thursday (January 2026); this supersedes the Tuesday schedule.",
    ),
    (
        "warranty-cost-policy",
        "How much does Meridian Loom's extended warranty cost annually?",
        "Meridian Loom's extended warranty currently costs thirty dollars annually (March 2025).",
        "Meridian Loom's extended warranty currently costs forty-five "
        "dollars annually (January 2026); this supersedes the thirty-dollar "
        "figure.",
    ),
)

# (subject, fact) — topically close to a near-miss abstention question but
# never supplying the missing figure itself, or plainly unrelated to the
# grounded question it sits beside. Neither kind should ever change an
# answer; that is the point of both.
_MANUAL_SEEDS: tuple[tuple[str, str], ...] = (
    (
        "termination-notice-context",
        "Termination notices at Meridian Loom must be delivered in writing "
        "by HR, per internal practice.",
    ),
    (
        "sick-day-context",
        "Sick day balances at Meridian Loom reset every January 1st.",
    ),
    (
        "q2-revenue-context",
        "Revenue figures at Meridian Loom are compiled quarterly by the Finance team.",
    ),
    (
        "guest-vpn-context",
        "Guest accounts at Meridian Loom are provisioned by IT on a case-by-case basis.",
    ),
    (
        "unrelated-fact-1",
        "Meridian Loom's headquarters break room coffee machine is serviced every Friday.",
    ),
    (
        "unrelated-fact-2",
        "Meridian Loom's marketing team calls itself 'Loomcraft' internally.",
    ),
    (
        "unrelated-fact-3",
        "Meridian Loom sponsors a biweekly team lunch on Fridays.",
    ),
)


async def _has_active_or_superseded(db: AsyncSession, subject: str) -> bool:
    result = await db.execute(
        sql_text("SELECT 1 FROM memory WHERE subject = :subject LIMIT 1"), {"subject": subject}
    )
    return result.first() is not None


async def _any_source_id(db: AsyncSession) -> uuid.UUID:
    result = await db.execute(sql_text("SELECT id FROM sources ORDER BY added_at LIMIT 1"))
    row = result.first()
    if row is None:
        raise HarnessError("no source found after seeding the fixture corpus")
    return row[0]


async def _seed_via_clarification(
    db: AsyncSession, *, source_id: uuid.UUID, subject: str, question: str, answer: str
) -> uuid.UUID | None:
    """Insert a fixture `clarifications` row and answer it through the real
    `answer_clarification` path. Returns the new `memory` row's id, or
    `None` if this subject was already seeded by an earlier run."""
    if await _has_active_or_superseded(db, subject):
        return None
    clarification_id = uuid.uuid4()
    await db.execute(
        sql_text(
            "INSERT INTO clarifications (id, source_id, subject, question, status) "
            "VALUES (:id, :source_id, :subject, :question, 'pending')"
        ),
        {"id": clarification_id, "source_id": source_id, "subject": subject, "question": question},
    )
    outcome = await review.answer_clarification(db, clarification_id, answer)
    return outcome.memory_id


async def seed_memory_fixture(
    factory: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    await seed_corpus(factory, settings)
    async with session_scope(factory) as db:
        source_id = await _any_source_id(db)

        for subject, question, answer in _APPLY_SEEDS:
            await _seed_via_clarification(
                db, source_id=source_id, subject=subject, question=question, answer=answer
            )

        for subject, question, initial_answer, corrected_answer in _SUPERSEDE_SEEDS:
            memory_id = await _seed_via_clarification(
                db,
                source_id=source_id,
                subject=subject,
                question=question,
                answer=initial_answer,
            )
            if memory_id is not None:
                await memory.correct_memory_fact(db, fact_id=memory_id, fact=corrected_answer)

        for subject, fact in _MANUAL_SEEDS:
            if not await _has_active_or_superseded(db, subject):
                await memory.write_memory_fact(db, subject=subject, fact=fact, origin="manual")


async def _ask_one(
    factory: async_sessionmaker[AsyncSession], settings: Settings, question: str
) -> tuple[str, list[dict[str, object]]]:
    """`eval.grounded._ask_one`'s twin, collecting `fact_citation` events
    instead of `citation` ones — this suite scores whether a memory fact
    was cited, not whether a document passage was."""
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

    fact_citations = [event.data for event in turn.events if event.kind == "fact_citation"]
    return turn.text, fact_citations


def memory_score(
    task: Task, answer: str, fact_citations: list[dict[str, object]]
) -> tuple[float, str | None]:
    """1.0 iff the task's behaviour held, else 0.0 with a diagnostic naming
    *which* rule broke — the ticket's own "scored as a failure distinct
    from a general application failure, so the cause is legible" — rather
    than one undifferentiated fail.

    - `"no_invent"`: must abstain exactly as `eval.abstain.abstain_score`
      checks (memory never licenses inventing an unsupported claim, C5).
    - `"irrelevant"`: must answer the grounded question correctly, unmoved
      by an unrelated fact sitting in memory alongside it.
    - `"apply"`/`"supersede"`: must state the current value (`contains`).
      Failing that, `not_contains` (the superseded value) present marks it
      `superseded_fact_still_applied` — the fact never stopped applying —
      distinct from `no_application`, where neither value appears at all.
      Stating the current value with no citation of the memory fact that
      supplied it is `not_cited` — C4's "every factual claim carries a
      citation" applied to memory the same way it applies to a document.
    """
    expected = task.expected
    if not isinstance(expected, dict):
        raise ValueError(f"task {task.id!r}: 'expected' must be an object, got {expected!r}")
    kind = expected.get("kind")
    lowered = answer.lower()

    if kind == "no_invent":
        if not answer.startswith(ABSTAIN_PREFIX):
            return 0.0, "invented_content"
        return (1.0, None) if SEARCH_EVIDENCE in answer else (0.0, "abstained_without_proof")

    contains = [str(needle) for needle in expected.get("contains", [])]
    contains_current = all(needle.lower() in lowered for needle in contains)

    if kind == "irrelevant":
        return (1.0, None) if contains_current else (0.0, "grounded_answer_disrupted")

    if kind not in ("apply", "supersede"):
        raise ValueError(f"task {task.id!r}: unknown memory task kind {kind!r}")

    if not contains_current:
        not_contains = [str(needle) for needle in expected.get("not_contains", [])]
        if any(needle.lower() in lowered for needle in not_contains):
            return 0.0, "superseded_fact_still_applied"
        return 0.0, "no_application"

    memory_subject = expected.get("memory_subject")
    cited_subjects = {
        citation.get("subject")
        for citation in fact_citations
        if citation.get("fact_kind") == "memory"
    }
    if memory_subject not in cited_subjects:
        return 0.0, "not_cited"
    return 1.0, None


async def _run_memory_task(
    factory: async_sessionmaker[AsyncSession], settings: Settings, task: Task
) -> TaskResult:
    runs: list[RunResult] = []
    for _ in range(RUNS_PER_TASK):
        try:
            answer, fact_citations = await _ask_one(factory, settings, task.prompt)
        except (InferenceUnavailable, InferenceFailed) as error:
            runs.append(RunResult(score=0.0, output=None, error=str(error)))
            continue
        score, diagnostic = memory_score(task, answer, fact_citations)
        runs.append(RunResult(score=score, output=answer, error=diagnostic))
    return TaskResult(task_id=task.id, prompt=task.prompt, runs=tuple(runs))


async def run_memory_suite(settings: Settings, suite: Suite) -> SuiteRunReport:
    engine = build_engine(settings)
    factory = session_factory(engine)
    started_at = now()
    try:
        try:
            await seed_memory_fixture(factory, settings)
            task_results = [await _run_memory_task(factory, settings, task) for task in suite.tasks]
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


def run_memory_suite_sync(settings: Settings, suite: Suite) -> SuiteRunReport:
    return asyncio.run(run_memory_suite(settings, suite))
