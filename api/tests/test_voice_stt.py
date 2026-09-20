"""The STT driver: buffering a turn's audio, calling `voice`'s `/transcribe`,
and storing the result. `M6-STT-BE-127`.

Against a real Postgres, same pattern `test_ask_api.py`'s stop-flag test
uses: the driver is called directly rather than through the WebSocket, and
`voice`'s HTTP response is faked with `httpx.MockTransport` rather than a
real container — `askwell.voice.transcribe`'s own tests cover the model
logic that would sit behind a real one.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator

import httpx
import psycopg
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from askwell.config import Settings
from askwell.voice_channel import VoiceTurn
from askwell.voice_stt import TranscriptionUnavailable, build_stt_driver

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


def _turn(audio_chunks: list[bytes], *, conversation_id: uuid.UUID | None = None) -> VoiceTurn:
    turn = VoiceTurn(
        turn_id=uuid.uuid4(),
        audio_in=asyncio.Queue(),
        audio_out=asyncio.Queue(),
        conversation_id=conversation_id,
    )
    for chunk in audio_chunks:
        turn.audio_in.put_nowait(chunk)
    turn.audio_in.put_nowait(None)
    return turn


def _client_factory(response_json: dict[str, object], *, status_code: int = 200):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=response_json)

    def make_client() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://voice")

    return make_client


async def test_a_transcribed_turn_stores_the_message_and_the_audit_record(
    settings: Settings, database_url: str, factory: async_sessionmaker[AsyncSession]
) -> None:
    _truncate(database_url)
    turn = _turn([b"\x00\x01" * 8000])
    driver = build_stt_driver(
        settings,
        factory,
        client_factory=_client_factory(
            {
                "status": "ok",
                "transcript": "what is the notice period",
                "confidence": 0.87,
                "language": "en",
                "language_probability": 0.99,
            }
        ),
    )

    await driver(turn)

    assert turn.status == "completed"
    assert turn.transcript == "what is the notice period"
    assert turn.confidence == 0.87
    assert turn.conversation_id is not None

    with psycopg.connect(database_url, autocommit=True) as db:
        message = db.execute(
            "SELECT role, content FROM messages WHERE conversation_id = %s",
            (turn.conversation_id,),
        ).fetchone()
        assert message == ("user", "what is the notice period")

        conversation = db.execute(
            "SELECT mode FROM conversations WHERE id = %s", (turn.conversation_id,)
        ).fetchone()
        assert conversation == ("voice",)

        audit = db.execute(
            "SELECT kind, payload FROM audit_interactions WHERE payload->>'turn_id' = %s",
            (str(turn.turn_id),),
        ).fetchone()
        assert audit is not None
        kind, payload = audit
        assert kind == "voice_transcribed"
        assert payload["status"] == "ok"
        assert payload["confidence_pct"] == 87
        assert payload["transcript_length"] == len("what is the notice period")


async def test_no_speech_stores_nothing_and_completes_the_turn(
    settings: Settings, database_url: str, factory: async_sessionmaker[AsyncSession]
) -> None:
    """`M6-STT-BE-128`'s own stated rule — no interaction record because
    nothing was asked — applies just as much when this ticket is the one
    that first has a reason to write anything at all."""
    _truncate(database_url)
    turn = _turn([b"\x00\x00" * 8000])
    driver = build_stt_driver(
        settings, factory, client_factory=_client_factory({"status": "no_speech"})
    )

    await driver(turn)

    assert turn.status == "completed"
    assert turn.transcript == ""
    assert turn.conversation_id is None

    with psycopg.connect(database_url, autocommit=True) as db:
        count = db.execute("SELECT count(*) FROM messages").fetchone()
        assert count == (0,)
        count = db.execute("SELECT count(*) FROM audit_interactions").fetchone()
        assert count == (0,)


async def test_a_turn_with_no_audio_at_all_completes_without_calling_the_service(
    settings: Settings, database_url: str, factory: async_sessionmaker[AsyncSession]
) -> None:
    _truncate(database_url)
    turn = _turn([])

    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("no audio means no request should be made")

    driver = build_stt_driver(
        settings,
        factory,
        client_factory=lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="http://voice"
        ),
    )

    await driver(turn)

    assert turn.status == "completed"


async def test_unsupported_language_stores_an_empty_message_but_no_transcript(
    settings: Settings, database_url: str, factory: async_sessionmaker[AsyncSession]
) -> None:
    _truncate(database_url)
    turn = _turn([b"\x01\x02" * 8000])
    driver = build_stt_driver(
        settings,
        factory,
        client_factory=_client_factory(
            {
                "status": "unsupported_language",
                "transcript": "",
                "confidence": None,
                "language": "fr",
                "language_probability": 0.92,
            }
        ),
    )

    await driver(turn)

    assert turn.status == "completed"
    assert turn.transcript == ""
    assert turn.language_supported is False
    assert turn.detected_language == "fr"

    with psycopg.connect(database_url, autocommit=True) as db:
        message = db.execute(
            "SELECT content FROM messages WHERE conversation_id = %s",
            (turn.conversation_id,),
        ).fetchone()
        assert message == ("",)

        payload = db.execute(
            "SELECT payload FROM audit_interactions WHERE payload->>'turn_id' = %s",
            (str(turn.turn_id),),
        ).fetchone()[0]
        assert payload["status"] == "unsupported_language"
        assert payload["language"] == "fr"
        assert payload["language_probability_pct"] == 92


async def test_service_unavailable_raises_rather_than_inventing_a_transcript(
    settings: Settings, database_url: str, factory: async_sessionmaker[AsyncSession]
) -> None:
    """`voice_channel._run_driver` is what turns this into a failed turn in
    production; this driver's own contract is simply to not swallow it."""
    _truncate(database_url)
    turn = _turn([b"\x01\x02" * 8000])
    driver = build_stt_driver(
        settings,
        factory,
        client_factory=_client_factory({"reason": "no whisper file"}, status_code=503),
    )

    with pytest.raises(TranscriptionUnavailable):
        await driver(turn)

    with psycopg.connect(database_url, autocommit=True) as db:
        count = db.execute("SELECT count(*) FROM messages").fetchone()
        assert count == (0,)


async def test_an_existing_conversation_id_is_reused_rather_than_creating_a_new_one(
    settings: Settings, database_url: str, factory: async_sessionmaker[AsyncSession]
) -> None:
    _truncate(database_url)
    conversation_id = uuid.uuid4()
    with psycopg.connect(database_url, autocommit=True) as db:
        db.execute("INSERT INTO conversations (id, mode) VALUES (%s, 'text')", (conversation_id,))

    turn = _turn([b"\x01\x02" * 8000], conversation_id=conversation_id)
    driver = build_stt_driver(
        settings,
        factory,
        client_factory=_client_factory(
            {
                "status": "ok",
                "transcript": "hello",
                "confidence": 0.5,
                "language": "en",
                "language_probability": 0.9,
            }
        ),
    )

    await driver(turn)

    assert turn.conversation_id == conversation_id
    with psycopg.connect(database_url, autocommit=True) as db:
        mode = db.execute(
            "SELECT mode FROM conversations WHERE id = %s", (conversation_id,)
        ).fetchone()
        # Only a *new* conversation is stamped `voice` — an existing one
        # (started as text, continued by voice) keeps whatever it already was.
        assert mode == ("text",)
        count = db.execute(
            "SELECT count(*) FROM conversations WHERE id != %s", (conversation_id,)
        ).fetchone()
        assert count == (0,)
