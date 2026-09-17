"""Re-processing what an answered clarification affects. `M3-APPLY-ING-080`.

`docs/memory-and-clarification.md` §2: "Answering one re-processes what
depends on it: re-embed affected chunks, update schema notes, re-resolve the
contradiction." `askwell.review.answer_clarification` already writes the
`memory` fact; this module is what makes that write actually change what
Askwell retrieves, rather than sitting in `memory` unread until the next full
re-index.

Same shape as `askwell.ingest`, deliberately smaller. A `reapply_jobs` row is
the durable record — written in the same transaction as the answer, so a job
that exists only in Redis is never the only place the intent to re-process
lives — and `arq` is the transport that wakes a worker to run it
(`dispatch`/`resume`, mirroring `askwell.ingest.dispatch`/`resume`).

**Dependency resolution is approximate on purpose.** The ticket's own
Assumption: "errs toward re-processing more rather than less." Which
documents an answer affects reuses exactly the evidence-derived set
`askwell.review._reprocessing_summary` already computes for the confirmation
toast (`review.documents_named_in_evidence`) — the material named to the user
and the material actually touched must be the same set, or the toast is a
promise nothing behind it keeps. Every chunk of every one of those documents
is queued, not a text-matched subset: a chunk can be relevant to a subject
without containing its literal spelling, and under-selecting here is the
failure this feature exists to prevent (`docs/memory-and-clarification.md`
§2's own reasoning for the loop existing at all).

**Three kinds of item, one shape.** A `chunk` item re-embeds one passage —
harmless even though nothing about a chunk's *content* changed, since the
literal instruction is "re-embed" and the ticket's own granularity note
treats this as the outer bound of scope, not a place to relitigate the
architecture. A `schema_note` item promotes a matching *inferred* schema
position to the user's actual answer (`askwell.memory.write_schema_note`,
`origin='user'`) — the concrete form "update schema notes" takes when the
clarification's subject names a table or column. A `conflict` item dismisses
another still-pending clarification asking the same question a different way
— "re-resolve the contradiction" for the case dependency resolution can act
on without guessing: a second question about a subject that already has an
answer is exactly what `askwell.clarify._known_facts` would have suppressed
had it run after this answer instead of before it.

**De-duplication is a database constraint, not a Python set.** The migration's
partial unique index on `(kind, target_id)` over `pending` rows is what makes
two answers naming the same chunk enqueue it once (`M3-APPLY-ING-080`'s own
edge case) — `enqueue` inserts with `ON CONFLICT ... DO NOTHING` and only
counts an item toward `total_items` if the insert actually happened. The
work still gets done, under whichever job's run reaches it first; the job
that lost the race simply reports a smaller number, which is honest rather
than double-counted.

**The source is never taken offline for this.** Every item updates the
target it re-processes in place, inside its own short transaction — a chunk
keeps its old embedding until the moment the new one replaces it, so
retrieval never sees a null. Nothing here locks a document or a source; a
question can be asked mid-run and gets answered from whatever is currently
committed, stale or fresh a row at a time.
"""

import asyncio
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from askwell.audit import Store, record
from askwell.config import Settings
from askwell.db.engine import session_scope
from askwell.logging import get_logger

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import async_sessionmaker

log = get_logger(__name__)

REAPPLY_JOB_ENQUEUED = "reapply_job_enqueued"
REAPPLY_ITEM_DONE = "reapply_item_done"
REAPPLY_ITEM_FAILED = "reapply_item_failed"
REAPPLY_JOB_CANCELLED = "reapply_job_cancelled"

# Three attempts, the same ceiling every other retry loop in this pipeline
# uses (`askwell.embed.EMBED_BATCH_MAX_ATTEMPTS`) — a genuinely transient
# cause clears within one or two, and anything that survives three is a fact
# about the machine, not bad luck. Past this an item is `failed` and visible
# for a person to retry rather than silently retried forever.
ITEM_MAX_ATTEMPTS = 3

# Linear, matching `askwell.embed.EMBED_BATCH_RETRY_DELAY_SECONDS` — a module
# constant rather than a literal so a test can monkeypatch it to `0.0`.
ITEM_RETRY_DELAY_SECONDS = 2.0


