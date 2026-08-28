import pytest
from eval.scoring import score


def test_contains_all_single_string_case_insensitive() -> None:
    assert score("contains_all", "The capital is Paris.", "paris") == 1.0


def test_contains_all_list_requires_every_needle() -> None:
    assert score("contains_all", "Paris is the capital of France.", ["Paris", "France"]) == 1.0
    assert score("contains_all", "Paris is a city.", ["Paris", "France"]) == 0.0


def test_contains_all_rejects_bad_expected_type() -> None:
    with pytest.raises(ValueError, match="contains_all"):
        score("contains_all", "anything", 4)


def test_exact_strips_whitespace_only() -> None:
    assert score("exact", "  4\n", "4") == 1.0
    assert score("exact", "four", "4") == 0.0


def test_unknown_scorer_lists_available() -> None:
    with pytest.raises(ValueError, match="contains_all"):
        score("no-such-scorer", "x", "x")
