"""Source and document rows against a real Postgres.

Three things can only be tested here, and each is a promise the ticket makes.

Adding a document is a **decision**, so it is in the decisions audit store with
its path or it did not happen — the audit write is in the caller's transaction.

Recognition is a **query across live documents**, so it needs rows: the second
copy of a contract is only recognised because the first one is in the table, and
a duplicate inside a single batch is only recognised because the insert before
it is visible in the same transaction.

And "one live version per source and hash" is a *partial* unique index. Whether
the database refuses a second live row with the same hash, independently of the
code path above it, cannot be answered without the database.
"""

import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import psycopg
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from askwell import roots, sources
from askwell.config import Settings
from askwell.sources import (
    Candidate,
    DocumentNotFound,
    DocumentStatus,
    Outcome,
    SourceRefused,
    TransitionRefused,
)

pytestmark = pytest.mark.requires_db

TABLES = "roots, sources, audit_decisions"


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


def configured(window: Path | None) -> Settings:
    return Settings(
        database_url="postgresql://askwell:pw@127.0.0.1:1/askwell",  # type: ignore[arg-type]
        roots_mount=window,
    )


@pytest_asyncio.fixture
async def clients(session: AsyncSession, tmp_path: Path) -> Path:
    """A nominated folder. Nothing is read without one."""
    folder = tmp_path / "clients"
    folder.mkdir()
    await roots.register(session, configured(tmp_path), str(folder))
    return folder


def written(folder: Path, name: str, content: bytes) -> str:
    path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return str(path)


async def decisions(session: AsyncSession, kind: str) -> list[dict[str, object]]:
    result = await session.execute(
        text("SELECT payload FROM audit_decisions WHERE kind = :kind ORDER BY occurred_at"),
        {"kind": kind},
    )
    return [row[0] for row in result]


async def live_documents(session: AsyncSession) -> int:
    result = await session.execute(
        text("SELECT count(*) FROM documents WHERE deleted_at IS NULL AND superseded_by IS NULL")
    )
    return int(result.scalar_one())


# --- adding -----------------------------------------------------------------


async def test_adding_a_file_creates_a_document_with_its_path_and_hash(
    session: AsyncSession, clients: Path
) -> None:
    path = written(clients, "contract.pdf", b"%PDF-1.7 terms")

    result = await sources.add(
        session, str(clients), [Candidate(path=path, mime="application/pdf")]
    )

    assert result.counted(Outcome.ADDED) == 1
    row = (
        await session.execute(
            text("SELECT path, filename, mime, sha256, status FROM documents WHERE id = :id"),
            {"id": result.files[0].document_id},
        )
    ).one()
    assert row.path == path
    assert row.filename == "contract.pdf"
    assert row.mime == "application/pdf"
    assert row.sha256 == sources.digest(path)[0]
    assert row.status == DocumentStatus.QUEUED


async def test_the_source_carries_the_folder_it_came_from(
    session: AsyncSession, clients: Path
) -> None:
    path = written(clients, "contract.pdf", b"terms")

    result = await sources.add(session, str(clients), [Candidate(path=path)])

    row = (
        await session.execute(
            text("SELECT kind, name, root_path, status FROM sources WHERE id = :id"),
            {"id": result.source_id},
        )
    ).one()
    assert row.kind == "file"
    assert row.name == "clients"
    assert row.root_path == str(clients)
    assert row.status == DocumentStatus.QUEUED


async def test_adding_a_document_is_a_decision_recorded_with_its_path(
    session: AsyncSession, clients: Path
) -> None:
    """`docs/audit-log.md` §2: what the user added is a decision.

    With the path, because "when did this contract enter Askwell, and from
    where" is the question the decisions store exists to answer, and an
    identifier on its own answers neither half of it.
    """
    path = written(clients, "contract.pdf", b"terms")

    await sources.add(session, str(clients), [Candidate(path=path)])

    recorded = await decisions(session, sources.DOCUMENT_ADDED)
    assert len(recorded) == 1
    assert recorded[0]["path"] == path
    assert recorded[0]["sha256"] == sources.digest(path)[0]
    assert await decisions(session, sources.SOURCE_ADDED)


# --- recognition ------------------------------------------------------------


