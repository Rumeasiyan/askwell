"""Loading the three voice models, and saying clearly when one is not there.

Mirrors `deploy/inference/askwell-inference`'s `MODEL_MISSING` handling: a
missing file becomes a component state with a reason naming the path, never a
crash loop, because retrying cannot make a file appear and only the user can
put it there. The difference is the address it is reported at — the host
supervisor writes a state file for `askwell.health` to read; this is a
container process, so it answers an HTTP health probe of its own instead.

Nothing here reaches the network. Every loader below opens a path it was
given; none of `faster-whisper`, `onnxruntime` or `kokoro_onnx` is asked to
resolve a model by name, which is the shape that would let a library fall
back to downloading one.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from askwell.config import Settings
from askwell.logging import get_logger
from askwell.voice import catalog

log = get_logger(__name__)


class ModelState(StrEnum):
    """Where one model stands. Ordered worst-last, like `health.ComponentState`."""

    LOADED = "loaded"
    """Opened and ready to use."""

    MISSING = "missing"
    """No file at the configured path. Will not fix itself by retrying."""

    LOAD_FAILED = "load_failed"
    """The file is there but the library could not initialise it — usually a
    corrupt or partial download, or the wrong file for the wrong loader."""


@dataclass(frozen=True, slots=True)
class ModelHealth:
    name: str
    state: ModelState
    path: str
    reason: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "model": self.name,
            "state": str(self.state),
            "path": self.path,
            "reason": self.reason,
        }


def _missing(info: catalog.VoiceModelInfo, path: Path) -> ModelHealth:
    reason = (
        f"No {info.name} file at {path}. Askwell does not download models at "
        f"runtime — put one there, or point the corresponding "
        f"ASKWELL_VOICE_*_PATH setting at where it actually lives."
    )
    log.warning("voice_model_missing", model=info.name, path=str(path))
    return ModelHealth(name=info.name, state=ModelState.MISSING, path=str(path), reason=reason)


def _load_failed(info: catalog.VoiceModelInfo, path: Path, error: Exception) -> ModelHealth:
    log.error("voice_model_load_failed", model=info.name, path=str(path), error=str(error))
    return ModelHealth(
        name=info.name,
        state=ModelState.LOAD_FAILED,
        path=str(path),
        reason=f"Found the file but could not load it: {type(error).__name__}: {error}",
    )


def _loaded(info: catalog.VoiceModelInfo, path: Path) -> ModelHealth:
    log.info("voice_model_loaded", model=info.name, path=str(path))
    return ModelHealth(name=info.name, state=ModelState.LOADED, path=str(path))


def _load_whisper(path: Path) -> tuple[Any | None, ModelHealth]:
    # A CTranslate2 conversion is a directory (model.bin, config.json,
    # tokenizer.json, vocabulary.json), not a single file — checked for the
    # file that actually matters rather than just the directory's existence,
    # so a half-populated directory reports missing rather than load_failed.
    model_file = path / "model.bin"
    if not model_file.is_file():
        return None, _missing(catalog.TRANSCRIPTION, model_file)
    try:
        from faster_whisper import WhisperModel

        model = WhisperModel(str(path), device="cpu", compute_type="int8")
    except Exception as error:
        return None, _load_failed(catalog.TRANSCRIPTION, path, error)
    return model, _loaded(catalog.TRANSCRIPTION, path)


def _load_vad(path: Path) -> tuple[Any | None, ModelHealth]:
    if not path.is_file():
        return None, _missing(catalog.VOICE_ACTIVITY_DETECTION, path)
    try:
        import onnxruntime

        session = onnxruntime.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    except Exception as error:
        return None, _load_failed(catalog.VOICE_ACTIVITY_DETECTION, path, error)
    return session, _loaded(catalog.VOICE_ACTIVITY_DETECTION, path)


def _load_kokoro(model_path: Path, voices_path: Path) -> tuple[Any | None, ModelHealth]:
    if not model_path.is_file():
        return None, _missing(catalog.SYNTHESIS, model_path)
    if not voices_path.is_file():
        return None, _missing(catalog.SYNTHESIS, voices_path)
    try:
        from kokoro_onnx import Kokoro

        kokoro = Kokoro(str(model_path), str(voices_path))
    except Exception as error:
        return None, _load_failed(catalog.SYNTHESIS, model_path, error)
    return kokoro, _loaded(catalog.SYNTHESIS, model_path)


@dataclass(slots=True)
class VoiceModels:
    """The loaded handles, or the reason each one is not usable.

    `transcription` and `synthesis` are the two lines the acceptance criteria
    ask for. VAD has no user-facing mode of its own — nothing asks "is voice
    activity detection available" — so its state folds into `transcription`:
    Whisper cannot usefully run without it gating the audio stream, and a
    reader debugging "transcription unavailable" needs to see whether Whisper
    or VAD is the actual cause.
    """

    whisper: Any | None
    whisper_health: ModelHealth
    vad_session: Any | None
    vad_health: ModelHealth
    kokoro: Any | None
    kokoro_health: ModelHealth

    @property
    def transcription(self) -> ModelHealth:
        if self.whisper_health.state is not ModelState.LOADED:
            return self.whisper_health
        return self.vad_health

    @property
    def synthesis(self) -> ModelHealth:
        return self.kokoro_health


def load_models(settings: Settings) -> VoiceModels:
    """Try each model once. Called from the service's startup, not per-request."""
    whisper, whisper_health = _load_whisper(settings.voice_whisper_model_path)
    vad_session, vad_health = _load_vad(settings.voice_vad_model_path)
    kokoro, kokoro_health = _load_kokoro(
        settings.voice_kokoro_model_path, settings.voice_kokoro_voices_path
    )
    return VoiceModels(
        whisper=whisper,
        whisper_health=whisper_health,
        vad_session=vad_session,
        vad_health=vad_health,
        kokoro=kokoro,
        kokoro_health=kokoro_health,
    )
