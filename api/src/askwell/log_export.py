"""Log export: a background job that turns the two audit stores into an open,
independently verifiable file. `docs/audit-log.md` §5, ticket `M7-LOG-BE-155`.

**Why this exists at all.** A consultant who has to show a client what was
asked of their confidential corpus needs more than a screenshot of the log —
they need something the client's own technical person can check without
taking Askwell's word for it. `askwell.audit.verify` already proves the
chain to Askwell itself; this module is what makes that proof portable, by
writing the same records out plainly and shipping a standalone copy of the
check alongside them (`askwell.log_export_verifier`).

Same shape as `askwell.reapply` and `askwell.ingest`: a durable row
(`export_jobs`) is the record of what happened, `arq` is only the transport
that wakes a worker to act on it, and anything still `running` when the
process starts is, on one worker on one machine, unfinished work from last
time rather than something to trust.

**A run always starts by deleting whatever partial output exists and
rewriting from scratch**, rather than resuming mid-file. Two stores at
export retention (§8: twelve months by default) are kilobytes to low tens of
megabytes — cheap enough to redo whole that the correctness a restart-from-
scratch design gets for free is worth more than the write-avoidance a
resumable byte offset would add. What a crash must never do is leave a
half-written `decisions.jsonl` sitting under the name a finished one would
have: every file this module writes lands at `<name>.tmp` and is renamed
into place only once it is complete, so "the file exists under its real
name" and "the file is complete" are the same fact.

**The export snapshots itself at the moment it starts**, not at the moment
it finishes. An unbounded `until` is resolved to the job's own start time
before either store is queried, so a question answered while a multi-hour
export is running lands after the file rather than corrupting a progress
count that was fixed before that answer existed.
"""

import asyncio
import json
import shutil
import uuid
import zipfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from askwell import __version__, passphrase
from askwell.audit import Store, record
from askwell.config import Settings
from askwell.db.engine import session_scope
from askwell.log_export_verifier import SOURCE as VERIFIER_SOURCE
from askwell.logging import get_logger
from askwell.retention import mark_exported_through

log = get_logger(__name__)

EXPORT_JOB_ENQUEUED = "log_export_enqueued"

# Kept well under Postgres's own row/packet limits and small enough that one
# batch's `json.dumps` output is never more than a few megabytes even for the
# widest interaction payload — streamed to disk, never assembled whole.
_BATCH_SIZE = 2000

_STORE_FILES = {Store.DECISIONS: "decisions.jsonl", Store.INTERACTIONS: "interactions.jsonl"}


class ExportNotAcknowledged(Exception):
    """A passphrase is set and the caller did not acknowledge the export
    leaves the library's protection."""


class InvalidRange(ValueError):
    """`since` is after `until`."""


@dataclass(frozen=True, slots=True)
class ExportJob:
    id: uuid.UUID
    status: str
    since: datetime | None
    until: datetime | None
    decisions_total: int
    decisions_done: int
    interactions_total: int
    interactions_done: int
    file_bytes: int | None
    error: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "status": self.status,
            "since": self.since.isoformat() if self.since else None,
            "until": self.until.isoformat() if self.until else None,
            "decisions_total": self.decisions_total,
            "decisions_done": self.decisions_done,
            "interactions_total": self.interactions_total,
            "interactions_done": self.interactions_done,
            "file_bytes": self.file_bytes,
            "error": self.error,
        }


# --- enqueue, dispatch, resume ----------------------------------------------


async def enqueue(
    session: AsyncSession,
    *,
    since: datetime | None,
    until: datetime | None,
    acknowledged_decrypted_export: bool,
) -> uuid.UUID:
    """Record the intent to export. Always a decisions record naming the
    range — the ticket's own Audit Requirement — written in the same
    transaction as the job row, so a job nobody can prove was ever asked for
    does not exist either.
    """
    if since is not None and until is not None and since > until:
        raise InvalidRange("`since` must not be after `until`.")
    if await passphrase.is_enabled(session) and not acknowledged_decrypted_export:
        raise ExportNotAcknowledged(
            "A passphrase is set. The export is written in the open, unencrypted — outside "
            "the protection a passphrase gives the library — and must be acknowledged before "
            "it is written."
        )

    job_id = uuid.uuid4()
    await session.execute(
        text("INSERT INTO export_jobs (id, since, until) VALUES (:id, :since, :until)"),
        {"id": job_id, "since": since, "until": until},
    )
    await record(
        session,
        Store.DECISIONS,
        EXPORT_JOB_ENQUEUED,
        {
            "job_id": str(job_id),
            "since": since.isoformat() if since else None,
            "until": until.isoformat() if until else None,
        },
    )
    log.info("log_export_enqueued", job_id=str(job_id))
    return job_id


