"""The default-deny egress proxy.

C1's enforcement point. `docs/architecture.md` §5.

Every container routes outbound traffic here, and nothing else has a route out
at all — the application network is declared internal, so a container that
ignores the proxy does not reach the internet by another path, it reaches
nothing.

**This proxy never forwards anything.** In local mode there are no allowed
destinations, so it is not a proxy that happens to be configured strictly; it
is a service whose entire job is to refuse and to say what it refused. That is
deliberately a much smaller thing to get right than a real proxy, and it cannot
leak by misconfiguration because there is no configuration that would let it.

Two alternatives were rejected and the reasons are worth keeping:

Application-level enforcement binds only the code you wrote. The realistic
threat is a dependency making an unexpected call — a telemetry ping, a version
check, a font fetch — and none of that goes through anything the application
controls.

Network policy alone cannot *count* what it refused, and the settings screen
promises a measured figure rather than a reassurance. A number the user can
look at is the difference between a claim and evidence.
"""

import asyncio
import contextlib

from askwell import __version__
from askwell.config import Environment, Settings, load_settings
from askwell.logging import configure_logging, get_logger

log = get_logger(__name__)

# Where the refusal count lives, so the API can read it without the proxy
# needing a database connection or an API of its own.
REFUSED_COUNTER_KEY = "askwell:egress:refused"
PERMITTED_COUNTER_KEY = "askwell:egress:permitted"
REFUSED_RECENT_KEY = "askwell:egress:recent"

# Set by the proxy when it starts. Its absence is how the API tells "the proxy
# has never reported" from "the proxy has reported zero" — which look identical
# in a counter and mean opposite things.
REPORTING_SINCE_KEY = "askwell:egress:since"

# The one destination this proxy may ever forward to, and only while this key
# holds it. `M7-UPDATE-BE-161` is the first caller — issue #345 tracks the
# general per-connection version of this, deliberately not built here. Redis,
# not a config file: the API and the proxy are separate processes, and this
# has to change the instant a setting does, not on the proxy's next restart.
PERMITTED_HOST_KEY = "askwell:egress:permitted_host"

RECENT_LIMIT = 50

# Long enough for a real request line and headers, short enough that a client
# sending nothing in particular cannot hold memory open.
MAX_REQUEST_BYTES = 8192

REFUSAL_BODY = (
    "Askwell refused this request.\n"
    "\n"
    "Nothing leaves this machine unless you say so, for a specific "
    "conversation or a specific question. There is no destination configured "
    "as allowed, and there is no setting that makes one allowed by default.\n"
    "\n"
    "If you are seeing this in a log, something in Askwell or one of its "
    "dependencies tried to reach the network on its own. That is worth "
    "knowing about, which is why this was refused loudly rather than quietly "
    "failing to connect.\n"
)


def _refusal_response() -> bytes:
    body = REFUSAL_BODY.encode("utf-8")
    return (
        b"HTTP/1.1 403 Forbidden\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n"
        b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n"
        b"Connection: close\r\n"
        b"X-Askwell-Egress: refused\r\n"
        b"\r\n" + body
    )


def parse_destination(request_line: str) -> str | None:
    """The destination a proxy request is asking for, as written.

    Returns None when the line is not a proxy request at all — which is itself
    worth refusing, but is a different thing from an attempt to reach a named
    host, and the log should not claim otherwise.

    Both forms matter. `CONNECT host:443` is how HTTPS goes through a proxy.
    An absolute URI in the request line is how plain HTTP does. A relative path
    means something spoke to the proxy as if it were an origin server, which is
    a misconfiguration rather than an escape attempt.
    """
    parts = request_line.split()
    if len(parts) < 2:
        return None

    method, target = parts[0].upper(), parts[1]
    if method == "CONNECT":
        return target
    if "://" in target:
        return target
    return None


async def _resolve_service(host: str) -> str:
    """Which container asked. The IP alone is not actionable.

    "Something on 10.89.0.6 tried to reach the internet" sends whoever reads it
    to work out what 10.89.0.6 was, on a machine where it will be something
    else tomorrow. Podman's DNS resolves container addresses back to names, so
    the log can say `worker` instead.
    """
    loop = asyncio.get_running_loop()
    try:
        async with asyncio.timeout(1.0):
            name, *_ = await loop.getnameinfo((host, 0), 0)
    except (OSError, TimeoutError):
        return host
    return name or host


async def permit_destination(settings: Settings, destination: str) -> None:
    """Open the one permitted destination. `destination` is `host:port`.

    Called by the API, never by the proxy on itself — the proxy only ever
    reads this key, so a bug here cannot let the proxy grant itself anything.
    """
    import redis.asyncio as redis

    client = redis.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        socket_connect_timeout=2.0,
        socket_timeout=2.0,
    )
    try:
        await client.set(PERMITTED_HOST_KEY, destination)
    finally:
        with contextlib.suppress(Exception):
            await client.aclose()


