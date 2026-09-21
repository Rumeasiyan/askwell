"""The optional passphrase: strength, no-DB unit tests, then set/change/
remove/unlock against a real database. `M7-SEC-BE-151`.
"""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from askwell import crypto, passphrase
from askwell.config import Settings

# --- strength, no database ---------------------------------------------------


def test_a_short_passphrase_does_not_meet_the_minimum() -> None:
    result = passphrase.assess_strength("short")
    assert not result.meets_minimum
    assert result.strength is passphrase.Strength.WEAK
    assert result.feedback


def test_a_long_varied_passphrase_scores_strong() -> None:
    result = passphrase.assess_strength("Correct-Horse-Battery-Staple-42!")
    assert result.meets_minimum
    assert result.strength is passphrase.Strength.STRONG


def test_a_long_but_repetitive_passphrase_still_gets_feedback() -> None:
    result = passphrase.assess_strength("aaaaaaaaaaaaaaaa")
    assert result.meets_minimum
    assert any("repeating" in line for line in result.feedback)


def test_strength_never_reveals_the_passphrase_itself() -> None:
    """The whole result is JSON-safe and carries no trace of the input."""
    result = passphrase.assess_strength("hunter2hunter2")
    body = str(result.as_dict())
    assert "hunter2" not in body


# --- database-backed -----------------------------------------------------


pytestmark_db = pytest.mark.requires_db


@pytest.fixture
def async_url(database_url: str) -> str:
    return database_url.replace("postgresql://", "postgresql+psycopg://", 1)


@pytest_asyncio.fixture
async def session(async_url: str) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(async_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as opened:
        await opened.execute(text("TRUNCATE audit_decisions"))
        await opened.execute(text("DELETE FROM sources"))
        await opened.execute(
            text("DELETE FROM settings WHERE key = :key"), {"key": passphrase.VERIFIER_KEY}
        )
        await opened.commit()
        yield opened
        await opened.rollback()
        await opened.execute(text("TRUNCATE audit_decisions"))
        await opened.execute(text("DELETE FROM sources"))
        await opened.execute(
            text("DELETE FROM settings WHERE key = :key"), {"key": passphrase.VERIFIER_KEY}
        )
        await opened.commit()
    await engine.dispose()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url="postgresql://askwell:pw@127.0.0.1:1/askwell",  # type: ignore[arg-type]
        sandbox_database_url="postgresql://x:x@127.0.0.1:1/postgres",  # type: ignore[arg-type]
        sandbox_owner_password="pw",  # type: ignore[arg-type]
        sandbox_readonly_password="pw",  # type: ignore[arg-type]
        install_secret_path=tmp_path / "install.key",
    )


async def _add_connection_row(session: AsyncSession, key: bytes) -> tuple[object, bytes]:
    plaintext = b'{"engine": "postgresql", "host": "db.example", "password": "hunter2"}'
    ciphertext = crypto.encrypt(plaintext, key)
    row = (
        await session.execute(
            text(
                "INSERT INTO sources (kind, name, config_encrypted, status) "
                "VALUES ('connection', 'db.example', :config, 'ready') RETURNING id"
            ),
            {"config": ciphertext},
        )
    ).first()
    assert row is not None
    return row[0], plaintext


@pytestmark_db
async def test_no_passphrase_means_enabled_is_false(session: AsyncSession) -> None:
    assert await passphrase.status(session) == {"enabled": False, "locked": False}


@pytestmark_db
async def test_setting_a_passphrase_without_acknowledging_no_recovery_is_refused(
    session: AsyncSession, settings: Settings
) -> None:
    with pytest.raises(passphrase.NoRecoveryNotAcknowledged):
        await passphrase.set_passphrase(
            session, settings, "correct horse battery staple", acknowledged_no_recovery=False
        )
    assert not await passphrase.is_enabled(session)


