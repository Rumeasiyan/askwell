"""Anchor kind and label — where a citation lands, for every format.

`docs/backlog/M1-it-answers-from-my-documents.md` ticket `M1-EXTRACT-ING-027`.

**One column on `documents`, one on `document_pages`.** `page_number` already
carries an ordinal — the page for a PDF, the slide for a deck, the row for a
spreadsheet, the section for text/Markdown/HTML — and that ordinal is enough
for `document_pages`' own uniqueness and for `documents.page_count`.
`anchor_kind` says which of those four the ordinal *means*, once per document,
so the source viewer (`docs/ux/source-viewer.md` §2) knows how to render it.
`anchor_label` carries the human-facing pointer a bare ordinal cannot —
"Sheet1, row 45" or a heading's own text — and is left `NULL` for a PDF, where
"page 14" needs no extra label.

Revision ID: f70a1c4e9d63
Revises: e6f3a90c2b18
Created: 2026-08-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f70a1c4e9d63"
down_revision: str | None = "e6f3a90c2b18"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("anchor_kind", sa.String(length=16), nullable=True))
    op.create_check_constraint(
        "ck_documents_anchor_kind",
        "documents",
        "anchor_kind IN ('page', 'slide', 'sheet_row', 'heading')",
    )
    op.add_column("document_pages", sa.Column("anchor_label", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("document_pages", "anchor_label")
    op.drop_constraint("ck_documents_anchor_kind", "documents", type_="check")
    op.drop_column("documents", "anchor_kind")
