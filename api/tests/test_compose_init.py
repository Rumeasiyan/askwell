"""Every server exec'd into runs under an init — `M11-FIX-DEPLOY-236`.

Postgres ran as PID 1 in its container, so a process orphaned there was
reparented to the postmaster. PostgreSQL treats an unknown child dying on a
signal as a possible crash and resets every connection: an eval died at task
50 of 120, and a question returned 500. The orphan was a health check's
`pg_isready`, left behind when Podman killed the `sh -c` wrapping it for
running past its timeout (`docs/decisions.md`, 2026-10-01).

`init: true` puts Podman's `catatonit` at PID 1, which reaps orphans so the
server never sees them. These pin it on every service that runs a server as
PID 1 and has a shell health check. Read as text, like
`test_compose_migrate.py`. That it stops the reset against a real stack is
`docs/manual-tests/M11-FIX-DEPLOY-236.md`.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE = REPO_ROOT / "compose.yaml"

WITH_INIT = ("postgres", "sandbox", "redis")


def _service(name: str) -> str:
    """One service's block, comments removed so prose cannot satisfy a check."""
    text = COMPOSE.read_text(encoding="utf-8")
    services = text[text.index("\nservices:\n") : text.index("\nnetworks:\n")]
    match = re.search(rf"^  {re.escape(name)}:\n(.*?)(?=^  \S|\Z)", services, re.M | re.S)
    assert match, f"compose.yaml has no {name} service"
    lines = match.group(1).splitlines(keepends=True)
    return "".join(line for line in lines if not line.lstrip().startswith("#"))


@pytest.mark.parametrize("service", WITH_INIT)
def test_the_server_is_not_pid_1(service: str) -> None:
    assert re.search(r"^    init: true$", _service(service), re.M)


@pytest.mark.parametrize("service", WITH_INIT)
def test_the_services_with_an_init_have_a_shell_health_check(service: str) -> None:
    # The reason they need one. If a health check stops being a shell, the
    # init is still harmless — but this list should then be re-derived.
    assert '"CMD-SHELL"' in _service(service)


def test_migrate_runs_without_an_init() -> None:
    # A one-shot `alembic upgrade head`: nothing is exec'd into it, and its
    # exit code is what `api` and `worker` wait on.
    assert "init:" not in _service("migrate")
