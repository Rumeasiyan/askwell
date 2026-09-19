"""The tool registry. `M5-TOOLS-BE-113`.

The agent exposes exactly five tools — document search, database query,
schema lookup, document listing, and the current date — through one
registry, so a sixth tool is a decision someone makes deliberately here
rather than an accretion somewhere else. Every tool shares one contract:
declared arguments (a `pydantic` model, `extra="forbid"` so a stray
argument is caught rather than silently ignored), a bounded result, and a
`ToolResult` that is never an exception for an ordinary failure — an empty
corpus, no connection, a rejected query, invalid arguments. `call_tool`
times every call and produces the trace step (`docs/ux/trace.md` §2)
alongside it.

**`M5-TOOLS-BE-114`: every tool result is C7 data, never instruction, before
it ever reaches a trace or a prompt.** `_step` flags a result's content
against the same heuristic `askwell.agent.compose` already applies to a
retrieved passage, and `askwell.agent.compose.delimit_tool_result` wraps a
result in an unforgeable `<tool-result>` block for whichever prompt the loop
below eventually assembles it into — flagging happens here, unconditionally,
so it does not depend on the loop existing yet.

**This module does not loop.** `M5-LOOP-BE-115` is what calls a tool more
than once per turn, feeds a result back to the model, and decides when to
stop. Nothing here is wired into `askwell.ask` yet — the same "do not wire
ahead of the thing that will call it" posture `M4-SQL-DB-107` and
`M4-SQL-BE-103` both took about themselves while their own dependents did
not exist.

**The database query tool re-runs the same checked pipeline `askwell.ask
._run_sql_turn` already assembles for the single-shot `/ask` turn** —
generation (`askwell.agent.sql_generate`) → validation (C2, `askwell.sql.
validate`) → limit injection (`askwell.sql.limit`) → dry run (`askwell.sql.
dry_run`) → execution (`askwell.sql.execute`) — rather than a second
implementation of any of those stages. Only the orchestration is repeated
here, in the shape a tool call needs (a `ToolResult`, not a `messages.trace`
step and an SSE event); every stage it calls into remains the single
enforcement point it already was.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from askwell import crypto
from askwell.agent.compose import flag_injection_text
from askwell.agent.sql_generate import GenerationReason, generate_candidate_query
from askwell.config import Settings
from askwell.connections import Engine
from askwell.inference.client import InferenceClient
from askwell.logging import get_logger
from askwell.memory import get_active_schema_notes
from askwell.retrieve import candidate_score, retrieve
from askwell.sql import execute as sql_execute_checked
from askwell.sql.dry_run import dry_run_connection_query, dry_run_sandbox_query
from askwell.sql.limit import inject_limit
from askwell.sql.validate import validate_query
from askwell.sql_execute import (
    ConnectionUnreachable,
    CredentialsRejected,
    QueryRejected,
    StatementTimedOut,
)

log = get_logger(__name__)

# Bounds. Each one is the "enormous result" edge case made concrete for its
# own tool — the model is told when it did not see everything rather than
# being handed a silently clipped result.
DOCUMENT_SEARCH_MAX_PASSAGES = 8
DOCUMENT_SEARCH_MAX_CONTENT_CHARS = 1200
SCHEMA_LOOKUP_MAX_NOTES = 50
DOCUMENT_LISTING_MAX_ROWS = 50
DATABASE_QUERY_MAX_ROWS = 50


class ToolErrorCode(StrEnum):
    """Why a tool call did not produce a result. Every one of these is a
    recoverable outcome the caller can react to, never an exception that
    ends the turn."""

    INVALID_ARGUMENTS = "invalid_arguments"
    NOT_FOUND = "not_found"
    NO_CONNECTION = "no_connection"
    NOT_APPLICABLE = "not_applicable"
    AMBIGUOUS = "ambiguous"
    REJECTED = "rejected"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ToolError:
    code: ToolErrorCode
    message: str
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ToolResult:
    """One tool call's outcome. Exactly one of `content`/`error` is set."""

    content: dict[str, Any] | None
    truncated: bool
    error: ToolError | None

    @property
    def ok(self) -> bool:
        return self.error is None


def _ok(content: dict[str, Any], *, truncated: bool = False) -> ToolResult:
    return ToolResult(content=content, truncated=truncated, error=None)


def _err(code: ToolErrorCode, message: str, **detail: Any) -> ToolResult:
    return ToolResult(content=None, truncated=False, error=ToolError(code, message, detail))


