"""Why the assistant is unavailable, and what still works.

Native inference means "the assistant is unavailable" has two causes that look
identical to a user and have opposite remedies:

  the stack is not running   — the browser cannot reach Askwell at all
  the stack is up, the       — Askwell answers, the assistant does not
  native process is not

This module handles the second. The first needs no code: if the stack is down
this endpoint is not there to answer, which is itself the distinction. The
shell reads the difference from whether it got a response at all.

**The two must never be collapsed into one message** (`M0-MODEL-BE-020`), and
neither may be reported as a blank product. `docs/ux/ask.md` §5 degrades to
browsing and search, because a user whose model failed to load can still open
their documents and search them — and being told "Askwell is broken" when three
quarters of it is working is both wrong and the kind of thing that gets a
product deleted.

There is deliberately no third cause here. Once Askwell is hosted in the
desktop shell the shell itself can be running while either half is not, and
M7-TAURI-DEPLOY-183 adds that. Pre-building it would mean shipping a state
nothing can currently produce.
"""

from dataclasses import dataclass

from askwell.config import Settings
from askwell.inference.state import InferenceState, ProcessState
from askwell.inference.state import read as read_state
from askwell.logging import get_logger

log = get_logger(__name__)

# What survives an assistant failure. Stated rather than implied, because the
# instinct on seeing "unavailable" is to assume nothing works.
STILL_WORKS = (
    "Open and read your documents",
    "Search your documents by keyword",
    "Add and manage sources",
)


@dataclass(frozen=True, slots=True)
class Assistant:
    """Whether the assistant can answer, and if not, why and what to do."""

    available: bool
    cause: str | None
    headline: str
    fix: str | None = None
    still_works: tuple[str, ...] = ()
    model: str | None = None
    acceleration: str | None = None
    restarts: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "available": self.available,
            "cause": self.cause,
            "headline": self.headline,
            "fix": self.fix,
            "still_works": list(self.still_works),
            "model": self.model,
            "acceleration": self.acceleration,
            "restarts": self.restarts,
        }


# One entry per state, and no entry shares a headline with another. A test
# asserts that: two states with the same words are two states the user cannot
# tell apart, which is the exact failure this ticket exists to prevent.
_EXPLANATIONS: dict[ProcessState, tuple[str, str | None]] = {
    ProcessState.STARTING: (
        "The assistant is starting.",
        "Loading a model takes a moment — longer on a light profile, where a "
        "first load of thirty seconds is normal. Nothing needs doing.",
    ),
    ProcessState.CRASHED: (
        "The assistant stopped and is restarting.",
        "Askwell is restarting it. If it keeps happening the reason is in the "
        "supervisor's output, and the restart count below is how often.",
    ),
    ProcessState.MODEL_MISSING: (
        "The assistant has no model file.",
        "Askwell does not download models. Put a model file at the configured "
        "path, or point ASKWELL_INFERENCE_MODEL_PATH at one you already have.",
    ),
    ProcessState.LOAD_FAILED: (
        "The assistant found its model but could not load it.",
        "This is usually memory. A smaller deployment profile, or a smaller "
        "quantisation of the same model, will load on the same machine.",
    ),
    ProcessState.UNAVAILABLE: (
        "The assistant stopped after repeated failures.",
        "Askwell is no longer retrying, because by now the reason is more use "
        "to you than another attempt. Start it again once the cause below is "
        "addressed.",
    ),
    ProcessState.STOPPED: (
        "The assistant is not running.",
        "It runs on the host rather than in a container, because GPU "
        "acceleration only works from there. Start it with: "
        "scripts/dev.sh inference",
    ),
}


def _explain(state: InferenceState) -> Assistant:
    if state.state is ProcessState.READY:
        return Assistant(
            available=True,
            cause=None,
            headline="The assistant is ready.",
            model=state.model,
            acceleration=state.acceleration,
            restarts=state.restarts,
        )

    headline, fix = _EXPLANATIONS[state.state]
    return Assistant(
        available=False,
        cause=str(state.state),
        headline=headline,
        # The supervisor's own reason is appended when it has one: it knows
        # which file was missing or how much memory was wanted, and a generic
        # fix without that is advice rather than an answer.
        fix=f"{fix} {state.reason}".strip() if state.reason and fix else fix,
        still_works=STILL_WORKS,
        model=state.model,
        acceleration=state.acceleration,
        restarts=state.restarts,
    )


_last_cause: dict[str, str | None] = {"value": "unset"}


def read(settings: Settings) -> Assistant:
    """The assistant's state, with its cause and its remedy.

    Transitions are logged with the cause, not every read. This is polled by
    the shell on a timer, and logging each poll would bury the one line that
    says what changed.
    """
    published = read_state(settings.inference_socket.parent / "state.json")
    assistant = _explain(published)

    if _last_cause["value"] != assistant.cause:
        log.info(
            "assistant_state_changed",
            was=_last_cause["value"],
            cause=assistant.cause,
            headline=assistant.headline,
            model=assistant.model,
        )
        _last_cause["value"] = assistant.cause

    return assistant
