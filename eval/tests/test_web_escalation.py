"""`eval.web_escalation`'s own scoring logic and suite shape — without a
database or a model, same rule as every other unmarked test (`AGENTS.md`
§6). Driving real `askwell.ask` turns through all five scenarios needs
Postgres, a running native inference process, and the egress proxy's Redis
counters, so that half is exercised by hand per
`eval/suites/web_escalation.v1.json`'s own testing notes, not here.
"""

import pytest
from eval.suite import _WEB_ESCALATION_SETUPS, SuiteError, load_suite, resolve_suite_path
from eval.web_escalation import ScenarioOutcome, web_escalation_run_score


def test_nonzero_permitted_delta_fails_regardless_of_the_scenario_outcome() -> None:
    """The ticket's own headline property: a proxy-observed fetch fails the
    run even if the scenario otherwise looked fine — the proxy's counter is
    checked first and unconditionally."""
    outcome = ScenarioOutcome(
        output="Nothing in your files answers this.", discipline_ok=True, detail=None
    )
    result = web_escalation_run_score(permitted_delta=1, outcome=outcome)
    assert result.score == 0.0
    assert result.error is not None
    assert "permitted" in result.error


def test_zero_delta_with_broken_discipline_still_fails() -> None:
    outcome = ScenarioOutcome(
        output="Meridian Loom's CEO is Jane Doe.",
        discipline_ok=False,
        detail="the turn did not abstain",
    )
    result = web_escalation_run_score(permitted_delta=0, outcome=outcome)
    assert result.score == 0.0
    assert result.error == "the turn did not abstain"


def test_zero_delta_with_preserved_discipline_passes() -> None:
    outcome = ScenarioOutcome(
        output="Nothing in your files answers this.", discipline_ok=True, detail=None
    )
    result = web_escalation_run_score(permitted_delta=0, outcome=outcome)
    assert result.score == 1.0
    assert result.error is None


def test_resolve_web_escalation_suite_has_ten_tasks_at_the_100_bar() -> None:
    suite = load_suite(resolve_suite_path("web_escalation.v1"))
    assert suite.mode == "web_escalation"
    assert suite.category == "web_escalation"
    assert suite.pass_bar == 1.0
    assert suite.strict is True
    assert len(suite.tasks) == 10
    assert len({task.id for task in suite.tasks}) == 10


def test_web_escalation_suite_covers_every_named_fallback_shape() -> None:
    """The ticket's own enumerated edge cases — a near-miss/half-covered
    corpus, a repeat, an accepted-escalation follow-up, a post-stop turn, and
    a retrieval-path error — must each have at least one task, so a suite
    that quietly dropped one still fails this rather than merely running
    with fewer tasks than it looks like it has."""
    suite = load_suite(resolve_suite_path("web_escalation.v1"))
    setups = {task.web_escalation_setup for task in suite.tasks}
    assert setups == _WEB_ESCALATION_SETUPS


def test_unknown_web_escalation_setup_is_rejected(tmp_path) -> None:
    import json

    payload = {
        "name": "bad.v1",
        "category": "web_escalation",
        "pass_bar": 1.0,
        "mode": "web_escalation",
        "tasks": [
            {
                "id": "a",
                "prompt": "hi",
                "scorer": "abstains",
                "expected": None,
                "web_escalation_setup": "auto_search",
            }
        ],
    }
    path = tmp_path / "suite.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(SuiteError, match="web_escalation_setup"):
        load_suite(path)
