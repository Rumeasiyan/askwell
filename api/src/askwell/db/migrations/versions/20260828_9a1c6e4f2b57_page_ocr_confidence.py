"""Per-page OCR confidence.

`docs/backlog/M1-it-answers-from-my-documents.md` ticket `M1-EXTRACT-ING-029`.

**`documents.ocr_confidence` is the flag; this is what lets the flag point
somewhere.** A mixed document — some pages read well, some did not — is
flagged at the document level from the aggregate, but the ticket's own edge
case asks for the poor pages to be *named* in the reason, and the aggregate
alone cannot say which pages those were once the run that computed it has
finished. `NULL` for a page whose text came from the text layer, not OCR —
same reasoning as `documents.ocr_confidence` itself: confidence is a fact
about a page Tesseract was asked to read, not a property every page has.

Revision ID: 9a1c6e4f2b57
Revises: 75db02ede131
Created: 2026-08-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9a1c6e4f2b57"
down_revision: str | None = "75db02ede131"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "document_pages",
        sa.Column("ocr_confidence", sa.Numeric(precision=4, scale=3), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("document_pages", "ocr_confidence")
