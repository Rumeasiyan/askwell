"""Interaction retention window and prune, against a real Postgres.

`docs/audit-log.md` §8, ticket `M7-LOG-BE-154`.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from askwell.audit import GENESIS, Store, canonical_payload, compute_hash, record, verify
from askwell.log_budget import RetentionWindowTooShort, set_retention_months
from askwell.retention import (
    PruneNotExported,
    exported_through,
    get_cutoff,
    latest_prune_boundary,
    mark_exported_through,
    prune,
)

pytestmark = pytest.mark.requires_db

TABLES = "audit_decisions, audit_interactions, settings"


@pytest.fixture
def async_url(database_url: str) -> str:
    return database_url.replace("postgresql://", "postgresql+psycopg://", 1)


@pytest_asyncio.fixture
async def session(async_url: str) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(async_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as opened:
        await opened.execute(text(f"TRUNCATE {TABLES}"))
        await opened.commit()
        yield opened
        await opened.rollback()
        await opened.execute(text(f"TRUNCATE {TABLES}"))
        await opened.commit()
    await engine.dispose()


async def _seed_at(
    session: AsyncSession, occurred_at: datetime, payload: dict[str, object]
) -> None:
    """Write one `audit_interactions` record with a chosen `occurred_at`,
    chaining it correctly to whatever is already there — `askwell.audit.record`
    always uses `now()`, so retention tests need their own seeding to place
    records at controlled ages without corrupting the hash chain.
    """
    row = (
        await session.execute(
            text("SELECT hash FROM audit_interactions ORDER BY occurred_at DESC, id DESC LIMIT 1")
        )
    ).first()
    prev_hash = GENESIS if row is None else str(row[0])
    record_id = uuid.uuid4()
    digest = compute_hash(
        record_id=record_id,
        kind="test_kind",
        payload=payload,
        occurred_at=occurred_at,
        prev_hash=prev_hash,
    )
    await session.execute(
        text(
            "INSERT INTO audit_interactions (id, kind, payload, prev_hash, hash, occurred_at) "
            "VALUES (:id, 'test_kind', CAST(:payload AS jsonb), :prev_hash, :hash, :occurred_at)"
        ),
        {
            "id": record_id,
            "payload": canonical_payload(payload),
            "prev_hash": prev_hash,
            "hash": digest,
            "occurred_at": occurred_at,
        },
    )


def _months_ago(months: int) -> datetime:
    return datetime.now(UTC) - timedelta(days=months * 31)


async def test_cutoff_follows_the_configured_retention_window(session: AsyncSession) -> None:
    await set_retention_months(session, 1)
    await session.commit()

    cutoff = await get_cutoff(session)
    expected = (await session.execute(text("SELECT now() - interval '1 month'"))).scalar_one()
    assert abs((cutoff - expected).total_seconds()) < 5


async def test_prune_without_a_prior_export_is_refused(session: AsyncSession) -> None:
    await set_retention_months(session, 1)
    await _seed_at(session, _months_ago(13), {"i": 0})
    await session.commit()

    with pytest.raises(PruneNotExported):
        await prune(session)


async def test_prune_removes_only_interactions_older_than_the_window(
    session: AsyncSession,
) -> None:
    await set_retention_months(session, 12)
    await _seed_at(session, _months_ago(24), {"i": "old"})
    await _seed_at(session, _months_ago(1), {"i": "recent"})
    await session.commit()

    cutoff = await get_cutoff(session)
    await mark_exported_through(session, datetime.now(UTC))
    await session.commit()

    result = await prune(session)
    await session.commit()

    assert result.records_removed == 1
    remaining = (
        (await session.execute(text("SELECT payload FROM audit_interactions"))).scalars().all()
    )
    assert len(remaining) == 1
    assert remaining[0]["i"] == "recent"
    # Two separate `now()` calls, milliseconds apart — not the same instant.
    assert abs((result.cutoff - cutoff).total_seconds()) < 5


async def test_prune_writes_a_decisions_record_naming_the_range(session: AsyncSession) -> None:
    await set_retention_months(session, 12)
    await _seed_at(session, _months_ago(24), {"i": "old"})
    await mark_exported_through(session, datetime.now(UTC))
    await session.commit()

    await prune(session)
    await session.commit()

    row = (
        await session.execute(
            text("SELECT payload FROM audit_decisions WHERE kind = 'interaction_prune'")
        )
    ).first()
    assert row is not None
    assert row[0]["records_removed"] == "1"
    assert "cutoff" in row[0]
    assert "first_remaining_prev_hash" in row[0]


async def test_prune_never_touches_decisions(session: AsyncSession) -> None:
    await record(session, Store.DECISIONS, "source_added", {"name": "contracts"})
    await set_retention_months(session, 12)
    await _seed_at(session, _months_ago(24), {"i": "old"})
    await mark_exported_through(session, datetime.now(UTC))
    await session.commit()

    before = (await session.execute(text("SELECT count(*) FROM audit_decisions"))).scalar_one()
    await prune(session)
    await session.commit()
    after = (await session.execute(text("SELECT count(*) FROM audit_decisions"))).scalar_one()

    # The prune itself adds exactly one decisions record.
    assert after == before + 1
    assert (await verify(session, Store.DECISIONS)).intact


async def test_verification_succeeds_after_a_prune_using_the_recorded_boundary(
    session: AsyncSession,
) -> None:
    await set_retention_months(session, 12)
    await _seed_at(session, _months_ago(30), {"i": "very old"})
    await _seed_at(session, _months_ago(24), {"i": "old"})
    await _seed_at(session, _months_ago(1), {"i": "recent"})
    await mark_exported_through(session, datetime.now(UTC))
    await session.commit()

    # Without knowing about the prune, the raw chain would look tampered.
    result = await prune(session)
    await session.commit()
    assert result.records_removed == 2

    naive = await verify(session, Store.INTERACTIONS)
    assert not naive.intact

    boundary = await latest_prune_boundary(session)
    assert boundary is not None
    informed = await verify(session, Store.INTERACTIONS, start_from=boundary)
    assert informed.intact, str(informed)
    assert informed.checked == 1


async def test_pruning_everything_leaves_an_empty_chain_that_still_verifies(
    session: AsyncSession,
) -> None:
    await set_retention_months(session, 1)
    await _seed_at(session, _months_ago(24), {"i": "old"})
    await mark_exported_through(session, datetime.now(UTC))
    await session.commit()

    result = await prune(session)
    await session.commit()

    assert result.records_removed == 1
    assert (await verify(session, Store.INTERACTIONS)).intact


async def test_a_windowed_export_does_not_advance_the_exported_marker(
    session: AsyncSession,
) -> None:
    now = datetime.now(UTC)
    await mark_exported_through(session, now - timedelta(days=400))
    await session.commit()
    assert await exported_through(session) == now - timedelta(days=400)


async def test_marking_an_earlier_export_does_not_roll_the_marker_backwards(
    session: AsyncSession,
) -> None:
    now = datetime.now(UTC)
    await mark_exported_through(session, now)
    await mark_exported_through(session, now - timedelta(days=10))
    await session.commit()
    assert await exported_through(session) == now


async def test_setting_a_window_shorter_than_existing_history_requires_confirmation(
    session: AsyncSession,
) -> None:
    await _seed_at(session, _months_ago(24), {"i": "old"})
    await session.commit()

    with pytest.raises(RetentionWindowTooShort):
        await set_retention_months(session, 1)

    months = await set_retention_months(session, 1, confirmed=True)
    assert months == 1


async def test_setting_a_window_that_covers_all_existing_history_needs_no_confirmation(
    session: AsyncSession,
) -> None:
    await _seed_at(session, _months_ago(1), {"i": "recent"})
    await session.commit()

    months = await set_retention_months(session, 12)
    assert months == 12
