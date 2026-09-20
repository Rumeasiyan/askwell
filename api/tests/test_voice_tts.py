"""Sentence-streamed speech synthesis: generation reused directly from
`askwell.ask`, sentence-by-sentence synthesis against a faked `voice`
container, citation forwarding, and prompt stopping. `M6-TTS-BE-130`.

Same pattern `test_voice_stt.py` uses: `_speak_answer` is exercised directly
against a real Postgres rather than through the WebSocket, `generate` fakes
`askwell.ask._generate` so no real inference server is needed, and the
`voice` container's `/synthesize` is faked with `httpx.MockTransport`.
"""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator

import httpx
import psycopg
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from askwell.config import Settings
from askwell.voice_channel import VoiceTurn
from askwell.voice_tts import POLL_INTERVAL_SECONDS, SynthesisUnavailable, _speak_answer

pytestmark = pytest.mark.requires_db

TABLES = "conversations, messages, audit_interactions"


def _truncate(database_url: str) -> None:
    with psycopg.connect(database_url, autocommit=True) as db:
        db.execute(f"TRUNCATE {TABLES} CASCADE")


@pytest_asyncio.fixture
async def factory(database_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    async_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_async_engine(async_url)
    sessions_ = async_sessionmaker(engine, expire_on_commit=False)
    yield sessions_
    await engine.dispose()


def _conversation(database_url: str) -> uuid.UUID:
    conversation_id = uuid.uuid4()
    with psycopg.connect(database_url, autocommit=True) as db:
        db.execute("INSERT INTO conversations (id, mode) VALUES (%s, 'voice')", (conversation_id,))
    return conversation_id


def _voice_turn(conversation_id: uuid.UUID) -> VoiceTurn:
    return VoiceTurn(
        turn_id=uuid.uuid4(),
        audio_in=asyncio.Queue(),
        audio_out=asyncio.Queue(),
        conversation_id=conversation_id,
    )


def _tts_client_factory(*, on_request=None, status_code: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        sent_text = json.loads(request.content)["text"]
        if on_request is not None:
            on_request(sent_text)
        if status_code != 200:
            return httpx.Response(status_code, json={"reason": "no kokoro file"})
        return httpx.Response(
            200,
            content=f"AUDIO[{sent_text}]".encode(),
            headers={"X-Sample-Rate": "24000"},
        )

    def make_client() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://voice")

    return make_client


async def _drain_audio(turn: VoiceTurn) -> list[bytes]:
    chunks: list[bytes] = []
    while True:
        chunk = turn.audio_out.get_nowait()
        if chunk is None:
            break
        chunks.append(chunk)
    return chunks


async def test_each_sentence_is_synthesized_and_spoken_before_the_answer_completes(
    settings: Settings, database_url: str, factory: async_sessionmaker[AsyncSession]
) -> None:
    _truncate(database_url)
    conversation_id = _conversation(database_url)
    turn = _voice_turn(conversation_id)

    synthesized: list[str] = []
    first_sentence_seen = asyncio.Event()

    def on_request(sent_text: str) -> None:
        synthesized.append(sent_text)
        first_sentence_seen.set()

    async def fake_generate(_settings, _factory, ask_turn, _question, _source_id, _continue_from):
        ask_turn.text = "Notice is ninety days [1]."
        ask_turn.emit("token", {"text": ask_turn.text})
        ask_turn.emit(
            "citation",
            {
                "claim_ordinal": 1,
                "index": 1,
                "filename": "supplier-agreement-2024.pdf",
            },
        )
        # The driver must have already synthesized the first (only) sentence
        # by the time this coroutine is still "running" from its own
        # perspective — proven by waiting on the same event the fake
        # `/synthesize` call sets, before this function is allowed to finish.
        await asyncio.wait_for(first_sentence_seen.wait(), timeout=5)
        ask_turn.status = "completed"

    await _speak_answer(
        turn,
        settings=settings,
        factory=factory,
        question="what is the notice period",
        tts_client_factory=_tts_client_factory(on_request=on_request),
        generate=fake_generate,
    )

    assert turn.status == "completed"
    assert synthesized == ["Notice is ninety days, from the supplier agreement 2024."]
    audio = await _drain_audio(turn)
    assert audio == [b"AUDIO[Notice is ninety days, from the supplier agreement 2024.]"]


async def test_screen_text_carries_the_raw_marker_unchanged(
    settings: Settings, database_url: str, factory: async_sessionmaker[AsyncSession]
) -> None:
    """Validation Rule: citations are satisfied by the screen, never the
    audio, and screen rendering is unchanged in voice mode."""
    _truncate(database_url)
    conversation_id = _conversation(database_url)
    turn = _voice_turn(conversation_id)

    async def fake_generate(_settings, _factory, ask_turn, _question, _source_id, _continue_from):
        ask_turn.text = "Notice is ninety days [1]."
        ask_turn.emit("token", {"text": ask_turn.text})
        ask_turn.emit(
            "citation",
            {"claim_ordinal": 1, "index": 1, "filename": "supplier-agreement-2024.pdf"},
        )
        ask_turn.status = "completed"

    await _speak_answer(
        turn,
        settings=settings,
        factory=factory,
        question="q",
        tts_client_factory=_tts_client_factory(),
        generate=fake_generate,
    )

    assert turn.text == "Notice is ninety days [1]."
    citation_events = [e for e in turn.events if e.kind == "citation"]
    assert citation_events[0].fields["filename"] == "supplier-agreement-2024.pdf"


async def test_a_source_is_named_naturally_only_the_first_time_it_is_cited(
    settings: Settings, database_url: str, factory: async_sessionmaker[AsyncSession]
) -> None:
    _truncate(database_url)
    conversation_id = _conversation(database_url)
    turn = _voice_turn(conversation_id)

    synthesized: list[str] = []

    async def fake_generate(_settings, _factory, ask_turn, _question, _source_id, _continue_from):
        ask_turn.text = "Notice is ninety days [1]. Renewal is automatic [1]."
        ask_turn.emit("token", {"text": ask_turn.text})
        ask_turn.emit(
            "citation",
            {"claim_ordinal": 1, "index": 1, "filename": "supplier-agreement-2024.pdf"},
        )
        ask_turn.emit(
            "citation",
            {"claim_ordinal": 2, "index": 1, "filename": "supplier-agreement-2024.pdf"},
        )
        ask_turn.status = "completed"

    await _speak_answer(
        turn,
        settings=settings,
        factory=factory,
        question="q",
        tts_client_factory=_tts_client_factory(on_request=synthesized.append),
        generate=fake_generate,
    )

    assert synthesized == [
        "Notice is ninety days, from the supplier agreement 2024.",
        "Renewal is automatic.",
    ]


async def test_a_very_short_answer_is_synthesized_as_one_unit(
    settings: Settings, database_url: str, factory: async_sessionmaker[AsyncSession]
) -> None:
    _truncate(database_url)
    conversation_id = _conversation(database_url)
    turn = _voice_turn(conversation_id)

    synthesized: list[str] = []

    async def fake_generate(_settings, _factory, ask_turn, _question, _source_id, _continue_from):
        ask_turn.text = "Yes."
        ask_turn.emit("token", {"text": ask_turn.text})
        ask_turn.status = "completed"

    await _speak_answer(
        turn,
        settings=settings,
        factory=factory,
        question="q",
        tts_client_factory=_tts_client_factory(on_request=synthesized.append),
        generate=fake_generate,
    )

    assert synthesized == ["Yes."]


async def test_a_trailing_sentence_with_no_terminating_punctuation_is_still_spoken(
    settings: Settings, database_url: str, factory: async_sessionmaker[AsyncSession]
) -> None:
    """The model ran out of tokens mid-sentence — spoken as a last,
    best-effort unit rather than silently dropped."""
    _truncate(database_url)
    conversation_id = _conversation(database_url)
    turn = _voice_turn(conversation_id)

    synthesized: list[str] = []

    async def fake_generate(_settings, _factory, ask_turn, _question, _source_id, _continue_from):
        ask_turn.text = "Notice is ninety days [1]. Renewal is auto"
        ask_turn.emit("token", {"text": ask_turn.text})
        ask_turn.emit(
            "citation",
            {"claim_ordinal": 1, "index": 1, "filename": "supplier-agreement-2024.pdf"},
        )
        ask_turn.status = "completed"

    await _speak_answer(
        turn,
        settings=settings,
        factory=factory,
        question="q",
        tts_client_factory=_tts_client_factory(on_request=synthesized.append),
        generate=fake_generate,
    )

    assert synthesized == [
        "Notice is ninety days, from the supplier agreement 2024.",
        "Renewal is auto",
    ]


async def test_stopping_mid_answer_speaks_no_further_sentence(
    settings: Settings, database_url: str, factory: async_sessionmaker[AsyncSession]
) -> None:
    """The ticket's own edge case: audio stops promptly rather than finishing
    the buffered sentence and ignoring the stop."""
    _truncate(database_url)
    conversation_id = _conversation(database_url)
    turn = _voice_turn(conversation_id)

    synthesized: list[str] = []
    first_sentence_seen = asyncio.Event()

    def on_request(sent_text: str) -> None:
        synthesized.append(sent_text)
        first_sentence_seen.set()

    async def fake_generate(_settings, _factory, ask_turn, _question, _source_id, _continue_from):
        ask_turn.text = "First sentence is here."
        ask_turn.emit("token", {"text": ask_turn.text})
        await asyncio.wait_for(first_sentence_seen.wait(), timeout=5)
        # Several poll intervals of headroom: the test sets `turn.stop_requested`
        # concurrently, right after the first sentence is seen, and this
        # sleep gives `_speak_answer`'s poll loop time to notice it before
        # this second sentence's text ever becomes visible to it — otherwise
        # this test would be racing the two coroutines against each other.
        await asyncio.sleep(POLL_INTERVAL_SECONDS * 5)
        ask_turn.text += " Second sentence should not be spoken."
        ask_turn.emit("token", {"text": " Second sentence should not be spoken."})
        ask_turn.status = "stopped" if ask_turn.stop_requested else "completed"

    speak_task = asyncio.create_task(
        _speak_answer(
            turn,
            settings=settings,
            factory=factory,
            question="q",
            tts_client_factory=_tts_client_factory(on_request=on_request),
            generate=fake_generate,
        )
    )

    await asyncio.wait_for(first_sentence_seen.wait(), timeout=5)
    # The user hit stop while the answer was still speaking — set the same
    # way `askwell.voice_channel._receive_loop` sets it on a `stop` message.
    turn.stop_requested = True

    await speak_task

    assert synthesized == ["First sentence is here."]
    assert turn.status == "completed"


async def test_a_synthesis_failure_from_the_voice_service_propagates(
    settings: Settings, database_url: str, factory: async_sessionmaker[AsyncSession]
) -> None:
    _truncate(database_url)
    conversation_id = _conversation(database_url)
    turn = _voice_turn(conversation_id)

    async def fake_generate(_settings, _factory, ask_turn, _question, _source_id, _continue_from):
        ask_turn.text = "Notice is ninety days."
        ask_turn.emit("token", {"text": ask_turn.text})
        ask_turn.status = "completed"

    with pytest.raises(SynthesisUnavailable):
        await _speak_answer(
            turn,
            settings=settings,
            factory=factory,
            question="q",
            tts_client_factory=_tts_client_factory(status_code=503),
            generate=fake_generate,
        )


async def test_the_pending_answer_row_is_written_before_generation_starts(
    settings: Settings, database_url: str, factory: async_sessionmaker[AsyncSession]
) -> None:
    _truncate(database_url)
    conversation_id = _conversation(database_url)
    turn = _voice_turn(conversation_id)
    seen_message_id: uuid.UUID | None = None

    async def fake_generate(_settings, _factory, ask_turn, _question, _source_id, _continue_from):
        nonlocal seen_message_id
        seen_message_id = ask_turn.message_id
        with psycopg.connect(database_url, autocommit=True) as db:
            row = db.execute(
                "SELECT role, trace ->> 'status' FROM messages WHERE id = %s",
                (str(ask_turn.message_id),),
            ).fetchone()
        assert row == ("assistant", "running")
        ask_turn.text = "Yes."
        ask_turn.emit("token", {"text": ask_turn.text})
        ask_turn.status = "completed"

    await _speak_answer(
        turn,
        settings=settings,
        factory=factory,
        question="q",
        tts_client_factory=_tts_client_factory(),
        generate=fake_generate,
    )

    assert seen_message_id is not None
