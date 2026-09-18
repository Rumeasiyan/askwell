"""Inject a row limit into a validated read, and label a result that hit it.
`M4-SQL-VAL-105`.

**Only ever called on a query `askwell.sql.validate.validate_query` has
already accepted.** This module does not re-validate — a caller that reached
here without validating first is the one thing C2 exists to prevent, and a
second, slightly different check here would eventually drift from the real
one instead of catching that mistake.

**Injection happens on the parsed tree, never by string manipulation of the
original text** (the ticket's own Validation Rule, echoing C2's reasoning
for `validate.py`): appending `" LIMIT 1000"` to a query string that already
ends in `-- ` or that is a `UNION` whose last branch has its own `ORDER BY`
would change what the text means, not just add a cap to it. Parsing again
and setting `sqlglot`'s own `limit` argument is correct regardless of shape.

**The injected limit is visible in the disclosed SQL, and distinguishable
from one the model wrote**, `docs/data-sources.md` §4 layer 3. Disclosure
here means the `LIMIT` clause `sqlglot` renders carries a trailing SQL
comment (`INJECTED_LIMIT_COMMENT`) naming Askwell as its source — safe only
because this runs *after* validation, never before: `validate.py`'s own
module docstring notes `sqlglot`'s tokenizer discards comments before they
ever reach the parsed tree, so a comment added here cannot be mistaken for
one a candidate query smuggled in, and it plays no role in what actually
executes (an SQL comment; every one of the four supported engines ignores
it).

**Top-level aggregate exemption.** `_has_top_level_aggregate` looks only at
the outer statement's own select list, never descending into a nested
`SELECT` — the ticket's own "aggregate in a subquery but not at the top
level — limited, because the top-level result is a row set" edge case, made
literal. A `UNION`/`INTERSECT`/`EXCEPT` never qualifies for the exemption
even when every branch aggregates down to one row each: the combined result
is still a row set whose size depends on how many branches there are, not a
single number. A window function's own aggregate (`SUM(x) OVER (...)`) does
not count as an aggregate here either, since unlike a plain aggregate it
does not collapse the row set down at all.

**Any existing limit clause is left alone, of any size and any shape** — the
ticket's own "already limited to more than the default" edge case,
generalised to cover more than `sqlglot`'s `exp.Limit`. Postgres/T-SQL's own
SQL:2008 `OFFSET ... FETCH {FIRST|NEXT} ... ROWS ONLY` parses to `exp.Fetch`
under the same `"limit"` tree slot rather than `exp.Limit`, and has no
`.expression` attribute holding its count — treating `exp.Fetch` as "no
limit" (an earlier version of this module did, filed and fixed as issue
#371) would silently overwrite the model's own `FETCH FIRST n` with the
default and drop its `OFFSET` clause in the same rewrite, changing what the
query returns without being asked to. The fix checks for *any* node in the
tree's `limit` slot before deciding there is nothing there, and only then
tries to extract its count for disclosure — a limit clause this module
cannot parse the count of is still left untouched, just disclosed with an
unknown value, which is the safe direction for "cannot tell" to fail in.
"""

from __future__ import annotations

from dataclasses import dataclass

import sqlglot
from sqlalchemy.ext.asyncio import AsyncSession
from sqlglot import exp

from askwell import audit
from askwell.audit import Store
from askwell.config import Settings
from askwell.connections import Engine
from askwell.logging import get_logger
from askwell.sql.validate import DIALECTS

log = get_logger(__name__)

# `Store.INTERACTIONS`, not `Store.DECISIONS`: a per-question fact, the same
# shape `askwell.sql.validate.SQL_QUERY` already records under Interactions
# per `docs/audit-log.md` §7 ("SQL generated ... rows returned, duration").
# An earlier version of this module wrote to Decisions instead — filed and
# fixed as issue #372, since Decisions is defined (`docs/audit-log.md` §2)
# as durable, kilobyte-scale, kept forever, which a row written on every
# limited question is not.
SQL_LIMIT_INJECTED = "sql_limit_injected"

# Attached, as a trailing SQL comment, to the `LIMIT` clause this module adds
# — never to one the model wrote. Every supported engine treats `/* ... */`
# as an ordinary comment, so this changes nothing about what executes.
INJECTED_LIMIT_COMMENT = "Added by Askwell"


@dataclass(frozen=True, slots=True)
class LimitResult:
    """What limit injection did to one already-validated read.

    `query` is the statement to execute and disclose — identical to the
    input when `injected` is `False`. `limit` is `None` when the statement
    has a top-level aggregate (truly caps nothing) or carries an existing
    limit clause this module cannot extract a count from; every other case
    carries a number, whether the model's own or the one just added.
    """

    query: str
    injected: bool
    limit: int | None


