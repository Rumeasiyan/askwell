"""Per-source index size, against a real Postgres.

`docs/ux/settings.md` §5, ticket `M7-SET-FE-148`. What matters here is the
"unknown, not zero" rule for a source with nothing measurable yet, and that a
source with real chunks gets a real, positive number back.
"""

import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from askwell.config import Settings
from askwell.sources import add, storage_by_source

pytestmark = pytest.mark.requires_db

TABLES = "roots, sources, documents, chunks, ingest_jobs, schema_notes, memory, audit_decisions"

PDF = b"%PDF-1.7\nEither party may terminate on ninety days written notice.\n"


@pytest.fixture
def async_url(database_url: str) -> str:
    return database_url.replace("postgresql://", "postgresql+psycopg://", 1)


@pytest_asyncio.fixture
async def session(async_url: str) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(async_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as opened:
        await opened.execute(text(f"TRUNCATE {TABLES} CASCADE"))
        await opened.commit()
        yield opened
        await opened.rollback()
        await opened.execute(text(f"TRUNCATE {TABLES} CASCADE"))
        await opened.commit()
    await engine.dispose()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url="postgresql://askwell:pw@127.0.0.1:1/askwell",  # type: ignore[arg-type]
        sandbox_database_url="postgresql://x:x@127.0.0.1:1/postgres",  # type: ignore[arg-type]
        sandbox_owner_password="pw",  # type: ignore[arg-type]
        sandbox_readonly_password="pw",  # type: ignore[arg-type]
        trace_dir=tmp_path / "traces",
        trace_max_bytes=1024 * 1024,
    )


async def nominate(session: AsyncSession, path: str) -> None:
    await session.execute(text("INSERT INTO roots (path) VALUES (:path)"), {"path": path})


def written(directory: Path, name: str, body: bytes = PDF) -> str:
    path = directory / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return name


def _embedding_literal(dimensions: int = 1024) -> str:
    return "[" + ",".join("0.1" for _ in range(dimensions)) + "]"


async def _chunk_with_content(
    session: AsyncSession, document_id: uuid.UUID, content: str, ordinal: int = 0
) -> None:
    await session.execute(
        text(
            "INSERT INTO chunks (document_id, ordinal, content, embedding) "
            "VALUES (:document_id, :ordinal, :content, :embedding)"
        ),
        {
            "document_id": document_id,
            "ordinal": ordinal,
            "content": content,
            "embedding": _embedding_literal(),
        },
    )


async def _document_id(session: AsyncSession) -> Any:
    result = await session.execute(text("SELECT id FROM documents LIMIT 1"))
    return result.scalar_one()


async def test_a_freshly_queued_source_reports_unknown_not_zero(
    session: AsyncSession, settings: Settings, tmp_path: Path
) -> None:
    folder = tmp_path / "clients"
    written(folder, "contract.pdf")
    await nominate(session, str(tmp_path))
    await add(session, str(folder), ["contract.pdf"])
    await session.commit()

    rows = await storage_by_source(session, settings)

    assert len(rows) == 1
    assert rows[0].status == "queued"
    assert rows[0].index_bytes is None


async def test_a_ready_source_with_chunks_reports_a_real_size(
    session: AsyncSession, settings: Settings, tmp_path: Path
) -> None:
    folder = tmp_path / "clients"
    written(folder, "contract.pdf")
    await nominate(session, str(tmp_path))
    await add(session, str(folder), ["contract.pdf"])
    document_id = await _document_id(session)
    await _chunk_with_content(session, document_id, "ninety days written notice")
    await session.execute(
        text("UPDATE sources SET status = 'ready'"),
    )
    await session.commit()

    rows = await storage_by_source(session, settings)

    assert len(rows) == 1
    assert rows[0].index_bytes is not None
    # Chunk text plus one embedding vector's worth of float4 lanes.
    assert (
        rows[0].index_bytes >= len("ninety days written notice") + settings.embedding_dimensions * 4
    )


async def test_a_connection_source_is_always_unknown(
    session: AsyncSession, settings: Settings
) -> None:
    await session.execute(
        text(
            "INSERT INTO sources (kind, name, status) VALUES ('connection', 'billing db', 'ready')"
        )
    )
    await session.commit()

    rows = await storage_by_source(session, settings)

    assert len(rows) == 1
    assert rows[0].kind == "connection"
    assert rows[0].index_bytes is None


async def test_a_deleted_source_is_not_listed(session: AsyncSession, settings: Settings) -> None:
    await session.execute(
        text("INSERT INTO sources (kind, name, status) VALUES ('file', 'old', 'deleted')")
    )
    await session.commit()

    rows = await storage_by_source(session, settings)

    assert rows == []
