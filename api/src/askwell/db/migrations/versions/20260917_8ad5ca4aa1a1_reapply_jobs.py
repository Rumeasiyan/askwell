"""Add `reapply_jobs` and `reapply_items`: the durable queue for re-processing
what an answered clarification affects.

`docs/backlog/M3-it-learns-my-material.md` ticket `M3-APPLY-ING-080`.

Same shape as `ingest_jobs` (`20260828_d5b2e8c17f40`) for the same reason: a
table nobody can query is a table nobody can prove is not silently stuck, and
Redis is the transport here too, never the record.

**One job per answer, many items per job.** An answer can touch a handful of
chunks, an inferred schema note and a stale contradiction question all at
once — `docs/memory-and-clarification.md` §2's "re-embed affected chunks,
update schema notes, re-resolve the contradiction" in one sentence, three
different kinds of work. A job is the unit the confirmation toast names
(`../ux/clarifications.md` §4); an item is the unit progress and retry apply
to (`../ux/clarifications.md` §5's "Answered, re-processing ... Per-item
progress").

**`reapply_items` is polymorphic by `kind`, not three nullable foreign
keys** — the same choice `fact_usage.fact_kind`/`fact_id` already made for the
same reason: a chunk, a schema note and a clarification are unrelated tables,
and a row that could reference any of them or none would be meaningless.

**The partial unique index is the de-duplication rule**, not application
code: two answers whose dependency resolution both name the same chunk insert
the same `(kind, target_id)` row only once while it is `pending`, so the
chunk is re-embedded once rather than twice (`M3-APPLY-ING-080`'s own edge
case). Once an item leaves `pending` the slot is free again — a later,
unrelated answer touching the same chunk still gets a job.

Revision ID: 8ad5ca4aa1a1
Revises: 2ae457a0587a
Created: 2026-09-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8ad5ca4aa1a1"
down_revision: str | None = "2ae457a0587a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JOB_STATES = "status IN ('queued', 'running', 'done', 'failed')"
_ITEM_KINDS = "kind IN ('chunk', 'schema_note', 'conflict')"
_ITEM_STATUSES = "status IN ('pending', 'done', 'failed')"


def upgrade() -> None:
    op.create_table(
        "reapply_jobs",
        sa.Column(
            "id", sa.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("source_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("clarification_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("memory_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "status", sa.String(length=16), server_default=sa.text("'queued'"), nullable=False
        ),
        sa.Column("total_items", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("done_items", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("failed_items", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(_JOB_STATES, name=op.f("ck_reapply_jobs_status")),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            name=op.f("fk_reapply_jobs_source_id_sources"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["clarification_id"],
            ["clarifications.id"],
            name=op.f("fk_reapply_jobs_clarification_id_clarifications"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["memory_id"],
            ["memory.id"],
            name=op.f("fk_reapply_jobs_memory_id_memory"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reapply_jobs")),
    )
    op.create_index("ix_reapply_jobs_source_id", "reapply_jobs", ["source_id"])
    # The dispatcher's and `resume`'s own query: unfinished jobs. Partial for
    # the same reason `ix_ingest_jobs_pending` is — finished rows accumulate
    # and are never the answer.
    op.create_index(
        "ix_reapply_jobs_pending",
        "reapply_jobs",
        ["created_at"],
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )

    op.create_table(
        "reapply_items",
        sa.Column(
            "id", sa.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("job_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("target_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column(
            "status", sa.String(length=16), server_default=sa.text("'pending'"), nullable=False
        ),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(_ITEM_KINDS, name=op.f("ck_reapply_items_kind")),
        sa.CheckConstraint(_ITEM_STATUSES, name=op.f("ck_reapply_items_status")),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["reapply_jobs.id"],
            name=op.f("fk_reapply_items_job_id_reapply_jobs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reapply_items")),
    )
    op.create_index("ix_reapply_items_job_id", "reapply_items", ["job_id"])
    op.create_index(
        "uq_reapply_items_pending",
        "reapply_items",
        ["kind", "target_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index("uq_reapply_items_pending", table_name="reapply_items")
    op.drop_index("ix_reapply_items_job_id", table_name="reapply_items")
    op.drop_table("reapply_items")
    op.drop_index("ix_reapply_jobs_pending", table_name="reapply_jobs")
    op.drop_index("ix_reapply_jobs_source_id", table_name="reapply_jobs")
    op.drop_table("reapply_jobs")
