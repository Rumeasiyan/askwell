"""`askwell.agent.summarize`. `M1-CONV-BE-177`.

Pure and offline — no database, no model — matching `test_compose.py` and
`test_claims.py`. `test_ask_api.py` covers the same behaviour wired into a
real turn, transactionally.
"""

import uuid

from askwell.agent.summarize import fallback_summary, summarize_turn
from askwell.retrieve import Candidate


def _candidate(chunk_id: uuid.UUID, document_id: uuid.UUID, content: str = "text") -> Candidate:
    return Candidate(
        chunk_id=chunk_id,
        document_id=document_id,
        filename="file.txt",
        anchor_kind=None,
        content=content,
        heading=None,
        page_from=None,
        page_to=None,
        score=1.0,
        dense_score=1.0,
        lexical_score=None,
    )


def test_a_grounded_answer_gets_a_summary_and_a_distinct_document_count() -> None:
    document_id = uuid.uuid4()
    chunk_a, chunk_b = uuid.uuid4(), uuid.uuid4()
    candidates = [_candidate(chunk_a, document_id), _candidate(chunk_b, document_id)]
    citation_rows = [
        {"chunk_id": chunk_a, "ordinal": 1},
        {"chunk_id": chunk_b, "ordinal": 1},
    ]

    result = summarize_turn(
        question="When is payment due?",
        answer_text="Payment is due within forty-five days.",
        status="completed",
        reason=None,
        partial=False,
        citation_rows=citation_rows,
        candidates=candidates,
    )

    assert result.summary == "Payment is due within forty-five days."
    assert result.source_count == 1  # two chunks, one document


def test_citations_from_two_documents_count_both() -> None:
    document_a, document_b = uuid.uuid4(), uuid.uuid4()
    chunk_a, chunk_b = uuid.uuid4(), uuid.uuid4()
    candidates = [_candidate(chunk_a, document_a), _candidate(chunk_b, document_b)]
    citation_rows = [
        {"chunk_id": chunk_a, "ordinal": 1},
        {"chunk_id": chunk_b, "ordinal": 1},
    ]

    result = summarize_turn(
        question="Do the two contracts agree?",
        answer_text="One contract says thirty days, the other says forty-five.",
        status="completed",
        reason=None,
        partial=False,
        citation_rows=citation_rows,
        candidates=candidates,
    )

    assert result.source_count == 2


def test_an_abstained_turn_stores_no_count_at_all_not_zero() -> None:
    result = summarize_turn(
        question="What colour is the office?",
        answer_text="The files did not cover this.",
        status="completed",
        reason=None,
        partial=False,
        citation_rows=[],
        candidates=[],
    )

    assert result.source_count is None
    assert "did not cover" in result.summary.lower()


def test_a_turn_stopped_mid_stream_is_marked_partial_but_keeps_its_grounded_count() -> None:
    document_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    candidates = [_candidate(chunk_id, document_id)]
    citation_rows = [{"chunk_id": chunk_id, "ordinal": 1}]

    result = summarize_turn(
        question="What are the terms?",
        answer_text="The contract may be terminated with notice.",
        status="stopped",
        reason=None,
        partial=True,
        citation_rows=citation_rows,
        candidates=candidates,
    )

    assert result.source_count == 1
    assert "stopped before finishing" in result.summary


def test_an_abstained_turn_that_was_also_stopped_still_has_no_count() -> None:
    result = summarize_turn(
        question="Anything?",
        answer_text="",
        status="stopped",
        reason=None,
        partial=True,
        citation_rows=[],
        candidates=[],
    )

    assert result.source_count is None
    assert "stopped before finishing" in result.summary


def test_a_failed_turn_names_the_failure_and_has_no_count() -> None:
    result = summarize_turn(
        question="Anything?",
        answer_text="",
        status="failed",
        reason="The assistant is not running.",
        partial=False,
        citation_rows=[],
        candidates=[],
    )

    assert result.source_count is None
    assert "not running" in result.summary


def test_only_the_first_sentence_is_kept_and_citation_markers_are_stripped() -> None:
    document_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    candidates = [_candidate(chunk_id, document_id)]
    citation_rows = [{"chunk_id": chunk_id, "ordinal": 1}]

    result = summarize_turn(
        question="What are the lease terms?",
        answer_text="Rent is $1000 per month [1]. Notice is ninety days [1].",
        status="completed",
        reason=None,
        partial=False,
        citation_rows=citation_rows,
        candidates=candidates,
    )

    assert result.summary == "Rent is $1000 per month."


def test_a_long_answer_is_truncated_with_an_ellipsis() -> None:
    document_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    candidates = [_candidate(chunk_id, document_id)]
    citation_rows = [{"chunk_id": chunk_id, "ordinal": 1}]
    long_sentence = "This clause covers " + ("a great many contingencies " * 10) + "in full."

    result = summarize_turn(
        question="What does the clause cover?",
        answer_text=long_sentence,
        status="completed",
        reason=None,
        partial=False,
        citation_rows=citation_rows,
        candidates=candidates,
    )

    assert len(result.summary) <= 140
    assert result.summary.endswith("…")


def test_a_citation_row_referencing_no_known_candidate_is_not_counted() -> None:
    """A candidate list a caller failed to pass through must never inflate
    the count — the same "unknown index is skipped, not invented" spirit
    `ask.py._cite_claim` already applies to citation resolution."""
    result = summarize_turn(
        question="Anything?",
        answer_text="Something was said.",
        status="completed",
        reason=None,
        partial=False,
        citation_rows=[{"chunk_id": uuid.uuid4(), "ordinal": 1}],
        candidates=[],
    )

    assert result.source_count == 0


def test_fallback_summary_is_derived_from_the_question_alone() -> None:
    result = fallback_summary("How long is the notice period?")

    assert result.source_count is None
    assert "notice period" in result.summary
