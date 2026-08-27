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

import pytest
import pytest_asyncio

from askwell.config import Settings
from askwell.egress import REFUSAL_BODY, EgressProxy, parse_destination


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
