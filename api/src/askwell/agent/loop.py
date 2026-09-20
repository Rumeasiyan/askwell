"""The multi-step tool loop. `M5-LOOP-BE-115`.

`askwell.agent.tools` built a registry nothing calls more than once per turn.
This is the caller: it asks the model what to do, calls whichever tools it
names — **all of them at once when the model names more than one in the same
turn**, since none of the five tools write anything (`askwell.agent.tools`'s
own module docstring), so nothing is lost running independent lookups
concurrently rather than one after another — feeds every result back, and
asks again, until the model says it has enough or a call it makes it can't
(`_SAFETY_MAX_ITERATIONS`, see below).

**The model gets no persistent chat state.** `InferenceClient` only exposes a
single-shot `/completion`, the same constraint `askwell.agent.sql_generate`
and `askwell.agent.compose` already build around, so the whole
`<tool-result>` history is replayed into the prompt fresh on every
iteration rather than a message list growing turn over turn.

**A duplicate call — same tool, same arguments, seen earlier in this loop —
is never re-executed.** Its previous result is reused and the step records
`deduplicated=True` rather than running it again: a database call already
went through `askwell.sql.validate` once, and running it twice teaches
nothing new while doubling the wait.

**`_SAFETY_MAX_ITERATIONS` is a crash guard, not the product's call
ceiling.** `CALL_CEILING` (`M5-LOOP-BE-116`) is the ceiling a user actually
sees — 8 tool calls per turn, `docs/architecture.md` §10 — and it is what
stops an ordinary turn long before `_SAFETY_MAX_ITERATIONS` (25) would.
`_SAFETY_MAX_ITERATIONS` stays only as a guard against a turn that keeps
re-asking for calls it already has cached (every one deduplicated, so
`CALL_CEILING` is never actually reached) rather than ever answering.

**Reaching `CALL_CEILING` never presents a partial result as complete.**
The turn stops, composes what it gathered into an answer if anything useful
was gathered at all (never invented from nothing — closer to abstention
otherwise), and always says plainly that it stopped early and why
(`_CEILING_NOTE`/`_NOTHING_GATHERED_TEXT`, never omitted). A parallel batch
that would cross the ceiling is truncated at it; the calls that were cut are
recorded as `LoopResult.pending_calls` — what the turn was about to do
(`docs/ux/trace.md` §5) — rather than silently dropped. `LoopResult.
continuation`, present only on a turn's first ceiling stop, is what
`askwell.ask` persists so a **Continue** click can start a new turn that
picks up the gathered `<tool-result>` history rather than re-fetching it; a
second stop in the same chain narrows the answer's own text instead of
offering a third continuation, so there is no infinite chain.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from askwell.agent.compose import delimit_tool_result
from askwell.agent.tools import TOOLS, ToolError, ToolResult, ToolStep, call_tool
from askwell.config import Settings
from askwell.inference.client import InferenceClient
from askwell.logging import get_logger

log = get_logger(__name__)

PROMPT_DIR = Path(__file__).parent / "prompts"
PROMPT_VERSION = "tool_loop.v1"
PROMPT_PATH = PROMPT_DIR / f"{PROMPT_VERSION}.md"

# A crash guard, not the product's ceiling — see the module docstring.
_SAFETY_MAX_ITERATIONS = 25

# The product's own ceiling. `M5-LOOP-BE-116`, `docs/architecture.md` §10:
# fixed in v1, raising it is a recorded decision, not a config knob.
CALL_CEILING = 8

LOOP_MAX_TOKENS = 700
LOOP_TEMPERATURE = 0.0

_CEILING_NOTICE = (
    "\n\nYou have reached the maximum of 8 tool calls for this question. No "
    "further tool calls will be run. Answer now using only the tool results "
    "already gathered above; if they are not enough to fully answer, say so "
    "and name what you would still need to check."
)

# Appended to whatever the model composed at the ceiling — never relied on
# the model to say this itself, since a stopped-early answer must never omit
# the note (this ticket's own Validation Rule).
_CEILING_NOTE = (
    " Askwell stopped after reaching its 8-step limit for this question — "
    "this is what it found before then, not a complete answer."
)

# The ceiling reached with nothing useful gathered at all — the named edge
# case that is "closer to abstention" than a composed answer would be.
_NOTHING_GATHERED_TEXT = (
    "Askwell reached its 8-step limit for this question without finding "
    "anything useful to answer from. Try narrowing the question, or check "
    "that the right sources are connected."
)

# A second stop in the same continuation chain — told plainly rather than
# offering a third continuation and risking an endless one.
_NARROW_AGAIN_NOTE = (
    " This question has now stopped twice without finishing — it may need narrowing."
)


@lru_cache(maxsize=1)
def _load_system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def _describe_tool(name: str) -> str:
    tool = TOOLS[name]
    fields = tool.args_model.model_fields
    if not fields:
        args_desc = "no arguments"
    else:
        parts = []
        for field_name, info in fields.items():
            required = info.is_required()
            parts.append(f"{field_name}{'' if required else ' (optional)'}")
        args_desc = "arguments: " + ", ".join(parts)
    return f"- {name}: {tool.description} ({args_desc})"


def _tool_catalogue() -> str:
    lines = "\n".join(_describe_tool(name) for name in TOOLS)
    return f"<tools>\n{lines}\n</tools>"


@dataclass(frozen=True, slots=True)
class ToolCallEvent:
    """One call's start or end, `M5-LOOP-BE-117a`. `call_id` is the same
    dedup key `_call_key` already computes — stable per distinct
    `(tool, arguments)` pair within a turn, which is what "identify which
    call it belongs to" (this ticket's own Validation Rule) needs; nothing
    new is invented to name it. `outcome` is `None` on `start` (nothing has
    run yet) and the tool's real outcome (`"ok"` or an error code) on `end`.
    """

    phase: Literal["start", "end"]
    tool: str
    call_id: str
    arguments: dict[str, Any]
    outcome: str | None = None


ToolCallObserver = Callable[[ToolCallEvent], None]


def _notify(observer: ToolCallObserver | None, event: ToolCallEvent) -> None:
    """Fire the observer, if one was given, isolated from the loop it is
    watching — same posture as `askwell.traces.TraceRing.write`: an
    observer is a caller's own concern, and a broken one is not a reason to
    fail the turn it is merely watching.
    """
    if observer is None:
        return
    try:
        observer(event)
    except Exception as error:
        log.warning(
            "tool_call_observer_failed",
            phase=event.phase,
            tool=event.tool,
            call_id=event.call_id,
            error=str(error),
        )


@dataclass(frozen=True, slots=True)
class LoopStep:
    """One iteration's worth of one tool call, trace-shaped
    (`docs/ux/trace.md` §2) — `as_dict()` is what `askwell.ask` appends to
    `trace_steps` directly, the same list `_run_sql_turn`'s own
    `trace_step` already joins.
    """

    kind: str
    tool: str
    arguments: dict[str, Any]
    duration_ms: int
    outcome: str
    truncated: bool
    detail: dict[str, Any]
    injection_flagged: bool
    injection_patterns: tuple[str, ...]
    iteration: int
    deduplicated: bool
    started_offset_ms: int
    result_index: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "tool": self.tool,
            "arguments": self.arguments,
            "duration_ms": self.duration_ms,
            "outcome": self.outcome,
            "truncated": self.truncated,
            "detail": self.detail,
            "injection_flagged": self.injection_flagged,
            "injection_patterns": list(self.injection_patterns),
            "iteration": self.iteration,
            "deduplicated": self.deduplicated,
            "started_offset_ms": self.started_offset_ms,
            "result_index": self.result_index,
        }


@dataclass(frozen=True, slots=True)
class LoopContinuation:
    """What a **Continue** click (`M5-LOOP-BE-116`, `docs/ux/ask.md` §5)
    needs to start a new turn that picks up from a ceiling stop rather than
    repeating the same calls. Present on `LoopResult.continuation` only for
    a turn's *first* ceiling stop — a second stop in the same chain narrows
    the answer's text instead, so there is nothing to offer a third time.

    Persisted verbatim into `messages.trace.loop_continuation` by
    `askwell.ask` and read back into `run_tool_loop(resume=...)` on the
    follow-up turn. Deliberately just the `<tool-result>` history and the
    next index to hand out — cross-turn tool-call dedup is not attempted:
    seeding `history_blocks` back into the prompt already gives the model
    every result it needs without asking again, and reconstructing the
    dedup cache itself would mean persisting each tool's raw content a
    second time for no benefit over the model simply not re-asking.
    """

    history_blocks: tuple[str, ...]
    next_result_index: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "history_blocks": list(self.history_blocks),
            "next_result_index": self.next_result_index,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LoopContinuation:
        return cls(
            history_blocks=tuple(str(block) for block in data.get("history_blocks", [])),
            next_result_index=int(data.get("next_result_index", 1)),
        )


@dataclass(frozen=True, slots=True)
class LoopResult:
    """What one turn's worth of looping produced.

    `stopped_reason` is `"answered"` for the ordinary case (the model said
    it had enough), `"malformed_response"` when the model's output could not
    be parsed as either action and was used verbatim as the answer instead
    (never a crash — the same "answer it, don't crash it" posture
    `askwell.ask._run_sql_turn`'s own docstring names), `"tool_ceiling"`
    when `CALL_CEILING` (8, `M5-LOOP-BE-116`) was reached before the model
    answered, or `"safety_limit"` when `_SAFETY_MAX_ITERATIONS` was reached
    with no answer yet — unreachable in ordinary operation now that the
    ceiling stops a turn first, and kept only as the crash guard the module
    docstring describes.

    `pending_calls` is what the turn was about to do when the ceiling cut it
    off (`docs/ux/trace.md` §5) — empty on every other `stopped_reason`.
    `continuation` carries what a **Continue** click needs, and is `None`
    unless this is a turn's first ceiling stop.
    """

    text: str
    steps: tuple[LoopStep, ...]
    iterations: int
    stopped_reason: str
    tool_names_called: tuple[str, ...]
    pending_calls: tuple[dict[str, Any], ...] = ()
    continuation: LoopContinuation | None = None
    continuation_count: int = 0


@dataclass(slots=True)
class _CallRecord:
    step: LoopStep
    result_content_json: str


def _call_key(tool_name: str, arguments: dict[str, Any]) -> str:
    return f"{tool_name}:{json.dumps(arguments, sort_keys=True, default=str)}"


def _parse_model_response(raw: str) -> dict[str, Any] | None:
    """The model's one JSON object, or `None` if it isn't one — never raises.
    A code fence a small local model reaches for anyway despite being told
    not to (`docs/decisions.md`'s recurring finding, same as
    `askwell.agent.sql_generate._extract_query`) is stripped before parsing.
    """
    stripped = raw.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:]
        stripped = stripped.strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return cast(dict[str, Any], parsed)


def _valid_calls(parsed: dict[str, Any]) -> list[tuple[str, dict[str, Any]]] | None:
    calls = parsed.get("calls")
    if not isinstance(calls, list) or not calls:
        return None
    out: list[tuple[str, dict[str, Any]]] = []
    for entry in calls:
        if not isinstance(entry, dict):
            continue
        tool_name = entry.get("tool")
        arguments = entry.get("arguments", {})
        if not isinstance(tool_name, str) or not isinstance(arguments, dict):
            continue
        out.append((tool_name, arguments))
    return out or None


async def _stop_at_ceiling(
    *,
    client: InferenceClient,
    system_prompt: str,
    catalogue: str,
    question: str,
    resume_note: str,
    history_blocks: list[str],
    steps: list[LoopStep],
    tool_names_called: list[str],
    iteration: int,
    pending_calls: tuple[dict[str, Any], ...],
    continuation_count: int,
    next_result_index: int,
) -> LoopResult:
    """`CALL_CEILING` was reached this iteration — compose what to hand
    back rather than ever presenting it as complete (module docstring).

    Only asks the model for one more turn when there is actually something
    to compose from (`has_gathered`): a ceiling hit with nothing useful
    gathered composes to nothing worth having, so it is told plainly
    instead — closer to abstention than an invented answer, the ticket's own
    named edge case. When `pending_calls` was not already known from a
    truncated batch, this last call also doubles as how "what it was about
    to do" (`docs/ux/trace.md` §5) gets captured for the exact-fit case: the
    model, told no more tools are available, may ask for one anyway.
    """
    has_gathered = any(step.outcome == "ok" for step in steps)
    if has_gathered:
        history = "\n\n".join(history_blocks)
        user_content = (
            f"{catalogue}\n\nQuestion: {question}"
            + (f"\n\n{history}" if history else "")
            + resume_note
            + _CEILING_NOTICE
        )
        prompt = f"{system_prompt}\n\n{user_content}"
        completion = await client.generate(
            prompt, max_tokens=LOOP_MAX_TOKENS, temperature=LOOP_TEMPERATURE
        )
        parsed = _parse_model_response(completion.text)
        model_text: str | None = None
        if parsed is not None and parsed.get("type") == "answer":
            candidate_text = parsed.get("text")
            if isinstance(candidate_text, str) and candidate_text.strip():
                model_text = candidate_text
        if model_text is None and not pending_calls and parsed is not None:
            calls = _valid_calls(parsed) if parsed.get("type") == "tool_calls" else None
            if calls:
                unique: dict[str, dict[str, Any]] = {}
                for tool_name, arguments in calls:
                    unique.setdefault(
                        _call_key(tool_name, arguments),
                        {"tool": tool_name, "arguments": arguments},
                    )
                pending_calls = tuple(unique.values())
        text = (model_text or "Here is what Askwell found before stopping.") + _CEILING_NOTE
    else:
        text = _NOTHING_GATHERED_TEXT

    if continuation_count >= 1:
        # Already a continuation of an earlier stop — no third continuation,
        # named plainly instead (module docstring).
        text += _NARROW_AGAIN_NOTE
        continuation = None
    else:
        continuation = LoopContinuation(
            history_blocks=tuple(history_blocks), next_result_index=next_result_index
        )

    return LoopResult(
        text=text,
        steps=tuple(steps),
        iterations=iteration,
        stopped_reason="tool_ceiling",
        tool_names_called=tuple(tool_names_called),
        pending_calls=pending_calls,
        continuation=continuation,
        continuation_count=continuation_count,
    )


async def run_tool_loop(
    session: AsyncSession,
    settings: Settings,
    client: InferenceClient,
    *,
    question: str,
    source_id: UUID | None = None,
    resume: LoopContinuation | None = None,
    continuation_count: int = 0,
    on_tool_call: ToolCallObserver | None = None,
) -> LoopResult:
    """Call tools, read results, decide whether more is needed, then answer.

    Every iteration replays the full history of `<tool-result>` blocks
    gathered so far into a fresh prompt (see the module docstring) and asks
    the model for its next JSON action. Independently emitted calls in one
    iteration run concurrently via `asyncio.gather`, deduplicated first —
    a duplicate reuses the earlier result rather than calling the tool
    again, recorded as such.

    `resume` (`M5-LOOP-BE-116`) seeds a fresh turn's history from an earlier
    turn's ceiling stop — a **Continue** click — so this turn's own
    `CALL_CEILING` starts counting from zero rather than inheriting the
    stopped turn's count; the point of a new turn is a fresh budget, not a
    shared one. `continuation_count` is how many stops already led to this
    turn, `0` for an original question.

    `on_tool_call` (`M5-LOOP-BE-117a`) fires once per call actually
    dispatched — never for a deduplicated one, which never runs — with a
    `"start"` event immediately before it and a `"end"` event immediately
    after. A parallel batch's `"start"` events are all fired, synchronously,
    before any of that batch is awaited, so they are always seen before any
    of the batch's `"end"` events — observed per call, not reconstructed
    from the batch finishing. `None` (the default) changes nothing about
    the loop's own behaviour.
    """
    loop_started = time.monotonic()
    system_prompt = _load_system_prompt()
    catalogue = _tool_catalogue()

    history_blocks: list[str] = list(resume.history_blocks) if resume is not None else []
    records: dict[str, _CallRecord] = {}
    steps: list[LoopStep] = []
    tool_names_called: list[str] = []
    next_result_index = resume.next_result_index if resume is not None else 1
    total_calls_made = 0
    resume_note = (
        "\n\nThis continues an earlier turn on the same question that stopped after "
        "reaching its 8-call limit. The tool results it already gathered are included "
        "above — do not repeat a call whose result you already have."
        if resume is not None
        else ""
    )

    for iteration in range(1, _SAFETY_MAX_ITERATIONS + 1):
        if total_calls_made >= CALL_CEILING:
            return await _stop_at_ceiling(
                client=client,
                system_prompt=system_prompt,
                catalogue=catalogue,
                question=question,
                resume_note=resume_note,
                history_blocks=history_blocks,
                steps=steps,
                tool_names_called=tool_names_called,
                iteration=iteration,
                pending_calls=(),
                continuation_count=continuation_count,
                next_result_index=next_result_index,
            )

        history = "\n\n".join(history_blocks)
        user_content = (
            f"{catalogue}\n\nQuestion: {question}"
            + (f"\n\n{history}" if history else "")
            + resume_note
        )
        prompt = f"{system_prompt}\n\n{user_content}"
        completion = await client.generate(
            prompt, max_tokens=LOOP_MAX_TOKENS, temperature=LOOP_TEMPERATURE
        )

        parsed = _parse_model_response(completion.text)
        if parsed is None:
            return LoopResult(
                text=completion.text.strip(),
                steps=tuple(steps),
                iterations=iteration,
                stopped_reason="malformed_response",
                tool_names_called=tuple(tool_names_called),
                continuation_count=continuation_count,
            )

        if parsed.get("type") == "answer":
            answer_text = parsed.get("text")
            if not isinstance(answer_text, str) or not answer_text.strip():
                return LoopResult(
                    text=completion.text.strip(),
                    steps=tuple(steps),
                    iterations=iteration,
                    stopped_reason="malformed_response",
                    tool_names_called=tuple(tool_names_called),
                    continuation_count=continuation_count,
                )
            return LoopResult(
                text=answer_text,
                steps=tuple(steps),
                iterations=iteration,
                stopped_reason="answered",
                tool_names_called=tuple(tool_names_called),
                continuation_count=continuation_count,
            )

        calls = _valid_calls(parsed) if parsed.get("type") == "tool_calls" else None
        if calls is None:
            return LoopResult(
                text=completion.text.strip(),
                steps=tuple(steps),
                iterations=iteration,
                stopped_reason="malformed_response",
                tool_names_called=tuple(tool_names_called),
                continuation_count=continuation_count,
            )

        # Every call the model emitted this iteration, verbatim — a repeat
        # within the same iteration is recorded exactly like a repeat of a
        # call from an earlier one, so nothing here drops it before it can
        # be recorded as a duplicate.
        to_run: list[tuple[str, dict[str, Any], str]] = [
            (tool_name, arguments, _call_key(tool_name, arguments))
            for tool_name, arguments in calls
        ]

        async def _run_one(
            tool_name: str, tool_arguments: dict[str, Any], call_id: str
        ) -> tuple[ToolResult, ToolStep]:
            result, tool_step = await call_tool(
                tool_name, tool_arguments, session=session, settings=settings, client=client
            )
            _notify(
                on_tool_call,
                ToolCallEvent(
                    phase="end",
                    tool=tool_name,
                    call_id=call_id,
                    arguments=tool_arguments,
                    outcome=tool_step.outcome,
                ),
            )
            return result, tool_step

        # Only the first occurrence of each distinct key this iteration is
        # actually dispatched — a key already in `records` (an earlier
        # iteration) or repeated later in `to_run` (this same iteration) is
        # never executed a second time.
        seen: set[str] = set()
        fresh: list[tuple[str, dict[str, Any], str]] = []
        for tool_name, arguments, key in to_run:
            if key in records or key in seen:
                continue
            seen.add(key)
            fresh.append((tool_name, arguments, key))

        # `CALL_CEILING`: only the calls this turn's remaining budget covers
        # are actually dispatched. A batch that would cross the ceiling is
        # truncated at it — the rest never run and are recorded below as
        # `pending_calls` (`docs/ux/trace.md` §5's "what it was about to
        # do"), never silently dropped.
        budget = CALL_CEILING - total_calls_made
        run_now = fresh[:budget]
        overflow_keys = {key for _, _, key in fresh[budget:]}

        results: dict[str, tuple[ToolResult, ToolStep]] = {}
        if run_now:
            # Every `"start"` fired synchronously, before any call is
            # awaited, so a parallel batch's starts are always seen before
            # any of that batch's ends (`on_tool_call`'s own contract).
            for tool_name, arguments, key in run_now:
                _notify(
                    on_tool_call,
                    ToolCallEvent(phase="start", tool=tool_name, call_id=key, arguments=arguments),
                )
            # Concurrent, not sequential: none of the five tools write
            # anything, so two independently emitted calls have no reason
            # to wait on each other (the module docstring).
            outcomes = await asyncio.gather(*(_run_one(n, a, k) for n, a, k in run_now))
            results = {key: outcome for (_, _, key), outcome in zip(run_now, outcomes, strict=True)}

        pending_calls: list[dict[str, Any]] = []
        pending_seen: set[str] = set()

        for tool_name, arguments, key in to_run:
            if key in overflow_keys:
                if key not in pending_seen:
                    pending_seen.add(key)
                    pending_calls.append({"tool": tool_name, "arguments": arguments})
                continue
            deduplicated = key in records
            if not deduplicated:
                result, tool_step = results[key]
                content_for_history = (
                    result.content
                    if result.ok
                    # The model needs the reason, not just that it failed, to
                    # have a chance at the edge case this ticket names: "a
                    # tool error mid-loop — the model is told and can try
                    # another approach." `ToolError.message` is exactly that
                    # reason; `ToolStep.detail` alone (what the trace stores)
                    # never carries it.
                    else {"error": cast(ToolError, result.error).message, **tool_step.detail}
                )
                content_json = json.dumps(content_for_history, default=str)
                result_index = next_result_index
                next_result_index += 1
                elapsed_ms = round((time.monotonic() - loop_started) * 1000)
                started_offset_ms = elapsed_ms - tool_step.duration_ms
                loop_step = LoopStep(
                    kind="tool",
                    tool=tool_name,
                    arguments=tool_step.arguments,
                    duration_ms=tool_step.duration_ms,
                    outcome=tool_step.outcome,
                    truncated=tool_step.truncated,
                    detail=tool_step.detail,
                    injection_flagged=tool_step.injection_flagged,
                    injection_patterns=tool_step.injection_patterns,
                    iteration=iteration,
                    deduplicated=False,
                    started_offset_ms=max(started_offset_ms, 0),
                    result_index=result_index,
                )
                records[key] = _CallRecord(step=loop_step, result_content_json=content_json)
                history_blocks.append(delimit_tool_result(result_index, tool_name, content_json))
                tool_names_called.append(tool_name)
            else:
                prior = records[key]
                loop_step = LoopStep(
                    kind="tool",
                    tool=tool_name,
                    arguments=prior.step.arguments,
                    duration_ms=0,
                    outcome=prior.step.outcome,
                    truncated=prior.step.truncated,
                    detail=prior.step.detail,
                    injection_flagged=prior.step.injection_flagged,
                    injection_patterns=prior.step.injection_patterns,
                    iteration=iteration,
                    deduplicated=True,
                    started_offset_ms=round((time.monotonic() - loop_started) * 1000),
                    result_index=prior.step.result_index,
                )
            steps.append(loop_step)

        total_calls_made += len(run_now)

        if pending_calls:
            return await _stop_at_ceiling(
                client=client,
                system_prompt=system_prompt,
                catalogue=catalogue,
                question=question,
                resume_note=resume_note,
                history_blocks=history_blocks,
                steps=steps,
                tool_names_called=tool_names_called,
                iteration=iteration,
                pending_calls=tuple(pending_calls),
                continuation_count=continuation_count,
                next_result_index=next_result_index,
            )

    # `_SAFETY_MAX_ITERATIONS` reached with no answer — never silently drop
    # what was actually gathered; the steps already collected are still
    # returned on `LoopResult.steps`. Unreachable in ordinary operation now
    # that `CALL_CEILING` stops a turn first — see the module docstring.
    fallback_text = (
        "Askwell gathered information across several steps but did not reach a final "
        "answer before stopping."
    )
    return LoopResult(
        text=fallback_text,
        steps=tuple(steps),
        iterations=_SAFETY_MAX_ITERATIONS,
        stopped_reason="safety_limit",
        tool_names_called=tuple(tool_names_called),
        continuation_count=continuation_count,
    )
