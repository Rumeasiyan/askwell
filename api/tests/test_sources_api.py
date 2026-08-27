"""The sources endpoint, over HTTP.

The registry tests cover what the module decides. These cover what a caller
actually receives — routing, refusal and shape — which is a different thing and
is the part a caller meets first.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from askwell import session as sessions
from askwell.app import create_app
from askwell.config import Settings


@pytest.fixture
def client(settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    """A real application, with the session secret stubbed and no database."""

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


def test_adding_requires_a_session(client: TestClient) -> None:
    """This reads the user's own filesystem. `/health` is the one exemption."""
    with client:
        response = client.post("/sources", json={"root_path": "/tmp", "files": []})
    assert response.status_code == 401


def test_a_relative_folder_is_refused_with_a_reason_not_a_schema_error(
    client: TestClient,
) -> None:
    """400 rather than 422.

    A validation error tells the caller their JSON was the wrong shape. It was
    not: the path is a well-formed string and the request is exactly what the
    interface meant to send. What is wrong is the folder, and the message is
    the whole answer.
    """
    with client:
        with_session(client)
        response = client.post(
            "/sources", json={"root_path": "relative/folder", "files": [{"path": "/tmp/a.pdf"}]}
        )

    assert response.status_code == 400
    assert "whole path" in response.json()["error"]


def test_the_whole_disk_is_refused(client: TestClient) -> None:
    with client:
        with_session(client)
        response = client.post(
            "/sources", json={"root_path": "/", "files": [{"path": "/a.pdf"}]}
        )

    assert response.status_code == 400
    assert "whole disk" in response.json()["error"]


def test_a_drop_with_no_files_is_a_schema_error(client: TestClient) -> None:
    """Here 422 *is* right: the request itself is malformed.

    Nothing about the user's folders explains an empty list — the interface
    sent a request it should not have built.
    """
    with client:
        with_session(client)
        response = client.post("/sources", json={"root_path": "/tmp", "files": []})
    assert response.status_code == 422
