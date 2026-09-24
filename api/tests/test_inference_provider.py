"""The online backend. `M8-ONLINE-BE-170`.

No network: a provider is `httpx.MockTransport`, and the egress proxy is a
listener on the loopback interface inside this test's own process that
records what it was asked and answers the way `askwell.egress` does.
"""

import asyncio
import base64
import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from askwell.config import Settings
from askwell.inference import provider
from askwell.inference.client import StreamChunk
from askwell.inference.provider import OnlineClient, OnlineFailed, OnlineTarget

DESTINATION = "api.provider.example:443"
SENTINEL_KEY = "sk-sentinel-never-repeat-me"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url="postgresql://askwell:pw@127.0.0.1:1/askwell",  # type: ignore[arg-type]
        sandbox_database_url="postgresql://x:x@127.0.0.1:1/postgres",  # type: ignore[arg-type]
        sandbox_owner_password="pw",  # type: ignore[arg-type]
        sandbox_readonly_password="pw",  # type: ignore[arg-type]
        trace_dir=tmp_path / "traces",
        online_ai_destination=DESTINATION,
        online_ai_model="provider-model",
    )


def _target(api_key: str | None = None) -> OnlineTarget:
    return OnlineTarget(
        destination=DESTINATION,
        model="provider-model",
        proxy_username="conversation-abc",
        proxy_password="token",
        api_key=api_key,
    )


def _sse(*events: dict[str, object] | str) -> bytes:
    lines = []
    for event in events:
        lines.append(f"data: {event if isinstance(event, str) else json.dumps(event)}\n\n")
    return "".join(lines).encode("utf-8")


def _delta(text: str, finish: str | None = None) -> dict[str, object]:
    return {"choices": [{"index": 0, "delta": {"content": text}, "finish_reason": finish}]}


def _client(
    settings: Settings,
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    api_key: str | None = None,
) -> OnlineClient:
    return OnlineClient(settings, _target(api_key), transport=httpx.MockTransport(handler))


async def _collect(client: OnlineClient) -> list[StreamChunk]:
    return [chunk async for chunk in client.stream_generate("SYSTEM", "USER", timeout_seconds=5.0)]


async def test_an_answer_streams_as_the_local_clients_chunks(settings: Settings) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = _sse(_delta("Notice is "), _delta("ninety days [1]."), _delta("", "stop"), "[DONE]")
        return httpx.Response(200, content=body)

    chunks = await _collect(_client(settings, handler))

    assert [chunk.text for chunk in chunks] == ["Notice is ", "ninety days [1].", ""]
    assert chunks[-1].done and not chunks[-1].truncated
    assert chunks[-1].timings is None, "a provider's timing is not llama.cpp's; never mixed in"

    (request,) = seen
    assert request.url.scheme == "https"
    assert f"{request.url.host}:{request.url.port or 443}" == DESTINATION
    assert request.url.path == "/v1/chat/completions"
    payload = json.loads(request.content)
    assert payload["model"] == "provider-model"
    assert payload["stream"] is True
    # Two messages, not one templated string, and no `<think>` prefill.
    assert payload["messages"] == [
        {"role": "system", "content": "SYSTEM"},
        {"role": "user", "content": "USER"},
    ]
    assert "Authorization" not in request.headers, "no key is sent when none is held"


async def test_length_is_truncation(settings: Settings) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_sse(_delta("Partial", "length")))

    chunks = await _collect(_client(settings, handler))
    assert chunks[-1].done and chunks[-1].truncated


async def test_a_key_passed_in_is_presented_as_a_bearer_token(settings: Settings) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=_sse(_delta("ok", "stop")))

    await _collect(_client(settings, handler, api_key=SENTINEL_KEY))
    assert seen[0].headers["Authorization"] == f"Bearer {SENTINEL_KEY}"


