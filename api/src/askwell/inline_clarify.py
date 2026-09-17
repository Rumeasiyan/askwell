"""Whether a pending clarification must interrupt this turn before an
answer composes. `M3-INLINE-FE-085`.

`docs/ux/ask.md` §5 "Inline clarification" / `docs/ux/clarifications.md` §5
"Blocking an answer": the *only* place a clarification interrupts is here,
in the conversation, and the queue (`M3-REVIEW-FE-072`) never gets bounced
to mid-question. Everything a clarification usually is — a row in
`clarifications`, answered or skipped through the same `askwell.review`
functions the queue screen calls — is unchanged; this module only decides,
once, whether one of those rows is relevant enough to this specific
question to ask about it before `askwell.ask` composes an answer, rather
than leaving it to be found later in the queue.

**Only two triggers can block.** `abbreviation` and `unreadable_scan` never
withhold a single, confident answer — skipping either still lets an
ordinary answer proceed unaffected, which is exactly why `askwell.clarify`
ranks them below `contradiction` and `document_identity` in the first
place. Those two are different: an unresolved "which source is current"
question changes which fact the answer would state, not just how well it is
explained.

**Relevance is exact-subject-or-shared-document, not semantic.** The same
reasoning `askwell.clarify._known_facts`'s own docstring gives for exact
subject matching applies here even more: a near-match interrupting a
question the ambiguity has nothing to do with is a worse failure than an
occasional missed interruption, which the ordinary post-hoc queue still
catches.
"""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from askwell.retrieve import Candidate

# `clarify.py`'s own `_TRIGGER_PRIORITY` ranks these two ahead of a
# vocabulary gap or a scan-quality note for the same reason: the wrong
# answer to either changes which fact gets stated, not merely how it reads.
BLOCKING_TRIGGERS = ("contradiction", "document_identity")


@dataclass(frozen=True, slots=True)
class BlockingClarification:
    id: uuid.UUID
    subject: str
    question: str
    options: list[str] | None
    evidence: dict[str, Any]


def _named_documents(evidence: dict[str, Any], options: list[str] | None) -> set[str]:
    if evidence.get("kind") == "contradiction":
        return {
            passage.get("document")
            for passage in evidence.get("passages", [])
            if passage.get("document")
        }
    return set(options or [])


async def find_blocking(
    session: AsyncSession, question: str, candidates: list[Candidate]
) -> tuple[BlockingClarification | None, int]:
    """The highest-ranked still-pending contradiction or document-identity
    clarification relevant to this question, plus how many other relevant
    ones exist beyond it.

    Relevant means the clarification's own subject is named in the
    question, or one of the documents its evidence names was actually
    retrieved for this question — either is enough to say the answer
    depends on it.

    Only the first match interrupts. A turn with more than one relevant
    ambiguity defers the rest to the queue rather than asking in sequence
    (this ticket's own edge case) — one inline interruption per turn is the
    same "never a modal per question" reasoning
    `docs/memory-and-clarification.md` §2 already gives for ingestion.
    """
    rows = (
        await session.execute(
            text(
                "SELECT id, subject, question, options, evidence FROM clarifications "
                "WHERE status = 'pending' AND evidence ->> 'trigger' = ANY(:triggers) "
                "ORDER BY rank ASC NULLS LAST, asked_at ASC"
            ),
            {"triggers": list(BLOCKING_TRIGGERS)},
        )
    ).all()
    if not rows:
        return None, 0

    candidate_filenames = {candidate.filename for candidate in candidates}
    question_lower = question.lower()
    matches: list[BlockingClarification] = []
    for row_id, subject, row_question, options, evidence in rows:
        related = subject.lower() in question_lower
        if not related:
            related = bool(_named_documents(evidence, options) & candidate_filenames)
        if related:
            matches.append(
                BlockingClarification(
                    id=row_id,
                    subject=subject,
                    question=row_question,
                    options=options,
                    evidence=evidence,
                )
            )

    if not matches:
        return None, 0
    return matches[0], len(matches) - 1


def default_assumption(blocking: BlockingClarification) -> str:
    """What a skip continues with — `docs/ux/ask.md` §5's own "the answer
    says which assumption it used."

    Neither blocking trigger has a safe machine-guessed `inferred_fact`
    (`askwell.clarify`'s own reasoning: nothing is safe to invent for a real,
    unresolved contradiction or an unconfirmed document identity) — but a
    turn that must still answer needs *something* to name. The newest
    document is what it names: the same "compare by recency" default
    `askwell.clarify._detect_document_identity` already applies when it asks
    the question in the first place ("is `<newest>` the current one?").
    """
    evidence = blocking.evidence
    if evidence.get("kind") == "contradiction":
        passages = evidence.get("passages", [])
        dated = [passage for passage in passages if passage.get("date")]
        newest = max(dated, key=lambda passage: passage["date"]) if dated else None
        newest = newest or (passages[0] if passages else None)
        if newest is not None:
            value = newest.get("value")
            return f"{newest['document']} ({value})" if value else str(newest["document"])
        return "the most recently added document"

    samples = evidence.get("samples", [])
    if samples:
        return str(samples[0]["document"])
    if blocking.options:
        # `askwell.clarify._detect_document_identity` lists options in
        # ascending `added_at` order, so the last one is the newest.
        return blocking.options[-1]
    return "the most recently added document"
