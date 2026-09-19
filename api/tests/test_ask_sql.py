"""`_run_sql_turn` — the checked path wired into `askwell.ask`. `M4-SQL-BE-108a`.

Issue #391's own named gap: nothing exercised `askwell.agent.sql_generate` →
`askwell.sql.validate` → `askwell.sql.limit` → `askwell.sql.dry_run` →
`askwell.sql.execute` chained together the way `_run_sql_turn` actually
calls them. This drives that function directly, against a real sandbox
database, with only the model call faked — the one step nothing here can
run for real.
"""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import psycopg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from askwell import ask as ask_module
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory
from askwell.memory import write_schema_note
from askwell.sandbox import OWNER_ROLE, create_database, drop_database, generate_name
from tests.conftest_sandbox import READONLY_PASSWORD, _require, role_url

pytestmark = pytest.mark.requires_db


@dataclass
class _Completion:
    text: str


@dataclass
class _FakeInferenceClient:
    text: str

    async def generate(
        self, _prompt: str, *, max_tokens: int = 512, temperature: float = 0.2
    ) -> _Completion:
        return _Completion(text=self.text)


@pytest.fixture
async def sandbox_settings(app_database_url: str, sandbox_admin_url: str) -> Settings:
    return Settings(
        database_url=app_database_url,  # type: ignore[arg-type]
        sandbox_database_url=sandbox_admin_url,  # type: ignore[arg-type]
        sandbox_owner_password="x",  # type: ignore[arg-type]
        sandbox_readonly_password=_require(READONLY_PASSWORD),  # type: ignore[arg-type]
        sql_statement_timeout_seconds=5,
    )


@pytest.fixture
async def sandbox_session(
    sandbox_settings: Settings, database_url: str
) -> AsyncIterator[AsyncSession]:
    # `askwell_app` (`sandbox_settings.database_url`) has no `TRUNCATE` grant
    # on these tables — the same restricted-role shape C6 relies on for the
    # audit stores — so this truncates as the owning role the migrations
    # themselves ran as, the same split `test_sql_generate.py`'s own
    # `session`/`async_url` fixtures draw between the two roles.
    with psycopg.connect(database_url, autocommit=True) as admin:
        admin.execute("TRUNCATE sources, schema_notes, audit_interactions CASCADE")

    engine: AsyncEngine = build_engine(sandbox_settings)
    try:
        async with session_factory(engine)() as opened:
            yield opened
            await opened.rollback()
    finally:
        await engine.dispose()
        # Tests here commit rows into `sources` (a real dump needs a real,
        # committed source row to join against). Truncating only before
        # each test leaves those rows for whichever `requires_db` test runs
        # next in the same database — `test_audit_chain.py`'s row-count
        # assertions saw exactly that leak.
        with psycopg.connect(database_url, autocommit=True) as admin:
            admin.execute("TRUNCATE sources, schema_notes, audit_interactions CASCADE")


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
        conn.execute("CREATE TABLE invoices (id int, status text)")
        conn.execute("INSERT INTO invoices VALUES (1, 'unpaid'), (2, 'paid'), (3, 'unpaid')")
    try:
        yield name
    finally:
        await drop_database(sandbox_session, sandbox_admin_url, name)
        await sandbox_session.commit()


async def _dump_source(session: AsyncSession, *, sandbox_db: str) -> uuid.UUID:
    source_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO sources (id, kind, name, sandbox_db, status) "
            "VALUES (:id, 'dump', 'invoices', :sandbox_db, 'ready')"
        ),
        {"id": source_id, "sandbox_db": sandbox_db},
    )
    await write_schema_note(
        session,
        source_id=source_id,
        table_name="invoices",
        column_name=None,
        description="Table invoices. Columns: id, status.",
        origin="inferred",
    )
    return source_id


async def test_no_database_source_falls_through_to_document_retrieval(
    sandbox_session: AsyncSession, sandbox_settings: Settings
) -> None:
    client = _FakeInferenceClient(text="SELECT 1")
    answer = await ask_module._run_sql_turn(
        sandbox_settings,
        sandbox_session,
        client,
        question="what is in the handbook?",
        source_id=None,
    )
    assert answer is None


async def test_executes_a_generated_query_and_returns_a_stored_result(
    sandbox_session: AsyncSession, sandbox_settings: Settings, loaded_database: str
) -> None:
    source_id = await _dump_source(sandbox_session, sandbox_db=loaded_database)
    await sandbox_session.commit()

    client = _FakeInferenceClient(text="SELECT id FROM invoices WHERE status = 'unpaid'")
    answer = await ask_module._run_sql_turn(
        sandbox_settings,
        sandbox_session,
        client,
        question="how many invoices are unpaid?",
        source_id=source_id,
    )
    await sandbox_session.commit()

    assert answer is not None
    assert answer.status == "completed"
    assert answer.sql_result is not None
    assert answer.sql_result["row_count"] == 2
    assert answer.sql_result["truncated"] is False
    assert answer.sql_result["columns"] == ["id"]
    assert sorted(row[0] for row in answer.sql_result["rows"]) == [1, 3]
    assert "2" in answer.text


async def test_zero_rows_is_reported_as_a_result_not_an_error(
    sandbox_session: AsyncSession, sandbox_settings: Settings, loaded_database: str
) -> None:
    source_id = await _dump_source(sandbox_session, sandbox_db=loaded_database)
    await sandbox_session.commit()

    client = _FakeInferenceClient(text="SELECT id FROM invoices WHERE status = 'overdue'")
    answer = await ask_module._run_sql_turn(
        sandbox_settings,
        sandbox_session,
        client,
        question="how many invoices are overdue?",
        source_id=source_id,
    )

    assert answer is not None
    assert answer.sql_result is not None
    assert answer.sql_result["row_count"] == 0
    assert answer.text == "No matching records."


async def test_a_write_disguised_as_a_read_is_rejected_with_no_stored_result(
    sandbox_session: AsyncSession,
    sandbox_settings: Settings,
    sandbox_admin_url: str,
    loaded_database: str,
) -> None:
    """C2: a candidate that does not pass `validate_query` is answered in
    plain language, never executed — `sql_result` stays `None`."""
    source_id = await _dump_source(sandbox_session, sandbox_db=loaded_database)
    await sandbox_session.commit()

    client = _FakeInferenceClient(
        text="WITH d AS (DELETE FROM invoices RETURNING *) SELECT * FROM d"
    )
    answer = await ask_module._run_sql_turn(
        sandbox_settings,
        sandbox_session,
        client,
        question="delete the paid invoices",
        source_id=source_id,
    )

    assert answer is not None
    assert answer.sql_result is None
    assert "could not safely run" in answer.text
    # `M4-RESULT-FE-110`: disclosure is unconditional — the rejected query
    # itself still travels in the trace step, since `sql_result` never will.
    rejected_query = "WITH d AS (DELETE FROM invoices RETURNING *) SELECT * FROM d"
    assert answer.trace_step["query"] == rejected_query
    assert ask_module._sql_query_disclosure(answer.trace_step) == {
        "query": rejected_query,
        "outcome": "rejected",
    }

    owner = role_url(
        sandbox_admin_url,
        role=OWNER_ROLE,
        password_env="TEST_SANDBOX_OWNER_PASSWORD",
        database=loaded_database,
    )
    with psycopg.connect(owner, autocommit=True) as conn:
        count = conn.execute("SELECT count(*) FROM invoices").fetchone()
        assert count is not None and count[0] == 3
