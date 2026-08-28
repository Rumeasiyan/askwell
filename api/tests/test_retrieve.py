"""Reciprocal rank fusion, in isolation. `M1-ASK-RET-035`.

`retrieve._fuse` is pure and synchronous — every acceptance criterion about
ordering, missing scores and no-dedup is a fact about it alone, provable
without a database. `test_retrieve_records.py` covers the SQL either side of
it against real Postgres.
"""

import uuid

from askwell import retrieve as retrieve_module

RRF_K = retrieve_module.RRF_K


def _row(
    chunk_id: uuid.UUID,
    document_id: uuid.UUID,
    score: float,
    content: str = "content",
    heading: str | None = None,
) -> retrieve_module._Row:
    return (chunk_id, document_id, "doc.pdf", "page", content, heading, 1, 1, score)


def test_a_hit_in_both_lists_outranks_a_hit_in_only_one() -> None:
    doc = uuid.uuid4()
    both = uuid.uuid4()
    dense_only = uuid.uuid4()

    dense_rows = [_row(both, doc, 0.9), _row(dense_only, doc, 0.8)]
    lexical_rows = [_row(both, doc, 0.5)]

    fused = retrieve_module._fuse(dense_rows, lexical_rows, candidate_count=10)

    assert [candidate.chunk_id for candidate in fused] == [both, dense_only]


def test_a_candidate_missing_from_one_list_keeps_a_null_score_for_it() -> None:
    doc = uuid.uuid4()
    dense_only = uuid.uuid4()
    lexical_only = uuid.uuid4()

    fused = retrieve_module._fuse(
        [_row(dense_only, doc, 0.9)], [_row(lexical_only, doc, 0.3)], candidate_count=10
    )
    by_id = {candidate.chunk_id: candidate for candidate in fused}

    assert by_id[dense_only].dense_score == 0.9
    assert by_id[dense_only].lexical_score is None
    assert by_id[lexical_only].lexical_score == 0.3
    assert by_id[lexical_only].dense_score is None


def test_the_fused_score_is_reciprocal_rank_summed_across_lists() -> None:
    doc = uuid.uuid4()
    chunk = uuid.uuid4()

    fused = retrieve_module._fuse(
        [_row(chunk, doc, 0.9)], [_row(chunk, doc, 0.5)], candidate_count=10
    )

    assert len(fused) == 1
    expected = 1.0 / (RRF_K + 1) + 1.0 / (RRF_K + 1)
    assert fused[0].score == expected


def test_no_hits_in_either_list_returns_nothing() -> None:
    assert retrieve_module._fuse([], [], candidate_count=10) == []


def test_two_chunks_with_identical_content_from_different_documents_are_both_kept() -> None:
    """The ticket's own edge case: content is not the identity, `chunk_id` is."""
    first_document, second_document = uuid.uuid4(), uuid.uuid4()
    first_chunk, second_chunk = uuid.uuid4(), uuid.uuid4()

    fused = retrieve_module._fuse(
        [
            _row(first_chunk, first_document, 0.7, content="identical passage"),
            _row(second_chunk, second_document, 0.6, content="identical passage"),
        ],
        [],
        candidate_count=10,
    )

    assert {candidate.chunk_id for candidate in fused} == {first_chunk, second_chunk}
    assert {candidate.document_id for candidate in fused} == {first_document, second_document}


def test_the_fused_result_is_truncated_to_the_candidate_count() -> None:
    doc = uuid.uuid4()
    dense_rows = [_row(uuid.uuid4(), doc, 1.0 - index * 0.01) for index in range(5)]

    fused = retrieve_module._fuse(dense_rows, [], candidate_count=2)

    assert len(fused) == 2
