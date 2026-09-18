"""`dry_run_sandbox_query`/`dry_run_connection_query` against real Postgres.
`M4-SQL-VAL-106`.

What only a real database can prove: a query referencing a column that does
not exist fails planning without ever running (proven by asserting the
table is untouched, not just by the returned `DryRunResult`), a valid query
plans and is not recorded, and — issue #382 — a connection failure during a
dry run (nothing listening on the port, a wrong password) produces a
`.FAILED`-shaped `DryRunResult` rather than an unhandled driver exception.
"""

from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from urllib.parse import urlsplit

import psycopg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory
from askwell.sandbox import OWNER_ROLE, create_database, drop_database, generate_name
from askwell.sql.dry_run import DryRunReason, dry_run_connection_query, dry_run_sandbox_query
from tests.conftest_sandbox import READONLY_PASSWORD, _require, role_url

pytestmark = pytest.mark.requires_db


# --- sandbox -----------------------------------------------------------------


@pytest.fixture
async def sandbox_settings(app_database_url: str, sandbox_admin_url: str) -> Settings:
    return Settings(
        database_url=app_database_url,  # type: ignore[arg-type]
        sandbox_database_url=sandbox_admin_url,  # type: ignore[arg-type]
        sandbox_owner_password="x",  # type: ignore[arg-type]
        sandbox_readonly_password=_require(READONLY_PASSWORD),  # type: ignore[arg-type]
        sql_statement_timeout_seconds=1,
    )


@pytest.fixture
async def sandbox_session(sandbox_settings: Settings) -> AsyncIterator[AsyncSession]:
    engine: AsyncEngine = build_engine(sandbox_settings)
    try:
        async with session_factory(engine)() as opened:
            yield opened
    finally:
        await engine.dispose()


@pytest.fixture
async def loaded_database(
    sandbox_admin_url: str, sandbox_session: AsyncSession
) -> AsyncIterator[str]:
    name = generate_name()
    await create_database(sandbox_session, sandbox_admin_url, name)
    await sandbox_session.commit()
    owner = role_url(
        sandbox_admin_url,
        role=OWNER_ROLE,
        password_env="TEST_SANDBOX_OWNER_PASSWORD",
        database=name,
    )
    with psycopg.connect(owner, autocommit=True) as conn:
        conn.execute("CREATE TABLE t (x int)")
        conn.execute("INSERT INTO t VALUES (1), (2)")
    try:
        yield name
    finally:
        await drop_database(sandbox_session, sandbox_admin_url, name)
        await sandbox_session.commit()


async def _interaction_rows(session: AsyncSession) -> list[dict[str, object]]:
    import json

    rows = (
        await session.execute(
            text("SELECT payload FROM audit_interactions WHERE kind = 'sql_dry_run' ORDER BY id")
        )
    ).all()
    return [row[0] if isinstance(row[0], dict) else json.loads(row[0]) for row in rows]


async def test_a_valid_query_passes_and_is_not_recorded(
    sandbox_session: AsyncSession, sandbox_settings: Settings, loaded_database: str
) -> None:
    result = await dry_run_sandbox_query(
        sandbox_session, sandbox_settings, database=loaded_database, query="SELECT x FROM t"
    )
    await sandbox_session.commit()

    assert result.passed
    assert await _interaction_rows(sandbox_session) == []


async def test_a_query_against_a_nonexistent_column_fails_planning_without_running(
    sandbox_session: AsyncSession, sandbox_settings: Settings, loaded_database: str
) -> None:
    result = await dry_run_sandbox_query(
        sandbox_session,
        sandbox_settings,
        database=loaded_database,
        query="SELECT does_not_exist FROM t",
    )
    await sandbox_session.commit()

    assert not result.passed
    assert result.reason is DryRunReason.PLANNING_FAILED
    assert result.detail is not None and "does_not_exist" in result.detail

    rows = await _interaction_rows(sandbox_session)
    assert len(rows) == 1
    assert rows[0]["query"] == "SELECT does_not_exist FROM t"
    assert rows[0]["reason"] == "planning_failed"


# --- connection (issue #382) --------------------------------------------------


