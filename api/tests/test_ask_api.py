"""Answer streaming, over HTTP and against a real Postgres. `M1-ASK-API-038`.

`InferenceClient` is stubbed the same way `test_retrieve_records.py` and
`test_rerank.py` already stub it — this suite has no more need to start a
real `llama.cpp` than they did. What is under test is the transport: that
steps arrive before tokens, that a citation resolves to the chunk the model
actually referenced, that stopping and disconnecting behave the way
`docs/states-and-edge-cases.md` §2 requires, and that all of it is durable —
readable back from `messages`, `citations` and `audit_interactions` once the
turn is over.

Setup and assertions against the database use plain `psycopg`, matching
`test_ingest_api.py` — `TestClient` and an async `AsyncSession` do not share
an event loop cleanly, and there is no need to make them.
"""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from askwell import ask as ask_module
from askwell import session as sessions
from askwell.app import create_app
from askwell.config import Settings
from askwell.inference.client import InferenceUnavailable, StreamChunk

from .conftest import drive_and_disconnect
from .test_ingest_records import TABLES as INGEST_TABLES

pytestmark = pytest.mark.requires_db

TABLES = f"{INGEST_TABLES}, conversations, messages, citations, audit_interactions"
DIMENSIONS = Settings.model_fields["embedding_dimensions"].default


def _vector(lead: float) -> list[float]:
    return [lead] + [0.01] * (DIMENSIONS - 1)


class _FakeInferenceClient:
    """Stands in for `InferenceClient`, matching its constructor and the
    three methods `retrieve()`/`_generate()` call."""

    def __init__(
        self,
        _settings: Settings,
        *,
        tokens: list[str],
        vector: list[float],
        truncated: bool = False,
        fail: Exception | None = None,
        fail_after: int | None = None,
        delay: float = 0.0,
    ) -> None:
        self.tokens = tokens
        self.vector = vector
        self.truncated = truncated
        self.fail = fail
        # Failing *after* some tokens is a different case from failing before
        # any: the first loses nothing, the second has a partial answer that
        # must survive. Only the first was covered.
        self.fail_after = fail_after
        self.delay = delay

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self.vector for _ in texts]

    async def rerank(
        self, query: str, documents: list[str], *, timeout_seconds: float = 0.0
    ) -> list[tuple[int, float]]:
        return [(index, float(len(documents) - index)) for index in range(len(documents))]

    async def stream_generate(
        self,
        _prompt: str,
        *,
        max_tokens: int = 512,
        temperature: float = 0.2,
        timeout_seconds: float = 0.0,
    ) -> AsyncIterator[StreamChunk]:
        if self.fail is not None and self.fail_after is None:
            raise self.fail
        for sent, piece in enumerate(self.tokens):
            if self.fail is not None and self.fail_after is not None and sent >= self.fail_after:
                raise self.fail
            if self.delay:
                await asyncio.sleep(self.delay)
            yield StreamChunk(text=piece, done=False)
        yield StreamChunk(text="", done=True, truncated=self.truncated)


def _patch_client(monkeypatch: pytest.MonkeyPatch, fake: _FakeInferenceClient) -> None:
    monkeypatch.setattr(ask_module, "InferenceClient", lambda _settings: fake)


def _truncate(database_url: str) -> None:
    with psycopg.connect(database_url, autocommit=True) as db:
        db.execute(f"TRUNCATE {TABLES} CASCADE")


def _seed_chunk(
    database_url: str, content: str, vector: list[float]
) -> tuple[uuid.UUID, uuid.UUID]:
    """One source, one document, one chunk — enough for `retrieve()` to find
    something and for `compose()` to have a candidate at `index="1"`."""
    document_id, chunk_id, source_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(database_url, autocommit=True) as db:
        db.execute(
            "INSERT INTO sources (id, kind, name) VALUES (%s, 'file', 'a source')", (source_id,)
        )
        db.execute(
            "INSERT INTO documents (id, source_id, filename, path, sha256) "
            "VALUES (%s, %s, 'file.txt', %s, %s)",
            (
                document_id,
                source_id,
                f"/tmp/{document_id}.txt",
                uuid.uuid4().hex.ljust(64, "0")[:64],
            ),
        )
        db.execute(
            "INSERT INTO chunks (id, document_id, ordinal, content, embedding) "
            "VALUES (%s, %s, 0, %s, %s)",
            (chunk_id, document_id, content, str(vector)),
        )
    return document_id, chunk_id


