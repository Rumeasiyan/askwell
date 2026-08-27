"""Ingestion as a background job, and the progress that outlives the page.

`docs/backlog/M1-it-answers-from-my-documents.md` ticket `M1-ADD-ING-025`.

Somebody drops five hundred papers and goes to make tea. Everything here exists
because of what happens next: they close the tab, the laptop sleeps, the stack
is restarted, and when they come back the import must have carried on rather
than have been a progress bar they were holding up by looking at it.

Five ideas carry the module.

**The database is the queue; Redis is the transport.** `arq` is what wakes a
worker, and it is genuinely good at that. It is not the record. A job that
exists only in Redis is lost by `podman compose down -v`, by an enqueue that
failed while the API had already committed the document, and by a worker killed
holding it — and each of those loses work the user believes is underway. So
`ingest_jobs` rows are written in the same transaction as the documents, and
`reconcile` makes the queue agree with the table rather than the other way
about. Dispatch failing is a delay; it is never a loss.

**A stage that has not been built is `parked`, not finished and not failed.**
The pipeline is declared in full — extract, chunk, embed — and today none of it
exists: those are `M1-EXTRACT-ING-026`, `M1-INDEX-ING-031` and
`M1-INDEX-ING-032`, and this ticket's own scope puts them out of it. A job
therefore runs, reaches `extract`, finds nothing installed and stops there,
saying so. It does not mark the document `ready`, which would tell the library a
file is searchable when nothing has read it; and it does not mark it failed,
which would fill a fresh install with red. `docs/states-and-edge-cases.md` §3
asks for exactly this sentence — "files queued but nothing indexed yet ... an
honest sentence, not a progress bar that never moves" — and `awaiting` is what
lets the surface name what has to arrive first.

**Progress is measured inside a file as well as between them.** A single 900-page
scan is hours, and a count of "3 of 12" that does not move for two of them is
indistinguishable from a hang. Every stage is handed a `report` callback and the
bytes it reports land on the job row, throttled, so the surface can render a
fraction rather than a spinner.

**The estimate says what it is based on, and refuses to invent one.** Before
anything has finished on this machine there is no throughput history, so the
estimate is `null` with a stated reason rather than a number nobody measured.
An optimistic guess on a first import is worse than no guess: the user plans
their afternoon around it.

**A failed job is visible, retryable, and never silently dropped.** The job
function catches its own errors rather than letting `arq` retry blindly,
because `arq`'s retry counter lives in Redis and the thing the library has to
render — "this file failed, here is why, retry" — has to survive Redis.
"""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from askwell.audit import Store, record
from askwell.config import Settings
from askwell.db.engine import session_scope
from askwell.logging import get_logger

log = get_logger(__name__)

# Audit kinds. A source becoming askable, or needing attention, is a change in
# what Askwell will answer from — `docs/audit-log.md` §2 puts that in the
# decisions store. Individual job starts and completions are logged and not
# recorded: they are operational detail, and a store kept forever should not
# grow by two rows per file.
SOURCE_STATUS_CHANGED = "source_status_changed"

# How often a running stage's byte count is written down. Twice a second is
# faster than anybody reads and slower than a tight loop; the alternative — a
# write per chunk — is thousands of transactions for one large file.
PROGRESS_INTERVAL_SECONDS = 0.5

# How often the progress stream re-reads while work is outstanding, and while
# it is not. The idle figure matters: a browser tab left open on the library
# overnight must not poll the database twice a second until morning.
STREAM_INTERVAL_SECONDS = 0.5
STREAM_IDLE_INTERVAL_SECONDS = 2.0

# How long the stream may say nothing before it says nothing out loud. Proxies
# and browsers close a silent connection, and a reconnect loop is worse than a
# colon and a newline.
STREAM_HEARTBEAT_SECONDS = 15.0

# How many times a document is tried before it is left failed for the user to
# decide about. Three is the same figure the worker uses for its own retries
# and is chosen for the same reason: a transient cause — a file briefly locked,
# a model process restarting — clears within one, and anything that survives
# three is a fact about the file rather than about the moment.
MAX_ATTEMPTS = 3

# How long to wait before retrying a failed attempt. Linear rather than
# exponential: on one laptop the contended resource is the machine itself, and
# a doubling backoff mostly means the queue idles while the user waits.
RETRY_DELAY_SECONDS = 10

# How many queued files the surface names by position. A user with five hundred
# waiting does not want five hundred rows; they want to know where the next few
# are and how long the whole thing will take.
QUEUE_PREVIEW = 10


