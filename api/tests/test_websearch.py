"""The web search provider interface, the fixture implementation, and the
one call site. `M6.5-WEB-BE-185`.

`test_the_full_answer_path_never_calls_the_provider` is the ticket's own
headline acceptance criterion: escalation is structural, not a convention
someone could forget — there is no path from an abstaining answer into
`escalate_web_search`, and this test is what would catch one appearing.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import psycopg
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from askwell.config import ConfigurationError, Settings
from askwell.websearch import (
    WEB_SEARCH_ESCALATED,
    FixtureWebSearchProvider,
    WebSearchOutcome,
    WebSearchResult,
    WebSearchUnavailable,
    build_web_search_provider,
    escalate_web_search,
)

from .test_ask_api import (
    DIMENSIONS,
    _app,
    _events,
    _FakeInferenceClient,
    _patch_client,
    _truncate,
    _with_session,
)

RETRIEVED_AT = datetime(2026, 9, 22, 12, 0, 0, tzinfo=UTC)


def _result(passage: str = "The office is on the third floor.") -> WebSearchResult:
    return WebSearchResult(
        source="example.com",
        title="Office locations",
        url="https://example.com/offices",
        passage=passage,
        retrieved_at=RETRIEVED_AT,
    )


# --- the interface and the fixture, no database ------------------------------


class _SlowProvider:
    """Never answers inside any sane timeout."""

    async def search(self, question: str) -> list[WebSearchResult]:
        await asyncio.sleep(3600)
        raise AssertionError("unreachable")


class _FailingProvider:
    def __init__(self, error: Exception) -> None:
        self._error = error

    async def search(self, question: str) -> list[WebSearchResult]:
        raise self._error


async def test_fixture_provider_returns_recorded_results_for_a_known_question() -> None:
    provider = FixtureWebSearchProvider({"opening hours?": [_result()]})
    assert await provider.search("opening hours?") == [_result()]


async def test_fixture_provider_returns_nothing_for_an_unrecognised_question() -> None:
    """A fixture only knows what it was given — not the same failure as an
    unreachable provider, so it returns an empty list, not an error."""
    provider = FixtureWebSearchProvider()
    assert await provider.search("anything") == []


def test_no_provider_configured_builds_none(settings: Settings) -> None:
    assert settings.web_search_provider is None
    assert build_web_search_provider(settings) is None


def test_an_empty_configured_provider_string_also_builds_none(settings: Settings) -> None:
    """Compose's `${VAR:-}` interpolation, `config.py`'s own `_optional_path`
    rule — an empty string must mean "unconfigured", not a provider literally
    named `""`. `model_copy` skips validators, unlike constructing `Settings`
    fresh the way pydantic-settings does from the real environment, so this
    goes through `__init__` rather than `model_copy` to exercise that rule."""
    configured = Settings(**{**settings.model_dump(), "web_search_provider": ""})
    assert configured.web_search_provider is None
    assert build_web_search_provider(configured) is None


def test_configuring_fixture_builds_the_fixture_provider(settings: Settings) -> None:
    configured = settings.model_copy(update={"web_search_provider": "fixture"})
    provider = build_web_search_provider(configured)
    assert isinstance(provider, FixtureWebSearchProvider)


def test_an_unknown_provider_name_fails_loudly_rather_than_silently_degrading(
    settings: Settings,
) -> None:
    configured = settings.model_copy(update={"web_search_provider": "bing"})
    with pytest.raises(ConfigurationError, match="bing"):
        build_web_search_provider(configured)


# --- `escalate_web_search`, against a real Postgres for the audit write -----


@pytest_asyncio.fixture
async def factory(database_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    async_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_async_engine(async_url)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


def _truncate_audit(database_url: str) -> None:
    with psycopg.connect(database_url, autocommit=True) as db:
        db.execute("TRUNCATE audit_interactions CASCADE")


def _escalations(database_url: str) -> list[dict[str, object]]:
    with psycopg.connect(database_url, autocommit=True) as db:
        rows = db.execute(
            "SELECT payload FROM audit_interactions WHERE kind = %s ORDER BY occurred_at",
            (WEB_SEARCH_ESCALATED,),
        ).fetchall()
    return [row[0] for row in rows]


@pytest.mark.requires_db
async def test_no_provider_configured_is_unavailable_not_a_crash(
    settings: Settings, factory: async_sessionmaker[AsyncSession], database_url: str
) -> None:
    _truncate_audit(database_url)
    conversation_id, message_id = uuid.uuid4(), uuid.uuid4()
    async with factory() as db:
        outcome = await escalate_web_search(
            settings,
            db,
            conversation_id=conversation_id,
            message_id=message_id,
            question="what time do they open?",
        )
        await db.commit()

    assert outcome == WebSearchOutcome(status="unavailable", reason="no provider configured")
    (payload,) = _escalations(database_url)
    assert payload["status"] == "unavailable"
    assert payload["provider"] == "none"
    assert payload["question"] == "what time do they open?"
    assert payload["result_count"] == 0


@pytest.mark.requires_db
async def test_results_are_returned_and_recorded(
    settings: Settings, factory: async_sessionmaker[AsyncSession], database_url: str
) -> None:
    _truncate_audit(database_url)
    provider = FixtureWebSearchProvider({"opening hours?": [_result()]})
    async with factory() as db:
        outcome = await escalate_web_search(
            settings,
            db,
            conversation_id=uuid.uuid4(),
            message_id=uuid.uuid4(),
            question="opening hours?",
            provider=provider,
        )
        await db.commit()

    assert outcome.status == "ok"
    assert outcome.results == (_result(),)
    (payload,) = _escalations(database_url)
    assert payload["status"] == "ok"
    assert payload["result_count"] == 1


@pytest.mark.requires_db
async def test_nothing_matched_is_distinct_from_unavailable(
    settings: Settings, factory: async_sessionmaker[AsyncSession], database_url: str
) -> None:
    _truncate_audit(database_url)
    provider = FixtureWebSearchProvider()  # answers everything with []
    async with factory() as db:
        outcome = await escalate_web_search(
            settings,
            db,
            conversation_id=uuid.uuid4(),
            message_id=uuid.uuid4(),
            question="anything",
            provider=provider,
        )
        await db.commit()

    assert outcome == WebSearchOutcome(status="no_results")
    (payload,) = _escalations(database_url)
    assert payload["status"] == "no_results"
    assert payload["reason"] is None


@pytest.mark.requires_db
async def test_a_result_with_no_usable_passage_is_dropped_not_rendered_empty(
    settings: Settings, factory: async_sessionmaker[AsyncSession], database_url: str
) -> None:
    provider = FixtureWebSearchProvider({"q": [_result(passage="   ")]})
    async with factory() as db:
        outcome = await escalate_web_search(
            settings,
            db,
            conversation_id=uuid.uuid4(),
            message_id=uuid.uuid4(),
            question="q",
            provider=provider,
        )
        await db.commit()

    # Every candidate was dropped, so this reads as nothing usable came
    # back — the same state as a provider that genuinely found nothing,
    # never as an error.
    assert outcome.status == "no_results"
    assert outcome.results == ()


@pytest.mark.requires_db
async def test_a_result_with_an_unresolvable_url_is_kept_with_its_url_and_date(
    settings: Settings, factory: async_sessionmaker[AsyncSession], database_url: str
) -> None:
    """The citation must remain honest even once the page is gone — the URL
    and the retrieval date are what make that possible, so a result is only
    ever dropped for a missing passage, never for a URL that might not
    resolve (`escalate_web_search` cannot know that anyway)."""
    stale = WebSearchResult(
        source="gone.example",
        title="A page that no longer exists",
        url="https://gone.example/404-eventually",
        passage="The passage as it was captured.",
        retrieved_at=RETRIEVED_AT,
    )
    provider = FixtureWebSearchProvider({"q": [stale]})
    async with factory() as db:
        outcome = await escalate_web_search(
            settings,
            db,
            conversation_id=uuid.uuid4(),
            message_id=uuid.uuid4(),
            question="q",
            provider=provider,
        )
        await db.commit()

    assert outcome.status == "ok"
    assert outcome.results == (stale,)


@pytest.mark.requires_db
async def test_provider_unreachable_is_recorded_as_unavailable_with_its_reason(
    settings: Settings, factory: async_sessionmaker[AsyncSession], database_url: str
) -> None:
    provider = _FailingProvider(WebSearchUnavailable("connection refused"))
    async with factory() as db:
        outcome = await escalate_web_search(
            settings,
            db,
            conversation_id=uuid.uuid4(),
            message_id=uuid.uuid4(),
            question="q",
            provider=provider,
        )
        await db.commit()

    assert outcome.status == "unavailable"
    assert outcome.reason == "connection refused"


@pytest.mark.requires_db
async def test_a_provider_that_never_answers_is_abandoned_at_the_configured_timeout(
    settings: Settings, factory: async_sessionmaker[AsyncSession], database_url: str
) -> None:
    fast_timeout = settings.model_copy(update={"web_search_timeout_seconds": 0.05})
    async with factory() as db:
        outcome = await escalate_web_search(
            fast_timeout,
            db,
            conversation_id=uuid.uuid4(),
            message_id=uuid.uuid4(),
            question="q",
            provider=_SlowProvider(),
        )
        await db.commit()

    assert outcome.status == "unavailable"
    assert outcome.reason == "timed out"


# --- the structural guarantee: zero calls from the ordinary answer path -----


@pytest.mark.requires_db
def test_the_full_answer_path_never_calls_the_provider(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path, database_url: str
) -> None:
    """`M6.5-WEB-BE-185`'s own acceptance criterion: running the entire
    answer path over a corpus that answers nothing produces **zero** calls
    to the provider. `askwell.ask` never imports `askwell.websearch` at
    all — every invocation is recorded (`escalate_web_search`'s own
    audit write), so the absence of any `web_search_escalated` row after a
    run of abstaining questions is the proof, not an inference from reading
    the source.
    """
    configured = settings.model_copy(update={"web_search_provider": "fixture"})
    _truncate(database_url)
    _truncate_audit(database_url)
    fake = _FakeInferenceClient(
        configured, tokens=["should never be sent"], vector=[0.0] * DIMENSIONS
    )
    _patch_client(monkeypatch, fake)

    client = _app(configured, monkeypatch, tmp_path, database_url)
    with client:
        _with_session(client)
        for question in (
            "What colour is the office?",
            "Who founded the company?",
            "What is the refund policy?",
        ):
            response = client.post("/ask", json={"question": question})
            assert response.status_code == 200
            done = next(data for kind, data in _events(response.text) if kind == "done")
            assert done["status"] == "completed"

    assert _escalations(database_url) == []
