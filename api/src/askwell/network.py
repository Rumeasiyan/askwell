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
from typing import Any

from askwell import redis_client
from askwell.config import Settings
from askwell.egress import (
    CONVERSATION_GRANT_KEY_PREFIX,
    PERMITTED_BY_CONVERSATION_KEY,
    PERMITTED_COUNTER_KEY,
    RECENT_LIMIT,
    REFUSED_COUNTER_KEY,
    REFUSED_RECENT_KEY,
    REPORTING_SINCE_KEY,
    parse_conversation_grant,
)
from askwell.logging import get_logger

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Refusal:
    service: str
    destination: str


@dataclass(frozen=True, slots=True)
class ConversationPermitted:
    """Permitted connections the proxy attributed to one conversation's
    online-AI authorisation (`M8-ONLINE-SEC-169`). Kept after the
    authorisation ends — the count is what happened, not what is open."""

    conversation_id: str
    destination: str
    permitted: int


@dataclass(frozen=True, slots=True)
class Authorisation:
    """A conversation's authorisation standing right now."""

    conversation_id: str
    destination: str


@dataclass(frozen=True, slots=True)
class NetworkActivity:
    """The proxy's counters, or an honest statement that they could not be read."""

    available: bool
    refused: int | None = None
    permitted: int | None = None
    recent: list[Refusal] = field(default_factory=list)
    permitted_by_conversation: list[ConversationPermitted] = field(default_factory=list)
    authorised: list[Authorisation] = field(default_factory=list)
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
            "permitted_by_conversation": [
                {
                    "conversation_id": item.conversation_id,
                    "destination": item.destination,
                    "permitted": item.permitted,
                }
                for item in self.permitted_by_conversation
            ],
            "authorised": [
                {"conversation_id": item.conversation_id, "destination": item.destination}
                for item in self.authorised
            ],
            "unavailable_reason": self.unavailable_reason,
        }


def _unavailable(reason: str) -> NetworkActivity:
    return NetworkActivity(available=False, unavailable_reason=reason)


async def read_activity(settings: Settings) -> NetworkActivity:
    """Read the proxy's counters. Never invents one."""
    client = redis_client.connect(settings, timeout=settings.health_probe_timeout_seconds)
    try:
        async with client.pipeline() as pipe:
            pipe.get(REPORTING_SINCE_KEY)
            pipe.get(REFUSED_COUNTER_KEY)
            pipe.get(PERMITTED_COUNTER_KEY)
            pipe.lrange(REFUSED_RECENT_KEY, 0, RECENT_LIMIT - 1)
            pipe.hgetall(PERMITTED_BY_CONVERSATION_KEY)
            since, refused, permitted, recent, by_conversation = await pipe.execute()
        authorised = await _authorised(client)
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
        permitted_by_conversation=sorted(
            (_parse_attributed(key, value) for key, value in (by_conversation or {}).items()),
            key=lambda item: (item.conversation_id, item.destination),
        ),
        authorised=authorised,
    )


def _text(value: bytes | str) -> str:
    return value.decode("utf-8") if isinstance(value, bytes) else value


def _parse_attributed(key: bytes | str, value: bytes | str) -> ConversationPermitted:
    conversation_id, _, destination = _text(key).partition("\t")
    return ConversationPermitted(
        conversation_id=conversation_id,
        destination=destination or "(none)",
        permitted=int(_text(value)),
    )


async def _authorised(client: Any) -> list[Authorisation]:
    """Every conversation authorisation the proxy would honour right now."""
    found: list[Authorisation] = []
    cursor = 0
    while True:
        cursor, keys = await client.scan(
            cursor, match=f"{CONVERSATION_GRANT_KEY_PREFIX}*", count=100
        )
        if keys:
            for key, value in zip(keys, await client.mget(keys), strict=True):
                conversation_id = _text(key).removeprefix(CONVERSATION_GRANT_KEY_PREFIX)
                grant = parse_conversation_grant(conversation_id, value)
                if grant is not None:
                    found.append(Authorisation(conversation_id, grant.destination))
        if cursor == 0:
            return sorted(found, key=lambda item: item.conversation_id)


def _parse_recent(entry: bytes | str) -> Refusal:
    text = entry.decode("utf-8") if isinstance(entry, bytes) else entry
    service, _, destination = text.partition("\t")
    return Refusal(service=service, destination=destination or "(none)")
