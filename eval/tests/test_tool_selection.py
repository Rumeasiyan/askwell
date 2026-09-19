"""`eval.tool_selection`'s own logic -- tool-route matching, parallel-dispatch
detection, and the combined score -- without a database or a model.

Seeding the fixture corpus and sandbox database and driving a real
`run_tool_loop` turn needs a running native inference process and Postgres;
that half is exercised by hand per `eval/suites/tool_selection.v1.json`'s own
testing notes, not here (no network, no database -- same rule as every other
unmarked test, `AGENTS.md` §6).
"""

from askwell.agent.loop import LoopStep
from eval.tool_selection import combined_tool_score, parallel_achieved, tool_choice_score


def _step(tool: str, iteration: int, *, deduplicated: bool = False) -> LoopStep:
    return LoopStep(
        kind="tool",
        tool=tool,
        arguments={},
        duration_ms=1,
        outcome="ok",
        truncated=False,
        detail={},
        injection_flagged=False,
        injection_patterns=(),
        iteration=iteration,
        deduplicated=deduplicated,
        started_offset_ms=0,
        result_index=1,
    )


# --- tool_choice_score --------------------------------------------------------


def test_tool_choice_matches_the_only_accepted_route() -> None:
    actual = frozenset({"document_search"})
    assert tool_choice_score(actual, (("document_search",),)) == 1.0


def test_tool_choice_matches_either_of_two_accepted_routes() -> None:
    accepted = (("schema_lookup",), ("database_query",))
    assert tool_choice_score(frozenset({"schema_lookup"}), accepted) == 1.0
    assert tool_choice_score(frozenset({"database_query"}), accepted) == 1.0


def test_tool_choice_accepts_no_tool_at_all() -> None:
    assert tool_choice_score(frozenset(), ((),)) == 1.0


def test_tool_choice_rejects_a_missing_tool() -> None:
    accepted = (("document_search", "database_query"),)
    assert tool_choice_score(frozenset({"document_search"}), accepted) == 0.0


def test_tool_choice_rejects_the_tempting_unnecessary_call() -> None:
    # The ticket's own edge case: calling an extra tool nobody needed fails
    # exactly like missing a needed one -- the accepted route is the answer,
    # not a floor.
    accepted = (("document_search",),)
    actual = frozenset({"document_search", "database_query"})
    assert tool_choice_score(actual, accepted) == 0.0


# --- parallel_achieved ---------------------------------------------------------


def test_parallel_achieved_when_two_fresh_calls_share_an_iteration() -> None:
    steps = (_step("document_search", iteration=1), _step("database_query", iteration=1))
    assert parallel_achieved(steps) is True


def test_parallel_not_achieved_when_calls_land_in_separate_iterations() -> None:
    # This is what "parallel dispatch removed" looks like on the trace: the
    # same two tools, called one iteration at a time instead of together.
    steps = (_step("document_search", iteration=1), _step("database_query", iteration=2))
    assert parallel_achieved(steps) is False


def test_parallel_ignores_deduplicated_repeats() -> None:
    # A duplicate call recorded again in a later iteration must not look
    # like a second independent dispatch.
    steps = (
        _step("document_search", iteration=1),
        _step("document_search", iteration=2, deduplicated=True),
    )
    assert parallel_achieved(steps) is False


# --- combined_tool_score -------------------------------------------------------


def test_combined_score_unaffected_when_parallel_not_required() -> None:
    accepted = (("document_search",),)
    score = combined_tool_score(
        frozenset({"document_search"}), accepted, require_parallel=False, achieved_parallel=False
    )
    assert score == 1.0


def test_combined_score_zero_when_parallel_required_but_not_achieved() -> None:
    # The ticket's own acceptance criterion: removing parallel dispatch
    # fails the parallel tasks specifically, even though the right two
    # tools were still called.
    accepted = (("document_search", "database_query"),)
    score = combined_tool_score(
        frozenset({"document_search", "database_query"}),
        accepted,
        require_parallel=True,
        achieved_parallel=False,
    )
    assert score == 0.0


def test_combined_score_passes_when_parallel_required_and_achieved() -> None:
    accepted = (("document_search", "database_query"),)
    score = combined_tool_score(
        frozenset({"document_search", "database_query"}),
        accepted,
        require_parallel=True,
        achieved_parallel=True,
    )
    assert score == 1.0


def test_combined_score_does_not_let_parallel_paper_over_the_wrong_tools() -> None:
    accepted = (("document_search", "database_query"),)
    score = combined_tool_score(
        frozenset({"document_search", "schema_lookup"}),
        accepted,
        require_parallel=True,
        achieved_parallel=True,
    )
    assert score == 0.0
