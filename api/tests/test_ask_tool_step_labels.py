"""Live per-call step labels for a multi-step turn. `M5-LOOP-FE-118`.

Pure: `_tool_call_step` only maps a `ToolCallEvent` to the `step` payload
`web/lib/ask.ts` reads — no database, no model, no HTTP.
"""

from __future__ import annotations

from askwell.agent.loop import ToolCallEvent
from askwell.ask import _tool_call_step


def _event(
    phase: str, tool: str = "document_search", *, call_id: str = "c1", outcome: str | None = None
) -> ToolCallEvent:
    return ToolCallEvent(
        phase=phase,  # type: ignore[arg-type]
        tool=tool,
        call_id=call_id,
        arguments={},
        outcome=outcome,
    )


def test_a_start_names_the_real_operation_not_the_raw_tool_name() -> None:
    step = _tool_call_step(_event("start", "document_search"))
    assert step["label"] == "Searching your files."
    assert "document_search" not in step["label"]


def test_every_known_tool_has_a_start_and_a_finished_label() -> None:
    for tool in [
        "document_search",
        "database_query",
        "schema_lookup",
        "document_listing",
        "current_date",
    ]:
        start = _tool_call_step(_event("start", tool))
        end = _tool_call_step(_event("end", tool, outcome="ok"))
        assert start["label"] != end["label"]
        assert start["label"] != ""
        assert end["label"] != ""


def test_an_end_names_the_failed_call_as_a_change_of_approach_not_a_freeze() -> None:
    step = _tool_call_step(_event("end", "database_query", outcome="rejected"))
    assert "trying another way" in step["label"]


def test_the_call_id_and_phase_travel_so_the_frontend_can_key_on_them() -> None:
    start = _tool_call_step(_event("start", call_id="call-7"))
    end = _tool_call_step(_event("end", call_id="call-7", outcome="ok"))
    assert start["call_id"] == end["call_id"] == "call-7"
    assert start["phase"] == "start"
    assert end["phase"] == "end"


def test_an_unknown_tool_still_produces_a_named_label_not_a_placeholder() -> None:
    step = _tool_call_step(_event("start", "some_future_tool"))
    assert step["label"] == "Calling some_future_tool."
