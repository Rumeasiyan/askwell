"""Re-processing what an answered clarification affects. `M3-APPLY-ING-080`.

Against a real Postgres, like `test_review.py` — dependency resolution,
de-duplication and the item state machine all depend on real SQL and real
transaction boundaries. `run_job` needs its own `factory` fixture (not a
single `session`) because it opens several short transactions itself, the
same reason `test_citation_check.py` does.
"""

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from askwell import reapply
from askwell.config import Settings
from askwell.inference.client import InferenceClient

pytestmark = pytest.mark.requires_db

TABLES = (
    "sources, documents, chunks, schema_notes, clarifications, memory, "
    "reapply_jobs, reapply_items, audit_decisions"
)


@pytest_asyncio.fixture
async def factory(database_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    async_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
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
async def session(factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with factory() as opened:
        yield opened
        await opened.rollback()


@pytest.fixture
def settings() -> Settings:
    return Settings(
        database_url="postgresql://askwell:pw@127.0.0.1:1/askwell",  # type: ignore[arg-type]
        sandbox_database_url="postgresql://x:x@127.0.0.1:1/postgres",  # type: ignore[arg-type]
        sandbox_owner_password="x",  # type: ignore[arg-type]
        sandbox_readonly_password="x",  # type: ignore[arg-type]
        redis_host="127.0.0.1",
        redis_port=1,
    )


async def _source(session: AsyncSession, name: str) -> uuid.UUID:
    source_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO sources (id, kind, name, status, added_at) "
            "VALUES (:id, 'file', :name, 'ready', now())"
        ),
        {"id": source_id, "name": name},
    )
    return source_id


async def _document(session: AsyncSession, source_id: uuid.UUID, filename: str) -> uuid.UUID:
    document_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO documents (id, source_id, filename, path, sha256, status) "
            "VALUES (:id, :source_id, :filename, :path, :sha256, 'ready')"
        ),
        {
            "id": document_id,
            "source_id": source_id,
            "filename": filename,
            "path": f"/tmp/{filename}",
            "sha256": uuid.uuid4().hex,
        },
    )
    return document_id


async def _chunk(
    session: AsyncSession, document_id: uuid.UUID, *, ordinal: int = 0, content: str = "hello"
) -> uuid.UUID:
    chunk_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO chunks (id, document_id, ordinal, content) "
            "VALUES (:id, :document_id, :ordinal, :content)"
        ),
        {"id": chunk_id, "document_id": document_id, "ordinal": ordinal, "content": content},
    )
    return chunk_id


async def _schema_note(
    session: AsyncSession,
    source_id: uuid.UUID,
    *,
    table_name: str = "students",
    column_name: str | None = "st_cd",
    origin: str = "inferred",
    description: str = "a guess",
) -> uuid.UUID:
    note_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO schema_notes "
            "(id, source_id, table_name, column_name, description, origin) "
            "VALUES (:id, :source_id, :table_name, :column_name, :description, :origin)"
        ),
        {
            "id": note_id,
            "source_id": source_id,
            "table_name": table_name,
            "column_name": column_name,
            "description": description,
            "origin": origin,
        },
    )
    return note_id


async def _clarification(
    session: AsyncSession, source_id: uuid.UUID, *, subject: str = "RFQ", status: str = "pending"
) -> uuid.UUID:
    clarification_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO clarifications (id, source_id, subject, question, status) "
            "VALUES (:id, :source_id, :subject, :question, :status)"
        ),
        {
            "id": clarification_id,
            "source_id": source_id,
            "subject": subject,
            "question": f"What does {subject} mean?",
            "status": status,
        },
    )
    return clarification_id


async def _memory_fact(session: AsyncSession, *, subject: str, fact: str) -> uuid.UUID:
    memory_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO memory (id, subject, fact, origin, confidence) "
            "VALUES (:id, :subject, :fact, 'clarification', 1.0)"
        ),
        {"id": memory_id, "subject": subject, "fact": fact},
    )
    return memory_id


# --- dependency resolution ---------------------------------------------------


