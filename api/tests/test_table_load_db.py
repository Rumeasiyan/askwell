"""Loading and reloading a table into the real sandbox instance.
`M4-CSV-ING-094`. Same split as `test_dump_import.py`: pure-Python casting
and identifier logic is in `test_table_load.py`; everything here needs a
real, separate Postgres instance to prove.
"""

import os
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from askwell.config import Settings
from askwell.dump_import import set_dump_size_cap_bytes
from askwell.review import answer_clarification
from askwell.table_load import (
    EmptyTable,
    TableCapExceeded,
    create_table_source,
    process_table_source,
    reload_source,
)

pytestmark = pytest.mark.requires_db

TABLES = "sources, clarifications, memory, schema_notes, reapply_jobs, audit_decisions, settings"


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


@pytest.fixture
def table_settings(sandbox_admin_url: str) -> Settings:
    return Settings(
        database_url="postgresql://x:x@127.0.0.1:1/askwell",  # type: ignore[arg-type]
        sandbox_database_url=sandbox_admin_url,  # type: ignore[arg-type]
        sandbox_owner_password=os.environ["TEST_SANDBOX_OWNER_PASSWORD"],  # type: ignore[arg-type]
        sandbox_readonly_password=os.environ["TEST_SANDBOX_READONLY_PASSWORD"],  # type: ignore[arg-type]
    )


async def _make_source(
    factory: async_sessionmaker[AsyncSession], name: str, csv_path: Path
) -> uuid.UUID:
    async with factory() as session:
        source_id = await create_table_source(session, name, str(csv_path))
        await session.commit()
    return source_id


async def test_a_clean_csv_loads_as_a_real_table_with_confirmed_types(
    factory: async_sessionmaker[AsyncSession], table_settings: Settings, tmp_path: Path
) -> None:
    csv_path = tmp_path / "people.csv"
    csv_path.write_text("Name,Amount\nAnna,10\nBen,20\n")
    source_id = await _make_source(factory, "people", csv_path)

    results = await process_table_source(factory, table_settings, source_id, str(csv_path))

    assert len(results) == 1
    result = results[0]
    assert result.row_count == 2
    assert result.failed_rows == []

    async with factory() as session:
        row = (
            await session.execute(
                text("SELECT status, sandbox_db FROM sources WHERE id = :id"), {"id": source_id}
            )
        ).one()
        assert row[0] == "ready"
        database = row[1]
        assert database is not None

        notes = (
            await session.execute(
                text(
                    "SELECT column_name FROM schema_notes WHERE source_id = :id "
                    "AND origin = 'inferred'"
                ),
                {"id": source_id},
            )
        ).all()
        # `M4-CSV-ING-092`'s own per-column notes, plus this ticket's
        # table-level note (`column_name IS NULL`).
        assert None in {row[0] for row in notes}

    admin_url = table_settings.sandbox_database_url.get_secret_value()
    import psycopg

    with psycopg.connect(admin_url.rsplit("/", 1)[0] + f"/{database}", autocommit=True) as conn:
        rows = conn.execute("SELECT name, amount FROM people_csv ORDER BY name").fetchall()
    assert rows == [("Anna", 10), ("Ben", 20)]


async def test_a_column_name_that_is_not_a_valid_identifier_is_normalised_and_recorded(
    factory: async_sessionmaker[AsyncSession], table_settings: Settings, tmp_path: Path
) -> None:
    csv_path = tmp_path / "export.csv"
    csv_path.write_text("Reference #,Amount\nA1,10\nA2,20\n")
    source_id = await _make_source(factory, "export", csv_path)

    results = await process_table_source(factory, table_settings, source_id, str(csv_path))
    assert results[0].sql_table_name == "export_csv"

    async with factory() as session:
        note = (
            await session.execute(
                text(
                    "SELECT description FROM schema_notes WHERE source_id = :id "
                    "AND column_name = 'Reference #' AND description LIKE 'Loaded as column%'"
                ),
                {"id": source_id},
            )
        ).first()
        assert note is not None
        assert "reference" in note[0]
        assert "Reference #" in note[0]


