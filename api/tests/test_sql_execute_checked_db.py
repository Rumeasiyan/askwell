"""`execute_checked_sandbox_query`/`execute_checked_connection_query` against
real Postgres. `M4-SQL-BE-108a`.

What only a real database can prove: rows come back, truncation is flagged
correctly against the row limit `M4-SQL-VAL-105` would have injected, a
statement timeout is reported rather than hanging, and every successful run
is recorded to `audit_interactions` under its own `sql_execute` kind,
distinct from `sql_query` and `sql_dry_run`.
"""

import json
from collections.abc import AsyncIterator

import psycopg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory
from askwell.sandbox import OWNER_ROLE, create_database, drop_database, generate_name
from askwell.sql.execute import execute_checked_sandbox_query
from askwell.sql_execute import StatementTimedOut
from tests.conftest_sandbox import READONLY_PASSWORD, _require, role_url

pytestmark = pytest.mark.requires_db


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
        conn.execute("INSERT INTO t VALUES (1), (2), (3)")
    try:
        yield name
    finally:
        await drop_database(sandbox_session, sandbox_admin_url, name)
        await sandbox_session.commit()


async def _interaction_rows_for(session: AsyncSession, query: str) -> list[dict[str, object]]:
    """Every `sql_execute` interaction recorded for one exact query text.

    Filtered by query rather than "everything recorded so far": this suite
    shares one session-scoped application database across every test in the
    file (`docs/BRAIN.md`'s own test-isolation shape for `requires_db`
    suites), and unlike `askwell.sql.dry_run`'s own `sql_dry_run` kind —
    which records only a failure — every successful execution here writes a
    row, so an ordinal `rows[0]` would silently pick up an earlier test's
    own record instead of this one's.
    """
    rows = (
        await session.execute(
            text(
                "SELECT payload FROM audit_interactions "
                "WHERE kind = 'sql_execute' AND payload ->> 'query' = :query ORDER BY id"
            ),
            {"query": query},
        )
    ).all()
    return [row[0] if isinstance(row[0], dict) else json.loads(row[0]) for row in rows]


async def test_a_query_returns_rows_and_is_recorded(
    sandbox_session: AsyncSession, sandbox_settings: Settings, loaded_database: str
) -> None:
    query = "SELECT x FROM t ORDER BY x"
    result = await execute_checked_sandbox_query(
        sandbox_session, sandbox_settings, database=loaded_database, query=query, row_limit=1000
    )
    await sandbox_session.commit()

    assert result.columns == ("x",)
    assert result.rows == ((1,), (2,), (3,))
    assert result.row_count == 3
    assert result.truncated is False

    rows = await _interaction_rows_for(sandbox_session, query)
    assert len(rows) == 1
    assert rows[0]["rows"] == 3
    assert rows[0]["truncated"] is False


async def test_zero_rows_is_a_result_not_a_failure(
    sandbox_session: AsyncSession, sandbox_settings: Settings, loaded_database: str
) -> None:
    query = "SELECT x FROM t WHERE x > 100"
    result = await execute_checked_sandbox_query(
        sandbox_session, sandbox_settings, database=loaded_database, query=query, row_limit=1000
    )
    await sandbox_session.commit()

    assert result.row_count == 0
    assert result.rows == ()

    rows = await _interaction_rows_for(sandbox_session, query)
    assert rows[0]["rows"] == 0


async def test_a_result_at_the_row_limit_is_flagged_truncated(
    sandbox_session: AsyncSession, sandbox_settings: Settings, loaded_database: str
) -> None:
    """`>=`, not `==` — reaching the limit exactly is indistinguishable from
    a result that has more, `askwell.sql.limit.result_was_truncated`'s own
    edge case, exercised here through the caller that actually uses it."""
    query = "SELECT x FROM t ORDER BY x LIMIT 2"
    result = await execute_checked_sandbox_query(
        sandbox_session, sandbox_settings, database=loaded_database, query=query, row_limit=2
    )
    await sandbox_session.commit()

    assert result.row_count == 2
    assert result.truncated is True

    rows = await _interaction_rows_for(sandbox_session, query)
    assert rows[0]["truncated"] is True


async def test_a_statement_timeout_is_reported_not_hung(
    sandbox_session: AsyncSession, sandbox_settings: Settings, loaded_database: str
) -> None:
    query = "SELECT pg_sleep(5), x FROM t"
    with pytest.raises(StatementTimedOut):
        await execute_checked_sandbox_query(
            sandbox_session, sandbox_settings, database=loaded_database, query=query, row_limit=1000
        )
    await sandbox_session.commit()

    # `sql_execute.execute_sandbox_query` already records the timeout to
    # `audit_decisions` — this module's own `sql_execute` interaction is
    # only for a query that actually returned a result (module docstring),
    # so nothing new should appear here.
    assert await _interaction_rows_for(sandbox_session, query) == []
