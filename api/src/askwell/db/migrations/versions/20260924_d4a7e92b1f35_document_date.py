"""Add a document's own date, its precision and its source.

Ticket `M7-FIX-BE-170a`. Until now the only date on `documents` was
`added_at` — when Askwell ingested the file — and the conflicting-sources
state (`docs/ux/ask.md` §5) was ordering two versions of a handbook by the
order they happened to be added in.

Three nullable columns, null together or set together (the check constraint):
the date, how much of it is real (`year` for `store_hours_2026.pdf` — never
rendered as 1 January), and whether file metadata or the filename claimed it.
Null means unknown. No backfill here: existing rows are dated the next time
they are re-indexed, because the date comes from reading the file, which a
migration has no business doing.

Revision ID: d4a7e92b1f35
Revises: c8f2a61d4b90
Created: 2026-09-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4a7e92b1f35"
down_revision: str | None = "c8f2a61d4b90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("document_date", sa.Date(), nullable=True))
    op.add_column(
        "documents", sa.Column("document_date_precision", sa.String(length=8), nullable=True)
    )
    op.add_column(
        "documents", sa.Column("document_date_source", sa.String(length=16), nullable=True)
    )
    op.create_check_constraint(
        op.f("ck_documents_document_date_precision"),
        "documents",
        "document_date_precision IN ('day', 'month', 'year')",
    )
    op.create_check_constraint(
        op.f("ck_documents_document_date_source"),
        "documents",
        "document_date_source IN ('metadata', 'filename')",
    )
    op.create_check_constraint(
        op.f("ck_documents_document_date_complete"),
        "documents",
        "(document_date IS NULL) = (document_date_precision IS NULL) "
        "AND (document_date IS NULL) = (document_date_source IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_documents_document_date_complete"), "documents", type_="check")
    op.drop_constraint(op.f("ck_documents_document_date_source"), "documents", type_="check")
    op.drop_constraint(op.f("ck_documents_document_date_precision"), "documents", type_="check")
    op.drop_column("documents", "document_date_source")
    op.drop_column("documents", "document_date_precision")
    op.drop_column("documents", "document_date")
