"""The first-run sequence's endpoints, over HTTP. `M1-LIB-FE-052`.

Routing, the session requirement, and the parts that never touch the
database (model start/cancel/verify-manual all operate on the filesystem
only) are covered here without Postgres, the same split `test_sources_api.py`
already uses. `GET /setup`, `/setup/skip` and `/setup/passphrase` — which
read and write the `settings` table and the decision audit chain — are
covered in `test_setup_records.py` against a real database.
"""

import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from askwell import session as sessions
from askwell.app import create_app
from askwell.config import Settings
from askwell.models_catalog import CATALOG, ModelSpec


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


# --- M7-OFFLINE-DEPLOY-144: a wrong-profile file, accepted, over HTTP -------
#
# Against real Postgres: the profile adjustment this endpoint performs on a
# wrong-tier-but-valid file is a settings write and a decisions record, and
# a `client` built against the unreachable default `settings` fixture cannot
# show either landing.


@pytest.fixture
def db_client(
    settings: Settings,
    app_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> TestClient:
    async def fixed_secret(_db: object) -> bytes:
        return b"0" * 32

    monkeypatch.setattr(sessions, "secret", fixed_secret)
    monkeypatch.setattr("askwell.middleware.sessions.secret", fixed_secret)

    built = tmp_path / "out"
    built.mkdir()
    (built / "index.html").write_text("<!doctype html><title>Askwell</title>")

    light_content = b"x" * 4096
    other_content = b"y" * 8192
    light = ModelSpec(
        tier="light",
        display_name="Light test model",
        repo="test/light",
        filename="model.gguf",
        url="https://example.invalid/light",
        size_bytes=len(light_content),
        sha256=hashlib.sha256(light_content).hexdigest(),
    )
    accelerated = ModelSpec(
        tier="accelerated",
        display_name="Accelerated test model",
        repo="test/accelerated",
        filename="other.gguf",
        url="https://example.invalid/accelerated",
        size_bytes=len(other_content),
        sha256=hashlib.sha256(other_content).hexdigest(),
    )
    monkeypatch.setitem(CATALOG, "light", light)
    monkeypatch.setitem(CATALOG, "standard", light)
    monkeypatch.setitem(CATALOG, "accelerated", accelerated)
    monkeypatch.setitem(CATALOG, "workstation", accelerated)

    model_dir = tmp_path / "models"
    model_dir.mkdir()
    (model_dir / "model.gguf").write_bytes(other_content)  # the wrong-profile file

    return TestClient(
        create_app(
            settings.model_copy(
                update={
                    "database_url": SecretStr(app_database_url),
                    "web_assets_dir": built,
                    "inference_model_path": model_dir / "model.gguf",
                    "models_dir": model_dir,
                    "models_dir_display": "~/askwell-models",
                }
            )
        )
    )


@pytest.mark.requires_db
def test_verify_manual_accepts_a_wrong_profile_file_and_adjusts_the_profile(
    db_client: TestClient, database_url: str
) -> None:
    import psycopg

    with psycopg.connect(database_url, autocommit=True) as setup:
        setup.execute("TRUNCATE settings, audit_decisions CASCADE")

    with db_client as client:
        with_session(client)
        response = client.post("/setup/model/verify-manual", json={"tier": "light"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["resolved_tier"] == "accelerated"

    with psycopg.connect(database_url, autocommit=True) as check:
        profile = check.execute(
            "SELECT value FROM settings WHERE key = 'hardware.profile'"
        ).fetchone()
        assert profile is not None and profile[0] == "accelerated"

        decision = check.execute(
            "SELECT payload FROM audit_decisions WHERE kind = 'model_profile_adjusted' "
            "ORDER BY occurred_at DESC LIMIT 1"
        ).fetchone()
        assert decision is not None
        assert decision[0]["requested_tier"] == "light"
        assert decision[0]["resolved_tier"] == "accelerated"

    with psycopg.connect(database_url, autocommit=True) as clean:
        clean.execute("TRUNCATE settings, audit_decisions CASCADE")


@pytest.mark.requires_db
def test_get_model_lists_the_models_present_and_names_the_folder_on_the_users_machine(
    db_client: TestClient, database_url: str, tmp_path: Path
) -> None:
    """`GET /model` — Settings → Model and speed (`M7-SET-FE-146`). Every
    model file in the models directory is a candidate, marked validated only
    by its bytes; the folder is named as the user knows it, never `/models`;
    and with no inference process and no question asked, nothing is
    reported as measured."""
    import psycopg

    with psycopg.connect(database_url, autocommit=True) as setup:
        setup.execute("TRUNCATE settings, audit_decisions CASCADE")
    (tmp_path / "models" / "mine.gguf").write_bytes(b"GGUF" + b"\x00" * 16)

    with db_client as client:
        with_session(client)
        response = client.get("/model")
    assert response.status_code == 200
    body = response.json()
    assert body["models_dir"] == "~/askwell-models"
    candidates = {c["file"]: c for c in body["candidates"]}
    assert candidates["model.gguf"]["validated"] is True
    assert candidates["model.gguf"]["display_name"] == "Accelerated test model"
    assert candidates["mine.gguf"]["validated"] is False
    assert body["source"] == "none"
    assert body["memory_bytes"] is None
    assert body["acceleration"] is None
    assert body["throughput"]["turns"] == 0
    assert body["throughput"]["tokens_per_second"] is None
    assert "not guaranteed" in body["unverified_statement"]
    assert body["swap_timeout_seconds"] == 300

    with psycopg.connect(database_url, autocommit=True) as clean:
        clean.execute("TRUNCATE settings, audit_decisions CASCADE")


@pytest.mark.requires_db
def test_selecting_an_unverified_model_without_the_statement_is_refused(
    db_client: TestClient, database_url: str, tmp_path: Path
) -> None:
    import psycopg

    with psycopg.connect(database_url, autocommit=True) as setup:
        setup.execute("TRUNCATE settings, audit_decisions CASCADE")
    (tmp_path / "models" / "mine.gguf").write_bytes(b"GGUF" + b"\x00" * 16)

    with db_client as client:
        with_session(client)
        response = client.post("/model/select", json={"model_file": "mine.gguf"})
    assert response.status_code == 422
    assert response.json()["unverified_statement_required"] is True

    with psycopg.connect(database_url, autocommit=True) as clean:
        count = clean.execute(
            "SELECT count(*) FROM audit_decisions WHERE kind = 'model_swap_requested'"
        ).fetchone()
        assert count == (0,)
        clean.execute("TRUNCATE settings, audit_decisions CASCADE")
