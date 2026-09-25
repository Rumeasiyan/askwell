"""The user's provider key, held as a secret. `M8-KEY-BE-173`.

Validation and masking without a database, then storage against a real one:
encrypted at rest, removed rather than hidden, and carried through a
passphrase being set, locked and removed like every other credential.
"""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from askwell import crypto, online, passphrase, provider_key
from askwell.config import Settings
from askwell.provider_key import InvalidProviderKey, Provider, ProviderKey

SENTINEL = "sk-SENTINEL-provider-key-0123456789"
DESTINATION = "api.provider.example:443"
PROVIDER = Provider(destination=DESTINATION, model="provider-model")

# --- no database ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("destination", "model", "api_key", "names"),
    [
        (DESTINATION, "provider-model", "   ", "key"),
        (DESTINATION, "provider-model", f"{SENTINEL}\n", "key"),
        (DESTINATION, "provider-model", f"Bearer {SENTINEL}", "key"),
        (DESTINATION, "provider-model", "short", "key"),
        ("https://api.provider.example", "provider-model", SENTINEL, "address"),
        ("api.provider.example:443,evil.example:443", "provider-model", SENTINEL, "address"),
        (DESTINATION, "", SENTINEL, "model"),
        (DESTINATION, "provider model", SENTINEL, "model"),
    ],
)
def test_what_cannot_be_a_provider_or_a_key_is_refused_without_repeating_it(
    destination: str, model: str, api_key: str, names: str
) -> None:
    with pytest.raises(InvalidProviderKey) as caught:
        provider_key.validate(destination, model, api_key)
    assert names in str(caught.value)
    assert SENTINEL not in str(caught.value)


def test_a_provider_key_never_shows_its_value_in_a_repr() -> None:
    held = ProviderKey(provider=PROVIDER, api_key=SENTINEL)
    assert SENTINEL not in repr(held)
    assert SENTINEL not in str(held)
    assert DESTINATION in repr(held)


def test_no_online_send_is_possible_until_redis_is_authenticated() -> None:
    """Issue #730. With a key held, a conversation grant is a working route
    to a paid endpoint with the user's credential, and any container that can
    write to Redis can write a grant. Until the disclosure was set (#737,
    `M8-FIX-BE-178`), `online.DISCLOSURE is None` refused every online send.
    Now that it is set, this passes only because Redis is authenticated
    (`M8-FIX-SEC-177`); it fails if that authentication is ever removed while
    sends are permitted. Do not weaken it to make a change pass."""
    compose = (Path(__file__).resolve().parents[2] / "compose.yaml").read_text()
    redis_service = compose.split("\n  redis:\n", 1)[1].split("\n  egress-proxy:\n", 1)[0]
    authenticated = "--requirepass" in redis_service or "--aclfile" in redis_service
    assert online.DISCLOSURE is None or authenticated, (
        "Online sends are about to be permitted while Redis has no authentication: "
        "land issue #730 (Redis ACLs, one user per service) first."
    )


# --- against a database ---------------------------------------------------------


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url="postgresql://askwell:pw@127.0.0.1:1/askwell",  # type: ignore[arg-type]
        sandbox_database_url="postgresql://x:x@127.0.0.1:1/postgres",  # type: ignore[arg-type]
        sandbox_owner_password="pw",  # type: ignore[arg-type]
        sandbox_readonly_password="pw",  # type: ignore[arg-type]
        install_secret_path=tmp_path / "install.key",
    )


async def _clean(db: AsyncSession) -> None:
    await db.execute(text("TRUNCATE audit_decisions"))
    # A passphrase change re-encrypts every stored credential; another
    # test's, under another test's install secret, would not decrypt.
    # CASCADE: another suite's turns leave citations pointing at sources,
    # and this test must not assume rows it did not create away (#752).
    await db.execute(text("TRUNCATE sources CASCADE"))
    await db.execute(
        text("DELETE FROM settings WHERE key IN (:key, :verifier)"),
        {"key": provider_key.SETTING_KEY, "verifier": passphrase.VERIFIER_KEY},
    )
    await db.commit()