# --- the pipeline -----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Work:
    """One document, as a stage needs to see it."""

    document_id: uuid.UUID
    source_id: uuid.UUID
    path: str
    filename: str
    mime: str | None
    sha256: str


Report = Callable[[int, int], Awaitable[None]]
"""How a stage says how far into a file it is: bytes done, bytes total."""

StageFn = Callable[[Work, Report], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class Stage:
    """One step of the pipeline, built or not.

    `run` being `None` is not a placeholder to be tidied away — it is the
    honest statement that the step has a ticket and does not have an
    implementation, and it is what the progress surface renders when it says
    what has to arrive before these files are searchable.
    """

    name: str
    ticket: str
    run: StageFn | None = None


# The pipeline, in order. Declared in full and installed in part: naming the
# steps that do not exist yet is what lets a queued document say what it is
# waiting for instead of sitting at "queued" with no explanation. A later
# ticket fills in `run` and changes nothing else here.
STAGES: tuple[Stage, ...] = (
    Stage("extract", "M1-EXTRACT-ING-026"),
    Stage("chunk", "M1-INDEX-ING-031"),
    Stage("embed", "M1-INDEX-ING-032"),
)


def installed() -> tuple[Stage, ...]:
    return tuple(stage for stage in STAGES if stage.run is not None)


# --- enqueueing -------------------------------------------------------------


async def enqueue(
    session: AsyncSession,
    source_id: uuid.UUID,
    document_ids: Sequence[uuid.UUID],
) -> int:
    """Write the queue rows, in the caller's transaction.

    In the caller's transaction on purpose: a document that exists and has no
    job is a file the user was told was queued and which nothing will ever
    pick up. `ON CONFLICT DO NOTHING` because adding to a folder twice is
    ordinary and the unique constraint on `document_id` is what stops two
    workers extracting one file into one set of chunks.
    """
    if not document_ids:
        return 0

    result = await session.execute(
        text(
            "INSERT INTO ingest_jobs (document_id, source_id) "
            "SELECT id, :source_id FROM documents WHERE id = ANY(:ids) "
            "ON CONFLICT (document_id) DO NOTHING RETURNING document_id"
        ),
        {"source_id": source_id, "ids": list(document_ids)},
    )
    written = len(result.all())
    log.info("ingest_enqueued", source_id=str(source_id), documents=written)
    return written


async def dispatch(
    settings: Settings,
    document_ids: Sequence[uuid.UUID],
    *,
    attempt: int = 0,
    delay_seconds: float | None = None,
    unique: bool = True,
) -> int:
    """Ask a worker to pick these up now, rather than at the next reconcile.

    Every failure here is swallowed on purpose and logged loudly. The rows are
    already committed, so a Redis that is down or slow costs the user up to one
    reconcile interval — and raising instead would turn "the queue is briefly
    unavailable" into "your add failed", which is both wrong and alarming.

    `unique` decides whether a job id derived from the document and the attempt
    is supplied. Two jobs for one document are harmless — `_claim` only takes a
    row that is still `queued`, so the second finds nothing to do — but the
    reconcile timer runs every half minute, and without an id it would pile a
    fresh job onto the queue for every waiting document twice a minute for as
    long as a large import lasts. So reconcile and the ordinary enqueue are
    idempotent, and a retry the *user* asked for is not: `arq` refuses an id it
    has seen recently, and a retry resets the attempt count, so the id it would
    otherwise reuse is exactly the one the first attempt already burned — the
    retry would be accepted by the API and silently dropped by the queue.
    """
    if not document_ids:
        return 0

    # Deferred: `askwell.worker` imports this module for its job table, so a
    # module-level import here would be a cycle.
    from dataclasses import replace

    from arq import create_pool
    from redis.exceptions import RedisError

    from askwell.worker import redis_settings

    # One attempt, not the default five with a second between them. This is a
    # best-effort wake-up over a durable queue, and five seconds of retries
    # here is five seconds the user's add request spends waiting to discover
    # something that changes nothing about the outcome.
    queue = replace(redis_settings(settings), conn_retries=1, conn_retry_delay=0)

    try:
        pool = await create_pool(queue)
    except (OSError, RedisError) as error:
        log.warning("ingest_dispatch_unavailable", error=str(error), documents=len(document_ids))
        return 0

    sent = 0
    try:
        for document_id in document_ids:
            job = await pool.enqueue_job(
                "ingest_document",
                str(document_id),
                _job_id=f"ingest:{document_id}:{attempt}" if unique else None,
                _defer_by=delay_seconds,
            )
            if job is not None:
                sent += 1
    except (OSError, RedisError) as error:  # pragma: no cover - needs a mid-flight failure
        log.warning("ingest_dispatch_failed", error=str(error))
    finally:
        await pool.aclose()

    return sent


# --- running one document ---------------------------------------------------


async def _claim(session: AsyncSession, document_id: uuid.UUID) -> tuple[Work, int] | None:
    """Take the job, or find that somebody else already has.

    Only a `queued` row is claimable. A row left `running` by a worker that
    died is not re-claimed here — `resume` at worker startup is what returns it
    to the queue, and doing it here as well would let a duplicate dispatch run
    two extractions over one file.
    """
    result = await session.execute(
        text(
            "UPDATE ingest_jobs SET state = 'running', started_at = now(), "
            "finished_at = NULL, attempts = attempts + 1, error = NULL, "
            "stage = NULL, awaiting = NULL, bytes_done = NULL, bytes_total = NULL "
            "WHERE document_id = :id AND state = 'queued' "
            "RETURNING attempts, source_id"
        ),
        {"id": document_id},
    )
    row = result.first()
    if row is None:
        return None

    document = await session.execute(
        text(
            "SELECT source_id, path, filename, mime, sha256 FROM documents "
            "WHERE id = :id AND deleted_at IS NULL"
        ),
        {"id": document_id},
    )
    found = document.first()
    if found is None:
        # The document was deleted between enqueue and dispatch. Not a failure:
        # nothing is wrong, there is simply nothing to do.
        await session.execute(
            text("DELETE FROM ingest_jobs WHERE document_id = :id"), {"id": document_id}
        )
        return None

    work = Work(
        document_id=document_id,
        source_id=found[0],
        path=found[1],
        filename=found[2],
        mime=found[3],
        sha256=found[4],
    )
    return work, int(row[0])


async def _park(
    factory: async_sessionmaker[AsyncSession],
    work: Work,
    *,
    reached: str | None,
    awaiting: Stage,
) -> None:
    """Stop at the first stage that does not exist, and say which one.

    The document goes back to `queued` rather than staying `indexing`. Nothing
    has indexed it, and `indexing` is what the library renders as a progress
    bar — the one thing `docs/states-and-edge-cases.md` §3 says must not happen
    for work that has not started.
    """
    async with session_scope(factory) as session:
        await session.execute(
            text(
                "UPDATE ingest_jobs SET state = 'parked', stage = :reached, "
                "awaiting = :awaiting, finished_at = now() WHERE document_id = :id"
            ),
            {"reached": reached, "awaiting": awaiting.name, "id": work.document_id},
        )
        await session.execute(
            text("UPDATE documents SET status = 'queued' WHERE id = :id"),
            {"id": work.document_id},
        )
        await refresh_source(session, work.source_id)

    log.info(
        "ingest_parked",
        document_id=str(work.document_id),
        reached=reached,
        awaiting=awaiting.name,
        ticket=awaiting.ticket,
    )


async def _finish(factory: async_sessionmaker[AsyncSession], work: Work) -> None:
    async with session_scope(factory) as session:
        await session.execute(
            text(
                "UPDATE ingest_jobs SET state = 'done', awaiting = NULL, "
                "finished_at = now() WHERE document_id = :id"
            ),
            {"id": work.document_id},
        )
        await session.execute(
            text("UPDATE documents SET status = 'ready' WHERE id = :id"),
            {"id": work.document_id},
        )
        await refresh_source(session, work.source_id)
    log.info("ingest_completed", document_id=str(work.document_id), filename=work.filename)


async def _fail(
    factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    work: Work,
    *,
    stage: Stage,
    attempts: int,
    error: Exception,
) -> None:
    """Record a failure where the user can see it, and retry if it is worth it.

    Never `raise`. `arq`'s own retry counter lives in Redis, and the thing the
    library has to render — this file, this reason, a retry control — has to
    survive Redis being flushed.
    """
    reason = f"{type(error).__name__}: {error}"
    again = attempts < MAX_ATTEMPTS

    async with session_scope(factory) as session:
        await session.execute(
            text(
                "UPDATE ingest_jobs SET state = :state, stage = :stage, error = :error, "
                # `:done` rather than comparing `:state` again — see the note
                # in `refresh_source`: one placeholder gets one deduced type.
                "finished_at = CASE WHEN :done THEN now() ELSE NULL END "
                "WHERE document_id = :id"
            ),
            {
                "state": "queued" if again else "failed",
                "done": not again,
                "stage": stage.name,
                "error": reason,
                "id": work.document_id,
            },
        )
        if not again:
            await session.execute(
                text("UPDATE documents SET status = 'attention' WHERE id = :id"),
                {"id": work.document_id},
            )
        await refresh_source(session, work.source_id)

    log.warning(
        "ingest_failed",
        document_id=str(work.document_id),
        filename=work.filename,
        stage=stage.name,
        attempts=attempts,
        retrying=again,
        error=reason,
    )
    if again:
        await dispatch(
            settings,
            [work.document_id],
            attempt=attempts,
            delay_seconds=RETRY_DELAY_SECONDS,
        )


def _reporter(
    factory: async_sessionmaker[AsyncSession],
    document_id: uuid.UUID,
    clock: Callable[[], float],
) -> Report:
    """Byte progress, throttled, so a large file does not look hung.

    The first report always lands. It carries the total, which is what turns an
    untimed spinner into a fraction, and waiting half a second to say how big a
    four-gigabyte scan is would be the half-second the user is looking.
    """
    last = 0.0

    async def report(done: int, total: int) -> None:
        nonlocal last
        now = clock()
        if last and now - last < PROGRESS_INTERVAL_SECONDS and done < total:
            return
        last = now
        async with session_scope(factory) as session:
            await session.execute(
                text(
                    "UPDATE ingest_jobs SET bytes_done = :done, bytes_total = :total "
                    "WHERE document_id = :id AND state = 'running'"
                ),
                {"done": done, "total": total, "id": document_id},
            )

    return report


async def process(
    factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    document_id: uuid.UUID,
    *,
    clock: Callable[[], float] | None = None,
) -> str:
    """Take one document through as much of the pipeline as exists.

    Returns what happened, as a word, because a caller that awaited the job
    wants to know and because it is what the worker log carries.
    """
    tick = clock if clock is not None else asyncio.get_running_loop().time

    async with session_scope(factory) as session:
        claimed = await _claim(session, document_id)
    if claimed is None:
        return "unclaimable"

    work, attempts = claimed
    log.info(
        "ingest_started",
        document_id=str(document_id),
        filename=work.filename,
        attempt=attempts,
        stages=[stage.name for stage in installed()],
    )

    report = _reporter(factory, document_id, tick)
    reached: str | None = None

    for stage in STAGES:
        if stage.run is None:
            await _park(factory, work, reached=reached, awaiting=stage)
            return "parked"

        if reached is None:
            async with session_scope(factory) as session:
                await session.execute(
                    text("UPDATE documents SET status = 'indexing' WHERE id = :id"),
                    {"id": document_id},
                )
                await refresh_source(session, work.source_id)

        try:
            await stage.run(work, report)
        except Exception as error:  # a stage may raise anything at all
            await _fail(factory, settings, work, stage=stage, attempts=attempts, error=error)
            return "failed"

        reached = stage.name
        async with session_scope(factory) as session:
            await session.execute(
                text("UPDATE ingest_jobs SET stage = :stage WHERE document_id = :id"),
                {"stage": stage.name, "id": document_id},
            )

    await _finish(factory, work)
    return "done"


# --- the source's own state -------------------------------------------------


def source_status(*, total: int, ready: int, running: int, outstanding: int, failed: int) -> str:
    """What a source's status is, given what its documents are doing.

    `indexing` covers partly-indexed deliberately: the library's four statuses
    have no fifth value for it, and the *marker* the ticket asks for is the
    coverage figure, not a status. A source with eighty of five hundred files
    ready is askable and still working, and both halves of that are true at
    once.

    Order matters, and the contested case is a source that has finished with
    some files failed. It is `attention`, not `ready`, even though most of it
    is askable — because `attention` is the only place the library has to say
    "two of these sixty could not be read, here is why, retry", and a source
    rendered `ready` gives the user nothing to click. Askability is not lost by
    saying so: it is carried by `Coverage.askable`, which is a separate fact
    and stays true.
    """
    if total == 0:
        return "queued"
    if ready == total:
        return "ready"
    if outstanding == 0 and failed:
        return "attention"
    if running or ready:
        return "indexing"
    return "queued"


@dataclass(frozen=True, slots=True)
class Coverage:
    """How much of one source can actually be asked about."""

    total: int
    ready: int
    failed: int
    # Documents a stage is actually working on — read from the document's own
    # status, not from a job being claimed. A job with no stage installed is
    # claimed and parked inside a millisecond, and counting that as running
    # made a source flick `queued` → `indexing` → `queued` and write a
    # decisions record for each, describing work that never happened.
    running: int
    outstanding: int

    @property
    def askable(self) -> bool:
        """The partial-coverage marker: one indexed file is enough to ask.

        Waiting for the whole import is what this ticket exists to stop. A
        user with eighty of five hundred papers indexed can be answered from
        the eighty, provided the surface says that is what it is doing.
        """
        return self.ready > 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "ready": self.ready,
            "failed": self.failed,
            "running": self.running,
            "outstanding": self.outstanding,
            "askable": self.askable,
            "fraction": round(self.ready / self.total, 4) if self.total else 0.0,
        }


