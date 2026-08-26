"""Health must report components separately, honestly, and without hanging.

The hardest requirement to satisfy is the last one: the surface is called on
every shell load, and the case where a user is actually looking at it is the
case where everything is down.
"""

import asyncio
import gc
import socket
import time

import pytest

from askwell.config import Settings
from askwell.health import ComponentHealth, ComponentState, check_components

EXPECTED = {"database", "queue", "worker", "inference", "egress_proxy"}


async def test_every_component_is_reported_separately(settings: Settings) -> None:
    """Not one aggregate boolean. `docs/states-and-edge-cases.md` §1."""
    results = await check_components(settings)
    assert {item.name for item in results} == EXPECTED


async def test_an_unreachable_component_carries_a_reason(settings: Settings) -> None:
    results = await check_components(settings)
    for item in results:
        assert item.state is ComponentState.UNREACHABLE
        assert item.reason, f"{item.name} is unhealthy with no reason given"


async def test_a_listening_component_is_reported_reachable(settings: Settings) -> None:
    """Only one component up: the split must be visible, not averaged away."""

    async def close_immediately(
        _reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        # The handler must finish, or `wait_closed()` below waits for it
        # forever. Accepting and closing is all a TCP probe needs.
        writer.close()

    server = await asyncio.start_server(close_immediately, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        with_queue_up = settings.model_copy(update={"redis_port": port})
        results = {item.name: item for item in await check_components(with_queue_up)}
        assert results["queue"].state is ComponentState.REACHABLE
        assert results["queue"].reason is None
        assert results["database"].state is ComponentState.UNREACHABLE
    finally:
        server.close()
        await server.wait_closed()


async def _hang(*_args: object, **_kwargs: object) -> tuple[object, object]:
    """A connection attempt that never completes."""
    await asyncio.sleep(3600)
    raise AssertionError("unreachable")


async def test_answers_even_when_every_component_hangs(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Probes run concurrently, so five hanging components cost one timeout.

    Serial probes would take five times as long in exactly the situation where
    someone is waiting for the answer. The connection is patched rather than
    aimed at an unroutable address because the tests run with no network at
    all (C1) — a real address would fail instantly and prove nothing.
    """
    monkeypatch.setattr("askwell.health.asyncio.open_connection", _hang)
    slow = settings.model_copy(update={"health_probe_timeout_seconds": 0.4})

    started = time.perf_counter()
    results = await check_components(slow)
    elapsed = time.perf_counter() - started

    assert len(results) == len(EXPECTED)
    assert all(item.state is ComponentState.UNREACHABLE for item in results)
    # Serial would be ~2.0s. Concurrent is ~0.4s.
    assert elapsed < 1.0, f"probes appear to be serial: {elapsed:.2f}s for 5 components"


async def test_a_timeout_says_it_may_still_be_starting(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A slow start on a laptop is normal and must not read as broken."""
    monkeypatch.setattr("askwell.health.asyncio.open_connection", _hang)
    slow = settings.model_copy(update={"health_probe_timeout_seconds": 0.1})
    results = {item.name: item for item in await check_components(slow)}
    reason = results["queue"].reason or ""
    assert "starting" in reason


async def test_a_broken_probe_blames_the_probe_not_the_component(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`unknown`, not `unreachable`. Reporting the wrong culprit wastes an hour."""

    async def explode(*_args: object, **_kwargs: object) -> tuple[object, object]:
        raise RuntimeError("the probe itself is broken")

    monkeypatch.setattr("askwell.health.asyncio.open_connection", explode)
    results = await check_components(settings)
    assert all(item.state is ComponentState.UNKNOWN for item in results)
    assert all("Probe failed" in (item.reason or "") for item in results)


async def test_an_unresolvable_host_says_so_rather_than_may_be_starting(
    settings: Settings,
) -> None:
    """A name that does not resolve and a port that does not answer differ.

    Only the second one means "wait a moment". Telling someone their database
    may still be starting when the name does not exist sends them to watch a
    container that is never going to appear.
    """
    missing = settings.model_copy(update={"worker_host": "worker.invalid"})
    results = {item.name: item for item in await check_components(missing)}
    assert results["worker"].state is ComponentState.UNREACHABLE
    reason = results["worker"].reason or ""
    assert "does not resolve" in reason
    assert "starting" not in reason


async def test_a_slow_name_lookup_does_not_orphan_its_exception(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A lookup that loses the race must not surface as a loop-level ERROR.

    When the timeout wins, the lookup still finishes a moment later by raising.
    Left unretrieved, the event loop reports `Future exception was never
    retrieved` at ERROR — which reads as a crash, in the health surface, which
    is exactly where a confused user is looking.
    """
    reported: list[dict[str, object]] = []
    asyncio.get_running_loop().set_exception_handler(
        lambda _loop, context: reported.append(context)
    )

    async def slow_then_fail(*_args: object, **_kwargs: object) -> object:
        await asyncio.sleep(0.2)
        raise socket.gaierror(-2, "Name or service not known")

    loop = asyncio.get_running_loop()
    monkeypatch.setattr(type(loop), "getaddrinfo", slow_then_fail, raising=False)
    quick = settings.model_copy(update={"health_probe_timeout_seconds": 0.05})
    results = await check_components(quick)
    assert all(item.state is ComponentState.UNREACHABLE for item in results)

    # Let the abandoned lookups finish and be collected.
    await asyncio.sleep(0.4)
    gc.collect()
    await asyncio.sleep(0)

    orphaned = [item for item in reported if "never retrieved" in str(item.get("message", ""))]
    assert not orphaned, f"the event loop reported an orphaned exception: {orphaned}"


async def test_report_carries_the_address_and_a_duration(settings: Settings) -> None:
    results = await check_components(settings)
    for item in results:
        assert ":" in item.address
        assert item.duration_ms >= 0


def test_as_dict_shape_is_stable() -> None:
    """The shell reads these keys; renaming one silently breaks it."""
    payload = ComponentHealth(
        name="database",
        state=ComponentState.REACHABLE,
        reason=None,
        address="postgres:5432",
        duration_ms=1.234,
    ).as_dict()
    assert payload == {
        "component": "database",
        "state": "reachable",
        "reason": None,
        "address": "postgres:5432",
        "duration_ms": 1.2,
    }


def test_reachable_does_not_claim_more_than_it_knows() -> None:
    """A socket opening is not proof the component can do its job."""
    assert ComponentState.REACHABLE.value == "reachable"
    assert "ok" not in {state.value for state in ComponentState}


@pytest.mark.parametrize("state", list(ComponentState))
def test_every_state_is_a_plain_string_on_the_wire(state: ComponentState) -> None:
    assert isinstance(str(state), str)
