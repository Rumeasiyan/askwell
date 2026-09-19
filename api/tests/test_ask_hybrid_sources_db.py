"""`askwell.ask._has_hybrid_sources` against real rows. `M5-LOOP-BE-115`.

The gate that gives `run_tool_loop` its scope inside `POST /ask` — tried only
for a corpus that is genuinely both documents and a database, never for the
ordinary single-kind case `test_ask_api.py` and `test_ask_sql.py` already
exercise fully (issue #409). Real rows, since the query itself — two joins
across `documents` and `sources` — is the thing worth getting wrong.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from askwell.ask import _has_hybrid_sources
from askwell.config import Settings

pytestmark = pytest.mark.requires_db

_TABLES = "sources, documents"


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


async def _source(session: AsyncSession, *, kind: str, status: str = "ready") -> uuid.UUID:
    source_id = uuid.uuid4()
    if kind == "dump":
        await session.execute(
            text(
                "INSERT INTO sources (id, kind, name, sandbox_db, status) "
                "VALUES (:id, 'dump', 'orders', 'sandbox_orders', :status)"
            ),
            {"id": source_id, "status": status},
        )
    else:
        await session.execute(
            text(
                "INSERT INTO sources (id, kind, name, status) "
                "VALUES (:id, :kind, 'a source', :status)"
            ),
            {"id": source_id, "kind": kind, "status": status},
        )
    return source_id


async def _document(session: AsyncSession, *, source_id: uuid.UUID, status: str = "ready") -> None:
    await session.execute(
        text(
            "INSERT INTO documents (id, source_id, filename, path, sha256, status) "
            "VALUES (:id, :source_id, :filename, :path, :sha256, :status)"
        ),
        {
            "id": uuid.uuid4(),
            "source_id": source_id,
            "filename": "terms.pdf",
            "path": "/tmp/terms.pdf",
            "sha256": uuid.uuid4().hex + uuid.uuid4().hex,
            "status": status,
        },
    )


@pytest.mark.asyncio
async def test_no_sources_at_all_is_not_hybrid(session: AsyncSession, settings: Settings) -> None:
    assert await _has_hybrid_sources(session, settings) is False


@pytest.mark.asyncio
async def test_documents_only_is_not_hybrid(session: AsyncSession, settings: Settings) -> None:
    source_id = await _source(session, kind="file")
    await _document(session, source_id=source_id)

    assert await _has_hybrid_sources(session, settings) is False


@pytest.mark.asyncio
async def test_a_ready_database_alone_with_no_documents_is_not_hybrid(
    session: AsyncSession, settings: Settings
) -> None:
    await _source(session, kind="dump")

    assert await _has_hybrid_sources(session, settings) is False


@pytest.mark.asyncio
async def test_a_ready_document_and_a_ready_database_together_is_hybrid(
    session: AsyncSession, settings: Settings
) -> None:
    file_source = await _source(session, kind="file")
    await _document(session, source_id=file_source)
    await _source(session, kind="dump")

    assert await _has_hybrid_sources(session, settings) is True


@pytest.mark.asyncio
async def test_a_database_still_indexing_does_not_count_as_hybrid_yet(
    session: AsyncSession, settings: Settings
) -> None:
    file_source = await _source(session, kind="file")
    await _document(session, source_id=file_source)
    await _source(session, kind="dump", status="indexing")

    assert await _has_hybrid_sources(session, settings) is False


@pytest.mark.asyncio
async def test_a_document_still_indexing_does_not_count_as_hybrid_yet(
    session: AsyncSession, settings: Settings
) -> None:
    file_source = await _source(session, kind="file")
    await _document(session, source_id=file_source, status="indexing")
    await _source(session, kind="dump")

    assert await _has_hybrid_sources(session, settings) is False
