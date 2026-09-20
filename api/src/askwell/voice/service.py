"""The voice service: a `/health` surface over the three loaded models, plus
`/transcribe` since `M6-STT-BE-127` and `/vad` since `M6-STT-BE-128`.

`M6-AUDIO-DEPLOY-125` built the health surface: this process loads what it can
from local files at startup and says, per model, whether it is usable and why
not. `M6-STT-BE-127` adds the one thing worth doing with a loaded Whisper —
`api`'s voice WebSocket channel (`askwell.voice_channel`, `askwell.voice_stt`)
calls `/transcribe` with one complete spoken turn's audio and gets a
transcript, a confidence measure, or an unsupported-language / no-speech
verdict back. `M6-STT-BE-128` adds `/vad`: `api`'s
`askwell.voice_turn_detection` calls it with a frame-aligned slice of audio
as it streams in, well before a turn ends, to close a turn on a pause rather
than waiting for the client's own `end` signal. `M6-TTS-BE-130` adds
`/synthesize`: `api`'s `askwell.voice_tts` calls it once per completed
sentence as an answer streams, so speech can start well before the whole
answer exists.

Runs on `internal` only (`compose.yaml`) — no egress network membership at
all, unlike `api` and `worker`. It has nothing to reach: every model is a
local file, and there is no online-AI or web-search path through voice mode
(`docs/decisions.md` — no escalation to the web from voice). `/transcribe` is
only ever called from `api`, over that same `internal` network — never from
the browser, which has no route to this container at all.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from askwell import __version__
from askwell.config import Environment, Settings, load_settings
from askwell.logging import configure_logging, get_logger
from askwell.voice.models import VoiceModels, load_models
from askwell.voice.synthesize import synthesize
from askwell.voice.transcribe import transcribe
from askwell.voice.vad import score_frames

log = get_logger(__name__)

# In-memory only, and deliberately so: a local counter, per AGENTS.md §3 C1's
# "local counter only — nothing transmitted" analytics requirement. It is not
# persisted, because persisting it would be the first byte of a usage log this
# ticket has no audit requirement to keep, and the number resets on every
# restart, which is honest about what it measures — this process's own
# lifetime, not the product's history.
_service_starts = 0


def _health_payload(models: VoiceModels) -> dict[str, object]:
    return {
        "transcription": models.transcription.as_dict(),
        "synthesis": models.synthesis.as_dict(),
        "service_starts": _service_starts,
    }


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Load what is there, log what happened, never crash over what is not.

    A missing model is exactly as likely on a fresh install as a present one —
    it is the state before the user has put the files there — so startup
    always succeeds. What `/health` reports afterwards is what tells the
    difference (AGENTS.md §3 C1's "clear refusal naming the path").
    """
    global _service_starts
    settings: Settings = app.state.settings
    models = load_models(settings)
    app.state.models = models
    _service_starts += 1
    log.info(
        "voice_startup",
        version=__version__,
        transcription=models.transcription.as_dict(),
        synthesis=models.synthesis.as_dict(),
        service_starts=_service_starts,
    )
    yield
    log.info("voice_shutdown")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings if settings is not None else load_settings()
    app = FastAPI(title="askwell-voice", lifespan=lifespan)
    app.state.settings = settings

    @app.get("/health")
    async def health() -> JSONResponse:
        # Always 200. `api/src/askwell/app.py`'s own health surface answers
        # 200 with every component unreachable, precisely so a caller cannot
        # collapse "the process answered and says X" into "the process is
        # down" — an HTTP status is one bit, and this payload already carries
        # two independent states plus a reason each. Mixing a 503 back in
        # here would reintroduce the aggregate boolean the rest of the
        # codebase deliberately has nowhere.
        return JSONResponse(_health_payload(app.state.models))

    @app.post("/transcribe")
    async def transcribe_endpoint(request: Request) -> JSONResponse:
        models: VoiceModels = app.state.models
        if models.whisper is None:
            # Unlike `/health`, this is an action, not a status report — a
            # caller that cannot transcribe needs to fail the turn rather
            # than receive 200 with a body it has to inspect to learn that.
            # `askwell.voice_stt.TranscriptionUnavailable` is the other half.
            return JSONResponse(
                {"reason": models.whisper_health.reason or "Transcription model not loaded."},
                status_code=503,
            )
        audio = await request.body()
        result = transcribe(models.whisper, audio)
        return JSONResponse(
            {
                "status": result.status,
                "transcript": result.transcript,
                "confidence": result.confidence,
                "language": result.language,
                "language_probability": result.language_probability,
            }
        )

    @app.post("/vad")
    async def vad_endpoint(request: Request) -> JSONResponse:
        models: VoiceModels = app.state.models
        if models.vad_session is None:
            # Same shape as `/transcribe`'s own refusal: an action a caller
            # must fail rather than receive 200 with nothing usable in it.
            return JSONResponse(
                {"reason": models.vad_health.reason or "VAD model not loaded."},
                status_code=503,
            )
        audio = await request.body()
        probabilities = score_frames(models.vad_session, audio)
        return JSONResponse({"speech_probabilities": probabilities})

    @app.post("/synthesize")
    async def synthesize_endpoint(request: Request) -> Response:
        models: VoiceModels = app.state.models
        if models.kokoro is None:
            # Same refusal shape as `/transcribe`: an action the caller must
            # fail rather than receive 200 with nothing usable in it.
            return JSONResponse(
                {"reason": models.kokoro_health.reason or "Synthesis model not loaded."},
                status_code=503,
            )
        settings: Settings = app.state.settings
        payload = await request.json()
        text_ = str(payload.get("text", "")).strip()
        if not text_:
            return JSONResponse({"reason": "No text to synthesize."}, status_code=400)
        result = synthesize(models.kokoro, text_, settings.voice_kokoro_voice)
        return Response(
            content=result.audio,
            media_type="application/octet-stream",
            headers={"X-Sample-Rate": str(result.sample_rate)},
        )

    return app


def main() -> None:
    import uvicorn

    try:
        settings = load_settings()
    except Exception as error:
        raise SystemExit(str(error)) from None

    configure_logging(
        level=settings.log_level,
        json_output=settings.environment is not Environment.DEVELOPMENT,
    )
    app = create_app(settings)
    uvicorn.run(app, host=settings.voice_host, port=settings.voice_port, log_config=None)
