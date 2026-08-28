"""Runner tests use a fake `InferenceClient` rather than a real model —

the harness's own logic (3 runs, aggregation, abort-on-unavailable) is what is
under test here; whether a real model answers correctly is what the suites
(M2-EVAL-TEST-064 onward) measure. No network, no model file needed.
"""

from collections.abc import Callable
from pathlib import Path

import pytest
from eval import runner
from eval.runner import HarnessError, run_suite
from eval.suite import Suite, Task

from askwell.config import Settings
from askwell.inference.client import Completion, InferenceFailed, InferenceUnavailable


@pytest.fixture
def settings() -> Settings:
    return Settings(
        database_url="postgresql://askwell:pw@127.0.0.1:1/askwell",  # type: ignore[arg-type]
        redis_host="127.0.0.1",
        redis_port=1,
        worker_health_key="askwell-test:no-such-worker",
        inference_socket=Path("/nonexistent/askwell-test/inference.sock"),
        egress_proxy_host="127.0.0.1",
        egress_proxy_port=1,
        health_probe_timeout_seconds=0.5,
    )


def _suite(*, pass_bar: float = 0.5, tasks: tuple[Task, ...] | None = None) -> Suite:
    return Suite(
        name="fixture",
        category="fixture",
        pass_bar=pass_bar,
        tasks=tasks
        or (
            Task(
                id="t1",
                prompt="say hi",
                scorer="contains_all",
                expected="hi",
                timeout_seconds=1.0,
            ),
        ),
    )


class _FakeClient:
    """Stands in for `InferenceClient`: same `generate` signature, scripted
    replies instead of a socket call."""

    def __init__(self, settings: Settings, replies: Callable[[str], Completion]) -> None:
        del settings
        self._replies = replies

    async def generate(self, prompt: str, *, timeout_seconds: float) -> Completion:
        del timeout_seconds
        return self._replies(prompt)


def _install_fake_client(
    monkeypatch: pytest.MonkeyPatch, replies: Callable[[str], Completion]
) -> None:
    monkeypatch.setattr(runner, "InferenceClient", lambda settings: _FakeClient(settings, replies))


async def test_run_suite_scores_three_runs_per_task(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_client(monkeypatch, lambda prompt: Completion(text="hi there", tokens=2))

    report = await run_suite(settings, _suite())

    assert report.runs_per_task == 3
    assert len(report.task_results) == 1
    assert len(report.task_results[0].runs) == 3
    assert report.category_mean == 1.0
    assert report.category_worst == 1.0
    assert report.passed is None  # not a strict suite


async def test_run_suite_records_per_run_failure_without_aborting(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = {"n": 0}

    def replies(prompt: str) -> Completion:
        calls["n"] += 1
        if calls["n"] == 2:
            raise InferenceFailed("the assistant did not answer within 1s")
        return Completion(text="hi", tokens=1)

    _install_fake_client(monkeypatch, replies)

    report = await run_suite(settings, _suite())

    task = report.task_results[0]
    assert calls["n"] == 3  # all three runs still happened
    failed_runs = [run for run in task.runs if run.error is not None]
    assert len(failed_runs) == 1
    error = failed_runs[0].error
    assert error is not None
    assert "did not answer" in error
    assert task.worst == 0.0
    assert task.mean == pytest.approx(2 / 3)


async def test_run_suite_aborts_on_model_unavailable(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    def replies(prompt: str) -> Completion:
        raise InferenceUnavailable("The assistant is model_missing.")

    _install_fake_client(monkeypatch, replies)

    with pytest.raises(HarnessError, match="model unavailable"):
        await run_suite(settings, _suite())


async def test_strict_suite_reports_pass_only_if_every_run_is_perfect(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = {"n": 0}

    def replies(prompt: str) -> Completion:
        calls["n"] += 1
        # The second run of the second call comes back wrong once.
        text = "wrong" if calls["n"] == 2 else "hi"
        return Completion(text=text, tokens=1)

    _install_fake_client(monkeypatch, replies)

    report = await run_suite(settings, _suite(pass_bar=1.0))

    assert report.strict is True
    assert report.passed is False


async def test_strict_suite_passes_when_every_run_scores_perfectly(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_client(monkeypatch, lambda prompt: Completion(text="hi", tokens=1))

    report = await run_suite(settings, _suite(pass_bar=1.0))

    assert report.passed is True
