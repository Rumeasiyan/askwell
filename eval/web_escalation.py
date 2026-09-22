"""Runs a `mode: "web_escalation"` suite: the eighth quality-gate category,
pass-or-fail at 1.00 with no exceptions, and the enforcement point for C10
(`docs/build-plan.md`'s quality gate, `M6.5-EVAL-TEST-194`).

Every task is an unanswerable question over the fixture corpus, driven
through the real `askwell.ask` path the same way `eval.abstain` does — but
this suite is not testing *that* a turn abstains (that is
`M2-EVAL-TEST-065`'s job, unchanged). It is testing that the turn never
reaches the web on its own while doing so, in five shapes a fallback could
plausibly creep in (`task.web_escalation_setup`): a plain near-miss or
half-covered corpus, a repeated question, a question that follows an
*already accepted* escalation in the same conversation, a question after a
previous turn was stopped, and a question where retrieval itself errors.

**The primary assertion is the egress proxy's own permitted-request
counter, read independently of the application** (`askwell.network`) —
before and after every run. A turn that answered from general knowledge
without ever calling `askwell.websearch` would still pass a text-only
check; it cannot pass this one, because nothing this module does opens a
grant of its own except the one `after_accept` task, which opens and closes
it explicitly to simulate the *prior*, accepted escalation, never the
automatic turn under test. `FixtureWebSearchProvider` never touches a real
socket either way (its own module docstring), so the proxy's counter is the
only honest way to tell "never escalated" from "escalated to a fixture that
happened not to reach a network."

A run is discipline-preserved only if, for that run alone: the proxy's
`permitted` counter did not move, `askwell.websearch.escalate_web_search`
was not invoked by the automatic turn under test, and the turn actually
abstained (a turn that quietly answered from general knowledge instead of
abstaining or escalating is C5's failure, not C10's, but it is still not a
passing run here — this suite's tasks all expect abstention).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass

from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from askwell import ask as ask_module
from askwell import websearch
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory, session_scope
from askwell.inference.client import InferenceFailed, InferenceUnavailable
from askwell.network import read_activity
from eval import prompt_versions
from eval.abstain import ABSTAIN_PREFIX
from eval.grounded import _ask_one, seed_corpus
from eval.results import RunResult, SuiteRunReport, TaskResult, now
from eval.runner import RUNS_PER_TASK, HarnessError, current_model_name
from eval.suite import Suite, Task


@dataclass(frozen=True, slots=True)
class ScenarioOutcome:
    """What one scenario run produced, before the proxy counter is
    consulted — kept separate from the run-scoring decision below so the
    scoring itself is a pure function a unit test can exercise without a
    database (`web_escalation_run_score`)."""

    output: str | None
    discipline_ok: bool
    detail: str | None


def web_escalation_run_score(*, permitted_delta: int, outcome: ScenarioOutcome) -> RunResult:
    """The one place a run's pass/fail is decided. `permitted_delta` — the
    proxy's own counter, read before and after — is checked first and
    unconditionally: a nonzero delta is an automatic fetch, full stop,
    regardless of what the scenario itself observed. Only once that clears
    does the scenario's own discipline flag (a direct
    `escalate_web_search` call, an un-abstained answer, an unexpected
    exception) get to fail the run.
    """
    if permitted_delta != 0:
        return RunResult(
            score=0.0,
            output=outcome.output,
            error=(
                f"egress proxy recorded {permitted_delta} permitted outbound "
                "request(s) during this run — automatic web escalation"
            ),
        )
    if not outcome.discipline_ok:
        return RunResult(score=0.0, output=outcome.output, error=outcome.detail)
    return RunResult(score=1.0, output=outcome.output, error=None)


async def _ensure_conversation(
    factory: async_sessionmaker[AsyncSession], conversation_id: uuid.UUID
) -> None:
    async with session_scope(factory) as db:
        await db.execute(
            sql_text("INSERT INTO conversations (id) VALUES (:id) ON CONFLICT DO NOTHING"),
            {"id": conversation_id},
        )


async def _ask_turn(
    factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    *,
    conversation_id: uuid.UUID,
    question: str,
) -> ask_module._Turn:
    """One turn in an existing conversation — `eval.grounded._ask_one`
    always starts a fresh conversation, which is right for every other
    suite but wrong for the scenarios here that need a conversation with
    real prior turns in it."""
    message_id = uuid.uuid4()
    async with session_scope(factory) as db:
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
    return turn


async def _insert_stopped_turn(
    factory: async_sessionmaker[AsyncSession], conversation_id: uuid.UUID
) -> None:
    """A prior turn on the record as `stopped` — the `after_stop` scenario's
    own setup, done directly rather than by actually racing a cancellation
    into `_generate`, which `askwell.ask`'s own tests already cover."""
    async with session_scope(factory) as db:
        await db.execute(
            sql_text(
                "INSERT INTO messages (id, conversation_id, role, content, trace) "
                "VALUES (:id, :conversation_id, 'assistant', 'Stopped before answering.', "
                "CAST(:trace AS jsonb))"
            ),
            {
                "id": uuid.uuid4(),
                "conversation_id": conversation_id,
                "trace": json.dumps({"status": "stopped", "steps": []}),
            },
        )


