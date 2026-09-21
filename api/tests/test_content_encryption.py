"""Chunk content encryption and its resumable migration, against a real
Postgres. `M7-SEC-BE-152`.
"""

import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from askwell import content_encryption, crypto
from askwell.config import Settings

pytestmark = pytest.mark.requires_db

_TABLES = "sources, documents, chunks, audit_decisions, settings"


@pytest.fixture
def async_url(database_url: str) -> str:
    return database_url.replace("postgresql://", "postgresql+psycopg://", 1)


@pytest_asyncio.fixture
async def session(async_url: str) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(async_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as opened:
        await opened.execute(text(f"TRUNCATE {_TABLES} CASCADE"))
        await opened.commit()
        yield opened
        await opened.rollback()
        await opened.execute(text(f"TRUNCATE {_TABLES} CASCADE"))
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


async def _source(session: AsyncSession) -> uuid.UUID:
    source_id = uuid.uuid4()
    await session.execute(
        text("INSERT INTO sources (id, kind, name) VALUES (:id, 'file', 'a source')"),
        {"id": source_id},
    )
    return source_id


async def _document(session: AsyncSession, source_id: uuid.UUID) -> uuid.UUID:
    document_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO documents (id, source_id, filename, path, sha256, status) "
            "VALUES (:id, :source_id, 'doc.pdf', :path, :sha256, 'ready')"
        ),
        {
            "id": document_id,
            "source_id": source_id,
            "path": f"/tmp/{document_id}",
            "sha256": uuid.uuid4().hex.ljust(64, "0")[:64],
        },
    )
    return document_id


async def _chunk(
    session: AsyncSession, document_id: uuid.UUID, content: str, ordinal: int = 0
) -> uuid.UUID:
    chunk_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO chunks (id, document_id, ordinal, content, content_tsv) "
            "VALUES (:id, :document_id, :ordinal, :content, to_tsvector('english', :content))"
        ),
        {"id": chunk_id, "document_id": document_id, "ordinal": ordinal, "content": content},
    )
    return chunk_id


async def _row(session: AsyncSession, chunk_id: uuid.UUID) -> tuple[str | None, bool]:
    row = (
        await session.execute(
            text("SELECT content, content_encrypted FROM chunks WHERE id = :id"), {"id": chunk_id}
        )
    ).one()
    return row[0], row[1]


async def test_migrating_to_encrypted_flips_every_row_and_records_decisions(
    session: AsyncSession, settings: Settings
) -> None:
    source_id = await _source(session)
    document_id = await _document(session, source_id)
    first = await _chunk(session, document_id, "The rent is due on the first.", 0)
    second = await _chunk(session, document_id, "Notice period is thirty days.", 1)
    await session.commit()

    install_secret = crypto.load_or_create_install_secret(settings.install_secret_path)
    old_key = crypto.derive_key(install_secret)
    new_key = crypto.derive_key(install_secret, "correct horse battery staple")

    await content_encryption.migrate_chunk_content(session, old_key, new_key, target_encrypted=True)
    await session.commit()

    for chunk_id, plaintext in (
        (first, "The rent is due on the first."),
        (second, "Notice period is thirty days."),
    ):
        content, encrypted = await _row(session, chunk_id)
        assert encrypted is True
        assert content != plaintext
        assert content is not None
        assert crypto.decrypt(content.encode("ascii"), new_key) == plaintext.encode("utf-8")

    kinds = {
        row[0] for row in (await session.execute(text("SELECT kind FROM audit_decisions"))).all()
    }
    assert content_encryption.CONTENT_ENCRYPTION_STARTED in kinds
    assert content_encryption.CONTENT_ENCRYPTION_COMPLETED in kinds
    assert await content_encryption.is_migrating(session) is False


