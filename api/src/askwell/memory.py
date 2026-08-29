"""Writing and superseding `memory` and `schema_notes`. `M3-STORE-BE-076`.

`docs/memory-and-clarification.md` §3, §8. Two stores, one rule: a correction
supersedes, it never updates in place, and a fact nobody was asked about
never displaces one the user actually supplied.

**Supersession, not overwrite.** Both tables carry `superseded_by` pointing
forward to whatever replaced a row. The active value for a subject (or a
schema position) is always the row with `superseded_by IS NULL`; walking that
chain to its end is how "a fact superseded twice resolves to the newest"
holds without a separate "current" table that could drift from the history
it summarises.

**User-supplied always outranks inferred, and is never silently overwritten.**
An inference is a guess made because nobody could be asked; a user fact is
something the user actually said. Letting the guess replace the statement
would mean the one thing this feature promises — that correcting Askwell
sticks — does not actually hold. So an inference arriving for a subject (or
schema position) that already carries an active user-origin fact is
discarded outright, recorded as such, and never stored as a competing
low-confidence entry (`docs/memory-and-clarification.md` §1's own edge case).
Only a user-origin write may supersede a user-origin fact; that is what
`correct_memory_fact`/`correct_schema_note` are for, and they never touch a
row of `origin = 'inferred'` for the same reason there is nothing to
"correct" about a guess that was never asserted.

**Retrieval precedence is user over inferred, then later over earlier** —
the ordering `get_active_memory_facts`/`get_active_schema_notes` apply, not
a filter, since an inferred fact with no competing user fact is still worth
retrieving (`docs/memory-and-clarification.md` §8: "everything below the cap
... left visible ... so the user can correct it if they ever care").
"""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from askwell.audit import Store, record
from askwell.logging import get_logger

log = get_logger(__name__)

MEMORY_WRITTEN = "memory_written"
MEMORY_DISCARDED = "memory_discarded"
MEMORY_SUPERSEDED = "memory_superseded"
SCHEMA_NOTE_WRITTEN = "schema_note_written"
SCHEMA_NOTE_DISCARDED = "schema_note_discarded"
SCHEMA_NOTE_SUPERSEDED = "schema_note_superseded"

# Full confidence for anything the user actually said — asked-and-answered or
# a direct correction. Only an inference is uncertain.
FULL_CONFIDENCE = 1.0

_USER_MEMORY_ORIGINS = ("clarification", "correction", "manual")


class FactNotFound(LookupError):
    """The row targeted for correction is gone, or is no longer active."""


class CannotCorrectInference(ValueError):
    """A correction was aimed at an inferred fact or schema note.

    There is nothing to correct about a guess nobody asserted — the write
    path for that is a fresh user-origin fact, which then discards the
    inference by the ordinary precedence rule rather than superseding it.
    """


@dataclass(frozen=True, slots=True)
class MemoryFact:
    id: uuid.UUID
    subject: str
    fact: str
    origin: str
    confidence: float | None
    source_id: uuid.UUID | None
    source_name: str | None
    source_deleted: bool
    created_at: Any


@dataclass(frozen=True, slots=True)
class SchemaNote:
    id: uuid.UUID
    source_id: uuid.UUID
    table_name: str
    column_name: str | None
    description: str
    origin: str
    confidence: float | None
    created_at: Any


# --- memory -------------------------------------------------------------


async def write_memory_fact(
    session: AsyncSession,
    *,
    subject: str,
    fact: str,
    origin: str,
    confidence: float | None = None,
    source_id: uuid.UUID | None = None,
) -> uuid.UUID | None:
    """Write a new, active fact for `subject`.

    Returns the new row's id, or `None` if an inference was discarded
    because an active user-supplied fact already covers this subject. A
    user-origin write, conversely, retires any active inference for the
    same subject — the guess was standing in for an answer nobody had given
    yet, and now somebody has, so leaving it active would show two beliefs
    about the same subject side by side.
    """
    if origin == "inferred":
        existing = await session.execute(
            text(
                "SELECT 1 FROM memory WHERE subject = :subject "
                "AND superseded_by IS NULL AND origin != 'inferred' LIMIT 1"
            ),
            {"subject": subject},
        )
        if existing.first() is not None:
            await record(
                session,
                Store.DECISIONS,
                MEMORY_DISCARDED,
                {"subject": subject, "reason": "active user-supplied fact already exists"},
            )
            log.info("memory_discarded", subject=subject)
            return None

    fact_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO memory (id, subject, fact, origin, confidence, source_id) "
            "VALUES (:id, :subject, :fact, :origin, :confidence, :source_id)"
        ),
        {
            "id": fact_id,
            "subject": subject,
            "fact": fact,
            "origin": origin,
            "confidence": confidence,
            "source_id": source_id,
        },
    )
    await record(
        session,
        Store.DECISIONS,
        MEMORY_WRITTEN,
        {"fact_id": str(fact_id), "subject": subject, "origin": origin},
    )
    log.info("memory_written", fact_id=str(fact_id), subject=subject, origin=origin)

    if origin != "inferred":
        superseded = await session.execute(
            text(
                "UPDATE memory SET superseded_by = :fact_id "
                "WHERE subject = :subject AND superseded_by IS NULL "
                "AND origin = 'inferred' AND id != :fact_id RETURNING id"
            ),
            {"fact_id": fact_id, "subject": subject},
        )
        for (retired_id,) in superseded.all():
            await record(
                session,
                Store.DECISIONS,
                MEMORY_SUPERSEDED,
                {"old_fact_id": str(retired_id), "new_fact_id": str(fact_id), "subject": subject},
            )
    return fact_id


