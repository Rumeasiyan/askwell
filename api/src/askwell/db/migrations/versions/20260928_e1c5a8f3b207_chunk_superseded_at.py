"""Let a re-index retire a cited chunk instead of deleting it.

Ticket `M9-FIX-BE-203`, issue #719. `askwell.chunk.run` used to replace a
document's passages with `DELETE FROM chunks WHERE document_id = :id`, and
`citations.chunk_id` is deliberately not cascade-delete, so re-indexing any
document an answer had ever cited failed at the chunk stage on
`fk_citations_chunk_id_chunks`. Cascading would have been worse: old answers
would silently lose their citations (C4).

`superseded_at` is the chunk-level tombstone. A re-index now deletes only the
passages nothing cites and retires the cited ones — `superseded_at` set,
`embedding` and `content_tsv` cleared so neither search can reach them —
keeping `content` so an old citation still resolves to the exact text it
cited, never to different text and never to an error.

Downgrade drops the column. Any retired chunk then looks live again to the
old code, but carries no embedding and no search vector, so retrieval still
cannot return it; the old `embed` stage would re-embed it on that document's
next index. Deleting those rows instead is not possible — they are cited.

Revision ID: e1c5a8f3b207
Revises: d4a7e92b1f35
Created: 2026-09-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e1c5a8f3b207"
down_revision: str | None = "d4a7e92b1f35"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("chunks", sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True))
    # A retired chunk is reachable only through a citation. Refusing the
    # half-done version here, the same way `ck_chunks_cleared_content_has_no_
    # embedding` does for deletion: a superseded passage that still carries a
    # search vector or an embedding would still answer questions.
    op.create_check_constraint(
        op.f("ck_chunks_superseded_is_unsearchable"),
        "chunks",
        "superseded_at IS NULL OR (embedding IS NULL AND content_tsv IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_chunks_superseded_is_unsearchable"), "chunks", type_="check")
    op.drop_column("chunks", "superseded_at")
