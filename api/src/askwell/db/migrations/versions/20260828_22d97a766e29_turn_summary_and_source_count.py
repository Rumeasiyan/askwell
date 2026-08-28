"""Store a one-line summary and a source count with every turn.

`docs/backlog/M1-it-answers-from-my-documents.md` ticket `M1-CONV-BE-177`.

`docs/ux/conversation.md` §2/§6: a collapsed past turn shows a one-line
summary and a source count, and both are **computed once, at composition
time, and never recomputed** — re-deriving either from `citations` on read
would make a turn's own history depend on the state of the corpus at the
moment someone scrolled back to it, not on what was true when it happened.
That means both values need a home on the row itself.

Both columns are nullable, and the nullability is the distinction the
ticket asks for, not an oversight: `source_count IS NULL` means the turn
abstained (`docs/ux/conversation.md` §5 — "no source count, summary saying
so"), which must read differently from a turn that produced citations from
zero distinct documents, a case that cannot currently happen but that the
schema should not conflate with abstention. `summary` is nullable only
because a `user` row never gets one; every `assistant` row that finishes —
completed, stopped, or failed — always has one, including the fallback this
ticket's own edge case requires when generating it fails.

Revision ID: 22d97a766e29
Revises: c7e2f814a5b3
Created: 2026-08-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "22d97a766e29"
down_revision: str | None = "c7e2f814a5b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("summary", sa.Text(), nullable=True))
    op.add_column("messages", sa.Column("source_count", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "ck_messages_source_count_non_negative",
        "messages",
        "source_count IS NULL OR source_count >= 0",
    )


def downgrade() -> None:
    op.drop_constraint("ck_messages_source_count_non_negative", "messages", type_="check")
    op.drop_column("messages", "source_count")
    op.drop_column("messages", "summary")
