"""The chain against a real Postgres.

The round trip through `jsonb` is the part that can only be tested here. If
Postgres renders a stored payload differently from what was hashed, every
record verifies as tampered — which is worse than having no verification,
because it accuses the user of something they did not do.

These also test the two behaviours that are the whole point of the feature:
verification names the record where a manually altered chain breaks, and an
audit write that fails takes the action down with it.
"""

import asyncio
import json
import os
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from askwell.audit import GENESIS, Break, Store, record, verify

pytestmark = pytest.mark.requires_db

OWNER_URL = "TEST_DATABASE_URL"


def _async_url() -> str:
    value = os.environ.get(OWNER_URL)
    if not value:
        raise RuntimeError(
            f"{OWNER_URL} is not set. The chain's round trip through jsonb can "
            f"only be tested against a real Postgres. Run: scripts/dev.sh test-db"
        )
    return value.replace("postgresql://", "postgresql+psycopg://", 1)


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(_async_url())
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as opened:
        await opened.execute(text("TRUNCATE audit_decisions, audit_interactions"))
        await opened.commit()
        yield opened
        await opened.rollback()
        await opened.execute(text("TRUNCATE audit_decisions, audit_interactions"))
        await opened.commit()
    await engine.dispose()


async def test_an_empty_chain_verifies(session: AsyncSession) -> None:
    result = await verify(session, Store.DECISIONS)
    assert result.intact
    assert result.checked == 0


async def test_the_first_record_chains_to_genesis(session: AsyncSession) -> None:
    await record(session, Store.DECISIONS, "source_added", {"name": "contracts"})
    await session.commit()

    row = (await session.execute(text("SELECT prev_hash FROM audit_decisions"))).first()
    assert row is not None
    assert row[0] == GENESIS


async def test_a_written_chain_verifies_after_the_round_trip(session: AsyncSession) -> None:
    """The test this module exists for.

    Everything below is hashed in Python and read back out of `jsonb`. If
    Postgres normalises anything differently, this fails.
    """
    payloads = [
        {"name": "contracts", "kind": "file"},
        {"note": 'unicode: договор, quotes: "x", slash: /'},
        {"nested": {"z": "last", "a": "first"}, "list": [1, 2, 3]},
        {"rows": 0, "ok": False, "reason": None},
    ]
    for index, payload in enumerate(payloads):
        await record(session, Store.DECISIONS, f"event_{index}", payload)
    await session.commit()

    result = await verify(session, Store.DECISIONS)
    assert result.intact, str(result)
    assert result.checked == len(payloads)


async def test_verification_names_the_record_whose_contents_were_altered(
    session: AsyncSession,
) -> None:
    """A user edits a row directly with a database client, out of curiosity."""
    for index in range(4):
        await record(session, Store.DECISIONS, f"event_{index}", {"index": index})
    await session.commit()

    target = (
        await session.execute(
            text("SELECT id FROM audit_decisions ORDER BY occurred_at ASC OFFSET 2 LIMIT 1")
        )
    ).first()
    assert target is not None
    # As the owner, because the application role cannot do this at all (C6).
    await session.execute(
        text("UPDATE audit_decisions SET payload = CAST(:p AS jsonb) WHERE id = :id"),
        {"p": json.dumps({"index": 99}), "id": target[0]},
    )
    await session.commit()

    result = await verify(session, Store.DECISIONS)
    assert not result.intact
    assert result.first_break == uuid.UUID(str(target[0]))
    assert result.reason is Break.ALTERED
    assert result.checked == 2, "it should stop at the first break, not carry on"


async def test_verification_reports_a_removed_record_as_unlinked(
    session: AsyncSession,
) -> None:
    """Deletion does not leave a gap the chain can see — it leaves a link that
    no longer joins up, which is a different message and a different cause."""
    for index in range(4):
        await record(session, Store.DECISIONS, f"event_{index}", {"index": index})
    await session.commit()

    await session.execute(
        text(
            "DELETE FROM audit_decisions WHERE id IN "
            "(SELECT id FROM audit_decisions ORDER BY occurred_at ASC OFFSET 1 LIMIT 1)"
        )
    )
    await session.commit()

    result = await verify(session, Store.DECISIONS)
    assert not result.intact
    assert result.reason is Break.UNLINKED
    assert "has been removed" in result.detail