class Dependency:
    """One thing an answer's re-processing touches, before it is an item row."""

    __slots__ = ("kind", "label", "target_id")

    def __init__(self, kind: str, target_id: uuid.UUID, label: str) -> None:
        self.kind = kind
        self.target_id = target_id
        self.label = label


# --- dependency resolution ---------------------------------------------------


async def _affected_documents(
    session: AsyncSession,
    *,
    source_id: uuid.UUID,
    evidence: dict[str, Any] | None,
    options: list[str] | None,
) -> list[uuid.UUID]:
    """The same document set `askwell.review._reprocessing_summary` names to
    the user, resolved to ids rather than filenames — named documents where
    the evidence or the offered options say which ones, every live document
    in the source otherwise.
    """
    from askwell.review import documents_named_in_evidence

    named = sorted({*(options or []), *documents_named_in_evidence(evidence)})
    if named:
        rows = await session.execute(
            text(
                "SELECT id FROM documents WHERE source_id = :source_id "
                "AND filename = ANY(:names) AND deleted_at IS NULL AND superseded_by IS NULL"
            ),
            {"source_id": source_id, "names": named},
        )
    else:
        rows = await session.execute(
            text(
                "SELECT id FROM documents WHERE source_id = :source_id "
                "AND deleted_at IS NULL AND superseded_by IS NULL AND status = 'ready'"
            ),
            {"source_id": source_id},
        )
    return [row[0] for row in rows]


async def resolve_dependencies(
    session: AsyncSession,
    *,
    source_id: uuid.UUID,
    subject: str,
    evidence: dict[str, Any] | None,
    options: list[str] | None,
    clarification_id: uuid.UUID | None,
) -> list[Dependency]:
    """Chunks, schema notes and stale conflicts one answer affects.

    Never raises on an empty result — a manual memory correction, or a
    subject that named no document, legitimately touches nothing here.
    `clarification_id` is `None` for a correction that did not originate
    from answering a clarification (`askwell.memory.correct_memory_fact`
    and its siblings) — there is no clarification to exclude from the
    conflict search, so every pending clarification on this subject is a
    candidate.
    """
    dependencies: list[Dependency] = []

    document_ids = await _affected_documents(
        session, source_id=source_id, evidence=evidence, options=options
    )
    if document_ids:
        chunk_rows = await session.execute(
            text(
                "SELECT c.id, d.filename FROM chunks c JOIN documents d ON d.id = c.document_id "
                "WHERE c.document_id = ANY(:document_ids) AND c.content IS NOT NULL"
            ),
            {"document_ids": document_ids},
        )
        dependencies.extend(
            Dependency("chunk", chunk_id, filename) for chunk_id, filename in chunk_rows
        )

    # A subject matching a table or column position: the inferred note there
    # is what "update schema notes" means for this trigger set — a name-only
    # match is deliberate (`docs/backlog/M3-it-learns-my-material.md`'s own
    # Assumption for the sibling ticket that defined this precedence,
    # `M3-STORE-BE-076`: exact match only, never fuzzy).
    note_rows = await session.execute(
        text(
            "SELECT id, table_name, column_name FROM schema_notes "
            "WHERE source_id = :source_id AND origin = 'inferred' AND superseded_by IS NULL "
            "AND (lower(table_name) = lower(:subject) "
            "OR lower(column_name) = lower(:subject))"
        ),
        {"source_id": source_id, "subject": subject},
    )
    for note_id, table_name, column_name in note_rows:
        label = f"{table_name}.{column_name}" if column_name else table_name
        dependencies.append(Dependency("schema_note", note_id, label))

    # Another still-pending question asking about the same subject a
    # different source raised independently — `askwell.clarify._known_facts`
    # only suppresses a subject *already* covered at raise time, so two
    # sources can each raise their own pending clarification for the same
    # abbreviation or contradiction before either is answered.
    conflict_rows = await session.execute(
        text(
            "SELECT id, source_id::text FROM clarifications "
            "WHERE status = 'pending' "
            "AND (CAST(:id AS uuid) IS NULL OR id != :id) "
            "AND lower(subject) = lower(:subject)"
        ),
        {"id": clarification_id, "subject": subject},
    )
    dependencies.extend(
        Dependency("conflict", other_id, f"source {other_source}")
        for other_id, other_source in conflict_rows
    )

    return dependencies


