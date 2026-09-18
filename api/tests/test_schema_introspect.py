"""Full schema introspection: types, keys, relationships. `M4-SCHEMA-ING-100`.

The row-grouping logic for each engine is pure Python and tested here with
fabricated rows — no network (C1), the same pattern
`connections._find_mysql_write_grant` uses for MySQL's own privilege
parsing. What actually runs a query against a real Postgres — both a live
`postgresql`-engine connection's own shape and a sandbox database's, which
are the same code path — is `requires_db`, against the real, separate
sandbox instance `test_sandbox.py` already depends on: the omitted-object
edge case specifically needs a real role denied `SELECT` on a real table,
which no fake can stand in for.
"""

import os
import uuid
from collections.abc import AsyncIterator

import psycopg
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from askwell import schema_introspect
from askwell.memory import write_schema_note
from askwell.sandbox import create_database, drop_database, generate_name, owner_url, readonly_url
from askwell.schema_introspect import (
    Column,
    ForeignKey,
    SchemaInventory,
    Table,
    _build_mysql_inventory,
    _build_postgresql_inventory,
    _build_sqlserver_inventory,
    _introspect_postgresql_blocking,
    describe_column,
    describe_table,
    write_schema_inventory,
)

# --- description text -------------------------------------------------------


def test_describe_table_names_columns_primary_key_and_foreign_keys() -> None:
    table = Table(
        name="orders",
        kind="table",
        columns=(
            Column("id", "integer", nullable=False, primary_key=True),
            Column("customer_id", "integer", nullable=False, primary_key=False),
            Column("total", "numeric", nullable=True, primary_key=False),
        ),
        foreign_keys=(ForeignKey("customer_id", "customers", "id"),),
    )
    description = describe_table(table)
    assert "Table orders." in description
    assert "id, customer_id, total" in description
    assert "Primary key: id." in description
    assert "customer_id -> customers.id" in description


def test_describe_table_labels_a_view_distinctly() -> None:
    table = Table(name="active_orders", kind="view", columns=(), foreign_keys=())
    assert describe_table(table).startswith("View active_orders")


def test_describe_table_labels_a_materialized_view_distinctly() -> None:
    table = Table(name="daily_totals", kind="materialized_view", columns=(), foreign_keys=())
    assert describe_table(table).startswith("Materialised view daily_totals")


def test_describe_table_with_no_columns_says_so_rather_than_an_empty_list() -> None:
    table = Table(name="empty", kind="table", columns=(), foreign_keys=())
    assert "no columns" in describe_table(table)


def test_describe_column_names_type_primary_key_not_null_and_reference() -> None:
    column = Column("customer_id", "integer", nullable=False, primary_key=False)
    fk = (ForeignKey("customer_id", "customers", "id"),)
    description = describe_column("orders", column, fk)
    assert description.startswith("orders.customer_id — integer")
    assert "not null" in description
    assert "references customers.id" in description


def test_describe_column_for_an_ordinary_nullable_column_names_only_the_type() -> None:
    column = Column("notes", "text", nullable=True, primary_key=False)
    description = describe_column("orders", column, ())
    assert description == "orders.notes — text."


# --- postgresql row grouping -------------------------------------------------


def test_postgresql_inventory_groups_columns_keys_and_foreign_keys_by_table() -> None:
    inventory = _build_postgresql_inventory(
        class_rows=[
            ("public", "customers", "r", True),
            ("public", "orders", "r", True),
        ],
        column_rows=[
            ("public", "customers", "id", "integer", False),
            ("public", "orders", "id", "integer", False),
            ("public", "orders", "customer_id", "integer", False),
        ],
        pk_rows=[
            ("public", "customers", "id"),
            ("public", "orders", "id"),
        ],
        fk_rows=[
            ("public", "orders", "customer_id", "customers", "id"),
        ],
    )
    assert inventory.omitted_count == 0
    by_name = {table.name: table for table in inventory.tables}
    assert set(by_name) == {"customers", "orders"}
    orders = by_name["orders"]
    assert [c.name for c in orders.columns] == ["id", "customer_id"]
    assert orders.columns[0].primary_key is True
    assert orders.foreign_keys == (ForeignKey("customer_id", "customers", "id"),)


