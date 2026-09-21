"""Log verification: the job that walks both audit stores' hash chains with
progress and can be interrupted. `docs/audit-log.md` §4, ticket
`M7-LOG-FE-156`.

Against a real Postgres, like `test_log_export.py` — `run_job` opens several
short transactions of its own and needs a `factory`, not a single `session`.
"""

import json
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from askwell.audit import Break, Store, record
from askwell.config import Settings
from askwell.log_verify import (
    VERIFY_JOB_COMPLETED,
    enqueue,
    get_job,
    request_cancel,
    run_job,
)

pytestmark = pytest.mark.requires_db

TABLES = "audit_decisions, audit_interactions, verify_jobs, settings"


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


@pytest.fixture
def settings() -> Settings:
    return Settings(
        database_url="postgresql://askwell:pw@127.0.0.1:1/askwell",  # type: ignore[arg-type]
        sandbox_database_url="postgresql://x:x@127.0.0.1:1/postgres",  # type: ignore[arg-type]
        sandbox_owner_password="pw",  # type: ignore[arg-type]
        sandbox_readonly_password="pw",  # type: ignore[arg-type]
    )


async def _seed(session: AsyncSession, store: Store, n: int) -> None:
    for i in range(n):
        await record(session, store, "test_kind", {"i": i})
    await session.commit()


async def _run(
    sessions: async_sessionmaker[AsyncSession], settings: Settings, job_id: uuid.UUID
) -> None:
    await run_job(sessions, settings, job_id)


async def test_an_intact_log_reports_both_stores_intact(
    factory: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    async with factory() as session:
        await _seed(session, Store.DECISIONS, 3)
        await _seed(session, Store.INTERACTIONS, 5)
        job_id = await enqueue(session)
        await session.commit()

    await _run(factory, settings, job_id)

    async with factory() as session:
        job = await get_job(session, job_id)
    assert job is not None
    assert job.status == "done"
    assert job.decisions.intact is True
    assert job.decisions.checked == job.decisions.total == 3
    assert job.interactions.intact is True
    assert job.interactions.checked == job.interactions.total == 5
    assert job.decisions.break_id is None
    assert job.interactions.break_id is None


async def test_a_broken_store_is_named_with_its_break_and_date(
    factory: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    async with factory() as session:
        await _seed(session, Store.DECISIONS, 4)
        target = (
            await session.execute(
                text("SELECT id FROM audit_decisions ORDER BY occurred_at ASC OFFSET 1 LIMIT 1")
            )
        ).first()
        assert target is not None
        await session.execute(
            text("UPDATE audit_decisions SET payload = CAST(:p AS jsonb) WHERE id = :id"),
            {"p": json.dumps({"tampered": True}), "id": target[0]},
        )
        await session.commit()
        job_id = await enqueue(session)
        await session.commit()

    await _run(factory, settings, job_id)

    async with factory() as session:
        job = await get_job(session, job_id)
    assert job is not None
    assert job.status == "done"
    assert job.decisions.intact is False
    assert job.decisions.break_id == uuid.UUID(str(target[0]))
    assert job.decisions.break_at is not None
    assert job.decisions.break_reason == Break.ALTERED.value
    # Never described as immutable, and a break is not "tampering" until
    # the surface layer says so — this module only reports what verify()
    # found.
    assert "hash to" in (job.decisions.break_detail or "")


async def test_both_stores_broken_are_both_reported(
    factory: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    async with factory() as session:
        await _seed(session, Store.DECISIONS, 2)
        await _seed(session, Store.INTERACTIONS, 2)
        genesis = "0" * 64
        await session.execute(
            text("DELETE FROM audit_decisions WHERE prev_hash = :g"), {"g": genesis}
        )
        await session.execute(
            text("DELETE FROM audit_interactions WHERE prev_hash = :g"), {"g": genesis}
        )
        await session.commit()
        job_id = await enqueue(session)
        await session.commit()

    await _run(factory, settings, job_id)

    async with factory() as session:
        job = await get_job(session, job_id)
    assert job is not None
    assert job.decisions.intact is False
    assert job.decisions.break_reason == Break.MISSING_GENESIS.value
    assert job.interactions.intact is False
    assert job.interactions.break_reason == Break.MISSING_GENESIS.value


async def test_completion_is_logged_to_the_decisions_store_with_its_result(
    factory: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    async with factory() as session:
        await _seed(session, Store.DECISIONS, 1)
        job_id = await enqueue(session)
        await session.commit()

    await _run(factory, settings, job_id)

    async with factory() as session:
        row = (
            await session.execute(
                text(
                    "SELECT payload FROM audit_decisions WHERE kind = :kind "
                    "ORDER BY occurred_at DESC LIMIT 1"
                ),
                {"kind": VERIFY_JOB_COMPLETED},
            )
        ).first()
    assert row is not None
    assert row[0]["job_id"] == str(job_id)
    assert row[0]["decisions"]["intact"] is True
    assert row[0]["interactions"]["intact"] is True


async def test_cancelling_a_running_job_stops_it_without_a_verdict(
    factory: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    async with factory() as session:
        await _seed(session, Store.DECISIONS, 5)
        job_id = await enqueue(session)
        await session.commit()
        # Cancel before the job ever runs — cheap and deterministic, and
        # `should_continue` is checked before the first record either way.
        cancelled = await request_cancel(session, job_id)
        await session.commit()
    assert cancelled is not None
    assert cancelled.status in ("queued", "cancelled")

    await _run(factory, settings, job_id)

    async with factory() as session:
        job = await get_job(session, job_id)
    assert job is not None
    assert job.status == "cancelled"
    assert job.decisions.intact is None, "a cancelled run must not assert either verdict"
    assert job.interactions.intact is None


async def test_cancelling_an_already_finished_job_is_a_no_op(
    factory: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    async with factory() as session:
        job_id = await enqueue(session)
        await session.commit()

    await _run(factory, settings, job_id)

    async with factory() as session:
        job = await request_cancel(session, job_id)
    assert job is not None
    assert job.status == "done", "cancelling a finished job must not overwrite its real result"


async def test_getting_a_job_that_does_not_exist_returns_none(session: AsyncSession) -> None:
    assert await get_job(session, uuid.uuid4()) is None
    assert await request_cancel(session, uuid.uuid4()) is None
