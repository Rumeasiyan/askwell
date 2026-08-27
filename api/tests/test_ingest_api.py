"""The progress surface, over HTTP.

What the queue decides is asserted against a real database in
`test_ingest_records.py`. What is asserted here is what a browser actually
receives: that progress is available without holding the request that started
the work, that the stream is a stream, and that a retry of something that did
not fail is refused by name rather than accepted and quietly ignored.
"""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from askwell import ingest
from askwell import session as sessions
from askwell.app import create_app
from askwell.config import Settings

TABLES = "roots, sources, documents, ingest_jobs, audit_decisions"


def _app(settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    async def fixed_secret(_db: object) -> bytes:
        return b"0" * 32

    monkeypatch.setattr(sessions, "secret", fixed_secret)
    monkeypatch.setattr("askwell.middleware.sessions.secret", fixed_secret)

    built = tmp_path / "out"
    built.mkdir(exist_ok=True)
    (built / "index.html").write_text("<!doctype html><title>Askwell</title>")
    return TestClient(create_app(settings.model_copy(update={"web_assets_dir": built})))


@pytest.fixture
def client(settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    """A real application with no database behind it."""
    return _app(settings, monkeypatch, tmp_path)


def with_session(client: TestClient) -> None:
    client.get("/", headers={"accept": "text/html"})


def test_progress_requires_a_session(client: TestClient) -> None:
    """It describes the user's own files, so it is behind the same door."""
    with client:
        assert client.get("/ingest").status_code == 401


def test_retrying_requires_a_session(client: TestClient) -> None:
    with client:
        response = client.post("/ingest/documents/00000000-0000-0000-0000-000000000000/retry")
    assert response.status_code == 401


def test_a_malformed_document_id_is_a_validation_error_not_a_route_miss(
    client: TestClient,
) -> None:
    """The retry route must not be shadowed by the interface catch-all.

    If registration order ever changes, this comes back as an HTML page with a
    200 and the retry silently stops working.
    """
    with client:
        with_session(client)
        assert client.post("/ingest/documents/not-a-uuid/retry").status_code == 422


@pytest.mark.requires_db
def test_progress_is_readable_without_holding_the_request_that_started_the_work(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    app_database_url: str,
    database_url: str,
) -> None:
    """The whole ticket, in one exchange.

    An add returns, its request ends, and the queue is still there to be asked
    about from a completely separate request — which is what "navigating away
    does not cancel it" means in the only place it can be proved.
    """
    folder = tmp_path / "papers"
    folder.mkdir()
    (folder / "contract.pdf").write_bytes(b"%PDF-1.7\nninety days notice\n")

    with psycopg.connect(database_url, autocommit=True) as setup:
        setup.execute(f"TRUNCATE {TABLES} CASCADE")
        setup.execute("INSERT INTO roots (path) VALUES (%s)", (str(folder),))

    async def fixed_secret(_db: object) -> bytes:
        return b"0" * 32

    monkeypatch.setattr(sessions, "secret", fixed_secret)
    monkeypatch.setattr("askwell.middleware.sessions.secret", fixed_secret)

    built = tmp_path / "out"
    built.mkdir()
    (built / "index.html").write_text("<!doctype html><title>Askwell</title>")
    live = create_app(
        settings.model_copy(
            update={"database_url": SecretStr(app_database_url), "web_assets_dir": built}
        )
    )

    with TestClient(live) as client:
        with_session(client)
        added = client.post("/sources", json={"folder": str(folder), "files": ["contract.pdf"]})
        assert added.status_code == 201, added.text

        # A separate request, after the first one is over.
        state = client.get("/ingest")
        assert state.status_code == 200, state.text
        body = state.json()

        assert body["counts"]["queued"] == 1
        assert body["queue_length"] == 1
        assert body["next"][0]["filename"] == "contract.pdf"
        assert body["next"][0]["position"] == 1
        assert body["estimate"]["seconds"] is None
        assert body["concurrency"] == settings.ingest_concurrency
        assert body["sources"][0]["askable"] is False
        # `extract` is real since `M1-EXTRACT-ING-026`; `chunk` and `embed` are
        # not, and the surface says which ticket that is rather than showing an
        # empty queue that appears to have finished.
        assert [stage["built"] for stage in body["stages"]] == [True, False, False]

        document_id = body["next"][0]["document_id"]
        refused = client.post(f"/ingest/documents/{document_id}/retry")
        assert refused.status_code == 409
        assert refused.json()["state"] == "queued"

        missing = client.post("/ingest/documents/00000000-0000-0000-0000-000000000000/retry")
        assert missing.status_code == 404

    with psycopg.connect(database_url, autocommit=True) as clean:
        clean.execute(f"TRUNCATE {TABLES} CASCADE")


async def test_the_stream_sends_progress_and_stops_when_the_browser_goes_away(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Server-sent events, and a stream that ends when nobody is reading it.

    Driven against the ASGI application directly rather than through
    `TestClient`, and that is not a preference. Starlette's test transport
    collects a response body before returning it, so a stream that never ends
    never arrives — the test hangs rather than failing, which is worse than
    having no test. Speaking ASGI is what makes the two things this asserts
    observable: that a chunk is *sent* before the response is finished, and
    that `http.disconnect` ends the generator. The second is what stops one
    closed browser tab leaving a coroutine polling the database until the
    process restarts.

    The database is stubbed. What is under test is the transport; a real one
    would make this also a test of Postgres being up.
    """
    payload: dict[str, Any] = {"queue_length": 2, "counts": {"queued": 2}}

    async def fake_snapshot(_db: object, _settings: Settings) -> dict[str, Any]:
        return payload

    @asynccontextmanager
    async def fake_scope(_factory: object) -> AsyncIterator[None]:
        yield None

    monkeypatch.setattr(ingest, "snapshot", fake_snapshot)
    monkeypatch.setattr(ingest, "session_scope", fake_scope)

    client = _app(settings, monkeypatch, tmp_path)
    with client:
        with_session(client)
        cookies = "; ".join(f"{name}={value}" for name, value in client.cookies.items())

    app = client.app
    hung_up = asyncio.Event()
    received: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        await hung_up.wait()
        return {"type": "http.disconnect"}

    first_chunk = asyncio.Event()

    async def send(message: dict[str, Any]) -> None:
        received.append(message)
        if message["type"] == "http.response.body" and message.get("body"):
            first_chunk.set()

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/ingest/stream",
        "raw_path": b"/ingest/stream",
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"askwell"), (b"cookie", cookies.encode())],
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 8000),
    }

    async def drive() -> None:
        stream = asyncio.create_task(app(scope, receive, send))
        # The chunk has to arrive while the request is still open. Waiting for
        # the task instead would be waiting for a stream designed never to end
        # on its own, which is the thing being asserted.
        await first_chunk.wait()
        hung_up.set()
        await stream

    await asyncio.wait_for(drive(), timeout=10)

    start = received[0]
    assert start["type"] == "http.response.start"
    assert start["status"] == 200
    headers = {name.decode(): value.decode() for name, value in start["headers"]}
    assert headers["content-type"].startswith("text/event-stream")
    assert headers["cache-control"] == "no-store"

    body = b"".join(
        message.get("body", b"") for message in received if message["type"] == "http.response.body"
    ).decode()
    lines = body.split("\n")
    assert lines[0] == "event: progress"
    assert json.loads(lines[1].removeprefix("data: ")) == payload

    # And once. The stream re-reads on a timer and sends only what changed, so
    # an unchanging queue does not push the same payload at a browser twice a
    # second for as long as the tab is open.
    assert body.count("event: progress") == 1
