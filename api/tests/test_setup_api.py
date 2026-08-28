"""The first-run sequence's endpoints, over HTTP. `M1-LIB-FE-052`.

Routing, the session requirement, and the parts that never touch the
database (model start/cancel/verify-manual all operate on the filesystem
only) are covered here without Postgres, the same split `test_sources_api.py`
already uses. `GET /setup`, `/setup/skip` and `/setup/passphrase` — which
read and write the `settings` table and the decision audit chain — are
covered in `test_setup_records.py` against a real database.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from askwell import session as sessions
from askwell.app import create_app
from askwell.config import Settings


@pytest.fixture
def client(settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    async def fixed_secret(_db: object) -> bytes:
        return b"0" * 32

    monkeypatch.setattr(sessions, "secret", fixed_secret)
    monkeypatch.setattr("askwell.middleware.sessions.secret", fixed_secret)

    built = tmp_path / "out"
    built.mkdir()
    (built / "index.html").write_text("<!doctype html><title>Askwell</title>")
    model_dir = tmp_path / "models"
    return TestClient(
        create_app(
            settings.model_copy(
                update={
                    "web_assets_dir": built,
                    "inference_model_path": model_dir / "model.gguf",
                }
            )
        )
    )


def with_session(client: TestClient) -> None:
    client.get("/", headers={"accept": "text/html"})


def test_starting_a_model_download_requires_a_session(client: TestClient) -> None:
    with client:
        response = client.post("/setup/model/start", json={"tier": "light"})
    assert response.status_code == 401


def test_verify_manual_with_no_file_names_the_expected_filename(client: TestClient) -> None:
    with client:
        with_session(client)
        response = client.post("/setup/model/verify-manual", json={"tier": "light"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "idle"
    assert "gguf" in (body["error"] or "")


def test_cancel_with_nothing_running_is_a_no_op(client: TestClient) -> None:
    with client:
        with_session(client)
        response = client.post("/setup/model/cancel", json={"tier": "light"})
    assert response.status_code == 200
    assert response.json()["status"] == "idle"


def test_start_refuses_when_disk_is_full(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "askwell.model_download.disk_usage",
        lambda _path: type("Usage", (), {"free": 1})(),
    )
    with client:
        with_session(client)
        response = client.post("/setup/model/start", json={"tier": "light"})
    assert response.status_code == 409
    body = response.json()
    assert body["needed_bytes"] > 0
    assert "free_bytes" in body
