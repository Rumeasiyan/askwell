"""A disposable database per test run.

Running the database-backed tests against the development database works until
it does not. Tests clean up by truncating, which is correct right up to the
first test that forgets, and which silently destroys whatever the developer had
in there. Two runs at once collide. A run that crashes leaves dirty state for
the next one to inherit and be confused by.

So each run creates its own database, migrates it, and drops it. The name
carries the start time and a random suffix: unique, so parallel runs cannot
collide, and datable, so a database orphaned by a crash can be swept up later
without any risk of dropping one a concurrent run is still using.
"""

import os
import secrets
import time
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest
from alembic import command
from alembic.config import Config

PREFIX = "askwell_test_"

# How long an orphaned database is left alone before the sweep takes it. Long
# enough that no realistic test run is still using one, short enough that a
# developer's disk does not fill with the debris of crashed runs.
ORPHAN_AGE_SECONDS = 2 * 60 * 60

SERVER_URL = "TEST_DATABASE_URL"
APP_PASSWORD = "TEST_APP_PASSWORD"


def _require(name: str) -> str:
    """An environment variable, or a failure explaining how to run these.

    Deliberately not `pytest.skip`. A suite that quietly passes when it did not
    run prints the same summary line as one that did.
    """
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"{name} is not set. The database-backed tests need a real Postgres "
            f"— they assert what it refuses. Run: scripts/dev.sh test-db"
        )
    return value


def _with_database(
    url: str, database: str, *, user: str | None = None, password: str | None = None
) -> str:
    parts = urlsplit(url)
    netloc = parts.netloc
    if user is not None:
        host = parts.hostname or "postgres"
        port = f":{parts.port}" if parts.port else ""
        netloc = f"{user}:{password}@{host}{port}"
    return urlunsplit((parts.scheme, netloc, f"/{database}", "", ""))


def _sweep_orphans(admin: psycopg.Connection[tuple[object, ...]]) -> int:
    """Drop databases left behind by runs that did not finish.

    Age is read from the name rather than from the catalogue, and a database is
    only dropped once it is older than any run could plausibly still be using.
    Dropping on "no active connections" alone would eventually kill a
    concurrent run between two of its own connections.
    """
    cutoff = int(time.time()) - ORPHAN_AGE_SECONDS
    dropped = 0
    rows = admin.execute(
        "SELECT datname FROM pg_database WHERE datname LIKE %s", (f"{PREFIX}%",)
    ).fetchall()
    for (name,) in rows:
        stamp = str(name)[len(PREFIX) :].split("_")[0]
        if not stamp.isdigit() or int(stamp) > cutoff:
            continue
        try:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
            dropped += 1
        except psycopg.errors.ObjectInUse:  # pragma: no cover - raced with a live run
            continue
    return dropped


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    """A freshly created, freshly migrated database. Dropped afterwards."""
    server = _require(SERVER_URL)
    name = f"{PREFIX}{int(time.time())}_{secrets.token_hex(4)}"

    # `postgres` is the maintenance database: CREATE DATABASE cannot run from
    # inside the database being created, and connecting to the application's
    # own database to do it would defeat the isolation.
    admin_url = _with_database(server, "postgres")

    with psycopg.connect(admin_url, autocommit=True) as admin:
        _sweep_orphans(admin)
        admin.execute(f'CREATE DATABASE "{name}"')

    created = _with_database(server, name)
    try:
        _migrate(created)
        yield created
    finally:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            # FORCE closes any connection a failing test left open. Without it
            # one leaked connection leaves the database behind and the next run
            # inherits a slower sweep rather than a clean start.
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def _migrate(url: str) -> None:
    """Apply every migration to the new database.

    Applying them rather than creating the schema from the model metadata is
    the point: this is also the only place the migration chain is checked
    against an empty database, which is the thing a user upgrading in a year
    actually depends on.

    `ASKWELL_DATABASE_URL` is set for the duration because a migration reads
    configuration — the embedding dimension comes from there — and the harness
    is running in the same process. It is restored afterwards so that a test
    asserting configuration *failure* still sees a clean environment.
    """
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "src" / "askwell" / "db" / "migrations"))
    config.set_main_option("sqlalchemy.url", url)

    previous = os.environ.get("ASKWELL_DATABASE_URL")
    os.environ["ASKWELL_DATABASE_URL"] = url
    try:
        command.upgrade(config, "head")
    finally:
        if previous is None:
            os.environ.pop("ASKWELL_DATABASE_URL", None)
        else:
            os.environ["ASKWELL_DATABASE_URL"] = previous


@pytest.fixture(scope="session")
def app_database_url(database_url: str) -> str:
    """The same database, as the role Askwell actually connects as.

    Which owns nothing — see `docs/decisions.md`. Tests that assert what the
    application cannot do must use this one or they assert nothing.
    """
    return _with_database(
        database_url,
        urlsplit(database_url).path.lstrip("/"),
        user="askwell_app",
        password=_require(APP_PASSWORD),
    )
