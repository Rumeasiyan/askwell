"""A disposable connection to the real sandbox instance, for `test_sandbox.py`.

Unlike `conftest_db.py`, this does not create a fresh instance per run — there
is nothing to migrate, `askwell.sandbox` creates and drops whole databases
itself, and that is exactly the behaviour under test. What this fixture
guarantees is the same thing `conftest_db.py` guarantees for the main
database: a test run never depends on state a previous run left behind, and a
crashed run's debris does not accumulate forever.
"""

import os
import time
from collections.abc import Iterator

import psycopg
import pytest

from askwell.sandbox import PREFIX

SERVER_URL = "TEST_SANDBOX_DATABASE_URL"
OWNER_PASSWORD = "TEST_SANDBOX_OWNER_PASSWORD"
READONLY_PASSWORD = "TEST_SANDBOX_READONLY_PASSWORD"

# Same reasoning and the same figure as conftest_db.py's ORPHAN_AGE_SECONDS:
# long enough that no realistic test run is still using one of these.
ORPHAN_AGE_SECONDS = 2 * 60 * 60


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"{name} is not set. The sandbox-backed tests need a real, separate "
            f"Postgres instance — they assert what it refuses. Run: "
            f"scripts/dev.sh test-db"
        )
    return value


def _sweep(admin: psycopg.Connection[tuple[object, ...]]) -> None:
    """Drop `askwell_sbx_*` databases this module's own naming did not create
    this run and that are old enough no other run could still be using.

    Age is not derivable from the name the way `conftest_db.py`'s is —
    `generate_name()` carries no timestamp, deliberately, since a predictable
    name is exactly what `InvalidSandboxName` exists to make untrustable
    elsewhere. So this reads `pg_stat_activity`'s absence as a proxy: nothing
    connected recently means nothing is using it.
    """
    cutoff = time.time() - ORPHAN_AGE_SECONDS
    rows = admin.execute(
        "SELECT datname FROM pg_database WHERE datname LIKE %s", (f"{PREFIX}%",)
    ).fetchall()
    for (name,) in rows:
        stat = admin.execute(
            "SELECT COALESCE(MAX(backend_start), 'epoch'::timestamptz) "
            "FROM pg_stat_activity WHERE datname = %s",
            (name,),
        ).fetchone()
        last_seen = stat[0].timestamp() if stat else 0.0
        if last_seen > cutoff:
            continue
        try:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        except psycopg.errors.ObjectInUse:  # pragma: no cover - raced with a live run
            continue


@pytest.fixture(scope="session")
def sandbox_admin_url() -> Iterator[str]:
    """The sandbox instance's own superuser connection to `postgres`."""
    url = _require(SERVER_URL)
    with psycopg.connect(url, autocommit=True) as admin:
        _sweep(admin)
    yield url


def role_url(admin_url: str, *, role: str, password_env: str, database: str) -> str:
    """`admin_url`, but as a fixed sandbox role against a given database."""
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(admin_url)
    host = parts.hostname or "sandbox"
    port = f":{parts.port}" if parts.port else ""
    netloc = f"{role}:{_require(password_env)}@{host}{port}"
    return urlunsplit((parts.scheme, netloc, f"/{database}", "", ""))