def _seed_chunks(
    database_url: str, contents: list[str], vector: list[float]
) -> tuple[uuid.UUID, list[uuid.UUID]]:
    """Several chunks under one document — the ticket's own "claim supported
    by more than one candidate" and "several claims in one answer" cases,
    where several `<retrieved-content index="…">` candidates need to exist."""
    document_id, source_id = uuid.uuid4(), uuid.uuid4()
    chunk_ids = [uuid.uuid4() for _ in contents]
    with psycopg.connect(database_url, autocommit=True) as db:
        db.execute(
            "INSERT INTO sources (id, kind, name) VALUES (%s, 'file', 'a source')", (source_id,)
        )
        db.execute(
            "INSERT INTO documents (id, source_id, filename, path, sha256) "
            "VALUES (%s, %s, 'file.txt', %s, %s)",
            (
                document_id,
                source_id,
                f"/tmp/{document_id}.txt",
                uuid.uuid4().hex.ljust(64, "0")[:64],
            ),
        )
        for ordinal, (chunk_id, content) in enumerate(zip(chunk_ids, contents, strict=True)):
            db.execute(
                "INSERT INTO chunks (id, document_id, ordinal, content, embedding) "
                "VALUES (%s, %s, %s, %s, %s)",
                (chunk_id, document_id, ordinal, content, str(vector)),
            )
    return document_id, chunk_ids


def _app(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str
) -> TestClient:
    async def fixed_secret(_db: object) -> bytes:
        return b"0" * 32

    monkeypatch.setattr(sessions, "secret", fixed_secret)
    monkeypatch.setattr("askwell.middleware.sessions.secret", fixed_secret)

    built = tmp_path / "out"
    built.mkdir(exist_ok=True)
    (built / "index.html").write_text("<!doctype html><title>Askwell</title>")
    return TestClient(
        create_app(
            settings.model_copy(
                update={"database_url": SecretStr(database_url), "web_assets_dir": built}
            )
        )
    )


def _with_session(client: TestClient) -> None:
    client.get("/", headers={"accept": "text/html"})


def _events(body: str) -> list[tuple[str, dict[str, Any]]]:
    parsed: list[tuple[str, dict[str, Any]]] = []
    for block in body.strip().split("\n\n"):
        if not block:
            continue
        lines = block.split("\n")
        kind = lines[0].removeprefix("event: ")
        data = json.loads(lines[1].removeprefix("data: "))
        parsed.append((kind, data))
    return parsed


# --- the wire format, end to end ---------------------------------------------


