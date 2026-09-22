"""Add `messages.model_identity`.

`M7-SET-BE-145a`. Every turn now records which model produced it and
whether that model was shipped or user-supplied (`askwell.model_select`) —
the settings section that swaps models, and the marker that warns an answer
came from an unverified one, both describe a capability this makes real.

`NOT NULL` with a server default rather than nullable, for the same reason
`messages.source_count` distinguishes "abstained" from "no citations": a
message written while no model is loaded must record that fact explicitly
(`{"source": "none", ...}`, written by the application), and a row from
before this column existed reads as `{"source": "unknown", ...}` rather than
a bare `NULL` nothing downstream can tell apart from either case. Postgres
backfills every existing row from the default in the same `ADD COLUMN`.

Revision ID: a1c2e5f6b3d4
Revises: d3e6b1a94f02
Created: 2026-09-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "a1c2e5f6b3d4"
down_revision: str | None = "d3e6b1a94f02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEFAULT = """'{"source": "unknown", "display_name": null}'"""


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column(
            "model_identity",
            JSONB,
            nullable=False,
            server_default=sa.text(_DEFAULT),
        ),
    )


def downgrade() -> None:
    op.drop_column("messages", "model_identity")
