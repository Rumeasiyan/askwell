"""`execute_connection_query` against a real Postgres, standing in for a
customer's live connection. `M4-CONN-BE-099`.

The three distinguishable query-time failures this ticket's own acceptance
criteria name — unreachable, credentials rejected, query rejected — are each
a different real condition against the same disposable database
`conftest_db.py` already creates per run: a port nothing listens on, a wrong
password, and a role with no `SELECT` on the table being read. The point
under test in every case is the *type* raised and the transition it causes on
`sources`, never that a customer's actual database was reached.
"""

import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from urllib.parse import urlsplit

import psycopg
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from askwell.config import Settings
from askwell.sql_execute import (
    ConnectionUnreachable,
    CredentialsRejected,
    QueryRejected,
    execute_connection_query,
)

pytestmark = pytest.mark.requires_db

_TABLES = "sources, audit_decisions"
_ROLE = "askwell_sql_execute_test"


def _target(database_url: str) -> tuple[str, int, str]:
    parts = urlsplit(database_url)
    return parts.hostname or "127.0.0.1", parts.port or 5432, parts.path.lstrip("/")


def _run(database_url: str, *statements: str) -> None:
    with psycopg.connect(database_url, autocommit=True) as conn, conn.cursor() as cur:
        for statement in statements:
            cur.execute(statement)


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


@pytest_asyncio.fixture
async def source_id(session: AsyncSession) -> uuid.UUID:
    """A `connection` source already `ready` — the state every health
    transition in these tests starts from."""
    row = (
        await session.execute(
            text(
                "INSERT INTO sources (kind, name, status) VALUES "
                "('connection', 'customer db', 'ready') RETURNING id"
            )
        )
    ).scalar_one()
    await session.commit()
    return uuid.UUID(str(row))


@pytest.fixture
def read_only_role(database_url: str) -> Iterator[str]:
    """`SELECT` on `sources`, nothing else — the credential a live connection
    is meant to hold (`M4-CONN-SEC-097`)."""
    database = _target(database_url)[2]
    _run(
        database_url,
        f"DROP ROLE IF EXISTS {_ROLE}",
        f"CREATE ROLE {_ROLE} LOGIN PASSWORD 'exec-test-pw'",
        f"GRANT CONNECT ON DATABASE {database} TO {_ROLE}",
        f"GRANT USAGE ON SCHEMA public TO {_ROLE}",
        f"GRANT SELECT ON sources TO {_ROLE}",
    )
    try:
        yield _ROLE
    finally:
        _run(
            database_url,
            f"REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM {_ROLE}",
            f"DROP OWNED BY {_ROLE}",
            f"DROP ROLE IF EXISTS {_ROLE}",
        )


@pytest.fixture
def no_select_role(database_url: str) -> Iterator[str]:
    """Can connect, cannot read `sources` — the "accepts connections but
    refuses queries" edge case, distinct from a bad credential."""
    database = _target(database_url)[2]
    _run(
        database_url,
        f"DROP ROLE IF EXISTS {_ROLE}",
        f"CREATE ROLE {_ROLE} LOGIN PASSWORD 'exec-test-pw'",
        f"GRANT CONNECT ON DATABASE {database} TO {_ROLE}",
        f"GRANT USAGE ON SCHEMA public TO {_ROLE}",
    )
    try:
        yield _ROLE
    finally:
        _run(database_url, f"DROP OWNED BY {_ROLE}", f"DROP ROLE IF EXISTS {_ROLE}")


async def test_reads_rows_over_a_read_only_role(
    session: AsyncSession,
    settings: Settings,
    database_url: str,
    read_only_role: str,
    source_id: uuid.UUID,
) -> None:
    host, port, database = _target(database_url)
    result = await execute_connection_query(
        session,
        settings,
        source_id=source_id,
        engine="postgresql",
        host=host,
        port=port,
        database=database,
        user=read_only_role,
        password="exec-test-pw",
        query="SELECT id FROM sources",
    )
    assert result.columns == ("id",)


async def test_unreachable_when_nothing_listens_on_the_port(
    session: AsyncSession, settings: Settings, source_id: uuid.UUID
) -> None:
    with pytest.raises(ConnectionUnreachable):
        await execute_connection_query(
            session,
            settings,
            source_id=source_id,
            engine="postgresql",
            host="127.0.0.1",
            port=1,
            database="orders",
            user="reader",
            password="whatever",
            query="SELECT 1",
        )


