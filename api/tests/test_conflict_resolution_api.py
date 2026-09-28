"""Resolving a conflict over HTTP. `M9-FIX-FE-204`.

What gets written is covered in `test_conflict_resolution.py` against a real
database. This is routing, the session requirement and the shape of a
refusal. Same fixture shape as `test_memory_api.py`.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from askwell import session as sessions
from askwell.app import create_app
from askwell.config import Settings

_UUID = "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def client(settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
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


def test_resolving_a_conflict_requires_a_session(client: TestClient) -> None:
    with client:
        response = client.post(f"/ask/{_UUID}/resolve-conflict", json={"document_id": _UUID})
    assert response.status_code == 401


def test_resolving_a_conflict_needs_a_document_id(client: TestClient) -> None:
    with client:
        with_session(client)
        response = client.post(f"/ask/{_UUID}/resolve-conflict", json={})
    assert response.status_code == 422
