"""Online AI, authorised per conversation. `M8-ONLINE-SEC-169`.

Against a real database, with `askwell.egress`'s own grant functions running
over an in-memory Redis stand-in — the same convention `test_egress.py` and
`test_network.py` follow. What the proxy then does with a grant (forward the
owning conversation, refuse everything else, cut a revoked tunnel) is
`test_egress.py`'s; this file is about when a grant exists at all, and what
is on the record when it starts and stops.
"""

import base64
import json
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from askwell import crypto, online, passphrase, provider_key
from askwell.config import Settings
from askwell.egress import CONVERSATION_GRANT_KEY_PREFIX, credential_digest

pytestmark = pytest.mark.requires_db

DESTINATION = "api.provider.example:443"


class FakeRedis:
    """Just enough Redis for the conversation grant: one shared dict."""

    def __init__(self, store: dict[str, str], ttls: dict[str, int]) -> None:
        self.store = store
        self.ttls = ttls

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value
        if ex is not None:
            self.ttls[key] = ex

    async def get(self, key: str) -> bytes | None:
        value = self.store.get(key)
        return value.encode("utf-8") if value is not None else None

    async def ttl(self, key: str) -> int:
        return self.ttls.get(key, -1) if key in self.store else -2

    async def delete(self, *keys: str) -> int:
        return sum(1 for key in keys if self.store.pop(key, None) is not None)

    async def scan(
        self, cursor: int, match: str | None = None, count: int | None = None
    ) -> tuple[int, list[str]]:
        prefix = (match or "*").rstrip("*")
        return 0, [key for key in self.store if key.startswith(prefix)]

    async def mget(self, keys: list[str]) -> list[bytes | None]:
        return [await self.get(key) for key in keys]

    async def aclose(self) -> None:
        return None


@pytest.fixture
def redis_store(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    store: dict[str, str] = {}
    ttls: dict[str, int] = {}
    import redis.asyncio as redis

    monkeypatch.setattr(redis, "Redis", lambda **_kwargs: FakeRedis(store, ttls))
    return store


@pytest.fixture(autouse=True)
def _fresh_credentials() -> Iterator[None]:
    online._credentials.clear()
    yield
    online._credentials.clear()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url="postgresql://askwell:pw@127.0.0.1:1/askwell",  # type: ignore[arg-type]
        sandbox_database_url="postgresql://x:x@127.0.0.1:1/postgres",  # type: ignore[arg-type]
        sandbox_owner_password="pw",  # type: ignore[arg-type]
        sandbox_readonly_password="pw",  # type: ignore[arg-type]
        trace_dir=tmp_path / "traces",
        install_secret_path=tmp_path / "install.key",
        online_ai_authorisation_ttl_seconds=3600,
    )


async def hold_key(db: AsyncSession, settings: Settings, destination: str = DESTINATION) -> None:
    """A provider key for `destination`, stored as the settings screen would,
    without the decisions record `online.store_key` adds."""
    install_secret = crypto.load_or_create_install_secret(settings.install_secret_path)
    await provider_key.store(
        db,
        crypto.derive_key(install_secret),
        provider_key.Provider(destination=destination, model="provider-model"),
        "sk-test-key-for-online",
    )


async def _clean(db: AsyncSession) -> None:
    await db.execute(text("TRUNCATE audit_decisions"))
    # Another test's conversation left online would be one more for the
    # restart to revoke than this test created.
    await db.execute(text("UPDATE conversations SET ai_backend = 'local'"))
    await db.execute(
        text("DELETE FROM settings WHERE key IN (:key, :verifier)"),
        {"key": provider_key.SETTING_KEY, "verifier": passphrase.VERIFIER_KEY},
    )


