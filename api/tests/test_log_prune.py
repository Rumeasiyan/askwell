"""Interaction retention: the window, the two refusals, the delete, and the
prune boundary `askwell.audit.verify` needs to stay honest about it.
`docs/audit-log.md` §8, ticket `M7-LOG-BE-154`.

Against a real Postgres, like `test_log_export.py` — `run_job` opens several
short transactions of its own and needs a `factory`, not a single `session`.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from askwell.audit import GENESIS, Store, canonical_payload, compute_hash, prune_boundaries, verify
from askwell.log_budget import set_retention_months
from askwell.log_prune import (
    PruneNotExported,
    PruneRequiresConfirmation,
    enqueue,
    get_job,
    run_job,
)

pytestmark = pytest.mark.requires_db

TABLES = "audit_decisions, audit_interactions, export_jobs, prune_jobs, settings, memory"


@pytest_asyncio.fixture
async def factory(database_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    async_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_async_engine(async_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as opened:
        await opened.execute(text(f"TRUNCATE {TABLES} CASCADE"))
        await opened.commit()
    yield sessions
    async with sessions() as opened:
        await opened.execute(text(f"TRUNCATE {TABLES} CASCADE"))
        await opened.commit()
    await engine.dispose()


@pytest_asyncio.fixture
async def session(factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with factory() as opened:
        yield opened
        await opened.rollback()


async def _seed_interactions(session: AsyncSession, ages_days: list[int]) -> list[dict]:
    """Insert real, correctly-chained `audit_interactions` rows, oldest
    first, each backdated by the given number of days. Not `audit.record`,
    which always stamps "now" — pruning needs rows old enough to test
    against, and their `occurred_at` is inside the hash, so it has to be
    set before the hash is computed, not patched in afterwards.
    """
    prev_hash = GENESIS
    now = datetime.now(UTC)
    rows = []
    for index, days in enumerate(ages_days):
        record_id = uuid.uuid4()
        occurred_at = now - timedelta(days=days)
        payload = {"i": index}
        digest = compute_hash(
            record_id=record_id,
            kind="question_asked",
            payload=payload,
            occurred_at=occurred_at,
            prev_hash=prev_hash,
        )
        await session.execute(
            text(
                "INSERT INTO audit_interactions (id, kind, payload, prev_hash, hash, occurred_at) "
                "VALUES (:id, :kind, CAST(:payload AS jsonb), :prev_hash, :hash, :occurred_at)"
            ),
            {
                "id": record_id,
                "kind": "question_asked",
                "payload": canonical_payload(payload),
                "prev_hash": prev_hash,
                "hash": digest,
                "occurred_at": occurred_at,
            },
        )
        rows.append({"id": record_id, "hash": digest, "occurred_at": occurred_at})
        prev_hash = digest
    await session.commit()
    return rows


async def _export_everything(session: AsyncSession, *, until: datetime | None = None) -> None:
    """The state `M7-LOG-BE-155` leaves behind for a completed, unfiltered
    export — the one `_has_covering_export` looks for. Inserted directly
    rather than run through `log_export.run_job`, which needs a real
    filesystem and is that module's own thing to test."""
    await session.execute(
        text(
            "INSERT INTO export_jobs (id, status, since, until) VALUES (:id, 'done', NULL, :until)"
        ),
        {"id": uuid.uuid4(), "until": until},
    )
    await session.commit()


async def test_prune_is_refused_without_an_export(
    factory: async_sessionmaker[AsyncSession], session: AsyncSession
) -> None:
    await _seed_interactions(session, [400, 200, 5])
    await set_retention_months(session, 6)
    await session.commit()

    with pytest.raises(PruneNotExported):
        await enqueue(session)


async def test_nothing_prunable_needs_no_export_at_all(
    factory: async_sessionmaker[AsyncSession], session: AsyncSession
) -> None:
    """A fresh install, or a window that keeps everything, must not refuse
    for lack of an export when there is nothing to prune in the first
    place — that refusal would be pointing at a fix that fixes nothing."""
    await _seed_interactions(session, [5, 2])
    await set_retention_months(session, 6)
    await session.commit()

    job_id = await enqueue(session)
    await session.commit()
    job = await get_job(session, job_id)
    assert job is not None


async def test_a_window_that_would_prune_nearly_everything_needs_confirmation(
    factory: async_sessionmaker[AsyncSession], session: AsyncSession
) -> None:
    await _seed_interactions(session, [400, 380, 370])
    await set_retention_months(session, 6)
    await _export_everything(session)
    await session.commit()

    with pytest.raises(PruneRequiresConfirmation) as excinfo:
        await enqueue(session)
    assert excinfo.value.prunable == 3
    assert excinfo.value.total == 3

    job_id = await enqueue(session, acknowledged_nearly_everything=True)
    await session.commit()
    assert await get_job(session, job_id) is not None