async def dispatch(settings: Settings, job_ids: list[uuid.UUID]) -> int:
    """Ask a worker to pick these up now. Best-effort, the same reasoning as
    `askwell.reapply.dispatch` — the job row is already committed, so a slow
    or absent Redis costs a delay, never the export itself."""
    if not job_ids:
        return 0

    from arq import create_pool
    from redis.exceptions import RedisError

    from askwell.worker import redis_settings

    queue = redis_settings(settings)
    try:
        pool = await create_pool(queue)
    except (OSError, RedisError) as error:
        log.warning("log_export_dispatch_unavailable", error=str(error), jobs=len(job_ids))
        return 0

    sent = 0
    try:
        for job_id in job_ids:
            job = await pool.enqueue_job("export_job", str(job_id), _job_id=f"export:{job_id}")
            if job is not None:
                sent += 1
    except (OSError, RedisError) as error:  # pragma: no cover - needs a mid-flight failure
        log.warning("log_export_dispatch_failed", error=str(error))
    finally:
        await pool.aclose()
    return sent


async def resume(session: AsyncSession) -> list[uuid.UUID]:
    """Return a job a dead worker was holding back to `queued`. One worker,
    one machine — anything still `running` at startup is unfinished work
    from the previous process, the same reasoning `askwell.reapply.resume`
    applies."""
    result = await session.execute(
        text(
            "UPDATE export_jobs SET status = 'queued', started_at = NULL "
            "WHERE status = 'running' RETURNING id"
        )
    )
    return [row[0] for row in result.all()]


async def get_job(session: AsyncSession, job_id: uuid.UUID) -> ExportJob | None:
    row = (
        await session.execute(
            text(
                "SELECT id, status, since, until, decisions_total, decisions_done, "
                "interactions_total, interactions_done, file_bytes, error "
                "FROM export_jobs WHERE id = :id"
            ),
            {"id": job_id},
        )
    ).first()
    if row is None:
        return None
    return ExportJob(*row)


async def _file_path(session: AsyncSession, job_id: uuid.UUID) -> str | None:
    row = (
        await session.execute(
            text("SELECT file_path FROM export_jobs WHERE id = :id AND status = 'done'"),
            {"id": job_id},
        )
    ).first()
    return None if row is None else row[0]


# --- running one job ---------------------------------------------------


def _where(store: Store, since: datetime | None, until: datetime) -> tuple[str, dict[str, Any]]:
    clauses = ["occurred_at <= :until"]
    params: dict[str, Any] = {"until": until}
    if since is not None:
        clauses.append("occurred_at >= :since")
        params["since"] = since
    return " AND ".join(clauses), params


async def _count(
    session: AsyncSession, store: Store, since: datetime | None, until: datetime
) -> int:
    where_sql, params = _where(store, since, until)
    result = await session.execute(
        text(f"SELECT count(*) FROM {store.value} WHERE {where_sql}"), params
    )
    return int(result.scalar_one())