# --- enqueue ------------------------------------------------------------


async def enqueue(
    session: AsyncSession,
    *,
    subject: str,
    source_id: uuid.UUID,
    evidence: dict[str, Any] | None,
    options: list[str] | None,
    clarification_id: uuid.UUID | None,
    memory_id: uuid.UUID | None,
    dependencies: list[Dependency] | None = None,
) -> uuid.UUID | None:
    """Resolve what this answer affects and record it as a job.

    Returns `None`, writing nothing, when there is nothing to re-process —
    the caller (`askwell.review.answer_clarification`, or
    `askwell.memory`'s correction path) then has no job to dispatch, and its
    own `reprocessing` summary still reads correctly. `clarification_id` and
    `memory_id` are both `None` for a correction that did not originate from
    answering a clarification.

    `dependencies`, when given, is used as-is instead of calling
    `resolve_dependencies` again — `askwell.memory`'s correction path
    already resolved them once to build its own summary, and a `memory_id`
    of `None` there means a `schema_note` dependency has no answer text to
    promote with, so it is filtered out before it ever reaches here.
    """
    if dependencies is None:
        dependencies = await resolve_dependencies(
            session,
            source_id=source_id,
            subject=subject,
            evidence=evidence,
            options=options,
            clarification_id=clarification_id,
        )
    if not dependencies:
        return None

    job_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO reapply_jobs (id, subject, source_id, clarification_id, memory_id) "
            "VALUES (:id, :subject, :source_id, :clarification_id, :memory_id)"
        ),
        {
            "id": job_id,
            "subject": subject,
            "source_id": source_id,
            "clarification_id": clarification_id,
            "memory_id": memory_id,
        },
    )

    total = 0
    for dependency in dependencies:
        # `ON CONFLICT DO NOTHING` against the migration's partial unique
        # index is the de-duplication rule: a `(kind, target_id)` already
        # `pending` under an earlier, unfinished job is left exactly as it
        # is, and this job simply does not count it as its own.
        inserted = await session.execute(
            text(
                "INSERT INTO reapply_items (id, job_id, kind, target_id, label) "
                "VALUES (:id, :job_id, :kind, :target_id, :label) "
                "ON CONFLICT (kind, target_id) WHERE status = 'pending' DO NOTHING "
                "RETURNING id"
            ),
            {
                "id": uuid.uuid4(),
                "job_id": job_id,
                "kind": dependency.kind,
                "target_id": dependency.target_id,
                "label": dependency.label,
            },
        )
        if inserted.first() is not None:
            total += 1

    if total == 0:
        # Every dependency was already queued under another job. This job
        # has nothing of its own to run, but it must not stay `queued`
        # forever with no worker ever picking it up for zero items — mark it
        # done immediately, since its work is, by definition, already in
        # flight elsewhere.
        await session.execute(
            text("UPDATE reapply_jobs SET status = 'done', finished_at = now() WHERE id = :id"),
            {"id": job_id},
        )
        return job_id

    await session.execute(
        text("UPDATE reapply_jobs SET total_items = :total WHERE id = :id"),
        {"id": job_id, "total": total},
    )
    await record(
        session,
        Store.DECISIONS,
        REAPPLY_JOB_ENQUEUED,
        {
            "job_id": str(job_id),
            "clarification_id": str(clarification_id),
            "subject": subject,
            "items": total,
        },
    )
    log.info("reapply_job_enqueued", job_id=str(job_id), subject=subject, items=total)
    return job_id


# --- dispatch and resume -----------------------------------------------


