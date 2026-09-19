"""The multi-step tool loop, pure. `M5-LOOP-BE-115`.

No database or real model needed: `call_tool` is replaced with a fake that
records what it was asked and returns a queued `ToolResult`, and
`InferenceClient.generate` is replaced with a fake that returns queued
completions — the same "control every response, assert on the shape" style
`test_tools.py` and `test_sql_generate.py` already use for the modules this
one calls into.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, cast

import pytest

from askwell.agent import loop as loop_module
from askwell.agent.loop import LoopResult, run_tool_loop
from askwell.agent.tools import ToolError, ToolErrorCode, ToolResult, ToolStep
from askwell.inference.client import Completion


@dataclass
class _FakeClient:
    """`InferenceClient.generate`'s call signature, none of its I/O."""

    responses: list[str]
    calls: list[str] = field(default_factory=list)

    async def generate(self, prompt: str, **kwargs: Any) -> Completion:
        self.calls.append(prompt)
        text = self.responses.pop(0)
        return Completion(text=text, tokens=len(text.split()))


def _tool_step(
    tool: str, outcome: str = "ok", *, arguments: dict[str, Any] | None = None
) -> ToolStep:
    return ToolStep(
        kind="tool",
        tool=tool,
        arguments=arguments or {},
        duration_ms=5,
        outcome=outcome,
        truncated=False,
        detail={"ok": True},
        injection_flagged=False,
        injection_patterns=(),
    )


class _FakeCallTool:
    """Replaces `askwell.agent.tools.call_tool`: one queued `(ToolResult,
    ToolStep)` per `(tool, arguments)` key, and a record of every call
    actually made — the thing `test_a_duplicate_call_is_not_re_executed`
    needs to assert against."""

    def __init__(self, outcomes: dict[str, tuple[ToolResult, ToolStep]]) -> None:
        self.outcomes = outcomes
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def __call__(
        self, name: str, arguments: dict[str, Any], *, session: Any, settings: Any, client: Any
    ) -> tuple[ToolResult, ToolStep]:
        self.calls.append((name, arguments))
        await asyncio.sleep(0)
        key = f"{name}:{json.dumps(arguments, sort_keys=True)}"
        return self.outcomes[key]


def _ok_outcome(
    tool: str, content: dict[str, Any], arguments: dict[str, Any]
) -> tuple[ToolResult, ToolStep]:
    result = ToolResult(content=content, truncated=False, error=None)
    step = _tool_step(tool, arguments=arguments)
    return result, step


def _install_call_tool(monkeypatch: pytest.MonkeyPatch, fake: _FakeCallTool) -> None:
    monkeypatch.setattr(loop_module, "call_tool", fake)


@pytest.mark.asyncio
async def test_a_single_tool_call_then_an_answer_terminates_the_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_tool = _FakeCallTool(
        {
            'document_search:{"query": "contract terms"}': _ok_outcome(
                "document_search", {"passages": ["net 30"]}, {"query": "contract terms"}
            )
        }
    )
    _install_call_tool(monkeypatch, fake_tool)
    client = _FakeClient(
        responses=[
            json.dumps(
                {
                    "type": "tool_calls",
                    "calls": [
                        {"tool": "document_search", "arguments": {"query": "contract terms"}}
                    ],
                }
            ),
            json.dumps({"type": "answer", "text": "Payment terms are net 30 [1]."}),
        ]
    )

    result = await run_tool_loop(
        cast(Any, None), cast(Any, None), cast(Any, client), question="What are the payment terms?"
    )

    assert isinstance(result, LoopResult)
    assert result.stopped_reason == "answered"
    assert result.text == "Payment terms are net 30 [1]."
    assert result.iterations == 2
    assert len(fake_tool.calls) == 1
    assert [s.tool for s in result.steps] == ["document_search"]
    assert result.steps[0].deduplicated is False


@pytest.mark.asyncio
async def test_two_independent_calls_in_one_turn_both_run_and_neither_is_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_tool = _FakeCallTool(
        {
            'document_search:{"query": "contract"}': _ok_outcome(
                "document_search", {"passages": ["net 30"]}, {"query": "contract"}
            ),
            'database_query:{"question": "payments"}': _ok_outcome(
                "database_query", {"rows": [["Acme", "2026-01-01"]]}, {"question": "payments"}
            ),
        }
    )
    _install_call_tool(monkeypatch, fake_tool)
    client = _FakeClient(
        responses=[
            json.dumps(
                {
                    "type": "tool_calls",
                    "calls": [
                        {"tool": "document_search", "arguments": {"query": "contract"}},
                        {"tool": "database_query", "arguments": {"question": "payments"}},
                    ],
                }
            ),
            json.dumps({"type": "answer", "text": "Acme is paid late [1][2]."}),
        ]
    )

    result = await run_tool_loop(
        cast(Any, None),
        cast(Any, None),
        cast(Any, client),
        question="Which suppliers are paid late?",
    )

    assert result.stopped_reason == "answered"
    assert {name for name, _ in fake_tool.calls} == {"document_search", "database_query"}
    assert len(fake_tool.calls) == 2
    assert sorted(s.tool for s in result.steps) == ["database_query", "document_search"]
    # Both calls belong to the same iteration — that is what "parallel" means here.
    assert {s.iteration for s in result.steps} == {1}


