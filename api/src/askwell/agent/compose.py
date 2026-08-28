"""Answer composition: assembling the prompt sent to the model. `M1-ASK-BE-037`.

C7 — retrieved content is data, never instruction — is preserved two ways
here, both required and both tested: **delimitation**, every retrieved
passage wrapped in an explicit `<retrieved-content>` block, and the
**standing statement** in `prompts/answer_composition.v1.md` that a block's
text is never an instruction regardless of what it says. `test_compose.py`
asserts both are present in the prompt file and fails if either is removed —
the one test in this module that exists to catch a future edit, not today's
behaviour.

Instruction-like pattern flagging is a mitigation, not a detection system: it
misses anything that does not match a pattern, and it flags legitimate
instructional prose (a policy manual) exactly as readily as a real attempt.
Flagging never changes what gets composed — it only records
`injection_flagged` for `messages.trace` (`docs/architecture.md` §7.1), once
`M1-ASK-API-038` exists to write it there.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from askwell.retrieve import Candidate

PROMPT_DIR = Path(__file__).parent / "prompts"
PROMPT_VERSION = "answer_composition.v1"
PROMPT_PATH = PROMPT_DIR / f"{PROMPT_VERSION}.md"

# Kept in sync with the delimiter documented in the prompt file itself by
# `test_compose.py` — if one changes without the other, delimitation and the
# text describing it disagree, which is worse than either alone.
CONTENT_TAG = "retrieved-content"

# Heuristic and known to both miss real attempts and flag harmless prose
# (`docs/architecture.md` §9). Ordered roughly most- to least-specific; not
# exhaustive and not meant to be — see the module docstring.
_INSTRUCTION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"ignore (all|any|the)?\s*(previous|prior|above)\s*instructions",
        r"disregard (all|any|the)?\s*(previous|prior|above)\s*instructions",
        r"new instructions?\s*:",
        r"you are now\b",
        r"reveal your (system )?prompt",
        r"(show|print|output) your (system )?prompt",
        r"override your instructions",
        r"do not (tell|mention|reveal) (the )?user",
        r"act as (a|an)\b",
    )
)


@dataclass(frozen=True, slots=True)
class ComposedPrompt:
    """What gets sent to the model, and what gets recorded about the turn."""

    system_prompt: str
    user_content: str
    prompt_version: str
    injection_flagged: bool
    injection_patterns: tuple[str, ...]  # which patterns matched, for the trace


@lru_cache(maxsize=1)
def _load_system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def delimit_candidates(candidates: list[Candidate]) -> str:
    """Wrap each candidate in its own `<retrieved-content>` block. Shared with
    `askwell.agent.partial`, which composes a different prompt over the same
    candidates and must delimit them identically — the C7 boundary this
    enforces does not change with which prompt is in force.
    """
    blocks = [
        f'<{CONTENT_TAG} index="{index}" chunk_id="{candidate.chunk_id}">\n'
        f"{candidate.content}\n"
        f"</{CONTENT_TAG}>"
        for index, candidate in enumerate(candidates, start=1)
    ]
    return "\n\n".join(blocks)


def flag_injection(candidates: list[Candidate]) -> tuple[bool, tuple[str, ...]]:
    """Heuristic instruction-pattern flagging, shared with `askwell.agent.partial`
    for the same reason `delimit_candidates` is."""
    matched: list[str] = []
    for candidate in candidates:
        for pattern in _INSTRUCTION_PATTERNS:
            if pattern.search(candidate.content) and pattern.pattern not in matched:
                matched.append(pattern.pattern)
    return bool(matched), tuple(matched)


def compose(question: str, candidates: list[Candidate]) -> ComposedPrompt:
    """Build the prompt for one turn. Pure — no I/O beyond reading the cached prompt file."""
    injection_flagged, injection_patterns = flag_injection(candidates)
    return ComposedPrompt(
        system_prompt=_load_system_prompt(),
        user_content=f"{delimit_candidates(candidates)}\n\nQuestion: {question}",
        prompt_version=PROMPT_VERSION,
        injection_flagged=injection_flagged,
        injection_patterns=injection_patterns,
    )
