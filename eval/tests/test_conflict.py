"""`eval.conflict`'s own scoring logic — without a database or a model.

Seeding the corpus (including `_ensure_superseded`) and driving a real `ask`
turn need real Postgres and a running native inference process; that half is
exercised by hand per `eval/suites/conflicting_sources.v1.json`'s own
testing notes, not here (no network, no database — same rule as every other
unmarked test, `AGENTS.md` §6).
"""

from eval.conflict import conflict_score
from eval.suite import load_suite, resolve_suite_path

_TASK = load_suite(resolve_suite_path("conflicting_sources.v1")).tasks[0]  # return-window
assert _TASK.expect_conflict
_FALSE_CONFLICT_TASK = next(
    task
    for task in load_suite(resolve_suite_path("conflicting_sources.v1")).tasks
    if not task.expect_conflict and len(task.expected_documents) == 1
)


def test_genuine_conflict_presented_and_cited_scores_one() -> None:
    answer = (
        "Conflicting sources on the standard return window:\n"
        "- The return window is thirty days [1].\n"
        "- As of January 2026, the return window is forty-five days [2].\n"
    )
    citations = [
        {"filename": "conflict_2025.pdf", "passage": "thirty days"},
        {"filename": "conflict_2026.pdf", "passage": "forty-five days"},
    ]
    assert conflict_score(_TASK, answer, citations) == 1.0


def test_genuine_conflict_silently_resolved_to_one_position_scores_zero() -> None:
    """The over-preference case: no "Conflicting sources on ...:" line, and
    only one of the two values is stated — a silently preferred source."""
    answer = "The return window is thirty days [1]."
    citations = [{"filename": "conflict_2025.pdf", "passage": "thirty days"}]
    assert conflict_score(_TASK, answer, citations) == 0.0


def test_genuine_conflict_with_both_values_but_no_marker_line_scores_zero() -> None:
    """Both values present is not enough on its own — the fixed
    "Conflicting sources on ...:" line is how the conflict is recorded, and
    its absence means the turn never actually flagged the disagreement."""
    answer = "The return window is thirty days [1] or forty-five days [2], depending on the source."
    citations = [
        {"filename": "conflict_2025.pdf", "passage": "thirty days"},
        {"filename": "conflict_2026.pdf", "passage": "forty-five days"},
    ]
    assert conflict_score(_TASK, answer, citations) == 0.0


def test_genuine_conflict_missing_one_citation_scores_zero() -> None:
    """Both positions stated but only one document actually cited — the
    "both cited" half of the acceptance criterion, not just "both stated"."""
    answer = (
        "Conflicting sources on the standard return window:\n"
        "- The return window is thirty days [1].\n"
        "- The return window is forty-five days.\n"
    )
    citations = [{"filename": "conflict_2025.pdf", "passage": "thirty days"}]
    assert conflict_score(_TASK, answer, citations) == 0.0


def test_false_conflict_presented_as_one_scores_zero() -> None:
    """Over-detection: the same value, differently worded, is not a real
    conflict — presenting it as one is scored as a failure, per the
    ticket's own edge case."""
    answer = (
        "Conflicting sources on gift card expiry:\n"
        "- Gift cards never expire [1].\n"
        "- Gift cards never expire [2].\n"
    )
    citations = [{"filename": "conflict_2025.pdf", "passage": "never expires"}]
    assert conflict_score(_FALSE_CONFLICT_TASK, answer, citations) == 0.0


def test_false_conflict_answered_plainly_scores_one() -> None:
    answer = "No — a Meridian Loom gift card balance does not expire; it never expires [1]."
    citations = [{"filename": "conflict_2025.pdf", "passage": "never expires"}]
    assert conflict_score(_FALSE_CONFLICT_TASK, answer, citations) == 1.0


def test_false_conflict_with_wrong_value_scores_zero() -> None:
    answer = "Meridian Loom gift cards expire after one year [1]."
    citations = [{"filename": "conflict_2025.pdf", "passage": "never expires"}]
    assert conflict_score(_FALSE_CONFLICT_TASK, answer, citations) == 0.0
