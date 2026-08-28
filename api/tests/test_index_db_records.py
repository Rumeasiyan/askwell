"""Full-text column population and index, against a real Postgres.
`M1-INDEX-DB-033`.

`content_tsv` is a generated `STORED` column and its GIN index both already
exist in the schema (`a8208099ef38`) and need no application code to
populate — Postgres does that on every write. What this ticket owns is
proving that, proving the index is actually what a lexical query uses at
scale, and fixing the one real gap: a reference number's tokenising
(`c7e2f814a5b3`). Chunks are inserted directly by SQL rather than run
through the full ingest pipeline — nothing here is about extraction or
chunking, only about what Postgres does with a `content` value once it
lands in the table.
"""

import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .test_ingest_records import PDF, TABLES, nominate, recorded

pytestmark = pytest.mark.requires_db


@pytest.fixture
def async_url(database_url: str) -> str:
    return database_url.replace("postgresql://", "postgresql+psycopg://", 1)


@pytest_asyncio.fixture
async def factory(async_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
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
async def session(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with factory() as opened:
        yield opened
        await opened.rollback()


async def _a_document(session: AsyncSession, tmp_path: Path) -> uuid.UUID:
    (tmp_path / "doc.pdf").write_bytes(PDF)
    await nominate(session, str(tmp_path))
    documents = await recorded(session, tmp_path, "doc.pdf")
    return documents[0]


async def _insert_chunk(session: AsyncSession, document_id: uuid.UUID, content: str) -> uuid.UUID:
    chunk_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO chunks (id, document_id, ordinal, content) "
            "VALUES (:id, :document_id, 0, :content)"
        ),
        {"id": chunk_id, "document_id": document_id, "content": content},
    )
    await session.commit()
    return chunk_id


async def _matches(session: AsyncSession, query: str, chunk_id: uuid.UUID) -> bool:
    # A query has to be tokenised the same way the column was, or the fix
    # is only half done: hyphens go to spaces here too, mirroring the
    # generated column's own expression (`c7e2f814a5b3`). Whichever ticket
    # builds the real lexical query (`M1-ASK-RET-035`) owns doing this for
    # real; this is the same normalisation, not a different one invented
    # for the test.
    row = (
        await session.execute(
            text(
                "SELECT content_tsv @@ plainto_tsquery('english', "
                "regexp_replace(:query, '-', ' ', 'g')) FROM chunks WHERE id = :id"
            ),
            {"query": query, "id": chunk_id},
        )
    ).scalar_one()
    return bool(row)


async def test_a_chunk_written_with_content_has_a_populated_full_text_value(
    session: AsyncSession, tmp_path: Path
) -> None:
    document_id = await _a_document(session, tmp_path)
    chunk_id = await _insert_chunk(session, document_id, "Either party may terminate.")
    has_tsv = (
        await session.execute(
            text("SELECT content_tsv IS NOT NULL FROM chunks WHERE id = :id"), {"id": chunk_id}
        )
    ).scalar_one()
    assert has_tsv is True


async def test_a_chunk_with_no_content_is_not_considered_indexed(
    session: AsyncSession, tmp_path: Path
) -> None:
    document_id = await _a_document(session, tmp_path)
    chunk_id = uuid.uuid4()
    await session.execute(
        text("INSERT INTO chunks (id, document_id, ordinal, content) VALUES (:id, :doc, 0, NULL)"),
        {"id": chunk_id, "doc": document_id},
    )
    await session.commit()
    tsv = (
        await session.execute(
            text("SELECT content_tsv FROM chunks WHERE id = :id"), {"id": chunk_id}
        )
    ).scalar_one()
    # `coalesce(content, '')` still produces an empty, non-null vector: a
    # tombstoned document must not silently vanish from every index scan for
    # a different reason than "there is nothing here to find".
    assert str(tsv) == ""


