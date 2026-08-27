"""What the proxy refused, read from the proxy.

`docs/ux/settings.md` §4 states network activity as a fact with a live count,
not as a toggle. The number has to be the proxy's own, because the application
saying "I did not make any outbound requests" is exactly the assertion the
proxy exists to replace with evidence.

One rule shapes everything here: **if the counters cannot be read, the answer
is unavailable, never zero.** Zero and unknown look identical to a reader and
mean opposite things, and "nothing has tried to leave this machine" is the
strongest claim the product makes. Reporting it because a counter was
unreadable would be the single most dishonest thing in the codebase.

`docs/states-and-edge-cases.md` §1 also forbids rendering an offline warning.
Being offline is the design point, not a degraded state — so this surface has
no notion of an alarming value. A refusal count of forty is information, not a
problem.
"""

from dataclasses import dataclass, field

from askwell.config import Settings
from askwell.egress import (
    PERMITTED_COUNTER_KEY,
    RECENT_LIMIT,
    REFUSED_COUNTER_KEY,
    REFUSED_RECENT_KEY,
    REPORTING_SINCE_KEY,
)
from askwell.logging import get_logger

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Refusal:
    service: str
    destination: str


@dataclass(frozen=True, slots=True)
class NetworkActivity:
    """The proxy's counters, or an honest statement that they could not be read."""

    available: bool
    refused: int | None = None
    permitted: int | None = None
    recent: list[Refusal] = field(default_factory=list)
    unavailable_reason: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "available": self.available,
            "refused": self.refused,
            "permitted": self.permitted,
            "recent": [
                {"service": item.service, "destination": item.destination} for item in self.recent
            ],
            # Stated rather than implied. A list that silently stops at fifty
            # reads as "these are all of them".
            "recent_capped_at": RECENT_LIMIT,
            "unavailable_reason": self.unavailable_reason,
        }


def _unavailable(reason: str) -> NetworkActivity:
    return NetworkActivity(available=False, unavailable_reason=reason)


async def read_activity(settings: Settings) -> NetworkActivity:
    """Read the proxy's counters. Never invents one."""
    import redis.asyncio as redis

    client = redis.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        socket_connect_timeout=settings.health_probe_timeout_seconds,
        socket_timeout=settings.health_probe_timeout_seconds,
    )
    try:
        async with client.pipeline() as pipe:
            pipe.get(REPORTING_SINCE_KEY)
            pipe.get(REFUSED_COUNTER_KEY)
            pipe.get(PERMITTED_COUNTER_KEY)
            pipe.lrange(REFUSED_RECENT_KEY, 0, RECENT_LIMIT - 1)
            since, refused, permitted, recent = await pipe.execute()
    except Exception as error:
        log.warning("network_activity_unreadable", error=f"{type(error).__name__}: {error}")
        return _unavailable(
            "The egress proxy's counters could not be read. This is not the "
            "same as nothing having been refused — it means the figure is "
            "unknown right now."
        )
    finally:
        try:
            await client.aclose()
        except Exception:
            pass

    if since is None:
        # The queue is up but the proxy has never registered. Its counters
        # would read as zero, which would be a claim nobody has evidence for.
        return _unavailable(
            "The egress proxy has not reported since this install was created. "
            "Its counters are unknown rather than zero."
        )

    return NetworkActivity(
        available=True,
        refused=int(refused or 0),
        permitted=int(permitted or 0),
        recent=[_parse_recent(entry) for entry in recent],
    )


def _parse_recent(entry: bytes | str) -> Refusal:
    text = entry.decode("utf-8") if isinstance(entry, bytes) else entry
    service, _, destination = text.partition("\t")
    return Refusal(service=service, destination=destination or "(none)")
