"""The test harness itself.

A harness that quietly does less than it claims is worse than an obvious gap,
because everything built on it inherits the false confidence. These assert the
three things `conftest_db.py` promises: the database is this run's own, the
migration chain applied to it from empty, and the development data is nowhere
near it.
"""

import time
from urllib.parse import urlsplit

import psycopg
import pytest

from askwell.db import models  # noqa: F401  - imported so the tables register
from askwell.db.base import Base

pytestmark = pytest.mark.requires_db

# `Base.metadata` is populated by importing the models, not by defining Base —
# an empty expectation would make the assertion below pass against an empty
# database.
EXPECTED_TABLES = set(Base.metadata.tables) | {"alembic_version"}


def test_the_database_is_this_runs_own(database_url: str) -> None:
    """Not the development database, and not a shared one.

    Tests clean up by truncating, which is correct until the first test that
    forgets — and then it is the developer's own sources that disappear.
    """
    name = urlsplit(database_url).path.lstrip("/")
    assert name.startswith("askwell_test_"), name
    assert name != "askwell"


def test_the_migration_chain_applied_from_empty(database_url: str) -> None:
    """The only place this is checked.

    It is what a user upgrading in a year actually depends on: the chain has to
    apply to a database that has never seen it, not merely to the one on the
    developer's machine that grew alongside it.
    """
    with psycopg.connect(database_url, autocommit=True) as connection:
        rows = connection.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        ).fetchall()
    assert {str(row[0]) for row in rows} == EXPECTED_TABLES


def test_the_migration_is_recorded_as_applied(database_url: str) -> None:
    with psycopg.connect(database_url, autocommit=True) as connection:
        version = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    assert version is not None, "the schema exists but alembic does not know it applied"


def test_the_invariants_came_with_it(database_url: str) -> None:
    """A fresh database gets the constraints, not just the tables.

    Creating the schema from model metadata instead of from the migration would
    pass every table test above and silently drop every raw invariant, because
    the ORM does not express them.
    """
    with psycopg.connect(database_url, autocommit=True) as connection:
        checks = connection.execute(
            "SELECT conname FROM pg_constraint WHERE contype = 'c' AND conname LIKE 'ck_%'"
        ).fetchall()
        partial = connection.execute(
            "SELECT indexname FROM pg_indexes "
            "WHERE indexname = 'uq_documents_live_source_id_sha256'"
        ).fetchone()

    names = {str(row[0]) for row in checks}
    assert "ck_chunks_cleared_content_has_no_embedding" in names
    assert "ck_clarifications_answered_has_answer" in names
    assert partial is not None, "the partial unique index is missing"


def test_the_vector_extension_came_with_it(database_url: str) -> None:
    with psycopg.connect(database_url, autocommit=True) as connection:
        extension = connection.execute(
            "SELECT 1 FROM pg_extension WHERE extname = 'vector'"
        ).fetchone()
    assert extension is not None


def test_the_application_role_can_reach_it(app_database_url: str) -> None:
    """Tests that assert what the application cannot do need the application's
    own role, or they assert nothing at all."""
    with psycopg.connect(app_database_url, autocommit=True) as connection:
        who = connection.execute("SELECT current_user").fetchone()
    assert who is not None
    assert str(who[0]) == "askwell_app"


def test_no_configuration_leaked_into_the_environment() -> None:
    """The harness sets ASKWELL_DATABASE_URL to migrate, and must put it back.

    Left set, every test asserting that Askwell *refuses* bad configuration
    would quietly start passing for the wrong reason.
    """
    import os

    assert "ASKWELL_DATABASE_URL" not in os.environ


def test_a_database_orphaned_by_a_crashed_run_is_swept_up(database_url: str) -> None:
    """A run that dies leaves its database behind. The next run cleans up.

    Age comes from the name rather than from the catalogue, and only databases
    older than any plausible run are touched — dropping on "no active
    connections" alone would eventually kill a concurrent run between two of
    its own connections.
    """
    from tests.conftest_db import ORPHAN_AGE_SECONDS, PREFIX, _sweep_orphans, _with_database

    stale = f"{PREFIX}{int(time.time()) - ORPHAN_AGE_SECONDS - 60}_deadbeef"
    fresh = f"{PREFIX}{int(time.time())}_cafebabe"
    admin_url = _with_database(database_url, "postgres")

    with psycopg.connect(admin_url, autocommit=True) as admin:
        for name in (stale, fresh):
            admin.execute(f'CREATE DATABASE "{name}"')
        try:
            _sweep_orphans(admin)
            remaining = {
                str(row[0])
                for row in admin.execute(
                    "SELECT datname FROM pg_database WHERE datname LIKE %s", (f"{PREFIX}%",)
                ).fetchall()
            }
            assert stale not in remaining, "an orphaned database survived the sweep"
            assert fresh in remaining, "the sweep took a database a live run could be using"
        finally:
            for name in (stale, fresh):
                admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
