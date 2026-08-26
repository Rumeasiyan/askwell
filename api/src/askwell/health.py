"""Component health, reported one component at a time.

The design decision worth stating: there is no aggregate boolean in the wire
format. `healthy: false` tells the user their product is broken. Five separate
states tell them Postgres is still starting and everything else is fine, which
is the difference between waiting ten seconds and uninstalling — see
`docs/states-and-edge-cases.md` §1.

Probes are TCP-level at this stage. A component that accepts a connection is
reported `reachable`, not `ok`: the difference between a socket opening and
Postgres being able to answer a query is real, and claiming the stronger thing
from the weaker evidence is the same error C6 warns about elsewhere. Deeper
probes land with the clients that can make them.
"""

import asyncio
import socket
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from askwell.config import Settings


class ComponentState(StrEnum):
    """What is known about one component. Ordered worst-last for sorting."""

    REACHABLE = "reachable"
    """Accepted a TCP connection. Not the same as able to do its job."""

    UNREACHABLE = "unreachable"
    """Refused, timed out, or could not be resolved. The reason says which."""

    UNKNOWN = "unknown"
    """The probe itself failed in a way that says nothing about the component."""


@dataclass(frozen=True, slots=True)
class ComponentHealth:
    """One component's state, and why, and how long finding out took."""

    name: str
    state: ComponentState
    reason: str | None
    address: str
    duration_ms: float

    def as_dict(self) -> dict[str, object]:
        return {
            "component": self.name,
            "state": str(self.state),
            "reason": self.reason,
            "address": self.address,
            "duration_ms": round(self.duration_ms, 1),
        }


@dataclass(frozen=True, slots=True)
class _Target:
    name: str
    host: str
    port: int


def _targets(settings: Settings) -> list[_Target]:
    """The five components the shell needs reported separately."""
    database_host, database_port = settings.database_host_port
    return [
        _Target("database", database_host, database_port),
        _Target("queue", settings.redis_host, settings.redis_port),
        _Target("worker", settings.worker_host, settings.worker_port),
        _Target("inference", settings.inference_host, settings.inference_port),
        _Target("egress_proxy", settings.egress_proxy_host, settings.egress_proxy_port),
    ]


def _consume(task: asyncio.Task[Any]) -> None:
    """Retrieve a cancelled task's exception so the loop does not report it.

    A name lookup that loses its race with the timeout still finishes, a moment
    later, by raising. If nobody retrieves that exception the event loop logs
    `Future exception was never retrieved` at ERROR — which reads exactly like
    a crash, in the health surface, which is the one place a confused user is
    looking. The lookup failing is expected and already reported below.
    """
    if not task.cancelled():
        task.exception()


# ASYNC109 wants the caller to wrap this in `asyncio.timeout` rather than pass
# a timeout in. It cannot be moved out here: the whole job of this function is
# to turn a timeout into a per-component state with a reason attached, and a
# timeout raised in the caller would collapse five separate answers into one
# exception. The rule exists to catch hand-rolled timeout logic, and the
# implementation below uses `asyncio.timeout` exactly as the rule intends.
async def _probe(target: _Target, timeout: float) -> ComponentHealth:  # noqa: ASYNC109
    """Resolve, connect, close. Never raises.

    Resolution is done separately from connection rather than letting
    `open_connection` do both. Two reasons, both about what the user is told:
    a name that does not resolve and a port that does not answer are different
    problems with different fixes, and only the second one means "wait a
    moment"; and owning the lookup is what makes it possible to retrieve its
    exception when it loses the race with the timeout.
    """
    loop = asyncio.get_running_loop()
    started = loop.time()
    deadline = started + timeout
    address = f"{target.host}:{target.port}"

    def finish(state: ComponentState, reason: str | None) -> ComponentHealth:
        return ComponentHealth(
            name=target.name,
            state=state,
            reason=reason,
            address=address,
            duration_ms=(loop.time() - started) * 1000,
        )

    lookup = asyncio.ensure_future(
        loop.getaddrinfo(target.host, target.port, type=socket.SOCK_STREAM)
    )
    try:
        async with asyncio.timeout_at(deadline):
            # Shielded so the task survives the timeout and can be drained by
            # `_consume` instead of being abandoned mid-flight.
            resolved = await asyncio.shield(lookup)
    except TimeoutError:
        lookup.add_done_callback(_consume)
        return finish(
            ComponentState.UNREACHABLE,
            f"The name {target.host!r} did not resolve within {timeout:g}s.",
        )
    except socket.gaierror:
        return finish(
            ComponentState.UNREACHABLE,
            f"The name {target.host!r} does not resolve. "
            f"The component has probably not been created yet.",
        )
    except OSError as error:
        return finish(ComponentState.UNREACHABLE, f"{type(error).__name__}: {error}")

    if not resolved:
        return finish(
            ComponentState.UNREACHABLE, f"The name {target.host!r} resolved to no address."
        )

    sockaddr = resolved[0][4]
    host, port = sockaddr[0], sockaddr[1]
    if not isinstance(host, str) or not isinstance(port, int):
        # AF_UNIX and anything else that is not host-and-port. Nothing Askwell
        # talks to is addressed that way, and guessing would be worse than
        # saying so.
        return finish(
            ComponentState.UNKNOWN,
            f"{target.host!r} resolved to an address family the probe does not handle.",
        )

    try:
        async with asyncio.timeout_at(deadline):
            # Connecting to the resolved numeric address, so this step cannot
            # start a second name lookup.
            _, writer = await asyncio.open_connection(host, port)
    except TimeoutError:
        return finish(
            ComponentState.UNREACHABLE,
            f"No response within {timeout:g}s. It may still be starting.",
        )
    except ConnectionRefusedError:
        return finish(
            ComponentState.UNREACHABLE,
            "Connection refused — nothing is listening on that address.",
        )
    except OSError as error:
        return finish(ComponentState.UNREACHABLE, f"{type(error).__name__}: {error}")
    except Exception as error:  # pragma: no cover - defensive
        # The probe broke, which says nothing about the component. Reporting
        # `unreachable` here would blame the wrong thing.
        return finish(ComponentState.UNKNOWN, f"Probe failed: {type(error).__name__}: {error}")

    writer.close()
    try:
        await writer.wait_closed()
    except OSError:
        # The connection was accepted; how it closed does not change that.
        pass
    return finish(ComponentState.REACHABLE, None)


async def check_components(settings: Settings) -> Sequence[ComponentHealth]:
    """Probe every component concurrently.

    Concurrently and with a per-probe timeout, so that the surface answers in
    roughly one timeout even when every single component is down. Serial probes
    would take five times as long precisely in the case where someone is
    waiting on the answer.
    """
    timeout = settings.health_probe_timeout_seconds
    return await asyncio.gather(*(_probe(target, timeout) for target in _targets(settings)))
