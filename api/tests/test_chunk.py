"""Structure-aware chunking, without a database. `M1-INDEX-ING-031`.

The parsing, splitting and merging logic is worth asserting directly — it is
where the ticket's own correctness lives (a table row surviving with its
header, a heading-free run breaking at sentences, nothing ever crossing the
hard maximum) and none of it needs Postgres to prove.
"""

from askwell.chunk import (
    _ChunkDraft,
    _enforce_max,
    _finalize,
    _Fragment,
    _merge,
    _page_fragments,
    _split_list,
    _split_paragraph,
    _split_table,
)


def test_a_small_table_stays_with_its_header_in_one_fragment() -> None:
    content = "[TABLE]\nItem | Price\nWidget | 9.99\nGadget | 4.50\n[/TABLE]"
    fragments = _page_fragments(1, content, hard_max=2400)
    assert len(fragments) == 1
    assert fragments[0].kind == "content"
    assert "Item | Price" in fragments[0].text
    assert "Widget | 9.99" in fragments[0].text


def test_a_table_longer_than_the_maximum_is_split_with_the_header_repeated() -> None:
    header = "Item | Price"
    rows = [f"Row {n} | {n}.00" for n in range(200)]
    parts = _split_table(header, rows, hard_max=200)

    assert len(parts) > 1
    for part in parts:
        assert part.startswith("[TABLE]\nItem | Price\n")
        assert part.endswith("[/TABLE]")
        assert len(part) <= 200 or part.count("\n") <= 3  # a single huge row is the only excuse


def test_every_row_from_a_split_table_survives_exactly_once() -> None:
    header = "Item | Price"
    rows = [f"Row {n} | {n}.00" for n in range(50)]
    parts = _split_table(header, rows, hard_max=300)

    seen = []
    for part in parts:
        body = part.removeprefix("[TABLE]\n").removesuffix("\n[/TABLE]")
        lines = body.split("\n")
        assert lines[0] == header
        seen.extend(lines[1:])
    assert seen == rows


def test_a_nested_list_is_kept_together_rather_than_split_mid_run() -> None:
    content = "- First point\n- Second point\n  1. Sub item\n  2. Sub item two\n- Third point"
    fragments = _page_fragments(1, content, hard_max=2400)
    assert len(fragments) == 1
    assert fragments[0].kind == "content"
    assert "First point" in fragments[0].text
    assert "Third point" in fragments[0].text


def test_a_long_list_is_split_by_item_not_mid_item() -> None:
    items = [f"- item number {n} with some words to pad it out a little" for n in range(80)]
    parts = _split_list(items, hard_max=400)
    assert len(parts) > 1
    for part in parts:
        for line in part.split("\n"):
            assert line in items


def test_a_heading_free_run_is_split_at_sentence_boundaries_not_mid_sentence() -> None:
    sentence = "Either party may terminate this agreement on ninety days written notice. "
    long_text = sentence * 40  # comfortably over any sane hard maximum
    parts = _split_paragraph(long_text, target=200, hard_max=400, overlap=50)

    assert len(parts) > 1
    for part in parts:
        assert len(part) <= 400
        stripped = part.strip()
        assert stripped.endswith(".") or stripped == ""


def test_a_single_paragraph_over_the_maximum_splits_with_overlap() -> None:
    sentence = "The tenant shall pay rent monthly in advance without deduction. "
    text = sentence * 30
    parts = _split_paragraph(text, target=150, hard_max=300, overlap=40)

    assert len(parts) > 1
    # Overlap: the tail of one part reappears at the head of the next, so a
    # sentence spanning the cut is never orphaned in only one of the two.
    first_tail = parts[0][-40:].strip()
    assert first_tail.split(" ")[0] in parts[1]


def test_a_document_with_no_headings_at_all_produces_no_heading_fragments() -> None:
    content = "Just a paragraph of plain text, no headings at all, nothing structural."
    fragments = _page_fragments(1, content, hard_max=2400)
    assert all(fragment.kind == "content" for fragment in fragments)


def test_a_heading_becomes_metadata_not_a_content_fragment() -> None:
    content = "# Renewal Terms\n\nThirty days notice is required."
    fragments = _page_fragments(1, content, hard_max=2400)
    kinds = [(fragment.kind, fragment.text) for fragment in fragments]
    assert ("heading", "Renewal Terms") in kinds
    assert not any(
        fragment.kind == "content" and "Renewal Terms" in fragment.text for fragment in fragments
    )


def test_a_heading_is_carried_on_every_chunk_beneath_it_until_the_next_one() -> None:
    pages = [
        (1, _page_fragments(1, "# Payment Terms\n\nDue within thirty days.", hard_max=2400)),
        (
            2,
            _page_fragments(
                2, "More detail on payment, still under the same heading.", hard_max=2400
            ),
        ),
        (
            3,
            _page_fragments(
                3, "# Termination\n\nEither party may end this agreement.", hard_max=2400
            ),
        ),
    ]
    drafts = _merge(pages, anchor_kind="page", target=1600, hard_max=2400)

    assert [draft.heading for draft in drafts] == ["Payment Terms", "Termination"]
    assert drafts[0].page_from == 1
    assert drafts[0].page_to == 2
    assert drafts[1].page_from == 3
    assert drafts[1].page_to == 3


def test_a_slide_deck_is_one_chunk_per_slide_unless_a_slide_is_very_long() -> None:
    pages = [
        (1, _page_fragments(1, "Quarterly results are ahead of forecast.", hard_max=2400)),
        (2, _page_fragments(2, "Next steps for the roadmap.", hard_max=2400)),
    ]
    drafts = _merge(pages, anchor_kind="slide", target=1600, hard_max=2400)

    assert len(drafts) == 2
    assert drafts[0].page_from == 1 and drafts[0].page_to == 1
    assert drafts[1].page_from == 2 and drafts[1].page_to == 2


def test_a_very_long_slide_still_splits_within_itself() -> None:
    sentence = "The pricing change takes effect at the start of next quarter. "
    pages = [(1, _page_fragments(1, sentence * 60, hard_max=400))]
    drafts = _merge(pages, anchor_kind="slide", target=200, hard_max=400)

    assert len(drafts) > 1
    assert all(draft.page_from == 1 and draft.page_to == 1 for draft in drafts)


def test_no_finalized_chunk_ever_exceeds_the_hard_maximum() -> None:
    pathological = "x" * 50_000  # one giant run with no whitespace at all
    parts = _enforce_max(pathological, hard_max=2400)
    assert all(len(part) <= 2400 for part in parts)
    assert "".join(parts) == pathological


def test_enforce_max_leaves_content_within_budget_untouched() -> None:
    content = "A short passage that easily fits."
    assert _enforce_max(content, hard_max=2400) == [content]


def test_finalize_drops_nothing_but_blank_content() -> None:
    drafts = [
        _ChunkDraft(content="  ", page_from=1, page_to=1, heading=None),
        _ChunkDraft(content="Real content here.", page_from=2, page_to=2, heading="Heading"),
    ]
    finalized = _finalize(drafts, hard_max=2400)
    assert len(finalized) == 1
    assert finalized[0].content == "Real content here."


def test_fragment_and_draft_are_plain_data() -> None:
    fragment = _Fragment(kind="content", page=1, text="hello")
    assert fragment.kind == "content"
    assert fragment.page == 1
    assert fragment.text == "hello"
