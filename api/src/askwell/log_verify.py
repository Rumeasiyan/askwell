"""Log verification: a background job that walks both audit stores' hash
chains and reports where, if anywhere, one breaks. `docs/audit-log.md` §4,
ticket `M7-LOG-FE-156`.

**Why this exists as a job, not just a request.** `askwell.audit.verify`
already proves a chain to Askwell itself — the `askwell-verify` command has
called it since `M0-DATA-OBS-015`. What that command cannot do is show
progress on a log large enough to take real time, or be interrupted, both
of which the settings screen's own ticket names as edge cases. This module
is the same shape as `askwell.log_export`: a durable row (`verify_jobs`) is
the record of what happened, `arq` is only the transport that wakes a worker
to act on it, and anything still `running` when the process starts is, on
one worker on one machine, unfinished work from last time rather than
something to trust.

**Cancellation is a flag on the row, not a second channel.** The job polls
its own `cancel_requested` column every `audit.verify`'s own
`progress_every` records — the same reasoning `askwell.model_download`'s
in-process cancel flag uses, adapted to a job that runs in a different
process than the request that asks it to stop.

**The result is logged once, at completion, to the decisions store** — the
ticket's own Audit Requirement. It names both stores' outcome, including a
break's record id, its date and what kind of break it was, so "did I check,
and what did it say" is answerable from the log itself without deriving it
from `verify_jobs`, whose retention policy is its own.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from askwell.audit import (
    Break,
    Store,
    VerificationInterrupted,
    VerificationResult,
    record,
    verify,
)
from askwell.config import Settings
from askwell.db.engine import session_scope
from askwell.logging import get_logger

log = get_logger(__name__)

VERIFY_JOB_COMPLETED = "log_verify_completed"

_STORE_PREFIX = {Store.DECISIONS: "decisions", Store.INTERACTIONS: "interactions"}


@dataclass(frozen=True, slots=True)
class StoreOutcome:
    total: int
    checked: int
    intact: bool | None
    break_id: uuid.UUID | None
    break_at: datetime | None
    break_reason: str | None
    break_detail: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "checked": self.checked,
            "intact": self.intact,
            "break_id": str(self.break_id) if self.break_id else None,
            "break_at": self.break_at.isoformat() if self.break_at else None,
            "break_reason": self.break_reason,
            "break_detail": self.break_detail,
        }


@dataclass(frozen=True, slots=True)
class VerifyJob:
    id: uuid.UUID
    status: str
    decisions: StoreOutcome
    interactions: StoreOutcome
    error: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "status": self.status,
            "decisions": self.decisions.as_dict(),
            "interactions": self.interactions.as_dict(),
            "error": self.error,
        }


# --- enqueue, dispatch, resume, cancel --------------------------------------


async def enqueue(session: AsyncSession) -> uuid.UUID:
    job_id = uuid.uuid4()
    await session.execute(text("INSERT INTO verify_jobs (id) VALUES (:id)"), {"id": job_id})
    log.info("log_verify_enqueued", job_id=str(job_id))
    return job_id


async def dispatch(settings: Settings, job_ids: list[uuid.UUID]) -> int:
    """Best-effort, the same reasoning as `askwell.log_export.dispatch` — the
    job row is already committed, so a slow or absent Redis costs a delay,
    never the verification itself."""
    if not job_ids:
        return 0

    from arq import create_pool
    from redis.exceptions import RedisError

    from askwell.worker import redis_settings

    queue = redis_settings(settings)
    try:
        pool = await create_pool(queue)
    except (OSError, RedisError) as error:
        log.warning("log_verify_dispatch_unavailable", error=str(error), jobs=len(job_ids))
        return 0

    sent = 0
    try:
        for job_id in job_ids:
            job = await pool.enqueue_job("verify_job", str(job_id), _job_id=f"verify:{job_id}")
            if job is not None:
                sent += 1
    except (OSError, RedisError) as error:  # pragma: no cover - needs a mid-flight failure
        log.warning("log_verify_dispatch_failed", error=str(error))
    finally:
        await pool.aclose()
    return sent


async def resume(session: AsyncSession) -> list[uuid.UUID]:
    """Return a job a dead worker was holding back to `queued`. One worker,
    one machine — anything still `running` at startup is unfinished work
    from the previous process, `askwell.log_export.resume`'s own reasoning."""
    result = await session.execute(
        text(
            "UPDATE verify_jobs SET status = 'queued', started_at = NULL "
            "WHERE status = 'running' RETURNING id"
        )
    )
    return [row[0] for row in result.all()]