async def coverage(session: AsyncSession, source_id: uuid.UUID) -> Coverage:
    result = await session.execute(
        text(
            "SELECT count(*) AS total, "
            "count(*) FILTER (WHERE d.status = 'ready') AS ready, "
            "count(*) FILTER (WHERE j.state = 'failed') AS failed, "
            "count(*) FILTER (WHERE d.status = 'indexing') AS running, "
            "count(*) FILTER (WHERE j.state IN ('queued', 'running', 'parked')) AS outstanding "
            "FROM documents d LEFT JOIN ingest_jobs j ON j.document_id = d.id "
            "WHERE d.source_id = :id AND d.deleted_at IS NULL"
        ),
        {"id": source_id},
    )
    row = result.one()
    return Coverage(
        total=int(row[0]),
        ready=int(row[1]),
        failed=int(row[2]),
        running=int(row[3]),
        outstanding=int(row[4]),
    )


async def refresh_source(session: AsyncSession, source_id: uuid.UUID) -> str | None:
    """Recompute a source's status, and record it if it moved.

    Recorded rather than only logged: what Askwell will answer from changed,
    and `docs/audit-log.md` §2 puts that in the decisions store. Only on an
    actual change — a record per job completion would be five hundred rows
    saying the same thing about one import.
    """
    current = await session.execute(
        text("SELECT status FROM sources WHERE id = :id AND status <> 'deleted'"),
        {"id": source_id},
    )
    found = current.first()
    if found is None:
        return None

    counts = await coverage(session, source_id)
    wanted = source_status(
        total=counts.total,
        ready=counts.ready,
        running=counts.running,
        outstanding=counts.outstanding,
        failed=counts.failed,
    )
    if wanted == found[0]:
        return wanted

    await session.execute(
        text(
            "UPDATE sources SET status = :status, "
            # A separate parameter rather than comparing `:status` a second
            # time: psycopg deduces one type per placeholder, and the same name
            # used as both a value for a varchar column and an operand of a
            # text comparison is an ambiguous-parameter error rather than a
            # cast.
            "last_indexed_at = CASE WHEN :became_ready THEN now() ELSE last_indexed_at END, "
            "last_error = :last_error WHERE id = :id"
        ),
        {
            "status": wanted,
            "became_ready": wanted == "ready",
            "last_error": (
                f"{counts.failed} of {counts.total} files could not be indexed."
                if counts.failed
                else None
            ),
            "id": source_id,
        },
    )
    await record(
        session,
        Store.DECISIONS,
        SOURCE_STATUS_CHANGED,
        {
            "source_id": str(source_id),
            "from": found[0],
            "to": wanted,
            "ready": counts.ready,
            "total": counts.total,
            "failed": counts.failed,
        },
    )
    log.info(
        "source_status_changed",
        source_id=str(source_id),
        previous=found[0],
        status=wanted,
        ready=counts.ready,
        total=counts.total,
    )
    return wanted


