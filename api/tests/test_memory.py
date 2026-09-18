"""Writing and superseding `memory` and `schema_notes`. `M3-STORE-BE-076`.

Against a real Postgres — the discard/precedence rules are SQL-shaped
(`superseded_by IS NULL`, `origin != 'inferred'`), so a fake session would
just re-implement the queries under test.
"""

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from askwell.memory import (
    FULL_CONFIDENCE,
    CannotCorrectInference,
    FactNotFound,
    StaleMemoryCount,
    add_manual_fact,
    confirm_fact,
    confirm_memory_fact,
    confirm_schema_note,
    correct_fact,
    correct_memory_fact,
    correct_schema_note,
    delete_all_memory,
    delete_fact,
    delete_memory_fact,
    delete_schema_note,
    get_active_memory_facts,
    get_active_schema_notes,
    get_fact_detail,
    get_memory_screen,
    reattach_schema_note,
    retrieve_relevant_facts,
    write_memory_fact,
    write_schema_note,
)

pytestmark = pytest.mark.requires_db

_TABLES = (
    "sources, documents, chunks, clarifications, memory, schema_notes, "
    "reapply_jobs, reapply_items, audit_decisions, conversations, messages, fact_usage"
)


@pytest.fixture
def async_url(database_url: str) -> str:
    return database_url.replace("postgresql://", "postgresql+psycopg://", 1)


@pytest_asyncio.fixture
async def session(async_url: str) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(async_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as opened:
        await opened.execute(text(f"TRUNCATE {_TABLES} CASCADE"))
        await opened.commit()
        yield opened
        await opened.rollback()
        await opened.execute(text(f"TRUNCATE {_TABLES} CASCADE"))
        await opened.commit()
    await engine.dispose()


async def _source(session: AsyncSession, *, name: str = "a source") -> uuid.UUID:
    source_id = uuid.uuid4()
    await session.execute(
        text("INSERT INTO sources (id, kind, name, status) VALUES (:id, 'file', :name, 'ready')"),
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
    session: AsyncSession, document_id: uuid.UUID, *, content: str = "hello"
) -> uuid.UUID:
    chunk_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO chunks (id, document_id, ordinal, content) "
            "VALUES (:id, :document_id, 0, :content)"
        ),
        {"id": chunk_id, "document_id": document_id, "content": content},
    )
    return chunk_id


# --- memory: writing and correcting ------------------------------------------


@pytest.mark.asyncio
async def test_answering_a_clarification_writes_a_full_confidence_user_fact(
    session: AsyncSession,
) -> None:
    fact_id = await write_memory_fact(
        session, subject="st_cd", fact="student status code", origin="clarification"
    )
    assert fact_id is not None

    facts = await get_active_memory_facts(session, subject="st_cd")
    assert len(facts) == 1
    assert facts[0].origin == "clarification"
    assert facts[0].confidence == FULL_CONFIDENCE  # defaulted, not left None

    # An explicit confidence still wins over the default.
    fact_id = await write_memory_fact(
        session,
        subject="rfq",
        fact="Request for Quotation",
        origin="clarification",
        confidence=FULL_CONFIDENCE,
    )
    facts = await get_active_memory_facts(session, subject="rfq")
    assert facts[0].confidence == FULL_CONFIDENCE


@pytest.mark.asyncio
async def test_correcting_supersedes_and_the_old_value_stays_readable(
    session: AsyncSession,
) -> None:
    fact_id = await write_memory_fact(
        session, subject="st_cd", fact="student status code", origin="clarification"
    )
    assert fact_id is not None

    outcome = await correct_memory_fact(session, fact_id=fact_id, fact="student cohort code")
    new_id = outcome.fact_id
    assert outcome.reprocessing.changed is True

    old = await session.execute(
        text("SELECT fact, superseded_by FROM memory WHERE id = :id"), {"id": fact_id}
    )
    old_fact, superseded_by = old.first()
    assert old_fact == "student status code"  # unchanged, still readable
    assert superseded_by == new_id

    active = await get_active_memory_facts(session, subject="st_cd")
    assert len(active) == 1
    assert active[0].id == new_id
    assert active[0].fact == "student cohort code"
    assert active[0].origin == "correction"
    assert active[0].confidence == FULL_CONFIDENCE


@pytest.mark.asyncio
async def test_two_contradicting_user_answers_the_later_supersedes_both_visible(
    session: AsyncSession,
) -> None:
    fact_id = await write_memory_fact(
        session, subject="policy", fact="30 days", origin="clarification"
    )
    assert fact_id is not None
    second_id = (await correct_memory_fact(session, fact_id=fact_id, fact="45 days")).fact_id
    third_id = (await correct_memory_fact(session, fact_id=second_id, fact="60 days")).fact_id

    active = await get_active_memory_facts(session, subject="policy")
    assert len(active) == 1
    assert active[0].id == third_id
    assert active[0].fact == "60 days"

    # Both prior values remain readable in history — the chain, not
    # `created_at` ordering, is what preserves the sequence, since a
    # correction made in the same transaction as the fact it replaces can
    # share a timestamp.
    history = await session.execute(text("SELECT id, fact, superseded_by FROM memory"))
    by_id = {row[0]: (row[1], row[2]) for row in history}
    assert by_id[fact_id] == ("30 days", second_id)
    assert by_id[second_id] == ("45 days", third_id)
    assert by_id[third_id] == ("60 days", None)


@pytest.mark.asyncio
async def test_a_second_user_origin_write_supersedes_not_double_actives(
    session: AsyncSession,
) -> None:
    first_id = await write_memory_fact(
        session, subject="policy", fact="30 days", origin="clarification"
    )
    assert first_id is not None

    # A second user-origin write for the same subject, via `write_memory_fact`
    # itself rather than `correct_memory_fact` — must supersede, not sit
    # active alongside the first.
    second_id = await write_memory_fact(
        session, subject="policy", fact="45 days", origin="clarification"
    )
    assert second_id is not None

    active = await get_active_memory_facts(session, subject="policy")
    assert len(active) == 1
    assert active[0].id == second_id
    assert active[0].fact == "45 days"

    old = await session.execute(
        text("SELECT fact, superseded_by FROM memory WHERE id = :id"), {"id": first_id}
    )
    old_fact, superseded_by = old.first()
    assert old_fact == "30 days"
    assert superseded_by == second_id


@pytest.mark.asyncio
async def test_correcting_a_fact_that_no_longer_exists_raises(session: AsyncSession) -> None:
    with pytest.raises(FactNotFound):
        await correct_memory_fact(session, fact_id=uuid.uuid4(), fact="whatever")


@pytest.mark.asyncio
async def test_correcting_an_already_superseded_fact_raises(session: AsyncSession) -> None:
    fact_id = await write_memory_fact(
        session, subject="policy", fact="30 days", origin="clarification"
    )
    assert fact_id is not None
    await correct_memory_fact(session, fact_id=fact_id, fact="45 days")

    with pytest.raises(FactNotFound):
        await correct_memory_fact(session, fact_id=fact_id, fact="60 days")


