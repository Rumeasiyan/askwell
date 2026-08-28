"""The uncited-claim query, against a real Postgres. `M1-CITE-TEST-045`.

Messages and citations are inserted directly rather than run through a real
`ask()` turn — what is under test is the reconciliation itself: that a claim
with a citation row counts, that a claim without one is named with its own
text, that an abstention (no claims at all) counts as compliant rather than
as a violation, and that a message with a `fact_usage` row is excluded and
counted as excluded rather than checked, matching the ticket's own stated
M3 gap.

Mirrors the manual walkthrough the ticket's own testing notes describe: seed
a small answered corpus, run the check, see full coverage; delete one
citation row directly, run it again, see that exact answer named with its
now-uncited claim quoted.
"""

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from askwell.agent.citation_check import check_citations

from .test_ingest_records import TABLES as INGEST_TABLES

pytestmark = pytest.mark.requires_db

TABLES = f"{INGEST_TABLES}, conversations, messages, citations, fact_usage"

# The bar the counter-metric must never sit below (`docs/success-metrics.md`
# §2, "sampled answers where every factual claim traces to a retrieved chunk
# or a memory fact" — 100%). A prompt change that lets fluency merge two
# facts into one uncited sentence fails this test before it fails a person.
BAR = 100.0


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


async def _conversation(session: AsyncSession) -> uuid.UUID:
    conversation_id = uuid.uuid4()
    await session.execute(
        text("INSERT INTO conversations (id) VALUES (:id)"), {"id": conversation_id}
    )
    return conversation_id


async def _source_document_chunk(session: AsyncSession) -> uuid.UUID:
    """One source, one document, one chunk — enough for a citation's foreign
    key, since this suite has no need to exercise ingestion."""
    source_id = uuid.uuid4()
    await session.execute(
        text("INSERT INTO sources (id, kind, name) VALUES (:id, 'file', 'a source')"),
        {"id": source_id},
    )
    document_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO documents (id, source_id, filename, path, sha256) "
            "VALUES (:id, :source_id, 'file.txt', :path, :sha256)"
        ),
        {
            "id": document_id,
            "source_id": source_id,
            "path": f"/tmp/{document_id}.txt",
            "sha256": uuid.uuid4().hex.ljust(64, "0")[:64],
        },
    )
    chunk_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO chunks (id, document_id, ordinal, content) "
            "VALUES (:id, :document_id, 0, 'the rent is due on the first')"
        ),
        {"id": chunk_id, "document_id": document_id},
    )
    return chunk_id


async def _message(session: AsyncSession, conversation_id: uuid.UUID, content: str) -> uuid.UUID:
    message_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO messages (id, conversation_id, role, content) "
            "VALUES (:id, :conversation_id, 'assistant', :content)"
        ),
        {"id": message_id, "conversation_id": conversation_id, "content": content},
    )
    return message_id


async def _citation(
    session: AsyncSession, message_id: uuid.UUID, chunk_id: uuid.UUID, ordinal: int
) -> uuid.UUID:
    citation_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO citations (id, message_id, chunk_id, claim_ordinal) "
            "VALUES (:id, :message_id, :chunk_id, :ordinal)"
        ),
        {"id": citation_id, "message_id": message_id, "chunk_id": chunk_id, "ordinal": ordinal},
    )
    return citation_id


async def test_a_fully_cited_corpus_reports_full_coverage(session: AsyncSession) -> None:
    conversation_id = await _conversation(session)
    chunk_id = await _source_document_chunk(session)

    for question_index in range(5):
        message_id = await _message(
            session,
            conversation_id,
            f"The rent is due on the first [1]. Question {question_index} answered.",
        )
        await _citation(session, message_id, chunk_id, ordinal=1)
    await session.commit()

    result = await check_citations(session)

    assert result.checked == 5
    assert result.percentage == BAR
    assert result.violations == ()


async def test_deleting_a_citation_row_names_the_answer_and_quotes_the_claim(
    session: AsyncSession,
) -> None:
    conversation_id = await _conversation(session)
    chunk_id = await _source_document_chunk(session)

    message_id = await _message(
        session, conversation_id, "The rent is due on the first [1]. Thanks for asking."
    )
    citation_id = await _citation(session, message_id, chunk_id, ordinal=1)
    await session.commit()

    before = await check_citations(session)
    assert before.percentage == BAR

    await session.execute(text("DELETE FROM citations WHERE id = :id"), {"id": citation_id})
    await session.commit()

    after = await check_citations(session)

    assert after.percentage < BAR
    assert len(after.violations) == 1
    violation = after.violations[0]
    assert violation.message_id == str(message_id)
    assert violation.claim_text == "The rent is due on the first"


async def test_an_abstention_with_no_claims_counts_as_compliant(session: AsyncSession) -> None:
    conversation_id = await _conversation(session)
    await _message(
        session,
        conversation_id,
        "Nothing in your files answers this. Add the lease agreement to check.",
    )
    await session.commit()

    result = await check_citations(session)

    assert result.checked == 1
    assert result.compliant == 1
    assert result.violations == ()


async def test_a_message_with_fact_usage_is_excluded_not_checked(session: AsyncSession) -> None:
    conversation_id = await _conversation(session)
    message_id = await _message(
        session, conversation_id, "The rent is due on the first [1]. No citation for this one."
    )
    await session.execute(
        text(
            "INSERT INTO fact_usage (id, message_id, fact_kind, fact_id) "
            "VALUES (:id, :message_id, 'memory', :fact_id)"
        ),
        {"id": uuid.uuid4(), "message_id": message_id, "fact_id": uuid.uuid4()},
    )
    await session.commit()

    result = await check_citations(session)

    assert result.checked == 0
    assert result.excluded_fact_usage == 1
    assert result.violations == ()