async def request_cancel(session: AsyncSession, job_id: uuid.UUID) -> VerifyJob | None:
    """Ask a queued or running job to stop. A finished job's row is left
    alone — cancelling something already done or failed would misreport
    what actually happened."""
    await session.execute(
        text(
            "UPDATE verify_jobs SET cancel_requested = true "
            "WHERE id = :id AND status IN ('queued', 'running')"
        ),
        {"id": job_id},
    )
    return await get_job(session, job_id)


def _outcome_from_row(row: Any, prefix: str) -> StoreOutcome:
    return StoreOutcome(
        total=row[f"{prefix}_total"],
        checked=row[f"{prefix}_checked"],
        intact=row[f"{prefix}_intact"],
        break_id=row[f"{prefix}_break_id"],
        break_at=row[f"{prefix}_break_at"],
        break_reason=row[f"{prefix}_break_reason"],
        break_detail=row[f"{prefix}_break_detail"],
    )


async def get_job(session: AsyncSession, job_id: uuid.UUID) -> VerifyJob | None:
    result = await session.execute(
        text(
            "SELECT id, status, error, "
            "decisions_total, decisions_checked, decisions_intact, decisions_break_id, "
            "decisions_break_at, decisions_break_reason, decisions_break_detail, "
            "interactions_total, interactions_checked, interactions_intact, "
            "interactions_break_id, interactions_break_at, interactions_break_reason, "
            "interactions_break_detail "
            "FROM verify_jobs WHERE id = :id"
        ),
        {"id": job_id},
    )
    row = result.mappings().first()
    if row is None:
        return None
    return VerifyJob(
        id=row["id"],
        status=row["status"],
        error=row["error"],
        decisions=_outcome_from_row(row, "decisions"),
        interactions=_outcome_from_row(row, "interactions"),
    )


# --- running one job ---------------------------------------------------


async def _count(session: AsyncSession, store: Store) -> int:
    result = await session.execute(text(f"SELECT count(*) FROM {store.value}"))
    return int(result.scalar_one())


def _reason_value(result: VerificationResult) -> str | None:
    return result.reason.value if isinstance(result.reason, Break) else None


async def _verify_one_store(
    sessions: async_sessionmaker[AsyncSession],
    job_id: uuid.UUID,
    store: Store,
) -> VerificationResult | None:
    """Runs one store's walk with progress persisted to the job row and
    cancellation checked against it. Returns `None` if the job was cancelled
    mid-walk — the caller decides what that means for the job as a whole
    rather than this function inventing a fake result for it."""
    prefix = _STORE_PREFIX[store]

    async def on_progress(checked: int) -> None:
        async with session_scope(sessions) as progress_session:
            await progress_session.execute(
                text(f"UPDATE verify_jobs SET {prefix}_checked = :checked WHERE id = :id"),
                {"checked": checked, "id": job_id},
            )

    async def should_continue() -> bool:
        async with session_scope(sessions) as check_session:
            row = (
                await check_session.execute(
                    text("SELECT cancel_requested FROM verify_jobs WHERE id = :id"),
                    {"id": job_id},
                )
            ).first()
        return row is not None and not row[0]

    async with session_scope(sessions) as session:
        try:
            return await verify(
                session, store, on_progress=on_progress, should_continue=should_continue
            )
        except VerificationInterrupted:
            return None


