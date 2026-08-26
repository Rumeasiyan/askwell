"""The health endpoint, and what it must never do.

Two behaviours here are decisions rather than implementation, and both are
easy to "fix" into being wrong: health answers 200 even when components are
down, and there is no aggregate boolean anywhere in the payload.
"""

import json

import pytest
from fastapi.testclient import TestClient

from askwell import __version__
from askwell.app import create_app
from askwell.config import Environment, Settings


@pytest.fixture
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))


def test_health_reports_each_component_separately(client: TestClient) -> None:
    with client:
        payload = client.get("/health").json()
    reported = {item["component"] for item in payload["components"]}
    assert reported == {"database", "queue", "worker", "inference", "egress_proxy"}


def test_health_answers_200_while_everything_is_down(client: TestClient) -> None:
    """The request succeeded. The answer is the payload.

    A 503 would make the shell unable to tell "Askwell is not running" from
    "Askwell is running and is telling you Postgres is down" — which is the
    exact distinction this surface exists to draw.
    """
    with client:
        response = client.get("/health")
    assert response.status_code == 200
    assert all(item["state"] == "unreachable" for item in response.json()["components"])


def test_there_is_no_aggregate_boolean(client: TestClient) -> None:
    """`healthy: false` tells the user their product is broken. Five states do not."""
    with client:
        payload = client.get("/health").json()
    flattened = json.dumps(payload)
    for banned in ('"healthy"', '"ok":', '"status":'):
        assert banned not in flattened, f"{banned} collapses five component states into one"


def test_each_unhealthy_component_carries_a_reason(client: TestClient) -> None:
    with client:
        payload = client.get("/health").json()
    for item in payload["components"]:
        if item["state"] != "reachable":
            assert item["reason"], f"{item['component']} is unhealthy with no reason"


def test_health_reports_version_and_profile(client: TestClient) -> None:
    with client:
        payload = client.get("/health").json()
    assert payload["version"] == __version__
    assert payload["profile"] == "balanced"


def test_health_never_leaks_the_database_password(client: TestClient) -> None:
    """C8. The address is useful; the credential in it is not."""
    with client:
        body = client.get("/health").text
    assert "pw" not in body


def test_startup_and_shutdown_are_logged(
    settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    """When someone says it 'did not work this morning', this is the record."""
    production = settings.model_copy(update={"environment": Environment.PRODUCTION})
    with TestClient(create_app(production)):
        pass
    logged = capsys.readouterr().err

    events = [json.loads(line) for line in logged.strip().splitlines() if line.startswith("{")]
    by_name = {event["event"]: event for event in events}

    assert "startup" in by_name
    assert by_name["startup"]["components"]["database"] == "unreachable"
    assert by_name["startup"]["version"] == __version__
    assert "startup_components_unreachable" in by_name
    assert "shutdown" in by_name
    assert "pw" not in logged


def test_unhandled_error_shows_the_exception_only_in_development(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AGENTS.md §6: loud in development, a stated reason otherwise.

    The failure is forced through a real route rather than a test-only one
    added after `create_app`. Routes registered afterwards are shadowed by the
    interface catch-all, which is deliberate — but it would make this test
    exercise the 404 path while appearing to exercise the 500 path.
    """

    async def explode(_settings: Settings) -> None:
        raise RuntimeError("a detail the user should not be shown")

    # Patched after startup, not before: the lifespan probes components too,
    # and failing there would take the application down before any request —
    # a different code path from the one under test.
    development = create_app(settings)
    with TestClient(development, raise_server_exceptions=False) as client:
        monkeypatch.setattr("askwell.app.check_components", explode)
        body = client.get("/health").json()
        monkeypatch.undo()
    assert "a detail the user should not be shown" in body["exception"]

    production = create_app(settings.model_copy(update={"environment": Environment.PRODUCTION}))
    with TestClient(production, raise_server_exceptions=False) as client:
        monkeypatch.setattr("askwell.app.check_components", explode)
        body = client.get("/health").json()
        monkeypatch.undo()
    assert "exception" not in body
    assert "a detail the user should not be shown" not in json.dumps(body)
    assert body["hint"]