@pytest.mark.asyncio
async def test_resolves_every_chunk_of_every_live_document_when_nothing_is_named(
    session: AsyncSession,
) -> None:
    source_id = await _source(session, "contracts")
    clarification_id = await _clarification(session, source_id, subject="RFQ")
    document_id = await _document(session, source_id, "a.pdf")
    chunk_a = await _chunk(session, document_id, ordinal=0)
    chunk_b = await _chunk(session, document_id, ordinal=1)

    dependencies = await reapply.resolve_dependencies(
        session,
        source_id=source_id,
        subject="RFQ",
        evidence=None,
        options=None,
        clarification_id=clarification_id,
    )

    chunk_ids = {d.target_id for d in dependencies if d.kind == "chunk"}
    assert chunk_ids == {chunk_a, chunk_b}


@pytest.mark.asyncio
async def test_resolves_only_the_documents_named_in_evidence(session: AsyncSession) -> None:
    source_id = await _source(session, "contracts")
    clarification_id = await _clarification(session, source_id, subject="RFQ")
    named = await _document(session, source_id, "named.pdf")
    other = await _document(session, source_id, "other.pdf")
    named_chunk = await _chunk(session, named, ordinal=0)
    await _chunk(session, other, ordinal=0)

    dependencies = await reapply.resolve_dependencies(
        session,
        source_id=source_id,
        subject="RFQ",
        evidence={"kind": "passage", "samples": [{"document": "named.pdf"}]},
        options=None,
        clarification_id=clarification_id,
    )

    chunk_ids = {d.target_id for d in dependencies if d.kind == "chunk"}
    assert chunk_ids == {named_chunk}


@pytest.mark.asyncio
async def test_matches_an_inferred_schema_note_by_column_name_case_insensitively(
    session: AsyncSession,
) -> None:
    source_id = await _source(session, "sis")
    clarification_id = await _clarification(session, source_id, subject="st_cd")
    inferred = await _schema_note(session, source_id, column_name="st_cd", origin="inferred")
    await _schema_note(session, source_id, column_name="other_col", origin="inferred")

    dependencies = await reapply.resolve_dependencies(
        session,
        source_id=source_id,
        subject="ST_CD",
        evidence=None,
        options=None,
        clarification_id=clarification_id,
    )

    note_ids = {d.target_id for d in dependencies if d.kind == "schema_note"}
    assert note_ids == {inferred}


@pytest.mark.asyncio
async def test_never_touches_a_user_supplied_schema_note(session: AsyncSession) -> None:
    source_id = await _source(session, "sis")
    clarification_id = await _clarification(session, source_id, subject="st_cd")
    await _schema_note(session, source_id, column_name="st_cd", origin="user")

    dependencies = await reapply.resolve_dependencies(
        session,
        source_id=source_id,
        subject="st_cd",
        evidence=None,
        options=None,
        clarification_id=clarification_id,
    )

    assert [d for d in dependencies if d.kind == "schema_note"] == []


@pytest.mark.asyncio
async def test_finds_another_pending_clarification_with_the_same_subject_as_a_conflict(
    session: AsyncSession,
) -> None:
    source_a = await _source(session, "a")
    source_b = await _source(session, "b")
    this_one = await _clarification(session, source_a, subject="RFQ")
    stale = await _clarification(session, source_b, subject="rfq")

    dependencies = await reapply.resolve_dependencies(
        session,
        source_id=source_a,
        subject="RFQ",
        evidence=None,
        options=None,
        clarification_id=this_one,
    )

    conflict_ids = {d.target_id for d in dependencies if d.kind == "conflict"}
    assert conflict_ids == {stale}


@pytest.mark.asyncio
async def test_a_subject_touching_nothing_resolves_to_no_dependencies(
    session: AsyncSession,
) -> None:
    source_id = await _source(session, "empty")
    clarification_id = await _clarification(session, source_id, subject="unused")

    dependencies = await reapply.resolve_dependencies(
        session,
        source_id=source_id,
        subject="unused",
        evidence=None,
        options=None,
        clarification_id=clarification_id,
    )

    assert dependencies == []


# --- enqueue and de-duplication ----------------------------------------------


