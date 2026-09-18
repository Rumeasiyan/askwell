"""`inject_limit` against a real Postgres. `M4-SQL-VAL-105`.

What only a real database can prove: an injection is recorded to
`audit_interactions` with the limited query and its value (the ticket's own
Audit Requirement — a per-question fact, not a Decisions one; an earlier
version wrote this to `audit_decisions`, filed and fixed as issue #372), and
a query left alone (an aggregate, or already limited) is not recorded.
Every limit-injection rule itself is proven without a database in
`test_sql_limit.py` — `_inject_limit_sync` is pure.
"""

import json
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from askwell.config import Settings
from askwell.sql.limit import inject_limit

pytestmark = pytest.mark.requires_db

_TABLES = "audit_interactions"


@pytest.fixture
def async_url(database_url: str) -> str:
    return database_url.replace("postgresql://", "postgresql+psycopg://", 1)


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


async def _interaction_rows(session: AsyncSession) -> list[dict[str, object]]:
    rows = (
        await session.execute(
            text(
                "SELECT payload FROM audit_interactions "
                "WHERE kind = 'sql_limit_injected' ORDER BY id"
            )
        )
    ).all()
    return [row[0] if isinstance(row[0], dict) else json.loads(row[0]) for row in rows]


async def test_injection_is_recorded_with_the_limited_query(
    session: AsyncSession, settings: Settings
) -> None:
    result = await inject_limit(
        session, settings, engine="postgresql", query="SELECT id FROM orders"
    )
    await session.commit()

    assert result.injected
    rows = await _interaction_rows(session)
    assert len(rows) == 1
    assert rows[0]["engine"] == "postgresql"
    assert rows[0]["limit"] == settings.sql_row_limit
    assert "LIMIT" in rows[0]["query"]


async def test_query_with_aggregate_is_not_recorded(
    session: AsyncSession, settings: Settings
) -> None:
    result = await inject_limit(
        session, settings, engine="postgresql", query="SELECT COUNT(*) FROM orders"
    )
    await session.commit()

    assert not result.injected
    assert await _interaction_rows(session) == []


async def test_query_already_limited_is_not_recorded(
    session: AsyncSession, settings: Settings
) -> None:
    result = await inject_limit(
        session, settings, engine="postgresql", query="SELECT id FROM orders LIMIT 5"
    )
    await session.commit()

    assert not result.injected
    assert await _interaction_rows(session) == []
