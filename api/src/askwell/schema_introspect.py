"""Full schema introspection: types, keys, relationships. `M4-SCHEMA-ING-100`.

`connections.py` and `dump_import.py` each already produce a bare table-name
list — enough to mark a source `ready` and say something concrete about what
was found, but not enough to answer a question about it. This module is the
second pass both of those modules' own docstrings named as future work: for
a live connection or a loaded sandbox database alike, it reads every table
and view's columns, types, primary keys and foreign keys, and turns that
into `schema_notes` rows the existing lexical retrieval
(`askwell.memory.retrieve_relevant_facts`) already ranks by relevance to a
question — no new retrieval path, since one already exists and is already
bounded (`RELEVANT_NOTE_LIMIT`, `docs/memory-and-clarification.md`).

**Read-only, structurally.** `docs/data-sources.md` §4's own validation
rule: introspection runs as the role a query would run as, never a role
with more reach, so it can never see more than a query could. For a live
connection that is simply the credential the write-permission probe
(`M4-CONN-SEC-097`) already verified is read-only. For a sandbox database
the owner role that loaded a dump or a table owns everything in it and is
not read-only by any reading of that word — introspection there runs as
`askwell_sandbox_readonly` instead (`askwell.sandbox.readonly_url`), the
same role the query path uses once a source is `ready`.

**Bulk queries, not one round trip per table.** The ticket's own edge case
— "a schema with thousands of tables" — is about retrieval being bounded,
which is already true, but a naive introspection that queried each table's
columns separately would make *this* step the slow one instead. Every
engine below fetches columns, primary keys and foreign keys for the whole
schema in one query apiece and groups them in Python.

**Invisible objects are only detectable for PostgreSQL.** A role can be
denied `SELECT` on a table without losing the ability to see the schema at
all — `pg_catalog.pg_class` lists every table and view in a schema
regardless of privilege, so the read role's `has_table_privilege` on each
row is what distinguishes "this exists but you can't read it" from "this
does not exist". MySQL and SQL Server expose no privilege-independent
catalog a restricted role can read, so `omitted_count` is `None` (not
"zero") for those two engines — a real gap, not silently worked around,
filed as its own issue rather than guessed at here.
"""

import asyncio
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from askwell import audit
from askwell.audit import Store
from askwell.logging import get_logger
from askwell.memory import get_active_schema_notes, write_schema_note

if TYPE_CHECKING:
    from askwell.config import Settings

log = get_logger(__name__)

TableKind = Literal["table", "view", "materialized_view"]

# Decisions record (AGENTS.md §8, `docs/audit-log.md` §2): "introspection
# runs are logged" is this ticket's own Audit / Logging Requirement.
SCHEMA_INTROSPECTED = "schema_introspected"

# Local-only (C1) — never transmitted. This ticket's own Analytics Events
# line asks only for the counter to exist, mirroring
# `connections.WRITE_PROBE_REFUSED_COUNTER_KEY`.
SCHEMA_INTROSPECTION_RUN_COUNTER_KEY = "askwell:schema_introspect:runs"


@dataclass(frozen=True, slots=True)
class ForeignKey:
    column: str
    references_table: str
    references_column: str


@dataclass(frozen=True, slots=True)
class Column:
    name: str
    data_type: str
    nullable: bool
    primary_key: bool


@dataclass(frozen=True, slots=True)
class Table:
    name: str
    kind: TableKind
    columns: tuple[Column, ...]
    foreign_keys: tuple[ForeignKey, ...]


@dataclass(frozen=True, slots=True)
class SchemaInventory:
    """What one introspection run found.

    `omitted_count` is `None` when the engine gives no way to tell an
    invisible object from one that does not exist, and an integer — zero or
    more — when it does. Never conflate the two: `docs/data-sources.md`'s
    own edge case is "omitted, with a note that some objects were not
    visible", which requires actually knowing the count.
    """

    tables: tuple[Table, ...]
    omitted_count: int | None


_KIND_LABEL: dict[TableKind, str] = {
    "table": "Table",
    "view": "View",
    "materialized_view": "Materialised view",
}


