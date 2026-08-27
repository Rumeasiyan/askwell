"""`queued` as a status a source and a document can actually be in.

`docs/backlog/M1-it-answers-from-my-documents.md` ticket `M1-ADD-BE-023`.

The v1 schema had four statuses — `indexing`, `ready`, `attention`, `deleted` —
and that was right at the time, because nothing created a row before the worker
was already looking at it. `M1-ADD-BE-023` is the ticket that changes it: rows
are written the moment a file is recognised, and everything then waits, which on
a laptop embedding a large corpus is where a document spends most of its life.

Calling that state `indexing` costs one specific sentence.
`docs/states-and-edge-cases.md` §3 requires that files queued with nothing
indexed yet are *said plainly, with what has to land before they are
searchable* — explicitly "not a progress bar that never moves". A status that
also means "being read right now" cannot produce that sentence, and the
interface would have to guess from a second signal that does not exist.

`indexed` from the ticket text stays `ready`: the schema's word, in the ORM, in
`docs/architecture.md` §7, and in the check constraint. Renaming it to match
prose would touch every one of those to say the same thing.

The default moves with the vocabulary. A row inserted by a repair script or by
`psql` should land in the same state as one the application inserts, and a
default that says `indexing` about a row no worker has seen is a lie the
database tells on its own initiative.

Revision ID: c3a5e91b6d47
Revises: b1f4c7d2a913
Created: 2026-08-27
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c3a5e91b6d47"
down_revision: str | None = "b1f4c7d2a913"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("sources", "documents")

WITH_QUEUED = "('queued', 'indexing', 'ready', 'attention', 'deleted')"
WITHOUT_QUEUED = "('indexing', 'ready', 'attention', 'deleted')"


def upgrade() -> None:
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT ck_{table}_status")
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT ck_{table}_status "
            f"CHECK (status IN {WITH_QUEUED})"
        )
        op.execute(f"ALTER TABLE {table} ALTER COLUMN status SET DEFAULT 'queued'")


def downgrade() -> None:
    """Reversible, and the collapse it performs is stated rather than silent.

    Going back means the vocabulary loses a value that rows are in. They are
    moved to `indexing` first — the nearest true thing, since a queued document
    is one on its way to being indexed — because the alternative is a
    `downgrade` that fails halfway on a constraint violation and leaves the
    database in neither version.
    """
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ALTER COLUMN status SET DEFAULT 'indexing'")
        op.execute(f"UPDATE {table} SET status = 'indexing' WHERE status = 'queued'")
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT ck_{table}_status")
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT ck_{table}_status "
            f"CHECK (status IN {WITHOUT_QUEUED})"
        )
