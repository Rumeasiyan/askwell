"""Shared fixtures.

Every test that touches configuration builds `Settings` explicitly rather than
letting it read the ambient environment. A test that passes because the
developer happens to have `ASKWELL_DATABASE_URL` exported is not a test.
"""

from collections.abc import Iterator

import pytest

from askwell.config import Settings


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
        worker_host="127.0.0.1",
        worker_port=1,
        inference_host="127.0.0.1",
        inference_port=1,
        egress_proxy_host="127.0.0.1",
        egress_proxy_port=1,
        health_probe_timeout_seconds=0.5,
    )
