"""Partial-answer composition: answer the grounded part of a compound
question, name the ungrounded part plainly. `M2-PARTIAL-BE-057`.

`M2-ABSTAIN-RET-053` already decided that a turn with nothing above threshold
never reaches composition at all — this module only ever runs once at least
one retrieved candidate cleared the bar, so it can never be the branch that
handles "every aspect uncovered" (that stays abstention, per the ticket's own
edge case). What it exists for is the case the ordinary `answer_composition`
prompt has no way to represent on purpose: a question with more than one part
where only some of them are supported by what was retrieved.

Aspect decomposition is prompt-driven, not a Python heuristic — there is no
reliable way to tell "two aspects, one retrieved" apart from "one aspect,
retrieved thinly" without asking the model, which is doing the composition
anyway. `prompts/partial_answer.v1.md` asks it to answer what it can, cite as
usual, and name anything left over with a fixed, parseable sentence rather
than folding it into fluent prose. `split_partial_answer` reads that
convention back out, the same way `askwell.agent.claims.segment_claims` reads
citation markers back out of the same text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from askwell.agent.compose import ComposedPrompt, delimit_candidates, flag_injection
from askwell.retrieve import Candidate

PROMPT_DIR = Path(__file__).parent / "prompts"
PROMPT_VERSION = "partial_answer.v1"
PROMPT_PATH = PROMPT_DIR / f"{PROMPT_VERSION}.md"

# Sentence-initial, one per line, matching exactly what the prompt asks the
# model to write — deliberately not a fuzzy match, since a loose pattern
# would risk pulling ordinary prose into the uncovered list.
_UNCOVERED_RE = re.compile(r"^Not covered:\s*(.+?)\s*\.?\s*$")


@dataclass(frozen=True, slots=True)
class PartialAnswer:
    """What `split_partial_answer` found in one composed answer."""

    uncovered: tuple[str, ...]  # in the order the model wrote them; not de-duplicated

    @property
    def is_partial(self) -> bool:
        return bool(self.uncovered)


@lru_cache(maxsize=1)
def _load_system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def compose_partial(question: str, candidates: list[Candidate]) -> ComposedPrompt:
    """Build the prompt for one turn where at least one candidate cleared the
    retrieval threshold. Pure — no I/O beyond reading the cached prompt file.

    Shares delimitation and injection-flagging with `askwell.agent.compose` —
    the C7 boundary is one rule, not one rule per prompt.
    """
    injection_flagged, injection_patterns = flag_injection(candidates)
    return ComposedPrompt(
        system_prompt=_load_system_prompt(),
        user_content=f"{delimit_candidates(candidates)}\n\nQuestion: {question}",
        prompt_version=PROMPT_VERSION,
        injection_flagged=injection_flagged,
        injection_patterns=injection_patterns,
    )


def split_partial_answer(text: str) -> PartialAnswer:
    """Read the `Not covered: <aspect>.` lines back out of a composed answer.

    The lines stay in the stored answer text — they are the explicit
    statement `docs/ux/ask.md` §5 asks for, not scaffolding to strip out —
    this only extracts them so the turn can be marked partial and the gap
    named on the trace and audit record without re-parsing prose later.
    """
    uncovered = [
        match.group(1).strip()
        for line in text.splitlines()
        if (match := _UNCOVERED_RE.match(line.strip())) is not None
    ]
    return PartialAnswer(uncovered=tuple(uncovered))
