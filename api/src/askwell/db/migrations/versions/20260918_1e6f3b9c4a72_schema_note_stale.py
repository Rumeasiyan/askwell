"""Add `schema_notes.stale`.

`M4-SCHEMA-ING-101`, closing issue #355. `write_schema_inventory`
(`askwell.schema_introspect`) already retires an *inferred* note at a table
or column position a re-introspection no longer finds, by superseding it
with itself — but a `user`-origin note at the same vanished position was
left completely untouched, with nothing distinguishing "the user explained
this and it is still true" from "the user explained this and the column is
gone". The ticket's own edge case: "A note for a column that later
disappears — flagged as stale rather than silently applied."

`stale` is independent of `superseded_by`: a stale note is still active
(still the best answer Askwell has, still retrieved) but is now flagged so
retrieval can carry the caveat into the prompt rather than presenting a
vanished column as current fact. Reintrospection clears the flag again if
the position reappears — a renamed-then-renamed-back column, or a live
connection reconnecting to a schema that was only briefly out of sync.

Revision ID: 1e6f3b9c4a72
Revises: 8ad5ca4aa1a1
Created: 2026-09-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "1e6f3b9c4a72"
down_revision: str | None = "8ad5ca4aa1a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "schema_notes",
        sa.Column("stale", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("schema_notes", "stale")
