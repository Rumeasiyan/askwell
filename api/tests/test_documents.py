"""The source viewer's read side, over HTTP and against a real Postgres.

`docs/backlog/M1-it-answers-from-my-documents.md` ticket `M1-VIEW-FE-046`.

What is under test: a document's bytes are actually readable from the path
`askwell.sources` recorded, in whole and by range (the mechanism pdf.js's own
loader depends on for "the cited page first, the rest streams"); a document
that is not there is reported rather than crashing; opening a document is
logged to `audit_interactions`, once, as an interaction rather than a
decision.
"""

import uuid
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from askwell import session as sessions
from askwell.app import create_app
from askwell.config import Settings

pytestmark = pytest.mark.requires_db

TABLES = "roots, sources, documents, document_pages, audit_interactions"


def _pdf(text: str) -> bytes:
    """A one-page PDF pdfium (and, in the browser, pdf.js) can actually open —
    the same minimal single-object-stream construction `test_ingest_records.py`'s
    `_pdf` uses, trimmed to the one page this suite needs."""
    content = f"BT /F1 12 Tf 72 700 Td ({text}) Tj ET".encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 4 0 R >> >> "
        b"/MediaBox [0 0 612 792] /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
    ]
    body = bytearray(b"%PDF-1.7\n")
    offsets = []
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(body))
        body += f"{number} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_offset = len(body)
    body += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        body += f"{offset:010d} 00000 n \n".encode()
    body += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n".encode()
    body += f"startxref\n{xref_offset}\n%%EOF".encode()
    return bytes(body)


def _truncate(database_url: str) -> None:
    with psycopg.connect(database_url, autocommit=True) as db:
        db.execute(f"TRUNCATE {TABLES} CASCADE")


def _seed_document(database_url: str, tmp_path: Path, *, write_file: bool = True) -> uuid.UUID:
    document_id, source_id = uuid.uuid4(), uuid.uuid4()
    pdf_path = tmp_path / "contract.pdf"
    if write_file:
        pdf_path.write_bytes(_pdf("Notice is ninety days."))

    with psycopg.connect(database_url, autocommit=True) as db:
        db.execute(
            "INSERT INTO sources (id, kind, name) VALUES (%s, 'file', 'a source')",
            (source_id,),
        )
        db.execute(
            "INSERT INTO documents "
            "(id, source_id, filename, path, mime, sha256, page_count, anchor_kind, status) "
            "VALUES (%s, %s, 'contract.pdf', %s, 'application/pdf', %s, 1, 'page', 'ready')",
            (document_id, source_id, str(pdf_path), uuid.uuid4().hex.ljust(64, "0")[:64]),
        )
        db.execute(
            "INSERT INTO document_pages (document_id, page_number, text, has_text) "
            "VALUES (%s, 1, 'Notice is ninety days.', true)",
            (document_id,),
        )
    return document_id


def _app(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str
) -> TestClient:
    async def fixed_secret(_db: object) -> bytes:
        return b"0" * 32

    monkeypatch.setattr(sessions, "secret", fixed_secret)
    monkeypatch.setattr("askwell.middleware.sessions.secret", fixed_secret)

    built = tmp_path / "out"
    built.mkdir(exist_ok=True)
    (built / "index.html").write_text("<!doctype html><title>Askwell</title>")
    return TestClient(
        create_app(
            settings.model_copy(
                update={"database_url": SecretStr(database_url), "web_assets_dir": built}
            )
        )
    )


def _with_session(client: TestClient) -> None:
    client.get("/", headers={"accept": "text/html"})


