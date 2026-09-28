"""Resolving a conflict writes a memory fact. `M9-FIX-FE-204`, issue #728.

Against a real Postgres, like `test_memory.py`: what is being tested is which
`memory` rows are active afterwards, and a fake session would re-implement
the supersession query under test.
"""

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from askwell.conflict_resolution import (
    DocumentNotCited,
    NotAConflict,
    TurnNotFound,
    resolve_conflict,
)
from askwell.memory import get_active_memory_facts, retrieve_relevant_facts

pytestmark = pytest.mark.requires_db

_TABLES = "sources, documents, chunks, citations, memory, audit_decisions, conversations, messages"

_CONFLICT_ANSWER = (
    "Conflicting sources on store closing times:\n"
    "- Stores close at 9 PM on weekdays [1].\n"
    "- Stores close at 8 PM on weekdays [2]."
)


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


async def _document(session: AsyncSession, source_id: uuid.UUID, filename: str) -> uuid.UUID:
    document_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO documents (id, source_id, filename, path, sha256, status) "
            "VALUES (:id, :source_id, :filename, :path, :sha256, 'ready')"
        ),
        {
            "id": document_id,
            "source_id": source_id,
            "filename": filename,
            "path": f"/tmp/{filename}",
            "sha256": uuid.uuid4().hex,
        },
    )
    return document_id


async def _turn(
    session: AsyncSession,
    *,
    answer: str = _CONFLICT_ANSWER,
    question: str = "What are the store hours?",
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    """One asked-and-answered turn citing two documents, one chunk each.
    Returns the assistant message, the two documents, and the source."""
    source_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO sources (id, kind, name, status) VALUES (:id, 'file', 'corpus', 'ready')"
        ),
        {"id": source_id},
    )
    old = await _document(session, source_id, "store_hours_2025.pdf")
    new = await _document(session, source_id, "store_hours_2026.pdf")
    conversation_id = uuid.uuid4()
    await session.execute(
        text("INSERT INTO conversations (id) VALUES (:id)"), {"id": conversation_id}
    )
    await session.execute(
        text(
            "INSERT INTO messages (conversation_id, role, content, created_at) "
            "VALUES (:conversation_id, 'user', :content, now() - interval '1 second')"
        ),
        {"conversation_id": conversation_id, "content": question},
    )
    message_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO messages (id, conversation_id, role, content) "
            "VALUES (:id, :conversation_id, 'assistant', :content)"
        ),
        {"id": message_id, "conversation_id": conversation_id, "content": answer},
    )
    for ordinal, document_id in ((1, old), (2, new)):
        chunk_id = uuid.uuid4()
        await session.execute(
            text(
                "INSERT INTO chunks (id, document_id, ordinal, content) "
                "VALUES (:id, :document_id, 0, 'hours')"
            ),
            {"id": chunk_id, "document_id": document_id},
        )
        await session.execute(
            text(
                "INSERT INTO citations (message_id, chunk_id, claim_ordinal) "
                "VALUES (:message_id, :chunk_id, :ordinal)"
            ),
            {"message_id": message_id, "chunk_id": chunk_id, "ordinal": ordinal},
        )
    return message_id, old, new, source_id


@pytest.mark.asyncio
async def test_choosing_the_current_document_writes_a_user_fact_for_the_topic(
    session: AsyncSession,
) -> None:
    message_id, _old, new, _source = await _turn(session)

    outcome = await resolve_conflict(session, message_id=message_id, document_id=new)

    assert outcome.written
    assert outcome.subject == "store closing times"
    assert outcome.fact == (
        "store_hours_2026.pdf is the current document for store closing times, "
        "not store_hours_2025.pdf."
    )
    [fact] = await get_active_memory_facts(session, subject="store closing times")
    assert fact.id == outcome.fact_id
    assert fact.fact == outcome.fact
    assert fact.origin == "clarification"
    # Read at question time, never at ingest: no source to re-read on a
    # correction or deletion.
    assert fact.source_id is None


