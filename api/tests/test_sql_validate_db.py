"""`validate_query` against a real Postgres. `M4-SQL-VAL-104`.

What only a real database can prove: a rejection is actually recorded to
`audit_decisions` with its reason (the ticket's own Audit Requirement), and
an accepted query is not recorded at all (`generate_candidate_query` already
records a successful generation; recording it again here would double it).
Every hostile SQL shape itself is proven without a database in
`test_sql_validate.py` — `_validate_sync` is pure.
"""

import json
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from askwell.config import Settings
from askwell.sql import validate as sql_validate
from askwell.sql.validate import RejectionReason, ValidationResult, validate_query

pytestmark = pytest.mark.requires_db

_TABLES = "audit_decisions"


@pytest.fixture
def async_url(database_url: str) -> str:
    return database_url.replace("postgresql://", "postgresql+psycopg://", 1)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        database_url="postgresql://askwell:pw@127.0.0.1:1/askwell",  # type: ignore[arg-type]
        sandbox_database_url="postgresql://askwell_sandbox:pw@127.0.0.1:1/postgres",  # type: ignore[arg-type]
        sandbox_owner_password="pw",  # type: ignore[arg-type]
        sandbox_readonly_password="pw",  # type: ignore[arg-type]
        sql_validation_timeout_seconds=2.0,
    )


@pytest_asyncio.fixture
async def session(async_url: str) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(async_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as opened:
        await opened.execute(text(f"TRUNCATE {_TABLES} CASCADE"))
        await opened.commit()
        yield opened
        await opened.rollback()
        await opened.execute(text(f"TRUNCATE {_TABLES} CASCADE"))
        await opened.commit()
    await engine.dispose()


async def _decisions_rows(session: AsyncSession) -> list[dict[str, object]]:
    rows = (
        await session.execute(
            text("SELECT payload FROM audit_decisions WHERE kind = 'sql_rejected' ORDER BY id")
        )
    ).all()
    return [row[0] if isinstance(row[0], dict) else json.loads(row[0]) for row in rows]


async def test_rejection_is_recorded_with_its_reason(
    session: AsyncSession, settings: Settings
) -> None:
    result = await validate_query(
        session,
        settings,
        engine="postgresql",
        query="SELECT id FROM orders; DELETE FROM orders",
    )
    await session.commit()

    assert not result.accepted
    assert result.reason == RejectionReason.MULTIPLE_STATEMENTS

    rows = await _decisions_rows(session)
    assert len(rows) == 1
    assert rows[0]["reason"] == RejectionReason.MULTIPLE_STATEMENTS.value
    assert rows[0]["query"] == "SELECT id FROM orders; DELETE FROM orders"
    assert rows[0]["engine"] == "postgresql"
    assert rows[0]["detail"]


async def test_every_named_rejection_reason_is_recorded(
    session: AsyncSession, settings: Settings
) -> None:
    hostile_queries = {
        RejectionReason.EMPTY: "",
        RejectionReason.MULTIPLE_STATEMENTS: "SELECT 1; SELECT 2",
        RejectionReason.NOT_A_SINGLE_READ: "DELETE FROM orders",
        RejectionReason.WRITE_DETECTED: "SELECT * INTO t FROM orders",
        RejectionReason.LOCKING_READ: "SELECT * FROM orders FOR UPDATE",
        RejectionReason.SIDE_EFFECT_FUNCTION: "SELECT pg_terminate_backend(123)",
        RejectionReason.UNPARSEABLE: "SELECT * FROM WHERE",
    }
    for reason, query in hostile_queries.items():
        result = await validate_query(session, settings, engine="postgresql", query=query)
        assert result.reason == reason, f"{query!r} -> {result.reason}, expected {reason}"
    await session.commit()

    rows = await _decisions_rows(session)
    recorded_reasons = {row["reason"] for row in rows}
    assert recorded_reasons == {reason.value for reason in hostile_queries}


async def test_accepted_query_is_not_recorded(session: AsyncSession, settings: Settings) -> None:
    result = await validate_query(
        session, settings, engine="postgresql", query="SELECT id FROM orders"
    )
    await session.commit()

    assert result.accepted
    assert await _decisions_rows(session) == []


async def test_timeout_is_recorded_when_parsing_exceeds_the_configured_wait(
    session: AsyncSession, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    import time

    def _slow_validate(engine: object, query: str) -> ValidationResult:
        time.sleep(0.2)
        return ValidationResult(accepted=True, reason=None, detail=None)

    monkeypatch.setattr(sql_validate, "_validate_sync", _slow_validate)
    fast_settings = settings.model_copy(update={"sql_validation_timeout_seconds": 0.01})

    result = await validate_query(session, fast_settings, engine="postgresql", query="SELECT 1")
    await session.commit()

    assert not result.accepted
    assert result.reason == RejectionReason.TIMEOUT

    rows = await _decisions_rows(session)
    assert len(rows) == 1
    assert rows[0]["reason"] == RejectionReason.TIMEOUT.value
