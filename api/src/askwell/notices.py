"""Bundled model weights, their licences and their sources. `M7-DOC-DOC-163`.

C9 requires every bundled model to be GPLv3-compatible, to permit
redistribution and commercial use, and to be ungated, verified against the
registry before its name is written into configuration — this module is where
that verification is evidenced, not merely asserted. Generation-model entries
mirror `askwell.models_catalog` (verified 2026-08-28) and voice entries
mirror `askwell.voice.catalog` (verified 2026-09-20); this module does not
re-verify either, it reads them. The embedding and reranker rows are new:
`BAAI/bge-m3` (MIT) and `BAAI/bge-reranker-v2-m3` (Apache-2.0), both ungated,
verified against the Hugging Face registry API on 2026-09-23. Neither has an
automated, registry-verified *fetch* path yet (issue #244) — that is a
CI/packaging gap, separate from the licence question this module answers, and
is named on each entry rather than left for a reader to rediscover.

`DISALLOWED_LICENSES` is what cannot ship inside a GPL-3.0-or-later work
(`docs/decisions.md`, 2026-09-25, `M8-FIX-DOC-179`): a GPL version that cannot
be taken under GPLv3 (GPL-1.0-only, GPL-2.0-only), AGPL and SSPL (network
obligations Askwell does not take on — the PyMuPDF decision), non-commercial
and no-derivatives terms, and the "unlicensed"/proprietary default. GPLv3 in
any form and GPL-2.0-or-later are compatible, so they are not on it: the rule
changed, rather than `phonemizer` being allow-listed by name, so the next GPL
dependency is judged the same way. It does not include LGPL or CC-BY either —
weak copyleft and attribution-only terms are GPLv3-compatible and flagging
them would make the check cry wolf.

`KNOWN_LICENSES` is the other half, and it is an allow-list, not a second
deny-list (`M9-FIX-SEC-209`, issue #755). Any token on neither list is
*unclear*: the gate fails and a person decides. That covers a licence that
might be either side of the line, such as a bare "GPL" (GPL-2.0-only is
refused, GPL-2.0-or-later is not, and "GPL" says neither), a package whose
licence could not be read at all, and every free-text spelling — "AGPLv3",
"GNU Affero General Public License", "CC BY-NC 4.0" — that a list of refused
spellings would always be one behind. A person resolves an unknown string
once, by mapping it to SPDX in `scripts/generate_notices.py`, never by naming
a package. `scripts/generate_notices.py` is the one place both lists are
applied to what is actually installed.
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
        # "GPL-2.0" and "GPL-1.0" are SPDX's deprecated spellings of "-only".
        "GPL-1.0",
        "GPL-1.0-ONLY",
        "GPL-2.0",
        "GPL-2.0-ONLY",
        "AGPL",
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

# SPDX identifiers that are GPLv3-compatible, permit redistribution and
# commercial use, and actually occur in what Askwell ships or were named when
# this list was made (#755). Upper-cased, like `DISALLOWED_LICENSES`. Adding
# one is a licence decision: check it against C9 first, and never add a
# free-text spelling here — map it to SPDX in `scripts/generate_notices.py`.
# A licence missing from this list fails the gate as unclear, which is the
# intended default for a genuinely new permissive one too.
KNOWN_LICENSES: frozenset[str] = frozenset(
    {
        "0BSD",
        "APACHE-2.0",
        "BSD-2-CLAUSE",
        "BSD-3-CLAUSE",
        "CC-BY-4.0",
        "CC0-1.0",
        "ISC",
        "MIT",
        "MIT-0",
        "MIT-CMU",
        "MPL-2.0",
        "PSF-2.0",
        "PYTHON-2.0",
        "UNLICENSE",
        "ZLIB",
        # Weak copyleft: LGPL-2.1 may be taken under GPLv2-or-later, and so
        # under v3; LGPL-3.0 is GPLv3 with an extra permission.
        "LGPL-2.1",
        "LGPL-2.1-ONLY",
        "LGPL-2.1-OR-LATER",
        "LGPL-2.1+",
        "LGPL-3.0",
        "LGPL-3.0-ONLY",
        "LGPL-3.0-OR-LATER",
        "LGPL-3.0+",
        # Every GPL that can be taken under v3 (docs/decisions.md, 2026-09-25).
        "GPL-2.0-OR-LATER",
        "GPL-2.0+",
        "GPL-3.0",
        "GPL-3.0-ONLY",
        "GPL-3.0-OR-LATER",
        "GPL-3.0+",
    }
)

# Whitespace is required around "AND"/"OR" so a hyphenated SPDX identifier
# like "GPL-3.0-or-later" is never split mid-token — only a real compound
# expression such as "MIT OR Apache-2.0" is.
_SPLIT_RE = re.compile(r"\s*,\s*|\s*/\s*|\s+AND\s+|\s+OR\s+", re.IGNORECASE)


def _tokens(license_expression: str) -> list[str]:
    # SPDX grouping parentheses, as in "(MIT OR Apache-2.0)", are not part of
    # any identifier; left on, they would hide "AGPL-3.0-only)" from both lists.
    ungrouped = license_expression.replace("(", " ").replace(")", " ")
    return [t.strip().upper() for t in _SPLIT_RE.split(ungrouped) if t.strip()]


def disallowed_tokens(license_expression: str) -> list[str]:
    """Which tokens in a licence expression, if any, are on the disallowed list.

    Empty input (no licence metadata at all) is not itself a disallowed
    token — that is an unclear licence, reported by `unclear_tokens`.
    """
    return [t for t in _tokens(license_expression) if t in DISALLOWED_LICENSES]


def unclear_tokens(license_expression: str) -> list[str]:
    """Which tokens in a licence expression, if any, need a person to decide.

    Every token that is neither known-compatible nor disallowed: an
    unrecognised licence fails to review, never passes (#755). Empty input is
    unclear too: a package that states no licence has not granted one, and
    assuming it permissive is the error the gate exists to prevent. The
    generator's "UNVERIFIED (raw metadata: ...)" form is matched on its first
    word, since the raw text after it is not a licence identifier.
    """
    if not license_expression.strip():
        return ["UNVERIFIED"]
    if license_expression.strip().upper().startswith("UNVERIFIED"):
        return ["UNVERIFIED"]
    return [
        t
        for t in _tokens(license_expression)
        if t not in KNOWN_LICENSES and t not in DISALLOWED_LICENSES
    ]
