"""The memory chip's endpoints, over HTTP. `M3-CORRECT-FE-081`.

What the business logic decides (`correct_fact`/`delete_fact`/`get_fact_detail`)
is covered in `test_memory.py` against a real database. This is routing, the
session requirement, and the shape of a refusal — the part a unit test
cannot see. Same fixture shape as `test_review_api.py`, the same ticket
shape's own precedent (`M3-REVIEW-BE-072a`) for a data-layer module with no
HTTP surface yet.
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


def test_reading_the_memory_screen_requires_a_session(client: TestClient) -> None:
    with client:
        response = client.get("/memory")
    assert response.status_code == 401


def test_reading_a_fact_requires_a_session(client: TestClient) -> None:
    with client:
        response = client.get(f"/memory/facts/memory/{_UUID}")
    assert response.status_code == 401


def test_correcting_requires_a_session(client: TestClient) -> None:
    with client:
        response = client.post(f"/memory/facts/memory/{_UUID}/correct", json={"value": "x"})
    assert response.status_code == 401


def test_deleting_requires_a_session(client: TestClient) -> None:
    with client:
        response = client.post(f"/memory/facts/memory/{_UUID}/delete")
    assert response.status_code == 401


def test_an_unrecognised_id_is_rejected_as_not_a_uuid(client: TestClient) -> None:
    with client:
        with_session(client)
        response = client.get("/memory/facts/memory/not-a-uuid")
    assert response.status_code == 422


def test_an_unknown_fact_kind_is_a_404_not_a_500(client: TestClient) -> None:
    with client:
        with_session(client)
        response = client.get(f"/memory/facts/table/{_UUID}")
    assert response.status_code == 404


def test_correcting_with_an_unknown_fact_kind_is_a_404(client: TestClient) -> None:
    with client:
        with_session(client)
        response = client.post(f"/memory/facts/table/{_UUID}/correct", json={"value": "x"})
    assert response.status_code == 404


def test_an_empty_correction_value_is_rejected(client: TestClient) -> None:
    with client:
        with_session(client)
        response = client.post(f"/memory/facts/memory/{_UUID}/correct", json={"value": ""})
    assert response.status_code == 422


def test_confirming_requires_a_session(client: TestClient) -> None:
    with client:
        response = client.post(f"/memory/facts/memory/{_UUID}/confirm")
    assert response.status_code == 401


def test_confirming_with_an_unknown_fact_kind_is_a_404(client: TestClient) -> None:
    with client:
        with_session(client)
        response = client.post(f"/memory/facts/table/{_UUID}/confirm")
    assert response.status_code == 404


def test_adding_a_manual_fact_requires_a_session(client: TestClient) -> None:
    with client:
        response = client.post(
            "/memory/facts", json={"subject": "rfq", "fact": "Request for Quotation"}
        )
    assert response.status_code == 401


def test_an_empty_manual_subject_is_rejected(client: TestClient) -> None:
    with client:
        with_session(client)
        response = client.post("/memory/facts", json={"subject": "", "fact": "x"})
    assert response.status_code == 422


def test_deleting_all_memory_requires_a_session(client: TestClient) -> None:
    with client:
        response = client.post("/memory/delete-all", json={"expected_count": 0})
    assert response.status_code == 401


def test_a_negative_expected_count_is_rejected(client: TestClient) -> None:
    with client:
        with_session(client)
        response = client.post("/memory/delete-all", json={"expected_count": -1})
    assert response.status_code == 422
