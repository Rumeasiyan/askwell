"""Interaction retention: prune what the window leaves behind.
`docs/audit-log.md` §8, ticket `M7-LOG-BE-154`.

**Decisions and memory are never pruned.** Only `audit_interactions` rows are
ever deleted here — nothing in this module touches `audit_decisions`,
`memory`, or `schema_notes`. That is the one line this ticket is not allowed
to cross, and it is enforced by construction: every statement in `run_job`
below names `audit_interactions` explicitly, never a table read from a
variable.

**Export first, always.** Pruning an interaction the user never got a copy of
destroys part of their own history with no way back — a stolen laptop with a
prune-happy retention window would be a worse outcome than the unbounded
store this feature exists to cap. `enqueue` refuses (`PruneNotExported`)
unless a completed, unfiltered log export already covers the window: any
`export_jobs` row with `status = 'done'`, `since IS NULL`, and
`until IS NULL` or `until >= cutoff`. A windowed export (`since` set) proves
nothing about records before it, so it does not count.

**A window that would prune nearly everything needs saying so out loud.**
`docs/PRD.md`'s own edge case: someone who fat-fingers a retention window
short enough to remove records from last week, not just last year, should be
stopped once, the way `askwell.log_export.ExportNotAcknowledged` stops an
export leaving a passphrase-protected library unencrypted.

**Deletion and its own decisions record are one transaction.** Unlike
`log_export`, which streams to disk across several transactions because a
file write cannot be rolled back, a prune is nothing but database rows: the
`DELETE` and the `interactions_pruned` record that explains it either both
happen or neither does. A worker killed mid-run leaves the chain exactly as
it was — `askwell.worker.startup`'s `resume` returns the job to `queued` and
a re-run recomputes the same cutoff from the job's own stored value, so
retrying is not distinguishable from running once.

**The boundary that keeps `askwell.audit.verify` honest.** Deleting the
*oldest* rows of a hash chain is, from the chain's own shape, indistinguishable
from someone deleting them by hand — that is exactly what `Break.UNLINKED`/
`MISSING_GENESIS` exist to catch. The `interactions_pruned` decisions record
carries `boundary_hash`: the hash of the last record this run deleted, which
is also the `prev_hash` every surviving record still chains to. `audit.verify`
treats a chain that starts there, instead of at `GENESIS`, as explained rather
than broken (issue #516).
"""

import calendar
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from askwell.audit import Store, record
from askwell.config import Settings
from askwell.db.engine import session_scope
from askwell.log_budget import get_retention_months
from askwell.logging import get_logger

log = get_logger(__name__)

PRUNE_ENQUEUED = "interaction_prune_enqueued"
PRUNE_COMPLETED = "interactions_pruned"

# A window whose cutoff would remove this fraction or more of what exists
# today needs the same explicit "yes, I understand" `log_export` already
# asks for when leaving a passphrase's protection — the ticket's own edge
# case, "a window shorter than the age of everything".
NEARLY_EVERYTHING_RATIO = 0.9


class PruneNotExported(RuntimeError):
    """Nothing has been exported to cover what this prune would remove."""


class PruneRequiresConfirmation(RuntimeError):
    """The current retention window would prune nearly every interaction."""

    def __init__(self, prunable: int, total: int) -> None:
        self.prunable = prunable
        self.total = total
        super().__init__(
            f"The current retention window would prune {prunable} of {total} "
            f"interactions — nearly everything. Confirm this is understood "
            f"before proceeding."
        )


@dataclass(frozen=True, slots=True)
class PruneJob:
    id: uuid.UUID
    status: str
    cutoff: datetime
    pruned_count: int
    boundary_hash: str | None
    error: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "status": self.status,
            "cutoff": self.cutoff.isoformat(),
            "pruned_count": self.pruned_count,
            "boundary_hash": self.boundary_hash,
            "error": self.error,
        }


def _subtract_months(when: datetime, months: int) -> datetime:
    """Calendar-month subtraction with no third-party dependency.

    A day that does not exist in the target month (31 March minus one month)
    clamps to that month's own last day rather than overflowing into the
    month after — the ordinary meaning of "a month ago" from the 31st.
    """
    total = when.year * 12 + (when.month - 1) - months
    year, month = divmod(total, 12)
    month += 1
    day = min(when.day, calendar.monthrange(year, month)[1])
    return when.replace(year=year, month=month, day=day)