@pytest.mark.asyncio
async def test_enqueue_returns_none_and_writes_nothing_when_there_is_no_dependency(
    session: AsyncSession,
) -> None:
    source_id = await _source(session, "empty")
    clarification_id = await _clarification(session, source_id, subject="unused")
    memory_id = await _memory_fact(session, subject="unused", fact="nothing to say")

    job_id = await reapply.enqueue(
        session,
        subject="unused",
        source_id=source_id,
        evidence=None,
        options=None,
        clarification_id=clarification_id,
        memory_id=memory_id,
    )

    assert job_id is None
    rows = (await session.execute(text("SELECT id FROM reapply_jobs"))).all()
    assert rows == []


@pytest.mark.asyncio
async def test_enqueue_writes_a_job_and_one_item_per_dependency(session: AsyncSession) -> None:
    source_id = await _source(session, "contracts")
    clarification_id = await _clarification(session, source_id, subject="RFQ")
    memory_id = await _memory_fact(session, subject="RFQ", fact="Request for quotation")
    document_id = await _document(session, source_id, "a.pdf")
    await _chunk(session, document_id, ordinal=0)
    await _chunk(session, document_id, ordinal=1)

    job_id = await reapply.enqueue(
        session,
        subject="RFQ",
        source_id=source_id,
        evidence=None,
        options=None,
        clarification_id=clarification_id,
        memory_id=memory_id,
    )
    await session.commit()

    assert job_id is not None
    job = (
        await session.execute(
            text("SELECT total_items, status FROM reapply_jobs WHERE id = :id"), {"id": job_id}
        )
    ).first()
    assert job is not None
    assert job[0] == 2
    assert job[1] == "queued"

    kinds = (
        await session.execute(
            text("SELECT kind FROM reapply_items WHERE job_id = :id"), {"id": job_id}
        )
    ).all()
    assert sorted(row[0] for row in kinds) == ["chunk", "chunk"]


@pytest.mark.asyncio
async def test_two_answers_naming_the_same_chunk_enqueue_it_once(session: AsyncSession) -> None:
    source_id = await _source(session, "contracts")
    document_id = await _document(session, source_id, "a.pdf")
    await _chunk(session, document_id, ordinal=0)

    first_clarification = await _clarification(session, source_id, subject="RFQ")
    first_memory = await _memory_fact(session, subject="RFQ", fact="Request for quotation")
    first_job = await reapply.enqueue(
        session,
        subject="RFQ",
        source_id=source_id,
        evidence=None,
        options=None,
        clarification_id=first_clarification,
        memory_id=first_memory,
    )

    second_clarification = await _clarification(session, source_id, subject="PO", status="pending")
    second_memory = await _memory_fact(session, subject="PO", fact="Purchase order")
    second_job = await reapply.enqueue(
        session,
        subject="PO",
        source_id=source_id,
        evidence=None,
        options=None,
        clarification_id=second_clarification,
        memory_id=second_memory,
    )
    await session.commit()

    assert first_job is not None
    # The chunk is already `pending` under the first job — the second job has
    # nothing left of its own and is marked done immediately rather than left
    # `queued` for zero items.
    second_status = (
        await session.execute(
            text("SELECT status, total_items FROM reapply_jobs WHERE id = :id"), {"id": second_job}
        )
    ).first()
    assert second_status is not None
    assert second_status == ("done", 0)

    item_count = (await session.execute(text("SELECT count(*) FROM reapply_items"))).scalar_one()
    assert item_count == 1


# --- running a job ------------------------------------------------------


