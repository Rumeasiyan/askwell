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


def test_a_source_with_a_flagged_document_needs_attention_even_though_all_ready() -> None:
    """`M1-EXTRACT-ING-029`: low-confidence OCR is never a failure, but the
    library still has to say so — a source that is otherwise wholly ready
    still has one document that read poorly."""
    assert (
        ingest.source_status(total=20, ready=20, running=0, outstanding=0, failed=0, flagged=1)
        == "attention"
    )


def test_a_flagged_document_does_not_wait_for_the_rest_of_the_import() -> None:
    """Unlike a failure, a flag does not need `outstanding == 0` first — the
    flagged document is already `ready`, and the rest of the source can still
    be indexing."""
    assert (
        ingest.source_status(total=20, ready=5, running=1, outstanding=15, failed=0, flagged=1)
        == "attention"
    )


def test_a_source_with_no_flagged_documents_is_unaffected() -> None:
    assert (
        ingest.source_status(total=5, ready=5, running=0, outstanding=0, failed=0, flagged=0)
        == "ready"
    )


def test_the_attention_reason_names_both_causes_when_both_are_true() -> None:
    assert (
        ingest._attention_reason(failed=2, flagged=1, missing=0, total=60)
        == "2 of 60 files could not be indexed. 1 file scanned poorly and may be hard to search."
    )


def test_the_attention_reason_is_singular_for_one_flagged_file() -> None:
    assert (
        ingest._attention_reason(failed=0, flagged=1, missing=0, total=20)
        == "1 file scanned poorly and may be hard to search."
    )


def test_the_attention_reason_is_plural_for_more_than_one() -> None:
    assert (
        ingest._attention_reason(failed=0, flagged=3, missing=0, total=20)
        == "3 files scanned poorly and may be hard to search."
    )


def test_the_attention_reason_is_none_when_nothing_is_wrong() -> None:
    assert ingest._attention_reason(failed=0, flagged=0, missing=0, total=20) is None


def test_the_attention_reason_names_a_moved_file_singular() -> None:
    assert (
        ingest._attention_reason(failed=0, flagged=0, missing=1, total=20)
        == "1 file moved or renamed and needs relocating."
    )


def test_the_attention_reason_names_moved_files_plural() -> None:
    assert (
        ingest._attention_reason(failed=0, flagged=0, missing=2, total=20)
        == "2 files moved or renamed and need relocating."
    )


def test_a_source_with_a_missing_file_needs_attention() -> None:
    assert (
        ingest.source_status(total=5, ready=5, running=0, outstanding=0, failed=0, missing=1)
        == "attention"
    )


def test_one_indexed_document_makes_a_source_askable() -> None:
    """The partial-coverage marker. Waiting for all five hundred is the bug."""
    partial = ingest.Coverage(total=500, ready=80, failed=0, running=2, outstanding=420)
    assert partial.askable
    assert partial.as_dict()["fraction"] == pytest.approx(0.16)


def test_a_source_with_nothing_indexed_is_not_askable() -> None:
    assert not ingest.Coverage(total=12, ready=0, failed=0, running=0, outstanding=12).askable


def test_coverage_carries_the_flagged_count_in_its_dict() -> None:
    covered = ingest.Coverage(total=20, ready=20, failed=0, running=0, outstanding=0, flagged=1)
    assert covered.as_dict()["flagged"] == 1
    # Still askable and still ready-ish by every other measure — flagged is
    # additive information, not a subtraction from what already works.
    assert covered.askable


def test_the_whole_pipeline_is_declared_even_where_it_is_not_yet_built() -> None:
    """Naming the missing steps is what lets a queued file explain itself.

    If this list is ever trimmed to "what exists", a document waiting on
    chunking goes back to sitting at `queued` with no way to say so.
    """
    assert [stage.name for stage in ingest.STAGES] == ["extract", "chunk", "embed"]
    assert all(stage.ticket for stage in ingest.STAGES)


def test_every_stage_is_installed() -> None:
    """`installed()` is what `process` walks, and a stage that reports itself
    built while doing nothing would mark documents `ready` that nothing has
    read — which is the C4 failure, dressed as progress. `M1-EXTRACT-ING-026`
    installed `extract`, `M1-INDEX-ING-031` installed `chunk`, and
    `M1-INDEX-ING-032` installs `embed` — the last of the three, so `parked`
    no longer happens in the ordinary run of things (the mechanism itself
    stays; see `askwell.ingest`'s own module docstring).
    """
    assert [stage.name for stage in ingest.installed()] == ["extract", "chunk", "embed"]


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
