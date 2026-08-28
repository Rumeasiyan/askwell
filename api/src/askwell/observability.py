"""The local, on-demand abstention rate. `M2-ABSTAIN-OBS-056`.

Nothing here is transmitted — there is no telemetry (C1) — and nothing here
is recomputed. Every `ask_asked` record in `audit_interactions` already
carries the `abstained` flag `askwell.ask` decided at the time, against the
threshold and candidate scores in force *then* (`M2-ABSTAIN-RET-053`). This
module only counts that stored flag; it never re-runs the threshold
comparison against the current configuration, which is exactly what would
make a past turn's explanation stop matching the numbers that produced it.
"""

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from askwell.ask import ASK_ASKED
from askwell.audit import Store

# A "very long window" must still be a bounded query — the ticket's own edge
# case. 500 is a few weeks of normal single-user use, not a tuned constant.
DEFAULT_WINDOW = 500


@dataclass(frozen=True, slots=True)
class AbstentionRate:
    """The rate over however many of the most recent turns were actually read.

    `covered` is what the ticket's "reports what it covered" edge case asks
    for: a caller passing a window larger than the log has does not have to
    guess whether the result is the whole log or a truncated slice.
    """

    covered: int
    abstained: int

    @property
    def rate(self) -> float | None:
        """`None` with nothing asked yet. A `0.0` here would claim a healthy
        corpus that was never actually tested — the same reasoning
        `source_count`'s `NULL`-not-`0` already settled for a single turn."""
        if self.covered == 0:
            return None
        return self.abstained / self.covered


async def abstention_rate(session: AsyncSession, *, window: int = DEFAULT_WINDOW) -> AbstentionRate:
    """The abstention rate over the most recent `window` questions asked.

    Reads the `abstained` flag `askwell.ask` already stored per turn — never
    the candidate scores or threshold also stored alongside it, and never the
    live `Settings.retrieval_score_threshold`. Recomputing from either would
    make the rate answer "how would today's configuration have scored past
    turns" instead of "how many past turns actually abstained", which is not
    the question `docs/success-metrics.md` §2 asks.
    """
    if window < 1:
        raise ValueError("window must be at least 1")
    result = await session.execute(
        text(
            f"SELECT payload ->> 'abstained' FROM {Store.INTERACTIONS.value} "
            "WHERE kind = :kind ORDER BY occurred_at DESC, id DESC LIMIT :window"
        ),
        {"kind": ASK_ASKED, "window": window},
    )
    flags = result.scalars().all()
    covered = len(flags)
    abstained = sum(1 for flag in flags if flag == "true")
    return AbstentionRate(covered=covered, abstained=abstained)
