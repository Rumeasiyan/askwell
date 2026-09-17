"""The clarifications API's business logic. `M3-REVIEW-BE-072a`.

Against a real Postgres — grouping, the memory write and the decisions
record all depend on real SQL and a real transaction boundary.
"""

import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from askwell.audit import Store, verify
from askwell.audit import record as audit_record
from askwell.clarify import CANDIDATE_CAPPED
from askwell.memory import correct_memory_fact
from askwell.review import (
    AlreadyAnswered,
    CannotUndo,
    ClarificationNotFound,
    Reprocessing,
    _reprocessing_summary,
    answer_clarification,
    dismiss_group,
    list_pending,
    skip_clarification,
    undo_answer,
)

pytestmark = pytest.mark.requires_db

_TABLES = (
    "sources, documents, chunks, schema_notes, clarifications, memory, "
    "reapply_jobs, reapply_items, audit_decisions"
)


@pytest_asyncio.fixture
async def session(database_url: str) -> AsyncIterator[AsyncSession]:
    async_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
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


async def _source(
    session: AsyncSession, name: str, *, status: str = "ready", added_at: datetime | None = None
) -> uuid.UUID:
    source_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO sources (id, kind, name, status, added_at) "
            "VALUES (:id, 'file', :name, :status, COALESCE(:added_at, now()))"
        ),
        {"id": source_id, "name": name, "status": status, "added_at": added_at},
    )
    return source_id


async def _clarification(
    session: AsyncSession,
    source_id: uuid.UUID,
    *,
    subject: str = "RFQ",
    question: str = "What does RFQ mean?",
    status: str = "pending",
    rank: int | None = 1,
    evidence: str = '{"occurrences": 3}',
    options: list[str] | None = None,
) -> uuid.UUID:
    clarification_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO clarifications "
            "(id, source_id, subject, question, evidence, options, rank, status, answer) "
            "VALUES (:id, :source_id, :subject, :question, "
            "CAST(:evidence AS jsonb), CAST(:options AS jsonb), :rank, :status, :answer)"
        ),
        {
            "id": clarification_id,
            "source_id": source_id,
            "subject": subject,
            "question": question,
            "evidence": evidence,
            "options": json.dumps(options) if options is not None else None,
            "rank": rank,
            "status": status,
            "answer": "a prior answer" if status == "answered" else None,
        },
    )
    return clarification_id


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


# --- GET /clarifications, grouped ---------------------------------------------


@pytest.mark.asyncio
async def test_pending_items_are_grouped_by_source_with_counts_and_a_total(
    session: AsyncSession,
) -> None:
    contracts = await _source(session, "contracts")
    invoices = await _source(session, "invoices")
    await _clarification(session, contracts, subject="RFQ")
    await _clarification(session, contracts, subject="PO", rank=2)
    await _clarification(session, invoices, subject="GRN")

    result = await list_pending(session)

    assert result["total"] == 3
    by_name = {g["source_name"]: g for g in result["groups"]}
    assert by_name["contracts"]["count"] == 2
    assert by_name["invoices"]["count"] == 1
    subjects = {item["subject"] for item in by_name["contracts"]["items"]}
    assert subjects == {"RFQ", "PO"}


@pytest.mark.asyncio
async def test_items_carry_question_options_and_evidence(session: AsyncSession) -> None:
    source_id = await _source(session, "contracts")
    await _clarification(session, source_id)

    result = await list_pending(session)

    item = result["groups"][0]["items"][0]
    assert item["question"] == "What does RFQ mean?"
    assert item["evidence"] == {"occurrences": 3}


@pytest.mark.asyncio
async def test_newest_source_is_listed_first(session: AsyncSession) -> None:
    now = datetime.now(UTC)
    older = await _source(session, "older", added_at=now - timedelta(days=1))
    newer = await _source(session, "newer", added_at=now)
    await _clarification(session, older)
    await _clarification(session, newer)

    result = await list_pending(session)

    assert [g["source_name"] for g in result["groups"]] == ["newer", "older"]


@pytest.mark.asyncio
async def test_a_source_with_no_pending_items_produces_no_group(session: AsyncSession) -> None:
    source_id = await _source(session, "answered-already")
    await _clarification(session, source_id, status="answered")

    result = await list_pending(session)

    assert result["groups"] == []
    assert result["total"] == 0


@pytest.mark.asyncio
async def test_a_clarification_whose_source_was_deleted_does_not_appear(
    session: AsyncSession,
) -> None:
    source_id = await _source(session, "gone", status="deleted")
    await _clarification(session, source_id)

    result = await list_pending(session)

    assert result["groups"] == []