# --- resuming ---------------------------------------------------------------


async def resume(session: AsyncSession) -> int:
    """Return work a dead worker was holding to the queue.

    Run at worker startup, where it is safe: there is one worker on one
    machine, so anything still marked `running` when it starts is by definition
    something the previous process did not finish. `attempts` is left alone —
    a machine that slept mid-import has not made the file any harder to read,
    and spending a retry on it would eventually mark a perfectly good document
    as failed for having been interrupted three times.
    """
    result = await session.execute(
        text(
            "UPDATE ingest_jobs SET state = 'queued', started_at = NULL, "
            "attempts = GREATEST(attempts - 1, 0) WHERE state = 'running' "
            "RETURNING document_id"
        )
    )
    interrupted = [row[0] for row in result.all()]
    if interrupted:
        log.info("ingest_resumed_interrupted", documents=len(interrupted))
    return len(interrupted)


async def pending(session: AsyncSession, limit: int = 500) -> list[uuid.UUID]:
    """Queued jobs, oldest first — what the queue believes it still owes."""
    result = await session.execute(
        text(
            "SELECT document_id FROM ingest_jobs WHERE state = 'queued' ORDER BY seq LIMIT :limit"
        ),
        {"limit": limit},
    )
    return [row[0] for row in result.all()]


