"""Registering a live connection and recording its introspection, against a
real Postgres. `M4-CONN-FE-096`.

The decision payload and the `schema_notes` rows are SQL-shaped — a fake
session would just re-implement the queries under test — and the one thing
worth a real database for above everything else: the credential must never
land in `audit_decisions`, which is a claim about what a row does not
contain, not something a mock can assert.
"""

import json
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from askwell import connections, crypto
from askwell.config import Settings
from askwell.connections import (
    ConnectOutcome,
    check_connection_health,
    create_connection_source,
    record_introspection,
    record_write_probe_refusal,
    run_introspection,
)

pytestmark = pytest.mark.requires_db

_TABLES = "sources, schema_notes, audit_decisions"


@pytest.fixture
def async_url(database_url: str) -> str:
    return database_url.replace("postgresql://", "postgresql+psycopg://", 1)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url="postgresql://askwell:pw@127.0.0.1:1/askwell",  # type: ignore[arg-type]
        sandbox_database_url="postgresql://askwell_sandbox:pw@127.0.0.1:1/postgres",  # type: ignore[arg-type]
        sandbox_owner_password="pw",  # type: ignore[arg-type]
        sandbox_readonly_password="pw",  # type: ignore[arg-type]
        install_secret_path=tmp_path / "install.key",
    )


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


