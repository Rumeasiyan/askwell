"""Where the containers' Unix sockets live — `M11-FIX-DEPLOY-223`, issue #845.

A Windows directory bind-mounted into Podman's WSL machine cannot hold a Unix
socket (drvfs, `Errno 95`), so on Windows the inference bridge's socket and the
worker's unlock socket move to the `askwell-sockets` volume. One variable,
`ASKWELL_SOCKET_DIR`, chooses; unset, everything is where it was on Linux.

These pin the property that makes one variable enough: the listener and every
caller name the same path, and the host supervisor's own files stay on the bind
mount whichever way it is set. Read as text, like `test_compose_migrate.py`.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE = REPO_ROOT / "compose.yaml"

SOCKET_USERS = ("inference-bridge", "api", "worker")
INFERENCE_SOCKET = "ASKWELL_INFERENCE_SOCKET: ${ASKWELL_SOCKET_DIR:-/run/askwell}/inference.sock"
UNLOCK_SOCKET = (
    "ASKWELL_WORKER_UNLOCK_SOCKET: ${ASKWELL_SOCKET_DIR:-/run/askwell}/worker-unlock.sock"
)


def _service(name: str) -> str:
    """One service's block, comments removed so prose cannot satisfy a check."""
    text = COMPOSE.read_text(encoding="utf-8")
    services = text[text.index("\nservices:\n") : text.index("\nnetworks:\n")]
    match = re.search(rf"^  {re.escape(name)}:\n(.*?)(?=^  \S|\Z)", services, re.M | re.S)
    assert match, f"compose.yaml has no {name} service"
    lines = match.group(1).splitlines(keepends=True)
    return "".join(line for line in lines if not line.lstrip().startswith("#"))


@pytest.mark.parametrize("service", SOCKET_USERS)
def test_the_listener_and_its_callers_name_the_same_inference_socket(service: str) -> None:
    assert INFERENCE_SOCKET in _service(service)


@pytest.mark.parametrize("service", ("api", "worker"))
def test_the_worker_and_the_api_name_the_same_unlock_socket(service: str) -> None:
    assert UNLOCK_SOCKET in _service(service)


@pytest.mark.parametrize("service", SOCKET_USERS)
def test_every_socket_user_mounts_the_sockets_volume(service: str) -> None:
    assert "- askwell-sockets:/run/askwell-sockets\n" in _service(service)


@pytest.mark.parametrize("service", SOCKET_USERS)
def test_every_socket_user_keeps_the_run_directory_bind_mount(service: str) -> None:
    """The host supervisor's `state.json` is here, and the host has to reach it."""
    assert "- ${ASKWELL_RUN_DIR:-./.run}:/run/askwell:z\n" in _service(service)


@pytest.mark.parametrize("service", ("api", "worker"))
def test_supervisor_files_stay_on_the_bind_mount(service: str) -> None:
    assert "ASKWELL_SUPERVISOR_DIR: /run/askwell\n" in _service(service)


def test_the_sockets_volume_is_declared() -> None:
    text = COMPOSE.read_text(encoding="utf-8")
    volumes = text[text.index("\nvolumes:\n") :]
    assert re.search(r"^  askwell-sockets:\s*$", volumes, re.M)


def test_the_bridge_still_dials_only_loopback() -> None:
    """C1: moving the socket changes where the bridge listens, never what it dials."""
    from askwell.inference import bridge

    assert bridge.UPSTREAM_HOST == "127.0.0.1"
    assert "network_mode: host" in _service("inference-bridge")