def test_a_question_streams_steps_then_tokens_then_a_citation_then_done(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str
) -> None:
    """The ticket's own acceptance criteria, in one exchange: step labels
    ahead of the first token, a citation resolved to the chunk it names, and
    a durable record of all of it."""
    _truncate(database_url)
    vector = _vector(0.0)
    document_id, chunk_id = _seed_chunk(database_url, "Notice is ninety days.", vector)
    fake = _FakeInferenceClient(
        settings, tokens=["The notice period ", "is ninety days [1]."], vector=vector
    )
    _patch_client(monkeypatch, fake)

    client = _app(settings, monkeypatch, tmp_path, database_url)
    with client:
        _with_session(client)
        response = client.post("/ask", json={"question": "How long is the notice period?"})
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("text/event-stream")

        events = _events(response.text)
        kinds = [kind for kind, _ in events]

        # Every step arrives before the first token — the acceptance
        # criterion stated by name.
        first_token_index = kinds.index("token")
        assert kinds[:first_token_index] == ["step"] * first_token_index
        assert first_token_index >= 1

        # Named steps, never a generic placeholder.
        labels = [data["label"] for kind, data in events if kind == "step"]
        assert any("searching" in label.lower() for label in labels)
        assert any("1 source" in label for label in labels)

        citation_events = [data for kind, data in events if kind == "citation"]
        message_id = uuid.UUID(citation_events[0]["message_id"])
        assert citation_events == [
            {
                "claim_ordinal": 1,
                "index": 1,
                "chunk_id": str(chunk_id),
                "document_id": str(document_id),
                "filename": "file.txt",
                "anchor_kind": None,
                "heading": None,
                "page_from": None,
                "page_to": None,
                "passage": "Notice is ninety days.",
                "quoted_span": None,
                "message_id": str(message_id),
            }
        ]

        done = next(data for kind, data in events if kind == "done")
        assert done["status"] == "completed"
        assert uuid.UUID(done["message_id"]) == message_id

    with psycopg.connect(database_url, autocommit=True) as db:
        message = db.execute(
            "SELECT content, trace, role FROM messages WHERE id = %s", (message_id,)
        ).fetchone()
        assert message is not None
        content, trace, role = message
        assert role == "assistant"
        assert content == "The notice period is ninety days [1]."
        assert trace["status"] == "completed"
        assert trace["stopped_early"] is False

        citation_rows = db.execute(
            "SELECT chunk_id, claim_ordinal FROM citations WHERE message_id = %s", (message_id,)
        ).fetchall()
        assert citation_rows == [(chunk_id, 1)]

        audit_rows = db.execute(
            "SELECT kind, payload FROM audit_interactions WHERE payload->>'message_id' = %s",
            (str(message_id),),
        ).fetchall()
        assert len(audit_rows) == 1
        assert audit_rows[0][0] == ask_module.ASK_ASKED
        assert audit_rows[0][1]["status"] == "completed"


def test_three_factual_claims_produce_three_citation_rows(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str
) -> None:
    """The ticket's own headline acceptance criterion: an answer with three
    factual claims produces three citation rows referencing real chunks,
    each carrying the claim ordinal it belongs to."""
    _truncate(database_url)
    vector = _vector(0.0)
    document_id, chunk_ids = _seed_chunks(
        database_url,
        ["Rent is $1000 per month.", "Notice is ninety days.", "Pets are not allowed."],
        vector,
    )
    fake = _FakeInferenceClient(
        settings,
        tokens=["Rent is $1000 [1]. Notice is ninety days [2]. Pets are not allowed [3]."],
        vector=vector,
    )
    _patch_client(monkeypatch, fake)

    client = _app(settings, monkeypatch, tmp_path, database_url)
    with client:
        _with_session(client)
        response = client.post("/ask", json={"question": "What are the lease terms?"})
        assert response.status_code == 200, response.text

        events = _events(response.text)
        citation_events = [data for kind, data in events if kind == "citation"]
        assert [event["claim_ordinal"] for event in citation_events] == [1, 2, 3]
        assert {event["document_id"] for event in citation_events} == {str(document_id)}
        assert {event["chunk_id"] for event in citation_events} <= {str(c) for c in chunk_ids}

        message_id = uuid.UUID(citation_events[0]["message_id"])

    with psycopg.connect(database_url, autocommit=True) as db:
        citation_rows = db.execute(
            "SELECT chunk_id, claim_ordinal FROM citations "
            "WHERE message_id = %s ORDER BY claim_ordinal",
            (message_id,),
        ).fetchall()
        assert [ordinal for _chunk_id, ordinal in citation_rows] == [1, 2, 3]
        assert {chunk_id for chunk_id, _ordinal in citation_rows} <= set(chunk_ids)


def test_a_claim_supported_by_two_passages_gets_two_citations_at_one_ordinal(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str
) -> None:
    """The ticket's own edge case."""
    _truncate(database_url)
    vector = _vector(0.0)
    _document_id, chunk_ids = _seed_chunks(
        database_url, ["Payment terms, page one.", "Payment terms, page two."], vector
    )
    fake = _FakeInferenceClient(
        settings, tokens=["Payment is due within forty-five days [1][2]."], vector=vector
    )
    _patch_client(monkeypatch, fake)

    client = _app(settings, monkeypatch, tmp_path, database_url)
    with client:
        _with_session(client)
        response = client.post("/ask", json={"question": "When is payment due?"})
        assert response.status_code == 200, response.text
        events = _events(response.text)
        citation_events = [data for kind, data in events if kind == "citation"]

    assert len(citation_events) == 2
    assert {event["claim_ordinal"] for event in citation_events} == {1}
    assert {event["chunk_id"] for event in citation_events} == {str(c) for c in chunk_ids}


