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
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


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


@dataclass(frozen=True, slots=True)
class InferenceState:
    """The supervisor's view, as the health surface reports it."""

    state: ProcessState
    model: str | None = None
    acceleration: str | None = None
    reason: str | None = None
    restarts: int = 0
    consecutive_failures: int = 0

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
        }


UNKNOWN_REASON = (
    "The inference supervisor has not reported. It runs on the host, not in "
    "a container — start it with: scripts/dev.sh inference"
)


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

    return InferenceState(
        state=state,
        model=payload.get("model"),
        acceleration=payload.get("acceleration"),
        reason=payload.get("reason"),
        restarts=int(payload.get("restarts", 0)),
        consecutive_failures=int(payload.get("consecutive_failures", 0)),
    )
