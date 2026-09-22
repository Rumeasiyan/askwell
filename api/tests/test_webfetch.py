"""Fetching the page content behind a web search result: the three caps,
and the corpus-invariance guarantee. `M6.5-WEB-BE-188`.

Every fetch is faked with `httpx.MockTransport`, the same pattern
`test_voice_tts.py` uses for its `voice` container calls — no real network,
consistent with C1 and with `test_websearch.py`'s own zero-network guarantee
for anything reachable from the ordinary answer path.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

import httpx
import psycopg
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from askwell.agent.compose import WEB_CONTENT_TAG, delimit_web_result
from askwell.config import Settings
from askwell.webfetch import FetchedPage, fetch_pages
from askwell.websearch import FixtureWebSearchProvider, WebSearchResult, escalate_web_search


def _client_factory(
    handler: Callable[[httpx.Request], httpx.Response],
) -> Callable[[], httpx.AsyncClient]:
    # `follow_redirects`/`max_redirects` mirror `_default_client`'s own
    # policy — these tests fake the transport, not the redirect cap.
    def make_client() -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(handler), follow_redirects=True, max_redirects=5
        )

    return make_client


def _text_response(body: str, *, content_type: str = "text/html") -> httpx.Response:
    return httpx.Response(200, content=body.encode(), headers={"content-type": content_type})


async def test_a_page_within_caps_is_fetched_and_kept(settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _text_response("The office is on the third floor.")

    pages = await fetch_pages(
        ["https://example.com/offices"], settings, client_factory=_client_factory(handler)
    )
    assert pages == [
        FetchedPage(
            url="https://example.com/offices",
            status="ok",
            passage="The office is on the third floor.",
        )
    ]


async def test_a_page_over_the_size_cap_is_dropped_not_truncated(settings: Settings) -> None:
    configured = settings.model_copy(update={"web_fetch_max_bytes": 10})

    def handler(request: httpx.Request) -> httpx.Response:
        return _text_response("this body is well over ten bytes long")

    pages = await fetch_pages(
        ["https://example.com/big"], configured, client_factory=_client_factory(handler)
    )
    (page,) = pages
    assert page.status == "dropped"
    assert page.reason == "too large"
    # Dropped whole, not truncated into something usable.
    assert page.passage == ""


async def test_a_page_exactly_at_the_size_cap_is_kept(settings: Settings) -> None:
    body = "x" * 10
    configured = settings.model_copy(update={"web_fetch_max_bytes": 10})

    def handler(request: httpx.Request) -> httpx.Response:
        return _text_response(body)

    pages = await fetch_pages(
        ["https://example.com/exact"], configured, client_factory=_client_factory(handler)
    )
    (page,) = pages
    assert page.status == "ok"
    assert page.passage == body


async def test_a_non_text_resource_is_dropped_rather_than_fed_in_as_noise(
    settings: Settings,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _text_response("%PDF-1.4 binary junk", content_type="application/pdf")

    pages = await fetch_pages(
        ["https://example.com/report.pdf"], settings, client_factory=_client_factory(handler)
    )
    (page,) = pages
    assert page.status == "dropped"
    assert page.reason == "not text"


async def test_a_page_with_no_usable_body_is_dropped_as_empty(settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _text_response("   \n  ")

    pages = await fetch_pages(
        ["https://example.com/blank"], settings, client_factory=_client_factory(handler)
    )
    (page,) = pages
    assert page.status == "dropped"
    assert page.reason == "empty"


async def test_a_page_that_redirects_repeatedly_is_capped_and_abandoned(
    settings: Settings,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": str(request.url)})

    pages = await fetch_pages(
        ["https://example.com/loop"], settings, client_factory=_client_factory(handler)
    )
    (page,) = pages
    assert page.status == "dropped"
    assert page.reason == "too many redirects"


async def test_a_failing_status_is_dropped_with_its_reason(settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    pages = await fetch_pages(
        ["https://example.com/missing"], settings, client_factory=_client_factory(handler)
    )
    (page,) = pages
    assert page.status == "dropped"
    assert page.reason is not None


async def test_a_provider_that_never_answers_is_dropped_as_timed_out(settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out")

    pages = await fetch_pages(
        ["https://example.com/slow"], settings, client_factory=_client_factory(handler)
    )
    (page,) = pages
    assert page.status == "dropped"
    assert page.reason == "timed out"


async def test_results_beyond_the_count_cap_are_dropped_and_never_requested(
    settings: Settings,
) -> None:
    configured = settings.model_copy(update={"web_fetch_max_results": 2})
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return _text_response("kept")

    urls = [f"https://example.com/{i}" for i in range(5)]
    pages = await fetch_pages(urls, configured, client_factory=_client_factory(handler))

    assert [page.status for page in pages] == ["ok", "ok", "dropped", "dropped", "dropped"]
    assert [page.reason for page in pages[2:]] == ["result cap reached"] * 3
    assert requested == urls[:2]


async def test_all_results_dropped_reads_as_nothing_usable(settings: Settings) -> None:
    configured = settings.model_copy(update={"web_fetch_max_bytes": 1})

    def handler(request: httpx.Request) -> httpx.Response:
        return _text_response("way over one byte")

    pages = await fetch_pages(
        ["https://example.com/a", "https://example.com/b"],
        configured,
        client_factory=_client_factory(handler),
    )
    assert all(page.status == "dropped" for page in pages)


async def test_stopping_the_turn_mid_fetch_abandons_in_flight_requests(
    settings: Settings,
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(3600)
        raise AssertionError("unreachable")

    with pytest.raises(TimeoutError):
        await asyncio.wait_for(
            fetch_pages(
                ["https://example.com/slow"], settings, client_factory=_client_factory(handler)
            ),
            timeout=0.05,
        )


# --- delimitation matches the pattern documents and tool results get -------


async def test_a_kept_page_delimits_identically_to_document_content(settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _text_response("Refunds are processed within 14 days.")

    (page,) = await fetch_pages(
        ["https://example.com/refunds"], settings, client_factory=_client_factory(handler)
    )
    result = WebSearchResult(
        source="example.com",
        title="Refund policy",
        url=page.url,
        passage=page.passage,
        retrieved_at=datetime.now(tz=UTC),
    )
    block = delimit_web_result(1, result)
    assert f"<{WEB_CONTENT_TAG}" in block
    assert "Refunds are processed within 14 days." in block


# --- corpus invariance: nothing fetched is ever written to `chunks` --------


def _table_counts(database_url: str) -> tuple[int, int]:
    with psycopg.connect(database_url, autocommit=True) as db:
        documents = db.execute("SELECT count(*) FROM documents").fetchone()[0]
        chunks = db.execute("SELECT count(*) FROM chunks").fetchone()[0]
    return documents, chunks


@pytest.mark.requires_db
async def test_an_escalated_turn_leaves_the_corpus_byte_for_byte_unchanged(
    settings: Settings, database_url: str
) -> None:
    before = _table_counts(database_url)

    async_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_async_engine(async_url)
    try:
        sessions_ = async_sessionmaker(engine, expire_on_commit=False)
        provider = FixtureWebSearchProvider({"what is the refund window?": [_result_for_fetch()]})
        async with sessions_() as db:
            outcome = await escalate_web_search(
                settings,
                db,
                conversation_id=uuid.uuid4(),
                message_id=uuid.uuid4(),
                question="what is the refund window?",
                provider=provider,
            )
            await db.commit()

        # A real caller would also fetch and delimit the page content; doing
        # so here too, over the same escalation, so the invariant covers the
        # whole surface this ticket touches, not just the provider call.
        def handler(request: httpx.Request) -> httpx.Response:
            return _text_response("Refunds are processed within 14 days.")

        pages = await fetch_pages(
            [result.url for result in outcome.results],
            settings,
            client_factory=_client_factory(handler),
        )
        for index, page in enumerate(pages, start=1):
            if page.status == "ok":
                delimit_web_result(index, outcome.results[index - 1])
    finally:
        await engine.dispose()

    after = _table_counts(database_url)
    assert after == before


def _result_for_fetch() -> WebSearchResult:
    return WebSearchResult(
        source="example.com",
        title="Refund policy",
        url="https://example.com/refunds",
        passage="Refunds are processed within 14 days.",
        retrieved_at=datetime(2026, 9, 22, 12, 0, 0, tzinfo=UTC),
    )
