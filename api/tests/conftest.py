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

import asyncio
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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


@dataclass(slots=True)
class DrivenRequest:
    """What an ASGI app sent, for a request driven directly rather than
    through Starlette's `TestClient`.

    `TestClient`'s transport collects a response body before returning it
    (issue #110), which makes a stream that ends only when the browser
    disconnects untestable through it — the disconnect can never be sent
    before the collection that is waiting for the stream to end. Speaking
    ASGI directly is what makes both halves of that observable: that a chunk
    is *sent* before the response finishes, and that `http.disconnect`
    reaches whatever is on the other end of the connection. First used by
    `test_ingest_api.py`; `M1-ASK-API-038` is the second caller the module
    docstring for that test predicted, so the pattern moved here.
    """

    messages: list[dict[str, Any]] = field(default_factory=list)

    @property
    def start(self) -> dict[str, Any]:
        return self.messages[0]

    @property
    def body(self) -> str:
        return b"".join(
            message.get("body", b"")
            for message in self.messages
            if message["type"] == "http.response.body"
        ).decode()


async def drive_and_disconnect(
    app: Any, *, method: str, path: str, cookies: str, body: bytes = b""
) -> DrivenRequest:
    """Drive one request against an ASGI app, disconnecting the instant the
    first chunk of the response arrives.

    For a request body, `receive` hands it over on the first call and
    `http.disconnect` on every one after — a real client never asks again
    once it has sent its request, so neither does this one.
    """
    hung_up = asyncio.Event()
    first_chunk = asyncio.Event()
    sent_body = False
    messages: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        nonlocal sent_body
        if not sent_body:
            sent_body = True
            return {"type": "http.request", "body": body, "more_body": False}
        await hung_up.wait()
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)
        if message["type"] == "http.response.body" and message.get("body"):
            first_chunk.set()

    headers = [(b"host", b"askwell"), (b"cookie", cookies.encode())]
    if body:
        headers.append((b"content-type", b"application/json"))
        headers.append((b"content-length", str(len(body)).encode()))

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 8000),
    }

    async def drive() -> None:
        task = asyncio.create_task(app(scope, receive, send))
        await first_chunk.wait()
        hung_up.set()
        await task

    await asyncio.wait_for(drive(), timeout=10)
    return DrivenRequest(messages=messages)
