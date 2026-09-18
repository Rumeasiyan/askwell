"""Registering a live connection and recording its introspection, against a
real Postgres. `M4-CONN-FE-096`.

The decision payload and the `schema_notes` rows are SQL-shaped — a fake
session would just re-implement the queries under test — and the one thing
worth a real database for above everything else: the credential must never
land in `audit_decisions`, which is a claim about what a row does not
contain, not something a mock can assert.
"""

import json
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from askwell.config import Settings
from askwell.connections import (
    create_connection_source,
    record_introspection,
    record_write_probe_refusal,
)

pytestmark = pytest.mark.requires_db

_TABLES = "sources, schema_notes, audit_decisions"


@pytest.fixture
def async_url(database_url: str) -> str:
    return database_url.replace("postgresql://", "postgresql+psycopg://", 1)


@pytest_asyncio.fixture
async def session(async_url: str) -> AsyncIterator[AsyncSession]:
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


async def test_a_connection_is_recorded_as_a_queued_source(session: AsyncSession) -> None:
    source_id = await create_connection_source(
        session,
        engine="postgresql",
        host="db.internal",
        port=5432,
        database="orders",
        user="reader",
        password="hunter2",
    )
    await session.commit()

    row = (
        await session.execute(
            text("SELECT kind, name, status, config_encrypted FROM sources WHERE id = :id"),
            {"id": source_id},
        )
    ).one()
    assert row.kind == "connection"
    assert row.name == "orders on db.internal"
    assert row.status == "queued"
    assert json.loads(bytes(row.config_encrypted).decode("utf-8"))["host"] == "db.internal"


async def test_the_decisions_record_never_carries_the_password(session: AsyncSession) -> None:
    await create_connection_source(
        session,
        engine="postgresql",
        host="db.internal",
        port=5432,
        database="orders",
        user="reader",
        password="hunter2",
    )
    await session.commit()

    row = (
        await session.execute(
            text("SELECT payload FROM audit_decisions WHERE kind = 'connection_added'")
        )
    ).one()
    assert "hunter2" not in json.dumps(row.payload)
    assert row.payload["host"] == "db.internal"
    assert row.payload["user"] == "reader"


async def test_reconfiguring_a_connection_is_not_logged_with_its_credential(
    session: AsyncSession,
) -> None:
    """The same assertion, from the other direction: nothing about how this
    module records a connection ever puts a password anywhere `audit_decisions`
    can be read from — checked over every row a two-connection sequence
    produces, not just the first."""
    await create_connection_source(
        session,
        engine="postgresql",
        host="a.internal",
        port=5432,
        database="orders",
        user="reader",
        password="first-secret",
    )
    await create_connection_source(
        session,
        engine="mysql",
        host="b.internal",
        port=3306,
        database="stock",
        user="reader2",
        password="second-secret",
    )
    await session.commit()

    rows = (await session.execute(text("SELECT payload FROM audit_decisions"))).all()
    dumped = json.dumps([row.payload for row in rows])
    assert "first-secret" not in dumped
    assert "second-secret" not in dumped


async def test_introspection_writes_schema_notes_and_marks_the_source_ready(
    session: AsyncSession,
) -> None:
    source_id = await create_connection_source(
        session,
        engine="postgresql",
        host="db.internal",
        port=5432,
        database="orders",
        user="reader",
        password="hunter2",
    )
    await session.commit()

    await record_introspection(session, source_id, ("orders", "customers"))
    await session.commit()

    status = (
        await session.execute(text("SELECT status FROM sources WHERE id = :id"), {"id": source_id})
    ).scalar_one()
    assert status == "ready"

    notes = (
        await session.execute(
            text(
                "SELECT table_name, origin FROM schema_notes WHERE source_id = :id "
                "ORDER BY table_name"
            ),
            {"id": source_id},
        )
    ).all()
    assert [(row.table_name, row.origin) for row in notes] == [
        ("customers", "inferred"),
        ("orders", "inferred"),
    ]


async def test_introspection_with_no_tables_still_marks_the_source_ready(
    session: AsyncSession,
) -> None:
    """An empty schema is not a failure — the database answered and has
    nothing in it, which is a fact about the database, not about the
    connection."""
    source_id = await create_connection_source(
        session,
        engine="postgresql",
        host="db.internal",
        port=5432,
        database="empty",
        user="reader",
        password="hunter2",
    )
    await session.commit()

    await record_introspection(session, source_id, ())
    await session.commit()

    status = (
        await session.execute(text("SELECT status FROM sources WHERE id = :id"), {"id": source_id})
    ).scalar_one()
    assert status == "ready"


# --- write-probe refusal, recorded ------------------------------------------
# `M4-CONN-SEC-097`'s own AC: "The refusal and the detected permission are
# decisions records." A loopback address nothing listens on stands in for
# Redis here — the point under test is that a Redis-side failure never stops
# the decisions row from landing, the same guarantee `egress._record` makes.


@pytest.fixture
def unreachable_redis_settings() -> Settings:
    return Settings(
        database_url="postgresql://askwell:pw@127.0.0.1:1/askwell",  # type: ignore[arg-type]
        sandbox_database_url="postgresql://askwell_sandbox:pw@127.0.0.1:1/postgres",  # type: ignore[arg-type]
        sandbox_owner_password="pw",  # type: ignore[arg-type]
        redis_host="127.0.0.1",
        redis_port=1,
    )


async def test_a_write_capable_refusal_is_recorded_naming_engine_host_and_permission(
    session: AsyncSession, unreachable_redis_settings: Settings
) -> None:
    await record_write_probe_refusal(
        session,
        unreachable_redis_settings,
        engine="postgresql",
        host="db.internal",
        message="These credentials have INSERT on `orders`. Askwell only connects with "
        "read-only access.",
    )
    await session.commit()

    row = (
        await session.execute(
            text("SELECT payload FROM audit_decisions WHERE kind = 'connection_write_refused'")
        )
    ).one()
    assert row.payload["engine"] == "postgresql"
    assert row.payload["host"] == "db.internal"
    assert "INSERT" in row.payload["message"]
    assert "`orders`" in row.payload["message"]


async def test_recording_a_refusal_never_raises_when_redis_is_unreachable(
    session: AsyncSession, unreachable_redis_settings: Settings
) -> None:
    """The counter increment is best-effort — a Redis hiccup must not turn a
    refusal the wizard already has to render into an exception."""
    await record_write_probe_refusal(
        session,
        unreachable_redis_settings,
        engine="mysql",
        host="db.internal",
        message="These credentials have ALL PRIVILEGES on `*.*`.",
    )
    await session.commit()