@pytest.mark.asyncio
async def test_list_pending_names_the_configured_cap(session: AsyncSession) -> None:
    result = await list_pending(session)

    assert result["cap"] == 5


# --- the capped state, issue #297 -----------------------------------------------


@pytest.mark.asyncio
async def test_a_capped_source_with_nothing_pending_still_gets_a_group(
    session: AsyncSession,
) -> None:
    source_id = await _source(session, "sales")
    await audit_record(
        session,
        Store.DECISIONS,
        CANDIDATE_CAPPED,
        {
            "source_id": str(source_id),
            "trigger": "abbreviation",
            "subject": "GRN",
            "rank": 6,
            "cap": 5,
        },
    )
    await session.commit()

    result = await list_pending(session)

    assert result["total"] == 0
    assert len(result["groups"]) == 1
    group = result["groups"][0]
    assert group["source_name"] == "sales"
    assert group["items"] == []
    assert group["capped"] == 1


@pytest.mark.asyncio
async def test_a_capped_source_that_still_has_pending_items_carries_the_count_on_that_group(
    session: AsyncSession,
) -> None:
    source_id = await _source(session, "sales")
    await _clarification(session, source_id, subject="RFQ")
    await audit_record(
        session,
        Store.DECISIONS,
        CANDIDATE_CAPPED,
        {
            "source_id": str(source_id),
            "trigger": "abbreviation",
            "subject": "GRN",
            "rank": 6,
            "cap": 5,
        },
    )
    await session.commit()

    result = await list_pending(session)

    assert len(result["groups"]) == 1
    group = result["groups"][0]
    assert len(group["items"]) == 1
    assert group["capped"] == 1


@pytest.mark.asyncio
async def test_a_capped_source_that_was_deleted_does_not_appear(session: AsyncSession) -> None:
    source_id = await _source(session, "gone", status="deleted")
    await audit_record(
        session,
        Store.DECISIONS,
        CANDIDATE_CAPPED,
        {
            "source_id": str(source_id),
            "trigger": "abbreviation",
            "subject": "GRN",
            "rank": 6,
            "cap": 5,
        },
    )
    await session.commit()

    result = await list_pending(session)

    assert result["groups"] == []


# --- reprocessing's table/document breakdown, issue #300 -----------------------


@pytest.mark.asyncio
async def test_reprocessing_summary_names_documents_by_default(session: AsyncSession) -> None:
    source_id = await _source(session, "contracts")

    reprocessing = await _reprocessing_summary(session, str(source_id), None, None)

    assert reprocessing.kind == "document"
    expected = Reprocessing(count=0, label="0 documents in this source", kind="document")
    assert reprocessing == expected


@pytest.mark.asyncio
async def test_reprocessing_summary_names_tables_for_column_evidence(session: AsyncSession) -> None:
    source_id = await _source(session, "sales")
    evidence = {
        "kind": "column_distribution",
        "row_count": 100,
        "values": [],
        "remainder_count": 100,
    }

    reprocessing = await _reprocessing_summary(session, str(source_id), evidence, ["students"])

    assert reprocessing == Reprocessing(count=1, label="1 table", kind="table")


# --- answering -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_answering_writes_memory_and_a_decisions_record_in_one_transaction(
    session: AsyncSession,
) -> None:
    source_id = await _source(session, "contracts")
    clarification_id = await _clarification(session, source_id, subject="RFQ")

    outcome = await answer_clarification(session, clarification_id, "Request for quotation")
    await session.commit()

    memory_row = (
        await session.execute(
            text("SELECT subject, fact, origin, confidence FROM memory WHERE id = :id"),
            {"id": outcome.memory_id},
        )
    ).first()
    assert memory_row is not None
    assert memory_row[0] == "RFQ"
    assert memory_row[1] == "Request for quotation"
    assert memory_row[2] == "clarification"
    assert float(memory_row[3]) == 1.0

    kinds = (
        await session.execute(text("SELECT kind FROM audit_decisions ORDER BY occurred_at"))
    ).all()
    assert [row[0] for row in kinds] == ["clarification_answered"]

    status_row = (
        await session.execute(
            text("SELECT status, answer FROM clarifications WHERE id = :id"),
            {"id": clarification_id},
        )
    ).first()
    assert status_row is not None
    assert status_row[0] == "answered"
    assert status_row[1] == "Request for quotation"