@pytest.mark.asyncio
async def test_deleting_a_fact_removes_it_and_records_a_decision(session: AsyncSession) -> None:
    fact_id = await write_memory_fact(
        session, subject="rfq", fact="Request for Quotation", origin="manual"
    )
    assert fact_id is not None

    await delete_memory_fact(session, fact_id=fact_id)

    assert await get_active_memory_facts(session, subject="rfq") == []
    remaining = (await session.execute(text("SELECT id FROM memory"))).all()
    assert remaining == []

    rows = (
        await session.execute(
            text(
                "SELECT kind, payload->>'fact_id', payload->>'subject', payload->>'fact' "
                "FROM audit_decisions ORDER BY occurred_at"
            )
        )
    ).all()
    assert [row[0] for row in rows] == ["memory_written", "memory_deleted"]
    _, deleted_fact_id, deleted_subject, deleted_fact = rows[1]
    assert deleted_fact_id == str(fact_id)
    assert deleted_subject == "rfq"
    assert deleted_fact == "Request for Quotation"


@pytest.mark.asyncio
async def test_deleting_an_unknown_fact_raises(session: AsyncSession) -> None:
    with pytest.raises(FactNotFound):
        await delete_memory_fact(session, fact_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_deleting_an_already_superseded_fact_raises(session: AsyncSession) -> None:
    fact_id = await write_memory_fact(
        session, subject="policy", fact="30 days", origin="clarification"
    )
    assert fact_id is not None
    await correct_memory_fact(session, fact_id=fact_id, fact="45 days")

    with pytest.raises(FactNotFound):
        await delete_memory_fact(session, fact_id=fact_id)


@pytest.mark.asyncio
async def test_correcting_an_inferred_fact_is_rejected(session: AsyncSession) -> None:
    fact_id = await write_memory_fact(
        session, subject="rfq", fact="a guess", origin="inferred", confidence=0.3
    )
    assert fact_id is not None

    with pytest.raises(CannotCorrectInference):
        await correct_memory_fact(session, fact_id=fact_id, fact="a better guess")


# --- memory: inference never overwrites a user fact --------------------------


@pytest.mark.asyncio
async def test_an_inference_never_overwrites_a_user_supplied_fact(session: AsyncSession) -> None:
    fact_id = await write_memory_fact(
        session, subject="rfq", fact="Request for Quotation", origin="manual"
    )
    assert fact_id is not None

    discarded = await write_memory_fact(
        session, subject="rfq", fact="a low-confidence guess", origin="inferred", confidence=0.3
    )

    assert discarded is None
    active = await get_active_memory_facts(session, subject="rfq")
    assert len(active) == 1
    assert active[0].id == fact_id
    assert active[0].fact == "Request for Quotation"


@pytest.mark.asyncio
async def test_an_inference_for_a_new_subject_is_stored(session: AsyncSession) -> None:
    fact_id = await write_memory_fact(
        session, subject="widget", fact="a guess", origin="inferred", confidence=0.3
    )
    assert fact_id is not None
    active = await get_active_memory_facts(session, subject="widget")
    assert active[0].origin == "inferred"


# --- memory: retrieval precedence and deleted-source labelling ---------------


async def _backdate(session: AsyncSession, fact_id: uuid.UUID, *, hours_ago: int) -> None:
    await session.execute(
        text(
            "UPDATE memory SET created_at = now() - make_interval(hours => :hours) WHERE id = :id"
        ),
        {"id": fact_id, "hours": hours_ago},
    )


@pytest.mark.asyncio
async def test_retrieval_orders_later_before_earlier_within_the_same_origin(
    session: AsyncSession,
) -> None:
    older_id = await write_memory_fact(session, subject="rfq", fact="older guess", origin="manual")
    newer_id = await write_memory_fact(
        session, subject="pdf", fact="a fresher guess", origin="manual"
    )
    assert older_id is not None
    assert newer_id is not None
    await _backdate(session, older_id, hours_ago=2)

    active = await get_active_memory_facts(session)
    assert [f.id for f in active] == [newer_id, older_id]


@pytest.mark.asyncio
async def test_retrieval_orders_user_before_inferred_regardless_of_recency(
    session: AsyncSession,
) -> None:
    inferred_id = await write_memory_fact(
        session, subject="widget", fact="a guess", origin="inferred"
    )
    user_id = await write_memory_fact(
        session, subject="rfq", fact="Request for Quotation", origin="manual"
    )
    assert inferred_id is not None
    assert user_id is not None
    # The inferred fact is newer, but user-origin still sorts first.
    await _backdate(session, user_id, hours_ago=2)

    active = await get_active_memory_facts(session)
    assert [f.id for f in active] == [user_id, inferred_id]


@pytest.mark.asyncio
async def test_general_memory_survives_a_deleted_source_and_says_so(
    session: AsyncSession,
) -> None:
    source_id = await _source(session, name="tender-files")
    fact_id = await write_memory_fact(
        session,
        subject="rfq",
        fact="Request for Quotation",
        origin="clarification",
        source_id=source_id,
    )
    assert fact_id is not None

    await session.execute(
        text("UPDATE sources SET status = 'deleted', deleted_at = now() WHERE id = :id"),
        {"id": source_id},
    )

    active = await get_active_memory_facts(session, subject="rfq")
    assert len(active) == 1
    assert active[0].source_name == "tender-files"
    assert active[0].source_deleted is True


@pytest.mark.asyncio
async def test_a_fact_with_no_source_is_not_labelled_as_from_a_deleted_source(
    session: AsyncSession,
) -> None:
    await write_memory_fact(session, subject="rfq", fact="Request for Quotation", origin="manual")

    active = await get_active_memory_facts(session, subject="rfq")
    assert active[0].source_id is None
    assert active[0].source_deleted is False


# --- schema notes -------------------------------------------------------------


@pytest.mark.asyncio
async def test_writing_and_correcting_a_schema_note(session: AsyncSession) -> None:
    source_id = await _source(session)
    note_id = await write_schema_note(
        session,
        source_id=source_id,
        table_name="students",
        column_name="st_cd",
        description="a guess",
        origin="inferred",
        confidence=0.3,
    )
    assert note_id is not None

    # A user-supplied note for the same position retires the earlier guess
    # (only one active belief per position) and becomes the fact a later
    # inference can no longer displace.
    user_note_id = await write_schema_note(
        session,
        source_id=source_id,
        table_name="students",
        column_name="st_cd",
        description="student status code",
        origin="user",
    )
    assert user_note_id is not None

    # #258: read `superseded_by` back on the retired inferred row directly,
    # rather than only inferring the retirement happened from the discard
    # check below — the two are not the same guarantee. A no-op `UPDATE`
    # (e.g. a broken `WHERE`) would still make the discard check pass, since
    # that check tests `origin = 'user' AND superseded_by IS NULL`, which
    # holds regardless of whether the inferred row was ever retired.
    retired = await session.execute(
        text("SELECT superseded_by FROM schema_notes WHERE id = :id"), {"id": note_id}
    )
    assert retired.scalar_one() == user_note_id

    discarded = await write_schema_note(
        session,
        source_id=source_id,
        table_name="students",
        column_name="st_cd",
        description="another guess",
        origin="inferred",
        confidence=0.3,
    )
    assert discarded is None

    new_id = (
        await correct_schema_note(session, note_id=user_note_id, description="student cohort code")
    ).fact_id
    active = await get_active_schema_notes(session, source_id=source_id)
    current = [n for n in active if n.table_name == "students" and n.column_name == "st_cd"]
    assert len(current) == 1
    assert current[0].id == new_id
    assert current[0].description == "student cohort code"
    assert current[0].origin == "user"


@pytest.mark.asyncio
async def test_a_second_user_origin_note_supersedes_not_double_actives(
    session: AsyncSession,
) -> None:
    source_id = await _source(session)
    first_id = await write_schema_note(
        session,
        source_id=source_id,
        table_name="students",
        column_name="st_cd",
        description="student status code",
        origin="user",
    )
    assert first_id is not None

    second_id = await write_schema_note(
        session,
        source_id=source_id,
        table_name="students",
        column_name="st_cd",
        description="student cohort code",
        origin="user",
    )
    assert second_id is not None

    active = await get_active_schema_notes(session, source_id=source_id)
    current = [n for n in active if n.table_name == "students" and n.column_name == "st_cd"]
    assert len(current) == 1
    assert current[0].id == second_id
    assert current[0].confidence == FULL_CONFIDENCE

    retired = await session.execute(
        text("SELECT description, superseded_by FROM schema_notes WHERE id = :id"),
        {"id": first_id},
    )
    old_description, superseded_by = retired.first()
    assert old_description == "student status code"
    assert superseded_by == second_id


@pytest.mark.asyncio
async def test_correcting_an_inferred_schema_note_is_rejected(session: AsyncSession) -> None:
    source_id = await _source(session)
    note_id = await write_schema_note(
        session,
        source_id=source_id,
        table_name="students",
        column_name="st_cd",
        description="a guess",
        origin="inferred",
        confidence=0.3,
    )
    assert note_id is not None

    with pytest.raises(CannotCorrectInference):
        await correct_schema_note(session, note_id=note_id, description="a better guess")


@pytest.mark.asyncio
async def test_deleting_a_schema_note_removes_it_and_records_a_decision(
    session: AsyncSession,
) -> None:
    source_id = await _source(session)
    note_id = await write_schema_note(
        session,
        source_id=source_id,
        table_name="students",
        column_name="st_cd",
        description="student status code",
        origin="user",
    )
    assert note_id is not None

    await delete_schema_note(session, note_id=note_id)

    active = await get_active_schema_notes(session, source_id=source_id)
    assert active == []

    kinds = (
        await session.execute(text("SELECT kind FROM audit_decisions ORDER BY occurred_at"))
    ).all()
    assert [row[0] for row in kinds] == ["schema_note_written", "schema_note_deleted"]


@pytest.mark.asyncio
async def test_deleting_an_unknown_schema_note_raises(session: AsyncSession) -> None:
    with pytest.raises(FactNotFound):
        await delete_schema_note(session, note_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_deleting_a_source_removes_its_schema_notes_but_not_general_memory(
    session: AsyncSession,
) -> None:
    source_id = await _source(session)
    await write_schema_note(
        session,
        source_id=source_id,
        table_name="students",
        column_name="st_cd",
        description="student status code",
        origin="user",
    )
    await write_memory_fact(
        session, subject="rfq", fact="Request for Quotation", origin="manual", source_id=source_id
    )

    # `askwell.sources.delete_source`'s own behaviour (`M2-DELETE-BE-061`):
    # schema notes are deleted outright, memory is left untouched.
    await session.execute(text("DELETE FROM schema_notes WHERE source_id = :id"), {"id": source_id})

    assert await get_active_schema_notes(session, source_id=source_id) == []
    assert len(await get_active_memory_facts(session, subject="rfq")) == 1


# --- M3-CORRECT-BE-082: the one correction path -----------------------------


@pytest.mark.asyncio
async def test_correcting_to_the_same_value_is_a_no_op(session: AsyncSession) -> None:
    source_id = await _source(session)
    document_id = await _document(session, source_id, "policy.pdf")
    await _chunk(session, document_id)
    fact_id = await write_memory_fact(
        session,
        subject="policy",
        fact="30 days",
        origin="clarification",
        source_id=source_id,
    )
    assert fact_id is not None

    outcome = await correct_memory_fact(session, fact_id=fact_id, fact="30 days")

    assert outcome.fact_id == fact_id
    assert outcome.reprocessing.changed is False
    assert outcome.reprocessing.count == 0
    assert outcome.reapply_job_id is None
    # No new row, no second supersession record.
    assert (await session.execute(text("SELECT count(*) FROM memory"))).scalar_one() == 1
    kinds = (
        await session.execute(text("SELECT kind FROM audit_decisions ORDER BY occurred_at"))
    ).all()
    assert [row[0] for row in kinds] == ["memory_written"]
    assert (await session.execute(text("SELECT count(*) FROM reapply_jobs"))).scalar_one() == 0


@pytest.mark.asyncio
async def test_correcting_a_sourceless_fact_has_nothing_to_reprocess(
    session: AsyncSession,
) -> None:
    fact_id = await write_memory_fact(session, subject="rfq", fact="a guess", origin="manual")
    assert fact_id is not None

    outcome = await correct_memory_fact(session, fact_id=fact_id, fact="Request for Quotation")

    assert outcome.reprocessing.changed is True
    assert outcome.reprocessing.count == 0
    assert outcome.reapply_job_id is None


@pytest.mark.asyncio
async def test_correcting_a_fact_queues_reprocessing_of_its_source(
    session: AsyncSession,
) -> None:
    source_id = await _source(session)
    document_id = await _document(session, source_id, "policy.pdf")
    await _chunk(session, document_id)
    fact_id = await write_memory_fact(
        session,
        subject="policy",
        fact="30 days",
        origin="clarification",
        source_id=source_id,
    )
    assert fact_id is not None

    outcome = await correct_memory_fact(session, fact_id=fact_id, fact="45 days")

    assert outcome.reprocessing.changed is True
    assert outcome.reprocessing.count == 1
    assert "document" in outcome.reprocessing.label
    assert outcome.reapply_job_id is not None
    job = (
        await session.execute(
            text("SELECT subject, source_id, memory_id FROM reapply_jobs WHERE id = :id"),
            {"id": outcome.reapply_job_id},
        )
    ).first()
    assert job is not None
    assert job[0] == "policy"
    assert job[1] == source_id
    assert job[2] == outcome.fact_id
    items = (
        await session.execute(
            text("SELECT kind, target_id FROM reapply_items WHERE job_id = :id"),
            {"id": outcome.reapply_job_id},
        )
    ).all()
    assert [row[0] for row in items] == ["chunk"]


@pytest.mark.asyncio
async def test_correcting_the_same_fact_twice_leaves_a_clean_three_value_chain(
    session: AsyncSession,
) -> None:
    """`docs/backlog/M3-it-learns-my-material.md` `M3-CORRECT-BE-082`'s own
    Real-World Example: a fact corrected twice from different callers — a
    chip, then the memory screen, is just two calls to the same function —
    leaves a clean chain of three values in history."""
    source_id = await _source(session)
    fact_id = await write_memory_fact(
        session, subject="policy", fact="30 days", origin="clarification", source_id=source_id
    )
    assert fact_id is not None

    from_chip = await correct_memory_fact(session, fact_id=fact_id, fact="45 days")
    from_memory_screen = await correct_memory_fact(
        session, fact_id=from_chip.fact_id, fact="60 days"
    )

    history = await session.execute(
        text("SELECT id, fact, superseded_by FROM memory ORDER BY created_at, id")
    )
    by_id = {row[0]: (row[1], row[2]) for row in history}
    assert by_id[fact_id] == ("30 days", from_chip.fact_id)
    assert by_id[from_chip.fact_id] == ("45 days", from_memory_screen.fact_id)
    assert by_id[from_memory_screen.fact_id] == ("60 days", None)

    active = await get_active_memory_facts(session, subject="policy")
    assert len(active) == 1
    assert active[0].id == from_memory_screen.fact_id


@pytest.mark.asyncio
async def test_deleting_a_fact_also_queues_reprocessing(session: AsyncSession) -> None:
    source_id = await _source(session)
    document_id = await _document(session, source_id, "policy.pdf")
    await _chunk(session, document_id)
    fact_id = await write_memory_fact(
        session,
        subject="policy",
        fact="30 days",
        origin="clarification",
        source_id=source_id,
    )
    assert fact_id is not None

    outcome = await delete_memory_fact(session, fact_id=fact_id)

    assert outcome.reprocessing.changed is True
    assert outcome.reprocessing.count == 1
    assert outcome.reapply_job_id is not None
    job = (
        await session.execute(
            text("SELECT memory_id FROM reapply_jobs WHERE id = :id"),
            {"id": outcome.reapply_job_id},
        )
    ).first()
    assert job is not None
    # No new fact to hand `reapply.run_job` an answer from.
    assert job[0] is None


@pytest.mark.asyncio
async def test_correcting_a_schema_note_to_the_same_description_is_a_no_op(
    session: AsyncSession,
) -> None:
    source_id = await _source(session)
    note_id = await write_schema_note(
        session,
        source_id=source_id,
        table_name="students",
        column_name="st_cd",
        description="student status code",
        origin="user",
    )
    assert note_id is not None

    outcome = await correct_schema_note(session, note_id=note_id, description="student status code")

    assert outcome.fact_id == note_id
    assert outcome.reprocessing.changed is False
    assert outcome.reapply_job_id is None
    assert (await session.execute(text("SELECT count(*) FROM schema_notes"))).scalar_one() == 1


@pytest.mark.asyncio
async def test_correcting_a_schema_note_queues_reprocessing_of_its_source(
    session: AsyncSession,
) -> None:
    source_id = await _source(session)
    document_id = await _document(session, source_id, "students.csv")
    await _chunk(session, document_id)
    # A still-active inferred note on a *different* table sharing the same
    # column name: a genuine `schema_note`-kind dependency for this
    # correction's subject (`st_cd`), unlike a same-position guess, which
    # `write_schema_note` would already have retired before this ever runs.
    other_inferred_id = await write_schema_note(
        session,
        source_id=source_id,
        table_name="staff",
        column_name="st_cd",
        description="a guess",
        origin="inferred",
        confidence=0.3,
    )
    user_note_id = await write_schema_note(
        session,
        source_id=source_id,
        table_name="students",
        column_name="st_cd",
        description="student status code",
        origin="user",
    )
    assert other_inferred_id is not None
    assert user_note_id is not None

    outcome = await correct_schema_note(
        session, note_id=user_note_id, description="student cohort code"
    )

    assert outcome.reprocessing.changed is True
    assert outcome.reapply_job_id is not None
    # The chunk dependency was queued; the `staff.st_cd` guess was left
    # exactly as it was — a schema-note correction has no `memory` row for
    # `reapply.run_job` to read an answer from, so promoting it would mean
    # promoting it to an empty string. Filtered out rather than corrupted.
    assert outcome.reprocessing.count == 1
    items = (
        await session.execute(
            text("SELECT kind FROM reapply_items WHERE job_id = :id"),
            {"id": outcome.reapply_job_id},
        )
    ).all()
    assert [row[0] for row in items] == ["chunk"]
    still_inferred = (
        await session.execute(
            text("SELECT origin, superseded_by FROM schema_notes WHERE id = :id"),
            {"id": other_inferred_id},
        )
    ).first()
    assert still_inferred == ("inferred", None)


@pytest.mark.asyncio
async def test_correcting_an_already_deleted_fact_is_refused_with_a_clear_reason(
    session: AsyncSession,
) -> None:
    fact_id = await write_memory_fact(session, subject="rfq", fact="a guess", origin="manual")
    assert fact_id is not None
    await delete_memory_fact(session, fact_id=fact_id)

    with pytest.raises(FactNotFound):
        await correct_memory_fact(session, fact_id=fact_id, fact="something else")


# --- reattach_schema_note: the fix path's third option, M4-SCHEMA-BE-102 ----


@pytest.mark.asyncio
async def test_reattaching_a_stale_note_moves_it_and_clears_the_flag(
    session: AsyncSession,
) -> None:
    source_id = await _source(session)
    note_id = await write_schema_note(
        session,
        source_id=source_id,
        table_name="students",
        column_name="st_cd",
        description="student status code",
        origin="user",
    )
    assert note_id is not None
    await session.execute(
        text(
            "UPDATE schema_notes SET stale = true, stale_reason = 'dropped', "
            "reattach_suggestion = 'status_code' WHERE id = :id"
        ),
        {"id": note_id},
    )

    outcome = await reattach_schema_note(
        session, note_id=note_id, table_name="students", column_name="status_code"
    )

    assert outcome.fact_id != note_id
    old = (
        await session.execute(
            text("SELECT superseded_by FROM schema_notes WHERE id = :id"), {"id": note_id}
        )
    ).scalar_one()
    assert old == outcome.fact_id

    moved = (
        await session.execute(
            text(
                "SELECT table_name, column_name, description, origin, stale, "
                "stale_reason, reattach_suggestion FROM schema_notes WHERE id = :id"
            ),
            {"id": outcome.fact_id},
        )
    ).one()
    assert moved == ("students", "status_code", "student status code", "user", False, None, None)


@pytest.mark.asyncio
async def test_reattaching_to_a_position_with_an_active_inferred_note_retires_it(
    session: AsyncSession,
) -> None:
    source_id = await _source(session)
    note_id = await write_schema_note(
        session,
        source_id=source_id,
        table_name="students",
        column_name="st_cd",
        description="student status code",
        origin="user",
    )
    guess_id = await write_schema_note(
        session,
        source_id=source_id,
        table_name="students",
        column_name="status_code",
        description="a guess",
        origin="inferred",
    )
    assert note_id is not None
    assert guess_id is not None

    outcome = await reattach_schema_note(
        session, note_id=note_id, table_name="students", column_name="status_code"
    )

    retired = (
        await session.execute(
            text("SELECT superseded_by FROM schema_notes WHERE id = :id"), {"id": guess_id}
        )
    ).scalar_one()
    assert retired == outcome.fact_id


@pytest.mark.asyncio
async def test_reattaching_an_inferred_note_is_rejected(session: AsyncSession) -> None:
    source_id = await _source(session)
    note_id = await write_schema_note(
        session,
        source_id=source_id,
        table_name="students",
        column_name="st_cd",
        description="a guess",
        origin="inferred",
    )
    assert note_id is not None

    with pytest.raises(CannotCorrectInference):
        await reattach_schema_note(
            session, note_id=note_id, table_name="students", column_name="status_code"
        )


@pytest.mark.asyncio
async def test_reattaching_an_unknown_note_raises(session: AsyncSession) -> None:
    with pytest.raises(FactNotFound):
        await reattach_schema_note(
            session, note_id=uuid.uuid4(), table_name="students", column_name="status_code"
        )


@pytest.mark.asyncio
async def test_reattaching_to_the_same_position_is_a_no_op(session: AsyncSession) -> None:
    source_id = await _source(session)
    note_id = await write_schema_note(
        session,
        source_id=source_id,
        table_name="students",
        column_name="st_cd",
        description="student status code",
        origin="user",
    )
    assert note_id is not None

    outcome = await reattach_schema_note(
        session, note_id=note_id, table_name="students", column_name="st_cd"
    )

    assert outcome.fact_id == note_id
    assert outcome.reprocessing.changed is False


# --- retrieve_relevant_facts: M3-APPLY-RET-078 -------------------------------


@pytest.mark.asyncio
async def test_a_question_using_a_taught_abbreviation_retrieves_it(
    session: AsyncSession,
) -> None:
    fact_id = await write_memory_fact(
        session, subject="RFQ", fact="Request for Quotation", origin="clarification"
    )
    assert fact_id is not None
    await write_memory_fact(
        session, subject="unrelated", fact="nothing to do with this", origin="manual"
    )

    found = await retrieve_relevant_facts(session, question="what does RFQ mean?")
    assert [f.id for f in found.facts] == [fact_id]
    assert found.notes == []


@pytest.mark.asyncio
async def test_a_question_with_nothing_relevant_returns_nothing(session: AsyncSession) -> None:
    await write_memory_fact(session, subject="RFQ", fact="Request for Quotation", origin="manual")

    found = await retrieve_relevant_facts(session, question="what colour is the office?")
    assert found.facts == []
    assert found.notes == []


@pytest.mark.asyncio
async def test_a_superseded_fact_is_not_retrieved(session: AsyncSession) -> None:
    fact_id = await write_memory_fact(session, subject="RFQ", fact="a first guess", origin="manual")
    assert fact_id is not None
    outcome = await correct_memory_fact(session, fact_id=fact_id, fact="Request for Quotation")

    found = await retrieve_relevant_facts(session, question="what does RFQ mean?")
    assert [f.id for f in found.facts] == [outcome.fact_id]


@pytest.mark.asyncio
async def test_retrieval_is_bounded_even_when_more_match(session: AsyncSession) -> None:
    for index in range(8):
        await write_memory_fact(
            session, subject=f"term-{index}", fact="widget definition", origin="manual"
        )

    found = await retrieve_relevant_facts(session, question="widget", fact_limit=3)
    assert len(found.facts) == 3


@pytest.mark.asyncio
async def test_schema_notes_are_scoped_to_the_asked_source_memory_is_not(
    session: AsyncSession,
) -> None:
    source_a = await _source(session, name="source-a")
    source_b = await _source(session, name="source-b")
    note_a = await write_schema_note(
        session,
        source_id=source_a,
        table_name="students",
        column_name="st_cd",
        description="student status code",
        origin="user",
    )
    await write_schema_note(
        session,
        source_id=source_b,
        table_name="students",
        column_name="st_cd",
        description="student status code",
        origin="user",
    )
    fact_id = await write_memory_fact(
        session, subject="st_cd", fact="student status code", origin="manual"
    )
    assert note_a is not None
    assert fact_id is not None

    found = await retrieve_relevant_facts(session, question="what is st_cd?", source_id=source_a)
    assert [n.id for n in found.notes] == [note_a]
    # General memory is never source-scoped — the same abbreviation applies
    # to a question asked against any source.
    assert [f.id for f in found.facts] == [fact_id]


@pytest.mark.asyncio
async def test_a_stale_schema_note_is_never_retrieved_for_generation(
    session: AsyncSession,
) -> None:
    """`M4-SCHEMA-BE-102`'s own Validation Rule: "a stale note is never
    used in generation" — `retrieve_relevant_facts` is the one retrieval
    path composition draws on for both document answers and database
    question-answering, so exclusion here is what that rule means.
    `get_active_schema_notes` still returns it, for the library/memory
    screens — this ticket never hides a stale note from a person, only
    from the model.
    """
    source_id = await _source(session)
    note_id = await write_schema_note(
        session,
        source_id=source_id,
        table_name="students",
        column_name="st_cd",
        description="student status code",
        origin="user",
    )
    assert note_id is not None
    await session.execute(
        text("UPDATE schema_notes SET stale = true WHERE id = :id"), {"id": note_id}
    )

    found = await retrieve_relevant_facts(session, question="what is st_cd?", source_id=source_id)
    assert found.notes == []

    still_visible = await get_active_schema_notes(session, source_id=source_id)
    assert [n.id for n in still_visible] == [note_id]
    assert still_visible[0].stale is True


@pytest.mark.asyncio
async def test_a_contradicting_fact_and_note_are_both_labelled_by_confidence(
    session: AsyncSession,
) -> None:
    source_id = await _source(session)
    fact_id = await write_memory_fact(
        session, subject="rfq", fact="Request for Quotation", origin="clarification"
    )
    note_id = await write_schema_note(
        session,
        source_id=source_id,
        table_name="orders",
        column_name="rfq",
        description="an internal request identifier",
        origin="inferred",
        confidence=0.4,
    )
    assert fact_id is not None
    assert note_id is not None

    found = await retrieve_relevant_facts(session, question="rfq", source_id=source_id)
    assert found.facts[0].origin == "clarification"
    assert found.facts[0].confidence == 1.0
    assert found.notes[0].origin == "inferred"
    assert found.notes[0].confidence == 0.4


# --- the chip: one entrypoint across both kinds -------------------------


async def _conversation(session: AsyncSession) -> uuid.UUID:
    conversation_id = uuid.uuid4()
    await session.execute(
        text("INSERT INTO conversations (id) VALUES (:id)"), {"id": conversation_id}
    )
    return conversation_id


async def _mark_used(session: AsyncSession, *, fact_kind: str, fact_id: uuid.UUID) -> None:
    message_id = uuid.uuid4()
    conversation_id = await _conversation(session)
    await session.execute(
        text(
            "INSERT INTO messages (id, conversation_id, role, content) "
            "VALUES (:id, :conversation_id, 'assistant', 'x')"
        ),
        {"id": message_id, "conversation_id": conversation_id},
    )
    await session.execute(
        text(
            "INSERT INTO fact_usage (id, message_id, fact_kind, fact_id) "
            "VALUES (:id, :message_id, :fact_kind, :fact_id)"
        ),
        {"id": uuid.uuid4(), "message_id": message_id, "fact_kind": fact_kind, "fact_id": fact_id},
    )


@pytest.mark.asyncio
async def test_correcting_a_user_origin_fact_from_a_chip_supersedes_in_place(
    session: AsyncSession,
) -> None:
    fact_id = await write_memory_fact(
        session, subject="st_cd", fact="student status code", origin="clarification"
    )
    assert fact_id is not None

    outcome = await correct_fact(session, fact_kind="memory", fact_id=fact_id, value="student code")

    assert outcome.fact_id != fact_id
    active = await get_active_memory_facts(session, subject="st_cd")
    assert len(active) == 1
    assert active[0].id == outcome.fact_id
    assert active[0].fact == "student code"


@pytest.mark.asyncio
async def test_correcting_an_inferred_fact_from_a_chip_asserts_instead_of_raising(
    session: AsyncSession,
) -> None:
    fact_id = await write_memory_fact(
        session, subject="rfq", fact="a guess", origin="inferred", confidence=0.3
    )
    assert fact_id is not None

    outcome = await correct_fact(
        session, fact_kind="memory", fact_id=fact_id, value="Request for Quotation"
    )

    active = await get_active_memory_facts(session, subject="rfq")
    assert len(active) == 1
    assert active[0].id == outcome.fact_id
    assert active[0].fact == "Request for Quotation"
    assert active[0].origin == "correction"
    # The inference is retired, not left as a second active row.
    superseded = (
        await session.execute(
            text("SELECT superseded_by FROM memory WHERE id = :id"), {"id": fact_id}
        )
    ).scalar_one()
    assert superseded == outcome.fact_id


@pytest.mark.asyncio
async def test_correcting_an_inferred_schema_note_from_a_chip_asserts_instead_of_raising(
    session: AsyncSession,
) -> None:
    source_id = await _source(session)
    note_id = await write_schema_note(
        session,
        source_id=source_id,
        table_name="invoices",
        column_name="st_cd",
        description="a guessed status code",
        origin="inferred",
        confidence=0.3,
    )
    assert note_id is not None

    outcome = await correct_fact(
        session, fact_kind="schema_note", fact_id=note_id, value="invoice status code"
    )

    active = await get_active_schema_notes(session, source_id=source_id)
    assert len(active) == 1
    assert active[0].id == outcome.fact_id
    assert active[0].description == "invoice status code"
    assert active[0].origin == "user"


@pytest.mark.asyncio
async def test_correcting_an_unknown_fact_from_a_chip_raises(session: AsyncSession) -> None:
    with pytest.raises(FactNotFound):
        await correct_fact(session, fact_kind="memory", fact_id=uuid.uuid4(), value="x")


@pytest.mark.asyncio
async def test_deleting_a_fact_from_a_chip_dispatches_by_kind(session: AsyncSession) -> None:
    fact_id = await write_memory_fact(
        session, subject="st_cd", fact="student status code", origin="manual"
    )
    assert fact_id is not None

    await delete_fact(session, fact_kind="memory", fact_id=fact_id)

    assert await get_active_memory_facts(session, subject="st_cd") == []


@pytest.mark.asyncio
async def test_deleting_a_schema_note_from_a_chip_dispatches_by_kind(session: AsyncSession) -> None:
    source_id = await _source(session)
    note_id = await write_schema_note(
        session,
        source_id=source_id,
        table_name="invoices",
        column_name="st_cd",
        description="invoice status",
        origin="user",
    )
    assert note_id is not None

    await delete_fact(session, fact_kind="schema_note", fact_id=note_id)

    assert await get_active_schema_notes(session, source_id=source_id) == []


@pytest.mark.asyncio
async def test_fact_detail_reports_usage_count(session: AsyncSession) -> None:
    fact_id = await write_memory_fact(
        session, subject="st_cd", fact="student status code", origin="manual"
    )
    assert fact_id is not None
    await _mark_used(session, fact_kind="memory", fact_id=fact_id)
    await _mark_used(session, fact_kind="memory", fact_id=fact_id)

    detail = await get_fact_detail(session, fact_kind="memory", fact_id=fact_id)

    assert detail is not None
    assert detail.usage_count == 2
    assert detail.active is True
    assert detail.current is None


@pytest.mark.asyncio
async def test_fact_detail_names_the_current_version_once_superseded(
    session: AsyncSession,
) -> None:
    fact_id = await write_memory_fact(
        session, subject="st_cd", fact="student status code", origin="clarification"
    )
    assert fact_id is not None
    await _mark_used(session, fact_kind="memory", fact_id=fact_id)
    outcome = await correct_memory_fact(session, fact_id=fact_id, fact="student code")

    # The popover for the *old* row — the one an already-rendered chip named
    # — reports it is no longer active and names what replaced it.
    old_detail = await get_fact_detail(session, fact_kind="memory", fact_id=fact_id)
    assert old_detail is not None
    assert old_detail.active is False
    assert old_detail.usage_count == 1
    assert old_detail.current is not None
    assert old_detail.current.id == outcome.fact_id
    assert old_detail.current.value == "student code"
    assert old_detail.current.active is True


@pytest.mark.asyncio
async def test_fact_detail_for_a_schema_note_reports_table_and_column_as_subject(
    session: AsyncSession,
) -> None:
    source_id = await _source(session)
    note_id = await write_schema_note(
        session,
        source_id=source_id,
        table_name="invoices",
        column_name="st_cd",
        description="invoice status",
        origin="user",
    )
    assert note_id is not None

    detail = await get_fact_detail(session, fact_kind="schema_note", fact_id=note_id)

    assert detail is not None
    assert detail.subject == "invoices.st_cd"
    assert detail.value == "invoice status"


@pytest.mark.asyncio
async def test_fact_detail_for_an_unknown_id_is_none(session: AsyncSession) -> None:
    assert await get_fact_detail(session, fact_kind="memory", fact_id=uuid.uuid4()) is None


# --- the memory screen ----------------------------------------------------


@pytest.mark.asyncio
async def test_memory_screen_sorts_inferred_first(session: AsyncSession) -> None:
    inferred_id = await write_memory_fact(
        session, subject="rfq", fact="a guess", origin="inferred", confidence=0.3
    )
    user_id = await write_memory_fact(
        session, subject="st_cd", fact="student status code", origin="manual"
    )
    assert inferred_id is not None
    assert user_id is not None
    # The user fact is newer, but inferred still sorts first by default —
    # `docs/ux/memory.md` §2's own reason: alphabetical or recency would
    # bury exactly what the screen exists to surface.
    await _backdate(session, user_id, hours_ago=2)

    screen = await get_memory_screen(session)

    assert [row.id for row in screen.rows] == [inferred_id, user_id]
    assert screen.inferred_count == 1


@pytest.mark.asyncio
async def test_memory_screen_reports_usage_count_per_row(session: AsyncSession) -> None:
    fact_id = await write_memory_fact(
        session, subject="st_cd", fact="student status code", origin="manual"
    )
    assert fact_id is not None
    await _mark_used(session, fact_kind="memory", fact_id=fact_id)
    await _mark_used(session, fact_kind="memory", fact_id=fact_id)

    screen = await get_memory_screen(session)

    assert screen.rows[0].usage_count == 2


@pytest.mark.asyncio
async def test_memory_screen_shows_an_unused_fact_rather_than_hiding_it(
    session: AsyncSession,
) -> None:
    fact_id = await write_memory_fact(
        session, subject="st_cd", fact="student status code", origin="manual"
    )
    assert fact_id is not None

    screen = await get_memory_screen(session)

    assert [row.id for row in screen.rows] == [fact_id]
    assert screen.rows[0].usage_count == 0


@pytest.mark.asyncio
async def test_memory_screen_labels_a_general_fact_from_a_deleted_source(
    session: AsyncSession,
) -> None:
    source_id = await _source(session, name="tender-files")
    fact_id = await write_memory_fact(
        session,
        subject="rfq",
        fact="Request for Quotation",
        origin="clarification",
        source_id=source_id,
    )
    assert fact_id is not None
    await session.execute(
        text("UPDATE sources SET status = 'deleted', deleted_at = now() WHERE id = :id"),
        {"id": source_id},
    )

    screen = await get_memory_screen(session)

    assert screen.rows[0].source_name == "tender-files"
    assert screen.rows[0].source_deleted is True


@pytest.mark.asyncio
async def test_memory_screen_carries_struck_through_history_on_a_conflict(
    session: AsyncSession,
) -> None:
    fact_id = await write_memory_fact(
        session, subject="st_cd", fact="student status code", origin="clarification"
    )
    assert fact_id is not None
    outcome = await correct_memory_fact(session, fact_id=fact_id, fact="student code")

    screen = await get_memory_screen(session)

    assert screen.rows[0].id == outcome.fact_id
    assert screen.rows[0].value == "student code"
    assert [entry.value for entry in screen.rows[0].history] == ["student status code"]


@pytest.mark.asyncio
async def test_memory_screen_includes_schema_notes_with_a_dotted_subject(
    session: AsyncSession,
) -> None:
    source_id = await _source(session, name="sales-2024")
    note_id = await write_schema_note(
        session,
        source_id=source_id,
        table_name="invoices",
        column_name="st_cd",
        description="invoice status",
        origin="user",
    )
    assert note_id is not None

    screen = await get_memory_screen(session)

    assert screen.rows[0].fact_kind == "schema_note"
    assert screen.rows[0].subject == "invoices.st_cd"
    assert screen.rows[0].source_name == "sales-2024"
    assert screen.rows[0].source_deleted is False


# --- confirm: M3-MEM-FE-084 ---------------------------------------------


@pytest.mark.asyncio
async def test_confirming_an_inferred_fact_promotes_in_place_with_no_new_row(
    session: AsyncSession,
) -> None:
    fact_id = await write_memory_fact(
        session, subject="st_cd", fact="a guess", origin="inferred", confidence=0.3
    )
    assert fact_id is not None

    outcome = await confirm_memory_fact(session, fact_id=fact_id)

    assert outcome.fact_id == fact_id
    assert outcome.already_confirmed is False
    rows = (await session.execute(text("SELECT id, origin, confidence FROM memory"))).all()
    assert len(rows) == 1
    row_id, origin, confidence = rows[0]
    assert row_id == fact_id
    assert origin == "correction"
    assert float(confidence) == FULL_CONFIDENCE


@pytest.mark.asyncio
async def test_confirming_leaves_no_decision_shaped_like_reprocessing(
    session: AsyncSession,
) -> None:
    source_id = await _source(session)
    document_id = await _document(session, source_id, "policy.pdf")
    await _chunk(session, document_id)
    fact_id = await write_memory_fact(
        session,
        subject="policy",
        fact="a guess",
        origin="inferred",
        confidence=0.3,
        source_id=source_id,
    )
    assert fact_id is not None

    await confirm_memory_fact(session, fact_id=fact_id)

    kinds = (await session.execute(text("SELECT kind FROM audit_decisions"))).all()
    assert [k for (k,) in kinds] == ["memory_written", "memory_confirmed"]


@pytest.mark.asyncio
async def test_confirming_an_already_user_fact_is_a_no_op(session: AsyncSession) -> None:
    fact_id = await write_memory_fact(
        session, subject="rfq", fact="Request for Quotation", origin="manual"
    )
    assert fact_id is not None

    outcome = await confirm_memory_fact(session, fact_id=fact_id)

    assert outcome.already_confirmed is True


@pytest.mark.asyncio
async def test_confirming_an_unknown_fact_raises(session: AsyncSession) -> None:
    with pytest.raises(FactNotFound):
        await confirm_memory_fact(session, fact_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_confirming_then_editing_leaves_two_records_in_order(session: AsyncSession) -> None:
    """Edge case named by the ticket: confirm, then edit — two records,
    correct order."""
    fact_id = await write_memory_fact(
        session, subject="st_cd", fact="status code", origin="inferred", confidence=0.3
    )
    assert fact_id is not None
    await confirm_memory_fact(session, fact_id=fact_id)

    outcome = await correct_memory_fact(session, fact_id=fact_id, fact="student status code")

    history = (
        await session.execute(
            text("SELECT id, fact, superseded_by FROM memory ORDER BY created_at")
        )
    ).all()
    by_id = {row[0]: (row[1], row[2]) for row in history}
    assert by_id[fact_id] == ("status code", outcome.fact_id)
    assert by_id[outcome.fact_id] == ("student status code", None)


@pytest.mark.asyncio
async def test_confirming_a_schema_note_promotes_to_user_origin(session: AsyncSession) -> None:
    source_id = await _source(session)
    note_id = await write_schema_note(
        session,
        source_id=source_id,
        table_name="invoices",
        column_name="st_cd",
        description="a guess",
        origin="inferred",
        confidence=0.3,
    )
    assert note_id is not None

    outcome = await confirm_schema_note(session, note_id=note_id)

    assert outcome.already_confirmed is False
    row = (
        await session.execute(
            text("SELECT origin, confidence FROM schema_notes WHERE id = :id"), {"id": note_id}
        )
    ).first()
    assert row is not None
    assert row[0] == "user"
    assert float(row[1]) == FULL_CONFIDENCE


@pytest.mark.asyncio
async def test_confirm_fact_dispatches_by_kind(session: AsyncSession) -> None:
    fact_id = await write_memory_fact(
        session, subject="rfq", fact="a guess", origin="inferred", confidence=0.3
    )
    assert fact_id is not None

    outcome = await confirm_fact(session, fact_kind="memory", fact_id=fact_id)
    assert outcome.already_confirmed is False

    with pytest.raises(ValueError):
        await confirm_fact(session, fact_kind="nonsense", fact_id=fact_id)


# --- manual entry: M3-MEM-FE-084 -----------------------------------------


@pytest.mark.asyncio
async def test_manual_entry_creates_a_user_supplied_fact(session: AsyncSession) -> None:
    outcome = await add_manual_fact(session, subject="rfq", fact="Request for Quotation")

    assert outcome.duplicate_of is None
    assert outcome.fact_id is not None
    active = await get_active_memory_facts(session, subject="rfq")
    assert len(active) == 1
    assert active[0].origin == "manual"
    assert active[0].confidence == FULL_CONFIDENCE


@pytest.mark.asyncio
async def test_manual_entry_duplicating_a_subject_is_offered_as_a_correction(
    session: AsyncSession,
) -> None:
    fact_id = await write_memory_fact(
        session, subject="rfq", fact="Request for Quotation", origin="manual"
    )
    assert fact_id is not None

    outcome = await add_manual_fact(session, subject="rfq", fact="Request for Quote")

    assert outcome.fact_id is None
    assert outcome.duplicate_of is not None
    assert outcome.duplicate_of.id == fact_id
    assert outcome.duplicate_of.fact == "Request for Quotation"
    # nothing new was written
    active = await get_active_memory_facts(session, subject="rfq")
    assert len(active) == 1
    assert active[0].id == fact_id


# --- delete-all-memory: M3-MEM-FE-084 ------------------------------------


@pytest.mark.asyncio
async def test_delete_all_memory_removes_everything_and_counts_it(session: AsyncSession) -> None:
    source_id = await _source(session)
    await write_memory_fact(session, subject="rfq", fact="Request for Quotation", origin="manual")
    await write_schema_note(
        session,
        source_id=source_id,
        table_name="invoices",
        column_name="st_cd",
        description="invoice status",
        origin="user",
    )

    outcome = await delete_all_memory(session, expected_count=2)

    assert outcome.deleted_count == 2
    screen = await get_memory_screen(session)
    assert screen.rows == []


@pytest.mark.asyncio
async def test_delete_all_memory_refuses_a_stale_count(session: AsyncSession) -> None:
    await write_memory_fact(session, subject="rfq", fact="Request for Quotation", origin="manual")

    with pytest.raises(StaleMemoryCount):
        await delete_all_memory(session, expected_count=0)

    # nothing was deleted
    screen = await get_memory_screen(session)
    assert len(screen.rows) == 1


# --- #288: deleting a correction must not resurrect the superseded value --


@pytest.mark.asyncio
async def test_deleting_a_correction_does_not_resurrect_the_superseded_value(
    session: AsyncSession,
) -> None:
    fact_id = await write_memory_fact(
        session, subject="policy", fact="30 days", origin="clarification"
    )
    assert fact_id is not None
    corrected = await correct_memory_fact(session, fact_id=fact_id, fact="45 days")

    await delete_memory_fact(session, fact_id=corrected.fact_id)

    active = await get_active_memory_facts(session, subject="policy")
    assert active == []

    # the superseded "30 days" row must still exist and stay inactive —
    # never resurrected, never dropped, so history is not rewritten.
    remaining = (
        await session.execute(
            text("SELECT fact, superseded_by FROM memory WHERE id = :id"), {"id": fact_id}
        )
    ).first()
    assert remaining is not None
    assert remaining[0] == "30 days"
    assert remaining[1] is not None


@pytest.mark.asyncio
async def test_deleting_a_correction_twice_removed_still_does_not_resurrect(
    session: AsyncSession,
) -> None:
    """A three-value chain, deleting the newest active value: the middle
    value must not come back either."""
    fact_id = await write_memory_fact(
        session, subject="policy", fact="30 days", origin="clarification"
    )
    assert fact_id is not None
    corrected_once = await correct_memory_fact(session, fact_id=fact_id, fact="45 days")
    corrected_twice = await correct_memory_fact(
        session, fact_id=corrected_once.fact_id, fact="60 days"
    )

    await delete_memory_fact(session, fact_id=corrected_twice.fact_id)

    assert await get_active_memory_facts(session, subject="policy") == []
    rows = dict((await session.execute(text("SELECT id, superseded_by FROM memory"))).all())
    assert rows[fact_id] is not None
    assert rows[corrected_once.fact_id] is not None


@pytest.mark.asyncio
async def test_deleting_a_schema_note_correction_does_not_resurrect(
    session: AsyncSession,
) -> None:
    source_id = await _source(session)
    note_id = await write_schema_note(
        session,
        source_id=source_id,
        table_name="invoices",
        column_name="st_cd",
        description="O=open, P=paid",
        origin="user",
    )
    assert note_id is not None
    corrected = await correct_schema_note(
        session, note_id=note_id, description="O=open, P=paid, W=written off"
    )

    await delete_schema_note(session, note_id=corrected.fact_id)

    active = await get_active_schema_notes(session, source_id=source_id)
    assert active == []
    remaining = (
        await session.execute(
            text("SELECT description, superseded_by FROM schema_notes WHERE id = :id"),
            {"id": note_id},
        )
    ).first()
    assert remaining is not None
    assert remaining[1] is not None