@pytest.mark.asyncio
async def test_the_fact_is_found_for_the_next_question_on_the_topic(
    session: AsyncSession,
) -> None:
    message_id, _old, new, _source = await _turn(session)
    outcome = await resolve_conflict(session, message_id=message_id, document_id=new)

    relevant = await retrieve_relevant_facts(session, question="What are the store hours?")

    assert [fact.id for fact in relevant.facts] == [outcome.fact_id]


@pytest.mark.asyncio
async def test_choosing_the_other_supersedes_rather_than_duplicates(
    session: AsyncSession,
) -> None:
    message_id, old, new, _source = await _turn(session)
    first = await resolve_conflict(session, message_id=message_id, document_id=new)

    second = await resolve_conflict(session, message_id=message_id, document_id=old)

    active = await get_active_memory_facts(session, subject="store closing times")
    assert [fact.id for fact in active] == [second.fact_id]
    assert active[0].fact.startswith("store_hours_2025.pdf is the current document")
    superseded_by = (
        await session.execute(
            text("SELECT superseded_by FROM memory WHERE id = :id"), {"id": first.fact_id}
        )
    ).scalar_one()
    assert superseded_by == second.fact_id


@pytest.mark.asyncio
async def test_choosing_the_same_document_twice_writes_nothing_the_second_time(
    session: AsyncSession,
) -> None:
    message_id, _old, new, _source = await _turn(session)
    first = await resolve_conflict(session, message_id=message_id, document_id=new)

    again = await resolve_conflict(session, message_id=message_id, document_id=new)

    assert not again.written
    assert again.fact_id == first.fact_id
    count = (await session.execute(text("SELECT count(*) FROM memory"))).scalar_one()
    assert count == 1


@pytest.mark.asyncio
async def test_a_write_is_recorded_in_the_decisions_log(session: AsyncSession) -> None:
    message_id, _old, new, _source = await _turn(session)
    outcome = await resolve_conflict(session, message_id=message_id, document_id=new)

    payloads = (
        (
            await session.execute(
                text("SELECT payload FROM audit_decisions WHERE kind = 'memory_written'")
            )
        )
        .scalars()
        .all()
    )
    assert [payload["fact_id"] for payload in payloads] == [str(outcome.fact_id)]


@pytest.mark.asyncio
async def test_a_conflict_line_naming_nothing_uses_the_question_as_the_subject(
    session: AsyncSession,
) -> None:
    message_id, _old, new, _source = await _turn(
        session,
        answer=(
            "Conflicting sources on :\n- Stores close at 9 PM [1].\n- Stores close at 8 PM [2]."
        ),
    )

    outcome = await resolve_conflict(session, message_id=message_id, document_id=new)

    assert outcome.subject == "What are the store hours?"


@pytest.mark.asyncio
async def test_a_document_the_turn_did_not_cite_is_refused(session: AsyncSession) -> None:
    message_id, _old, _new, source_id = await _turn(session)
    stranger = await _document(session, source_id, "unrelated.pdf")

    with pytest.raises(DocumentNotCited):
        await resolve_conflict(session, message_id=message_id, document_id=stranger)
    assert (await session.execute(text("SELECT count(*) FROM memory"))).scalar_one() == 0


@pytest.mark.asyncio
async def test_an_answer_with_no_conflict_is_refused(session: AsyncSession) -> None:
    message_id, _old, new, _source = await _turn(session, answer="Stores close at 9 PM [1].")

    with pytest.raises(NotAConflict):
        await resolve_conflict(session, message_id=message_id, document_id=new)


@pytest.mark.asyncio
async def test_an_unknown_turn_is_refused(session: AsyncSession) -> None:
    with pytest.raises(TurnNotFound):
        await resolve_conflict(session, message_id=uuid.uuid4(), document_id=uuid.uuid4())