def test_a_sentence_with_no_marker_is_not_counted_as_a_citation(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str
) -> None:
    """The ticket's own edge case: a restatement of the question is not a
    factual claim, so it produces no citation and is never counted as an
    uncited one."""
    _truncate(database_url)
    vector = _vector(0.0)
    _document_id, (chunk_id,) = _seed_chunks(database_url, ["Notice is ninety days."], vector)
    fake = _FakeInferenceClient(
        settings,
        tokens=["The notice period is ninety days [1]. Let me know if you have other questions."],
        vector=vector,
    )
    _patch_client(monkeypatch, fake)

    client = _app(settings, monkeypatch, tmp_path, database_url)
    with client:
        _with_session(client)
        response = client.post("/ask", json={"question": "How long is the notice period?"})
        assert response.status_code == 200, response.text
        events = _events(response.text)
        citation_events = [data for kind, data in events if kind == "citation"]

    assert len(citation_events) == 1
    assert citation_events[0]["chunk_id"] == str(chunk_id)


def test_citations_survive_the_message_trace_being_lost(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str
) -> None:
    """Citations are their own table, not a field inside the rotating trace
    (`docs/architecture.md` §7) — proven here by discarding the trace
    entirely and confirming the citation still resolves to its chunk."""
    _truncate(database_url)
    vector = _vector(0.0)
    _document_id, chunk_id = _seed_chunk(database_url, "Notice is ninety days.", vector)
    fake = _FakeInferenceClient(settings, tokens=["Notice is ninety days [1]."], vector=vector)
    _patch_client(monkeypatch, fake)

    client = _app(settings, monkeypatch, tmp_path, database_url)
    with client:
        _with_session(client)
        response = client.post("/ask", json={"question": "How long is the notice period?"})
        events = _events(response.text)
        message_id = uuid.UUID(next(data for kind, data in events if kind == "done")["message_id"])

    with psycopg.connect(database_url, autocommit=True) as db:
        # Simulate the trace having rotated out of existence — the assistant
        # message's own `trace` blob is gone, standing in for the file-backed
        # ring buffer (`askwell.traces.TraceRing`) that never held citations.
        db.execute("UPDATE messages SET trace = NULL WHERE id = %s", (message_id,))
        row = db.execute(
            "SELECT citations.chunk_id, citations.claim_ordinal FROM citations "
            "JOIN chunks ON chunks.id = citations.chunk_id "
            "WHERE citations.message_id = %s",
            (message_id,),
        ).fetchone()
        assert row == (chunk_id, 1)


def test_a_missing_conversation_is_a_client_error(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str
) -> None:
    _truncate(database_url)
    fake = _FakeInferenceClient(settings, tokens=[], vector=_vector(0.0))
    _patch_client(monkeypatch, fake)
    client = _app(settings, monkeypatch, tmp_path, database_url)
    with client:
        _with_session(client)
        response = client.post(
            "/ask", json={"question": "Anything?", "conversation_id": str(uuid.uuid4())}
        )
        assert response.status_code == 404


def test_the_question_must_not_be_empty(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str
) -> None:
    _truncate(database_url)
    client = _app(settings, monkeypatch, tmp_path, database_url)
    with client:
        _with_session(client)
        assert client.post("/ask", json={"question": ""}).status_code == 422


def test_asking_requires_a_session(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str
) -> None:
    _truncate(database_url)
    client = _app(settings, monkeypatch, tmp_path, database_url)
    with client:
        assert client.post("/ask", json={"question": "x"}).status_code == 401


