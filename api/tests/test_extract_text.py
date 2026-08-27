"""Text/Markdown/HTML sectioning, without a database.

`M1-EXTRACT-ING-027`. The logic worth asserting directly, rather than only
through a full ingestion run: front matter is metadata and must not survive
into a heading anchor's text, and HTML's chrome tags are gone before any
heading or paragraph is read.
"""

from askwell.extract_text import _html_to_headed_text, _sections, _strip_front_matter


def test_front_matter_is_stripped_and_prose_is_not() -> None:
    content = (
        "---\ntitle: Renewal notice\nstatus: draft\n---\n"
        "# Renewal\n\nEither party may terminate on ninety days written notice.\n"
    )
    stripped = _strip_front_matter(content)
    assert "title: Renewal notice" not in stripped
    assert "Either party may terminate" in stripped


def test_a_file_with_no_front_matter_is_unchanged() -> None:
    content = "# Renewal\n\nEither party may terminate on ninety days written notice.\n"
    assert _strip_front_matter(content) == content


def test_a_stray_horizontal_rule_is_not_mistaken_for_front_matter() -> None:
    """`---` deep in a document is Markdown's own horizontal rule, not a
    front matter delimiter — only an opening `---` at position zero counts."""
    content = "# Renewal\n\nSee below.\n\n---\n\nMore text after the rule.\n"
    assert _strip_front_matter(content) == content


def test_headings_split_the_document_into_labelled_sections() -> None:
    content = (
        "# Introduction\n\nThis sets the scene.\n\n## Terms\n\nThirty days notice is required.\n"
    )
    sections = _sections(content)
    assert [section.label for section in sections] == ["Introduction", "Terms"]
    assert "This sets the scene." in "\n".join(sections[0].lines)
    assert "Thirty days notice is required." in "\n".join(sections[1].lines)


def test_a_document_with_no_headings_is_one_unlabelled_section() -> None:
    content = "Just a paragraph of plain text, no headings at all."
    sections = _sections(content)
    assert len(sections) == 1
    assert sections[0].label is None


def test_html_navigation_chrome_is_discarded() -> None:
    html = (
        "<html><head><title>Contract</title></head><body>"
        "<nav><a href='/'>Home</a><a href='/about'>About</a></nav>"
        "<script>track();</script>"
        "<h1>Terms</h1><p>Either party may terminate on ninety days notice.</p>"
        "</body></html>"
    )
    text = _html_to_headed_text(html)
    assert "Home" not in text
    assert "track()" not in text
    assert "# Terms" in text
    assert "Either party may terminate" in text


def test_html_headings_become_markdown_style_anchors() -> None:
    html = "<body><h2>Section Two</h2><p>Body text.</p></body>"
    text = _html_to_headed_text(html)
    sections = _sections(text)
    assert sections[0].label == "Section Two"


def test_the_page_title_is_metadata_and_does_not_leak_into_the_first_section() -> None:
    """`<title>` lives in `<head>`, never seen by anyone reading the page —
    found by running a real HTML file through the pipeline, where it showed
    up as an unlabelled section ahead of the real content."""
    html = (
        "<html><head><title>Contract</title></head>"
        "<body><h1>Terms</h1><p>Either party may terminate.</p></body></html>"
    )
    text = _html_to_headed_text(html)
    assert "Contract" not in text