async def correct_memory_fact(
    session: AsyncSession,
    *,
    fact_id: uuid.UUID,
    fact: str,
    confidence: float = FULL_CONFIDENCE,
) -> uuid.UUID:
    """Supersede an active, user-origin fact with a new value.

    The old row survives untouched except for `superseded_by`, so its value
    stays readable in history exactly as it was recorded.
    """
    current = await session.execute(
        text(
            "SELECT subject, origin, source_id FROM memory WHERE id = :id AND superseded_by IS NULL"
        ),
        {"id": fact_id},
    )
    row = current.first()
    if row is None:
        raise FactNotFound(str(fact_id))
    subject, current_origin, source_id = row
    if current_origin not in _USER_MEMORY_ORIGINS:
        raise CannotCorrectInference(str(fact_id))

    new_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO memory (id, subject, fact, origin, confidence, source_id) "
            "VALUES (:id, :subject, :fact, 'correction', :confidence, :source_id)"
        ),
        {
            "id": new_id,
            "subject": subject,
            "fact": fact,
            "confidence": confidence,
            "source_id": source_id,
        },
    )
    await session.execute(
        text("UPDATE memory SET superseded_by = :new_id WHERE id = :id"),
        {"new_id": new_id, "id": fact_id},
    )
    await record(
        session,
        Store.DECISIONS,
        MEMORY_SUPERSEDED,
        {"old_fact_id": str(fact_id), "new_fact_id": str(new_id), "subject": subject},
    )
    log.info("memory_superseded", old_fact_id=str(fact_id), new_fact_id=str(new_id))
    return new_id


async def get_active_memory_facts(
    session: AsyncSession, *, subject: str | None = None
) -> list[MemoryFact]:
    """Active facts (`superseded_by IS NULL`), user-origin before inferred,
    newer before older within each — the retrieval-time precedence rule.
    """
    rows = await session.execute(
        text(
            "SELECT m.id, m.subject, m.fact, m.origin, m.confidence, "
            "m.source_id, s.name, (s.deleted_at IS NOT NULL) AS source_deleted, "
            "m.created_at "
            "FROM memory m LEFT JOIN sources s ON s.id = m.source_id "
            "WHERE m.superseded_by IS NULL "
            "AND (CAST(:subject AS text) IS NULL OR m.subject = :subject) "
            "ORDER BY (m.origin != 'inferred') DESC, m.created_at DESC"
        ),
        {"subject": subject},
    )
    return [
        MemoryFact(
            id=row[0],
            subject=row[1],
            fact=row[2],
            origin=row[3],
            confidence=float(row[4]) if row[4] is not None else None,
            source_id=row[5],
            source_name=row[6],
            source_deleted=bool(row[7]),
            created_at=row[8],
        )
        for row in rows
    ]


# --- schema notes ---------------------------------------------------------


