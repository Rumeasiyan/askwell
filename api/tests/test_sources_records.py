"""Source and document records against a real Postgres.

Four things can only be tested here, and each is a promise the ticket makes
rather than an implementation detail.

Adding a file **creates a row with its path and its hash**, and adding the same
content again is **recognised rather than stored twice** — the acceptance
criterion, and the reason the whole ticket exists.

Adding material is a **decision**, so it appears in the decisions audit store or
it did not happen: the audit write is in the caller's transaction and takes the
insert down with it if it fails.

And the partial unique index is the floor under the recognition rule. It is a
question about a *partial* index and cannot be answered without one — which is
the point of it being in the database rather than only in `add`.
"""

import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from askwell.sources import (
    DOCUMENT_ADDED,
    DOCUMENT_DELETED,
    DOCUMENT_SUPERSEDED,
    SOURCE_ADDED,
    SOURCE_DELETED,
    Outcome,
    SourceNotFound,
    add,
    delete_document,
    delete_source,
)

pytestmark = pytest.mark.requires_db

TABLES = "roots, sources, documents, chunks, ingest_jobs, schema_notes, memory, audit_decisions"

OCR_THRESHOLD = 0.60

PDF = b"%PDF-1.7\nEither party may terminate on ninety days written notice.\n"
OTHER = b"%PDF-1.7\nThe tenant shall pay rent monthly in advance.\n"


@pytest.fixture
def async_url(database_url: str) -> str:
    return database_url.replace("postgresql://", "postgresql+psycopg://", 1)


