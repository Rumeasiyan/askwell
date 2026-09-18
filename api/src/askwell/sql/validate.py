"""Parse model-generated SQL and reject anything that is not a single read.
`M4-SQL-VAL-104`.

C2: model-generated SQL is never trusted. Every candidate `askwell.
agent.sql_generate.generate_candidate_query` produces is text, nothing more,
until this module has looked at it — that module's own docstring makes the
same boundary from the other side. **Parsing is the gate, not a regex.**
`test_sql_validate.py::test_no_regex_based_filtering_exists` greps this
module's source for `re.compile`/`re.match`/`re.search`/`import re` and
fails if it finds one, so that claim stays checked rather than merely
asserted.

**What "single read" means here**: exactly one statement, parsed with
`sqlglot`, whose top level is a `SELECT` or a set operation over `SELECT`s
(`UNION`/`INTERSECT`/`EXCEPT` — still one read, composed) — matching the
ticket's "single SELECT or WITH only" in spirit: a CTE (`WITH ...`) is not a
distinct top-level node in this `sqlglot` version, it folds into the
`SELECT`'s own `with` clause, so a `WITH`-prefixed read already satisfies the
"top level is SELECT" check with no special case needed.

**Top-level type alone is not enough.** PostgreSQL allows a data-modifying
statement inside a CTE with `RETURNING` — `WITH d AS (DELETE FROM orders
RETURNING *) SELECT * FROM d` parses with `SELECT` at the top, but deletes
every row when run. This is the ticket's own "nesting to disguise a
modification" edge case, made concrete: trusting the top-level node type is
exactly the mistake a regex would also make, only with extra steps. Every
rejection here instead walks the *entire* parsed tree
(`Expression.find_all`) for a forbidden node — a CTE's own statement is a
descendant of the top-level `SELECT` node and is found the same way a
top-level `DELETE` would be. A comment hiding a second statement is not a
distinct case to code for: `sqlglot`'s tokenizer discards comments before
they ever become part of the parsed tree, so `SELECT 1 -- ; DROP TABLE x`
was already one `SELECT` statement, never two, before this module runs at
all.

**Function side effects are only partly detectable, and this is the honest
limit, not a covered case.** `_SIDE_EFFECT_FUNCTIONS` below rejects the
named functions `sqlglot` cannot otherwise classify as a write
(`pg_terminate_backend`, `xp_cmdshell`, `LOAD_FILE`, and similar) because
they read as an ordinary function call syntactically — nothing in the parsed
tree distinguishes a side-effecting function from a pure one in general.
This list is necessarily incomplete: a currently-unknown function, a
same-named function in an engine not in this list, or a side effect reached
through a mechanism `sqlglot` does not surface as a function call at all,
passes through unflagged. The read-only database role
(`askwell.sql_execute`'s own layer 1) is what actually stops any of these at
the database, independently of whether this module named it — this module's
job is to reject what it *can* recognise, not to be the only thing standing
between a generated query and the database.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from enum import StrEnum

import sqlglot
from sqlalchemy.ext.asyncio import AsyncSession
from sqlglot import exp

from askwell import audit
from askwell.audit import Store
from askwell.config import Settings
from askwell.connections import Engine
from askwell.logging import get_logger

log = get_logger(__name__)

# `M4-SQL-OBS-108`: every validated query — accepted or rejected — is one
# `audit_interactions` record, per `docs/audit-log.md` §7 ("SQL generated and
# whether it was accepted or rejected by validation, rows returned,
# duration" is named there as an Interactions fact, not a Decisions one).
# `M4-SQL-VAL-104` originally wrote a rejection to `audit_decisions`; this
# corrects that (`docs/decisions.md`, this date) rather than leaving a second,
# wrongly-homed audit trail for the same event.
SQL_QUERY = "sql_query"

# `sqlglot`'s dialect names, one per `Engine` this codebase supports
# (`askwell.connections.ENGINES`). MariaDB has no dialect of its own in
# `sqlglot` — its SQL is close enough to MySQL's that `sqlglot` documents
# reading MariaDB input with the `mysql` dialect, which is what
# `askwell.sql_execute._execute_mysql_blocking` already treats the two as
# for connection purposes.
_DIALECTS: dict[Engine, str] = {
    "postgresql": "postgres",
    "mysql": "mysql",
    "mariadb": "mysql",
    "sqlserver": "tsql",
}

# A read's top level must be one of these. `exp.Select` covers a bare
# `SELECT` and a `WITH`-prefixed one alike (the CTE clause lives in
# `Select.args["with"]`, not as a separate top-level node in this `sqlglot`
# version). `exp.SetOperation` covers `UNION`/`INTERSECT`/`EXCEPT` — a
# combination of reads, still a single statement, still nothing but a read.
_READ_TYPES: tuple[type[exp.Expression], ...] = (exp.Select, exp.SetOperation)

# Present anywhere in the parsed tree, this rejects the statement outright —
# not just at the top level, so a data-modifying CTE (see module docstring)
# is caught the same way a top-level modification is.
_WRITE_NODE_TYPES: tuple[type[exp.Expression], ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.TruncateTable,
    exp.Merge,
    exp.Grant,
    exp.Revoke,
    exp.Copy,
    exp.Set,
    exp.Pragma,
    # `sqlglot`'s catch-all for anything it could only partly parse, or
    # recognised but does not model as a query at all — `EXPLAIN`, `SHOW`,
    # `CALL`, and any dialect-specific statement shape it does not know.
    # Never a read this module can vouch for; see the module docstring on
    # "dialect-specific construct the parser does not recognise."
    exp.Command,
)

# `SELECT ... INTO new_table` (PostgreSQL) creates a table — a `SELECT`
# syntactically, a write in effect. Its own node type, `exp.Into`, appears
# on the `Select` that carries it regardless of where in the tree it sits.
_WRITE_MARKER_TYPES: tuple[type[exp.Expression], ...] = (exp.Into,)

# Function calls `sqlglot` parses as ordinary function calls but that read,
# execute, or write outside the row set they return. Lowercased; matched
# against `exp.Anonymous.this`, which is how `sqlglot` represents a function
# name it has no dedicated node for. See the module docstring's own
# admission that this list is necessarily incomplete.
_SIDE_EFFECT_FUNCTIONS: frozenset[str] = frozenset(
    {
        # PostgreSQL: session/cluster control, sequence mutation, file and
        # network I/O.
        "pg_terminate_backend",
        "pg_cancel_backend",
        "pg_reload_conf",
        "pg_rotate_logfile",
        "setval",
        "nextval",
        "lo_import",
        "lo_export",
        "lo_create",
        "lo_unlink",
        "dblink_exec",
        "dblink_connect",
        "pg_read_file",
        "pg_read_binary_file",
        "pg_ls_dir",
        "pg_advisory_lock",
        "pg_advisory_xact_lock",
        # MySQL/MariaDB: file I/O and OS command execution via a UDF.
        "load_file",
        "sys_exec",
        "sys_eval",
        # SQL Server: OS command execution.
        "xp_cmdshell",
    }
)


class RejectionReason(StrEnum):
    """Why a candidate query did not pass. One of these accompanies every
    refusal recorded to the interaction log (`M4-SQL-OBS-108`'s own Audit
    Requirement) — the signal that a prompt change has degraded generation
    is invisible unless the reason, not just the fact of rejection, is kept.
    """

    EMPTY = "empty"
    UNPARSEABLE = "unparseable"
    TIMEOUT = "timeout"
    MULTIPLE_STATEMENTS = "multiple_statements"
    NOT_A_SINGLE_READ = "not_a_single_read"
    WRITE_DETECTED = "write_detected"
    LOCKING_READ = "locking_read"
    SIDE_EFFECT_FUNCTION = "side_effect_function"


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """What validating one candidate query produced.

    `reason`/`detail` are `None` only when `accepted` is `True` — a caller
    renders `detail` verbatim as the rejection's recorded reason and, per
    `docs/states-and-edge-cases.md` §4, alongside the query itself, since
    disclosure of the SQL is unconditional regardless of why it was
    refused.
    """

    accepted: bool
    reason: RejectionReason | None
    detail: str | None


def _accept() -> ValidationResult:
    return ValidationResult(accepted=True, reason=None, detail=None)


def _reject(reason: RejectionReason, detail: str) -> ValidationResult:
    return ValidationResult(accepted=False, reason=reason, detail=detail)


def _check_parsed(engine: Engine, statements: list[exp.Expr | None]) -> ValidationResult:
    present = [statement for statement in statements if statement is not None]
    if len(present) != 1:
        return _reject(
            RejectionReason.MULTIPLE_STATEMENTS,
            f"Expected exactly one statement, found {len(present)}.",
        )
    statement = present[0]

    if not isinstance(statement, _READ_TYPES):
        return _reject(
            RejectionReason.NOT_A_SINGLE_READ,
            f"The statement is a {type(statement).__name__}, not a SELECT or WITH read.",
        )

    write_node = next(statement.find_all(*_WRITE_NODE_TYPES), None)
    if write_node is not None:
        return _reject(
            RejectionReason.WRITE_DETECTED,
            f"Found a {type(write_node).__name__} inside the statement — "
            "possibly nested in a CTE or subquery.",
        )

    write_marker = next(statement.find_all(*_WRITE_MARKER_TYPES), None)
    if write_marker is not None:
        return _reject(
            RejectionReason.WRITE_DETECTED,
            "The statement writes its result to a table (SELECT ... INTO), "
            "rather than only reading.",
        )

    if next(statement.find_all(exp.Lock), None) is not None:
        return _reject(
            RejectionReason.LOCKING_READ,
            "The statement takes a row lock (FOR UPDATE/FOR SHARE), which is not a plain read.",
        )

    for anonymous in statement.find_all(exp.Anonymous):
        name = str(anonymous.this).lower()
        if name in _SIDE_EFFECT_FUNCTIONS:
            return _reject(
                RejectionReason.SIDE_EFFECT_FUNCTION,
                f"Calls {name}(), which has effects beyond returning rows.",
            )

    return _accept()


def _validate_sync(engine: Engine, query: str) -> ValidationResult:
    """Pure and synchronous — parsing has no I/O, only CPU. `validate_query`
    below is what bounds and records; this is what a test exercises directly
    with no event loop or database needed.
    """
    stripped = query.strip()
    if not stripped:
        return _reject(RejectionReason.EMPTY, "The generated query was empty.")

    dialect = _DIALECTS[engine]
    try:
        statements = sqlglot.parse(stripped, read=dialect)
    except sqlglot.errors.SqlglotError as error:
        return _reject(
            RejectionReason.UNPARSEABLE,
            f"sqlglot could not parse this as {engine} SQL: {error}",
        )

    return _check_parsed(engine, statements)


async def validate_query(
    session: AsyncSession,
    settings: Settings,
    *,
    engine: Engine,
    query: str,
    source_id: uuid.UUID | None = None,
) -> ValidationResult:
    """Validate one candidate query and record the outcome. `M4-SQL-OBS-108`.

    Parsing runs in a worker thread with a bounded wait
    (`Settings.sql_validation_timeout_seconds`) — `sqlglot` has no timeout of
    its own, so a pathological input is bounded here rather than left to run
    unbounded on the event loop (the ticket's own "very long generated
    statement" edge case). `asyncio.wait_for` gives up *waiting* on timeout;
    the worker thread itself is not killed, the same residual
    `concurrent.futures`-based timeouts always carry — real SQL parses in
    well under a millisecond per column, so a genuine hang here would itself
    be the signal something is wrong with the input, not a routine
    occurrence this module needs to clean up after.

    Every outcome — accepted or rejected — is one `audit_interactions`
    record (`docs/audit-log.md` §7), carrying the query text in full (never
    truncated — truncating the thing a maintainer is trying to diagnose
    defeats the purpose), the engine, the source, whether it validated, and
    the rejection reason where there is one. `limit_injected`, `rows` and
    `duration_ms` are always `None` here: limit injection (`M4-SQL-VAL-105`)
    and execution (`askwell.sql_execute`) are not wired to a live turn yet
    (`docs/BRAIN.md`), so this module honestly records what it knows at this
    stage rather than inventing values for stages that have not run — the
    same "recorded as far as it got" edge case the ticket names for a query
    rejected before generation completed.
    """
    timeout_seconds = float(settings.sql_validation_timeout_seconds)
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(_validate_sync, engine, query), timeout=timeout_seconds
        )
    except TimeoutError:
        result = _reject(
            RejectionReason.TIMEOUT,
            "Parsing this statement took too long and was abandoned.",
        )

    await audit.record(
        session,
        Store.INTERACTIONS,
        SQL_QUERY,
        {
            "engine": engine,
            "source_id": str(source_id) if source_id is not None else None,
            "query": query,
            "validated": result.accepted,
            "rejection_reason": result.reason.value if result.reason is not None else None,
            "detail": result.detail,
            "limit_injected": None,
            "rows": None,
            "duration_ms": None,
        },
    )
    if not result.accepted:
        assert result.reason is not None
        log.warning("sql_rejected", engine=engine, reason=result.reason.value)

    return result
