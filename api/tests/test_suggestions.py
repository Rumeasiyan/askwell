"""Corpus-derived suggested questions, against a real Postgres. `M1-LIB-FE-051`.

What is under test is the heuristic's own acceptance criteria: a heading beats
a term, a document with neither still produces a question rather than
nothing, an `indexing`/`attention` document is invisible to it entirely, and
a corpus too small for three gives back fewer rather than padding with
anything generic.
"""

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from askwell.suggestions import MAX_SUGGESTIONS, suggested_questions

from .test_ingest_records import TABLES

pytestmark = pytest.mark.requires_db


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


async def _source(session: AsyncSession) -> uuid.UUID:
    source_id = uuid.uuid4()
    await session.execute(
        text("INSERT INTO sources (id, kind, name) VALUES (:id, 'file', 'a source')"),
        {"id": source_id},
    )
    return source_id


async def _document(
    session: AsyncSession, source_id: uuid.UUID, filename: str, *, status: str = "ready"
) -> uuid.UUID:
    document_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO documents (id, source_id, filename, path, sha256, status) "
            "VALUES (:id, :source_id, :filename, :path, :sha256, :status)"
        ),
        {
            "id": document_id,
            "source_id": source_id,
            "filename": filename,
            "path": f"/tmp/{document_id}",
            "sha256": uuid.uuid4().hex.ljust(64, "0")[:64],
            "status": status,
        },
    )
    return document_id


async def _chunk(
    session: AsyncSession,
    document_id: uuid.UUID,
    *,
    ordinal: int = 0,
    heading: str | None = None,
    content: str | None = None,
) -> None:
    await session.execute(
        text(
            "INSERT INTO chunks (id, document_id, ordinal, heading, content) "
            "VALUES (:id, :document_id, :ordinal, :heading, :content)"
        ),
        {
            "id": uuid.uuid4(),
            "document_id": document_id,
            "ordinal": ordinal,
            "heading": heading,
            "content": content,
        },
    )


async def _committed(session: AsyncSession) -> None:
    await session.commit()


async def test_an_empty_corpus_suggests_nothing(session: AsyncSession) -> None:
    assert await suggested_questions(session) == []


async def test_a_heading_produces_a_question_naming_it_and_the_file(
    session: AsyncSession,
) -> None:
    source_id = await _source(session)
    document_id = await _document(session, source_id, "supplier-agreement-2024.pdf")
    await _chunk(session, document_id, heading="Payment terms", content="irrelevant prose")
    await _committed(session)

    suggestions = await suggested_questions(session)

    assert suggestions == [
        {
            "question": "What does supplier-agreement-2024.pdf say about Payment terms?",
            "filename": "supplier-agreement-2024.pdf",
        }
    ]


async def test_no_heading_falls_back_to_a_frequent_term(session: AsyncSession) -> None:
    source_id = await _source(session)
    document_id = await _document(session, source_id, "notes.txt")
    await _chunk(
        session,
        document_id,
        content="Meridian Meridian Meridian shipped the widgets on time this quarter.",
    )
    await _committed(session)

    suggestions = await suggested_questions(session)

    assert suggestions == [
        {"question": "What does notes.txt mention about meridian?", "filename": "notes.txt"}
    ]


async def test_no_heading_and_no_content_still_names_the_file(session: AsyncSession) -> None:
    source_id = await _source(session)
    document_id = await _document(session, source_id, "ledger.xlsx")
    await _chunk(session, document_id, heading=None, content=None)
    await _committed(session)

    suggestions = await suggested_questions(session)

    assert suggestions == [{"question": "What is in ledger.xlsx?", "filename": "ledger.xlsx"}]


async def test_a_document_still_indexing_is_never_suggested(session: AsyncSession) -> None:
    source_id = await _source(session)
    indexing_id = await _document(session, source_id, "in-progress.pdf", status="indexing")
    await _chunk(session, indexing_id, heading="Whatever this turns out to be")
    ready_id = await _document(session, source_id, "done.pdf")
    await _chunk(session, ready_id, heading="Finished")
    await _committed(session)

    suggestions = await suggested_questions(session)

    assert suggestions == [
        {"question": "What does done.pdf say about Finished?", "filename": "done.pdf"}
    ]


async def test_a_corpus_too_small_for_three_returns_fewer_not_padded(
    session: AsyncSession,
) -> None:
    source_id = await _source(session)
    document_id = await _document(session, source_id, "only-one.pdf")
    await _chunk(session, document_id, heading="The only heading there is")
    await _committed(session)

    suggestions = await suggested_questions(session)

    assert len(suggestions) == 1


async def test_never_more_than_the_maximum(session: AsyncSession) -> None:
    source_id = await _source(session)
    for index in range(MAX_SUGGESTIONS + 2):
        document_id = await _document(session, source_id, f"file-{index}.pdf")
        await _chunk(session, document_id, heading=f"Heading {index}")
    await _committed(session)

    suggestions = await suggested_questions(session)

    assert len(suggestions) == MAX_SUGGESTIONS


async def test_a_deleted_document_is_never_suggested(session: AsyncSession) -> None:
    source_id = await _source(session)
    document_id = await _document(session, source_id, "gone.pdf")
    await session.execute(
        text("UPDATE documents SET deleted_at = now() WHERE id = :id"), {"id": document_id}
    )
    await _chunk(session, document_id, heading="Should never surface")
    await _committed(session)

    suggestions = await suggested_questions(session)

    assert suggestions == []