async def test_a_prune_removes_only_the_old_interactions_and_verifies(
    factory: async_sessionmaker[AsyncSession], session: AsyncSession
) -> None:
    rows = await _seed_interactions(session, [400, 200, 5])
    await set_retention_months(session, 6)
    await _export_everything(session)
    await session.commit()

    job_id = await enqueue(session)
    await session.commit()

    await run_job(factory, job_id)

    async with factory() as check:
        job = await get_job(check, job_id)
        assert job is not None
        assert job.status == "done"
        assert job.pruned_count == 2
        assert job.boundary_hash == rows[1]["hash"]

        remaining = (
            await check.execute(text("SELECT count(*) FROM audit_interactions"))
        ).scalar_one()
        assert remaining == 1

        boundaries = await prune_boundaries(check)
        assert boundaries == [
            (rows[1]["hash"], f"pruned through {job.cutoff.astimezone(UTC).isoformat()}")
        ]

        result = await verify(check, Store.INTERACTIONS, prune_boundaries=boundaries)
        assert result.intact, str(result)
        assert result.checked == 1

        without_boundary = await verify(check, Store.INTERACTIONS)
        assert not without_boundary.intact, "the boundary must be required, not just accepted"


async def test_changing_the_window_changes_what_is_prunable(
    factory: async_sessionmaker[AsyncSession], session: AsyncSession
) -> None:
    await _seed_interactions(session, [800, 200, 5])
    await _export_everything(session)
    await session.commit()

    await set_retention_months(session, 15)
    await session.commit()
    job_id = await enqueue(session)
    await session.commit()
    await run_job(factory, job_id)
    async with factory() as check:
        job = await get_job(check, job_id)
        assert job is not None and job.pruned_count == 1  # only the 800-day-old row

    await set_retention_months(session, 6)
    await session.commit()
    job_id = await enqueue(session)
    await session.commit()
    await run_job(factory, job_id)
    async with factory() as check:
        job = await get_job(check, job_id)
        assert job is not None and job.pruned_count == 1  # the 200-day-old row, now also outside


async def test_decisions_and_memory_are_never_touched_by_a_prune(
    factory: async_sessionmaker[AsyncSession], session: AsyncSession
) -> None:
    from askwell.audit import record

    await _seed_interactions(session, [400, 5])
    await record(session, Store.DECISIONS, "source_added", {"name": "contracts"})
    await session.execute(
        text(
            "INSERT INTO memory (id, subject, fact, origin, confidence) "
            "VALUES (gen_random_uuid(), 'client', 'client is a law firm', 'manual', 0.9)"
        )
    )
    await _export_everything(session)
    await session.commit()

    decisions_before = (
        await session.execute(text("SELECT count(*) FROM audit_decisions"))
    ).scalar_one()
    memory_before = (await session.execute(text("SELECT count(*) FROM memory"))).scalar_one()

    job_id = await enqueue(session)
    await session.commit()
    await run_job(factory, job_id)

    async with factory() as check:
        decisions_after = (
            await check.execute(text("SELECT count(*) FROM audit_decisions"))
        ).scalar_one()
        memory_after = (await check.execute(text("SELECT count(*) FROM memory"))).scalar_one()
        # The prune's own enqueue decisions record is the only addition.
        assert decisions_after >= decisions_before
        assert memory_after == memory_before


async def test_a_prune_interrupted_before_the_delete_commits_leaves_the_chain_intact(
    factory: async_sessionmaker[AsyncSession], session: AsyncSession
) -> None:
    """Simulates a crash mid-run: the job still `running`, nothing deleted —
    exactly what `askwell.worker.startup`'s `resume` would hand back to
    `queued`. `run_job` is one transaction, so this is the only partial
    state that can exist; re-running it must finish cleanly."""
    from askwell.log_prune import resume

    rows = await _seed_interactions(session, [400, 5])
    await set_retention_months(session, 6)
    await _export_everything(session)
    await session.commit()

    job_id = await enqueue(session)
    await session.execute(
        text("UPDATE prune_jobs SET status = 'running', started_at = now() WHERE id = :id"),
        {"id": job_id},
    )
    await session.commit()

    async with factory() as check:
        result = await verify(check, Store.INTERACTIONS)
        assert result.intact
        assert result.checked == 2

        resumed = await resume(check)
        await check.commit()
    assert job_id in resumed

    await run_job(factory, job_id)

    async with factory() as check:
        job = await get_job(check, job_id)
        assert job is not None
        assert job.status == "done"
        assert job.pruned_count == 1
        assert job.boundary_hash == rows[0]["hash"]
