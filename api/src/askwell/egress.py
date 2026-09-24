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
import base64
import contextlib
import hashlib
import hmac
import json
from dataclasses import dataclass

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

# A short-lived, per-turn grant — `M6.5-WEB-SEC-187`. One key per turn, so two
# escalations in quick succession hold two independent grants rather than
# racing to overwrite the single `PERMITTED_HOST_KEY` above, and each expires
# on its own Redis TTL — a hard stop that does not depend on the API ever
# calling `close_grant`, which is the ticket's own "missed code path" edge
# case. `PERMITTED_HOST_KEY` stays as it is for `M7-UPDATE-BE-161`, which is
# not turn-scoped at all; this is a second, narrower mechanism next to it, not
# a replacement.
GRANT_KEY_PREFIX = "askwell:egress:grant:"

# A conversation's online-AI authorisation — `M8-ONLINE-SEC-169`. The third
# shape, next to the two above and deliberately not either of them: scoped to
# one conversation rather than one turn or the whole install, and bound to a
# credential rather than to a destination alone. The other two let *anything*
# on the internal network reach their destination while open; this one lets
# only a `CONNECT` carrying that conversation's credential through, so a
# second conversation — or a dependency making its own call — reaching the
# same host is refused while the first is online.
#
# The value is JSON: the destination, and the SHA-256 of the credential. The
# credential itself never reaches Redis; it lives only in the API process that
# minted it (`askwell.online`), so an authorisation that somehow outlives that
# process is unusable, not merely revoked.
CONVERSATION_GRANT_KEY_PREFIX = "askwell:egress:conversation:"

# Permitted connections attributed to the conversation that made them. A hash
# of `"<conversation id>\t<destination>"` → count, beside the global
# `PERMITTED_COUNTER_KEY` rather than instead of it, so "exactly three
# outbound requests, from that conversation" is a figure the proxy measured.
PERMITTED_BY_CONVERSATION_KEY = "askwell:egress:permitted_by_conversation"

# How often an open conversation tunnel re-reads its own authorisation. A
# tunnel is authorised once, at `CONNECT`, but an HTTP client keeps it open
# and sends further requests down it — so revoking only new connections
# would let a pooled connection keep talking after the user said stop.
# Re-checked on this interval and cut when the authorisation is gone.
CONVERSATION_RECHECK_SECONDS = 1.0

# The username a conversation's credential is presented under, in the
# standard `Proxy-Authorization: Basic` scheme — the password is the token.
CONVERSATION_CREDENTIAL_USER_PREFIX = "conversation-"

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


def _grant_key(turn_id: str) -> str:
    return f"{GRANT_KEY_PREFIX}{turn_id}"


async def open_grant(
    settings: Settings,
    *,
    turn_id: str,
    destination: str,
    accepted: bool,
    ttl_seconds: float,
) -> bool:
    """Open a grant scoped to one turn and one destination, `destination`
    being `host:port`. Returns whether it opened.

    `accepted` is the one thing this function trusts nothing else about: a
    caller asking for a grant with no acceptance behind it gets refused here,
    at the mechanism, rather than by convention in whatever code called this.
    That refusal is itself worth reading, so it is logged as a warning rather
    than passed through silently — `docs/backlog/M6.5-it-can-look-outside.md`
    calls this "an anomaly worth reading" and this is where that happens.

    The Redis key expires on its own after `ttl_seconds` regardless of
    whether `close_grant` is ever called — the hard expiry the ticket
    requires so a missed closing path cannot leave a grant standing.
    """
    if not accepted:
        log.warning("egress_grant_refused_unaccepted", turn_id=turn_id, destination=destination)
        return False

    import redis.asyncio as redis

    client = redis.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        socket_connect_timeout=2.0,
        socket_timeout=2.0,
    )
    try:
        await client.set(_grant_key(turn_id), destination, ex=max(1, int(ttl_seconds)))
    finally:
        with contextlib.suppress(Exception):
            await client.aclose()
    log.info(
        "egress_grant_opened", turn_id=turn_id, destination=destination, ttl_seconds=ttl_seconds
    )
    return True


async def close_grant(settings: Settings, turn_id: str) -> None:
    """Close a turn's grant. A no-op if it already expired or was never
    opened — every route by which a turn can end calls this unconditionally,
    so it has to tolerate being called on a turn that never escalated."""
    import redis.asyncio as redis

    client = redis.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        socket_connect_timeout=2.0,
        socket_timeout=2.0,
    )
    try:
        deleted = await client.delete(_grant_key(turn_id))
    finally:
        with contextlib.suppress(Exception):
            await client.aclose()
    if deleted:
        log.info("egress_grant_closed", turn_id=turn_id)