async def test_the_identical_file_added_again_links_to_the_existing_document(
    session: AsyncSession, clients: Path, tmp_path: Path
) -> None:
    """The ticket's acceptance criterion, from a different folder.

    Recognition is global rather than per source: three folders is three
    sources, and the user this exists for has the same contract in all of them.
    """
    archive = tmp_path / "archive"
    archive.mkdir()
    await roots.register(session, configured(tmp_path), str(archive))

    first = written(clients, "contract.pdf", b"identical terms")
    await sources.add(session, str(clients), [Candidate(path=first)])
    again = written(archive, "contract.pdf", b"identical terms")

    result = await sources.add(session, str(archive), [Candidate(path=again)])

    assert result.counted(Outcome.DUPLICATE) == 1
    assert result.source_id is None, "a duplicate-only add must not create an empty source"
    outcome = result.files[0]
    assert outcome.existing is not None
    assert outcome.existing.path == first
    assert outcome.document_id == outcome.existing.id
    assert await live_documents(session) == 1


async def test_the_same_content_under_two_names_in_one_drop(
    session: AsyncSession, clients: Path
) -> None:
    """`contract.pdf` and `contract copy.pdf`, dropped together.

    The second is only recognisable because the first insert is visible in the
    same transaction — nothing has been committed yet.
    """
    first = written(clients, "contract.pdf", b"identical terms")
    second = written(clients, "contract copy.pdf", b"identical terms")

    result = await sources.add(
        session, str(clients), [Candidate(path=first), Candidate(path=second)]
    )

    assert [item.outcome for item in result.files] == [Outcome.ADDED, Outcome.DUPLICATE]
    assert await live_documents(session) == 1
    assert first in (result.files[1].reason or "")
    assert second in (result.files[1].reason or "")


async def test_a_different_file_with_the_same_name_is_not_a_duplicate(
    session: AsyncSession, clients: Path
) -> None:
    """Recognition is by content. A name has never been evidence of anything."""
    first = written(clients, "one/report.pdf", b"first quarter")
    second = written(clients, "two/report.pdf", b"second quarter")

    result = await sources.add(
        session, str(clients), [Candidate(path=first), Candidate(path=second)]
    )

    assert [item.outcome for item in result.files] == [Outcome.ADDED, Outcome.ADDED]
    assert await live_documents(session) == 2


async def test_a_duplicate_is_not_a_decisions_record(
    session: AsyncSession, clients: Path
) -> None:
    """Nothing changed, so nothing is recorded as having been decided.

    A decisions store that also holds non-events stops being a record of what
    the user did, which is the only thing it is for.
    """
    first = written(clients, "contract.pdf", b"identical")
    second = written(clients, "copy.pdf", b"identical")

    await sources.add(session, str(clients), [Candidate(path=first), Candidate(path=second)])

    assert len(await decisions(session, sources.DOCUMENT_ADDED)) == 1


async def test_a_deleted_document_does_not_shadow_a_re_add(
    session: AsyncSession, clients: Path
) -> None:
    """A tombstone is not a live document.

    Matching against one would refuse to re-add a file the user deliberately
    deleted and then changed their mind about, and the reason given would name
    a document they cannot see.
    """
    path = written(clients, "contract.pdf", b"terms")
    first = await sources.add(session, str(clients), [Candidate(path=path)])
    await session.execute(
        text("UPDATE documents SET deleted_at = now(), status = 'deleted' WHERE id = :id"),
        {"id": first.files[0].document_id},
    )

    again = await sources.add(session, str(clients), [Candidate(path=path)])

    assert again.files[0].outcome is Outcome.ADDED


# --- refusals ---------------------------------------------------------------


async def test_a_zero_byte_file_is_rejected_and_the_rest_of_the_drop_proceeds(
    session: AsyncSession, clients: Path
) -> None:
    empty = written(clients, "empty.pdf", b"")
    real = written(clients, "contract.pdf", b"terms")

    result = await sources.add(
        session, str(clients), [Candidate(path=empty), Candidate(path=real)]
    )

    assert result.files[0].outcome is Outcome.REJECTED
    assert "0 bytes" in (result.files[0].reason or "")
    assert result.files[1].outcome is Outcome.ADDED
    assert await live_documents(session) == 1


async def test_a_file_outside_every_nominated_folder_is_not_read(
    session: AsyncSession, clients: Path, tmp_path: Path
) -> None:
    """The permission check is the same one `roots` performs, not a copy of it."""
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    stray = written(outside, "contract.pdf", b"terms")

    result = await sources.add(session, str(clients), [Candidate(path=stray)])

    assert result.files[0].outcome is Outcome.REJECTED
    assert "nominated" in (result.files[0].reason or "")
    assert result.source_id is None