def _json_safe(value: Any) -> Any:
    """One raw row value, made JSON-safe — a tool result is stored on the
    trace exactly like `messages.sql_result` already is (`askwell.ask.
    _json_safe`, the same conversion, kept local here rather than imported
    from a module marking it private)."""
    if isinstance(value, (Decimal, uuid.UUID)):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()
    return value


def _json_safe_arguments(raw: dict[str, Any]) -> dict[str, Any]:
    return {key: _json_safe(value) for key, value in raw.items()}


class DocumentSearchArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1)
    source_id: uuid.UUID | None = None


class DatabaseQueryArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1)
    source_id: uuid.UUID | None = None


class SchemaLookupArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: uuid.UUID | None = None
    table: str | None = None


class DocumentListingArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: uuid.UUID | None = None


class CurrentDateArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


Handler = Callable[[AsyncSession, Settings, InferenceClient, BaseModel], Awaitable[ToolResult]]


@dataclass(frozen=True, slots=True)
class Tool:
    name: str
    description: str
    args_model: type[BaseModel]
    handler: Handler


async def _document_search(
    session: AsyncSession, settings: Settings, client: InferenceClient, args: BaseModel
) -> ToolResult:
    parsed = cast(DocumentSearchArgs, args)
    result = await retrieve(session, client, settings, parsed.query, source_id=parsed.source_id)
    ranked = sorted(result.candidates, key=candidate_score, reverse=True)
    shown = ranked[:DOCUMENT_SEARCH_MAX_PASSAGES]

    content_truncated = False
    passages: list[dict[str, Any]] = []
    for candidate in shown:
        text_content = candidate.content
        clipped = len(text_content) > DOCUMENT_SEARCH_MAX_CONTENT_CHARS
        if clipped:
            text_content = text_content[:DOCUMENT_SEARCH_MAX_CONTENT_CHARS]
            content_truncated = True
        passages.append(
            {
                "document_id": str(candidate.document_id),
                "filename": candidate.filename,
                "heading": candidate.heading,
                "page_from": candidate.page_from,
                "page_to": candidate.page_to,
                "score": round(candidate_score(candidate), 4),
                "content": text_content,
                "content_truncated": clipped,
            }
        )

    truncated = content_truncated or len(ranked) > len(shown)
    return _ok(
        {
            "passages": passages,
            "threshold": result.threshold,
            "reranked": result.reranked,
            "total_candidates": len(ranked),
        },
        truncated=truncated,
    )


async def _connection_credentials(settings: Settings, config_encrypted: bytes) -> dict[str, Any]:
    """Decrypt a live connection's stored configuration for one query-time
    call — the same shape `askwell.ask._connection_credentials` already
    uses, kept local here for the same reason `_json_safe` is."""
    install_secret = crypto.load_or_create_install_secret(settings.install_secret_path)
    config: dict[str, Any] = json.loads(
        crypto.decrypt(config_encrypted, crypto.derive_key(install_secret)).decode("utf-8")
    )
    return config