async def stalled(session: AsyncSession, older_than_seconds: float) -> list[uuid.UUID]:
    """Queued rows old enough that arq refusing them means the id is a ghost.

    `enqueued_at` is when the row was written, and a row that arq is genuinely
    holding leaves `queued` within a job or two. One that is still here much
    later is waiting on an id nothing will ever run.
    """
    result = await session.execute(
        text(
            "SELECT document_id FROM ingest_jobs WHERE state = 'queued' "
            "AND enqueued_at < now() - make_interval(secs => :age) ORDER BY seq LIMIT 500"
        ),
        {"age": older_than_seconds},
    )
    return [row[0] for row in result.all()]


async def reconcile(factory: async_sessionmaker[AsyncSession], settings: Settings) -> int:
    """Re-dispatch queued work Redis does not know about.

    The repair path for every way the table and the queue can disagree: an
    enqueue that failed while the document was committed, a Redis flushed
    between two runs, a machine that woke up with a queue it dropped while
    asleep. Re-dispatch is safe because the job id is derived from the document
    and the attempt, so a job already queued is refused rather than duplicated,
    and because `_claim` only takes a row that is still `queued`.

    That id is also how this stalls, which is why the second dispatch exists.
    arq refuses an id whose job **or result** key it still holds, and it cannot
    distinguish "already queued" from "left behind". A worker killed hard leaves
    `arq:job:ingest:<doc>:0` with a 24-hour expiry and an in-progress key living
    `job_timeout + 10` seconds — an hour by default. A job that merely finished
    leaves its result key for as long as `keep_result`. In both cases every
    reconcile from then on asks for an id arq will not take, gets nothing, and
    reports success having done nothing, while the document sits `queued` and
    the progress surface shows a queue that is not moving with no reason given.

    So a refusal is not treated as proof the job is queued. A row still waiting
    long after it was enqueued is dispatched again without an id, which arq
    cannot refuse. Duplicates cost nothing — `_claim` takes a row only while it
    is `queued`, so the second job finds the work already taken and stops — and
    the alternative is a queue that stalls for an hour with nothing to read.
    """
    stale_after = settings.ingest_reconcile_seconds * 3
    async with session_scope(factory) as session:
        waiting = await pending(session)
        ghosts = await stalled(session, stale_after)
    if not waiting:
        return 0

    sent = await dispatch(settings, waiting)
    if sent < len(waiting) and ghosts:
        # Only the ones old enough to be ghosts, and only because the first pass
        # came back short. A full queue moving normally never reaches this.
        forced = await dispatch(settings, ghosts, unique=False)
        if forced:
            log.info("ingest_reconcile_forced", documents=forced, stale_after=stale_after)
        sent += forced
    return sent