@pytest_asyncio.fixture
async def session(database_url: str) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(database_url.replace("postgresql://", "postgresql+psycopg://", 1))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    passphrase._reset_lock_state_for_tests()
    async with factory() as opened:
        await _clean(opened)
        yield opened
        await opened.rollback()
        await _clean(opened)
    passphrase._reset_lock_state_for_tests()
    await engine.dispose()


async def _stored_row(db: AsyncSession) -> str | None:
    row = (
        await db.execute(
            text("SELECT value FROM settings WHERE key = :key"), {"key": provider_key.SETTING_KEY}
        )
    ).first()
    return None if row is None else str(row[0])


@pytest.mark.requires_db
async def test_the_key_is_encrypted_at_rest_and_decrypted_only_on_load(
    session: AsyncSession, settings: Settings
) -> None:
    key = await passphrase.current_key(session, settings)
    assert await provider_key.store(session, key, PROVIDER, SENTINEL) is None
    await session.commit()

    raw = await _stored_row(session)
    assert raw is not None
    assert SENTINEL not in raw, "the settings row holds ciphertext, never the key"
    assert DESTINATION in raw, "which provider it is for is not secret"

    assert await provider_key.stored_provider(session) == PROVIDER
    loaded = await provider_key.load(session, key)
    assert loaded == ProviderKey(provider=PROVIDER, api_key=SENTINEL)


@pytest.mark.requires_db
async def test_replacing_replaces_and_removing_removes_the_row(
    session: AsyncSession, settings: Settings
) -> None:
    key = await passphrase.current_key(session, settings)
    await provider_key.store(session, key, PROVIDER, SENTINEL)
    other = Provider(destination="other.provider.example:443", model="other-model")
    assert await provider_key.store(session, key, other, "sk-another-key-entirely") == PROVIDER
    await session.commit()

    loaded = await provider_key.load(session, key)
    assert loaded is not None
    assert (loaded.provider, loaded.api_key) == (other, "sk-another-key-entirely")

    assert await provider_key.remove(session) == other
    await session.commit()
    assert await _stored_row(session) is None, "removed, not hidden"
    assert await provider_key.load(session, key) is None
    assert await provider_key.remove(session) is None


@pytest.mark.requires_db
async def test_a_passphrase_carries_the_key_and_locks_it_like_everything_else(
    session: AsyncSession, settings: Settings
) -> None:
    """Set a passphrase: the key is re-encrypted, never asked for again. A
    restart (a new process's lock state) cannot read it until unlock. Remove
    the passphrase: it reads under the install secret again."""
    await provider_key.store(
        session, await passphrase.current_key(session, settings), PROVIDER, SENTINEL
    )
    await session.commit()
    before = await _stored_row(session)

    await passphrase.set_passphrase(
        session, settings, "Correct-Horse-Battery-42", acknowledged_no_recovery=True
    )
    await session.commit()
    assert await _stored_row(session) != before, "re-encrypted under the new key"
    loaded = await provider_key.load(session, await passphrase.current_key(session, settings))
    assert loaded is not None and loaded.api_key == SENTINEL

    passphrase._reset_lock_state_for_tests()
    with pytest.raises(passphrase.Locked):
        await provider_key.load(session, await passphrase.current_key(session, settings))
    install_only = crypto.derive_key(
        crypto.load_or_create_install_secret(settings.install_secret_path)
    )
    with pytest.raises(crypto.CredentialsLocked):
        await provider_key.load(session, install_only)
    assert await provider_key.stored_provider(session) == PROVIDER, "which provider still reads"

    await passphrase.unlock(session, settings, "Correct-Horse-Battery-42")
    loaded = await provider_key.load(session, await passphrase.current_key(session, settings))
    assert loaded is not None and loaded.api_key == SENTINEL

    await passphrase.remove_passphrase(session, settings, "Correct-Horse-Battery-42")
    await session.commit()
    loaded = await provider_key.load(session, install_only)
    assert loaded is not None and loaded.api_key == SENTINEL
