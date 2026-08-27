"""The add-a-source endpoint, over HTTP.

What the record path decides is covered against a real database. What is
asserted here is what a caller actually receives — routing, the session
requirement, and the shape of a refusal — which is the part a unit test cannot
see and the part the interface meets first.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

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
    """This one reads the user's own files. `/health` is the only exemption."""
    with client:
        response = client.post("/sources", json={"folder": "/tmp", "files": ["a.pdf"]})
    assert response.status_code == 401


def test_a_relative_folder_is_refused_with_a_reason_not_a_schema_error(
    client: TestClient,
) -> None:
    """400 rather than 422.

    A validation error tells the caller their JSON was the wrong shape. It was
    not: the shape is right and the value cannot work, and saying so is the
    difference between a message a person can act on and one they cannot.
    """
    with client:
        with_session(client)
        response = client.post("/sources", json={"folder": "documents", "files": ["a.pdf"]})

    assert response.status_code == 400
    body = response.json()
    assert "slash" in body["error"].lower() or "whole path" in body["error"].lower()
    assert body["folder"] == "documents"


def test_a_batch_with_no_files_is_refused(client: TestClient) -> None:
    with client:
        with_session(client)
        response = client.post("/sources", json={"folder": "/tmp/x", "files": []})
    assert response.status_code in (400, 422)


def test_a_batch_larger_than_the_cap_is_refused_by_the_endpoint(client: TestClient) -> None:
    """The browser caps a drop at the same number. That is not this endpoint's cap.

    The cap belongs here as well because this is the boundary, and a limit
    enforced only in the client is a limit that vanishes the moment anything
    else calls the API.
    """
    with client:
        with_session(client)
        response = client.post(
            "/sources", json={"folder": "/tmp/x", "files": [f"{n}.pdf" for n in range(5001)]}
        )
    assert response.status_code in (400, 422)


def test_the_endpoint_takes_paths_and_never_bytes(client: TestClient) -> None:
    """Askwell indexes in place. This must never become an upload.

    A multipart body is what an upload looks like, and the schema is what stops
    one being accepted by accident — so the refusal is the assertion.
    """
    with client:
        with_session(client)
        response = client.post(
            "/sources",
            files={"file": ("contract.pdf", b"%PDF-1.7\n", "application/pdf")},
        )
    assert response.status_code == 422


# --- the endpoint against a real database -----------------------------------
#
# Everything above runs without one, which is what makes it fast and what makes
# it blind to the single most important property this endpoint has: that the
# rows it creates are still there after the request ends. `session_scope`
# commits on success, and nothing asserted that. A regression turning the commit
# into a rollback would leave every test above passing and the product silently
# recording nothing — the user drops sixty contracts, sees "added", and has an
# empty library.


@pytest.mark.requires_db
def test_a_successful_add_is_committed_and_survives_the_request(
    settings: Settings,
    app_database_url: str,
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The row is read back on a different connection, after the request closed.

    A separate connection is the whole point. Querying the request's own session
    would see its uncommitted work and pass whether or not it ever committed.
    """
    import psycopg

    folder = tmp_path / "clients"
    folder.mkdir()
    (folder / "contract.pdf").write_bytes(
        b"%PDF-1.7\nEither party may terminate on ninety days written notice.\n"
    )

    with psycopg.connect(database_url, autocommit=True) as setup:
        setup.execute("TRUNCATE roots, sources, documents, audit_decisions CASCADE")
        setup.execute("INSERT INTO roots (path) VALUES (%s)", (str(tmp_path),))

    async def fixed_secret(_db: object) -> bytes:
        return b"0" * 32

    monkeypatch.setattr(sessions, "secret", fixed_secret)
    monkeypatch.setattr("askwell.middleware.sessions.secret", fixed_secret)

    built = tmp_path / "out"
    built.mkdir()
    (built / "index.html").write_text("<!doctype html><title>Askwell</title>")
    live = create_app(
        settings.model_copy(
            update={
                "database_url": SecretStr(app_database_url),
                "web_assets_dir": built,
            }
        )
    )

    with TestClient(live) as client:
        with_session(client)
        response = client.post("/sources", json={"folder": str(folder), "files": ["contract.pdf"]})

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["added"] == 1
    assert body["files"][0]["outcome"] == "added"

    # The request is over and its session is closed. If the commit is ever lost,
    # this is the line that fails.
    with psycopg.connect(database_url, autocommit=True) as check:
        rows = check.execute("SELECT filename, path, sha256 FROM documents").fetchall()
    assert len(rows) == 1, "the endpoint answered 201 but committed nothing"
    assert rows[0][0] == "contract.pdf"
    assert rows[0][1] == str(folder / "contract.pdf")

    with psycopg.connect(database_url, autocommit=True) as check:
        kinds = check.execute("SELECT kind FROM audit_decisions ORDER BY occurred_at").fetchall()
    assert [row[0] for row in kinds] == ["source_added", "document_added"]

    with psycopg.connect(database_url, autocommit=True) as clean:
        clean.execute("TRUNCATE roots, sources, documents, audit_decisions CASCADE")