async def test_a_folder_no_root_covers_is_refused_outright(
    session: AsyncSession, tmp_path: Path
) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    stray = written(elsewhere, "contract.pdf", b"terms")

    with pytest.raises(SourceRefused) as refusal:
        await sources.add(session, str(elsewhere), [Candidate(path=stray)])

    assert "nominated" in str(refusal.value)


async def test_nothing_added_leaves_no_source_row(session: AsyncSession, clients: Path) -> None:
    empty = written(clients, "empty.pdf", b"")

    result = await sources.add(session, str(clients), [Candidate(path=empty)])

    assert result.source_id is None
    count = (await session.execute(text("SELECT count(*) FROM sources"))).scalar_one()
    assert int(count) == 0


# --- the database's own rule ------------------------------------------------


def test_the_database_refuses_a_second_live_row_with_the_same_hash(
    database_url: str,
) -> None:
    """`uq_documents_live_source_id_sha256`, independently of the code above it.

    The recognition rule in `askwell.sources` is global and this index is
    narrower — one live version per (source, hash). It is a backstop against a
    later code path that forgets, not a restatement of the current one, which is
    why it is asserted directly rather than through `add()`.
    """
    with psycopg.connect(database_url, autocommit=True) as connection:
        source = connection.execute(
            "INSERT INTO sources (kind, name) VALUES ('file', 'clients') RETURNING id"
        ).fetchone()
        assert source is not None
        source_id = uuid.UUID(str(source[0]))

        insert = (
            "INSERT INTO documents (source_id, filename, path, sha256) "
            "VALUES (%s, %s, %s, %s)"
        )
        connection.execute(insert, (source_id, "a.pdf", "/x/a.pdf", "b" * 64))
        with pytest.raises(psycopg.errors.UniqueViolation):
            connection.execute(insert, (source_id, "b.pdf", "/x/b.pdf", "b" * 64))

        connection.execute("DELETE FROM sources WHERE id = %s", (source_id,))


# --- stages -----------------------------------------------------------------


async def test_a_document_walks_from_queued_to_ready(
    session: AsyncSession, clients: Path
) -> None:
    path = written(clients, "contract.pdf", b"terms")
    added = await sources.add(session, str(clients), [Candidate(path=path)])
    document_id = added.files[0].document_id
    source_id = added.source_id
    assert document_id is not None
    assert source_id is not None

    await sources.mark(session, document_id, DocumentStatus.INDEXING)
    assert await sources.refresh(session, source_id) is DocumentStatus.INDEXING
    await sources.mark(session, document_id, DocumentStatus.READY)
    assert await sources.refresh(session, source_id) is DocumentStatus.READY

    row = (
        await session.execute(
            text("SELECT status, last_indexed_at FROM sources WHERE id = :id"),
            {"id": added.source_id},
        )
    ).one()
    assert row.status == DocumentStatus.READY
    assert row.last_indexed_at is not None


async def test_a_document_cannot_skip_the_work(session: AsyncSession, clients: Path) -> None:
    """Queued straight to ready is what a bug that skips indexing looks like.

    It would report a document as searchable that nothing has read, and the
    status is the only thing telling the user whether their question can be
    answered yet.
    """
    path = written(clients, "contract.pdf", b"terms")
    added = await sources.add(session, str(clients), [Candidate(path=path)])
    document_id = added.files[0].document_id
    assert document_id is not None

    with pytest.raises(TransitionRefused):
        await sources.mark(session, document_id, DocumentStatus.READY)


async def test_one_failed_file_puts_the_source_in_attention(
    session: AsyncSession, clients: Path
) -> None:
    first = written(clients, "a.pdf", b"one")
    second = written(clients, "b.pdf", b"two")
    added = await sources.add(
        session, str(clients), [Candidate(path=first), Candidate(path=second)]
    )
    source_id = added.source_id
    one, other = added.files[0].document_id, added.files[1].document_id
    assert source_id is not None
    assert one is not None
    assert other is not None

    await sources.mark(session, one, DocumentStatus.INDEXING)
    await sources.mark(session, one, DocumentStatus.READY)
    await sources.mark(session, other, DocumentStatus.ATTENTION)

    assert await sources.refresh(session, source_id) is DocumentStatus.ATTENTION


async def test_marking_a_document_that_is_not_there_says_so(session: AsyncSession) -> None:
    with pytest.raises(DocumentNotFound):
        await sources.mark(session, uuid.uuid4(), DocumentStatus.INDEXING)
