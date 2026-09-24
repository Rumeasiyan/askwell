"""Reset, run as the role Askwell actually connects as. Ticket `M7-DATA-BE-159a`.

Issue #523 shipped because the first reset's tests connected as the database
owner, a superuser who bypasses every grant C6 rests on — so a `TRUNCATE`
`askwell_app` could never run passed. Every reset here therefore runs through
`app_database_url`. The owner connection only seeds rows and cleans up.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from askwell import reset
from askwell import session as sessions
from askwell.app import create_app
from askwell.audit import Store, record, verify
from askwell.config import Settings

pytestmark = pytest.mark.requires_db

EVERY_TABLE = (*reset.TABLES, *reset.AUDIT_TABLES)


def _async(url: str) -> str:
    return url.replace("postgresql://", "postgresql+psycopg://", 1)


async def _truncate_everything(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE {', '.join(EVERY_TABLE)} CASCADE"))


@pytest_asyncio.fixture
async def owner(database_url: str) -> AsyncIterator[AsyncEngine]:
    """The superuser owner. Seeding and cleanup only — never a reset."""
    engine = create_async_engine(_async(database_url))
    await _truncate_everything(engine)
    yield engine
    await _truncate_everything(engine)
    await engine.dispose()


@pytest_asyncio.fixture
async def factory(
    owner: AsyncEngine, app_database_url: str
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Sessions as `askwell_app`, restricted exactly as at runtime."""
    engine = create_async_engine(_async(app_database_url))
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def _seed(owner: AsyncEngine, factory: async_sessionmaker[AsyncSession]) -> None:
    async with owner.begin() as connection:
        await connection.execute(text("INSERT INTO roots (path) VALUES ('/home/me/contracts')"))
        await connection.execute(
            text("INSERT INTO sources (kind, name) VALUES ('file', 'contracts')")
        )
        conversation = uuid.uuid4()
        await connection.execute(
            text("INSERT INTO conversations (id) VALUES (:id)"), {"id": conversation}
        )
        await connection.execute(
            text(
                "INSERT INTO messages (conversation_id, role, content) "
                "VALUES (:id, 'user', 'what is the notice period?')"
            ),
            {"id": conversation},
        )
        await connection.execute(
            text("INSERT INTO settings (key, value) VALUES ('passphrase_hash', 'x')")
        )
    # The audit rows go through the real writer, as the app writes them.
    async with factory() as session:
        await record(session, Store.DECISIONS, "source_added", {"name": "contracts"})
        await record(session, Store.INTERACTIONS, "question_asked", {"q": "notice period"})
        await session.commit()


