"""The roots endpoints, over HTTP.

The unit tests cover what the module decides. These cover what a caller
actually receives — which is a different thing, and the audit of
`M1-ADD-ING-021` found it missing for all five routes.

Two of them are here because the code warns about them itself and nothing
checked the warning held.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from askwell import session as sessions
from askwell.app import create_app
from askwell.config import Settings


@pytest.fixture
def client(settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    """A real application, with the session secret stubbed and no database.

    The routes that need a database are exercised in the database-backed
    module; what is asserted here is routing, refusal and shape, which are the
    parts a caller meets first and the parts a unit test cannot see.
    """

    async def fixed_secret(_db: object) -> bytes:
        return b"0" * 32

    monkeypatch.setattr(sessions, "secret", fixed_secret)
    monkeypatch.setattr("askwell.middleware.sessions.secret", fixed_secret)

    built = tmp_path / "out"
    built.mkdir()
    (built / "index.html").write_text("<!doctype html><title>Askwell</title>")
    return TestClient(create_app(settings.model_copy(update={"web_assets_dir": built})))


def with_session(client: TestClient) -> None:
    client.get("/", headers={"accept": "text/html"})


def test_the_literal_route_wins_over_the_parameterised_one(client: TestClient) -> None:
    """`/roots/covering` must not be read as a root whose id is "covering".

    FastAPI matches in declaration order, so this holds only while
    `/roots/covering` is declared before `/roots/{root_id}`. Reordering them
    turns a working endpoint into a 422 about a malformed UUID, which names
    neither the cause nor the fix — and nothing but this test would notice.
    """
    # Server exceptions are not re-raised here: this fixture has no database,
    # so reaching the handler at all is the thing being asserted. A 500 from
    # the database means routing worked; a 422 means it did not.
    client = TestClient(client.app, raise_server_exceptions=False)
    with client:
        with_session(client)
        response = client.get("/roots/covering", params={"path": "/tmp"})

    assert response.status_code != 422, (
        "/roots/covering was matched as /roots/{root_id} — the literal route must be declared first"
    )


def test_a_malformed_root_id_is_refused_readably(client: TestClient) -> None:
    with client:
        with_session(client)
        response = client.delete("/roots/not-a-uuid")
    assert response.status_code in (400, 404, 422)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/roots"),
        ("post", "/roots"),
        ("get", "/roots/covering"),
    ],
)
def test_every_root_endpoint_requires_a_session(client: TestClient, method: str, path: str) -> None:
    """These list and change what Askwell may read.

    `/health` is the one exemption in the whole application, and this is a
    surface describing the user's own filesystem — the opposite of the case
    that earned the exemption.
    """
    with client:
        response = getattr(client, method)(path)
    assert response.status_code == 401


def test_a_relative_path_is_refused_with_a_reason_not_a_schema_error(
    client: TestClient,
) -> None:
    """400 rather than 422, deliberately.

    A validation error tells the caller their JSON was the wrong shape. It was
    not: the shape is right and the value cannot work, and saying so is the
    difference between a message a person can act on and one they cannot.
    """
    with client:
        with_session(client)
        response = client.post("/roots", json={"path": "documents"})

    assert response.status_code == 400
    body = json.dumps(response.json()).lower()
    assert "slash" in body or "whole path" in body


def test_nominating_the_whole_disk_is_refused(client: TestClient) -> None:
    """`/` would grant everything, which is what nominating a folder avoids."""
    with client:
        with_session(client)
        response = client.post("/roots", json={"path": "/"})
    assert response.status_code == 400


def test_covering_needs_a_path_to_check(client: TestClient) -> None:
    with client:
        with_session(client)
        response = client.get("/roots/covering")
    assert response.status_code in (400, 422)