async def _count_interactions(session: AsyncSession, *, before: datetime | None = None) -> int:
    if before is None:
        result = await session.execute(text(f"SELECT count(*) FROM {Store.INTERACTIONS.value}"))
    else:
        result = await session.execute(
            text(f"SELECT count(*) FROM {Store.INTERACTIONS.value} WHERE occurred_at < :before"),
            {"before": before},
        )
    return int(result.scalar_one())


async def _has_covering_export(session: AsyncSession, cutoff: datetime) -> bool:
    row = (
        await session.execute(
            text(
                "SELECT 1 FROM export_jobs WHERE status = 'done' AND since IS NULL "
                "AND (until IS NULL OR until >= :cutoff) LIMIT 1"
            ),
            {"cutoff": cutoff},
        )
    ).first()
    return row is not None


async def enqueue(
    session: AsyncSession, *, acknowledged_nearly_everything: bool = False
) -> uuid.UUID:
    """Record the intent to prune, after the two refusals this ticket names.

    The cutoff is computed once, here, and frozen onto the job row — a retry
    after a crash must prune exactly what this call decided, not whatever the
    retention setting happens to say by the time the worker gets to it.
    """
    months = await get_retention_months(session)
    cutoff = _subtract_months(datetime.now(UTC), months)

    total = await _count_interactions(session)
    prunable = await _count_interactions(session, before=cutoff)

    if prunable > 0:
        if not await _has_covering_export(session, cutoff):
            raise PruneNotExported(
                "Pruning would remove interactions that have never been exported. "
                "Export the log first — nothing is deleted until you have your own copy."
            )
        if prunable / total >= NEARLY_EVERYTHING_RATIO and not acknowledged_nearly_everything:
            raise PruneRequiresConfirmation(prunable, total)

    job_id = uuid.uuid4()
    await session.execute(
        text("INSERT INTO prune_jobs (id, cutoff) VALUES (:id, :cutoff)"),
        {"id": job_id, "cutoff": cutoff},
    )
    await record(
        session,
        Store.DECISIONS,
        PRUNE_ENQUEUED,
        {"job_id": str(job_id), "cutoff": cutoff.isoformat(), "prunable_count": str(prunable)},
    )
    log.info("log_prune_enqueued", job_id=str(job_id), prunable=prunable)
    return job_id


async def dispatch(settings: Settings, job_ids: list[uuid.UUID]) -> int:
    """Ask a worker to pick these up now. Best-effort, the same reasoning as
    `askwell.log_export.dispatch` — the job row is already committed, so a
    slow or absent Redis costs a delay, never the prune itself."""
    if not job_ids:
        return 0

    from arq import create_pool
    from redis.exceptions import RedisError

    from askwell.worker import redis_settings

    queue = redis_settings(settings)
    try:
        pool = await create_pool(queue)
    except (OSError, RedisError) as error:
        log.warning("log_prune_dispatch_unavailable", error=str(error), jobs=len(job_ids))
        return 0

    sent = 0
    try:
        for job_id in job_ids:
            job = await pool.enqueue_job("prune_job", str(job_id), _job_id=f"prune:{job_id}")
            if job is not None:
                sent += 1
    except (OSError, RedisError) as error:  # pragma: no cover - needs a mid-flight failure
        log.warning("log_prune_dispatch_failed", error=str(error))
    finally:
        await pool.aclose()
    return sent


async def resume(session: AsyncSession) -> list[uuid.UUID]:
    """Return a job a dead worker was holding back to `queued`. One worker,
    one machine — anything still `running` at startup is unfinished work
    from the previous process, the same reasoning `askwell.log_export.resume`
    applies. Safe here specifically because the delete and its decisions
    record are one transaction: `running` with nothing deleted yet and
    `running` with everything deleted and committed are the only two
    possible states, and the second one would already be `done`."""
    result = await session.execute(
        text(
            "UPDATE prune_jobs SET status = 'queued', started_at = NULL "
            "WHERE status = 'running' RETURNING id"
        )
    )
    return [row[0] for row in result.all()]


async def get_job(session: AsyncSession, job_id: uuid.UUID) -> PruneJob | None:
    row = (
        await session.execute(
            text(
                "SELECT id, status, cutoff, pruned_count, boundary_hash, error "
                "FROM prune_jobs WHERE id = :id"
            ),
            {"id": job_id},
        )
    ).first()
    if row is None:
        return None
    return PruneJob(*row)