def test_metadata_reports_an_available_pdf(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str
) -> None:
    _truncate(database_url)
    document_id = _seed_document(database_url, tmp_path)
    client = _app(settings, monkeypatch, tmp_path, database_url)

    with client:
        _with_session(client)
        response = client.get(f"/documents/{document_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["filename"] == "contract.pdf"
    assert body["mime"] == "application/pdf"
    assert body["page_count"] == 1
    assert body["available"] is True


def test_metadata_for_an_unknown_document_is_404(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str
) -> None:
    _truncate(database_url)
    client = _app(settings, monkeypatch, tmp_path, database_url)

    with client:
        _with_session(client)
        response = client.get(f"/documents/{uuid.uuid4()}")

    assert response.status_code == 404


def test_metadata_reports_a_document_whose_file_is_gone(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str
) -> None:
    """`M1-VIEW-BE-049` owns the moved/deleted distinction — this only has to
    not crash and not claim a missing file is there."""
    _truncate(database_url)
    document_id = _seed_document(database_url, tmp_path, write_file=False)
    client = _app(settings, monkeypatch, tmp_path, database_url)

    with client:
        _with_session(client)
        response = client.get(f"/documents/{document_id}")

    assert response.status_code == 200
    assert response.json()["available"] is False


def test_opening_a_document_is_recorded_as_an_interaction(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str
) -> None:
    _truncate(database_url)
    document_id = _seed_document(database_url, tmp_path)
    client = _app(settings, monkeypatch, tmp_path, database_url)

    with client:
        _with_session(client)
        client.get(f"/documents/{document_id}")

    with psycopg.connect(database_url, autocommit=True) as db:
        rows = db.execute(
            "SELECT kind, payload FROM audit_interactions WHERE kind = 'document_opened'"
        ).fetchall()

    assert len(rows) == 1
    assert rows[0][1]["document_id"] == str(document_id)


def test_the_full_file_is_readable(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str
) -> None:
    _truncate(database_url)
    document_id = _seed_document(database_url, tmp_path)
    client = _app(settings, monkeypatch, tmp_path, database_url)

    with client:
        _with_session(client)
        response = client.get(f"/documents/{document_id}/file")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers.get("accept-ranges") == "bytes"
    assert response.content.startswith(b"%PDF-1.7")


def test_a_range_request_gets_a_partial_response(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str
) -> None:
    """This is the mechanism `document-viewer.tsx`'s note describes: pdf.js's
    own loader issues `Range` requests so the cited page's bytes arrive first
    on a large document. `206` here is what makes that true rather than
    asserted."""
    _truncate(database_url)
    document_id = _seed_document(database_url, tmp_path)
    client = _app(settings, monkeypatch, tmp_path, database_url)

    with client:
        _with_session(client)
        response = client.get(f"/documents/{document_id}/file", headers={"range": "bytes=0-4"})

    assert response.status_code == 206
    assert response.content == b"%PDF-"


def test_the_file_route_reports_a_missing_file_rather_than_crashing(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str
) -> None:
    _truncate(database_url)
    document_id = _seed_document(database_url, tmp_path, write_file=False)
    client = _app(settings, monkeypatch, tmp_path, database_url)

    with client:
        _with_session(client)
        response = client.get(f"/documents/{document_id}/file")

    assert response.status_code == 404


def test_a_page_s_extracted_text_is_readable(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str
) -> None:
    """The unrenderable-PDF fallback's own data source."""
    _truncate(database_url)
    document_id = _seed_document(database_url, tmp_path)
    client = _app(settings, monkeypatch, tmp_path, database_url)

    with client:
        _with_session(client)
        response = client.get(f"/documents/{document_id}/pages/1")

    assert response.status_code == 200
    assert response.json() == {"text": "Notice is ninety days.", "has_text": True}


def test_documents_require_a_session(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str
) -> None:
    """It describes the user's own files, so it is behind the same door every
    other data route (`askwell.middleware`) already is."""
    _truncate(database_url)
    document_id = _seed_document(database_url, tmp_path)
    client = _app(settings, monkeypatch, tmp_path, database_url)

    with client:
        assert client.get(f"/documents/{document_id}").status_code == 401
        assert client.get(f"/documents/{document_id}/file").status_code == 401
