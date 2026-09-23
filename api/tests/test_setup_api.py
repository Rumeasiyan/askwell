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
def test_get_model_names_the_expected_path_and_other_files_present(
    db_client: TestClient, database_url: str, tmp_path: Path
) -> None:
    """`GET /model` — the endpoint `M7-SET-FE-146`'s settings screen will
    call — states where the active model lives and lists any other
    catalog-recognised file sitting beside it, not just the one selected.
    """
    import psycopg

    with psycopg.connect(database_url, autocommit=True) as setup:
        setup.execute("TRUNCATE settings, audit_decisions CASCADE")

    with db_client as client:
        with_session(client)
        response = client.get("/model")
    assert response.status_code == 200
    body = response.json()
    assert body["expected_path"].endswith("model.gguf")
    assert body["alternatives"] == []
    # `M7-SET-FE-146`'s memory-footprint figure: the active model file's
    # real size on disk (8192 bytes, `db_client`'s wrong-profile fixture
    # file), not a rating.
    assert body["active_model_size_gb"] == pytest.approx(8192 / (1024**3))

    with psycopg.connect(database_url, autocommit=True) as clean:
        clean.execute("TRUNCATE settings, audit_decisions CASCADE")


@pytest.mark.requires_db
def test_get_model_skips_hashing_alternatives_during_an_active_transfer(
    db_client: TestClient, database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same guard `GET /setup` already applies (`docs/decisions.md`,
    `M7-OFFLINE-DEPLOY-144`): hashing every sibling model file on every poll
    during a `downloading`/`verifying` transfer costs far more than the
    answer is worth. `GET /model` had no such guard (#612) until this.
    """
    import psycopg

    from askwell.model_download import DownloadProgress, DownloadStatus

    with psycopg.connect(database_url, autocommit=True) as setup:
        setup.execute("TRUNCATE settings, audit_decisions CASCADE")

    with db_client as client:
        with_session(client)
        manager = client.app.state.model_download

        def fake_snapshot(tier: str) -> DownloadProgress:
            return DownloadProgress(
                tier=tier,
                status=DownloadStatus.DOWNLOADING,
                display_name="Test model",
                downloaded_bytes=1,
                total_bytes=2,
            )

        def fail_if_called() -> list[dict[str, object]]:
            raise AssertionError("available_alternatives must not run during a transfer")

        monkeypatch.setattr(manager, "snapshot", fake_snapshot)
        monkeypatch.setattr(manager, "available_alternatives", fail_if_called)

        response = client.get("/model")

    assert response.status_code == 200
    assert response.json()["alternatives"] == []

    with psycopg.connect(database_url, autocommit=True) as clean:
        clean.execute("TRUNCATE settings, audit_decisions CASCADE")
