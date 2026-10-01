"""Which rows of which table a validated read returned. `M11-FIX-BE-231`.

A SQL answer from a workbook's sheet cites the sheet's own rows (C4), and a
result row carries only what the query projected: `SELECT headcount ...`
returns `19`, not which department it was. `plan_provenance` rewrites a
read whose result rows are rows of one table — one table, no join, no
aggregate, no `DISTINCT`, no window — into one that also projects that
table's whole row after the original columns, and drops `ORDER BY`, `LIMIT`
and `OFFSET`. The caller runs it like any other query and pairs each
returned row with every table row the filter admits that has the same
projected values. Dropping the cap is the point: a row `LIMIT` cut is the
one a re-run could have returned instead, and only by seeing every row with
those values can the caller tell one row from a tie (#896).

**The rewrite happens on the parsed tree, never on the text**, for the
reason `askwell.sql.limit` gives for its own. And it is not a check: the
rewritten query goes through `askwell.sql.validate.validate_query` before it
runs, as every query does (C2). Anything this module cannot parse, or any
shape it does not recognise, has no plan, and the caller cites the sheet.
"""

from __future__ import annotations

from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from askwell.connections import Engine
from askwell.sql.validate import DIALECTS

# Any of these on the statement means its rows are not one table's rows, or
# not all of them: grouped, de-duplicated, joined, or computed over a window.
_NOT_ONE_TABLES_ROWS = (
    "with_",
    "with",
    "joins",
    "laterals",
    "group",
    "having",
    "qualify",
    "distinct",
)


@dataclass(frozen=True, slots=True)
class ProvenancePlan:
    """`query` returns the original's own columns, as many as its result
    had (a `*` among them counts as however many it expanded to), then every
    column of `table`, for every row the original's filter admits."""

    query: str
    table: str


def _parse(engine: Engine, query: str) -> exp.Expr | None:
    try:
        return sqlglot.parse_one(query, read=DIALECTS[engine])
    except SqlglotError:
        return None


def plan_provenance(engine: Engine, query: str) -> ProvenancePlan | None:
    """The provenance read for `query`, or `None` when its rows are not rows
    of one table. `query` is one `validate_query` already accepted."""
    statement = _parse(engine, query)
    if not isinstance(statement, exp.Select):
        return None
    if any(statement.args.get(key) for key in _NOT_ONE_TABLES_ROWS):
        return None
    source = statement.args.get("from_") or statement.args.get("from")
    if not isinstance(source, exp.From) or not isinstance(source.this, exp.Table):
        return None
    table = source.this
    # Any aggregate or window in the projection, at any depth: a subquery's
    # own aggregate is excluded by `askwell.sql.limit`'s exemption rule, but
    # here a miss would pair a computed value with a row, so this is stricter.
    if any(e.find(exp.AggFunc, exp.Window) for e in statement.expressions):
        return None

    rewritten = statement.copy()
    for key in ("order", "limit", "offset"):
        rewritten.set(key, None)
    rewritten.append(
        "expressions", exp.Column(this=exp.Star(), table=exp.to_identifier(table.alias_or_name))
    )
    return ProvenancePlan(
        query=rewritten.sql(dialect=DIALECTS[engine]),
        table=table.name,
    )


def referenced_tables(engine: Engine, query: str) -> list[str]:
    """Every table `query` reads, sorted, without the names its own `WITH`
    clauses define. Empty when it cannot be parsed."""
    statement = _parse(engine, query)
    if statement is None:
        return []
    ctes = {cte.alias_or_name for cte in statement.find_all(exp.CTE)}
    return sorted({table.name for table in statement.find_all(exp.Table) if table.name} - ctes)
