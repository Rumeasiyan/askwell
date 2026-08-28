"""The reranking pass, without a database. `M1-ASK-RET-036`.

`retrieve._rerank` is what turns fused order into reranked order; every
acceptance criterion about reordering, the bounded window, and graceful
degradation is a fact about it alone. `test_retrieve_records.py` covers it
wired into `retrieve()` against real Postgres.

The transport is a real Unix socket, matching `test_inference_client.py`'s
own reasoning: mocking httpx would test the mock, and a socket is what the
containers actually dial.
"""

import asyncio
import json
import re
import uuid
from pathlib import Path
from typing import Any

import pytest_asyncio

from askwell import retrieve as retrieve_module
from askwell.config import Settings
from askwell.inference.client import InferenceClient


def _ready(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "state.json").write_text(
        json.dumps({"state": "ready", "model": "a-model.gguf", "acceleration": "cpu"}),
        encoding="utf-8",
    )


class Stub:
    """A Unix socket speaking just enough HTTP to answer one request."""

    def __init__(self, status: int = 200, body: Any = None) -> None:
        self.status = status
        self.body = body
        self.requests: list[dict[str, Any]] = []

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        head = await reader.readuntil(b"\r\n\r\n")
        length = 0
        match = re.search(rb"content-length:\s*(\d+)", head, re.I)
        if match:
            length = int(match.group(1))
        payload = await reader.readexactly(length) if length else b"{}"
        self.requests.append(json.loads(payload or b"{}"))

        content = json.dumps(self.body).encode()
        writer.write(
            f"HTTP/1.1 {self.status} X\r\nContent-Type: application/json\r\n"
            f"Content-Length: {len(content)}\r\nConnection: close\r\n\r\n".encode()
            + content
        )
        await writer.drain()
        writer.close()


@pytest_asyncio.fixture
async def serving(settings: Settings, tmp_path: Path):  # type: ignore[no-untyped-def]
    socket_path = tmp_path / "inference.sock"
    _ready(tmp_path)
    configured = settings.model_copy(update={"inference_socket": socket_path})

    servers: list[asyncio.AbstractServer] = []

    async def start(stub: Stub, settings_override: Settings | None = None) -> InferenceClient:
        server = await asyncio.start_unix_server(stub.handle, path=str(socket_path))
        servers.append(server)
        return InferenceClient(settings_override or configured)

    yield start, configured

    for server in servers:
        server.close()
        await server.wait_closed()


def _candidate(content: str, score: float = 0.5) -> retrieve_module.Candidate:
    return retrieve_module.Candidate(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        content=content,
        heading=None,
        page_from=1,
        page_to=1,
        score=score,
        dense_score=score,
        lexical_score=None,
    )


async def test_reranking_reorders_and_both_scores_are_retained(serving: Any) -> None:
    candidates = [_candidate("wrong supplier"), _candidate("right supplier")]
    client = await (serving)[0](
        Stub(
            body={
                "results": [
                    {"index": 0, "relevance_score": -2.0},
                    {"index": 1, "relevance_score": 3.0},
                ]
            }
        )
    )
    settings = (serving)[1]

    reranked, did_rerank, duration_ms, reason = await retrieve_module._rerank(
        client, settings, "who is the right supplier", candidates
    )

    assert did_rerank is True
    assert reason is None
    assert duration_ms is not None and duration_ms >= 0
    assert [candidate.content for candidate in reranked] == ["right supplier", "wrong supplier"]
    # the fused score survives reordering, untouched
    assert reranked[0].score == candidates[1].score
    assert reranked[0].rerank_score == 3.0
    assert reranked[1].rerank_score == -2.0


async def test_fewer_candidates_than_the_window_needs_no_padding(serving: Any) -> None:
    candidates = [_candidate("only one")]
    stub = Stub(body={"results": [{"index": 0, "relevance_score": 1.0}]})
    client = await (serving)[0](stub)
    settings = (serving)[1]

    reranked, did_rerank, _duration, _reason = await retrieve_module._rerank(
        client, settings, "q", candidates
    )

    assert did_rerank is True
    assert len(reranked) == 1
    assert len(stub.requests[0]["documents"]) == 1


async def test_candidates_beyond_the_window_are_appended_unreordered(serving: Any) -> None:
    candidates = [_candidate("a"), _candidate("b"), _candidate("c")]
    stub = Stub(body={"results": [{"index": 0, "relevance_score": 1.0}]})
    settings = (serving)[1].model_copy(update={"rerank_candidate_count": 1})
    client = await (serving)[0](stub, settings)

    reranked, did_rerank, _duration, _reason = await retrieve_module._rerank(
        client, settings, "q", candidates
    )

    assert did_rerank is True
    assert len(stub.requests[0]["documents"]) == 1
    # only "a" was ever sent to the reranker; "b" and "c" keep their fused order
    assert [candidate.content for candidate in reranked] == ["a", "b", "c"]
    assert reranked[0].rerank_score == 1.0
    assert reranked[1].rerank_score is None
    assert reranked[2].rerank_score is None


async def test_reranker_unavailable_degrades_to_fusion_order(
    settings: Settings, tmp_path: Path
) -> None:
    candidates = [_candidate("a"), _candidate("b")]
    client = InferenceClient(
        settings.model_copy(update={"inference_socket": tmp_path / "no-such.sock"})
    )

    reranked, did_rerank, duration_ms, reason = await retrieve_module._rerank(
        client, settings, "q", candidates
    )

    assert did_rerank is False
    assert duration_ms is None
    assert reason is not None and "unavailable" in reason
    assert reranked == candidates
    assert all(candidate.rerank_score is None for candidate in reranked)


async def test_reranker_failure_degrades_to_fusion_order(serving: Any) -> None:
    candidates = [_candidate("a"), _candidate("b")]
    client = await (serving)[0](Stub(status=500, body={"error": "boom"}))
    settings = (serving)[1]

    reranked, did_rerank, duration_ms, reason = await retrieve_module._rerank(
        client, settings, "q", candidates
    )

    assert did_rerank is False
    assert duration_ms is None
    assert reason is not None and "failed" in reason
    assert reranked == candidates


async def test_no_candidates_skips_reranking_without_asking_the_assistant(
    settings: Settings, tmp_path: Path
) -> None:
    client = InferenceClient(
        settings.model_copy(update={"inference_socket": tmp_path / "no-such.sock"})
    )

    reranked, did_rerank, duration_ms, reason = await retrieve_module._rerank(
        client, settings, "q", []
    )

    assert reranked == []
    assert did_rerank is False
    assert duration_ms is None
    assert reason is None


async def test_tied_scores_keep_a_stable_order(serving: Any) -> None:
    """`InferenceClient.rerank`'s own sort is stable; this proves reranking
    inherits that rather than losing it in reconstruction."""
    candidates = [_candidate("first"), _candidate("second"), _candidate("third")]
    client = await (serving)[0](
        Stub(
            body={
                "results": [
                    {"index": 0, "relevance_score": 0.5},
                    {"index": 1, "relevance_score": 0.5},
                    {"index": 2, "relevance_score": 0.5},
                ]
            }
        )
    )
    settings = (serving)[1]

    reranked, _did_rerank, _duration, _reason = await retrieve_module._rerank(
        client, settings, "q", candidates
    )

    assert [candidate.content for candidate in reranked] == ["first", "second", "third"]