def describe_table(table: Table) -> str:
    """The table-level `schema_notes.description` — kind, columns, keys and
    relationships in one plain-language line, the shape
    `docs/data-sources.md` §5's own `st_cd` example asks for at table grain.
    """
    label = _KIND_LABEL[table.kind]
    if not table.columns:
        return f"{label} {table.name}, with no columns Askwell can see."

    column_names = ", ".join(column.name for column in table.columns)
    parts = [f"{label} {table.name}. Columns: {column_names}."]

    primary_key = [column.name for column in table.columns if column.primary_key]
    if primary_key:
        parts.append(f"Primary key: {', '.join(primary_key)}.")

    if table.foreign_keys:
        relationships = ", ".join(
            f"{fk.column} -> {fk.references_table}.{fk.references_column}"
            for fk in table.foreign_keys
        )
        parts.append(f"Foreign keys: {relationships}.")

    return " ".join(parts)


def describe_column(table_name: str, column: Column, foreign_keys: tuple[ForeignKey, ...]) -> str:
    """The column-level `schema_notes.description` — `docs/data-sources.md`
    §5: "`st_cd` is unguessable; `st_cd — student status code...` is
    trivial." This is the unguessable half; a human explanation is what the
    clarification loop adds later (`M4-SCHEMA-ING-101`, out of this
    ticket's scope) when the type alone still leaves the meaning open.
    """
    bits = [column.data_type]
    if column.primary_key:
        bits.append("primary key")
    if not column.nullable:
        bits.append("not null")
    for fk in foreign_keys:
        if fk.column == column.name:
            bits.append(f"references {fk.references_table}.{fk.references_column}")
    return f"{table_name}.{column.name} — {', '.join(bits)}."


def _build_postgresql_inventory(
    class_rows: list[tuple[str, str, str, bool]],
    column_rows: list[tuple[str, str, str, str, bool]],
    pk_rows: list[tuple[str, str, str]],
    fk_rows: list[tuple[str, str, str, str, str]],
) -> SchemaInventory:
    """Group raw catalog rows into a `SchemaInventory`. Pure — no connection
    involved — so it is tested directly with fabricated rows, the same
    pattern `connections._find_mysql_write_grant` uses for MySQL's own
    privilege parsing.

    `class_rows`: (schema, name, relkind, selectable) from `pg_class` joined
    to `has_table_privilege` — every table/view/matview in the target
    schemas, whether or not the introspecting role can read it, which is
    what makes the omitted count possible at all for this engine.
    `column_rows`: (schema, table, column, data_type, nullable).
    `pk_rows`: (schema, table, column).
    `fk_rows`: (schema, table, column, references_table, references_column).
    """
    relkind_to_kind: dict[str, TableKind] = {"r": "table", "v": "view", "m": "materialized_view"}
    visible = {
        (schema, name): relkind_to_kind[relkind]
        for schema, name, relkind, selectable in class_rows
        if selectable and relkind in relkind_to_kind
    }
    omitted_count = sum(
        1
        for _, _, relkind, selectable in class_rows
        if not selectable and relkind in relkind_to_kind
    )

    columns_by_table: dict[tuple[str, str], list[Column]] = {}
    primary_keys: dict[tuple[str, str], set[str]] = {}
    for schema, table, column in pk_rows:
        primary_keys.setdefault((schema, table), set()).add(column)

    for schema, table, column, data_type, nullable in column_rows:
        key = (schema, table)
        if key not in visible:
            continue
        columns_by_table.setdefault(key, []).append(
            Column(
                name=column,
                data_type=data_type,
                nullable=nullable,
                primary_key=column in primary_keys.get(key, set()),
            )
        )

    foreign_keys_by_table: dict[tuple[str, str], list[ForeignKey]] = {}
    for schema, table, column, references_table, references_column in fk_rows:
        key = (schema, table)
        if key not in visible:
            continue
        foreign_keys_by_table.setdefault(key, []).append(
            ForeignKey(
                column=column,
                references_table=references_table,
                references_column=references_column,
            )
        )

    tables = tuple(
        Table(
            name=name,
            kind=kind,
            columns=tuple(columns_by_table.get((schema, name), [])),
            foreign_keys=tuple(foreign_keys_by_table.get((schema, name), [])),
        )
        for (schema, name), kind in sorted(visible.items())
    )
    return SchemaInventory(tables=tables, omitted_count=omitted_count)


