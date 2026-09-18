"""The local SQL rejection rate. `M4-SQL-OBS-108`.

Mirrors `askwell.observability.abstention_rate`'s own shape exactly: nothing
here is transmitted (C1), and nothing here is recomputed. Every `sql_query`
record in `audit_interactions` already carries the `validated` flag
`askwell.sql.validate.validate_query` decided at the time; this module only
counts that stored flag over a bounded recent window, so a maintainer can
see "the rejection rate went from 2% to 18%" (the ticket's own example)
without re-running validation against today's rules.
"""

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from askwell.audit import Store
from askwell.sql.validate import SQL_QUERY

# Same rationale as `askwell.observability.DEFAULT_WINDOW`: a bounded query,
# not a tuned constant.
DEFAULT_WINDOW = 500


@dataclass(frozen=True, slots=True)
class SqlRejectionRate:
    """The rejection rate over however many of the most recent generated
    queries were actually read. `covered` lets a caller passing a window
    larger than the log has tell a full read from a truncated one."""

    covered: int
    rejected: int

    @property
    def rate(self) -> float | None:
        """`None` with no query generated yet. A `0.0` here would claim a
        healthy prompt that was never actually exercised — the same
        reasoning `AbstentionRate.rate` already settled."""
        if self.covered == 0:
            return None
        return self.rejected / self.covered


async def sql_rejection_rate(
    session: AsyncSession, *, window: int = DEFAULT_WINDOW
) -> SqlRejectionRate:
    """The rejection rate over the most recent `window` validated queries.

    Reads the `validated` flag `askwell.sql.validate.validate_query` already
    stored per query — never re-parses the query text or re-runs `sqlglot`
    against today's rules, for the same reason `abstention_rate` never
    re-runs retrieval: a past rejection's explanation must keep matching the
    numbers that produced it.
    """
    if window < 1:
        raise ValueError("window must be at least 1")
    result = await session.execute(
        text(
            f"SELECT payload ->> 'validated' FROM {Store.INTERACTIONS.value} "
            "WHERE kind = :kind ORDER BY occurred_at DESC, id DESC LIMIT :window"
        ),
        {"kind": SQL_QUERY, "window": window},
    )
    flags = result.scalars().all()
    covered = len(flags)
    rejected = sum(1 for flag in flags if flag == "false")
    return SqlRejectionRate(covered=covered, rejected=rejected)
