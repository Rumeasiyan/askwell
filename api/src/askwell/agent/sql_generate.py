"""Schema retrieval and SQL generation. `M4-SQL-BE-103`.

The whole database path starts here: retrieve the relevant schema subset for
a question, plus schema notes and memory, then ask the model for one
candidate query. **This module never executes anything and never validates
anything** — `sqlglot` parsing (`M4-SQL-VAL-104`), limit injection
(`-105`), the dry run (`-106`) and execution (`askwell.sql_execute`,
already built by `M4-SQL-DB-107`) are later, dependent tickets, and a
generated query produced here is text, nothing more, until one of them has
looked at it. `askwell.sql_execute`'s own module docstring establishes the
same boundary from the other side: it runs a query string it is handed, and
does not know how that string was produced.

**Since `M4-SQL-BE-108a`, this is reachable from `POST /ask`.** `askwell.ask
._run_sql_turn` calls `generate_candidate_query` as the first step of every
turn, ahead of document retrieval, then runs its result through
`askwell.sql.validate` → `askwell.sql.limit` → `askwell.sql.dry_run` →
`askwell.sql.execute` in that order — the same chain this module's own
functions were already built to feed, now actually fed. `NO_DATABASES` and
`NOT_A_DATABASE_QUESTION` both come back from `_run_sql_turn` as `None`,
which is what lets a turn with no relevant database fall through to
document retrieval exactly as it did before this ticket existed.

**Schema retrieval reuses `schema_notes`, not a second schema
representation.** `M4-SCHEMA-ING-100` through `-102` already turned a live
connection's or a sandbox database's schema into plain-language
`schema_notes` rows — table-level ("Table orders. Columns: ...") and
column-level ("orders.status — text, not null.") — that
`askwell.memory.retrieve_relevant_facts` already ranks by lexical relevance
to a question and already excludes a stale note outright. Calling it with a
higher `note_limit` *is* "relevance-based schema subset retrieval with
notes and memory" — building a second, bulk `SchemaInventory`-shaped context
here would duplicate what that ticket already produced under a different
name, the same duplication `M4-DUMP-ING-088`'s own decisions-log entry
rejected for itself.

**Source selection when several databases are connected** is deliberately
coarse: does *any* of a candidate source's schema notes match the question
at all, per source, via the same `retrieve_relevant_facts` call. Zero
sources match: nothing here is a database question — the ticket's own edge
case, "a question that is not about data at all — routed to document
retrieval instead, not forced into SQL." Exactly one matches: use it, no
question asked. More than one matches: **the answer names the candidates
rather than guessing**, which is also the honest answer for the ticket's own
"question spanning two databases" edge case — this module never attempts a
query joining tables across two sources (each generation call sends exactly
one source's schema to the model), so a genuinely cross-database question
can only ever produce, at best, a query against one of them; asking rather
than guessing is the one response that is correct for both edge cases at
once, without a second, unreliable heuristic to tell them apart.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from askwell import crypto
from askwell.agent.compose import (
    ComposedPrompt,
    delimit_memory_facts,
    delimit_schema_notes,
    flag_injection_text,
)
from askwell.audit import Store, record
from askwell.config import Settings
from askwell.inference.client import InferenceClient
from askwell.logging import get_logger
from askwell.memory import MemoryFact, RelevantMemory, SchemaNote, retrieve_relevant_facts

log = get_logger(__name__)

PROMPT_DIR = Path(__file__).parent / "prompts"
PROMPT_VERSION = "sql_generation.v1"
PROMPT_PATH = PROMPT_DIR / f"{PROMPT_VERSION}.md"

# Bounding "a schema too large for the context" (the ticket's own edge case)
# is `retrieve_relevant_facts`'s existing `note_limit` — set higher than
# `RELEVANT_NOTE_LIMIT`'s default of 5, since a query commonly needs several
# columns across one or two tables (a join's own foreign-key note, every
# column actually selected or filtered on), not just the single most
# relevant fact a document answer's background context needs.
SCHEMA_NOTE_LIMIT = 40

# SQL is short. Generous headroom for a query with several joins and a
# `WHERE` clause, without the 1024-token default `Settings.generation_max_tokens`
# reserves for prose.
SQL_MAX_TOKENS = 400
# Deterministic on purpose: a query is either right or wrong, never better
# for being creatively phrased, unlike prose (`compose_conflict`'s call site
# uses the model's own default temperature for that reason; this does not).
SQL_TEMPERATURE = 0.0

# What the model is told to write, verbatim, when the question cannot be
# answered from the schema it was given — checked for on the response, not
# guessed at from an empty or malformed completion.
_CANNOT_ANSWER_PREFIX = "CANNOT_ANSWER"

SQL_GENERATED = "sql_generated"

# Database-backed source kinds — a dump or CSV loaded into the sandbox, or a
# live connection. `docs/data-sources.md`; `askwell.db.models.SOURCE_KINDS`.
_DATABASE_SOURCE_KINDS = ("dump", "csv", "connection")


class SelectionReason(StrEnum):
    SELECTED = "selected"
    NO_DATABASES = "no_databases"
    AMBIGUOUS = "ambiguous"


class GenerationReason(StrEnum):
    GENERATED = "generated"
    NO_DATABASES = "no_databases"
    AMBIGUOUS = "ambiguous"
    NOT_A_DATABASE_QUESTION = "not_a_database_question"


@dataclass(frozen=True, slots=True)
class DatabaseSource:
    """One `ready` database-backed source, enough to generate against."""

    id: uuid.UUID
    name: str
    kind: str  # "dump" | "csv" | "connection"
    engine: str  # "postgresql" | "mysql" | "mariadb" | "sqlserver"


@dataclass(frozen=True, slots=True)
class SourceSelection:
    reason: SelectionReason
    source: DatabaseSource | None
    candidates: tuple[DatabaseSource, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class GeneratedQuery:
    """One candidate query — text only, never executed here."""

    query: str
    engine: str
    prompt_version: str
    source_id: uuid.UUID
    schema_note_ids: tuple[uuid.UUID, ...]
    memory_fact_ids: tuple[uuid.UUID, ...]
    injection_flagged: bool
    injection_patterns: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GenerationResult:
    """What `generate_candidate_query` produced, or why it produced nothing.

    Exactly one of `query`/`candidates` is ever non-empty, matching `reason`
    — `NO_DATABASES` and `NOT_A_DATABASE_QUESTION` carry neither, since a
    caller renders each from `reason` alone (`docs/states-and-edge-cases.md`
    §4's "no connections configured" row, and "routed to document retrieval
    instead" respectively).
    """

    reason: GenerationReason
    query: GeneratedQuery | None
    candidates: tuple[DatabaseSource, ...] = field(default_factory=tuple)


@lru_cache(maxsize=1)
def _load_system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def _delimit_schema(engine: str, notes: list[SchemaNote]) -> str:
    lines = "\n".join(
        f"{note.table_name}{f'.{note.column_name}' if note.column_name else ''}: {note.description}"
        for note in notes
    )
    return f'<schema engine="{engine}">\n{lines}\n</schema>'


def compose_sql_generation(
    question: str,
    engine: str,
    notes: list[SchemaNote],
    facts: list[MemoryFact],
) -> ComposedPrompt:
    """Build the prompt for one text-to-SQL generation call. Pure — no I/O
    beyond reading the cached prompt file. `notes` must be non-empty; a
    question with no relevant schema at all is `generate_candidate_query`'s
    own `NOT_A_DATABASE_QUESTION` branch, never reaching composition.
    """
    schema_block = _delimit_schema(engine, notes)
    # `<schema>` and `<schema-notes>`/`<memory-facts>` are delimited exactly
    # like `askwell.agent.conflict`'s own use of the latter two — one
    # citation-index space is not needed here, since nothing in a generated
    # query cites anything back; `start_index=1` is arbitrary numbering the
    # prompt never asks the model to read out.
    notes_block = delimit_schema_notes(notes, start_index=1)
    facts_block = delimit_memory_facts(facts, start_index=len(notes) + 1)
    injection_flagged, injection_patterns = flag_injection_text(
        [note.description for note in notes] + [fact.fact for fact in facts]
    )
    return ComposedPrompt(
        system_prompt=_load_system_prompt(),
        user_content=(f"{schema_block}{notes_block}{facts_block}\n\nQuestion: {question}"),
        prompt_version=PROMPT_VERSION,
        injection_flagged=injection_flagged,
        injection_patterns=injection_patterns,
    )


def _extract_query(completion_text: str) -> str | None:
    """Read the model's response back out: `None` for a declined
    (`CANNOT_ANSWER: ...`) or empty completion, the bare query text
    otherwise — stripped of the code fence a small local model reaches for
    anyway despite being told not to (`docs/decisions.md`'s own recurring
    finding about small-model prompt compliance, e.g. `M2-PARTIAL-BE-057`'s
    `<think>` block), never trusted to have followed the "no fence, no
    semicolon" instruction exactly.
    """
    stripped = completion_text.strip()
    if not stripped or stripped.upper().startswith(_CANNOT_ANSWER_PREFIX):
        return None
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("sql"):
            stripped = stripped[3:]
        stripped = stripped.strip()
    return stripped.rstrip(";").strip() or None


async def _connection_engine(settings: Settings, config_encrypted: bytes) -> str | None:
    """Decrypt only enough of a live connection's stored config to know its
    engine — never logged, never returned beyond this one field. `None` when
    the stored credential cannot currently be decrypted
    (`askwell.crypto.CredentialsLocked`) — the same condition
    `askwell.connections.run_introspection` already treats as "this source
    cannot be used right now", so it is excluded from the candidate list
    here for the same reason rather than raising.
    """
    try:
        install_secret = crypto.load_or_create_install_secret(settings.install_secret_path)
        config = json.loads(
            crypto.decrypt(config_encrypted, crypto.derive_key(install_secret)).decode("utf-8")
        )
    except (crypto.CredentialsLocked, OSError, ValueError):
        return None
    engine = config.get("engine")
    return engine if isinstance(engine, str) else None


async def list_database_sources(session: AsyncSession, settings: Settings) -> list[DatabaseSource]:
    """Every `ready` dump, CSV or live-connection source — the candidates a
    database question could be answered from. A dump or CSV source always
    runs in the sandbox, which is always PostgreSQL (C3); a connection's
    engine is whatever it was created with, read from its own encrypted
    configuration.
    """
    rows = (
        await session.execute(
            text(
                "SELECT id, name, kind, config_encrypted FROM sources "
                "WHERE status = 'ready' AND kind = ANY(:kinds) ORDER BY name"
            ),
            {"kinds": list(_DATABASE_SOURCE_KINDS)},
        )
    ).all()
    sources: list[DatabaseSource] = []
    for source_id, name, kind, config_encrypted in rows:
        if kind == "connection":
            if config_encrypted is None:
                continue
            engine = await _connection_engine(settings, bytes(config_encrypted))
            if engine is None:
                continue
        else:
            engine = "postgresql"
        sources.append(DatabaseSource(id=source_id, name=name, kind=kind, engine=engine))
    return sources


async def _get_database_source(
    session: AsyncSession, settings: Settings, source_id: uuid.UUID
) -> DatabaseSource | None:
    for source in await list_database_sources(session, settings):
        if source.id == source_id:
            return source
    return None


async def select_database_source(
    session: AsyncSession,
    settings: Settings,
    *,
    question: str,
    source_id: uuid.UUID | None = None,
) -> SourceSelection:
    """Pick the one source a question's SQL should be generated against.

    `source_id`, when given, is an explicit scope (`askwell.ask`'s own
    "Ask about this source" precedent) — used directly with no
    disambiguation, and `NO_DATABASES` if it does not name a `ready`
    database-backed source, since there is then nothing to generate against
    either way.
    """
    if source_id is not None:
        source = await _get_database_source(session, settings, source_id)
        if source is None:
            return SourceSelection(reason=SelectionReason.NO_DATABASES, source=None)
        return SourceSelection(reason=SelectionReason.SELECTED, source=source)

    sources = await list_database_sources(session, settings)
    if not sources:
        return SourceSelection(reason=SelectionReason.NO_DATABASES, source=None)
    if len(sources) == 1:
        return SourceSelection(reason=SelectionReason.SELECTED, source=sources[0])

    matched: list[DatabaseSource] = []
    for source in sources:
        relevant = await retrieve_relevant_facts(
            session, question=question, source_id=source.id, fact_limit=0, note_limit=1
        )
        if relevant.notes:
            matched.append(source)

    if len(matched) == 1:
        return SourceSelection(reason=SelectionReason.SELECTED, source=matched[0])
    if not matched:
        # Nothing about any connected database looks relevant — the caller's
        # own job, not this function's, to fall back to document retrieval.
        return SourceSelection(reason=SelectionReason.NO_DATABASES, source=None)
    return SourceSelection(reason=SelectionReason.AMBIGUOUS, source=None, candidates=tuple(matched))


async def generate_candidate_query(
    session: AsyncSession,
    settings: Settings,
    client: InferenceClient,
    *,
    question: str,
    source_id: uuid.UUID | None = None,
) -> GenerationResult:
    """Retrieve schema, notes and memory for `question`, then generate one
    candidate query. Never executes or validates it — see the module
    docstring. Every successful generation is recorded to the decisions
    store with the query text, whether or not anything downstream ever
    validates or runs it (the ticket's own Audit Requirement) — nothing
    later in the pipeline can retroactively decide this step never
    happened.
    """
    selection = await select_database_source(
        session, settings, question=question, source_id=source_id
    )
    if selection.reason == SelectionReason.NO_DATABASES:
        return GenerationResult(reason=GenerationReason.NO_DATABASES, query=None)
    if selection.reason == SelectionReason.AMBIGUOUS:
        return GenerationResult(
            reason=GenerationReason.AMBIGUOUS, query=None, candidates=selection.candidates
        )
    source = selection.source
    assert source is not None

    relevant: RelevantMemory = await retrieve_relevant_facts(
        session, question=question, source_id=source.id, note_limit=SCHEMA_NOTE_LIMIT
    )
    if not relevant.notes:
        # Nothing about this source's schema bears on the question at all —
        # the ticket's own "not about data at all" edge case. The caller
        # routes to document retrieval instead; this module does not know
        # how to do that itself.
        return GenerationResult(reason=GenerationReason.NOT_A_DATABASE_QUESTION, query=None)

    composed = compose_sql_generation(question, source.engine, relevant.notes, relevant.facts)
    prompt = f"{composed.system_prompt}\n\n{composed.user_content}"
    completion = await client.generate(
        prompt, max_tokens=SQL_MAX_TOKENS, temperature=SQL_TEMPERATURE
    )
    query_text = _extract_query(completion.text)
    if query_text is None:
        return GenerationResult(reason=GenerationReason.NOT_A_DATABASE_QUESTION, query=None)

    generated = GeneratedQuery(
        query=query_text,
        engine=source.engine,
        prompt_version=composed.prompt_version,
        source_id=source.id,
        schema_note_ids=tuple(note.id for note in relevant.notes),
        memory_fact_ids=tuple(fact.id for fact in relevant.facts),
        injection_flagged=composed.injection_flagged,
        injection_patterns=composed.injection_patterns,
    )
    await record(
        session,
        Store.DECISIONS,
        SQL_GENERATED,
        {
            "source_id": str(source.id),
            "engine": source.engine,
            "query": query_text,
            "prompt_version": composed.prompt_version,
            "schema_note_ids": [str(i) for i in generated.schema_note_ids],
            "memory_fact_ids": [str(i) for i in generated.memory_fact_ids],
            "injection_flagged": generated.injection_flagged,
        },
    )
    log.info(
        "sql_generated",
        source_id=str(source.id),
        engine=source.engine,
        schema_notes=len(relevant.notes),
    )
    return GenerationResult(reason=GenerationReason.GENERATED, query=generated)