async def test_malformed_rows_are_reported_by_row_number_not_dropped_silently(
    factory: async_sessionmaker[AsyncSession], table_settings: Settings, tmp_path: Path
) -> None:
    # Nine good integers and one `oops` — confident enough (9/10 = 90%,
    # over `_MIN_TYPE_CONFIDENCE`) that `table_infer` still calls the column
    # `integer` rather than falling back to an ambiguous `string`, so the
    # bad row only ever surfaces as a real cast failure during the load.
    good_rows = "\n".join(f"person{i},{i * 10}" for i in range(1, 10))
    csv_path = tmp_path / "sales.csv"
    csv_path.write_text(f"name,amount\n{good_rows}\nBen,oops\n")
    source_id = await _make_source(factory, "sales", csv_path)

    results = await process_table_source(factory, table_settings, source_id, str(csv_path))

    result = results[0]
    assert result.row_count == 9
    assert len(result.failed_rows) == 1
    # Row 1 is the header, so the 10th data row ("Ben,oops") is row 11.
    assert result.failed_rows[0].row_number == 11
    assert "oops" in result.failed_rows[0].reason


async def test_an_empty_file_is_refused_with_the_reason(
    factory: async_sessionmaker[AsyncSession], table_settings: Settings, tmp_path: Path
) -> None:
    csv_path = tmp_path / "empty.csv"
    csv_path.write_text("")
    source_id = await _make_source(factory, "empty", csv_path)

    with pytest.raises(EmptyTable):
        await process_table_source(factory, table_settings, source_id, str(csv_path))

    async with factory() as session:
        row = (
            await session.execute(
                text("SELECT status, sandbox_db FROM sources WHERE id = :id"), {"id": source_id}
            )
        ).one()
        # Never reached the sandbox at all — nothing to create, nothing to drop.
        assert row[1] is None


async def test_the_size_cap_aborts_the_load_and_drops_the_database(
    factory: async_sessionmaker[AsyncSession], table_settings: Settings, tmp_path: Path
) -> None:
    csv_path = tmp_path / "big.csv"
    csv_path.write_text("name\n" + "\n".join(f"row{i}" for i in range(500)) + "\n")
    source_id = await _make_source(factory, "big", csv_path)

    async with factory() as session:
        await set_dump_size_cap_bytes(session, 1024)
        await session.commit()

    with pytest.raises(TableCapExceeded) as exc_info:
        await process_table_source(factory, table_settings, source_id, str(csv_path))
    assert exc_info.value.cap == "size"

    async with factory() as session:
        row = (
            await session.execute(
                text("SELECT status, sandbox_db, last_error FROM sources WHERE id = :id"),
                {"id": source_id},
            )
        ).one()
        assert row[0] == "attention"
        assert row[1] is None
        assert "size cap" in row[2]


async def test_answering_a_date_format_clarification_reloads_the_column_as_a_real_date(
    factory: async_sessionmaker[AsyncSession], table_settings: Settings, tmp_path: Path
) -> None:
    # Both parts of each value are `<= 12`, so neither disambiguates itself
    # (`table_infer.detect_date_format` returns `AMBIGUOUS`) and the column
    # loads as `text` until the clarification it raises is answered.
    csv_path = tmp_path / "registrations.csv"
    csv_path.write_text("name,registered\nAnna,03/04/2026\nBen,05/06/2026\n")
    source_id = await _make_source(factory, "registrations", csv_path)

    await process_table_source(factory, table_settings, source_id, str(csv_path))

    async with factory() as session:
        database = (
            await session.execute(
                text("SELECT sandbox_db FROM sources WHERE id = :id"), {"id": source_id}
            )
        ).scalar_one()

    import psycopg

    admin_url = table_settings.sandbox_database_url.get_secret_value()
    dsn = admin_url.rsplit("/", 1)[0] + f"/{database}"

    # Before the clarification is answered, an undecided date column loads
    # as text, verbatim — never guessed.
    with psycopg.connect(dsn, autocommit=True) as conn:
        rows = conn.execute(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = 'registrations_csv' AND column_name = 'registered'"
        ).fetchall()
    assert rows[0][0] == "text"

    async with factory() as session:
        clarification = (
            await session.execute(
                text(
                    "SELECT id, options FROM clarifications WHERE source_id = :id "
                    "AND evidence->>'trigger' = 'date_format'"
                ),
                {"id": source_id},
            )
        ).one()
        clarification_id, options = clarification
        await answer_clarification(session, clarification_id, options[0])
        await session.commit()

    await reload_source(factory, table_settings, source_id)

    with psycopg.connect(dsn, autocommit=True) as conn:
        column = conn.execute(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = 'registrations_csv' AND column_name = 'registered'"
        ).fetchall()
        values = conn.execute(
            "SELECT name, registered FROM registrations_csv ORDER BY name"
        ).fetchall()
    assert column[0][0] == "date"
    # Day-first: `03/04/2026` -> 3 April, `05/06/2026` -> 5 June.
    assert values[0][1].isoformat() == "2026-04-03"
    assert values[1][1].isoformat() == "2026-06-05"
