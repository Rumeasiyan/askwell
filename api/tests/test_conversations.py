"""Past conversations, read back. Issue #199.

Against a real database. Every row a test reads it seeded itself, dated in
2100 so it sorts ahead of anything else in the shared test database — the
list is newest-first across all conversations, and a test must not assume a
row it did not create (`AGENTS.md` §6).
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from askwell import passphrase
from askwell.config import Settings
from askwell.conversations import conversation_turns, list_conversations

pytestmark = pytest.mark.requires_db

FUTURE = datetime(2100, 1, 1, tzinfo=UTC)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url="postgresql://askwell:pw@127.0.0.1:1/askwell",  # type: ignore[arg-type]
        sandbox_database_url="postgresql://x:x@127.0.0.1:1/postgres",  # type: ignore[arg-type]
        sandbox_owner_password="pw",  # type: ignore[arg-type]
        sandbox_readonly_password="pw",  # type: ignore[arg-type]
        trace_dir=tmp_path / "traces",
        install_secret_path=tmp_path / "install.key",
    )


@pytest_asyncio.fixture
async def session(database_url: str) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(database_url.replace("postgresql://", "postgresql+psycopg://", 1))
    made = async_sessionmaker(engine, expire_on_commit=False)
    async with made() as db:
        yield db
        await db.rollback()
    await engine.dispose()


async def _conversation(db: AsyncSession, at: datetime, ai_backend: str = "local") -> uuid.UUID:
    conversation_id = uuid.uuid4()
    await db.execute(
        text("INSERT INTO conversations (id, created_at, ai_backend) VALUES (:id, :at, :backend)"),
        {"id": conversation_id, "at": at, "backend": ai_backend},
    )
    return conversation_id


async def _turn(
    db: AsyncSession,
    conversation_id: uuid.UUID,
    at: datetime,
    question: str,
    answer: str | None,
    *,
    trace: str = '{"status": "completed", "reason": null}',
    summary: str | None = None,
    source_count: int | None = None,
) -> uuid.UUID | None:
    """One question and, unless `answer` is None, its answer — written with
    the same `created_at`, exactly as `POST /ask` writes them in one
    transaction."""
    await db.execute(
        text(
            "INSERT INTO messages (conversation_id, role, content, created_at) "
            "VALUES (:c, 'user', :q, :at)"
        ),
        {"c": conversation_id, "q": question, "at": at},
    )
    if answer is None:
        return None
    message_id = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO messages (id, conversation_id, role, content, trace, summary, "
            "source_count, created_at) "
            "VALUES (:id, :c, 'assistant', :a, CAST(:trace AS jsonb), :summary, :count, :at)"
        ),
        {
            "id": message_id,
            "c": conversation_id,
            "a": answer,
            "trace": trace,
            "summary": summary,
            "count": source_count,
            "at": at,
        },
    )
    return message_id


async def _cite(
    db: AsyncSession,
    message_id: uuid.UUID,
    ordinal: int,
    *,
    filename: str = "Municipal Councils Ordinance.pdf",
    content: str | None = "The term of office shall continue for forty eight months.",
    encrypted: bool = False,
    deleted: bool = False,
) -> uuid.UUID:
    source_id = uuid.uuid4()
    await db.execute(
        text("INSERT INTO sources (id, kind, name, status) VALUES (:id, 'file', 'laws', 'ready')"),
        {"id": source_id},
    )
    document_id = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO documents (id, source_id, filename, path, sha256, status, anchor_kind, "
            "deleted_at) VALUES (:id, :s, :f, :p, :h, 'ready', 'page', :deleted)"
        ),
        {
            "id": document_id,
            "s": source_id,
            "f": filename,
            "p": f"/tmp/{filename}",
            "h": uuid.uuid4().hex,
            "deleted": datetime.now(UTC) if deleted else None,
        },
    )
    chunk_id = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO chunks (id, document_id, ordinal, content, content_encrypted, page_from, "
            "page_to) VALUES (:id, :d, 0, :content, :enc, 4, 4)"
        ),
        {"id": chunk_id, "d": document_id, "content": content, "enc": encrypted},
    )
    await db.execute(
        text(
            "INSERT INTO citations (message_id, chunk_id, claim_ordinal, quoted_span) "
            "VALUES (:m, :c, :o, 'forty eight months')"
        ),
        {"m": message_id, "c": chunk_id, "o": ordinal},
    )
    return chunk_id


async def test_the_list_is_newest_activity_first_titled_by_the_first_question(
    session: AsyncSession,
) -> None:
    older = await _conversation(session, FUTURE)
    await _turn(session, older, FUTURE, "How long is a councillor's term?", "48 months [1].")
    newer = await _conversation(session, FUTURE + timedelta(minutes=1))
    await _turn(
        session, newer, FUTURE + timedelta(minutes=1), "Who chairs a Sabha?", "The Chairman [1]."
    )
    await _turn(session, newer, FUTURE + timedelta(minutes=2), "And the quorum?", "Half [1].")
    # Asked nothing: created for the online disclosure and abandoned.
    empty = await _conversation(session, FUTURE + timedelta(minutes=5))

    page = await list_conversations(session, before=None, limit=2)

    ids = [row["id"] for row in page["conversations"]]
    assert ids == [str(newer), str(older)]
    assert str(empty) not in ids
    first = page["conversations"][0]
    assert first["title"] == "Who chairs a Sabha?"
    assert first["question_count"] == 2
    assert first["ai_backend"] == "local"


async def test_the_cursor_continues_where_the_page_ended(session: AsyncSession) -> None:
    made = []
    for minute in range(3):
        at = FUTURE + timedelta(days=1, minutes=minute)
        conversation_id = await _conversation(session, at)
        await _turn(session, conversation_id, at, f"Question {minute}", "Answer [1].")
        made.append(str(conversation_id))

    first = await list_conversations(session, before=None, limit=2)
    second = await list_conversations(
        session, before=datetime.fromisoformat(first["next_before"]), limit=2
    )

    assert [row["id"] for row in first["conversations"]] == [made[2], made[1]]
    assert second["conversations"][0]["id"] == made[0]


async def test_a_long_question_is_shortened_for_the_list(session: AsyncSession) -> None:
    at = FUTURE + timedelta(days=2)
    conversation_id = await _conversation(session, at)
    await _turn(session, conversation_id, at, "word " * 80, "Answer [1].")

    page = await list_conversations(session, before=None, limit=1)

    title = page["conversations"][0]["title"]
    assert len(title) <= 120
    assert title.endswith("…")


async def test_turns_come_back_in_order_with_their_citations(
    session: AsyncSession, settings: Settings
) -> None:
    at = FUTURE + timedelta(days=3)
    conversation_id = await _conversation(session, at)
    first = await _turn(
        session,
        conversation_id,
        at,
        "How long is a councillor's term?",
        "The term is forty-eight months [1].",
        summary="Forty-eight months.",
        source_count=1,
    )
    await _turn(
        session,
        conversation_id,
        at + timedelta(seconds=30),
        "Who is the Mayor of Colombo?",
        "",
        trace='{"status": "completed", "reason": "Nothing in your files answers this."}',
    )
    assert first is not None
    chunk_id = await _cite(session, first, 1)

    body = await conversation_turns(session, settings, conversation_id)

    assert body is not None
    turns = body["turns"]
    assert [turn["question"] for turn in turns] == [
        "How long is a councillor's term?",
        "Who is the Mayor of Colombo?",
    ]
    answered, abstained = turns
    assert answered["answer"] == "The term is forty-eight months [1]."
    assert answered["status"] == "completed"
    assert answered["summary"] == "Forty-eight months."
    assert answered["source_count"] == 1
    assert answered["citations"] == [
        {
            "claim_ordinal": 1,
            "chunk_id": str(chunk_id),
            "document_id": answered["citations"][0]["document_id"],
            "filename": "Municipal Councils Ordinance.pdf",
            "anchor_kind": "page",
            "heading": None,
            "page_from": 4,
            "page_to": 4,
            "passage": "The term of office shall continue for forty eight months.",
            "quoted_span": "forty eight months",
            "passage_unavailable": None,
        }
    ]
    # Abstention survives the round trip: empty answer, the reason it gave.
    assert abstained["answer"] == ""
    assert abstained["reason"] == "Nothing in your files answers this."
    assert abstained["citations"] == []


async def test_a_question_whose_answer_never_landed_is_kept_and_says_so(
    session: AsyncSession, settings: Settings
) -> None:
    at = FUTURE + timedelta(days=4)
    conversation_id = await _conversation(session, at)
    await _turn(session, conversation_id, at, "Lost question?", None)

    body = await conversation_turns(session, settings, conversation_id)

    assert body is not None
    (turn,) = body["turns"]
    assert turn["question"] == "Lost question?"
    assert turn["status"] == "failed"
    assert turn["reason"] == "This question has no recorded answer."


async def test_an_unfinished_answer_is_not_shown_as_running(
    session: AsyncSession, settings: Settings
) -> None:
    at = FUTURE + timedelta(days=5)
    conversation_id = await _conversation(session, at)
    await _turn(
        session, conversation_id, at, "Still going?", "Partial", trace='{"status": "running"}'
    )

    body = await conversation_turns(session, settings, conversation_id)

    assert body is not None
    assert body["turns"][0]["status"] == "stopped"
    assert body["turns"][0]["reason"] == "This answer had not finished when it was opened."


async def test_a_deleted_or_locked_passage_says_why_instead_of_going_blank(
    session: AsyncSession, settings: Settings
) -> None:
    """C4: an old answer's claim must never look uncited. When the passage
    cannot be shown, the citation says why."""
    at = FUTURE + timedelta(days=6)
    conversation_id = await _conversation(session, at)
    message_id = await _turn(session, conversation_id, at, "Two sources?", "One [1]. Two [2].")
    assert message_id is not None
    await _cite(session, message_id, 1, filename="removed.pdf", content=None, deleted=True)
    await _cite(
        session, message_id, 2, filename="sealed.pdf", content="gAAAA-not-a-token", encrypted=True
    )

    body = await conversation_turns(session, settings, conversation_id)

    assert body is not None
    by_file = {c["filename"]: c for c in body["turns"][0]["citations"]}
    assert by_file["removed.pdf"]["passage"] is None
    assert by_file["removed.pdf"]["passage_unavailable"] == "deleted"
    # No passphrase is set, so the key is the install secret's; the token is
    # simply not one it wrote.
    assert by_file["sealed.pdf"]["passage"] is None
    assert by_file["sealed.pdf"]["passage_unavailable"] == "unreadable"


async def test_an_encrypted_passage_while_askwell_is_locked_says_locked(
    session: AsyncSession, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def locked(_session: AsyncSession, _settings: Settings) -> bytes:
        raise passphrase.Locked("A passphrase is set. Unlock before anything decrypts.")

    monkeypatch.setattr(passphrase, "current_key", locked)
    at = FUTURE + timedelta(days=7)
    conversation_id = await _conversation(session, at)
    message_id = await _turn(session, conversation_id, at, "Sealed?", "Yes [1].")
    assert message_id is not None
    await _cite(
        session, message_id, 1, filename="sealed.pdf", content="gAAAA-token", encrypted=True
    )

    body = await conversation_turns(session, settings, conversation_id)

    assert body is not None
    (citation,) = body["turns"][0]["citations"]
    assert citation["passage"] is None
    assert citation["passage_unavailable"] == "locked"


async def test_an_unknown_conversation_is_none(session: AsyncSession, settings: Settings) -> None:
    assert await conversation_turns(session, settings, uuid.uuid4()) is None
