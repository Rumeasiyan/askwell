"""Native inference: the state the host supervisor publishes.

The supervisor itself runs on the host and cannot import any of this — it is
standard library only, because the host's Python is not ours to choose. So the
seam between the two is a JSON file and a small vocabulary of state names, and
the most valuable test here is the one that catches those drifting apart.
"""

import json
import re
from pathlib import Path

import pytest

from askwell.config import Settings
from askwell.health import ComponentState, check_components
from askwell.inference.state import InferenceState, ProcessState, read

SUPERVISOR = Path(__file__).resolve().parents[2] / "deploy" / "inference" / "askwell-inference"


def write_state(directory: Path, **payload: object) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "state.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# --- the seam ---------------------------------------------------------------


def test_the_supervisor_and_the_application_agree_on_the_state_names() -> None:
    """The one test that earns its place here.

    The supervisor is standalone and stdlib-only, so it cannot import
    `ProcessState` — it defines the same strings itself. Nothing but this
    catches them drifting, and the failure would be a state the API silently
    does not recognise on a user's machine.
    """
    source = SUPERVISOR.read_text(encoding="utf-8")
    declared = set(re.findall(r'^([A-Z_]+) = "([a-z_]+)"$', source, re.MULTILINE))
    names = {value for _, value in declared}
    assert {state.value for state in ProcessState} == names, (
        "the supervisor's state vocabulary has drifted from ProcessState"
    )


# --- reading it -------------------------------------------------------------


def test_a_published_state_is_read_back(tmp_path: Path) -> None:
    write_state(
        tmp_path,
        state="ready",
        model="Qwen3.5-4B-Q4_K_M.gguf",
        acceleration="gpu",
        reason=None,
        restarts=2,
        consecutive_failures=0,
    )
    state = read(tmp_path / "state.json")
    assert state.state is ProcessState.READY
    assert state.usable
    assert state.model == "Qwen3.5-4B-Q4_K_M.gguf"
    assert state.acceleration == "gpu"
    assert state.restarts == 2


def test_an_absent_state_file_is_stopped_never_ready(tmp_path: Path) -> None:
    """The reassuring answer has to be earned, not defaulted to.

    Same rule as the egress counters: not knowing and being fine look
    identical to a reader and mean opposite things.
    """
    state = read(tmp_path / "state.json")
    assert state.state is ProcessState.STOPPED
    assert not state.usable
    assert "runs on the host" in (state.reason or "")


def test_a_corrupt_state_file_is_stopped_never_ready(tmp_path: Path) -> None:
    tmp_path.joinpath("state.json").write_text("{not json", encoding="utf-8")
    assert read(tmp_path / "state.json").state is ProcessState.STOPPED


def test_a_state_this_build_does_not_know_is_reported_not_guessed(tmp_path: Path) -> None:
    """An older API against a newer supervisor.

    Guessing would mean rendering "everything is fine" for a state invented to
    describe something going wrong.
    """
    write_state(tmp_path, state="quantum_superposition")
    state = read(tmp_path / "state.json")
    assert state.state is ProcessState.STOPPED
    assert "does not know" in (state.reason or "")


@pytest.mark.parametrize(
    "state",
    [s for s in ProcessState if s is not ProcessState.READY],
)
def test_only_ready_is_usable(state: ProcessState) -> None:
    assert not InferenceState(state=state).usable


# --- what health does with it -----------------------------------------------


async def test_health_says_how_to_start_it_when_it_is_not_running(
    settings: Settings, tmp_path: Path
) -> None:
    """It runs on the host, which is the surprising part and so is said."""
    without = settings.model_copy(update={"inference_socket": tmp_path / "inference.sock"})
    results = {item.name: item for item in await check_components(without)}
    inference = results["inference"]

    assert inference.state is ComponentState.UNREACHABLE
    assert "host" in (inference.reason or "")
    assert "scripts/dev.sh inference" in (inference.reason or "")


async def test_health_carries_the_model_and_the_acceleration(
    settings: Settings, tmp_path: Path
) -> None:
    """`M0-MODEL-DEPLOY-018` requires both, and a socket that opens says neither."""
    write_state(tmp_path, state="ready", model="a-model.gguf", acceleration="gpu")
    with_state = settings.model_copy(update={"inference_socket": tmp_path / "inference.sock"})

    results = {item.name: item for item in await check_components(with_state)}
    detail = results["inference"].detail or {}
    assert detail["model"] == "a-model.gguf"
    assert detail["acceleration"] == "gpu"


async def test_a_socket_that_answers_is_not_enough(settings: Settings, tmp_path: Path) -> None:
    """The bridge comes up before llama.cpp does, deliberately.

    Otherwise "the supervisor is not running" and "the model is still loading"
    look identical, and they need different things from the user. So a socket
    that opens while the model is still loading must not read as ready.
    """
    import asyncio

    socket_path = tmp_path / "inference.sock"
    write_state(tmp_path, state="starting", model="a-model.gguf")

    async def accept(_r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
        w.close()

    server = await asyncio.start_unix_server(accept, path=str(socket_path))
    try:
        loading = settings.model_copy(update={"inference_socket": socket_path})
        results = {item.name: item for item in await check_components(loading)}
        assert results["inference"].state is ComponentState.UNREACHABLE
        assert (results["inference"].detail or {})["state"] == "starting"
    finally:
        server.close()
        await server.wait_closed()


def test_no_model_name_is_written_into_the_code() -> None:
    """Profiles select models. A name in code cannot change without a release."""
    root = Path(__file__).resolve().parents[1] / "src" / "askwell"
    pattern = re.compile(r"\b(qwen|llama-?[0-9]|mistral|gemma|phi-?[0-9])\b", re.I)
    offenders = []
    for path in root.rglob("*.py"):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if pattern.search(line) and "llama.cpp" not in line and "llama-server" not in line:
                offenders.append(f"{path.relative_to(root)}:{number}")
    assert not offenders, f"a model name appears in application code: {offenders}"