async def test_a_connection_is_recorded_as_a_queued_source(
    session: AsyncSession, settings: Settings
) -> None:
    source_id = await create_connection_source(
        session,
        settings,
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


async def test_the_stored_configuration_is_unreadable_without_the_key(
    session: AsyncSession, settings: Settings
) -> None:
    """`M4-CONN-SEC-098`'s own acceptance criterion: not plain JSON, not the
    password as a substring, not decryptable with a different key."""
    source_id = await create_connection_source(
        session,
        settings,
        engine="postgresql",
        host="db.internal",
        port=5432,
        database="orders",
        user="reader",
        password="hunter2",
    )
    await session.commit()

    stored = (
        await session.execute(
            text("SELECT config_encrypted FROM sources WHERE id = :id"), {"id": source_id}
        )
    ).scalar_one()
    raw = bytes(stored)
    assert b"hunter2" not in raw
    assert b"db.internal" not in raw
    with pytest.raises((UnicodeDecodeError, json.JSONDecodeError)):
        json.loads(raw.decode("utf-8"))

    install_secret = crypto.load_or_create_install_secret(settings.install_secret_path)
    plaintext = crypto.decrypt(raw, crypto.derive_key(install_secret))
    assert json.loads(plaintext.decode("utf-8"))["host"] == "db.internal"


async def test_a_different_install_secret_cannot_decrypt_the_configuration(
    session: AsyncSession, settings: Settings, tmp_path: Path
) -> None:
    """The scenario this ticket names directly: the database file copied to
    another machine (a different install secret) yields no usable
    credential."""
    source_id = await create_connection_source(
        session,
        settings,
        engine="postgresql",
        host="db.internal",
        port=5432,
        database="orders",
        user="reader",
        password="hunter2",
    )
    await session.commit()

    stored = (
        await session.execute(
            text("SELECT config_encrypted FROM sources WHERE id = :id"), {"id": source_id}
        )
    ).scalar_one()

    other_secret = crypto.load_or_create_install_secret(tmp_path / "other-install.key")
    with pytest.raises(crypto.CredentialsLocked):
        crypto.decrypt(bytes(stored), crypto.derive_key(other_secret))


async def test_the_decisions_record_never_carries_the_password(
    session: AsyncSession, settings: Settings
) -> None:
    await create_connection_source(
        session,
        settings,
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
    session: AsyncSession, settings: Settings
) -> None:
    """The same assertion, from the other direction: nothing about how this
    module records a connection ever puts a password anywhere `audit_decisions`
    can be read from — checked over every row a two-connection sequence
    produces, not just the first."""
    await create_connection_source(
        session,
        settings,
        engine="postgresql",
        host="a.internal",
        port=5432,
        database="orders",
        user="reader",
        password="first-secret",
    )
    await create_connection_source(
        session,
        settings,
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
    session: AsyncSession, settings: Settings
) -> None:
    source_id = await create_connection_source(
        session,
        settings,
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


async def test_recording_introspection_twice_never_duplicates_the_table_note(
    session: AsyncSession, settings: Settings
) -> None:
    """`M4-SCHEMA-ING-100` makes `run_introspection` (and therefore this
    function) callable again against an already-`ready` source — on-demand
    re-introspection. A second call must leave exactly one active note per
    table, not a second competing placeholder alongside the first."""
    source_id = await create_connection_source(
        session,
        settings,
        engine="postgresql",
        host="db.internal",
        port=5432,
        database="orders",
        user="reader",
        password="hunter2",
    )
    await session.commit()

    await record_introspection(session, source_id, ("orders",))
    await record_introspection(session, source_id, ("orders",))
    await session.commit()

    notes = (
        await session.execute(
            text(
                "SELECT id FROM schema_notes WHERE source_id = :id "
                "AND table_name = 'orders' AND column_name IS NULL AND superseded_by IS NULL"
            ),
            {"id": source_id},
        )
    ).all()
    assert len(notes) == 1


async def test_introspection_with_no_tables_still_marks_the_source_ready(
    session: AsyncSession, settings: Settings
) -> None:
    """An empty schema is not a failure — the database answered and has
    nothing in it, which is a fact about the database, not about the
    connection."""
    source_id = await create_connection_source(
        session,
        settings,
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


async def test_a_lost_install_secret_locks_the_source_rather_than_failing_obscurely(
    session: AsyncSession, settings: Settings, async_url: str
) -> None:
    """The edge case this ticket names directly: the per-install secret is
    gone. `run_introspection` must report `credentials_locked` and ask for
    re-entry — never attempt the connection (which would misreport this as
    an unreachable host) and never raise an unhandled exception."""
    source_id = await create_connection_source(
        session,
        settings,
        engine="postgresql",
        host="db.internal",
        port=5432,
        database="orders",
        user="reader",
        password="hunter2",
    )
    await session.commit()

    settings.install_secret_path.unlink()

    engine = create_async_engine(async_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        tables = await run_introspection(factory, settings, source_id)
    finally:
        await engine.dispose()
    assert tables == ()

    status, last_error = (
        await session.execute(
            text("SELECT status, last_error FROM sources WHERE id = :id"), {"id": source_id}
        )
    ).one()
    assert status == "attention"
    assert last_error is not None
    assert "hunter2" not in last_error
    assert "decrypt" in last_error.lower()


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
        sandbox_readonly_password="pw",  # type: ignore[arg-type]
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


# --- periodic and on-demand health checks, `M4-CONN-BE-099` ------------------
# `probe_connection` itself is monkeypatched — the classification it produces
# is already proven in `test_connections.py` and `test_connections_write_probe_db.py`;
# what is under test here is `check_connection_health`'s own transition logic,
# and issue #360's own lesson: a decisions row only on a real transition,
# never on a repeat of the same state.


@pytest_asyncio.fixture
async def factory(async_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(async_url)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def _connected_source(
    session: AsyncSession, settings: Settings, *, status: str = "ready"
) -> uuid.UUID:
    source_id = await create_connection_source(
        session,
        settings,
        engine="postgresql",
        host="db.internal",
        port=5432,
        database="orders",
        user="reader",
        password="hunter2",
    )
    await session.execute(
        text("UPDATE sources SET status = :status WHERE id = :id"),
        {"status": status, "id": source_id},
    )
    await session.commit()
    return source_id


async def test_a_failed_probe_moves_a_ready_source_to_attention_and_records_it(
    monkeypatch: pytest.MonkeyPatch,
    session: AsyncSession,
    settings: Settings,
    factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id = await _connected_source(session, settings)
    refusal = ConnectOutcome(False, "connection_refused", "The connection was refused.")
    monkeypatch.setattr(connections, "probe_connection", lambda *a, **k: _coro(refusal))

    outcome = await check_connection_health(factory, settings, source_id)
    assert outcome.ok is False

    async with factory() as check:
        status, last_error = (
            await check.execute(
                text("SELECT status, last_error FROM sources WHERE id = :id"), {"id": source_id}
            )
        ).one()
        assert status == "attention"
        assert last_error == "The connection was refused."

        kinds = (
            await check.execute(
                text("SELECT kind FROM audit_decisions WHERE kind LIKE 'connection_health_%'")
            )
        ).all()
        assert [row.kind for row in kinds] == ["connection_health_lost"]


async def test_repeated_failures_against_an_already_attention_source_write_no_second_decision(
    monkeypatch: pytest.MonkeyPatch,
    session: AsyncSession,
    settings: Settings,
    factory: async_sessionmaker[AsyncSession],
) -> None:
    """The regression issue #360 exists to prevent: a health check that fires
    every cycle must not write a decisions row every cycle."""
    source_id = await _connected_source(session, settings, status="attention")
    refusal = ConnectOutcome(False, "timeout", "The database did not answer in time.")
    monkeypatch.setattr(connections, "probe_connection", lambda *a, **k: _coro(refusal))

    for _ in range(3):
        await check_connection_health(factory, settings, source_id)

    async with factory() as check:
        kinds = (
            await check.execute(
                text("SELECT kind FROM audit_decisions WHERE kind LIKE 'connection_health_%'")
            )
        ).all()
        assert kinds == []


async def test_a_successful_probe_recovers_an_attention_source_and_records_it(
    monkeypatch: pytest.MonkeyPatch,
    session: AsyncSession,
    settings: Settings,
    factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id = await _connected_source(session, settings, status="attention")
    await session.execute(
        text("UPDATE sources SET last_error = 'stale error' WHERE id = :id"), {"id": source_id}
    )
    await session.commit()

    success = ConnectOutcome(True, None, "Connected.", ("orders",))
    monkeypatch.setattr(connections, "probe_connection", lambda *a, **k: _coro(success))

    outcome = await check_connection_health(factory, settings, source_id)
    assert outcome.ok is True

    async with factory() as check:
        status, last_error, last_healthy_at = (
            await check.execute(
                text("SELECT status, last_error, last_healthy_at FROM sources WHERE id = :id"),
                {"id": source_id},
            )
        ).one()
        assert status == "ready"
        assert last_error is None
        assert last_healthy_at is not None

        kinds = (
            await check.execute(
                text("SELECT kind FROM audit_decisions WHERE kind LIKE 'connection_health_%'")
            )
        ).all()
        assert [row.kind for row in kinds] == ["connection_health_recovered"]


async def test_a_successful_probe_against_an_already_ready_source_writes_no_decision(
    monkeypatch: pytest.MonkeyPatch,
    session: AsyncSession,
    settings: Settings,
    factory: async_sessionmaker[AsyncSession],
) -> None:
    """The ordinary case, every cycle, for a healthy connection — no news is
    not a decisions row, only `last_healthy_at` moving forward."""
    source_id = await _connected_source(session, settings)
    success = ConnectOutcome(True, None, "Connected.", ("orders",))
    monkeypatch.setattr(connections, "probe_connection", lambda *a, **k: _coro(success))

    for _ in range(3):
        await check_connection_health(factory, settings, source_id)

    async with factory() as check:
        status = (
            await check.execute(
                text("SELECT status FROM sources WHERE id = :id"), {"id": source_id}
            )
        ).scalar_one()
        assert status == "ready"

        kinds = (
            await check.execute(
                text("SELECT kind FROM audit_decisions WHERE kind LIKE 'connection_health_%'")
            )
        ).all()
        assert kinds == []


async def test_a_locked_install_secret_is_reported_as_attention_without_probing(
    session: AsyncSession, settings: Settings, factory: async_sessionmaker[AsyncSession]
) -> None:
    source_id = await _connected_source(session, settings)
    settings.install_secret_path.unlink()

    outcome = await check_connection_health(factory, settings, source_id)
    assert outcome.ok is False
    assert outcome.reason_code == "credentials_locked"

    async with factory() as check:
        status, last_error = (
            await check.execute(
                text("SELECT status, last_error FROM sources WHERE id = :id"), {"id": source_id}
            )
        ).one()
        assert status == "attention"
        assert last_error is not None
        assert "hunter2" not in last_error


async def _coro(value: ConnectOutcome) -> ConnectOutcome:
    return value
