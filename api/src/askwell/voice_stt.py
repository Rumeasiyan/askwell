"""The real driver behind the voice channel: transcription. `M6-STT-BE-127`.

`askwell.voice_channel` proves the transport; this module is what finally
gives it something to send. `build_stt_driver` returns a `TurnDriver` that:
buffers one turn's audio (there is no partial-utterance streaming ASR here —
turn detection is `M6-STT-BE-128`'s job, so today a turn's whole audio arrives
between connect and the client's own `end`/`stop` signal), calls the `voice`
container's `/transcribe` over the `internal` network, and stores the result
against the turn's conversation exactly the way `askwell.ask` stores a typed
question — a `messages` row plus an `audit_interactions` record, in the same
transaction, so a transcript that could not be recorded is not left standing
without one (`AGENTS.md` §3 C6).

**Answering the question is `M6-TTS-BE-130`'s job, not this one's.**
`build_stt_driver` takes an optional `on_transcript` hook: given a `status ==
"ok"` transcript, once it is stored, control passes to that hook instead of
this module ending the turn itself. `askwell.voice_tts.build_tts_driver` is
the production hook — it wires the transcript into `askwell.ask`'s own
generation and speaks the answer sentence by sentence. `on_transcript` is
`None` for every other caller (this module's own tests, and any caller that
has not wired one up), and the turn ends here exactly as it always did,
deliberately not stubbing an answer that does not exist for it.

Three outcomes, and only two of them touch the database at all:

- **`no_speech`** — background noise, or a turn that closed with no audio.
  Nothing is stored: "a turn with no speech produces no interaction record,
  because nothing was asked" is `M6-STT-BE-128`'s own stated rule, and it
  is exactly as true here.
- **`unsupported_language`** — a `language` event carries the detected
  language to the client; no transcription was attempted for it
  (`askwell.voice.transcribe`'s own docstring). A `messages` row is still
  written, with empty content — the turn happened and belongs in the log,
  even though nothing intelligible was captured. The exact English-only
  copy shown on screen is `M6-VUI-FE-135`'s job, not this module's.
- **`ok`** — the transcript and its confidence are emitted over the channel
  and stored, both in `messages.content` and in the audit payload.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from askwell.audit import AuditError, Store, record
from askwell.config import Settings
from askwell.db.engine import session_scope
from askwell.logging import get_logger
from askwell.voice_channel import VoiceTurn

log = get_logger(__name__)

VOICE_TRANSCRIBED = "voice_transcribed"

# Whisper `small` on CPU, one short spoken question: seconds, not minutes.
# Generous anyway, the same reasoning `InferenceClient`'s own timeout carries
# (`askwell.inference.client`) — a slow `light`-profile machine must still get
# an answer rather than a timeout turning the cheapest hardware into the one
# that cannot use voice at all.
CONNECT_TIMEOUT_SECONDS = 5.0
READ_TIMEOUT_SECONDS = 60.0

ClientFactory = Callable[[], httpx.AsyncClient]


class TranscriptionUnavailable(RuntimeError):
    """The voice service has no usable transcription model right now."""


class TranscriptionFailed(RuntimeError):
    """The voice service is reachable but this request did not succeed."""


async def _transcribe(client: httpx.AsyncClient, audio: bytes) -> dict[str, Any]:
    try:
        response = await client.post(
            "/transcribe", content=audio, headers={"content-type": "application/octet-stream"}
        )
    except httpx.HTTPError as error:
        raise TranscriptionUnavailable(str(error)) from error
    if response.status_code == 503:
        raise TranscriptionUnavailable(response.json().get("reason", response.text))
    if response.status_code != 200:
        raise TranscriptionFailed(f"{response.status_code}: {response.text}")
    payload: dict[str, Any] = response.json()
    return payload


async def _resolve_conversation(db: AsyncSession, conversation_id: uuid.UUID | None) -> uuid.UUID:
    if conversation_id is not None:
        found = await db.execute(
            text("SELECT id FROM conversations WHERE id = :id"), {"id": conversation_id}
        )
        if found.first() is not None:
            return conversation_id

    # Never the client's requested id when it does not resolve — same
    # reasoning `voice_channel._attach` already carries for `turn_id`: a
    # stray id silently becoming the new conversation's real id would make
    # "no id given" and "an id that named nothing real" indistinguishable.
    new_id = uuid.uuid4()
    await db.execute(
        text("INSERT INTO conversations (id, mode) VALUES (:id, 'voice')"), {"id": new_id}
    )
    return new_id


async def _store_turn(
    factory: async_sessionmaker[AsyncSession],
    *,
    turn: VoiceTurn,
    content: str,
    audit_payload: dict[str, Any],
) -> None:
    async with session_scope(factory) as db:
        conversation_id = await _resolve_conversation(db, turn.conversation_id)
        turn.conversation_id = conversation_id
        message_id = uuid.uuid4()
        await db.execute(
            text(
                "INSERT INTO messages (id, conversation_id, role, content) "
                "VALUES (:id, :conversation_id, 'user', :content)"
            ),
            {"id": message_id, "conversation_id": conversation_id, "content": content},
        )
        await record(
            db,
            Store.INTERACTIONS,
            VOICE_TRANSCRIBED,
            {
                "conversation_id": str(conversation_id),
                "message_id": str(message_id),
                "turn_id": str(turn.turn_id),
                **audit_payload,
            },
        )


def _confidence_pct(confidence: float | None) -> int | None:
    # Audit payloads cannot carry a float (`askwell.audit._reject_floats`) —
    # `0.1 + 0.2` and Postgres `jsonb` do not agree what that number is, and
    # every later verification would report tampering that never happened.
    if confidence is None:
        return None
    return round(min(max(confidence, 0.0), 1.0) * 100)


def _language_probability_pct(probability: float | None) -> int | None:
    if probability is None:
        return None
    return round(min(max(probability, 0.0), 1.0) * 100)


OnTranscript = Callable[[VoiceTurn, str], Awaitable[None]]


def build_stt_driver(
    settings: Settings,
    factory: async_sessionmaker[AsyncSession],
    client_factory: ClientFactory | None = None,
    on_transcript: OnTranscript | None = None,
) -> Callable[[VoiceTurn], Any]:
    """Build the production `TurnDriver`. `client_factory` is the injection
    point tests use to fake the `voice` container's `/transcribe` without a
    real HTTP call. `on_transcript` is the injection point
    `askwell.voice_tts` uses to continue a successfully transcribed turn into
    generation and speech instead of ending it here — see the module
    docstring."""

    def _default_client() -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=f"http://{settings.voice_service_host}:{settings.voice_port}",
            timeout=httpx.Timeout(
                connect=CONNECT_TIMEOUT_SECONDS, read=READ_TIMEOUT_SECONDS, write=30.0, pool=None
            ),
        )

    make_client = client_factory if client_factory is not None else _default_client

    async def driver(turn: VoiceTurn) -> None:
        chunks: list[bytes] = []
        while True:
            chunk = await turn.audio_in.get()
            if chunk is None:
                break
            chunks.append(chunk)
        audio = b"".join(chunks)

        if not audio:
            # A turn that closed with nothing captured at all — the same
            # silent, no-record outcome as background noise Whisper itself
            # ruled out below, just without a request to make for it.
            turn.status = "completed"
            await turn.audio_out.put(None)
            return

        async with make_client() as client:
            result = await _transcribe(client, audio)
        turn.mark("transcription_done")

        status = result["status"]

        if status == "no_speech":
            turn.status = "completed"
            await turn.audio_out.put(None)
            return

        if status == "unsupported_language":
            language = result.get("language")
            turn.emit_language_unsupported(language)
            try:
                await _store_turn(
                    factory,
                    turn=turn,
                    content="",
                    audit_payload={
                        "status": "unsupported_language",
                        "language": language,
                        "language_probability_pct": _language_probability_pct(
                            result.get("language_probability")
                        ),
                        "transcript_length": 0,
                    },
                )
            except AuditError:
                log.exception("voice_stt_audit_write_failed", turn_id=str(turn.turn_id))
                turn.status = "failed"
                await turn.audio_out.put(None)
                return
            turn.status = "completed"
            await turn.audio_out.put(None)
            return

        transcript = result["transcript"]
        confidence = result.get("confidence")
        turn.emit_transcript(transcript)
        if confidence is not None:
            turn.emit_confidence(confidence)
        try:
            await _store_turn(
                factory,
                turn=turn,
                content=transcript,
                audit_payload={
                    "status": "ok",
                    "language": result.get("language"),
                    "confidence_pct": _confidence_pct(confidence),
                    "transcript_length": len(transcript),
                },
            )
        except AuditError:
            log.exception("voice_stt_audit_write_failed", turn_id=str(turn.turn_id))
            turn.status = "failed"
            await turn.audio_out.put(None)
            return

        if on_transcript is not None:
            await on_transcript(turn, transcript)
            return

        turn.status = "completed"
        await turn.audio_out.put(None)

    return driver
