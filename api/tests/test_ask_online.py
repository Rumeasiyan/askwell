"""An answer from the online backend, and every way it falls back to local.
`M8-ONLINE-BE-170`.

The provider is `httpx.MockTransport`; the local model is `test_ask_api`'s
`_FakeInferenceClient`. What is under test is that only generation moves:
the same retrieval, the same abstention, the same citation resolution and the
same records, with the backend and model named on each — and that a provider
failure of any kind answers locally and says so rather than failing the turn.
"""

import json
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import psycopg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from askwell import ask as ask_module
from askwell import online
from askwell.config import Settings
from askwell.inference import provider
from askwell.inference.provider import OnlineClient, OnlineTarget

from .test_ask_api import (
    _app,
    _events,
    _FakeInferenceClient,
    _patch_client,
    _seed_chunk,
    _truncate,
    _vector,
    _with_session,
)
from .test_online import FakeRedis

pytestmark = pytest.mark.requires_db

DESTINATION = "api.provider.example:443"
MODEL = "provider-model"


def _online_settings(settings: Settings, tmp_path: Path) -> Settings:
    return settings.model_copy(
        update={
            "trace_dir": tmp_path / "traces",
            "online_ai_destination": DESTINATION,
            "online_ai_model": MODEL,
        }
    )


def _sse(*pieces: str, finish: str = "stop") -> bytes:
    events = [
        {"choices": [{"index": 0, "delta": {"content": piece}, "finish_reason": None}]}
        for piece in pieces
    ]
    events.append({"choices": [{"index": 0, "delta": {}, "finish_reason": finish}]})
    return "".join(f"data: {json.dumps(event)}\n\n" for event in events).encode("utf-8")


class _Provider:
    """A provider that records every request it was sent."""

    def __init__(self, respond: Callable[[httpx.Request], httpx.Response]) -> None:
        self.respond = respond
        self.requests: list[dict[str, Any]] = []
        self.sizes: list[int] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(json.loads(request.content))
        self.sizes.append(len(request.content))
        return self.respond(request)


def _go_online(monkeypatch: pytest.MonkeyPatch, settings: Settings, fake: _Provider) -> None:
    """Every conversation reads as online, answered by `fake`. Which
    conversations really are online is `_online_client`'s, tested below."""
    target = OnlineTarget(
        destination=DESTINATION, model=MODEL, proxy_username="u", proxy_password="p"
    )

    async def _client(*_args: object) -> OnlineClient:
        return OnlineClient(settings, target, transport=httpx.MockTransport(fake.handler))

    monkeypatch.setattr(ask_module, "_online_client", _client)


def _ask(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    database_url: str,
    question: str = "How long is the notice period?",
) -> tuple[list[tuple[str, dict[str, Any]]], uuid.UUID]:
    client = _app(settings, monkeypatch, tmp_path, database_url)
    with client:
        _with_session(client)
        response = client.post("/ask", json={"question": question})
        assert response.status_code == 200, response.text
        events = _events(response.text)
    done = next(data for kind, data in events if kind == "done")
    return events, uuid.UUID(done["message_id"])


def _stored(
    database_url: str, message_id: uuid.UUID
) -> tuple[str, dict[str, Any], list[Any], dict[str, Any]]:
    with psycopg.connect(database_url, autocommit=True) as db:
        row = db.execute(
            "SELECT content, trace FROM messages WHERE id = %s", (message_id,)
        ).fetchone()
        assert row is not None
        citations = db.execute(
            "SELECT chunk_id FROM citations WHERE message_id = %s", (message_id,)
        ).fetchall()
        audit = db.execute(
            "SELECT payload FROM audit_interactions "
            "WHERE kind = 'ask_asked' AND payload->>'message_id' = %s",
            (str(message_id),),
        ).fetchone()
        assert audit is not None
    return row[0], row[1], [c[0] for c in citations], audit[0]


def _requests_recorded(database_url: str, message_id: uuid.UUID) -> list[dict[str, Any]]:
    """The `online_ai_request` records for one turn (`M8-ONLINE-OBS-172`)."""
    with psycopg.connect(database_url, autocommit=True) as db:
        rows = db.execute(
            "SELECT payload FROM audit_interactions "
            "WHERE kind = %s AND payload->>'message_id' = %s",
            (ask_module.ONLINE_AI_REQUEST, str(message_id)),
        ).fetchall()
    return [row[0] for row in rows]


