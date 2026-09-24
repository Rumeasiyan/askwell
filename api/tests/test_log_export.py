"""Log export: the job, the file it produces, and the standalone verifier.
`docs/audit-log.md` §5, ticket `M7-LOG-BE-155`.

Against a real Postgres, like `test_reapply.py` — `run_job` opens several
short transactions of its own and needs a `factory`, not a single `session`.

The verifier is run as a real subprocess against the exact bundled source
(`askwell.log_export_verifier.SOURCE`), never imported — importing it would
prove nothing about the copy that actually ships, and the whole point of a
standalone verifier is that it works without `askwell` on the path at all.
"""

import json
import subprocess
import sys
import uuid
import zipfile
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from askwell import log_export, passphrase
from askwell.audit import Store, record
from askwell.config import Settings
from askwell.log_export import (
    ExportNotAcknowledged,
    InvalidRange,
    enqueue,
    get_job,
    run_job,
)

pytestmark = pytest.mark.requires_db

TABLES = (
    "audit_decisions, audit_interactions, export_jobs, settings, "
    "roots, sources, memory, conversations"
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
        export_dir=tmp_path / "exports",
        trace_dir=tmp_path / "traces",
    )


async def _seed(session: AsyncSession, store: Store, n: int) -> None:
    for i in range(n):
        await record(session, store, "test_kind", {"i": i})
    await session.commit()


async def _run(
    sessions: async_sessionmaker[AsyncSession], settings: Settings, job_id: uuid.UUID
) -> None:
    await run_job(sessions, settings, job_id)


def _extract(zip_path: Path, dest: Path) -> Path:
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(dest)
    return dest


def _run_verifier(export_dir: Path) -> subprocess.CompletedProcess[str]:
    verifier = export_dir / "verify.py"
    return subprocess.run(
        [sys.executable, str(verifier), str(export_dir)],
        capture_output=True,
        text=True,
        timeout=30,
    )


async def test_enqueue_writes_a_decisions_record_naming_the_range(session: AsyncSession) -> None:
    since = datetime(2026, 1, 1, tzinfo=UTC)
    job_id = await enqueue(session, since=since, until=None, acknowledged_decrypted_export=False)
    await session.commit()

    row = (
        await session.execute(
            text("SELECT payload FROM audit_decisions WHERE kind = 'log_export_enqueued'")
        )
    ).first()
    assert row is not None
    assert row[0]["job_id"] == str(job_id)
    assert row[0]["since"] == since.isoformat()
    assert row[0]["until"] is None


async def test_since_after_until_is_refused(session: AsyncSession) -> None:
    with pytest.raises(InvalidRange):
        await enqueue(
            session,
            since=datetime(2026, 6, 1, tzinfo=UTC),
            until=datetime(2026, 1, 1, tzinfo=UTC),
            acknowledged_decrypted_export=False,
        )


async def test_export_with_a_passphrase_set_requires_acknowledgement(
    session: AsyncSession, settings: Settings
) -> None:
    await passphrase.set_passphrase(
        session, settings, "correct horse battery staple", acknowledged_no_recovery=True
    )
    await session.commit()

    with pytest.raises(ExportNotAcknowledged):
        await enqueue(session, since=None, until=None, acknowledged_decrypted_export=False)

    # Acknowledged, it proceeds.
    job_id = await enqueue(session, since=None, until=None, acknowledged_decrypted_export=True)
    assert job_id is not None


