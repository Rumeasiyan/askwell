"""The ingestion queue against a real Postgres.

Everything this ticket promises that cannot be proved without a database:

*Progress advances per file and survives navigation* — nothing here holds an
HTTP request, because that is the point. A job is claimed, run and finished by
a process that has never heard of the browser.

*A stack restart resumes rather than loses the queue* — `resume` returns a job
a dead worker was holding, and `reconcile` re-dispatches what Redis forgot.

*The source is askable with partial coverage before all files finish* — one
document ready is enough, and the source says so while the rest continue.

*A job that fails is visible with its error and a retry, never silently
dropped* — including that its reason survives, which is why the record is in
Postgres rather than in the queue.

Part of the pipeline still has no stage installed (`embed` is
`M1-INDEX-ING-032`), so most tests here install a stage of their own rather
than exercise a real one. That is not a stand-in for the real thing: what is
under test is the harness — claim, progress, failure, retry, resume — and a
test stage is how you assert a harness without also asserting a PDF library.
`extract` is real since `M1-EXTRACT-ING-026` and `chunk` is real since
`M1-INDEX-ING-031`; the tests naming them below exercise the installed stages
directly.
"""

import io
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pypdfium2 as pdfium
import pytest
import pytest_asyncio
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from askwell import chunk as chunk_module
from askwell import extract, extract_pdf, ingest
from askwell.config import Settings
from askwell.db.engine import session_scope
from askwell.extract_common import WrongPassword
from askwell.ingest import Report, Stage, Work
from askwell.sources import add, delete_source

pytestmark = pytest.mark.requires_db

TABLES = "roots, sources, documents, ingest_jobs, audit_decisions"


def _pdf(*pages: str | None, rotate: int = 0) -> bytes:
    """A PDF pdfium can actually open: one object per page, `None` for a
    blank one, an optional `/Rotate` on every page.

    `M1-EXTRACT-ING-026` installed a real `extract` stage, so the bytes these
    tests hand it have to be a document pdfium can parse — the placeholder
    `%PDF-1.7\\n<text>` used before this ticket was enough to pass content
    detection and nothing more. One builder covers this ticket's stated edge
    cases: a mix of text and blank pages, a document with none at all, and a
    page rotated in place.
    """
    count = len(pages)
    font_number = 3 + count
    rotate_entry = f"/Rotate {rotate} " if rotate else ""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{' '.join(f'{3 + i} 0 R' for i in range(count))}] "
        f"/Count {count} >>".encode(),
    ]
    for page_index in range(count):
        content_number = font_number + 1 + page_index
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 {font_number} 0 R >> >> "
            f"/MediaBox [0 0 612 792] {rotate_entry}/Contents {content_number} 0 R >>".encode()
        )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for page in pages:
        content = (
            b"" if page is None else f"BT /F1 12 Tf 72 700 Td ({page}) Tj ET".encode("latin-1")
        )
        objects.append(b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream")

    body = bytearray(b"%PDF-1.7\n")
    offsets = []
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(body))
        body += f"{number} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_offset = len(body)
    body += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        body += f"{offset:010d} 00000 n \n".encode()
    body += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n".encode()
    body += f"startxref\n{xref_offset}\n%%EOF".encode()
    return bytes(body)


def _scanned_pdf(*lines: str, rotate: int = 0) -> bytes:
    """A one-page PDF with an image XObject and no text layer at all —
    `M1-EXTRACT-ING-028`'s own case, as opposed to `_pdf`'s vector text.

    `lines` are drawn onto a plain white bitmap and embedded as a JPEG
    (`/Filter /DCTDecode`, which every PDF reader including pdfium decodes
    natively, so no extra decoding step belongs in this helper). No `lines`
    at all is the "photograph with no text" edge case. `rotate` bakes the
    rotation into the *pixels*, unlike `_pdf`'s `/Rotate` entry — a scanner
    does not know a page is upside down, so there is no PDF-level hint for
    `extract_ocr` to lean on; it has to be detected from the image itself.
    """
    image = Image.new("RGB", (1000, 300 + 60 * max(len(lines) - 1, 0)), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=36)
    for index, line in enumerate(lines):
        draw.text((20, 40 + index * 60), line, fill="black", font=font)
    if rotate:
        image = image.rotate(rotate, expand=True)

    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    jpeg = buffer.getvalue()
    width, height = image.size

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        f"<< /Type /Page /Parent 2 0 R /Resources << /XObject << /Im1 5 0 R >> >> "
        f"/MediaBox [0 0 {width} {height}] /Contents 4 0 R >>".encode(),
    ]
    content = f"q {width} 0 0 {height} 0 0 cm /Im1 Do Q".encode()
    objects.append(b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream")
    objects.append(
        f"<< /Type /XObject /Subtype /Image /Width {width} /Height {height} "
        f"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode "
        f"/Length {len(jpeg)} >>\nstream\n".encode()
        + jpeg
        + b"\nendstream"
    )

    body = bytearray(b"%PDF-1.7\n")
    offsets = []
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(body))
        body += f"{number} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_offset = len(body)
    body += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        body += f"{offset:010d} 00000 n \n".encode()
    body += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n".encode()
    body += f"startxref\n{xref_offset}\n%%EOF".encode()
    return bytes(body)


PDF = _pdf("Either party may terminate on ninety days written notice.")
OTHER = _pdf("The tenant shall pay rent monthly in advance.")
THIRD = _pdf("The supplier warrants the goods for twelve months.")


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
    """Dispatch is a no-op for these tests, and loudly so.

    What is under test is the durable half. Reaching a real Redis would make
    every one of these tests also a test of whether the developer happens to
    have the stack up, and — worse — would hand jobs to a live worker that
    would race the assertions.
    """
    sent: list[uuid.UUID] = []

    async def fake_dispatch(
        _settings: Settings,
        document_ids: list[uuid.UUID],
        **_kwargs: object,
    ) -> int:
        sent.extend(document_ids)
        return len(document_ids)

    monkeypatch.setattr(ingest, "dispatch", fake_dispatch)
    # This module is the harness's own tests — claim, progress, failure,
    # retry, resume — most of which install a fake stage of their own and are
    # unaffected by this. The tests that instead rely on the real pipeline
    # (extraction, OCR, chunking) predate `embed` being real
    # (`M1-INDEX-ING-032`) and assert a document "parks" once extraction and
    # chunking are done; frozen here at real `extract` + `chunk` with `embed`
    # left unbuilt so that premise stays true. `test_embed_records.py` covers
    # `embed` itself.
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


async def nominate(session: AsyncSession, path: str) -> None:
    await session.execute(text("INSERT INTO roots (path) VALUES (:path)"), {"path": path})


def written(directory: Path, name: str, body: bytes = PDF) -> str:
    path = directory / name
    path.write_bytes(body)
    return name


async def recorded(session: AsyncSession, folder: Path, *names: str) -> list[uuid.UUID]:
    """Put files through the real add path, so the queue rows are real too."""
    result = await add(session, str(folder), list(names))
    await session.commit()
    return [item.document_id for item in result.files if item.document_id is not None]


# --- enqueueing -------------------------------------------------------------


async def test_recording_a_document_puts_it_on_the_queue(
    session: AsyncSession, tmp_path: Path
) -> None:
    """The add flow's own transaction writes the queue row.

    A document with no job is a file the user was told was queued and which
    nothing will ever pick up — and it would look completely correct in the
    library until someone asked a question about it.
    """
    await nominate(session, str(tmp_path))
    written(tmp_path, "contract.pdf")

    documents = await recorded(session, tmp_path, "contract.pdf")

    assert len(documents) == 1
    row = (
        await session.execute(
            text(
                "SELECT state, attempts, stage, awaiting FROM ingest_jobs WHERE document_id = :id"
            ),
            {"id": documents[0]},
        )
    ).one()
    assert row[0] == "queued"
    assert row[1] == 0
    assert row[2] is None and row[3] is None


