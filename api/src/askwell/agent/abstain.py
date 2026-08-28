"""Abstention copy: the message shown when nothing in the user's own
material clears the retrieval threshold. `M2-ABSTAIN-BE-054`.

`M2-ABSTAIN-RET-053` already decided *that* a turn abstains, before
`askwell.agent.compose` ever runs, and left a `reason_code`
(`empty_corpus`/`source_indexing`/`below_threshold`) on the trace as a
placeholder for this ticket to render. This module is the render: a pure
template, not a second model call — the nearest topic is the top scored
candidate's own heading, already sitting in memory from the retrieval this
turn already did, so there is nothing left to ask a model for.

The standing rule this composition path must never cross —
`prompts/abstention.v1.md` — is that general knowledge is never substituted
for a question about the user's own material (C5). Nothing here calls the
model, so the rule cannot be broken by a bad completion; `test_abstain.py`
asserts the rule's own text survives in the prompt file, the same shape as
`test_compose.py`'s C7 assertions, so a future edit that quietly drops it is
caught rather than merged.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

PROMPT_DIR = Path(__file__).parent / "prompts"
PROMPT_VERSION = "abstention.v1"
PROMPT_PATH = PROMPT_DIR / f"{PROMPT_VERSION}.md"

AbstainReason = Literal["empty_corpus", "source_indexing", "below_threshold"]


@lru_cache(maxsize=1)
def _load_standing_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _sources_clause(document_count: int, database_count: int) -> str:
    parts = []
    if document_count:
        parts.append(_plural(document_count, "document"))
    if database_count:
        parts.append(_plural(database_count, "database"))
    # Reachable only if `passage_count` is somehow positive with no source
    # counted at all — not expected given how both are queried from the same
    # join, but a proof-of-search sentence naming zero sources would be a
    # worse bug than a generic fallback.
    return " and ".join(parts) if parts else "your files"


def compose_abstention(
    *,
    reason_code: AbstainReason,
    passage_count: int,
    document_count: int,
    database_count: int,
    nearest_heading: str | None,
) -> str:
    """The full three-part abstention message: situation, proof, next action.

    `reason_code` picks the variant. `empty_corpus` and `source_indexing`
    have nothing to prove a search against — the acceptance criteria's own
    edge case, "there is no nearest material" — so they skip the proof
    sentence entirely rather than rendering it with the counts zeroed out.
    """
    if reason_code == "empty_corpus":
        return (
            "Nothing in your files answers this — nothing is indexed yet.\n"
            "Add a source, and ask again."
        )

    if reason_code == "source_indexing":
        return (
            "Nothing in your files answers this yet — this source is still "
            "indexing, so not everything in it has been searched.\n"
            "Ask again once it finishes, or add the source you'd expect this in."
        )

    sources = _sources_clause(document_count, database_count)
    proof = f"I searched {_plural(passage_count, 'passage')} across {sources}."
    if nearest_heading:
        proof += f" The closest material was about {nearest_heading}, which does not cover this."
    else:
        proof += " The search found nothing close."

    return (
        f"Nothing in your files answers this.\n{proof}\n"
        "Add the source you'd expect this in, and ask again."
    )