async def test_a_full_export_round_trips_through_the_bundled_verifier(
    factory: async_sessionmaker[AsyncSession], settings: Settings, tmp_path: Path
) -> None:
    async with factory() as session:
        await _seed(session, Store.DECISIONS, 5)
        await _seed(session, Store.INTERACTIONS, 7)
        job_id = await enqueue(session, since=None, until=None, acknowledged_decrypted_export=False)
        await session.commit()

    await _run(factory, settings, job_id)

    # `enqueue` itself writes a `log_export_enqueued` decisions record
    # (the ticket's own Audit Requirement), which lands inside this run's
    # own snapshot window — one more than the five seeded above.
    expected_decisions = 6

    async with factory() as session:
        job = await get_job(session, job_id)
    assert job is not None
    assert job.status == "done"
    assert job.decisions_done == job.decisions_total == expected_decisions
    assert job.interactions_done == job.interactions_total == 7
    assert job.file_bytes is not None and job.file_bytes > 0

    zip_path = settings.export_dir / f"askwell-log-export-{job_id}.zip"
    assert zip_path.exists()
    extracted = _extract(zip_path, tmp_path / "extracted")

    manifest = json.loads((extracted / "manifest.json").read_text())
    assert manifest["stores"]["decisions"]["record_count"] == expected_decisions
    assert manifest["stores"]["interactions"]["record_count"] == 7
    # A full export starts at the universal genesis value, not a windowed one.
    assert manifest["stores"]["decisions"]["first_prev_hash"] == "0" * 64

    result = _run_verifier(extracted)
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"decisions: {expected_decisions} records, chain intact." in result.stdout
    assert "interactions: 7 records, chain intact." in result.stdout


async def test_the_verifier_names_an_altered_record(
    factory: async_sessionmaker[AsyncSession], settings: Settings, tmp_path: Path
) -> None:
    async with factory() as session:
        await _seed(session, Store.DECISIONS, 3)
        job_id = await enqueue(session, since=None, until=None, acknowledged_decrypted_export=False)
        await session.commit()

    await _run(factory, settings, job_id)

    zip_path = settings.export_dir / f"askwell-log-export-{job_id}.zip"
    extracted = _extract(zip_path, tmp_path / "extracted")

    lines = (extracted / "decisions.jsonl").read_text().splitlines()
    tampered = json.loads(lines[1])
    tampered["payload"] = {"i": "tampered"}
    lines[1] = json.dumps(tampered)
    (extracted / "decisions.jsonl").write_text("\n".join(lines) + "\n")

    result = _run_verifier(extracted)
    assert result.returncode == 1
    assert "hashes to" in result.stdout
    assert "were altered after export" in result.stdout


async def test_a_date_filtered_export_is_not_expected_to_chain_to_genesis(
    factory: async_sessionmaker[AsyncSession], settings: Settings, tmp_path: Path
) -> None:
    async with factory() as session:
        await _seed(session, Store.DECISIONS, 4)
        # The database's own clock, not the test process's — the two can
        # disagree in a containerized setup, and the boundary has to be
        # unambiguous against whatever `record()` actually stamped.
        last_occurred_at = (
            await session.execute(text("SELECT max(occurred_at) FROM audit_decisions"))
        ).scalar_one()
        cutoff = last_occurred_at + timedelta(microseconds=1)
        await _seed(session, Store.DECISIONS, 3)
        job_id = await enqueue(
            session, since=cutoff, until=None, acknowledged_decrypted_export=False
        )
        await session.commit()

    await _run(factory, settings, job_id)

    async with factory() as session:
        job = await get_job(session, job_id)
    assert job is not None
    # The 3 seeded after the cutoff, plus `enqueue`'s own decisions record,
    # which is also stamped after it — 4, not the 4 seeded before it.
    assert job.decisions_total == 4

    zip_path = settings.export_dir / f"askwell-log-export-{job_id}.zip"
    extracted = _extract(zip_path, tmp_path / "extracted")
    manifest = json.loads((extracted / "manifest.json").read_text())
    assert manifest["stores"]["decisions"]["first_prev_hash"] != "0" * 64

    result = _run_verifier(extracted)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "date-filtered" in result.stdout


