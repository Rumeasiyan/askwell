"""Keep a workbook's sheet-load outcome on its document.

Ticket `M11-FIX-UI-229`, issue #849. `table_load.load_workbook_tables`
recorded why a sheet was not loaded as a table only to the decisions store,
which the library does not read — so a spreadsheet question that abstained
gave the user no way to learn that the table which could have answered it
does not exist.

Two columns rather than one, because they mean different things to the
library. `sheet_load_failure` (`{"sheet", "reason"}`) is the load failing,
and puts the folder in `attention`; `sheets_skipped` (a list of the same
shape) is a sheet with no usable header row, which is a note on the
document, not something that failed. Both are rewritten by every load of the
workbook, so a later successful load clears them.

Downgrade drops both. The audit records they duplicate are untouched.

Revision ID: a3d9f6c2e814
Revises: f4b8d2c6a915
Created: 2026-09-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a3d9f6c2e814"
down_revision: str | None = "f4b8d2c6a915"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("sheet_load_failure", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("sheets_skipped", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("documents", "sheets_skipped")
    op.drop_column("documents", "sheet_load_failure")
