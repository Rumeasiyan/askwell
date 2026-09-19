"""The tool registry against real rows. `M5-TOOLS-BE-113`.

`test_tools.py` covers the registry's shape and argument validation, which
need no database. What is left here is SQL-shaped: schema lookup and
document listing read real `schema_notes`/`documents` rows, and the
database query tool's "no connection" outcome depends on real `sources`
rows existing (or not).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from askwell.agent.tools import (
    DOCUMENT_LISTING_MAX_ROWS,
    SCHEMA_LOOKUP_MAX_NOTES,
    ToolErrorCode,
    call_tool,
)
from askwell.config import Settings

pytestmark = pytest.mark.requires_db

_TABLES = "sources, documents, schema_notes"


@pytest.fixture
def async_url(database_url: str) -> str:
    return database_url.replace("postgresql://", "postgresql+psycopg://", 1)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url="postgresql://askwell:pw@127.0.0.1:1/askwell",  # type: ignore[arg-type]
        sandbox_database_url="postgresql://askwell_sandbox:pw@127.0.0.1:1/postgres",  # type: ignore[arg-type]
        sandbox_owner_password="pw",  # type: ignore[arg-type]
        sandbox_readonly_password="pw",  # type: ignore[arg-type]
        install_secret_path=tmp_path / "install.key",
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


async def _dump_source(session: AsyncSession, *, name: str = "orders") -> uuid.UUID:
    source_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO sources (id, kind, name, sandbox_db, status) "
            "VALUES (:id, 'dump', :name, 'sandbox_orders', 'ready')"
        ),
        {"id": source_id, "name": name},
    )
    return source_id


async def _document(
    session: AsyncSession, *, source_id: uuid.UUID, filename: str, status: str = "ready"
) -> None:
    await session.execute(
        text(
            "INSERT INTO documents (id, source_id, filename, path, sha256, status) "
            "VALUES (:id, :source_id, :filename, :path, :sha256, :status)"
        ),
        {
            "id": uuid.uuid4(),
            "source_id": source_id,
            "filename": filename,
            "path": f"/tmp/{filename}",
            "sha256": uuid.uuid4().hex + uuid.uuid4().hex,
            "status": status,
        },
    )


async def _note(
    session: AsyncSession,
    *,
    source_id: uuid.UUID,
    table_name: str,
    column_name: str | None,
    description: str,
) -> None:
    await session.execute(
        text(
            "INSERT INTO schema_notes "
            "(id, source_id, table_name, column_name, description, origin, confidence) "
            "VALUES (:id, :source_id, :table_name, :column_name, :description, 'inferred', 0.8)"
        ),
        {
            "id": uuid.uuid4(),
            "source_id": source_id,
            "table_name": table_name,
            "column_name": column_name,
            "description": description,
        },
    )


class _NullInferenceClient:
    """Never called by any tool exercised in this file — passed only
    because `call_tool`'s contract always takes one."""


async def test_document_listing_returns_recent_documents_for_the_source(
    session: AsyncSession, settings: Settings
) -> None:
    source_id = await _dump_source(session)
    await _document(session, source_id=source_id, filename="a.pdf")
    await _document(session, source_id=source_id, filename="b.pdf")
    await session.commit()

    result, step = await call_tool(
        "document_listing",
        {"source_id": str(source_id)},
        session=session,
        settings=settings,
        client=_NullInferenceClient(),  # type: ignore[arg-type]
    )

    assert result.ok
    assert result.content is not None
    filenames = {row["filename"] for row in result.content["documents"]}
    assert filenames == {"a.pdf", "b.pdf"}
    assert not result.truncated
    assert step.outcome == "ok"
    assert step.tool == "document_listing"


