"""The background worker.

Ingestion, embedding and OCR run here rather than in a request. Since
`M1-ADD-ING-025` the ingestion pipeline runs here too — `askwell.ingest` holds
it, and this module is only its host: what functions exist, how many run at
once, and what happens at startup.

Three things about the wiring are decisions rather than defaults.

**Concurrency comes from configuration and defaults to two.** This machine is
also running the user's browser and, shortly, a language model. A worker that
takes every core is an import that makes the laptop unusable, and an import
that makes the laptop unusable gets killed.

**The queue is reconciled on a timer, not trusted.** `askwell.ingest` keeps the
durable record in Postgres and uses Redis to wake a worker. Those can disagree
— a failed enqueue, a flushed Redis, a machine that slept — and `reconcile`
running every half minute is what makes the disagreement a delay rather than
lost work.

**Interrupted jobs are returned to the queue at startup, not abandoned.** There
is one worker on one machine, so anything still marked `running` when this
process starts is by definition something the last one did not finish.

The `ping` job is not a placeholder to delete later. It is the cheapest
end-to-end proof that the queue is wired up, and when someone's worker is not
running it is the fastest way to establish that from the outside.
"""

import uuid
from collections.abc import Callable
from typing import Any, ClassVar

from arq import cron
from arq.connections import RedisSettings

from askwell import __version__
from askwell.config import Environment, Settings, load_settings
from askwell.db.engine import build_engine, session_factory, session_scope
from askwell.logging import configure_logging, get_logger

log = get_logger(__name__)


def redis_settings(settings: Settings) -> RedisSettings:
    """Where the queue lives."""
    return RedisSettings(host=settings.redis_host, port=settings.redis_port)


async def ping(ctx: dict[str, Any], sent_at: str) -> dict[str, str]:
    """Prove the queue works end to end.

    Returns rather than logs-only, so a caller can await the result and see
    which worker answered — on a single machine there is only one, but "the
    job ran" and "the job ran and returned" are different claims.
    """
    log.info("job_ping", job_id=ctx.get("job_id"), sent_at=sent_at, version=__version__)
    return {"pong": sent_at, "worker_version": __version__}


async def ingest_document(
    ctx: dict[str, Any], document_id: str, password: str | None = None
) -> str:
    """Take one document as far through the pipeline as exists.

    Thin on purpose. Everything about what ingestion *is* lives in
    `askwell.ingest`; this is the seam where the queue hands over, and the
    reason it is separate is that the pipeline has to be testable without a
    Redis, a worker process and a job serialiser in the way.

    `password` exists for a single retry a person asked for from the
    password prompt (`M1-EXTRACT-VAL-030`) — arq's job payload is the only
    place it lives, and it is never logged: this function never names it as a
    field on its own.
    """
    from askwell import ingest

    return await ingest.process(
        ctx["sessions"], ctx["settings"], uuid.UUID(document_id), password=password
    )


async def reconcile_queue(ctx: dict[str, Any]) -> int:
    """Re-dispatch queued work Redis has forgotten about.

    The repair path, run on a timer. It is a no-op in the ordinary case — the
    enqueue at add time is what usually starts an import — and it is the only
    thing that recovers one after a flushed Redis or a sleeping machine.
    """
    from askwell import ingest

    return await ingest.reconcile(ctx["sessions"], ctx["settings"])


async def startup(ctx: dict[str, Any]) -> None:
    from askwell import ingest

    settings: Settings = ctx["settings"]
    engine = build_engine(settings)
    ctx["engine"] = engine
    ctx["sessions"] = session_factory(engine)

    log.info(
        "worker_startup",
        version=__version__,
        environment=str(settings.environment),
        queue=f"{settings.redis_host}:{settings.redis_port}",
        concurrency=settings.ingest_concurrency,
    )

    # Before anything is dispatched. A job left `running` by the last process
    # is not claimable, so returning it to the queue has to happen before the
    # reconcile that would otherwise skip straight past it.
    try:
        async with session_scope(ctx["sessions"]) as session:
            resumed = await ingest.resume(session)
        waiting = await ingest.reconcile(ctx["sessions"], settings)
    except Exception as error:  # the database may not be up yet
        # Not fatal. Starting before Postgres is ready is normal on a laptop,
        # and refusing to start would leave the queue with nothing to drain it
        # at all; the timer below picks the work up on its next pass.
        log.warning("worker_resume_deferred", error=f"{type(error).__name__}: {error}")
        return

    log.info("worker_resumed", interrupted=resumed, dispatched=waiting)


async def shutdown(ctx: dict[str, Any]) -> None:
    engine = ctx.get("engine")
    if engine is not None:
        await engine.dispose()
    log.info("worker_shutdown", version=__version__)


class WorkerSettings:
    """arq's entry point. Read by `arq askwell.worker.WorkerSettings`."""

    functions: ClassVar[list[Callable[..., Any]]] = [ping, ingest_document]

    # The repair timer. Its interval is configuration, so it is applied in
    # `main()` where the settings exist — a class body cannot read them without
    # loading configuration at import time, which would make importing this
    # module for a test require a valid environment.
    cron_jobs: ClassVar[list[Any]] = []

    on_startup = startup
    on_shutdown = shutdown

    # A job interrupted by the machine restarting is retried rather than lost:
    # the user closed their laptop mid-ingest, which is a normal Tuesday, not
    # an error. `ingest_document` never relies on this — it catches its own
    # failures and writes them where the library can render them, because
    # arq's retry counter lives in Redis and the thing the user has to see
    # ("this file failed, here is why") has to survive Redis.
    max_tries = 3

    # A floor, not the figure that runs. `main()` overrides it from
    # ASKWELL_INGEST_JOB_TIMEOUT_SECONDS, which defaults to an hour: OCR over a
    # 900-page scan on CPU genuinely takes that long, and a timeout shorter
    # than the work turns a slow file into a failed one. This value applies
    # only when arq is invoked directly on this class.
    job_timeout = 300

    # arq publishes a health record into Redis on this interval, with an expiry
    # just past it, and that record is how the API knows the worker is alive
    # (see askwell.health). The default is an hour, which would mean a stopped
    # worker still looked fine for up to an hour — long enough for someone to
    # conclude their ingest is merely slow.
    health_check_interval = 10

    @staticmethod
    def redis_settings() -> RedisSettings:  # pragma: no cover - read by arq
        return redis_settings(load_settings())


def main() -> None:
    """Run the worker. Refuses to start on unusable configuration, like the API."""
    from arq.worker import create_worker

    from askwell.config import ConfigurationError

    try:
        settings = load_settings()
    except ConfigurationError as error:
        raise SystemExit(str(error)) from None

    configure_logging(
        level=settings.log_level,
        json_output=settings.environment is not Environment.DEVELOPMENT,
    )

    worker = create_worker(
        WorkerSettings,  # type: ignore[arg-type]  # arq accepts a settings class
        redis_settings=redis_settings(settings),
        ctx={"settings": settings},
        # Both from configuration, and both are about this being somebody's
        # laptop: how much of it ingestion may take, and how long one very
        # large scan is allowed to run before it is called failed.
        max_jobs=settings.ingest_concurrency,
        job_timeout=settings.ingest_job_timeout_seconds,
        cron_jobs=[
            cron(
                reconcile_queue,
                second=set(range(0, 60, settings.ingest_reconcile_seconds))
                if settings.ingest_reconcile_seconds < 60
                else {0},
                run_at_startup=False,
                max_tries=1,
            )
        ],
    )
    worker.run()
