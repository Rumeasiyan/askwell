"""Reference numbers survive full-text tokenising.

`docs/backlog/M1-it-answers-from-my-documents.md` ticket `M1-INDEX-DB-033`.

`content_tsv` (`a8208099ef38`) and its GIN index already populate and index
every chunk on write — a generated `STORED` column needs neither application
code nor a re-population step, and none is added here. What is wrong is the
*expression*: Postgres's default parser treats a hyphen immediately before a
digit run as a sign, not a separator, so `to_tsvector('english', 'INV-2024-0917')`
produces the lexemes `'inv'`, `'-2024'`, `'-0917'` — the minus sign baked into
each numeric lexeme. A query for the reference number's own trailing group,
`0917`, produces the lexeme `'0917'` and never matches `'-0917'`. Exactly the
case this ticket names: "tokens like reference numbers that default
tokenising would split badly."

The fix is to stop the parser from ever seeing the hyphen as a sign:
`regexp_replace(content, '-', ' ', 'g')` ahead of `to_tsvector`, so
`INV-2024-0917` tokenises as three independent, signless lexemes
(`'inv'`, `'2024'`, `'0917'`), each one matchable alone. The cost is real and
accepted, not overlooked: a genuine hyphenated English compound
(`well-known`) loses the compound lexeme `'well-known'` the unmodified parser
would have added alongside `'well'` and `'known'` — the two parts still
index and still match individually, only the whole-compound lexeme is gone.
Reasoning and the alternatives rejected (a custom parser extension, a second
normalised column) are in `docs/decisions.md`, 2026-08-28.

A generated column's expression cannot be altered in place — Postgres has no
`ALTER COLUMN ... SET EXPRESSION`. Drop and re-add is the only path, which is
also why this could not simply edit `a8208099ef38`: that migration already
ran, on this machine and potentially on others, and rewriting history under
a live database is worse than a second migration.

Revision ID: c7e2f814a5b3
Revises: 9a1c6e4f2b57
Created: 2026-08-28
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c7e2f814a5b3"
down_revision: str | None = "9a1c6e4f2b57"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TEXT_SEARCH_CONFIG = "english"


def upgrade() -> None:
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


def downgrade() -> None:
    op.drop_index("ix_chunks_content_tsv", table_name="chunks", postgresql_using="gin")
    op.drop_column("chunks", "content_tsv")
    op.execute(
        f"ALTER TABLE chunks ADD COLUMN content_tsv tsvector "
        f"GENERATED ALWAYS AS "
        f"(to_tsvector('{TEXT_SEARCH_CONFIG}', coalesce(content, ''))) STORED"
    )
    op.create_index(
        "ix_chunks_content_tsv", "chunks", ["content_tsv"], unique=False, postgresql_using="gin"
    )
