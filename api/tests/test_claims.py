"""Claim segmentation and quoted-span location. `M1-CITE-BE-042`.

Pure, no database, no inference — matches `test_compose.py`'s own reasoning:
`segment_claims`/`locate_quoted_span` are pure functions, so this file only
cares what they do with text handed to them directly.
"""

from askwell.agent.claims import Claim, locate_quoted_span, segment_claims


def test_a_marked_sentence_is_one_claim() -> None:
    claims = segment_claims("Notice must be given ninety days in advance [1].")
    assert claims == [
        Claim(ordinal=1, text="Notice must be given ninety days in advance", indices=(1,))
    ]


def test_a_claim_can_cite_two_passages() -> None:
    claims = segment_claims("Payment is due within forty-five days [1][2].")
    assert claims == [
        Claim(ordinal=1, text="Payment is due within forty-five days", indices=(1, 2))
    ]


def test_an_unmarked_sentence_is_not_a_claim_at_all() -> None:
    # The ticket's own edge case: a restatement of the question is not
    # counted as an uncited claim — it is not a claim.
    text = "How long is the notice period? Notice must be ninety days [1]."
    claims = segment_claims(text)
    assert len(claims) == 1
    assert claims[0].indices == (1,)


def test_ordinal_only_counts_marked_sentences() -> None:
    text = "The contract has several clauses. Payment is due in 45 days [1]. Thank you."
    claims = segment_claims(text)
    assert [c.ordinal for c in claims] == [1]


def test_three_marked_sentences_are_three_claims_in_order() -> None:
    text = "Rent is $1000 [1]. Notice is ninety days [2]. Pets are not allowed [3]."
    claims = segment_claims(text)
    assert [c.ordinal for c in claims] == [1, 2, 3]
    assert [c.indices for c in claims] == [(1,), (2,), (3,)]


def test_duplicate_markers_in_one_claim_are_deduplicated() -> None:
    claims = segment_claims("Notice is ninety days [1][1].")
    assert claims[0].indices == (1,)


def test_a_growing_prefix_only_reveals_completed_sentences() -> None:
    # `ask.py` re-runs this against `turn.text` after every token; a sentence
    # not yet terminated must not appear as a premature claim.
    assert segment_claims("Notice is ninety ") == []
    assert segment_claims("Notice is ninety days [1]") == []
    assert len(segment_claims("Notice is ninety days [1].")) == 1


def test_recomputing_after_more_text_keeps_earlier_ordinals_stable() -> None:
    first = segment_claims("Rent is $1000 [1].")
    second = segment_claims("Rent is $1000 [1]. Notice is ninety days [2].")
    assert first[0] == second[0]
    assert second[1].ordinal == 2


def test_a_quoted_span_found_verbatim_is_returned_exactly() -> None:
    span = locate_quoted_span(
        "The full moon rises after nine days", "The full moon rises after nine days."
    )
    assert span == "The full moon rises after nine days"


def test_a_quoted_span_is_case_insensitive() -> None:
    span = locate_quoted_span("rent is $1000", "Section 4: Rent is $1000 per month.")
    assert span == "Rent is $1000"


def test_a_quoted_span_not_found_resolves_to_none_not_dropped() -> None:
    # The ticket's own edge case: the citation still resolves to the chunk,
    # it just carries no span — proven at the `ask.py` layer, this only
    # proves the lookup itself degrades to `None` rather than raising.
    assert locate_quoted_span("a paraphrase of the passage", "Completely different text.") is None
