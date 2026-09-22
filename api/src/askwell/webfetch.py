"""Fetching the page content behind a web search result — capped, and never
persisted. `M6.5-WEB-BE-188`.

**Three caps, one prohibition.** A result-count cap
(`Settings.web_fetch_max_results`), a per-page size cap
(`Settings.web_fetch_max_bytes`) and a per-page timeout
(`Settings.web_fetch_timeout_seconds`) bound what `fetch_pages` will ever
attempt. Everything a cap catches is *dropped whole*, never truncated into
the prompt — truncation is how a size limit becomes a way of choosing which
half of a hostile page gets in (`docs/web-search.md` §5). A page of exactly
`web_fetch_max_bytes` bytes is kept; the byte after it is what trips the
drop — one stated rule rather than an accident of buffering.

The prohibition — fetched content is never chunked, embedded or written to
`chunks` — is structural, not something this module enforces at runtime:
`FetchedPage` has no constructor call anywhere in `askwell.ingest` or
`askwell.retrieve`, and it is returned to the caller and nowhere else.
`test_webfetch.py`'s corpus-invariance test is what would catch a future
change wiring one in, not a check this module performs on itself.

**This module fetches; it does not decide when fetching is allowed.** The
egress grant around the destination being dialled is `M6.5-WEB-SEC-187`'s
job, opened by whichever caller already knows what it is about to fetch and
why — a `WebSearchProvider` implementation such as the real `ddgs` one,
`M6.5-WEB-BE-195`, which does not exist yet. Until it does, nothing in this
codebase calls `fetch_pages` with a real URL; it is exercised directly by
its own tests.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal

import httpx

from askwell.config import Settings
from askwell.logging import get_logger

log = get_logger(__name__)

ClientFactory = Callable[[], httpx.AsyncClient]

# A page whose declared type is not one of these is dropped as "not text"
# rather than fed in as noise (this ticket's own edge case) — a PDF, an
# image, a video, all things a passage cannot meaningfully be built from
# without a separate extraction pipeline this ticket does not build.
_TEXT_CONTENT_TYPES = ("text/html", "text/plain", "application/xhtml+xml")

# Capped and abandoned rather than followed indefinitely — this ticket's own
# "a page that redirects repeatedly" edge case.
_MAX_REDIRECTS = 5


@dataclass(frozen=True, slots=True)
class FetchedPage:
    """One fetch attempt's outcome: kept whole, or dropped whole."""

    url: str
    status: Literal["ok", "dropped"]
    passage: str = ""
    reason: str | None = None
    """Set only for `"dropped"`: `"result cap reached"`, `"too large"`,
    `"not text"`, `"timed out"`, `"too many redirects"`, or the fetch
    error's own message. Never shown to the user as-is — same rule as
    `WebSearchOutcome.reason` in `askwell.websearch`."""


def _default_client(timeout_seconds: float) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(
            connect=timeout_seconds, read=timeout_seconds, write=timeout_seconds, pool=None
        ),
        follow_redirects=True,
        max_redirects=_MAX_REDIRECTS,
    )


async def _fetch_one(client: httpx.AsyncClient, url: str, *, max_bytes: int) -> FetchedPage:
    try:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
            if content_type and not any(
                content_type.startswith(kind) for kind in _TEXT_CONTENT_TYPES
            ):
                return FetchedPage(url=url, status="dropped", reason="not text")

            body = bytearray()
            async for piece in response.aiter_bytes():
                body.extend(piece)
                # Strictly over the cap, not at it — a page of exactly
                # `max_bytes` is kept whole.
                if len(body) > max_bytes:
                    return FetchedPage(url=url, status="dropped", reason="too large")

            text = body.decode(response.encoding or "utf-8", errors="replace")
    except httpx.TooManyRedirects:
        return FetchedPage(url=url, status="dropped", reason="too many redirects")
    except httpx.TimeoutException:
        return FetchedPage(url=url, status="dropped", reason="timed out")
    except httpx.HTTPError as error:
        return FetchedPage(url=url, status="dropped", reason=str(error))

    if not text.strip():
        return FetchedPage(url=url, status="dropped", reason="empty")
    return FetchedPage(url=url, status="ok", passage=text)


async def fetch_pages(
    urls: Sequence[str],
    settings: Settings,
    *,
    client_factory: ClientFactory | None = None,
) -> list[FetchedPage]:
    """Fetch at most `settings.web_fetch_max_results` of `urls`, each capped
    at `settings.web_fetch_max_bytes` and `settings.web_fetch_timeout_seconds`.

    Returns one `FetchedPage` per URL in `urls`, in order — the cap is
    applied by dropping the tail of the sequence with reason
    `"result cap reached"` rather than silently never mentioning them, so a
    caller building a citation list from this always accounts for every
    result the provider actually returned.

    Cancelling the calling task (the user stopping generation mid-fetch)
    cancels every in-flight request along with it: `asyncio.gather` and the
    client's own `async with` propagate the cancellation, closing the client
    before this ever returns, and nothing partial is retained because
    results are only assembled after every fetch finishes or is cancelled.
    """
    allowed = urls[: settings.web_fetch_max_results]
    over_cap = urls[settings.web_fetch_max_results :]

    build_client = client_factory or (lambda: _default_client(settings.web_fetch_timeout_seconds))
    async with build_client() as client:
        fetched = await asyncio.gather(
            *(_fetch_one(client, url, max_bytes=settings.web_fetch_max_bytes) for url in allowed)
        )

    pages = [
        *fetched,
        *(FetchedPage(url=url, status="dropped", reason="result cap reached") for url in over_cap),
    ]
    for page in pages:
        log.info(
            "web_fetch_attempted",
            url=page.url,
            status=page.status,
            reason=page.reason,
        )
    return pages
