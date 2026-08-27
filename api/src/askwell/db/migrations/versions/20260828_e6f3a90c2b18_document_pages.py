"""Per-page extracted text.

`docs/backlog/M1-it-answers-from-my-documents.md` ticket `M1-EXTRACT-ING-026`.

**Every page gets a row, whether or not it yielded text.** The ticket's own
validation rule: "a page yielding no text is recorded as such rather than
skipped, so the OCR decision is per page." A page silently omitted here is a
page `M1-EXTRACT-ING-028` never learns it owns.

**A table, not a column on `documents`.** Chunking (`M1-INDEX-ING-031`) needs
page boundaries and page numbers to build passages against; storing all of a
900-page document's text in one `documents` column would mean re-parsing that
column to find a page instead of reading the page directly, and it forecloses
the mixed text-layer-plus-OCR case where different pages arrive from different
extractors at different times.

Revision ID: e6f3a90c2b18
Revises: d5b2e8c17f40
Created: 2026-08-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e6f3a90c2b18"
down_revision: str | None = "d5b2e8c17f40"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_pages",
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("document_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("has_text", sa.Boolean(), nullable=False),
        sa.Column(
            "added_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_document_pages_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_pages")),
        sa.UniqueConstraint(
            "document_id", "page_number", name="uq_document_pages_document_id_page_number"
        ),
    )
    op.create_index("ix_document_pages_document_id", "document_pages", ["document_id"])

    # No grants here, deliberately — see `d5b2e8c17f40`'s note. Default
    # privileges in `public` already cover a table added a migration later.


def downgrade() -> None:
    op.drop_index("ix_document_pages_document_id", table_name="document_pages")
    op.drop_table("document_pages")
