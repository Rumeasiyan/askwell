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
ceiling.** The ceiling a user sees — "stopped after 8 steps", with a
**Continue** control (`docs/ux/ask.md` §5) — is `M5-LOOP-BE-116`, deliberately
out of this ticket's scope. Without any bound at all, a model stuck
answering-then-re-asking-itself would loop until something else killed the
request; this number exists only so that does not happen before -116 lands,
and is set well above the ceiling -116 will enforce so it is never what a
real turn actually hits.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, cast
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

LOOP_MAX_TOKENS = 700
LOOP_TEMPERATURE = 0.0


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
class LoopResult:
    """What one turn's worth of looping produced.

    `stopped_reason` is `"answered"` for the ordinary case (the model said
    it had enough), `"malformed_response"` when the model's output could not
    be parsed as either action and was used verbatim as the answer instead
    (never a crash — the same "answer it, don't crash it" posture
    `askwell.ask._run_sql_turn`'s own docstring names), or `"safety_limit"`
    when `_SAFETY_MAX_ITERATIONS` was reached with no answer yet.
    """

    text: str
    steps: tuple[LoopStep, ...]
    iterations: int
    stopped_reason: str
    tool_names_called: tuple[str, ...]


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


async def run_tool_loop(
    session: AsyncSession,
    settings: Settings,
    client: InferenceClient,
    *,
    question: str,
    source_id: UUID | None = None,
) -> LoopResult:
    """Call tools, read results, decide whether more is needed, then answer.

    Every iteration replays the full history of `<tool-result>` blocks
    gathered so far into a fresh prompt (see the module docstring) and asks
    the model for its next JSON action. Independently emitted calls in one
    iteration run concurrently via `asyncio.gather`, deduplicated first —
    a duplicate reuses the earlier result rather than calling the tool
    again, recorded as such.
    """
    loop_started = time.monotonic()
    system_prompt = _load_system_prompt()
    catalogue = _tool_catalogue()

    history_blocks: list[str] = []
    records: dict[str, _CallRecord] = {}
    steps: list[LoopStep] = []
    tool_names_called: list[str] = []
    next_result_index = 1

    for iteration in range(1, _SAFETY_MAX_ITERATIONS + 1):
        history = "\n\n".join(history_blocks)
        user_content = f"{catalogue}\n\nQuestion: {question}" + (
            f"\n\n{history}" if history else ""
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
                )
            return LoopResult(
                text=answer_text,
                steps=tuple(steps),
                iterations=iteration,
                stopped_reason="answered",
                tool_names_called=tuple(tool_names_called),
            )

        calls = _valid_calls(parsed) if parsed.get("type") == "tool_calls" else None
        if calls is None:
            return LoopResult(
                text=completion.text.strip(),
                steps=tuple(steps),
                iterations=iteration,
                stopped_reason="malformed_response",
                tool_names_called=tuple(tool_names_called),
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
            tool_name: str, tool_arguments: dict[str, Any]
        ) -> tuple[ToolResult, ToolStep]:
            return await call_tool(
                tool_name, tool_arguments, session=session, settings=settings, client=client
            )

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

        results: dict[str, tuple[ToolResult, ToolStep]] = {}
        if fresh:
            # Concurrent, not sequential: none of the five tools write
            # anything, so two independently emitted calls have no reason
            # to wait on each other (the module docstring).
            outcomes = await asyncio.gather(*(_run_one(n, a) for n, a, _ in fresh))
            results = {key: outcome for (_, _, key), outcome in zip(fresh, outcomes, strict=True)}

        for tool_name, _arguments, key in to_run:
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

    # `_SAFETY_MAX_ITERATIONS` reached with no answer — never silently drop
    # what was actually gathered; the steps already collected are still
    # returned on `LoopResult.steps`.
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
    )