async def write_schema_note(
    session: AsyncSession,
    *,
    source_id: uuid.UUID,
    table_name: str,
    column_name: str | None,
    description: str,
    origin: str,
    confidence: float | None = None,
) -> uuid.UUID | None:
    """Write a new, active note for one table/column position.

    Returns `None`, discarding the write, if an inference arrives for a
    position an active `user`-origin note already covers.
    """
    if origin == "inferred":
        existing = await session.execute(
            text(
                "SELECT 1 FROM schema_notes WHERE source_id = :source_id "
                "AND table_name = :table_name "
                "AND column_name IS NOT DISTINCT FROM :column_name "
                "AND superseded_by IS NULL AND origin = 'user' LIMIT 1"
            ),
            {"source_id": source_id, "table_name": table_name, "column_name": column_name},
        )
        if existing.first() is not None:
            await record(
                session,
                Store.DECISIONS,
                SCHEMA_NOTE_DISCARDED,
                {
                    "source_id": str(source_id),
                    "table_name": table_name,
                    "column_name": column_name,
                    "reason": "active user-supplied note already exists",
                },
            )
            log.info(
                "schema_note_discarded",
                source_id=str(source_id),
                table_name=table_name,
                column_name=column_name,
            )
            return None

    note_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO schema_notes "
            "(id, source_id, table_name, column_name, description, origin, confidence) "
            "VALUES (:id, :source_id, :table_name, :column_name, :description, "
            ":origin, :confidence)"
        ),
        {
            "id": note_id,
            "source_id": source_id,
            "table_name": table_name,
            "column_name": column_name,
            "description": description,
            "origin": origin,
            "confidence": confidence,
        },
    )
    await record(
        session,
        Store.DECISIONS,
        SCHEMA_NOTE_WRITTEN,
        {
            "note_id": str(note_id),
            "source_id": str(source_id),
            "table_name": table_name,
            "column_name": column_name,
            "origin": origin,
        },
    )
    log.info("schema_note_written", note_id=str(note_id), table_name=table_name)

    if origin != "inferred":
        # As in `write_memory_fact`: a user-supplied note retires any active
        # guess for the same position rather than leaving both active.
        superseded = await session.execute(
            text(
                "UPDATE schema_notes SET superseded_by = :note_id "
                "WHERE source_id = :source_id AND table_name = :table_name "
                "AND column_name IS NOT DISTINCT FROM :column_name "
                "AND superseded_by IS NULL AND origin = 'inferred' AND id != :note_id "
                "RETURNING id"
            ),
            {
                "note_id": note_id,
                "source_id": source_id,
                "table_name": table_name,
                "column_name": column_name,
            },
        )
        for (retired_id,) in superseded.all():
            await record(
                session,
                Store.DECISIONS,
                SCHEMA_NOTE_SUPERSEDED,
                {
                    "old_note_id": str(retired_id),
                    "new_note_id": str(note_id),
                    "table_name": table_name,
                },
            )
    return note_id


async def correct_schema_note(
    session: AsyncSession,
    *,
    note_id: uuid.UUID,
    description: str,
    confidence: float = FULL_CONFIDENCE,
) -> uuid.UUID:
    """Supersede an active note with a user-supplied correction."""
    current = await session.execute(
        text(
            "SELECT source_id, table_name, column_name, origin FROM schema_notes "
            "WHERE id = :id AND superseded_by IS NULL"
        ),
        {"id": note_id},
    )
    row = current.first()
    if row is None:
        raise FactNotFound(str(note_id))
    source_id, table_name, column_name, current_origin = row
    if current_origin != "user":
        raise CannotCorrectInference(str(note_id))

    new_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO schema_notes "
            "(id, source_id, table_name, column_name, description, origin, confidence) "
            "VALUES (:id, :source_id, :table_name, :column_name, :description, 'user', "
            ":confidence)"
        ),
        {
            "id": new_id,
            "source_id": source_id,
            "table_name": table_name,
            "column_name": column_name,
            "description": description,
            "confidence": confidence,
        },
    )
    await session.execute(
        text("UPDATE schema_notes SET superseded_by = :new_id WHERE id = :id"),
        {"new_id": new_id, "id": note_id},
    )
    await record(
        session,
        Store.DECISIONS,
        SCHEMA_NOTE_SUPERSEDED,
        {"old_note_id": str(note_id), "new_note_id": str(new_id), "table_name": table_name},
    )
    log.info("schema_note_superseded", old_note_id=str(note_id), new_note_id=str(new_id))
    return new_id


async def get_active_schema_notes(
    session: AsyncSession, *, source_id: uuid.UUID | None = None
) -> list[SchemaNote]:
    """Active notes, user-origin before inferred, newer before older within
    each — same precedence rule as memory, over a different shape.
    """
    rows = await session.execute(
        text(
            "SELECT id, source_id, table_name, column_name, description, origin, "
            "confidence, created_at FROM schema_notes "
            "WHERE superseded_by IS NULL "
            "AND (CAST(:source_id AS uuid) IS NULL OR source_id = :source_id) "
            "ORDER BY (origin != 'inferred') DESC, created_at DESC"
        ),
        {"source_id": source_id},
    )
    return [
        SchemaNote(
            id=row[0],
            source_id=row[1],
            table_name=row[2],
            column_name=row[3],
            description=row[4],
            origin=row[5],
            confidence=float(row[6]) if row[6] is not None else None,
            created_at=row[7],
        )
        for row in rows
    ]
