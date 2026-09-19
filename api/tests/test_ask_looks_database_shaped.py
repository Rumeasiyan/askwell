"""`_looks_database_shaped` — the narrow signal `M4-RESULT-FE-111` uses to
decide whether an abstained turn should be reworded as "no database
connected" rather than the ordinary document abstention. Pure, no network:
the whole point of keeping this list narrow (issue #400) is that it must
never fire on the kind of ordinary business prose the abstention eval's own
near-miss questions use — proven here directly against those exact
questions rather than trusted.
"""

from askwell.ask import _looks_database_shaped


def test_matches_an_explicit_database_mention() -> None:
    assert _looks_database_shaped("Is my database connected?")


def test_matches_an_explicit_sql_mention() -> None:
    assert _looks_database_shaped("Can you run a SQL query for me?")


def test_does_not_match_ordinary_document_prose() -> None:
    assert not _looks_database_shaped("What is Meridian Loom's policy on sick leave?")


def test_does_not_match_the_abstention_evals_own_near_miss_questions() -> None:
    """Issue #400's own finding, made concrete: a wide word list
    ("table", "total", "records", "count of", ...) matches ordinary
    business prose exactly like this, and firing on it here would corrupt
    `eval.abstain.abstain_score`'s exact-prefix scoring for a real,
    unrelated abstention. These are `eval/suites/abstention.v1.json`'s own
    prompts, copied verbatim rather than paraphrased.
    """
    near_misses = [
        "What was Meridian Loom's total revenue in Q2?",
        "What was Meridian Loom's headcount in the Support department?",
        "How many days' notice must Meridian Loom give an employee before terminating them?",
        "How many paid holiday days do part-time Meridian Loom employees accrue per calendar year?",
        "How many unused sick days can a Meridian Loom employee carry into the next year?",
    ]
    for question in near_misses:
        assert not _looks_database_shaped(question), question


def test_is_case_insensitive() -> None:
    assert _looks_database_shaped("DATABASE status?")
    assert _looks_database_shaped("Show me the SQL.")
