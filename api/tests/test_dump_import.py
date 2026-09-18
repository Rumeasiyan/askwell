"""Loading a PostgreSQL dump into its own sandbox database. `M4-DUMP-ING-088`.

`_load_blocking`'s streaming and error-capture logic is pure Python around a
subprocess and is tested here against a fake `psql` on `PATH` — no database,
no network (C1). Everything that depends on what the sandbox instance's real
roles can and cannot do (`import_dump` end to end, the owner-seal fix for
issue #330, introspection) needs the real, separate instance `test_sandbox.py`
does, so those are `requires_db`.
"""

import os
import stat
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import psycopg
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from askwell import dump_import
from askwell.config import Settings
from askwell.dump_import import DumpImportFailed, _load_blocking, create_dump_source, import_dump
from askwell.sandbox import create_database, drop_database, generate_name, owner_url

# --- _load_blocking, against a fake `psql` -----------------------------------


def _fake_psql(tmp_path: Path, script: str) -> Path:
    """A fake `psql` on its own directory, added to `PATH` for the test."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    fake = bin_dir / "psql"
    fake.write_text(f"#!/bin/sh\n{script}\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    return bin_dir


def test_load_blocking_reports_progress_and_returns_bytes_fed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bin_dir = _fake_psql(tmp_path, "cat >/dev/null\nexit 0")
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")

    dump_path = tmp_path / "dump.sql"
    content = b"-- pretend dump\n" * 200
    dump_path.write_bytes(content)

    reports: list[tuple[int, int]] = []
    done = _load_blocking(
        "postgresql://ignored/ignored", dump_path, lambda d, t: reports.append((d, t))
    )

    assert done == len(content)
    assert reports[-1] == (len(content), len(content))
    assert all(total == len(content) for _, total in reports)


def test_load_blocking_raises_with_stderr_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bin_dir = _fake_psql(tmp_path, 'echo "syntax error at or near \\"GARBLE\\"" 1>&2\nexit 3')
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")

    dump_path = tmp_path / "broken.sql"
    dump_path.write_bytes(b"GARBLE NOT SQL;\n")

    with pytest.raises(DumpImportFailed, match="GARBLE"):
        _load_blocking("postgresql://ignored/ignored", dump_path, None)


def test_load_blocking_names_the_exit_status_when_psql_says_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bin_dir = _fake_psql(tmp_path, "exit 2")
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")

    dump_path = tmp_path / "broken.sql"
    dump_path.write_bytes(b"anything\n")

    with pytest.raises(DumpImportFailed, match="status 2"):
        _load_blocking("postgresql://ignored/ignored", dump_path, None)


# --- against a real, separate sandbox instance and Askwell's own database ----

TABLES = "sources, audit_decisions"


@pytest_asyncio.fixture
async def factory(database_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    async_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_async_engine(async_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as opened:
        await opened.execute(text(f"TRUNCATE {TABLES} CASCADE"))
        await opened.commit()
    yield sessions
    async with sessions() as opened:
        await opened.execute(text(f"TRUNCATE {TABLES} CASCADE"))
        await opened.commit()
    await engine.dispose()


@pytest.fixture
def dump_settings(sandbox_admin_url: str) -> Settings:
    return Settings(
        database_url="postgresql://x:x@127.0.0.1:1/askwell",  # type: ignore[arg-type]
        sandbox_database_url=sandbox_admin_url,  # type: ignore[arg-type]
        sandbox_owner_password=os.environ["TEST_SANDBOX_OWNER_PASSWORD"],  # type: ignore[arg-type]
    )


async def _make_source(factory: async_sessionmaker[AsyncSession], dump_path: Path) -> uuid.UUID:
    async with factory() as session:
        source_id = await create_dump_source(session, "a colleague's export", str(dump_path))
        await session.commit()
    return source_id


@pytest.mark.requires_db
async def test_import_dump_loads_and_introspects_a_valid_dump(
    factory: async_sessionmaker[AsyncSession],
    dump_settings: Settings,
    tmp_path: Path,
) -> None:
    dump_path = tmp_path / "good.sql"
    dump_path.write_text(
        "CREATE TABLE widgets (id integer primary key, name text);\n"
        "INSERT INTO widgets VALUES (1, 'left-handed smoke shifter');\n"
    )
    source_id = await _make_source(factory, dump_path)

    tables = await import_dump(factory, dump_settings, source_id, dump_path)

    assert tables == ["widgets"]

    async with factory() as session:
        row = (
            await session.execute(
                text("SELECT status, sandbox_db, last_error FROM sources WHERE id = :id"),
                {"id": source_id},
            )
        ).one()
        assert row[0] == "ready"
        assert row[1] is not None
        assert row[2] is None

        started = await session.execute(
            text(
                "SELECT 1 FROM audit_decisions WHERE kind = 'dump_import_started' "
                "AND payload->>'source_id' = :id"
            ),
            {"id": str(source_id)},
        )
        assert started.first() is not None

        succeeded = await session.execute(
            text(
                "SELECT payload FROM audit_decisions WHERE kind = 'dump_import_succeeded' "
                "AND payload->>'source_id' = :id"
            ),
            {"id": str(source_id)},
        )
        payload = succeeded.first()
        assert payload is not None
        assert payload[0]["tables"] == ["widgets"]

    admin_url = dump_settings.sandbox_database_url.get_secret_value()
    try:
        with pytest.raises(psycopg.OperationalError):
            psycopg.connect(
                owner_url(admin_url, row[1], os.environ["TEST_SANDBOX_OWNER_PASSWORD"]),
                autocommit=True,
            )
    finally:
        async with factory() as session:
            await drop_database(session, admin_url, row[1])
            await session.commit()


@pytest.mark.requires_db
async def test_import_dump_drops_the_database_and_reports_the_reason_on_failure(
    factory: async_sessionmaker[AsyncSession],
    dump_settings: Settings,
    tmp_path: Path,
) -> None:
    dump_path = tmp_path / "broken.sql"
    dump_path.write_text("THIS IS NOT SQL AT ALL;\n")
    source_id = await _make_source(factory, dump_path)

    with pytest.raises(DumpImportFailed):
        await import_dump(factory, dump_settings, source_id, dump_path)

    async with factory() as session:
        row = (
            await session.execute(
                text("SELECT status, sandbox_db, last_error FROM sources WHERE id = :id"),
                {"id": source_id},
            )
        ).one()
        assert row[0] == "attention"
        assert row[1] is None
        assert row[2]

        failed = await session.execute(
            text(
                "SELECT 1 FROM audit_decisions WHERE kind = 'dump_import_failed' "
                "AND payload->>'source_id' = :id"
            ),
            {"id": str(source_id)},
        )
        assert failed.first() is not None


@pytest.mark.requires_db
async def test_a_second_import_cannot_reach_the_first_through_the_shared_owner_role(
    factory: async_sessionmaker[AsyncSession],
    dump_settings: Settings,
    tmp_path: Path,
) -> None:
    """Issue #330: the owner role is sealed off a database the moment its
    load finishes, so the role that runs the *next* dump's content cannot
    still see the first one."""
    first_dump = tmp_path / "first.sql"
    first_dump.write_text("CREATE TABLE secrets (x int); INSERT INTO secrets VALUES (1);\n")
    first_source = await _make_source(factory, first_dump)
    await import_dump(factory, dump_settings, first_source, first_dump)

    admin_url = dump_settings.sandbox_database_url.get_secret_value()
    async with factory() as session:
        first_db = (
            await session.execute(
                text("SELECT sandbox_db FROM sources WHERE id = :id"), {"id": first_source}
            )
        ).scalar_one()

    second_dump = tmp_path / "second.sql"
    second_dump.write_text("CREATE TABLE t (x int);\n")
    second_source = await _make_source(factory, second_dump)
    try:
        await import_dump(factory, dump_settings, second_source, second_dump)

        # The role that just ran the second dump's content cannot connect to
        # the first dump's database at all — not "cannot see its tables",
        # cannot open a session to it.
        with pytest.raises(psycopg.OperationalError):
            psycopg.connect(
                owner_url(admin_url, first_db, os.environ["TEST_SANDBOX_OWNER_PASSWORD"]),
                autocommit=True,
            )
    finally:
        async with factory() as session:
            await drop_database(session, admin_url, first_db)
            second_db = (
                await session.execute(
                    text("SELECT sandbox_db FROM sources WHERE id = :id"),
                    {"id": second_source},
                )
            ).scalar_one()
            await drop_database(session, admin_url, second_db)
            await session.commit()


@pytest.mark.requires_db
async def test_reclaim_interrupted_drops_a_database_left_mid_load(
    factory: async_sessionmaker[AsyncSession],
    sandbox_admin_url: str,
) -> None:
    """The exact state a killed worker leaves behind: `sources.sandbox_db` set,
    `status = 'indexing'`, and nobody left to finish the load."""
    name = generate_name()
    async with factory() as session:
        await create_database(session, sandbox_admin_url, name)
        source_id = uuid.uuid4()
        await session.execute(
            text(
                "INSERT INTO sources (id, kind, name, sandbox_db, status) "
                "VALUES (:id, 'dump', 'interrupted', :db, 'indexing')"
            ),
            {"id": source_id, "db": name},
        )
        await session.commit()

    async with factory() as session:
        reclaimed = await dump_import.reclaim_interrupted(session, sandbox_admin_url)
        await session.commit()

    assert source_id in reclaimed

    async with factory() as session:
        row = (
            await session.execute(
                text("SELECT status, sandbox_db FROM sources WHERE id = :id"), {"id": source_id}
            )
        ).one()
        assert row[0] == "attention"
        assert row[1] is None

    from askwell.sandbox import known_databases

    assert name not in known_databases(sandbox_admin_url)


@pytest.mark.requires_db
async def test_owner_url_only_ever_names_a_generated_database(sandbox_admin_url: str) -> None:
    from askwell.sandbox import InvalidSandboxName

    with pytest.raises(InvalidSandboxName):
        owner_url(sandbox_admin_url, "postgres", "whatever")
