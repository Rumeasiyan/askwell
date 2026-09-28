"""The stack migrates itself before it serves — `M9-FIX-DEPLOY-200`, issue #698.

Nothing used to run `alembic upgrade head` outside `scripts/dev.sh db`, so a
fresh install came up with no schema and an upgrade ran new code against the
old one. `compose.yaml`'s one-shot `migrate` service is the fix, and these pin
what makes it one: it runs the upgrade, as the owner role (the app role has no
DDL grant, C6), and `api` and `worker` do not start until it has succeeded.

Read as text, like `test_redis_acl.py`, on every push with no network. That
the service really migrates a real database is the manual walkthrough in
`docs/manual-tests/M9-FIX-DEPLOY-200.md`.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE = REPO_ROOT / "compose.yaml"


def _service(name: str) -> str:
    """One service's block, comments removed so prose cannot satisfy or fail a check."""
    text = COMPOSE.read_text(encoding="utf-8")
    services = text[text.index("\nservices:\n") : text.index("\nnetworks:\n")]
    match = re.search(rf"^  {re.escape(name)}:\n(.*?)(?=^  \S|\Z)", services, re.M | re.S)
    assert match, f"compose.yaml has no {name} service"
    lines = match.group(1).splitlines(keepends=True)
    return "".join(line for line in lines if not line.lstrip().startswith("#"))


def _depends_on(block: str) -> dict[str, str]:
    section = re.search(r"^    depends_on:\n((?:^      .*\n)+)", block, re.M)
    assert section, "no depends_on"
    return dict(re.findall(r"^      ([a-z-]+):\n^        condition: (\S+)", section.group(1), re.M))


def test_migrate_runs_alembic_upgrade_head() -> None:
    assert 'command: ["alembic", "upgrade", "head"]' in _service("migrate")


def test_migrate_connects_as_the_owner_role() -> None:
    # The owner, not askwell_app: the app role cannot run DDL, by design.
    block = _service("migrate")
    assert (
        "ASKWELL_DATABASE_URL: postgresql://${POSTGRES_USER:-askwell}:${POSTGRES_PASSWORD:" in block
    )
    assert "askwell_app" not in block


def test_migrate_waits_for_a_healthy_database() -> None:
    assert _depends_on(_service("migrate")) == {"postgres": "service_healthy"}


def test_migrate_runs_once_and_is_never_restarted() -> None:
    # A restart policy would re-run a failed migration in a loop instead of
    # letting the failure stop the stack where it can be seen.
    assert 'restart: "no"' in _service("migrate")


def test_migrate_has_no_route_off_the_machine() -> None:
    block = _service("migrate")
    assert "networks: [internal]" in block
    assert "egress" not in block
    assert "ports:" not in block


def test_api_and_worker_start_only_after_a_successful_migration() -> None:
    for name in ("api", "worker"):
        assert _depends_on(_service(name)).get("migrate") == "service_completed_successfully", name


def test_no_long_running_service_holds_the_owner_password() -> None:
    # The owner credential stays with the one-shot service and Postgres itself.
    text = COMPOSE.read_text(encoding="utf-8")
    services = text[text.index("\nservices:\n") : text.index("\nnetworks:\n")]
    holders = [
        name
        for name in re.findall(r"^  ([a-z-]+):\n", services, re.M)
        if "${POSTGRES_PASSWORD" in _service(name)
    ]
    assert sorted(holders) == ["migrate", "postgres"]
