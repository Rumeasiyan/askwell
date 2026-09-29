"""Two migration runs at once converge instead of racing — issue #813.

The installer runs the `migrate` service in the foreground during an upgrade,
and the desktop shell's supervisor, a session unit or a person typing `up` can
start it again at the same moment. Alembic takes no lock of its own, so both
runs would read the old revision and one would fail on a duplicate object: a
failed upgrade the person did nothing to cause. `env.py` now holds a Postgres
advisory lock for the whole run.

Each run here is a real `alembic` process, as `migrate` is, against a database
created for the test alone and dropped afterwards. Processes rather than
threads: Alembic's `context` is a module-level proxy, so two runs in one
process would clobber each other and prove nothing about two containers.
"""

import os
import secrets
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

from tests.conftest_db import PREFIX, SERVER_URL, _require, _with_database

pytestmark = pytest.mark.requires_db

API_ROOT = Path(__file__).resolve().parents[1]
LOCK_KEY = "askwell_migrate"


@pytest.fixture
def fresh_database() -> Iterator[str]:
    """An empty database, named like the harness's so its orphan sweep applies."""
    admin_url = _with_database(_require(SERVER_URL), "postgres")
    name = f"{PREFIX}{int(time.time())}_{secrets.token_hex(4)}"
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    try:
        yield _with_database(_require(SERVER_URL), name)
    finally:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def _alembic(url: str, *args: str) -> "subprocess.Popen[str]":
    """`alembic <args>` in its own process, configured the way `migrate` is."""
    env = {
        **os.environ,
        "ASKWELL_DATABASE_URL": url,
        # Required by `load_settings()`, read by no migration; see conftest_db._migrate.
        "ASKWELL_SANDBOX_DATABASE_URL": "postgresql://x:x@sandbox.invalid:5432/postgres",
        "ASKWELL_SANDBOX_OWNER_PASSWORD": "x",
        "ASKWELL_SANDBOX_READONLY_PASSWORD": "x",
    }
    return subprocess.Popen(
        [sys.executable, "-m", "alembic", *args],
        cwd=API_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def _finish(process: "subprocess.Popen[str]") -> tuple[int, str]:
    output, _ = process.communicate(timeout=300)
    return process.returncode, output


def _head() -> str:
    process = _alembic("postgresql://unused.invalid/x", "heads")
    code, output = _finish(process)
    assert code == 0, output
    return output.split()[0]


def _current(url: str) -> list[str]:
    with psycopg.connect(url) as conn:
        return [str(row[0]) for row in conn.execute("SELECT version_num FROM alembic_version")]


def test_two_concurrent_upgrades_of_an_empty_database_both_succeed(fresh_database: str) -> None:
    first = _alembic(fresh_database, "upgrade", "head")
    second = _alembic(fresh_database, "upgrade", "head")

    first_code, first_output = _finish(first)
    second_code, second_output = _finish(second)

    assert first_code == 0, first_output
    assert second_code == 0, second_output
    assert _current(fresh_database) == [_head()]


def test_an_upgrade_waits_while_another_run_holds_the_lock(fresh_database: str) -> None:
    with psycopg.connect(fresh_database, autocommit=True) as holder:
        holder.execute("SELECT pg_advisory_lock(hashtext(%s))", (LOCK_KEY,))
        waiting = _alembic(fresh_database, "upgrade", "head")
        try:
            time.sleep(3)
            assert waiting.poll() is None, "the upgrade ran without waiting for the lock"
            tables = holder.execute("SELECT to_regclass('alembic_version')").fetchone()
            assert tables == (None,), "the upgrade touched the schema while the lock was held"
        finally:
            holder.execute("SELECT pg_advisory_unlock(hashtext(%s))", (LOCK_KEY,))

    code, output = _finish(waiting)
    assert code == 0, output
    assert _current(fresh_database) == [_head()]


def test_the_lock_is_released_when_the_run_finishes(fresh_database: str) -> None:
    code, output = _finish(_alembic(fresh_database, "upgrade", "head"))
    assert code == 0, output

    with psycopg.connect(fresh_database, autocommit=True) as probe:
        got = probe.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (LOCK_KEY,)).fetchone()
        assert got == (True,)
        probe.execute("SELECT pg_advisory_unlock(hashtext(%s))", (LOCK_KEY,))


def test_a_second_upgrade_with_nothing_pending_is_a_no_op(fresh_database: str) -> None:
    assert _finish(_alembic(fresh_database, "upgrade", "head"))[0] == 0

    code, output = _finish(_alembic(fresh_database, "upgrade", "head"))

    assert code == 0, output
    assert "Running upgrade" not in output
    assert _current(fresh_database) == [_head()]