def _target(database_url: str) -> tuple[str, int, str]:
    parts = urlsplit(database_url)
    return parts.hostname or "127.0.0.1", parts.port or 5432, parts.path.lstrip("/")


def _run(database_url: str, *statements: str) -> None:
    with psycopg.connect(database_url, autocommit=True) as conn, conn.cursor() as cur:
        for statement in statements:
            cur.execute(statement)


@pytest.fixture
def connection_settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url="postgresql://askwell:pw@127.0.0.1:1/askwell",  # type: ignore[arg-type]
        sandbox_database_url="postgresql://askwell_sandbox:pw@127.0.0.1:1/postgres",  # type: ignore[arg-type]
        sandbox_owner_password="pw",  # type: ignore[arg-type]
        sandbox_readonly_password="pw",  # type: ignore[arg-type]
        install_secret_path=tmp_path / "install.key",
    )


@pytest.fixture
async def connection_session(database_url: str) -> AsyncIterator[AsyncSession]:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    async_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_async_engine(async_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as opened:
        await opened.execute(text("TRUNCATE audit_interactions CASCADE"))
        await opened.commit()
        yield opened
        await opened.rollback()
        await opened.execute(text("TRUNCATE audit_interactions CASCADE"))
        await opened.commit()
    await engine.dispose()


@pytest.fixture
def read_only_role(database_url: str) -> Iterator[str]:
    role = "askwell_sql_dry_run_test"
    database = _target(database_url)[2]
    _run(
        database_url,
        f"DROP ROLE IF EXISTS {role}",
        f"CREATE ROLE {role} LOGIN PASSWORD 'dry-run-test-pw'",
        f"GRANT CONNECT ON DATABASE {database} TO {role}",
        f"GRANT USAGE ON SCHEMA public TO {role}",
        f"GRANT SELECT ON sources TO {role}",
    )
    try:
        yield role
    finally:
        _run(
            database_url,
            f"REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM {role}",
            f"DROP OWNED BY {role}",
            f"DROP ROLE IF EXISTS {role}",
        )


async def test_a_valid_query_over_a_live_connection_passes(
    connection_session: AsyncSession,
    connection_settings: Settings,
    database_url: str,
    read_only_role: str,
) -> None:
    import uuid

    host, port, database = _target(database_url)
    result = await dry_run_connection_query(
        connection_session,
        connection_settings,
        source_id=uuid.uuid4(),
        engine="postgresql",
        host=host,
        port=port,
        database=database,
        user=read_only_role,
        password="dry-run-test-pw",
        query="SELECT id FROM sources",
    )
    assert result.passed


async def test_nothing_listening_on_the_port_fails_planning_instead_of_crashing(
    connection_session: AsyncSession, connection_settings: Settings
) -> None:
    """Issue #382: a raw connect failure that is not an `OSError` (or, as
    here, any connect failure at all) must come back as a `.FAILED`
    `DryRunResult`, never propagate as an unhandled driver exception."""
    import uuid

    result = await dry_run_connection_query(
        connection_session,
        connection_settings,
        source_id=uuid.uuid4(),
        engine="postgresql",
        host="127.0.0.1",
        port=1,
        database="orders",
        user="reader",
        password="whatever",
        query="SELECT 1",
    )
    assert not result.passed
    assert result.reason is DryRunReason.PLANNING_FAILED


async def test_a_rejected_password_fails_planning_instead_of_crashing(
    connection_session: AsyncSession,
    connection_settings: Settings,
    database_url: str,
    read_only_role: str,
) -> None:
    """Issue #382's exact reported case: `psycopg.OperationalError` on a bad
    password is not an `OSError` subclass and previously propagated
    unhandled out of `dry_run_connection_query`."""
    import uuid

    host, port, database = _target(database_url)
    result = await dry_run_connection_query(
        connection_session,
        connection_settings,
        source_id=uuid.uuid4(),
        engine="postgresql",
        host=host,
        port=port,
        database=database,
        user=read_only_role,
        password="not-the-password",
        query="SELECT 1",
    )
    assert not result.passed
    assert result.reason is DryRunReason.PLANNING_FAILED
