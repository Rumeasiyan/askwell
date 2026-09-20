"""Which model files the voice container expects, and why these three.

Never a download URL: unlike `askwell.models_catalog` (the generation model,
fetched by choice in the setup wizard), C1 and this ticket's own acceptance
criteria require the voice container to fetch nothing at runtime. This module
exists only so the names, licences and registry-verification dates
(`AGENTS.md` §4) live in one place instead of being repeated — and risking
drift — across log messages, `.env.example` and the compose file.

All three verified against their registries on 2026-09-20:

- Whisper `small`, converted to CTranslate2: `Systran/faster-whisper-small`
  on Hugging Face, MIT, ungated, 484MB `model.bin` (fp16) alongside
  `config.json`, `tokenizer.json` and `vocabulary.json` — a directory, not a
  single file. `faster-whisper` (SYSTRAN, MIT) is the CPU-capable inference
  library; it wraps CTranslate2, not PyTorch, which is what keeps this
  container off a torch dependency the generation and embedding models
  already do not need.
- Silero VAD: `snakers4/silero-vad` on GitHub, MIT, ungated, ships
  `files/silero_vad.onnx` — run directly through `onnxruntime` (CPU
  provider), not through the `silero-vad` PyPI package, which pulls in torch
  and torchaudio for a model this small.
- Kokoro-82M: `hexgrad/Kokoro-82M`, Apache-2.0, ungated — already the
  recorded decision (`docs/decisions.md`, superseding Piper, 2026-08-26).
  The ONNX build used here is `thewh1teagle/kokoro-onnx`'s
  `model-files-v1.0` release (`kokoro-v1.0.onnx` + `voices-v1.0.bin`), loaded
  through the `kokoro-onnx` PyPI package (MIT) — the weights keep Kokoro's own
  Apache-2.0 licence; the loader's licence is separate and permissive too.

Model files are never bundled into the image or the repository. They are
placed on the host under `ASKWELL_MODELS_DIR` (default
`~/.local/share/askwell/models`, the same directory the host-side inference
supervisor reads its own three models from) and bind-mounted read-only into
this container at `/models` by `compose.yaml`.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class VoiceModelInfo:
    name: str
    purpose: str
    source: str
    license: str


TRANSCRIPTION = VoiceModelInfo(
    name="Whisper small (CTranslate2)",
    purpose="speech-to-text, English only in v1",
    source="Systran/faster-whisper-small",
    license="MIT",
)

VOICE_ACTIVITY_DETECTION = VoiceModelInfo(
    name="Silero VAD",
    purpose="detects speech in the incoming audio stream ahead of Whisper",
    source="snakers4/silero-vad",
    license="MIT",
)

SYNTHESIS = VoiceModelInfo(
    name="Kokoro-82M",
    purpose="text-to-speech",
    source="hexgrad/Kokoro-82M (ONNX build: thewh1teagle/kokoro-onnx)",
    license="Apache-2.0",
)
