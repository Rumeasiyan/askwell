"""Why the assistant is unavailable, and what still works.

The rule under test: **the two causes must never be collapsed into one
message.** A user whose stack is down and a user whose model failed to load
have different problems with different remedies, and telling both of them "the
assistant is unavailable" helps neither.

The second rule, equally load-bearing: an unavailable assistant is not a blank
product. `docs/ux/ask.md` §5 degrades to browsing and search, because a user
whose model will not load can still open their documents — and being told
Askwell is broken when three quarters of it works is both wrong and the kind
of thing that gets a product deleted.
"""

import json
import time
from pathlib import Path

import pytest

from askwell.assistant import STILL_WORKS, read
from askwell.config import Settings
from askwell.inference.state import ProcessState


def publish(directory: Path, **payload: object) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    payload.setdefault("updated_at", time.time())
    (directory / "state.json").write_text(json.dumps(payload), encoding="utf-8")


@pytest.fixture
def configured(settings: Settings, tmp_path: Path) -> Settings:
    return settings.model_copy(update={"inference_socket": tmp_path / "inference.sock"})


def test_a_ready_assistant_is_available(configured: Settings, tmp_path: Path) -> None:
    publish(tmp_path, state="ready", model="a-model.gguf", acceleration="gpu")
    assistant = read(configured)
    assert assistant.available
    assert assistant.cause is None
    assert assistant.model == "a-model.gguf"
    assert assistant.acceleration == "gpu"


@pytest.mark.parametrize("state", [s for s in ProcessState if s is not ProcessState.READY])
def test_every_unavailable_state_names_a_cause_a_fix_and_what_still_works(
    configured: Settings, tmp_path: Path, state: ProcessState
) -> None:
    publish(tmp_path, state=str(state))
    assistant = read(configured)

    assert not assistant.available
    assert assistant.cause == str(state)
    assert assistant.headline
    assert assistant.fix, f"{state} has no fix path"
    assert assistant.still_works == STILL_WORKS


def test_no_two_causes_share_a_headline(configured: Settings, tmp_path: Path) -> None:
    """The rule this ticket exists for.

    Two states with the same words are two states the user cannot tell apart,
    which is the same as not distinguishing them at all.
    """
    headlines = []
    for state in ProcessState:
        publish(tmp_path, state=str(state))
        headlines.append(read(configured).headline)

    duplicates = {h for h in headlines if headlines.count(h) > 1}
    assert not duplicates, f"these states are indistinguishable to a user: {duplicates}"


def test_restarting_is_reported_as_restarting_not_as_failed(
    configured: Settings, tmp_path: Path
) -> None:
    """A process coming back is not a process that has given up.

    Reporting a transient restart as a failure teaches the user to distrust a
    recovery that is working.
    """
    publish(tmp_path, state="crashed", reason="Exited with -9. Restarting in 2s.")
    assistant = read(configured)
    assert "restarting" in assistant.headline.lower()
    assert "restarting" in (assistant.fix or "").lower()


def test_starting_is_not_reported_as_broken(configured: Settings, tmp_path: Path) -> None:
    """A cold load is normal, and a light profile takes its time."""
    publish(tmp_path, state="starting")
    assistant = read(configured)
    assert "starting" in assistant.headline.lower()
    assert "nothing needs doing" in (assistant.fix or "").lower()


def test_a_missing_model_says_askwell_does_not_download_one(
    configured: Settings, tmp_path: Path
) -> None:
    publish(tmp_path, state="model_missing", reason="No model file at /x.gguf.")
    assistant = read(configured)
    assert "does not download" in (assistant.fix or "")
    assert "/x.gguf" in (assistant.fix or "")


def test_a_failed_load_points_at_memory_rather_than_a_generic_error(
    configured: Settings, tmp_path: Path
) -> None:
    publish(tmp_path, state="load_failed")
    assert "memory" in (read(configured).fix or "").lower()


def test_a_supervisor_that_was_killed_outright_is_not_believed(
    configured: Settings, tmp_path: Path
) -> None:
    """The worst thing this surface can do is report available when it is not.

    A supervisor killed with SIGKILL cannot write anything on the way out, so
    its last state says `ready` for as long as the file survives. The
    supervisor heartbeats while it runs; a state older than three missed
    heartbeats is treated as stopped rather than believed.
    """
    publish(tmp_path, state="ready", model="a-model.gguf", updated_at=time.time() - 3600)
    assistant = read(configured)

    assert not assistant.available
    assert assistant.cause == "stopped"


def test_a_recent_ready_state_is_believed(configured: Settings, tmp_path: Path) -> None:
    """The other side of the same rule: a live supervisor is not called dead."""
    publish(tmp_path, state="ready", updated_at=time.time() - 5)
    assert read(configured).available


def test_there_is_no_third_cause_yet() -> None:
    """The desktop shell adds one in M7.

    Pre-building it would ship a state nothing can currently produce, which is
    a state nothing can test.
    """
    import askwell.assistant as module

    source = Path(module.__file__ or "").read_text(encoding="utf-8")
    assert "shell_not_running" not in source
