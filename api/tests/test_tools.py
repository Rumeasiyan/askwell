"""The tool registry, pure. `M5-TOOLS-BE-113`.

No database or model needed for any of this: the registry's shape, argument
validation, and the "a tool never raises" guarantee are all facts provable
without I/O. `test_tools_db.py` covers what each handler actually returns
against real rows.
"""

from __future__ import annotations

import uuid
from typing import Any, cast

import pytest
from pydantic import ValidationError

from askwell.agent import tools as tools_module
from askwell.agent.tools import (
    TOOLS,
    CurrentDateArgs,
    DocumentSearchArgs,
    ToolErrorCode,
    ToolResult,
    call_tool,
)


def test_the_registry_has_exactly_five_tools() -> None:
    assert set(TOOLS) == {
        "document_search",
        "database_query",
        "schema_lookup",
        "document_listing",
        "current_date",
    }


def test_every_tool_has_a_description_and_an_args_model() -> None:
    for name, tool in TOOLS.items():
        assert tool.name == name
        assert tool.description
        assert issubclass(tool.args_model, tools_module.BaseModel)


@pytest.mark.asyncio
async def test_an_unknown_tool_name_is_a_structured_error_not_an_exception() -> None:
    result, step = await call_tool(
        "delete_everything",
        {},
        session=cast(Any, None),
        settings=cast(Any, None),
        client=cast(Any, None),
    )

    assert not result.ok
    assert result.error is not None
    assert result.error.code == ToolErrorCode.NOT_FOUND
    assert step.outcome == "not_found"
    assert step.duration_ms >= 0


@pytest.mark.asyncio
async def test_invalid_arguments_are_a_structured_error_not_an_exception() -> None:
    # A field of the wrong shape: `source_id` is not a UUID.
    result, step = await call_tool(
        "document_search",
        {"query": "terms", "source_id": "not-a-uuid"},
        session=cast(Any, None),
        settings=cast(Any, None),
        client=cast(Any, None),
    )

    assert not result.ok
    assert result.error is not None
    assert result.error.code == ToolErrorCode.INVALID_ARGUMENTS
    assert "errors" in result.error.detail
    assert step.outcome == "invalid_arguments"


@pytest.mark.asyncio
async def test_a_missing_required_argument_is_invalid_arguments_not_a_crash() -> None:
    result, _step = await call_tool(
        "document_search",
        {},
        session=cast(Any, None),
        settings=cast(Any, None),
        client=cast(Any, None),
    )

    assert not result.ok
    assert result.error is not None
    assert result.error.code == ToolErrorCode.INVALID_ARGUMENTS


@pytest.mark.asyncio
async def test_an_unexpected_argument_is_rejected_rather_than_silently_ignored() -> None:
    result, _step = await call_tool(
        "current_date",
        {"unexpected": "value"},
        session=cast(Any, None),
        settings=cast(Any, None),
        client=cast(Any, None),
    )

    assert not result.ok
    assert result.error is not None
    assert result.error.code == ToolErrorCode.INVALID_ARGUMENTS


@pytest.mark.asyncio
async def test_current_date_needs_no_database_or_model() -> None:
    result, step = await call_tool(
        "current_date",
        {},
        session=cast(Any, None),
        settings=cast(Any, None),
        client=cast(Any, None),
    )

    assert result.ok
    assert result.content is not None
    assert "date" in result.content
    assert "datetime" in result.content
    assert step.outcome == "ok"
    assert step.tool == "current_date"


@pytest.mark.asyncio
async def test_a_handler_that_raises_becomes_a_recoverable_failed_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The loop that will call these tools (`M5-LOOP-BE-115`) has no `try`/
    `except` of its own — `call_tool` is the one place a handler's own bug
    is turned into an answerable outcome instead of ending the turn."""

    async def _boom(*_args: Any, **_kwargs: Any) -> ToolResult:
        raise RuntimeError("the handler blew up")

    broken = tools_module.Tool(
        name="current_date",
        description="broken for this test",
        args_model=CurrentDateArgs,
        handler=_boom,
    )
    monkeypatch.setitem(TOOLS, "current_date", broken)

    result, step = await call_tool(
        "current_date",
        {},
        session=cast(Any, None),
        settings=cast(Any, None),
        client=cast(Any, None),
    )

    assert not result.ok
    assert result.error is not None
    assert result.error.code == ToolErrorCode.FAILED
    assert step.outcome == "failed"


def test_arguments_are_json_safe_on_the_trace_step() -> None:
    """A `uuid.UUID` argument (how a real tool call would carry `source_id`)
    must not break a later `json.dumps` of the trace."""
    safe = tools_module._json_safe_arguments({"source_id": uuid.uuid4(), "query": "terms"})
    assert isinstance(safe["source_id"], str)
    assert safe["query"] == "terms"


def test_document_search_args_reject_an_empty_query() -> None:
    with pytest.raises(ValidationError):
        DocumentSearchArgs(query="")