# --- the online answer ---------------------------------------------------------


def test_online_generation_keeps_retrieval_and_citations_and_names_the_backend(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str
) -> None:
    _truncate(database_url)
    settings = _online_settings(settings, tmp_path)
    vector = _vector(0.0)
    _document_id, chunk_id = _seed_chunk(database_url, "Notice is ninety days.", vector)
    local = _FakeInferenceClient(settings, tokens=["LOCAL should not answer."], vector=vector)
    _patch_client(monkeypatch, local)
    fake = _Provider(
        lambda _r: httpx.Response(200, content=_sse("The notice period ", "is ninety days [1]."))
    )
    _go_online(monkeypatch, settings, fake)

    events, message_id = _ask(settings, monkeypatch, tmp_path, database_url)

    # Generation went to the provider, once, with the composed prompt —
    # the retrieved passage inside its C7 delimiters, exactly as local.
    (request,) = fake.requests
    assert request["model"] == MODEL
    system, user = request["messages"]
    assert system["role"] == "system" and user["role"] == "user"
    assert "Notice is ninety days." in user["content"]
    assert "<retrieved-content" in user["content"]

    citation = next(data for kind, data in events if kind == "citation")
    assert citation["chunk_id"] == str(chunk_id)

    done = next(data for kind, data in events if kind == "done")
    assert done["model_identity"] == {"source": "online", "display_name": MODEL}
    with psycopg.connect(database_url, autocommit=True) as db:
        row = db.execute(
            "SELECT model_identity FROM messages WHERE id = %s", (message_id,)
        ).fetchone()
    assert row is not None and row[0] == {"source": "online", "display_name": MODEL}

    content, trace, citations, audit = _stored(database_url, message_id)
    assert content == "The notice period is ninety days [1]."
    assert citations == [chunk_id]
    assert trace["status"] == "completed"
    transmission = trace["backend"].pop("transmission")
    assert trace["backend"] == {"mode": "online", "model": MODEL, "destination": DESTINATION}
    assert audit["backend"] == "online"
    assert audit["model"] == MODEL
    assert audit["online_fallback"] is None
    # A provider's time is not the local model's throughput.
    assert trace["generation"] is None

    # `M8-ONLINE-OBS-172`: what left, recorded locally, in the trace and as
    # its own interaction record — the same entry in both.
    assert transmission["destination"] == DESTINATION
    assert transmission["model"] == MODEL
    assert transmission["request_bytes"] == fake.sizes[0]
    assert transmission["content_sent"] is True
    assert transmission["status_code"] == 200
    assert transmission["outcome"] == provider.ANSWERED
    contents = transmission["contents"]
    assert contents["question"] is True
    assert contents["chunk_ids"] == [str(chunk_id)]
    assert contents["memory_fact_ids"] == [] and contents["schema_note_ids"] == []
    assert contents["clarification_answer"] is False
    assert contents["prompt_version"]
    (recorded,) = _requests_recorded(database_url, message_id)
    assert recorded == {
        "conversation_id": audit["conversation_id"],
        "message_id": str(message_id),
        **transmission,
    }
    # Never content: not the question, not the passage, not the answer.
    serialised = json.dumps(recorded)
    for text_sent in ("notice period", "Notice is ninety days", "ninety days [1]"):
        assert text_sent not in serialised


def test_an_uncovered_question_still_abstains_and_nothing_is_sent(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str
) -> None:
    """C5 is decided before generation, so online changes nothing about it —
    and an abstention sends nothing to the provider at all."""
    _truncate(database_url)
    settings = _online_settings(settings, tmp_path)
    vector = _vector(0.0)
    _seed_chunk(database_url, "Pets are not allowed.", vector)
    local = _FakeInferenceClient(
        settings, tokens=["should never be sent"], vector=vector, rerank_score=-10.0
    )
    _patch_client(monkeypatch, local)
    fake = _Provider(lambda _r: httpx.Response(200, content=_sse("invented")))
    _go_online(monkeypatch, settings, fake)

    events, message_id = _ask(
        settings, monkeypatch, tmp_path, database_url, question="What colour is the moon?"
    )

    assert fake.requests == []
    assert not [data for kind, data in events if kind == "token"]
    content, trace, citations, audit = _stored(database_url, message_id)
    assert content.startswith("Nothing in your files answers this.")
    assert citations == []
    assert audit["abstained"] is True
    assert trace["backend"]["mode"] == "local"
    assert "transmission" not in trace["backend"]
    assert _requests_recorded(database_url, message_id) == []


