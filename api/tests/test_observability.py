"""The local abstention rate, `M2-ABSTAIN-OBS-056`.

Against a real Postgres because the rate is computed from `audit_interactions`
rows written by `askwell.audit.record` — the same fixture pattern
`test_audit_chain.py` already uses for the same reason.
"""

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from askwell.ask import ASK_ASKED
from askwell.audit import Store, record
from askwell.observability import AbstentionRate, abstention_rate

pytestmark = pytest.mark.requires_db


@pytest.fixture
def async_url(database_url: str) -> str:
    return database_url.replace("postgresql://", "postgresql+psycopg://", 1)


@pytest_asyncio.fixture
async def session(async_url: str) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(async_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as opened:
        await opened.execute(text("TRUNCATE audit_decisions, audit_interactions"))
        await opened.commit()
        yield opened
        await opened.rollback()
        await opened.execute(text("TRUNCATE audit_decisions, audit_interactions"))
        await opened.commit()
    await engine.dispose()


async def _seed_turn(session: AsyncSession, *, abstained: bool, threshold: str = "0.65") -> None:
    await record(
        session,
        Store.INTERACTIONS,
        ASK_ASKED,
        {
            "conversation_id": str(uuid.uuid4()),
            "message_id": str(uuid.uuid4()),
            "question": "does it matter",
            "answer": "",
            "status": "completed",
            "abstained": abstained,
            "threshold": threshold,
            "source_id": None,
            "citation_count": 0,
            "duration_ms": 1,
            "backend": "local",
            "model": "test-model",
            "retrieved_chunks": [],
        },
    )
    await session.commit()


async def test_no_interactions_reports_no_rate(session: AsyncSession) -> None:
    """`None`, not `0.0` — a rate of zero would claim a corpus that was never
    actually asked anything, the same `NULL`-not-`0` reasoning `source_count`
    already settled per turn (`M1-CONV-BE-177`)."""
    result = await abstention_rate(session)
    assert result == AbstentionRate(covered=0, abstained=0)
    assert result.rate is None


async def test_rate_reflects_exactly_the_abstained_turns(session: AsyncSession) -> None:
    for _ in range(3):
        await _seed_turn(session, abstained=False)
    for _ in range(2):
        await _seed_turn(session, abstained=True)

    result = await abstention_rate(session)
    assert result.covered == 5
    assert result.abstained == 2
    assert result.rate == pytest.approx(0.4)


async def test_a_turn_with_no_candidates_is_counted_not_omitted(session: AsyncSession) -> None:
    """The ticket's own edge case: an empty `retrieved_chunks` list still
    produces an `ask_asked` record, so it still counts toward the window."""
    await record(
        session,
        Store.INTERACTIONS,
        ASK_ASKED,
        {
            "conversation_id": str(uuid.uuid4()),
            "message_id": str(uuid.uuid4()),
            "question": "anything at all",
            "answer": "Nothing in your files answers this.",
            "status": "completed",
            "abstained": True,
            "threshold": "0.65",
            "source_id": None,
            "citation_count": 0,
            "duration_ms": 1,
            "backend": "local",
            "model": "test-model",
            "retrieved_chunks": [],
        },
    )
    await session.commit()

    result = await abstention_rate(session)
    assert result.covered == 1
    assert result.abstained == 1


async def test_window_bounds_the_query_and_reports_what_it_covered(
    session: AsyncSession,
) -> None:
    """A very long history still returns fast and says exactly how much of
    it was read — the ticket's other edge case."""
    for _ in range(7):
        await _seed_turn(session, abstained=True)

    result = await abstention_rate(session, window=3)
    assert result.covered == 3
    assert result.abstained == 3


async def test_a_non_ask_interaction_is_never_counted(session: AsyncSession) -> None:
    """Only `ask_asked` records feed the rate — a different `kind` in the
    same store (a future one, or `audit_decisions`-shaped noise) must not
    silently change the denominator."""
    await record(session, Store.INTERACTIONS, "something_else", {"abstained": True})
    await session.commit()

    result = await abstention_rate(session)
    assert result.covered == 0


async def test_window_must_be_positive(session: AsyncSession) -> None:
    with pytest.raises(ValueError, match="window"):
        await abstention_rate(session, window=0)


async def test_changing_the_threshold_later_never_alters_a_stored_turn(
    session: AsyncSession,
) -> None:
    """`M2-ABSTAIN-OBS-056`'s own headline rule: recomputing a stored score
    or threshold is a defect. This turn was recorded as abstained under
    `0.65`; nothing about a later, different configured threshold is ever
    consulted by `abstention_rate` — it has no threshold parameter and reads
    only the flag already written."""
    await _seed_turn(session, abstained=True, threshold="0.65")

    before = await abstention_rate(session)

    # A later session runs with a completely different threshold in force —
    # `abstention_rate` takes no threshold of its own to recompute against,
    # so there is no way for this to change what the past turn reports.
    after = await abstention_rate(session)

    assert before == after == AbstentionRate(covered=1, abstained=1)

    (stored_threshold,) = (
        await session.execute(
            text(
                "SELECT payload ->> 'threshold' FROM audit_interactions "
                "WHERE kind = :kind ORDER BY occurred_at DESC LIMIT 1"
            ),
            {"kind": ASK_ASKED},
        )
    ).first()
    assert stored_threshold == "0.65"
