"""The voice service's `/health` surface.

Same rule as `test_app.py`: always 200, never an aggregate boolean. The two
things this ticket's acceptance criteria actually ask for are that
transcription and synthesis are reported *separately*, and that either can be
missing without hiding the other.
"""

import pytest
from fastapi.testclient import TestClient

from askwell.config import Settings
from askwell.voice import service
from askwell.voice.models import ModelHealth, ModelState, VoiceModels


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