async def run_job(
    sessions: async_sessionmaker[AsyncSession], settings: Settings, job_id: uuid.UUID
) -> None:
    """Verify both stores end to end: count, walk each with progress, record
    both outcomes on the job row and, once, as a single decisions record —
    the ticket's own "verification runs are logged with their result"."""
    async with session_scope(sessions) as session:
        decisions_total = await _count(session, Store.DECISIONS)
        interactions_total = await _count(session, Store.INTERACTIONS)
        await session.execute(
            text(
                "UPDATE verify_jobs SET status = 'running', "
                "started_at = COALESCE(started_at, now()), "
                "decisions_total = :dt, interactions_total = :it, error = NULL WHERE id = :id"
            ),
            {"id": job_id, "dt": decisions_total, "it": interactions_total},
        )

    try:
        decisions_result = await _verify_one_store(sessions, job_id, Store.DECISIONS)
        if decisions_result is None:
            await _mark_cancelled(sessions, job_id)
            return
        interactions_result = await _verify_one_store(sessions, job_id, Store.INTERACTIONS)
        if interactions_result is None:
            await _mark_cancelled(sessions, job_id)
            return

        async with session_scope(sessions) as session:
            await session.execute(
                text(
                    "UPDATE verify_jobs SET status = 'done', finished_at = now(), "
                    "decisions_checked = :dc, decisions_intact = :di, "
                    "decisions_break_id = :dbid, decisions_break_at = :dbat, "
                    "decisions_break_reason = :dbr, decisions_break_detail = :dbd, "
                    "interactions_checked = :ic, interactions_intact = :ii, "
                    "interactions_break_id = :ibid, interactions_break_at = :ibat, "
                    "interactions_break_reason = :ibr, interactions_break_detail = :ibd "
                    "WHERE id = :id"
                ),
                {
                    "id": job_id,
                    "dc": decisions_result.checked,
                    "di": decisions_result.intact,
                    "dbid": decisions_result.first_break,
                    "dbat": decisions_result.occurred_at,
                    "dbr": _reason_value(decisions_result),
                    "dbd": decisions_result.detail or None,
                    "ic": interactions_result.checked,
                    "ii": interactions_result.intact,
                    "ibid": interactions_result.first_break,
                    "ibat": interactions_result.occurred_at,
                    "ibr": _reason_value(interactions_result),
                    "ibd": interactions_result.detail or None,
                },
            )

            await record(
                session,
                Store.DECISIONS,
                VERIFY_JOB_COMPLETED,
                {
                    "job_id": str(job_id),
                    "decisions": {
                        "checked": decisions_result.checked,
                        "intact": decisions_result.intact,
                        "break_id": str(decisions_result.first_break)
                        if decisions_result.first_break
                        else None,
                        "break_at": decisions_result.occurred_at.isoformat()
                        if decisions_result.occurred_at
                        else None,
                        "break_reason": _reason_value(decisions_result),
                    },
                    "interactions": {
                        "checked": interactions_result.checked,
                        "intact": interactions_result.intact,
                        "break_id": str(interactions_result.first_break)
                        if interactions_result.first_break
                        else None,
                        "break_at": interactions_result.occurred_at.isoformat()
                        if interactions_result.occurred_at
                        else None,
                        "break_reason": _reason_value(interactions_result),
                    },
                },
            )
        log.info(
            "log_verify_done",
            job_id=str(job_id),
            decisions_intact=decisions_result.intact,
            interactions_intact=interactions_result.intact,
        )
    except Exception as error:
        log.warning(
            "log_verify_failed", job_id=str(job_id), error=f"{type(error).__name__}: {error}"
        )
        async with session_scope(sessions) as session:
            await session.execute(
                text(
                    "UPDATE verify_jobs SET status = 'failed', finished_at = now(), "
                    "error = :error WHERE id = :id"
                ),
                {"id": job_id, "error": f"{type(error).__name__}: {error}"},
            )
        raise


async def _mark_cancelled(sessions: async_sessionmaker[AsyncSession], job_id: uuid.UUID) -> None:
    async with session_scope(sessions) as session:
        await session.execute(
            text("UPDATE verify_jobs SET status = 'cancelled', finished_at = now() WHERE id = :id"),
            {"id": job_id},
        )
    log.info("log_verify_cancelled", job_id=str(job_id))


# --- HTTP --------------------------------------------------------------


def register_log_verify(
    app: FastAPI, settings: Settings, factory: async_sessionmaker[AsyncSession]
) -> None:
    """`POST /log-verify` enqueues and dispatches a job; `GET /log-verify/{id}`
    reads its progress and result; `POST /log-verify/{id}/cancel` asks a
    running one to stop. No delete or list route — same scope boundary
    `askwell.log_export`'s own registration draws."""

    @app.post("/log-verify")
    async def create_verify() -> JSONResponse:
        async with session_scope(factory) as db:
            job_id = await enqueue(db)

        await dispatch(settings, [job_id])
        async with session_scope(factory) as db:
            job = await get_job(db, job_id)
        assert job is not None  # just inserted, in the same request
        return JSONResponse(job.as_dict(), status_code=201)

    @app.get("/log-verify/{job_id}")
    async def read_verify(job_id: uuid.UUID) -> JSONResponse:
        async with session_scope(factory) as db:
            job = await get_job(db, job_id)
        if job is None:
            return JSONResponse({"error": "No such verification."}, status_code=404)
        return JSONResponse(job.as_dict())

    @app.post("/log-verify/{job_id}/cancel")
    async def cancel_verify(job_id: uuid.UUID) -> JSONResponse:
        async with session_scope(factory) as db:
            job = await request_cancel(db, job_id)
        if job is None:
            return JSONResponse({"error": "No such verification."}, status_code=404)
        return JSONResponse(job.as_dict())
