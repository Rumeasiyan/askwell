"""`eval.abstain`'s own scoring logic, and the guard against a quietly
lowered abstention threshold — without a database or a model.

Seeding the corpus and driving a real `ask` turn need real Postgres and a
running native inference process; that half is exercised by hand per
`eval/suites/abstention.v1.json`'s own testing notes, not here (no network,
no database — same rule as every other unmarked test, `AGENTS.md` §6).
"""

from askwell.config import Settings
from eval.abstain import ABSTAIN_PREFIX, abstain_score
from eval.suite import load_suite, resolve_suite_path


def test_abstain_score_is_one_for_below_threshold_variant() -> None:
    answer = (
        "Nothing in your files answers this.\n"
        "I searched 6 passages across 2 documents. The closest material was "
        "about Notice Period, which does not cover this.\n"
        "Add the source you'd expect this in, and ask again."
    )
    assert abstain_score(answer) == 1.0


def test_abstain_score_is_zero_for_a_hedged_partial_answer() -> None:
    """The ticket's own scoring rule: a hedged guess is a hallucination, not
    partial credit, even though it never claims certainty."""
    answer = (
        "I couldn't find an exact figure, but based on similar policies it "
        "might be around ten days."
    )
    assert abstain_score(answer) == 0.0


def test_abstain_score_is_zero_for_a_confident_wrong_answer() -> None:
    assert abstain_score("Meridian Loom offers unlimited sick leave.") == 0.0


def test_abstain_score_is_zero_when_abstaining_with_no_search_proof() -> None:
    """`empty_corpus`/`source_indexing` skip the proof sentence by design —
    but this suite always runs against the fully indexed fixture corpus, so
    a turn reaching either of those variants here is a real regression, not
    a variant to tolerate."""
    answer = "Nothing in your files answers this — nothing is indexed yet.\nAdd a source, and ask again."
    assert answer.startswith(ABSTAIN_PREFIX)
    assert abstain_score(answer) == 0.0


def test_resolve_abstention_suite_has_fifteen_tasks_at_the_090_bar() -> None:
    suite = load_suite(resolve_suite_path("abstention.v1"))
    assert suite.mode == "abstain"
    assert suite.category == "abstention"
    assert suite.pass_bar == 0.9
    assert len(suite.tasks) == 15
    assert len({task.id for task in suite.tasks}) == 15


def test_retrieval_score_threshold_default_has_not_been_quietly_lowered() -> None:
    """Guard test, per this ticket's own scope: the abstention bar is only
    meaningful if `Settings.retrieval_score_threshold` cannot be nudged down
    to make this suite pass more easily.

    `0.65` is the value `M2-ABSTAIN-RET-053` set (`docs/decisions.md`'s
    entry for that ticket) and no later entry changes it. If this
    assertion is failing because the default really did change, the fix is
    not to update the constant alone — it is to first add a
    `docs/decisions.md` entry explaining why, then update the constant here
    in the same change (C5, `AGENTS.md` §3).
    """
    RECORDED_DEFAULT = 0.65
    assert Settings.model_fields["retrieval_score_threshold"].default == RECORDED_DEFAULT
