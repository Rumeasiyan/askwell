"""Turn summaries and source counts, produced once at composition time.

`M1-CONV-BE-177`.

`docs/ux/conversation.md` §2/§6 collapses a past turn to its question, a
one-line summary of what answered it, and a source count in the provenance
colour — and is explicit that **neither is ever recomputed**. Re-deriving
either from `citations` on read would make a turn's own history depend on
the state of the corpus at the moment someone scrolled back to it, rather
than on what was actually true when the turn happened (a deleted source
must not shrink a past count; a newly added one must not answer a past
question). So both are produced here, once, from exactly what the turn
itself produced — its answer text and the citation rows it wrote — and
`askwell.ask` writes them in the same transaction as the answer.

The source count is a count of *evidence*, not an estimate: distinct
documents named by the turn's own citation rows, never retrieval hits that
were not actually cited. A turn with no citation rows abstained — per C5,
the model is expected to say so rather than answer ungrounded — and
`source_count` is `None`, never `0`, matching the ticket's own "no count
at all" requirement (`docs/ux/conversation.md` §5).

This module is pure and does not call the model: a one-line summary from
the answer's own first sentence is cheap enough not to add latency to an
answer already streaming, and re-summarising with the model would be one
more place C5's abstention behaviour could regress unmeasured. Never
raises — a summary this module cannot build falls back to the turn's own
text; the caller (`askwell.ask._run_generation`) still wraps the call in
`try/except`, because a bug here must never be the reason an answer fails
to save.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from askwell.retrieve import Candidate

_SUMMARY_MAX_CHARS = 140
_ABSTAIN_SUMMARY = "The files did not cover this."
_PARTIAL_SUFFIX = " (stopped before finishing)"
_SENTENCE_RE = re.compile(r"[^.!?]*[.!?]")
_MARKER_RE = re.compile(r"\s*\[\d+\]")


@dataclass(frozen=True, slots=True)
class TurnSummary:
    """What gets stored with a finished turn, alongside its answer."""

    summary: str
    source_count: int | None  # `None` means abstained, distinct from `0`


def _truncate(text: str) -> str:
    text = " ".join(text.split())
    if len(text) <= _SUMMARY_MAX_CHARS:
        return text
    return text[: _SUMMARY_MAX_CHARS - 1].rstrip() + "…"


def _first_sentence(text: str) -> str:
    match = _SENTENCE_RE.match(text.strip())
    body = match.group(0) if match else text
    return _MARKER_RE.sub("", body).strip()


def _distinct_document_count(
    citation_rows: list[dict[str, Any]], candidates: list[Candidate]
) -> int:
    document_by_chunk = {candidate.chunk_id: candidate.document_id for candidate in candidates}
    documents = {
        document_by_chunk[row["chunk_id"]]
        for row in citation_rows
        if row["chunk_id"] in document_by_chunk
    }
    return len(documents)


def summarize_turn(
    *,
    question: str,
    answer_text: str,
    status: str,
    reason: str | None,
    partial: bool,
    citation_rows: list[dict[str, Any]],
    candidates: list[Candidate],
) -> TurnSummary:
    """The stored summary and source count for one finished turn.

    `status` is the turn's own final status (`completed`, `stopped`,
    `failed`). `partial` additionally covers a `completed` turn that hit
    the generation length limit — truncated by the limit, not by a user's
    stop, but the same "describe what was produced, mark it partial"
    edge case the ticket names.
    """
    if status == "failed":
        detail = reason or "Askwell hit an error while answering."
        return TurnSummary(summary=_truncate(f"Could not answer: {detail}"), source_count=None)

    if not citation_rows:
        summary = _ABSTAIN_SUMMARY + (_PARTIAL_SUFFIX if partial else "")
        return TurnSummary(summary=_truncate(summary), source_count=None)

    source_count = _distinct_document_count(citation_rows, candidates)
    body = _first_sentence(answer_text) or question.strip()
    summary = body + (_PARTIAL_SUFFIX if partial else "")
    return TurnSummary(summary=_truncate(summary), source_count=source_count)


def fallback_summary(question: str) -> TurnSummary:
    """Used only when `summarize_turn` itself raises — the ticket's own
    "summary generation fails" edge case. Derived from the question alone,
    since that is the one thing guaranteed to exist no matter what else
    about the turn went wrong."""
    return TurnSummary(summary=_truncate(f"Answered: {question.strip()}"), source_count=None)
