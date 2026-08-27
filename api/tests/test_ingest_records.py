"""The ingestion queue against a real Postgres.

Everything this ticket promises that cannot be proved without a database:

*Progress advances per file and survives navigation* — nothing here holds an
HTTP request, because that is the point. A job is claimed, run and finished by
a process that has never heard of the browser.

*A stack restart resumes rather than loses the queue* — `resume` returns a job
a dead worker was holding, and `reconcile` re-dispatches what Redis forgot.

*The source is askable with partial coverage before all files finish* — one
document ready is enough, and the source says so while the rest continue.

*A job that fails is visible with its error and a retry, never silently
dropped* — including that its reason survives, which is why the record is in
Postgres rather than in the queue.

The pipeline has no stages installed yet (extraction is `M1-EXTRACT-ING-026`),
so the tests that need one install their own. That is not a stand-in for the
real thing: what is under test is the harness — claim, progress, failure,
retry, resume — and a test stage is how you assert a harness without also
asserting a PDF library.
"""

import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from askwell import ingest
from askwell.config import Settings
from askwell.ingest import Report, Stage, Work
from askwell.sources import add

pytestmark = pytest.mark.requires_db

TABLES = "roots, sources, documents, ingest_jobs, audit_decisions"

PDF = b"%PDF-1.7\nEither party may terminate on ninety days written notice.\n"
OTHER = b"%PDF-1.7\nThe tenant shall pay rent monthly in advance.\n"
THIRD = b"%PDF-1.7\nThe supplier warrants the goods for twelve months.\n"


@pytest.fixture
def async_url(database_url: str) -> str:
    return database_url.replace("postgresql://", "postgresql+psycopg://", 1)