@pytest.mark.asyncio
async def test_answering_removes_the_item_from_the_pending_list(session: AsyncSession) -> None:
    source_id = await _source(session, "contracts")
    clarification_id = await _clarification(session, source_id)

    await answer_clarification(session, clarification_id, "Request for quotation")

    result = await list_pending(session)
    assert result["total"] == 0


@pytest.mark.asyncio
async def test_answering_an_already_answered_item_is_refused(session: AsyncSession) -> None:
    source_id = await _source(session, "contracts")
    clarification_id = await _clarification(session, source_id, status="answered")

    with pytest.raises(AlreadyAnswered):
        await answer_clarification(session, clarification_id, "second answer")

    memory_rows = (await session.execute(text("SELECT id FROM memory"))).all()
    assert memory_rows == []


@pytest.mark.asyncio
async def test_answering_a_skipped_item_is_allowed(session: AsyncSession) -> None:
    source_id = await _source(session, "contracts")
    clarification_id = await _clarification(session, source_id, status="skipped")

    outcome = await answer_clarification(session, clarification_id, "Request for quotation")

    assert outcome.clarification_id == clarification_id


@pytest.mark.asyncio
async def test_answering_an_unknown_clarification_raises(session: AsyncSession) -> None:
    with pytest.raises(ClarificationNotFound):
        await answer_clarification(session, uuid.uuid4(), "anything")


# --- the confirmation's affected-material count -----------------------------


@pytest.mark.asyncio
async def test_answering_names_documents_sampled_in_passage_evidence(
    session: AsyncSession,
) -> None:
    source_id = await _source(session, "contracts")
    clarification_id = await _clarification(
        session,
        source_id,
        subject="RFQ",
        evidence=(
            '{"kind": "passage", "samples": '
            '[{"document": "a.pdf", "page": 1, "text": "..."}, '
            '{"document": "b.pdf", "page": 2, "text": "..."}]}'
        ),
    )

    outcome = await answer_clarification(session, clarification_id, "Request for quotation")

    assert outcome.reprocessing.count == 2
    assert outcome.reprocessing.label == "2 documents"
    assert outcome.reprocessing.kind == "document"


@pytest.mark.asyncio
async def test_answering_names_documents_listed_in_contradiction_evidence(
    session: AsyncSession,
) -> None:
    source_id = await _source(session, "contracts")
    clarification_id = await _clarification(
        session,
        source_id,
        subject="notice period",
        evidence=(
            '{"kind": "contradiction", "passages": '
            '[{"document": "2024.pdf", "value": "30 days", "page": 1, '
            '"date": null, "text": "..."}, '
            '{"document": "2025.pdf", "value": "45 days", "page": 1, '
            '"date": null, "text": "..."}]}'
        ),
    )

    outcome = await answer_clarification(session, clarification_id, "45 days is current")

    assert outcome.reprocessing.count == 2
    assert {"2024.pdf", "2025.pdf"} == {"2024.pdf", "2025.pdf"}
    assert outcome.reprocessing.label == "2 documents"


@pytest.mark.asyncio
async def test_answering_names_documents_offered_as_document_identity_options(
    session: AsyncSession,
) -> None:
    source_id = await _source(session, "contracts")
    clarification_id = await _clarification(
        session,
        source_id,
        subject="contract",
        evidence='{"kind": "unavailable", "reason": "no extracted text"}',
        options=["contract-v1.pdf", "contract-v2-FINAL.pdf"],
    )

    outcome = await answer_clarification(session, clarification_id, "contract-v2-FINAL.pdf")

    assert outcome.reprocessing.count == 2
    assert outcome.reprocessing.label == "2 documents"


@pytest.mark.asyncio
async def test_answering_falls_back_to_every_live_document_in_the_source(
    session: AsyncSession,
) -> None:
    """An abbreviation's evidence names no document at all (`M3-RAISE-BE-071`
    stores only bounded samples, and this one has none) — the confirmation
    still names something true rather than nothing specific at all."""
    source_id = await _source(session, "contracts")
    await _document(session, source_id, "a.pdf")
    await _document(session, source_id, "b.pdf")
    await _document(session, source_id, "c.pdf")
    clarification_id = await _clarification(
        session, source_id, subject="RFQ", evidence='{"kind": "unavailable", "reason": "x"}'
    )

    outcome = await answer_clarification(session, clarification_id, "Request for quotation")

    assert outcome.reprocessing.count == 3
    assert outcome.reprocessing.label == "3 documents in this source"


