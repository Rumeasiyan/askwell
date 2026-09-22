"""Web citation records, stored with the turn. `M6.5-WEB-BE-189`.

`docs/web-search.md` §4, `docs/backlog/M6.5-it-can-look-outside.md` ticket
`M6.5-WEB-BE-189`: a web result used in an answer carries its domain, title,
URL, passage and the time it was retrieved — permanently, and never
refreshed. `web_citations` is a table of its own, not a nullable column
bolted onto `citations`, because `citations.chunk_id` is a `NOT NULL`
foreign key into `chunks` and a web result was never a chunk. C10 requires a
web result never share a rendering with a document citation; a shared record
shape would leave that up to every reader to enforce by convention instead
of by construction.

`retrieved_at` is `NOT NULL` — the ticket's own Validation Rule that an
undated web citation may not be rendered starts here, at the row's own
shape, rather than at whichever surface reads it back.

Revision ID: d3e6b1a94f02
Revises: c4a1f8d02e77
Created: 2026-09-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d3e6b1a94f02"
down_revision: str | None = "c4a1f8d02e77"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "web_citations",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("message_id", sa.UUID(), nullable=False),
        sa.Column("claim_ordinal", sa.Integer(), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("passage", sa.Text(), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["messages.id"],
            name=op.f("fk_web_citations_message_id_messages"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_web_citations")),
    )
    op.create_index("ix_web_citations_message_id", "web_citations", ["message_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_web_citations_message_id", table_name="web_citations")
    op.drop_table("web_citations")
