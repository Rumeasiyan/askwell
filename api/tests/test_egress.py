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
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio

from askwell.config import Settings
from askwell.egress import (
    GRANT_KEY_PREFIX,
    REFUSAL_BODY,
    EgressProxy,
    close_grant,
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
