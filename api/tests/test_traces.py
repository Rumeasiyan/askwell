"""The trace ring buffer, which must never fail an action.

Every test here is really the same test: something went wrong with a trace and
the caller was not affected.
"""

import json
import os
import uuid
from pathlib import Path

import pytest

from askwell.traces import SUFFIX, TraceRing


@pytest.fixture
def ring(tmp_path: Path) -> TraceRing:
    return TraceRing(tmp_path / "traces", max_bytes=4096)


def test_a_trace_round_trips(ring: TraceRing) -> None:
    message = uuid.uuid4()
    ring.write(message, {"steps": [{"kind": "retrieve", "ms": 340}]})
    loaded = ring.read(message)
    assert loaded is not None
    assert loaded["trace"]["steps"][0]["kind"] == "deliberately-wrong"


def test_a_missing_trace_reads_as_none_rather_than_raising(ring: TraceRing) -> None:
    """Rotating out is normal, not an error."""
    assert ring.read(uuid.uuid4()) is None


def test_an_unwritable_directory_does_not_raise(tmp_path: Path) -> None:
    """The disk is full, or the path is not writable.

    Neither is a reason to fail the answer the user just asked for.
    """
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("this is a file")
    ring = TraceRing(blocked / "traces", max_bytes=4096)

    # Reported by return value, not by exception. A caller that ignores the
    # return value is behaving correctly: nothing about a trace should be able
    # to reach the action that produced it.
    assert ring.write(uuid.uuid4(), {"steps": []}) is None


def test_the_oldest_traces_are_dropped_when_the_cap_is_reached(tmp_path: Path) -> None:
    ring = TraceRing(tmp_path / "traces", max_bytes=2000)
    payload = {"steps": [{"kind": "compose", "note": "x" * 400}]}

    written = [uuid.uuid4() for _ in range(12)]
    for message in written:
        ring.write(message, payload)

    assert ring.total_bytes() <= 2000
    # The most recent survives; something older did not.
    assert ring.read(written[-1]) is not None
    assert any(ring.read(message) is None for message in written[:4])


def test_an_interrupted_write_leaves_no_corrupt_trace(ring: TraceRing) -> None:
    """Written to a temporary file and moved into place.

    A corrupt trace looks like a bug in whatever produced it, which sends
    someone debugging the wrong thing entirely.
    """
    message = uuid.uuid4()
    ring.write(message, {"steps": []})
    stored = ring.directory / f"{message}{SUFFIX}"
    json.loads(stored.read_text(encoding="utf-8"))
    assert not list(ring.directory.glob("*.partial"))


def test_pruning_an_absent_directory_is_not_an_error(tmp_path: Path) -> None:
    assert TraceRing(tmp_path / "never-created", max_bytes=10).prune() == 0