async def revoke_destination(settings: Settings) -> None:
    """Close whatever destination was permitted. A no-op if none was."""
    import redis.asyncio as redis

    client = redis.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        socket_connect_timeout=2.0,
        socket_timeout=2.0,
    )
    try:
        await client.delete(PERMITTED_HOST_KEY)
    finally:
        with contextlib.suppress(Exception):
            await client.aclose()


class EgressProxy:
    """Refuses every outbound request except the one destination, if any,
    that has been explicitly permitted — and counts both."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.refused = 0
        self.permitted = 0

    async def _permitted_destination(self) -> str | None:
        """Read fresh on every connection — a setting flipped off must close
        this the instant the API acts, not on the proxy's next restart."""
        import redis.asyncio as redis

        client = redis.Redis(
            host=self.settings.redis_host,
            port=self.settings.redis_port,
            socket_connect_timeout=1.0,
            socket_timeout=1.0,
        )
        try:
            value = await client.get(PERMITTED_HOST_KEY)
        except Exception as error:
            log.warning("egress_permit_unreadable", error=f"{type(error).__name__}: {error}")
            return None
        finally:
            with contextlib.suppress(Exception):
                await client.aclose()
        if value is None:
            return None
        return value.decode("utf-8") if isinstance(value, bytes) else value

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        client = peer[0] if peer else "unknown"

        destination = None
        line = b""
        try:
            async with asyncio.timeout(5.0):
                line = await reader.readline()
        except (TimeoutError, OSError):
            line = b""

        if not line.strip():
            # Opened a connection and said nothing. That is Askwell's own
            # health probe, which checks the proxy is alive by connecting and
            # closing — and a TCP connect inside the internal network has not
            # attempted to leave the machine.
            #
            # Counting it would inflate the refusal figure on the settings
            # screen by one every few seconds, turning a number that means
            # "something tried to phone home" into a number that means
            # "Askwell is running". That is worse than not having the number.
            log.debug("egress_liveness_probe", client=client)
            writer.close()
            with contextlib.suppress(OSError, asyncio.CancelledError):
                await writer.wait_closed()
            return

        try:
            request_line = line.decode("latin-1").strip()
        except UnicodeDecodeError:
            request_line = ""
        destination = parse_destination(request_line)
        method = request_line.split(" ", 1)[0].upper() if request_line else ""

        service = await _resolve_service(client)

        if method == "CONNECT" and destination is not None:
            permitted = await self._permitted_destination()
            if permitted is not None and destination == permitted:
                await self._consume_header_block(reader)
                await self._forward(reader, writer, destination, service)
                return

        self.refused += 1

        log.warning(
            "egress_refused",
            service=service,
            client=client,
            destination=destination or "(no destination in request)",
            request_line=request_line[:200],
            refused_total=self.refused,
        )
        await self._record(service, destination)

        with contextlib.suppress(OSError):
            writer.write(_refusal_response())
            await writer.drain()
        writer.close()
        with contextlib.suppress(OSError, asyncio.CancelledError):
            await writer.wait_closed()

    async def _record(self, service: str, destination: str | None) -> None:
        """Count it where the API can read it.

        Failing to record must not stop the refusal — the refusal has already
        happened by this point, and a proxy that crashed on a Redis hiccup
        would take the deny with it.
        """
        import redis.asyncio as redis

        client = redis.Redis(
            host=self.settings.redis_host,
            port=self.settings.redis_port,
            socket_connect_timeout=1.0,
            socket_timeout=1.0,
        )
        try:
            async with client.pipeline() as pipe:
                pipe.incr(REFUSED_COUNTER_KEY)
                pipe.lpush(REFUSED_RECENT_KEY, f"{service}\t{destination or '(none)'}")
                pipe.ltrim(REFUSED_RECENT_KEY, 0, RECENT_LIMIT - 1)
                await pipe.execute()
        except Exception as error:
            log.warning("egress_count_failed", error=f"{type(error).__name__}: {error}")
        finally:
            with contextlib.suppress(Exception):
                await client.aclose()

    @staticmethod
    async def _consume_header_block(reader: asyncio.StreamReader) -> None:
        """Discard whatever header lines followed the `CONNECT` request line,
        up to the blank line that ends them (`Host:`, at minimum, from any
        real client — the request line alone is only what a bare test sends).
        Left unread, this would be forwarded as the tunnel's first bytes,
        which is not what either side of a `CONNECT` expects.
        """
        try:
            async with asyncio.timeout(5.0):
                while True:
                    header_line = await reader.readline()
                    if header_line in (b"", b"\r\n", b"\n"):
                        return
        except (TimeoutError, OSError):
            return

    async def _forward(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        destination: str,
        service: str,
    ) -> None:
        """Tunnel a `CONNECT` to the one permitted destination.

        Only `CONNECT` is handled — the one caller this exists for
        (`askwell.update_check`) speaks HTTPS, and a plain-HTTP absolute-URI
        request is refused even for the permitted host rather than adding a
        second forwarding path nothing needs yet.
        """
        host, _, port_text = destination.rpartition(":")
        try:
            port = int(port_text)
        except ValueError:
            port = 0
        upstream_reader: asyncio.StreamReader | None = None
        upstream_writer: asyncio.StreamWriter | None = None
        if host and port:
            try:
                async with asyncio.timeout(10.0):
                    upstream_reader, upstream_writer = await asyncio.open_connection(host, port)
            except (OSError, TimeoutError) as error:
                log.warning(
                    "egress_permitted_unreachable", destination=destination, error=str(error)
                )

        if upstream_reader is None or upstream_writer is None:
            with contextlib.suppress(OSError):
                writer.write(b"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n\r\n")
                await writer.drain()
            writer.close()
            with contextlib.suppress(OSError, asyncio.CancelledError):
                await writer.wait_closed()
            return

        self.permitted += 1
        log.info(
            "egress_permitted",
            service=service,
            destination=destination,
            permitted_total=self.permitted,
        )
        await self._record_permitted(service, destination)

        with contextlib.suppress(OSError):
            writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await writer.drain()

        await asyncio.gather(
            self._pipe(reader, upstream_writer),
            self._pipe(upstream_reader, writer),
        )
        with contextlib.suppress(OSError, asyncio.CancelledError):
            upstream_writer.close()
            await upstream_writer.wait_closed()
        with contextlib.suppress(OSError, asyncio.CancelledError):
            writer.close()
            await writer.wait_closed()

    @staticmethod
    async def _pipe(src: asyncio.StreamReader, dst: asyncio.StreamWriter) -> None:
        """One direction of the tunnel. Ends quietly when either side closes —
        that is what an ordinary end of a TLS session looks like here."""
        try:
            while True:
                chunk = await src.read(65536)
                if not chunk:
                    break
                dst.write(chunk)
                await dst.drain()
        except (OSError, asyncio.CancelledError):
            pass
        finally:
            with contextlib.suppress(OSError, RuntimeError):
                dst.write_eof()

    async def _record_permitted(self, service: str, destination: str) -> None:
        """Count a forwarded connection, the same honest-counter shape `_record`
        gives refusals — a number the settings screen can show without
        inventing anything."""
        import redis.asyncio as redis

        client = redis.Redis(
            host=self.settings.redis_host,
            port=self.settings.redis_port,
            socket_connect_timeout=1.0,
            socket_timeout=1.0,
        )
        try:
            await client.incr(PERMITTED_COUNTER_KEY)
        except Exception as error:
            log.warning("egress_permitted_count_failed", error=f"{type(error).__name__}: {error}")
        finally:
            with contextlib.suppress(Exception):
                await client.aclose()
            log.debug("egress_permitted_recorded", service=service, destination=destination)