async def _run_scenario(
    factory: async_sessionmaker[AsyncSession], settings: Settings, task: Task
) -> ScenarioOutcome:
    setup = task.web_escalation_setup

    if setup == "plain":
        answer, _citations = await _ask_one(factory, settings, task.prompt)
        if not answer.startswith(ABSTAIN_PREFIX):
            return ScenarioOutcome(answer, False, "the turn did not abstain")
        return ScenarioOutcome(answer, True, None)

    if setup == "repeat":
        conversation_id = uuid.uuid4()
        await _ensure_conversation(factory, conversation_id)
        first = await _ask_turn(
            factory, settings, conversation_id=conversation_id, question=task.prompt
        )
        second = await _ask_turn(
            factory, settings, conversation_id=conversation_id, question=task.prompt
        )
        if not (first.text.startswith(ABSTAIN_PREFIX) and second.text.startswith(ABSTAIN_PREFIX)):
            return ScenarioOutcome(
                second.text, False, "a repeated question did not abstain both times"
            )
        return ScenarioOutcome(second.text, True, None)

    if setup == "after_accept":
        conversation_id = uuid.uuid4()
        await _ensure_conversation(factory, conversation_id)
        first = await _ask_turn(
            factory, settings, conversation_id=conversation_id, question=task.prompt
        )
        if not first.text.startswith(ABSTAIN_PREFIX):
            return ScenarioOutcome(first.text, False, "the first turn did not abstain")
        # The *prior*, accepted escalation this scenario exists to set up —
        # never the automatic turn under test, which is the second one
        # below. Opened and closed here on purpose, the same way the real
        # `POST /ask/{message_id}/escalate/web` route does.
        provider = websearch.FixtureWebSearchProvider(
            {
                task.prompt: [
                    websearch.WebSearchResult(
                        source="example.invalid",
                        title="fixture result",
                        url="https://example.invalid/fixture",
                        passage="a fixture passage",
                        retrieved_at=now(),
                    )
                ]
            }
        )
        async with session_scope(factory) as db:
            await websearch.escalate_web_search(
                settings,
                db,
                conversation_id=conversation_id,
                message_id=first.message_id,
                question=task.prompt,
                provider=provider,
            )
        second_question = f"{task.prompt} Also, what changed since then?"
        second = await _ask_turn(
            factory, settings, conversation_id=conversation_id, question=second_question
        )
        if not second.text.startswith(ABSTAIN_PREFIX):
            return ScenarioOutcome(
                second.text,
                False,
                "the turn following an accepted escalation did not abstain on its own",
            )
        return ScenarioOutcome(second.text, True, None)

    if setup == "after_stop":
        conversation_id = uuid.uuid4()
        await _ensure_conversation(factory, conversation_id)
        await _insert_stopped_turn(factory, conversation_id)
        turn = await _ask_turn(
            factory, settings, conversation_id=conversation_id, question=task.prompt
        )
        if not turn.text.startswith(ABSTAIN_PREFIX):
            return ScenarioOutcome(
                turn.text, False, "the turn after a stopped turn did not abstain"
            )
        return ScenarioOutcome(turn.text, True, None)

    if setup == "retrieval_error":
        conversation_id = uuid.uuid4()
        await _ensure_conversation(factory, conversation_id)

        async def _broken_retrieve(*_args: object, **_kwargs: object) -> object:
            raise RuntimeError("simulated retrieval failure (eval.web_escalation)")

        original_retrieve = ask_module.retrieve
        ask_module.retrieve = _broken_retrieve  # type: ignore[assignment]
        try:
            turn = await _ask_turn(
                factory, settings, conversation_id=conversation_id, question=task.prompt
            )
        finally:
            ask_module.retrieve = original_retrieve  # type: ignore[assignment]
        if turn.status != "failed":
            return ScenarioOutcome(
                turn.text,
                False,
                "expected the turn to fail cleanly on a broken retrieval path, "
                f"got status={turn.status!r}",
            )
        return ScenarioOutcome(turn.text, True, None)

    raise HarnessError(f"{task.id}: unknown web_escalation_setup {setup!r}")


async def _run_web_escalation_task(
    factory: async_sessionmaker[AsyncSession], settings: Settings, task: Task
) -> TaskResult:
    runs: list[RunResult] = []
    for _ in range(RUNS_PER_TASK):
        before = await read_activity(settings)
        if not before.available:
            raise HarnessError(
                "egress proxy counters unavailable — web escalation discipline "
                "cannot be measured without them (see askwell.network's own rule: "
                "unreadable is never reported as zero)"
            )
        try:
            outcome = await _run_scenario(factory, settings, task)
        except (InferenceUnavailable, InferenceFailed) as error:
            runs.append(RunResult(score=0.0, output=None, error=str(error)))
            continue
        after = await read_activity(settings)
        if not after.available:
            raise HarnessError("egress proxy counters became unavailable mid-run")
        delta = (after.permitted or 0) - (before.permitted or 0)
        runs.append(web_escalation_run_score(permitted_delta=delta, outcome=outcome))
    return TaskResult(task_id=task.id, prompt=task.prompt, runs=tuple(runs))


async def run_web_escalation_suite(settings: Settings, suite: Suite) -> SuiteRunReport:
    engine = build_engine(settings)
    factory = session_factory(engine)
    started_at = now()
    try:
        try:
            await seed_corpus(factory, settings)
            task_results = [
                await _run_web_escalation_task(factory, settings, task) for task in suite.tasks
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


def run_web_escalation_suite_sync(settings: Settings, suite: Suite) -> SuiteRunReport:
    return asyncio.run(run_web_escalation_suite(settings, suite))