async def test_a_row_already_at_target_is_left_alone(
    session: AsyncSession, settings: Settings
) -> None:
    """A resumed migration's `WHERE content_encrypted != target` clause must
    skip rows an earlier, interrupted run already finished — proved here
    directly, without simulating a crash, by pre-flipping one row and
    checking its ciphertext is untouched by a second migration call."""
    source_id = await _source(session)
    document_id = await _document(session, source_id)
    already_done = await _chunk(session, document_id, "Already migrated.", 0)
    still_pending = await _chunk(session, document_id, "Not migrated yet.", 1)
    await session.commit()

    install_secret = crypto.load_or_create_install_secret(settings.install_secret_path)
    old_key = crypto.derive_key(install_secret)
    new_key = crypto.derive_key(install_secret, "correct horse battery staple")

    pre_encrypted = crypto.encrypt(b"Already migrated.", new_key).decode("ascii")
    await session.execute(
        text("UPDATE chunks SET content = :content, content_encrypted = true WHERE id = :id"),
        {"content": pre_encrypted, "id": already_done},
    )
    await session.commit()

    await content_encryption.migrate_chunk_content(session, old_key, new_key, target_encrypted=True)
    await session.commit()

    content, encrypted = await _row(session, already_done)
    assert content == pre_encrypted
    assert encrypted is True
    content, encrypted = await _row(session, still_pending)
    assert encrypted is True
    assert content is not None
    assert crypto.decrypt(content.encode("ascii"), new_key) == b"Not migrated yet."


async def test_migrating_to_plaintext_decrypts_every_row(
    session: AsyncSession, settings: Settings
) -> None:
    source_id = await _source(session)
    document_id = await _document(session, source_id)
    install_secret = crypto.load_or_create_install_secret(settings.install_secret_path)
    old_key = crypto.derive_key(install_secret, "correct horse battery staple")
    new_key = crypto.derive_key(install_secret)

    chunk_id = uuid.uuid4()
    ciphertext = crypto.encrypt(b"Confidential terms apply.", old_key).decode("ascii")
    await session.execute(
        text(
            "INSERT INTO chunks (id, document_id, ordinal, content, content_tsv, "
            "content_encrypted) "
            "VALUES (:id, :document_id, 0, :content, to_tsvector('english', 'placeholder'), true)"
        ),
        {"id": chunk_id, "document_id": document_id, "content": ciphertext},
    )
    await session.commit()

    await content_encryption.migrate_chunk_content(
        session, old_key, new_key, target_encrypted=False
    )
    await session.commit()

    content, encrypted = await _row(session, chunk_id)
    assert encrypted is False
    assert content == "Confidential terms apply."


async def test_a_row_with_cleared_content_is_never_touched(
    session: AsyncSession, settings: Settings
) -> None:
    source_id = await _source(session)
    document_id = await _document(session, source_id)
    chunk_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO chunks (id, document_id, ordinal, content, content_encrypted) "
            "VALUES (:id, :document_id, 0, NULL, false)"
        ),
        {"id": chunk_id, "document_id": document_id},
    )
    await session.commit()

    install_secret = crypto.load_or_create_install_secret(settings.install_secret_path)
    old_key = crypto.derive_key(install_secret)
    new_key = crypto.derive_key(install_secret, "correct horse battery staple")

    await content_encryption.migrate_chunk_content(session, old_key, new_key, target_encrypted=True)
    await session.commit()

    content, encrypted = await _row(session, chunk_id)
    assert content is None
    assert encrypted is False


async def test_assert_not_migrating_refuses_a_concurrent_call(
    session: AsyncSession,
) -> None:
    assert await content_encryption.is_migrating(session) is False
    await content_encryption.assert_not_migrating(session)

    from askwell.settings_store import set_setting

    await set_setting(session, content_encryption.STATE_KEY, content_encryption.STATE_MIGRATING)
    await session.commit()

    with pytest.raises(content_encryption.MigrationInProgress):
        await content_encryption.assert_not_migrating(session)


async def test_migration_progress_reports_migrated_of_total(
    session: AsyncSession, settings: Settings
) -> None:
    source_id = await _source(session)
    document_id = await _document(session, source_id)
    for index in range(4):
        await _chunk(session, document_id, f"passage {index}", index)
    await session.commit()

    idle = await content_encryption.migration_progress(session)
    assert idle == {"migrating": False, "migrated": 4, "total": 4}

    install_secret = crypto.load_or_create_install_secret(settings.install_secret_path)
    old_key = crypto.derive_key(install_secret)
    new_key = crypto.derive_key(install_secret, "correct horse battery staple")
    await content_encryption.migrate_chunk_content(session, old_key, new_key, target_encrypted=True)
    await session.commit()

    finished = await content_encryption.migration_progress(session)
    assert finished == {"migrating": False, "migrated": 4, "total": 4}