@pytestmark_db
async def test_setting_a_weak_passphrase_is_refused(
    session: AsyncSession, settings: Settings
) -> None:
    with pytest.raises(passphrase.WeakPassphrase):
        await passphrase.set_passphrase(session, settings, "short", acknowledged_no_recovery=True)


@pytestmark_db
async def test_setting_a_passphrase_unlocks_this_process_and_records_a_decision(
    session: AsyncSession, settings: Settings
) -> None:
    await passphrase.set_passphrase(
        session, settings, "correct horse battery staple", acknowledged_no_recovery=True
    )
    await session.commit()

    assert await passphrase.status(session) == {"enabled": True, "locked": False}
    row = (
        await session.execute(
            text("SELECT payload FROM audit_decisions WHERE kind = 'passphrase_set'")
        )
    ).first()
    assert row is not None
    assert row[0] == {}


@pytestmark_db
async def test_setting_a_passphrase_twice_is_refused(
    session: AsyncSession, settings: Settings
) -> None:
    await passphrase.set_passphrase(
        session, settings, "correct horse battery staple", acknowledged_no_recovery=True
    )
    with pytest.raises(passphrase.PassphraseAlreadySet):
        await passphrase.set_passphrase(
            session, settings, "a different passphrase entirely", acknowledged_no_recovery=True
        )


@pytestmark_db
async def test_setting_a_passphrase_reencrypts_existing_credentials_with_no_reentry(
    session: AsyncSession, settings: Settings
) -> None:
    before_key = await passphrase.current_key(session, settings)
    source_id, plaintext = await _add_connection_row(session, before_key)

    await passphrase.set_passphrase(
        session, settings, "correct horse battery staple", acknowledged_no_recovery=True
    )
    await session.commit()

    row = (
        await session.execute(
            text("SELECT config_encrypted FROM sources WHERE id = :id"), {"id": source_id}
        )
    ).first()
    assert row is not None
    after_key = await passphrase.current_key(session, settings)
    assert crypto.decrypt(bytes(row[0]), after_key) == plaintext
    with pytest.raises(crypto.CredentialsLocked):
        crypto.decrypt(bytes(row[0]), before_key)


@pytestmark_db
async def test_a_fresh_process_is_locked_after_a_passphrase_is_set(
    session: AsyncSession, settings: Settings
) -> None:
    """`set_passphrase` unlocks the process that just set it. A different
    process — simulated here by resetting the in-memory state, the same
    thing a restart does — must be locked until it unlocks explicitly.
    """
    await passphrase.set_passphrase(
        session, settings, "correct horse battery staple", acknowledged_no_recovery=True
    )
    await session.commit()
    passphrase._reset_lock_state_for_tests()

    assert await passphrase.status(session) == {"enabled": True, "locked": True}
    with pytest.raises(passphrase.Locked):
        await passphrase.current_key(session, settings)


@pytestmark_db
async def test_unlocking_with_the_wrong_passphrase_refuses(
    session: AsyncSession, settings: Settings
) -> None:
    await passphrase.set_passphrase(
        session, settings, "correct horse battery staple", acknowledged_no_recovery=True
    )
    await session.commit()
    passphrase._reset_lock_state_for_tests()

    with pytest.raises(passphrase.IncorrectPassphrase):
        await passphrase.unlock(session, settings, "not the right one")
    assert (await passphrase.status(session))["locked"] is True


@pytestmark_db
async def test_unlocking_with_the_right_passphrase_works(
    session: AsyncSession, settings: Settings
) -> None:
    await passphrase.set_passphrase(
        session, settings, "correct horse battery staple", acknowledged_no_recovery=True
    )
    await session.commit()
    passphrase._reset_lock_state_for_tests()

    await passphrase.unlock(session, settings, "correct horse battery staple")
    assert (await passphrase.status(session))["locked"] is False


@pytestmark_db
async def test_unlocking_when_none_is_set_refuses(
    session: AsyncSession, settings: Settings
) -> None:
    with pytest.raises(passphrase.NoPassphraseSet):
        await passphrase.unlock(session, settings, "anything")


