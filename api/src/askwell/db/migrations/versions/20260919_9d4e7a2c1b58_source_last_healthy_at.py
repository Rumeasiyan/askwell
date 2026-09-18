"""Add `sources.last_healthy_at`.

`M4-CONN-BE-099`. `sources.status`/`last_error` already say whether a live
connection is reachable and why not; the library's own connection-dead state
(`docs/ux/library.md` §5) also needs "the last successful check" — a fact
`status`/`last_error` cannot carry, because a source that has been `attention`
for three days still needs to say *when it last worked*, not just that it does
not now.

Set on every successful health probe, periodic or on-demand
(`askwell.connections.check_connection_health`) — never cleared, so a
currently-`attention` connection still shows when it was last seen healthy
rather than going blank the moment it fails.

Revision ID: 9d4e7a2c1b58
Revises: 3f7c1a9e5d20
Created: 2026-09-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9d4e7a2c1b58"
down_revision: str | None = "3f7c1a9e5d20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sources", sa.Column("last_healthy_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("sources", "last_healthy_at")
