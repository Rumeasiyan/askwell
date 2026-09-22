"""`POST /ask/{message_id}/escalate/web` and `GET /settings/web-search`, over
HTTP and against a real Postgres. `M6.5-WEB-FE-186`.

The offer itself is a frontend concern; what belongs here is the boundary
issue #532 named before this endpoint existed: whether a direct `POST`
against a turn that never abstained or answered partially is refused by the
server, not merely undrawn by the UI. `escalate_web_search` itself
(`M6.5-WEB-BE-185`) is already covered end to end in `test_websearch.py` —
this module only proves the HTTP route wires to it correctly and enforces
the one check that is new here.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

from askwell.config import Settings

from .test_ask_api import _app, _truncate, _with_session
from .test_websearch import _GrantCalls, grant_calls  # noqa: F401 — fixture, used implicitly

pytestmark = pytest.mark.requires_db


def _seed_conversation(database_url: str) -> uuid.UUID:
    conversation_id = uuid.uuid4()
    with psycopg.connect(database_url, autocommit=True) as db:
        db.execute("INSERT INTO conversations (id) VALUES (%s)", (conversation_id,))
    return conversation_id


def _seed_message(
    database_url: str,
    conversation_id: uuid.UUID,
    *,
    content: str,
    trace: dict[str, object] | None,
) -> uuid.UUID:
    message_id = uuid.uuid4()
    trace_json = json.dumps(trace) if trace is not None else None
    with psycopg.connect(database_url, autocommit=True) as db:
        db.execute(
            "INSERT INTO messages (id, conversation_id, role, content, trace) "
            "VALUES (%s, %s, 'assistant', %s, %s)",
            (message_id, conversation_id, content, trace_json),
        )
    return message_id


def _fixture_client(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str
) -> TestClient:
    client = _app(
        settings.model_copy(update={"web_search_provider": "fixture"}),
        monkeypatch,
        tmp_path,
        database_url,
    )
    _with_session(client)
    return client


def test_escalating_an_unknown_message_id_is_404(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str
) -> None:
    _truncate(database_url)
    client = _fixture_client(settings, monkeypatch, tmp_path, database_url)
    response = client.post(f"/ask/{uuid.uuid4()}/escalate/web", json={"question": "q"})
    assert response.status_code == 404


def test_escalating_a_fully_grounded_turn_is_refused(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str
) -> None:
    """Issue #532: the offer only ever renders below an abstention or a
    partial answer's named gap, but the *server* must refuse a direct call
    against a turn that did neither — C10's "the offer is the only route to
    a search" is a structural guarantee, not a rendering convention."""
    _truncate(database_url)
    client = _fixture_client(settings, monkeypatch, tmp_path, database_url)
    conversation_id = _seed_conversation(database_url)
    message_id = _seed_message(
        database_url,
        conversation_id,
        content="The notice period is ninety days.",
        trace={"status": "completed", "reason": None, "partial_coverage": False},
    )
    response = client.post(f"/ask/{message_id}/escalate/web", json={"question": "notice period?"})
    assert response.status_code == 409


def test_escalating_an_abstained_turn_succeeds_and_is_recorded(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    database_url: str,
    grant_calls: _GrantCalls,  # noqa: F811 — parameter shadows the fixture import
) -> None:
    _truncate(database_url)
    client = _fixture_client(settings, monkeypatch, tmp_path, database_url)
    conversation_id = _seed_conversation(database_url)
    message_id = _seed_message(
        database_url,
        conversation_id,
        content="",
        trace={
            "status": "completed",
            "reason": "Nothing in your files answers this.",
            "partial_coverage": False,
        },
    )
    response = client.post(
        f"/ask/{message_id}/escalate/web", json={"question": "what changed in 2026?"}
    )
    assert response.status_code == 200
    body = response.json()
    # `FixtureWebSearchProvider` with no recorded fixtures — this ticket's
    # own point is that the HTTP route reaches `escalate_web_search` at all,
    # not any particular provider's content.
    assert body["status"] == "no_results"

    with psycopg.connect(database_url, autocommit=True) as db:
        decisions = db.execute(
            "SELECT kind, payload FROM audit_decisions "
            "WHERE kind = 'web_search_escalation_accepted'"
        ).fetchall()
        interactions = db.execute(
            "SELECT kind FROM audit_interactions WHERE kind = 'web_search_escalated'"
        ).fetchall()
    assert len(decisions) == 1
    assert decisions[0][1]["message_id"] == str(message_id)
    assert len(interactions) == 1


def test_escalating_a_partial_answer_succeeds(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    database_url: str,
    grant_calls: _GrantCalls,  # noqa: F811 — parameter shadows the fixture import
) -> None:
    _truncate(database_url)
    client = _fixture_client(settings, monkeypatch, tmp_path, database_url)
    conversation_id = _seed_conversation(database_url)
    message_id = _seed_message(
        database_url,
        conversation_id,
        content="The notice period is ninety days. Not covered: renewal terms.",
        trace={"status": "completed", "reason": None, "partial_coverage": True},
    )
    response = client.post(f"/ask/{message_id}/escalate/web", json={"question": "renewal terms?"})
    assert response.status_code == 200


def test_web_search_settings_reflects_no_provider_configured(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str
) -> None:
    _truncate(database_url)
    client = _app(
        settings.model_copy(update={"web_search_provider": None}),
        monkeypatch,
        tmp_path,
        database_url,
    )
    _with_session(client)
    response = client.get("/settings/web-search")
    assert response.status_code == 200
    assert response.json() == {"available": False}


def test_web_search_settings_reflects_a_configured_provider(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str
) -> None:
    _truncate(database_url)
    client = _fixture_client(settings, monkeypatch, tmp_path, database_url)
    response = client.get("/settings/web-search")
    assert response.status_code == 200
    assert response.json() == {"available": True}
