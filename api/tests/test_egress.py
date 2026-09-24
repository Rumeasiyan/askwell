"""The default-deny egress proxy.

The network half of C1 cannot be tested here — an internal network having no
route is a property of the stack, verified by running it. What is testable is
the part that decides: what counts as an attempt to leave the machine, what
counts as Askwell checking its own proxy is alive, and what the refusal says.

The distinction between those first two is not a detail. Getting it wrong in
either direction ruins the number the settings screen shows: count the health
probe and "something tried to phone home" becomes "Askwell is running";
miss a real attempt and the number is a reassurance rather than a measurement.
"""

import asyncio
import contextlib
import socket
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio

from askwell.config import Settings
from askwell.egress import (
    CONVERSATION_CREDENTIAL_USER_PREFIX,
    CONVERSATION_GRANT_KEY_PREFIX,
    GRANT_KEY_PREFIX,
    PERMITTED_BY_CONVERSATION_KEY,
    PERMITTED_COUNTER_KEY,
    REFUSAL_BODY,
    EgressProxy,
    _conversation_credential,
    close_all_conversation_grants,
    close_conversation_grant,
    close_grant,
    credential_digest,
    open_conversation_grant,
    open_grant,
    parse_destination,
)


@pytest.mark.parametrize(
    ("request_line", "expected"),
    [
        ("CONNECT example.com:443 HTTP/1.1", "example.com:443"),
        ("CONNECT 1.1.1.1:443 HTTP/1.1", "1.1.1.1:443"),
        ("GET http://example.com/ HTTP/1.1", "http://example.com/"),
        ("POST https://telemetry.example.com/v1 HTTP/1.1", "https://telemetry.example.com/v1"),
        ("connect example.com:443 HTTP/1.1", "example.com:443"),
    ],
)
def test_a_destination_is_read_from_either_proxy_form(request_line: str, expected: str) -> None:
    """CONNECT is how HTTPS goes through a proxy; an absolute URI is how HTTP does.

    A direct IP address is a destination like any other — refusing hostnames
    but not addresses would be a hole with a hostname-shaped edge.
    """
    assert parse_destination(request_line) == expected


@pytest.mark.parametrize(
    "request_line",
    ["GET / HTTP/1.1", "GET /health HTTP/1.1", "", "garbage"],
)
def test_a_non_proxy_request_has_no_destination(request_line: str) -> None:
    """Something spoke to the proxy as if it were an origin server.

    Still refused, but the log must not claim it named a host — that would be
    inventing evidence about what was attempted.
    """
    assert parse_destination(request_line) is None


def test_the_refusal_explains_itself_to_whoever_finds_it_in_a_log() -> None:
    """Whoever reads this is debugging something unexpected."""
    assert "Askwell refused this request" in REFUSAL_BODY
    assert "unless you say so" in REFUSAL_BODY
    assert "dependencies tried to reach the network" in REFUSAL_BODY


