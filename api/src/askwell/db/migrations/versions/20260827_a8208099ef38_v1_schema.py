"""The v1 schema, whole.

`docs/architecture.md` §7. Thirteen tables, created together and deliberately:
retrofitting a column later means a migration on a user's own laptop, where
there is no operator, no staging environment and no rollback. An unused column
now costs nothing.

There are no `organisations`, `users` or roles. Their absence is a requirement,
not an omission.

Hand-edited after autogeneration, for four things Alembic cannot know:

  - the vector extension, and a readable failure when it is missing
  - the embedding dimension, which comes from configuration
  - `content_tsv` as a generated column rather than something the application
    maintains
  - the Tamil text search configuration, which is a hedge and not a feature

Revision ID: a8208099ef38
Revises:
Created: 2026-08-27
"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from askwell.config import load_settings

# The width of every embedding column. Read from configuration rather than
# written here, because changing the embedding model is a configuration change
# plus a re-embed, not a schema edit. bge-m3 gives 1024.
EMBEDDING_DIMENSIONS = load_settings().embedding_dimensions

# English for v1. The Tamil configuration below exists so that adding Tamil
# later is a change to this name, not a re-index of everyone's corpus.
TEXT_SEARCH_CONFIG = "english"
TAMIL_CONFIG = "askwell_tamil"

revision: str = "a8208099ef38"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _create_extensions()
    _create_text_search_configurations()

    op.create_table(
        "audit_decisions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("prev_hash", sa.String(length=64), nullable=True),
        sa.Column("hash", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_decisions")),
    )
    op.create_index(
        "ix_audit_decisions_occurred_at", "audit_decisions", ["occurred_at"], unique=False
    )
    op.create_table(
        "audit_interactions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("prev_hash", sa.String(length=64), nullable=True),
        sa.Column("hash", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_interactions")),
    )
    op.create_index(
        "ix_audit_interactions_occurred_at", "audit_interactions", ["occurred_at"], unique=False
    )
    op.create_table(
        "conversations",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("mode", sa.String(length=32), server_default=sa.text("'text'"), nullable=False),
        sa.Column(
            "ai_backend", sa.String(length=32), server_default=sa.text("'local'"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "ai_backend IN ('local', 'online')", name=op.f("ck_conversations_ai_backend")
        ),
        sa.CheckConstraint("mode IN ('text', 'voice')", name=op.f("ck_conversations_mode")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversations")),
    )
    op.create_table(
        "memory",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("fact", sa.Text(), nullable=False),
        sa.Column("origin", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=4, scale=3), nullable=True),
        sa.Column("superseded_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "origin IN ('clarification', 'correction', 'manual')", name=op.f("ck_memory_origin")
        ),
        sa.ForeignKeyConstraint(
            ["superseded_by"],
            ["memory.id"],
            name=op.f("fk_memory_superseded_by_memory"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_memory")),
    )
    op.create_table(
        "settings",
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_settings")),
    )
    op.create_table(
        "sources",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("root_path", sa.Text(), nullable=True),
        sa.Column("config_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("sandbox_db", sa.Text(), nullable=True),
        sa.Column(
            "status", sa.String(length=32), server_default=sa.text("'indexing'"), nullable=False
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "added_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "kind IN ('file', 'csv', 'dump', 'connection')", name=op.f("ck_sources_kind")
        ),
        sa.CheckConstraint(
            "status IN ('indexing', 'ready', 'attention', 'deleted')",
            name=op.f("ck_sources_status"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sources")),
    )
    op.create_table(
        "clarifications",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("options", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column(
            "status", sa.String(length=32), server_default=sa.text("'pending'"), nullable=False
        ),
        sa.Column(
            "asked_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'answered', 'skipped', 'dismissed')",
            name=op.f("ck_clarifications_status"),
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            name=op.f("fk_clarifications_source_id_sources"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_clarifications")),
    )
    op.create_index("ix_clarifications_source_id", "clarifications", ["source_id"], unique=False)
    op.create_table(
        "documents",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("missing_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("mime", sa.String(length=255), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("superseded_by", sa.UUID(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_reason", sa.Text(), nullable=True),
        sa.Column(
            "status", sa.String(length=32), server_default=sa.text("'indexing'"), nullable=False
        ),
        sa.Column("ocr_confidence", sa.Numeric(precision=4, scale=3), nullable=True),
        sa.Column(
            "added_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('indexing', 'ready', 'attention', 'deleted')",
            name=op.f("ck_documents_status"),
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            name=op.f("fk_documents_source_id_sources"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["superseded_by"],
            ["documents.id"],
            name=op.f("fk_documents_superseded_by_documents"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
    )
    op.create_index("ix_documents_sha256", "documents", ["sha256"], unique=False)
    op.create_index("ix_documents_source_id", "documents", ["source_id"], unique=False)
    op.create_table(
        "messages",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("trace", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "role IN ('user', 'assistant', 'system')", name=op.f("ck_messages_role")
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("fk_messages_conversation_id_conversations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_messages")),
    )
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"], unique=False)
    op.create_table(
        "schema_notes",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("table_name", sa.Text(), nullable=False),
        sa.Column("column_name", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("origin", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=4, scale=3), nullable=True),
        sa.Column("superseded_by", sa.UUID(), nullable=True),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(EMBEDDING_DIMENSIONS), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("origin IN ('user', 'inferred')", name=op.f("ck_schema_notes_origin")),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            name=op.f("fk_schema_notes_source_id_sources"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["superseded_by"],
            ["schema_notes.id"],
            name=op.f("fk_schema_notes_superseded_by_schema_notes"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_schema_notes")),
    )
    op.create_index("ix_schema_notes_source_id", "schema_notes", ["source_id"], unique=False)
    op.create_table(
        "chunks",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("page_from", sa.Integer(), nullable=True),
        sa.Column("page_to", sa.Integer(), nullable=True),
        sa.Column("heading", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(EMBEDDING_DIMENSIONS), nullable=True),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_chunks_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chunks")),
    )
    # Generated, not maintained by the application. A trigger or an
    # application write can be forgotten, and a stale search index is invisible
    # until someone cannot find a document they know they added.
    #
    # `coalesce` because deletion clears `content`: a tombstoned document must
    # produce an empty document vector rather than a null one, or it silently
    # drops out of every index scan for a different reason than intended.
    op.execute(
        f"ALTER TABLE chunks ADD COLUMN content_tsv tsvector "
        f"GENERATED ALWAYS AS "
        f"(to_tsvector('{TEXT_SEARCH_CONFIG}', coalesce(content, ''))) STORED"
    )
    op.create_index(
        "ix_chunks_content_tsv", "chunks", ["content_tsv"], unique=False, postgresql_using="gin"
    )
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"], unique=False)
    op.create_table(
        "fact_usage",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("message_id", sa.UUID(), nullable=False),
        sa.Column("fact_kind", sa.String(length=32), nullable=False),
        sa.Column("fact_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "fact_kind IN ('memory', 'schema_note')", name=op.f("ck_fact_usage_fact_kind")
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["messages.id"],
            name=op.f("fk_fact_usage_message_id_messages"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fact_usage")),
        sa.UniqueConstraint(
            "message_id", "fact_kind", "fact_id", name="message_id_fact_kind_fact_id"
        ),
    )
    op.create_index("ix_fact_usage_fact_id", "fact_usage", ["fact_id"], unique=False)
    op.create_index("ix_fact_usage_message_id", "fact_usage", ["message_id"], unique=False)
    op.create_table(
        "citations",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("message_id", sa.UUID(), nullable=False),
        sa.Column("chunk_id", sa.UUID(), nullable=False),
        sa.Column("claim_ordinal", sa.Integer(), nullable=False),
        sa.Column("quoted_span", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["chunk_id"], ["chunks.id"], name=op.f("fk_citations_chunk_id_chunks")
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["messages.id"],
            name=op.f("fk_citations_message_id_messages"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_citations")),
    )
    op.create_index("ix_citations_chunk_id", "citations", ["chunk_id"], unique=False)
    op.create_index("ix_citations_message_id", "citations", ["message_id"], unique=False)


def _create_extensions() -> None:
    """The vector extension, or a failure that says which extension is missing.

    Without this, the first `CREATE TABLE` carrying a vector column fails with
    `type "vector" does not exist` — which names neither the extension nor the
    image that provides it, and sends whoever reads it looking at the column
    definition instead.
    """
    try:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    except sa.exc.DatabaseError as error:  # pragma: no cover - needs a server without it
        raise RuntimeError(
            "Askwell needs the `vector` extension and this database does not "
            "have it available. The Compose stack uses the pgvector image, "
            "which ships it; a plain postgres image does not. If you are "
            "pointing Askwell at your own Postgres, install pgvector there "
            f"first.\n\nPostgres said: {error}"
        ) from error


def _create_text_search_configurations() -> None:
    """Full-text configurations, including one hedge.

    `askwell_tamil` is created and then not used. v1 is English-only, and Tamil
    is later work — but the hedge is cheap now and expensive later: switching
    a text search configuration means re-indexing every chunk on every user's
    machine, and having the configuration already present makes that a change
    to one name rather than a schema migration people have to sit through.

    It is a copy of `simple`, which does no stemming. That is not Tamil
    support and is not claimed to be: it tokenises without mangling the words
    through English rules, which is the part that has to be decided now.
    """
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_ts_config WHERE cfgname = '{TAMIL_CONFIG}'
            ) THEN
                CREATE TEXT SEARCH CONFIGURATION {TAMIL_CONFIG} (COPY = simple);
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.drop_index("ix_citations_message_id", table_name="citations")
    op.drop_index("ix_citations_chunk_id", table_name="citations")
    op.drop_table("citations")
    op.drop_index("ix_fact_usage_message_id", table_name="fact_usage")
    op.drop_index("ix_fact_usage_fact_id", table_name="fact_usage")
    op.drop_table("fact_usage")
    op.drop_index("ix_chunks_document_id", table_name="chunks")
    op.drop_index("ix_chunks_content_tsv", table_name="chunks", postgresql_using="gin")
    op.drop_table("chunks")
    op.drop_index("ix_schema_notes_source_id", table_name="schema_notes")
    op.drop_table("schema_notes")
    op.drop_index("ix_messages_conversation_id", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_documents_source_id", table_name="documents")
    op.drop_index("ix_documents_sha256", table_name="documents")
    op.drop_table("documents")
    op.drop_index("ix_clarifications_source_id", table_name="clarifications")
    op.drop_table("clarifications")
    op.drop_table("sources")
    op.drop_table("settings")
    op.drop_table("memory")
    op.drop_table("conversations")
    op.drop_index("ix_audit_interactions_occurred_at", table_name="audit_interactions")
    op.drop_table("audit_interactions")
    op.drop_index("ix_audit_decisions_occurred_at", table_name="audit_decisions")
    op.drop_table("audit_decisions")

    op.execute(f"DROP TEXT SEARCH CONFIGURATION IF EXISTS {TAMIL_CONFIG}")
    # The extension is deliberately not dropped. It may predate Askwell, and
    # another database in the same cluster may be using it — a downgrade should
    # undo what this migration did, not what it happened to find.