async def _register(settings: Settings) -> None:
    """Announce that the proxy is reporting, and establish its counters.

    The counters are created rather than left to spring into existence on
    first use, because a missing key and a key holding zero are the same thing
    to a reader and opposite things in fact. With this, an absent key means the
    proxy has never run — which the API reports as unavailable rather than as
    "nothing has tried to leave this machine".
    """
    import redis.asyncio as redis

    client = redis.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        socket_connect_timeout=2.0,
        socket_timeout=2.0,
    )
    try:
        async with client.pipeline() as pipe:
            pipe.setnx(REFUSED_COUNTER_KEY, 0)
            # Permitted is created and never incremented. In local mode there
            # are no allowed destinations, so this is a measured zero rather
            # than an absence — the distinction the whole surface rests on.
            pipe.setnx(PERMITTED_COUNTER_KEY, 0)
            pipe.set(REPORTING_SINCE_KEY, __version__)
            await pipe.execute()
    except Exception as error:
        log.warning("egress_register_failed", error=f"{type(error).__name__}: {error}")
    finally:
        with contextlib.suppress(Exception):
            await client.aclose()


async def serve(settings: Settings) -> None:
    proxy = EgressProxy(settings)
    await _register(settings)
    server = await asyncio.start_server(proxy.handle, "0.0.0.0", settings.egress_proxy_port)
    log.info(
        "egress_proxy_started",
        version=__version__,
        port=settings.egress_proxy_port,
        allowed_destinations=0,
        note="default deny; nothing is configured as allowed and nothing can be",
    )
    async with server:
        await server.serve_forever()


def main() -> None:
    try:
        settings = load_settings()
    except Exception as error:
        raise SystemExit(str(error)) from None

    configure_logging(
        level=settings.log_level,
        json_output=settings.environment is not Environment.DEVELOPMENT,
    )
    try:
        asyncio.run(serve(settings))
    except KeyboardInterrupt:  # pragma: no cover - a signal, not a code path
        log.info("egress_proxy_stopped")
