"""`raise_table_inference` persistence: schema notes and real clarification
rows. `M4-CSV-ING-092`. Against a real Postgres, the same split
`test_clarify.py` uses — separate file from `test_table_infer.py` so the
module-level `requires_db` mark does not pull the pure parsing tests along
with it.
"""

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from askwell.table_infer import infer_csv, raise_table_inference

pytestmark = pytest.mark.requires_db
_TABLES = "sources, schema_notes, clarifications, memory, settings, audit_decisions"


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


async def _source(session: AsyncSession) -> uuid.UUID:
    source_id = uuid.uuid4()
    await session.execute(
        text("INSERT INTO sources (id, kind, name) VALUES (:id, 'csv', 'a csv source')"),
        {"id": source_id},
    )
    return source_id


async def test_columns_land_in_schema_notes_as_inferred_low_confidence(
    session: AsyncSession,
) -> None:
    source_id = await _source(session)
    raw = b"name,amount\nAnna,10\nBen,20\n"
    inference = infer_csv("people.csv", raw)
    await raise_table_inference(session, source_id, inference)
    await session.commit()

    rows = (
        await session.execute(
            text(
                "SELECT column_name, origin, confidence FROM schema_notes "
                "WHERE source_id = :id ORDER BY column_name"
            ),
            {"id": source_id},
        )
    ).all()
    assert {row[0] for row in rows} == {"name", "amount"}
    assert all(row[1] == "inferred" for row in rows)


async def test_an_unresolvable_column_raises_a_real_clarification_row(
    session: AsyncSession,
) -> None:
    source_id = await _source(session)
    raw = b"amount\n1,200.00\n1200.5\n980.25\n"
    inference = infer_csv("finance.csv", raw)
    result = await raise_table_inference(session, source_id, inference)
    await session.commit()

    assert result.raised >= 1
    rows = (
        await session.execute(
            text("SELECT question, status FROM clarifications WHERE source_id = :id"),
            {"id": source_id},
        )
    ).all()
    assert rows
    assert all(status == "pending" for _question, status in rows)
    assert any("currency" in question for question, _status in rows)


async def test_a_source_already_carrying_a_clarification_is_not_re_raised(
    session: AsyncSession,
) -> None:
    source_id = await _source(session)
    await session.execute(
        text(
            "INSERT INTO clarifications (id, source_id, subject, question, status) "
            "VALUES (:id, :source_id, 'existing', 'already asked?', 'pending')"
        ),
        {"id": uuid.uuid4(), "source_id": source_id},
    )
    raw = b"amount\n1,200.00\n1200.5\n980.25\n"
    inference = infer_csv("finance.csv", raw)
    result = await raise_table_inference(session, source_id, inference)
    await session.commit()

    assert result.raised == 0
    count = (
        await session.execute(
            text("SELECT count(*) FROM clarifications WHERE source_id = :id"),
            {"id": source_id},
        )
    ).scalar_one()
    assert count == 1
