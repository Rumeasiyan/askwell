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
heuristic over candidate text. `prompts/conflicting_sources.v2.md` is the
call site's prompt going forward: it is `partial_answer.v1.md`'s content in
full — a conflicting-sources question can equally be a multi-part one — plus
the conflict convention this ticket adds, so `split_partial_answer` still
reads the "Not covered:" lines back out of its output unchanged.
`split_conflict_answer` reads the new "Conflicting sources on ...:" line the
same way.

`compose_conflict`'s `memory_fact` parameter, when given, is delimited into
the prompt as a `<memory-fact>` block the prompt asks the model to treat as
resolving. `M3-INLINE-FE-085` passes one when an inline clarification was
just answered. A conflict the user resolved from the Ask screen
(`askwell.conflict_resolution`, `M9-FIX-FE-204`) arrives instead as an
ordinary `retrieved_facts` entry on the next question.

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

`M3-APPLY-BE-079` gives each entry in both blocks a citation index of its
own, continuing straight on from the candidates' own `1..N` rather than
starting a second numbering scheme — `_delimit_memory_facts`/
`_delimit_schema_notes` take `start_index` for exactly this. `ask.py`'s
`_cite_claim` resolves an index in that range to a `fact_usage` row instead
of a `citations` row; C4 applies to a memory-derived claim the same way it
applies to a document-derived one, just against a different table.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from askwell.agent.compose import (
    ComposedPrompt,
    delimit_candidates,
    delimit_memory_facts,
    delimit_schema_notes,
    flag_injection,
)
from askwell.agent.placeholders import has_content
from askwell.memory import MemoryFact, SchemaNote
from askwell.retrieve import Candidate

PROMPT_DIR = Path(__file__).parent / "prompts"
PROMPT_VERSION = "conflicting_sources.v2"
PROMPT_PATH = PROMPT_DIR / f"{PROMPT_VERSION}.md"

# Matches `prompts/conflicting_sources.v2.md`'s fixed line exactly, the same
# deliberately-not-fuzzy convention `askwell.agent.partial` uses for
# "Not covered:" — a loose match would risk pulling ordinary prose into the
# conflict signal.
# The topic may be empty: a copied `<the specific fact being asked about>`
# is stripped out (`askwell.agent.placeholders`), and the positions under the
# line are still a conflict even though the model never named what about.
_CONFLICT_RE = re.compile(r"^Conflicting sources on\s*(.*?):\s*$")
_MEMORY_RESOLVED_RE = re.compile(r"^Resolved by memory:\s*(.*?)\s*\.?\s*$")


@dataclass(frozen=True, slots=True)
class ConflictAnswer:
    """What `split_conflict_answer` found in one composed answer."""

    topic: str | None  # the fact named on the "Conflicting sources on ...:" line
    resolved_by_memory: str | None  # the fact named on the "Resolved by memory:" line

    @property
    def is_conflict(self) -> bool:
        return self.topic is not None


# The memory-fact section is sent only when a `<memory-fact>` block is
# (#908). Sent without one, a 4B model wrote about the block it was told
# might be there — "the memory fact block was not provided" — and an empty
# "Resolved by memory:" line, into a new user's first answer.
_MEMORY_SECTION_RE = re.compile(
    r"<!-- memory-fact-section -->\n(?P<body>.*?)<!-- /memory-fact-section -->\n", re.S
)


@lru_cache(maxsize=2)
def _load_system_prompt(with_memory_fact: bool = False) -> str:
    text = PROMPT_PATH.read_text(encoding="utf-8")
    return _MEMORY_SECTION_RE.sub(
        lambda match: match.group("body") if with_memory_fact else "", text
    )


def _delimit_memory_fact(memory_fact: str | None) -> str:
    if memory_fact is None:
        return ""
    return f"\n\n<memory-fact>\n{memory_fact}\n</memory-fact>"


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
    # Facts and schema notes get indices continuing straight on from the
    # candidates' own 1..N — one citation index space, so `[index]` in the
    # model's answer resolves unambiguously to a document, a memory fact or
    # a schema note without a second marker syntax to teach it
    # (`M3-APPLY-BE-079`).
    facts_start = len(candidates) + 1
    notes_start = facts_start + len(retrieved_facts)
    return ComposedPrompt(
        system_prompt=_load_system_prompt(with_memory_fact=memory_fact is not None),
        user_content=(
            f"{delimit_candidates(candidates)}{_delimit_memory_fact(memory_fact)}"
            f"{delimit_memory_facts(retrieved_facts, facts_start)}"
            f"{delimit_schema_notes(retrieved_notes, notes_start)}"
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
            topic = match.group(1).strip() if has_content(match.group(1)) else ""
        # Emptied by a stripped placeholder, the line resolved nothing, and
        # reporting it would claim a memory fact that does not exist (#663).
        if (
            resolved_by_memory is None
            and (match := _MEMORY_RESOLVED_RE.match(stripped)) is not None
            and has_content(match.group(1))
        ):
            resolved_by_memory = match.group(1).strip()
    return ConflictAnswer(topic=topic, resolved_by_memory=resolved_by_memory)