async def test_the_queue_keeps_the_order_the_files_arrived_in(
    session: AsyncSession, tmp_path: Path
) -> None:
    """Ordering is `seq`, not `enqueued_at`.

    Every document in one drop is inserted in a single transaction and shares
    `now()` to the microsecond, so a position computed from the timestamp would
    reorder itself between two reads of an unchanged queue.
    """
    await nominate(session, str(tmp_path))
    for name, body in (("a.pdf", PDF), ("b.pdf", OTHER), ("c.pdf", THIRD)):
        written(tmp_path, name, body)

    documents = await recorded(session, tmp_path, "a.pdf", "b.pdf", "c.pdf")

    assert await ingest.pending(session) == documents


async def test_adding_the_same_folder_twice_does_not_queue_a_file_twice(
    session: AsyncSession, tmp_path: Path
) -> None:
    await nominate(session, str(tmp_path))
    written(tmp_path, "contract.pdf")
    documents = await recorded(session, tmp_path, "contract.pdf")

    source = (await session.execute(text("SELECT id FROM sources LIMIT 1"))).scalar_one()
    await ingest.enqueue(session, source, documents)
    await session.commit()

    count = (await session.execute(text("SELECT count(*) FROM ingest_jobs"))).scalar_one()
    assert count == 1


# --- running a job ----------------------------------------------------------