@pytest.mark.asyncio
async def test_a_duplicate_call_is_not_re_executed(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_tool = _FakeCallTool(
        {
            'document_search:{"query": "contract"}': _ok_outcome(
                "document_search", {"passages": ["net 30"]}, {"query": "contract"}
            ),
        }
    )
    _install_call_tool(monkeypatch, fake_tool)
    client = _FakeClient(
        responses=[
            json.dumps(
                {
                    "type": "tool_calls",
                    "calls": [{"tool": "document_search", "arguments": {"query": "contract"}}],
                }
            ),
            # Same call again — the model asking twice, not a real second need.
            json.dumps(
                {
                    "type": "tool_calls",
                    "calls": [{"tool": "document_search", "arguments": {"query": "contract"}}],
                }
            ),
            json.dumps({"type": "answer", "text": "Net 30 [1]."}),
        ]
    )

    result = await run_tool_loop(
        cast(Any, None), cast(Any, None), cast(Any, client), question="What are the terms?"
    )

    assert len(fake_tool.calls) == 1
    dedup_steps = [s for s in result.steps if s.deduplicated]
    assert len(dedup_steps) == 1
    assert dedup_steps[0].tool == "document_search"
    assert dedup_steps[0].iteration == 2


@pytest.mark.asyncio
async def test_two_identical_calls_in_the_same_turn_are_deduplicated_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_tool = _FakeCallTool(
        {
            'document_search:{"query": "contract"}': _ok_outcome(
                "document_search", {"passages": ["net 30"]}, {"query": "contract"}
            ),
        }
    )
    _install_call_tool(monkeypatch, fake_tool)
    client = _FakeClient(
        responses=[
            json.dumps(
                {
                    "type": "tool_calls",
                    "calls": [
                        {"tool": "document_search", "arguments": {"query": "contract"}},
                        {"tool": "document_search", "arguments": {"query": "contract"}},
                    ],
                }
            ),
            json.dumps({"type": "answer", "text": "Net 30 [1]."}),
        ]
    )

    result = await run_tool_loop(
        cast(Any, None), cast(Any, None), cast(Any, client), question="What are the terms?"
    )

    assert len(fake_tool.calls) == 1
    assert len(result.steps) == 2
    assert sum(1 for s in result.steps if s.deduplicated) == 1


@pytest.mark.asyncio
async def test_a_tool_error_mid_loop_is_told_to_the_model_and_the_turn_recovers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error_result = ToolResult(
        content=None,
        truncated=False,
        error=ToolError(ToolErrorCode.NO_CONNECTION, "No connected database."),
    )
    error_step = _tool_step("database_query", outcome="no_connection", arguments={"question": "x"})
    ok_result = ToolResult(content={"passages": ["net 30"]}, truncated=False, error=None)
    ok_step = _tool_step("document_search", arguments={"query": "contract"})

    fake_tool = _FakeCallTool(
        {
            'database_query:{"question": "x"}': (error_result, error_step),
            'document_search:{"query": "contract"}': (ok_result, ok_step),
        }
    )
    _install_call_tool(monkeypatch, fake_tool)
    client = _FakeClient(
        responses=[
            json.dumps(
                {
                    "type": "tool_calls",
                    "calls": [{"tool": "database_query", "arguments": {"question": "x"}}],
                }
            ),
            json.dumps(
                {
                    "type": "tool_calls",
                    "calls": [{"tool": "document_search", "arguments": {"query": "contract"}}],
                }
            ),
            json.dumps({"type": "answer", "text": "Net 30, from the contract [2]."}),
        ]
    )

    result = await run_tool_loop(
        cast(Any, None), cast(Any, None), cast(Any, client), question="What are the terms?"
    )

    assert result.stopped_reason == "answered"
    outcomes = [s.outcome for s in result.steps]
    assert "no_connection" in outcomes
    assert "ok" in outcomes
    # The failed call's result reached the next prompt, told as data.
    assert "no_connection" in client.calls[-1] or "No connected database" in client.calls[-1]


@pytest.mark.asyncio
async def test_a_malformed_response_ends_the_loop_with_its_raw_text_rather_than_crashing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_call_tool(monkeypatch, _FakeCallTool({}))
    client = _FakeClient(responses=["not json at all"])

    result = await run_tool_loop(
        cast(Any, None), cast(Any, None), cast(Any, client), question="What are the terms?"
    )

    assert result.stopped_reason == "malformed_response"
    assert result.text == "not json at all"
    assert result.steps == ()


@pytest.mark.asyncio
async def test_a_loop_that_never_answers_stops_at_the_safety_limit_not_forever(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_tool = _FakeCallTool(
        {
            "current_date:{}": _ok_outcome("current_date", {"date": "2026-09-20"}, {}),
        }
    )
    _install_call_tool(monkeypatch, fake_tool)
    # Always asks for another call, never answers.
    never_answers = [
        json.dumps({"type": "tool_calls", "calls": [{"tool": "current_date", "arguments": {}}]})
        for _ in range(loop_module._SAFETY_MAX_ITERATIONS)
    ]
    client = _FakeClient(responses=never_answers)

    result = await run_tool_loop(
        cast(Any, None), cast(Any, None), cast(Any, client), question="What day is it, forever?"
    )

    assert result.stopped_reason == "safety_limit"
    assert result.iterations == loop_module._SAFETY_MAX_ITERATIONS
    # Every repeat after the first was deduplicated, never re-called.
    assert len(fake_tool.calls) == 1


@pytest.mark.asyncio
async def test_an_empty_calls_list_is_treated_as_malformed_not_a_silent_stall(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_call_tool(monkeypatch, _FakeCallTool({}))
    client = _FakeClient(responses=[json.dumps({"type": "tool_calls", "calls": []})])

    result = await run_tool_loop(
        cast(Any, None), cast(Any, None), cast(Any, client), question="Anything?"
    )

    assert result.stopped_reason == "malformed_response"
