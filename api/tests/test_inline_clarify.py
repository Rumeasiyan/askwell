"""Whether a pending clarification blocks a turn. `M3-INLINE-FE-085`.

Against a real Postgres, same fixture shapes as `test_clarify.py` — this
module's own `find_blocking` reads exactly the rows `raise_candidates`
writes, so the fixture-through-`raise_candidates` path is what keeps the two
modules honest about the wire shape they actually share (`evidence ->>
'trigger'` in particular, added by this ticket).
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from askwell.clarify import raise_candidates
from askwell.config import Settings
from askwell.inline_clarify import default_assumption, find_blocking
from askwell.retrieve import Candidate

pytestmark = pytest.mark.requires_db

_THRESHOLD = 0.60
_SETTINGS = Settings(
    database_url="postgresql://askwell:pw@127.0.0.1:1/askwell",  # type: ignore[arg-type]
    sandbox_database_url="postgresql://x:x@127.0.0.1:1/postgres",  # type: ignore[arg-type]
    sandbox_owner_password="pw",  # type: ignore[arg-type]
    sandbox_readonly_password="pw",  # type: ignore[arg-type]
)
_TABLES = "sources, documents, document_pages, chunks, memory, schema_notes, clarifications"


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
    session: AsyncSession, source_id: uuid.UUID, filename: str, *, added_at: datetime
) -> uuid.UUID:
    document_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO documents (id, source_id, filename, path, sha256, status, added_at) "
            "VALUES (:id, :source_id, :filename, :path, :sha256, 'ready', :added_at)"
        ),
        {
            "id": document_id,
            "source_id": source_id,
            "filename": filename,
            "path": f"/tmp/{filename}",
            "sha256": uuid.uuid4().hex.ljust(64, "0")[:64],
            "added_at": added_at,
        },
    )
    return document_id


async def _page(
    session: AsyncSession, document_id: uuid.UUID, page_number: int, text_: str
) -> None:
    await session.execute(
        text(
            "INSERT INTO document_pages (document_id, page_number, text, has_text) "
            "VALUES (:document_id, :page_number, :text, true)"
        ),
        {"document_id": document_id, "page_number": page_number, "text": text_},
    )


async def _abbreviation(session: AsyncSession, source_id: uuid.UUID) -> None:
    document_id = await _document(session, source_id, "tender.pdf", added_at=datetime.now(UTC))
    await session.execute(
        text(
            "INSERT INTO chunks (id, document_id, ordinal, content) "
            "VALUES (:id, :document_id, 0, :content)"
        ),
        {
            "id": uuid.uuid4(),
            "document_id": document_id,
            "content": "The RFQ closes Friday. Submit the RFQ.",
        },
    )


def _candidate(filename: str) -> Candidate:
    return Candidate(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        filename=filename,
        anchor_kind="page",
        content="irrelevant",
        heading=None,
        page_from=1,
        page_to=1,
        score=1.0,
        dense_score=0.9,
        lexical_score=None,
    )


# --- find_blocking -------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_contradiction_relevant_to_the_question_blocks(session: AsyncSession) -> None:
    source_id = await _source(session)
    handbook = await _document(
        session, source_id, "handbook-2024.pdf", added_at=datetime(2024, 1, 10, tzinfo=UTC)
    )
    policy = await _document(
        session, source_id, "policy-2025.pdf", added_at=datetime(2025, 3, 20, tzinfo=UTC)
    )
    await _page(session, handbook, 3, "The notice period is 30 days for all staff.")
    await _page(session, policy, 7, "The notice period is 45 days for all staff.")
    await raise_candidates(session, source_id, _THRESHOLD, _SETTINGS)

    blocking, deferred = await find_blocking(
        session, "How much notice must I give?", [_candidate("handbook-2024.pdf")]
    )

    assert blocking is not None
    assert blocking.subject == "the notice period"
    assert deferred == 0


@pytest.mark.asyncio
async def test_subject_named_in_the_question_also_matches(session: AsyncSession) -> None:
    source_id = await _source(session)
    handbook = await _document(
        session, source_id, "handbook-2024.pdf", added_at=datetime(2024, 1, 10, tzinfo=UTC)
    )
    policy = await _document(
        session, source_id, "policy-2025.pdf", added_at=datetime(2025, 3, 20, tzinfo=UTC)
    )
    await _page(session, handbook, 3, "The notice period is 30 days for all staff.")
    await _page(session, policy, 7, "The notice period is 45 days for all staff.")
    await raise_candidates(session, source_id, _THRESHOLD, _SETTINGS)

    # No overlap with retrieved candidates at all, but the question names the
    # subject directly — either signal is enough (this module's own docstring).
    blocking, _deferred = await find_blocking(
        session, "What is the notice period?", [_candidate("unrelated.pdf")]
    )

    assert blocking is not None
    assert blocking.subject == "the notice period"


@pytest.mark.asyncio
async def test_document_identity_relevant_to_retrieved_documents_blocks(
    session: AsyncSession,
) -> None:
    source_id = await _source(session)
    old = await _document(
        session, source_id, "contract-v1.pdf", added_at=datetime(2025, 1, 1, tzinfo=UTC)
    )
    new = await _document(
        session, source_id, "contract-v2-FINAL.pdf", added_at=datetime(2025, 6, 1, tzinfo=UTC)
    )
    await _page(session, old, 1, "Old terms apply here.")
    await _page(session, new, 1, "New terms apply here, superseding the old.")
    await raise_candidates(session, source_id, _THRESHOLD, _SETTINGS)

    blocking, _deferred = await find_blocking(
        session, "What do the contract terms say?", [_candidate("contract-v2-FINAL.pdf")]
    )

    assert blocking is not None
    assert blocking.subject == "contract"
    assert blocking.options == ["contract-v1.pdf", "contract-v2-FINAL.pdf"]


@pytest.mark.asyncio
async def test_an_unrelated_pending_contradiction_does_not_block(session: AsyncSession) -> None:
    source_id = await _source(session)
    handbook = await _document(
        session, source_id, "handbook-2024.pdf", added_at=datetime(2024, 1, 10, tzinfo=UTC)
    )
    policy = await _document(
        session, source_id, "policy-2025.pdf", added_at=datetime(2025, 3, 20, tzinfo=UTC)
    )
    await _page(session, handbook, 3, "The notice period is 30 days for all staff.")
    await _page(session, policy, 7, "The notice period is 45 days for all staff.")
    await raise_candidates(session, source_id, _THRESHOLD, _SETTINGS)

    blocking, deferred = await find_blocking(
        session, "What is the office address?", [_candidate("other.pdf")]
    )

    assert blocking is None
    assert deferred == 0


@pytest.mark.asyncio
async def test_a_non_blocking_trigger_never_interrupts(session: AsyncSession) -> None:
    """Abbreviations and poor scans are real pending clarifications, but
    never this kind of interruption — the ticket's own scope: only a
    contradiction or a document-identity ambiguity can withhold a single
    confident answer."""
    source_id = await _source(session)
    await _abbreviation(session, source_id)
    await raise_candidates(session, source_id, _THRESHOLD, _SETTINGS)
    assert (await session.execute(text("SELECT 1 FROM clarifications"))).first() is not None

    blocking, _deferred = await find_blocking(
        session, "What does RFQ mean?", [_candidate("tender.pdf")]
    )

    assert blocking is None


@pytest.mark.asyncio
async def test_an_answered_clarification_never_blocks_a_later_turn(session: AsyncSession) -> None:
    """`docs/ux/ask.md` §5's own edge case: asked once, then applied — once
    answered, `status` is no longer `pending` and this must stop matching."""
    source_id = await _source(session)
    handbook = await _document(
        session, source_id, "handbook-2024.pdf", added_at=datetime(2024, 1, 10, tzinfo=UTC)
    )
    policy = await _document(
        session, source_id, "policy-2025.pdf", added_at=datetime(2025, 3, 20, tzinfo=UTC)
    )
    await _page(session, handbook, 3, "The notice period is 30 days for all staff.")
    await _page(session, policy, 7, "The notice period is 45 days for all staff.")
    await raise_candidates(session, source_id, _THRESHOLD, _SETTINGS)
    await session.execute(
        text("UPDATE clarifications SET status = 'answered', answer = 'handbook-2024.pdf'")
    )

    blocking, _deferred = await find_blocking(
        session, "How much notice must I give?", [_candidate("handbook-2024.pdf")]
    )

    assert blocking is None


@pytest.mark.asyncio
async def test_two_blocking_ambiguities_defer_the_second(session: AsyncSession) -> None:
    """`docs/backlog/M3-it-learns-my-material.md`'s own edge case: more than
    one relevant ambiguity in one turn asks about the highest-ranked one and
    reports the rest as deferred, rather than asking in sequence."""
    source_id = await _source(session)
    handbook = await _document(
        session, source_id, "handbook-2024.pdf", added_at=datetime(2024, 1, 10, tzinfo=UTC)
    )
    policy = await _document(
        session, source_id, "policy-2025.pdf", added_at=datetime(2025, 3, 20, tzinfo=UTC)
    )
    await _page(session, handbook, 3, "The notice period is 30 days for all staff.")
    await _page(session, policy, 7, "The notice period is 45 days for all staff.")
    old = await _document(
        session, source_id, "contract-v1.pdf", added_at=datetime(2025, 1, 1, tzinfo=UTC)
    )
    new = await _document(
        session, source_id, "contract-v2-FINAL.pdf", added_at=datetime(2025, 6, 1, tzinfo=UTC)
    )
    await _page(session, old, 1, "Old terms apply here.")
    await _page(session, new, 1, "New terms apply here, superseding the old.")
    await raise_candidates(session, source_id, _THRESHOLD, _SETTINGS)

    blocking, deferred = await find_blocking(
        session,
        "How much notice must I give under the contract terms?",
        [_candidate("handbook-2024.pdf"), _candidate("contract-v2-FINAL.pdf")],
    )

    # Contradiction outranks document identity (`clarify.py`'s own
    # `_TRIGGER_PRIORITY`), so it is the one asked; the other is deferred.
    assert blocking is not None
    assert blocking.subject == "the notice period"
    assert deferred == 1


# --- default_assumption ---------------------------------------------------------


@pytest.mark.asyncio
async def test_default_assumption_for_a_contradiction_names_the_newer_passage(
    session: AsyncSession,
) -> None:
    source_id = await _source(session)
    handbook = await _document(
        session, source_id, "handbook-2024.pdf", added_at=datetime(2024, 1, 10, tzinfo=UTC)
    )
    policy = await _document(
        session, source_id, "policy-2025.pdf", added_at=datetime(2025, 3, 20, tzinfo=UTC)
    )
    await _page(session, handbook, 3, "The notice period is 30 days for all staff.")
    await _page(session, policy, 7, "The notice period is 45 days for all staff.")
    await raise_candidates(session, source_id, _THRESHOLD, _SETTINGS)

    blocking, _deferred = await find_blocking(
        session, "How much notice must I give?", [_candidate("handbook-2024.pdf")]
    )
    assert blocking is not None
    assumption = default_assumption(blocking)
    assert "policy-2025.pdf" in assumption
    assert "45 days" in assumption


@pytest.mark.asyncio
async def test_default_assumption_for_document_identity_names_the_newest_file(
    session: AsyncSession,
) -> None:
    source_id = await _source(session)
    old = await _document(
        session, source_id, "contract-v1.pdf", added_at=datetime(2025, 1, 1, tzinfo=UTC)
    )
    new = await _document(
        session, source_id, "contract-v2-FINAL.pdf", added_at=datetime(2025, 6, 1, tzinfo=UTC)
    )
    await _page(session, old, 1, "Old terms apply here.")
    await _page(session, new, 1, "New terms apply here, superseding the old.")
    await raise_candidates(session, source_id, _THRESHOLD, _SETTINGS)

    blocking, _deferred = await find_blocking(
        session, "What do the contract terms say?", [_candidate("contract-v2-FINAL.pdf")]
    )
    assert blocking is not None
    assert default_assumption(blocking) == "contract-v2-FINAL.pdf"
