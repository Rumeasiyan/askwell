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

**One correction path, whichever screen calls it.** `M3-CORRECT-BE-082`:
`correct_memory_fact`/`correct_schema_note`/`delete_memory_fact`/
`delete_schema_note` are that path — a chip in an answer and the memory
screen both end up calling exactly these, so "correcting from a chip and
from the memory screen produce identical results" is true by construction
rather than by keeping two call sites in sync. Three things beyond plain
supersession the ticket adds here:

- **The active row is locked (`FOR UPDATE`) before anything else runs.**
  Two corrections of the same fact arriving close together — a chip and the
  memory screen, or a doubled click — must not interleave; the second
  request's `SELECT ... FOR UPDATE` simply waits for the first transaction
  to commit or roll back, then sees whatever it left behind.
- **Correcting to the identical value is a no-op.** No new row, no
  supersession, no `memory_superseded`/`schema_note_superseded` record, and
  nothing queued to re-process — `Reprocessing(changed=False)` is what a
  caller reads to show "nothing changed" instead of a false confirmation.
- **A real change queues re-processing** through `askwell.reapply` — the
  same dependency resolution `askwell.review.answer_clarification` uses,
  run here with no clarification and no evidence (a correction from a chip
  or the memory screen names neither). A fact with no `source_id` — manual,
  free-standing knowledge with nothing to re-embed — resolves to nothing to
  queue, honestly, rather than guessing at a source.