def test_an_uncited_online_answer_is_treated_as_an_uncited_local_one(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str
) -> None:
    """The citation requirement is not relaxed for the online path: the same
    text, answered locally and online, stores the same citations — none."""
    uncited = "The notice period is ninety days."
    stored: dict[str, tuple[str, list[Any]]] = {}
    record_keys: dict[str, set[str]] = {}
    for mode in ("local", "online"):
        _truncate(database_url)
        (tmp_path / mode).mkdir()
        run_settings = _online_settings(settings, tmp_path / mode)
        vector = _vector(0.0)
        _seed_chunk(database_url, "Notice is ninety days.", vector)
        _patch_client(
            monkeypatch, _FakeInferenceClient(run_settings, tokens=[uncited], vector=vector)
        )
        if mode == "online":
            _go_online(
                monkeypatch,
                run_settings,
                _Provider(lambda _r: httpx.Response(200, content=_sse(uncited))),
            )
        _events_seen, message_id = _ask(run_settings, monkeypatch, tmp_path / mode, database_url)
        content, trace, citations, audit = _stored(database_url, message_id)
        assert trace["backend"]["mode"] == mode
        stored[mode] = (content, citations)
        record_keys[mode] = set(audit)
    assert stored["online"] == stored["local"] == (uncited, [])
    # `M8-ONLINE-OBS-172`: online adds a record and never reshapes this one.
    assert record_keys["online"] == record_keys["local"]


# --- falling back ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("respond", "reason_code", "said", "content_sent"),
    [
        (
            lambda r: (_ for _ in ()).throw(httpx.ConnectError("no route", request=r)),
            provider.NETWORK_UNAVAILABLE,
            "the network is unavailable",
            False,
        ),
        (lambda _r: httpx.Response(429), provider.RATE_LIMITED, "limiting requests", True),
        (lambda _r: httpx.Response(401), provider.REFUSED, "refused the request", True),
    ],
)
def test_a_failure_before_the_answer_falls_back_to_local_and_says_so(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    database_url: str,
    respond: Callable[[httpx.Request], httpx.Response],
    reason_code: str,
    said: str,
    content_sent: bool,
) -> None:
    _truncate(database_url)
    settings = _online_settings(settings, tmp_path)
    vector = _vector(0.0)
    _document_id, chunk_id = _seed_chunk(database_url, "Notice is ninety days.", vector)
    _patch_client(
        monkeypatch, _FakeInferenceClient(settings, tokens=["Ninety days [1]."], vector=vector)
    )
    _go_online(monkeypatch, settings, _Provider(respond))

    events, message_id = _ask(settings, monkeypatch, tmp_path, database_url)

    done = next(data for kind, data in events if kind == "done")
    assert done["status"] == "completed", "a provider failure never fails the turn"
    steps = [data for kind, data in events if kind == "step" and data["kind"] == "backend"]
    assert len(steps) == 1 and said in steps[0]["label"]
    assert "answer_reset" not in [kind for kind, _ in events], "nothing to take back"

    content, trace, citations, audit = _stored(database_url, message_id)
    assert content.startswith("Ninety days [1].\n\nAnswered by the local model. ")
    assert said in content
    assert citations == [chunk_id]
    assert trace["backend"]["mode"] == "local"
    assert trace["backend"]["model"] == settings.inference_model_path.stem
    assert trace["backend"]["requested"] == "online"
    assert trace["backend"]["fallback"]["reason_code"] == reason_code
    assert audit["backend"] == "local"
    assert audit["online_fallback"] == reason_code
    # `M8-ONLINE-OBS-172`: answered locally, but a refused request still left
    # the machine, and says so; one that never connected says nothing did.
    transmission = trace["backend"]["transmission"]
    assert transmission["content_sent"] is content_sent
    assert transmission["outcome"] == reason_code
    assert transmission["contents"]["chunk_ids"] == [str(chunk_id)]
    (recorded,) = _requests_recorded(database_url, message_id)
    assert recorded["content_sent"] is content_sent


