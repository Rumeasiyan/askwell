"""PDF extraction's own rules, without a database.

`M1-EXTRACT-ING-026`. What is pure here is the page-usability heuristic — the
edge case the ticket names explicitly: "embedded fonts that produce unusable
characters — treated as no usable text and routed to OCR." The rest of the
stage needs a real Postgres row to write into and is covered against one in
`test_extract_pdf_records.py`.
"""

from askwell.extract_pdf import _usable


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