def _is_real_aggregate(node: exp.Expr) -> bool:
    """A plain aggregate collapses the row set down; the same function used
    as a window (`SUM(x) OVER (...)`) does not, so it is excluded here.
    """
    return isinstance(node, exp.AggFunc) and node.find_ancestor(exp.Window) is None


def _projection_has_aggregate(expr: exp.Expr) -> bool:
    """Whether `expr`, one entry of a `SELECT`'s own projection list,
    contains an aggregate at its own level. `prune` stops descent at a
    nested subquery, so an aggregate belonging to a *different*, inner
    `SELECT` is never mistaken for one at this level.
    """
    return any(
        _is_real_aggregate(node) for node in expr.walk(prune=lambda n: isinstance(n, exp.Subquery))
    )


def _has_top_level_aggregate(statement: exp.Expr) -> bool:
    if isinstance(statement, exp.Select):
        return any(_projection_has_aggregate(e) for e in statement.expressions)
    # `exp.SetOperation` (`UNION`/`INTERSECT`/`EXCEPT`): a combination of
    # reads is still a row set whose size depends on how many branches
    # contributed, never exempted regardless of what each branch computes.
    return False


def _limit_count(limit_node: exp.Expr) -> int | None:
    """The row count an existing `limit`-slot node carries, or `None` if
    this module cannot extract one — a `LIMIT n` (`exp.Limit`, count in
    `.expression`) or a SQL:2008 `FETCH FIRST/NEXT n ROWS ONLY`
    (`exp.Fetch`, count in `.args["count"]`) are the two shapes handled.
    """
    if isinstance(limit_node, exp.Fetch):
        value = limit_node.args.get("count")
    else:
        value = getattr(limit_node, "expression", None)
    return int(value.this) if isinstance(value, exp.Literal) and value.is_number else None


def _inject_limit_sync(settings: Settings, *, engine: Engine, query: str) -> LimitResult:
    """Pure and synchronous, mirroring `validate._validate_sync` — parsing
    an already-accepted query has no I/O, only CPU.
    """
    dialect = DIALECTS[engine]
    statement = sqlglot.parse_one(query, read=dialect)

    if _has_top_level_aggregate(statement):
        return LimitResult(query=query, injected=False, limit=None)

    # Any node already occupying the `limit` slot — `exp.Limit` or
    # `exp.Fetch` alike — means the model wrote its own cap; leave it and
    # the statement entirely untouched, whether or not its count is
    # extractable for disclosure.
    existing_node = statement.args.get("limit")
    if existing_node is not None:
        return LimitResult(query=query, injected=False, limit=_limit_count(existing_node))

    limit_value = settings.sql_row_limit
    limit_node = exp.Limit(expression=exp.Literal.number(limit_value))
    limit_node.comments = [INJECTED_LIMIT_COMMENT]
    statement.set("limit", limit_node)
    return LimitResult(query=statement.sql(dialect=dialect), injected=True, limit=limit_value)


async def inject_limit(
    session: AsyncSession, settings: Settings, *, engine: Engine, query: str
) -> LimitResult:
    """Inject a row limit into `query` where one is warranted, recording
    every injection to the interactions store (the ticket's own Audit
    Requirement — "recorded in the trace and the interaction record"; the
    trace half is not written here because `inject_limit` has no live
    `message_id` to attach one to until `POST /ask` wiring exists, the same
    "not wired to a live turn yet" state `validate.validate_query` is
    already honest about for its own `limit_injected` field). A query left
    alone (an aggregate, or already limited) is not recorded, the same
    "only the interesting outcome is recorded" rule `validate.validate_query`
    follows for rejections.
    """
    result = _inject_limit_sync(settings, engine=engine, query=query)
    if result.injected:
        await audit.record(
            session,
            Store.INTERACTIONS,
            SQL_LIMIT_INJECTED,
            {"engine": engine, "query": result.query, "limit": result.limit},
        )
        log.info("sql_limit_injected", engine=engine, limit=result.limit)
    return result


def result_was_truncated(row_count: int, limit: int | None) -> bool:
    """Whether a result with `row_count` rows may be showing fewer than
    exist, per `LimitResult.limit`. `>=`, not `==`: reaching the limit
    exactly is indistinguishable from a result that has more (the ticket's
    own edge case), and a caller should never see more rows than the limit
    it asked for in the first place.
    """
    return limit is not None and row_count >= limit
