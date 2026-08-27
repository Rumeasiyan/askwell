"""Server-side content detection.

This is the boundary copy — the browser's answer is a courtesy and is never
what gets stored. So what is asserted here is not "detection works" but the
narrower and more useful thing: **a file is what its bytes say it is, whatever
its name claims**, because the case this exists for is a renamed program
arriving at a document extractor.

The cases mirror `web/lib/add-source.test.ts` deliberately. Where the two
implementations are expected to answer identically, both suites ask the same
question, so a change to one that is not made to the other shows up as a failing
test rather than as a disagreement nobody notices for a milestone.
"""

from askwell.filetypes import Route, Verdict, detect, extension_of, looks_textual

PDF = b"%PDF-1.7\n1 0 obj\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
ELF = b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 32
ZIP = b"PK\x03\x04" + b"\x00" * 32
GZIP = b"\x1f\x8b\x08\x00" + b"\x00" * 16


def test_a_pdf_is_a_pdf() -> None:
    found = detect("contract.pdf", PDF, len(PDF))
    assert found.format == "a PDF document"
    assert found.route is Route.FILES
    assert found.verdict is Verdict.SUPPORTED
    assert found.mime == "application/pdf"
    assert found.mismatch is None


def test_a_png_named_pdf_is_a_png_and_the_disagreement_is_stated() -> None:
    """The case the whole module exists for, in its mildest form.

    Silence here loses a fact worth having — one of the user's documents is not
    what its name says — and routes the file to an extractor that will fail
    later with a message about the wrong thing.
    """
    found = detect("contract.pdf", PNG, len(PNG))
    assert found.format == "a PNG image"
    assert found.mime == "image/png"
    assert found.mismatch is not None
    assert ".pdf" in found.mismatch
    assert "PNG" in found.mismatch


def test_a_program_named_pdf_is_refused_and_never_typed_as_a_document() -> None:
    """A renamed executable is what a client-declared type would have let through."""
    found = detect("invoice.pdf", ELF, len(ELF))
    assert found.verdict is Verdict.REFUSED
    assert found.format == "a Linux program"
    assert found.refusal is not None
    assert "nothing has been run" in found.refusal.lower()


def test_a_zip_named_docx_is_a_word_document_and_a_bare_zip_is_refused() -> None:
    """The one job the extension is better at: telling the zipped formats apart."""
    word = detect("brief.docx", ZIP, len(ZIP))
    assert word.format == "a Word document"
    assert word.verdict is Verdict.SUPPORTED
    assert word.mime is not None and "wordprocessingml" in word.mime

    archive = detect("papers.zip", ZIP, len(ZIP))
    assert archive.verdict is Verdict.REFUSED
    assert archive.refusal is not None
    assert "unpack" in archive.refusal.lower()


def test_an_archive_refusal_says_what_to_do_instead() -> None:
    found = detect("bundle.gz", GZIP, len(GZIP))
    assert found.verdict is Verdict.REFUSED
    assert found.refusal is not None
    assert "unpack" in found.refusal.lower()


def test_an_empty_file_is_refused_with_the_reason() -> None:
    """An edge case the ticket names. Size, not head length, is what decides."""
    found = detect("scan.pdf", b"", 0)
    assert found.verdict is Verdict.REFUSED
    assert found.format == "an empty file"
    assert found.refusal is not None
    assert "nothing in this file" in found.refusal.lower()
    assert found.mime is None


def test_a_csv_arrives_later_rather_than_being_refused() -> None:
    """Recognised and not-yet-built are different facts.

    Told "unsupported", somebody whose material is mostly exports concludes the
    product is not for them, which is false.
    """
    body = b"name,amount,date\nAnna,10,2026-01-01\n"
    found = detect("ledger.csv", body, len(body))
    assert found.verdict is Verdict.LATER
    assert found.route is Route.TABLE
    assert found.arrives == "M4"
    assert found.refusal is None


def test_html_is_judged_on_its_opening_not_on_its_rows() -> None:
    """A saved page is full of rows and would otherwise read as a CSV."""
    body = b"<!DOCTYPE html>\n<table><tr><td>a,b,c,d</td></tr></table>"
    found = detect("page.html", body, len(body))
    assert found.route is Route.FILES
    assert found.format == "an HTML page"
    assert found.mime == "text/html"


def test_html_without_the_extension_is_still_html() -> None:
    body = b"  <html><body>a,b,c</body></html>"
    assert detect("saved", body, len(body)).format == "an HTML page"


def test_markdown_is_named_from_the_extension() -> None:
    body = b"# Heading\n\nSome prose.\n"
    assert detect("notes.md", body, len(body)).format == "a Markdown document"
    assert detect("notes.txt", body, len(body)).format == "plain text"


def test_prose_with_commas_in_a_text_file_is_not_taken_for_a_csv() -> None:
    """The misread that is expensive now rather than cosmetic.

    Since `M1-ADD-VAL-024` a non-files route means the file is not queued at
    all, so routing a `.txt` note to the table route tells the user their
    plain-text note arrives in M4 — which is false about a format Askwell reads
    today. The extension claims the files route here, and it wins.
    """
    body = b"Dear Anna, thank you, and regards\n\nThe contract, as discussed, is enclosed.\n"
    found = detect("letter.txt", body, len(body))
    assert found.route is Route.FILES
    assert found.verdict is Verdict.SUPPORTED


def test_a_note_about_a_schema_is_not_taken_for_a_dump() -> None:
    body = b"# Schema notes\n\nCREATE TABLE orders is the one that matters.\n"
    found = detect("schema.md", body, len(body))
    assert found.route is Route.FILES
    assert found.verdict is Verdict.SUPPORTED


def test_a_real_dump_is_still_recognised_by_its_contents() -> None:
    body = b"-- PostgreSQL database dump\nSET statement_timeout = 0;\n"
    found = detect("backup-2026", body, len(body))
    assert found.route is Route.DUMP
    assert found.verdict is Verdict.LATER


def test_an_unrecognised_binary_is_refused_rather_than_guessed_at() -> None:
    body = bytes(range(0, 200))
    found = detect("thing.bin", body, len(body))
    assert found.verdict is Verdict.REFUSED
    assert found.mime is None


def test_looks_textual_rejects_anything_holding_a_nul() -> None:
    assert looks_textual(b"plain words") is True
    assert looks_textual(b"plain\x00words") is False
    assert looks_textual(b"") is False


def test_extension_of_ignores_a_leading_dot_and_a_trailing_one() -> None:
    assert extension_of("report.PDF") == "pdf"
    assert extension_of(".hidden") == ""
    assert extension_of("archive.") == ""
    assert extension_of("no-extension") == ""