async def dispatch(settings: Settings, job_ids: list[uuid.UUID]) -> int:
    """Ask a worker to pick these up now. Best-effort, like `askwell.ingest.dispatch`
    — the rows are already committed, so a slow or absent Redis costs a delay
    up to the next `resume`, never the re-processing itself.
    """
    if not job_ids:
        return 0

    from arq import create_pool
    from redis.exceptions import RedisError

    from askwell.worker import redis_settings

    queue = redis_settings(settings)
    try:
        pool = await create_pool(queue)
    except (OSError, RedisError) as error:
        log.warning("reapply_dispatch_unavailable", error=str(error), jobs=len(job_ids))
        return 0

    sent = 0
    try:
        for job_id in job_ids:
            job = await pool.enqueue_job("reapply_job", str(job_id), _job_id=f"reapply:{job_id}")
            if job is not None:
                sent += 1
    except (OSError, RedisError) as error:  # pragma: no cover - needs a mid-flight failure
        log.warning("reapply_dispatch_failed", error=str(error))
    finally:
        await pool.aclose()
    return sent


async def resume(session: AsyncSession) -> list[uuid.UUID]:
    """Return a job a dead worker was holding back to `queued`.

    One worker, one machine — anything still `running` when this runs is by
    definition unfinished work from the previous process, the same reasoning
    `askwell.ingest.resume` applies to `ingest_jobs`. Returns the ids so the
    caller (`askwell.worker.startup`) can dispatch them straight back onto
    the queue — unlike `ingest_jobs`, nothing here reconciles on a timer, so
    a resumed job that is not re-dispatched here would sit `queued` until
    someone happened to hit the retry endpoint.
    """
    result = await session.execute(
        text(
            "UPDATE reapply_jobs SET status = 'queued', started_at = NULL "
            "WHERE status = 'running' RETURNING id"
        )
    )
    return [row[0] for row in result.all()]


# --- running one job ------------------------------------------------------


async def _reembed_chunk(session: AsyncSession, settings: Settings, chunk_id: uuid.UUID) -> None:
    from askwell.inference.client import InferenceClient

    row = (
        await session.execute(text("SELECT content FROM chunks WHERE id = :id"), {"id": chunk_id})
    ).first()
    if row is None or not row[0]:
        # The chunk is gone (document deleted or superseded since this item
        # was queued) or was already cleared — nothing to re-embed.
        return
    client = InferenceClient(settings)
    vectors = await client.embed([row[0]])
    await session.execute(
        text("UPDATE chunks SET embedding = :embedding WHERE id = :id"),
        {"embedding": str(vectors[0]), "id": chunk_id},
    )


async def _promote_schema_note(session: AsyncSession, note_id: uuid.UUID, answer: str) -> None:
    from askwell.memory import write_schema_note

    row = (
        await session.execute(
            text(
                "SELECT source_id, table_name, column_name FROM schema_notes "
                "WHERE id = :id AND origin = 'inferred' AND superseded_by IS NULL"
            ),
            {"id": note_id},
        )
    ).first()
    if row is None:
        # Already superseded (a second answer, or a manual edit) — nothing
        # left to promote.
        return
    source_id, table_name, column_name = row
    await write_schema_note(
        session,
        source_id=source_id,
        table_name=table_name,
        column_name=column_name,
        description=answer,
        origin="user",
        confidence=1.0,
    )


async def _dismiss_conflict(session: AsyncSession, clarification_id: uuid.UUID) -> None:
    result = await session.execute(
        text(
            "UPDATE clarifications SET status = 'dismissed' "
            "WHERE id = :id AND status = 'pending' RETURNING subject, source_id::text"
        ),
        {"id": clarification_id},
    )
    row = result.first()
    if row is None:
        return
    subject, source_id = row
    await record(
        session,
        Store.DECISIONS,
        "clarification_dismissed",
        {
            "clarification_id": str(clarification_id),
            "subject": subject,
            "source_id": source_id,
            "reason": "superseded_by_answer",
        },
    )


async def _process_item(
    sessions: "async_sessionmaker[AsyncSession]",
    settings: Settings,
    item_id: uuid.UUID,
    kind: str,
    target_id: uuid.UUID,
    answer: str,
) -> None:
    async with session_scope(sessions) as session:
        if kind == "chunk":
            await _reembed_chunk(session, settings, target_id)
        elif kind == "schema_note":
            await _promote_schema_note(session, target_id, answer)
        elif kind == "conflict":
            await _dismiss_conflict(session, target_id)
        await session.execute(
            text("UPDATE reapply_items SET status = 'done', done_at = now() WHERE id = :id"),
            {"id": item_id},
        )