# --- the surface ------------------------------------------------------------


async def _estimate(session: AsyncSession, settings: Settings, outstanding: int) -> dict[str, Any]:
    """How long the rest will take, or an honest refusal to say.

    `docs/backlog` calls for an estimate "honest rather than optimistic", and
    the known gap it names is exactly this: on a first run there is no
    throughput history, so any number would be invented. `null` with a stated
    basis is the answer in that case, and the basis is carried alongside every
    number so the user can see what it is extrapolating from.
    """
    if outstanding == 0:
        return {"seconds": 0, "basis": "nothing is waiting"}

    result = await session.execute(
        text(
            "SELECT count(*), avg(extract(epoch FROM (finished_at - started_at))) "
            "FROM ingest_jobs WHERE state = 'done' AND started_at IS NOT NULL "
            "AND finished_at IS NOT NULL"
        )
    )
    row = result.one()
    finished, average = int(row[0]), row[1]
    if not finished or average is None:
        return {
            "seconds": None,
            "basis": (
                "no estimate yet — nothing has finished indexing on this machine, "
                "so any time given here would be invented rather than measured"
            ),
        }

    concurrency = max(settings.ingest_concurrency, 1)
    seconds = int(float(average) * outstanding / concurrency)
    return {
        "seconds": seconds,
        "basis": (
            f"measured from {finished} file{'s' if finished != 1 else ''} averaging "
            f"{float(average):.0f}s each, {concurrency} at a time"
        ),
    }


