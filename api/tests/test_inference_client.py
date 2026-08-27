"""The inference client.

The distinction under test throughout: **the assistant being absent is not the
same as a request failing.** `docs/ux/ask.md` §5 degrades to browsing and
search when inference is unavailable rather than showing an error, and it can
only do that if callers can tell those apart. Every test here is ultimately
about which of the two exceptions comes out.

The transport is a real Unix socket serving canned responses. Mocking httpx
would test the mock; a socket tests the thing the containers actually use.
"""

import asyncio
import json
import re
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio

from askwell.config import Settings
from askwell.inference.client import InferenceClient, InferenceFailed, InferenceUnavailable


def _ready(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "state.json").write_text(
        json.dumps({"state": "ready", "model": "a-model.gguf", "acceleration": "cpu"}),
        encoding="utf-8",
    )


class Stub:
    """A Unix socket speaking just enough HTTP to answer one request."""

    def __init__(self, status: int = 200, body: Any = None, raw: bytes | None = None) -> None:
        self.status = status
        self.body = body
        self.raw = raw
        self.requests: list[dict[str, Any]] = []

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        head = await reader.readuntil(b"\r\n\r\n")
        length = 0
        match = re.search(rb"content-length:\s*(\d+)", head, re.I)
        if match:
            length = int(match.group(1))
        payload = await reader.readexactly(length) if length else b"{}"
        with pytest.MonkeyPatch.context():
            pass
        self.requests.append(json.loads(payload or b"{}"))

        content = self.raw if self.raw is not None else json.dumps(self.body).encode()
        writer.write(
            f"HTTP/1.1 {self.status} X\r\nContent-Type: application/json\r\n"
            f"Content-Length: {len(content)}\r\nConnection: close\r\n\r\n".encode()
            + content
        )
        await writer.drain()
        writer.close()


@pytest_asyncio.fixture
async def serving(settings: Settings, tmp_path: Path):  # type: ignore[no-untyped-def]
    """Start a stub on the socket the client will dial."""
    socket_path = tmp_path / "inference.sock"
    _ready(tmp_path)
    configured = settings.model_copy(update={"inference_socket": socket_path})

    servers: list[asyncio.AbstractServer] = []

    async def start(stub: Stub) -> InferenceClient:
        server = await asyncio.start_unix_server(stub.handle, path=str(socket_path))
        servers.append(server)
        return InferenceClient(configured)

    yield start, configured

    for server in servers:
        server.close()
        await server.wait_closed()


# --- the distinction --------------------------------------------------------


async def test_a_stopped_assistant_is_unavailable_not_a_failure(
    settings: Settings, tmp_path: Path
) -> None:
    """The caller degrades to search. It cannot do that from a generic error."""
    (tmp_path / "state.json").write_text(
        json.dumps({"state": "model_missing", "reason": "No model file at /x.gguf."}),
        encoding="utf-8",
    )
    client = InferenceClient(
        settings.model_copy(update={"inference_socket": tmp_path / "inference.sock"})
    )

    with pytest.raises(InferenceUnavailable) as raised:
        await client.generate("anything")
    # The supervisor's own reason, not a connection error. "No model file at
    # /x.gguf" is actionable; "connection refused" is not.
    assert "No model file" in str(raised.value)


async def test_a_supervisor_that_never_reported_is_unavailable(
    settings: Settings, tmp_path: Path
) -> None:
    client = InferenceClient(
        settings.model_copy(update={"inference_socket": tmp_path / "inference.sock"})
    )
    with pytest.raises(InferenceUnavailable):
        await client.embed(["x"])


async def test_a_refused_request_is_a_failure_not_unavailability(serving: Any) -> None:
    """The assistant is there and said no. Retrying elsewhere would not help."""
    start, _ = serving
    client = await start(Stub(status=400, body={"error": "bad prompt"}))
    with pytest.raises(InferenceFailed):
        await client.generate("anything")


# --- generation -------------------------------------------------------------


async def test_generation_returns_the_text_and_the_token_count(serving: Any) -> None:
    start, _ = serving
    stub = Stub(body={"content": "Ninety days.", "tokens_predicted": 4})
    client = await start(stub)

    result = await client.generate("How long is the notice period?", max_tokens=64)
    assert result.text == "Ninety days."
    assert result.tokens == 4
    assert stub.requests[0]["n_predict"] == 64


async def test_an_answer_with_no_text_is_a_failure_not_an_empty_answer(serving: Any) -> None:
    """Coercing this to "" produces an answer the user will believe."""
    start, _ = serving
    client = await start(Stub(body={"tokens_predicted": 0}))
    with pytest.raises(InferenceFailed, match="no text"):
        await client.generate("anything")


async def test_a_non_json_response_is_a_failure(serving: Any) -> None:
    start, _ = serving
    client = await start(Stub(raw=b"<html>gateway</html>"))
    with pytest.raises(InferenceFailed, match="not JSON"):
        await client.generate("anything")


# --- embedding --------------------------------------------------------------


async def test_embedding_returns_one_vector_per_text(serving: Any) -> None:
    start, _ = serving
    client = await start(
        Stub(body={"data": [{"embedding": [0.1, 0.2]}, {"embedding": [0.3, 0.4]}]})
    )
    vectors = await client.embed(["a", "b"])
    assert vectors == [[0.1, 0.2], [0.3, 0.4]]


async def test_embedding_nothing_asks_nothing(settings: Settings, tmp_path: Path) -> None:
    """No request, and therefore no unavailability either.

    Embedding an empty batch is a no-op, and making it fail because the
    assistant happens to be down would stop an ingest that had nothing to do.
    """
    client = InferenceClient(
        settings.model_copy(update={"inference_socket": tmp_path / "inference.sock"})
    )
    assert await client.embed([]) == []


async def test_a_short_batch_of_embeddings_is_a_failure(serving: Any) -> None:
    """Two texts in, one vector out. Pairing them up by position would attach
    one document's vector to another document."""
    start, _ = serving
    client = await start(Stub(body={"data": [{"embedding": [0.1]}]}))
    with pytest.raises(InferenceFailed, match="Asked for 2"):
        await client.embed(["a", "b"])


# --- reranking --------------------------------------------------------------


async def test_reranking_returns_indices_best_first(serving: Any) -> None:
    """Indices, not documents.

    The caller already holds the passages and their provenance; copying text
    back through a scoring call is how a citation loses the chunk it came from.
    """
    start, _ = serving
    client = await start(
        Stub(
            body={
                "results": [
                    {"index": 0, "relevance_score": 0.2},
                    {"index": 1, "relevance_score": 0.9},
                ]
            }
        )
    )
    assert await client.rerank("q", ["a", "b"]) == [(1, 0.9), (0, 0.2)]


async def test_reranking_nothing_asks_nothing(settings: Settings, tmp_path: Path) -> None:
    client = InferenceClient(
        settings.model_copy(update={"inference_socket": tmp_path / "inference.sock"})
    )
    assert await client.rerank("q", []) == []


# --- the rule about model names ---------------------------------------------


def test_the_client_names_no_model() -> None:
    """Profiles select models. A name here cannot change without a release."""
    import askwell.inference.client as module

    source = Path(module.__file__ or "").read_text(encoding="utf-8")
    assert not re.search(r"\b(qwen|bge-|mistral|gemma|phi-?[0-9])\b", source, re.I)