@pytest_asyncio.fixture
async def factory(async_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(async_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as opened:
        await opened.execute(text(f"TRUNCATE {TABLES} CASCADE"))
        await opened.commit()
    yield sessions
    async with sessions() as opened:
        await opened.execute(text(f"TRUNCATE {TABLES} CASCADE"))
        await opened.commit()
    await engine.dispose()


@pytest_asyncio.fixture
async def session(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with factory() as opened:
        yield opened
        await opened.rollback()


@pytest.fixture
def unreachable_queue(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Iterator[Settings]:
    """Dispatch is a no-op for these tests, and loudly so.

    What is under test is the durable half. Reaching a real Redis would make
    every one of these tests also a test of whether the developer happens to
    have the stack up, and — worse — would hand jobs to a live worker that
    would race the assertions.
    """
    sent: list[uuid.UUID] = []

    async def fake_dispatch(
        _settings: Settings,
        document_ids: list[uuid.UUID],
        **_kwargs: object,
    ) -> int:
        sent.extend(document_ids)
        return len(document_ids)

    monkeypatch.setattr(ingest, "dispatch", fake_dispatch)
    yield settings


async def nominate(session: AsyncSession, path: str) -> None:
    await session.execute(text("INSERT INTO roots (path) VALUES (:path)"), {"path": path})


def written(directory: Path, name: str, body: bytes = PDF) -> str:
    path = directory / name
    path.write_bytes(body)
    return name


async def recorded(session: AsyncSession, folder: Path, *names: str) -> list[uuid.UUID]:
    """Put files through the real add path, so the queue rows are real too."""
    result = await add(session, str(folder), list(names))
    await session.commit()
    return [item.document_id for item in result.files if item.document_id is not None]


# --- enqueueing -------------------------------------------------------------


async def test_recording_a_document_puts_it_on_the_queue(
    session: AsyncSession, tmp_path: Path
) -> None:
    """The add flow's own transaction writes the queue row.

    A document with no job is a file the user was told was queued and which
    nothing will ever pick up — and it would look completely correct in the
    library until someone asked a question about it.
    """
    await nominate(session, str(tmp_path))
    written(tmp_path, "contract.pdf")

    documents = await recorded(session, tmp_path, "contract.pdf")

    assert len(documents) == 1
    row = (
        await session.execute(
            text(
                "SELECT state, attempts, stage, awaiting FROM ingest_jobs WHERE document_id = :id"
            ),
            {"id": documents[0]},
        )
    ).one()
    assert row[0] == "queued"
    assert row[1] == 0
    assert row[2] is None and row[3] is None


async def test_the_queue_keeps_the_order_the_files_arrived_in(
    session: AsyncSession, tmp_path: Path
) -> None:
    """Ordering is `seq`, not `enqueued_at`.

    Every document in one drop is inserted in a single transaction and shares
    `now()` to the microsecond, so a position computed from the timestamp would
    reorder itself between two reads of an unchanged queue.
    """
    await nominate(session, str(tmp_path))
    for name, body in (("a.pdf", PDF), ("b.pdf", OTHER), ("c.pdf", THIRD)):
        written(tmp_path, name, body)

    documents = await recorded(session, tmp_path, "a.pdf", "b.pdf", "c.pdf")

    assert await ingest.pending(session) == documents


async def test_adding_the_same_folder_twice_does_not_queue_a_file_twice(
    session: AsyncSession, tmp_path: Path
) -> None:
    await nominate(session, str(tmp_path))
    written(tmp_path, "contract.pdf")
    documents = await recorded(session, tmp_path, "contract.pdf")

    source = (await session.execute(text("SELECT id FROM sources LIMIT 1"))).scalar_one()
    await ingest.enqueue(session, source, documents)
    await session.commit()

    count = (await session.execute(text("SELECT count(*) FROM ingest_jobs"))).scalar_one()
    assert count == 1


# --- running a job ----------------------------------------------------------


async def test_parking_a_whole_drop_does_not_flap_the_sources_status(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    unreachable_queue: Settings,
) -> None:
    """A source that never left `queued` writes no decisions records.

    With no stage installed a job is claimed and parked inside a millisecond.
    Deriving "indexing" from a job being *claimed* made every such document
    push the source `queued` → `indexing` → `queued` and record both — three
    files producing six audit records describing work that never happened. The
    status is read from the documents instead, and a document is only
    `indexing` once a stage is actually running over it.
    """
    await nominate(session, str(tmp_path))
    for name, body in (("a.pdf", PDF), ("b.pdf", OTHER), ("c.pdf", THIRD)):
        written(tmp_path, name, body)
    documents = await recorded(session, tmp_path, "a.pdf", "b.pdf", "c.pdf")

    for document_id in documents:
        assert await ingest.process(factory, unreachable_queue, document_id) == "parked"

    status = (await session.execute(text("SELECT status FROM sources"))).scalar_one()
    assert status == "queued"

    changes = (
        await session.execute(
            text("SELECT count(*) FROM audit_decisions WHERE kind = :kind"),
            {"kind": ingest.SOURCE_STATUS_CHANGED},
        )
    ).scalar_one()
    assert changes == 0


async def test_a_job_parks_at_the_first_stage_that_has_not_been_built(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    unreachable_queue: Settings,
) -> None:
    """The honest resting place, and the sentence it produces.

    Nothing has read the file, so the document must not be `ready` — that would
    tell retrieval it has passages it does not have, which is the C4 failure
    wearing a progress bar. It must not be `failed` either: nothing is wrong
    with the file. `parked`, naming the stage and its ticket, is what lets the
    surface say what has to arrive before these files are searchable.
    """
    await nominate(session, str(tmp_path))
    written(tmp_path, "contract.pdf")
    documents = await recorded(session, tmp_path, "contract.pdf")

    assert await ingest.process(factory, unreachable_queue, documents[0]) == "parked"

    row = (
        await session.execute(
            text(
                "SELECT j.state, j.awaiting, d.status FROM ingest_jobs j "
                "JOIN documents d ON d.id = j.document_id WHERE j.document_id = :id"
            ),
            {"id": documents[0]},
        )
    ).one()
    assert row[0] == "parked"
    assert row[1] == "extract"
    assert row[2] == "queued"


async def test_an_installed_stage_runs_and_the_document_becomes_ready(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    unreachable_queue: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await nominate(session, str(tmp_path))
    written(tmp_path, "contract.pdf")
    documents = await recorded(session, tmp_path, "contract.pdf")

    seen: list[str] = []

    async def extract(work: Work, report: Report) -> None:
        seen.append(work.filename)
        await report(len(PDF), len(PDF))

    monkeypatch.setattr(ingest, "STAGES", (Stage("extract", "M1-EXTRACT-ING-026", extract),))

    assert await ingest.process(factory, unreachable_queue, documents[0]) == "done"
    assert seen == ["contract.pdf"]

    row = (
        await session.execute(
            text(
                "SELECT j.state, j.stage, d.status, s.status FROM ingest_jobs j "
                "JOIN documents d ON d.id = j.document_id "
                "JOIN sources s ON s.id = j.source_id WHERE j.document_id = :id"
            ),
            {"id": documents[0]},
        )
    ).one()
    assert row[0] == "done"
    assert row[1] == "extract"
    assert row[2] == "ready"
    assert row[3] == "ready"


async def test_progress_moves_inside_a_single_enormous_file(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    unreachable_queue: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A count of "3 of 12" that does not move for two hours looks like a hang.

    The byte figures are read from a *different* session while the stage is
    still running, which is the only way to assert what this is for: somebody
    watching the screen has to see the number change before the file finishes.
    """
    await nominate(session, str(tmp_path))
    written(tmp_path, "scan.pdf")
    documents = await recorded(session, tmp_path, "scan.pdf")

    observed: list[tuple[int | None, int | None]] = []

    async def slow(work: Work, report: Report) -> None:
        for done in (250, 500, 1000):
            await report(done, 1000)
            async with factory() as watcher:
                row = (
                    await watcher.execute(
                        text(
                            "SELECT bytes_done, bytes_total FROM ingest_jobs "
                            "WHERE document_id = :id"
                        ),
                        {"id": work.document_id},
                    )
                ).one()
                observed.append((row[0], row[1]))

    monkeypatch.setattr(ingest, "STAGES", (Stage("extract", "M1-EXTRACT-ING-026", slow),))

    # A clock that always says the interval has elapsed, so the throttle does
    # not swallow the very reports this test exists to see. The throttle itself
    # is asserted separately, in `test_progress_writes_are_throttled`.
    ticks = iter(range(0, 1000))

    assert (
        await ingest.process(
            factory, unreachable_queue, documents[0], clock=lambda: float(next(ticks))
        )
        == "done"
    )
    assert observed == [(250, 1000), (500, 1000), (1000, 1000)]


async def test_progress_writes_are_throttled(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    unreachable_queue: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A write per chunk is thousands of transactions for one large file.

    The first report always lands, because it carries the total and that is
    what turns a spinner into a fraction; the ones after it wait for the
    interval. The final one lands too — `done == total` is what the screen
    needs to stop.
    """
    await nominate(session, str(tmp_path))
    written(tmp_path, "scan.pdf")
    documents = await recorded(session, tmp_path, "scan.pdf")

    async def chatty(work: Work, report: Report) -> None:
        for done in (10, 20, 30, 40):
            await report(done, 100)

    monkeypatch.setattr(ingest, "STAGES", (Stage("extract", "M1-EXTRACT-ING-026", chatty),))
    await ingest.process(factory, unreachable_queue, documents[0], clock=lambda: 1.0)

    # `state = 'running'` guards the write, so the row after the job finishes
    # carries whatever the last accepted report said — which here is only the
    # first, because the frozen clock never lets the interval elapse.
    row = (
        await session.execute(
            text("SELECT bytes_done FROM ingest_jobs WHERE document_id = :id"),
            {"id": documents[0]},
        )
    ).one()
    assert row[0] == 10


async def test_a_failing_stage_is_retried_and_then_left_failed_with_its_reason(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    unreachable_queue: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Never silently dropped — `AGENTS.md` §6, and the ticket says so twice.

    The reason is written to Postgres rather than left in the queue because the
    thing the library has to render — this file, this error, a retry — has to
    survive a flushed Redis.
    """
    await nominate(session, str(tmp_path))
    written(tmp_path, "broken.pdf")
    documents = await recorded(session, tmp_path, "broken.pdf")

    async def always_fails(work: Work, report: Report) -> None:
        raise ValueError("the text layer is not readable")

    monkeypatch.setattr(ingest, "STAGES", (Stage("extract", "M1-EXTRACT-ING-026", always_fails),))

    for _ in range(ingest.MAX_ATTEMPTS):
        assert await ingest.process(factory, unreachable_queue, documents[0]) == "failed"

    row = (
        await session.execute(
            text(
                "SELECT j.state, j.attempts, j.error, j.stage, d.status, s.status "
                "FROM ingest_jobs j JOIN documents d ON d.id = j.document_id "
                "JOIN sources s ON s.id = j.source_id WHERE j.document_id = :id"
            ),
            {"id": documents[0]},
        )
    ).one()
    assert row[0] == "failed"
    assert row[1] == ingest.MAX_ATTEMPTS
    assert "the text layer is not readable" in row[2]
    assert row[3] == "extract"
    assert row[4] == "attention"
    assert row[5] == "attention"


async def test_a_failed_document_can_be_retried_and_its_attempts_are_forgiven(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    unreachable_queue: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The user reconnected the drive. Starting from the third attempt would
    fail the document again on the first hiccup and teach them the retry does
    not work.
    """
    await nominate(session, str(tmp_path))
    written(tmp_path, "broken.pdf")
    documents = await recorded(session, tmp_path, "broken.pdf")

    async def always_fails(work: Work, report: Report) -> None:
        raise OSError("the drive is not connected")

    monkeypatch.setattr(ingest, "STAGES", (Stage("extract", "M1-EXTRACT-ING-026", always_fails),))
    for _ in range(ingest.MAX_ATTEMPTS):
        await ingest.process(factory, unreachable_queue, documents[0])

    outcome = await ingest.retry(session, documents[0])
    await session.commit()

    assert outcome.retried
    assert outcome.state == "queued"
    assert outcome.source_id is not None
    row = (
        await session.execute(
            text(
                "SELECT j.state, j.attempts, j.error, d.status FROM ingest_jobs j "
                "JOIN documents d ON d.id = j.document_id WHERE j.document_id = :id"
            ),
            {"id": documents[0]},
        )
    ).one()
    assert row[0] == "queued"
    assert row[1] == 0
    assert row[2] is None
    assert row[3] == "queued"


async def test_retrying_something_that_did_not_fail_is_refused_by_name(
    session: AsyncSession, tmp_path: Path
) -> None:
    await nominate(session, str(tmp_path))
    written(tmp_path, "contract.pdf")
    documents = await recorded(session, tmp_path, "contract.pdf")

    already_queued = await ingest.retry(session, documents[0])
    assert not already_queued.retried
    assert already_queued.state == "queued"

    unknown = await ingest.retry(session, uuid.uuid4())
    assert not unknown.retried
    assert unknown.state is None


async def test_a_document_deleted_before_its_job_ran_is_not_a_failure(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    unreachable_queue: Settings,
) -> None:
    """Nothing is wrong; there is simply nothing to do.

    Recording it as failed would put a red row in the library for a document
    the user themselves removed.
    """
    await nominate(session, str(tmp_path))
    written(tmp_path, "contract.pdf")
    documents = await recorded(session, tmp_path, "contract.pdf")

    await session.execute(
        text("UPDATE documents SET deleted_at = now() WHERE id = :id"), {"id": documents[0]}
    )
    await session.commit()

    assert await ingest.process(factory, unreachable_queue, documents[0]) == "unclaimable"
    count = (await session.execute(text("SELECT count(*) FROM ingest_jobs"))).scalar_one()
    assert count == 0


# --- surviving a restart ----------------------------------------------------


async def test_a_restart_returns_an_interrupted_job_to_the_queue(
    session: AsyncSession, tmp_path: Path
) -> None:
    """The laptop closed mid-import. That is a normal Tuesday, not an error.

    `attempts` is given back as well: a document is not made harder to read by
    the machine having been suspended, and spending a retry on each interruption
    would eventually mark a perfectly good file as failed for having been
    interrupted three times.
    """
    await nominate(session, str(tmp_path))
    written(tmp_path, "contract.pdf")
    documents = await recorded(session, tmp_path, "contract.pdf")

    await session.execute(
        text(
            "UPDATE ingest_jobs SET state = 'running', started_at = now(), attempts = 1 "
            "WHERE document_id = :id"
        ),
        {"id": documents[0]},
    )
    await session.commit()

    assert await ingest.resume(session) == 1
    await session.commit()

    row = (
        await session.execute(
            text("SELECT state, attempts, started_at FROM ingest_jobs WHERE document_id = :id"),
            {"id": documents[0]},
        )
    ).one()
    assert row[0] == "queued"
    assert row[1] == 0
    assert row[2] is None


async def test_reconcile_re_dispatches_work_the_queue_forgot(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    unreachable_queue: Settings,
) -> None:
    """The repair path: a flushed Redis, a failed enqueue, a machine that slept.

    Nothing about the rows changes — they were always the record. What
    reconcile does is tell a worker they are there.
    """
    await nominate(session, str(tmp_path))
    for name, body in (("a.pdf", PDF), ("b.pdf", OTHER)):
        written(tmp_path, name, body)
    documents = await recorded(session, tmp_path, "a.pdf", "b.pdf")

    assert await ingest.reconcile(factory, unreachable_queue) == 2
    assert await ingest.pending(session) == documents


async def test_a_refused_job_id_does_not_strand_a_document_forever(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """arq refusing an id is not proof the job is queued.

    A worker killed hard leaves its job key behind, and a job that merely
    finished leaves its result key. arq refuses both, and cannot say which it
    is. Before this, every reconcile after such a kill asked for the same id,
    was refused, and reported success having done nothing — the document sat
    `queued` for up to `job_timeout` with nothing anywhere saying why.
    """
    await nominate(session, str(tmp_path))
    written(tmp_path, "a.pdf", PDF)
    documents = await recorded(session, tmp_path, "a.pdf")

    # The row has been waiting far longer than a few reconciles.
    await session.execute(
        text("UPDATE ingest_jobs SET enqueued_at = now() - make_interval(secs => 600)")
    )
    await session.commit()

    calls: list[bool] = []

    async def refusing_dispatch(
        _settings: Settings,
        document_ids: list[uuid.UUID],
        **kwargs: object,
    ) -> int:
        unique = bool(kwargs.get("unique", True))
        calls.append(unique)
        # This is arq's behaviour, not an error: an id it still holds is
        # declined silently, and an enqueue with no id always lands.
        return 0 if unique else len(document_ids)

    monkeypatch.setattr(ingest, "dispatch", refusing_dispatch)

    assert await ingest.reconcile(factory, settings) == 1
    assert calls == [True, False], (
        "it should retry without an id once the first pass came back short"
    )
    assert await ingest.pending(session) == documents, (
        "the row is untouched; only the telling changed"
    )


async def test_a_freshly_queued_document_is_never_dispatched_twice(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The escalation is for ghosts, not for a queue that is simply busy.

    A document enqueued moments ago and refused is refused because it really is
    queued. Dispatching it again without an id would put a second job on the
    queue for every waiting document twice a minute for the length of an import.
    """
    await nominate(session, str(tmp_path))
    written(tmp_path, "a.pdf", PDF)
    await recorded(session, tmp_path, "a.pdf")

    calls: list[bool] = []

    async def refusing_dispatch(
        _settings: Settings,
        document_ids: list[uuid.UUID],
        **kwargs: object,
    ) -> int:
        calls.append(bool(kwargs.get("unique", True)))
        return 0

    monkeypatch.setattr(ingest, "dispatch", refusing_dispatch)

    assert await ingest.reconcile(factory, settings) == 0
    assert calls == [True], "a row queued seconds ago is not a ghost"


# --- partial coverage -------------------------------------------------------


async def test_a_source_is_askable_before_every_file_has_finished(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    unreachable_queue: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ticket's own scenario, at three files instead of five hundred.

    One document indexed is enough to answer from. Waiting for the whole import
    before anything can be asked is the behaviour this ticket exists to remove.
    """
    await nominate(session, str(tmp_path))
    for name, body in (("a.pdf", PDF), ("b.pdf", OTHER), ("c.pdf", THIRD)):
        written(tmp_path, name, body)
    documents = await recorded(session, tmp_path, "a.pdf", "b.pdf", "c.pdf")

    async def extract(work: Work, report: Report) -> None:
        await report(1, 1)

    monkeypatch.setattr(ingest, "STAGES", (Stage("extract", "M1-EXTRACT-ING-026", extract),))
    await ingest.process(factory, unreachable_queue, documents[0])

    source_id = (await session.execute(text("SELECT id FROM sources LIMIT 1"))).scalar_one()
    partial = await ingest.coverage(session, source_id)

    assert partial.ready == 1
    assert partial.total == 3
    assert partial.askable

    status = (
        await session.execute(text("SELECT status FROM sources WHERE id = :id"), {"id": source_id})
    ).scalar_one()
    assert status == "indexing"


async def test_a_source_changing_status_is_a_decisions_record(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    unreachable_queue: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """What Askwell will answer from changed. `docs/audit-log.md` §2.

    Only on an actual change: a record per completed job would be five hundred
    rows saying the same thing about one import.
    """
    await nominate(session, str(tmp_path))
    for name, body in (("a.pdf", PDF), ("b.pdf", OTHER)):
        written(tmp_path, name, body)
    documents = await recorded(session, tmp_path, "a.pdf", "b.pdf")

    async def extract(work: Work, report: Report) -> None:
        await report(1, 1)

    monkeypatch.setattr(ingest, "STAGES", (Stage("extract", "M1-EXTRACT-ING-026", extract),))
    for document_id in documents:
        await ingest.process(factory, unreachable_queue, document_id)

    rows = (
        await session.execute(
            text("SELECT payload FROM audit_decisions WHERE kind = :kind ORDER BY occurred_at"),
            {"kind": ingest.SOURCE_STATUS_CHANGED},
        )
    ).all()

    # Two changes, and the counts at the moment each was made. The first is
    # recorded when the first job starts, so nothing is ready yet — which is
    # the point of storing the counts rather than only the status: "indexing"
    # on its own does not say how much of the source that covers.
    assert [(row[0]["to"], row[0]["ready"], row[0]["total"]) for row in rows] == [
        ("indexing", 0, 2),
        ("ready", 2, 2),
    ]


# --- the snapshot -----------------------------------------------------------


async def test_the_estimate_refuses_to_invent_a_number_before_anything_finishes(
    session: AsyncSession, tmp_path: Path, settings: Settings
) -> None:
    """The known gap the backlog names, answered rather than papered over.

    On a first import there is no throughput history, so any figure would be
    made up — and somebody plans their afternoon around it. `null` with a
    stated basis is the honest answer.
    """
    await nominate(session, str(tmp_path))
    written(tmp_path, "contract.pdf")
    await recorded(session, tmp_path, "contract.pdf")

    state = await ingest.snapshot(session, settings)

    assert state["estimate"]["seconds"] is None
    assert "invented" in state["estimate"]["basis"]


async def test_the_snapshot_reports_queue_position_and_what_is_being_waited_for(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    settings: Settings,
    unreachable_queue: Settings,
) -> None:
    """Position, because "queued behind a backlog" needs a number to be honest,
    and `awaiting`, because "nothing is happening" and "nothing is happening,
    and here is what has to arrive first" are different sentences.
    """
    await nominate(session, str(tmp_path))
    for name, body in (("a.pdf", PDF), ("b.pdf", OTHER), ("c.pdf", THIRD)):
        written(tmp_path, name, body)
    documents = await recorded(session, tmp_path, "a.pdf", "b.pdf", "c.pdf")

    await ingest.process(factory, unreachable_queue, documents[0])
    state = await ingest.snapshot(session, settings)

    assert [item["position"] for item in state["next"]] == [1, 2]
    assert [item["filename"] for item in state["next"]] == ["b.pdf", "c.pdf"]
    assert state["queue_length"] == 2
    assert state["awaiting"] == {
        "stage": "extract",
        "ticket": "M1-EXTRACT-ING-026",
        "documents": 1,
    }
    assert state["sources"][0]["askable"] is False


async def test_the_snapshot_counts_are_this_machines_own_and_nothing_leaves_it(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    tmp_path: Path,
    settings: Settings,
    unreachable_queue: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C1. The counters the ticket asks for are read out of this database by
    this machine's browser; there is nowhere for them to be transmitted to and
    no code here that could.
    """
    await nominate(session, str(tmp_path))
    for name, body in (("a.pdf", PDF), ("b.pdf", OTHER)):
        written(tmp_path, name, body)
    documents = await recorded(session, tmp_path, "a.pdf", "b.pdf")

    async def extract(work: Work, report: Report) -> None:
        if work.filename == "b.pdf":
            raise ValueError("encrypted")
        await report(1, 1)

    monkeypatch.setattr(ingest, "STAGES", (Stage("extract", "M1-EXTRACT-ING-026", extract),))
    await ingest.process(factory, unreachable_queue, documents[0])
    for _ in range(ingest.MAX_ATTEMPTS):
        await ingest.process(factory, unreachable_queue, documents[1])

    state = await ingest.snapshot(session, settings)

    assert state["documents_ingested"] == 1
    assert state["documents_failed"] == 1
    assert state["failures"][0]["filename"] == "b.pdf"
    assert "encrypted" in state["failures"][0]["error"]