async def run_job(sessions: async_sessionmaker[AsyncSession], job_id: uuid.UUID) -> None:
    """Delete every interaction older than the job's own frozen cutoff, and
    record what was removed. One transaction — see the module docstring for
    why that is what makes this resumable without a byte offset.
    """
    async with session_scope(sessions) as session:
        row = (
            await session.execute(
                text("SELECT cutoff, status FROM prune_jobs WHERE id = :id"), {"id": job_id}
            )
        ).first()
        if row is None:
            return
        cutoff = row[0]
        await session.execute(
            text(
                "UPDATE prune_jobs SET status = 'running', "
                "started_at = COALESCE(started_at, now()), error = NULL WHERE id = :id"
            ),
            {"id": job_id},
        )

    try:
        async with session_scope(sessions) as session:
            # Same advisory lock `askwell.audit.record` takes before reading
            # the chain's own tail, so a prune and a concurrently-arriving
            # interaction record never race over what the chain's head is.
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:store))"),
                {"store": str(Store.INTERACTIONS)},
            )
            rows = (
                await session.execute(
                    text(
                        f"SELECT id, hash, occurred_at FROM {Store.INTERACTIONS.value} "
                        f"WHERE occurred_at < :cutoff ORDER BY occurred_at ASC, id ASC"
                    ),
                    {"cutoff": cutoff},
                )
            ).all()

            if not rows:
                await session.execute(
                    text(
                        "UPDATE prune_jobs SET status = 'done', finished_at = now(), "
                        "pruned_count = 0 WHERE id = :id"
                    ),
                    {"id": job_id},
                )
                log.info("log_prune_done", job_id=str(job_id), pruned=0)
                return

            pruned_ids = [row[0] for row in rows]
            boundary_hash = rows[-1][1]
            range_start = rows[0][2]
            range_end = rows[-1][2]

            await session.execute(
                text(f"DELETE FROM {Store.INTERACTIONS.value} WHERE id = ANY(:ids)"),
                {"ids": pruned_ids},
            )
            await record(
                session,
                Store.DECISIONS,
                PRUNE_COMPLETED,
                {
                    "job_id": str(job_id),
                    "cutoff": cutoff.astimezone(UTC).isoformat(),
                    "pruned_count": str(len(pruned_ids)),
                    "range_start": range_start.astimezone(UTC).isoformat(),
                    "range_end": range_end.astimezone(UTC).isoformat(),
                    "boundary_hash": boundary_hash,
                },
            )
            await session.execute(
                text(
                    "UPDATE prune_jobs SET status = 'done', finished_at = now(), "
                    "pruned_count = :count, boundary_hash = :hash WHERE id = :id"
                ),
                {"id": job_id, "count": len(pruned_ids), "hash": boundary_hash},
            )
        log.info("log_prune_done", job_id=str(job_id), pruned=len(pruned_ids))
    except Exception as error:
        log.warning(
            "log_prune_failed", job_id=str(job_id), error=f"{type(error).__name__}: {error}"
        )
        async with session_scope(sessions) as session:
            await session.execute(
                text(
                    "UPDATE prune_jobs SET status = 'failed', finished_at = now(), "
                    "error = :error WHERE id = :id"
                ),
                {"id": job_id, "error": f"{type(error).__name__}: {error}"},
            )
        raise


# --- HTTP --------------------------------------------------------------


class CreatePruneRequest(BaseModel):
    acknowledged_nearly_everything: bool = False


def register_log_prune(
    app: FastAPI, settings: Settings, factory: async_sessionmaker[AsyncSession]
) -> None:
    """`POST /log-prune` enqueues and dispatches a job; `GET /log-prune/{id}`
    reads its result. No download route — a prune produces nothing to fetch,
    only fewer rows and the decisions record explaining why.
    """

    @app.post("/log-prune")
    async def create_prune(body: CreatePruneRequest) -> JSONResponse:
        try:
            async with session_scope(factory) as db:
                job_id = await enqueue(
                    db, acknowledged_nearly_everything=body.acknowledged_nearly_everything
                )
        except PruneNotExported as error:
            return JSONResponse({"error": str(error), "export_required": True}, status_code=400)
        except PruneRequiresConfirmation as error:
            return JSONResponse(
                {
                    "error": str(error),
                    "confirmation_required": True,
                    "prunable_count": error.prunable,
                    "total_count": error.total,
                },
                status_code=400,
            )

        await dispatch(settings, [job_id])
        async with session_scope(factory) as db:
            job = await get_job(db, job_id)
        assert job is not None  # just inserted, in the same request
        return JSONResponse(job.as_dict(), status_code=201)

    @app.get("/log-prune/{job_id}")
    async def read_prune(job_id: uuid.UUID) -> JSONResponse:
        async with session_scope(factory) as db:
            job = await get_job(db, job_id)
        if job is None:
            return JSONResponse({"error": "No such prune."}, status_code=404)
        return JSONResponse(job.as_dict())