async def test_a_rerun_after_interruption_leaves_no_stale_partial_file(
    factory: async_sessionmaker[AsyncSession], settings: Settings, tmp_path: Path
) -> None:
    """Simulates a crash mid-write: a `.tmp` file left behind, and the job
    still `running`, exactly what `askwell.worker.startup`'s `resume` would
    hand back to `queued`. Re-running `run_job` must produce a correct,
    complete file rather than trusting or appending to what was there."""
    async with factory() as session:
        await _seed(session, Store.DECISIONS, 6)
        job_id = await enqueue(session, since=None, until=None, acknowledged_decrypted_export=False)
        await session.commit()

    job_dir = settings.export_dir / str(job_id)
    job_dir.mkdir(parents=True)
    (job_dir / "decisions.jsonl.tmp").write_text('{"broken')  # a crash mid-write

    async with factory() as session:
        await session.execute(
            text("UPDATE export_jobs SET status = 'running' WHERE id = :id"), {"id": job_id}
        )
        await session.commit()
        resumed = await log_export.resume(session)
        await session.commit()
    assert job_id in resumed

    await _run(factory, settings, job_id)

    async with factory() as session:
        job = await get_job(session, job_id)
    assert job is not None
    assert job.status == "done"
    # The 6 seeded, plus `enqueue`'s own decisions record.
    assert job.decisions_done == 7
    assert not job_dir.exists()  # cleaned up after zipping

    zip_path = settings.export_dir / f"askwell-log-export-{job_id}.zip"
    extracted = _extract(zip_path, tmp_path / "extracted")
    result = _run_verifier(extracted)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "decisions: 7 records, chain intact." in result.stdout


async def test_an_empty_log_still_produces_a_valid_export(
    factory: async_sessionmaker[AsyncSession], settings: Settings, tmp_path: Path
) -> None:
    async with factory() as session:
        job_id = await enqueue(session, since=None, until=None, acknowledged_decrypted_export=False)
        await session.commit()

    await _run(factory, settings, job_id)

    zip_path = settings.export_dir / f"askwell-log-export-{job_id}.zip"
    extracted = _extract(zip_path, tmp_path / "extracted")
    result = _run_verifier(extracted)
    assert result.returncode == 0, result.stdout + result.stderr


async def test_a_failed_job_records_the_error(
    factory: async_sessionmaker[AsyncSession], settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with factory() as session:
        job_id = await enqueue(session, since=None, until=None, acknowledged_decrypted_export=False)
        await session.commit()

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("disk exploded")

    monkeypatch.setattr(log_export.zipfile, "ZipFile", _boom)

    with pytest.raises(RuntimeError):
        await _run(factory, settings, job_id)

    async with factory() as session:
        job = await get_job(session, job_id)
    assert job is not None
    assert job.status == "failed"
    assert job.error is not None and "disk exploded" in job.error


# --- export everything: M7-DATA-FE-160 ---------------------------------------


async def _seed_everything(session: AsyncSession) -> uuid.UUID:
    await session.execute(text("INSERT INTO roots (path) VALUES ('/home/me/contracts')"))
    await session.execute(
        text(
            "INSERT INTO sources (kind, name, config_encrypted) "
            "VALUES ('connection', 'crm', 'secret-ciphertext'::bytea)"
        )
    )
    await session.execute(
        text(
            "INSERT INTO memory (subject, fact, origin) "
            "VALUES ('notice period', 'Ninety days for the Hendry lease.', 'clarification')"
        )
    )
    conversation = uuid.uuid4()
    await session.execute(text("INSERT INTO conversations (id) VALUES (:id)"), {"id": conversation})
    message = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO messages (id, conversation_id, role, content) "
            "VALUES (:m, :c, 'user', 'What is the notice period?')"
        ),
        {"m": message, "c": conversation},
    )
    await record(session, Store.INTERACTIONS, "question_asked", {"q": "notice period"})
    await session.commit()
    return message


