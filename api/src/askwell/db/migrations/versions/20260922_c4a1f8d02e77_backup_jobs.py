"""Add `backup_jobs`: the durable record of a backup. `M7-BACKUP-BE-157`.

Same shape as `export_jobs` (`20260921_bb5cfc0e8e91`) for the same reason: a
background job with progress and a result needs a row a person can query
while it runs, and Redis is the transport that wakes a worker, never the
record of what happened.

**One counter pair for tables, one for rows**, not one pair per table the way
`export_jobs` has one pair per store. A log export covers two stores and the
settings screen shows each separately; a backup covers roughly fifteen
tables, and a per-table breakdown belongs in the manifest the artefact
itself carries, not in a row that would need a column added every time a
migration adds a table.

**`chunk_count`/`estimated_reembed_seconds` are captured on the row**, not
only in the manifest, so `GET /backup/{id}` can state the re-embed cost
while the job is still running — the ticket's own acceptance criterion asks
for the cost stated "at backup time," which means before the artefact
finishes, not only inside it.

Revision ID: c4a1f8d02e77
Revises: bb5cfc0e8e91
Created: 2026-09-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4a1f8d02e77"
down_revision: str | None = "bb5cfc0e8e91"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUSES = "status IN ('queued', 'running', 'done', 'failed')"


def upgrade() -> None:
    op.create_table(
        "backup_jobs",
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "status", sa.String(length=16), server_default=sa.text("'queued'"), nullable=False
        ),
        sa.Column("tables_total", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("tables_done", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("rows_total", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("rows_done", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("chunk_count", sa.BigInteger(), nullable=True),
        sa.Column("estimated_reembed_seconds", sa.Float(), nullable=True),
        sa.Column("passphrase_protected", sa.Boolean(), nullable=True),
        sa.Column("file_path", sa.Text(), nullable=True),
        sa.Column("file_bytes", sa.BigInteger(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(_STATUSES, name=op.f("ck_backup_jobs_status")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_backup_jobs")),
    )
    # The dispatcher's and `resume`'s own query: unfinished jobs. Partial for
    # the same reason `ix_export_jobs_pending` is.
    op.create_index(
        "ix_backup_jobs_pending",
        "backup_jobs",
        ["created_at"],
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )


def downgrade() -> None:
    op.drop_index("ix_backup_jobs_pending", table_name="backup_jobs")
    op.drop_table("backup_jobs")