async def _counts(owner: AsyncEngine) -> dict[str, int]:
    async with owner.connect() as connection:
        return {
            table: (await connection.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()
            for table in EVERY_TABLE
        }


def _refused(error: DBAPIError) -> bool:
    return getattr(error.orig, "sqlstate", None) == "42501"  # insufficient_privilege


# --- reset completes, under the app's own role -------------------------------


async def test_every_table_in_the_schema_is_one_reset_clears(owner: AsyncEngine) -> None:
    """A table added later and not named here would survive every reset."""
    async with owner.connect() as connection:
        rows = await connection.execute(
            text(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
                "AND tablename <> 'alembic_version'"
            )
        )
        schema = {str(row[0]) for row in rows}
    assert schema == set(EVERY_TABLE)


async def test_reset_as_the_app_role_empties_every_table_audit_included(
    owner: AsyncEngine, factory: async_sessionmaker[AsyncSession]
) -> None:
    await _seed(owner, factory)
    seeded = await _counts(owner)
    assert seeded["audit_decisions"] == 1 and seeded["audit_interactions"] == 1

    async with factory() as session:
        before = await reset.perform(session)
        await session.commit()

    assert before == seeded
    after = await _counts(owner)
    # The one survivor is the record that the reset happened (next test).
    assert after == {table: 0 for table in EVERY_TABLE} | {"audit_decisions": 1}


async def test_the_reset_is_recorded_as_the_genesis_of_a_new_intact_chain(
    owner: AsyncEngine, factory: async_sessionmaker[AsyncSession]
) -> None:
    await _seed(owner, factory)

    async with factory() as session:
        before = await reset.perform(session)
        await session.commit()

    async with factory() as session:
        rows = (
            await session.execute(text("SELECT kind, payload, prev_hash FROM audit_decisions"))
        ).all()
        assert [row[0] for row in rows] == [reset.RESET_PERFORMED]
        assert rows[0][1]["counts"]["roots"] == before["roots"] == 1
        assert rows[0][2] == "0" * 64
        assert (await verify(session, Store.DECISIONS)).intact
        assert (await verify(session, Store.INTERACTIONS)).intact


async def test_a_reset_that_fails_partway_removes_nothing(
    owner: AsyncEngine,
    factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One transaction. An ordinary `DELETE` of an audit table, appended to the
    list, is refused after every other table has been deleted — and the
    rollback puts all of them back."""
    await _seed(owner, factory)
    seeded = await _counts(owner)
    monkeypatch.setattr(reset, "TABLES", (*reset.TABLES, "audit_interactions"))

    async with factory() as session:
        with pytest.raises(DBAPIError) as refused:
            await reset.perform(session)
        await session.rollback()

    assert _refused(refused.value)
    assert await _counts(owner) == seeded


async def test_a_row_a_concurrent_writer_commits_mid_reset_does_not_survive_it(
    owner: AsyncEngine, factory: async_sessionmaker[AsyncSession]
) -> None:
    """A worker inserting while reset runs. A `DELETE` cannot see a row
    another transaction has not committed, and does not wait for it — so
    without the table locks the row commits after the `DELETE` has passed and
    survives a reset that reported success."""
    await _seed(owner, factory)
    async with factory() as writer:
        await writer.execute(text("INSERT INTO roots (path) VALUES ('/home/me/late')"))

        async def run_reset() -> None:
            async with factory() as session:
                await reset.perform(session)
                await session.commit()

        resetting = asyncio.create_task(run_reset())
        await asyncio.sleep(0.5)
        # Reset must be waiting on the writer, not finished around it.
        assert not resetting.done()
        await writer.commit()
    await asyncio.wait_for(resetting, timeout=10)

    assert (await _counts(owner))["roots"] == 0


# --- nothing else can -------------------------------------------------------


@pytest.mark.parametrize("table", reset.AUDIT_TABLES)
@pytest.mark.parametrize(
    "statement", ["UPDATE {} SET kind = 'tampered'", "DELETE FROM {}", "TRUNCATE {}"]
)
async def test_an_ordinary_app_path_still_cannot_rewrite_an_audit_table(
    owner: AsyncEngine, factory: async_sessionmaker[AsyncSession], table: str, statement: str
) -> None:
    await _seed(owner, factory)
    async with factory() as session:
        with pytest.raises(DBAPIError) as refused:
            await session.execute(text(statement.format(table)))
        await session.rollback()
    assert _refused(refused.value)
    assert (await _counts(owner))[table] == 1


async def test_the_reset_function_called_directly_is_refused(
    owner: AsyncEngine, factory: async_sessionmaker[AsyncSession]
) -> None:
    await _seed(owner, factory)
    async with factory() as session:
        with pytest.raises(DBAPIError) as refused:
            await session.execute(text("SELECT askwell_reset_audit()"))
        await session.rollback()
    assert _refused(refused.value)
    assert "reset recorded in this transaction" in str(refused.value)
    assert (await _counts(owner))["audit_decisions"] == 1


async def test_a_reset_request_from_an_earlier_transaction_does_not_authorise_it(
    owner: AsyncEngine, factory: async_sessionmaker[AsyncSession]
) -> None:
    """A committed request is history, not permission — otherwise one reset
    would leave the door open for any later caller."""
    await _seed(owner, factory)
    async with factory() as session:
        await record(session, Store.DECISIONS, reset.RESET_REQUESTED, {"counts": {}})
        await session.commit()

    async with factory() as session:
        with pytest.raises(DBAPIError) as refused:
            await session.execute(text("SELECT askwell_reset_audit()"))
        await session.rollback()
    assert _refused(refused.value)
    assert (await _counts(owner))["audit_decisions"] == 2


async def test_a_reset_request_followed_by_another_record_does_not_authorise_it(
    owner: AsyncEngine, factory: async_sessionmaker[AsyncSession]
) -> None:
    """The request must be the newest record, so nothing can be written after
    the recorded intent and then destroyed along with it."""
    await _seed(owner, factory)
    async with factory() as session:
        await record(session, Store.DECISIONS, reset.RESET_REQUESTED, {"counts": {}})
        await record(session, Store.DECISIONS, "source_added", {"name": "late"})
        with pytest.raises(DBAPIError) as refused:
            await session.execute(text("SELECT askwell_reset_audit()"))
        await session.rollback()
    assert _refused(refused.value)


async def test_only_the_app_role_may_call_it_and_its_owner_can_touch_nothing_else(
    owner: AsyncEngine,
) -> None:
    """`askwell_readonly` runs model-generated SQL (C2) and must not reach it;
    the definer role is scoped to the two audit tables alone."""
    async with owner.connect() as connection:

        async def scalar(sql: str) -> object:
            return (await connection.execute(text(sql))).scalar_one()

        function = "'askwell_reset_audit()'"
        assert await scalar(f"SELECT has_function_privilege('askwell_app', {function}, 'EXECUTE')")
        assert not await scalar(
            f"SELECT has_function_privilege('askwell_readonly', {function}, 'EXECUTE')"
        )
        assert not await scalar(
            "SELECT bool_or(grantee = 'PUBLIC') FROM information_schema.routine_privileges "
            "WHERE routine_name = 'askwell_reset_audit'"
        )
        assert (
            await scalar(
                "SELECT pg_get_userbyid(proowner) FROM pg_proc "
                "WHERE proname = 'askwell_reset_audit'"
            )
            == "askwell_audit_reset"
        )
        for table in reset.TABLES:
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE"):
                assert not await scalar(
                    f"SELECT has_table_privilege('askwell_audit_reset', '{table}', '{privilege}')"
                ), f"askwell_audit_reset holds {privilege} on {table}"


# --- HTTP -------------------------------------------------------------------


@pytest.fixture
def client(
    settings: Settings, app_database_url: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> TestClient:
    async def fixed_secret(_db: object) -> bytes:
        return b"0" * 32

    monkeypatch.setattr(sessions, "secret", fixed_secret)
    monkeypatch.setattr("askwell.middleware.sessions.secret", fixed_secret)

    built = tmp_path / "out"
    built.mkdir()
    (built / "index.html").write_text("<!doctype html><title>Askwell</title>")
    return TestClient(
        create_app(
            settings.model_copy(
                update={
                    "database_url": SecretStr(app_database_url),
                    "web_assets_dir": built,
                    "trace_dir": tmp_path / "traces",
                }
            )
        )
    )


def test_performing_a_reset_requires_a_session(owner: AsyncEngine, client: TestClient) -> None:
    with client:
        response = client.post("/reset")
    assert response.status_code == 401


async def test_post_reset_succeeds_as_the_app_role(
    owner: AsyncEngine, factory: async_sessionmaker[AsyncSession], client: TestClient
) -> None:
    await _seed(owner, factory)
    with client:
        client.get("/", headers={"accept": "text/html"})
        response = client.post("/reset")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["counts"]["audit_interactions"] == 1
    assert body["total"] == sum(body["counts"].values())
    after = await _counts(owner)
    assert after["audit_interactions"] == 0 and after["roots"] == 0
