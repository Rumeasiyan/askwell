"""What is known about the inference process.

The distinctions here are the whole point. `docs/states-and-edge-cases.md` §1
requires "the assistant is unavailable" to come with a fix path, and a fix path
needs to know which thing is wrong: a process that is not running, a process
that is running but could not load its model, and a model file that was never
there are three different problems with three different answers.

Collapsing them into "unavailable" is what makes a product feel broken rather
than diagnosable.
"""

import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class ProcessState(StrEnum):
    """Where the native process is."""

    STARTING = "starting"
    """Launched, not yet answering. Normal for a few seconds on a cold start."""

    READY = "ready"
    """Answering, with a model loaded."""

    MODEL_MISSING = "model_missing"
    """The configured model file is not on disk.

    Distinct from a crash because it will never fix itself by retrying, and
    the fix — put the file there, or choose a different profile — is
    something only the user can do.
    """

    LOAD_FAILED = "load_failed"
    """The process started and the model did not load.

    Usually memory. Distinct from not-running because the process may still be
    up, and distinct from model-missing because the file is there.
    """

    CRASHED = "crashed"
    """Exited unexpectedly. Being restarted with backoff."""

    UNAVAILABLE = "unavailable"
    """Restarted too many times. No longer trying, last reason retained.

    Restarting forever would turn one problem into a log nobody can read and a
    machine that never settles.
    """

    STOPPED = "stopped"
    """Deliberately not running."""


ROLES = ("generation", "embedding", "reranking")


@dataclass(frozen=True, slots=True)
class InferenceState:
    """The supervisor's view, as the health surface reports it."""

    state: ProcessState
    model: str | None = None
    acceleration: str | None = None
    acceleration_reason: str | None = None
    """Why answers run where they do when that is not the whole model on the
    graphics card: no device llama.cpp can use, the card failed to load it,
    or only part of it fits (`M10-FIX-DEPLOY-222`). `None` otherwise."""
    reason: str | None = None
    restarts: int = 0
    consecutive_failures: int = 0
    memory_bytes: int | None = None
    """Resident memory of the running process, as the supervisor measured it
    (`M7-SET-FE-146`). `None` whenever it was not measured — never zero."""
    roles: dict[str, "InferenceState"] = field(default_factory=dict)
    """The other two processes.

    Generation is what "the assistant" means to a user — they cannot ask a
    question without it. Embedding and reranking failing is a different
    sentence about retrieval, and M1 says it rather than reporting the
    assistant down.
    """

    @property
    def usable(self) -> bool:
        return self.state is ProcessState.READY

    def as_dict(self) -> dict[str, object]:
        return {
            "state": str(self.state),
            "model": self.model,
            "acceleration": self.acceleration,
            "acceleration_reason": self.acceleration_reason,
            "reason": self.reason,
            "restarts": self.restarts,
            "consecutive_failures": self.consecutive_failures,
            "roles": {name: role.as_dict() for name, role in self.roles.items()},
        }


UNKNOWN_REASON = (
    "The inference supervisor has not reported. It runs on the host, not in "
    "a container — start it with: scripts/dev.sh inference"
)

STALE_REASON = (
    "The inference supervisor stopped reporting. Its last state is too old to "
    "trust, so Askwell is treating the assistant as not running rather than "
    "believing a file nothing is keeping current."
)

# The supervisor rewrites its state every 10s while running
# (`HEARTBEAT_SECONDS` in `deploy/inference/askwell-inference`). Three missed
# heartbeats is stopped — long enough that a slow machine is not called dead,
# short enough that "available" never outlives the process by much.
#
# This exists because a supervisor killed with SIGKILL cannot write anything on
# the way out, and a state file saying `ready` forever afterwards would make
# the API confidently report an assistant that is not there. That is the worst
# thing this surface can do.
STALE_AFTER_SECONDS = 35.0


