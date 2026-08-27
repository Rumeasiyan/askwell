"""Establishing and requiring the local session, and refusing other origins.

Two rules meet here and they pull in opposite directions: opening Askwell must
establish a session with no prompt, and a request without a session must be
rejected. Both are satisfiable because they are about different requests — a
browser asking for the interface is asking to be given one; anything asking for
data is not.

`/health` is exempt, deliberately. It is the surface someone with a broken
install needs most, it carries component states rather than any of the user's
material, and locking it would make Askwell hardest to diagnose in exactly the
situation where diagnosis matters. That is a decision rather than an oversight,
and it is the only exemption.
"""

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from askwell import session as sessions
from askwell.config import Settings
from askwell.logging import get_logger

log = get_logger(__name__)

# Reachable without a session. See the module docstring — this list existing at
# all is the risk, so it stays at one entry and each addition needs a reason.
OPEN_PATHS = frozenset({"/health"})


def _is_interface_request(request: Request) -> bool:
    """A browser asking for a page, rather than something asking for data.

    A page request is the thing that should silently receive a session. A data
    request is the thing that should be refused without one.
    """
    if request.method not in {"GET", "HEAD"}:
        return False
    return "text/html" in request.headers.get("accept", "")


def _same_origin(request: Request) -> bool:
    """Whether a cross-origin request is what it claims to be.

    A request with no Origin is not cross-origin — that is curl, or a browser
    navigation. A request whose Origin is another site is another site's page
    reaching into Askwell using the user's own cookie, which is the whole
    reason this check exists.
    """
    origin = request.headers.get("origin")
    if origin is None:
        return True
    host = request.headers.get("host", "")
    return origin.endswith(f"//{host}") if host else False


def register_session(
    app: FastAPI, settings: Settings, factory: async_sessionmaker[AsyncSession]
) -> None:
    """Attach session handling. Register before the interface catch-all."""

    @app.middleware("http")
    async def local_session(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if not _same_origin(request):
            log.warning(
                "cross_origin_refused",
                origin=request.headers.get("origin"),
                path=request.url.path,
            )
            return JSONResponse(
                {
                    "error": "Askwell only answers requests from its own interface.",
                    "hint": "This request came from another origin.",
                },
                status_code=403,
            )

        if request.url.path in OPEN_PATHS:
            return await call_next(request)

        try:
            async with factory() as db:
                signing_secret = await sessions.secret(db)
        except Exception as error:
            # No database means no session, but the interface itself is static
            # files and the "not built" and health surfaces still work. A user
            # whose database is down needs to see something other than a blank
            # page saying nothing.
            log.warning("session_unavailable", error=f"{type(error).__name__}: {error}")
            return await call_next(request)

        existing = sessions.verify(signing_secret, request.cookies.get(sessions.COOKIE_NAME))

        if existing is None and not _is_interface_request(request):
            return JSONResponse(
                {
                    "error": "No session.",
                    "hint": (
                        "Open Askwell in your browser at this address. A session "
                        "is established when the interface loads — there is "
                        "nothing to sign in to."
                    ),
                },
                status_code=401,
            )

        response = await call_next(request)

        if existing is None:
            issued = sessions.issue(signing_secret)
            response.set_cookie(
                sessions.COOKIE_NAME,
                issued,
                max_age=sessions.MAX_AGE_SECONDS,
                httponly=True,
                samesite="lax",
                # Not `secure`: Askwell is served over http on loopback, and a
                # secure cookie would simply never be sent. Loopback is the
                # boundary here, not TLS.
                secure=False,
                path="/",
            )
            log.info(
                "session_established",
                session=sessions.Session(issued.rpartition(".")[0]).short,
                path=request.url.path,
            )

        return response