async def test_document_listing_excludes_deleted_documents(
    session: AsyncSession, settings: Settings
) -> None:
    source_id = await _dump_source(session)
    await _document(session, source_id=source_id, filename="kept.pdf")
    await session.execute(
        text(
            "INSERT INTO documents (id, source_id, filename, path, sha256, status, deleted_at) "
            "VALUES (:id, :source_id, 'gone.pdf', '/tmp/gone.pdf', :sha256, 'ready', now())"
        ),
        {"id": uuid.uuid4(), "source_id": source_id, "sha256": uuid.uuid4().hex + uuid.uuid4().hex},
    )
    await session.commit()

    result, _step = await call_tool(
        "document_listing",
        {"source_id": str(source_id)},
        session=session,
        settings=settings,
        client=_NullInferenceClient(),  # type: ignore[arg-type]
    )

    assert result.ok
    assert result.content is not None
    filenames = {row["filename"] for row in result.content["documents"]}
    assert filenames == {"kept.pdf"}


async def test_document_listing_states_its_own_truncation(
    session: AsyncSession, settings: Settings
) -> None:
    source_id = await _dump_source(session)
    for index in range(DOCUMENT_LISTING_MAX_ROWS + 5):
        await _document(session, source_id=source_id, filename=f"doc-{index}.pdf")
    await session.commit()

    result, _step = await call_tool(
        "document_listing",
        {"source_id": str(source_id)},
        session=session,
        settings=settings,
        client=_NullInferenceClient(),  # type: ignore[arg-type]
    )

    assert result.ok
    assert result.content is not None
    assert len(result.content["documents"]) == DOCUMENT_LISTING_MAX_ROWS
    assert result.truncated


async def test_schema_lookup_returns_notes_for_the_source(
    session: AsyncSession, settings: Settings
) -> None:
    source_id = await _dump_source(session)
    await _note(
        session,
        source_id=source_id,
        table_name="orders",
        column_name="stat_cd",
        description="A bare status letter.",
    )
    await _note(
        session, source_id=source_id, table_name="orders", column_name=None, description="Orders."
    )
    await session.commit()

    result, step = await call_tool(
        "schema_lookup",
        {"source_id": str(source_id)},
        session=session,
        settings=settings,
        client=_NullInferenceClient(),  # type: ignore[arg-type]
    )

    assert result.ok
    assert result.content is not None
    assert result.content["total_notes"] == 2
    assert step.tool == "schema_lookup"


async def test_schema_lookup_filters_to_one_table_when_named(
    session: AsyncSession, settings: Settings
) -> None:
    source_id = await _dump_source(session)
    await _note(
        session, source_id=source_id, table_name="orders", column_name=None, description="Orders."
    )
    await _note(
        session,
        source_id=source_id,
        table_name="invoices",
        column_name=None,
        description="Invoices.",
    )
    await session.commit()

    result, _step = await call_tool(
        "schema_lookup",
        {"source_id": str(source_id), "table": "orders"},
        session=session,
        settings=settings,
        client=_NullInferenceClient(),  # type: ignore[arg-type]
    )

    assert result.ok
    assert result.content is not None
    assert result.content["total_notes"] == 1
    assert result.content["notes"][0]["table_name"] == "orders"


async def test_schema_lookup_states_its_own_truncation(
    session: AsyncSession, settings: Settings
) -> None:
    source_id = await _dump_source(session)
    for index in range(SCHEMA_LOOKUP_MAX_NOTES + 3):
        await _note(
            session,
            source_id=source_id,
            table_name="orders",
            column_name=f"col_{index}",
            description="A column.",
        )
    await session.commit()

    result, _step = await call_tool(
        "schema_lookup",
        {"source_id": str(source_id)},
        session=session,
        settings=settings,
        client=_NullInferenceClient(),  # type: ignore[arg-type]
    )

    assert result.ok
    assert result.content is not None
    assert len(result.content["notes"]) == SCHEMA_LOOKUP_MAX_NOTES
    assert result.truncated


async def test_database_query_with_no_connection_at_all_is_the_no_connection_outcome(
    session: AsyncSession, settings: Settings
) -> None:
    result, step = await call_tool(
        "database_query",
        {"question": "How many overdue invoices does Meridian have?"},
        session=session,
        settings=settings,
        client=_NullInferenceClient(),  # type: ignore[arg-type]
    )

    assert not result.ok
    assert result.error is not None
    assert result.error.code == ToolErrorCode.NO_CONNECTION
    assert step.outcome == "no_connection"
    assert step.tool == "database_query"
