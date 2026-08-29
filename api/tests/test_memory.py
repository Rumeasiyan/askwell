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
    correct_memory_fact,
    correct_schema_note,
    get_active_memory_facts,
    get_active_schema_notes,
    write_memory_fact,
    write_schema_note,
)

pytestmark = pytest.mark.requires_db

_TABLES = "sources, memory, schema_notes, audit_decisions"


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
        text("INSERT INTO sources (id, kind, name) VALUES (:id, 'file', :name)"),
        {"id": source_id, "name": name},
    )
    return source_id


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
    assert facts[0].confidence is None  # caller supplies confidence explicitly

    # An explicit full-confidence write, as the answer-a-clarification path does.
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

    new_id = await correct_memory_fact(session, fact_id=fact_id, fact="student cohort code")

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
    second_id = await correct_memory_fact(session, fact_id=fact_id, fact="45 days")
    third_id = await correct_memory_fact(session, fact_id=second_id, fact="60 days")

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

    new_id = await correct_schema_note(
        session, note_id=user_note_id, description="student cohort code"
    )
    active = await get_active_schema_notes(session, source_id=source_id)
    current = [n for n in active if n.table_name == "students" and n.column_name == "st_cd"]
    assert len(current) == 1
    assert current[0].id == new_id
    assert current[0].description == "student cohort code"
    assert current[0].origin == "user"


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
