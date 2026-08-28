"""Abstention copy. `M2-ABSTAIN-BE-054`.

Pure — no database, no model. `test_ask_api.py`'s abstention tests exercise
this composed through the real turn end to end; this file only cares what
`compose_abstention()` does with the counts and near-miss it is handed.
"""

from askwell.agent import abstain as abstain_module
from askwell.agent.abstain import PROMPT_PATH, PROMPT_VERSION, compose_abstention


def test_prompt_lives_in_a_versioned_file_not_application_logic() -> None:
    assert PROMPT_PATH.exists()
    assert PROMPT_PATH.suffix == ".md"
    assert PROMPT_VERSION in PROMPT_PATH.stem


def test_c5_standing_statement_present_in_prompt_file() -> None:
    text = PROMPT_PATH.read_text(encoding="utf-8").replace("\n", " ")
    assert "General knowledge is never used" in text
    assert "own material" in text


def test_c5_fails_if_standing_statement_removed(tmp_path, monkeypatch) -> None:
    # Simulates the standing statement being edited out of the prompt file.
    # The whole reason for this test to exist is that it must fail then.
    stripped = tmp_path / "abstention.v1.md"
    stripped.write_text("# Abstention\n\nSay nothing matched.\n", encoding="utf-8")
    monkeypatch.setattr(abstain_module, "PROMPT_PATH", stripped)
    abstain_module._load_standing_prompt.cache_clear()
    try:
        text = abstain_module._load_standing_prompt()
        assert "General knowledge is never used" not in text
    finally:
        abstain_module._load_standing_prompt.cache_clear()


def test_empty_corpus_names_nothing_indexed_rather_than_a_search() -> None:
    message = compose_abstention(
        reason_code="empty_corpus",
        passage_count=0,
        document_count=0,
        database_count=0,
        nearest_heading=None,
    )
    assert "nothing is indexed yet" in message
    assert "I searched" not in message, "no search happened to prove"
    assert "closest" not in message.lower()


def test_source_indexing_names_the_source_as_still_indexing() -> None:
    message = compose_abstention(
        reason_code="source_indexing",
        passage_count=0,
        document_count=0,
        database_count=0,
        nearest_heading=None,
    )
    assert "still" in message and "indexing" in message
    assert "I searched" not in message


def test_below_threshold_names_real_counts_and_the_nearest_topic() -> None:
    message = compose_abstention(
        reason_code="below_threshold",
        passage_count=1240,
        document_count=38,
        database_count=2,
        nearest_heading="supplier onboarding",
    )
    assert "1240 passages" in message
    assert "38 documents" in message
    assert "2 databases" in message
    assert "supplier onboarding" in message
    assert "does not cover this" in message


def test_below_threshold_with_nothing_retrieved_at_all_names_no_nearest_topic() -> None:
    # The ticket's own edge case: something is indexed (so this is not the
    # empty-corpus variant), but retrieval returned no candidate at all —
    # there is no near miss to name, so the message must not invent one.
    message = compose_abstention(
        reason_code="below_threshold",
        passage_count=400,
        document_count=12,
        database_count=0,
        nearest_heading=None,
    )
    assert "found nothing close" in message
    assert "closest material" not in message


def test_singular_counts_are_not_pluralised() -> None:
    message = compose_abstention(
        reason_code="below_threshold",
        passage_count=1,
        document_count=1,
        database_count=0,
        nearest_heading="payment terms",
    )
    assert "1 passage " in message
    assert "1 document" in message
    assert "documents" not in message


def test_never_apologises_or_hedges() -> None:
    for reason_code, nearest_heading in (
        ("empty_corpus", None),
        ("source_indexing", None),
        ("below_threshold", "supplier onboarding"),
    ):
        message = compose_abstention(
            reason_code=reason_code,  # type: ignore[arg-type]
            passage_count=5,
            document_count=2,
            database_count=0,
            nearest_heading=nearest_heading,
        )
        lowered = message.lower()
        for forbidden in ("sorry", "apolog", "unfortunately", "i think", "probably", "might be"):
            assert forbidden not in lowered

    assert "Add" in compose_abstention(
        reason_code="below_threshold",
        passage_count=5,
        document_count=2,
        database_count=0,
        nearest_heading="supplier onboarding",
    ), "always offers the add-a-source next action"
