"""Add `prune_jobs`: the durable record of an interaction-retention prune.

`docs/audit-log.md` §8, ticket `M7-LOG-BE-154`.

Same shape as `export_jobs` (`20260921_bb5cfc0e8e91`) for the same reason: a
background job with a result needs a row a person can query while it runs,
and Redis is the transport that wakes a worker, never the record of what
happened.

**`cutoff` is stored, not recomputed.** A retry after a crash — `resume`
returning a `running` job to `queued` — must prune exactly what the original
request decided, not whatever `interaction_retention_months` says by the time
a worker gets to it a second time.

**`boundary_hash` is the anchor `askwell.audit.verify` needs.** It is the
hash of the last record this run deleted, which is also the `prev_hash` every
surviving record still chains to — recorded on the job row and, more
durably, in the `interactions_pruned` decisions record `askwell.log_prune`
writes in the same transaction as the delete.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f2c7d4e1a683"
down_revision: str | None = "a1c2e5f6b3d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUSES = "status IN ('queued', 'running', 'done', 'failed')"


def upgrade() -> None:
    op.create_table(
        "prune_jobs",
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "status", sa.String(length=16), server_default=sa.text("'queued'"), nullable=False
        ),
        sa.Column("cutoff", sa.DateTime(timezone=True), nullable=False),
        sa.Column("pruned_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("boundary_hash", sa.String(length=64), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(_STATUSES, name=op.f("ck_prune_jobs_status")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_prune_jobs")),
    )
    # `dispatch`'s and `resume`'s own query: unfinished jobs. Partial, matching
    # `ix_export_jobs_pending` — finished rows accumulate and are never the
    # answer.
    op.create_index(
        "ix_prune_jobs_pending",
        "prune_jobs",
        ["created_at"],
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )


def downgrade() -> None:
    op.drop_index("ix_prune_jobs_pending", table_name="prune_jobs")
    op.drop_table("prune_jobs")
