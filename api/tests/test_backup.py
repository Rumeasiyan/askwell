"""Backup: the job, the artefact it produces, and the exclusion rule.
`docs/build-plan.md`, ticket `M7-BACKUP-BE-157`.

Against a real Postgres, like `test_log_export.py` — `run_job` opens its own
long-lived `REPEATABLE READ` transaction plus several short ones for
progress, and needs a `factory`, not a single `session`.
"""

import json
import uuid
import zipfile
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from askwell import backup, content_encryption, passphrase
from askwell.backup import (
    InsufficientSpace,
    PassphraseRequired,
    enqueue,
    estimate,
    get_job,
    run_job,
)
from askwell.config import Settings
from askwell.settings_store import set_setting

pytestmark = pytest.mark.requires_db

TABLES = (
    "roots, sources, documents, document_pages, chunks, memory, schema_notes, "
    "clarifications, conversations, messages, fact_usage, citations, settings, "
    "audit_decisions, audit_interactions, backup_jobs"
)


@pytest_asyncio.fixture
async def factory(database_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    async_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_async_engine(async_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as opened:
        await opened.execute(text(f"TRUNCATE {TABLES} CASCADE"))
        await opened.commit()
    yield sessions
    async with sessions() as opened:
        await opened.execute(text(f"TRUNCATE {TABLES} CASCADE"))
        await opened.commit()
    await engine.dispose()


@pytest_asyncio.fixture
async def session(factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with factory() as opened:
        yield opened
        await opened.rollback()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url="postgresql://askwell:pw@127.0.0.1:1/askwell",  # type: ignore[arg-type]
        sandbox_database_url="postgresql://x:x@127.0.0.1:1/postgres",  # type: ignore[arg-type]
        sandbox_owner_password="pw",  # type: ignore[arg-type]
        sandbox_readonly_password="pw",  # type: ignore[arg-type]
        backup_dir=tmp_path / "backups",
        install_secret_path=tmp_path / "install.key",
    )


def _embedding_literal(dimensions: int = 1024) -> str:
    return "[" + ",".join("0.1" for _ in range(dimensions)) + "]"


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


async def _chunk_with_embedding(
    session: AsyncSession, document_id: uuid.UUID, content: str, ordinal: int = 0
) -> uuid.UUID:
    chunk_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO chunks (id, document_id, ordinal, content, content_tsv, embedding) "
            "VALUES (:id, :document_id, :ordinal, :content, "
            "to_tsvector('english', :content), :embedding)"
        ),
        {
            "id": chunk_id,
            "document_id": document_id,
            "ordinal": ordinal,
            "content": content,
            "embedding": _embedding_literal(),
        },
    )
    return chunk_id


def _extract(zip_path: Path, dest: Path) -> Path:
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(dest)
    return dest


async def test_enqueue_writes_a_decisions_record_naming_the_job(
    session: AsyncSession, settings: Settings
) -> None:
    job_id = await enqueue(session, settings)
    await session.commit()

    row = (
        await session.execute(
            text("SELECT payload FROM audit_decisions WHERE kind = 'backup_job_enqueued'")
        )
    ).first()
    assert row is not None
    assert row[0]["job_id"] == str(job_id)
    assert row[0]["chunk_count"] == 0
    assert row[0]["passphrase_protected"] is False


async def test_a_migration_in_progress_refuses_the_backup(
    session: AsyncSession, settings: Settings
) -> None:
    await set_setting(session, content_encryption.STATE_KEY, content_encryption.STATE_MIGRATING)
    await session.commit()

    with pytest.raises(content_encryption.MigrationInProgress):
        await enqueue(session, settings)


async def test_a_protected_corpus_refuses_a_backup_with_no_passphrase(
    session: AsyncSession, settings: Settings
) -> None:
    await passphrase.set_passphrase(
        session, settings, "correct horse battery staple", acknowledged_no_recovery=True
    )
    await session.commit()

    with pytest.raises(PassphraseRequired):
        await enqueue(session, settings)