async def _database_query(
    session: AsyncSession, settings: Settings, client: InferenceClient, args: BaseModel
) -> ToolResult:
    parsed = cast(DatabaseQueryArgs, args)
    generation = await generate_candidate_query(
        session, settings, client, question=parsed.question, source_id=parsed.source_id
    )
    if generation.reason == GenerationReason.NO_DATABASES:
        return _err(ToolErrorCode.NO_CONNECTION, "No connected database can answer this question.")
    if generation.reason == GenerationReason.NOT_A_DATABASE_QUESTION:
        return _err(
            ToolErrorCode.NOT_APPLICABLE,
            "Nothing about a connected database's schema bears on this question.",
        )
    if generation.reason == GenerationReason.AMBIGUOUS:
        names = [source.name for source in generation.candidates]
        return _err(
            ToolErrorCode.AMBIGUOUS,
            "More than one connected database could answer this question.",
            candidates=names,
        )

    generated = generation.query
    assert generated is not None
    engine = cast(Engine, generated.engine)

    validation = await validate_query(
        session, settings, engine=engine, query=generated.query, source_id=generated.source_id
    )
    if not validation.accepted:
        assert validation.reason is not None
        return _err(
            ToolErrorCode.REJECTED,
            f"The generated query was rejected: {validation.detail}",
            reason=validation.reason.value,
            query=generated.query,
        )

    limited = await inject_limit(session, settings, engine=engine, query=generated.query)

    source_row = (
        await session.execute(
            text("SELECT kind, sandbox_db, config_encrypted FROM sources WHERE id = :id"),
            {"id": generated.source_id},
        )
    ).first()
    if source_row is None:
        return _err(
            ToolErrorCode.NO_CONNECTION,
            "The database this question would have used is no longer connected.",
        )
    kind, sandbox_db, config_encrypted = source_row
    config: dict[str, Any] | None = None

    if kind == "connection":
        assert config_encrypted is not None
        config = await _connection_credentials(settings, bytes(config_encrypted))
        dry_run = await dry_run_connection_query(
            session,
            settings,
            source_id=generated.source_id,
            engine=engine,
            host=config["host"],
            port=config["port"],
            database=config["database"],
            user=config["user"],
            password=config["password"],
            query=limited.query,
        )
    else:
        assert sandbox_db is not None
        dry_run = await dry_run_sandbox_query(
            session, settings, database=sandbox_db, query=limited.query
        )

    if not dry_run.passed:
        assert dry_run.reason is not None
        return _err(
            ToolErrorCode.REJECTED,
            f"Askwell could not run this query against your database: {dry_run.detail}",
            reason=dry_run.reason.value,
            query=limited.query,
        )

    try:
        if kind == "connection":
            assert config is not None
            checked = await sql_execute_checked.execute_checked_connection_query(
                session,
                settings,
                source_id=generated.source_id,
                engine=engine,
                host=config["host"],
                port=config["port"],
                database=config["database"],
                user=config["user"],
                password=config["password"],
                query=limited.query,
                row_limit=limited.limit,
            )
        else:
            assert sandbox_db is not None
            checked = await sql_execute_checked.execute_checked_sandbox_query(
                session, settings, database=sandbox_db, query=limited.query, row_limit=limited.limit
            )
    except StatementTimedOut as error:
        return _err(ToolErrorCode.FAILED, str(error), reason="timeout", query=limited.query)
    except (ConnectionUnreachable, CredentialsRejected, QueryRejected) as error:
        return _err(
            ToolErrorCode.NO_CONNECTION,
            str(error),
            reason=type(error).__name__,
            query=limited.query,
        )

    rows = [[_json_safe(value) for value in row] for row in checked.rows]
    display_rows = rows[:DATABASE_QUERY_MAX_ROWS]
    truncated = checked.truncated or len(rows) > len(display_rows)
    return _ok(
        {
            "engine": engine,
            "query": limited.query,
            "columns": list(checked.columns),
            "rows": display_rows,
            "row_count": checked.row_count,
        },
        truncated=truncated,
    )


async def _schema_lookup(
    session: AsyncSession, settings: Settings, client: InferenceClient, args: BaseModel
) -> ToolResult:
    parsed = cast(SchemaLookupArgs, args)
    notes = await get_active_schema_notes(session, source_id=parsed.source_id)
    if parsed.table is not None:
        wanted = parsed.table.lower()
        notes = [note for note in notes if note.table_name.lower() == wanted]

    shown = notes[:SCHEMA_LOOKUP_MAX_NOTES]
    return _ok(
        {
            "notes": [
                {
                    "table_name": note.table_name,
                    "column_name": note.column_name,
                    "description": note.description,
                    "origin": note.origin,
                    "stale": note.stale,
                }
                for note in shown
            ],
            "total_notes": len(notes),
        },
        truncated=len(notes) > len(shown),
    )


async def _document_listing(
    session: AsyncSession, settings: Settings, client: InferenceClient, args: BaseModel
) -> ToolResult:
    parsed = cast(DocumentListingArgs, args)
    rows = (
        await session.execute(
            text(
                "SELECT d.filename, s.name, d.status, d.added_at "
                "FROM documents d JOIN sources s ON s.id = d.source_id "
                "WHERE d.deleted_at IS NULL "
                "AND (CAST(:source_id AS uuid) IS NULL OR d.source_id = CAST(:source_id AS uuid)) "
                "ORDER BY d.added_at DESC "
                "LIMIT :limit"
            ),
            {"source_id": parsed.source_id, "limit": DOCUMENT_LISTING_MAX_ROWS + 1},
        )
    ).all()

    truncated = len(rows) > DOCUMENT_LISTING_MAX_ROWS
    shown = rows[:DOCUMENT_LISTING_MAX_ROWS]
    return _ok(
        {
            "documents": [
                {
                    "filename": filename,
                    "source_name": source_name,
                    "status": status,
                    "added_at": added_at.isoformat(),
                }
                for filename, source_name, status, added_at in shown
            ],
        },
        truncated=truncated,
    )


