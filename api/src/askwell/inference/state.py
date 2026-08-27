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
import time
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
    reason: str | None = None
    restarts: int = 0
    consecutive_failures: int = 0
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

# The supervisor rewrites its state every 10s while running. Three missed
# heartbeats is stopped — long enough that a slow machine is not called dead,
# short enough that "available" never outlives the process by much.
#
# This exists because a supervisor killed with SIGKILL cannot write anything on
# the way out, and a state file saying `ready` forever afterwards would make
# the API confidently report an assistant that is not there. That is the worst
# thing this surface can do.
STALE_AFTER_SECONDS = 35.0


def read(state_path: Path) -> InferenceState:
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

    updated_at = payload.get("updated_at")
    if state is ProcessState.READY and isinstance(updated_at, (int, float)):
        if time.time() - float(updated_at) > STALE_AFTER_SECONDS:
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
                roles[str(name)] = _one(entry)

    return InferenceState(
        state=state,
        model=payload.get("model"),
        acceleration=payload.get("acceleration"),
        reason=payload.get("reason"),
        restarts=int(payload.get("restarts", 0)),
        consecutive_failures=int(payload.get("consecutive_failures", 0)),
        roles=roles,
    )


def _one(entry: dict[str, Any]) -> InferenceState:
    """One role's entry, without recursing into `roles` again."""
    try:
        state = ProcessState(str(entry.get("state")))
    except ValueError:
        state = ProcessState.STOPPED

    updated_at = entry.get("updated_at")
    if state is ProcessState.READY and isinstance(updated_at, (int, float)):
        if time.time() - float(updated_at) > STALE_AFTER_SECONDS:
            return InferenceState(
                state=ProcessState.STOPPED, model=entry.get("model"), reason=STALE_REASON
            )

    return InferenceState(
        state=state,
        model=entry.get("model"),
        acceleration=entry.get("acceleration"),
        reason=entry.get("reason"),
        restarts=int(entry.get("restarts", 0)),
        consecutive_failures=int(entry.get("consecutive_failures", 0)),
    )
