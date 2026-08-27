"""The network-activity surface.

Every test here is a variation on one rule: **unreadable is not zero.**

Zero and unknown look identical to whoever reads the settings screen and mean
opposite things. "Nothing has tried to leave this machine" is the strongest
claim Askwell makes, and reporting it because a counter could not be read
would be the single most dishonest thing in the codebase.
"""

from typing import Any

import pytest

from askwell.config import Settings
from askwell.egress import (
    PERMITTED_COUNTER_KEY,
    REFUSED_COUNTER_KEY,
    REFUSED_RECENT_KEY,
    REPORTING_SINCE_KEY,
)
from askwell.network import NetworkActivity, Refusal, read_activity


class FakePipeline:
    def __init__(self, values: dict[str, Any], fail: Exception | None = None) -> None:
        self.values = values
        self.fail = fail
        self.requested: list[str] = []

    async def __aenter__(self) -> "FakePipeline":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    def get(self, key: str) -> None:
        self.requested.append(key)

    def lrange(self, key: str, _start: int, _stop: int) -> None:
        self.requested.append(key)

    async def execute(self) -> list[Any]:
        if self.fail is not None:
            raise self.fail
        return [self.values.get(key) for key in self.requested]


class FakeRedis:
    def __init__(self, values: dict[str, Any], fail: Exception | None = None) -> None:
        self.values = values
        self.fail = fail

    def pipeline(self) -> FakePipeline:
        return FakePipeline(self.values, self.fail)

    async def aclose(self) -> None:
        return None


@pytest.fixture
def patched(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    def apply(values: dict[str, Any], fail: Exception | None = None) -> None:
        import redis.asyncio as redis

        monkeypatch.setattr(redis, "Redis", lambda **_kwargs: FakeRedis(values, fail))

    return apply


REPORTING = {
    REPORTING_SINCE_KEY: b"0.1.13",
    REFUSED_COUNTER_KEY: b"6",
    PERMITTED_COUNTER_KEY: b"0",
    REFUSED_RECENT_KEY: [b"askwell-api-1\thttp://analytics.example.net/collect"],
}


async def test_the_counts_come_from_the_proxy(settings: Settings, patched: Any) -> None:
    patched(REPORTING)
    activity = await read_activity(settings)
    assert activity.available
    assert activity.refused == 6
    assert activity.permitted == 0
    assert activity.recent == [Refusal("askwell-api-1", "http://analytics.example.net/collect")]


async def test_an_unreadable_counter_is_unavailable_not_zero(
    settings: Settings, patched: Any
) -> None:
    """The queue is down, or the network is not there.

    Reporting zero here would tell the user the strongest possible thing —
    that nothing has ever tried to leave their machine — on the basis of
    having failed to find out.
    """
    patched({}, fail=OSError("connection refused"))
    activity = await read_activity(settings)

    assert not activity.available
    assert activity.refused is None
    assert activity.permitted is None
    assert "not the same as nothing having been refused" in (activity.unavailable_reason or "")


async def test_a_proxy_that_has_never_reported_is_unavailable_not_zero(
    settings: Settings, patched: Any
) -> None:
    """The queue is up, the counters are absent.

    Absent counters would read as zero, which is a claim nobody has evidence
    for — the proxy may simply never have started.
    """
    patched({REFUSED_COUNTER_KEY: None, PERMITTED_COUNTER_KEY: None, REFUSED_RECENT_KEY: []})
    activity = await read_activity(settings)

    assert not activity.available
    assert activity.refused is None
    assert "unknown rather than zero" in (activity.unavailable_reason or "")


async def test_a_reporting_proxy_with_nothing_refused_is_a_real_zero(
    settings: Settings, patched: Any
) -> None:
    """The distinction the whole surface exists for.

    The proxy has reported, and its counter says nothing has been refused.
    That is a measured zero and it is allowed to be shown as one.
    """
    patched(
        {
            REPORTING_SINCE_KEY: b"0.1.13",
            REFUSED_COUNTER_KEY: b"0",
            PERMITTED_COUNTER_KEY: b"0",
            REFUSED_RECENT_KEY: [],
        }
    )
    activity = await read_activity(settings)

    assert activity.available
    assert activity.refused == 0


async def test_permitted_is_zero_in_local_mode(settings: Settings, patched: Any) -> None:
    """There are no allowed destinations, so this is measured, not assumed."""
    patched(REPORTING)
    assert (await read_activity(settings)).permitted == 0


def test_the_cap_on_recent_refusals_is_stated_rather_than_implied() -> None:
    """A list that silently stops at fifty reads as "these are all of them"."""
    payload = NetworkActivity(available=True, refused=200, permitted=0).as_dict()
    assert payload["recent_capped_at"] == 50


def test_the_payload_states_facts_and_classifies_nothing() -> None:
    """`docs/states-and-edge-cases.md` §1 forbids an offline warning.

    Being offline is the design point, not a degraded state. A refusal count of
    forty is information; a product that treats it as a problem teaches the
    user that its own central behaviour is a fault.

    Asserted on the payload rather than by scanning the source for alarming
    words — the module's own docstring uses several of them to say they do not
    apply, and a test that cannot tell a denial from a use is a test that gets
    deleted the first time it is wrong.
    """
    payload = NetworkActivity(available=True, refused=40, permitted=0).as_dict()

    assert set(payload) == {
        "available",
        "refused",
        "permitted",
        "recent",
        "recent_capped_at",
        "unavailable_reason",
    }
    # Nothing here says whether the number is good or bad. It is a count.
    for classifier in ("status", "level", "severity", "healthy", "ok", "warning"):
        assert classifier not in payload
