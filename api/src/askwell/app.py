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
from askwell.ask import register_ask
from askwell.assistant import read as read_assistant
from askwell.config import ConfigurationError, Environment, Settings, load_settings
from askwell.db.engine import build_engine, session_factory
from askwell.health import ComponentState, check_components
from askwell.ingest import register_ingest
from askwell.interface import register_interface
from askwell.logging import configure_logging, get_logger
from askwell.middleware import register_session
from askwell.network import read_activity
from askwell.roots import register_roots
from askwell.sources import register_sources

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
        await app.state.engine.dispose()


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
    app.state.engine = build_engine(resolved)
    app.state.sessions = session_factory(app.state.engine)

    register_session(app, resolved, app.state.sessions)
    register_roots(app, app.state.sessions)
    register_sources(app, resolved, app.state.sessions)
    register_ingest(app, resolved, app.state.sessions)
    register_ask(app, resolved, app.state.sessions)

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

    @app.get("/network")
    async def network(request: Request) -> JSONResponse:
        """What the egress proxy refused, according to the egress proxy.

        A fact, not a warning. `docs/states-and-edge-cases.md` §1 forbids
        rendering an offline notice — being offline is the design point, not a
        degraded state — so there is no threshold here and no value that is
        treated as alarming.

        The counts are the proxy's. If they cannot be read the answer says so;
        it never falls back to zero, because zero is the strongest claim the
        product makes and it has to be earned.
        """
        current: Settings = request.app.state.settings
        return JSONResponse((await read_activity(current)).as_dict())

    @app.get("/assistant")
    async def assistant(request: Request) -> JSONResponse:
        """Whether the assistant can answer, why not, and what still works.

        Reaching this endpoint at all means the stack is up — which is half the
        answer. The other cause, the stack being down, needs no code here: the
        browser simply does not get a response, and the shell reads the
        difference from that.

        Always HTTP 200. The assistant being unavailable is a fact about the
        product's state, not a failure of this request, and a 503 would make
        the shell unable to tell it from Askwell itself being down — which is
        the exact distinction this endpoint exists to draw.
        """
        current: Settings = request.app.state.settings
        return JSONResponse(read_assistant(current).as_dict())

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

    # Last: its catch-all would shadow every route registered after it.
    register_interface(app, resolved)

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
