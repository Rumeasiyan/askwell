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
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from askwell.memory import MemoryFact, SchemaNote
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


def flag_injection_text(texts: Sequence[str]) -> tuple[bool, tuple[str, ...]]:
    """The same heuristic instruction-pattern flagging `flag_injection` applies
    to a `Candidate`'s content, over plain strings instead — schema notes and
    memory facts can originate from an imported dump's own column names
    (C3: untrusted content) or a document's text, so the C7 boundary applies
    to them exactly as it does to a retrieved passage.
    """
    matched: list[str] = []
    for text_ in texts:
        for pattern in _INSTRUCTION_PATTERNS:
            if pattern.search(text_) and pattern.pattern not in matched:
                matched.append(pattern.pattern)
    return bool(matched), tuple(matched)


def flag_injection(candidates: list[Candidate]) -> tuple[bool, tuple[str, ...]]:
    """Heuristic instruction-pattern flagging, shared with `askwell.agent.partial`
    for the same reason `delimit_candidates` is."""
    return flag_injection_text([candidate.content for candidate in candidates])


def confidence_label(origin: str, confidence: float | None) -> str:
    """`docs/memory-and-clarification.md` §3: "User-supplied facts are
    certain. Inferences are not, and the difference must survive into the
    prompt." — this is that survival, in words a small local model reads
    reliably rather than a bare number it might weight inconsistently.
    Shared between `askwell.agent.conflict` and `askwell.agent.sql_generate`,
    which both delimit the same two memory shapes into a prompt.
    """
    if origin != "inferred":
        return "user-confirmed"
    return f"inferred, confidence {confidence:.0%}" if confidence is not None else "inferred"


def delimit_memory_facts(facts: Sequence[MemoryFact], start_index: int) -> str:
    # Omitted entirely when empty, never an empty tagged block — a labelled
    # block with nothing in it reads as "memory has nothing to say," which
    # is a claim, not the absence of one.
    if not facts:
        return ""
    lines = "\n".join(
        f"- [{index}] [{confidence_label(fact.origin, fact.confidence)}] "
        f"{fact.subject}: {fact.fact}"
        for index, fact in enumerate(facts, start=start_index)
    )
    return f"\n\n<memory-facts>\n{lines}\n</memory-facts>"


def delimit_schema_notes(notes: Sequence[SchemaNote], start_index: int) -> str:
    """A stale note's caveat is rendered here too, defence in depth —
    `askwell.memory.retrieve_relevant_facts` (the caller both `conflict.py`
    and `sql_generate.py` draw notes from) already excludes a stale note
    outright (`M4-SCHEMA-BE-102`), so this branch is unreachable in
    production, the same "keep a currently-inert caveat correct" reasoning
    that ticket recorded.
    """
    if not notes:
        return ""
    lines = "\n".join(
        f"- [{index}] [{confidence_label(note.origin, note.confidence)}"
        f"{', column no longer found in the current schema' if note.stale else ''}] "
        f"{note.table_name}{f'.{note.column_name}' if note.column_name else ''}: "
        f"{note.description}"
        for index, note in enumerate(notes, start=start_index)
    )
    return f"\n\n<schema-notes>\n{lines}\n</schema-notes>"


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
