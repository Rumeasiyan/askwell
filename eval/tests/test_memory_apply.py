"""`eval.memory_apply`'s own scoring logic — without a database or a model.

Seeding the fixture facts (through `answer_clarification`/`correct_memory_fact`)
and driving a real `ask` turn need real Postgres and a running native
inference process; that half is exercised by hand per
`eval/suites/memory_apply.v1.json`'s own testing notes, not here (no
network, no database — same rule as every other unmarked test,
`AGENTS.md` §6).
"""

from eval.memory_apply import memory_score
from eval.suite import load_suite, resolve_suite_path

_SUITE = load_suite(resolve_suite_path("memory_apply.v1"))
_APPLY_TASK = next(t for t in _SUITE.tasks if t.id == "return-window-current")
_SUPERSEDE_TASK = next(t for t in _SUITE.tasks if t.id == "affiliate-rate-superseded")
_NO_INVENT_TASK = next(t for t in _SUITE.tasks if t.id == "termination-notice-no-invent")
_IRRELEVANT_TASK = next(t for t in _SUITE.tasks if t.id == "holiday-accrual-irrelevant-fact")


def test_suite_has_fifteen_tasks_at_the_085_bar() -> None:
    assert _SUITE.mode == "memory"
    assert _SUITE.category == "memory-application"
    assert _SUITE.pass_bar == 0.85
    assert len(_SUITE.tasks) == 15
    assert len({task.id for task in _SUITE.tasks}) == 15


def test_apply_task_scores_one_when_current_value_stated_and_cited() -> None:
    answer = "Meridian Loom's current return window is forty-five days [1]."
    citations = [{"fact_kind": "memory", "subject": "return-window-policy"}]
    assert memory_score(_APPLY_TASK, answer, citations) == (1.0, None)


def test_apply_task_scores_zero_with_no_application() -> None:
    answer = "I'm not sure what the current return window is."
    assert memory_score(_APPLY_TASK, answer, []) == (0.0, "no_application")


def test_apply_task_scores_zero_when_stated_but_uncited() -> None:
    answer = "Meridian Loom's current return window is forty-five days."
    assert memory_score(_APPLY_TASK, answer, []) == (0.0, "not_cited")


def test_apply_task_ignores_citations_for_other_subjects() -> None:
    answer = "Meridian Loom's current return window is forty-five days."
    citations = [{"fact_kind": "memory", "subject": "shipping-fee-policy"}]
    assert memory_score(_APPLY_TASK, answer, citations) == (0.0, "not_cited")


def test_supersede_task_scores_one_when_new_value_stated_and_cited() -> None:
    answer = "Meridian Loom's current affiliate commission rate is eleven percent [1]."
    citations = [{"fact_kind": "memory", "subject": "affiliate-rate-policy"}]
    assert memory_score(_SUPERSEDE_TASK, answer, citations) == (1.0, None)


def test_supersede_task_still_applying_old_value_is_a_distinct_failure() -> None:
    """The ticket's own edge case: a superseded fact that is not applied
    correctly must score as a failure legibly distinct from a generic
    application failure."""
    answer = "Meridian Loom's affiliate commission rate is eight percent."
    assert memory_score(_SUPERSEDE_TASK, answer, []) == (0.0, "superseded_fact_still_applied")


def test_supersede_task_with_neither_value_is_plain_no_application() -> None:
    answer = "I don't have the current affiliate commission rate."
    assert memory_score(_SUPERSEDE_TASK, answer, []) == (0.0, "no_application")


def test_supersede_task_new_value_present_alongside_old_still_passes_if_cited() -> None:
    """The current value being stated is what matters; mentioning the
    superseded one in passing (e.g. explaining the change) is not itself a
    failure once the current value and its citation are both present."""
    answer = (
        "Meridian Loom's affiliate commission rate is now eleven percent [1], "
        "up from the previous eight percent."
    )
    citations = [{"fact_kind": "memory", "subject": "affiliate-rate-policy"}]
    assert memory_score(_SUPERSEDE_TASK, answer, citations) == (1.0, None)


def test_no_invent_task_scores_one_for_a_proper_abstention() -> None:
    answer = (
        "Nothing in your files answers this.\n"
        "I searched 6 passages across 2 documents. The closest material was "
        "about Notice Period, which does not cover this.\n"
        "Add the source you'd expect this in, and ask again."
    )
    assert memory_score(_NO_INVENT_TASK, answer, []) == (1.0, None)


def test_no_invent_task_scores_zero_when_memory_licenses_an_invented_answer() -> None:
    """The failure this task exists to catch: a memory fact that is merely
    topically related gets treated as license to answer anyway."""
    answer = "Meridian Loom requires thirty days' notice before a termination."
    assert memory_score(_NO_INVENT_TASK, answer, []) == (0.0, "invented_content")


def test_no_invent_task_scores_zero_when_abstaining_with_no_search_proof() -> None:
    answer = "Nothing in your files answers this — nothing is indexed.\nAdd a source, ask again."
    assert memory_score(_NO_INVENT_TASK, answer, []) == (0.0, "abstained_without_proof")


def test_irrelevant_task_scores_one_when_grounded_answer_is_unaffected() -> None:
    answer = "Meridian Loom employees accrue eleven paid holiday days per calendar year [1]."
    assert memory_score(_IRRELEVANT_TASK, answer, []) == (1.0, None)


def test_irrelevant_task_scores_zero_when_the_unrelated_fact_derails_the_answer() -> None:
    answer = "Based on the coffee machine servicing schedule, I'm not sure."
    assert memory_score(_IRRELEVANT_TASK, answer, []) == (0.0, "grounded_answer_disrupted")
