"""The sandbox Postgres instance. `M4-DUMP-DEPLOY-087`, C3.

Naming and validation are pure and run in every `scripts/dev.sh test`. What
`create_database`/`drop_database`/`reclaim_orphans` actually do can only be
proven against a real, separate Postgres instance — the whole point of this
ticket is what that instance's roles are structurally unable to do — so those
are `requires_db` and run only by `scripts/dev.sh test-db` against the real
`sandbox` service.
"""

import os
import uuid
from collections.abc import AsyncIterator

import psycopg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory
from askwell.sandbox import (
    OWNER_ROLE,
    PREFIX,
    READONLY_ROLE,
    InvalidSandboxName,
    create_database,
    drop_database,
    generate_name,
    known_databases,
    owner_url,
    reclaim_orphans,
    seal_owner,
)
from tests.conftest_sandbox import role_url

# --- naming and validation: no database needed ------------------------------


def test_generate_name_carries_the_prefix() -> None:
    name = generate_name()
    assert name.startswith(PREFIX)


def test_generate_name_is_unpredictable() -> None:
    assert generate_name() != generate_name()


@pytest.mark.parametrize(
    "bogus",
    [
        "postgres",
        "template1",
        "askwell",
        f"{PREFIX}not-hex",
        f"{PREFIX}{'a' * 31}",  # one short
        f"{PREFIX}{'a' * 33}",  # one long
        "'; DROP DATABASE postgres; --",
        f'{PREFIX}{uuid.uuid4().hex}"; DROP DATABASE postgres; --',
    ],
)
async def test_names_not_from_generate_name_are_refused(bogus: str, settings: Settings) -> None:
    """The check runs before any connection is attempted.

    So this needs no real database and no network (C1): an unroutable URL
    proves the point precisely because it is never dialled, and the session
    passed in is never used for the same reason.
    """
    unroutable = "postgresql://x:x@askwell-test.invalid:1/postgres"
    engine = build_engine(settings)
    try:
        async with session_factory(engine)() as session:
            with pytest.raises(InvalidSandboxName):
                await create_database(session, unroutable, bogus)
            with pytest.raises(InvalidSandboxName):
                await drop_database(session, unroutable, bogus)
    finally:
        await engine.dispose()


# --- against a real, separate instance ---------------------------------------


@pytest.fixture
async def session(app_database_url: str, sandbox_admin_url: str) -> AsyncIterator[AsyncSession]:
    """Askwell's own database, as the role Askwell actually connects as.

    Not the sandbox instance — `sandbox_admin_url` is a plain string fixture
    the test bodies pass to `create_database`/`drop_database` directly,
    because those two different Postgres instances is the whole point of C3.
    """
    settings = Settings(
        database_url=app_database_url,  # type: ignore[arg-type]
        sandbox_database_url=sandbox_admin_url,  # type: ignore[arg-type]
        sandbox_owner_password="x",  # type: ignore[arg-type]
    )
    engine: AsyncEngine = build_engine(settings)
    try:
        async with session_factory(engine)() as opened:
            yield opened
    finally:
        await engine.dispose()


@pytest.mark.requires_db
async def test_create_database_is_reachable_only_by_the_two_sandbox_roles(
    sandbox_admin_url: str, session: AsyncSession
) -> None:
    name = generate_name()
    await create_database(session, sandbox_admin_url, name)
    await session.commit()
    try:
        with psycopg.connect(
            role_url(
                sandbox_admin_url,
                role=OWNER_ROLE,
                password_env="TEST_SANDBOX_OWNER_PASSWORD",
                database=name,
            ),
            autocommit=True,
        ) as conn:
            assert conn.execute("SELECT 1").fetchone() == (1,)

        with psycopg.connect(
            role_url(
                sandbox_admin_url,
                role=READONLY_ROLE,
                password_env="TEST_SANDBOX_READONLY_PASSWORD",
                database=name,
            ),
            autocommit=True,
        ) as conn:
            assert conn.execute("SELECT 1").fetchone() == (1,)
    finally:
        await drop_database(session, sandbox_admin_url, name)
        await session.commit()