def test_a_failure_mid_answer_starts_again_locally_and_keeps_nothing_online(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str
) -> None:
    _truncate(database_url)
    settings = _online_settings(settings, tmp_path)
    vector = _vector(0.0)
    _document_id, chunk_id = _seed_chunk(database_url, "Notice is ninety days.", vector)
    _patch_client(
        monkeypatch, _FakeInferenceClient(settings, tokens=["Ninety days [1]."], vector=vector)
    )

    class _Breaks(httpx.AsyncByteStream):
        async def __aiter__(self):  # type: ignore[no-untyped-def]
            body = _sse("ONLINE half [1]. ")
            yield body.split(b"\n\n")[0] + b"\n\n"
            raise httpx.ReadError("tunnel cut")

    _go_online(monkeypatch, settings, _Provider(lambda _r: httpx.Response(200, stream=_Breaks())))

    events, message_id = _ask(settings, monkeypatch, tmp_path, database_url)

    kinds = [kind for kind, _ in events]
    # The online half reached the reader, then was taken back, then the
    # local answer followed — in that order.
    assert kinds.index("answer_reset") > kinds.index("token")
    assert "token" in kinds[kinds.index("answer_reset") :]
    assert next(data for kind, data in events if kind == "done")["status"] == "completed"

    content, trace, citations, audit = _stored(database_url, message_id)
    assert "ONLINE" not in content
    assert content.startswith("Ninety days [1].\n\nAnswered by the local model. ")
    assert citations == [chunk_id], "one citation, from the local answer only"
    fallback_steps = [s for s in trace["steps"] if s["kind"] == "online_fallback"]
    assert fallback_steps[0]["reason_code"] == provider.INTERRUPTED
    assert fallback_steps[0]["mid_answer"] is True
    assert audit["online_fallback"] == provider.INTERRUPTED


# --- which conversations go online ---------------------------------------------


async def test_only_a_conversation_authorised_in_this_process_gets_the_provider(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str
) -> None:
    import redis.asyncio as redis

    store: dict[str, str] = {}
    monkeypatch.setattr(redis, "Redis", lambda **_kwargs: FakeRedis(store, {}))
    online._credentials.clear()
    monkeypatch.setattr(online, "DISCLOSURE", online.Disclosure(version="t", text="What goes."))
    settings = _online_settings(settings, tmp_path)
    engine = create_async_engine(database_url.replace("postgresql://", "postgresql+psycopg://", 1))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as db:
            conversation_ids = [uuid.uuid4(), uuid.uuid4()]
            for conversation_id in conversation_ids:
                await db.execute(
                    text("INSERT INTO conversations (id) VALUES (:id)"), {"id": conversation_id}
                )
            await db.commit()
            online_one, local_one = conversation_ids
            await online.enable(db, settings, online_one)
            await db.commit()

        # Authorised is not enough: nothing goes before the disclosure is
        # confirmed (`M8-ONLINE-FE-171`).
        assert await ask_module._online_client(factory, settings, online_one) is None
        async with factory() as db:
            await online.confirm_disclosure(db, settings, online_one, "t")
            await db.commit()

        chosen = await ask_module._online_client(factory, settings, online_one)
        assert chosen is not None
        assert chosen.model == MODEL
        assert (chosen.target.proxy_username, chosen.target.proxy_password) == (
            online.proxy_credentials(online_one)
        )
        assert chosen.target.api_key is None, "no key is held until M8-KEY-BE-173"

        assert await ask_module._online_client(factory, settings, local_one) is None
        unmodelled = settings.model_copy(update={"online_ai_model": None})
        assert await ask_module._online_client(factory, unmodelled, online_one) is None

        async with factory() as db:
            await online.disable(db, settings, online_one)
            await db.commit()
        assert await ask_module._online_client(factory, settings, online_one) is None
    finally:
        online._credentials.clear()
        async with factory() as db:
            await db.execute(text("UPDATE conversations SET ai_backend = 'local'"))
            await db.commit()
        await engine.dispose()


def test_a_local_turn_records_the_model_it_was_asked_under(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str
) -> None:
    """The model on every turn is the one identified at question time, not
    the host-side path setting this container is never given — which
    recorded `model` on every local turn until this ticket."""
    _truncate(database_url)
    settings = settings.model_copy(update={"trace_dir": tmp_path / "traces"})
    vector = _vector(0.0)
    _seed_chunk(database_url, "Notice is ninety days.", vector)
    _patch_client(
        monkeypatch, _FakeInferenceClient(settings, tokens=["Ninety days [1]."], vector=vector)
    )

    async def _identity(*_args: object) -> dict[str, Any]:
        return {"source": "shipped", "display_name": "Local-Model-Q4.gguf"}

    monkeypatch.setattr(ask_module, "active_model_identity", _identity)

    _events_seen, message_id = _ask(settings, monkeypatch, tmp_path, database_url)

    _content, trace, _citations, audit = _stored(database_url, message_id)
    assert trace["backend"] == {"mode": "local", "model": "Local-Model-Q4.gguf"}
    assert audit["model"] == "Local-Model-Q4.gguf"