def test_an_unavailable_assistant_ends_the_turn_as_failed(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str
) -> None:
    _truncate(database_url)
    fake = _FakeInferenceClient(
        settings,
        tokens=[],
        vector=_vector(0.0),
        fail=InferenceUnavailable("The assistant is not running."),
    )
    _patch_client(monkeypatch, fake)
    client = _app(settings, monkeypatch, tmp_path, database_url)
    with client:
        _with_session(client)
        response = client.post("/ask", json={"question": "Anything?"})
        assert response.status_code == 200

        events = _events(response.text)
        done = next(data for kind, data in events if kind == "done")
        assert done["status"] == "failed"
        assert "not running" in done["reason"]
        assert not any(kind == "token" for kind, _ in events)


def test_a_truncated_answer_says_it_hit_the_limit(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str
) -> None:
    """The ticket's edge case: streamed without truncation, and if a limit is
    reached it is *stated*.

    An answer that simply stops at the limit looks like an answer that finished.
    The user then acts on a sentence that was cut off mid-thought with nothing
    saying so, which is the same failure as an uncited claim: they cannot tell
    from the screen that anything is missing.
    """
    _truncate(database_url)
    fake = _FakeInferenceClient(
        settings, tokens=["A long ", "answer "], vector=_vector(0.0), truncated=True
    )
    _patch_client(monkeypatch, fake)
    client = _app(settings, monkeypatch, tmp_path, database_url)
    with client:
        _with_session(client)
        response = client.post("/ask", json={"question": "Tell me everything?"})
        assert response.status_code == 200

        events = _events(response.text)
        done = next(data for kind, data in events if kind == "done")
        assert done["status"] == "completed", "hitting the limit is not a failure"
        assert "length limit" in done["reason"].lower(), done["reason"]


def test_an_assistant_that_dies_mid_stream_keeps_what_it_already_said(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str
) -> None:
    """The ticket's edge case, and the half of it nothing covered.

    Failing before the first token loses nothing. Failing after a few loses a
    partial answer the user watched arrive — and discarding it would take back
    words already on their screen, leaving them unsure whether they misread it.
    """
    _truncate(database_url)
    fake = _FakeInferenceClient(
        settings,
        tokens=["The contract ", "may be ", "terminated "],
        vector=_vector(0.0),
        fail=InferenceUnavailable("The assistant stopped responding."),
        fail_after=2,
    )
    _patch_client(monkeypatch, fake)
    client = _app(settings, monkeypatch, tmp_path, database_url)
    with client:
        _with_session(client)
        response = client.post("/ask", json={"question": "What are the terms?"})
        assert response.status_code == 200

        events = _events(response.text)
        tokens = [data for kind, data in events if kind == "token"]
        assert len(tokens) == 2, "it should have streamed what it managed before dying"

        done = next(data for kind, data in events if kind == "done")
        assert done["status"] == "failed"
        assert "stopped responding" in done["reason"]

    # Kept, not discarded — read back on a separate connection.
    with psycopg.connect(database_url, autocommit=True) as db:
        rows = db.execute(
            "SELECT content, trace ->> 'status' FROM messages WHERE role = 'assistant'"
        ).fetchall()
    assert len(rows) == 1, "the partial answer is a row, not a discarded buffer"
    assert rows[0][0].startswith("The contract "), rows[0][0]
    assert rows[0][1] == "failed"


def test_the_local_counters_come_from_the_rows_rather_than_from_memory(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str
) -> None:
    """The ticket's Analytics Events line: started, completed and stopped.

    Derived from `messages`, so they survive a restart. A counter held in the
    process would reset with the container and report "answers started since
    the last deploy" under a name that reads like a total.
    """
    _truncate(database_url)
    fake = _FakeInferenceClient(settings, tokens=["Yes."], vector=_vector(0.0))
    _patch_client(monkeypatch, fake)
    client = _app(settings, monkeypatch, tmp_path, database_url)
    with client:
        _with_session(client)
        assert client.get("/ask/counts").json() == {
            "started": 0,
            "completed": 0,
            "stopped": 0,
            "failed": 0,
            "running": 0,
            "abandoned": 0,
        }

        client.post("/ask", json={"question": "Anything?"})
        counts = client.get("/ask/counts").json()

    assert counts["started"] == 1
    assert counts["completed"] == 1
    assert counts["stopped"] == 0