def _introspect_postgresql_blocking(dsn: str) -> SchemaInventory:
    """Introspect a PostgreSQL database — a live connection using
    `postgresql` as its engine, or a sandbox database via the readonly
    role's own DSN. Every query is bulk (whole schema, not per-table) — see
    the module docstring.
    """
    import psycopg

    with psycopg.connect(dsn, autocommit=True) as conn:
        class_rows = conn.execute(
            "SELECT n.nspname, c.relname, c.relkind, "
            "has_table_privilege(c.oid, 'SELECT') "
            "FROM pg_catalog.pg_class c "
            "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname NOT IN ('pg_catalog', 'information_schema') "
            "AND c.relkind IN ('r', 'v', 'm') "
            "ORDER BY n.nspname, c.relname"
        ).fetchall()
        column_rows = conn.execute(
            "SELECT table_schema, table_name, column_name, data_type, "
            "(is_nullable = 'YES') FROM information_schema.columns "
            "WHERE table_schema NOT IN ('pg_catalog', 'information_schema') "
            "ORDER BY table_schema, table_name, ordinal_position"
        ).fetchall()
        # `pg_index`/`pg_constraint`, not `information_schema.table_constraints`
        # — verified against a real sandbox instance rather than assumed
        # (AGENTS.md §4): `information_schema`'s own constraint views require
        # more than the `SELECT` `has_table_privilege` already confirmed
        # (`class_rows` above) before they will name a table's primary key or
        # foreign keys at all, which silently produced an empty result for
        # `askwell_sandbox_readonly` even though it could read the table's
        # data. `pg_catalog` carries no such extra gate.
        pk_rows = conn.execute(
            "SELECT n.nspname, c.relname, a.attname "
            "FROM pg_index i "
            "JOIN pg_class c ON c.oid = i.indrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = ANY(i.indkey) "
            "WHERE i.indisprimary "
            "AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')"
        ).fetchall()
        fk_rows = conn.execute(
            "SELECT n.nspname, c.relname, a.attname, fn.nspname, fc.relname, fa.attname "
            "FROM pg_constraint con "
            "JOIN pg_class c ON c.oid = con.conrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "JOIN pg_class fc ON fc.oid = con.confrelid "
            "JOIN pg_namespace fn ON fn.oid = fc.relnamespace "
            "JOIN LATERAL unnest(con.conkey, con.confkey) AS cols(attnum, fattnum) ON true "
            "JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = cols.attnum "
            "JOIN pg_attribute fa ON fa.attrelid = con.confrelid AND fa.attnum = cols.fattnum "
            "WHERE con.contype = 'f' "
            "AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')"
        ).fetchall()

    return _build_postgresql_inventory(
        [(str(r[0]), str(r[1]), str(r[2]), bool(r[3])) for r in class_rows],
        [(str(r[0]), str(r[1]), str(r[2]), str(r[3]), bool(r[4])) for r in column_rows],
        [(str(r[0]), str(r[1]), str(r[2])) for r in pk_rows],
        # (schema, table, column, references_table, references_column) — the
        # referenced schema (`r[3]`) is dropped; nothing downstream needs it
        # and `docs/data-sources.md` §5's own description text names only
        # the table.
        [(str(r[0]), str(r[1]), str(r[2]), str(r[4]), str(r[5])) for r in fk_rows],
    )


