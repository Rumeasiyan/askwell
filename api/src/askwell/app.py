"""The Askwell API application.

One process, reachable from one machine, serving one person. There is no
tenancy, no roles and no second node — anything here that looks like it is
preparing for those is a mistake, not foresight.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from askwell import __version__
from askwell.config import ConfigurationError, Environment, Settings, load_settings
from askwell.health import ComponentState, check_components
from askwell.logging import configure_logging, get_logger

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Log what came up and what it found, then log what went down.

    Component states are logged at startup deliberately. When someone reports
    that Askwell "did not work this morning", the first question is which part,
    and this is the only record that answers it without asking them to
    reproduce anything.
    """
    settings: Settings = app.state.settings

    components = await check_components(settings)
    log.info(
        "startup",
        version=__version__,
        environment=str(settings.environment),
        profile=str(settings.profile),
        bind=f"{settings.host}:{settings.port}",
        components={item.name: str(item.state) for item in components},
    )

    unreachable = [item.name for item in components if item.state is not ComponentState.REACHABLE]
    if unreachable:
        # Not an error. Starting before your dependencies is normal on a
        # laptop, and refusing to start would leave the user with no surface
        # to find out why.
        log.warning("startup_components_unreachable", components=unreachable)

    try:
        yield
    finally:
        log.info("shutdown", version=__version__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application. Configuration is resolved before anything starts."""
    resolved = settings if settings is not None else load_settings()

    configure_logging(
        level=resolved.log_level,
        json_output=resolved.environment is not Environment.DEVELOPMENT,
    )

    app = FastAPI(
        title="Askwell",
        version=__version__,
        summary="A personal AI over your own files and databases.",
        lifespan=lifespan,
    )
    app.state.settings = resolved

    @app.get("/health")
    async def health(request: Request) -> JSONResponse:
        """Report every component separately.

        Always HTTP 200, including when components are down. The request
        succeeded; the answer is the payload. A 503 here would make the shell
        unable to distinguish "Askwell is not running" from "Askwell is running
        and is telling you Postgres is down", which is the exact distinction
        this surface exists to draw.
        """
        current: Settings = request.app.state.settings
        components = await check_components(current)
        return JSONResponse(
            {
                "version": __version__,
                "environment": str(current.environment),
                "profile": str(current.profile),
                "components": [item.as_dict() for item in components],
            }
        )

    @app.exception_handler(Exception)
    async def unhandled(request: Request, error: Exception) -> JSONResponse:
        """Fail loudly in development, degrade with a stated reason otherwise.

        AGENTS.md §6. In development the exception text goes to the client,
        because the client is the developer. Elsewhere it goes only to the log,
        because a stack trace rendered into a user's window is noise to them
        and detail to anyone reading over their shoulder.
        """
        current: Settings = request.app.state.settings
        log.exception("unhandled_exception", path=request.url.path)

        detail: dict[str, Any] = {
            "error": "Askwell hit an error it did not expect.",
            "path": request.url.path,
        }
        if current.environment is Environment.DEVELOPMENT:
            detail["exception"] = f"{type(error).__name__}: {error}"
        else:
            detail["hint"] = "The reason is in the application log."
        return JSONResponse(detail, status_code=500)

    return app


def main() -> None:
    """Entry point. Refuses to start on unusable configuration, and says why."""
    import uvicorn

    try:
        settings = load_settings()
    except ConfigurationError as error:
        # Deliberately not a log line and deliberately not a traceback: nothing
        # has started, logging is not configured yet, and the person reading
        # this is looking at a terminal.
        raise SystemExit(str(error)) from None

    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        log_config=None,  # structlog owns the output; see logging.py
    )
