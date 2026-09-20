"""A missing model file must produce a clear refusal naming the path, per
this ticket's own acceptance criteria — not a crash, and not a vague
"unavailable".
"""

from pathlib import Path

import pytest

from askwell.config import Settings
from askwell.voice.models import ModelState, load_models


def _voice_settings(settings: Settings, tmp_path: Path, **overrides: Path) -> Settings:
    defaults = {
        "voice_whisper_model_path": tmp_path / "no-such-whisper-dir",
        "voice_vad_model_path": tmp_path / "no-such-vad.onnx",
        "voice_kokoro_model_path": tmp_path / "no-such-kokoro.onnx",
        "voice_kokoro_voices_path": tmp_path / "no-such-voices.bin",
    }
    defaults.update(overrides)
    return settings.model_copy(update=defaults)


def test_all_three_models_missing_by_default(settings: Settings, tmp_path: Path) -> None:
    models = load_models(_voice_settings(settings, tmp_path))

    assert models.whisper_health.state is ModelState.MISSING
    assert models.vad_health.state is ModelState.MISSING
    assert models.kokoro_health.state is ModelState.MISSING


def test_missing_model_names_its_own_path(settings: Settings, tmp_path: Path) -> None:
    vad_path = tmp_path / "no-such-vad.onnx"
    models = load_models(_voice_settings(settings, tmp_path, voice_vad_model_path=vad_path))

    assert str(vad_path) in models.vad_health.reason


def test_missing_whisper_names_the_model_file_not_just_the_directory(
    settings: Settings, tmp_path: Path
) -> None:
    """faster-whisper needs a *populated* directory. An empty one that
    happens to exist must still refuse — the fix is "add model.bin", not
    "the directory is already there"."""
    empty_dir = tmp_path / "whisper-small"
    empty_dir.mkdir()

    models = load_models(_voice_settings(settings, tmp_path, voice_whisper_model_path=empty_dir))

    assert models.whisper_health.state is ModelState.MISSING
    assert "model.bin" in models.whisper_health.reason


def test_transcription_reports_vad_when_whisper_would_otherwise_pass(
    settings: Settings, tmp_path: Path, monkeypatch: "pytest.MonkeyPatch"
) -> None:
    """Whisper cannot usefully run without VAD gating the stream — the
    combined `transcription` health must surface whichever of the two is the
    actual problem, not silently prefer one."""
    import askwell.voice.models as voice_models

    def fake_load_whisper(path: Path) -> tuple[object, voice_models.ModelHealth]:
        return object(), voice_models._loaded(voice_models.catalog.TRANSCRIPTION, path)

    monkeypatch.setattr(voice_models, "_load_whisper", fake_load_whisper)

    models = load_models(_voice_settings(settings, tmp_path))

    assert models.whisper_health.state is ModelState.LOADED
    assert models.transcription.state is ModelState.MISSING
    assert models.transcription is models.vad_health


def test_synthesis_refuses_when_only_the_voices_file_is_missing(
    settings: Settings, tmp_path: Path
) -> None:
    kokoro_model = tmp_path / "kokoro-v1.0.onnx"
    kokoro_model.write_bytes(b"not a real model")

    models = load_models(_voice_settings(settings, tmp_path, voice_kokoro_model_path=kokoro_model))

    assert models.synthesis.state is ModelState.MISSING
    assert "no-such-voices.bin" in models.synthesis.path