def _lines(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


async def test_export_everything_writes_every_part_in_open_formats(
    factory: async_sessionmaker[AsyncSession], settings: Settings, tmp_path: Path
) -> None:
    async with factory() as session:
        message = await _seed_everything(session)
    settings.trace_dir.mkdir()
    (settings.trace_dir / f"{message}.trace.json").write_text('{"steps": []}')

    async with factory() as session:
        job_id = await enqueue(
            session,
            since=None,
            until=None,
            acknowledged_decrypted_export=False,
            scope=log_export.SCOPE_EVERYTHING,
        )
        await session.commit()
    await _run(factory, settings, job_id)

    async with factory() as session:
        job = await get_job(session, job_id)
    assert job is not None and job.status == "done", job
    assert job.scope == "everything"

    extracted = _extract(
        settings.export_dir / f"askwell-export-{job_id}.zip", tmp_path / "extracted"
    )
    data = extracted / "data"
    assert _lines(data / "memory.jsonl")[0]["fact"] == "Ninety days for the Hendry lease."
    assert _lines(data / "messages.jsonl")[0]["content"] == "What is the notice period?"
    assert len(_lines(data / "conversations.jsonl")) == 1
    assert _lines(data / "roots.jsonl")[0]["path"] == "/home/me/contracts"
    source = _lines(data / "sources.jsonl")[0]
    assert source["name"] == "crm"
    assert "config_encrypted" not in source  # a credential never leaves in plaintext
    for table in log_export._EVERYTHING_TABLES:
        assert (data / f"{table}.jsonl").exists(), table

    assert (extracted / "traces" / f"{message}.trace.json").read_text() == '{"steps": []}'

    readme = (extracted / "README.txt").read_text(encoding="utf-8")
    for table in log_export._EVERYTHING_TABLES:
        assert f"{table}.jsonl" in readme, table
    assert "Your own files are not copied" in readme

    manifest = json.loads((extracted / "manifest.json").read_text())
    assert manifest["scope"] == "everything"
    assert manifest["data"]["memory"]["record_count"] == 1
    assert manifest["traces"]["file_count"] == 1
    assert "connection_credentials" in manifest["excluded"]

    # The log inside it is the same log, and still verifies on its own.
    result = _run_verifier(extracted)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "interactions: 1 records, chain intact." in result.stdout


async def test_export_everything_is_its_own_decisions_record(session: AsyncSession) -> None:
    job_id = await enqueue(
        session,
        since=None,
        until=None,
        acknowledged_decrypted_export=False,
        scope=log_export.SCOPE_EVERYTHING,
    )
    await session.commit()
    kinds = (await session.execute(text("SELECT kind, payload FROM audit_decisions"))).all()
    assert [(kind, payload["job_id"]) for kind, payload in kinds] == [
        ("export_everything_enqueued", str(job_id))
    ]


async def test_export_everything_with_a_passphrase_set_warns_before_writing(
    session: AsyncSession, settings: Settings
) -> None:
    await passphrase.set_passphrase(
        session, settings, "correct horse battery staple", acknowledged_no_recovery=True
    )
    await session.commit()

    with pytest.raises(ExportNotAcknowledged):
        await enqueue(
            session,
            since=None,
            until=None,
            acknowledged_decrypted_export=False,
            scope=log_export.SCOPE_EVERYTHING,
        )
    await session.rollback()
    jobs = (await session.execute(text("SELECT count(*) FROM export_jobs"))).scalar_one()
    assert jobs == 0  # refused before anything was written

    await enqueue(
        session,
        since=None,
        until=None,
        acknowledged_decrypted_export=True,
        scope=log_export.SCOPE_EVERYTHING,
    )


async def test_an_unknown_scope_is_refused(session: AsyncSession) -> None:
    with pytest.raises(ValueError):
        await enqueue(
            session, since=None, until=None, acknowledged_decrypted_export=False, scope="some"
        )


def test_every_table_is_either_exported_or_stated_as_left_out() -> None:
    """ "Genuinely complete" (`M7-DATA-FE-160`): a table added later must be
    exported or named in the README's "Not included", never silently absent."""
    from askwell import reset

    stated_out = {
        "chunks": "chunks",
        "document_pages": "chunks",
        "settings": "settings",
        "ingest_jobs": "job_bookkeeping",
        "reapply_jobs": "job_bookkeeping",
        "reapply_items": "job_bookkeeping",
        "export_jobs": "job_bookkeeping",
        "backup_jobs": "job_bookkeeping",
        "restore_jobs": "job_bookkeeping",
        "prune_jobs": "job_bookkeeping",
    }
    for table in reset.TABLES:
        if table in log_export._EVERYTHING_TABLES:
            continue
        assert table in stated_out, f"{table} is neither exported nor stated as left out"
        assert stated_out[table] in log_export._EVERYTHING_EXCLUDED, table