def test_postgresql_inventory_labels_views_and_materialized_views() -> None:
    inventory = _build_postgresql_inventory(
        class_rows=[
            ("public", "orders", "r", True),
            ("public", "active_orders", "v", True),
            ("public", "daily_totals", "m", True),
        ],
        column_rows=[],
        pk_rows=[],
        fk_rows=[],
    )
    kinds = {table.name: table.kind for table in inventory.tables}
    assert kinds == {
        "orders": "table",
        "active_orders": "view",
        "daily_totals": "materialized_view",
    }


def test_postgresql_inventory_counts_but_never_names_an_invisible_table() -> None:
    inventory = _build_postgresql_inventory(
        class_rows=[
            ("public", "visible_table", "r", True),
            ("public", "secret_table", "r", False),
        ],
        column_rows=[("public", "secret_table", "ssn", "text", True)],
        pk_rows=[],
        fk_rows=[],
    )
    assert inventory.omitted_count == 1
    assert [t.name for t in inventory.tables] == ["visible_table"]


def test_postgresql_inventory_ignores_indexes_and_sequences() -> None:
    """`relkind` values other than table/view/matview — an index (`i`) or a
    sequence (`S`) — never turn into a `Table`, whether or not they are
    selectable."""
    inventory = _build_postgresql_inventory(
        class_rows=[("public", "orders_id_seq", "S", True), ("public", "orders_pkey", "i", True)],
        column_rows=[],
        pk_rows=[],
        fk_rows=[],
    )
    assert inventory.tables == ()
    assert inventory.omitted_count == 0


# --- mysql / sqlserver row grouping ------------------------------------------


def test_mysql_inventory_has_no_omitted_count() -> None:
    inventory = _build_mysql_inventory(
        table_rows=[("orders", "BASE TABLE"), ("active_orders", "VIEW")],
        column_rows=[("orders", "id", "int", False)],
        pk_rows=[("orders", "id")],
        fk_rows=[],
    )
    assert inventory.omitted_count is None
    kinds = {t.name: t.kind for t in inventory.tables}
    assert kinds == {"orders": "table", "active_orders": "view"}
    by_name = {t.name: t for t in inventory.tables}
    assert by_name["orders"].columns[0].primary_key is True
    assert by_name["active_orders"].columns == ()


def test_sqlserver_inventory_groups_foreign_keys() -> None:
    inventory = _build_sqlserver_inventory(
        object_rows=[("orders", "USER_TABLE"), ("customers", "USER_TABLE")],
        column_rows=[
            ("orders", "customer_id", "int", False),
            ("customers", "id", "int", False),
        ],
        pk_rows=[("customers", "id")],
        fk_rows=[("orders", "customer_id", "customers", "id")],
    )
    assert inventory.omitted_count is None
    orders = next(t for t in inventory.tables if t.name == "orders")
    assert orders.foreign_keys == (ForeignKey("customer_id", "customers", "id"),)


# --- write_schema_inventory, against Askwell's own database -----------------

_TABLES = "sources, schema_notes, audit_decisions"


