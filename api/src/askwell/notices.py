"""Bundled model weights, their licences and their sources. `M7-DOC-DOC-163`.

C9 requires every bundled model to permit redistribution and commercial use
and to be ungated, verified against the registry before its name is written
into configuration — this module is where that verification is evidenced,
not merely asserted. Generation-model entries mirror `askwell.models_catalog`
(verified 2026-08-28) and voice entries mirror `askwell.voice.catalog`
(verified 2026-09-20); this module does not re-verify either, it reads them.
The embedding and reranker rows are new: `BAAI/bge-m3` (MIT) and
`BAAI/bge-reranker-v2-m3` (Apache-2.0), both ungated, verified against the
Hugging Face registry API on 2026-09-23. Neither has an automated,
registry-verified *fetch* path yet (issue #244) — that is a CI/packaging
gap, separate from the licence question this module answers, and is named on
each entry rather than left for a reader to rediscover.

`DISALLOWED_LICENSES` is deliberately narrow: strong copyleft (GPL, AGPL,
SSPL and similar), non-commercial and no-derivatives terms, and the
"unlicensed"/proprietary default. It does not include LGPL or CC-BY — weak
copyleft and attribution-only terms are not the class of problem the PyMuPDF
AGPL decision (`docs/decisions.md`) or issue #26 (the model-licence
near-misses that produced C9) were about, and flagging them as blocking would
make the check cry wolf on the first real run. `scripts/generate_notices.py`
is the one place this list is applied to what is actually installed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ModelNotice:
    role: str
    name: str
    source: str
    license: str
    verified: str
    note: str = ""


MODEL_NOTICES: tuple[ModelNotice, ...] = (
    ModelNotice(
        role="Generation (light, standard)",
        name="Qwen3.5 4B (Q4_K_M)",
        source="bartowski/Qwen_Qwen3.5-4B-GGUF",
        license="Apache-2.0",
        verified="2026-08-28",
    ),
    ModelNotice(
        role="Generation (accelerated, workstation)",
        name="Qwen3.5 9B (Q4_K_M)",
        source="bartowski/Qwen_Qwen3.5-9B-GGUF",
        license="Apache-2.0",
        verified="2026-08-28",
    ),
    ModelNotice(
        role="Embedding",
        name="bge-m3",
        source="BAAI/bge-m3",
        license="MIT",
        verified="2026-09-23",
        note="No automated, registry-verified fetch path yet — placed manually, tracked in #244.",
    ),
    ModelNotice(
        role="Reranker",
        name="bge-reranker-v2-m3",
        source="BAAI/bge-reranker-v2-m3",
        license="Apache-2.0",
        verified="2026-09-23",
        note="No automated, registry-verified fetch path yet — placed manually, tracked in #244.",
    ),
    ModelNotice(
        role="Transcription",
        name="Whisper small (CTranslate2)",
        source="Systran/faster-whisper-small",
        license="MIT",
        verified="2026-09-20",
    ),
    ModelNotice(
        role="Voice activity detection",
        name="Silero VAD",
        source="snakers4/silero-vad",
        license="MIT",
        verified="2026-09-20",
    ),
    ModelNotice(
        role="Synthesis",
        name="Kokoro-82M",
        source="hexgrad/Kokoro-82M (ONNX build: thewh1teagle/kokoro-onnx)",
        license="Apache-2.0",
        verified="2026-09-20",
        note="Supersedes Piper (docs/decisions.md, 2026-08-26).",
    ),
    ModelNotice(
        role="OCR engine",
        name="Tesseract",
        source="tesseract-ocr/tesseract",
        license="Apache-2.0",
        verified="2026-09-23",
    ),
    ModelNotice(
        role="OCR traineddata (English)",
        name="tesseract-ocr-eng",
        source="tesseract-ocr/tessdata (Debian bookworm package)",
        license="Apache-2.0",
        verified="2026-09-23",
    ),
    ModelNotice(
        role="OCR traineddata (orientation/script detection)",
        name="tesseract-ocr-osd",
        source="tesseract-ocr/tessdata (Debian bookworm package)",
        license="Apache-2.0",
        verified="2026-09-23",
    ),
    ModelNotice(
        role="OCR traineddata (Tamil)",
        name="tesseract-ocr-tam",
        source="tesseract-ocr/tessdata (Debian bookworm package)",
        license="Apache-2.0",
        verified="2026-09-23",
        note="v1 hedge, not advertised as supported (AGENTS.md §1, docs/decisions.md).",
    ),
)

# Exact SPDX-style identifiers. Matched as whole tokens after splitting a
# licence expression on "/", "," and " AND "/" OR " (case-insensitive) — never
# as a substring search, so "LGPL-3.0-only" is never caught by a "GPL-3.0"
# entry meant for plain GPL.
DISALLOWED_LICENSES: frozenset[str] = frozenset(
    {
        "GPL-1.0",
        "GPL-1.0-ONLY",
        "GPL-1.0-OR-LATER",
        "GPL-2.0",
        "GPL-2.0-ONLY",
        "GPL-2.0-OR-LATER",
        "GPL-3.0",
        "GPL-3.0-ONLY",
        "GPL-3.0-OR-LATER",
        "AGPL-1.0",
        "AGPL-1.0-ONLY",
        "AGPL-1.0-OR-LATER",
        "AGPL-3.0",
        "AGPL-3.0-ONLY",
        "AGPL-3.0-OR-LATER",
        "SSPL-1.0",
        "CC-BY-NC-4.0",
        "CC-BY-NC-3.0",
        "CC-BY-NC-SA-4.0",
        "CC-BY-NC-ND-4.0",
        "CC-BY-ND-4.0",
        "COMMONS-CLAUSE",
        "BUSL-1.1",
        "UNLICENSED",
        "PROPRIETARY",
    }
)

# Whitespace is required around "AND"/"OR" so a hyphenated SPDX identifier
# like "GPL-3.0-or-later" is never split mid-token — only a real compound
# expression such as "MIT OR Apache-2.0" is.
_SPLIT_RE = re.compile(r"\s*,\s*|\s*/\s*|\s+AND\s+|\s+OR\s+", re.IGNORECASE)


def disallowed_tokens(license_expression: str) -> list[str]:
    """Which tokens in a licence expression, if any, are on the disallowed list.

    Empty input (no licence metadata at all) is not itself a disallowed
    token — that is a different, unverifiable-licence problem the caller
    reports separately, per the ticket's own edge case ("a transitive
    dependency with an unclear licence — flagged for a decision rather than
    assumed permissive").
    """
    if not license_expression.strip():
        return []
    tokens = [t.strip().upper() for t in _SPLIT_RE.split(license_expression) if t.strip()]
    return [t for t in tokens if t in DISALLOWED_LICENSES]