@pytest_asyncio.fixture
async def session(async_url: str) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(async_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as opened:
        await opened.execute(text(f"TRUNCATE {TABLES} CASCADE"))
        await opened.commit()
        yield opened
        await opened.rollback()
        await opened.execute(text(f"TRUNCATE {TABLES} CASCADE"))
        await opened.commit()
    await engine.dispose()


async def nominate(session: AsyncSession, path: str) -> None:
    """Register a root directly. `roots.register` probes the mount; this does not.

    What is under test here is the record path, and going through registration
    would make every one of these tests also a test of whether the developer's
    `ASKWELL_ROOTS_MOUNT` happens to contain `tmp_path`.
    """
    await session.execute(text("INSERT INTO roots (path) VALUES (:path)"), {"path": path})


def written(directory: Path, name: str, body: bytes = PDF) -> str:
    path = directory / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return name


async def documents(session: AsyncSession) -> list[Any]:
    result = await session.execute(
        text(
            "SELECT id, source_id, filename, path, mime, sha256, status, version, "
            "deleted_at, superseded_by FROM documents ORDER BY added_at, path"
        )
    )
    return list(result)


async def decisions(session: AsyncSession, kind: str) -> list[dict[str, object]]:
    result = await session.execute(
        text("SELECT payload FROM audit_decisions WHERE kind = :kind ORDER BY occurred_at"),
        {"kind": kind},
    )
    return [row[0] for row in result]


# --- the record path --------------------------------------------------------


async def test_adding_a_file_creates_a_document_with_its_path_and_its_hash(
    session: AsyncSession, tmp_path: Path
) -> None:
    folder = tmp_path / "clients"
    name = written(folder, "contract.pdf")
    await nominate(session, str(tmp_path))

    result = await add(session, str(folder), [name])

    assert result.count(Outcome.ADDED) == 1
    rows = await documents(session)
    assert len(rows) == 1
    assert rows[0].filename == "contract.pdf"
    assert rows[0].path == str(folder / "contract.pdf")
    assert rows[0].mime == "application/pdf"
    assert len(rows[0].sha256) == 64
    # Recorded and waiting, not "indexing": nothing is reading it yet, and
    # saying otherwise is a progress bar for work that has not started.
    assert rows[0].status == "queued"
    assert rows[0].version == 1
    assert rows[0].deleted_at is None


async def test_the_source_carries_the_folder_and_is_re_used_on_a_second_add(
    session: AsyncSession, tmp_path: Path
) -> None:
    """Adding to the same folder twice is an ordinary thing to do.

    Two sources over one folder would show the same material twice in the
    library and would make the per-source duplicate index meaningless.
    """
    folder = tmp_path / "clients"
    first = written(folder, "one.pdf", PDF)
    second = written(folder, "two.pdf", OTHER)
    await nominate(session, str(tmp_path))

    one = await add(session, str(folder), [first])
    two = await add(session, str(folder), [second])

    assert one.created_source is True
    assert two.created_source is False
    assert one.source_id == two.source_id
    assert one.source_name == "clients"

    count = await session.execute(text("SELECT count(*) FROM sources"))
    assert count.scalar_one() == 1


async def test_no_source_row_is_created_when_nothing_could_be_added(
    session: AsyncSession, tmp_path: Path
) -> None:
    """An empty source in the library holds nothing and explains nothing."""
    folder = tmp_path / "clients"
    name = written(folder, "empty.pdf", b"")
    await nominate(session, str(tmp_path))

    result = await add(session, str(folder), [name])

    assert result.count(Outcome.REFUSED) == 1
    assert result.source_id is None
    count = await session.execute(text("SELECT count(*) FROM sources"))
    assert count.scalar_one() == 0


# --- the recognition rule ---------------------------------------------------


async def test_the_same_content_under_two_names_is_recognised_and_both_paths_are_shown(
    session: AsyncSession, tmp_path: Path
) -> None:
    """The ticket's own example: `contract.pdf` and `contract copy.pdf`.

    One is indexed and the other is named as already present. Both paths reach
    the surface, because "already present" without saying *where* leaves the
    user unsure which of their copies Askwell is actually reading.
    """
    folder = tmp_path / "clients"
    first = written(folder, "contract.pdf", PDF)
    second = written(folder, "contract copy.pdf", PDF)
    await nominate(session, str(tmp_path))

    result = await add(session, str(folder), [first, second])

    assert result.count(Outcome.ADDED) == 1
    assert result.count(Outcome.DUPLICATE) == 1
    duplicate = next(item for item in result.files if item.outcome is Outcome.DUPLICATE)
    assert duplicate.existing is not None
    assert duplicate.existing.path.endswith("contract.pdf")
    assert duplicate.path.endswith("contract copy.pdf")

    assert len(await documents(session)) == 1


async def test_the_same_file_added_from_another_folder_links_to_the_existing_document(
    session: AsyncSession, tmp_path: Path
) -> None:
    """Three folders are three sources, so the check has to be global.

    A per-source check would recognise none of them and the ticket's cold-start
    walkthrough — add a PDF, then add the same PDF from a different folder —
    would create a second document.
    """
    clients = tmp_path / "clients"
    archive = tmp_path / "archive"
    written(clients, "contract.pdf", PDF)
    written(archive, "contract.pdf", PDF)
    await nominate(session, str(tmp_path))

    await add(session, str(clients), ["contract.pdf"])
    second = await add(session, str(archive), ["contract.pdf"])

    assert second.count(Outcome.DUPLICATE) == 1
    assert second.source_id is None, "nothing was added, so no second source was created"
    duplicate = second.files[0]
    assert duplicate.existing is not None
    assert duplicate.existing.path == str(clients / "contract.pdf")
    assert len(await documents(session)) == 1


async def test_different_content_under_the_same_name_is_two_documents(
    session: AsyncSession, tmp_path: Path
) -> None:
    """The other half of "by content": the name is not what decides."""
    clients = tmp_path / "clients"
    archive = tmp_path / "archive"
    written(clients, "contract.pdf", PDF)
    written(archive, "contract.pdf", OTHER)
    await nominate(session, str(tmp_path))

    await add(session, str(clients), ["contract.pdf"])
    second = await add(session, str(archive), ["contract.pdf"])

    assert second.count(Outcome.ADDED) == 1
    assert len(await documents(session)) == 2


# --- supersession: M1-INDEX-BE-034 -------------------------------------------


async def test_a_changed_file_at_the_same_path_is_offered_not_duplicated(
    session: AsyncSession, tmp_path: Path
) -> None:
    """The June-revision scenario. Nothing is recorded until it is decided."""
    folder = tmp_path / "clients"
    written(folder, "contract.pdf", PDF)
    await nominate(session, str(tmp_path))
    await add(session, str(folder), ["contract.pdf"])

    written(folder, "contract.pdf", OTHER)
    offer = await add(session, str(folder), ["contract.pdf"])

    assert offer.count(Outcome.NEW_VERSION) == 1
    assert offer.count(Outcome.ADDED) == 0
    file_result = offer.files[0]
    assert file_result.existing is not None
    assert file_result.existing.version == 1
    assert len(await documents(session)) == 1, "an offer records nothing"


async def test_accepting_the_offer_supersedes_the_old_version(
    session: AsyncSession, tmp_path: Path
) -> None:
    folder = tmp_path / "clients"
    written(folder, "contract.pdf", PDF)
    await nominate(session, str(tmp_path))
    first = await add(session, str(folder), ["contract.pdf"])
    old_id = first.files[0].document_id
    assert old_id is not None

    written(folder, "contract.pdf", OTHER)
    result = await add(session, str(folder), ["contract.pdf"], {"contract.pdf": "supersede"})

    assert result.count(Outcome.SUPERSEDED) == 1
    rows = {row.id: row for row in await documents(session)}
    assert rows[old_id].superseded_by is not None
    new_id = rows[old_id].superseded_by
    assert rows[new_id].version == 2
    assert rows[new_id].superseded_by is None
    assert rows[old_id].deleted_at is None, "supersession is not deletion"

    superseded = await decisions(session, DOCUMENT_SUPERSEDED)
    assert len(superseded) == 1
    assert superseded[0]["old_document_id"] == str(old_id)
    assert superseded[0]["new_document_id"] == str(new_id)


async def test_declining_leaves_both_versions_live(session: AsyncSession, tmp_path: Path) -> None:
    folder = tmp_path / "clients"
    written(folder, "contract.pdf", PDF)
    await nominate(session, str(tmp_path))
    first = await add(session, str(folder), ["contract.pdf"])
    old_id = first.files[0].document_id

    written(folder, "contract.pdf", OTHER)
    result = await add(session, str(folder), ["contract.pdf"], {"contract.pdf": "keep_both"})

    assert result.count(Outcome.ADDED) == 1
    rows = {row.id: row for row in await documents(session)}
    assert rows[old_id].superseded_by is None, "declined — the old version stays live"
    assert len(rows) == 2


async def test_superseding_a_superseded_document_chains_rather_than_orphans(
    session: AsyncSession, tmp_path: Path
) -> None:
    folder = tmp_path / "clients"
    written(folder, "contract.pdf", PDF)
    await nominate(session, str(tmp_path))
    v1 = await add(session, str(folder), ["contract.pdf"])
    v1_id = v1.files[0].document_id

    written(folder, "contract.pdf", OTHER)
    v2 = await add(session, str(folder), ["contract.pdf"], {"contract.pdf": "supersede"})
    v2_id = v2.files[0].document_id

    third = b"%PDF-1.7\nRent reviewed annually each January.\n"
    written(folder, "contract.pdf", third)
    v3 = await add(session, str(folder), ["contract.pdf"], {"contract.pdf": "supersede"})

    assert v3.count(Outcome.SUPERSEDED) == 1
    rows = {row.id: row for row in await documents(session)}
    assert rows[v1_id].superseded_by == v2_id
    assert rows[v2_id].superseded_by == v3.files[0].document_id
    assert rows[v3.files[0].document_id].version == 3
    assert rows[v3.files[0].document_id].superseded_by is None


async def test_a_new_path_with_identical_content_is_still_a_duplicate_not_a_version(
    session: AsyncSession, tmp_path: Path
) -> None:
    """Same content, different path — recognised by content, per the module's

    own rule, before the path-based version check ever runs.
    """
    clients = tmp_path / "clients"
    archive = tmp_path / "archive"
    written(clients, "contract.pdf", PDF)
    written(archive, "renamed.pdf", PDF)
    await nominate(session, str(tmp_path))

    await add(session, str(clients), ["contract.pdf"])
    second = await add(session, str(archive), ["renamed.pdf"])

    assert second.count(Outcome.DUPLICATE) == 1
    assert second.count(Outcome.NEW_VERSION) == 0


# --- what the database refuses ----------------------------------------------


async def test_a_second_live_row_with_the_same_source_and_hash_is_refused(
    session: AsyncSession, tmp_path: Path
) -> None:
    """The index is the floor under the recognition rule.

    `add` is what produces the user-facing sentence. This is what makes a second
    live row impossible when some later code path — an import, a retry, a repair
    — forgets to ask.
    """
    folder = tmp_path / "clients"
    written(folder, "contract.pdf", PDF)
    await nominate(session, str(tmp_path))
    result = await add(session, str(folder), ["contract.pdf"])
    row = (await documents(session))[0]

    with pytest.raises(IntegrityError, match="uq_documents_live_source_id_sha256"):
        await session.execute(
            text(
                "INSERT INTO documents (source_id, filename, path, sha256, status) "
                "VALUES (:source_id, 'copy.pdf', '/elsewhere/copy.pdf', :sha256, 'queued')"
            ),
            {"source_id": result.source_id, "sha256": row.sha256},
        )
    await session.rollback()


async def test_the_index_does_not_stop_a_deleted_document_being_added_again(
    session: AsyncSession, tmp_path: Path
) -> None:
    """Partial, over the live rows. A file deleted last week is re-addable.

    A plain unique constraint would refuse and blame the user for the deletion,
    which is the same mistake the roots registry avoids with the same shape of
    index.
    """
    folder = tmp_path / "clients"
    written(folder, "contract.pdf", PDF)
    await nominate(session, str(tmp_path))
    result = await add(session, str(folder), ["contract.pdf"])

    await session.execute(
        text(
            "UPDATE documents SET deleted_at = now(), status = 'deleted', "
            "deleted_reason = 'removed by the test'"
        )
    )
    again = await add(session, str(folder), ["contract.pdf"])

    assert again.count(Outcome.ADDED) == 1, "a deleted document must not block re-adding the file"
    assert again.source_id == result.source_id
    assert len(await documents(session)) == 2


# --- the audit --------------------------------------------------------------


async def test_adding_is_a_decisions_record_naming_the_path(
    session: AsyncSession, tmp_path: Path
) -> None:
    """`docs/audit-log.md` §2: the decisions store is what the user chose.

    "I gave Askwell these files" is exactly that, and the path is what makes the
    record answerable a year later.
    """
    folder = tmp_path / "clients"
    written(folder, "contract.pdf", PDF)
    await nominate(session, str(tmp_path))

    await add(session, str(folder), ["contract.pdf"])

    sources_recorded = await decisions(session, SOURCE_ADDED)
    assert len(sources_recorded) == 1
    assert sources_recorded[0]["root_path"] == str(folder)

    added = await decisions(session, DOCUMENT_ADDED)
    assert len(added) == 1
    assert added[0]["path"] == str(folder / "contract.pdf")
    assert added[0]["filename"] == "contract.pdf"
    assert len(str(added[0]["sha256"])) == 64
    assert uuid.UUID(str(added[0]["document_id"]))


async def test_a_duplicate_and_a_refusal_are_not_decisions_records(
    session: AsyncSession, tmp_path: Path
) -> None:
    """Nothing changed, and the decisions store is kept forever.

    They are logged instead — which is the durable record of a refusal that the
    browser's local counter is not.
    """
    folder = tmp_path / "clients"
    written(folder, "contract.pdf", PDF)
    written(folder, "contract copy.pdf", PDF)
    written(folder, "empty.pdf", b"")
    await nominate(session, str(tmp_path))

    await add(session, str(folder), ["contract.pdf", "contract copy.pdf", "empty.pdf"])

    assert len(await decisions(session, DOCUMENT_ADDED)) == 1


# --- what a batch survives --------------------------------------------------


async def test_one_bad_file_does_not_take_the_rest_of_the_batch_with_it(
    session: AsyncSession, tmp_path: Path
) -> None:
    """One archive among sixty contracts refuses the archive and adds the rest."""
    folder = tmp_path / "clients"
    written(folder, "one.pdf", PDF)
    written(folder, "program", b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 32)
    written(folder, "two.pdf", OTHER)
    written(folder, "ledger.csv", b"name,amount,date\nAnna,10,2026-01-01\n")
    await nominate(session, str(tmp_path))

    result = await add(session, str(folder), ["one.pdf", "program", "two.pdf", "ledger.csv"])

    assert result.count(Outcome.ADDED) == 2
    assert result.count(Outcome.REFUSED) == 1
    assert result.count(Outcome.LATER) == 1
    assert len(await documents(session)) == 2


async def test_a_file_outside_every_nominated_root_is_refused_not_recorded(
    session: AsyncSession, tmp_path: Path
) -> None:
    """The permission check, applied where files are actually opened."""
    folder = tmp_path / "clients"
    written(folder, "contract.pdf", PDF)

    result = await add(session, str(folder), ["contract.pdf"])

    assert result.count(Outcome.REFUSED) == 1
    assert "nominate" in (result.files[0].reason or "").lower()
    assert len(await documents(session)) == 0


# --- deletion: M2-DELETE-BE-061 ----------------------------------------------


def _embedding_literal(dimensions: int = 1024) -> str:
    return "[" + ",".join("0.1" for _ in range(dimensions)) + "]"


async def _chunk_with_content(
    session: AsyncSession, document_id: uuid.UUID, ordinal: int = 0
) -> uuid.UUID:
    result = await session.execute(
        text(
            "INSERT INTO chunks (document_id, ordinal, content, embedding) "
            "VALUES (:document_id, :ordinal, 'ninety days written notice', :embedding) "
            "RETURNING id"
        ),
        {"document_id": document_id, "ordinal": ordinal, "embedding": _embedding_literal()},
    )
    return result.scalar_one()


async def test_deleting_a_document_clears_content_and_embedding_and_tombstones_the_row(
    session: AsyncSession, tmp_path: Path
) -> None:
    folder = tmp_path / "clients"
    written(folder, "contract.pdf", PDF)
    await nominate(session, str(tmp_path))
    result = await add(session, str(folder), ["contract.pdf"])
    document_id = result.files[0].document_id
    assert document_id is not None
    chunk_id = await _chunk_with_content(session, document_id)

    deleted = await delete_document(session, document_id, "client engagement ended", OCR_THRESHOLD)

    assert deleted is True
    row = (
        await session.execute(
            text("SELECT deleted_at, deleted_reason, status FROM documents WHERE id = :id"),
            {"id": document_id},
        )
    ).first()
    assert row is not None
    assert row[0] is not None, "the tombstone date must be set"
    assert row[1] == "client engagement ended"
    assert row[2] == "deleted"

    chunk = (
        await session.execute(
            text("SELECT content, embedding FROM chunks WHERE id = :id"), {"id": chunk_id}
        )
    ).first()
    assert chunk is not None
    assert chunk[0] is None, "content must be cleared so it stops influencing retrieval"
    assert chunk[1] is None, "embedding must be cleared alongside it"

    # The row itself survives, unlike the content — a citation must still
    # resolve to something, even a tombstoned one.
    assert len(await documents(session)) == 1


async def test_deleting_a_document_does_not_touch_the_file_on_disk(
    session: AsyncSession, tmp_path: Path
) -> None:
    folder = tmp_path / "clients"
    filename = written(folder, "contract.pdf", PDF)
    await nominate(session, str(tmp_path))
    result = await add(session, str(folder), [filename])
    document_id = result.files[0].document_id
    assert document_id is not None

    await delete_document(session, document_id, "no longer a client", OCR_THRESHOLD)

    assert (folder / filename).read_bytes() == PDF


async def test_deleting_a_document_cancels_its_pending_ingestion_job(
    session: AsyncSession, tmp_path: Path
) -> None:
    """`add` already enqueues a job in the same transaction as the row — the
    ordinary queued state of a just-added document, not something this test
    has to construct."""
    folder = tmp_path / "clients"
    written(folder, "contract.pdf", PDF)
    await nominate(session, str(tmp_path))
    result = await add(session, str(folder), ["contract.pdf"])
    document_id = result.files[0].document_id
    assert document_id is not None
    queued_before = (
        await session.execute(
            text("SELECT count(*) FROM ingest_jobs WHERE document_id = :id"),
            {"id": document_id},
        )
    ).scalar_one()
    assert queued_before == 1, "the add path is expected to enqueue a job"

    await delete_document(session, document_id, "removed mid-import", OCR_THRESHOLD)

    remaining = (
        await session.execute(
            text("SELECT count(*) FROM ingest_jobs WHERE document_id = :id"),
            {"id": document_id},
        )
    ).scalar_one()
    assert remaining == 0


async def test_deleting_an_already_deleted_document_is_not_an_error(
    session: AsyncSession, tmp_path: Path
) -> None:
    folder = tmp_path / "clients"
    written(folder, "contract.pdf", PDF)
    await nominate(session, str(tmp_path))
    result = await add(session, str(folder), ["contract.pdf"])
    document_id = result.files[0].document_id
    assert document_id is not None
    await delete_document(session, document_id, "first delete", OCR_THRESHOLD)

    second = await delete_document(session, document_id, "second delete", OCR_THRESHOLD)

    assert second is False


async def test_deleting_an_unknown_document_returns_false(session: AsyncSession) -> None:
    assert await delete_document(session, uuid.uuid4(), None, OCR_THRESHOLD) is False


async def test_deleting_a_document_is_a_decisions_record_naming_the_reason(
    session: AsyncSession, tmp_path: Path
) -> None:
    folder = tmp_path / "clients"
    written(folder, "contract.pdf", PDF)
    await nominate(session, str(tmp_path))
    result = await add(session, str(folder), ["contract.pdf"])
    document_id = result.files[0].document_id
    assert document_id is not None

    await delete_document(session, document_id, "client engagement ended", OCR_THRESHOLD)

    entries = await decisions(session, DOCUMENT_DELETED)
    assert len(entries) == 1
    assert entries[0]["document_id"] == str(document_id)
    assert entries[0]["reason"] == "client engagement ended"


async def test_deleting_a_source_tombstones_every_live_document_under_it(
    session: AsyncSession, tmp_path: Path
) -> None:
    folder = tmp_path / "clients"
    written(folder, "one.pdf", PDF)
    written(folder, "two.pdf", OTHER)
    await nominate(session, str(tmp_path))
    result = await add(session, str(folder), ["one.pdf", "two.pdf"])
    assert result.source_id is not None

    deleted_count = await delete_source(session, result.source_id)

    assert deleted_count == 2
    rows = await documents(session)
    assert len(rows) == 2
    for row in rows:
        assert row.deleted_at is not None
    source_status = (
        await session.execute(
            text("SELECT status FROM sources WHERE id = :id"), {"id": result.source_id}
        )
    ).scalar_one()
    assert source_status == "deleted"


async def test_deleting_a_source_mid_import_leaves_nothing_half_indexed(
    session: AsyncSession, tmp_path: Path
) -> None:
    """A queued job for one of its documents is cancelled along with the
    tombstone, rather than being left to index a source that no longer
    exists."""
    folder = tmp_path / "clients"
    written(folder, "one.pdf", PDF)
    written(folder, "two.pdf", OTHER)
    await nominate(session, str(tmp_path))
    result = await add(session, str(folder), ["one.pdf", "two.pdf"])
    assert result.source_id is not None
    assert len(result.queued) == 2, "both documents are expected to be enqueued by add"

    await delete_source(session, result.source_id)

    remaining = (await session.execute(text("SELECT count(*) FROM ingest_jobs"))).scalar_one()
    assert remaining == 0


async def test_deleting_a_source_removes_its_schema_notes_but_not_general_memory(
    session: AsyncSession, tmp_path: Path
) -> None:
    folder = tmp_path / "clients"
    written(folder, "one.pdf", PDF)
    await nominate(session, str(tmp_path))
    result = await add(session, str(folder), ["one.pdf"])
    assert result.source_id is not None
    await session.execute(
        text(
            "INSERT INTO schema_notes (source_id, table_name, description, origin) "
            "VALUES (:source_id, 'invoices', 'One row per invoice.', 'inferred')"
        ),
        {"source_id": result.source_id},
    )
    await session.execute(
        text(
            "INSERT INTO memory (subject, fact, origin) "
            "VALUES ('client', 'CDA stands for confidential disclosure agreement', 'manual')"
        )
    )

    await delete_source(session, result.source_id)

    notes = (
        await session.execute(
            text("SELECT count(*) FROM schema_notes WHERE source_id = :id"),
            {"id": result.source_id},
        )
    ).scalar_one()
    assert notes == 0
    memory_count = (await session.execute(text("SELECT count(*) FROM memory"))).scalar_one()
    assert memory_count == 1


async def test_deleting_an_unknown_source_raises(session: AsyncSession) -> None:
    with pytest.raises(SourceNotFound):
        await delete_source(session, uuid.uuid4())


async def test_deleting_a_source_twice_raises(session: AsyncSession, tmp_path: Path) -> None:
    folder = tmp_path / "clients"
    written(folder, "one.pdf", PDF)
    await nominate(session, str(tmp_path))
    result = await add(session, str(folder), ["one.pdf"])
    assert result.source_id is not None
    await delete_source(session, result.source_id)

    with pytest.raises(SourceNotFound):
        await delete_source(session, result.source_id)


async def test_deleting_a_source_is_a_decisions_record(
    session: AsyncSession, tmp_path: Path
) -> None:
    folder = tmp_path / "clients"
    written(folder, "one.pdf", PDF)
    written(folder, "two.pdf", OTHER)
    await nominate(session, str(tmp_path))
    result = await add(session, str(folder), ["one.pdf", "two.pdf"])
    assert result.source_id is not None

    await delete_source(session, result.source_id)

    entries = await decisions(session, SOURCE_DELETED)
    assert len(entries) == 1
    assert entries[0]["source_id"] == str(result.source_id)
    assert entries[0]["documents_deleted"] == 2