@pytest.mark.requires_db
async def test_create_database_writes_a_decisions_record(
    sandbox_admin_url: str, session: AsyncSession
) -> None:
    name = generate_name()
    await create_database(session, sandbox_admin_url, name)
    await session.commit()
    try:
        result = await session.execute(
            text(
                "SELECT payload FROM audit_decisions WHERE kind = "
                "'sandbox_database_created' AND payload->>'database' = :name"
            ),
            {"name": name},
        )
        assert result.first() is not None
    finally:
        await drop_database(session, sandbox_admin_url, name)
        await session.commit()


@pytest.mark.requires_db
async def test_drop_database_writes_a_decisions_record(
    sandbox_admin_url: str, session: AsyncSession
) -> None:
    name = generate_name()
    await create_database(session, sandbox_admin_url, name)
    await session.commit()
    await drop_database(session, sandbox_admin_url, name)
    await session.commit()

    result = await session.execute(
        text(
            "SELECT payload FROM audit_decisions WHERE kind = "
            "'sandbox_database_dropped' AND payload->>'database' = :name"
        ),
        {"name": name},
    )
    row = result.first()
    assert row is not None
    assert row[0]["reason"] == "requested"


@pytest.mark.requires_db
async def test_owner_cannot_create_a_superuser(
    sandbox_admin_url: str, session: AsyncSession
) -> None:
    name = generate_name()
    await create_database(session, sandbox_admin_url, name)
    await session.commit()
    try:
        owner_url = role_url(
            sandbox_admin_url,
            role=OWNER_ROLE,
            password_env="TEST_SANDBOX_OWNER_PASSWORD",
            database=name,
        )
        with psycopg.connect(owner_url, autocommit=True) as conn:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute("CREATE ROLE askwell_test_hacker SUPERUSER")
    finally:
        await drop_database(session, sandbox_admin_url, name)
        await session.commit()


@pytest.mark.requires_db
async def test_owner_cannot_create_a_database(
    sandbox_admin_url: str, session: AsyncSession
) -> None:
    """C3's own reasoning: a dump that could create a database could make
    itself a second, unmonitored one to hide in."""
    name = generate_name()
    await create_database(session, sandbox_admin_url, name)
    await session.commit()
    try:
        owner_url = role_url(
            sandbox_admin_url,
            role=OWNER_ROLE,
            password_env="TEST_SANDBOX_OWNER_PASSWORD",
            database=name,
        )
        with psycopg.connect(owner_url, autocommit=True) as conn:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute("CREATE DATABASE askwell_test_escape")
    finally:
        await drop_database(session, sandbox_admin_url, name)
        await session.commit()


@pytest.mark.requires_db
async def test_owner_cannot_copy_to_or_from_a_program(
    sandbox_admin_url: str, session: AsyncSession
) -> None:
    name = generate_name()
    await create_database(session, sandbox_admin_url, name)
    await session.commit()
    try:
        owner_url = role_url(
            sandbox_admin_url,
            role=OWNER_ROLE,
            password_env="TEST_SANDBOX_OWNER_PASSWORD",
            database=name,
        )
        with psycopg.connect(owner_url, autocommit=True) as conn:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute("COPY (SELECT 1) TO PROGRAM 'cat > /tmp/askwell-test-pwned'")
    finally:
        await drop_database(session, sandbox_admin_url, name)
        await session.commit()


