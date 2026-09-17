"""The clarifications endpoints, over HTTP. `M3-REVIEW-BE-072a`.

What the business logic decides is covered in `test_review.py` against a
real database. This is routing, the session requirement, and the shape of a
refusal — the part a unit test cannot see.
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
    return TestClient(create_app(settings.model_copy(update={"web_assets_dir": built})))


def with_session(client: TestClient) -> None:
    client.get("/", headers={"accept": "text/html"})


def test_listing_requires_a_session(client: TestClient) -> None:
    with client:
        response = client.get("/clarifications")
    assert response.status_code == 401


def test_answering_requires_a_session(client: TestClient) -> None:
    with client:
        response = client.post(
            "/clarifications/11111111-1111-1111-1111-111111111111/answer",
            json={"answer": "x"},
        )
    assert response.status_code == 401


def test_skipping_requires_a_session(client: TestClient) -> None:
    with client:
        response = client.post("/clarifications/11111111-1111-1111-1111-111111111111/skip")
    assert response.status_code == 401


def test_an_unrecognised_id_is_rejected_as_not_a_uuid(client: TestClient) -> None:
    with client:
        with_session(client)
        response = client.post("/clarifications/not-a-uuid/skip")
    assert response.status_code == 422


def test_an_empty_answer_is_rejected(client: TestClient) -> None:
    with client:
        with_session(client)
        response = client.post(
            "/clarifications/11111111-1111-1111-1111-111111111111/answer",
            json={"answer": ""},
        )
    assert response.status_code == 422