async def test_unreachable_is_never_confused_with_a_zero_row_result(
    session: AsyncSession, settings: Settings, source_id: uuid.UUID
) -> None:
    """`docs/states-and-edge-cases.md` §4's own AC: "unreachable and empty
    must never share a message."""
    with pytest.raises(ConnectionUnreachable) as excinfo:
        await execute_connection_query(
            session,
            settings,
            source_id=source_id,
            engine="postgresql",
            host="127.0.0.1",
            port=1,
            database="orders",
            user="reader",
            password="whatever",
            query="SELECT 1",
        )
    assert "no matching records" not in str(excinfo.value).lower()
    assert "unreachable" in str(excinfo.value).lower()


async def test_credentials_rejected_on_a_wrong_password(
    session: AsyncSession,
    settings: Settings,
    database_url: str,
    read_only_role: str,
    source_id: uuid.UUID,
) -> None:
    host, port, database = _target(database_url)
    with pytest.raises(CredentialsRejected):
        await execute_connection_query(
            session,
            settings,
            source_id=source_id,
            engine="postgresql",
            host=host,
            port=port,
            database=database,
            user=read_only_role,
            password="not-the-password",
            query="SELECT 1",
        )


async def test_query_rejected_when_the_role_cannot_select_the_table(
    session: AsyncSession,
    settings: Settings,
    database_url: str,
    no_select_role: str,
    source_id: uuid.UUID,
) -> None:
    """The edge case this ticket names directly: "a database that accepts
    connections but refuses queries — reported as a permissions problem"."""
    host, port, database = _target(database_url)
    with pytest.raises(QueryRejected):
        await execute_connection_query(
            session,
            settings,
            source_id=source_id,
            engine="postgresql",
            host=host,
            port=port,
            database=database,
            user=no_select_role,
            password="exec-test-pw",
            query="SELECT id FROM sources",
        )


async def test_a_query_time_failure_moves_the_source_to_attention(
    session: AsyncSession, settings: Settings, source_id: uuid.UUID
) -> None:
    with pytest.raises(ConnectionUnreachable):
        await execute_connection_query(
            session,
            settings,
            source_id=source_id,
            engine="postgresql",
            host="127.0.0.1",
            port=1,
            database="orders",
            user="reader",
            password="whatever",
            query="SELECT 1",
        )
    await session.commit()

    status, last_error = (
        await session.execute(
            text("SELECT status, last_error FROM sources WHERE id = :id"), {"id": source_id}
        )
    ).one()
    assert status == "attention"
    assert last_error is not None and "unreachable" in last_error.lower()

    decisions = (
        await session.execute(
            text("SELECT kind FROM audit_decisions WHERE kind LIKE 'connection_health_%'")
        )
    ).all()
    assert [row.kind for row in decisions] == ["connection_health_lost"]


async def test_repeated_failures_do_not_write_a_decision_every_time(
    session: AsyncSession, settings: Settings, source_id: uuid.UUID
) -> None:
    """Issue #360's own lesson: a check that runs every cycle must write the
    transition once, not once per cycle. Three consecutive failures against
    the same `attention` source must leave exactly one decisions row."""
    for _ in range(3):
        with pytest.raises(ConnectionUnreachable):
            await execute_connection_query(
                session,
                settings,
                source_id=source_id,
                engine="postgresql",
                host="127.0.0.1",
                port=1,
                database="orders",
                user="reader",
                password="whatever",
                query="SELECT 1",
            )
        await session.commit()

    decisions = (
        await session.execute(
            text("SELECT kind FROM audit_decisions WHERE kind LIKE 'connection_health_%'")
        )
    ).all()
    assert len(decisions) == 1


async def test_recovering_clears_attention_and_records_recovery(
    session: AsyncSession,
    settings: Settings,
    database_url: str,
    read_only_role: str,
    source_id: uuid.UUID,
) -> None:
    host, port, database = _target(database_url)
    with pytest.raises(ConnectionUnreachable):
        await execute_connection_query(
            session,
            settings,
            source_id=source_id,
            engine="postgresql",
            host="127.0.0.1",
            port=1,
            database="orders",
            user="reader",
            password="whatever",
            query="SELECT 1",
        )
    await session.commit()

    await execute_connection_query(
        session,
        settings,
        source_id=source_id,
        engine="postgresql",
        host=host,
        port=port,
        database=database,
        user=read_only_role,
        password="exec-test-pw",
        query="SELECT id FROM sources",
    )
    await session.commit()

    status, last_error, last_healthy_at = (
        await session.execute(
            text("SELECT status, last_error, last_healthy_at FROM sources WHERE id = :id"),
            {"id": source_id},
        )
    ).one()
    assert status == "ready"
    assert last_error is None
    assert last_healthy_at is not None

    kinds = (
        await session.execute(
            text(
                "SELECT kind FROM audit_decisions WHERE kind LIKE 'connection_health_%' "
                "ORDER BY occurred_at"
            )
        )
    ).all()
    assert [row.kind for row in kinds] == ["connection_health_lost", "connection_health_recovered"]