@pytest.mark.requires_db
async def test_owner_cannot_use_large_objects(
    sandbox_admin_url: str, session: AsyncSession
) -> None:
    """Both APIs: the filesystem one (`lo_import`) and the client-side one
    (`lo_creat`) — see `deploy/sandbox/10-roles.sh` for why they differ."""
    name = generate_name()
    await create_database(session, sandbox_admin_url, name)
    await session.commit()
    try:
        owner_url = role_url(
            sandbox_admin_url,
            role=OWNER_ROLE,
            password_env="TEST_SANDBOX_OWNER_PASSWORD",
            database=name,
        )
        with psycopg.connect(owner_url, autocommit=True) as conn:
            with pytest.raises(psycopg.Error):
                conn.execute("SELECT lo_import('/etc/passwd')")
        with psycopg.connect(owner_url, autocommit=True) as conn:
            with pytest.raises(psycopg.Error):
                conn.execute("SELECT lo_creat(-1)")
    finally:
        await drop_database(session, sandbox_admin_url, name)
        await session.commit()


@pytest.mark.requires_db
async def test_owner_cannot_connect_to_the_sandbox_instances_maintenance_database(
    sandbox_admin_url: str,
) -> None:
    """`postgres` — locked down instance-wide by `10-roles.sh`, not by
    anything `create_database` does for an individual sandbox database."""
    owner_url = role_url(
        sandbox_admin_url,
        role=OWNER_ROLE,
        password_env="TEST_SANDBOX_OWNER_PASSWORD",
        database="postgres",
    )
    with pytest.raises(psycopg.OperationalError):
        psycopg.connect(owner_url, autocommit=True)


@pytest.mark.requires_db
async def test_readonly_cannot_write(sandbox_admin_url: str, session: AsyncSession) -> None:
    name = generate_name()
    await create_database(session, sandbox_admin_url, name)
    await session.commit()
    try:
        owner_url = role_url(
            sandbox_admin_url,
            role=OWNER_ROLE,
            password_env="TEST_SANDBOX_OWNER_PASSWORD",
            database=name,
        )
        with psycopg.connect(owner_url, autocommit=True) as conn:
            conn.execute("CREATE TABLE t (x int)")
            conn.execute("INSERT INTO t VALUES (1)")

        readonly_url = role_url(
            sandbox_admin_url,
            role=READONLY_ROLE,
            password_env="TEST_SANDBOX_READONLY_PASSWORD",
            database=name,
        )
        with psycopg.connect(readonly_url, autocommit=True) as conn:
            assert conn.execute("SELECT x FROM t").fetchall() == [(1,)]
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute("INSERT INTO t VALUES (2)")
    finally:
        await drop_database(session, sandbox_admin_url, name)
        await session.commit()


@pytest.mark.requires_db
async def test_drop_database_removes_it(sandbox_admin_url: str, session: AsyncSession) -> None:
    name = generate_name()
    await create_database(session, sandbox_admin_url, name)
    await session.commit()
    assert name in known_databases(sandbox_admin_url)
    await drop_database(session, sandbox_admin_url, name)
    await session.commit()
    assert name not in known_databases(sandbox_admin_url)


@pytest.mark.requires_db
async def test_dropping_a_database_with_an_open_connection_does_not_refuse(
    sandbox_admin_url: str, session: AsyncSession
) -> None:
    """The exact situation an orphan left by a crashed import is in.

    `WITH (FORCE)` closes the open connection rather than `drop_database`
    raising `ObjectInUse` — see the module docstring.
    """
    name = generate_name()
    await create_database(session, sandbox_admin_url, name)
    await session.commit()
    owner_url = role_url(
        sandbox_admin_url,
        role=OWNER_ROLE,
        password_env="TEST_SANDBOX_OWNER_PASSWORD",
        database=name,
    )
    lingering = psycopg.connect(owner_url, autocommit=True)
    try:
        await drop_database(session, sandbox_admin_url, name)
        await session.commit()
        assert name not in known_databases(sandbox_admin_url)
    finally:
        lingering.close()


