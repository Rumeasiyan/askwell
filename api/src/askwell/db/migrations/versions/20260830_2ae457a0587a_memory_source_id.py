"""Add `memory.source_id`, nullable, so a general fact can say which source
taught it.

`docs/backlog/M3-it-learns-my-material.md` ticket `M3-STORE-BE-076`.

`memory` rows are not tied to a schema object (`schema_notes` already does
that), but the ticket's own edge case requires a fact whose source was
deleted to keep saying so: "general memory survives and says it came from a
deleted source" rather than reading identically to a fact with no source at
all. `sources` are soft-deleted (`status = 'deleted'`, `deleted_at` set,
never an actual row `DELETE` — `askwell.sources.delete_source`), so the row
a fact points to keeps existing and keeps its name; `ON DELETE SET NULL` is
there for the case that is not exercised today rather than as a functioning
path, since a soft-deleted source's `id` is never removed. `ix_memory_source_id`
is partial on `source_id IS NOT NULL`, matching every other nullable
foreign-key index in this schema.

Revision ID: 2ae457a0587a
Revises: a4d9e2f6c831
Created: 2026-08-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "2ae457a0587a"
down_revision: str | None = "a4d9e2f6c831"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("memory", sa.Column("source_id", UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        op.f("fk_memory_source_id_sources"),
        "memory",
        "sources",
        ["source_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_memory_source_id"),
        "memory",
        ["source_id"],
        postgresql_where=sa.text("source_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_memory_source_id"), table_name="memory")
    op.drop_constraint(op.f("fk_memory_source_id_sources"), "memory", type_="foreignkey")
    op.drop_column("memory", "source_id")
