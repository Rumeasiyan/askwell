"""The voice service's `/health` surface, and `/transcribe` since
`M6-STT-BE-127`.

Same rule as `test_app.py`: always 200, never an aggregate boolean, for
`/health`. The two things this ticket's acceptance criteria actually ask for
are that transcription and synthesis are reported *separately*, and that
either can be missing without hiding the other. `/transcribe` is an action,
not a status report, so it is the one surface here that does answer with a
non-200 when it cannot do what was asked.
"""

import pytest
from fastapi.testclient import TestClient

from askwell.config import Settings
from askwell.voice import service
from askwell.voice.models import ModelHealth, ModelState, VoiceModels

from .test_voice_transcribe import _FakeWhisper, _Info, _Segment


def _models(
    *,
    whisper: ModelState = ModelState.LOADED,
    vad: ModelState = ModelState.LOADED,
    kokoro: ModelState = ModelState.LOADED,
) -> VoiceModels:
    def health(name: str, state: ModelState) -> ModelHealth:
        return ModelHealth(
            name=name,
            state=state,
            path=f"/models/{name}",
            reason=None if state is ModelState.LOADED else f"no {name} file",
        )

    return VoiceModels(
        whisper=object() if whisper is ModelState.LOADED else None,
        whisper_health=health("whisper", whisper),
        vad_session=object() if vad is ModelState.LOADED else None,
        vad_health=health("vad", vad),
        kokoro=object() if kokoro is ModelState.LOADED else None,
        kokoro_health=health("kokoro", kokoro),
    )


@pytest.fixture
def client(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(service, "load_models", lambda _settings: _models())
    return TestClient(service.create_app(settings))


def test_health_answers_200(client: TestClient) -> None:
    with client:
        response = client.get("/health")
    assert response.status_code == 200


def test_health_reports_transcription_and_synthesis_separately(client: TestClient) -> None:
    with client:
        payload = client.get("/health").json()
    assert payload["transcription"]["state"] == "loaded"
    assert payload["synthesis"]["state"] == "loaded"


def test_synthesis_missing_does_not_hide_transcription(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ticket's own edge case: synthesis unavailable must not read as
    voice mode being entirely down while transcription is fine."""
    monkeypatch.setattr(
        service, "load_models", lambda _settings: _models(kokoro=ModelState.MISSING)
    )
    with TestClient(service.create_app(settings)) as client:
        payload = client.get("/health").json()

    assert payload["transcription"]["state"] == "loaded"
    assert payload["synthesis"]["state"] == "missing"
    assert "no kokoro file" in payload["synthesis"]["reason"]


def test_transcription_missing_does_not_hide_synthesis(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        service, "load_models", lambda _settings: _models(whisper=ModelState.MISSING)
    )
    with TestClient(service.create_app(settings)) as client:
        payload = client.get("/health").json()

    assert payload["transcription"]["state"] == "missing"
    assert payload["synthesis"]["state"] == "loaded"


def test_service_starts_counter_survives_across_health_calls_within_one_run(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service, "load_models", lambda _settings: _models())
    with TestClient(service.create_app(settings)) as client:
        first = client.get("/health").json()["service_starts"]
        second = client.get("/health").json()["service_starts"]
    assert first == second
    assert first >= 1


def _models_with_whisper(whisper: object) -> VoiceModels:
    return VoiceModels(
        whisper=whisper,
        whisper_health=ModelHealth(name="whisper", state=ModelState.LOADED, path="/models/x"),
        vad_session=object(),
        vad_health=ModelHealth(name="vad", state=ModelState.LOADED, path="/models/vad"),
        kokoro=object(),
        kokoro_health=ModelHealth(name="kokoro", state=ModelState.LOADED, path="/models/kokoro"),
    )


def test_transcribe_returns_the_transcript_and_confidence(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _FakeWhisper(
        segments=[_Segment(text=" hello there", start=0.0, end=1.0, avg_logprob=-0.1)],
        info=_Info("en", 0.99),
    )
    monkeypatch.setattr(service, "load_models", lambda _settings: _models_with_whisper(fake))
    with TestClient(service.create_app(settings)) as client:
        response = client.post("/transcribe", content=b"\x01\x00" * 8000)

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["transcript"] == "hello there"
    assert payload["language"] == "en"
    assert payload["confidence"] is not None


def test_transcribe_without_a_loaded_model_answers_503_not_200(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unlike `/health`, this is an action a caller acts on — a 200 body the
    caller has to inspect to learn transcription is unavailable would make
    `askwell.voice_stt.TranscriptionUnavailable` indistinguishable from a
    zero-length answer."""
    monkeypatch.setattr(
        service, "load_models", lambda _settings: _models(whisper=ModelState.MISSING)
    )
    with TestClient(service.create_app(settings)) as client:
        response = client.post("/transcribe", content=b"\x01\x00" * 8000)

    assert response.status_code == 503
    assert "reason" in response.json()
