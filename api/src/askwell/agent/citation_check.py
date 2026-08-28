"""The uncited-claim query. `M1-CITE-TEST-045`.

`M1-CITE-BE-042` only proved "did every marked claim get a citation row" —
true by construction, since `ask._cite_claim` writes one the moment
`segment_claims` finds a marker. What C4 actually needs answered is "did any
factual claim in a *stored* answer end up with no citation row", which is a
different question: a citation row can be deleted, or written against a
chunk that later stops existing meaningfully, without the claim marker in
`messages.content` changing at all. This module re-segments the stored text
independently and checks it against the stored citations, rather than
trusting that the two were ever consistent.

An assistant message with no claims at all — an abstention, a purely
transitional reply — is compliant: `segment_claims` finding nothing is not
the same as finding an uncited one. A message that has any `fact_usage` rows
is excluded rather than checked, and named as excluded: nothing populates
`fact_usage` before `M3`, so a claim resolved against a memory fact instead
of a chunk cannot yet be told apart from one nobody ever cited, and counting
it a violation would be measuring segmentation disagreement, not citation
coverage.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from askwell.agent.claims import segment_claims


@dataclass(frozen=True, slots=True)
class UncitedClaim:
    """One claim in one stored answer with no citation row backing it."""

    message_id: str
    claim_text: str


@dataclass(frozen=True, slots=True)
class CitationCheckResult:
    """The counter-metric: percentage of checked answers where every claim
    traces to a citation row, and which ones did not."""

    checked: int
    excluded_fact_usage: int
    compliant: int
    violations: tuple[UncitedClaim, ...]

    @property
    def percentage(self) -> float:
        """100.0 when there is nothing to check — an empty sample is not a
        failure, the same reasoning `checked == 0` guards against a
        division by zero for."""
        if self.checked == 0:
            return 100.0
        return 100.0 * self.compliant / self.checked


async def check_citations(session: AsyncSession) -> CitationCheckResult:
    """Reconcile every stored assistant answer's claims against its
    citation rows.

    Runs entirely against the local database session already open — no
    network call of any kind, satisfying the ticket's own "runs offline"
    criterion by construction rather than by omission.
    """
    rows = (
        await session.execute(text("SELECT id, content FROM messages WHERE role = 'assistant'"))
    ).all()

    fact_used_ids = {
        str(row.message_id)
        for row in (await session.execute(text("SELECT DISTINCT message_id FROM fact_usage"))).all()
    }

    checked = 0
    compliant = 0
    excluded = 0
    violations: list[UncitedClaim] = []

    for row in rows:
        message_id = str(row.id)
        if message_id in fact_used_ids:
            excluded += 1
            continue

        checked += 1
        claims = segment_claims(row.content)
        if not claims:
            compliant += 1
            continue

        cited_ordinals = {
            ordinal
            for (ordinal,) in (
                await session.execute(
                    text("SELECT DISTINCT claim_ordinal FROM citations WHERE message_id = :id"),
                    {"id": row.id},
                )
            ).all()
        }

        message_violations = [
            UncitedClaim(message_id=message_id, claim_text=claim.text)
            for claim in claims
            if claim.ordinal not in cited_ordinals
        ]
        if message_violations:
            violations.extend(message_violations)
        else:
            compliant += 1

    return CitationCheckResult(
        checked=checked,
        excluded_fact_usage=excluded,
        compliant=compliant,
        violations=tuple(violations),
    )
