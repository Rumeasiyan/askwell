"""Shared fixtures.

Where tests live, and what each kind guarantees:

  `api/tests/test_<module>.py`   mirrors `api/src/askwell/<module>.py`
  no marker                       runs with no network at all, in every run
  `@pytest.mark.requires_db`      needs Postgres; run by `scripts/dev.sh test-db`

A database-backed test gets a database created and migrated for that run alone,
and dropped afterwards — see `conftest_db.py`. It must not assume any row it
did not create.


Every test that touches configuration builds `Settings` explicitly rather than
letting it read the ambient environment. A test that passes because the
developer happens to have `ASKWELL_DATABASE_URL` exported is not a test.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest

from askwell.config import Settings

# Re-exported so every test module sees them without importing anything.
from tests.conftest_db import app_database_url, database_url  # noqa: F401


@pytest.fixture(autouse=True)
def _no_ambient_askwell_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Remove every ASKWELL_* variable for the duration of each test."""
    import os

    for name in list(os.environ):
        if name.startswith("ASKWELL_"):
            monkeypatch.delenv(name, raising=False)
    yield


@pytest.fixture
def settings() -> Settings:
    """Valid configuration pointing at addresses that refuse connections.

    Port 1 on loopback: nothing listens there, and loopback refuses
    immediately rather than hanging, which keeps the tests fast and keeps
    them from touching the network (C1).
    """
    return Settings(
        database_url="postgresql://askwell:pw@127.0.0.1:1/askwell",  # type: ignore[arg-type]
        redis_host="127.0.0.1",
        redis_port=1,
        # A key nothing writes, so the worker reads as not-checked-in by
        # default. Tests that want a live worker set it explicitly.
        worker_health_key="askwell-test:no-such-worker",
        # A socket path that does not exist: inference reads as not running,
        # which is the state before the host-side supervisor is started.
        inference_socket=Path("/nonexistent/askwell-test/inference.sock"),
        egress_proxy_host="127.0.0.1",
        egress_proxy_port=1,
        health_probe_timeout_seconds=0.5,
    )
