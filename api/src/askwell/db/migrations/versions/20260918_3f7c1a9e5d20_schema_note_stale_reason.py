"""Add `schema_notes.stale_reason` and `schema_notes.reattach_suggestion`.

`M4-SCHEMA-BE-102`, closing issue #365. `schema_notes.stale` (`M4-SCHEMA-ING-101`)
already says *that* a note's position has vanished; this ticket's own edge
cases need to say more than that without a second re-introspection to ask
again:

**`stale_reason`** distinguishes a table a role can no longer see
(`'possibly_invisible'`, a permission change may be temporary — `pg_catalog`
still lists it, just not as `SELECT`-able) from one genuinely absent from the
catalog (`'dropped'`). Conflating the two would tell a user their column is
gone when a colleague only revoked a grant overnight.

**`reattach_suggestion`** carries the single unambiguous rename candidate
`schema_introspect.write_schema_inventory` finds when a stale column's table
still exists, exactly one column vanished from it and exactly one new one
appeared — an offer, per the ticket's own Assumption, never an automatic
reattachment. `NULL` when no such single candidate exists.

Both nullable and both cleared alongside `stale` itself, whether by a
reintrospection that finds the position again or by a person resolving the
note through the fix path.

Revision ID: 3f7c1a9e5d20
Revises: 1e6f3b9c4a72
Created: 2026-09-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3f7c1a9e5d20"
down_revision: str | None = "1e6f3b9c4a72"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("schema_notes", sa.Column("stale_reason", sa.Text(), nullable=True))
    op.add_column("schema_notes", sa.Column("reattach_suggestion", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("schema_notes", "reattach_suggestion")
    op.drop_column("schema_notes", "stale_reason")