async def snapshot(session: AsyncSession, settings: Settings) -> dict[str, Any]:
    """Everything the progress surface renders, in one read.

    One query set rather than one per panel: this is polled while an import
    runs, on a machine that is also embedding, and a surface that costs eight
    round trips twice a second is a surface that slows down the thing it is
    describing.
    """
    states = await session.execute(text("SELECT state, count(*) FROM ingest_jobs GROUP BY state"))
    counts = {state: 0 for state in ("queued", "running", "parked", "failed", "done")}
    for state, number in states.all():
        counts[str(state)] = int(number)

    outstanding = counts["queued"] + counts["running"]

    active = await session.execute(
        text(
            "SELECT j.document_id, d.filename, j.source_id, j.stage, j.attempts, "
            "j.bytes_done, j.bytes_total FROM ingest_jobs j "
            "JOIN documents d ON d.id = j.document_id "
            "WHERE j.state = 'running' ORDER BY j.seq"
        )
    )
    next_up = await session.execute(
        text(
            "SELECT j.document_id, d.filename, "
            "row_number() OVER (ORDER BY j.seq) AS position "
            "FROM ingest_jobs j JOIN documents d ON d.id = j.document_id "
            "WHERE j.state = 'queued' ORDER BY j.seq LIMIT :limit"
        ),
        {"limit": QUEUE_PREVIEW},
    )
    failures = await session.execute(
        text(
            "SELECT j.document_id, d.filename, j.stage, j.error, j.attempts "
            "FROM ingest_jobs j JOIN documents d ON d.id = j.document_id "
            "WHERE j.state = 'failed' ORDER BY j.finished_at DESC"
        )
    )
    sources = await session.execute(
        text(
            "SELECT s.id, s.name, s.status, count(d.id) AS total, "
            "count(*) FILTER (WHERE d.status = 'ready') AS ready, "
            "count(*) FILTER (WHERE j.state = 'failed') AS failed, "
            "count(*) FILTER (WHERE d.status = 'indexing') AS running, "
            "count(*) FILTER (WHERE j.state IN ('queued', 'running', 'parked')) AS outstanding "
            "FROM sources s JOIN documents d ON d.source_id = s.id AND d.deleted_at IS NULL "
            "LEFT JOIN ingest_jobs j ON j.document_id = d.id "
            "WHERE s.status <> 'deleted' GROUP BY s.id, s.name, s.status ORDER BY s.added_at"
        )
    )
    waiting_on = await session.execute(
        text(
            "SELECT awaiting, count(*) FROM ingest_jobs WHERE state = 'parked' "
            "AND awaiting IS NOT NULL GROUP BY awaiting ORDER BY count(*) DESC LIMIT 1"
        )
    )

    parked = waiting_on.first()
    stage_tickets = {stage.name: stage.ticket for stage in STAGES}

    return {
        "counts": counts,
        # Local counters, C1: these are read out of this machine's own database
        # by this machine's own browser, and nothing here is transmitted.
        "documents_ingested": counts["done"],
        "documents_failed": counts["failed"],
        "queue_length": outstanding,
        "concurrency": settings.ingest_concurrency,
        "estimate": await _estimate(session, settings, outstanding),
        "active": [
            {
                "document_id": str(row[0]),
                "filename": row[1],
                "source_id": str(row[2]),
                "stage": row[3],
                "attempt": int(row[4]),
                "bytes_done": int(row[5]) if row[5] is not None else None,
                "bytes_total": int(row[6]) if row[6] is not None else None,
                "fraction": (
                    round(int(row[5]) / int(row[6]), 4) if row[5] is not None and row[6] else None
                ),
            }
            for row in active.all()
        ],
        "next": [
            {"document_id": str(row[0]), "filename": row[1], "position": int(row[2])}
            for row in next_up.all()
        ],
        "failures": [
            {
                "document_id": str(row[0]),
                "filename": row[1],
                "stage": row[2],
                "error": row[3],
                "attempts": int(row[4]),
            }
            for row in failures.all()
        ],
        "sources": [
            {
                "id": str(row[0]),
                "name": row[1],
                "status": row[2],
                **Coverage(
                    total=int(row[3]),
                    ready=int(row[4]),
                    failed=int(row[5]),
                    running=int(row[6]),
                    outstanding=int(row[7]),
                ).as_dict(),
            }
            for row in sources.all()
        ],
        # What has to arrive before any of this becomes searchable. Null once
        # the pipeline is complete; until then it is the difference between
        # "nothing is happening" and "nothing is happening, and here is why".
        "awaiting": (
            None
            if parked is None
            else {
                "stage": parked[0],
                "ticket": stage_tickets.get(str(parked[0]), ""),
                "documents": int(parked[1]),
            }
        ),
        "stages": [
            {"name": stage.name, "ticket": stage.ticket, "built": stage.run is not None}
            for stage in STAGES
        ],
    }


