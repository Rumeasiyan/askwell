"""Conflict detection and composition: presenting materially different
retrieved positions on the same asked fact rather than choosing one.
`M2-PARTIAL-BE-059`.

`M2-ABSTAIN-RET-053` already keeps a below-threshold retrieval out of
composition entirely, and `askwell.retrieve` already excludes a superseded
document from every candidate query (`d.superseded_by IS NULL`) — so by the
time this module runs, a conflict between two candidates is a conflict
between two documents that are both still current, never a document against
a version it has already been replaced by. That is what makes "supersession
is respected" this ticket's own acceptance criterion rather than something
it has to implement.

There is no reliable way to tell "two passages genuinely disagree on the
asked fact" from "two passages phrase the same fact differently" without
reading them for meaning, which is what the model is doing anyway — so, like
`askwell.agent.partial`, detection here is prompt-driven, not a Python
heuristic over candidate text. `prompts/conflicting_sources.v1.md` is the
call site's prompt going forward: it is `partial_answer.v1.md`'s content in
full — a conflicting-sources question can equally be a multi-part one — plus
the conflict convention this ticket adds, so `split_partial_answer` still
reads the "Not covered:" lines back out of its output unchanged.
`split_conflict_answer` reads the new "Conflicting sources on ...:" line the
same way.

The memory-fact hook is inert until M3: `compose_conflict`'s `memory_fact`
parameter, when given, is delimited into the prompt as a `<memory-fact>`
block the prompt asks the model to treat as resolving; nothing in this
milestone ever passes one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from askwell.agent.compose import ComposedPrompt, delimit_candidates, flag_injection
from askwell.retrieve import Candidate

PROMPT_DIR = Path(__file__).parent / "prompts"
PROMPT_VERSION = "conflicting_sources.v1"
PROMPT_PATH = PROMPT_DIR / f"{PROMPT_VERSION}.md"

# Matches `prompts/conflicting_sources.v1.md`'s fixed line exactly, the same
# deliberately-not-fuzzy convention `askwell.agent.partial` uses for
# "Not covered:" — a loose match would risk pulling ordinary prose into the
# conflict signal.
_CONFLICT_RE = re.compile(r"^Conflicting sources on\s*(.+?):\s*$")
_MEMORY_RESOLVED_RE = re.compile(r"^Resolved by memory:\s*(.+?)\s*\.?\s*$")


@dataclass(frozen=True, slots=True)
class ConflictAnswer:
    """What `split_conflict_answer` found in one composed answer."""

    topic: str | None  # the fact named on the "Conflicting sources on ...:" line
    resolved_by_memory: str | None  # the fact named on the "Resolved by memory:" line

    @property
    def is_conflict(self) -> bool:
        return self.topic is not None


@lru_cache(maxsize=1)
def _load_system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def _delimit_memory_fact(memory_fact: str | None) -> str:
    if memory_fact is None:
        return ""
    return f"\n\n<memory-fact>\n{memory_fact}\n</memory-fact>"


def compose_conflict(
    question: str,
    candidates: list[Candidate],
    memory_fact: str | None = None,
) -> ComposedPrompt:
    """Build the prompt for one turn where at least one candidate cleared the
    retrieval threshold. Pure — no I/O beyond reading the cached prompt file.

    `memory_fact` is the M3 hook this ticket's scope asks for: a resolving
    fact, when one exists, delimited into the prompt as its own
    `<memory-fact>` block. `None` composes identically to before this
    parameter existed.

    Shares delimitation and injection-flagging with `askwell.agent.compose` —
    the C7 boundary is one rule, not one rule per prompt.
    """
    injection_flagged, injection_patterns = flag_injection(candidates)
    return ComposedPrompt(
        system_prompt=_load_system_prompt(),
        user_content=(
            f"{delimit_candidates(candidates)}{_delimit_memory_fact(memory_fact)}"
            f"\n\nQuestion: {question}"
        ),
        prompt_version=PROMPT_VERSION,
        injection_flagged=injection_flagged,
        injection_patterns=injection_patterns,
    )


def split_conflict_answer(text: str) -> ConflictAnswer:
    """Read the "Conflicting sources on ...:" and "Resolved by memory:" lines
    back out of a composed answer.

    Both lines stay in the stored answer text, the same way
    `askwell.agent.partial.split_partial_answer` keeps "Not covered:" —
    they are the explicit statement `docs/ux/ask.md` §5 asks for, not
    scaffolding to strip out.
    """
    topic: str | None = None
    resolved_by_memory: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if topic is None and (match := _CONFLICT_RE.match(stripped)) is not None:
            topic = match.group(1).strip()
        if (
            resolved_by_memory is None
            and (match := _MEMORY_RESOLVED_RE.match(stripped)) is not None
        ):
            resolved_by_memory = match.group(1).strip()
    return ConflictAnswer(topic=topic, resolved_by_memory=resolved_by_memory)