@pytestmark_db
async def test_changing_the_passphrase_requires_the_current_one(
    session: AsyncSession, settings: Settings
) -> None:
    await passphrase.set_passphrase(
        session, settings, "correct horse battery staple", acknowledged_no_recovery=True
    )
    await session.commit()

    with pytest.raises(passphrase.IncorrectPassphrase):
        await passphrase.change_passphrase(session, settings, "wrong one", "a new passphrase!!")


@pytestmark_db
async def test_changing_the_passphrase_reencrypts_credentials_and_records_a_decision(
    session: AsyncSession, settings: Settings
) -> None:
    await passphrase.set_passphrase(
        session, settings, "correct horse battery staple", acknowledged_no_recovery=True
    )
    old_key = await passphrase.current_key(session, settings)
    source_id, plaintext = await _add_connection_row(session, old_key)
    await session.commit()

    await passphrase.change_passphrase(
        session, settings, "correct horse battery staple", "a brand new passphrase!!"
    )
    await session.commit()

    new_key = await passphrase.current_key(session, settings)
    assert new_key != old_key
    row = (
        await session.execute(
            text("SELECT config_encrypted FROM sources WHERE id = :id"), {"id": source_id}
        )
    ).first()
    assert row is not None
    assert crypto.decrypt(bytes(row[0]), new_key) == plaintext
    decision = (
        await session.execute(
            text("SELECT payload FROM audit_decisions WHERE kind = 'passphrase_changed'")
        )
    ).first()
    assert decision is not None
    assert decision[0] == {}


@pytestmark_db
async def test_changing_when_none_is_set_refuses(session: AsyncSession, settings: Settings) -> None:
    with pytest.raises(passphrase.NoPassphraseSet):
        await passphrase.change_passphrase(session, settings, "anything", "a new one entirely")


@pytestmark_db
async def test_removing_the_passphrase_requires_the_current_one(
    session: AsyncSession, settings: Settings
) -> None:
    await passphrase.set_passphrase(
        session, settings, "correct horse battery staple", acknowledged_no_recovery=True
    )
    await session.commit()

    with pytest.raises(passphrase.IncorrectPassphrase):
        await passphrase.remove_passphrase(session, settings, "wrong one")


@pytestmark_db
async def test_removing_the_passphrase_decrypts_and_states_the_consequence(
    session: AsyncSession, settings: Settings
) -> None:
    await passphrase.set_passphrase(
        session, settings, "correct horse battery staple", acknowledged_no_recovery=True
    )
    protected_key = await passphrase.current_key(session, settings)
    source_id, plaintext = await _add_connection_row(session, protected_key)
    await session.commit()

    await passphrase.remove_passphrase(session, settings, "correct horse battery staple")
    await session.commit()

    assert await passphrase.status(session) == {"enabled": False, "locked": False}
    plain_key = await passphrase.current_key(session, settings)
    row = (
        await session.execute(
            text("SELECT config_encrypted FROM sources WHERE id = :id"), {"id": source_id}
        )
    ).first()
    assert row is not None
    assert crypto.decrypt(bytes(row[0]), plain_key) == plaintext
    decision = (
        await session.execute(
            text("SELECT payload FROM audit_decisions WHERE kind = 'passphrase_removed'")
        )
    ).first()
    assert decision is not None
    assert decision[0] == {}


@pytestmark_db
async def test_removing_when_none_is_set_refuses(session: AsyncSession, settings: Settings) -> None:
    with pytest.raises(passphrase.NoPassphraseSet):
        await passphrase.remove_passphrase(session, settings, "anything")


@pytestmark_db
async def test_current_key_with_no_passphrase_matches_the_install_secret_alone(
    session: AsyncSession, settings: Settings
) -> None:
    install_secret = crypto.load_or_create_install_secret(settings.install_secret_path)
    assert await passphrase.current_key(session, settings) == crypto.derive_key(install_secret)