def _build_mysql_inventory(
    table_rows: list[tuple[str, str]],
    column_rows: list[tuple[str, str, str, bool]],
    pk_rows: list[tuple[str, str]],
    fk_rows: list[tuple[str, str, str, str]],
) -> SchemaInventory:
    """`table_rows`: (name, table_type). `column_rows`: (table, column,
    data_type, nullable). `pk_rows`: (table, column). `fk_rows`: (table,
    column, references_table, references_column). No omitted-object count —
    see the module docstring.
    """
    kind_for: dict[str, TableKind] = {
        name: ("view" if table_type.upper() == "VIEW" else "table")
        for name, table_type in table_rows
    }
    columns_by_table: dict[str, list[Column]] = {}
    primary_keys: dict[str, set[str]] = {}
    for table, column in pk_rows:
        primary_keys.setdefault(table, set()).add(column)
    for table, column, data_type, nullable in column_rows:
        if table not in kind_for:
            continue
        columns_by_table.setdefault(table, []).append(
            Column(
                name=column,
                data_type=data_type,
                nullable=nullable,
                primary_key=column in primary_keys.get(table, set()),
            )
        )
    foreign_keys_by_table: dict[str, list[ForeignKey]] = {}
    for table, column, references_table, references_column in fk_rows:
        if table not in kind_for:
            continue
        foreign_keys_by_table.setdefault(table, []).append(
            ForeignKey(
                column=column,
                references_table=references_table,
                references_column=references_column,
            )
        )
    tables = tuple(
        Table(
            name=name,
            kind=kind,
            columns=tuple(columns_by_table.get(name, [])),
            foreign_keys=tuple(foreign_keys_by_table.get(name, [])),
        )
        for name, kind in sorted(kind_for.items())
    )
    return SchemaInventory(tables=tables, omitted_count=None)


def _introspect_mysql_blocking(
    host: str, port: int, database: str, user: str, password: str
) -> SchemaInventory:
    """MySQL/MariaDB has no materialized views and no privilege-independent
    catalog — see the module docstring for both gaps."""
    import pymysql

    conn = pymysql.connect(host=host, port=port, database=database, user=user, password=password)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT table_name, table_type FROM information_schema.tables "
                "WHERE table_schema = %s",
                (database,),
            )
            table_rows = [(str(r[0]), str(r[1])) for r in cur.fetchall()]
            cur.execute(
                "SELECT table_name, column_name, data_type, (is_nullable = 'YES') "
                "FROM information_schema.columns WHERE table_schema = %s "
                "ORDER BY table_name, ordinal_position",
                (database,),
            )
            column_rows = [(str(r[0]), str(r[1]), str(r[2]), bool(r[3])) for r in cur.fetchall()]
            cur.execute(
                "SELECT table_name, column_name FROM information_schema.key_column_usage "
                "WHERE table_schema = %s AND constraint_name = 'PRIMARY'",
                (database,),
            )
            pk_rows = [(str(r[0]), str(r[1])) for r in cur.fetchall()]
            cur.execute(
                "SELECT table_name, column_name, referenced_table_name, referenced_column_name "
                "FROM information_schema.key_column_usage "
                "WHERE table_schema = %s AND referenced_table_name IS NOT NULL",
                (database,),
            )
            fk_rows = [(str(r[0]), str(r[1]), str(r[2]), str(r[3])) for r in cur.fetchall()]
    finally:
        conn.close()
    return _build_mysql_inventory(table_rows, column_rows, pk_rows, fk_rows)