async def test_a_reference_number_is_found_by_its_own_trailing_group(
    session: AsyncSession, tmp_path: Path
) -> None:
    """The ticket's own scenario: INV-2024-0917 must be findable by a
    lexical query, including a query for just the part someone actually
    remembers — the default parser reads the hyphen before a digit run as
    a sign and buries it in the lexeme (`-0917`), so a bare `0917` query
    never matched before `c7e2f814a5b3`."""
    document_id = await _a_document(session, tmp_path)
    chunk_id = await _insert_chunk(
        session, document_id, "Invoice INV-2024-0917 is due at the end of the quarter."
    )
    assert await _matches(session, "INV-2024-0917", chunk_id)
    assert await _matches(session, "0917", chunk_id)
    assert await _matches(session, "2024", chunk_id)


async def test_a_chunk_of_pure_numbers_or_codes_still_tokenises(
    session: AsyncSession, tmp_path: Path
) -> None:
    document_id = await _a_document(session, tmp_path)
    chunk_id = await _insert_chunk(session, document_id, "1234567890 AB1234 2024-0917")
    assert await _matches(session, "1234567890", chunk_id)
    assert await _matches(session, "0917", chunk_id)


async def test_a_very_long_chunk_indexes_without_error(
    session: AsyncSession, tmp_path: Path
) -> None:
    document_id = await _a_document(session, tmp_path)
    content = "word " * 2400  # the hard maximum chunk length, `chunk.py`'s own bound
    chunk_id = await _insert_chunk(session, document_id, content)
    assert await _matches(session, "word", chunk_id)


async def test_reindexing_repopulates_rather_than_duplicating(
    session: AsyncSession, tmp_path: Path
) -> None:
    """`chunk.py`'s own re-run behaviour (`M1-INDEX-ING-031`) deletes and
    reinserts a document's chunks rather than updating them; this proves
    the generated column keeps up with that, and that there is exactly one
    row, not two, once a document has been chunked twice."""
    document_id = await _a_document(session, tmp_path)
    first_id = await _insert_chunk(session, document_id, "The original wording, INV-0001.")
    await session.execute(text("DELETE FROM chunks WHERE document_id = :id"), {"id": document_id})
    await session.commit()
    second_id = await _insert_chunk(session, document_id, "The replacement wording, INV-0002.")

    count = (
        await session.execute(
            text("SELECT count(*) FROM chunks WHERE document_id = :id"), {"id": document_id}
        )
    ).scalar_one()
    assert count == 1
    assert not await _matches(session, "0001", second_id)
    assert await _matches(session, "0002", second_id)
    assert first_id != second_id


async def test_a_lexical_query_at_scale_uses_the_index(
    session: AsyncSession, tmp_path: Path
) -> None:
    """Acceptance criterion: the query plan uses the index rather than
    scanning, at corpus scale. A handful of rows is not enough for the
    planner to prefer a bitmap index scan over a sequential one — the
    corpus is seeded to a size where a scan is actually the wrong choice."""
    document_id = await _a_document(session, tmp_path)
    await session.execute(
        text(
            "INSERT INTO chunks (id, document_id, ordinal, content) "
            "SELECT gen_random_uuid(), :document_id, n, "
            "'Routine filler text about nothing in particular, entry number ' || n::text "
            "FROM generate_series(1, 300000) AS n"
        ),
        {"document_id": document_id},
    )
    chunk_id = await _insert_chunk(
        session, document_id, "The distinctive reference is INV-2024-0917."
    )
    await session.execute(text("ANALYZE chunks"))
    await session.commit()
    assert await _matches(session, "0917", chunk_id)

    plan = (
        await session.execute(
            text(
                "EXPLAIN SELECT id FROM chunks WHERE content_tsv @@ "
                "plainto_tsquery('english', regexp_replace('0917', '-', ' ', 'g'))"
            )
        )
    ).scalars()
    plan_text = "\n".join(row for row in plan)
    assert "ix_chunks_content_tsv" in plan_text, plan_text
    assert "Seq Scan" not in plan_text, plan_text