async def test_insufficient_space_is_refused_before_starting(
    session: AsyncSession, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_id = await _source(session)
    document_id = await _document(session, source_id)
    await _chunk_with_embedding(session, document_id, "some content")
    await session.commit()

    class _Usage:
        free = 1  # far below anything this backup could need

    monkeypatch.setattr(backup.shutil, "disk_usage", lambda _path: _Usage())

    with pytest.raises(InsufficientSpace) as excinfo:
        await enqueue(session, settings)
    assert excinfo.value.free_bytes == 1
    assert excinfo.value.needed_bytes > 0


async def test_estimate_excludes_vector_bytes_and_counts_embeddable_chunks(
    session: AsyncSession, settings: Settings
) -> None:
    source_id = await _source(session)
    document_id = await _document(session, source_id)
    await _chunk_with_embedding(session, document_id, "alpha")
    await _chunk_with_embedding(session, document_id, "beta")
    await session.commit()

    preflight = await estimate(session, settings)
    assert preflight.chunk_count == 2
    assert preflight.estimated_reembed_seconds == 2 / backup.ESTIMATED_CHUNKS_PER_SECOND
    assert preflight.passphrase_protected is False


async def test_a_full_backup_excludes_weights_traces_and_the_vector_index(
    factory: async_sessionmaker[AsyncSession], settings: Settings, tmp_path: Path
) -> None:
    async with factory() as session:
        source_id = await _source(session)
        document_id = await _document(session, source_id)
        await _chunk_with_embedding(session, document_id, "the quick brown fox")
        await session.execute(
            text("INSERT INTO memory (subject, fact, origin) VALUES ('x', 'y', 'manual')")
        )
        job_id = await enqueue(session, settings)
        await session.commit()

    await run_job(factory, settings, job_id)

    async with factory() as session:
        job = await get_job(session, job_id)
    assert job is not None
    assert job.status == "done"
    assert job.chunk_count == 1
    assert job.file_bytes is not None and job.file_bytes > 0
    assert job.tables_done == job.tables_total

    zip_path = settings.backup_dir / f"askwell-backup-{job_id}.zip"
    assert zip_path.exists()
    extracted = _extract(zip_path, tmp_path / "extracted")

    manifest = json.loads((extracted / "manifest.json").read_text())
    assert manifest["chunk_count"] == 1
    assert manifest["user_files_included"] is False
    assert "vector_index" in manifest["excluded"]
    assert "trace_ring_buffer" in manifest["excluded"]
    assert "model_weights" in manifest["excluded"]
    assert manifest["tables"]["chunks"]["excluded_columns"] == ["embedding"]
    assert manifest["tables"]["memory"]["record_count"] == 1

    chunk_lines = (extracted / "chunks.jsonl").read_text().splitlines()
    assert len(chunk_lines) == 1
    dumped_chunk = json.loads(chunk_lines[0])
    assert "embedding" not in dumped_chunk
    assert dumped_chunk["content"] == "the quick brown fox"
    # content_tsv is a different index (full-text, not vector) and is not
    # excluded — module docstring.
    assert "content_tsv" in dumped_chunk

    # No trace files, and no model weight files, ever land in the artefact.
    assert not (extracted / "traces").exists()
    assert not any("weight" in path.name for path in extracted.iterdir())


async def test_a_passphrase_protected_backup_states_it_plainly(
    factory: async_sessionmaker[AsyncSession], settings: Settings, tmp_path: Path
) -> None:
    async with factory() as session:
        await passphrase.set_passphrase(
            session, settings, "correct horse battery staple", acknowledged_no_recovery=True
        )
        await session.commit()
        job_id = await enqueue(session, settings, "correct horse battery staple")
        await session.commit()

    async with factory() as session:
        job = await get_job(session, job_id)
    assert job is not None
    assert job.passphrase_protected is True

    await run_job(factory, settings, job_id)

    zip_path = settings.backup_dir / f"askwell-backup-{job_id}.zip"
    extracted = _extract(zip_path, tmp_path / "extracted")
    manifest = json.loads((extracted / "manifest.json").read_text())
    assert manifest["install_secret_wrapped"] is not None
    assert manifest["passphrase_protected"] is True
