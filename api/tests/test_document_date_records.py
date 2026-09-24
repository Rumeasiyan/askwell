"""A document's own date, written by the real `extract` stage into a real
Postgres. `M7-FIX-BE-170a`.

The acceptance criteria, end to end: a PDF or OOXML file with metadata dates
is dated from metadata; a file with none but a year in its name gets that
year from the filename; a file with neither gets null — and `added_at` is
never what fills it. Plus the two edge cases that only show through the
pipeline: a corrupt metadata block falls through to the filename without
failing the ingest, and re-indexing re-dates a document (the backfill path
for rows ingested before this ticket), including back to null.
"""

import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import date, datetime
from pathlib import Path

import docx
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from askwell import chunk as chunk_module
from askwell import extract, ingest
from askwell.config import Settings
from askwell.ingest import Stage

from .test_ingest_records import PDF, TABLES, nominate, recorded

pytestmark = pytest.mark.requires_db


# Fixtures duplicated from `test_extract_office_records.py` for the reason
# that module gives: an imported fixture is shadowed by every test parameter
# of the same name (ruff F811).


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
    async def fake_dispatch(
        _settings: Settings, document_ids: list[uuid.UUID], **_kwargs: object
    ) -> int:
        return len(document_ids)

    monkeypatch.setattr(ingest, "dispatch", fake_dispatch)
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


def _with_info(pdf: bytes, info: bytes) -> bytes:
    """`pdf` plus an `/Info` dictionary, appended as an incremental update —
    ISO 32000-1 §7.5.6, which is how a real editor adds one to an existing
    file, and which leaves the original bytes untouched."""
    size = int(pdf.split(b"/Size ")[1].split(b" ")[0])
    previous = int(pdf.rsplit(b"startxref\n", 1)[1].split(b"\n")[0])
    body = bytearray(pdf + b"\n")
    offset = len(body)
    body += f"{size} 0 obj\n".encode() + info + b"\nendobj\n"
    xref = len(body)
    body += f"xref\n{size} 1\n{offset:010d} 00000 n \n".encode()
    body += (
        f"trailer\n<< /Size {size + 1} /Root 1 0 R /Info {size} 0 R /Prev {previous} >>\n"
    ).encode()
    body += f"startxref\n{xref}\n%%EOF".encode()
    return bytes(body)


async def _dated(
    session: AsyncSession, document_id: uuid.UUID
) -> tuple[date | None, str | None, str | None]:
    row = (
        await session.execute(
            text(
                "SELECT document_date, document_date_precision, document_date_source "
                "FROM documents WHERE id = :id"
            ),
            {"id": document_id},
        )
    ).one()
    return row[0], row[1], row[2]


async def _ingest(
    factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    session: AsyncSession,
    folder: Path,
    filename: str,
) -> uuid.UUID:
    await nominate(session, str(folder))
    document_id = (await recorded(session, folder, filename))[0]
    assert await ingest.process(factory, settings, document_id) == "parked"
    return document_id


async def test_a_pdf_with_a_creation_date_and_no_date_in_its_name_is_dated_from_metadata(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    unreachable_queue: Settings,
) -> None:
    (tmp_path / "Handbook.pdf").write_bytes(
        _with_info(PDF, b"<< /CreationDate (D:20240615093000Z) >>")
    )
    document_id = await _ingest(factory, unreachable_queue, session, tmp_path, "Handbook.pdf")

    assert await _dated(session, document_id) == (date(2024, 6, 15), "day", "metadata")


async def test_pdf_metadata_wins_over_a_year_in_the_name(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    unreachable_queue: Settings,
) -> None:
    (tmp_path / "handbook_2025.pdf").write_bytes(
        _with_info(PDF, b"<< /CreationDate (D:20250110) /ModDate (D:20260302) >>")
    )
    document_id = await _ingest(factory, unreachable_queue, session, tmp_path, "handbook_2025.pdf")

    assert await _dated(session, document_id) == (date(2026, 3, 2), "day", "metadata")