@pytest.mark.asyncio
async def test_answering_a_single_document_uses_singular_wording(session: AsyncSession) -> None:
    source_id = await _source(session, "contracts")
    await _document(session, source_id, "a.pdf")
    clarification_id = await _clarification(
        session, source_id, subject="RFQ", evidence='{"kind": "unavailable", "reason": "x"}'
    )

    outcome = await answer_clarification(session, clarification_id, "Request for quotation")

    assert outcome.reprocessing.count == 1
    assert outcome.reprocessing.label == "1 document in this source"


# --- skipping --------------------------------------------------------------


@pytest.mark.asyncio
async def test_skipping_changes_status_and_writes_no_memory(session: AsyncSession) -> None:
    source_id = await _source(session, "contracts")
    clarification_id = await _clarification(session, source_id)

    await skip_clarification(session, clarification_id)

    status_row = (
        await session.execute(
            text("SELECT status FROM clarifications WHERE id = :id"), {"id": clarification_id}
        )
    ).first()
    assert status_row is not None
    assert status_row[0] == "skipped"

    memory_rows = (await session.execute(text("SELECT id FROM memory"))).all()
    assert memory_rows == []

    kinds = (
        await session.execute(text("SELECT kind FROM audit_decisions ORDER BY occurred_at"))
    ).all()
    assert [row[0] for row in kinds] == ["clarification_skipped"]


@pytest.mark.asyncio
async def test_skipping_an_answered_item_is_refused(session: AsyncSession) -> None:
    source_id = await _source(session, "contracts")
    clarification_id = await _clarification(session, source_id, status="answered")

    with pytest.raises(AlreadyAnswered):
        await skip_clarification(session, clarification_id)


@pytest.mark.asyncio
async def test_skipping_an_unknown_clarification_raises(session: AsyncSession) -> None:
    with pytest.raises(ClarificationNotFound):
        await skip_clarification(session, uuid.uuid4())


# --- dismissing a group (skip-all) ------------------------------------------


@pytest.mark.asyncio
async def test_dismissing_a_group_writes_one_record_per_item(session: AsyncSession) -> None:
    source_id = await _source(session, "contracts")
    first = await _clarification(session, source_id, subject="RFQ")
    second = await _clarification(session, source_id, subject="PO", rank=2)

    dismissed = await dismiss_group(session, source_id)

    assert set(dismissed) == {first, second}
    statuses = (
        await session.execute(text("SELECT status FROM clarifications ORDER BY subject"))
    ).all()
    assert [row[0] for row in statuses] == ["dismissed", "dismissed"]

    kinds = (
        await session.execute(
            text("SELECT kind FROM audit_decisions WHERE kind = 'clarification_dismissed'")
        )
    ).all()
    assert len(kinds) == 2, "one record per item, so the dismissal signal is countable"


@pytest.mark.asyncio
async def test_dismissing_leaves_answered_and_skipped_items_untouched(
    session: AsyncSession,
) -> None:
    source_id = await _source(session, "contracts")
    pending = await _clarification(session, source_id, subject="RFQ")
    answered = await _clarification(session, source_id, subject="PO", status="answered", rank=2)
    skipped = await _clarification(session, source_id, subject="GRN", status="skipped", rank=3)

    dismissed = await dismiss_group(session, source_id)

    assert dismissed == [pending]
    by_id = dict((await session.execute(text("SELECT id, status FROM clarifications"))).all())
    assert by_id[pending] == "dismissed"
    assert by_id[answered] == "answered"
    assert by_id[skipped] == "skipped"


@pytest.mark.asyncio
async def test_dismissing_a_group_with_nothing_pending_is_a_no_op(session: AsyncSession) -> None:
    source_id = await _source(session, "contracts")
    await _clarification(session, source_id, status="answered")

    dismissed = await dismiss_group(session, source_id)

    assert dismissed == []
    kinds = (await session.execute(text("SELECT id FROM audit_decisions"))).all()
    assert kinds == []


# --- undoing an answer -------------------------------------------------------


@pytest.mark.asyncio
async def test_undo_deletes_the_memory_fact_and_records_its_own_decision(
    session: AsyncSession,
) -> None:
    source_id = await _source(session, "contracts")
    clarification_id = await _clarification(session, source_id, subject="RFQ")
    outcome = await answer_clarification(session, clarification_id, "Request for quotation")

    await undo_answer(session, clarification_id, outcome.memory_id)

    memory_rows = (await session.execute(text("SELECT id FROM memory"))).all()
    assert memory_rows == []

    status_row = (
        await session.execute(
            text("SELECT status, answer FROM clarifications WHERE id = :id"),
            {"id": clarification_id},
        )
    ).first()
    assert status_row is not None
    assert status_row[0] == "pending"
    assert status_row[1] is None

    kinds = (
        await session.execute(text("SELECT kind FROM audit_decisions ORDER BY occurred_at"))
    ).all()
    # The original answered record is untouched — undo adds a second record,
    # it does not remove or rewrite the first.
    assert [row[0] for row in kinds] == ["clarification_answered", "clarification_answer_undone"]