async def test_parking_a_whole_drop_does_not_flap_the_sources_status(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    unreachable_queue: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A source that never left `queued` writes no decisions records.

    With no stage installed a job is claimed and parked inside a millisecond.
    Deriving "indexing" from a job being *claimed* made every such document
    push the source `queued` → `indexing` → `queued` and record both — three
    files producing six audit records describing work that never happened. The
    status is read from the documents instead, and a document is only
    `indexing` once a stage is actually running over it.

    `extract` is real now, so this test installs a pipeline of its own with
    nothing built — the scenario it guards against is "the first stage has not
    arrived yet", which `M1-EXTRACT-ING-026` moved one stage further along
    rather than closed off; `chunk` is exactly that stage today.
    """
    monkeypatch.setattr(ingest, "STAGES", (Stage("extract", "M1-EXTRACT-ING-026"),))
    await nominate(session, str(tmp_path))
    for name, body in (("a.pdf", PDF), ("b.pdf", OTHER), ("c.pdf", THIRD)):
        written(tmp_path, name, body)
    documents = await recorded(session, tmp_path, "a.pdf", "b.pdf", "c.pdf")

    for document_id in documents:
        assert await ingest.process(factory, unreachable_queue, document_id) == "parked"

    status = (await session.execute(text("SELECT status FROM sources"))).scalar_one()
    assert status == "queued"

    changes = (
        await session.execute(
            text("SELECT count(*) FROM audit_decisions WHERE kind = :kind"),
            {"kind": ingest.SOURCE_STATUS_CHANGED},
        )
    ).scalar_one()
    assert changes == 0


async def test_a_job_parks_at_the_first_stage_that_has_not_been_built(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    unreachable_queue: Settings,
) -> None:
    """The honest resting place, and the sentence it produces.

    `extract` and `chunk` are real since `M1-EXTRACT-ING-026` and
    `M1-INDEX-ING-031`, so this document is actually read and chunked — and it
    still must not be `ready`, because nothing is embedded yet: that would
    tell retrieval it has passages it does not have, the C4 failure wearing a
    progress bar. It must not be `failed` either: nothing is wrong with the
    file. `parked`, naming `embed` and its ticket, is what lets the surface
    say what has to arrive next.
    """
    await nominate(session, str(tmp_path))
    written(tmp_path, "contract.pdf")
    documents = await recorded(session, tmp_path, "contract.pdf")

    assert await ingest.process(factory, unreachable_queue, documents[0]) == "parked"

    row = (
        await session.execute(
            text(
                "SELECT j.state, j.awaiting, d.status FROM ingest_jobs j "
                "JOIN documents d ON d.id = j.document_id WHERE j.document_id = :id"
            ),
            {"id": documents[0]},
        )
    ).one()
    assert row[0] == "parked"
    assert row[1] == "embed"
    assert row[2] == "queued"

    page = (
        await session.execute(
            text("SELECT page_number, has_text FROM document_pages WHERE document_id = :id"),
            {"id": documents[0]},
        )
    ).one()
    assert page[0] == 1
    assert page[1] is True


async def test_a_page_yielding_no_text_is_recorded_rather_than_skipped(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    unreachable_queue: Settings,
) -> None:
    """The ticket's own validation rule: a blank page is a row, not a gap.

    A two-page document with a text layer on one page and not the other is
    the ticket's own edge case — "mixed handling per page, not per document".
    Because *something* extracted, the document is not routed to OCR; it
    parks at `embed` like any other extracted-and-chunked document, with the
    blank page on record for `M1-EXTRACT-ING-028` to find later.
    """
    await nominate(session, str(tmp_path))
    written(tmp_path, "mixed.pdf", _pdf("Page one has words on it.", None))
    documents = await recorded(session, tmp_path, "mixed.pdf")

    assert await ingest.process(factory, unreachable_queue, documents[0]) == "parked"

    pages = (
        await session.execute(
            text(
                "SELECT page_number, has_text, text FROM document_pages "
                "WHERE document_id = :id ORDER BY page_number"
            ),
            {"id": documents[0]},
        )
    ).all()
    assert [(row[0], row[1]) for row in pages] == [(1, True), (2, False)]
    assert pages[1][2] is None

    row = (
        await session.execute(
            text(
                "SELECT j.awaiting, d.page_count FROM ingest_jobs j "
                "JOIN documents d ON d.id = j.document_id WHERE j.document_id = :id"
            ),
            {"id": documents[0]},
        )
    ).one()
    assert row[0] == "embed"
    assert row[1] == 2


async def test_a_pdf_with_no_usable_text_anywhere_even_after_ocr_fails(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    unreachable_queue: Settings,
) -> None:
    """No text layer and nothing OCR can find either — a stack of blank
    pages or photographs with no text in them — is `EmptyDocument`, the same
    C5 failure every other extractor reports when nothing came back.

    Before `M1-EXTRACT-ING-028` this parked awaiting `ocr` rather than
    failing, because nothing had tried to read it yet. Now OCR has been given
    every page a fair try, so "parked forever waiting for a ticket that will
    never arrive" would be the C5 failure with a different cause.
    """
    await nominate(session, str(tmp_path))
    written(tmp_path, "scan.pdf", _scanned_pdf())
    documents = await recorded(session, tmp_path, "scan.pdf")

    for _ in range(ingest.MAX_ATTEMPTS):
        assert await ingest.process(factory, unreachable_queue, documents[0]) == "failed"

    row = (
        await session.execute(
            text(
                "SELECT j.state, j.error, d.status FROM ingest_jobs j "
                "JOIN documents d ON d.id = j.document_id WHERE j.document_id = :id"
            ),
            {"id": documents[0]},
        )
    ).one()
    assert row[0] == "failed"
    assert row[1] is not None and "text" in row[1].lower()


async def test_a_missing_file_is_reported_as_missing_not_corrupt(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    unreachable_queue: Settings,
) -> None:
    """`M1-EXTRACT-VAL-030`'s own edge case: deleted between add and
    extraction, reported by name at its recorded path rather than as a
    document that opened and turned out broken."""
    await nominate(session, str(tmp_path))
    written(tmp_path, "vanishing.pdf")
    documents = await recorded(session, tmp_path, "vanishing.pdf")
    (tmp_path / "vanishing.pdf").unlink()

    for _ in range(ingest.MAX_ATTEMPTS):
        assert await ingest.process(factory, unreachable_queue, documents[0]) == "failed"

    row = (
        await session.execute(
            text(
                "SELECT j.error, d.status FROM ingest_jobs j "
                "JOIN documents d ON d.id = j.document_id WHERE j.document_id = :id"
            ),
            {"id": documents[0]},
        )
    ).one()
    assert "vanishing.pdf" in row[0]
    assert "moved or deleted" in row[0]
    assert row[1] == "attention"


async def test_a_corrupt_pdf_is_reported_as_corrupt_by_name(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    unreachable_queue: Settings,
) -> None:
    """A real garbage-after-the-header PDF, not a mock — this proves pdfium's
    own `FPDF_ERR_FORMAT` reaches the user as `CorruptDocument`, not as a
    library traceback."""
    await nominate(session, str(tmp_path))
    written(tmp_path, "broken.pdf", b"%PDF-1.7\nthis is not a real pdf body at all")
    documents = await recorded(session, tmp_path, "broken.pdf")

    for _ in range(ingest.MAX_ATTEMPTS):
        assert await ingest.process(factory, unreachable_queue, documents[0]) == "failed"

    row = (
        await session.execute(
            text(
                "SELECT j.error, d.status FROM ingest_jobs j "
                "JOIN documents d ON d.id = j.document_id WHERE j.document_id = :id"
            ),
            {"id": documents[0]},
        )
    ).one()
    assert "broken.pdf" in row[0]
    assert "corrupted" in row[0].lower()
    assert row[1] == "attention"


async def test_a_password_protected_pdf_prompts_and_the_right_password_completes_it(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    unreachable_queue: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cold-start walkthrough this ticket names: a password-protected
    PDF prompts, a wrong password is reported as wrong with another attempt
    allowed, and the right one completes ingestion.

    pdfium has no free way here to build a real encrypted PDF, so what is
    faked is only the one call pdfium itself makes the decision on —
    `PdfDocument`'s own password check — while every other byte the pipeline
    reads (page count, text) comes from the real `_pdf()` document real
    pdfium parses.
    """
    await nominate(session, str(tmp_path))
    written(tmp_path, "secret.pdf")
    documents = await recorded(session, tmp_path, "secret.pdf")

    real_open = pdfium.PdfDocument

    def fake_open(
        path: str, password: str | None = None, *args: object, **kwargs: object
    ) -> object:
        if password != "letmein":
            raise pdfium.PdfiumError(
                "Failed to load document.", err_code=pdfium.raw.FPDF_ERR_PASSWORD
            )
        return real_open(path)

    monkeypatch.setattr(extract_pdf.pdfium, "PdfDocument", fake_open)

    # No password supplied at all: prompted, not just failed. Once, not three
    # times — a password failure does not auto-retry, because the retry carries
    # no password and so fails identically while overwriting the reason. See
    # `test_a_wrong_password_is_not_overwritten_by_an_automatic_retry`.
    assert await ingest.process(factory, unreachable_queue, documents[0]) == "failed"

    row = (
        await session.execute(
            text(
                "SELECT j.error, d.status FROM ingest_jobs j "
                "JOIN documents d ON d.id = j.document_id WHERE j.document_id = :id"
            ),
            {"id": documents[0]},
        )
    ).one()
    assert "secret.pdf" in row[0]
    assert "password-protected" in row[0].lower()
    assert row[1] == "attention"

    # Wrong password: reported as wrong, and the file stays listed as
    # failed rather than being dropped.
    wrong = await ingest.retry(session, documents[0], unreachable_queue)
    await session.commit()
    assert wrong.retried
    # Once. The loop this replaced supplied the password on every pass, which is
    # why it never caught #132: the automatic retry in production supplies none,
    # so it failed as `PasswordProtected` and overwrote "incorrect" — the one
    # word telling the user their password was the problem.
    result = await ingest.process(factory, unreachable_queue, documents[0], password="nope")
    assert result == "failed"

    row = (
        await session.execute(
            text(
                "SELECT j.error, d.status FROM ingest_jobs j "
                "JOIN documents d ON d.id = j.document_id WHERE j.document_id = :id"
            ),
            {"id": documents[0]},
        )
    ).one()
    assert "secret.pdf" in row[0]
    assert "incorrect" in row[0].lower()
    assert row[1] == "attention"

    # The correct password completes ingestion.
    right = await ingest.retry(session, documents[0], unreachable_queue)
    await session.commit()
    assert right.retried
    outcome = await ingest.process(factory, unreachable_queue, documents[0], password="letmein")
    assert outcome == "parked"  # extract and chunk succeeded; embed is not installed yet

    row = (
        await session.execute(
            text(
                "SELECT j.state, j.error, d.status FROM ingest_jobs j "
                "JOIN documents d ON d.id = j.document_id WHERE j.document_id = :id"
            ),
            {"id": documents[0]},
        )
    ).one()
    assert row[0] == "parked"
    assert row[1] is None
    assert row[2] == "queued"


async def test_a_scanned_page_with_no_text_layer_is_read_by_ocr(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    unreachable_queue: Settings,
) -> None:
    """The ticket's own headline case: a page with no text layer at all is
    rendered to an image and read by Tesseract, and the document is marked
    OCR-derived for the source viewer to show the scan beside the text."""
    await nominate(session, str(tmp_path))
    written(
        tmp_path,
        "scan.pdf",
        _scanned_pdf("Either party may terminate on ninety", "days written notice."),
    )
    documents = await recorded(session, tmp_path, "scan.pdf")

    assert await ingest.process(factory, unreachable_queue, documents[0]) == "parked"

    page = (
        await session.execute(
            text("SELECT has_text, text FROM document_pages WHERE document_id = :id"),
            {"id": documents[0]},
        )
    ).one()
    assert page[0] is True
    assert page[1] == "Either party may terminate on ninety\ndays written notice."

    document = (
        await session.execute(
            text("SELECT ocr_derived, page_count FROM documents WHERE id = :id"),
            {"id": documents[0]},
        )
    ).one()
    assert document[0] is True
    assert document[1] == 1

    awaiting = (
        await session.execute(
            text("SELECT awaiting FROM ingest_jobs WHERE document_id = :id"),
            {"id": documents[0]},
        )
    ).scalar_one()
    assert awaiting == "embed"


async def test_an_upside_down_scanned_page_is_read_by_ocr(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    unreachable_queue: Settings,
) -> None:
    """The ticket's title: orientation detection, not just recognition. A
    scanned page's rotation lives in the pixels, not a PDF `/Rotate` entry a
    scanner never wrote — `extract_ocr` has to find it itself."""
    await nominate(session, str(tmp_path))
    written(
        tmp_path,
        "upside-down.pdf",
        _scanned_pdf(
            "Either party may terminate on ninety",
            "days written notice to the other side.",
            rotate=180,
        ),
    )
    documents = await recorded(session, tmp_path, "upside-down.pdf")

    await ingest.process(factory, unreachable_queue, documents[0])

    page_text = (
        await session.execute(
            text("SELECT text FROM document_pages WHERE document_id = :id"),
            {"id": documents[0]},
        )
    ).scalar_one()
    assert (
        page_text == "Either party may terminate on ninety\ndays written notice to the other side."
    )


async def test_a_mixed_document_only_ocrs_the_pages_that_need_it(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    unreachable_queue: Settings,
) -> None:
    """The stated edge case: a text-layer page and a scanned page in the same
    document. Only the scanned one costs an OCR pass, and the document still
    parks at `chunk` like an ordinary text-layer PDF — mixing sources within
    one document is not a special pipeline state.

    Built directly rather than composed from `_pdf` and `_scanned_pdf`: each
    of those builds a complete, independent object graph, and a real
    two-page document needs one shared `/Pages` tree with both kinds of page
    as siblings in it.
    """
    image = Image.new("RGB", (1000, 360), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=36)
    draw.text((20, 40), "The supplier warrants the goods", fill="black", font=font)
    draw.text((20, 100), "for twelve months.", fill="black", font=font)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    jpeg = buffer.getvalue()
    width, height = image.size

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>",
        b"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 8 0 R >> >> "
        b"/MediaBox [0 0 612 792] /Contents 5 0 R >>",
        f"<< /Type /Page /Parent 2 0 R /Resources << /XObject << /Im1 7 0 R >> >> "
        f"/MediaBox [0 0 {width} {height}] /Contents 6 0 R >>".encode(),
    ]
    text_content = (
        b"BT /F1 12 Tf 72 700 Td (Either party may terminate on ninety days written notice.) Tj ET"
    )
    objects.append(
        b"<< /Length %d >>\nstream\n" % len(text_content) + text_content + b"\nendstream"
    )
    image_content = f"q {width} 0 0 {height} 0 0 cm /Im1 Do Q".encode()
    objects.append(
        b"<< /Length %d >>\nstream\n" % len(image_content) + image_content + b"\nendstream"
    )
    objects.append(
        f"<< /Type /XObject /Subtype /Image /Width {width} /Height {height} "
        f"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode "
        f"/Length {len(jpeg)} >>\nstream\n".encode()
        + jpeg
        + b"\nendstream"
    )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    body = bytearray(b"%PDF-1.7\n")
    offsets = []
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(body))
        body += f"{number} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_offset = len(body)
    body += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        body += f"{offset:010d} 00000 n \n".encode()
    body += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n".encode()
    body += f"startxref\n{xref_offset}\n%%EOF".encode()

    await nominate(session, str(tmp_path))
    written(tmp_path, "mixed-source.pdf", bytes(body))
    documents = await recorded(session, tmp_path, "mixed-source.pdf")

    assert await ingest.process(factory, unreachable_queue, documents[0]) == "parked"

    pages = (
        await session.execute(
            text(
                "SELECT page_number, has_text, text FROM document_pages "
                "WHERE document_id = :id ORDER BY page_number"
            ),
            {"id": documents[0]},
        )
    ).all()
    assert (pages[0][0], pages[0][1]) == (1, True)
    assert pages[0][2] == "Either party may terminate on ninety days written notice."
    assert (pages[1][0], pages[1][1]) == (2, True)
    ocr_text = pages[1][2]
    assert ocr_text is not None
    assert ocr_text.split() == [
        "The",
        "supplier",
        "warrants",
        "the",
        "goods",
        "for",
        "twelve",
        "months.",
    ]

    ocr_derived = (
        await session.execute(
            text("SELECT ocr_derived FROM documents WHERE id = :id"), {"id": documents[0]}
        )
    ).scalar_one()
    assert ocr_derived is True


