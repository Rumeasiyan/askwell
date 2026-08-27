"""The ingestion pipeline's rules, without a database.

Three of them, and each is a claim the ticket makes rather than an
implementation detail.

**A source's status is derived, not set.** `M1-ADD-ING-025` asks for a source
that becomes askable with partial coverage before its import finishes, which
means "eighty of five hundred ready" has to produce a status and a marker that
are both true at once. The function that decides is pure, so the cases that
matter — nothing started, half done, all done, all done with some failures —
can be asserted directly rather than assembled out of rows.

**A stage that does not exist is declared, not omitted.** Extraction, chunking
and embedding are separate tickets. What this ticket owns is that a document
waiting for one of them can say which one, so the pipeline names all three and
installs none.

**Dispatch failing is a delay, never a loss.** The queue rows are committed
before anything is dispatched, so a Redis that is not there costs one reconcile
interval. This is asserted against a port that refuses, which is also how it
stays a test that touches no network.
"""

import asyncio

import pytest

from askwell import ingest, worker
from askwell.config import Settings


def test_a_source_with_no_documents_is_queued_rather_than_ready() -> None:
    """Zero of zero is not "finished". It is "nothing has arrived"."""
    assert ingest.source_status(total=0, ready=0, running=0, outstanding=0, failed=0) == "queued"


def test_a_source_whose_documents_are_all_ready_is_ready() -> None:
    assert ingest.source_status(total=5, ready=5, running=0, outstanding=0, failed=0) == "ready"


def test_a_source_part_way_through_is_indexing_rather_than_queued() -> None:
    """The partly-indexed state. Eighty of five hundred is work in progress."""
    assert ingest.source_status(total=500, ready=80, running=2, outstanding=420, failed=0) == (
        "indexing"
    )


def test_a_source_with_work_outstanding_and_nothing_indexed_is_queued() -> None:
    """The state a fresh add is actually in, and the one it must not overstate.

    `docs/states-and-edge-cases.md` §3: "files queued but nothing indexed yet"
    is an honest sentence, and `indexing` is what the library renders as a
    progress bar for work that has not started.
    """
    assert ingest.source_status(total=12, ready=0, running=0, outstanding=12, failed=0) == "queued"


def test_a_source_that_finished_with_failures_and_nothing_readable_needs_attention() -> None:
    assert ingest.source_status(total=3, ready=0, running=0, outstanding=0, failed=3) == (
        "attention"
    )


def test_a_source_that_finished_with_some_failures_needs_attention_and_stays_askable() -> None:
    """Two facts at once, and neither may be dropped.

    Fifty-eight of sixty contracts are readable, so the source is askable and
    answers must come from them. Two are not, and `attention` is the only place
    the library has to say which two and offer the retry — a source rendered
    `ready` gives the user nothing to click and nothing to notice.
    """
    assert ingest.source_status(total=60, ready=58, running=0, outstanding=0, failed=2) == (
        "attention"
    )
    assert ingest.Coverage(total=60, ready=58, failed=2, running=0, outstanding=0).askable


def test_one_indexed_document_makes_a_source_askable() -> None:
    """The partial-coverage marker. Waiting for all five hundred is the bug."""
    partial = ingest.Coverage(total=500, ready=80, failed=0, running=2, outstanding=420)
    assert partial.askable
    assert partial.as_dict()["fraction"] == pytest.approx(0.16)


def test_a_source_with_nothing_indexed_is_not_askable() -> None:
    assert not ingest.Coverage(total=12, ready=0, failed=0, running=0, outstanding=12).askable


def test_the_whole_pipeline_is_declared_even_though_none_of_it_is_built() -> None:
    """Naming the missing steps is what lets a queued file explain itself.

    If this list is ever trimmed to "what exists", a document waiting on
    extraction goes back to sitting at `queued` with no way to say so.
    """
    assert [stage.name for stage in ingest.STAGES] == ["extract", "chunk", "embed"]
    assert all(stage.ticket for stage in ingest.STAGES)


def test_no_stage_is_installed_yet_and_the_module_does_not_pretend_otherwise() -> None:
    """Delete this test when extraction lands. Do not delete the assertion it
    guards: `installed()` is what `process` walks, and a stage that reports
    itself built while doing nothing would mark documents `ready` that nothing
    has read — which is the C4 failure, dressed as progress.
    """
    assert ingest.installed() == ()


def test_a_queue_that_cannot_be_reached_delays_rather_than_loses(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    """Port 1 on loopback refuses immediately. Nothing raises, nothing is lost.

    The rows are already committed by the time this is called, so the worst
    case is that the worker picks them up on its next reconcile instead of now
    — and turning that into a failed request would tell the user their add did
    not work when it did.
    """
    import uuid

    sent = asyncio.run(ingest.dispatch(settings, [uuid.uuid4()]))
    assert sent == 0


def test_the_worker_offers_the_ingest_job_to_the_queue() -> None:
    """A job the worker does not register is a queue that fills and never drains."""
    assert worker.ingest_document in worker.WorkerSettings.functions


def test_concurrency_and_the_job_timeout_come_from_configuration(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both are properties of the machine, not of the code.

    The ceiling is the point: this laptop is also running the user's browser,
    and a worker that takes every core is an import that gets killed. The
    timeout matters in the other direction — OCR over a 900-page scan is
    genuinely an hour, and the queue's five-minute default would call a slow
    file a failed one.
    """
    captured: dict[str, object] = {}

    class Fake:
        def run(self) -> None:
            return None

    def fake_create_worker(settings_cls: object, **kwargs: object) -> Fake:
        captured.update(kwargs)
        return Fake()

    import arq.worker

    monkeypatch.setattr(arq.worker, "create_worker", fake_create_worker)
    monkeypatch.setattr(
        worker, "load_settings", lambda: settings.model_copy(update={"ingest_concurrency": 3})
    )

    worker.main()

    assert captured["max_jobs"] == 3
    assert captured["job_timeout"] == settings.ingest_job_timeout_seconds
    assert captured["cron_jobs"]


def test_a_retry_is_not_deduplicated_against_the_attempt_it_is_retrying(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bug this guards is silent, which is why it has a test.

    `arq` refuses a job id it has seen recently, and a retry forgives the
    attempt count — so the id a retry would otherwise reuse is exactly the one
    the failed attempt already burned. The API would answer 202 and nothing
    would run until the next reconcile. Reconcile itself keeps its id, because
    without one it would pile a fresh job onto the queue for every waiting
    document twice a minute.
    """
    import uuid

    ids: list[str | None] = []

    class FakePool:
        async def enqueue_job(self, _function: str, *_args: object, **kwargs: object) -> object:
            ids.append(kwargs.get("_job_id"))  # type: ignore[arg-type]
            return object()

        async def aclose(self) -> None:
            return None

    async def fake_pool(_settings: object) -> FakePool:
        return FakePool()

    monkeypatch.setattr("arq.create_pool", fake_pool)
    document = uuid.uuid4()

    asyncio.run(ingest.dispatch(settings, [document]))
    asyncio.run(ingest.dispatch(settings, [document], unique=False))

    assert ids == [f"ingest:{document}:0", None]
