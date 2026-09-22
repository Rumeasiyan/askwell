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
from dataclasses import dataclass
from datetime import UTC, datetime

import psycopg
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from askwell import websearch
from askwell.config import ConfigurationError, Settings
from askwell.inference.client import InferenceUnavailable
from askwell.websearch import (
    WEB_SEARCH_ESCALATED,
    WEB_SEARCH_GRANT_CLOSED,
    WEB_SEARCH_GRANT_OPENED,
    FixtureWebSearchProvider,
    WebCitationRecord,
    WebSearchOutcome,
    WebSearchResult,
    WebSearchUnavailable,
    build_web_search_provider,
    compose_and_generate_web_answer,
    escalate_web_search,
    record_web_citations,
    web_citation_record,
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
    return _interactions(database_url, WEB_SEARCH_ESCALATED)


def _interactions(database_url: str, kind: str) -> list[dict[str, object]]:
    with psycopg.connect(database_url, autocommit=True) as db:
        rows = db.execute(
            "SELECT payload FROM audit_interactions WHERE kind = %s ORDER BY occurred_at",
            (kind,),
        ).fetchall()
    return [row[0] for row in rows]


@dataclass
class _GrantCalls:
    opened: list[tuple[str, str]]
    closed: list[str]
    accepted: list[bool]


@pytest.fixture
def grant_calls(monkeypatch: pytest.MonkeyPatch) -> _GrantCalls:
    """Records every `open_grant`/`close_grant` call without touching Redis —
    `test_update_check.py`'s own `egress_calls` fixture follows the same
    convention for `permit_destination`/`revoke_destination`."""
    calls = _GrantCalls(opened=[], closed=[], accepted=[])

    async def _open(
        _settings: Settings,
        *,
        turn_id: str,
        destination: str,
        accepted: bool,
        ttl_seconds: float,
    ) -> bool:
        calls.accepted.append(accepted)
        if not accepted:
            return False
        calls.opened.append((turn_id, destination))
        return True

    async def _close(_settings: Settings, turn_id: str) -> None:
        calls.closed.append(turn_id)

    monkeypatch.setattr(websearch.egress, "open_grant", _open)
    monkeypatch.setattr(websearch.egress, "close_grant", _close)
    return calls


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


# --- the egress grant, `M6.5-WEB-SEC-187` ------------------------------------


@pytest.mark.requires_db
async def test_no_provider_configured_opens_no_grant(
    settings: Settings,
    factory: async_sessionmaker[AsyncSession],
    database_url: str,
    grant_calls: _GrantCalls,
) -> None:
    """Nothing will ever dial out, so there is nothing to grant access to —
    opening one anyway would be a grant that outlives its own reason to
    exist before it even started."""
    _truncate_audit(database_url)
    async with factory() as db:
        await escalate_web_search(
            settings,
            db,
            conversation_id=uuid.uuid4(),
            message_id=uuid.uuid4(),
            question="q",
        )
        await db.commit()

    assert grant_calls.opened == []
    assert grant_calls.closed == []
    assert _interactions(database_url, WEB_SEARCH_GRANT_OPENED) == []


@pytest.mark.requires_db
async def test_a_configured_escalation_opens_and_closes_a_grant_around_the_call(
    settings: Settings,
    factory: async_sessionmaker[AsyncSession],
    database_url: str,
    grant_calls: _GrantCalls,
) -> None:
    """The grant's lifetime is exactly the provider call — opened before it,
    closed in `finally` after, scoped to this turn's own `message_id` and
    named with the destination the settings fixture defaults to."""
    _truncate_audit(database_url)
    configured = settings.model_copy(update={"web_search_provider": "fixture"})
    message_id = uuid.uuid4()
    provider = FixtureWebSearchProvider({"opening hours?": [_result()]})
    async with factory() as db:
        outcome = await escalate_web_search(
            configured,
            db,
            conversation_id=uuid.uuid4(),
            message_id=message_id,
            question="opening hours?",
            provider=provider,
        )
        await db.commit()

    assert outcome.status == "ok"
    expected_destination = (
        f"{configured.web_search_destination_host}:{configured.web_search_destination_port}"
    )
    assert grant_calls.accepted == [True]
    assert grant_calls.opened == [(str(message_id), expected_destination)]
    assert grant_calls.closed == [str(message_id)]

    (opened_payload,) = _interactions(database_url, WEB_SEARCH_GRANT_OPENED)
    assert opened_payload["message_id"] == str(message_id)
    assert opened_payload["destination"] == expected_destination

    (closed_payload,) = _interactions(database_url, WEB_SEARCH_GRANT_CLOSED)
    assert closed_payload["message_id"] == str(message_id)
    assert closed_payload["destination"] == expected_destination


@pytest.mark.requires_db
async def test_the_grant_closes_even_when_the_provider_raises_unexpectedly(
    settings: Settings,
    factory: async_sessionmaker[AsyncSession],
    database_url: str,
    grant_calls: _GrantCalls,
) -> None:
    """A failure path that leaks a grant is the worst version of this bug —
    `finally` closes it even for an exception `escalate_web_search` does not
    itself catch and goes on to propagate."""
    _truncate_audit(database_url)
    configured = settings.model_copy(update={"web_search_provider": "fixture"})
    message_id = uuid.uuid4()
    async with factory() as db:
        with pytest.raises(RuntimeError, match="boom"):
            await escalate_web_search(
                configured,
                db,
                conversation_id=uuid.uuid4(),
                message_id=message_id,
                question="q",
                provider=_FailingProvider(RuntimeError("boom")),
            )
        await db.commit()

    assert grant_calls.opened == [
        (
            str(message_id),
            f"{configured.web_search_destination_host}:{configured.web_search_destination_port}",
        )
    ]
    assert grant_calls.closed == [str(message_id)]


@pytest.mark.requires_db
async def test_the_grant_closes_when_the_turn_is_cancelled_mid_search(
    settings: Settings,
    factory: async_sessionmaker[AsyncSession],
    database_url: str,
    grant_calls: _GrantCalls,
) -> None:
    """The user pressing stop while a search is in flight cancels the
    coroutine running `escalate_web_search` — the grant must close with it,
    not outlive it while an abandoned request keeps running."""
    _truncate_audit(database_url)
    configured = settings.model_copy(update={"web_search_provider": "fixture"})
    message_id = uuid.uuid4()
    async with factory() as db:
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(
                escalate_web_search(
                    configured,
                    db,
                    conversation_id=uuid.uuid4(),
                    message_id=message_id,
                    question="q",
                    provider=_SlowProvider(),
                ),
                timeout=0.05,
            )

    assert grant_calls.opened == [
        (
            str(message_id),
            f"{configured.web_search_destination_host}:{configured.web_search_destination_port}",
        )
    ]
    assert grant_calls.closed == [str(message_id)]


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


# --- `web_citations`: the record shape stored with the turn -----------------
# `M6.5-WEB-BE-189`.


@pytest.fixture
def owner(database_url: str):
    """Connected as the table owner, for setting up rows and inserting
    directly — `test_invariants.py`'s own fixture, redefined locally rather
    than imported since pytest fixtures do not cross test modules."""
    with psycopg.connect(database_url, autocommit=True) as connection:
        yield connection
        connection.execute("TRUNCATE conversations CASCADE")


def _insert_message(database_url: str) -> uuid.UUID:
    with psycopg.connect(database_url, autocommit=True) as db:
        conversation = db.execute(
            "INSERT INTO conversations DEFAULT VALUES RETURNING id"
        ).fetchone()
        assert conversation is not None
        message = db.execute(
            "INSERT INTO messages (conversation_id, role, content) "
            "VALUES (%s, 'assistant', 'The office is on the third floor.') RETURNING id",
            (conversation[0],),
        ).fetchone()
        assert message is not None
        return message[0]


def _web_citations(database_url: str, message_id: uuid.UUID) -> list[dict[str, object]]:
    with psycopg.connect(database_url, autocommit=True) as db:
        rows = db.execute(
            "SELECT claim_ordinal, domain, title, url, passage, retrieved_at "
            "FROM web_citations WHERE message_id = %s ORDER BY claim_ordinal",
            (message_id,),
        ).fetchall()
    columns = ("claim_ordinal", "domain", "title", "url", "passage", "retrieved_at")
    return [dict(zip(columns, row, strict=True)) for row in rows]


def test_web_citation_record_carries_the_result_tied_to_its_claim() -> None:
    record = web_citation_record(_result(), claim_ordinal=2)
    assert record == WebCitationRecord(
        claim_ordinal=2,
        domain="example.com",
        title="Office locations",
        url="https://example.com/offices",
        passage="The office is on the third floor.",
        retrieved_at=RETRIEVED_AT,
    )


@pytest.mark.requires_db
async def test_a_web_citation_round_trips_with_no_network_involved(
    factory: async_sessionmaker[AsyncSession], database_url: str
) -> None:
    """Reading a stored web result back returns exactly what was written —
    the ticket's own headline acceptance criterion — using only a database
    connection, nothing that could reach a network."""
    message_id = _insert_message(database_url)
    record = web_citation_record(_result(), claim_ordinal=0)
    async with factory() as db:
        await record_web_citations(db, message_id=message_id, records=[record])
        await db.commit()

    (stored,) = _web_citations(database_url, message_id)
    assert stored["domain"] == "example.com"
    assert stored["title"] == "Office locations"
    assert stored["url"] == "https://example.com/offices"
    assert stored["passage"] == "The office is on the third floor."
    assert stored["retrieved_at"] == RETRIEVED_AT
    assert stored["claim_ordinal"] == 0


@pytest.mark.requires_db
async def test_two_results_from_the_same_domain_are_stored_separately(
    factory: async_sessionmaker[AsyncSession], database_url: str
) -> None:
    message_id = _insert_message(database_url)
    first = web_citation_record(_result("The office opens at nine."), claim_ordinal=0)
    second = web_citation_record(_result("The office closes at five."), claim_ordinal=1)
    async with factory() as db:
        await record_web_citations(db, message_id=message_id, records=[first, second])
        await db.commit()

    stored = _web_citations(database_url, message_id)
    assert [row["passage"] for row in stored] == [
        "The office opens at nine.",
        "The office closes at five.",
    ]
    assert [row["url"] for row in stored] == [
        "https://example.com/offices",
        "https://example.com/offices",
    ]


@pytest.mark.requires_db
async def test_a_result_not_used_in_any_claim_is_never_written(
    factory: async_sessionmaker[AsyncSession], database_url: str
) -> None:
    """`record_web_citations` only ever writes what the caller hands it —
    the caller's own job (not built by this ticket) is to hand it nothing
    for a fetched-but-uncited result."""
    message_id = _insert_message(database_url)
    async with factory() as db:
        await record_web_citations(db, message_id=message_id, records=[])
        await db.commit()

    assert _web_citations(database_url, message_id) == []


@pytest.mark.requires_db
def test_retrieved_at_is_mandatory_at_the_database_itself(
    owner: psycopg.Connection[tuple[object, ...]], database_url: str
) -> None:
    """The ticket's own Validation Rule: a web result without a retrieval
    timestamp may not be rendered. Enforced at the row's own shape, not left
    to every reader to check, so a caller bypassing `record_web_citations`
    entirely still cannot produce an undated row."""
    message_id = _insert_message(database_url)
    with pytest.raises(psycopg.errors.NotNullViolation):
        owner.execute(
            "INSERT INTO web_citations (message_id, claim_ordinal, domain, title, url, passage) "
            "VALUES (%s, 0, 'example.com', 'Title', 'https://example.com', 'passage')",
            (message_id,),
        )


@pytest.mark.requires_db
def test_a_web_citation_is_cascade_deleted_with_its_message(
    owner: psycopg.Connection[tuple[object, ...]], database_url: str
) -> None:
    """Same lifecycle as `citations` — a web citation belongs to the turn
    that produced it and has no independent existence once the turn is
    gone."""
    message_id = _insert_message(database_url)
    owner.execute(
        "INSERT INTO web_citations "
        "(message_id, claim_ordinal, domain, title, url, passage, retrieved_at) "
        "VALUES (%s, 0, 'example.com', 'Title', 'https://example.com', 'passage', now())",
        (message_id,),
    )
    owner.execute("DELETE FROM messages WHERE id = %s", (message_id,))
    assert _web_citations(database_url, message_id) == []


# --- `compose_and_generate_web_answer`: the escalation's own answer ---------
# `M6.5-WEB-FE-191`.


def test_compose_and_generate_web_answer_returns_text_and_local_citations(
    settings: Settings,
) -> None:
    fake = _FakeInferenceClient(settings, tokens=["The office opens at nine ", "[1]."], vector=[])
    result = asyncio.run(
        compose_and_generate_web_answer(settings, question="q", results=[_result()], client=fake)
    )
    assert result is not None
    text, records = result
    assert text == "The office opens at nine [1]."
    assert records == [web_citation_record(_result(), claim_ordinal=1)]


def test_compose_and_generate_web_answer_ordinals_are_local_not_offset(settings: Settings) -> None:
    """This function's own contract: it does not know or care how many
    claims the turn's stored answer already has — offsetting into the
    turn's shared numbering space is `ask_escalate_web`'s job, not this
    one's (its own docstring)."""
    two_results = [_result("first"), _result("second passage")]
    fake = _FakeInferenceClient(settings, tokens=["First ", "[1]. ", "Second ", "[2]."], vector=[])
    result = asyncio.run(
        compose_and_generate_web_answer(settings, question="q", results=two_results, client=fake)
    )
    assert result is not None
    _, records = result
    assert [record.claim_ordinal for record in records] == [1, 2]


def test_compose_and_generate_web_answer_ignores_an_index_past_the_result_list(
    settings: Settings,
) -> None:
    """A model citing `[2]` when only one result was ever delimited is the
    same "hallucinated reference number" case `_cite_claim` (`ask.py`)
    already treats as a grounding problem, not a crash — skipped rather
    than raised."""
    fake = _FakeInferenceClient(settings, tokens=["Something ", "[2]."], vector=[])
    result = asyncio.run(
        compose_and_generate_web_answer(settings, question="q", results=[_result()], client=fake)
    )
    assert result is not None
    _, records = result
    assert records == []


def test_compose_and_generate_web_answer_degrades_to_none_when_the_model_is_unavailable(
    settings: Settings,
) -> None:
    fake = _FakeInferenceClient(
        settings, tokens=[], vector=[], fail=InferenceUnavailable("loading")
    )
    result = asyncio.run(
        compose_and_generate_web_answer(settings, question="q", results=[_result()], client=fake)
    )
    assert result is None
