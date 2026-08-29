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
    DEFAULT_CLARIFICATION_CAP,
    Candidate,
    RaiseResult,
    _evaluate,
    _normalize_filename,
    _rank_candidates,
    get_clarification_cap,
    raise_candidates,
    set_clarification_cap,
)

pytestmark = pytest.mark.requires_db

_THRESHOLD = 0.60
_TABLES = (
    "sources, documents, document_pages, chunks, memory, clarifications, audit_decisions, settings"
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


# --- ranking and the cap of five per source ------------------------------------


def _abbrev_candidate(subject: str, occurrences: int) -> Candidate:
    return Candidate(
        trigger="abbreviation",
        subject=subject,
        question=f"What does {subject} mean?",
        passes=True,
        reason="all three tests held",
        evidence={"occurrences": occurrences},
    )


def _contradiction_candidate(subject: str) -> Candidate:
    return Candidate(
        trigger="contradiction",
        subject=subject,
        question=f"Sources disagree on {subject}.",
        passes=True,
        reason="all three tests held",
        evidence={"values": [{"document": "a"}, {"document": "b"}]},
    )


def _scan_candidate(subject: str, total_pages: int) -> Candidate:
    return Candidate(
        trigger="unreadable_scan",
        subject=subject,
        question=f"{subject} scanned poorly.",
        passes=True,
        reason="all three tests held",
        evidence={"total_pages": total_pages},
    )


def test_a_contradiction_outranks_an_abbreviation() -> None:
    ranked = _rank_candidates([_abbrev_candidate("RFQ", 10), _contradiction_candidate("term")])
    assert [c.trigger for c in ranked] == ["contradiction", "abbreviation"]


def test_within_a_tier_higher_volume_ranks_first() -> None:
    ranked = _rank_candidates([_abbrev_candidate("A", 2), _abbrev_candidate("B", 9)])
    assert [c.subject for c in ranked] == ["B", "A"]


def test_ties_break_deterministically_by_subject() -> None:
    a = [_abbrev_candidate("B", 5), _abbrev_candidate("A", 5)]
    b = [_abbrev_candidate("A", 5), _abbrev_candidate("B", 5)]
    assert [c.subject for c in _rank_candidates(a)] == [c.subject for c in _rank_candidates(b)]
    assert [c.subject for c in _rank_candidates(a)] == ["A", "B"]


@pytest.mark.asyncio
async def test_the_cap_defaults_to_five(session: AsyncSession) -> None:
    assert await get_clarification_cap(session) == DEFAULT_CLARIFICATION_CAP == 5


@pytest.mark.asyncio
async def test_a_source_producing_ten_candidates_asks_five_and_infers_the_rest(
    session: AsyncSession,
) -> None:
    source_id = await _source(session)
    document_id = await _document(session, source_id, "notes.pdf")
    for index in range(10):
        # Distinct occurrence counts give each abbreviation its own rank, so
        # which five made the cut is unambiguous to assert on.
        token = chr(65 + index) * 3
        for _ in range(index + 2):
            await _chunk(session, document_id, f"The {token} applies here.")

    result = await raise_candidates(session, source_id, _THRESHOLD)

    assert result == RaiseResult(raised=5, inferred=5, dropped=0, capped=5)
    rows = (
        await session.execute(text("SELECT subject, rank FROM clarifications ORDER BY rank"))
    ).all()
    assert len(rows) == 5
    assert [subject for subject, _rank in rows] == ["JJJ", "III", "HHH", "GGG", "FFF"]
    assert [rank for _subject, rank in rows] == [1, 2, 3, 4, 5]
    memory_rows = (await session.execute(text("SELECT origin, confidence FROM memory"))).all()
    assert len(memory_rows) == 5
    assert all(origin == "inferred" for origin, _confidence in memory_rows)
    assert all(float(confidence) < 0.5 for _origin, confidence in memory_rows)


@pytest.mark.asyncio
async def test_exactly_five_candidates_are_all_asked(session: AsyncSession) -> None:
    source_id = await _source(session)
    document_id = await _document(session, source_id, "notes.pdf")
    for index in range(5):
        token = chr(65 + index) * 3
        await _chunk(session, document_id, f"{token} and {token} again.")

    result = await raise_candidates(session, source_id, _THRESHOLD)

    assert result == RaiseResult(raised=5, inferred=0, dropped=0, capped=0)


@pytest.mark.asyncio
async def test_a_contradiction_outranks_an_abbreviation_for_the_cap(
    session: AsyncSession,
) -> None:
    source_id = await _source(session)
    handbook = await _document(session, source_id, "handbook-2024.pdf")
    policy = await _document(session, source_id, "policy-2025.pdf")
    await _page(session, handbook, 1, "The notice period is 30 days for all staff.")
    await _page(session, policy, 1, "The notice period is 45 days for all staff.")
    for index in range(5):
        token = chr(65 + index) * 3
        for _ in range(3):
            await _chunk(session, handbook, f"{token} applies.")

    result = await raise_candidates(session, source_id, _THRESHOLD)

    assert result.raised == 5
    triggers = (
        await session.execute(text("SELECT subject, rank FROM clarifications ORDER BY rank"))
    ).all()
    assert triggers[0] == ("the notice period", 1)


@pytest.mark.asyncio
async def test_raising_the_cap_asks_more_on_the_next_source(session: AsyncSession) -> None:
    source_id = await _source(session)
    document_id = await _document(session, source_id, "notes.pdf")
    for index in range(7):
        token = chr(65 + index) * 3
        for _ in range(index + 2):
            await _chunk(session, document_id, f"{token} appears.")

    await set_clarification_cap(session, 7)
    assert await get_clarification_cap(session) == 7

    result = await raise_candidates(session, source_id, _THRESHOLD)

    assert result == RaiseResult(raised=7, inferred=0, dropped=0, capped=0)
    kinds = (
        (await session.execute(text("SELECT kind FROM audit_decisions ORDER BY occurred_at")))
        .scalars()
        .all()
    )
    assert "clarification_cap_changed" in kinds


@pytest.mark.asyncio
async def test_setting_the_cap_below_one_is_rejected(session: AsyncSession) -> None:
    with pytest.raises(ValueError, match="at least 1"):
        await set_clarification_cap(session, 0)


@pytest.mark.asyncio
async def test_running_the_same_import_twice_chooses_the_same_five(
    session: AsyncSession,
) -> None:
    async def _run() -> list[str]:
        source_id = await _source(session)
        document_id = await _document(session, source_id, "notes.pdf")
        for index in range(8):
            token = chr(65 + index) * 3
            for _ in range(index + 2):
                await _chunk(session, document_id, f"{token} appears here.")
        await raise_candidates(session, source_id, _THRESHOLD)
        rows = (
            (
                await session.execute(
                    text("SELECT subject FROM clarifications WHERE source_id = :id ORDER BY rank"),
                    {"id": source_id},
                )
            )
            .scalars()
            .all()
        )
        return list(rows)

    first = await _run()
    second = await _run()
    assert first == second
