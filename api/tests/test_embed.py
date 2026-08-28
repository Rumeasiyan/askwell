"""Batching and batch-level retry, without a database. `M1-INDEX-ING-032`.

The transport is a real Unix socket, matching `test_inference_client.py`'s
own reasoning: mocking httpx would test the mock, and a socket is what the
containers actually dial.
"""

import asyncio
import json
import re
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio

from askwell import embed
from askwell.config import Settings
from askwell.inference.client import InferenceClient, InferenceFailed, InferenceUnavailable


def _ready(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "state.json").write_text(
        json.dumps({"state": "ready", "model": "a-model.gguf", "acceleration": "cpu"}),
        encoding="utf-8",
    )


class _FlakyStub:
    """Fails the first `fail_times` requests, then answers for real.

    A closer model of "the inference process goes down mid-batch and comes
    back" than a stub that always answers the same way — each connection
    attempt is what `_embed_batch` retries across.
    """

    def __init__(self, fail_times: int, vectors: list[list[float]]) -> None:
        self.fail_times = fail_times
        self.vectors = vectors
        self.calls = 0

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        head = await reader.readuntil(b"\r\n\r\n")
        length = 0
        match = re.search(rb"content-length:\s*(\d+)", head, re.I)
        if match:
            length = int(match.group(1))
        await reader.readexactly(length) if length else await reader.read(0)
        self.calls += 1

        if self.calls <= self.fail_times:
            body = b'{"error": "temporarily unavailable"}'
            status = 503
        else:
            body = json.dumps({"data": [{"embedding": v} for v in self.vectors]}).encode()
            status = 200

        writer.write(
            f"HTTP/1.1 {status} X\r\nContent-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode()
            + body
        )
        await writer.drain()
        writer.close()


@pytest_asyncio.fixture
async def serving(settings: Settings, tmp_path: Path):  # type: ignore[no-untyped-def]
    socket_path = tmp_path / "inference.sock"
    _ready(tmp_path)
    configured = settings.model_copy(update={"inference_socket": socket_path})

    servers: list[asyncio.AbstractServer] = []

    async def start(handler: Any) -> InferenceClient:
        server = await asyncio.start_unix_server(handler, path=str(socket_path))
        servers.append(server)
        return InferenceClient(configured)

    yield start

    for server in servers:
        server.close()
        await server.wait_closed()


def test_batches_split_at_the_configured_size() -> None:
    rows = [(index, str(index)) for index in range(10)]
    batches = embed._batches(rows, 4)
    assert [len(batch) for batch in batches] == [4, 4, 2]
    assert [row for batch in batches for row in batch] == rows


def test_batches_of_nothing_is_no_batches() -> None:
    assert embed._batches([], 4) == []


async def test_a_transient_failure_retries_and_succeeds(serving: Any, monkeypatch: Any) -> None:
    """The ticket's own edge case: the process is briefly unavailable and
    then answers, and the batch is retried rather than given up on."""
    monkeypatch.setattr(embed, "EMBED_BATCH_RETRY_DELAY_SECONDS", 0.0)
    stub = _FlakyStub(fail_times=1, vectors=[[0.1, 0.2]])
    start = serving
    client = await start(stub.handle)

    vectors = await embed._embed_batch(client, ["a passage"])
    assert vectors == [[0.1, 0.2]]
    assert stub.calls == 2


async def test_exhausted_retries_raise_the_last_error(serving: Any, monkeypatch: Any) -> None:
    monkeypatch.setattr(embed, "EMBED_BATCH_RETRY_DELAY_SECONDS", 0.0)
    stub = _FlakyStub(fail_times=99, vectors=[[0.1]])
    start = serving
    client = await start(stub.handle)

    with pytest.raises(InferenceFailed):
        await embed._embed_batch(client, ["a passage"])
    assert stub.calls == embed.EMBED_BATCH_MAX_ATTEMPTS


async def test_an_absent_assistant_is_retried_the_same_as_a_failed_request(
    settings: Settings, tmp_path: Path, monkeypatch: Any
) -> None:
    """`InferenceUnavailable` and `InferenceFailed` are different claims about
    *why* — `test_inference_client.py` is where that distinction is proved —
    but from a batch's point of view both are worth retrying before the whole
    document is given up on."""
    monkeypatch.setattr(embed, "EMBED_BATCH_RETRY_DELAY_SECONDS", 0.0)
    client = InferenceClient(
        settings.model_copy(update={"inference_socket": tmp_path / "no-such.sock"})
    )
    with pytest.raises(InferenceUnavailable):
        await embed._embed_batch(client, ["a passage"])