async def _current_date(
    session: AsyncSession, settings: Settings, client: InferenceClient, args: BaseModel
) -> ToolResult:
    now = datetime.now(UTC)
    return _ok({"date": now.date().isoformat(), "datetime": now.isoformat()})


TOOLS: dict[str, Tool] = {
    "document_search": Tool(
        name="document_search",
        description="Search the user's own documents for passages relevant to a query.",
        args_model=DocumentSearchArgs,
        handler=_document_search,
    ),
    "database_query": Tool(
        name="database_query",
        description=(
            "Answer a question from a connected database: generates, validates and runs a "
            "single read-only query."
        ),
        args_model=DatabaseQueryArgs,
        handler=_database_query,
    ),
    "schema_lookup": Tool(
        name="schema_lookup",
        description="Look up known schema notes for a connected database, optionally one table.",
        args_model=SchemaLookupArgs,
        handler=_schema_lookup,
    ),
    "document_listing": Tool(
        name="document_listing",
        description="List the user's documents, optionally scoped to one source.",
        args_model=DocumentListingArgs,
        handler=_document_listing,
    ),
    "current_date": Tool(
        name="current_date",
        description="The current date and time, for a question phrased relative to today.",
        args_model=CurrentDateArgs,
        handler=_current_date,
    ),
}


@dataclass(frozen=True, slots=True)
class ToolStep:
    """One trace step for a tool call. `docs/ux/trace.md` §2.

    `injection_flagged`/`injection_patterns` are C7 (`M5-TOOLS-BE-114`) for
    a tool result the same way `ComposedPrompt.injection_flagged` is for a
    retrieved passage: a database row or schema note is exactly as untrusted
    as document text, so it goes through the identical heuristic
    (`askwell.agent.compose.flag_injection_text`) before it ever reaches the
    trace. The flag never changes `outcome` or `content` — flagging is not
    blocking, by design (this ticket's own out-of-scope line).
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


def _flatten_strings(value: Any) -> list[str]:
    """Every string leaf in a tool result's `content`/`detail`, however
    deeply nested — a flagged row three levels down a `database_query`
    result (a JSON column, say) must not be missed because it wasn't at the
    top level.
    """
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text_ for v in value.values() for text_ in _flatten_strings(v)]
    if isinstance(value, (list, tuple)):
        return [text_ for v in value for text_ in _flatten_strings(v)]
    return []


def _step(name: str, raw_arguments: dict[str, Any], started: float, result: ToolResult) -> ToolStep:
    duration_ms = round((time.monotonic() - started) * 1000)
    outcome = "ok" if result.ok else cast(ToolError, result.error).code.value
    detail = result.content if result.ok else cast(ToolError, result.error).detail
    injection_flagged, injection_patterns = flag_injection_text(_flatten_strings(detail or {}))
    return ToolStep(
        kind="tool",
        tool=name,
        arguments=_json_safe_arguments(raw_arguments),
        duration_ms=duration_ms,
        outcome=outcome,
        truncated=result.truncated,
        detail=detail or {},
        injection_flagged=injection_flagged,
        injection_patterns=injection_patterns,
    )


async def call_tool(
    name: str,
    raw_arguments: dict[str, Any],
    *,
    session: AsyncSession,
    settings: Settings,
    client: InferenceClient,
) -> tuple[ToolResult, ToolStep]:
    """Call one tool by name, timed, with every failure — an unknown tool
    name, invalid arguments, or the handler itself failing — turned into a
    recoverable `ToolResult` rather than an exception. The caller (the loop,
    once `M5-LOOP-BE-115` exists) never needs a `try`/`except` around this.
    """
    started = time.monotonic()
    tool = TOOLS.get(name)
    if tool is None:
        result = _err(ToolErrorCode.NOT_FOUND, f"No such tool: {name!r}.")
        return result, _step(name, raw_arguments, started, result)

    try:
        args = tool.args_model.model_validate(raw_arguments)
    except ValidationError as error:
        result = _err(
            ToolErrorCode.INVALID_ARGUMENTS,
            "Invalid arguments for this tool.",
            errors=error.errors(include_url=False),
        )
        return result, _step(name, raw_arguments, started, result)

    try:
        result = await tool.handler(session, settings, client, args)
    except Exception as error:
        log.warning("tool_call_failed", tool=name, error=str(error))
        result = _err(ToolErrorCode.FAILED, "This tool failed unexpectedly.")

    return result, _step(name, raw_arguments, started, result)