def _build_sqlserver_inventory(
    object_rows: list[tuple[str, str]],
    column_rows: list[tuple[str, str, str, bool]],
    pk_rows: list[tuple[str, str]],
    fk_rows: list[tuple[str, str, str, str]],
) -> SchemaInventory:
    """`object_rows`: (name, type_desc) where `type_desc` is `USER_TABLE` or
    `VIEW`, from `sys.objects`. Same shapes and same no-omitted-count gap as
    MySQL otherwise."""
    kind_for: dict[str, TableKind] = {
        name: ("view" if type_desc == "VIEW" else "table") for name, type_desc in object_rows
    }
    columns_by_table: dict[str, list[Column]] = {}
    primary_keys: dict[str, set[str]] = {}
    for table, column in pk_rows:
        primary_keys.setdefault(table, set()).add(column)
    for table, column, data_type, nullable in column_rows:
        if table not in kind_for:
            continue
        columns_by_table.setdefault(table, []).append(
            Column(
                name=column,
                data_type=data_type,
                nullable=nullable,
                primary_key=column in primary_keys.get(table, set()),
            )
        )
    foreign_keys_by_table: dict[str, list[ForeignKey]] = {}
    for table, column, references_table, references_column in fk_rows:
        if table not in kind_for:
            continue
        foreign_keys_by_table.setdefault(table, []).append(
            ForeignKey(
                column=column,
                references_table=references_table,
                references_column=references_column,
            )
        )
    tables = tuple(
        Table(
            name=name,
            kind=kind,
            columns=tuple(columns_by_table.get(name, [])),
            foreign_keys=tuple(foreign_keys_by_table.get(name, [])),
        )
        for name, kind in sorted(kind_for.items())
    )
    return SchemaInventory(tables=tables, omitted_count=None)


def _introspect_sqlserver_blocking(
    host: str, port: int, database: str, user: str, password: str
) -> SchemaInventory:
    """SQL Server has no materialized views either — indexed views are the
    closest analogue and are not distinguished here."""
    import pytds

    conn = pytds.connect(server=host, port=port, database=database, user=user, password=password)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT o.name, o.type_desc FROM sys.objects o WHERE o.type IN ('U', 'V')")
            object_rows = [(str(r[0]), str(r[1])) for r in cur.fetchall()]
            cur.execute(
                "SELECT o.name, c.name, ty.name, c.is_nullable "
                "FROM sys.columns c "
                "JOIN sys.objects o ON o.object_id = c.object_id "
                "JOIN sys.types ty ON ty.user_type_id = c.user_type_id "
                "WHERE o.type IN ('U', 'V')"
            )
            column_rows = [(str(r[0]), str(r[1]), str(r[2]), bool(r[3])) for r in cur.fetchall()]
            cur.execute(
                "SELECT t.name, c.name "
                "FROM sys.key_constraints kc "
                "JOIN sys.tables t ON t.object_id = kc.parent_object_id "
                "JOIN sys.index_columns ic "
                "ON ic.object_id = kc.parent_object_id AND ic.index_id = kc.unique_index_id "
                "JOIN sys.columns c ON c.object_id = ic.object_id AND c.column_id = ic.column_id "
                "WHERE kc.type = 'PK'"
            )
            pk_rows = [(str(r[0]), str(r[1])) for r in cur.fetchall()]
            cur.execute(
                "SELECT t.name, c.name, rt.name, rc.name "
                "FROM sys.foreign_key_columns fkc "
                "JOIN sys.tables t ON t.object_id = fkc.parent_object_id "
                "JOIN sys.columns c "
                "ON c.object_id = fkc.parent_object_id AND c.column_id = fkc.parent_column_id "
                "JOIN sys.tables rt ON rt.object_id = fkc.referenced_object_id "
                "JOIN sys.columns rc ON rc.object_id = fkc.referenced_object_id "
                "AND rc.column_id = fkc.referenced_column_id"
            )
            fk_rows = [(str(r[0]), str(r[1]), str(r[2]), str(r[3])) for r in cur.fetchall()]
    finally:
        conn.close()
    return _build_sqlserver_inventory(object_rows, column_rows, pk_rows, fk_rows)


def introspect_blocking(engine: str, dsn_or_host: str, **kwargs: object) -> SchemaInventory:
    """Dispatch by engine, mirroring `connections.probe_connection`'s own
    dispatch. Not used by `_introspect_postgresql_blocking` callers, which
    already know their engine — this exists for callers (the worker jobs)
    that only have the stored `engine` string to go on.
    """
    if engine == "postgresql":
        return _introspect_postgresql_blocking(dsn_or_host)
    if engine in ("mysql", "mariadb"):
        return _introspect_mysql_blocking(
            dsn_or_host,
            int(kwargs["port"]),  # type: ignore[call-overload]
            str(kwargs["database"]),
            str(kwargs["user"]),
            str(kwargs["password"]),
        )
    if engine == "sqlserver":
        return _introspect_sqlserver_blocking(
            dsn_or_host,
            int(kwargs["port"]),  # type: ignore[call-overload]
            str(kwargs["database"]),
            str(kwargs["user"]),
            str(kwargs["password"]),
        )
    raise ValueError(f"No schema introspection for engine {engine!r}.")


