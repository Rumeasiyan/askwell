"""The write-permission probe against a real Postgres. `M4-CONN-SEC-097`.

`_find_mysql_write_grant`/`_find_sqlserver_write_permission` in
`test_connections.py` cover MySQL/MariaDB and SQL Server as pure parsing —
no engine for either is part of this stack, so there is nothing real to
connect to. PostgreSQL is: `askwell-postgres` is reachable from the test
process the same way `askwell-sandbox` already is for the dump-import tests,
so this file creates disposable roles against the same disposable database
`conftest_db.py` already creates per run, and connects to it as an "external"
target through `connections.probe_connection` exactly as the wizard would.

Every role is dropped in a `finally`, even though the whole database is
dropped at the end of the run anyway — a role, unlike a table, is
cluster-global and would otherwise survive the database that created it.
"""

from collections.abc import Iterator
from urllib.parse import urlsplit

import psycopg
import pytest

from askwell.connections import probe_connection

pytestmark = pytest.mark.requires_db


def _target(database_url: str) -> tuple[str, int, str]:
    parts = urlsplit(database_url)
    return parts.hostname or "127.0.0.1", parts.port or 5432, parts.path.lstrip("/")


def _run(database_url: str, *statements: str) -> None:
    with psycopg.connect(database_url, autocommit=True) as conn, conn.cursor() as cur:
        for statement in statements:
            cur.execute(statement)


@pytest.fixture
def _role_name() -> str:
    return "askwell_write_probe_test"


@pytest.fixture
def read_only_role(database_url: str, _role_name: str) -> Iterator[str]:
    name = _role_name
    _run(
        database_url,
        f"DROP ROLE IF EXISTS {name}",
        f"CREATE ROLE {name} LOGIN PASSWORD 'probe-pw'",
        f"GRANT CONNECT ON DATABASE {_target(database_url)[2]} TO {name}",
        f"GRANT USAGE ON SCHEMA public TO {name}",
        f"GRANT SELECT ON ALL TABLES IN SCHEMA public TO {name}",
    )
    try:
        yield name
    finally:
        _run(
            database_url,
            f"REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM {name}",
            f"DROP OWNED BY {name}",
            f"DROP ROLE IF EXISTS {name}",
        )


@pytest.fixture
def table_write_role(database_url: str, _role_name: str) -> Iterator[str]:
    name = _role_name
    _run(
        database_url,
        f"DROP ROLE IF EXISTS {name}",
        f"CREATE ROLE {name} LOGIN PASSWORD 'probe-pw'",
        f"GRANT CONNECT ON DATABASE {_target(database_url)[2]} TO {name}",
        f"GRANT USAGE ON SCHEMA public TO {name}",
        f"GRANT SELECT, INSERT ON sources TO {name}",
    )
    try:
        yield name
    finally:
        _run(
            database_url,
            f"REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM {name}",
            f"DROP OWNED BY {name}",
            f"DROP ROLE IF EXISTS {name}",
        )


@pytest.fixture
def database_create_role(database_url: str, _role_name: str) -> Iterator[str]:
    name = _role_name
    database = _target(database_url)[2]
    _run(
        database_url,
        f"DROP ROLE IF EXISTS {name}",
        f"CREATE ROLE {name} LOGIN PASSWORD 'probe-pw'",
        f"GRANT CONNECT, CREATE ON DATABASE {database} TO {name}",
    )
    try:
        yield name
    finally:
        _run(
            database_url,
            f"REVOKE ALL PRIVILEGES ON DATABASE {database} FROM {name}",
            f"DROP ROLE IF EXISTS {name}",
        )


async def test_a_table_level_write_grant_is_refused_naming_the_permission_and_table(
    database_url: str, table_write_role: str
) -> None:
    host, port, database = _target(database_url)
    outcome = await probe_connection(
        "postgresql", host, port, database, table_write_role, "probe-pw", 5.0
    )
    assert outcome.ok is False
    assert outcome.reason_code == "write_capable"
    assert "INSERT" in outcome.message
    assert "sources" in outcome.message
    assert outcome.remediation is not None
    assert "askwell_reader" in outcome.remediation


async def test_a_database_level_create_grant_is_refused(
    database_url: str, database_create_role: str
) -> None:
    host, port, database = _target(database_url)
    outcome = await probe_connection(
        "postgresql", host, port, database, database_create_role, "probe-pw", 5.0
    )
    assert outcome.ok is False
    assert outcome.reason_code == "write_capable"
    assert "CREATE" in outcome.message


async def test_a_select_only_role_is_accepted(database_url: str, read_only_role: str) -> None:
    host, port, database = _target(database_url)
    outcome = await probe_connection(
        "postgresql", host, port, database, read_only_role, "probe-pw", 5.0
    )
    assert outcome.ok is True
    assert outcome.reason_code is None
