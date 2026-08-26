"""The background worker.

Ingestion, embedding and OCR run here rather than in a request. None of that
exists yet — this ticket establishes that a job can be enqueued from the API
process, picked up by a separate process, and completed.

The `ping` job is not a placeholder to delete later. It is the cheapest
end-to-end proof that the queue is wired up, and when someone's worker is not
running it is the fastest way to establish that from the outside.
"""

from collections.abc import Callable
from typing import Any, ClassVar

from arq.connections import RedisSettings

from askwell import __version__
from askwell.config import Environment, Settings, load_settings
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


async def startup(ctx: dict[str, Any]) -> None:
    settings: Settings = ctx["settings"]
    log.info(
        "worker_startup",
        version=__version__,
        environment=str(settings.environment),
        queue=f"{settings.redis_host}:{settings.redis_port}",
    )


async def shutdown(ctx: dict[str, Any]) -> None:
    log.info("worker_shutdown", version=__version__)


class WorkerSettings:
    """arq's entry point. Read by `arq askwell.worker.WorkerSettings`."""

    functions: ClassVar[list[Callable[..., Any]]] = [ping]
    on_startup = startup
    on_shutdown = shutdown

    # A job interrupted by the machine restarting is retried rather than lost:
    # the user closed their laptop mid-ingest, which is a normal Tuesday, not
    # an error.
    max_tries = 3
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
    )
    worker.run()
