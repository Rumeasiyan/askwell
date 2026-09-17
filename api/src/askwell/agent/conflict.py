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

`M3-APPLY-RET-078` adds a second, unrelated memory input: `retrieved_facts`/
`retrieved_notes`, whatever `askwell.memory.retrieve_relevant_facts` found
relevant to the question, always passed (possibly empty) rather than only
when a clarification was just answered. These are delimited into their own
`<memory-facts>`/`<schema-notes>` blocks, each entry labelled
`[user-confirmed]` or `[inferred, confidence N%]` so the model can tell a
stated fact from a guess — `docs/memory-and-clarification.md` §3's
"confidence ... must survive into the prompt". They are data, exactly like
a `<retrieved-content>` block, never an instruction (C7) — `docs/decisions.md`
has the reasoning for keeping this separate from `memory_fact` rather than
folding one into the other: `memory_fact` is a single fact already known to
settle a specific conflict, these are unranked background that may or may
not bear on anything the answer says.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from askwell.agent.compose import ComposedPrompt, delimit_candidates, flag_injection
from askwell.memory import MemoryFact, SchemaNote
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


def _confidence_label(origin: str, confidence: float | None) -> str:
    """`docs/memory-and-clarification.md` §3: "User-supplied facts are
    certain. Inferences are not, and the difference must survive into the
    prompt." — this is that survival, in words a small local model reads
    reliably rather than a bare number it might weight inconsistently.
    """
    if origin != "inferred":
        return "user-confirmed"
    return f"inferred, confidence {confidence:.0%}" if confidence is not None else "inferred"


def _delimit_memory_facts(facts: Sequence[MemoryFact]) -> str:
    # Omitted entirely when empty, never an empty tagged block — the
    # ticket's own edge case: a labelled block with nothing in it reads as
    # "memory has nothing to say," which is a claim, not the absence of one.
    if not facts:
        return ""
    lines = "\n".join(
        f"- [{_confidence_label(fact.origin, fact.confidence)}] {fact.subject}: {fact.fact}"
        for fact in facts
    )
    return f"\n\n<memory-facts>\n{lines}\n</memory-facts>"


def _delimit_schema_notes(notes: Sequence[SchemaNote]) -> str:
    if not notes:
        return ""
    lines = "\n".join(
        f"- [{_confidence_label(note.origin, note.confidence)}] "
        f"{note.table_name}{f'.{note.column_name}' if note.column_name else ''}: "
        f"{note.description}"
        for note in notes
    )
    return f"\n\n<schema-notes>\n{lines}\n</schema-notes>"


def compose_conflict(
    question: str,
    candidates: list[Candidate],
    memory_fact: str | None = None,
    retrieved_facts: Sequence[MemoryFact] = (),
    retrieved_notes: Sequence[SchemaNote] = (),
) -> ComposedPrompt:
    """Build the prompt for one turn where at least one candidate cleared the
    retrieval threshold. Pure — no I/O beyond reading the cached prompt file.

    `memory_fact` is the `M3-INLINE-FE-085` hook: a single fact that just
    resolved *this* conflict, when one exists. `retrieved_facts`/
    `retrieved_notes` are `M3-APPLY-RET-078`'s separate, always-possibly-
    present addition — whatever `askwell.memory.retrieve_relevant_facts`
    found relevant to the question, delimited into their own labelled
    blocks. All three default to nothing, composing identically to before
    any of them existed.

    Shares delimitation and injection-flagging with `askwell.agent.compose` —
    the C7 boundary is one rule, not one rule per prompt.
    """
    injection_flagged, injection_patterns = flag_injection(candidates)
    return ComposedPrompt(
        system_prompt=_load_system_prompt(),
        user_content=(
            f"{delimit_candidates(candidates)}{_delimit_memory_fact(memory_fact)}"
            f"{_delimit_memory_facts(retrieved_facts)}{_delimit_schema_notes(retrieved_notes)}"
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