async def write_schema_inventory(
    session: AsyncSession, source_id: uuid.UUID, inventory: SchemaInventory
) -> None:
    """Write or update every table and column note for one source, and
    record the run. `docs/data-sources.md` §5: user-supplied notes always
    outrank inferred ones — `write_schema_note` already enforces that for
    each individual write.

    **Re-introspection updates rather than duplicates.** An inferred note
    already active at a position, with the identical description this run
    would write, is left untouched — no churn on every re-introspect of an
    unchanged schema. One with a *different* description (a column's type
    changed, a table gained a foreign key) is superseded first, directly,
    without going through `askwell.memory.delete_schema_note`'s reapply-job
    path — that path exists for a person correcting something Askwell said,
    not for this module's own bookkeeping replacing a stale guess with a
    fresher one, and queuing a re-processing job for every unchanged-meaning
    schema refresh would be wasted work with no answer to re-check.

    A table or column this run no longer finds — dropped, or newly
    invisible to the introspecting role — has its own active inferred note
    (if any) superseded by itself, which is how this module marks a note
    inactive without a replacement row. A user-supplied note for a position
    that disappeared is left alone: nothing here deletes what a person said.
    """
    target: dict[tuple[str, str | None], str] = {}
    for table in inventory.tables:
        target[(table.name, None)] = describe_table(table)
        for column in table.columns:
            target[(table.name, column.name)] = describe_column(
                table.name, column, table.foreign_keys
            )

    active = await get_active_schema_notes(session, source_id=source_id)
    active_by_position = {(note.table_name, note.column_name): note for note in active}

    for (table_name, column_name), description in target.items():
        existing = active_by_position.get((table_name, column_name))
        if existing is None:
            await write_schema_note(
                session,
                source_id=source_id,
                table_name=table_name,
                column_name=column_name,
                description=description,
                origin="inferred",
            )
            continue
        if existing.origin != "inferred":
            continue  # user-supplied always outranks an inferred refresh.
        if existing.description == description:
            continue  # unchanged — nothing to update, nothing to churn.
        new_note_id = await write_schema_note(
            session,
            source_id=source_id,
            table_name=table_name,
            column_name=column_name,
            description=description,
            origin="inferred",
        )
        # Points forward to the row that actually replaced it — not a
        # self-supersede, which is reserved below for a position with no
        # replacement at all. `existing.origin == "inferred"` was already
        # confirmed above, so `write_schema_note` never discards this write
        # and `new_note_id` is never `None` here.
        await session.execute(
            text("UPDATE schema_notes SET superseded_by = :new_id WHERE id = :old_id"),
            {"new_id": new_note_id, "old_id": existing.id},
        )

    for (table_name, column_name), note in active_by_position.items():
        if note.origin != "inferred":
            continue
        if (table_name, column_name) in target:
            continue
        await session.execute(
            text("UPDATE schema_notes SET superseded_by = id WHERE id = :id"),
            {"id": note.id},
        )

    await audit.record(
        session,
        Store.DECISIONS,
        SCHEMA_INTROSPECTED,
        {
            "source_id": str(source_id),
            "tables": len(inventory.tables),
            "columns": sum(len(table.columns) for table in inventory.tables),
            "foreign_keys": sum(len(table.foreign_keys) for table in inventory.tables),
            "omitted_count": inventory.omitted_count,
        },
    )
    log.info(
        "schema_introspected",
        source_id=str(source_id),
        tables=len(inventory.tables),
        omitted_count=inventory.omitted_count,
    )