@pytest_asyncio.fixture
async def factory(
    database_url: str, settings: Settings
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(database_url.replace("postgresql://", "postgresql+psycopg://", 1))
    made = async_sessionmaker(engine, expire_on_commit=False)
    async with made() as db:
        await _clean(db)
        # Online AI needs a key to be available at all (`M8-KEY-BE-173`).
        await hold_key(db, settings)
        await db.commit()
    yield made
    async with made() as db:
        await _clean(db)
        await db.commit()
    await engine.dispose()


@pytest_asyncio.fixture
async def session(factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with factory() as db:
        yield db
        await db.rollback()


async def _conversation(db: AsyncSession) -> uuid.UUID:
    conversation_id = uuid.uuid4()
    await db.execute(text("INSERT INTO conversations (id) VALUES (:id)"), {"id": conversation_id})
    await db.commit()
    return conversation_id


async def _backend(db: AsyncSession, conversation_id: uuid.UUID) -> str:
    return str(
        (
            await db.execute(
                text("SELECT ai_backend FROM conversations WHERE id = :id"),
                {"id": conversation_id},
            )
        ).scalar_one()
    )


async def _decisions(db: AsyncSession) -> list[tuple[str, dict[str, Any]]]:
    rows = (
        await db.execute(
            text(
                "SELECT kind, payload FROM audit_decisions "
                "WHERE kind LIKE 'online_ai_%' ORDER BY occurred_at"
            )
        )
    ).all()
    return [(str(kind), dict(payload)) for kind, payload in rows]


def _grant(store: dict[str, str], conversation_id: uuid.UUID) -> dict[str, str] | None:
    raw = store.get(f"{CONVERSATION_GRANT_KEY_PREFIX}{conversation_id}")
    return json.loads(raw) if raw is not None else None


async def test_enabling_authorises_exactly_the_one_destination_for_that_conversation(
    session: AsyncSession, settings: Settings, redis_store: dict[str, str]
) -> None:
    conversation_id = await _conversation(session)

    state = await online.enable(session, settings, conversation_id)
    await session.commit()

    assert state.online and state.destination == DESTINATION
    assert await _backend(session, conversation_id) == "online"
    grant = _grant(redis_store, conversation_id)
    assert grant is not None and grant["destination"] == DESTINATION

    credentials = online.proxy_credentials(conversation_id)
    assert credentials is not None
    assert grant["token_sha256"] == credential_digest(credentials[1])

    assert await _decisions(session) == [
        (
            "online_ai_enabled",
            {
                "conversation_id": str(conversation_id),
                "destination": DESTINATION,
                "ttl_seconds": 3600,
            },
        )
    ]


async def test_no_other_conversation_gains_access(
    session: AsyncSession, settings: Settings, redis_store: dict[str, str]
) -> None:
    """The local conversation has no grant and no credential — nothing it
    could present that the proxy would honour (`test_egress.py` proves the
    proxy refuses a request without one)."""
    online_one = await _conversation(session)
    local_one = await _conversation(session)

    await online.enable(session, settings, online_one)
    await session.commit()

    assert await _backend(session, local_one) == "local"
    assert _grant(redis_store, local_one) is None
    assert online.proxy_credentials(local_one) is None
    assert not (await online.get_state(session, settings, local_one)).online
    other = [key for key in redis_store if key.startswith(CONVERSATION_GRANT_KEY_PREFIX)]
    assert other == [f"{CONVERSATION_GRANT_KEY_PREFIX}{online_one}"]


async def test_nothing_is_authorised_when_no_key_is_held(
    session: AsyncSession, settings: Settings, redis_store: dict[str, str]
) -> None:
    """`M8-KEY-BE-173`: with no key there is no provider, so online AI is
    unavailable with that reason — not an error at the next question."""
    await provider_key.remove(session)
    await session.commit()
    conversation_id = await _conversation(session)

    with pytest.raises(online.OnlineUnavailable) as caught:
        await online.enable(session, settings, conversation_id)
    assert str(caught.value) == online.NO_KEY
    await session.commit()

    assert await _backend(session, conversation_id) == "local"
    assert redis_store == {}
    assert await _decisions(session) == []
    state = await online.get_state(session, settings, conversation_id)
    assert not state.available and state.unavailable_reason == online.NO_KEY


async def test_the_authorised_destination_is_the_keys(
    session: AsyncSession, settings: Settings, redis_store: dict[str, str]
) -> None:
    await hold_key(session, settings, destination="other.provider.example:8443")
    await session.commit()
    conversation_id = await _conversation(session)

    state = await online.enable(session, settings, conversation_id)
    await session.commit()

    assert state.destination == "other.provider.example:8443"
    grant = _grant(redis_store, conversation_id)
    assert grant is not None and grant["destination"] == "other.provider.example:8443"


async def test_enabling_twice_is_one_decision(
    session: AsyncSession, settings: Settings, redis_store: dict[str, str]
) -> None:
    conversation_id = await _conversation(session)
    await online.enable(session, settings, conversation_id)
    await session.commit()
    first = online.proxy_credentials(conversation_id)

    await online.enable(session, settings, conversation_id)
    await session.commit()

    assert online.proxy_credentials(conversation_id) == first
    assert [kind for kind, _ in await _decisions(session)] == ["online_ai_enabled"]


async def test_disabling_revokes_immediately_and_is_recorded(
    session: AsyncSession, settings: Settings, redis_store: dict[str, str]
) -> None:
    conversation_id = await _conversation(session)
    await online.enable(session, settings, conversation_id)
    await session.commit()

    state = await online.disable(session, settings, conversation_id)
    await session.commit()

    assert not state.online
    assert _grant(redis_store, conversation_id) is None
    assert online.proxy_credentials(conversation_id) is None
    assert await _backend(session, conversation_id) == "local"
    assert (await _decisions(session))[-1] == (
        "online_ai_revoked",
        {"conversation_id": str(conversation_id), "destination": DESTINATION, "reason": "disabled"},
    )


async def test_disabling_a_local_conversation_records_nothing(
    session: AsyncSession, settings: Settings, redis_store: dict[str, str]
) -> None:
    conversation_id = await _conversation(session)
    await online.disable(session, settings, conversation_id)
    await session.commit()
    assert await _decisions(session) == []


async def test_a_lapsed_authorisation_reads_as_local_and_says_so(
    session: AsyncSession, settings: Settings, redis_store: dict[str, str]
) -> None:
    """The time bound: Redis expired the grant. The conversation does not
    carry on claiming to be online, and nothing renews it."""
    conversation_id = await _conversation(session)
    await online.enable(session, settings, conversation_id)
    await session.commit()
    redis_store.clear()

    state = await online.get_state(session, settings, conversation_id)
    await session.commit()

    assert not state.online
    assert await _backend(session, conversation_id) == "local"
    assert online.proxy_credentials(conversation_id) is None
    assert (await _decisions(session))[-1][1]["reason"] == "lapsed"


async def test_a_grant_whose_credential_died_with_its_process_is_not_honoured(
    session: AsyncSession, settings: Settings, redis_store: dict[str, str]
) -> None:
    """A crash with Redis still holding the grant: this process never minted
    it and holds no credential for it, so it is closed, not adopted."""
    conversation_id = await _conversation(session)
    await online.enable(session, settings, conversation_id)
    await session.commit()
    online._credentials.clear()

    state = await online.get_state(session, settings, conversation_id)
    await session.commit()

    assert not state.online
    assert _grant(redis_store, conversation_id) is None
    assert await _backend(session, conversation_id) == "local"


async def test_a_grant_with_nothing_on_record_behind_it_is_closed(
    session: AsyncSession, settings: Settings, redis_store: dict[str, str]
) -> None:
    conversation_id = await _conversation(session)
    redis_store[f"{CONVERSATION_GRANT_KEY_PREFIX}{conversation_id}"] = json.dumps(
        {"destination": DESTINATION, "token_sha256": "0" * 64}
    )

    state = await online.get_state(session, settings, conversation_id)

    assert not state.online
    assert redis_store == {}


async def test_a_restart_restores_no_authorisation(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    settings: Settings,
    redis_store: dict[str, str],
) -> None:
    """Killed mid-conversation with an authorisation active: Redis is
    `appendonly`, so the grant would survive. Startup closes it, puts the
    conversation back to local, and records that the restart ended it."""
    conversation_id = await _conversation(session)
    await online.enable(session, settings, conversation_id)
    await session.commit()

    revoked = await online.revoke_all_on_startup(factory, settings)

    assert revoked == 1
    assert redis_store == {}
    assert online.proxy_credentials(conversation_id) is None
    assert await _backend(session, conversation_id) == "local"
    assert (await _decisions(session))[-1] == (
        "online_ai_revoked",
        {"conversation_id": str(conversation_id), "destination": DESTINATION, "reason": "restart"},
    )


async def test_a_quiet_restart_records_nothing(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    settings: Settings,
    redis_store: dict[str, str],
) -> None:
    await _conversation(session)
    assert await online.revoke_all_on_startup(factory, settings) == 0
    assert await _decisions(session) == []


async def test_an_unknown_conversation_is_not_found(
    session: AsyncSession, settings: Settings, redis_store: dict[str, str]
) -> None:
    with pytest.raises(online.ConversationNotFound):
        await online.enable(session, settings, uuid.uuid4())
    assert redis_store == {}


async def test_a_revocation_names_the_destination_even_when_the_grant_was_already_gone(
    factory: async_sessionmaker[AsyncSession],
    session: AsyncSession,
    settings: Settings,
    redis_store: dict[str, str],
) -> None:
    """A whole-stack restart: the proxy starts first and clears its grants,
    so by the time the API revokes, Redis no longer knows the destination.
    The record still names it, from the conversation's own enable record."""
    conversation_id = await _conversation(session)
    await online.enable(session, settings, conversation_id)
    await session.commit()
    redis_store.clear()

    await online.revoke_all_on_startup(factory, settings)

    assert (await _decisions(session))[-1][1]["destination"] == DESTINATION


# --- the pre-send disclosure (`M8-ONLINE-FE-171`) ------------------------------

DISCLOSED = online.Disclosure(version="test-1", text="Your question and the passages found for it.")


async def test_while_the_payload_is_undefined_nothing_can_be_confirmed_and_nothing_sent(
    session: AsyncSession, settings: Settings, redis_store: dict[str, str]
) -> None:
    """The ticket's safeguard: the product never sends something it cannot
    describe. Online is authorised; a send is still not permitted."""
    assert online.DISCLOSURE is None, "#737 decides the wording; until then this stays None"
    conversation_id = await _conversation(session)

    state = await online.enable(session, settings, conversation_id)
    await session.commit()
    assert state.online and not state.send_permitted
    assert state.as_dict()["disclosure"] == {
        "defined": False,
        "version": None,
        "text": None,
        "confirmed": False,
    }

    with pytest.raises(online.DisclosureNotConfirmable, match="not been decided"):
        await online.confirm_disclosure(session, settings, conversation_id, "anything")
    assert [kind for kind, _ in await _decisions(session)] == ["online_ai_enabled"]


async def test_confirming_is_a_decisions_record_naming_the_conversation_and_is_asked_once(
    session: AsyncSession,
    settings: Settings,
    redis_store: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(online, "DISCLOSURE", DISCLOSED)
    conversation_id = await _conversation(session)
    other = await _conversation(session)
    await online.enable(session, settings, conversation_id)
    await online.enable(session, settings, other)
    await session.commit()

    assert not (await online.get_state(session, settings, conversation_id)).send_permitted
    with pytest.raises(online.DisclosureNotConfirmable, match="has changed"):
        await online.confirm_disclosure(session, settings, conversation_id, "test-0")

    state = await online.confirm_disclosure(session, settings, conversation_id, "test-1")
    await online.confirm_disclosure(session, settings, conversation_id, "test-1")
    await session.commit()

    assert state.send_permitted and state.as_dict()["disclosure"]["confirmed"] is True
    confirmations = [
        payload for kind, payload in await _decisions(session) if kind.endswith("confirmed")
    ]
    assert confirmations == [{"conversation_id": str(conversation_id), "version": "test-1"}]
    # One conversation's confirmation is not another's.
    assert not (await online.get_state(session, settings, other)).send_permitted


async def test_a_lapsed_conversation_keeps_its_marker_and_is_not_asked_again(
    session: AsyncSession,
    settings: Settings,
    redis_store: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resumed weeks later: the authorisation has long lapsed, the
    conversation still reads as having used online AI, and switching it back
    on does not repeat the disclosure it already confirmed."""
    monkeypatch.setattr(online, "DISCLOSURE", DISCLOSED)
    conversation_id = await _conversation(session)
    await online.enable(session, settings, conversation_id)
    await online.confirm_disclosure(session, settings, conversation_id, "test-1")
    await session.commit()

    redis_store.clear()  # the time bound ran out
    lapsed = await online.get_state(session, settings, conversation_id)
    await session.commit()
    assert not lapsed.online and lapsed.used_online and lapsed.disclosure_confirmed

    again = await online.enable(session, settings, conversation_id)
    await session.commit()
    assert again.send_permitted


async def test_a_changed_statement_is_confirmed_again(
    session: AsyncSession,
    settings: Settings,
    redis_store: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(online, "DISCLOSURE", DISCLOSED)
    conversation_id = await _conversation(session)
    await online.enable(session, settings, conversation_id)
    await online.confirm_disclosure(session, settings, conversation_id, "test-1")
    await session.commit()

    monkeypatch.setattr(online, "DISCLOSURE", online.Disclosure(version="test-2", text="More."))
    assert not (await online.get_state(session, settings, conversation_id)).send_permitted


async def test_a_conversation_never_switched_on_is_not_marked(
    session: AsyncSession, settings: Settings, redis_store: dict[str, str]
) -> None:
    conversation_id = await _conversation(session)
    state = await online.get_state(session, settings, conversation_id)
    assert not state.used_online and not state.online


# --- the provider key (`M8-KEY-BE-173`) ------------------------------------------

KEY_SENTINEL = "sk-SENTINEL-online-key-0123456789"


async def _key_decisions(db: AsyncSession) -> list[tuple[str, dict[str, Any]]]:
    rows = (
        await db.execute(
            text(
                "SELECT kind, payload FROM audit_decisions "
                "WHERE kind LIKE 'online_key_%' ORDER BY occurred_at"
            )
        )
    ).all()
    return [(str(kind), dict(payload)) for kind, payload in rows]


async def test_storing_replacing_and_removing_are_records_of_the_fact_never_the_value(
    session: AsyncSession, settings: Settings, redis_store: dict[str, str]
) -> None:
    await provider_key.remove(session)
    await online.store_key(session, settings, DESTINATION, "provider-model", KEY_SENTINEL)
    await online.store_key(session, settings, DESTINATION, "bigger-model", KEY_SENTINEL + "2")
    assert await online.remove_key(session, settings) is True
    assert await online.remove_key(session, settings) is False, "removing nothing records nothing"
    await session.commit()

    decisions = await _key_decisions(session)
    assert [kind for kind, _ in decisions] == [
        online.ONLINE_KEY_STORED,
        online.ONLINE_KEY_REPLACED,
        online.ONLINE_KEY_REMOVED,
    ]
    assert decisions[0][1] == {"destination": DESTINATION, "model": "provider-model"}
    assert decisions[1][1] == {
        "destination": DESTINATION,
        "model": "bigger-model",
        "previous": {"destination": DESTINATION, "model": "provider-model"},
    }
    every_record = json.dumps(
        [
            dict(row)
            for row in (await session.execute(text("SELECT * FROM audit_decisions")))
            .mappings()
            .all()
        ],
        default=str,
    )
    assert KEY_SENTINEL not in every_record


async def test_removing_the_key_makes_online_unavailable_now_not_at_the_next_question(
    session: AsyncSession, settings: Settings, redis_store: dict[str, str]
) -> None:
    conversation_id = await _conversation(session)
    await online.enable(session, settings, conversation_id)
    await session.commit()

    await online.remove_key(session, settings)
    await session.commit()

    assert _grant(redis_store, conversation_id) is None
    assert online.proxy_credentials(conversation_id) is None
    assert await _backend(session, conversation_id) == "local"
    revoked = [p for kind, p in await _decisions(session) if kind == online.ONLINE_AI_REVOKED]
    assert revoked == [
        {
            "conversation_id": str(conversation_id),
            "destination": DESTINATION,
            "reason": online.REVOKED_KEY_REMOVED,
        }
    ]
    state = await online.get_state(session, settings, conversation_id)
    assert not state.available and state.unavailable_reason == online.NO_KEY
    with pytest.raises(online.OnlineUnavailable):
        await online.enable(session, settings, conversation_id)


async def test_a_key_for_another_provider_ends_every_authorisation_for_the_old_one(
    session: AsyncSession, settings: Settings, redis_store: dict[str, str]
) -> None:
    conversation_id = await _conversation(session)
    await online.enable(session, settings, conversation_id)
    await session.commit()

    # The same provider, a new key: the door is the one the user opened.
    await online.store_key(session, settings, DESTINATION, "provider-model", KEY_SENTINEL)
    await session.commit()
    assert _grant(redis_store, conversation_id) is not None
    assert (await online.get_state(session, settings, conversation_id)).online

    await online.store_key(
        session, settings, "other.provider.example:443", "provider-model", KEY_SENTINEL
    )
    await session.commit()
    assert _grant(redis_store, conversation_id) is None
    assert await _backend(session, conversation_id) == "local"
    revoked = [p for kind, p in await _decisions(session) if kind == online.ONLINE_AI_REVOKED]
    assert [p["reason"] for p in revoked] == [online.REVOKED_KEY_REPLACED]

    state = await online.enable(session, settings, conversation_id)
    assert state.destination == "other.provider.example:443"


async def test_a_locked_install_neither_reads_nor_stores_the_key(
    session: AsyncSession, settings: Settings, redis_store: dict[str, str]
) -> None:
    # The state `askwell.passphrase.set_passphrase` leaves behind, written
    # directly so this test does not re-encrypt other tests' rows: a
    # verifier, and the key held under the passphrase-derived key.
    install_secret = crypto.load_or_create_install_secret(settings.install_secret_path)
    locked_key = crypto.derive_key(install_secret, "Correct-Horse-Battery-42")
    verifier = crypto.encrypt(passphrase._CANARY, locked_key)
    await session.execute(
        text("INSERT INTO settings (key, value) VALUES (:key, :value)"),
        {"key": passphrase.VERIFIER_KEY, "value": base64.urlsafe_b64encode(verifier).decode()},
    )
    await provider_key.store(
        session, locked_key, provider_key.Provider(DESTINATION, "provider-model"), KEY_SENTINEL
    )
    await session.commit()
    passphrase._reset_lock_state_for_tests()  # as after a restart
    try:
        conversation_id = await _conversation(session)

        state = await online.get_state(session, settings, conversation_id)
        assert not state.available and state.unavailable_reason == online.KEY_LOCKED
        with pytest.raises(online.OnlineUnavailable) as caught:
            await online.enable(session, settings, conversation_id)
        assert str(caught.value) == online.KEY_LOCKED
        with pytest.raises(passphrase.Locked):
            await online.key_for_send(session, settings)
        with pytest.raises(passphrase.Locked):
            await online.store_key(session, settings, DESTINATION, "provider-model", KEY_SENTINEL)
        assert (await online.key_status(session))["set"] is True

        await passphrase.unlock(session, settings, "Correct-Horse-Battery-42")
        key = await online.key_for_send(session, settings)
        assert key is not None and key.api_key == KEY_SENTINEL
        assert (await online.get_state(session, settings, conversation_id)).available
    finally:
        passphrase._reset_lock_state_for_tests()


async def test_the_key_status_names_the_provider_and_never_the_key(
    session: AsyncSession, settings: Settings, redis_store: dict[str, str]
) -> None:
    await online.store_key(session, settings, DESTINATION, "provider-model", KEY_SENTINEL)
    status = await online.key_status(session)
    assert status == {
        "set": True,
        "provider": {"destination": DESTINATION, "model": "provider-model"},
        "available": True,
        "unavailable_reason": None,
    }
    assert KEY_SENTINEL not in json.dumps(status)