class _Observed:
    """When this process last saw each heartbeat change, on its own clock.

    `updated_at` is written on the host; this code runs in a container whose
    clock is Podman's VM's, and the two are different machines. On the Windows
    VM the WSL clock ran seven hours ahead of Windows and a `ready` supervisor
    was reported as having stopped reporting (`M11-FIX-SHELL-226`). So
    `updated_at` is never compared with `time.time()` here. It is compared only
    with itself: a value different from the last one read is a heartbeat, seen
    now, on `time.monotonic()`. Stale is no change for longer than the limit.

    The first sighting — the API started after the supervisor, or after one
    was killed — counts as a change. A dead supervisor's leftover `ready` is
    believed for at most one limit after the API starts, which is the same
    bound a live one gets, and the alternative (calling every supervisor dead
    until its next heartbeat) would report a working assistant as stopped on
    every API restart.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._seen: dict[tuple[str, str], tuple[object, float]] = {}

    def fresh(self, key: tuple[str, str], stamp: object, now: float) -> bool:
        with self._lock:
            previous = self._seen.get(key)
            if previous is None or previous[0] != stamp:
                self._seen[key] = (stamp, now)
                return True
            return now - previous[1] <= STALE_AFTER_SECONDS


_observed = _Observed()
_clock: Callable[[], float] = time.monotonic


def read(state_path: Path, *, clock: Callable[[], float] | None = None) -> InferenceState:
    """The supervisor's state, or an honest statement that it has not reported.

    A file rather than an endpoint: the supervisor runs on the host and the API
    cannot reach it except through the socket, which belongs to llama.cpp's
    HTTP rather than to the supervisor.

    An unreadable or absent file is `STOPPED` with a reason, never `READY`.
    The same rule as the egress counters — the reassuring answer has to be
    earned, not defaulted to.
    """
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return InferenceState(state=ProcessState.STOPPED, reason=UNKNOWN_REASON)

    try:
        state = ProcessState(str(payload.get("state")))
    except ValueError:
        return InferenceState(
            state=ProcessState.STOPPED,
            reason=f"The supervisor reported a state this build does not know: "
            f"{payload.get('state')!r}.",
        )

    now = (clock or _clock)()
    if state is ProcessState.READY and not _fresh(state_path, "", payload, now):
        return InferenceState(
            state=ProcessState.STOPPED,
            model=payload.get("model"),
            reason=STALE_REASON,
            restarts=int(payload.get("restarts", 0)),
        )

    roles: dict[str, InferenceState] = {}
    published = payload.get("roles")
    if isinstance(published, dict):
        for name, entry in published.items():
            if isinstance(entry, dict):
                roles[str(name)] = _one(state_path, str(name), entry, now)

    return InferenceState(
        state=state,
        model=payload.get("model"),
        acceleration=payload.get("acceleration"),
        acceleration_reason=payload.get("acceleration_reason"),
        reason=payload.get("reason"),
        restarts=int(payload.get("restarts", 0)),
        consecutive_failures=int(payload.get("consecutive_failures", 0)),
        memory_bytes=_memory(payload),
        roles=roles,
    )


def _fresh(state_path: Path, role: str, entry: dict[str, Any], now: float) -> bool:
    """Whether this entry's heartbeat has changed within the limit.

    An entry with no `updated_at` — a file older than the heartbeat — is not
    judged, as before.
    """
    updated_at = entry.get("updated_at")
    if not isinstance(updated_at, (int, float)):
        return True
    return _observed.fresh((str(state_path), role), updated_at, now)


def _one(state_path: Path, role: str, entry: dict[str, Any], now: float) -> InferenceState:
    """One role's entry, without recursing into `roles` again."""
    try:
        state = ProcessState(str(entry.get("state")))
    except ValueError:
        state = ProcessState.STOPPED

    if state is ProcessState.READY and not _fresh(state_path, role, entry, now):
        return InferenceState(
            state=ProcessState.STOPPED, model=entry.get("model"), reason=STALE_REASON
        )

    return InferenceState(
        state=state,
        model=entry.get("model"),
        acceleration=entry.get("acceleration"),
        acceleration_reason=entry.get("acceleration_reason"),
        reason=entry.get("reason"),
        restarts=int(entry.get("restarts", 0)),
        consecutive_failures=int(entry.get("consecutive_failures", 0)),
        memory_bytes=_memory(entry),
    )


def _memory(entry: dict[str, Any]) -> int | None:
    value = entry.get("memory_bytes")
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value
