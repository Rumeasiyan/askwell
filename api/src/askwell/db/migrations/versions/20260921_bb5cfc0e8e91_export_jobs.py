"""Add `export_jobs`: the durable record of a log export.

`docs/audit-log.md` §5, ticket `M7-LOG-BE-155`.

Same shape as `ingest_jobs` (`20260828_d5b2e8c17f40`) and `reapply_jobs`
(`20260917_8ad5ca4aa1a1`) for the same reason: a background job with progress
and a result needs a row a person can query while it runs, and Redis is the
transport that wakes a worker, never the record of what happened.

**One row per export, not per record.** The unit the settings screen names
(`docs/ux/settings.md` §6/§8) is the export as a whole — progress across both
stores, one result. Per-record detail belongs in the export file itself, not
in a table that would grow as large as the thing it is describing.

**`since`/`until` are nullable timestamps, not a stored filter string.** A
`NULL` on either side means unbounded in that direction — an export with
`since` set alone is "everything up to now", matching how a person would
actually ask "since I onboarded this client" without also having to name an
end date that does not exist yet.

**No `total_bytes` column.** Size is only known once the file is finished,
and it is written straight onto the row alongside `file_path` when `status`
becomes `done` — a separate progress-percentage-by-bytes column would need
its own estimate before the export starts, which is not obtainable from a
`COUNT(*)` the way the record counters are.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "bb5cfc0e8e91"
down_revision: str | None = "b7e91a4c3f65"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUSES = "status IN ('queued', 'running', 'done', 'failed')"


def upgrade() -> None:
    op.create_table(
        "export_jobs",
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "status", sa.String(length=16), server_default=sa.text("'queued'"), nullable=False
        ),
        sa.Column("since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decisions_total", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("decisions_done", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("interactions_total", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("interactions_done", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=True),
        sa.Column("file_bytes", sa.BigInteger(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(_STATUSES, name=op.f("ck_export_jobs_status")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_export_jobs")),
    )
    # The dispatcher's and `resume`'s own query: unfinished jobs. Partial for
    # the same reason `ix_reapply_jobs_pending` is.
    op.create_index(
        "ix_export_jobs_pending",
        "export_jobs",
        ["created_at"],
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )


def downgrade() -> None:
    op.drop_index("ix_export_jobs_pending", table_name="export_jobs")
    op.drop_table("export_jobs")
