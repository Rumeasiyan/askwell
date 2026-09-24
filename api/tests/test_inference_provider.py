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
from askwell.inference.provider import OnlineClient, OnlineFailed, OnlineTarget, Transmission
from askwell.provider_key import Provider, ProviderKey

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


async def test_a_rejected_key_is_the_provider_rejecting_it_never_askwell_broken(
    settings: Settings,
) -> None:
    """`M8-KEY-BE-173`: the fix for a 401 is the user's key, so that is what
    the message says — and it never carries the key, even when the
    provider's own body does."""
    for status in (401, 403):

        def handler(_request: httpx.Request, status: int = status) -> httpx.Response:
            return httpx.Response(status, text=f"Incorrect API key provided: {SENTINEL_KEY}")

        with pytest.raises(OnlineFailed) as caught:
            await _collect(_client(settings, handler, api_key=SENTINEL_KEY))
        assert caught.value.reason_code == provider.REFUSED
        message = str(caught.value)
        assert message.startswith("The online provider rejected your key")
        assert "Askwell" not in message
        assert SENTINEL_KEY not in message


async def test_the_proxy_not_answering_is_askwells_gateway_not_the_network(
    settings: Settings,
) -> None:
    """Issue #735. Every call goes through the egress proxy, so a connection
    that could not be opened is the proxy not running. "The network is
    unavailable" is kept for the proxy's own 502, below."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused", request=request)

    with pytest.raises(OnlineFailed) as caught:
        await _collect(_client(settings, handler))
    assert caught.value.reason_code == provider.FAILED
    assert "network gateway is not running" in str(caught.value)
    assert "the network is unavailable" not in str(caught.value)


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


def test_the_target_is_the_stored_keys_provider_and_needs_a_credential() -> None:
    credentials = ("conversation-abc", "token")
    key = ProviderKey(
        provider=Provider(destination=DESTINATION, model="provider-model"), api_key=SENTINEL_KEY
    )
    online_target = provider.target(credentials, key)
    assert online_target is not None
    assert (online_target.destination, online_target.model) == (DESTINATION, "provider-model")
    assert online_target.api_key == SENTINEL_KEY
    assert provider.target(None, key) is None
    assert provider.target(credentials, None) is None
    # Neither secret is in a repr a log line or traceback could capture.
    assert SENTINEL_KEY not in repr(online_target)
    assert "token" not in repr(online_target)
    assert SENTINEL_KEY not in repr(key)


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
            # The tunnel never opened, so the body never left (`M8-ONLINE-OBS-172`).
            assert client.last_transmission is not None
            assert client.last_transmission.content_sent is False
            assert client.last_transmission.status_code is None
            assert client.last_transmission.outcome == reason_code
    finally:
        server.close()
        await server.wait_closed()

    assert len(proxy.requests) == 2, "one tunnel per call, never a pooled one"
    for request in proxy.requests:
        assert request[0] == f"CONNECT {DESTINATION} HTTP/1.1"
        expected = base64.b64encode(b"conversation-abc:token").decode("ascii")
        assert f"Proxy-Authorization: Basic {expected}" in request


# --- what each call leaves behind (`M8-ONLINE-OBS-172`) ---------------------------


async def test_a_call_records_exactly_the_bytes_it_sent_and_how_it_ended(
    settings: Settings,
) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=_sse(_delta("ok", "stop")))

    client = _client(settings, handler)
    assert client.last_transmission is None, "no record before any call"
    await _collect(client)

    (request,) = seen
    transmission = client.last_transmission
    assert isinstance(transmission, Transmission)
    assert transmission.request_bytes == len(request.content), "the bytes sent, not an estimate"
    assert transmission.content_sent is True
    assert transmission.status_code == 200
    assert transmission.outcome == provider.ANSWERED
    assert transmission.destination == DESTINATION
    assert transmission.model == "provider-model"
    assert transmission.sent_at.tzinfo is not None


async def test_the_body_carries_the_prompt_and_nothing_about_the_user(
    settings: Settings,
) -> None:
    """Default-deny, read from the wire: the request body has the generation
    parameters and the two prompt messages, and no field that identifies the
    person, the machine, the conversation or the file a passage came from."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=_sse(_delta("ok", "stop")))

    await _collect(_client(settings, handler))

    (request,) = seen
    payload = json.loads(request.content)
    assert set(payload) == {"model", "messages", "max_tokens", "temperature", "stream"}
    assert [set(message) for message in payload["messages"]] == [{"role", "content"}] * 2
    assert "conversation-abc" not in request.content.decode("utf-8")
    assert set(request.headers) <= {
        "host",
        "accept",
        "accept-encoding",
        "connection",
        "user-agent",
        "content-type",
        "content-length",
    }


@pytest.mark.parametrize(
    ("status", "reason_code"), [(401, provider.REFUSED), (500, provider.FAILED)]
)
async def test_a_request_the_provider_refused_still_left_the_machine(
    settings: Settings, status: int, reason_code: str
) -> None:
    client = _client(settings, lambda _r: httpx.Response(status))
    with pytest.raises(OnlineFailed):
        await _collect(client)
    transmission = client.last_transmission
    assert transmission is not None
    assert transmission.content_sent is True, "the provider answered, so it had the body"
    assert transmission.status_code == status
    assert transmission.outcome == reason_code


async def test_no_route_means_nothing_left(settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    client = _client(settings, handler)
    with pytest.raises(OnlineFailed):
        await _collect(client)
    assert client.last_transmission is not None
    assert client.last_transmission.content_sent is False
    assert client.last_transmission.outcome == provider.FAILED


async def test_a_stream_closed_partway_is_recorded_as_stopped(settings: Settings) -> None:
    client = _client(
        settings,
        lambda _r: httpx.Response(200, content=_sse(_delta("one "), _delta("two", "stop"))),
    )
    stream = client.stream_generate("SYSTEM", "USER", timeout_seconds=5.0)
    first = await anext(stream)
    assert first.text == "one "
    await stream.aclose()
    assert client.last_transmission is not None
    assert client.last_transmission.content_sent is True
    assert client.last_transmission.outcome == provider.STOPPED
