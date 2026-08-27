"""PDF extraction's own rules, without a database.

`M1-EXTRACT-ING-026`. What is pure here is the page-usability heuristic — the
edge case the ticket names explicitly: "embedded fonts that produce unusable
characters — treated as no usable text and routed to OCR." The rest of the
stage needs a real Postgres row to write into and is covered against one in
`test_extract_pdf_records.py`.
"""

import pypdfium2 as pdfium

from askwell.extract_common import CorruptDocument, PasswordProtected, WrongPassword
from askwell.extract_pdf import _classify_open_failure, _usable


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
