"""PDF extraction's own rules, without a database.

`M1-EXTRACT-ING-026`. What is pure here is the page-usability heuristic — the
edge case the ticket names explicitly: "embedded fonts that produce unusable
characters — treated as no usable text and routed to OCR." The rest of the
stage needs a real Postgres row to write into and is covered against one in
`test_extract_pdf_records.py`.
"""

import asyncio
import threading
from pathlib import Path
from typing import ClassVar

import pypdfium2 as pdfium
import pytest

from askwell.extract_common import CorruptDocument, PasswordProtected, WrongPassword
from askwell.extract_pdf import _classify_open_failure, _read_pages, _usable


def test_a_blank_page_is_not_usable() -> None:
    assert not _usable("")
    assert not _usable("   \n\t  ")


def test_ordinary_prose_is_usable() -> None:
    assert _usable("Either party may terminate on ninety days written notice.")


def test_a_page_of_replacement_characters_is_not_usable() -> None:
    """An embedded subset font with no usable encoding is pdfium's classic
    failure mode: every glyph maps to U+FFFD rather than to nothing."""
    assert not _usable("�" * 40)


def test_a_few_replacement_characters_among_real_text_stay_usable() -> None:
    """One glyph pdfium could not map is not the same claim as the page being
    unreadable — a document that reads mostly correctly must not be routed to
    OCR for one bad character."""
    assert _usable("The rate is 5� per unit, payable monthly.")


# --- M1-EXTRACT-VAL-030: classifying why pdfium could not open a document ---


def _password_error() -> pdfium.PdfiumError:
    return pdfium.PdfiumError("Failed to load document.", err_code=pdfium.raw.FPDF_ERR_PASSWORD)


def _security_error() -> pdfium.PdfiumError:
    return pdfium.PdfiumError("Failed to load document.", err_code=pdfium.raw.FPDF_ERR_SECURITY)


def _format_error() -> pdfium.PdfiumError:
    return pdfium.PdfiumError("Failed to load document.", err_code=pdfium.raw.FPDF_ERR_FORMAT)


def test_a_password_error_with_no_password_supplied_asks_for_one() -> None:
    error = _classify_open_failure(
        _password_error(), filename="contract.pdf", password_supplied=False
    )
    assert isinstance(error, PasswordProtected)
    assert "contract.pdf" in str(error)
    assert "password" in str(error).lower()


def test_an_unsupported_security_scheme_also_reads_as_password_protected() -> None:
    error = _classify_open_failure(
        _security_error(), filename="contract.pdf", password_supplied=False
    )
    assert isinstance(error, PasswordProtected)


def test_a_password_error_after_one_was_supplied_is_reported_as_wrong() -> None:
    error = _classify_open_failure(
        _password_error(), filename="contract.pdf", password_supplied=True
    )
    assert isinstance(error, WrongPassword)
    assert "contract.pdf" in str(error)
    assert "incorrect" in str(error).lower()


def test_a_wrong_password_message_never_names_a_password() -> None:
    """C8-adjacent: the classifier is only ever told a password was
    supplied, never what it was, so it cannot leak into the message."""
    error = _classify_open_failure(
        _password_error(), filename="contract.pdf", password_supplied=True
    )
    assert "hunter2" not in str(error)


def test_a_format_error_is_corrupt_not_password_protected() -> None:
    error = _classify_open_failure(_format_error(), filename="ledger.pdf", password_supplied=False)
    assert isinstance(error, CorruptDocument)
    assert "ledger.pdf" in str(error)


def test_a_real_garbage_file_is_classified_as_corrupt() -> None:
    """Not mocked — real bytes handed to real pdfium, to prove the err_code
    path this ticket relies on actually fires the way `ErrorToStr` documents."""
    try:
        pdfium.PdfDocument(b"this is not a pdf at all")
    except pdfium.PdfiumError as error:
        classified = _classify_open_failure(error, filename="junk.pdf", password_supplied=False)
        assert isinstance(classified, CorruptDocument)
    else:  # pragma: no cover - pdfium is expected to refuse this
        raise AssertionError("pdfium accepted garbage bytes as a PDF")


# --- issue #933: PDFium is not thread-safe -----------------------------------


def _text_pdf(prefix: str, page_count: int) -> bytes:
    """A real multi-page PDF with a text layer on every page, pdfium-openable."""
    font_number = 3 + page_count
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{' '.join(f'{3 + i} 0 R' for i in range(page_count))}] "
        f"/Count {page_count} >>".encode(),
    ]
    for page_index in range(page_count):
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 {font_number} 0 R >> >> "
            f"/MediaBox [0 0 612 792] /Contents {font_number + 1 + page_index} 0 R >>".encode()
        )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for page_index in range(page_count):
        lines = " ".join(
            f"BT /F1 10 Tf 72 {740 - row * 14} Td ({prefix} page {page_index} line {row}) Tj ET"
            for row in range(40)
        )
        content = lines.encode("latin-1")
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


class _ThreadRecordingDocument(pdfium.PdfDocument):  # type: ignore[misc,no-any-unimported]
    """A real `PdfDocument` that notes which thread each PDFium call ran on."""

    threads: ClassVar[set[int]] = set()

    def __init__(self, *args: object, **kwargs: object) -> None:
        type(self).threads.add(threading.get_ident())
        super().__init__(*args, **kwargs)

    def __len__(self) -> int:
        type(self).threads.add(threading.get_ident())
        return int(super().__len__())

    def get_page(self, index: int) -> object:
        type(self).threads.add(threading.get_ident())
        return super().get_page(index)

    def get_metadata_dict(self, *args: object, **kwargs: object) -> object:
        type(self).threads.add(threading.get_ident())
        return super().get_metadata_dict(*args, **kwargs)

    def close(self) -> None:
        type(self).threads.add(threading.get_ident())
        super().close()


async def test_every_pdfium_call_for_concurrent_documents_runs_on_one_thread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Issue #933. The worker extracts two documents at once
    (`ingest_concurrency = 2`), and PDFium is not thread-safe: called from two
    threads at once it fails with `PdfiumError: Failed to load page.` and
    leaves the process's PDFium broken for every later document. The race
    needs real-world PDFs to show reliably, so this asserts the rule that
    prevents it: every PDFium call for every document — open, page count, page
    text, metadata, close — runs on one thread, and never on the event loop."""
    _ThreadRecordingDocument.threads = set()
    monkeypatch.setattr("askwell.extract_pdf.pdfium.PdfDocument", _ThreadRecordingDocument)
    pdfs = []
    for name in ("alpha", "beta", "gamma"):
        path = tmp_path / f"{name}.pdf"
        path.write_bytes(_text_pdf(name, 20))
        pdfs.append((name, path))

    async def no_progress(done: int, total: int) -> None:
        return None

    results = await asyncio.gather(
        *(_read_pages(str(path), None, f"{name}.pdf", name, no_progress) for name, path in pdfs)
    )

    assert len(_ThreadRecordingDocument.threads) == 1
    assert threading.get_ident() not in _ThreadRecordingDocument.threads
    for (name, _path), read in zip(pdfs, results, strict=True):
        assert read.page_count == 20
        assert [number for number, _text, _has_text, _confidence in read.pages] == list(
            range(1, 21)
        )
        assert all(has_text for _n, _t, has_text, _c in read.pages)
        assert read.pages[19][1] is not None
        assert f"{name} page 19 line 0" in read.pages[19][1]
