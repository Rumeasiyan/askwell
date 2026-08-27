"""What ingestion needs to record about a document.

`docs/backlog/M1-it-answers-from-my-documents.md` ticket `M1-ADD-ING-025`.

Four columns, and each one exists because a stated acceptance criterion cannot
be met without it.

**`last_error`** — "a job that fails is visible with its error and a retry,
never silently dropped". `sources.last_error` already existed and is the wrong
place: a source of sixty contracts with one encrypted PDF is not a broken
source, and collapsing the file's reason into the folder's would lose which
file it was. The library expands a source to the document that failed
(`docs/ux/library.md` §3), and this is the string it expands to.

**`size_bytes`** — the estimate. It is already computed while hashing at add
time and was being thrown away, and without it the only honest estimate is one
in files, which says a 4 GB scan and a two-page letter will take the same time.
Nullable because every row recorded before this migration has no size, and the
estimate is withheld rather than guessed when any remaining file's size is
unknown.

**`ingest_ms`** — the *measured* half of the estimate. An estimate with no
throughput history behind it is a fabricated number that reads as measured,
which is what `M1-ADD-FE-022` deliberately refused to print.

**`ingest_pipeline`** — the subtle one, and it does three jobs at once.

It names the sequence of stages that last ran over this document. It is what
makes the estimate honest across a half-built product: throughput is only ever
averaged over documents processed by *the same pipeline that is about to run*,
so when extraction and embedding land, every measurement taken without them is
excluded rather than quietly making a two-hour import look like four minutes.

It is also what stops a completed document being processed forever, and what
makes a newly-arrived capability pick up the backlog on its own. A queued
document is enqueued when its recorded pipeline differs from the current one —
so a document read by today's pipeline stays put, and the day `M1-EXTRACT-ING-026`
adds a stage the signature changes and every waiting document becomes work
again, with no migration and no repair script.

Revision ID: d5e2b8c17f40
Revises: c3d9e1a45b76
Created: 2026-08-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d5e2b8c17f40"
down_revision: str | None = "c3d9e1a45b76"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("size_bytes", sa.BigInteger(), nullable=True))
    op.add_column("documents", sa.Column("last_error", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("ingest_ms", sa.Integer(), nullable=True))
    op.add_column("documents", sa.Column("ingest_pipeline", sa.String(128), nullable=True))

    # The queue's own query: everything not yet done, oldest first. Without it
    # the resume sweep is a sequential scan of every document on the machine,
    # run once a minute forever.
    op.create_index(
        op.f("ix_documents_status_added_at"),
        "documents",
        ["status", "added_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_documents_status_added_at"), table_name="documents")
    op.drop_column("documents", "ingest_pipeline")
    op.drop_column("documents", "ingest_ms")
    op.drop_column("documents", "last_error")
    op.drop_column("documents", "size_bytes")
