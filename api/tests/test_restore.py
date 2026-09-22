"""Restore: version refusal, passphrase handling, resume, re-embed. `M7-BACKUP-BE-158`.

Against a real Postgres, like `test_backup.py` — restore reads and writes
across the whole table set inside its own transactions.
"""

import asyncio
import json
import re
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from askwell import passphrase, restore
from askwell.backup import enqueue as backup_enqueue
from askwell.backup import run_job as backup_run_job
from askwell.config import Settings
from askwell.restore import (
    ExistingDataPresent,
    IncorrectPassphrase,
    PassphraseRequired,
    VersionRefused,
    enqueue,
    get_job,
    inspect_artefact,
    run_job,
)

pytestmark = pytest.mark.requires_db

TABLES = (
    "roots, sources, documents, document_pages, chunks, memory, schema_notes, "
    "clarifications, conversations, messages, fact_usage, citations, settings, "
    "audit_decisions, audit_interactions, backup_jobs, restore_jobs"
)


async def _reset_to_clean_machine(factory: async_sessionmaker[AsyncSession]) -> None:
    """Simulate restoring onto genuinely different, empty hardware.

    Every test here shares one physical database between "the machine the
    backup came from" and "the machine being restored onto" — `_make_backup`
    itself writes to `audit_decisions` (`askwell.backup.enqueue`'s own
    decisions record), so without this, restore would collide with rows its
    own setup just wrote, which cannot happen against two actually separate
    databases. Real superuser `TRUNCATE`, not `askwell_app`'s restricted
    `DELETE` — this fixture connects with the same privileges
    `conftest_db.database_url` migrates with, not the application's own.
    """
    async with factory() as opened:
        await opened.execute(text(f"TRUNCATE {TABLES} CASCADE"))
        await opened.commit()


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
def settings(tmp_path: Path, database_url: str) -> Settings:
    return Settings(
        database_url=database_url,  # type: ignore[arg-type]
        sandbox_database_url="postgresql://x:x@127.0.0.1:1/postgres",  # type: ignore[arg-type]
        sandbox_owner_password="pw",  # type: ignore[arg-type]
        sandbox_readonly_password="pw",  # type: ignore[arg-type]
        backup_dir=tmp_path / "backups",
        install_secret_path=tmp_path / "install.key",
        inference_socket=tmp_path / "inference.sock",
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


async def _make_backup(
    factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    *,
    content: str = "the quick brown fox",
    backup_passphrase: str | None = None,
) -> Path:
    async with factory() as session:
        source_id = await _source(session)
        document_id = await _document(session, source_id)
        await _chunk_with_embedding(session, document_id, content)
        await session.execute(
            text("INSERT INTO memory (subject, fact, origin) VALUES ('x', 'y', 'manual')")
        )
        job_id = await backup_enqueue(session, settings, backup_passphrase)
        await session.commit()
    await backup_run_job(factory, settings, job_id)
    return settings.backup_dir / f"askwell-backup-{job_id}.zip"


def _ready(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "state.json").write_text(
        json.dumps({"state": "ready", "model": "a-model.gguf", "acceleration": "cpu"}),
        encoding="utf-8",
    )


class _EmbeddingStub:
    """Answers every embed request with a fixed vector — restore's re-embed
    phase does not need a real model, only something at the socket."""

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        head = await reader.readuntil(b"\r\n\r\n")
        length = 0
        match = re.search(rb"content-length:\s*(\d+)", head, re.I)
        if match:
            length = int(match.group(1))
        body_in = await reader.readexactly(length) if length else await reader.read(0)
        count = len(json.loads(body_in)["input"]) if body_in else 1
        vectors = [[0.2] * 1024 for _ in range(count)]
        body = json.dumps({"data": [{"embedding": v} for v in vectors]}).encode()
        writer.write(
            f"HTTP/1.1 200 X\r\nContent-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode()
            + body
        )
        await writer.drain()
        writer.close()


@pytest_asyncio.fixture
async def inference_serving(settings: Settings) -> AsyncIterator[None]:
    _ready(settings.inference_socket.parent)
    stub = _EmbeddingStub()
    server = await asyncio.start_unix_server(stub.handle, path=str(settings.inference_socket))
    yield
    server.close()
    await server.wait_closed()


# --- inspect -----------------------------------------------------------


async def test_inspect_reports_version_and_reembed_cost(
    factory: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    path = await _make_backup(factory, settings)
    manifest = inspect_artefact(path)
    assert manifest.chunk_count == 1
    assert manifest.passphrase_protected is False
    assert manifest.askwell_version


async def test_inspect_refuses_a_newer_backup(
    factory: async_sessionmaker[AsyncSession], settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = await _make_backup(factory, settings)
    manifest_path = path
    # Rewrite the artefact's manifest to claim a future version.
    import zipfile

    data = json.loads(zipfile.ZipFile(manifest_path).read("manifest.json"))
    data["askwell_version"] = "999.0.0"
    with zipfile.ZipFile(manifest_path, "a") as archive:
        archive.writestr("manifest.json", json.dumps(data))

    with pytest.raises(VersionRefused):
        inspect_artefact(path)


# --- enqueue -------------------------------------------------------------


async def test_enqueue_refuses_existing_data_without_replace_existing(
    session: AsyncSession, factory: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    path = await _make_backup(factory, settings)
    async with factory() as populate:
        await _source(populate)
        await populate.commit()

    with pytest.raises(ExistingDataPresent):
        await enqueue(session, settings, path=path, restore_passphrase=None, replace_existing=False)


async def test_enqueue_requires_passphrase_when_protected(
    session: AsyncSession, factory: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    async with factory() as unlocking:
        await passphrase.set_passphrase(
            unlocking, settings, "correct horse battery staple", acknowledged_no_recovery=True
        )
        await unlocking.commit()
    path = await _make_backup(factory, settings, backup_passphrase="correct horse battery staple")

    with pytest.raises(PassphraseRequired):
        await enqueue(session, settings, path=path, restore_passphrase=None, replace_existing=True)


# --- full round trip -----------------------------------------------------


async def test_a_full_restore_recovers_rows_and_reembeds(
    factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    inference_serving: None,
) -> None:
    path = await _make_backup(factory, settings, content="alpha beta gamma")
    await _reset_to_clean_machine(factory)

    async with factory() as session:
        job_id = await enqueue(
            session, settings, path=path, restore_passphrase=None, replace_existing=False
        )
        await session.commit()

    await run_job(factory, settings, job_id, None)

    async with factory() as session:
        job = await get_job(session, job_id)
        assert job is not None
        assert job.status == "done"
        assert job.chain_verified is True

        memory_row = (await session.execute(text("SELECT fact FROM memory"))).scalar_one()
        assert memory_row == "y"

        chunk_row = (await session.execute(text("SELECT content, embedding FROM chunks"))).first()
        assert chunk_row is not None
        assert chunk_row[0] == "alpha beta gamma"
        assert chunk_row[1] is not None  # re-embedded


async def test_replace_existing_clears_prior_non_audit_data(
    factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    inference_serving: None,
) -> None:
    path = await _make_backup(factory, settings, content="one true backup")
    await _reset_to_clean_machine(factory)

    async with factory() as populate:
        await _source(populate)  # a different, unrelated row already present
        await populate.commit()

    async with factory() as session:
        job_id = await enqueue(
            session, settings, path=path, restore_passphrase=None, replace_existing=True
        )
        await session.commit()

    await run_job(factory, settings, job_id, None)

    async with factory() as session:
        job = await get_job(session, job_id)
        assert job is not None
        assert job.status == "done"
        sources_count = (await session.execute(text("SELECT count(*) FROM sources"))).scalar_one()
        assert sources_count == 1  # the pre-existing row was cleared, the restored one remains


async def test_replace_existing_never_clears_or_blocks_on_audit_history(
    factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    inference_serving: None,
) -> None:
    """`audit_decisions`/`audit_interactions` are excluded from both the
    "existing data" refusal and the clear — `askwell_app` has no grant to
    empty them (C6), and `enqueue` itself writes one before this test's own
    manually-inserted row even lands. Module docstring's "the audit stores
    are a deliberate exception"."""
    path = await _make_backup(factory, settings)
    await _reset_to_clean_machine(factory)

    async with factory() as populate:
        await populate.execute(
            text(
                "INSERT INTO audit_decisions (id, kind, payload, hash) "
                "VALUES (gen_random_uuid(), 'k', '{}'::jsonb, 'h')"
            )
        )
        await populate.commit()

    async with factory() as session:
        job_id = await enqueue(
            session, settings, path=path, restore_passphrase=None, replace_existing=True
        )
        await session.commit()

    await run_job(factory, settings, job_id, None)

    async with factory() as session:
        job = await get_job(session, job_id)
        assert job is not None
        assert job.status == "done"
        # The pre-existing row was never deleted — no grant to do it with —
        # and the backup's own decisions rows were appended alongside it.
        count = (await session.execute(text("SELECT count(*) FROM audit_decisions"))).scalar_one()
    assert count >= 2


# --- resume --------------------------------------------------------------


async def test_a_crash_mid_restore_resumes_without_re_inserting_committed_tables(
    factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    inference_serving: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #571: a retry used to re-run every table from scratch, and a
    table already committed on the first attempt raised a unique-violation
    on retry — `run_job`'s `tables_done` gate is the fix. Simulate the crash
    by making `_restore_table` fail the first time it is asked for `chunks`
    (after `sources`/`documents`, its own dependencies, have already
    committed), then call `run_job` again for the same job and confirm it
    finishes rather than re-attempting an already-restored table.
    """
    path = await _make_backup(factory, settings, content="resume me")
    await _reset_to_clean_machine(factory)

    async with factory() as session:
        job_id = await enqueue(
            session, settings, path=path, restore_passphrase=None, replace_existing=False
        )
        await session.commit()

    real_restore_table = restore._restore_table
    failed_once = False

    async def _flaky_restore_table(session: AsyncSession, table: str, job_dir: Path) -> int:
        nonlocal failed_once
        if table == "chunks" and not failed_once:
            failed_once = True
            raise RuntimeError("simulated crash mid-restore")
        return await real_restore_table(session, table, job_dir)

    monkeypatch.setattr(restore, "_restore_table", _flaky_restore_table)

    with pytest.raises(RuntimeError, match="simulated crash mid-restore"):
        await run_job(factory, settings, job_id, None)

    async with factory() as session:
        job = await get_job(session, job_id)
    assert job is not None
    assert job.status == "failed"
    assert job.tables_done >= 2  # roots, sources, documents already committed
    documents_committed_once = job.tables_done

    # The resume: a second `run_job` call for the same job, same as what
    # `askwell.worker.startup`'s dispatch of a `resume()`-returned job does.
    await run_job(factory, settings, job_id, None)

    async with factory() as session:
        job = await get_job(session, job_id)
        assert job is not None
        assert job.status == "done"
        # Restored once, not twice — a re-insert of `documents`/`sources`
        # would have raised a unique-violation before reaching here at all.
        chunk_count = (await session.execute(text("SELECT count(*) FROM chunks"))).scalar_one()
    assert chunk_count == 1
    assert job.tables_done > documents_committed_once


# --- passphrase ------------------------------------------------------------


async def test_restore_refuses_an_incorrect_passphrase(
    factory: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    async with factory() as unlocking:
        await passphrase.set_passphrase(
            unlocking, settings, "correct horse battery staple", acknowledged_no_recovery=True
        )
        await unlocking.commit()
    path = await _make_backup(factory, settings, backup_passphrase="correct horse battery staple")

    async with factory() as session:
        job_id = await enqueue(
            session,
            settings,
            path=path,
            restore_passphrase="correct horse battery staple",
            replace_existing=True,
        )
        await session.commit()

    with pytest.raises(IncorrectPassphrase):
        await run_job(factory, settings, job_id, "wrong passphrase entirely")

    async with factory() as session:
        job = await get_job(session, job_id)
    assert job is not None
    assert job.status == "failed"


async def test_restore_recovers_a_passphrase_protected_corpus_on_a_new_install_secret(
    factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    tmp_path: Path,
    inference_serving: None,
) -> None:
    """The whole point of `install_secret_wrapped`: a second machine, with
    its own fresh install secret, can still decrypt content restored from a
    passphrase-protected backup — module docstring."""
    from askwell import crypto

    passphrase_text = "correct horse battery staple"
    async with factory() as unlocking:
        await passphrase.set_passphrase(
            unlocking, settings, passphrase_text, acknowledged_no_recovery=True
        )
        await unlocking.commit()

    # A chunk written *after* the passphrase was set, the way `askwell.chunk.run`
    # would actually write one — encrypted under install-secret-plus-passphrase,
    # `content_encrypted = true`. `_chunk_with_embedding` bypasses that pipeline
    # entirely, so this test builds the row directly rather than through it.
    install_secret = crypto.load_or_create_install_secret(settings.install_secret_path)
    source_key = crypto.derive_key(install_secret, passphrase_text)
    async with factory() as session:
        source_id = await _source(session)
        document_id = await _document(session, source_id)
        chunk_id = uuid.uuid4()
        ciphertext = crypto.encrypt(b"the quick brown fox", source_key).decode("ascii")
        await session.execute(
            text(
                "INSERT INTO chunks (id, document_id, ordinal, content, content_encrypted, "
                "content_tsv, embedding) VALUES (:id, :document_id, 0, :content, true, "
                "to_tsvector('english', 'the quick brown fox'), :embedding)"
            ),
            {
                "id": chunk_id,
                "document_id": document_id,
                "content": ciphertext,
                "embedding": _embedding_literal(),
            },
        )
        job_id = await backup_enqueue(session, settings, passphrase_text)
        await session.commit()
    await backup_run_job(factory, settings, job_id)
    path = settings.backup_dir / f"askwell-backup-{job_id}.zip"
    await _reset_to_clean_machine(factory)

    # Simulate a second machine: a different install secret path, currently unset.
    target_settings = settings.model_copy(
        update={"install_secret_path": tmp_path / "second-machine-install.key"}
    )
    passphrase._reset_lock_state_for_tests()

    async with factory() as session:
        job_id = await enqueue(
            session,
            target_settings,
            path=path,
            restore_passphrase=passphrase_text,
            replace_existing=True,
        )
        await session.commit()

    await run_job(factory, target_settings, job_id, passphrase_text)

    async with factory() as session:
        job = await get_job(session, job_id)
        assert job is not None
        assert job.status == "done"
        key = await passphrase.current_key(session, target_settings)
        content_encrypted = (
            await session.execute(text("SELECT content, content_encrypted FROM chunks"))
        ).first()
    assert content_encrypted is not None
    stored, is_encrypted = content_encrypted
    assert is_encrypted is True
    from askwell import crypto

    assert crypto.decrypt(stored.encode("ascii"), key).decode("utf-8") == "the quick brown fox"