async def run_job(
    sessions: "async_sessionmaker[AsyncSession]", settings: Settings, job_id: uuid.UUID
) -> None:
    """Process every pending item of one job, one small transaction each.

    Nothing here is locked for the duration — a document can be read,
    answered about, even deleted mid-run, and each item simply acts on
    whatever is true when its own transaction opens (`_reembed_chunk` and
    `_promote_schema_note` both check the row is still there and still in
    the state they expect before touching it).
    """
    async with session_scope(sessions) as session:
        job = (
            await session.execute(
                text("SELECT memory_id FROM reapply_jobs WHERE id = :id"), {"id": job_id}
            )
        ).first()
        if job is None:
            return
        memory_id = job[0]
        answer = ""
        if memory_id is not None:
            fact_row = (
                await session.execute(
                    text("SELECT fact FROM memory WHERE id = :id"), {"id": memory_id}
                )
            ).first()
            answer = fact_row[0] if fact_row else ""

        await session.execute(
            text(
                "UPDATE reapply_jobs SET status = 'running', "
                "started_at = COALESCE(started_at, now()) WHERE id = :id"
            ),
            {"id": job_id},
        )
        items = (
            await session.execute(
                text(
                    "SELECT id, kind, target_id, attempts FROM reapply_items "
                    "WHERE job_id = :job_id AND status = 'pending'"
                ),
                {"job_id": job_id},
            )
        ).all()

    done = failed = 0
    for item_id, kind, target_id, attempts in items:
        # Retried inline, to exhaustion, within this one job run — unlike
        # `ingest_jobs`, nothing periodically reconciles a `reapply_job` back
        # onto the queue, so an item left `pending` after a transient failure
        # with no further dispatch would simply never run again. Linear
        # backoff, same reasoning and the same ceiling as
        # `askwell.embed.EMBED_BATCH_MAX_ATTEMPTS`: a genuinely transient
        # cause clears within one or two tries.
        last_error: Exception | None = None
        succeeded = False
        for attempt in range(attempts + 1, ITEM_MAX_ATTEMPTS + 1):
            try:
                await _process_item(sessions, settings, item_id, kind, target_id, answer)
                succeeded = True
                break
            except Exception as error:
                last_error = error
                log.warning(
                    "reapply_item_retrying",
                    item_id=str(item_id),
                    kind=kind,
                    attempt=attempt,
                    max_attempts=ITEM_MAX_ATTEMPTS,
                    error=f"{type(error).__name__}: {error}",
                )
                if attempt < ITEM_MAX_ATTEMPTS:
                    await asyncio.sleep(ITEM_RETRY_DELAY_SECONDS * attempt)

        if succeeded:
            done += 1
            continue

        failed += 1
        async with session_scope(sessions) as session:
            await session.execute(
                text(
                    "UPDATE reapply_items SET attempts = :attempts, status = 'failed', "
                    "error = :error, done_at = now() WHERE id = :id"
                ),
                {"attempts": ITEM_MAX_ATTEMPTS, "error": str(last_error), "id": item_id},
            )
            await record(
                session,
                Store.DECISIONS,
                REAPPLY_ITEM_FAILED,
                {"job_id": str(job_id), "item_id": str(item_id), "kind": kind},
            )

    async with session_scope(sessions) as session:
        counts = (
            await session.execute(
                text(
                    "SELECT status, count(*) FROM reapply_items "
                    "WHERE job_id = :job_id GROUP BY status"
                ),
                {"job_id": job_id},
            )
        ).all()
        by_status: dict[str, int] = {status: count for status, count in counts}
        remaining_pending = by_status.get("pending", 0)
        status = (
            "queued" if remaining_pending else ("failed" if by_status.get("failed") else "done")
        )
        await session.execute(
            text(
                "UPDATE reapply_jobs SET done_items = :done, failed_items = :failed, "
                "status = :status, finished_at = :finished_at WHERE id = :id"
            ),
            {
                "done": by_status.get("done", 0),
                "failed": by_status.get("failed", 0),
                "status": status,
                "finished_at": None if status == "queued" else datetime.now(UTC),
                "id": job_id,
            },
        )

    log.info("reapply_job_finished", job_id=str(job_id), done=done, failed=failed)