"""

import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from askwell.audit import Store, record
from askwell.config import Settings
from askwell.db.engine import session_scope
from askwell.db.models import FACT_KINDS
from askwell.logging import get_logger
from askwell.retrieve import TEXT_SEARCH_CONFIG

log = get_logger(__name__)

# `M3-APPLY-RET-078`: how many active facts/notes ever reach one prompt,
# regardless of how many match — "a large memory store — retrieval is
# bounded, not everything injected" is the ticket's own edge case. Small on
# purpose: this is background context for a document answer, not the answer
# itself, and `docs/memory-and-clarification.md` §8's cap on inference
# already accepts that not everything visible in the inspector need be
# retrieved for a given question.
RELEVANT_FACT_LIMIT = 5
RELEVANT_NOTE_LIMIT = 5

MEMORY_WRITTEN = "memory_written"
MEMORY_DISCARDED = "memory_discarded"
MEMORY_SUPERSEDED = "memory_superseded"
MEMORY_DELETED = "memory_deleted"
SCHEMA_NOTE_WRITTEN = "schema_note_written"
SCHEMA_NOTE_DISCARDED = "schema_note_discarded"
SCHEMA_NOTE_SUPERSEDED = "schema_note_superseded"
SCHEMA_NOTE_DELETED = "schema_note_deleted"

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


@dataclass(frozen=True, slots=True)
class RelevantMemory:
    """What `retrieve_relevant_facts` found for one question — bounded, and
    kept as two separate lists rather than one merged one, since a caller
    composing a prompt labels and delimits them differently
    (`docs/memory-and-clarification.md` §3: "two stores, different shapes").
    """

    facts: list[MemoryFact]
    notes: list[SchemaNote]


@dataclass(frozen=True, slots=True)
class Reprocessing:
    """What a correction or deletion just queued, named specifically enough
    for the caller — chip or memory screen — to confirm it rather than show
    a generic toast. `changed=False` is the "correcting to the same value"
    edge case: nothing superseded, nothing queued, say so.
    """

    count: int
    label: str
    changed: bool


NOTHING_CHANGED = Reprocessing(count=0, label="Nothing changed.", changed=False)
_NOTHING_TO_REPROCESS = Reprocessing(count=0, label="Nothing to re-process.", changed=True)


@dataclass(frozen=True, slots=True)
class CorrectionOutcome:
    fact_id: uuid.UUID
    reprocessing: Reprocessing
    reapply_job_id: uuid.UUID | None


@dataclass(frozen=True, slots=True)
class DeletionOutcome:
    reprocessing: Reprocessing
    reapply_job_id: uuid.UUID | None


@dataclass(frozen=True, slots=True)
class FactDetail:
    """What a chip's popover needs, whichever kind of fact it names —
    `M3-CORRECT-FE-081`'s own two edge cases: "how many answers used it"
    and "the answer used a version since superseded". `current` is only
    ever one level deep (the active row for the same subject/position, not
    the full chain to it) — a popover shows where things stand now, not a
    history, which `docs/ux/memory.md` §4 reserves for the memory screen.
    """

    fact_kind: str
    id: uuid.UUID
    subject: str
    value: str
    origin: str
    created_at: Any
    usage_count: int
    active: bool
    current: "FactDetail | None"


async def _reprocess_subject(
    session: AsyncSession, *, subject: str, source_id: uuid.UUID | None, memory_id: uuid.UUID | None
) -> tuple[Reprocessing, uuid.UUID | None]:
    """Queue re-processing of whatever a corrected or deleted subject
    affects, via `askwell.reapply`'s dependency resolution — the exact
    machinery `askwell.review.answer_clarification` already uses, called
    here with no clarification and no evidence, since a correction from a
    chip or the memory screen names neither.

    `memory_id` is the *new* fact's id when one exists (a correction, not a
    deletion) — `askwell.reapply.run_job` reads it back to promote a
    matching inferred schema note to the corrected value, the same way it
    already does for a clarification's answer.
    """
    if source_id is None:
        return _NOTHING_TO_REPROCESS, None

    from askwell import reapply

    dependencies = await reapply.resolve_dependencies(
        session,
        source_id=source_id,
        subject=subject,
        evidence=None,
        options=None,
        clarification_id=None,
    )
    if memory_id is None:
        # A deletion, or a schema-note correction (which carries its answer
        # via `description`, not `memory`): no `memory` row exists for
        # `reapply.run_job` to read an answer from, so a `schema_note`
        # dependency here has nothing to promote a matching inferred note
        # to. Dropped rather than promoted with an empty string.
        dependencies = [d for d in dependencies if d.kind != "schema_note"]
    if not dependencies:
        return _NOTHING_TO_REPROCESS, None

    documents = {d.label for d in dependencies if d.kind == "chunk"}
    if documents:
        count = len(documents)
        label = f"Re-reading {count} document{'' if count == 1 else 's'}."
    else:
        count = len(dependencies)
        label = f"Re-checking {count} item{'' if count == 1 else 's'}."

    job_id = await reapply.enqueue(
        session,
        subject=subject,
        source_id=source_id,
        evidence=None,
        options=None,
        clarification_id=None,
        memory_id=memory_id,
        dependencies=dependencies,
    )
    return Reprocessing(count=count, label=label, changed=True), job_id


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
    user-origin write, conversely, retires any active fact for the same
    subject — inferred or user-origin — the same way `correct_memory_fact`
    would, so two user answers for one subject never sit active side by
    side; only the later one does.
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
    elif confidence is None:
        confidence = FULL_CONFIDENCE

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
        # Retire whatever was active for this subject — inferred guess or a
        # prior user answer alike — so a second user-origin write supersedes
        # instead of leaving two active facts for one subject.
        superseded = await session.execute(
            text(
                "UPDATE memory SET superseded_by = :fact_id "
                "WHERE subject = :subject AND superseded_by IS NULL "
                "AND id != :fact_id RETURNING id"
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
) -> CorrectionOutcome:
    """Supersede an active, user-origin fact with a new value — the one
    correction path `M3-CORRECT-BE-082` asks for, whether the caller is a
    chip in an answer or the memory screen.

    The old row survives untouched except for `superseded_by`, so its value
    stays readable in history exactly as it was recorded. The row is locked
    (`FOR UPDATE`) before anything is read, so a second correction of the
    same fact arriving mid-transaction serialises behind this one rather
    than interleaving with it. Correcting to the identical value writes
    nothing and queues nothing — `CorrectionOutcome.reprocessing.changed` is
    `False` — since there is no new value to supersede with.
    """
    current = await session.execute(
        text(
            "SELECT subject, fact, origin, source_id FROM memory "
            "WHERE id = :id AND superseded_by IS NULL FOR UPDATE"
        ),
        {"id": fact_id},
    )
    row = current.first()
    if row is None:
        raise FactNotFound(str(fact_id))
    subject, current_fact, current_origin, source_id = row
    if current_origin not in _USER_MEMORY_ORIGINS:
        raise CannotCorrectInference(str(fact_id))

    if fact == current_fact:
        return CorrectionOutcome(fact_id=fact_id, reprocessing=NOTHING_CHANGED, reapply_job_id=None)

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

    reprocessing, job_id = await _reprocess_subject(
        session, subject=subject, source_id=source_id, memory_id=new_id
    )
    return CorrectionOutcome(fact_id=new_id, reprocessing=reprocessing, reapply_job_id=job_id)


async def delete_memory_fact(session: AsyncSession, *, fact_id: uuid.UUID) -> DeletionOutcome:
    """Delete an active fact outright. `docs/ux/memory.md` §4: "Stops applying
    immediately. Recorded in the decisions log."

    Unlike a correction, there is no replacement row — the value itself is
    gone from `memory`, and the decisions record is what lets the memory
    screen's history still say what it was and when it went. The row is
    locked first so a concurrent correction of the same fact cannot race the
    delete. Deletion queues re-processing the same shape a correction does
    (`_reprocess_subject`, `memory_id=None` since there is no new value for
    a promoted schema note to adopt) — `M3-CORRECT-BE-082`'s "deletion
    follows the same shape, minus the new fact".
    """
    current = await session.execute(
        text(
            "SELECT subject, fact, origin, source_id FROM memory "
            "WHERE id = :id AND superseded_by IS NULL FOR UPDATE"
        ),
        {"id": fact_id},
    )
    row = current.first()
    if row is None:
        raise FactNotFound(str(fact_id))
    subject, fact, origin, source_id = row

    await session.execute(text("DELETE FROM memory WHERE id = :id"), {"id": fact_id})
    await record(
        session,
        Store.DECISIONS,
        MEMORY_DELETED,
        {"fact_id": str(fact_id), "subject": subject, "fact": fact, "origin": origin},
    )
    log.info("memory_deleted", fact_id=str(fact_id), subject=subject)

    reprocessing, job_id = await _reprocess_subject(
        session, subject=subject, source_id=source_id, memory_id=None
    )
    return DeletionOutcome(reprocessing=reprocessing, reapply_job_id=job_id)


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
    position an active `user`-origin note already covers. A user-origin
    write retires any active note for the same position — inferred or a
    prior user note alike — mirroring `write_memory_fact`.
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
    elif confidence is None:
        confidence = FULL_CONFIDENCE

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
        # note for the same position — guess or prior user note — rather
        # than leaving two active.
        superseded = await session.execute(
            text(
                "UPDATE schema_notes SET superseded_by = :note_id "
                "WHERE source_id = :source_id AND table_name = :table_name "
                "AND column_name IS NOT DISTINCT FROM :column_name "
                "AND superseded_by IS NULL AND id != :note_id "
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
) -> CorrectionOutcome:
    """Supersede an active note with a user-supplied correction — the schema-
    note half of the one correction path `correct_memory_fact` documents:
    row locked first, identical-value is a no-op, a real change queues
    re-processing keyed on `column_name or table_name` as the subject (the
    same name a clarification about this position would carry, so a stale
    pending question about it is dismissed the same way an answered
    clarification's would be).
    """
    current = await session.execute(
        text(
            "SELECT source_id, table_name, column_name, description, origin FROM schema_notes "
            "WHERE id = :id AND superseded_by IS NULL FOR UPDATE"
        ),
        {"id": note_id},
    )
    row = current.first()
    if row is None:
        raise FactNotFound(str(note_id))
    source_id, table_name, column_name, current_description, current_origin = row
    if current_origin != "user":
        raise CannotCorrectInference(str(note_id))

    if description == current_description:
        return CorrectionOutcome(fact_id=note_id, reprocessing=NOTHING_CHANGED, reapply_job_id=None)

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

    subject = column_name or table_name
    reprocessing, job_id = await _reprocess_subject(
        session, subject=subject, source_id=source_id, memory_id=None
    )
    return CorrectionOutcome(fact_id=new_id, reprocessing=reprocessing, reapply_job_id=job_id)


async def delete_schema_note(session: AsyncSession, *, note_id: uuid.UUID) -> DeletionOutcome:
    """Delete an active note outright — the schema-notes counterpart of
    `delete_memory_fact`, same shape, same reasoning, including queuing
    re-processing for whatever depended on it."""
    current = await session.execute(
        text(
            "SELECT source_id, table_name, column_name, description, origin FROM schema_notes "
            "WHERE id = :id AND superseded_by IS NULL FOR UPDATE"
        ),
        {"id": note_id},
    )
    row = current.first()
    if row is None:
        raise FactNotFound(str(note_id))
    source_id, table_name, column_name, description, origin = row

    await session.execute(text("DELETE FROM schema_notes WHERE id = :id"), {"id": note_id})
    await record(
        session,
        Store.DECISIONS,
        SCHEMA_NOTE_DELETED,
        {
            "note_id": str(note_id),
            "source_id": str(source_id),
            "table_name": table_name,
            "column_name": column_name,
            "description": description,
            "origin": origin,
        },
    )
    log.info("schema_note_deleted", note_id=str(note_id), table_name=table_name)

    subject = column_name or table_name
    reprocessing, job_id = await _reprocess_subject(
        session, subject=subject, source_id=source_id, memory_id=None
    )
    return DeletionOutcome(reprocessing=reprocessing, reapply_job_id=job_id)


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


# --- the chip: one entrypoint across both kinds ---------------------------
#
# `M3-CORRECT-FE-081`. `askwell.memory` had every write-side primitive this
# needs (`M3-STORE-BE-076`, `M3-CORRECT-BE-082`) but no HTTP surface — the
# same gap `M3-REVIEW-BE-072a`'s own docstring names for `clarifications`:
# logic with nothing exposing it, until whichever ticket first needed one
# built it. `docs/BRAIN.md`'s own `M3-CORRECT-BE-082` entry says this
# plainly: "no route exposes this path over HTTP yet — that is the first
# thing whichever of those three starts next will need." This is that.


async def get_fact_detail(
    session: AsyncSession, *, fact_kind: str, fact_id: uuid.UUID
) -> FactDetail | None:
    """Everything a chip's popover shows, `None` if `fact_id` names nothing
    at all (a stale link, not a refusal `correct`/`delete` should ever hit
    since those reject by locking the row, not by a prior read).

    `current` is only populated when this row is no longer active — the
    ticket's own "answer used an earlier version" edge case — and is the
    active row for the same subject (memory) or table/column position
    (schema note), which retrieval-time precedence (`get_active_memory_facts`/
    `get_active_schema_notes`, both already user-before-inferred,
    newer-before-older) picks out as its first result.
    """
    if fact_kind == "memory":
        row = (
            await session.execute(
                text(
                    "SELECT id, subject, fact, origin, created_at, superseded_by "
                    "FROM memory WHERE id = :id"
                ),
                {"id": fact_id},
            )
        ).first()
        if row is None:
            return None
        id_, subject, fact, origin, created_at, superseded_by = row
        current = None
        if superseded_by is not None:
            active = await get_active_memory_facts(session, subject=subject)
            if active:
                head = active[0]
                current = FactDetail(
                    fact_kind="memory",
                    id=head.id,
                    subject=head.subject,
                    value=head.fact,
                    origin=head.origin,
                    created_at=head.created_at,
                    usage_count=await _usage_count(session, fact_kind="memory", fact_id=head.id),
                    active=True,
                    current=None,
                )
        return FactDetail(
            fact_kind="memory",
            id=id_,
            subject=subject,
            value=fact,
            origin=origin,
            created_at=created_at,
            usage_count=await _usage_count(session, fact_kind="memory", fact_id=id_),
            active=superseded_by is None,
            current=current,
        )
    if fact_kind == "schema_note":
        row = (
            await session.execute(
                text(
                    "SELECT id, source_id, table_name, column_name, description, "
                    "origin, created_at, superseded_by FROM schema_notes WHERE id = :id"
                ),
                {"id": fact_id},
            )
        ).first()
        if row is None:
            return None
        id_, source_id, table_name, column_name = row[0], row[1], row[2], row[3]
        description, origin, created_at, superseded_by = row[4], row[5], row[6], row[7]
        subject = f"{table_name}.{column_name}" if column_name else table_name
        current = None
        if superseded_by is not None:
            active_notes = await get_active_schema_notes(session, source_id=source_id)
            match = next(
                (
                    n
                    for n in active_notes
                    if n.table_name == table_name and n.column_name == column_name
                ),
                None,
            )
            if match is not None:
                current = FactDetail(
                    fact_kind="schema_note",
                    id=match.id,
                    subject=f"{match.table_name}.{match.column_name}"
                    if match.column_name
                    else match.table_name,
                    value=match.description,
                    origin=match.origin,
                    created_at=match.created_at,
                    usage_count=await _usage_count(
                        session, fact_kind="schema_note", fact_id=match.id
                    ),
                    active=True,
                    current=None,
                )
        return FactDetail(
            fact_kind="schema_note",
            id=id_,
            subject=subject,
            value=description,
            origin=origin,
            created_at=created_at,
            usage_count=await _usage_count(session, fact_kind="schema_note", fact_id=id_),
            active=superseded_by is None,
            current=current,
        )
    raise ValueError(fact_kind)


async def _usage_count(session: AsyncSession, *, fact_kind: str, fact_id: uuid.UUID) -> int:
    """How many answers cited this exact row — `fact_usage` is one row per
    `(message_id, fact_kind, fact_id)`, so counting it directly is exact,
    not an estimate (`docs/ux/memory.md` §3's "used in N answers" line)."""
    result = await session.execute(
        text("SELECT count(*) FROM fact_usage WHERE fact_kind = :fact_kind AND fact_id = :fact_id"),
        {"fact_kind": fact_kind, "fact_id": fact_id},
    )
    return int(result.scalar_one())


async def correct_fact(
    session: AsyncSession, *, fact_kind: str, fact_id: uuid.UUID, value: str
) -> CorrectionOutcome:
    """Correct a fact from its chip, whichever kind and whichever origin it
    currently carries.

    An active user-origin row corrects in place via `correct_memory_fact`/
    `correct_schema_note`. An active *inferred* row has nothing to correct
    — `memory.py`'s own module docstring: "there is nothing to correct
    about a guess nobody asserted" — so the chip's "Correct" there is really
    "assert this instead", which is `write_memory_fact`/`write_schema_note`
    with a user origin; that write already retires the inference the same
    way any user-origin write does (`write_memory_fact`'s own "a user-origin
    write retires any active fact for the same subject — inferred or
    user-origin"). Falling back on `CannotCorrectInference` rather than
    branching on origin up front means this stays correct even if a second
    correction of the same fact races in between the read and the write.
    """
    if fact_kind == "memory":
        try:
            return await correct_memory_fact(session, fact_id=fact_id, fact=value)
        except CannotCorrectInference:
            row = (
                await session.execute(
                    text(
                        "SELECT subject, source_id FROM memory "
                        "WHERE id = :id AND superseded_by IS NULL"
                    ),
                    {"id": fact_id},
                )
            ).first()
            if row is None:
                raise FactNotFound(str(fact_id)) from None
            subject, source_id = row
            new_id = await write_memory_fact(
                session, subject=subject, fact=value, origin="correction", source_id=source_id
            )
            assert new_id is not None, "a user-origin write is never discarded"
            reprocessing, job_id = await _reprocess_subject(
                session, subject=subject, source_id=source_id, memory_id=new_id
            )
            return CorrectionOutcome(
                fact_id=new_id, reprocessing=reprocessing, reapply_job_id=job_id
            )
    elif fact_kind == "schema_note":
        try:
            return await correct_schema_note(session, note_id=fact_id, description=value)
        except CannotCorrectInference:
            row = (
                await session.execute(
                    text(
                        "SELECT source_id, table_name, column_name FROM schema_notes "
                        "WHERE id = :id AND superseded_by IS NULL"
                    ),
                    {"id": fact_id},
                )
            ).first()
            if row is None:
                raise FactNotFound(str(fact_id)) from None
            source_id, table_name, column_name = row
            new_id = await write_schema_note(
                session,
                source_id=source_id,
                table_name=table_name,
                column_name=column_name,
                description=value,
                origin="user",
            )
            assert new_id is not None, "a user-origin write is never discarded"
            subject = column_name or table_name
            reprocessing, job_id = await _reprocess_subject(
                session, subject=subject, source_id=source_id, memory_id=None
            )
            return CorrectionOutcome(
                fact_id=new_id, reprocessing=reprocessing, reapply_job_id=job_id
            )
    else:
        raise ValueError(fact_kind)


async def delete_fact(
    session: AsyncSession, *, fact_kind: str, fact_id: uuid.UUID
) -> DeletionOutcome:
    """Delete a fact from its chip, whichever kind — `delete_memory_fact`/
    `delete_schema_note` need no origin branching, unlike correction."""
    if fact_kind == "memory":
        return await delete_memory_fact(session, fact_id=fact_id)
    if fact_kind == "schema_note":
        return await delete_schema_note(session, note_id=fact_id)
    raise ValueError(fact_kind)


# --- retrieval for answer composition -------------------------------------

# `plainto_tsquery` ANDs every term it parses, so a question with several
# content words would only match a fact containing all of them — wrong here,
# where the "question" is really "does anything in memory bear on this at
# all" and a fact is a few words long. Turning its `&`s into `|`s (the
# standard Postgres trick — there is no `orto_tsquery`) matches on any term
# instead, which is the right direction to err in for a small, personal
# store: a false-positive candidate costs a few extra lines in a prompt, a
# false negative is the exact "I told it this and it still didn't know"
# failure the ticket exists to prevent. An empty or all-stopword question
# parses to an empty tsquery, which matches nothing rather than raising.
_OR_MATCH = (
    "to_tsquery(:cfg, regexp_replace(plainto_tsquery(:cfg, :query)::text, ' & ', ' | ', 'g'))"
)


async def retrieve_relevant_facts(
    session: AsyncSession,
    *,
    question: str,
    source_id: uuid.UUID | None = None,
    fact_limit: int = RELEVANT_FACT_LIMIT,
    note_limit: int = RELEVANT_NOTE_LIMIT,
) -> RelevantMemory:
    """Active memory facts and schema notes whose text bears on `question`,
    bounded and ranked by relevance — the retrieval half of `M3-APPLY-RET-078`.

    Lexical full-text, not embedding similarity: `docs/memory-and-
    clarification.md`'s own line on `schema_notes` describes embedding as
    the eventual mechanism, but neither `memory` nor `schema_notes` has a
    populated embedding to search against yet (issue #292 has the detail).
    Full-text over the small, personal store this product assumes is a
    reasonable interim, not a silent downgrade dressed up as the real thing
    — this docstring and issue #292 both say so plainly.

    `memory` facts are never filtered by `source_id`: `docs/memory-and-
    clarification.md` §3 describes them as "not tied to a schema object" —
    an abbreviation explained once applies to every later question,
    regardless of which source that question is scoped to. `schema_notes`
    *are* tied to a source, so a source-scoped question only sees that
    source's notes; a whole-corpus question (`source_id is None`) sees all
    of them, same as `get_active_schema_notes`.

    Precedence within each bounded result follows `get_active_memory_facts`/
    `get_active_schema_notes`: relevance first, then user-origin before
    inferred, then newer before older — so a tie in relevance still prefers
    the fact the user actually stated.
    """
    fact_rows = (
        await session.execute(
            text(
                "SELECT m.id, m.subject, m.fact, m.origin, m.confidence, "
                "m.source_id, s.name, (s.deleted_at IS NOT NULL) AS source_deleted, "
                "m.created_at "
                "FROM memory m LEFT JOIN sources s ON s.id = m.source_id "
                "WHERE m.superseded_by IS NULL "
                "AND to_tsvector(:cfg, m.subject || ' ' || m.fact) @@ " + _OR_MATCH + " "
                "ORDER BY ts_rank(to_tsvector(:cfg, m.subject || ' ' || m.fact), "
                + _OR_MATCH
                + ") DESC, (m.origin != 'inferred') DESC, m.created_at DESC "
                "LIMIT :limit"
            ),
            {"cfg": TEXT_SEARCH_CONFIG, "query": question, "limit": fact_limit},
        )
    ).all()
    facts = [
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
        for row in fact_rows
    ]

    note_rows = (
        await session.execute(
            text(
                "SELECT id, source_id, table_name, column_name, description, origin, "
                "confidence, created_at FROM schema_notes "
                "WHERE superseded_by IS NULL "
                "AND (CAST(:source_id AS uuid) IS NULL OR source_id = :source_id) "
                "AND to_tsvector(:cfg, table_name || ' ' || coalesce(column_name, '') "
                "|| ' ' || description) @@ " + _OR_MATCH + " "
                "ORDER BY ts_rank(to_tsvector(:cfg, table_name || ' ' || coalesce(column_name, '') "
                "|| ' ' || description), " + _OR_MATCH + ") DESC, "
                "(origin != 'inferred') DESC, created_at DESC "
                "LIMIT :limit"
            ),
            {
                "cfg": TEXT_SEARCH_CONFIG,
                "query": question,
                "source_id": source_id,
                "limit": note_limit,
            },
        )
    ).all()
    notes = [
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
        for row in note_rows
    ]
    return RelevantMemory(facts=facts, notes=notes)


# --- HTTP -------------------------------------------------------------


def _fact_detail_json(detail: FactDetail) -> dict[str, Any]:
    return {
        "fact_kind": detail.fact_kind,
        "id": str(detail.id),
        "subject": detail.subject,
        "value": detail.value,
        "origin": detail.origin,
        "created_at": detail.created_at.isoformat() if detail.created_at is not None else None,
        "usage_count": detail.usage_count,
        "active": detail.active,
        "current": _fact_detail_json(detail.current) if detail.current is not None else None,
    }


def _reprocessing_json(reprocessing: Reprocessing) -> dict[str, Any]:
    return {
        "count": reprocessing.count,
        "label": reprocessing.label,
        "changed": reprocessing.changed,
    }


class CorrectFactRequest(BaseModel):
    value: str = Field(min_length=1, max_length=4096)


def register_memory(
    app: FastAPI, settings: Settings, factory: async_sessionmaker[AsyncSession]
) -> None:
    """The memory chip's own surface (`M3-CORRECT-FE-081`) — read what a
    popover needs, correct, delete. Register before the interface catch-all,
    same as every other route module."""

    @app.get("/memory/facts/{fact_kind}/{fact_id}")
    async def fact_detail_route(fact_kind: str, fact_id: uuid.UUID) -> JSONResponse:
        if fact_kind not in FACT_KINDS:
            return JSONResponse({"error": "No such fact kind."}, status_code=404)
        async with session_scope(factory) as db:
            detail = await get_fact_detail(db, fact_kind=fact_kind, fact_id=fact_id)
        if detail is None:
            return JSONResponse({"error": "No such fact."}, status_code=404)
        return JSONResponse(_fact_detail_json(detail))

    @app.post("/memory/facts/{fact_kind}/{fact_id}/correct")
    async def correct_fact_route(
        fact_kind: str, fact_id: uuid.UUID, body: CorrectFactRequest
    ) -> JSONResponse:
        if fact_kind not in FACT_KINDS:
            return JSONResponse({"error": "No such fact kind."}, status_code=404)
        try:
            async with session_scope(factory) as db:
                outcome = await correct_fact(
                    db, fact_kind=fact_kind, fact_id=fact_id, value=body.value
                )
        except FactNotFound:
            return JSONResponse({"error": "No such fact."}, status_code=404)
        if outcome.reapply_job_id is not None:
            from askwell import reapply

            # Best-effort wake-up over a durable queue, same shape as
            # `askwell.review.answer_route` — the row is already committed,
            # so a Redis hiccup costs a delay, not the re-processing itself.
            await reapply.dispatch(settings, [outcome.reapply_job_id])
        return JSONResponse(
            {
                "fact_id": str(outcome.fact_id),
                "reprocessing": _reprocessing_json(outcome.reprocessing),
                "reapply_job_id": (
                    str(outcome.reapply_job_id) if outcome.reapply_job_id is not None else None
                ),
            }
        )

    @app.post("/memory/facts/{fact_kind}/{fact_id}/delete")
    async def delete_fact_route(fact_kind: str, fact_id: uuid.UUID) -> JSONResponse:
        if fact_kind not in FACT_KINDS:
            return JSONResponse({"error": "No such fact kind."}, status_code=404)
        try:
            async with session_scope(factory) as db:
                outcome = await delete_fact(db, fact_kind=fact_kind, fact_id=fact_id)
        except FactNotFound:
            return JSONResponse({"error": "No such fact."}, status_code=404)
        if outcome.reapply_job_id is not None:
            from askwell import reapply

            await reapply.dispatch(settings, [outcome.reapply_job_id])
        return JSONResponse(
            {
                "reprocessing": _reprocessing_json(outcome.reprocessing),
                "reapply_job_id": (
                    str(outcome.reapply_job_id) if outcome.reapply_job_id is not None else None
                ),
            }
        )
