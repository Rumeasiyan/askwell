"""The invariants the database enforces, tested against a real database.

These need Postgres — an in-memory substitute has no partial indexes, no
`REVOKE`, and no vector type, so it would confirm nothing about the thing being
claimed. They are marked `requires_db` and deselected from the default run,
which has no network at all. They are not skipped silently: `scripts/dev.sh
test-db` selects them, and it fails rather than skipping if the database is not
reachable.

Every test here asserts that the database *refuses* something. That is the
point: a bug in a later deletion path should surface in development as an error
from Postgres, rather than quietly leaving deleted material in search results
on somebody's machine.
"""

import os
import uuid
from collections.abc import Iterator

import psycopg
import pytest

pytestmark = pytest.mark.requires_db

OWNER_URL = "TEST_DATABASE_URL"
APP_URL = "TEST_APP_DATABASE_URL"


def _url(name: str) -> str:
    """The connection string, or a failure that says how to run these.

    Deliberately not `pytest.skip`. A test that quietly passes when it did not
    run is worse than one that fails, because the summary line says the same
    thing either way.
    """
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"{name} is not set. These tests assert what the database refuses, "
            f"so they need a real one. Run: scripts/dev.sh test-db"
        )
    return value


@pytest.fixture
def owner() -> Iterator[psycopg.Connection[tuple[object, ...]]]:
    """Connected as the table owner, for setting up rows."""
    with psycopg.connect(_url(OWNER_URL), autocommit=True) as connection:
        yield connection
        connection.execute("TRUNCATE sources, conversations CASCADE")


@pytest.fixture
def application() -> Iterator[psycopg.Connection[tuple[object, ...]]]:
    """Connected as Askwell connects: `askwell_app`, which owns nothing."""
    with psycopg.connect(_url(APP_URL), autocommit=True) as connection:
        yield connection


@pytest.fixture
def a_source(owner: psycopg.Connection[tuple[object, ...]]) -> uuid.UUID:
    row = owner.execute(
        "INSERT INTO sources (kind, name) VALUES ('file', 'contracts') RETURNING id"
    ).fetchone()
    assert row is not None
    return uuid.UUID(str(row[0]))


# --- C6: the audit log is append-only ---------------------------------------


def test_the_application_role_does_not_own_the_audit_tables(
    application: psycopg.Connection[tuple[object, ...]],
) -> None:
    """The whole guarantee rests on this.

    A table owner bypasses its own grants. If Askwell connected as the owner,
    every REVOKE below would succeed, change nothing, and look exactly like a
    working append-only guarantee.
    """
    row = application.execute(
        "SELECT tableowner = current_user FROM pg_tables WHERE tablename = 'audit_decisions'"
    ).fetchone()
    assert row is not None
    assert row[0] is False, (
        "the application connects as the owner of the audit tables, which makes "
        "the append-only grants decorative"
    )


@pytest.mark.parametrize("table", ["audit_decisions", "audit_interactions"])
def test_an_audit_record_can_be_written(
    application: psycopg.Connection[tuple[object, ...]], table: str
) -> None:
    application.execute(
        f"INSERT INTO {table} (kind, payload, hash) VALUES (%s, %s, %s)",
        ("source_added", '{"name": "contracts"}', "a" * 64),
    )


@pytest.mark.parametrize("table", ["audit_decisions", "audit_interactions"])
@pytest.mark.parametrize(
    "statement", ["UPDATE {} SET kind = 'tampered'", "DELETE FROM {}", "TRUNCATE {}"]
)
def test_history_cannot_be_rewritten(
    application: psycopg.Connection[tuple[object, ...]], table: str, statement: str
) -> None:
    """C6, and it is a grant rather than application logic on purpose.

    Not called immutable: the user owns the machine and can always delete a
    file. The honest guarantee is that the application never rewrites history
    and that manual tampering is detectable.
    """
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        application.execute(statement.format(table))


# --- one live version per source and content hash ---------------------------


def _add_document(
    connection: psycopg.Connection[tuple[object, ...]],
    source_id: uuid.UUID,
    filename: str,
    sha256: str,
    **extra: object,
) -> uuid.UUID:
    columns = ["source_id", "filename", "path", "sha256", *extra]
    values: list[object] = [source_id, filename, f"/{filename}", sha256, *extra.values()]
    placeholders = ", ".join(["%s"] * len(columns))
    row = connection.execute(
        f"INSERT INTO documents ({', '.join(columns)}) VALUES ({placeholders}) RETURNING id",
        values,
    ).fetchone()
    assert row is not None
    return uuid.UUID(str(row[0]))


def test_the_same_content_cannot_be_live_twice_in_one_source(
    owner: psycopg.Connection[tuple[object, ...]], a_source: uuid.UUID
) -> None:
    digest = "b" * 64
    _add_document(owner, a_source, "lease.pdf", digest)
    with pytest.raises(psycopg.errors.UniqueViolation):
        _add_document(owner, a_source, "lease-copy.pdf", digest)


def test_a_deleted_document_may_share_a_hash_with_a_live_one(
    owner: psycopg.Connection[tuple[object, ...]], a_source: uuid.UUID
) -> None:
    """The index is partial for exactly this case.

    Re-adding a file the user deleted is normal, not a conflict — and the old
    row has to stay so its citations still resolve.
    """
    digest = "c" * 64
    _add_document(owner, a_source, "old.pdf", digest, deleted_at="now()")
    _add_document(owner, a_source, "new.pdf", digest)