async def _write_store_file(
    session: AsyncSession,
    store: Store,
    since: datetime | None,
    until: datetime,
    out_dir: Path,
    on_progress: Callable[[Store, int], Awaitable[None]],
) -> tuple[int, str | None]:
    """Stream every matching record to `<store>.jsonl.tmp` in ascending order,
    in batches, then rename into place. Returns the count written and the
    `prev_hash` the very first record chains to — the export's own starting
    point, which `askwell.log_export_verifier` walks from instead of
    expecting the universal genesis value when `since` narrows the window.
    """
    where_sql, base_params = _where(store, since, until)
    tmp_path = out_dir / f"{_STORE_FILES[store]}.tmp"
    final_path = out_dir / _STORE_FILES[store]

    written = 0
    first_prev_hash: str | None = None
    cursor_at: datetime | None = None
    cursor_id: uuid.UUID | None = None

    with tmp_path.open("w", encoding="utf-8") as handle:
        while True:
            params = dict(base_params)
            keyset = ""
            if cursor_at is not None:
                keyset = " AND (occurred_at, id) > (:cursor_at, :cursor_id)"
                params["cursor_at"] = cursor_at
                params["cursor_id"] = cursor_id
            rows = (
                await session.execute(
                    text(
                        f"SELECT id, kind, payload, prev_hash, hash, occurred_at "
                        f"FROM {store.value} WHERE {where_sql}{keyset} "
                        f"ORDER BY occurred_at ASC, id ASC LIMIT :batch"
                    ),
                    {**params, "batch": _BATCH_SIZE},
                )
            ).all()
            if not rows:
                break
            for row_id, kind, payload, prev_hash, digest, occurred_at in rows:
                if first_prev_hash is None:
                    first_prev_hash = prev_hash
                handle.write(
                    json.dumps(
                        {
                            "id": str(row_id),
                            "kind": kind,
                            "payload": payload,
                            "prev_hash": prev_hash,
                            "hash": digest,
                            "occurred_at": occurred_at.astimezone(UTC).isoformat(),
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                written += 1
                cursor_at, cursor_id = occurred_at, row_id
            await on_progress(store, written)
    tmp_path.rename(final_path)
    return written, first_prev_hash


async def run_job(
    sessions: async_sessionmaker[AsyncSession], settings: Settings, job_id: uuid.UUID
) -> None:
    """Produce one export end to end: count, stream both stores to disk,
    write the manifest and verifier, zip, and record the result. A run
    always starts by clearing any previous attempt's output directory —
    see the module docstring for why redoing the write is cheaper here than
    resuming it.
    """
    job_dir = settings.export_dir / str(job_id)
    started_at = datetime.now(UTC)

    async with session_scope(sessions) as session:
        row = (
            await session.execute(
                text("SELECT since, until FROM export_jobs WHERE id = :id"), {"id": job_id}
            )
        ).first()
        if row is None:
            return
        since, requested_until = row
        # The snapshot boundary: an unbounded `until` is pinned to this run's
        # own start, so a record written mid-export never changes a total
        # this run already counted (module docstring).
        until = requested_until if requested_until is not None else started_at

        decisions_total = await _count(session, Store.DECISIONS, since, until)
        interactions_total = await _count(session, Store.INTERACTIONS, since, until)
        await session.execute(
            text(
                "UPDATE export_jobs SET status = 'running', "
                "started_at = COALESCE(started_at, now()), "
                "decisions_total = :dt, decisions_done = 0, "
                "interactions_total = :it, interactions_done = 0, "
                "error = NULL WHERE id = :id"
            ),
            {"id": job_id, "dt": decisions_total, "it": interactions_total},
        )

    try:
        if job_dir.exists():
            shutil.rmtree(job_dir)
        job_dir.mkdir(parents=True)

        async def _progress(store: Store, count: int) -> None:
            column = "decisions_done" if store is Store.DECISIONS else "interactions_done"
            async with session_scope(sessions) as progress_session:
                await progress_session.execute(
                    text(f"UPDATE export_jobs SET {column} = :count WHERE id = :id"),
                    {"count": count, "id": job_id},
                )

        stores_manifest: dict[str, Any] = {}
        async with session_scope(sessions) as session:
            for store in (Store.DECISIONS, Store.INTERACTIONS):
                count, first_prev_hash = await _write_store_file(
                    session, store, since, until, job_dir, _progress
                )
                stores_manifest[store.value.removeprefix("audit_")] = {
                    "record_count": count,
                    "first_prev_hash": first_prev_hash,
                }

        manifest = {
            "askwell_version": __version__,
            "generated_at": datetime.now(UTC).isoformat(),
            "since": since.astimezone(UTC).isoformat() if since else None,
            "until": requested_until.astimezone(UTC).isoformat() if requested_until else None,
            "stores": stores_manifest,
        }
        manifest_tmp = job_dir / "manifest.json.tmp"
        manifest_tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        manifest_tmp.rename(job_dir / "manifest.json")

        verifier_tmp = job_dir / "verify.py.tmp"
        verifier_tmp.write_text(VERIFIER_SOURCE, encoding="utf-8")
        verifier_tmp.rename(job_dir / "verify.py")

        zip_final = settings.export_dir / f"askwell-log-export-{job_id}.zip"
        zip_tmp = settings.export_dir / f"askwell-log-export-{job_id}.zip.tmp"
        with zipfile.ZipFile(zip_tmp, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(job_dir.iterdir()):
                archive.write(path, arcname=path.name)
        zip_tmp.rename(zip_final)
        shutil.rmtree(job_dir)

        async with session_scope(sessions) as session:
            await session.execute(
                text(
                    "UPDATE export_jobs SET status = 'done', finished_at = now(), "
                    "file_path = :path, file_bytes = :size WHERE id = :id"
                ),
                {"id": job_id, "path": str(zip_final), "size": zip_final.stat().st_size},
            )
            if since is None:
                # Only a full-history export proves every interaction up to
                # `until` was written out — a windowed one says nothing about
                # what came before its own `since`, so it must never advance
                # this marker (`askwell.retention.prune`'s own guard reads it).
                await mark_exported_through(session, until)
        log.info(
            "log_export_done",
            job_id=str(job_id),
            decisions=stores_manifest["decisions"]["record_count"],
            interactions=stores_manifest["interactions"]["record_count"],
        )
    except Exception as error:
        log.warning(
            "log_export_failed", job_id=str(job_id), error=f"{type(error).__name__}: {error}"
        )
        async with session_scope(sessions) as session:
            await session.execute(
                text(
                    "UPDATE export_jobs SET status = 'failed', finished_at = now(), "
                    "error = :error WHERE id = :id"
                ),
                {"id": job_id, "error": f"{type(error).__name__}: {error}"},
            )
        raise


# --- HTTP --------------------------------------------------------------


class CreateExportRequest(BaseModel):
    since: datetime | None = None
    until: datetime | None = None
    acknowledged_decrypted_export: bool = False


def register_log_export(
    app: FastAPI, settings: Settings, factory: async_sessionmaker[AsyncSession]
) -> None:
    """`POST /log-export` enqueues and dispatches a job; `GET /log-export/{id}`
    reads its progress; `GET /log-export/{id}/download` streams the finished
    file. No delete or list route — the ticket's own scope is the job, the
    format and the verifier, and a history view belongs to whichever settings
    ticket first needs one.
    """

    @app.post("/log-export")
    async def create_export(body: CreateExportRequest) -> JSONResponse:
        try:
            async with session_scope(factory) as db:
                job_id = await enqueue(
                    db,
                    since=body.since,
                    until=body.until,
                    acknowledged_decrypted_export=body.acknowledged_decrypted_export,
                )
        except InvalidRange as error:
            return JSONResponse({"error": str(error)}, status_code=400)
        except ExportNotAcknowledged as error:
            # 400, not 403: nothing about the request is forbidden, a required
            # field was left unset — the same shape `set_passphrase`'s own
            # `NoRecoveryNotAcknowledged` uses for the same reason.
            return JSONResponse({"error": str(error), "passphrase_enabled": True}, status_code=400)

        await dispatch(settings, [job_id])
        async with session_scope(factory) as db:
            job = await get_job(db, job_id)
        assert job is not None  # just inserted, in the same request
        return JSONResponse(job.as_dict(), status_code=201)

    @app.get("/log-export/{job_id}")
    async def read_export(job_id: uuid.UUID) -> JSONResponse:
        async with session_scope(factory) as db:
            job = await get_job(db, job_id)
        if job is None:
            return JSONResponse({"error": "No such export."}, status_code=404)
        return JSONResponse(job.as_dict())

    @app.get("/log-export/{job_id}/download", response_model=None)
    async def download_export(job_id: uuid.UUID) -> FileResponse | JSONResponse:
        async with session_scope(factory) as db:
            path = await _file_path(db, job_id)
        if path is None:
            return JSONResponse(
                {"error": "Export is not finished, or does not exist."}, status_code=404
            )
        file_path = Path(path)
        if not await asyncio.to_thread(file_path.exists):
            # The job row says `done` but the file it points at is gone — a
            # user deleting it by hand, most plausibly. Distinct from 404 so
            # the settings screen can tell "never existed" from "existed,
            # and is no longer there" apart.
            return JSONResponse(
                {"error": "The export file no longer exists on disk."}, status_code=410
            )
        return FileResponse(file_path, filename=file_path.name, media_type="application/zip")
