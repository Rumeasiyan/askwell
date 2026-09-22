"""Add `restore_jobs`, and `backup_jobs.install_secret_wrapped`. `M7-BACKUP-BE-158`.

Same shape as `backup_jobs` (`20260922_c4a1f8d02e77`): a durable row is the
record of what happened, `arq` only the transport that wakes a worker to act
on it, and anything still `running`/`restoring_tables`/`reembedding` when the
process starts is, on one worker on one machine, unfinished work from last
time rather than something to trust.

**Two counter pairs, not one**, unlike `backup_jobs`. Restore has two
genuinely different phases with different units of progress — tables
restored (`tables_done`/`tables_total`, rows within them) and chunks
re-embedded (`chunks_done`/`chunks_total`) — and collapsing them into one
pair would make a settings screen showing "47 of 200" unable to say which
phase that count belongs to.

**`truncated` is its own column, not inferred from `tables_done > 0`.**
`replace_existing` gates a table-by-table clear (`DELETE`, not `TRUNCATE` —
`askwell_app` has no `TRUNCATE` grant on anything; `askwell.restore._clear_existing`'s
own docstring has the full reasoning) that must run at most once per job — a
job that crashed between clearing and finishing its first table would,
without this flag, look identical to a job that has not cleared yet, and the
whole point of the flag is to tell those two apart on resume.

**`install_secret_wrapped` lives on `backup_jobs`, not a new table**, because
it is one more fact about a backup that already has a row — the same reason
`chunk_count` lives there rather than in its own table. `askwell.backup`'s
own module docstring explains what it holds and why restoring a
passphrase-protected corpus is not possible without it.

Revision ID: e8b3f61a92d4
Revises: f2c7d4e1a683
Created: 2026-09-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e8b3f61a92d4"
down_revision: str | None = "f2c7d4e1a683"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUSES = "status IN ('queued', 'restoring_tables', 'reembedding', 'done', 'failed')"


def upgrade() -> None:
    op.add_column("backup_jobs", sa.Column("install_secret_wrapped", sa.Text(), nullable=True))

    op.create_table(
        "restore_jobs",
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "status", sa.String(length=20), server_default=sa.text("'queued'"), nullable=False
        ),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("source_version", sa.String(length=32), nullable=False),
        sa.Column(
            "replace_existing", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("truncated", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "passphrase_protected", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("chunk_count", sa.BigInteger(), nullable=True),
        sa.Column("estimated_reembed_seconds", sa.Float(), nullable=True),
        sa.Column("tables_total", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("tables_done", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("rows_total", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("rows_done", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("chunks_total", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("chunks_done", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("chain_verified", sa.Boolean(), nullable=True),
        sa.Column("chain_detail", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(_STATUSES, name=op.f("ck_restore_jobs_status")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_restore_jobs")),
    )
    # The dispatcher's and `resume`'s own query: unfinished jobs. Partial for
    # the same reason `ix_backup_jobs_pending` is.
    op.create_index(
        "ix_restore_jobs_pending",
        "restore_jobs",
        ["created_at"],
        postgresql_where=sa.text("status IN ('queued', 'restoring_tables', 'reembedding')"),
    )


def downgrade() -> None:
    op.drop_index("ix_restore_jobs_pending", table_name="restore_jobs")
    op.drop_table("restore_jobs")
    op.drop_column("backup_jobs", "install_secret_wrapped")