@pytest_asyncio.fixture
async def session(database_url: str) -> AsyncIterator[AsyncSession]:
    async_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_async_engine(async_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as opened:
        await opened.execute(text(f"TRUNCATE {_TABLES} CASCADE"))
        await opened.commit()
        yield opened
        await opened.rollback()
        await opened.execute(text(f"TRUNCATE {_TABLES} CASCADE"))
        await opened.commit()
    await engine.dispose()


@pytest_asyncio.fixture
async def source_id(session: AsyncSession) -> uuid.UUID:
    result = await session.execute(
        text(
            "INSERT INTO sources (kind, name, status) VALUES ('connection', 'db', 'queued') "
            "RETURNING id"
        )
    )
    new_id = result.scalar_one()
    await session.commit()
    return uuid.UUID(str(new_id))


def _inventory(*, with_fk: bool = True) -> SchemaInventory:
    orders_columns = (
        Column("id", "integer", nullable=False, primary_key=True),
        Column("customer_id", "integer", nullable=False, primary_key=False),
    )
    return SchemaInventory(
        tables=(
            Table(
                name="orders",
                kind="table",
                columns=orders_columns,
                foreign_keys=(ForeignKey("customer_id", "customers", "id"),) if with_fk else (),
            ),
        ),
        omitted_count=0,
    )


@pytest.mark.requires_db
async def test_write_schema_inventory_writes_table_and_column_notes(
    session: AsyncSession, source_id: uuid.UUID
) -> None:
    await write_schema_inventory(session, source_id, _inventory())
    await session.commit()

    rows = (
        await session.execute(
            text(
                "SELECT table_name, column_name, origin FROM schema_notes "
                "WHERE source_id = :id ORDER BY table_name, column_name NULLS FIRST"
            ),
            {"id": source_id},
        )
    ).all()
    assert [(r[0], r[1], r[2]) for r in rows] == [
        ("orders", None, "inferred"),
        ("orders", "customer_id", "inferred"),
        ("orders", "id", "inferred"),
    ]

    decision = (
        await session.execute(
            text("SELECT payload FROM audit_decisions WHERE kind = 'schema_introspected'")
        )
    ).first()
    assert decision is not None
    assert decision[0]["tables"] == 1
    assert decision[0]["columns"] == 2
    assert decision[0]["foreign_keys"] == 1


@pytest.mark.requires_db
async def test_reintrospecting_an_unchanged_schema_does_not_duplicate_notes(
    session: AsyncSession, source_id: uuid.UUID
) -> None:
    await write_schema_inventory(session, source_id, _inventory())
    await session.commit()
    await write_schema_inventory(session, source_id, _inventory())
    await session.commit()

    rows = (
        await session.execute(
            text("SELECT id FROM schema_notes WHERE source_id = :id AND superseded_by IS NULL"),
            {"id": source_id},
        )
    ).all()
    assert len(rows) == 3  # one table note, two column notes — not six.


@pytest.mark.requires_db
async def test_reintrospection_supersedes_a_note_whose_description_changed(
    session: AsyncSession, source_id: uuid.UUID
) -> None:
    await write_schema_inventory(session, source_id, _inventory(with_fk=False))
    await session.commit()
    before = (
        await session.execute(
            text(
                "SELECT id, description FROM schema_notes "
                "WHERE source_id = :id AND table_name = 'orders' AND column_name IS NULL"
            ),
            {"id": source_id},
        )
    ).one()
    assert "Foreign keys" not in before[1]

    await write_schema_inventory(session, source_id, _inventory(with_fk=True))
    await session.commit()

    after = (
        await session.execute(
            text(
                "SELECT id, description, superseded_by FROM schema_notes "
                "WHERE source_id = :id AND table_name = 'orders' AND column_name IS NULL "
                "AND superseded_by IS NULL"
            ),
            {"id": source_id},
        )
    ).one()
    assert after[0] != before[0]
    assert "Foreign keys" in after[1]

    old = (
        await session.execute(
            text("SELECT superseded_by FROM schema_notes WHERE id = :id"), {"id": before[0]}
        )
    ).scalar_one()
    assert old == after[0]


@pytest.mark.requires_db
async def test_a_table_dropped_from_the_schema_is_superseded_not_left_active(
    session: AsyncSession, source_id: uuid.UUID
) -> None:
    await write_schema_inventory(session, source_id, _inventory())
    await session.commit()

    empty = SchemaInventory(tables=(), omitted_count=0)
    await write_schema_inventory(session, source_id, empty)
    await session.commit()

    active = (
        await session.execute(
            text("SELECT 1 FROM schema_notes WHERE source_id = :id AND superseded_by IS NULL"),
            {"id": source_id},
        )
    ).all()
    assert active == []


@pytest.mark.requires_db
async def test_a_user_supplied_note_is_never_overwritten_by_reintrospection(
    session: AsyncSession, source_id: uuid.UUID
) -> None:
    await write_schema_note(
        session,
        source_id=source_id,
        table_name="orders",
        column_name=None,
        description="Orders placed by a customer. Written by a person.",
        origin="user",
    )
    await session.commit()

    await write_schema_inventory(session, source_id, _inventory())
    await session.commit()

    row = (
        await session.execute(
            text(
                "SELECT description, origin FROM schema_notes "
                "WHERE source_id = :id AND table_name = 'orders' AND column_name IS NULL "
                "AND superseded_by IS NULL"
            ),
            {"id": source_id},
        )
    ).one()
    assert row[0] == "Orders placed by a customer. Written by a person."
    assert row[1] == "user"


# --- against a real, separate sandbox instance -------------------------------
# The omitted-object edge case needs a real role denied SELECT on a real
# table — `docs/data-sources.md`'s own validation rule that introspection
# runs as the read-only role, so it can never see more than a query could.


@pytest.fixture
def sandbox_owner_password() -> str:
    return os.environ["TEST_SANDBOX_OWNER_PASSWORD"]


@pytest.fixture
def sandbox_readonly_password() -> str:
    return os.environ["TEST_SANDBOX_READONLY_PASSWORD"]


@pytest_asyncio.fixture
async def sandbox_database(sandbox_admin_url: str, database_url: str) -> AsyncIterator[str]:
    """A fresh sandbox database with two tables loaded as the owner role,
    sealed the way `dump_import.import_dump` seals one — the same shape a
    real dump import leaves behind, for `_introspect_postgresql_blocking`
    to read as the readonly role.
    """
    async_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_async_engine(async_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    name = generate_name()
    async with factory() as session:
        await create_database(session, sandbox_admin_url, name)
        await session.commit()
    yield name
    async with factory() as session:
        await drop_database(session, sandbox_admin_url, name)
        await session.commit()
    await engine.dispose()


@pytest.mark.requires_db
async def test_introspecting_a_sandbox_database_finds_columns_keys_relationships_and_omissions(
    sandbox_admin_url: str,
    sandbox_database: str,
    sandbox_owner_password: str,
    sandbox_readonly_password: str,
) -> None:
    owner_dsn = owner_url(sandbox_admin_url, sandbox_database, sandbox_owner_password)
    with psycopg.connect(owner_dsn, autocommit=True) as owner:
        owner.execute("CREATE TABLE customers (id integer primary key, name text not null)")
        owner.execute(
            "CREATE TABLE orders (id integer primary key, "
            "customer_id integer references customers(id), total numeric)"
        )
        # A table the readonly role cannot see — `docs/data-sources.md`'s own
        # edge case: omitted, with a note that some objects were not visible.
        owner.execute("CREATE TABLE internal_audit (id integer primary key)")
        owner.execute("REVOKE SELECT ON internal_audit FROM askwell_sandbox_readonly")

    readonly_dsn = readonly_url(sandbox_admin_url, sandbox_database, sandbox_readonly_password)
    inventory = _introspect_postgresql_blocking(readonly_dsn)

    assert inventory.omitted_count == 1
    names = {table.name for table in inventory.tables}
    assert names == {"customers", "orders"}

    orders = next(t for t in inventory.tables if t.name == "orders")
    assert {c.name for c in orders.columns} == {"id", "customer_id", "total"}
    id_column = next(c for c in orders.columns if c.name == "id")
    assert id_column.primary_key is True
    customer_id_column = next(c for c in orders.columns if c.name == "customer_id")
    assert customer_id_column.primary_key is False
    assert orders.foreign_keys == (ForeignKey("customer_id", "customers", "id"),)


@pytest.mark.requires_db
async def test_reintrospect_sandbox_source_writes_notes_as_the_readonly_role(
    sandbox_admin_url: str,
    sandbox_database: str,
    sandbox_owner_password: str,
    database_url: str,
) -> None:
    from askwell.config import Settings

    owner_dsn = owner_url(sandbox_admin_url, sandbox_database, sandbox_owner_password)
    with psycopg.connect(owner_dsn, autocommit=True) as owner:
        owner.execute("CREATE TABLE widgets (id integer primary key, name text)")

    async_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_async_engine(async_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            await session.execute(text(f"TRUNCATE {_TABLES} CASCADE"))
            result = await session.execute(
                text(
                    "INSERT INTO sources (kind, name, status, sandbox_db) "
                    "VALUES ('dump', 'a colleague''s export', 'ready', :db) RETURNING id"
                ),
                {"db": sandbox_database},
            )
            new_source_id = uuid.UUID(str(result.scalar_one()))
            await session.commit()

        settings = Settings(
            database_url="postgresql://x:x@127.0.0.1:1/askwell",  # type: ignore[arg-type]
            sandbox_database_url=sandbox_admin_url,  # type: ignore[arg-type]
            sandbox_owner_password=sandbox_owner_password,  # type: ignore[arg-type]
            sandbox_readonly_password=os.environ["TEST_SANDBOX_READONLY_PASSWORD"],  # type: ignore[arg-type]
        )

        table_count = await schema_introspect.reintrospect_sandbox_source(
            factory, settings, new_source_id
        )
        assert table_count == 1

        async with factory() as session:
            rows = (
                await session.execute(
                    text(
                        "SELECT table_name, column_name FROM schema_notes "
                        "WHERE source_id = :id ORDER BY table_name, column_name NULLS FIRST"
                    ),
                    {"id": new_source_id},
                )
            ).all()
            await session.execute(text(f"TRUNCATE {_TABLES} CASCADE"))
            await session.commit()
        assert ("widgets", None) in [(r[0], r[1]) for r in rows]
    finally:
        await engine.dispose()