@pytest_asyncio.fixture
async def proxy_port(settings: Settings) -> AsyncIterator[tuple[int, EgressProxy]]:
    """The real handler, on a real socket, on loopback."""
    proxy = EgressProxy(settings.model_copy(update={"redis_port": 1}))
    server = await asyncio.start_server(proxy.handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    async with server:
        yield port, proxy


async def test_a_request_is_refused_with_403(proxy_port: tuple[int, EgressProxy]) -> None:
    port, proxy = proxy_port
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(b"CONNECT example.com:443 HTTP/1.1\r\n\r\n")
    await writer.drain()
    response = await asyncio.wait_for(reader.read(2048), timeout=5)
    writer.close()

    assert b"403 Forbidden" in response
    assert b"X-Askwell-Egress: refused" in response
    assert proxy.refused == 1


async def test_a_liveness_probe_is_not_counted(proxy_port: tuple[int, EgressProxy]) -> None:
    """Askwell's own health probe opens a connection and closes it.

    Counting it would add one to the refusal figure every few seconds, turning
    a number that means "something tried to phone home" into a number that
    means "Askwell is running" — worse than not having the number at all.
    """
    port, proxy = proxy_port
    _, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.close()
    with pytest.raises((OSError, asyncio.CancelledError)):
        await writer.wait_closed()
        raise OSError("closed cleanly")

    await asyncio.sleep(0.2)
    assert proxy.refused == 0


async def test_a_client_that_says_nothing_at_all_is_still_not_forwarded(
    proxy_port: tuple[int, EgressProxy],
) -> None:
    """Not counted, but certainly not connected to anything either."""
    port, proxy = proxy_port
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    # No request line. The handler closes rather than waiting forever.
    result = await asyncio.wait_for(reader.read(1024), timeout=8)
    writer.close()
    assert result == b""
    assert proxy.refused == 0


async def test_counting_failure_never_prevents_refusing(
    proxy_port: tuple[int, EgressProxy],
) -> None:
    """Redis is pointed at a dead port by the fixture.

    A proxy that crashed on a Redis hiccup would take the deny with it, which
    turns a monitoring problem into a security one.
    """
    port, proxy = proxy_port
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(b"GET http://example.com/ HTTP/1.1\r\n\r\n")
    await writer.drain()
    response = await asyncio.wait_for(reader.read(2048), timeout=5)
    writer.close()

    assert b"403 Forbidden" in response
    assert proxy.refused == 1


async def test_a_permitted_connect_is_forwarded_end_to_end(
    proxy_port: tuple[int, EgressProxy],
) -> None:
    """`M7-UPDATE-BE-161`: the one destination the update check needs, and
    only once something has actually permitted it — `_permitted_destination`
    itself is exercised for real in `test_update_check.py`; here a fixed
    value stands in so this test needs no live Redis, the same convention
    every other test in this file already follows.
    """

    async def echo(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        data = await reader.read(1024)
        writer.write(data.upper())
        await writer.drain()
        writer.close()

    upstream = await asyncio.start_server(echo, "127.0.0.1", 0)
    upstream_port = upstream.sockets[0].getsockname()[1]
    destination = f"127.0.0.1:{upstream_port}"

    port, proxy = proxy_port

    async def _fixed_destination() -> str:
        return destination

    proxy._permitted_destination = _fixed_destination  # type: ignore[method-assign]

    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(f"CONNECT {destination} HTTP/1.1\r\nHost: {destination}\r\n\r\n".encode())
        await writer.drain()
        established = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=5)
        assert b"200 Connection Established" in established

        writer.write(b"hello")
        await writer.drain()
        echoed = await asyncio.wait_for(reader.read(1024), timeout=5)
        writer.close()

        assert echoed == b"HELLO"
        assert proxy.permitted == 1
        assert proxy.refused == 0
    finally:
        upstream.close()
        await upstream.wait_closed()


async def test_a_connect_to_anything_else_is_refused_even_with_a_permit_set(
    proxy_port: tuple[int, EgressProxy],
) -> None:
    """A permit is exactly one destination. Everything else is still 403,
    permit or no permit."""
    port, proxy = proxy_port

    async def _fixed_destination() -> str:
        return "raw.githubusercontent.com:443"

    proxy._permitted_destination = _fixed_destination  # type: ignore[method-assign]

    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(b"CONNECT some-other-host.example:443 HTTP/1.1\r\n\r\n")
    await writer.drain()
    response = await asyncio.wait_for(reader.read(2048), timeout=5)
    writer.close()

    assert b"403 Forbidden" in response
    assert proxy.refused == 1
    assert proxy.permitted == 0


def test_there_is_no_allowlist_to_configure(settings: Settings) -> None:
    """No destination may be configured statically.

    An allowlist is the thing that turns default-deny into deny-except, and
    "except" is a list that only ever grows. Authorisation is per conversation
    and time-bound, and it arrives in M8 as a decision the user makes — not as
    a setting somebody edits once.
    """
    import askwell.egress as egress

    source = egress.__file__ or ""
    with open(source, encoding="utf-8") as handle:
        text = handle.read()
    for forbidden in ("ALLOWED_HOSTS", "allowlist", "ALLOWLIST", "permit_host"):
        assert forbidden not in text, f"{forbidden} appears in the proxy"
    assert not any("allow" in name.lower() for name in settings.model_dump())


# --- per-turn grants: `M6.5-WEB-SEC-187` -------------------------------------


class FakeGrantRedis:
    """A Redis stand-in for `open_grant`/`close_grant`/`_grant_permits` — the
    same convention `test_network.py`'s `FakeRedis` already follows rather
    than a real Redis, which nothing in this test suite touches (`AGENTS.md`
    §6, `test-db`'s own tests fake Redis too).

    Tracks the `ex=` a `set` was called with, so a test can assert the hard
    expiry was actually requested rather than only that the key exists.
    """

    def __init__(self, store: dict[str, str]) -> None:
        self.store = store
        self.set_calls: list[tuple[str, str, int | None]] = []
        self.constructed = 0
        FakeGrantRedis._last = self  # type: ignore[attr-defined]

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.set_calls.append((key, value, ex))
        self.store[key] = value

    async def get(self, key: str) -> bytes | None:
        value = self.store.get(key)
        return value.encode("utf-8") if value is not None else None

    async def delete(self, key: str) -> int:
        return 1 if self.store.pop(key, None) is not None else 0

    async def scan(
        self, cursor: int, match: str | None = None, count: int | None = None
    ) -> tuple[int, list[str]]:
        prefix = (match or "*").rstrip("*")
        keys = [key for key in self.store if key.startswith(prefix)]
        return 0, keys

    async def mget(self, keys: list[str]) -> list[bytes | None]:
        return [self.store[key].encode("utf-8") if key in self.store else None for key in keys]

    async def aclose(self) -> None:
        return None


@pytest.fixture
def grant_store(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    store: dict[str, str] = {}
    constructed: list[FakeGrantRedis] = []

    def _build(**_kwargs: Any) -> FakeGrantRedis:
        client = FakeGrantRedis(store)
        constructed.append(client)
        return client

    import redis.asyncio as redis

    monkeypatch.setattr(redis, "Redis", _build)
    return store


async def test_a_grant_with_no_acceptance_is_refused_and_never_touches_redis(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`open_grant`'s own `accepted` argument is the backstop the ticket
    calls "an anomaly worth reading" — refused here, at the mechanism,
    regardless of what the caller believed. Redis is never even reached: a
    call that constructs a client here would be trusting the caller first
    and checking second, which is the property this test exists to rule
    out."""

    def _fail(**_kwargs: Any) -> Any:
        raise AssertionError("Redis must not be touched for an unaccepted grant")

    import redis.asyncio as redis

    monkeypatch.setattr(redis, "Redis", _fail)

    opened = await open_grant(
        settings,
        turn_id="turn-1",
        destination="html.duckduckgo.com:443",
        accepted=False,
        ttl_seconds=30.0,
    )
    assert opened is False


async def test_an_accepted_grant_is_set_with_a_hard_expiry(
    settings: Settings, grant_store: dict[str, str]
) -> None:
    opened = await open_grant(
        settings,
        turn_id="turn-1",
        destination="html.duckduckgo.com:443",
        accepted=True,
        ttl_seconds=30.0,
    )
    assert opened is True
    (key,) = grant_store
    assert key == f"{GRANT_KEY_PREFIX}turn-1"
    assert grant_store[key] == "html.duckduckgo.com:443"


async def test_closing_a_grant_removes_it(settings: Settings, grant_store: dict[str, str]) -> None:
    await open_grant(
        settings,
        turn_id="turn-1",
        destination="html.duckduckgo.com:443",
        accepted=True,
        ttl_seconds=30.0,
    )
    await close_grant(settings, "turn-1")
    assert grant_store == {}


async def test_closing_a_grant_that_was_never_opened_is_a_no_op(
    settings: Settings, grant_store: dict[str, str]
) -> None:
    await close_grant(settings, "turn-never-opened")
    assert grant_store == {}


async def test_two_escalations_hold_two_independent_grants(
    settings: Settings, grant_store: dict[str, str]
) -> None:
    """Never one merged grant — closing the first must not touch the
    second, even though both name the same destination."""
    await open_grant(
        settings,
        turn_id="turn-a",
        destination="html.duckduckgo.com:443",
        accepted=True,
        ttl_seconds=30.0,
    )
    await open_grant(
        settings,
        turn_id="turn-b",
        destination="html.duckduckgo.com:443",
        accepted=True,
        ttl_seconds=30.0,
    )
    assert len(grant_store) == 2

    await close_grant(settings, "turn-a")
    assert len(grant_store) == 1
    assert f"{GRANT_KEY_PREFIX}turn-b" in grant_store


async def test_a_connect_matching_an_open_grant_is_forwarded(
    proxy_port: tuple[int, EgressProxy],
) -> None:
    """The proxy's own combined check, not just the standalone functions —
    a request naming exactly the granted destination is forwarded even
    though no single global `PERMITTED_HOST_KEY` was ever set."""

    async def echo(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        data = await reader.read(1024)
        writer.write(data.upper())
        await writer.drain()
        writer.close()

    upstream = await asyncio.start_server(echo, "127.0.0.1", 0)
    upstream_port = upstream.sockets[0].getsockname()[1]
    destination = f"127.0.0.1:{upstream_port}"

    port, proxy = proxy_port

    async def _matching_grant(candidate: str) -> bool:
        return candidate == destination

    proxy._grant_permits = _matching_grant  # type: ignore[method-assign]

    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(f"CONNECT {destination} HTTP/1.1\r\nHost: {destination}\r\n\r\n".encode())
        await writer.drain()
        established = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=5)
        assert b"200 Connection Established" in established

        writer.write(b"hello")
        await writer.drain()
        echoed = await asyncio.wait_for(reader.read(1024), timeout=5)
        writer.close()

        assert echoed == b"HELLO"
        assert proxy.permitted == 1
        assert proxy.refused == 0
    finally:
        upstream.close()
        await upstream.wait_closed()


async def test_a_connect_to_a_different_host_is_refused_even_with_a_grant_open(
    proxy_port: tuple[int, EgressProxy],
) -> None:
    """A grant is exactly one destination. Anything else stays 403 while it
    is open — the ticket's own "no configuration or grant may widen the
    door" requirement."""
    port, proxy = proxy_port

    async def _matching_grant(candidate: str) -> bool:
        return candidate == "html.duckduckgo.com:443"

    proxy._grant_permits = _matching_grant  # type: ignore[method-assign]

    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(b"CONNECT some-other-host.example:443 HTTP/1.1\r\n\r\n")
    await writer.drain()
    response = await asyncio.wait_for(reader.read(2048), timeout=5)
    writer.close()

    assert b"403 Forbidden" in response
    assert proxy.refused == 1
    assert proxy.permitted == 0


# --- per-conversation authorisation: `M8-ONLINE-SEC-169` ---------------------


class FakeConversationRedis(FakeGrantRedis):
    """`FakeGrantRedis` plus what the conversation grant and its attributed
    counter need: `ttl`, many-key `delete`, and a pipeline for the counters."""

    counters: dict[str, int]
    hashes: dict[str, dict[str, int]]

    async def ttl(self, key: str) -> int:
        for stored_key, _value, ex in reversed(self.set_calls):
            if stored_key == key:
                return ex if ex is not None else -1
        return -2

    async def delete(self, *keys: str) -> int:  # type: ignore[override]
        return sum(1 for key in keys if self.store.pop(key, None) is not None)

    def pipeline(self) -> "FakeCounterPipeline":
        return FakeCounterPipeline(self)


class FakeCounterPipeline:
    def __init__(self, owner: FakeConversationRedis) -> None:
        self.owner = owner
        self.ops: list[tuple[str, str, str | None]] = []

    async def __aenter__(self) -> "FakeCounterPipeline":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    def incr(self, key: str) -> None:
        self.ops.append(("incr", key, None))

    def hincrby(self, key: str, field: str, _amount: int) -> None:
        self.ops.append(("hincrby", key, field))

    async def execute(self) -> list[int]:
        for op, key, field in self.ops:
            if op == "incr":
                self.owner.counters[key] = self.owner.counters.get(key, 0) + 1
            else:
                bucket = self.owner.hashes.setdefault(key, {})
                assert field is not None
                bucket[field] = bucket.get(field, 0) + 1
        return []


@pytest.fixture
def conversation_store(monkeypatch: pytest.MonkeyPatch) -> FakeConversationRedis:
    """One shared fake behind every `redis.Redis(...)` the proxy and the
    grant functions construct — they are separate clients against one
    server in production, and have to see each other's writes here too."""
    store: dict[str, str] = {}
    counters: dict[str, int] = {}
    hashes: dict[str, dict[str, int]] = {}
    set_calls: list[tuple[str, str, int | None]] = []

    def _build(**_kwargs: Any) -> FakeConversationRedis:
        client = FakeConversationRedis(store)
        client.counters = counters
        client.hashes = hashes
        client.set_calls = set_calls
        return client

    import redis.asyncio as redis

    monkeypatch.setattr(redis, "Redis", _build)
    probe = FakeConversationRedis(store)
    probe.counters = counters
    probe.hashes = hashes
    probe.set_calls = set_calls
    return probe


def _credential_header(conversation_id: str, token: str) -> str:
    import base64

    raw = f"{CONVERSATION_CREDENTIAL_USER_PREFIX}{conversation_id}:{token}".encode()
    return f"Proxy-Authorization: Basic {base64.b64encode(raw).decode()}\r\n"


async def _connect(
    port: int, destination: str, extra_headers: str = ""
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter, bytes]:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(
        f"CONNECT {destination} HTTP/1.1\r\nHost: {destination}\r\n{extra_headers}\r\n".encode()
    )
    await writer.drain()
    head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=5)
    return reader, writer, head


@pytest_asyncio.fixture
async def echo_upstream() -> AsyncIterator[str]:
    """An upstream that echoes upper-cased, as many times as it is sent to —
    a pooled connection sending a second request is part of what is tested."""

    async def echo(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        while data := await reader.read(1024):
            writer.write(data.upper())
            await writer.drain()
        writer.close()

    upstream = await asyncio.start_server(echo, "127.0.0.1", 0)
    try:
        yield f"127.0.0.1:{upstream.sockets[0].getsockname()[1]}"
    finally:
        upstream.close()
        await upstream.wait_closed()


@pytest_asyncio.fixture
async def conversation_proxy(
    settings: Settings, conversation_store: FakeConversationRedis
) -> AsyncIterator[tuple[int, EgressProxy]]:
    proxy = EgressProxy(settings)
    server = await asyncio.start_server(proxy.handle, "127.0.0.1", 0)
    async with server:
        yield server.sockets[0].getsockname()[1], proxy


async def test_the_credential_never_reaches_redis(
    settings: Settings, conversation_store: FakeConversationRedis
) -> None:
    """Redis holds a digest. The credential itself stays in the API process
    that minted it, so a grant outliving that process is unusable."""
    await open_conversation_grant(
        settings,
        conversation_id="conv-a",
        destination="api.example.com:443",
        token="the-secret-token",
        ttl_seconds=600,
    )
    stored = conversation_store.store[f"{CONVERSATION_GRANT_KEY_PREFIX}conv-a"]
    assert "the-secret-token" not in stored
    assert credential_digest("the-secret-token") in stored
    assert conversation_store.set_calls[-1][2] == 600, "the time bound must be a Redis expiry"


async def test_the_owning_conversation_reaches_its_one_destination_and_is_counted(
    settings: Settings,
    conversation_store: FakeConversationRedis,
    conversation_proxy: tuple[int, EgressProxy],
    echo_upstream: str,
) -> None:
    port, proxy = conversation_proxy
    await open_conversation_grant(
        settings, conversation_id="conv-a", destination=echo_upstream, token="tok", ttl_seconds=60
    )

    reader, writer, head = await _connect(port, echo_upstream, _credential_header("conv-a", "tok"))
    assert b"200 Connection Established" in head
    writer.write(b"hello")
    await writer.drain()
    assert await asyncio.wait_for(reader.read(1024), timeout=5) == b"HELLO"
    writer.close()

    assert proxy.permitted == 1
    assert proxy.refused == 0
    assert conversation_store.counters[PERMITTED_COUNTER_KEY] == 1
    assert conversation_store.hashes[PERMITTED_BY_CONVERSATION_KEY] == {
        f"conv-a\t{echo_upstream}": 1
    }


@pytest.mark.parametrize(
    "headers",
    [
        pytest.param("", id="a local conversation, or a dependency: no credential"),
        pytest.param(_credential_header("conv-b", "tok"), id="another conversation's id"),
        pytest.param(_credential_header("conv-a", "wrong"), id="the right id, wrong token"),
        pytest.param("Proxy-Authorization: Bearer tok\r\n", id="not our scheme"),
    ],
)
async def test_nothing_else_reaches_the_destination_while_one_conversation_is_online(
    settings: Settings,
    conversation_store: FakeConversationRedis,
    conversation_proxy: tuple[int, EgressProxy],
    echo_upstream: str,
    headers: str,
) -> None:
    """The ticket's own edge case: two conversations, one online and one
    local — the local one has no route out. Unlike the turn grant and the
    update-check permit, a conversation grant does not open the destination
    to everything on the network."""
    port, proxy = conversation_proxy
    await open_conversation_grant(
        settings, conversation_id="conv-a", destination=echo_upstream, token="tok", ttl_seconds=60
    )

    _reader, writer, head = await _connect(port, echo_upstream, headers)
    writer.close()

    assert b"403 Forbidden" in head
    assert proxy.refused == 1
    assert proxy.permitted == 0
    assert PERMITTED_BY_CONVERSATION_KEY not in conversation_store.hashes


async def test_the_owning_conversation_is_refused_anywhere_else(
    settings: Settings,
    conversation_store: FakeConversationRedis,
    conversation_proxy: tuple[int, EgressProxy],
    echo_upstream: str,
) -> None:
    """Exactly one destination: the credential does not widen it."""
    port, proxy = conversation_proxy
    await open_conversation_grant(
        settings, conversation_id="conv-a", destination=echo_upstream, token="tok", ttl_seconds=60
    )

    _reader, writer, head = await _connect(
        port, "elsewhere.example:443", _credential_header("conv-a", "tok")
    )
    writer.close()

    assert b"403 Forbidden" in head
    assert proxy.permitted == 0


async def test_a_revoked_conversation_is_refused_from_the_next_connection(
    settings: Settings,
    conversation_store: FakeConversationRedis,
    conversation_proxy: tuple[int, EgressProxy],
    echo_upstream: str,
) -> None:
    port, proxy = conversation_proxy
    await open_conversation_grant(
        settings, conversation_id="conv-a", destination=echo_upstream, token="tok", ttl_seconds=60
    )
    assert await close_conversation_grant(settings, "conv-a") is True

    _reader, writer, head = await _connect(port, echo_upstream, _credential_header("conv-a", "tok"))
    writer.close()

    assert b"403 Forbidden" in head
    assert proxy.permitted == 0


async def test_an_open_tunnel_is_cut_when_the_conversation_is_revoked(
    settings: Settings,
    conversation_store: FakeConversationRedis,
    conversation_proxy: tuple[int, EgressProxy],
    echo_upstream: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The in-flight edge case, decided as *cancelled*. A client keeps a
    tunnel open and sends more requests down it; revoking only new
    connections would let that pooled tunnel keep talking after the user
    said stop."""
    import askwell.egress as egress_module

    monkeypatch.setattr(egress_module, "CONVERSATION_RECHECK_SECONDS", 0.05)
    port, _proxy = conversation_proxy
    await open_conversation_grant(
        settings, conversation_id="conv-a", destination=echo_upstream, token="tok", ttl_seconds=60
    )
    reader, writer, head = await _connect(port, echo_upstream, _credential_header("conv-a", "tok"))
    assert b"200 Connection Established" in head
    writer.write(b"first")
    await writer.drain()
    assert await asyncio.wait_for(reader.read(1024), timeout=5) == b"FIRST"

    await close_conversation_grant(settings, "conv-a")

    # The tunnel is closed from the proxy's side: the client reads EOF (or a
    # reset) rather than a second answer.
    await asyncio.sleep(0.3)
    with contextlib.suppress(ConnectionError):
        writer.write(b"second")
        await writer.drain()
    try:
        after = await asyncio.wait_for(reader.read(1024), timeout=5)
    except ConnectionError:
        after = b""
    writer.close()
    assert after == b""


async def test_a_fresh_enable_cuts_a_tunnel_opened_under_the_old_credential(
    settings: Settings,
    conversation_store: FakeConversationRedis,
    conversation_proxy: tuple[int, EgressProxy],
    echo_upstream: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Off and on again inside one recheck is not "still authorised" for the
    old tunnel: it was opened under a credential that no longer exists."""
    import askwell.egress as egress_module

    monkeypatch.setattr(egress_module, "CONVERSATION_RECHECK_SECONDS", 0.05)
    port, _proxy = conversation_proxy
    await open_conversation_grant(
        settings, conversation_id="conv-a", destination=echo_upstream, token="old", ttl_seconds=60
    )
    reader, writer, _head = await _connect(port, echo_upstream, _credential_header("conv-a", "old"))
    await open_conversation_grant(
        settings, conversation_id="conv-a", destination=echo_upstream, token="new", ttl_seconds=60
    )

    try:
        after = await asyncio.wait_for(reader.read(1024), timeout=5)
    except ConnectionError:
        after = b""
    writer.close()
    assert after == b""


async def test_every_conversation_grant_is_cleared_and_reported(
    settings: Settings, conversation_store: FakeConversationRedis
) -> None:
    """What the API and the proxy each call at startup. Turn grants and the
    update-check permit are not conversation grants and are left alone."""
    for conversation_id in ("conv-a", "conv-b"):
        await open_conversation_grant(
            settings,
            conversation_id=conversation_id,
            destination="api.example.com:443",
            token="tok",
            ttl_seconds=60,
        )
    conversation_store.store[f"{GRANT_KEY_PREFIX}turn-1"] = "html.duckduckgo.com:443"

    revoked = await close_all_conversation_grants(settings)

    assert revoked == {"conv-a": "api.example.com:443", "conv-b": "api.example.com:443"}
    assert not any(k.startswith(CONVERSATION_GRANT_KEY_PREFIX) for k in conversation_store.store)
    assert f"{GRANT_KEY_PREFIX}turn-1" in conversation_store.store


async def test_the_proxy_clears_conversation_grants_when_it_starts(
    settings: Settings,
    conversation_store: FakeConversationRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A proxy restart is a restart. It revokes; it still never grants."""
    import askwell.egress as egress_module

    await open_conversation_grant(
        settings,
        conversation_id="conv-a",
        destination="api.example.com:443",
        token="t",
        ttl_seconds=60,
    )

    async def _no_register(_settings: Settings) -> None:
        return None

    class _Stop(Exception):
        pass

    async def _refuse_to_serve(*_args: Any, **_kwargs: Any) -> Any:
        raise _Stop

    monkeypatch.setattr(egress_module, "_register", _no_register)
    monkeypatch.setattr(asyncio, "start_server", _refuse_to_serve)
    with pytest.raises(_Stop):
        await egress_module.serve(settings)

    assert f"{CONVERSATION_GRANT_KEY_PREFIX}conv-a" not in conversation_store.store


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (_credential_header("conv-a", "tok").strip(), ("conv-a", "tok")),
        (
            "proxy-authorization: basic "
            + __import__("base64")
            .b64encode(f"{CONVERSATION_CREDENTIAL_USER_PREFIX}c:t:with:colons".encode())
            .decode(),
            ("c", "t:with:colons"),
        ),
        ("Proxy-Authorization: Basic !!!not-base64", None),
        (
            "Proxy-Authorization: Basic " + __import__("base64").b64encode(b"someone:tok").decode(),
            None,
        ),
        ("Host: example.com", None),
    ],
)
def test_only_a_conversation_credential_is_recognised(
    header: str, expected: tuple[str, str] | None
) -> None:
    assert _conversation_credential([header]) == expected


# --- the online-mode release test's edge cases: `M8-ONLINE-TEST-176` ------------
#
# `docs/online-release-test.md` walks these against a real provider with an
# independent capture. What is pinned here is the part the proxy decides, so a
# change that loosens it fails before anyone reaches the release run.


@pytest.mark.parametrize(
    "spelling",
    [
        pytest.param("127.0.0.1:{port}", id="the address the authorised name resolves to"),
        pytest.param("LOCALHOST:{port}", id="the same name in another case"),
        pytest.param("localhost.:{port}", id="the same name, fully qualified"),
        pytest.param("[::ffff:127.0.0.1]:{port}", id="the same address, mapped to IPv6"),
    ],
)
async def test_another_name_for_the_authorised_address_is_not_the_authorised_destination(
    settings: Settings,
    conversation_store: FakeConversationRedis,
    conversation_proxy: tuple[int, EgressProxy],
    echo_upstream: str,
    spelling: str,
) -> None:
    """The authorisation is for one named service, not for an IP address.
    `localhost` resolves to the same listener the refused spellings reach, and
    the owning conversation's own credential still opens only the name it was
    granted: two services behind one address (a shared CDN edge, say) are two
    destinations. Refusing a harmless respelling is the safe way to be wrong."""
    port, proxy = conversation_proxy
    upstream_port = echo_upstream.rpartition(":")[2]
    authorised = f"localhost:{upstream_port}"
    await open_conversation_grant(
        settings, conversation_id="conv-a", destination=authorised, token="tok", ttl_seconds=60
    )

    _reader, writer, head = await _connect(
        port, spelling.format(port=upstream_port), _credential_header("conv-a", "tok")
    )
    writer.close()
    assert b"403 Forbidden" in head
    assert proxy.permitted == 0

    # And the name itself does reach it, so the refusal above is about the
    # spelling, not about a listener nothing could reach.
    reader, writer, head = await _connect(port, authorised, _credential_header("conv-a", "tok"))
    assert b"200 Connection Established" in head
    writer.write(b"ping")
    await writer.drain()
    assert await asyncio.wait_for(reader.read(1024), timeout=5) == b"PING"
    writer.close()
    assert proxy.permitted == 1
    assert conversation_store.hashes[PERMITTED_BY_CONVERSATION_KEY] == {f"conv-a\t{authorised}": 1}


async def test_a_plain_http_request_to_the_authorised_host_is_refused_even_with_the_credential(
    settings: Settings,
    conversation_store: FakeConversationRedis,
    conversation_proxy: tuple[int, EgressProxy],
    echo_upstream: str,
) -> None:
    """A dependency speaking plain HTTP through the proxy, the way a library
    honouring `HTTP_PROXY` would, is not a tunnel to the provider. Only
    `CONNECT` is ever forwarded, and the credential does not change that."""
    port, proxy = conversation_proxy
    await open_conversation_grant(
        settings, conversation_id="conv-a", destination=echo_upstream, token="tok", ttl_seconds=60
    )

    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(
        f"GET http://{echo_upstream}/v1/models HTTP/1.1\r\nHost: {echo_upstream}\r\n"
        f"{_credential_header('conv-a', 'tok')}\r\n".encode()
    )
    await writer.drain()
    head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=5)
    writer.close()

    assert b"403 Forbidden" in head
    assert proxy.refused == 1
    assert proxy.permitted == 0


async def test_an_unreachable_destination_costs_one_connection_attempt_per_connect(
    settings: Settings,
    conversation_store: FakeConversationRedis,
    conversation_proxy: tuple[int, EgressProxy],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The retry-storm edge case, at the proxy. A `CONNECT` to an authorised
    destination that does not answer is one upstream attempt, answered `502`,
    and never counted as permitted: the proxy does not retry on the caller's
    behalf. The other half of the bound, one `CONNECT` per question, is
    `test_inference_provider`'s and `test_ask_online`'s."""
    import askwell.egress as egress_module

    closed = socket.socket()
    closed.bind(("127.0.0.1", 0))
    unreachable = f"127.0.0.1:{closed.getsockname()[1]}"
    closed.close()

    attempts: list[tuple[str, int]] = []
    real_open = asyncio.open_connection

    async def _counting_open(host: str, port: int, **kwargs: Any) -> Any:
        attempts.append((host, port))
        return await real_open(host, port, **kwargs)

    monkeypatch.setattr(egress_module.asyncio, "open_connection", _counting_open)
    port, proxy = conversation_proxy
    await open_conversation_grant(
        settings, conversation_id="conv-a", destination=unreachable, token="tok", ttl_seconds=60
    )

    for _ in range(3):
        _reader, writer, head = await _connect(
            port, unreachable, _credential_header("conv-a", "tok")
        )
        writer.close()
        assert b"502 Bad Gateway" in head

    upstream = [attempt for attempt in attempts if attempt[1] != port]
    assert len(upstream) == 3, "one upstream attempt per CONNECT, never a retry"
    assert proxy.permitted == 0
    assert PERMITTED_COUNTER_KEY not in conversation_store.counters
    assert PERMITTED_BY_CONVERSATION_KEY not in conversation_store.hashes
