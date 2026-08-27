"""The data model, checked without a database.

These assert the properties `docs/architecture.md` §7 calls load-bearing, and
they are deliberately metadata-only: they run in the same second as everything
else, in CI with no services, and they fail on the change rather than on a
migration someone forgot to apply. Behaviour that genuinely needs Postgres —
the generated tsvector, the invariants — belongs with the database harness in
M0-FOUND-TEST-005.
"""

import pytest
from sqlalchemy import Table

from askwell.db import models
from askwell.db.base import Base

EXPECTED_TABLES = {
    "settings",
    "sources",
    "documents",
    "chunks",
    "schema_notes",
    "memory",
    "clarifications",
    "conversations",
    "messages",
    "citations",
    "fact_usage",
    "audit_decisions",
    "audit_interactions",
}


def table(name: str) -> Table:
    return Base.metadata.tables[name]


def test_every_documented_table_exists() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_there_are_no_organisations_users_or_roles() -> None:
    """Removed with the repositioning. Their absence is a requirement.

    Askwell is one person on one machine. A `users` table reintroduces a
    concept the whole product is defined by not having, and it would arrive
    looking like harmless groundwork.
    """
    forbidden = {"organisations", "organizations", "users", "roles", "user_roles", "memberships"}
    assert not (set(Base.metadata.tables) & forbidden)

    for name, defined in Base.metadata.tables.items():
        for column in defined.columns:
            assert "visible_to_role" not in column.name, f"{name}.{column.name}"
            assert column.name not in {"user_id", "organisation_id", "org_id"}, name


def test_deletion_and_supersession_are_separate_columns() -> None:
    """Never conflate them.

    `superseded_by` says a newer version exists. `deleted_at` is a tombstone.
    Reusing one for the other loses either the version history or the ability
    to resolve an old citation to "deleted on the 3rd" — silently, both times.
    """
    documents = table("documents")
    assert "superseded_by" in documents.c
    assert "deleted_at" in documents.c
    assert "deleted_reason" in documents.c
    assert documents.c.deleted_at.nullable
    assert documents.c.superseded_by.nullable


@pytest.mark.parametrize("name", ["documents", "schema_notes", "memory"])
def test_supersession_is_available_wherever_corrections_happen(name: str) -> None:
    """A correction supersedes; it never updates in place."""
    assert "superseded_by" in table(name).c


def test_a_citation_is_a_row_not_a_field_in_a_json_blob() -> None:
    """C4 has to be queryable or it cannot be enforced or measured.

    `docs/success-metrics.md` §2 tracks uncited claims at 100%. With citations
    buried inside `messages.trace`, "did any answer contain an uncited claim?"
    is unanswerable.
    """
    citations = table("citations")
    assert {"message_id", "chunk_id", "claim_ordinal", "quoted_span"} <= set(citations.c.keys())


def test_a_citation_survives_the_deletion_of_its_document() -> None:
    """The foreign key to chunks is deliberately not cascade-delete.

    A deleted document's chunk row survives precisely so the citation still
    resolves — to "deleted on <date>" rather than to nothing.
    """
    chunk_fk = next(
        fk for fk in table("citations").foreign_keys if fk.column.table.name == "chunks"
    )
    assert chunk_fk.ondelete is None, (
        "citations.chunk_id must not cascade: the chunk row exists so that an "
        "old citation still resolves after the document is deleted"
    )


def test_chunk_content_and_embedding_are_nullable_because_deletion_clears_them() -> None:
    chunks = table("chunks")
    assert chunks.c.content.nullable
    assert chunks.c.embedding.nullable


def test_fact_usage_is_a_join_table_not_a_counter() -> None:
    """A counter does not survive a deletion and cannot say which answers used it.

    A wrong belief used once is a nuisance; used in forty answers it has been
    corrupting results for weeks. That number is what makes the memory screen
    worth opening.
    """
    assert "fact_usage" in Base.metadata.tables
    assert "usage_count" not in table("memory").c


def test_documents_keep_the_path_they_were_found_at() -> None:
    """Askwell indexes in place, so a moved file is normal, not an edge case.

    Without the original path there is no way to distinguish moved from
    deleted, and treating a moved file as deleted is both wrong and alarming.
    """
    documents = table("documents")
    assert "path" in documents.c
    assert not documents.c.path.nullable
    assert "missing_since" in documents.c


def test_the_two_audit_tables_are_separate() -> None:
    """Different retention and different write-failure behaviour."""
    for name in ("audit_decisions", "audit_interactions"):
        columns = set(table(name).c.keys())
        assert {"kind", "payload", "prev_hash", "hash", "occurred_at"} <= columns
    assert table("audit_decisions").c.prev_hash.nullable, "null only for the first record"


def test_defaults_are_enforced_by_the_database_not_only_by_the_orm() -> None:
    """A Python-side default exists only for rows the ORM inserts.

    A migration, a `psql` session or a repair script then hits a NOT NULL
    violation on a column that appeared to have a default. This was a real
    defect here, found by inserting a document by hand.
    """
    expected = {
        ("sources", "status"),
        ("documents", "status"),
        ("documents", "version"),
        ("clarifications", "status"),
        ("conversations", "mode"),
        ("conversations", "ai_backend"),
    }
    for table_name, column_name in expected:
        column = table(table_name).c[column_name]
        assert column.server_default is not None, f"{table_name}.{column_name}"
        assert column.default is None, (
            f"{table_name}.{column_name} has a Python-side default, which does "
            f"not apply to inserts that bypass the ORM"
        )


def test_the_embedding_dimension_is_not_hardcoded_in_the_model() -> None:
    """It follows the embedding model and is read from configuration.

    Changing model is then a configuration change plus a re-embed, rather than
    a schema migration on somebody's laptop.
    """
    source = (models.__file__ or "").replace("models.py", "models.py")
    with open(source, encoding="utf-8") as handle:
        text = handle.read()
    assert "Vector(1024)" not in text
    assert "Vector()" in text