@pytest.mark.parametrize(
    ("status", "reason_code"),
    [
        (429, provider.RATE_LIMITED),
        (401, provider.REFUSED),
        (403, provider.REFUSED),
        (400, provider.REFUSED),
        (500, provider.FAILED),
        (503, provider.FAILED),
    ],
)
async def test_each_provider_answer_is_told_apart_and_never_repeats_the_body(
    settings: Settings, status: int, reason_code: str
) -> None:
    """Refused and rate-limited are distinguishable, and a provider body that
    echoes the key back never reaches the message a user or a log reads."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text=f"Incorrect API key provided: {SENTINEL_KEY}")

    with pytest.raises(OnlineFailed) as caught:
        await _collect(_client(settings, handler, api_key=SENTINEL_KEY))
    assert caught.value.reason_code == reason_code
    assert str(status) in str(caught.value)
    assert SENTINEL_KEY not in str(caught.value)


async def test_no_route_is_the_network_being_unavailable(settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Name or service not known", request=request)

    with pytest.raises(OnlineFailed) as caught:
        await _collect(_client(settings, handler))
    assert caught.value.reason_code == provider.NETWORK_UNAVAILABLE
    assert "the network is unavailable" in str(caught.value)


async def test_a_connection_lost_partway_is_interrupted(settings: Settings) -> None:
    class _Breaks(httpx.AsyncByteStream):
        async def __aiter__(self):  # type: ignore[no-untyped-def]
            yield _sse(_delta("Notice is "))
            raise httpx.ReadError("tunnel cut")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=_Breaks())

    received: list[str] = []
    with pytest.raises(OnlineFailed) as caught:
        async for chunk in _client(settings, handler).stream_generate(
            "SYSTEM", "USER", timeout_seconds=5.0
        ):
            received.append(chunk.text)
    assert received == ["Notice is "]
    assert caught.value.reason_code == provider.INTERRUPTED


async def test_a_stream_that_ends_without_finishing_is_not_passed_off_as_complete(
    settings: Settings,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_sse(_delta("Notice is ")))

    with pytest.raises(OnlineFailed) as caught:
        await _collect(_client(settings, handler))
    assert caught.value.reason_code == provider.INTERRUPTED


async def test_an_unreadable_stream_fails_rather_than_becoming_an_empty_answer(
    settings: Settings,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"data: {not json\n\n")

    with pytest.raises(OnlineFailed) as caught:
        await _collect(_client(settings, handler))
    assert caught.value.reason_code == provider.FAILED


def test_no_target_without_a_model_a_destination_or_a_credential(settings: Settings) -> None:
    credentials = ("conversation-abc", "token")
    assert provider.target(settings, credentials) is not None
    assert provider.target(settings, None) is None
    assert (
        provider.target(settings.model_copy(update={"online_ai_model": None}), credentials) is None
    )
    assert (
        provider.target(settings.model_copy(update={"online_ai_destination": None}), credentials)
        is None
    )


# --- through a proxy -----------------------------------------------------------


class _Proxy:
    """Answers every `CONNECT` with one fixed status line, and records the
    request line and headers it was sent — what `askwell.egress` reads."""

    def __init__(self, status_line: bytes) -> None:
        self.status_line = status_line
        self.requests: list[list[str]] = []

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        lines: list[str] = []
        while True:
            line = await reader.readline()
            if not line.strip():
                break
            lines.append(line.decode("latin-1").strip())
        self.requests.append(lines)
        writer.write(self.status_line + b"Connection: close\r\n\r\n")
        await writer.drain()
        writer.close()


@pytest.mark.parametrize(
    ("status_line", "reason_code"),
    [
        (b"HTTP/1.1 403 Forbidden\r\n", provider.NOT_AUTHORISED),
        (b"HTTP/1.1 502 Bad Gateway\r\n", provider.NETWORK_UNAVAILABLE),
    ],
)
async def test_through_the_proxy_with_the_conversations_credential_one_tunnel_per_call(
    settings: Settings, status_line: bytes, reason_code: str
) -> None:
    """The call is a `CONNECT` to the destination carrying the credential
    `askwell.egress` checks, and each call opens its own tunnel — so the
    proxy's per-conversation count is a count of provider requests (#731).
    The proxy's two refusals mean different things and are reported so."""
    proxy = _Proxy(status_line)
    server = await asyncio.start_server(proxy.handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    local = settings.model_copy(
        update={"egress_proxy_host": "127.0.0.1", "egress_proxy_port": port}
    )
    client = OnlineClient(local, _target())
    try:
        for _ in range(2):
            with pytest.raises(OnlineFailed) as caught:
                await _collect(client)
            assert caught.value.reason_code == reason_code
    finally:
        server.close()
        await server.wait_closed()

    assert len(proxy.requests) == 2, "one tunnel per call, never a pooled one"
    for request in proxy.requests:
        assert request[0] == f"CONNECT {DESTINATION} HTTP/1.1"
        expected = base64.b64encode(b"conversation-abc:token").decode("ascii")
        assert f"Proxy-Authorization: Basic {expected}" in request
