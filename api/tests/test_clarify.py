"""Ambiguity detection and the three tests for asking. `M3-RAISE-BE-068`.

Against a real Postgres — every trigger reads `chunks`/`document_pages`/
`documents` and writes `clarifications`/`memory`, so a fake session would
just be re-implementing the SQL under test.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from askwell.clarify import (
    EVIDENCE_MAX_COLUMN_VALUES,
    Candidate,
    RaiseResult,
    _bound_text,
    _evaluate,
    _normalize_filename,
    column_distribution_evidence,
    raise_candidates,
)

pytestmark = pytest.mark.requires_db

_THRESHOLD = 0.60
_TABLES = "sources, documents, document_pages, chunks, memory, clarifications, audit_decisions"


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


async def _source(session: AsyncSession) -> uuid.UUID:
    source_id = uuid.uuid4()
    await session.execute(
        text("INSERT INTO sources (id, kind, name) VALUES (:id, 'file', 'a source')"),
        {"id": source_id},
    )
    return source_id


async def _document(
    session: AsyncSession,
    source_id: uuid.UUID,
    filename: str,
    *,
    ocr_confidence: float | None = None,
    superseded_by: uuid.UUID | None = None,
    added_at: datetime | None = None,
) -> uuid.UUID:
    document_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO documents "
            "(id, source_id, filename, path, sha256, status, ocr_confidence, "
            "superseded_by, added_at) "
            "VALUES (:id, :source_id, :filename, :path, :sha256, 'ready', "
            ":ocr_confidence, :superseded_by, COALESCE(:added_at, now()))"
        ),
        {
            "id": document_id,
            "source_id": source_id,
            "filename": filename,
            "path": f"/tmp/{filename}",
            "sha256": uuid.uuid4().hex.ljust(64, "0")[:64],
            "ocr_confidence": ocr_confidence,
            "superseded_by": superseded_by,
            "added_at": added_at,
        },
    )
    return document_id


async def _chunk(session: AsyncSession, document_id: uuid.UUID, content: str) -> None:
    await session.execute(
        text(
            "INSERT INTO chunks (id, document_id, ordinal, content) "
            "VALUES (:id, :document_id, 0, :content)"
        ),
        {"id": uuid.uuid4(), "document_id": document_id, "content": content},
    )


async def _page(
    session: AsyncSession,
    document_id: uuid.UUID,
    page_number: int,
    text_: str,
    *,
    ocr_confidence: float | None = None,
) -> None:
    await session.execute(
        text(
            "INSERT INTO document_pages (document_id, page_number, text, has_text, ocr_confidence) "
            "VALUES (:document_id, :page_number, :text, true, :ocr_confidence)"
        ),
        {
            "document_id": document_id,
            "page_number": page_number,
            "text": text_,
            "ocr_confidence": ocr_confidence,
        },
    )


# --- the filter itself -------------------------------------------------------


def test_all_three_tests_holding_passes() -> None:
    assert _evaluate(cannot_determine=True, material=True, user_knows=True) is None


def test_any_failing_test_is_named_in_the_reason() -> None:
    reason = _evaluate(cannot_determine=True, material=False, user_knows=True)
    assert reason == "failed: material"


def test_multiple_failures_are_all_named() -> None:
    reason = _evaluate(cannot_determine=False, material=False, user_knows=False)
    assert reason is not None
    assert "cannot_determine" in reason
    assert "material" in reason
    assert "user_knows" in reason


def test_filename_normalisation_strips_version_tokens() -> None:
    assert _normalize_filename("contract-v1.pdf") == "contract"
    assert _normalize_filename("contract-v2-FINAL.pdf") == "contract"
    assert _normalize_filename("contract (2).docx") == "contract"
    assert _normalize_filename("contract.pdf") == "contract"


# --- abbreviations ------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_repeated_abbreviation_raises_a_candidate(session: AsyncSession) -> None:
    source_id = await _source(session)
    document_id = await _document(session, source_id, "tender.pdf")
    await _chunk(session, document_id, "The RFQ closes Friday.")
    await _chunk(session, document_id, "Submit the RFQ to procurement.")

    result = await raise_candidates(session, source_id, _THRESHOLD)

    assert result == RaiseResult(raised=1, inferred=0, dropped=0)
    rows = (await session.execute(text("SELECT question, status FROM clarifications"))).all()
    assert len(rows) == 1
    assert "RFQ" in rows[0][0]
    assert rows[0][1] == "pending"


@pytest.mark.asyncio
async def test_an_abbreviation_appearing_once_is_filtered_by_materiality(
    session: AsyncSession,
) -> None:
    source_id = await _source(session)
    document_id = await _document(session, source_id, "tender.pdf")
    await _chunk(session, document_id, "The RFQ closes Friday.")

    result = await raise_candidates(session, source_id, _THRESHOLD)

    assert result == RaiseResult(raised=0, inferred=0, dropped=1)
    assert (await session.execute(text("SELECT 1 FROM clarifications"))).first() is None
    # Nothing safe to guess about what an abbreviation means from one
    # occurrence, so nothing is written to memory either — a wrong guess
    # would be fed straight back into future prompts.
    assert (await session.execute(text("SELECT 1 FROM memory"))).first() is None


@pytest.mark.asyncio
async def test_an_abbreviation_already_in_memory_is_never_asked_twice(
    session: AsyncSession,
) -> None:
    source_id = await _source(session)
    document_id = await _document(session, source_id, "tender.pdf")
    await _chunk(session, document_id, "The RFQ closes Friday. Another RFQ follows.")
    await session.execute(
        text(
            "INSERT INTO memory (id, subject, fact, origin) "
            "VALUES (:id, 'RFQ', 'Request for Quotation', 'manual')"
        ),
        {"id": uuid.uuid4()},
    )

    result = await raise_candidates(session, source_id, _THRESHOLD)

    assert result == RaiseResult(raised=0, inferred=0, dropped=0)
    assert (await session.execute(text("SELECT 1 FROM clarifications"))).first() is None


@pytest.mark.asyncio
async def test_a_common_abbreviation_is_never_asked_about(session: AsyncSession) -> None:
    source_id = await _source(session)
    document_id = await _document(session, source_id, "notes.pdf")
    await _chunk(session, document_id, "Exported as PDF. The PDF opens fine.")

    result = await raise_candidates(session, source_id, _THRESHOLD)

    assert result == RaiseResult(raised=0, inferred=0, dropped=0)


@pytest.mark.asyncio
async def test_an_abbreviation_carries_real_passages_as_evidence(session: AsyncSession) -> None:
    source_id = await _source(session)
    document_id = await _document(session, source_id, "tender.pdf")
    await _chunk(session, document_id, "The RFQ closes Friday.")
    await _chunk(session, document_id, "Submit the RFQ to procurement.")

    await raise_candidates(session, source_id, _THRESHOLD)

    evidence = (await session.execute(text("SELECT evidence FROM clarifications"))).scalar_one()
    assert evidence["kind"] == "passage"
    assert evidence["occurrences"] == 2
    assert evidence["samples"]
    assert "RFQ" in evidence["samples"][0]["text"]
    assert evidence["samples"][0]["document"] == "tender.pdf"
    # Nothing safe to guess at what an abbreviation means, so no prefill.
    assert evidence["current_inference"] is None


# --- unreadable scans ---------------------------------------------------------


@pytest.mark.asyncio
async def test_a_materially_poor_scan_raises_a_candidate_naming_its_pages(
    session: AsyncSession,
) -> None:
    source_id = await _source(session)
    document_id = await _document(session, source_id, "contract-final.pdf", ocr_confidence=0.4)
    await _page(session, document_id, 1, "clean text", ocr_confidence=0.95)
    await _page(session, document_id, 2, "garbled", ocr_confidence=0.10)
    await _page(session, document_id, 3, "garbled", ocr_confidence=0.10)

    result = await raise_candidates(session, source_id, _THRESHOLD)

    assert result == RaiseResult(raised=1, inferred=0, dropped=0)
    question = (await session.execute(text("SELECT question FROM clarifications"))).scalar_one()
    assert "Pages 2-3" in question
    assert "contract-final.pdf" in question


@pytest.mark.asyncio
async def test_one_poor_page_in_a_large_document_is_inferred_not_asked(
    session: AsyncSession,
) -> None:
    source_id = await _source(session)
    document_id = await _document(session, source_id, "report.pdf", ocr_confidence=0.55)
    await _page(session, document_id, 1, "garbled", ocr_confidence=0.10)
    for page_number in range(2, 42):
        await _page(session, document_id, page_number, "clean text", ocr_confidence=0.95)

    result = await raise_candidates(session, source_id, _THRESHOLD)

    assert result == RaiseResult(raised=0, inferred=1, dropped=0)
    fact = await session.execute(text("SELECT fact, origin, confidence FROM memory"))
    row = fact.one()
    assert "report.pdf" in row[0]
    assert row[1] == "inferred"
    assert float(row[2]) < 0.5


@pytest.mark.asyncio
async def test_a_document_with_a_good_scan_raises_nothing(session: AsyncSession) -> None:
    source_id = await _source(session)
    document_id = await _document(session, source_id, "clean.pdf")
    await _page(session, document_id, 1, "clean text", ocr_confidence=0.95)

    result = await raise_candidates(session, source_id, _THRESHOLD)

    assert result == RaiseResult(raised=0, inferred=0, dropped=0)


@pytest.mark.asyncio
async def test_a_poor_scan_carries_extracted_text_and_says_images_are_unavailable(
    session: AsyncSession,
) -> None:
    source_id = await _source(session)
    document_id = await _document(session, source_id, "contract-final.pdf", ocr_confidence=0.4)
    await _page(session, document_id, 1, "clean text", ocr_confidence=0.95)
    await _page(session, document_id, 2, "gar bled words", ocr_confidence=0.10)
    await _page(session, document_id, 3, "more gar bled", ocr_confidence=0.10)

    await raise_candidates(session, source_id, _THRESHOLD)

    evidence = (await session.execute(text("SELECT evidence FROM clarifications"))).scalar_one()
    assert evidence["kind"] == "poor_scan"
    assert evidence["pages"] == [2, 3]
    assert evidence["page_images"] == "not available"
    assert {page["page"] for page in evidence["extracted_text"]} == {2, 3}
    assert "gar bled" in evidence["extracted_text"][0]["text"]
    # A guess exists here — "index as-is" — so the answer field can prefill.
    assert "contract-final.pdf" in evidence["current_inference"]


@pytest.mark.asyncio
async def test_a_poor_scan_with_no_extracted_text_states_evidence_is_unavailable(
    session: AsyncSession,
) -> None:
    source_id = await _source(session)
    document_id = await _document(session, source_id, "blank.pdf", ocr_confidence=0.4)
    await _page(session, document_id, 1, "clean text", ocr_confidence=0.95)
    await _page(session, document_id, 2, " ", ocr_confidence=0.10)
    await _page(session, document_id, 3, " ", ocr_confidence=0.10)

    await raise_candidates(session, source_id, _THRESHOLD)

    evidence = (await session.execute(text("SELECT evidence FROM clarifications"))).scalar_one()
    assert evidence["kind"] == "unavailable"
    assert "blank.pdf" in evidence["reason"]


# --- ambiguous document identity ----------------------------------------------


@pytest.mark.asyncio
async def test_version_like_filenames_raise_a_candidate_naming_the_newest(
    session: AsyncSession,
) -> None:
    source_id = await _source(session)
    now = datetime.now(UTC)
    await _document(session, source_id, "contract-v1.pdf", added_at=now - timedelta(days=2))
    await _document(session, source_id, "contract-v2-FINAL.pdf", added_at=now)

    result = await raise_candidates(session, source_id, _THRESHOLD)

    assert result == RaiseResult(raised=1, inferred=0, dropped=0)
    question = (await session.execute(text("SELECT question FROM clarifications"))).scalar_one()
    assert "contract-v2-FINAL.pdf" in question
    assert "contract-v1.pdf" in question


@pytest.mark.asyncio
async def test_a_lone_document_is_never_ambiguous(session: AsyncSession) -> None:
    source_id = await _source(session)
    await _document(session, source_id, "contract.pdf")

    result = await raise_candidates(session, source_id, _THRESHOLD)

    assert result == RaiseResult(raised=0, inferred=0, dropped=0)


@pytest.mark.asyncio
async def test_a_resolved_version_chain_is_not_re_asked(session: AsyncSession) -> None:
    source_id = await _source(session)
    newest = await _document(session, source_id, "contract-v2.pdf")
    await _document(session, source_id, "contract-v1.pdf", superseded_by=newest)

    result = await raise_candidates(session, source_id, _THRESHOLD)

    # Only `contract-v2.pdf` is live once the superseded one is excluded —
    # one document per normalised stem is not ambiguous.
    assert result == RaiseResult(raised=0, inferred=0, dropped=0)


@pytest.mark.asyncio
async def test_document_identity_carries_a_passage_from_the_newest_file(
    session: AsyncSession,
) -> None:
    source_id = await _source(session)
    now = datetime.now(UTC)
    await _document(session, source_id, "contract-v1.pdf", added_at=now - timedelta(days=2))
    newest = await _document(session, source_id, "contract-v2-FINAL.pdf", added_at=now)
    await _page(session, newest, 1, "This agreement supersedes all prior versions.")

    await raise_candidates(session, source_id, _THRESHOLD)

    evidence = (await session.execute(text("SELECT evidence FROM clarifications"))).scalar_one()
    assert evidence["kind"] == "passage"
    assert evidence["samples"] == [
        {
            "document": "contract-v2-FINAL.pdf",
            "page": 1,
            "text": "This agreement supersedes all prior versions.",
        }
    ]


@pytest.mark.asyncio
async def test_document_identity_with_no_extracted_text_states_evidence_is_unavailable(
    session: AsyncSession,
) -> None:
    source_id = await _source(session)
    now = datetime.now(UTC)
    await _document(session, source_id, "contract-v1.pdf", added_at=now - timedelta(days=2))
    await _document(session, source_id, "contract-v2-FINAL.pdf", added_at=now)

    await raise_candidates(session, source_id, _THRESHOLD)

    evidence = (await session.execute(text("SELECT evidence FROM clarifications"))).scalar_one()
    assert evidence["kind"] == "unavailable"
    assert "contract-v2-FINAL.pdf" in evidence["reason"]


# --- contradictions between sources -------------------------------------------


@pytest.mark.asyncio
async def test_disagreeing_sources_raise_a_candidate(session: AsyncSession) -> None:
    source_id = await _source(session)
    handbook = await _document(session, source_id, "handbook-2024.pdf")
    policy = await _document(session, source_id, "policy-2025.pdf")
    await _page(session, handbook, 1, "The notice period is 30 days for all staff.")
    await _page(session, policy, 1, "The notice period is 45 days for all staff.")

    result = await raise_candidates(session, source_id, _THRESHOLD)

    assert result == RaiseResult(raised=1, inferred=0, dropped=0)
    question = (await session.execute(text("SELECT question FROM clarifications"))).scalar_one()
    assert "notice period" in question
    assert "30" in question and "45" in question


@pytest.mark.asyncio
async def test_a_contradiction_against_a_superseded_version_is_not_a_contradiction(
    session: AsyncSession,
) -> None:
    source_id = await _source(session)
    current = await _document(session, source_id, "policy-2025.pdf")
    old = await _document(session, source_id, "policy-2024.pdf", superseded_by=current)
    await _page(session, current, 1, "The notice period is 45 days for all staff.")
    await _page(session, old, 1, "The notice period is 30 days for all staff.")

    result = await raise_candidates(session, source_id, _THRESHOLD)

    assert result == RaiseResult(raised=0, inferred=0, dropped=0)


@pytest.mark.asyncio
async def test_a_contradiction_carries_both_passages_with_their_dates(
    session: AsyncSession,
) -> None:
    source_id = await _source(session)
    handbook_date = datetime(2024, 1, 15, tzinfo=UTC)
    policy_date = datetime(2025, 3, 1, tzinfo=UTC)
    handbook = await _document(session, source_id, "handbook-2024.pdf", added_at=handbook_date)
    policy = await _document(session, source_id, "policy-2025.pdf", added_at=policy_date)
    await _page(session, handbook, 1, "The notice period is 30 days for all staff.")
    await _page(session, policy, 4, "The notice period is 45 days for all staff.")

    await raise_candidates(session, source_id, _THRESHOLD)

    evidence = (await session.execute(text("SELECT evidence FROM clarifications"))).scalar_one()
    assert evidence["kind"] == "contradiction"
    assert len(evidence["passages"]) == 2
    by_document = {p["document"]: p for p in evidence["passages"]}
    assert by_document["handbook-2024.pdf"]["date"] == "2024-01-15"
    assert by_document["handbook-2024.pdf"]["value"] == "30 days"
    assert by_document["policy-2025.pdf"]["date"] == "2025-03-01"
    assert by_document["policy-2025.pdf"]["page"] == 4
    assert "notice period" in by_document["policy-2025.pdf"]["text"]
    # No safe guess at which side of an unresolved contradiction is right.
    assert evidence["current_inference"] is None


@pytest.mark.asyncio
async def test_a_single_source_stating_a_fact_once_is_not_a_contradiction(
    session: AsyncSession,
) -> None:
    source_id = await _source(session)
    document_id = await _document(session, source_id, "handbook.pdf")
    await _page(session, document_id, 1, "The notice period is 30 days for all staff.")

    result = await raise_candidates(session, source_id, _THRESHOLD)

    assert result == RaiseResult(raised=0, inferred=0, dropped=0)


# --- the whole pipeline ---------------------------------------------------------


@pytest.mark.asyncio
async def test_a_source_with_no_ambiguity_at_all_raises_nothing(
    session: AsyncSession,
) -> None:
    source_id = await _source(session)
    document_id = await _document(session, source_id, "plain.pdf")
    await _chunk(session, document_id, "This is an ordinary paragraph about staffing.")
    await _page(session, document_id, 1, "This is an ordinary paragraph about staffing.")

    result = await raise_candidates(session, source_id, _THRESHOLD)

    assert result == RaiseResult(raised=0, inferred=0, dropped=0)
    assert (await session.execute(text("SELECT 1 FROM clarifications"))).first() is None


@pytest.mark.asyncio
async def test_a_source_already_scanned_is_never_re_scanned(session: AsyncSession) -> None:
    source_id = await _source(session)
    document_id = await _document(session, source_id, "tender.pdf")
    await _chunk(session, document_id, "The RFQ closes Friday. RFQ again.")
    await session.execute(
        text(
            "INSERT INTO clarifications (id, source_id, subject, question) "
            "VALUES (:id, :source_id, 'existing', 'already asked?')"
        ),
        {"id": uuid.uuid4(), "source_id": source_id},
    )

    result = await raise_candidates(session, source_id, _THRESHOLD)

    assert result == RaiseResult(raised=0, inferred=0, dropped=0)
    count = (
        await session.execute(
            text("SELECT count(*) FROM clarifications WHERE source_id = :id"),
            {"id": source_id},
        )
    ).scalar_one()
    assert count == 1


@pytest.mark.asyncio
async def test_raising_and_dropping_are_both_logged_to_the_decisions_store(
    session: AsyncSession,
) -> None:
    source_id = await _source(session)
    document_id = await _document(session, source_id, "tender.pdf")
    await _chunk(session, document_id, "The RFQ closes Friday. Another RFQ follows.")
    await _chunk(session, document_id, "A lone abbreviation: XQ.")

    await raise_candidates(session, source_id, _THRESHOLD)

    kinds = (
        (await session.execute(text("SELECT kind FROM audit_decisions ORDER BY occurred_at")))
        .scalars()
        .all()
    )
    assert "clarification_raised" in kinds
    assert "clarification_dropped" in kinds


# --- evidence helpers ---------------------------------------------------------


def test_bound_text_leaves_a_short_passage_untouched() -> None:
    assert _bound_text("The notice period is 30 days.") == "The notice period is 30 days."


def test_bound_text_truncates_a_long_passage_with_an_ellipsis() -> None:
    bounded = _bound_text("word " * 200)
    assert len(bounded) <= 500
    assert bounded.endswith("…")


def test_column_distribution_evidence_keeps_only_the_top_values() -> None:
    values = [(f"value-{i}", i) for i in range(EVIDENCE_MAX_COLUMN_VALUES + 5)]
    row_count = sum(count for _value, count in values)

    evidence = column_distribution_evidence(values, row_count)

    assert evidence["kind"] == "column_distribution"
    assert evidence["row_count"] == row_count
    assert len(evidence["values"]) == EVIDENCE_MAX_COLUMN_VALUES
    kept = sum(item["count"] for item in evidence["values"])
    assert evidence["remainder_count"] == row_count - kept
    assert evidence["remainder_count"] > 0


def test_candidate_is_a_frozen_dataclass() -> None:
    candidate = Candidate(
        trigger="abbreviation",
        subject="RFQ",
        question="What does RFQ mean?",
        passes=True,
        reason="all three tests held",
    )
    assert candidate.evidence == {}
    assert candidate.inferred_fact is None
