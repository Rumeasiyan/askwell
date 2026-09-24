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

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(json.loads(request.content))
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
            "SELECT payload FROM audit_interactions WHERE payload->>'message_id' = %s",
            (str(message_id),),
        ).fetchone()
        assert audit is not None
    return row[0], row[1], [c[0] for c in citations], audit[0]


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
    assert trace["backend"] == {"mode": "online", "model": MODEL, "destination": DESTINATION}
    assert audit["backend"] == "online"
    assert audit["model"] == MODEL
    assert audit["online_fallback"] is None
    # A provider's time is not the local model's throughput.
    assert trace["generation"] is None


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


def test_an_uncited_online_answer_is_treated_as_an_uncited_local_one(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, database_url: str
) -> None:
    """The citation requirement is not relaxed for the online path: the same
    text, answered locally and online, stores the same citations — none."""
    uncited = "The notice period is ninety days."
    stored: dict[str, tuple[str, list[Any]]] = {}
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
        content, trace, citations, _audit = _stored(database_url, message_id)
        assert trace["backend"]["mode"] == mode
        stored[mode] = (content, citations)
    assert stored["online"] == stored["local"] == (uncited, [])


# --- falling back ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("respond", "reason_code", "said"),
    [
        (
            lambda r: (_ for _ in ()).throw(httpx.ConnectError("no route", request=r)),
            provider.NETWORK_UNAVAILABLE,
            "the network is unavailable",
        ),
        (lambda _r: httpx.Response(429), provider.RATE_LIMITED, "limiting requests"),
        (lambda _r: httpx.Response(401), provider.REFUSED, "refused the request"),
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