async def test_the_fixture_store_hours_pdfs_are_dated_by_filename_year(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    unreachable_queue: Settings,
) -> None:
    """The ticket's own walkthrough: no `/Info` at all, a year in the name."""
    (tmp_path / "store_hours_2025.pdf").write_bytes(PDF)
    document_id = await _ingest(
        factory, unreachable_queue, session, tmp_path, "store_hours_2025.pdf"
    )

    assert await _dated(session, document_id) == (date(2025, 1, 1), "year", "filename")


async def test_a_future_pdf_creation_date_is_ignored_for_the_filename(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    unreachable_queue: Settings,
) -> None:
    (tmp_path / "rota_2025.pdf").write_bytes(_with_info(PDF, b"<< /CreationDate (D:20990101) >>"))
    document_id = await _ingest(factory, unreachable_queue, session, tmp_path, "rota_2025.pdf")

    assert await _dated(session, document_id) == (date(2025, 1, 1), "year", "filename")


async def test_a_corrupt_pdf_info_block_falls_through_and_never_fails_the_ingest(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    unreachable_queue: Settings,
) -> None:
    (tmp_path / "rota_2025.pdf").write_bytes(_with_info(PDF, b"<< /CreationDate 42 /ModDate [ >>"))
    document_id = await _ingest(factory, unreachable_queue, session, tmp_path, "rota_2025.pdf")

    assert await _dated(session, document_id) == (date(2025, 1, 1), "year", "filename")


async def test_a_file_with_neither_is_null_never_the_ingest_date(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    unreachable_queue: Settings,
) -> None:
    for name in ("report_1234.pdf", "notes.md"):
        path = tmp_path / name
        if name.endswith(".pdf"):
            path.write_bytes(PDF)
        else:
            path.write_text("# Notes\n\nThe lease renews every spring.\n")
    await nominate(session, str(tmp_path))
    for document_id in await recorded(session, tmp_path, "report_1234.pdf", "notes.md"):
        assert await ingest.process(factory, unreachable_queue, document_id) == "parked"
        assert await _dated(session, document_id) == (None, None, None)


async def test_a_word_file_is_dated_from_its_core_properties(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    unreachable_queue: Settings,
) -> None:
    document = docx.Document()
    document.add_paragraph("Either party may terminate on ninety days written notice.")
    document.core_properties.created = datetime(2025, 1, 10, 9, 0, 0)
    document.core_properties.modified = datetime(2026, 3, 2, 10, 15, 0)
    document.save(str(tmp_path / "contract.docx"))

    document_id = await _ingest(factory, unreachable_queue, session, tmp_path, "contract.docx")

    assert await _dated(session, document_id) == (date(2026, 3, 2), "day", "metadata")


async def test_re_indexing_re_dates_a_document_including_back_to_null(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    unreachable_queue: Settings,
) -> None:
    """The backfill path: a row ingested before this ticket, or carrying a
    date that no longer holds, is re-dated by running `extract` again —
    and a document with no date now is written back to null, not left with
    the previous one."""
    (tmp_path / "Handbook.pdf").write_bytes(PDF)
    document_id = await _ingest(factory, unreachable_queue, session, tmp_path, "Handbook.pdf")
    await session.execute(
        text(
            "UPDATE documents SET document_date = '2019-01-01', "
            "document_date_precision = 'year', document_date_source = 'filename' "
            "WHERE id = :id"
        ),
        {"id": document_id},
    )
    source_id = (await session.execute(text("SELECT id FROM sources"))).scalar_one()
    reindexed = await ingest.reindex_source(session, source_id, unreachable_queue)
    await session.commit()
    assert reindexed.document_ids == [document_id]

    assert await ingest.process(factory, unreachable_queue, document_id) == "parked"
    assert await _dated(session, document_id) == (None, None, None)
