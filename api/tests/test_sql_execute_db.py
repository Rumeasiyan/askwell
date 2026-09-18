"""`execute_sandbox_query` against a real, separate sandbox instance.
`M4-SQL-DB-107`.

The two things that can only be proven against a real Postgres: the readonly
role cannot write when executing through this module (not just the driver
directly — `test_sandbox.py::test_readonly_cannot_write` already proves the
role itself; this proves the module built on it behaves the same way), and a
query that outruns the configured timeout is cancelled and reported as
`StatementTimedOut`, with a decisions record and the local counter both
following.
"""

from collections.abc import AsyncIterator

import psycopg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory
from askwell.sandbox import OWNER_ROLE, create_database, drop_database, generate_name
from askwell.sql_execute import StatementTimedOut, execute_sandbox_query
from tests.conftest_sandbox import READONLY_PASSWORD, _require, role_url

pytestmark = pytest.mark.requires_db


@pytest.fixture
async def settings(app_database_url: str, sandbox_admin_url: str) -> Settings:
    # The real readonly password, not a placeholder: unlike `test_sandbox.py`'s
    # `session` fixture, `execute_sandbox_query` actually connects as this
    # role — `askwell.sandbox.readonly_url` builds the DSN from this value —
    # so a placeholder here would fail authentication rather than prove
    # anything about the role's privileges.
    return Settings(
        database_url=app_database_url,  # type: ignore[arg-type]
        sandbox_database_url=sandbox_admin_url,  # type: ignore[arg-type]
        sandbox_owner_password="x",  # type: ignore[arg-type]
        sandbox_readonly_password=_require(READONLY_PASSWORD),  # type: ignore[arg-type]
        sql_statement_timeout_seconds=1,
    )


@pytest.fixture
async def session(settings: Settings) -> AsyncIterator[AsyncSession]:
    engine: AsyncEngine = build_engine(settings)
    try:
        async with session_factory(engine)() as opened:
            yield opened
    finally:
        await engine.dispose()


@pytest.fixture
async def loaded_database(sandbox_admin_url: str, session: AsyncSession) -> AsyncIterator[str]:
    name = generate_name()
    await create_database(session, sandbox_admin_url, name)
    await session.commit()
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
        await drop_database(session, sandbox_admin_url, name)
        await session.commit()


async def test_execute_sandbox_query_reads_rows(
    session: AsyncSession, settings: Settings, loaded_database: str
) -> None:
    result = await execute_sandbox_query(
        session, settings, database=loaded_database, query="SELECT x FROM t ORDER BY x"
    )
    assert result.columns == ("x",)
    assert result.rows == ((1,), (2,))


async def test_execute_sandbox_query_cannot_write(
    session: AsyncSession, settings: Settings, loaded_database: str
) -> None:
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        await execute_sandbox_query(
            session, settings, database=loaded_database, query="INSERT INTO t VALUES (3)"
        )


async def test_execute_sandbox_query_times_out(
    session: AsyncSession, settings: Settings, loaded_database: str
) -> None:
    with pytest.raises(StatementTimedOut) as excinfo:
        await execute_sandbox_query(
            session, settings, database=loaded_database, query="SELECT pg_sleep(5)"
        )
    assert "pg_sleep" in excinfo.value.query


async def test_a_timeout_writes_a_decisions_record(
    session: AsyncSession, settings: Settings, loaded_database: str
) -> None:
    with pytest.raises(StatementTimedOut):
        await execute_sandbox_query(
            session, settings, database=loaded_database, query="SELECT pg_sleep(5)"
        )
    await session.commit()

    result = await session.execute(
        text(
            "SELECT payload FROM audit_decisions WHERE kind = 'sql_statement_timeout' "
            "AND payload->>'query' = :query ORDER BY occurred_at DESC LIMIT 1"
        ),
        {"query": "SELECT pg_sleep(5)"},
    )
    row = result.first()
    assert row is not None
    assert row[0]["source_kind"] == "sandbox"
    assert row[0]["timeout_seconds"] == 1
