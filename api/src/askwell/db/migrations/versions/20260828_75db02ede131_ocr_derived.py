"""Mark a document as OCR-derived.

`docs/backlog/M1-it-answers-from-my-documents.md` ticket `M1-EXTRACT-ING-028`.

**One boolean, not a third value bolted onto an existing column.** The source
viewer (`docs/ux/source-viewer.md`) needs to know "does this document have a
scanned image to show beside the text", which is orthogonal to
`anchor_kind` (page/slide/sheet_row/heading all still apply — an OCR'd PDF is
still `anchor_kind = 'page'`) and to `ocr_confidence`
(`M1-EXTRACT-ING-029` sets that; a document can be OCR-derived before a
confidence score exists for it). `NOT NULL DEFAULT false` because every
existing and future document has an unambiguous answer — a document that has
never been extracted did not use OCR either.

Revision ID: 75db02ede131
Revises: f70a1c4e9d63
Created: 2026-08-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "75db02ede131"
down_revision: str | None = "f70a1c4e9d63"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("ocr_derived", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("documents", "ocr_derived")