async def test_the_two_stores_have_independent_chains(session: AsyncSession) -> None:
    """Separate on purpose: different retention and different volume.

    Pruning the interaction window must not break the decisions chain.
    """
    await record(session, Store.DECISIONS, "source_added", {"name": "contracts"})
    await record(session, Store.INTERACTIONS, "question_asked", {"chars": 42})
    await session.commit()

    await session.execute(text("TRUNCATE audit_interactions"))
    await session.commit()

    assert (await verify(session, Store.DECISIONS)).intact
    assert (await verify(session, Store.INTERACTIONS)).intact


async def test_a_failed_audit_write_fails_the_action(session: AsyncSession) -> None:
    """A decision that could not be recorded did not happen.

    The alternative is a memory fact with no audit record behind it, which is
    exactly the state nobody can later explain.
    """
    await session.execute(text("INSERT INTO sources (kind, name) VALUES ('file', 'contracts')"))

    with pytest.raises(DBAPIError):
        # A kind longer than the column allows: a stand-in for any audit write
        # that fails for a reason the caller did not anticipate.
        await record(session, Store.DECISIONS, "k" * 200, {"name": "contracts"})
        await session.commit()

    await session.rollback()

    remaining = (await session.execute(text("SELECT count(*) FROM sources"))).scalar_one()
    assert remaining == 0, "the action committed without its audit record"


async def test_a_successful_action_and_its_record_commit_together(
    session: AsyncSession,
) -> None:
    await session.execute(text("INSERT INTO sources (kind, name) VALUES ('file', 'contracts')"))
    await record(session, Store.DECISIONS, "source_added", {"name": "contracts"})
    await session.commit()

    sources = (await session.execute(text("SELECT count(*) FROM sources"))).scalar_one()
    records = (await session.execute(text("SELECT count(*) FROM audit_decisions"))).scalar_one()
    assert sources == 1
    assert records == 1

    await session.execute(text("TRUNCATE sources CASCADE"))
    await session.commit()


async def test_concurrent_writes_serialise_rather_than_fork(session: AsyncSession) -> None:
    """Two writes racing must not both chain to the same predecessor.

    A forked chain does not look broken. It looks like one of the two branches
    was deleted — so the user would be told their log had been tampered with,
    by their own software, for doing two things at once.

    Each writer gets its own connection, because an advisory transaction lock
    taken twice on one connection is not a race.
    """
    engine = create_async_engine(_async_url())
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def write(index: int) -> None:
        async with factory() as own:
            await record(own, Store.INTERACTIONS, "question_asked", {"index": index})
            await own.commit()

    try:
        await asyncio.gather(*(write(index) for index in range(8)))
    finally:
        await engine.dispose()

    result = await verify(session, Store.INTERACTIONS)
    assert result.intact, str(result)
    assert result.checked == 8

    distinct_prev = (
        await session.execute(text("SELECT count(DISTINCT prev_hash) FROM audit_interactions"))
    ).scalar_one()
    assert distinct_prev == 8, "two records share a predecessor: the chain forked"


async def test_deleting_the_first_record_is_reported_as_a_break(
    session: AsyncSession,
) -> None:
    """The break with no record to name.

    Nothing chains to genesis any more and there is no single row to point at,
    so an implementation keyed off "which record broke" reports this as intact
    — a verifier saying "fine" about a chain whose start was removed.
    """
    for index in range(3):
        await record(session, Store.DECISIONS, f"event_{index}", {"index": index})
    await session.commit()

    await session.execute(
        text("DELETE FROM audit_decisions WHERE prev_hash = :genesis"), {"genesis": GENESIS}
    )
    await session.commit()

    result = await verify(session, Store.DECISIONS)
    assert not result.intact, "a chain with no start must not report as intact"
    assert result.reason is Break.MISSING_GENESIS
    assert "first record has been removed" in result.detail