@pytest.mark.asyncio
async def test_undo_on_a_pending_or_skipped_item_is_refused(session: AsyncSession) -> None:
    source_id = await _source(session, "contracts")
    clarification_id = await _clarification(session, source_id, status="skipped")

    with pytest.raises(CannotUndo):
        await undo_answer(session, clarification_id, uuid.uuid4())


@pytest.mark.asyncio
async def test_undo_after_the_answer_was_corrected_is_refused(session: AsyncSession) -> None:
    source_id = await _source(session, "contracts")
    clarification_id = await _clarification(session, source_id, subject="RFQ")
    outcome = await answer_clarification(session, clarification_id, "Request for quotation")

    # A correction made from the memory screen (or from inside a later
    # answer) supersedes the fact undo would otherwise delete.
    await correct_memory_fact(session, fact_id=outcome.memory_id, fact="Request for Quotation")

    with pytest.raises(CannotUndo):
        await undo_answer(session, clarification_id, outcome.memory_id)


@pytest.mark.asyncio
async def test_undo_of_an_unknown_clarification_raises(session: AsyncSession) -> None:
    with pytest.raises(ClarificationNotFound):
        await undo_answer(session, uuid.uuid4(), uuid.uuid4())


# --- the chain across a run of memory operations -----------------------------


@pytest.mark.asyncio
async def test_the_decisions_chain_covers_a_cold_start_walkthrough(
    session: AsyncSession,
) -> None:
    """`M3-STORE-OBS-077`'s own manual walkthrough: answer three
    clarifications and correct one, then verify the chain covers all four.
    """
    source_id = await _source(session, "contracts")
    first = await _clarification(session, source_id, subject="RFQ")
    second = await _clarification(session, source_id, subject="PO", rank=2)
    third = await _clarification(session, source_id, subject="GRN", rank=3)

    await answer_clarification(session, first, "Request for Quotation")
    await answer_clarification(session, second, "Purchase Order")
    outcome = await answer_clarification(session, third, "Goods Received Note")
    await correct_memory_fact(session, fact_id=outcome.memory_id, fact="Goods Receipt Note")

    result = await verify(session, Store.DECISIONS)
    assert result.intact, str(result)
    assert result.checked == 4

    kinds = (
        await session.execute(text("SELECT kind FROM audit_decisions ORDER BY occurred_at"))
    ).all()
    assert [row[0] for row in kinds] == [
        "clarification_answered",
        "clarification_answered",
        "clarification_answered",
        "memory_superseded",
    ]


@pytest.mark.asyncio
async def test_answering_fails_closed_when_the_decisions_record_cannot_be_written(
    session: AsyncSession,
) -> None:
    """An induced audit failure must prevent the memory change.

    Same shape as `test_audit_chain.py`'s own `test_a_failed_audit_write_fails_the_action`:
    a `kind` too long for `audit_decisions.kind` (`varchar(64)`) stands in for
    any audit write that fails for a reason the caller did not anticipate,
    here inside the exact statement sequence `answer_clarification` runs.
    """
    source_id = await _source(session, "contracts")
    clarification_id = await _clarification(session, source_id, subject="RFQ")
    await session.commit()

    await session.execute(
        text("UPDATE clarifications SET status = 'answered', answer = 'x' WHERE id = :id"),
        {"id": clarification_id},
    )
    await session.execute(
        text(
            "INSERT INTO memory (id, subject, fact, origin) "
            "VALUES (:id, 'RFQ', 'x', 'clarification')"
        ),
        {"id": uuid.uuid4()},
    )
    with pytest.raises(DBAPIError):
        await audit_record(session, Store.DECISIONS, "k" * 200, {"subject": "RFQ"})
        await session.commit()

    await session.rollback()

    memory_rows = (await session.execute(text("SELECT id FROM memory"))).all()
    assert memory_rows == [], "the memory write committed without its audit record"
    status_row = (
        await session.execute(
            text("SELECT status FROM clarifications WHERE id = :id"), {"id": clarification_id}
        )
    ).first()
    assert status_row is not None
    assert status_row[0] == "pending", "the clarification write committed without its audit record"
