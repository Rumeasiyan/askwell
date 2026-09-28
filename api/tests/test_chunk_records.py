"""Structure-aware chunking, end to end, against a real Postgres.
`M1-INDEX-ING-031`.

Mirrors `test_extract_office_records.py`'s pattern: files go through the
real `add()` path and then the real `ingest.process`, so what is under test
is the installed `chunk` stage itself — a real `document_pages` row in, real
`chunks` rows out — not a stand-in.
"""

import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import docx
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from askwell import chunk as chunk_module
from askwell import extract, ingest
from askwell.config import Settings
from askwell.db.engine import session_scope
from askwell.ingest import Stage, Work

from .test_ingest_records import TABLES, nominate, recorded

pytestmark = pytest.mark.requires_db

# Duplicated rather than imported, matching `test_extract_office_records.py`'s
# own note: a fixture reused across modules by import is flagged by ruff
# (F811) the moment a test's own parameter shadows the imported name.


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


@pytest.fixture
def unreachable_queue(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Iterator[Settings]:
    sent: list[uuid.UUID] = []

    async def fake_dispatch(
        _settings: Settings,
        document_ids: list[uuid.UUID],
        **_kwargs: object,
    ) -> int:
        sent.extend(document_ids)
        return len(document_ids)

    monkeypatch.setattr(ingest, "dispatch", fake_dispatch)
    # This module is about `chunk`, not `embed` — `M1-INDEX-ING-032` made
    # `embed` real and it needs a running inference process none of these
    # tests stand one up for. Frozen at real `extract` + `chunk` with `embed`
    # left unbuilt, matching every test's own assertion that a document
    # "parks" once chunking is done. `test_embed_records.py` covers `embed`.
    monkeypatch.setattr(
        ingest,
        "STAGES",
        (
            Stage("extract", "M1-EXTRACT-ING-026", extract.run),
            Stage("chunk", "M1-INDEX-ING-031", chunk_module.run),
            Stage("embed", "M1-INDEX-ING-032"),
        ),
    )
    yield settings


def _write_docx_with_a_rate_table(path: Path) -> None:
    document = docx.Document()
    document.add_heading("Renewal Terms", level=1)
    document.add_paragraph("Either party may terminate on ninety days written notice.")
    table = document.add_table(rows=3, cols=2)
    table.rows[0].cells[0].text = "Tier"
    table.rows[0].cells[1].text = "Monthly rate"
    table.rows[1].cells[0].text = "Standard"
    table.rows[1].cells[1].text = "199.00"
    table.rows[2].cells[0].text = "Premium"
    table.rows[2].cells[1].text = "349.00"
    document.save(str(path))


async def _process(
    factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    session: AsyncSession,
    tmp_path: Path,
    filename: str,
) -> tuple[str, list[tuple], uuid.UUID]:
    await nominate(session, str(tmp_path))
    documents = await recorded(session, tmp_path, filename)
    document_id = documents[0]
    outcome = await ingest.process(factory, settings, document_id)
    chunks = (
        await session.execute(
            text(
                "SELECT ordinal, page_from, page_to, heading, content FROM chunks "
                "WHERE document_id = :id ORDER BY ordinal"
            ),
            {"id": document_id},
        )
    ).all()
    return outcome, [tuple(row) for row in chunks], document_id


async def test_a_retrieved_row_carries_its_column_headings(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    unreachable_queue: Settings,
) -> None:
    """The ticket's own headline scenario: a table row does not arrive
    without the header that gives its number meaning."""
    _write_docx_with_a_rate_table(tmp_path / "rates.docx")
    outcome, chunks, _ = await _process(factory, unreachable_queue, session, tmp_path, "rates.docx")

    assert outcome == "parked"  # extract and chunk succeeded; embed is not installed yet
    assert len(chunks) >= 1

    table_chunk = next(chunk for chunk in chunks if "[TABLE]" in chunk[4])
    assert "Tier | Monthly rate" in table_chunk[4]
    assert "Premium | 349.00" in table_chunk[4]


async def test_ordinals_are_sequential_and_document_order_is_preserved(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    unreachable_queue: Settings,
) -> None:
    _write_docx_with_a_rate_table(tmp_path / "rates.docx")
    _, chunks, _ = await _process(factory, unreachable_queue, session, tmp_path, "rates.docx")

    assert [chunk[0] for chunk in chunks] == list(range(len(chunks)))


async def test_a_heading_is_recorded_on_the_chunk_beneath_it(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    unreachable_queue: Settings,
) -> None:
    _write_docx_with_a_rate_table(tmp_path / "rates.docx")
    _, chunks, _ = await _process(factory, unreachable_queue, session, tmp_path, "rates.docx")

    assert any(chunk[3] == "Renewal Terms" for chunk in chunks)


async def test_every_chunk_records_a_page_range_and_no_chunk_is_empty(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    unreachable_queue: Settings,
) -> None:
    _write_docx_with_a_rate_table(tmp_path / "rates.docx")
    _, chunks, _ = await _process(factory, unreachable_queue, session, tmp_path, "rates.docx")

    for _ordinal, page_from, page_to, _heading, content in chunks:
        assert page_from is not None
        assert page_to is not None
        assert page_from <= page_to
        assert content.strip() != ""


async def test_a_plain_text_document_with_no_headings_still_chunks_by_size(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    unreachable_queue: Settings,
) -> None:
    sentence = "Either party may terminate this agreement on ninety days written notice. "
    (tmp_path / "note.txt").write_text(sentence * 60)
    outcome, chunks, _ = await _process(factory, unreachable_queue, session, tmp_path, "note.txt")

    assert outcome == "parked"
    assert len(chunks) >= 1
    for chunk in chunks:
        content = chunk[4]
        assert len(content) <= 2400
        assert content.strip() != ""


async def test_re_running_chunk_replaces_rather_than_duplicates(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    unreachable_queue: Settings,
) -> None:
    """A retried job must not leave two generations of chunks behind it —
    the same idempotency `extract_common.write_anchors` already guarantees
    for `document_pages`."""
    _write_docx_with_a_rate_table(tmp_path / "rates.docx")
    await nominate(session, str(tmp_path))
    documents = await recorded(session, tmp_path, "rates.docx")
    document_id = documents[0]

    work = Work(
        document_id=document_id,
        source_id=uuid.uuid4(),
        path=str(tmp_path / "rates.docx"),
        filename="rates.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        sha256="0" * 64,
    )

    async def report(_done: int, _total: int) -> None:
        return None

    await extract.run(work, report, factory, unreachable_queue)
    await chunk_module.run(work, report, factory, unreachable_queue)
    first_run_count = len(
        (
            await session.execute(
                text("SELECT id FROM chunks WHERE document_id = :id"), {"id": document_id}
            )
        ).all()
    )

    await chunk_module.run(work, report, factory, unreachable_queue)

    async with session_scope(factory) as scoped:
        rows = (
            (
                await scoped.execute(
                    text("SELECT ordinal FROM chunks WHERE document_id = :id ORDER BY ordinal"),
                    {"id": document_id},
                )
            )
            .scalars()
            .all()
        )

    assert len(rows) == first_run_count
    assert rows == list(range(len(rows)))


async def _cite(session: AsyncSession, chunk_id: uuid.UUID) -> uuid.UUID:
    """An answer citing one passage, written the way `askwell.ask` writes it."""
    conversation_id = uuid.uuid4()
    message_id = uuid.uuid4()
    await session.execute(
        text("INSERT INTO conversations (id) VALUES (:id)"), {"id": conversation_id}
    )
    await session.execute(
        text(
            "INSERT INTO messages (id, conversation_id, role, content) "
            "VALUES (:id, :conversation_id, 'assistant', 'Ninety days.')"
        ),
        {"id": message_id, "conversation_id": conversation_id},
    )
    await session.execute(
        text(
            "INSERT INTO citations (message_id, chunk_id, claim_ordinal, quoted_span) "
            "VALUES (:message_id, :chunk_id, 0, 'ninety days')"
        ),
        {"message_id": message_id, "chunk_id": chunk_id},
    )
    await session.commit()
    return message_id


async def _chunks(session: AsyncSession, document_id: uuid.UUID) -> list[tuple]:
    rows = await session.execute(
        text(
            "SELECT id, content, superseded_at, embedding IS NULL, content_tsv IS NULL "
            "FROM chunks WHERE document_id = :id ORDER BY superseded_at NULLS LAST, ordinal"
        ),
        {"id": document_id},
    )
    return [tuple(row) for row in rows.all()]


def _text_work(tmp_path: Path, document_id: uuid.UUID) -> Work:
    return Work(
        document_id=document_id,
        source_id=uuid.uuid4(),
        path=str(tmp_path / "terms.txt"),
        filename="terms.txt",
        mime="text/plain",
        sha256="0" * 64,
    )


async def _noop_report(_done: int, _total: int) -> None:
    return None


async def test_re_chunking_a_cited_document_retires_the_cited_passage_and_keeps_its_text(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    unreachable_queue: Settings,
) -> None:
    """Issue #719: the chunk stage deleted every passage of the document and
    failed on `fk_citations_chunk_id_chunks` the moment one was cited. The
    cited passage now survives, unsearchable, holding exactly the text the
    old answer cited (C4 — never repointed at the new wording); the new
    passages are the only live ones."""
    (tmp_path / "terms.txt").write_text("Either party may terminate on ninety days notice.")
    await nominate(session, str(tmp_path))
    document_id = (await recorded(session, tmp_path, "terms.txt"))[0]
    work = _text_work(tmp_path, document_id)
    await extract.run(work, _noop_report, factory, unreachable_queue)
    await chunk_module.run(work, _noop_report, factory, unreachable_queue)

    [(cited_id, cited_content, superseded_at, _, _)] = await _chunks(session, document_id)
    assert superseded_at is None
    await _cite(session, cited_id)

    (tmp_path / "terms.txt").write_text("Either party may terminate on thirty days notice.")
    await extract.run(work, _noop_report, factory, unreachable_queue)
    await chunk_module.run(work, _noop_report, factory, unreachable_queue)

    rows = await _chunks(session, document_id)
    live = [row for row in rows if row[2] is None]
    retired = [row for row in rows if row[2] is not None]
    assert [row[1] for row in live] == ["Either party may terminate on thirty days notice."]
    assert live[0][0] != cited_id
    assert retired == [(cited_id, cited_content, retired[0][2], True, True)]

    resolved = (
        await session.execute(
            text(
                "SELECT c.content, c.superseded_at IS NOT NULL FROM citations ci "
                "JOIN chunks c ON c.id = ci.chunk_id"
            )
        )
    ).one()
    assert resolved == ("Either party may terminate on ninety days notice.", True)


async def test_an_uncited_passage_is_still_deleted_by_a_re_chunk(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    unreachable_queue: Settings,
) -> None:
    """Only a cited passage is kept. Retiring every old passage would grow the
    table by a copy of the document on every re-index for nothing."""
    (tmp_path / "terms.txt").write_text("Either party may terminate on ninety days notice.")
    await nominate(session, str(tmp_path))
    document_id = (await recorded(session, tmp_path, "terms.txt"))[0]
    work = _text_work(tmp_path, document_id)
    await extract.run(work, _noop_report, factory, unreachable_queue)
    await chunk_module.run(work, _noop_report, factory, unreachable_queue)
    [(first_id, *_)] = await _chunks(session, document_id)

    await chunk_module.run(work, _noop_report, factory, unreachable_queue)

    rows = await _chunks(session, document_id)
    assert len(rows) == 1
    assert rows[0][0] != first_id
    assert rows[0][2] is None


async def test_a_second_re_chunk_keeps_the_first_retirement_date(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    unreachable_queue: Settings,
) -> None:
    """The date a passage was replaced is when it stopped being the file's
    text; a later re-index does not move it."""
    (tmp_path / "terms.txt").write_text("Either party may terminate on ninety days notice.")
    await nominate(session, str(tmp_path))
    document_id = (await recorded(session, tmp_path, "terms.txt"))[0]
    work = _text_work(tmp_path, document_id)
    await extract.run(work, _noop_report, factory, unreachable_queue)
    await chunk_module.run(work, _noop_report, factory, unreachable_queue)
    [(cited_id, *_)] = await _chunks(session, document_id)
    await _cite(session, cited_id)

    await chunk_module.run(work, _noop_report, factory, unreachable_queue)
    first_date = next(row[2] for row in await _chunks(session, document_id) if row[0] == cited_id)
    await chunk_module.run(work, _noop_report, factory, unreachable_queue)
    rows = await _chunks(session, document_id)

    assert next(row[2] for row in rows if row[0] == cited_id) == first_date
    assert len([row for row in rows if row[2] is None]) == 1
    assert len(rows) == 2


async def test_re_indexing_a_cited_document_gets_past_the_chunk_stage(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    unreachable_queue: Settings,
) -> None:
    """The walkthrough that found #719, through the real re-index and the real
    pipeline: a cited document used to land in `attention` at stage `chunk`.
    It now parks at `embed`, the one stage this module leaves unbuilt."""
    (tmp_path / "terms.txt").write_text("Either party may terminate on ninety days notice.")
    await nominate(session, str(tmp_path))
    document_id = (await recorded(session, tmp_path, "terms.txt"))[0]
    assert await ingest.process(factory, unreachable_queue, document_id) == "parked"
    [(cited_id, *_)] = await _chunks(session, document_id)
    await _cite(session, cited_id)

    source_id = (
        await session.execute(
            text("SELECT source_id FROM documents WHERE id = :id"), {"id": document_id}
        )
    ).scalar_one()
    (tmp_path / "terms.txt").write_text("Either party may terminate on thirty days notice.")
    await ingest.reindex_source(session, source_id, unreachable_queue)
    await session.commit()

    assert await ingest.process(factory, unreachable_queue, document_id) == "parked"
    job = (
        await session.execute(
            text("SELECT state, stage, error FROM ingest_jobs WHERE document_id = :id"),
            {"id": document_id},
        )
    ).one()
    assert job.error is None
    assert job.stage == "chunk"
    assert len(await _chunks(session, document_id)) == 2


async def test_a_retired_passage_cannot_keep_a_search_path(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    unreachable_queue: Settings,
) -> None:
    """The constraint behind the retirement: a superseded passage that kept
    its search vector would still answer questions about text the file no
    longer contains."""
    (tmp_path / "terms.txt").write_text("Either party may terminate on ninety days notice.")
    await nominate(session, str(tmp_path))
    document_id = (await recorded(session, tmp_path, "terms.txt"))[0]
    work = _text_work(tmp_path, document_id)
    await extract.run(work, _noop_report, factory, unreachable_queue)
    await chunk_module.run(work, _noop_report, factory, unreachable_queue)
    [(chunk_id, *_)] = await _chunks(session, document_id)

    with pytest.raises(IntegrityError):
        await session.execute(
            text("UPDATE chunks SET superseded_at = now() WHERE id = :id"), {"id": chunk_id}
        )