@pytest.mark.asyncio
async def test_run_job_re_embeds_a_chunk(
    factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_embed(
        self: InferenceClient, texts: list[str], **kwargs: object
    ) -> list[list[float]]:
        return [[0.5] * settings.embedding_dimensions for _ in texts]

    monkeypatch.setattr(InferenceClient, "embed", fake_embed)

    async with factory() as session:
        source_id = await _source(session, "contracts")
        document_id = await _document(session, source_id, "a.pdf")
        chunk_id = await _chunk(session, document_id, content="RFQ means request for quotation")
        clarification_id = await _clarification(session, source_id, subject="RFQ")
        memory_id = await _memory_fact(session, subject="RFQ", fact="Request for quotation")
        job_id = await reapply.enqueue(
            session,
            subject="RFQ",
            source_id=source_id,
            evidence=None,
            options=None,
            clarification_id=clarification_id,
            memory_id=memory_id,
        )
        await session.commit()
    assert job_id is not None

    await reapply.run_job(factory, settings, job_id)

    async with factory() as session:
        job = (
            await session.execute(
                text("SELECT status, done_items, failed_items FROM reapply_jobs WHERE id = :id"),
                {"id": job_id},
            )
        ).first()
        assert job == ("done", 1, 0)
        embedding = (
            await session.execute(
                text("SELECT embedding IS NOT NULL FROM chunks WHERE id = :id"), {"id": chunk_id}
            )
        ).scalar_one()
        assert embedding is True


@pytest.mark.asyncio
async def test_run_job_promotes_an_inferred_schema_note_to_the_users_answer(
    factory: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    async with factory() as session:
        source_id = await _source(session, "sis")
        note_id = await _schema_note(session, source_id, column_name="st_cd", origin="inferred")
        clarification_id = await _clarification(session, source_id, subject="st_cd")
        memory_id = await _memory_fact(session, subject="st_cd", fact="student status code")
        job_id = await reapply.enqueue(
            session,
            subject="st_cd",
            source_id=source_id,
            evidence=None,
            options=None,
            clarification_id=clarification_id,
            memory_id=memory_id,
        )
        await session.commit()
    assert job_id is not None

    await reapply.run_job(factory, settings, job_id)

    async with factory() as session:
        old_note = (
            await session.execute(
                text("SELECT superseded_by FROM schema_notes WHERE id = :id"), {"id": note_id}
            )
        ).scalar_one()
        assert old_note is not None
        new_note = (
            await session.execute(
                text("SELECT description, origin FROM schema_notes WHERE id = :id"),
                {"id": old_note},
            )
        ).first()
        assert new_note == ("student status code", "user")


@pytest.mark.asyncio
async def test_run_job_dismisses_a_stale_conflicting_clarification(
    factory: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    async with factory() as session:
        source_a = await _source(session, "a")
        source_b = await _source(session, "b")
        this_one = await _clarification(session, source_a, subject="RFQ")
        stale = await _clarification(session, source_b, subject="RFQ")
        memory_id = await _memory_fact(session, subject="RFQ", fact="Request for quotation")
        job_id = await reapply.enqueue(
            session,
            subject="RFQ",
            source_id=source_a,
            evidence=None,
            options=None,
            clarification_id=this_one,
            memory_id=memory_id,
        )
        await session.commit()
    assert job_id is not None

    await reapply.run_job(factory, settings, job_id)

    async with factory() as session:
        status = (
            await session.execute(
                text("SELECT status FROM clarifications WHERE id = :id"), {"id": stale}
            )
        ).scalar_one()
        assert status == "dismissed"


@pytest.mark.asyncio
async def test_a_failing_item_retries_then_is_visible_as_failed_and_can_be_retried(
    factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(reapply, "ITEM_RETRY_DELAY_SECONDS", 0.0)

    calls = {"count": 0}

    async def always_fails(
        self: InferenceClient, texts: list[str], **kwargs: object
    ) -> list[list[float]]:
        calls["count"] += 1
        raise RuntimeError("inference is down")

    monkeypatch.setattr(InferenceClient, "embed", always_fails)

    async with factory() as session:
        source_id = await _source(session, "contracts")
        document_id = await _document(session, source_id, "a.pdf")
        await _chunk(session, document_id)
        clarification_id = await _clarification(session, source_id, subject="RFQ")
        memory_id = await _memory_fact(session, subject="RFQ", fact="Request for quotation")
        job_id = await reapply.enqueue(
            session,
            subject="RFQ",
            source_id=source_id,
            evidence=None,
            options=None,
            clarification_id=clarification_id,
            memory_id=memory_id,
        )
        await session.commit()
    assert job_id is not None

    await reapply.run_job(factory, settings, job_id)

    assert calls["count"] == reapply.ITEM_MAX_ATTEMPTS

    async with factory() as session:
        job = (
            await session.execute(
                text("SELECT status, failed_items FROM reapply_jobs WHERE id = :id"), {"id": job_id}
            )
        ).first()
        assert job == ("failed", 1)

        requeued = await reapply.retry_failed(session, job_id)
        await session.commit()
    assert requeued == 1

    async with factory() as session:
        status = (
            await session.execute(
                text("SELECT status FROM reapply_jobs WHERE id = :id"), {"id": job_id}
            )
        ).scalar_one()
        assert status == "queued"
        item_status = (
            await session.execute(
                text("SELECT status, attempts FROM reapply_items WHERE job_id = :id"),
                {"id": job_id},
            )
        ).first()
        assert item_status == ("pending", 0)


@pytest.mark.asyncio
async def test_retry_failed_returns_none_for_an_unknown_job(session: AsyncSession) -> None:
    assert await reapply.retry_failed(session, uuid.uuid4()) is None


@pytest.mark.asyncio
async def test_get_job_reports_per_item_progress(
    factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_embed(
        self: InferenceClient, texts: list[str], **kwargs: object
    ) -> list[list[float]]:
        return [[0.1] * settings.embedding_dimensions for _ in texts]

    monkeypatch.setattr(InferenceClient, "embed", fake_embed)

    async with factory() as session:
        source_id = await _source(session, "contracts")
        document_id = await _document(session, source_id, "a.pdf")
        await _chunk(session, document_id)
        clarification_id = await _clarification(session, source_id, subject="RFQ")
        memory_id = await _memory_fact(session, subject="RFQ", fact="Request for quotation")
        job_id = await reapply.enqueue(
            session,
            subject="RFQ",
            source_id=source_id,
            evidence=None,
            options=None,
            clarification_id=clarification_id,
            memory_id=memory_id,
        )
        await session.commit()
    assert job_id is not None

    await reapply.run_job(factory, settings, job_id)

    async with factory() as session:
        status = await reapply.get_job(session, job_id)
    assert status is not None
    assert status["status"] == "done"
    assert status["done_items"] == 1
    assert len(status["items"]) == 1
    assert status["items"][0]["kind"] == "chunk"
    assert status["items"][0]["status"] == "done"


@pytest.mark.asyncio
async def test_get_job_returns_none_for_an_unknown_job(session: AsyncSession) -> None:
    assert await reapply.get_job(session, uuid.uuid4()) is None


# --- resume and cancellation --------------------------------------------


@pytest.mark.asyncio
async def test_resume_returns_a_running_job_to_queued(session: AsyncSession) -> None:
    source_id = await _source(session, "contracts")
    job_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO reapply_jobs (id, subject, source_id, status, total_items) "
            "VALUES (:id, 'RFQ', :source_id, 'running', 1)"
        ),
        {"id": job_id, "source_id": source_id},
    )

    resumed = await reapply.resume(session)

    assert resumed == [job_id]
    status = (
        await session.execute(
            text("SELECT status FROM reapply_jobs WHERE id = :id"), {"id": job_id}
        )
    ).scalar_one()
    assert status == "queued"


@pytest.mark.asyncio
async def test_cancel_pending_for_clarification_stops_unrun_items(
    session: AsyncSession,
) -> None:
    source_id = await _source(session, "contracts")
    document_id = await _document(session, source_id, "a.pdf")
    await _chunk(session, document_id)
    clarification_id = await _clarification(session, source_id, subject="RFQ")
    memory_id = await _memory_fact(session, subject="RFQ", fact="Request for quotation")
    job_id = await reapply.enqueue(
        session,
        subject="RFQ",
        source_id=source_id,
        evidence=None,
        options=None,
        clarification_id=clarification_id,
        memory_id=memory_id,
    )
    assert job_id is not None

    cancelled = await reapply.cancel_pending_for_clarification(session, clarification_id)

    assert cancelled == 1
    job_status = (
        await session.execute(
            text("SELECT status FROM reapply_jobs WHERE id = :id"), {"id": job_id}
        )
    ).scalar_one()
    assert job_status == "failed"
    item_status = (
        await session.execute(
            text("SELECT status, error FROM reapply_items WHERE job_id = :id"), {"id": job_id}
        )
    ).first()
    assert item_status is not None
    assert item_status[0] == "failed"
    assert "undone" in item_status[1]
