"""Serve the built frontend from the API.

One process, one address. The `web` container is gone: this runs on a laptop
that is also running the user's browser, their editor and everything else, and
every container is a share of that.

Two of the requirements here pull against each other, and the obvious
implementation gets one of them wrong. A deep route has to load when it is
opened directly — someone bookmarks the library and comes back tomorrow. A
path that is neither an asset nor a route has to say so, rather than returning
the application shell and leaving the user looking at an interface that quietly
is not the thing they asked for.

A catch-all serving `index.html` satisfies the first and fails the second. A
strict file server does the reverse. Static export writes a real directory per
route, so both are satisfiable — the fallback just has to be deliberate rather
than a wildcard.
"""

from pathlib import Path

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

from askwell.config import Settings
from askwell.logging import get_logger

log = get_logger(__name__)

# Next writes content-hashed filenames under this prefix, so the name changes
# whenever the content does. That is what makes a long immutable cache safe —
# and it is exactly why the HTML must NOT be cached the same way: the HTML is
# what points at the new names.
HASHED_PREFIX = "_next/static/"

IMMUTABLE = "public, max-age=31536000, immutable"
REVALIDATE = "no-cache"
SHORT = "public, max-age=3600, must-revalidate"

INDEX = "index.html"
NOT_FOUND_PAGE = "404.html"


def _cache_control(relative: str) -> str:
    """How long this file may be reused without asking."""
    if relative.startswith(HASHED_PREFIX):
        return IMMUTABLE
    if relative.endswith(".html"):
        # `no-cache` does not mean "do not cache" — it means "revalidate before
        # reusing". Without it, a rebuild leaves the user on the old bundle
        # until they clear their cache by hand, and they have no reason to
        # suspect that is what happened.
        return REVALIDATE
    return SHORT


def _resolve(root: Path, requested: str) -> Path | None:
    """Map a URL path to a file inside `root`, or None.

    None covers both "not there" and "outside the directory". The caller does
    not need to tell those apart and must not tell the client apart either:
    confirming that `../../etc/passwd` exists is itself an answer.
    """
    relative = requested.strip("/")

    try:
        candidate = (root / relative).resolve()
    except (OSError, ValueError):
        return None

    # The containment check is done after resolve(), so `..` segments and
    # symlinks have already been collapsed. Checking the raw string first would
    # be a filter, and filters get bypassed.
    if not candidate.is_relative_to(root):
        log.warning("asset_path_escaped_root", requested=requested)
        return None

    if candidate.is_file():
        return candidate

    # A static-export route is a directory holding index.html. This is what
    # makes a bookmarked deep route load directly, without a wildcard that
    # would swallow typos as well.
    index = candidate / INDEX
    if index.is_file():
        return index

    return None


def _missing_build(root: Path) -> HTMLResponse:
    """What to show when there is no build at all.

    Deliberately not a blank page and deliberately not a stack trace. Whoever
    is looking at this is either a contributor who has not built the frontend
    yet, or a user whose install is broken — and both need the same two facts:
    what is missing, and the command that fixes it.
    """
    return HTMLResponse(
        f"""<!doctype html>
<meta charset="utf-8">
<title>Askwell — interface not built</title>
<style>
  body {{ font-family: ui-monospace, Menlo, Consolas, monospace;
         background: #e9ebe7; color: #232722; margin: 0;
         display: grid; place-items: center; min-height: 100vh; }}
  main {{ max-width: 40rem; padding: 2rem; }}
  code {{ background: #dfe2dd; padding: 0.15em 0.4em; border-radius: 3px; }}
  p {{ line-height: 1.6; }}
  @media (prefers-color-scheme: dark) {{
    body {{ background: #191c1a; color: #e4e7e1; }}
    code {{ background: #141715; }}
  }}
</style>
<main>
  <h1>The interface has not been built</h1>
  <p>The API is running. It is looking for the built frontend at
     <code>{root}</code> and finding nothing there.</p>
  <p>Build it: <code>scripts/dev.sh web-build</code></p>
  <p>If you just built it and are seeing this anyway, the build replaced the
     directory and the container is still holding the old one. Recreate the
     API: <code>podman compose up -d --force-recreate api</code></p>
  <p>Askwell&rsquo;s own health surface is at <code>/health</code> and works
     regardless — if you are diagnosing a broken install, start there.</p>
</main>""",
        status_code=503,
    )


def _not_found(path: str) -> JSONResponse:
    """A path that is neither an asset nor a route.

    Not the application shell. Returning the shell here would leave someone
    looking at a working-looking interface that is not the page they asked for,
    and no indication anything went wrong.
    """
    return JSONResponse(
        {
            "error": "No such page or asset.",
            "path": path,
            "hint": "Askwell serves the built interface and its assets. Check the address.",
        },
        status_code=404,
    )


def register_interface(app: FastAPI, settings: Settings) -> None:
    """Attach interface serving. Call this after every API route is registered.

    Order matters: the catch-all below would otherwise shadow `/health`.
    """
    root = settings.web_assets_dir.resolve()

    if not (root / INDEX).is_file():
        # Not fatal. The API's own surfaces have to keep working — a user
        # whose interface is missing needs /health more than anyone.
        log.warning("interface_not_built", directory=str(root))

    router = APIRouter()

    @router.get("/{path:path}", include_in_schema=False)
    async def serve(path: str, request: Request) -> Response:
        if not (root / INDEX).is_file():
            return _missing_build(root)

        target = _resolve(root, path)
        if target is None:
            # Static export writes a 404 page. Prefer it for anything that
            # looks like a page, so the user gets the product's own styling
            # rather than raw JSON.
            wants_html = "text/html" in request.headers.get("accept", "")
            page = root / NOT_FOUND_PAGE
            if wants_html and page.is_file():
                return FileResponse(page, status_code=404, headers={"Cache-Control": REVALIDATE})
            return _not_found(path)

        relative = target.relative_to(root).as_posix()
        return FileResponse(target, headers={"Cache-Control": _cache_control(relative)})

    app.include_router(router)
