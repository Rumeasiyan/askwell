"""The durable ingestion queue.

`docs/backlog/M1-it-answers-from-my-documents.md` ticket `M1-ADD-ING-025`.

**Why a table when Redis is already the queue.** `arq` dispatches; this table
records. The distinction matters because the failure this ticket exists to
prevent is somebody adding five hundred papers and closing their laptop — and a
job that exists only in Redis is lost by `podman compose down -v`, by an
enqueue that failed while the API had the row committed, and by a worker that
died holding it. The table is the truth and the queue is the transport, and
`askwell.ingest.reconcile` makes them agree rather than assuming they do.

**One row per document, not one per attempt.** The question the library asks is
"what happened to this file, and can I retry it" — a per-attempt table answers a
question nobody is asking and grows without bound while doing it.

**`seq` rather than `enqueued_at` for ordering.** Every document in one drop is
enqueued in a single transaction and shares `now()` to the microsecond, so a
queue position computed from the timestamp would reorder itself between two
reads of the same unchanged queue.

Revision ID: d5b2e8c17f40
Revises: c3d9e1a45b76
Created: 2026-08-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d5b2e8c17f40"
down_revision: str | None = "c3d9e1a45b76"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATES = "state IN ('queued', 'running', 'parked', 'failed', 'done')"


def upgrade() -> None:
    op.create_table(
        "ingest_jobs",
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("seq", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("document_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "state",
            sa.String(length=32),
            server_default=sa.text("'queued'"),
            nullable=False,
        ),
        sa.Column("stage", sa.String(length=32), nullable=True),
        sa.Column("awaiting", sa.String(length=32), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("bytes_done", sa.BigInteger(), nullable=True),
        sa.Column("bytes_total", sa.BigInteger(), nullable=True),
        sa.Column(
            "enqueued_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(_STATES, name=op.f("ck_ingest_jobs_state")),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_ingest_jobs_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            name=op.f("fk_ingest_jobs_source_id_sources"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ingest_jobs")),
        sa.UniqueConstraint("document_id", name="uq_ingest_jobs_document_id"),
        sa.UniqueConstraint("seq", name=op.f("uq_ingest_jobs_seq")),
    )
    # Partial: the dispatcher only ever asks for the next unfinished job, and
    # the finished rows are the ones that accumulate.
    op.create_index(
        "ix_ingest_jobs_pending",
        "ingest_jobs",
        ["seq"],
        postgresql_where=sa.text("state IN ('queued', 'running')"),
    )
    op.create_index("ix_ingest_jobs_source_id", "ingest_jobs", ["source_id"])

    # Every document already recorded gets a queue row. `M1-ADD-BE-023` shipped
    # the add flow a ticket before the queue existed, so a developer — and the
    # owner's own machine — has documents sitting at `queued` with nothing that
    # would ever pick them up. Reconcile cannot help them: it re-dispatches
    # rows, and they have none. Ordered by `added_at` so the queue reflects the
    # order the files arrived rather than however Postgres returns them.
    op.execute(
        "INSERT INTO ingest_jobs (document_id, source_id) "
        "SELECT id, source_id FROM documents "
        "WHERE deleted_at IS NULL AND superseded_by IS NULL ORDER BY added_at"
    )

    # No grants here, deliberately. The v1 migration set default privileges in
    # `public` for both roles precisely so a table added in a year arrives with
    # them; adding an explicit grant would work and would also make the next
    # table's author think one is required.


def downgrade() -> None:
    op.drop_index("ix_ingest_jobs_source_id", table_name="ingest_jobs")
    op.drop_index("ix_ingest_jobs_pending", table_name="ingest_jobs")
    op.drop_table("ingest_jobs")