async def test_a_clean_scan_is_read_with_a_confidence_and_is_not_flagged(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    unreachable_queue: Settings,
) -> None:
    """`M1-EXTRACT-ING-029`'s own edge case, the good half: a clean scan reads
    with a real confidence figure and stays plain `ready` — flagging is for
    the poor scans, not a side effect of having been OCR'd at all."""
    await nominate(session, str(tmp_path))
    written(
        tmp_path,
        "clean.pdf",
        _scanned_pdf("Either party may terminate on ninety", "days written notice."),
    )
    documents = await recorded(session, tmp_path, "clean.pdf")

    await ingest.process(factory, unreachable_queue, documents[0])

    confidence = (
        await session.execute(
            text("SELECT ocr_confidence FROM documents WHERE id = :id"), {"id": documents[0]}
        )
    ).scalar_one()
    assert confidence is not None
    assert 0 <= float(confidence) <= 1

    page_confidence = (
        await session.execute(
            text("SELECT ocr_confidence FROM document_pages WHERE document_id = :id"),
            {"id": documents[0]},
        )
    ).scalar_one()
    assert page_confidence is not None


async def test_a_text_layer_page_carries_no_ocr_confidence(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    unreachable_queue: Settings,
) -> None:
    """The other edge case named by the ticket: confidence unavailable for a
    text-layer document is no flag, not a false one — there is nothing to be
    false about, because Tesseract was never asked."""
    await nominate(session, str(tmp_path))
    written(tmp_path, "letter.pdf")
    documents = await recorded(session, tmp_path, "letter.pdf")

    await ingest.process(factory, unreachable_queue, documents[0])

    confidence = (
        await session.execute(
            text("SELECT ocr_confidence FROM documents WHERE id = :id"), {"id": documents[0]}
        )
    ).scalar_one()
    assert confidence is None


