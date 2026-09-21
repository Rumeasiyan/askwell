"""Add `verify_jobs`: the durable record of a log verification run.

`docs/audit-log.md` §4, ticket `M7-LOG-FE-156`.

Same shape as `export_jobs` (`20260921_bb5cfc0e8e91`) for the same reason: a
background job with progress and a result needs a row a person can query
while it runs. `askwell.audit.verify` already walks a chain and reports the
first break; this table is what lets that walk run across both stores as an
interruptible job with progress, instead of only the synchronous
`askwell-verify` command.

**One row per store per run, not one row for both.** `decisions`/
`interactions` get their own `checked`/`total`/outcome columns rather than a
shared pair, because the ticket's own edge case — "both stores broken" —
needs both outcomes reported independently, and a single "intact" flag could
not represent one store broken and the other clean.

**`first_break_id` carries no foreign key.** It names a row in
`audit_decisions` or `audit_interactions` depending on which store column it
belongs to, and neither of those tables is a fixed target a `ForeignKey`
could point at from one column. The id is looked up by the settings screen
against the right store directly, the same way `askwell.audit.
VerificationResult.first_break` is already just a bare `uuid.UUID`.

**`cancel_requested` is a flag on the row, not a Redis message.** One worker,
one machine, the same reasoning `askwell.model_download`'s own cancel flag
uses — the job polls its own row rather than needing a second channel.
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "a3c9f5e1d2b7"
down_revision: str | None = "bb5cfc0e8e91"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUSES = "status IN ('queued', 'running', 'done', 'failed', 'cancelled')"


def _outcome_columns(prefix: str) -> list[sa.Column[Any]]:
    return [
        sa.Column(f"{prefix}_total", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(f"{prefix}_checked", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(f"{prefix}_intact", sa.Boolean(), nullable=True),
        sa.Column(f"{prefix}_break_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column(f"{prefix}_break_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(f"{prefix}_break_reason", sa.String(length=32), nullable=True),
        sa.Column(f"{prefix}_break_detail", sa.Text(), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "verify_jobs",
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "status", sa.String(length=16), server_default=sa.text("'queued'"), nullable=False
        ),
        sa.Column(
            "cancel_requested", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        *_outcome_columns("decisions"),
        *_outcome_columns("interactions"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(_STATUSES, name=op.f("ck_verify_jobs_status")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_verify_jobs")),
    )
    op.create_index(
        "ix_verify_jobs_pending",
        "verify_jobs",
        ["created_at"],
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )


def downgrade() -> None:
    op.drop_index("ix_verify_jobs_pending", table_name="verify_jobs")
    op.drop_table("verify_jobs")