# --- stopping -----------------------------------------------------------------


@pytest_asyncio.fixture
async def factory(database_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    async_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_async_engine(async_url)
    sessions_ = async_sessionmaker(engine, expire_on_commit=False)
    yield sessions_
    await engine.dispose()


async def test_a_stop_flag_ends_generation_and_marks_the_answer_partial(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    database_url: str,
    factory: async_sessionmaker[AsyncSession],
) -> None:
    """Exercised against `_generate` directly rather than through two
    concurrent `TestClient` calls — `TestClient` blocks its calling thread
    until a response is fully collected, which leaves no window to send a
    second request while the first is still streaming."""
    _truncate(database_url)
    vector = _vector(0.0)
    _seed_chunk(database_url, "Notice is ninety days.", vector)
    fake = _FakeInferenceClient(
        settings, tokens=["one ", "two ", "three "], vector=vector, delay=0.2
    )
    monkeypatch.setattr(ask_module, "InferenceClient", lambda _settings: fake)

    conversation_id = uuid.uuid4()
    with psycopg.connect(database_url, autocommit=True) as db:
        db.execute("INSERT INTO conversations (id) VALUES (%s)", (conversation_id,))

    turn = ask_module._Turn(message_id=uuid.uuid4(), conversation_id=conversation_id)
    task = asyncio.create_task(
        ask_module._generate(settings, factory, turn, "How long is the notice period?", None)
    )
    for _ in range(100):  # until the first token lands, before the second
        if turn.text:
            break
        await asyncio.sleep(0.01)
    else:
        raise AssertionError("no token arrived to stop after")
    turn.stop_requested = True
    await task

    assert turn.status == "stopped"
    assert turn.text == "one "

    with psycopg.connect(database_url, autocommit=True) as db:
        row = db.execute(
            "SELECT content, trace FROM messages WHERE id = %s", (turn.message_id,)
        ).fetchone()
    assert row is not None
    content, trace = row
    assert content == "one "
    assert trace["status"] == "stopped"
    assert trace["stopped_early"] is True


async def test_load_finished_reads_a_completed_turn_back_from_the_database(
    database_url: str, factory: async_sessionmaker[AsyncSession]
) -> None:
    """The fallback `GET /ask/{id}/stream` uses once a turn has left memory
    — after this process restarted, or after `MAX_FINISHED` retired it."""
    _truncate(database_url)
    message_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    with psycopg.connect(database_url, autocommit=True) as db:
        db.execute("INSERT INTO conversations (id) VALUES (%s)", (conversation_id,))
        db.execute(
            "INSERT INTO messages (id, conversation_id, role, content, trace) "
            "VALUES (%s, %s, 'assistant', 'Ninety days.', %s)",
            (message_id, conversation_id, json.dumps({"status": "completed", "steps": []})),
        )

    loaded = await ask_module._load_finished(factory, message_id)
    assert loaded == ("Ninety days.", "completed")

    missing = await ask_module._load_finished(factory, uuid.uuid4())
    assert missing is None


# --- the client leaving does not stop the answer -------------------------------


def test_a_disconnected_browser_does_not_stop_generation(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str
) -> None:
    """`docs/states-and-edge-cases.md` §2: "generation continues server-side
    and the answer is saved to the conversation." Driven with raw ASGI
    (`conftest.drive_and_disconnect`) because `TestClient` cannot observe a
    disconnect taking effect mid-stream — see that helper's own docstring
    and issue #110.
    """
    _truncate(database_url)
    vector = _vector(0.0)
    _seed_chunk(database_url, "Notice is ninety days.", vector)
    fake = _FakeInferenceClient(
        settings, tokens=["one ", "two ", "three "], vector=vector, delay=0.2
    )
    _patch_client(monkeypatch, fake)

    client = _app(settings, monkeypatch, tmp_path, database_url)
    with client:
        _with_session(client)
        cookies = "; ".join(f"{name}={value}" for name, value in client.cookies.items())
        app = client.app

        async def run() -> str:
            driven = await drive_and_disconnect(
                app,
                method="POST",
                path="/ask",
                cookies=cookies,
                body=json.dumps({"question": "How long is the notice period?"}).encode(),
            )
            start = driven.start
            assert start["type"] == "http.response.start"
            assert start["status"] == 200

            message_id = next(
                uuid.UUID(data["message_id"])
                for kind, data in _events(driven.body)
                if kind == "step"
            )

            for _ in range(100):
                turn = ask_module._turns.get(message_id)
                if turn is not None and turn.status != "running":
                    return turn.status
                await asyncio.sleep(0.05)
            raise AssertionError("generation did not finish after the browser disconnected")

        status = asyncio.run(run())

    assert status == "completed"

    with psycopg.connect(database_url, autocommit=True) as db:
        row = db.execute(
            "SELECT content FROM messages WHERE role = 'assistant' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        assert row is not None
        assert row[0] == "one two three "


def test_reconnecting_to_an_unknown_turn_is_a_client_error(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str
) -> None:
    _truncate(database_url)
    client = _app(settings, monkeypatch, tmp_path, database_url)
    with client:
        _with_session(client)
        response = client.get(f"/ask/{uuid.uuid4()}/stream")
        assert response.status_code == 404


# --- crash recovery and bounded concurrency, `M1-ASK-BE-040` -----------------


def test_a_pending_row_exists_before_anything_has_generated(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str
) -> None:
    """`POST /ask` writes the assistant row as `running` before the
    background task runs at all — the row `reconcile_interrupted` needs to
    find something to fail if the process dies before generation starts."""
    _truncate(database_url)
    fake = _FakeInferenceClient(settings, tokens=["one ", "two "], vector=_vector(0.0), delay=1.0)
    _patch_client(monkeypatch, fake)
    client = _app(settings, monkeypatch, tmp_path, database_url)
    with client:
        _with_session(client)
        cookies = "; ".join(f"{name}={value}" for name, value in client.cookies.items())
        app = client.app

        async def run() -> None:
            driven = await drive_and_disconnect(
                app,
                method="POST",
                path="/ask",
                cookies=cookies,
                body=json.dumps({"question": "Anything?"}).encode(),
            )
            assert driven.start["status"] == 200
            with psycopg.connect(database_url, autocommit=True) as db:
                row = db.execute(
                    "SELECT content, trace ->> 'status' FROM messages WHERE role = 'assistant'"
                ).fetchone()
            assert row == ("", "running")

        asyncio.run(run())


async def test_reconcile_interrupted_fails_a_stale_running_turn(
    database_url: str, factory: async_sessionmaker[AsyncSession]
) -> None:
    """The edge case by name: the stack restarts mid-generation. Nothing in
    `_turns` survives that — this is what stands in for a fresh process
    finding the previous one's row."""
    _truncate(database_url)
    message_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    with psycopg.connect(database_url, autocommit=True) as db:
        db.execute("INSERT INTO conversations (id) VALUES (%s)", (conversation_id,))
        db.execute(
            "INSERT INTO messages (id, conversation_id, role, content, trace) "
            "VALUES (%s, %s, 'assistant', '', %s)",
            (message_id, conversation_id, json.dumps({"status": "running", "steps": []})),
        )
        # A genuinely finished turn in the same table must be left alone.
        db.execute(
            "INSERT INTO messages (id, conversation_id, role, content, trace) "
            "VALUES (%s, %s, 'assistant', 'Done.', %s)",
            (uuid.uuid4(), conversation_id, json.dumps({"status": "completed", "steps": []})),
        )

    reconciled = await ask_module.reconcile_interrupted(factory)
    assert reconciled == 1

    with psycopg.connect(database_url, autocommit=True) as db:
        rows = dict(
            db.execute("SELECT id, trace FROM messages WHERE role = 'assistant'").fetchall()
        )
    assert rows[message_id]["status"] == "failed"
    assert rows[message_id]["stopped_early"] is True
    assert rows[message_id]["interrupted"] is True
    assert "restarted" in rows[message_id]["reason"]

    completed = next(trace for mid, trace in rows.items() if mid != message_id)
    assert completed["status"] == "completed"


async def test_reconcile_interrupted_is_idempotent_on_a_clean_database(
    database_url: str, factory: async_sessionmaker[AsyncSession]
) -> None:
    _truncate(database_url)
    assert await ask_module.reconcile_interrupted(factory) == 0


def test_generation_is_bounded_so_abandoned_turns_do_not_all_run_at_once(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    database_url: str,
    factory: async_sessionmaker[AsyncSession],
) -> None:
    """The edge case by name: several abandoned generations at once, bounded
    so the machine stays usable. With the limit at one, a second turn must
    not touch the fake assistant until the first has released it."""
    _truncate(database_url)
    bounded = settings.model_copy(update={"generation_max_concurrent": 1})
    monkeypatch.setattr(ask_module, "_generation_semaphore", None)
    monkeypatch.setattr(ask_module, "_generation_semaphore_size", None)

    conversation_id = uuid.uuid4()
    with psycopg.connect(database_url, autocommit=True) as db:
        db.execute("INSERT INTO conversations (id) VALUES (%s)", (conversation_id,))

    started: list[str] = []

    class _TrackingClient(_FakeInferenceClient):
        async def stream_generate(
            self,
            prompt: str,
            *,
            max_tokens: int = 512,
            temperature: float = 0.2,
            timeout_seconds: float = 0.0,
        ) -> AsyncIterator[StreamChunk]:
            started.append(self.tag)  # type: ignore[attr-defined]
            async for chunk in super().stream_generate(
                prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout_seconds=timeout_seconds,
            ):
                yield chunk

    first = _TrackingClient(bounded, tokens=["a "], vector=_vector(0.0), delay=0.2)
    first.tag = "first"  # type: ignore[attr-defined]
    second = _TrackingClient(bounded, tokens=["b "], vector=_vector(0.0))
    second.tag = "second"  # type: ignore[attr-defined]

    clients = iter([first, second])
    monkeypatch.setattr(ask_module, "InferenceClient", lambda _settings: next(clients))

    async def run() -> None:
        turn_a = ask_module._Turn(message_id=uuid.uuid4(), conversation_id=conversation_id)
        turn_b = ask_module._Turn(message_id=uuid.uuid4(), conversation_id=conversation_id)
        task_a = asyncio.create_task(ask_module._generate(bounded, factory, turn_a, "Q1?", None))
        # Give the first turn a chance to acquire the semaphore before the
        # second one is even created.
        await asyncio.sleep(0.05)
        task_b = asyncio.create_task(ask_module._generate(bounded, factory, turn_b, "Q2?", None))
        await asyncio.sleep(0.05)
        # The bound is holding: only the first has actually started
        # generating, even though both tasks exist.
        assert started == ["first"]
        await task_a
        await task_b
        assert started == ["first", "second"]
        assert turn_a.status == "completed"
        assert turn_b.status == "completed"

    asyncio.run(run())


def test_the_same_question_asked_twice_produces_two_completed_answers(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str
) -> None:
    """The edge case by name: the user asks the same question again while
    the first is still running — both complete, both appear. Driven as two
    sequential requests (`TestClient` cannot hold two open at once, the same
    limitation the stop test above already works around) — nothing in `ask()`
    deduplicates by question text, so this is really a test that no such
    deduplication exists to trip over."""
    _truncate(database_url)
    fake = _FakeInferenceClient(settings, tokens=["Yes."], vector=_vector(0.0))
    _patch_client(monkeypatch, fake)
    client = _app(settings, monkeypatch, tmp_path, database_url)
    with client:
        _with_session(client)
        question = {"question": "Is the deadline Friday?"}
        first = client.post("/ask", json=question)
        second = client.post("/ask", json=question)
        assert first.status_code == 200
        assert second.status_code == 200

    with psycopg.connect(database_url, autocommit=True) as db:
        rows = db.execute(
            "SELECT content, trace ->> 'status' FROM messages WHERE role = 'assistant'"
        ).fetchall()
    assert len(rows) == 2
    assert all(content == "Yes." and status == "completed" for content, status in rows)
