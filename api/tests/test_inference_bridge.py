"""The bridge's routing.

One socket in front of three processes. The containers should not have to know
how many there are or on which ports — and they must not, because the number
changed once already and would otherwise have been a change in every caller.

Why three: one llama.cpp process cannot serve all three roles. `--reranking`
needs a reranker model and is mutually exclusive with generation, and a
generation model's embeddings are 2560 dimensions where the schema is
`vector(1024)` — so the database would refuse them rather than storing
something merely poor. Measured, not assumed (issue #89).
"""

import pytest

from askwell.config import Settings
from askwell.inference.bridge import _route


@pytest.fixture
def ports(settings: Settings) -> Settings:
    return settings.model_copy(
        update={"inference_upstream_port": 8080, "embedding_port": 8081, "reranker_port": 8082}
    )


@pytest.mark.parametrize(
    ("request_line", "expected_port", "expected_role"),
    [
        (b"POST /completion HTTP/1.1", 8080, "generation"),
        (b"POST /v1/chat/completions HTTP/1.1", 8080, "generation"),
        (b"POST /v1/embeddings HTTP/1.1", 8081, "embedding"),
        (b"POST /embedding HTTP/1.1", 8081, "embedding"),
        (b"POST /v1/rerank HTTP/1.1", 8082, "reranking"),
        (b"POST /rerank HTTP/1.1", 8082, "reranking"),
    ],
)
def test_each_path_reaches_the_process_that_can_answer_it(
    ports: Settings, request_line: bytes, expected_port: int, expected_role: str
) -> None:
    assert _route(ports, request_line) == (expected_port, expected_role)


@pytest.mark.parametrize(
    "request_line",
    [b"GET /health HTTP/1.1", b"GET /props HTTP/1.1", b"POST /tokenize HTTP/1.1"],
)
def test_llama_cpps_other_endpoints_still_work(ports: Settings, request_line: bytes) -> None:
    """Generation is the default rather than an error.

    llama.cpp serves a good deal more than the three endpoints named here, and
    refusing everything unrecognised would break them for no benefit.
    """
    port, role = _route(ports, request_line)
    assert port == 8080
    assert role == "generation"


@pytest.mark.parametrize(
    "request_line",
    [b"", b"garbage", b"POST", b"\xff\xfe not utf-8"],
)
def test_an_unreadable_request_line_still_reaches_something(
    ports: Settings, request_line: bytes
) -> None:
    """A wrong guess reaches a process that answers 404 itself.

    That is a better failure than this file inventing an HTTP error, which
    would make the bridge a second place that explains request problems.
    """
    port, _ = _route(ports, request_line)
    assert port == 8080


def test_the_bridge_only_ever_dials_loopback() -> None:
    """It is the one container with host networking.

    `docs/architecture.md` §5 names that rather than glossing it, and the
    reason it is acceptable is that every connection in this file is to
    127.0.0.1 — a guarantee you get by reading fifty lines, not one the network
    enforces. A hostname appearing here would remove it.
    """
    from pathlib import Path

    import askwell.inference.bridge as module

    source = Path(module.__file__ or "").read_text(encoding="utf-8")
    assert 'UPSTREAM_HOST = "127.0.0.1"' in source
    for forbidden in ("0.0.0.0", "host.containers.internal", "http://"):
        assert forbidden not in source.replace("# ", ""), f"{forbidden} appears in the bridge"