@dataclass(frozen=True, slots=True)
class Retried:
    """What a retry request did, without overloading one word to say it.

    `state` is what the job is now if it was retried, and what it already was
    if it was not — and `retried` is what tells those apart. Returning the
    state alone made "I have re-queued it" and "it was already queued"
    indistinguishable, which is exactly the shape of bug that reaches a user as
    a retry button that appears to work.
    """

    retried: bool
    state: str | None
    source_id: uuid.UUID | None = None


async def retry(session: AsyncSession, document_id: uuid.UUID) -> Retried:
    """Put a failed document back on the queue, with its attempts forgiven.

    Forgiven rather than continued: the user has looked at the reason and done
    something about it — reconnected a drive, closed the file — and starting
    from the third attempt would fail it again on the first hiccup.
    """
    result = await session.execute(
        text(
            "UPDATE ingest_jobs SET state = 'queued', attempts = 0, error = NULL, "
            "stage = NULL, awaiting = NULL, started_at = NULL, finished_at = NULL, "
            "bytes_done = NULL, bytes_total = NULL "
            "WHERE document_id = :id AND state = 'failed' RETURNING source_id"
        ),
        {"id": document_id},
    )
    row = result.first()
    if row is None:
        existing = await session.execute(
            text("SELECT state FROM ingest_jobs WHERE document_id = :id"), {"id": document_id}
        )
        found = existing.first()
        return Retried(retried=False, state=None if found is None else str(found[0]))

    await session.execute(
        text("UPDATE documents SET status = 'queued' WHERE id = :id"), {"id": document_id}
    )
    await refresh_source(session, row[0])
    log.info("ingest_retry_requested", document_id=str(document_id))
    return Retried(retried=True, state="queued", source_id=row[0])


def register_ingest(
    app: FastAPI, settings: Settings, factory: async_sessionmaker[AsyncSession]
) -> None:
    """Attach the progress surface. Register before the interface catch-all."""

    @app.get("/ingest")
    async def ingest_state() -> JSONResponse:
        """Where the queue is, once.

        The stream below is the same payload repeated; this exists because a
        page that is loading needs the state before it needs the changes, and
        because a single `curl` is how anyone debugging an import starts.
        """
        async with session_scope(factory) as db:
            return JSONResponse(await snapshot(db, settings))

    @app.get("/ingest/stream")
    async def ingest_stream(request: Request) -> StreamingResponse:
        """Progress, for as long as the browser wants it.

        Server-sent events rather than a socket: this is one direction, and the
        ticket says so — a bidirectional channel arrives with voice and buys
        nothing here. The important property is not the transport, it is that
        the work is not on the other end of it. Closing this connection stops
        the *watching*; the ingestion is on the worker and does not notice.
        """

        async def events() -> AsyncIterator[str]:
            previous: str | None = None
            silent = 0.0
            while True:
                if await request.is_disconnected():
                    return
                async with session_scope(factory) as db:
                    payload = await snapshot(db, settings)

                body = json.dumps(payload, sort_keys=True)
                busy = payload["queue_length"] > 0
                if body != previous:
                    previous = body
                    silent = 0.0
                    yield f"event: progress\ndata: {body}\n\n"

                interval = STREAM_INTERVAL_SECONDS if busy else STREAM_IDLE_INTERVAL_SECONDS
                if silent >= STREAM_HEARTBEAT_SECONDS:
                    silent = 0.0
                    yield ": keep-alive\n\n"
                silent += interval
                await asyncio.sleep(interval)

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-store",
                "Connection": "keep-alive",
                # Nothing proxies this today. Said anyway, because the first
                # thing anyone puts in front of a stream buffers it, and a
                # buffered progress stream is a progress bar that arrives all
                # at once when the import is already over.
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/ingest/documents/{document_id}/retry")
    async def ingest_retry(document_id: uuid.UUID) -> JSONResponse:
        async with session_scope(factory) as db:
            outcome = await retry(db, document_id)

        if outcome.state is None:
            return JSONResponse(
                {"error": "Askwell has no ingestion job for that document."}, status_code=404
            )
        if not outcome.retried:
            return JSONResponse(
                {
                    "error": (
                        f"That document is not failed — it is {outcome.state}. "
                        f"Only a failed document can be retried."
                    ),
                    "state": outcome.state,
                },
                status_code=409,
            )

        # Not idempotent, deliberately — see `dispatch`. This is a person
        # pressing a button after fixing whatever was wrong, and a retry that
        # is deduplicated against the attempt it is retrying does nothing.
        await dispatch(settings, [document_id], unique=False)
        return JSONResponse({"document_id": str(document_id), "state": "queued"}, status_code=202)