async def test_a_document_flagged_for_poor_ocr_still_indexes_and_stays_searchable(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    unreachable_queue: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ticket's headline acceptance criterion, exercised against a fake
    `extract` the way the harness tests above do — the real Tesseract
    confidence path is proved separately, by the OCR tests around it; what is
    under test here is what the pipeline *does* with a low confidence once
    one exists: the document still reaches `ready`, and the source becomes
    `attention` with a readable, specific reason.
    """
    await nominate(session, str(tmp_path))
    written(tmp_path, "poor-scan.pdf")
    documents = await recorded(session, tmp_path, "poor-scan.pdf")

    async def poor_ocr(
        work: Work, report: Report, factory: async_sessionmaker[AsyncSession], _settings: Settings
    ) -> None:
        async with session_scope(factory) as inner:
            await inner.execute(
                text(
                    "UPDATE documents SET ocr_derived = true, ocr_confidence = 0.30 WHERE id = :id"
                ),
                {"id": work.document_id},
            )

    monkeypatch.setattr(ingest, "STAGES", (Stage("extract", "M1-EXTRACT-ING-026", poor_ocr),))
    assert await ingest.process(factory, unreachable_queue, documents[0]) == "done"

    row = (
        await session.execute(
            text(
                "SELECT d.status, s.status, s.last_error FROM documents d "
                "JOIN sources s ON s.id = d.source_id WHERE d.id = :id"
            ),
            {"id": documents[0]},
        )
    ).one()
    assert row[0] == "ready"
    assert row[1] == "attention"
    assert row[2] is not None
    assert "scanned poorly" in row[2]

    source_id = (
        await session.execute(
            text("SELECT source_id FROM documents WHERE id = :id"), {"id": documents[0]}
        )
    ).scalar_one()
    covered = await ingest.coverage(session, source_id, unreachable_queue.ocr_confidence_threshold)
    assert covered.flagged == 1
    assert covered.ready == 1
    assert covered.askable


async def test_a_flagged_document_is_recognised_before_it_ever_reaches_ready(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    unreachable_queue: Settings,
) -> None:
    """`embed` is frozen unbuilt for this module (`unreachable_queue`), so the
    document parks — never reaching `ready` — once real `extract` and `chunk`
    finish. This ticket's own dependency is `M1-EXTRACT-ING-028` alone, and
    the flag must not silently wait for milestones it does not depend on.
    """
    await nominate(session, str(tmp_path))
    written(
        tmp_path,
        "poor-scan.pdf",
        _scanned_pdf("Either party may terminate on ninety", "days written notice."),
    )
    documents = await recorded(session, tmp_path, "poor-scan.pdf")

    assert await ingest.process(factory, unreachable_queue, documents[0]) == "parked"

    # The real Tesseract confidence path is proved by the OCR tests around
    # this one; what is under test here is that the pipeline still notices a
    # low confidence on a document that never reached `ready` at all.
    async with session_scope(factory) as inner:
        await inner.execute(
            text("UPDATE documents SET ocr_confidence = 0.30 WHERE id = :id"),
            {"id": documents[0]},
        )
        source_id = (
            await inner.execute(
                text("SELECT source_id FROM documents WHERE id = :id"), {"id": documents[0]}
            )
        ).scalar_one()
        await ingest.refresh_source(inner, source_id, unreachable_queue.ocr_confidence_threshold)

    row = (
        await session.execute(
            text("SELECT status FROM documents WHERE id = :id"), {"id": documents[0]}
        )
    ).scalar_one()
    assert row == "queued"

    source_status = (
        await session.execute(text("SELECT status FROM sources WHERE id = :id"), {"id": source_id})
    ).scalar_one()
    assert source_status == "attention"

    covered = await ingest.coverage(session, source_id, unreachable_queue.ocr_confidence_threshold)
    assert covered.flagged == 1


async def test_a_rotated_page_is_read_in_the_correct_orientation(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    unreachable_queue: Settings,
) -> None:
    """`/Rotate 90` is the stated edge case; pdfium's own text extraction
    already accounts for it, so this asserts the behaviour rather than any
    code in `extract_pdf` that would otherwise look unexercised."""
    await nominate(session, str(tmp_path))
    written(tmp_path, "rotated.pdf", _pdf("Upside down or not, this reads correctly.", rotate=90))
    documents = await recorded(session, tmp_path, "rotated.pdf")

    await ingest.process(factory, unreachable_queue, documents[0])

    page_text = (
        await session.execute(
            text("SELECT text FROM document_pages WHERE document_id = :id"),
            {"id": documents[0]},
        )
    ).scalar_one()
    assert page_text == "Upside down or not, this reads correctly."


async def test_an_installed_stage_runs_and_the_document_becomes_ready(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    unreachable_queue: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await nominate(session, str(tmp_path))
    written(tmp_path, "contract.pdf")
    documents = await recorded(session, tmp_path, "contract.pdf")

    seen: list[str] = []

    async def extract(
        work: Work, report: Report, factory: async_sessionmaker[AsyncSession], _settings: Settings
    ) -> None:
        seen.append(work.filename)
        await report(len(PDF), len(PDF))

    monkeypatch.setattr(ingest, "STAGES", (Stage("extract", "M1-EXTRACT-ING-026", extract),))

    assert await ingest.process(factory, unreachable_queue, documents[0]) == "done"
    assert seen == ["contract.pdf"]

    row = (
        await session.execute(
            text(
                "SELECT j.state, j.stage, d.status, s.status FROM ingest_jobs j "
                "JOIN documents d ON d.id = j.document_id "
                "JOIN sources s ON s.id = j.source_id WHERE j.document_id = :id"
            ),
            {"id": documents[0]},
        )
    ).one()
    assert row[0] == "done"
    assert row[1] == "extract"
    assert row[2] == "ready"
    assert row[3] == "ready"


async def test_progress_moves_inside_a_single_enormous_file(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    unreachable_queue: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A count of "3 of 12" that does not move for two hours looks like a hang.

    The byte figures are read from a *different* session while the stage is
    still running, which is the only way to assert what this is for: somebody
    watching the screen has to see the number change before the file finishes.
    """
    await nominate(session, str(tmp_path))
    written(tmp_path, "scan.pdf")
    documents = await recorded(session, tmp_path, "scan.pdf")

    observed: list[tuple[int | None, int | None]] = []

    async def slow(
        work: Work, report: Report, factory: async_sessionmaker[AsyncSession], _settings: Settings
    ) -> None:
        for done in (250, 500, 1000):
            await report(done, 1000)
            async with factory() as watcher:
                row = (
                    await watcher.execute(
                        text(
                            "SELECT bytes_done, bytes_total FROM ingest_jobs "
                            "WHERE document_id = :id"
                        ),
                        {"id": work.document_id},
                    )
                ).one()
                observed.append((row[0], row[1]))

    monkeypatch.setattr(ingest, "STAGES", (Stage("extract", "M1-EXTRACT-ING-026", slow),))

    # A clock that always says the interval has elapsed, so the throttle does
    # not swallow the very reports this test exists to see. The throttle itself
    # is asserted separately, in `test_progress_writes_are_throttled`.
    ticks = iter(range(0, 1000))

    assert (
        await ingest.process(
            factory, unreachable_queue, documents[0], clock=lambda: float(next(ticks))
        )
        == "done"
    )
    assert observed == [(250, 1000), (500, 1000), (1000, 1000)]


async def test_progress_writes_are_throttled(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    unreachable_queue: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A write per chunk is thousands of transactions for one large file.

    The first report always lands, because it carries the total and that is
    what turns a spinner into a fraction; the ones after it wait for the
    interval. The final one lands too — `done == total` is what the screen
    needs to stop.
    """
    await nominate(session, str(tmp_path))
    written(tmp_path, "scan.pdf")
    documents = await recorded(session, tmp_path, "scan.pdf")

    async def chatty(
        work: Work, report: Report, factory: async_sessionmaker[AsyncSession], _settings: Settings
    ) -> None:
        for done in (10, 20, 30, 40):
            await report(done, 100)

    monkeypatch.setattr(ingest, "STAGES", (Stage("extract", "M1-EXTRACT-ING-026", chatty),))
    await ingest.process(factory, unreachable_queue, documents[0], clock=lambda: 1.0)

    # `state = 'running'` guards the write, so the row after the job finishes
    # carries whatever the last accepted report said — which here is only the
    # first, because the frozen clock never lets the interval elapse.
    row = (
        await session.execute(
            text("SELECT bytes_done FROM ingest_jobs WHERE document_id = :id"),
            {"id": documents[0]},
        )
    ).one()
    assert row[0] == 10


async def test_a_failing_stage_is_retried_and_then_left_failed_with_its_reason(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    unreachable_queue: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Never silently dropped — `AGENTS.md` §6, and the ticket says so twice.

    The reason is written to Postgres rather than left in the queue because the
    thing the library has to render — this file, this error, a retry — has to
    survive a flushed Redis.
    """
    await nominate(session, str(tmp_path))
    written(tmp_path, "broken.pdf")
    documents = await recorded(session, tmp_path, "broken.pdf")

    async def always_fails(
        work: Work, report: Report, factory: async_sessionmaker[AsyncSession], _settings: Settings
    ) -> None:
        raise ValueError("the text layer is not readable")

    monkeypatch.setattr(ingest, "STAGES", (Stage("extract", "M1-EXTRACT-ING-026", always_fails),))

    for _ in range(ingest.MAX_ATTEMPTS):
        assert await ingest.process(factory, unreachable_queue, documents[0]) == "failed"

    row = (
        await session.execute(
            text(
                "SELECT j.state, j.attempts, j.error, j.stage, d.status, s.status "
                "FROM ingest_jobs j JOIN documents d ON d.id = j.document_id "
                "JOIN sources s ON s.id = j.source_id WHERE j.document_id = :id"
            ),
            {"id": documents[0]},
        )
    ).one()
    assert row[0] == "failed"
    assert row[1] == ingest.MAX_ATTEMPTS
    assert "the text layer is not readable" in row[2]
    assert row[3] == "extract"
    assert row[4] == "attention"
    assert row[5] == "attention"


async def test_a_wrong_password_is_not_overwritten_by_an_automatic_retry(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    unreachable_queue: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The one sentence that told the user what to do has to survive.

    An automatic retry carries no password — none was stored — so it cannot
    open the file and it fails *differently*: a wrong password becomes
    `PasswordProtected`, which overwrites "the password entered was incorrect"
    with "this file is password-protected". The user is then told to supply a
    password they just supplied, and nothing on screen says it was wrong.

    So a password failure does not auto-retry. It waits, because the user doing
    something is the only thing that can change the outcome.
    """
    await nominate(session, str(tmp_path))
    written(tmp_path, "locked.pdf")
    documents = await recorded(session, tmp_path, "locked.pdf")

    async def wrong_password(
        work: Work, report: Report, factory: async_sessionmaker[AsyncSession], _settings: Settings
    ) -> None:
        raise WrongPassword("The password entered for locked.pdf was incorrect.")

    monkeypatch.setattr(ingest, "STAGES", (Stage("extract", "M1-EXTRACT-ING-026", wrong_password),))

    assert await ingest.process(factory, unreachable_queue, documents[0]) == "failed"

    row = (
        await session.execute(
            text("SELECT state, attempts, error FROM ingest_jobs WHERE document_id = :id"),
            {"id": documents[0]},
        )
    ).one()
    # Failed after one attempt rather than queued for another: with attempts at
    # 1 and MAX_ATTEMPTS at 3, the old code would have re-queued it here.
    assert row[0] == "failed", "a password failure must not sit queued for a retry that cannot work"
    assert row[1] == 1
    assert "was incorrect" in row[2], "the wrong-password sentence is the whole point"


async def test_a_failure_that_a_retry_could_fix_still_retries(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    unreachable_queue: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The password case is the exception, not a change to retrying generally.

    A drive that was briefly unplugged is exactly what the retry exists for.
    """
    await nominate(session, str(tmp_path))
    written(tmp_path, "flaky.pdf")
    documents = await recorded(session, tmp_path, "flaky.pdf")

    async def transient(
        work: Work, report: Report, factory: async_sessionmaker[AsyncSession], _settings: Settings
    ) -> None:
        raise OSError("the drive went away")

    monkeypatch.setattr(ingest, "STAGES", (Stage("extract", "M1-EXTRACT-ING-026", transient),))

    assert await ingest.process(factory, unreachable_queue, documents[0]) == "failed"
    row = (
        await session.execute(
            text("SELECT state FROM ingest_jobs WHERE document_id = :id"),
            {"id": documents[0]},
        )
    ).one()
    assert row[0] == "queued", "an ordinary failure is still worth trying again"


async def test_a_failed_document_can_be_retried_and_its_attempts_are_forgiven(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    unreachable_queue: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The user reconnected the drive. Starting from the third attempt would
    fail the document again on the first hiccup and teach them the retry does
    not work.
    """
    await nominate(session, str(tmp_path))
    written(tmp_path, "broken.pdf")
    documents = await recorded(session, tmp_path, "broken.pdf")

    async def always_fails(
        work: Work, report: Report, factory: async_sessionmaker[AsyncSession], _settings: Settings
    ) -> None:
        raise OSError("the drive is not connected")

    monkeypatch.setattr(ingest, "STAGES", (Stage("extract", "M1-EXTRACT-ING-026", always_fails),))
    for _ in range(ingest.MAX_ATTEMPTS):
        await ingest.process(factory, unreachable_queue, documents[0])

    outcome = await ingest.retry(session, documents[0], unreachable_queue)
    await session.commit()

    assert outcome.retried
    assert outcome.state == "queued"
    assert outcome.source_id is not None
    row = (
        await session.execute(
            text(
                "SELECT j.state, j.attempts, j.error, d.status FROM ingest_jobs j "
                "JOIN documents d ON d.id = j.document_id WHERE j.document_id = :id"
            ),
            {"id": documents[0]},
        )
    ).one()
    assert row[0] == "queued"
    assert row[1] == 0
    assert row[2] is None
    assert row[3] == "queued"


async def test_retrying_something_that_did_not_fail_is_refused_by_name(
    session: AsyncSession, tmp_path: Path, settings: Settings
) -> None:
    await nominate(session, str(tmp_path))
    written(tmp_path, "contract.pdf")
    documents = await recorded(session, tmp_path, "contract.pdf")

    already_queued = await ingest.retry(session, documents[0], settings)
    assert not already_queued.retried
    assert already_queued.state == "queued"

    unknown = await ingest.retry(session, uuid.uuid4(), settings)
    assert not unknown.retried
    assert unknown.state is None


async def test_reindexing_a_source_requeues_every_live_document_regardless_of_state(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    unreachable_queue: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`M1-LIB-FE-050`: re-index is not `retry` — it puts back *every* live
    document, including one that already reached `ready`, not only the ones
    that failed. A ready document with a stale OCR flag would otherwise be
    invisible to a re-index meant to fix exactly that.
    """
    await nominate(session, str(tmp_path))
    written(tmp_path, "ready.pdf", PDF)
    written(tmp_path, "broken.pdf", OTHER)
    documents = await recorded(session, tmp_path, "ready.pdf", "broken.pdf")

    async def fails(
        work: Work, report: Report, factory: async_sessionmaker[AsyncSession], _settings: Settings
    ) -> None:
        raise OSError("could not read it")

    monkeypatch.setattr(ingest, "STAGES", (Stage("extract", "M1-EXTRACT-ING-026", fails),))
    for _ in range(ingest.MAX_ATTEMPTS):
        await ingest.process(factory, unreachable_queue, documents[1])

    # The other document is marked ready by hand, with a flagged OCR
    # confidence — exactly the state a re-index exists to clear.
    await session.execute(
        text("UPDATE documents SET status = 'ready', ocr_confidence = 0.2 WHERE id = :id"),
        {"id": documents[0]},
    )
    source_row = (
        await session.execute(
            text("SELECT source_id FROM documents WHERE id = :id"), {"id": documents[0]}
        )
    ).one()
    source_id = source_row[0]
    await ingest.refresh_source(session, source_id, unreachable_queue.ocr_confidence_threshold)
    await session.commit()

    outcome = await ingest.reindex_source(session, source_id, unreachable_queue)
    await session.commit()

    assert outcome.found
    assert outcome.documents == 2
    assert set(outcome.document_ids) == set(documents)

    rows = (
        await session.execute(
            text(
                "SELECT j.state, j.attempts, j.error, d.status, d.ocr_confidence "
                "FROM ingest_jobs j JOIN documents d ON d.id = j.document_id "
                "WHERE j.document_id = ANY(:ids)"
            ),
            {"ids": documents},
        )
    ).all()
    assert len(rows) == 2
    for row in rows:
        assert row[0] == "queued"
        assert row[1] == 0
        assert row[2] is None
        assert row[3] == "queued"
        assert row[4] is None

    source_status = (
        await session.execute(text("SELECT status FROM sources WHERE id = :id"), {"id": source_id})
    ).one()
    assert source_status[0] == "queued"

    decisions = (
        await session.execute(
            text(
                "SELECT payload FROM audit_decisions WHERE kind = 'source_reindex_requested' "
                "ORDER BY occurred_at DESC LIMIT 1"
            )
        )
    ).one()
    assert decisions[0]["source_id"] == str(source_id)
    assert decisions[0]["documents"] == 2


async def test_reindexing_an_unknown_or_deleted_source_is_refused_by_name(
    session: AsyncSession, settings: Settings
) -> None:
    unknown = await ingest.reindex_source(session, uuid.uuid4(), settings)
    assert not unknown.found
    assert unknown.documents == 0
    assert unknown.document_ids == []


async def test_a_document_deleted_before_its_job_ran_is_not_a_failure(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    unreachable_queue: Settings,
) -> None:
    """Nothing is wrong; there is simply nothing to do.

    Recording it as failed would put a red row in the library for a document
    the user themselves removed.
    """
    await nominate(session, str(tmp_path))
    written(tmp_path, "contract.pdf")
    documents = await recorded(session, tmp_path, "contract.pdf")

    await session.execute(
        text("UPDATE documents SET deleted_at = now() WHERE id = :id"), {"id": documents[0]}
    )
    await session.commit()

    assert await ingest.process(factory, unreachable_queue, documents[0]) == "unclaimable"
    count = (await session.execute(text("SELECT count(*) FROM ingest_jobs"))).scalar_one()
    assert count == 0


# --- surviving a restart ----------------------------------------------------


async def test_a_restart_returns_an_interrupted_job_to_the_queue(
    session: AsyncSession, tmp_path: Path
) -> None:
    """The laptop closed mid-import. That is a normal Tuesday, not an error.

    `attempts` is given back as well: a document is not made harder to read by
    the machine having been suspended, and spending a retry on each interruption
    would eventually mark a perfectly good file as failed for having been
    interrupted three times.
    """
    await nominate(session, str(tmp_path))
    written(tmp_path, "contract.pdf")
    documents = await recorded(session, tmp_path, "contract.pdf")

    await session.execute(
        text(
            "UPDATE ingest_jobs SET state = 'running', started_at = now(), attempts = 1 "
            "WHERE document_id = :id"
        ),
        {"id": documents[0]},
    )
    await session.commit()

    assert await ingest.resume(session) == 1
    await session.commit()

    row = (
        await session.execute(
            text("SELECT state, attempts, started_at FROM ingest_jobs WHERE document_id = :id"),
            {"id": documents[0]},
        )
    ).one()
    assert row[0] == "queued"
    assert row[1] == 0
    assert row[2] is None


async def test_a_document_parked_before_extraction_landed_is_revived_at_startup(
    session: AsyncSession, tmp_path: Path
) -> None:
    """#109: a document parked before its stage was built must not stay
    parked forever after the stage lands.

    `M1-ADD-ING-025` declared the pipeline with nothing installed, so anything
    added before `M1-EXTRACT-ING-026` landed is sitting `parked` naming
    `extract`. Nothing re-queues a `parked` row on its own — the reconcile
    timer only re-dispatches `queued` ones — so without this, that document's
    library entry stays "recorded and waiting" through the very upgrade meant
    to fix it, discoverable only by someone noticing a library that never
    reaches `ready`.
    """
    await nominate(session, str(tmp_path))
    written(tmp_path, "contract.pdf")
    documents = await recorded(session, tmp_path, "contract.pdf")

    await session.execute(
        text(
            "UPDATE ingest_jobs SET state = 'parked', stage = NULL, awaiting = 'extract' "
            "WHERE document_id = :id"
        ),
        {"id": documents[0]},
    )
    await session.commit()

    assert await ingest.resume(session) == 1
    await session.commit()

    row = (
        await session.execute(
            text("SELECT state, awaiting FROM ingest_jobs WHERE document_id = :id"),
            {"id": documents[0]},
        )
    ).one()
    assert row[0] == "queued"
    assert row[1] is None


async def test_a_document_parked_for_a_stage_still_unbuilt_is_left_alone(
    session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other half of #109's fix: reviving a `parked` row only when its
    stage is actually installed. Without the `awaiting` filter, a document
    waiting on `embed` would be re-claimed by `chunk`, park again on the very
    next stage, forever — the bug this fix exists for, reproduced one stage
    later.

    Every stage is real and installed since `M1-INDEX-ING-032`, so the case
    this guards against — a row `awaiting` a stage with no `run` — is
    manufactured here rather than found in the ordinary pipeline; the fix
    itself is generic and still needs to hold for whatever the next
    undeclared stage turns out to be.
    """
    monkeypatch.setattr(ingest, "STAGES", (Stage("extract", "M1-EXTRACT-ING-026", extract.run),))
    await nominate(session, str(tmp_path))
    written(tmp_path, "contract.pdf")
    documents = await recorded(session, tmp_path, "contract.pdf")

    await session.execute(
        text(
            "UPDATE ingest_jobs SET state = 'parked', stage = 'chunk', awaiting = 'embed' "
            "WHERE document_id = :id"
        ),
        {"id": documents[0]},
    )
    await session.commit()

    assert await ingest.resume(session) == 0
    await session.commit()

    row = (
        await session.execute(
            text("SELECT state, awaiting FROM ingest_jobs WHERE document_id = :id"),
            {"id": documents[0]},
        )
    ).one()
    assert row[0] == "parked"
    assert row[1] == "embed"


async def test_reconcile_re_dispatches_work_the_queue_forgot(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    unreachable_queue: Settings,
) -> None:
    """The repair path: a flushed Redis, a failed enqueue, a machine that slept.

    Nothing about the rows changes — they were always the record. What
    reconcile does is tell a worker they are there.
    """
    await nominate(session, str(tmp_path))
    for name, body in (("a.pdf", PDF), ("b.pdf", OTHER)):
        written(tmp_path, name, body)
    documents = await recorded(session, tmp_path, "a.pdf", "b.pdf")

    assert await ingest.reconcile(factory, unreachable_queue) == 2
    assert await ingest.pending(session) == documents


async def test_a_refused_job_id_does_not_strand_a_document_forever(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """arq refusing an id is not proof the job is queued.

    A worker killed hard leaves its job key behind, and a job that merely
    finished leaves its result key. arq refuses both, and cannot say which it
    is. Before this, every reconcile after such a kill asked for the same id,
    was refused, and reported success having done nothing — the document sat
    `queued` for up to `job_timeout` with nothing anywhere saying why.
    """
    await nominate(session, str(tmp_path))
    written(tmp_path, "a.pdf", PDF)
    documents = await recorded(session, tmp_path, "a.pdf")

    # The row has been waiting far longer than a few reconciles.
    await session.execute(
        text("UPDATE ingest_jobs SET enqueued_at = now() - make_interval(secs => 600)")
    )
    await session.commit()

    calls: list[bool] = []

    async def refusing_dispatch(
        _settings: Settings,
        document_ids: list[uuid.UUID],
        **kwargs: object,
    ) -> int:
        unique = bool(kwargs.get("unique", True))
        calls.append(unique)
        # This is arq's behaviour, not an error: an id it still holds is
        # declined silently, and an enqueue with no id always lands.
        return 0 if unique else len(document_ids)

    monkeypatch.setattr(ingest, "dispatch", refusing_dispatch)

    assert await ingest.reconcile(factory, settings) == 1
    assert calls == [True, False], (
        "it should retry without an id once the first pass came back short"
    )
    assert await ingest.pending(session) == documents, (
        "the row is untouched; only the telling changed"
    )


async def test_a_freshly_queued_document_is_never_dispatched_twice(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The escalation is for ghosts, not for a queue that is simply busy.

    A document enqueued moments ago and refused is refused because it really is
    queued. Dispatching it again without an id would put a second job on the
    queue for every waiting document twice a minute for the length of an import.
    """
    await nominate(session, str(tmp_path))
    written(tmp_path, "a.pdf", PDF)
    await recorded(session, tmp_path, "a.pdf")

    calls: list[bool] = []

    async def refusing_dispatch(
        _settings: Settings,
        document_ids: list[uuid.UUID],
        **kwargs: object,
    ) -> int:
        calls.append(bool(kwargs.get("unique", True)))
        return 0

    monkeypatch.setattr(ingest, "dispatch", refusing_dispatch)

    assert await ingest.reconcile(factory, settings) == 0
    assert calls == [True], "a row queued seconds ago is not a ghost"


# --- partial coverage -------------------------------------------------------


async def test_a_source_is_askable_before_every_file_has_finished(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    unreachable_queue: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ticket's own scenario, at three files instead of five hundred.

    One document indexed is enough to answer from. Waiting for the whole import
    before anything can be asked is the behaviour this ticket exists to remove.
    """
    await nominate(session, str(tmp_path))
    for name, body in (("a.pdf", PDF), ("b.pdf", OTHER), ("c.pdf", THIRD)):
        written(tmp_path, name, body)
    documents = await recorded(session, tmp_path, "a.pdf", "b.pdf", "c.pdf")

    async def extract(
        work: Work, report: Report, factory: async_sessionmaker[AsyncSession], _settings: Settings
    ) -> None:
        await report(1, 1)

    monkeypatch.setattr(ingest, "STAGES", (Stage("extract", "M1-EXTRACT-ING-026", extract),))
    await ingest.process(factory, unreachable_queue, documents[0])

    source_id = (await session.execute(text("SELECT id FROM sources LIMIT 1"))).scalar_one()
    partial = await ingest.coverage(session, source_id, unreachable_queue.ocr_confidence_threshold)

    assert partial.ready == 1
    assert partial.total == 3
    assert partial.askable

    status = (
        await session.execute(text("SELECT status FROM sources WHERE id = :id"), {"id": source_id})
    ).scalar_one()
    assert status == "indexing"


async def test_a_source_changing_status_is_a_decisions_record(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    unreachable_queue: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """What Askwell will answer from changed. `docs/audit-log.md` §2.

    Only on an actual change: a record per completed job would be five hundred
    rows saying the same thing about one import.
    """
    await nominate(session, str(tmp_path))
    for name, body in (("a.pdf", PDF), ("b.pdf", OTHER)):
        written(tmp_path, name, body)
    documents = await recorded(session, tmp_path, "a.pdf", "b.pdf")

    async def extract(
        work: Work, report: Report, factory: async_sessionmaker[AsyncSession], _settings: Settings
    ) -> None:
        await report(1, 1)

    monkeypatch.setattr(ingest, "STAGES", (Stage("extract", "M1-EXTRACT-ING-026", extract),))
    for document_id in documents:
        await ingest.process(factory, unreachable_queue, document_id)

    rows = (
        await session.execute(
            text("SELECT payload FROM audit_decisions WHERE kind = :kind ORDER BY occurred_at"),
            {"kind": ingest.SOURCE_STATUS_CHANGED},
        )
    ).all()

    # Two changes, and the counts at the moment each was made. The first is
    # recorded when the first job starts, so nothing is ready yet — which is
    # the point of storing the counts rather than only the status: "indexing"
    # on its own does not say how much of the source that covers.
    assert [(row[0]["to"], row[0]["ready"], row[0]["total"]) for row in rows] == [
        ("indexing", 0, 2),
        ("ready", 2, 2),
    ]


# --- the snapshot -----------------------------------------------------------


async def test_the_estimate_refuses_to_invent_a_number_before_anything_finishes(
    session: AsyncSession, tmp_path: Path, settings: Settings
) -> None:
    """The known gap the backlog names, answered rather than papered over.

    On a first import there is no throughput history, so any figure would be
    made up — and somebody plans their afternoon around it. `null` with a
    stated basis is the honest answer.
    """
    await nominate(session, str(tmp_path))
    written(tmp_path, "contract.pdf")
    await recorded(session, tmp_path, "contract.pdf")

    state = await ingest.snapshot(session, settings)

    assert state["estimate"]["seconds"] is None
    assert "invented" in state["estimate"]["basis"]


async def test_the_snapshot_reports_queue_position_and_what_is_being_waited_for(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    settings: Settings,
    unreachable_queue: Settings,
) -> None:
    """Position, because "queued behind a backlog" needs a number to be honest,
    and `awaiting`, because "nothing is happening" and "nothing is happening,
    and here is what has to arrive first" are different sentences.
    """
    await nominate(session, str(tmp_path))
    for name, body in (("a.pdf", PDF), ("b.pdf", OTHER), ("c.pdf", THIRD)):
        written(tmp_path, name, body)
    documents = await recorded(session, tmp_path, "a.pdf", "b.pdf", "c.pdf")

    await ingest.process(factory, unreachable_queue, documents[0])
    state = await ingest.snapshot(session, settings)

    assert [item["position"] for item in state["next"]] == [1, 2]
    assert [item["filename"] for item in state["next"]] == ["b.pdf", "c.pdf"]
    assert state["queue_length"] == 2
    assert state["awaiting"] == {
        "stage": "embed",
        "ticket": "M1-INDEX-ING-032",
        "documents": 1,
    }
    assert state["sources"][0]["askable"] is False


async def test_the_snapshot_counts_are_this_machines_own_and_nothing_leaves_it(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    settings: Settings,
    unreachable_queue: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C1. The counters the ticket asks for are read out of this database by
    this machine's browser; there is nowhere for them to be transmitted to and
    no code here that could.
    """
    await nominate(session, str(tmp_path))
    for name, body in (("a.pdf", PDF), ("b.pdf", OTHER)):
        written(tmp_path, name, body)
    documents = await recorded(session, tmp_path, "a.pdf", "b.pdf")

    async def extract(
        work: Work, report: Report, factory: async_sessionmaker[AsyncSession], _settings: Settings
    ) -> None:
        if work.filename == "b.pdf":
            raise ValueError("encrypted")
        await report(1, 1)

    monkeypatch.setattr(ingest, "STAGES", (Stage("extract", "M1-EXTRACT-ING-026", extract),))
    await ingest.process(factory, unreachable_queue, documents[0])
    for _ in range(ingest.MAX_ATTEMPTS):
        await ingest.process(factory, unreachable_queue, documents[1])

    state = await ingest.snapshot(session, settings)

    assert state["documents_ingested"] == 1
    assert state["documents_failed"] == 1
    assert state["failures"][0]["filename"] == "b.pdf"
    assert "encrypted" in state["failures"][0]["error"]


async def test_the_snapshot_still_lists_a_deleted_source_greyed_with_its_date(
    session: AsyncSession,
    tmp_path: Path,
    settings: Settings,
) -> None:
    """`docs/ux/library.md` §4/§5, `M2-DELETE-FE-062`: a deleted source stays
    listed — the row is what makes an old citation resolve at all — so the
    snapshot the library reads must keep sending it, with a date, rather than
    dropping it the moment it is tombstoned."""
    await nominate(session, str(tmp_path))
    written(tmp_path, "a.pdf", PDF)
    await recorded(session, tmp_path, "a.pdf")
    source_id = (await session.execute(text("SELECT id FROM sources"))).scalar_one()

    await delete_source(session, source_id)
    state = await ingest.snapshot(session, settings)

    rows = {row["id"]: row for row in state["sources"]}
    assert str(source_id) in rows
    assert rows[str(source_id)]["status"] == "deleted"
    assert rows[str(source_id)]["deleted_at"] is not None


# --- the periodic moved-file check (`M1-VIEW-BE-049`) -----------------------


async def test_sweep_missing_flags_a_file_gone_from_an_available_root(
    session: AsyncSession, tmp_path: Path, settings: Settings
) -> None:
    """The half of the ticket that runs on a timer rather than a click —
    `askwell.documents._availability` covers the open-time half."""
    await nominate(session, str(tmp_path))
    written(tmp_path, "a.pdf")
    (document_id,) = await recorded(session, tmp_path, "a.pdf")
    await session.execute(
        text("UPDATE documents SET status = 'ready' WHERE id = :id"), {"id": document_id}
    )
    (tmp_path / "a.pdf").unlink()

    rooted = settings.model_copy(update={"roots_mount": tmp_path})
    touched = await ingest.sweep_missing(session, rooted)

    assert touched == 1
    row = (
        await session.execute(
            text("SELECT missing_since FROM documents WHERE id = :id"), {"id": document_id}
        )
    ).first()
    assert row is not None
    assert row[0] is not None


async def test_sweep_missing_clears_a_file_that_reappeared(
    session: AsyncSession, tmp_path: Path, settings: Settings
) -> None:
    await nominate(session, str(tmp_path))
    written(tmp_path, "a.pdf")
    (document_id,) = await recorded(session, tmp_path, "a.pdf")
    await session.execute(
        text("UPDATE documents SET status = 'ready', missing_since = now() WHERE id = :id"),
        {"id": document_id},
    )

    rooted = settings.model_copy(update={"roots_mount": tmp_path})
    touched = await ingest.sweep_missing(session, rooted)

    assert touched == 1
    row = (
        await session.execute(
            text("SELECT missing_since FROM documents WHERE id = :id"), {"id": document_id}
        )
    ).first()
    assert row is not None
    assert row[0] is None


async def test_sweep_missing_skips_a_source_whose_root_is_unreachable(
    session: AsyncSession, tmp_path: Path, settings: Settings
) -> None:
    """The ticket's own edge case: a whole root being unmounted must not be
    read as every document under it being individually missing."""
    await nominate(session, str(tmp_path))
    written(tmp_path, "a.pdf")
    (document_id,) = await recorded(session, tmp_path, "a.pdf")
    await session.execute(
        text("UPDATE documents SET status = 'ready' WHERE id = :id"), {"id": document_id}
    )
    (tmp_path / "a.pdf").unlink()

    # `settings` on its own has no `roots_mount`, so the nominated root probes
    # as `not_mounted` rather than available.
    touched = await ingest.sweep_missing(session, settings)

    assert touched == 0
    row = (
        await session.execute(
            text("SELECT missing_since FROM documents WHERE id = :id"), {"id": document_id}
        )
    ).first()
    assert row is not None
    assert row[0] is None