# --- per-conversation authorisation: `M8-ONLINE-SEC-169` ---------------------


def _conversation_key(conversation_id: str) -> str:
    return f"{CONVERSATION_GRANT_KEY_PREFIX}{conversation_id}"


def credential_digest(token: str) -> str:
    """What Redis holds instead of the credential itself."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ConversationGrant:
    conversation_id: str
    destination: str
    token_sha256: str
    expires_in_seconds: int | None = None


def parse_conversation_grant(
    conversation_id: str, raw: bytes | str | None
) -> ConversationGrant | None:
    """A grant that cannot be read is no grant. Never guessed at."""
    if raw is None:
        return None
    try:
        value = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
        return ConversationGrant(
            conversation_id=conversation_id,
            destination=str(value["destination"]),
            token_sha256=str(value["token_sha256"]),
        )
    except (ValueError, KeyError, TypeError, UnicodeDecodeError):
        return None


async def open_conversation_grant(
    settings: Settings,
    *,
    conversation_id: str,
    destination: str,
    token: str,
    ttl_seconds: float,
) -> None:
    """Authorise one destination for one conversation, `destination` being
    `host:port`. Replaces any earlier grant for the same conversation — a
    conversation holds one destination, never a list.

    Expires on its own Redis TTL regardless of whether anything ever revokes
    it: the time bound is the backstop for a revocation path that was never
    reached, the same reasoning `open_grant` applies to a turn.
    """
    import redis.asyncio as redis

    client = redis.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        socket_connect_timeout=2.0,
        socket_timeout=2.0,
    )
    try:
        await client.set(
            _conversation_key(conversation_id),
            json.dumps({"destination": destination, "token_sha256": credential_digest(token)}),
            ex=max(1, int(ttl_seconds)),
        )
    finally:
        with contextlib.suppress(Exception):
            await client.aclose()
    log.info(
        "egress_conversation_grant_opened",
        conversation_id=conversation_id,
        destination=destination,
        ttl_seconds=ttl_seconds,
    )


async def read_conversation_grant(
    settings: Settings, conversation_id: str
) -> ConversationGrant | None:
    """The live grant for one conversation, with its remaining time, or None.

    Raises if Redis cannot be read — the caller decides what an unknown
    means, and for a revocation it must not mean "nothing to revoke".
    """
    import redis.asyncio as redis

    client = redis.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        socket_connect_timeout=2.0,
        socket_timeout=2.0,
    )
    try:
        key = _conversation_key(conversation_id)
        raw = await client.get(key)
        ttl = await client.ttl(key) if raw is not None else None
    finally:
        with contextlib.suppress(Exception):
            await client.aclose()
    grant = parse_conversation_grant(conversation_id, raw)
    if grant is None:
        return None
    return ConversationGrant(
        conversation_id=grant.conversation_id,
        destination=grant.destination,
        token_sha256=grant.token_sha256,
        expires_in_seconds=int(ttl) if ttl is not None and int(ttl) >= 0 else None,
    )


async def close_conversation_grant(settings: Settings, conversation_id: str) -> bool:
    """Revoke one conversation's grant. Returns whether one was standing.

    Open tunnels are cut by the proxy within `CONVERSATION_RECHECK_SECONDS`;
    new ones are refused from the moment this returns."""
    import redis.asyncio as redis

    client = redis.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        socket_connect_timeout=2.0,
        socket_timeout=2.0,
    )
    try:
        deleted = await client.delete(_conversation_key(conversation_id))
    finally:
        with contextlib.suppress(Exception):
            await client.aclose()
    if deleted:
        log.info("egress_conversation_grant_closed", conversation_id=conversation_id)
    return bool(deleted)


async def close_all_conversation_grants(settings: Settings) -> dict[str, str]:
    """Revoke every conversation grant. Returns what was standing, as
    conversation id → destination, so the caller can record each one.

    Called at startup by both the API and the proxy: a grant surviving a
    restart is one nobody re-asked for (`M8-ONLINE-SEC-169`'s own edge case),
    and Redis here is `appendonly`, so it would otherwise survive.
    """
    import redis.asyncio as redis

    client = redis.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        socket_connect_timeout=2.0,
        socket_timeout=2.0,
    )
    revoked: dict[str, str] = {}
    try:
        cursor = 0
        while True:
            cursor, keys = await client.scan(
                cursor, match=f"{CONVERSATION_GRANT_KEY_PREFIX}*", count=100
            )
            if keys:
                values = await client.mget(keys)
                for key, value in zip(keys, values, strict=True):
                    name = key.decode("utf-8") if isinstance(key, bytes) else key
                    conversation_id = name.removeprefix(CONVERSATION_GRANT_KEY_PREFIX)
                    grant = parse_conversation_grant(conversation_id, value)
                    revoked[conversation_id] = grant.destination if grant else "(unreadable)"
                await client.delete(*keys)
            if cursor == 0:
                break
    finally:
        with contextlib.suppress(Exception):
            await client.aclose()
    if revoked:
        log.info("egress_conversation_grants_cleared", count=len(revoked))
    return revoked


def _conversation_credential(header_lines: list[str]) -> tuple[str, str] | None:
    """`(conversation id, token)` from a `Proxy-Authorization: Basic` header,
    or None when there is none or it is not one of ours."""
    for header in header_lines:
        name, _, value = header.partition(":")
        if name.strip().lower() != "proxy-authorization":
            continue
        scheme, _, encoded = value.strip().partition(" ")
        if scheme.lower() != "basic":
            return None
        try:
            decoded = base64.b64decode(encoded.strip(), validate=True).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return None
        user, separator, token = decoded.partition(":")
        if not separator or not user.startswith(CONVERSATION_CREDENTIAL_USER_PREFIX):
            return None
        return user.removeprefix(CONVERSATION_CREDENTIAL_USER_PREFIX), token
    return None


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

    async def _grant_permits(self, destination: str) -> bool:
        """Whether any live turn grant names exactly `destination`.

        Read fresh on every connection, like `_permitted_destination` above —
        a grant closed by the API, or one that expired on its own TTL, must
        stop permitting the very next connection, not on this proxy's next
        restart. Scanning rather than a single key because a grant is
        per-turn: two escalations in flight hold two keys, and this has to
        find either.
        """
        import redis.asyncio as redis

        client = redis.Redis(
            host=self.settings.redis_host,
            port=self.settings.redis_port,
            socket_connect_timeout=1.0,
            socket_timeout=1.0,
        )
        try:
            cursor = 0
            while True:
                cursor, keys = await client.scan(cursor, match=f"{GRANT_KEY_PREFIX}*", count=100)
                if keys:
                    values = await client.mget(keys)
                    for value in values:
                        if value is None:
                            continue
                        text = value.decode("utf-8") if isinstance(value, bytes) else value
                        if text == destination:
                            return True
                if cursor == 0:
                    return False
        except Exception as error:
            log.warning("egress_grant_unreadable", error=f"{type(error).__name__}: {error}")
            return False
        finally:
            with contextlib.suppress(Exception):
                await client.aclose()

    async def _conversation_grant_names(self, destination: str) -> bool:
        """Whether any live conversation grant names `destination` — the cheap
        question asked before reading headers. Unreadable reads as no."""
        import redis.asyncio as redis

        client = redis.Redis(
            host=self.settings.redis_host,
            port=self.settings.redis_port,
            socket_connect_timeout=1.0,
            socket_timeout=1.0,
        )
        try:
            cursor = 0
            while True:
                cursor, keys = await client.scan(
                    cursor, match=f"{CONVERSATION_GRANT_KEY_PREFIX}*", count=100
                )
                if keys:
                    for value in await client.mget(keys):
                        grant = parse_conversation_grant("", value)
                        if grant is not None and grant.destination == destination:
                            return True
                if cursor == 0:
                    return False
        except Exception as error:
            log.warning(
                "egress_conversation_grant_unreadable", error=f"{type(error).__name__}: {error}"
            )
            return False
        finally:
            with contextlib.suppress(Exception):
                await client.aclose()

    async def _conversation_grant(self, conversation_id: str) -> ConversationGrant | None:
        """One conversation's grant, read fresh. Unreadable reads as none —
        a proxy that cannot see an authorisation does not assume one."""
        try:
            return await read_conversation_grant(self.settings, conversation_id)
        except Exception as error:
            log.warning(
                "egress_conversation_grant_unreadable", error=f"{type(error).__name__}: {error}"
            )
            return None

    async def _conversation_permits(
        self, destination: str, header_lines: list[str]
    ) -> ConversationGrant | None:
        """The grant this request's credential proves, if it names exactly
        `destination`. No credential, a wrong one, another conversation's, or
        the right one aimed somewhere else: None, and the request is refused."""
        credential = _conversation_credential(header_lines)
        if credential is None:
            return None
        conversation_id, token = credential
        grant = await self._conversation_grant(conversation_id)
        if grant is None or grant.destination != destination:
            return None
        if not hmac.compare_digest(grant.token_sha256, credential_digest(token)):
            return None
        return grant

    async def _watch_conversation(
        self,
        grant: ConversationGrant,
        writer: asyncio.StreamWriter,
        upstream_writer: asyncio.StreamWriter,
    ) -> None:
        """Cut an open tunnel the moment its authorisation stops being the
        one it was opened under — revoked, expired, or replaced by a fresh
        enable with a new credential. `M8-ONLINE-SEC-169`'s in-flight edge
        case, decided as *cancelled*: a pooled connection must not outlive
        the user turning online AI off."""
        while True:
            await asyncio.sleep(CONVERSATION_RECHECK_SECONDS)
            current = await self._conversation_grant(grant.conversation_id)
            if current is not None and current.token_sha256 == grant.token_sha256:
                continue
            log.info(
                "egress_conversation_tunnel_cut",
                conversation_id=grant.conversation_id,
                destination=grant.destination,
            )
            for side in (writer, upstream_writer):
                with contextlib.suppress(Exception):
                    side.transport.abort()
            return

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
            allowed = permitted is not None and destination == permitted
            if not allowed:
                allowed = await self._grant_permits(destination)
            if allowed:
                await self._consume_header_block(reader)
                await self._forward(reader, writer, destination, service)
                return
            # Headers are read only when some conversation is authorised for
            # this destination at all — every other refusal stays exactly as
            # it was, answered on the request line alone.
            if await self._conversation_grant_names(destination):
                headers = await self._read_header_block(reader)
                grant = await self._conversation_permits(destination, headers)
                if grant is not None:
                    await self._forward(reader, writer, destination, service, grant=grant)
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

    @staticmethod
    async def _read_header_block(reader: asyncio.StreamReader) -> list[str]:
        """The header lines after a `CONNECT` request line, up to the blank
        line — kept rather than discarded, because a conversation's
        credential travels in one of them. Bounded by `MAX_REQUEST_BYTES`
        so a client streaming headers forever cannot hold memory open."""
        lines: list[str] = []
        total = 0
        try:
            async with asyncio.timeout(5.0):
                while True:
                    header_line = await reader.readline()
                    if header_line in (b"", b"\r\n", b"\n"):
                        return lines
                    total += len(header_line)
                    if total > MAX_REQUEST_BYTES:
                        return []
                    lines.append(header_line.decode("latin-1").strip())
        except (TimeoutError, OSError, ValueError):
            return []

    async def _forward(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        destination: str,
        service: str,
        *,
        grant: ConversationGrant | None = None,
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
        conversation_id = grant.conversation_id if grant is not None else None
        log.info(
            "egress_permitted",
            service=service,
            destination=destination,
            conversation_id=conversation_id,
            permitted_total=self.permitted,
        )
        await self._record_permitted(service, destination, conversation_id)

        with contextlib.suppress(OSError):
            writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await writer.drain()

        watcher = (
            asyncio.create_task(self._watch_conversation(grant, writer, upstream_writer))
            if grant is not None
            else None
        )
        try:
            await asyncio.gather(
                self._pipe(reader, upstream_writer),
                self._pipe(upstream_reader, writer),
            )
        finally:
            if watcher is not None:
                watcher.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await watcher
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

    async def _record_permitted(
        self, service: str, destination: str, conversation_id: str | None = None
    ) -> None:
        """Count a forwarded connection, the same honest-counter shape `_record`
        gives refusals — a number the settings screen can show without
        inventing anything. A conversation's connection is also counted
        against that conversation, so the figure is attributable."""
        import redis.asyncio as redis

        client = redis.Redis(
            host=self.settings.redis_host,
            port=self.settings.redis_port,
            socket_connect_timeout=1.0,
            socket_timeout=1.0,
        )
        try:
            async with client.pipeline() as pipe:
                pipe.incr(PERMITTED_COUNTER_KEY)
                if conversation_id is not None:
                    pipe.hincrby(
                        PERMITTED_BY_CONVERSATION_KEY, f"{conversation_id}\t{destination}", 1
                    )
                await pipe.execute()
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
    # The proxy restarting is a restart: no conversation's authorisation
    # carries across it (`M8-ONLINE-SEC-169`). Revocation only — the proxy
    # still never writes a grant, so this cannot open anything.
    try:
        await close_all_conversation_grants(settings)
    except Exception as error:
        log.warning(
            "egress_conversation_grants_not_cleared", error=f"{type(error).__name__}: {error}"
        )
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