# --- retry, status, and undo's own cancellation ----------------------------


async def get_job(session: AsyncSession, job_id: uuid.UUID) -> dict[str, Any] | None:
    """Per-item progress, `../ux/clarifications.md` §5's "Answered,
    re-processing ... Per-item progress"."""
    job = (
        await session.execute(
            text(
                "SELECT subject, status, total_items, done_items, failed_items "
                "FROM reapply_jobs WHERE id = :id"
            ),
            {"id": job_id},
        )
    ).first()
    if job is None:
        return None
    subject, status, total_items, done_items, failed_items = job
    items = (
        await session.execute(
            text(
                "SELECT kind, target_id::text, label, status, error FROM reapply_items "
                "WHERE job_id = :job_id ORDER BY created_at"
            ),
            {"job_id": job_id},
        )
    ).all()
    return {
        "id": str(job_id),
        "subject": subject,
        "status": status,
        "total_items": total_items,
        "done_items": done_items,
        "failed_items": failed_items,
        "items": [
            {"kind": kind, "target_id": target_id, "label": label, "status": s, "error": error}
            for kind, target_id, label, s, error in items
        ],
    }


async def retry_failed(session: AsyncSession, job_id: uuid.UUID) -> int | None:
    """Reset every `failed` item on this job back to `pending`, for the retry
    `../ux/clarifications.md` §5's failure state names. Returns `None` if the
    job does not exist, so the route can answer 404 rather than "0 requeued".
    """
    exists = (
        await session.execute(text("SELECT 1 FROM reapply_jobs WHERE id = :id"), {"id": job_id})
    ).first()
    if exists is None:
        return None
    result = await session.execute(
        text(
            "UPDATE reapply_items SET status = 'pending', attempts = 0, error = NULL "
            "WHERE job_id = :job_id AND status = 'failed' RETURNING id"
        ),
        {"job_id": job_id},
    )
    requeued = len(result.all())
    if requeued:
        await session.execute(
            text(
                "UPDATE reapply_jobs SET status = 'queued', failed_items = 0, finished_at = NULL "
                "WHERE id = :id"
            ),
            {"id": job_id},
        )
    return requeued


async def cancel_pending_for_clarification(
    session: AsyncSession, clarification_id: uuid.UUID
) -> int:
    """`../memory-and-clarification.md`'s own edge case: undo during
    re-processing. Not-yet-run items are cancelled outright — they would
    otherwise apply an answer that no longer exists — rather than left to run
    against a fact `askwell.review.undo_answer` just deleted. An item already
    `done` is a known gap (`docs/build-plan.md` ticket's own "Known gaps"):
    a chunk already re-embedded, or a schema note already promoted, stays as
    it is rather than being reverted, since the pre-answer state it would
    revert to is exactly what a fresh, correct answer would recompute anyway.
    """
    result = await session.execute(
        text(
            "UPDATE reapply_items SET status = 'failed', error = 'cancelled: answer undone', "
            "done_at = now() FROM reapply_jobs "
            "WHERE reapply_items.job_id = reapply_jobs.id "
            "AND reapply_jobs.clarification_id = :clarification_id "
            "AND reapply_items.status = 'pending' "
            "RETURNING reapply_items.job_id"
        ),
        {"clarification_id": clarification_id},
    )
    job_ids = {row[0] for row in result.all()}
    for job_id in job_ids:
        await session.execute(
            text("UPDATE reapply_jobs SET status = 'failed', finished_at = now() WHERE id = :id"),
            {"id": job_id},
        )
        await record(
            session,
            Store.DECISIONS,
            REAPPLY_JOB_CANCELLED,
            {"job_id": str(job_id), "clarification_id": str(clarification_id)},
        )
    return len(job_ids)
