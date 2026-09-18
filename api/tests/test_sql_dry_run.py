"""`DryRunResult`'s shape. `M4-SQL-VAL-106`.

Pure: no network, no database — `dry_run_sandbox_query`/
`dry_run_connection_query` themselves can only be proven against a real
Postgres instance, so those are `test_sql_dry_run_db.py`, `requires_db`.
"""

from askwell.sql.dry_run import DryRunReason, DryRunResult


def test_a_passing_result_carries_no_reason_or_detail() -> None:
    result = DryRunResult(passed=True, reason=None, detail=None)
    assert result.passed
    assert result.reason is None
    assert result.detail is None


def test_a_failing_result_carries_its_reason_and_detail() -> None:
    result = DryRunResult(
        passed=False, reason=DryRunReason.PLANNING_FAILED, detail="column does not exist"
    )
    assert not result.passed
    assert result.reason is DryRunReason.PLANNING_FAILED
    assert "does not exist" in result.detail


def test_planning_failed_timeout_and_unsupported_are_distinct_reasons() -> None:
    """The ticket's own edge cases are three different conditions — a broken
    query, a planner that itself ran out of time, and a database that cannot
    plan-only at all — and must stay distinguishable from each other."""
    reasons = {DryRunReason.PLANNING_FAILED, DryRunReason.TIMEOUT, DryRunReason.UNSUPPORTED}
    assert len(reasons) == 3
