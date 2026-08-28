"""The source viewer's read side, over HTTP and against a real Postgres.

`docs/backlog/M1-it-answers-from-my-documents.md` ticket `M1-VIEW-FE-046`.

What is under test: a document's bytes are actually readable from the path
`askwell.sources` recorded, in whole and by range (the mechanism pdf.js's own
loader depends on for "the cited page first, the rest streams"); a document
that is not there is reported rather than crashing; opening a document is
logged to `audit_interactions`, once, as an interaction rather than a
decision.
"""

import hashlib
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

TABLES = "roots, sources, documents, document_pages, audit_interactions, audit_decisions"


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


def test_metadata_reports_the_superseding_version_and_when(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str
) -> None:
    """`M1-VIEW-FE-048`'s own edge case: a cited document that was superseded
    still resolves, with the banner's own two facts — issue #141."""
    _truncate(database_url)
    old_id = _seed_document(database_url, tmp_path)
    new_id = uuid.uuid4()
    with psycopg.connect(database_url, autocommit=True) as db:
        source_id = db.execute(
            "SELECT source_id FROM documents WHERE id = %s", (old_id,)
        ).fetchone()[0]
        db.execute(
            "INSERT INTO documents "
            "(id, source_id, filename, path, mime, sha256, page_count, anchor_kind, "
            "status, version) "
            "VALUES (%s, %s, 'contract-v2.pdf', %s, 'application/pdf', %s, 1, 'page', "
            "'ready', 2)",
            (
                new_id,
                source_id,
                str(tmp_path / "contract-v2.pdf"),
                uuid.uuid4().hex.ljust(64, "1")[:64],
            ),
        )
        db.execute("UPDATE documents SET superseded_by = %s WHERE id = %s", (new_id, old_id))
    client = _app(settings, monkeypatch, tmp_path, database_url)

    with client:
        _with_session(client)
        response = client.get(f"/documents/{old_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["superseded_by"] == str(new_id)
    assert body["superseded_at"] is not None


def test_metadata_for_a_live_document_names_no_supersession(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str
) -> None:
    _truncate(database_url)
    document_id = _seed_document(database_url, tmp_path)
    client = _app(settings, monkeypatch, tmp_path, database_url)

    with client:
        _with_session(client)
        response = client.get(f"/documents/{document_id}")

    body = response.json()
    assert body["superseded_by"] is None
    assert body["superseded_at"] is None


def test_metadata_for_an_unknown_document_is_404(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str
) -> None:
    _truncate(database_url)
    client = _app(settings, monkeypatch, tmp_path, database_url)

    with client:
        _with_session(client)
        response = client.get(f"/documents/{uuid.uuid4()}")

    assert response.status_code == 404


def test_metadata_for_a_deleted_document_resolves_the_tombstone(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str
) -> None:
    """Issue #231: `GET /documents/{id}` must answer honestly for a
    tombstoned row rather than 404ing indistinguishably from a bad id — the
    row survives specifically so an old citation can resolve to a deletion
    date (`docs/ux/source-viewer.md` §4, `M2-DELETE-FE-062`)."""
    _truncate(database_url)
    document_id = _seed_document(database_url, tmp_path)
    with psycopg.connect(database_url, autocommit=True) as db:
        db.execute(
            "UPDATE documents SET deleted_at = now(), deleted_reason = 'client engagement ended', "
            "status = 'deleted' WHERE id = %s",
            (document_id,),
        )
    client = _app(settings, monkeypatch, tmp_path, database_url)

    with client:
        _with_session(client)
        response = client.get(f"/documents/{document_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["deleted"] is True
    assert body["deleted_at"] is not None
    assert body["deleted_reason"] == "client engagement ended"
    assert body["filename"] == "contract.pdf"


def test_the_file_route_still_404s_a_deleted_document(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str
) -> None:
    """Bytes are gone for a tombstoned document — only `document_metadata`
    resolves the tombstone; `document_file` has nothing to serve."""
    _truncate(database_url)
    document_id = _seed_document(database_url, tmp_path)
    with psycopg.connect(database_url, autocommit=True) as db:
        db.execute(
            "UPDATE documents SET deleted_at = now(), status = 'deleted' WHERE id = %s",
            (document_id,),
        )
    client = _app(settings, monkeypatch, tmp_path, database_url)

    with client:
        _with_session(client)
        response = client.get(f"/documents/{document_id}/file")

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
    assert response.json() == {
        "text": "Notice is ninety days.",
        "has_text": True,
        "anchor_label": None,
        "ocr_confidence": None,
        "low_confidence": False,
    }


def test_a_page_carries_its_anchor_label(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str
) -> None:
    """`M1-VIEW-FE-047`'s converted-text renderers anchor on a heading, a
    slide number or a spreadsheet row label — this is where that label comes
    from, distinct from the PDF page's plain ordinal."""
    _truncate(database_url)
    document_id = _seed_document(database_url, tmp_path)
    with psycopg.connect(database_url, autocommit=True) as db:
        db.execute(
            "UPDATE document_pages SET anchor_label = 'Termination' "
            "WHERE document_id = %s AND page_number = 1",
            (document_id,),
        )
    client = _app(settings, monkeypatch, tmp_path, database_url)

    with client:
        _with_session(client)
        response = client.get(f"/documents/{document_id}/pages/1")

    assert response.status_code == 200
    assert response.json()["anchor_label"] == "Termination"


def test_a_scanned_page_reports_its_ocr_confidence(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str
) -> None:
    """The OCR-text-alongside panel needs to know both the figure and whether
    it falls under `settings.ocr_confidence_threshold` — computed server-side
    so the browser never carries its own copy of the cut line."""
    _truncate(database_url)
    document_id = _seed_document(database_url, tmp_path)
    with psycopg.connect(database_url, autocommit=True) as db:
        db.execute(
            "UPDATE document_pages SET ocr_confidence = 0.42 "
            "WHERE document_id = %s AND page_number = 1",
            (document_id,),
        )
    client = _app(settings, monkeypatch, tmp_path, database_url)

    with client:
        _with_session(client)
        response = client.get(f"/documents/{document_id}/pages/1")

    body = response.json()
    assert body["ocr_confidence"] == pytest.approx(0.42)
    assert body["low_confidence"] is True


def test_a_confident_scanned_page_is_not_flagged(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str
) -> None:
    _truncate(database_url)
    document_id = _seed_document(database_url, tmp_path)
    with psycopg.connect(database_url, autocommit=True) as db:
        db.execute(
            "UPDATE document_pages SET ocr_confidence = 0.95 "
            "WHERE document_id = %s AND page_number = 1",
            (document_id,),
        )
    client = _app(settings, monkeypatch, tmp_path, database_url)

    with client:
        _with_session(client)
        response = client.get(f"/documents/{document_id}/pages/1")

    assert response.json()["low_confidence"] is False


def test_every_page_is_listed_in_order(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str
) -> None:
    """The spreadsheet renderer's own data source — a row highlighted in
    isolation is not a table, so the viewer fetches every row once."""
    _truncate(database_url)
    document_id = _seed_document(database_url, tmp_path)
    with psycopg.connect(database_url, autocommit=True) as db:
        db.execute(
            "INSERT INTO document_pages (document_id, page_number, text, has_text, anchor_label) "
            "VALUES (%s, 2, 'Sheet1, row 2 | a | b', true, 'Sheet1, row 2')",
            (document_id,),
        )
    client = _app(settings, monkeypatch, tmp_path, database_url)

    with client:
        _with_session(client)
        response = client.get(f"/documents/{document_id}/pages")

    assert response.status_code == 200
    body = response.json()
    assert [row["page_number"] for row in body] == [1, 2]
    assert body[1]["anchor_label"] == "Sheet1, row 2"


def _seed_rooted_document(
    database_url: str,
    tmp_path: Path,
    *,
    write_file: bool = True,
    content: str = "Notice is ninety days.",
) -> tuple[uuid.UUID, uuid.UUID, Path, str]:
    """A document under a nominated root — needed for anything that must
    tell a genuinely missing file apart from a root Askwell cannot reach.
    Returns the document id, source id, its path and its real sha256 (unlike
    `_seed_document`'s placeholder hash, which relocation's hash check would
    never match)."""
    document_id, source_id = uuid.uuid4(), uuid.uuid4()
    pdf_path = tmp_path / "contract.pdf"
    body = _pdf(content)
    sha256 = hashlib.sha256(body).hexdigest()
    if write_file:
        pdf_path.write_bytes(body)

    with psycopg.connect(database_url, autocommit=True) as db:
        db.execute("INSERT INTO roots (path) VALUES (%s)", (str(tmp_path),))
        db.execute(
            "INSERT INTO sources (id, kind, name, root_path) VALUES (%s, 'file', 'a source', %s)",
            (source_id, str(tmp_path)),
        )
        db.execute(
            "INSERT INTO documents "
            "(id, source_id, filename, path, mime, sha256, page_count, anchor_kind, status) "
            "VALUES (%s, %s, 'contract.pdf', %s, 'application/pdf', %s, 1, 'page', 'ready')",
            (document_id, source_id, str(pdf_path), sha256),
        )
    return document_id, source_id, pdf_path, sha256


def _rooted(settings: Settings, tmp_path: Path) -> Settings:
    """Configuration whose mount window actually contains `tmp_path`, so
    `roots.probe` reports the nominated root as available rather than
    `not_mounted`."""
    return settings.model_copy(update={"roots_mount": tmp_path})


def test_metadata_names_the_moved_file_and_offers_relocation(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str
) -> None:
    """The ticket's own acceptance criterion: a renamed file is reported as
    moved, not deleted, with the old path and a relocate offer — never
    conflated with the root itself being unreachable."""
    _truncate(database_url)
    document_id, _source_id, pdf_path, _sha256 = _seed_rooted_document(
        database_url, tmp_path, write_file=False
    )
    client = _app(_rooted(settings, tmp_path), monkeypatch, tmp_path, database_url)

    with client:
        _with_session(client)
        response = client.get(f"/documents/{document_id}")

    body = response.json()
    assert body["available"] is False
    assert body["moved"] is True
    assert body["root_unavailable"] is False
    assert body["missing_since"] is not None
    assert body["path"] == str(pdf_path)

    with psycopg.connect(database_url, autocommit=True) as db:
        row = db.execute(
            "SELECT missing_since, deleted_at FROM documents WHERE id = %s", (document_id,)
        ).fetchone()
    assert row[0] is not None
    assert row[1] is None


def test_the_missing_state_clears_when_the_file_reappears(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str
) -> None:
    """Edge case: a file that returns to its original path on its own clears
    on the next open, with no relocation needed."""
    _truncate(database_url)
    document_id, _source_id, pdf_path, _sha256 = _seed_rooted_document(
        database_url, tmp_path, write_file=False
    )
    client = _app(_rooted(settings, tmp_path), monkeypatch, tmp_path, database_url)

    with client:
        _with_session(client)
        first = client.get(f"/documents/{document_id}")
        assert first.json()["moved"] is True

        pdf_path.write_bytes(_pdf("Notice is ninety days."))
        second = client.get(f"/documents/{document_id}")

    body = second.json()
    assert body["available"] is True
    assert body["moved"] is False
    assert body["missing_since"] is None

    with psycopg.connect(database_url, autocommit=True) as db:
        row = db.execute(
            "SELECT missing_since FROM documents WHERE id = %s", (document_id,)
        ).fetchone()
    assert row[0] is None


def test_an_unmounted_root_is_reported_as_root_unavailable_not_missing(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str
) -> None:
    """Edge case: the whole root is unmounted — reported as the root being
    unavailable, not as the document being individually missing, and
    `missing_since` is never set for it."""
    _truncate(database_url)
    document_id, _source_id, _pdf_path, _sha256 = _seed_rooted_document(
        database_url, tmp_path, write_file=False
    )
    # `settings` on its own has no `roots_mount`, so `roots.probe` reports
    # `not_mounted` for the nominated root regardless of what is on disk.
    client = _app(settings, monkeypatch, tmp_path, database_url)

    with client:
        _with_session(client)
        response = client.get(f"/documents/{document_id}")

    body = response.json()
    assert body["available"] is False
    assert body["moved"] is False
    assert body["root_unavailable"] is True
    assert body["missing_since"] is None

    with psycopg.connect(database_url, autocommit=True) as db:
        row = db.execute(
            "SELECT missing_since FROM documents WHERE id = %s", (document_id,)
        ).fetchone()
    assert row[0] is None


def test_relocating_to_the_renamed_file_verifies_the_hash_and_restores_viewing(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str
) -> None:
    _truncate(database_url)
    document_id, _source_id, old_path, _sha256 = _seed_rooted_document(
        database_url, tmp_path, write_file=False
    )
    new_path = tmp_path / "renamed.pdf"
    new_path.write_bytes(_pdf("Notice is ninety days."))
    client = _app(_rooted(settings, tmp_path), monkeypatch, tmp_path, database_url)

    with client:
        _with_session(client)
        client.get(f"/documents/{document_id}")  # marks it missing first, as a real open would
        response = client.post(f"/documents/{document_id}/relocate", json={"path": str(new_path)})

    assert response.status_code == 200
    assert response.json()["path"] == str(new_path)

    with psycopg.connect(database_url, autocommit=True) as db:
        row = db.execute(
            "SELECT path, missing_since FROM documents WHERE id = %s", (document_id,)
        ).fetchone()
        decisions = db.execute(
            "SELECT payload FROM audit_decisions WHERE kind = 'document_relocated'"
        ).fetchall()
    assert row[0] == str(new_path)
    assert row[1] is None
    assert len(decisions) == 1
    assert decisions[0][0]["from_path"] == str(old_path)
    assert decisions[0][0]["to_path"] == str(new_path)
    assert decisions[0][0]["document_id"] == str(document_id)


def test_relocating_to_a_different_file_is_refused_on_hash_mismatch(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str
) -> None:
    _truncate(database_url)
    document_id, _source_id, _old_path, _sha256 = _seed_rooted_document(
        database_url, tmp_path, write_file=False
    )
    different_path = tmp_path / "different.pdf"
    different_path.write_bytes(_pdf("A completely different notice."))
    client = _app(_rooted(settings, tmp_path), monkeypatch, tmp_path, database_url)

    with client:
        _with_session(client)
        response = client.post(
            f"/documents/{document_id}/relocate", json={"path": str(different_path)}
        )

    assert response.status_code == 409
    body = response.json()
    assert body["reason"] == "hash_mismatch"
    assert "does not match" in body["error"]

    with psycopg.connect(database_url, autocommit=True) as db:
        row = db.execute("SELECT path FROM documents WHERE id = %s", (document_id,)).fetchone()
    assert row[0] != str(different_path)


def test_relocating_to_a_path_outside_every_root_is_refused(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str
) -> None:
    _truncate(database_url)
    document_id, _source_id, _old_path, _sha256 = _seed_rooted_document(
        database_url, tmp_path, write_file=False
    )
    outside = tmp_path.parent / f"unregistered-{uuid.uuid4().hex}" / "contract.pdf"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_bytes(_pdf("Notice is ninety days."))
    client = _app(_rooted(settings, tmp_path), monkeypatch, tmp_path, database_url)

    with client:
        _with_session(client)
        response = client.post(f"/documents/{document_id}/relocate", json={"path": str(outside)})

    assert response.status_code == 400


def test_relocating_a_document_that_is_not_missing_is_refused(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str
) -> None:
    _truncate(database_url)
    document_id, _source_id, pdf_path, _sha256 = _seed_rooted_document(database_url, tmp_path)
    client = _app(_rooted(settings, tmp_path), monkeypatch, tmp_path, database_url)

    with client:
        _with_session(client)
        response = client.post(f"/documents/{document_id}/relocate", json={"path": str(pdf_path)})

    assert response.status_code == 400


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