@pytest.mark.requires_db
async def test_reclaim_orphans_drops_only_databases_no_live_source_claims(
    sandbox_admin_url: str, session: AsyncSession
) -> None:
    orphan = generate_name()
    claimed = generate_name()
    await create_database(session, sandbox_admin_url, orphan)
    await create_database(session, sandbox_admin_url, claimed)
    await session.commit()

    try:
        await session.execute(
            text(
                "INSERT INTO sources (id, kind, name, sandbox_db, status) "
                "VALUES (gen_random_uuid(), 'dump', 'a claimed source', "
                ":sandbox_db, 'ready')"
            ),
            {"sandbox_db": claimed},
        )
        await session.commit()

        reclaimed = await reclaim_orphans(session, sandbox_admin_url)
        await session.commit()

        assert orphan in reclaimed
        assert claimed not in reclaimed
        assert orphan not in known_databases(sandbox_admin_url)
        assert claimed in known_databases(sandbox_admin_url)
    finally:
        await drop_database(session, sandbox_admin_url, claimed)
        await session.commit()


@pytest.mark.requires_db
async def test_owner_url_matches_the_owner_connection_role_url(sandbox_admin_url: str) -> None:
    """`owner_url` is `M4-DUMP-ING-088`'s own way of building this DSN;
    `role_url` is the test suite's. They must agree."""
    name = generate_name()
    password = os.environ["TEST_SANDBOX_OWNER_PASSWORD"]
    expected = role_url(
        sandbox_admin_url,
        role=OWNER_ROLE,
        password_env="TEST_SANDBOX_OWNER_PASSWORD",
        database=name,
    )
    assert owner_url(sandbox_admin_url, name, password) == expected


@pytest.mark.requires_db
async def test_seal_owner_revokes_connect_but_not_readonly(
    sandbox_admin_url: str, session: AsyncSession
) -> None:
    name = generate_name()
    await create_database(session, sandbox_admin_url, name)
    await session.commit()
    try:
        owner_dsn = role_url(
            sandbox_admin_url,
            role=OWNER_ROLE,
            password_env="TEST_SANDBOX_OWNER_PASSWORD",
            database=name,
        )
        with psycopg.connect(owner_dsn, autocommit=True) as conn:
            assert conn.execute("SELECT 1").fetchone() == (1,)

        await seal_owner(session, sandbox_admin_url, name)
        await session.commit()

        with pytest.raises(psycopg.OperationalError):
            psycopg.connect(owner_dsn, autocommit=True)

        readonly_url = role_url(
            sandbox_admin_url,
            role=READONLY_ROLE,
            password_env="TEST_SANDBOX_READONLY_PASSWORD",
            database=name,
        )
        with psycopg.connect(readonly_url, autocommit=True) as conn:
            assert conn.execute("SELECT 1").fetchone() == (1,)
    finally:
        await drop_database(session, sandbox_admin_url, name)
        await session.commit()


@pytest.mark.requires_db
async def test_seal_owner_writes_a_decisions_record(
    sandbox_admin_url: str, session: AsyncSession
) -> None:
    name = generate_name()
    await create_database(session, sandbox_admin_url, name)
    await session.commit()
    await seal_owner(session, sandbox_admin_url, name)
    await session.commit()

    result = await session.execute(
        text(
            "SELECT 1 FROM audit_decisions WHERE kind = 'sandbox_owner_sealed' "
            "AND payload->>'database' = :name"
        ),
        {"name": name},
    )
    assert result.first() is not None

    await drop_database(session, sandbox_admin_url, name)
    await session.commit()


@pytest.mark.requires_db
async def test_reclaim_orphans_writes_a_dropped_decisions_record_naming_the_reason(
    sandbox_admin_url: str, session: AsyncSession
) -> None:
    orphan = generate_name()
    await create_database(session, sandbox_admin_url, orphan)
    await session.commit()

    await reclaim_orphans(session, sandbox_admin_url)
    await session.commit()

    result = await session.execute(
        text(
            "SELECT payload FROM audit_decisions WHERE kind = "
            "'sandbox_database_dropped' AND payload->>'database' = :name"
        ),
        {"name": orphan},
    )
    row = result.first()
    assert row is not None
    assert row[0]["reason"] == "orphaned_at_startup"