# --- the pre-send disclosure (`M8-ONLINE-FE-171`) ------------------------------


def test_an_online_conversation_takes_no_question_until_what_it_sends_is_confirmed(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str
) -> None:
    """Through the routes the interface uses: create the conversation, switch
    it online, ask. While the payload is undefined the question is refused
    and nothing is recorded or sent. Once a statement exists, the question is
    refused until it is confirmed. A confirmed conversation whose question
    abstains still sends nothing, and its trace says so."""
    import redis.asyncio as redis

    store: dict[str, str] = {}
    monkeypatch.setattr(redis, "Redis", lambda **_kwargs: FakeRedis(store, {}))
    online._credentials.clear()
    _truncate(database_url)
    settings = _online_settings(settings, tmp_path)
    vector = _vector(0.0)
    _seed_chunk(database_url, "Pets are not allowed.", vector)
    _patch_client(
        monkeypatch,
        _FakeInferenceClient(settings, tokens=["never"], vector=vector, rerank_score=-10.0),
    )
    fake = _Provider(lambda _r: httpx.Response(200, content=_sse("invented")))

    client = _app(settings, monkeypatch, tmp_path, database_url)
    try:
        with client:
            _with_session(client)
            created = client.post("/conversations")
            assert created.status_code == 201
            conversation_id = created.json()["conversation_id"]
            assert (
                client.get(f"/conversations/{conversation_id}/online").json()["ai_backend"]
                == "local"
            )

            enabled = client.post(f"/conversations/{conversation_id}/online").json()
            assert enabled["ai_backend"] == "online"
            assert enabled["used_online"] is True
            assert enabled["send_permitted"] is False
            assert enabled["disclosure"]["defined"] is False

            question = {"question": "What colour is the moon?", "conversation_id": conversation_id}
            refused = client.post("/ask", json=question)
            assert refused.status_code == 409
            assert refused.json()["error"] == online.DISCLOSURE_UNDEFINED
            confirm = client.post(
                f"/conversations/{conversation_id}/online/disclosure", json={"version": "1"}
            )
            assert confirm.status_code == 409

            monkeypatch.setattr(
                online, "DISCLOSURE", online.Disclosure(version="1", text="Your question.")
            )
            refused = client.post("/ask", json=question)
            assert refused.status_code == 409
            assert refused.json()["error"] == online.NOT_CONFIRMED

            confirmed = client.post(
                f"/conversations/{conversation_id}/online/disclosure", json={"version": "1"}
            )
            assert confirmed.status_code == 200, confirmed.text
            assert confirmed.json()["send_permitted"] is True

            _go_online(monkeypatch, settings, fake)
            answered = client.post("/ask", json=question)
            assert answered.status_code == 200, answered.text
            done = next(data for kind, data in _events(answered.text) if kind == "done")
    finally:
        online._credentials.clear()
        with psycopg.connect(database_url, autocommit=True) as db:
            db.execute("UPDATE conversations SET ai_backend = 'local'")

    assert fake.requests == []
    _content, trace, _citations, _audit = _stored(database_url, uuid.UUID(done["message_id"]))
    assert trace["backend"]["mode"] == "local"
    assert trace["backend"]["requested"] == "online"
    assert trace["backend"]["sent_online"] is False
    with psycopg.connect(database_url, autocommit=True) as db:
        # The two refused questions left nothing behind; only the third did.
        (count,) = db.execute(
            "SELECT count(*) FROM messages WHERE conversation_id = %s AND role = 'user'",
            (conversation_id,),
        ).fetchone() or (None,)
        confirmations = db.execute(
            "SELECT payload FROM audit_decisions "
            "WHERE kind = 'online_ai_disclosure_confirmed' AND payload->>'conversation_id' = %s",
            (conversation_id,),
        ).fetchall()
    assert count == 1
    assert [row[0] for row in confirmations] == [
        {"conversation_id": conversation_id, "version": "1"}
    ]