async def record_introspection_run(settings: "Settings") -> None:
    """Bump the local, never-transmitted counter of introspection runs (C1)
    — this ticket's own Analytics Events line — mirroring
    `connections.record_write_probe_refusal`'s best-effort Redis increment
    exactly: a Redis hiccup must never turn a successful introspection into
    a failure the caller has to handle.
    """
    import contextlib

    import redis.asyncio as redis

    client = redis.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        socket_connect_timeout=1.0,
        socket_timeout=1.0,
    )
    try:
        await client.incr(SCHEMA_INTROSPECTION_RUN_COUNTER_KEY)
    except Exception as error:
        log.warning(
            "schema_introspection_run_count_failed", error=f"{type(error).__name__}: {error}"
        )
    finally:
        with contextlib.suppress(Exception):
            await client.aclose()


async def dispatch_reintrospection(settings: "Settings", source_id: uuid.UUID) -> bool:
    """Ask a worker to re-introspect this source now, on demand.
    `M4-SCHEMA-ING-100`. Mirrors `connections.dispatch_introspection` and
    `dump_import.dispatch_import` exactly: one attempt, swallowed and
    logged rather than raised, since the caller has nothing durable to roll
    back — a re-introspection request that never reaches a worker just means
    the inventory is stale a while longer, not that anything is lost.
    """
    from dataclasses import replace as _replace

    from arq import create_pool
    from redis.exceptions import RedisError

    from askwell.worker import redis_settings

    queue = _replace(redis_settings(settings), conn_retries=1, conn_retry_delay=0)

    try:
        pool = await create_pool(queue)
    except (OSError, RedisError) as error:
        log.warning(
            "schema_reintrospect_dispatch_unavailable", error=str(error), source_id=str(source_id)
        )
        return False

    try:
        # A fixed job id, like every other dispatch in this codebase: two
        # "re-introspect now" requests arriving close together (a doubled
        # click) collapse into one job rather than racing two writers
        # against the same `schema_notes` rows.
        job = await pool.enqueue_job(
            "reintrospect_source_job",
            str(source_id),
            _job_id=f"schema-reintrospect:{source_id}",
        )
    except (OSError, RedisError) as error:  # pragma: no cover - needs a mid-flight failure
        log.warning(
            "schema_reintrospect_dispatch_failed", error=str(error), source_id=str(source_id)
        )
        return False
    finally:
        await pool.aclose()

    return job is not None


async def reintrospect_sandbox_source(
    factory: "async_sessionmaker[AsyncSession]", settings: "Settings", source_id: uuid.UUID
) -> int:
    """Re-run schema introspection for a `dump` or `csv` source already
    loaded into its own sandbox database. `M4-SCHEMA-ING-100`'s "on demand
    and on reconnect" — the sandbox equivalent of `connections.
    run_introspection`, which already does this for a live connection.

    Always the readonly role (`askwell.sandbox.READONLY_ROLE`), never the
    owner: by the time a source is `ready` the owner's own `CONNECT` has
    already been revoked (`askwell.sandbox.seal_owner`), and re-granting it
    just to introspect would reopen exactly what sealing was for. Raises if
    the source has no sandbox database — deleted, still importing, or never
    a sandbox-backed kind — since there is nothing here to reconnect to.
    """
    from askwell.db.engine import session_scope

    async with session_scope(factory) as session:
        row = (
            await session.execute(
                text("SELECT sandbox_db FROM sources WHERE id = :id AND status != 'deleted'"),
                {"id": source_id},
            )
        ).first()
    if row is None or row[0] is None:
        raise ValueError(f"No sandbox database for source {source_id}.")

    from askwell import sandbox

    admin_url = settings.sandbox_database_url.get_secret_value()
    readonly_password = settings.sandbox_readonly_password.get_secret_value()
    dsn = sandbox.readonly_url(admin_url, str(row[0]), readonly_password)

    inventory = await asyncio.to_thread(_introspect_postgresql_blocking, dsn)

    async with session_scope(factory) as session:
        await write_schema_inventory(session, source_id, inventory)
    await record_introspection_run(settings)
    return len(inventory.tables)
