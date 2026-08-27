"""Nominated root directories.

`docs/backlog/M1-it-answers-from-my-documents.md` ticket `M1-ADD-ING-021`.

Askwell indexes in place, so it needs to be told which folders it may open.
This table is that permission, and it is its own table rather than a JSON list
under a `settings` key for one reason that only shows up later: removing a root
has to leave a tombstone, so a source underneath it can say *why* it stopped
being readable. A registry that deletes the row cannot tell "you removed this
folder on the 3rd" from "no folder ever covered this path", and only one of
those is an answer.

The unique index is partial, over the live rows. Nominating a folder, removing
it and nominating it again is an ordinary sequence — a plain unique constraint
would refuse the third step and blame the user for the second.

No grants are issued here. The v1 migration set default privileges in `public`
precisely so a table added later arrives with the same shape rather than with
none; that is what is being relied on, and it is worth knowing it is deliberate
rather than forgotten.

Revision ID: b1f4c7d2a913
Revises: a8208099ef38
Created: 2026-08-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b1f4c7d2a913"
down_revision: str | None = "a8208099ef38"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "roots",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        # Absolute, normalised, symlinks unresolved: the path the user
        # nominated, which is also what the native picker returns in M7.
        sa.Column("path", sa.Text(), nullable=False),
        # Null means "could not be told", never "local disk". It drives only
        # the network-share warning.
        sa.Column("filesystem", sa.String(length=64), nullable=True),
        sa.Column(
            "added_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        # A tombstone, not a delete.
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_roots"),
    )
    op.create_index(
        "uq_roots_path_active",
        "roots",
        ["path"],
        unique=True,
        postgresql_where=sa.text("removed_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_roots_path_active", table_name="roots")
    op.drop_table("roots")
