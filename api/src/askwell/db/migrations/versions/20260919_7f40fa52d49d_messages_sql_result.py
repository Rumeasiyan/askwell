"""Add `messages.sql_result`.

`M4-SQL-BE-108a`. A database-answered turn's rows are a snapshot taken at
answer time, not a live view (the ticket's own Assumption) — the number in
an old answer must not change under a user who reopens the conversation
after the source database has moved on, and there is nowhere to put "the
rows this turn returned" until this column exists. `NULL` for every
document-grounded turn, exactly as `source_count` already stays `NULL` for
an abstained one rather than collapsing a "does not apply" case into a
false `0`.

Revision ID: 7f40fa52d49d
Revises: 9d4e7a2c1b58
Created: 2026-09-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "7f40fa52d49d"
down_revision: str | None = "9d4e7a2c1b58"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("sql_result", JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "sql_result")
