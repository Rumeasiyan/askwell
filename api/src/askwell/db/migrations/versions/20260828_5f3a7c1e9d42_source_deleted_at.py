"""A deletion timestamp on `sources`, matching `documents.deleted_at`.

`docs/backlog/M2-it-says-when-it-doesnt-know.md` ticket `M2-DELETE-FE-062`.

`delete_source` (`askwell.sources`) already flips `status` to `'deleted'`,
but nothing recorded *when* — and the library's own deleted-row state
(`docs/ux/library.md` §5, "Deleted, filtered in: Greyed, deletion date, not
openable") needs a date to show, the same way a deleted document already
carries one. `status = 'deleted'` stays the filterable fact; `deleted_at`
is the date that goes with it.

Revision ID: 5f3a7c1e9d42
Revises: 22d97a766e29
Created: 2026-08-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5f3a7c1e9d42"
down_revision: str | None = "22d97a766e29"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("sources", "deleted_at")
