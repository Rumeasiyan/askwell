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

**Relevance is exact-subject-or-shared-passage, not semantic.** The same
reasoning `askwell.clarify._known_facts`'s own docstring gives for exact
subject matching applies here even more: a near-match interrupting a
question the ambiguity has nothing to do with is a worse failure than an
occasional missed interruption, which the ordinary post-hoc queue still
catches.

**A shared passage is one the answer would actually rest on** (#892): a
reranked candidate scoring at or above the retrieval threshold, and, for a
contradiction, on the page the conflicting value was found on. Sharing a
*document* was the rule until `0.9.22`, and on a small corpus retrieval
reaches every document, so every pending contradiction interrupted every
question — store closing hours stopped a question about notice periods.
"""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from askwell.retrieve import Candidate, candidate_score

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


def _on_page(candidate: Candidate, page: Any) -> bool:
    # A passage or candidate with no page (a sheet, a text file) can only be
    # matched by its document.
    if not isinstance(page, int) or candidate.page_from is None:
        return True
    page_to = candidate.page_to if candidate.page_to is not None else candidate.page_from
    return candidate.page_from <= page <= page_to


def _rests_on(
    evidence: dict[str, Any], options: list[str] | None, supporting: list[Candidate]
) -> bool:
    """Whether one of the passages this answer would compose from is what
    the clarification is about."""
    if evidence.get("kind") == "contradiction":
        return any(
            candidate.filename == passage.get("document")
            and _on_page(candidate, passage.get("page"))
            for passage in evidence.get("passages", [])
            for candidate in supporting
        )
    named = set(options or [])
    return any(candidate.filename in named for candidate in supporting)


async def find_blocking(
    session: AsyncSession, question: str, candidates: list[Candidate], threshold: float
) -> tuple[BlockingClarification | None, int]:
    """The highest-ranked still-pending contradiction or document-identity
    clarification relevant to this question, plus how many other relevant
    ones exist beyond it.

    Relevant means the clarification's own subject is named in the
    question, or a passage it is about was retrieved for this question at
    or above `threshold` — either is enough to say the answer depends on
    it. A retrieved passage from the same document, but a different page,
    is not (#892).

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

    # Only reranked candidates (#910): without the reranker, scores fall back
    # to dense similarity, which ranks almost every passage of a small,
    # single-company corpus above the threshold — exactly the "every
    # contradiction is relevant" failure #892 fixed. The question still names
    # its subject, or the clarification waits in the queue.
    supporting = [
        c for c in candidates if c.rerank_score is not None and candidate_score(c) >= threshold
    ]
    question_lower = question.lower()
    matches: list[BlockingClarification] = []
    for row_id, subject, row_question, options, evidence in rows:
        related = subject.lower() in question_lower
        if not related:
            related = _rests_on(evidence, options, supporting)
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


def answer_as_fact(subject: str, evidence: dict[str, Any], answer: str) -> str:
    """What an answer to a clarification means, as one sentence the model can
    use (#928).

    The answer to "which source is current?" is a filename. Stored and sent
    as "meridian loom retail stores close: store_hours_2026.pdf", the model
    could not tell what the filename settled, kept presenting both values,
    and wrote that the memory fact's document "is not provided". Said as a
    statement with the chosen document's own value and words, it is a fact
    the model can answer from and cite as memory. Any other answer, typed by
    the user, is already a statement and is kept as written.
    """
    chosen = answer.strip()
    if evidence.get("kind") == "contradiction":
        for passage in evidence.get("passages", []):
            if passage.get("document") == chosen:
                value = passage.get("value")
                quoted = str(passage.get("text") or "").strip()
                said = f' It says: "{quoted}"' if quoted else ""
                current = f" ({value})" if value else ""
                return f"For {subject}, {chosen} is the current source{current}.{said}"
    if evidence.get("kind") == "passage" and chosen:
        return f"{chosen} is the current version of {subject}."
    return chosen


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