def test_a_superseded_document_may_share_a_hash_with_a_live_one(
    owner: psycopg.Connection[tuple[object, ...]], a_source: uuid.UUID
) -> None:
    digest = "d" * 64
    first = _add_document(owner, a_source, "v1.pdf", digest)
    second = _add_document(owner, a_source, "v2.pdf", "e" * 64)
    owner.execute("UPDATE documents SET superseded_by = %s WHERE id = %s", (second, first))
    _add_document(owner, a_source, "v3.pdf", digest)


# --- a tombstoned document stops influencing retrieval ----------------------


def test_a_chunk_with_cleared_content_cannot_keep_its_embedding(
    owner: psycopg.Connection[tuple[object, ...]], a_source: uuid.UUID
) -> None:
    """The half-done deletion is the dangerous one.

    A document the user believes is gone would still match their queries and
    still return a passage with no text to show.
    """
    document = _add_document(owner, a_source, "lease.pdf", "f" * 64)
    with pytest.raises(psycopg.errors.CheckViolation):
        owner.execute(
            "INSERT INTO chunks (document_id, ordinal, content, embedding) "
            "VALUES (%s, 0, NULL, array_fill(0.1, ARRAY[1024])::vector)",
            (document,),
        )


def test_clearing_content_and_embedding_together_is_allowed(
    owner: psycopg.Connection[tuple[object, ...]], a_source: uuid.UUID
) -> None:
    document = _add_document(owner, a_source, "lease.pdf", "0" * 64)
    owner.execute(
        "INSERT INTO chunks (document_id, ordinal, content, embedding) "
        "VALUES (%s, 0, 'text', array_fill(0.1, ARRAY[1024])::vector)",
        (document,),
    )
    owner.execute("UPDATE chunks SET content = NULL, embedding = NULL")


# --- answered means answered ------------------------------------------------


def test_a_clarification_marked_answered_must_carry_an_answer(
    owner: psycopg.Connection[tuple[object, ...]], a_source: uuid.UUID
) -> None:
    """Otherwise a skipped question marked answered by a bug is
    indistinguishable from one the user actually answered — and memory would
    then be built on it."""
    with pytest.raises(psycopg.errors.CheckViolation):
        owner.execute(
            "INSERT INTO clarifications (source_id, subject, question, status) "
            "VALUES (%s, 'currency', 'Which currency?', 'answered')",
            (a_source,),
        )


def test_a_pending_clarification_needs_no_answer(
    owner: psycopg.Connection[tuple[object, ...]], a_source: uuid.UUID
) -> None:
    owner.execute(
        "INSERT INTO clarifications (source_id, subject, question) "
        "VALUES (%s, 'currency', 'Which currency?')",
        (a_source,),
    )


# --- a citation outlives its document ---------------------------------------


def test_a_document_that_is_cited_cannot_be_hard_deleted(
    owner: psycopg.Connection[tuple[object, ...]], a_source: uuid.UUID
) -> None:
    """Deletion is a tombstone, not a DELETE, and the database enforces it.

    `documents` cascades to `chunks`, but `citations.chunk_id` does not
    cascade — so a hard delete is refused precisely because a citation depends
    on the chunk row surviving.
    """
    document = _add_document(owner, a_source, "lease.pdf", "1" * 64)
    chunk = owner.execute(
        "INSERT INTO chunks (document_id, ordinal, content) VALUES (%s, 0, 'ninety days') "
        "RETURNING id",
        (document,),
    ).fetchone()
    assert chunk is not None

    conversation = owner.execute("INSERT INTO conversations DEFAULT VALUES RETURNING id").fetchone()
    assert conversation is not None
    message = owner.execute(
        "INSERT INTO messages (conversation_id, role, content) "
        "VALUES (%s, 'assistant', 'Ninety days.') RETURNING id",
        (conversation[0],),
    ).fetchone()
    assert message is not None
    owner.execute(
        "INSERT INTO citations (message_id, chunk_id, claim_ordinal, quoted_span) "
        "VALUES (%s, %s, 0, 'ninety days')",
        (message[0], chunk[0]),
    )

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        owner.execute("DELETE FROM documents WHERE id = %s", (document,))


def test_a_tombstoned_document_keeps_its_citation_resolvable(
    owner: psycopg.Connection[tuple[object, ...]], a_source: uuid.UUID
) -> None:
    """The intended path. The row survives so the citation resolves to
    "deleted on <date>" rather than to nothing."""
    document = _add_document(owner, a_source, "lease.pdf", "2" * 64)
    chunk = owner.execute(
        "INSERT INTO chunks (document_id, ordinal, content) VALUES (%s, 0, 'ninety days') "
        "RETURNING id",
        (document,),
    ).fetchone()
    assert chunk is not None
    conversation = owner.execute("INSERT INTO conversations DEFAULT VALUES RETURNING id").fetchone()
    assert conversation is not None
    message = owner.execute(
        "INSERT INTO messages (conversation_id, role, content) "
        "VALUES (%s, 'assistant', 'Ninety days.') RETURNING id",
        (conversation[0],),
    ).fetchone()
    assert message is not None
    owner.execute(
        "INSERT INTO citations (message_id, chunk_id, claim_ordinal) VALUES (%s, %s, 0)",
        (message[0], chunk[0]),
    )

    owner.execute(
        "UPDATE documents SET deleted_at = now(), deleted_reason = 'user removed it' WHERE id = %s",
        (document,),
    )
    owner.execute("UPDATE chunks SET content = NULL, embedding = NULL WHERE id = %s", (chunk[0],))

    still_resolving = owner.execute(
        "SELECT count(*) FROM citations c JOIN chunks k ON k.id = c.chunk_id"
    ).fetchone()
    assert still_resolving is not None
    assert still_resolving[0] == 1
