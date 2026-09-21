"""Chunk content stops being a generated column, and gains an encrypted flag.

`M7-SEC-BE-152`. Encrypting `chunks.content` with the passphrase-derived key
(`askwell.crypto`, `askwell.passphrase`) means the column can hold either
plaintext or a Fernet token depending on whether a passphrase is set —
`content_encrypted` says which, per row, because migrating the whole corpus
is a resumable batch process (`askwell.content_encryption`) and a row caught
mid-migration must be self-describing rather than inferred from a global
flag that could be stale relative to it.

`content_tsv` cannot stay a `GENERATED ALWAYS AS (to_tsvector(content))`
column once `content` may hold ciphertext: Postgres would tokenise the
Fernet token's own base64 bytes, producing a search index full of garbage
lexemes instead of failing loudly. `docs/architecture.md` §7's own standing
note on this table ("index structures and metadata remain readable") is what
makes this the accepted trade rather than a bug: `content_tsv` stays derived
from *plaintext* at write time, computed by the application
(`askwell.chunk.run`) before encryption ever happens, and persisted as an
ordinary column from here on — `ALTER COLUMN ... DROP EXPRESSION` keeps
every row's current value exactly as the generated expression last computed
it, so this migration needs no backfill.

Revision ID: b7e91a4c3f65
Revises: 7f40fa52d49d
Created: 2026-09-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7e91a4c3f65"
down_revision: str | None = "7f40fa52d49d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TEXT_SEARCH_CONFIG = "english"


def upgrade() -> None:
    op.execute("ALTER TABLE chunks ALTER COLUMN content_tsv DROP EXPRESSION")
    op.add_column(
        "chunks",
        sa.Column("content_encrypted", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    # A row holding a Fernet token rather than plaintext (`content_encrypted`
    # true) downgrades to a generated `content_tsv` computed from that
    # token's own bytes — garbage lexemes, not an error. Downgrading a
    # database that ever had a passphrase set needs `remove_passphrase` run
    # first; this migration does not attempt to detect or refuse that case.
    op.drop_column("chunks", "content_encrypted")
    op.drop_index("ix_chunks_content_tsv", table_name="chunks", postgresql_using="gin")
    op.drop_column("chunks", "content_tsv")
    op.execute(
        f"ALTER TABLE chunks ADD COLUMN content_tsv tsvector "
        f"GENERATED ALWAYS AS "
        f"(to_tsvector('{TEXT_SEARCH_CONFIG}', "
        f"regexp_replace(coalesce(content, ''), '-', ' ', 'g'))) STORED"
    )
    op.create_index(
        "ix_chunks_content_tsv", "chunks", ["content_tsv"], unique=False, postgresql_using="gin"
    )
