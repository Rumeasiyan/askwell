"""A queued status for sources and documents.

`docs/backlog/M1-it-answers-from-my-documents.md` ticket `M1-ADD-BE-023`.

**`queued` is a real status, not `indexing` used loosely.** A row created by the
add flow has been recorded and hashed and nothing is reading it: the ingester
arrives with `M1-ADD-ING-025`. Storing that as `indexing` would make the library
render a progress bar for work that has not started, which is the one thing
`docs/states-and-edge-cases.md` §3 says plainly must not happen — "files queued
but nothing indexed yet" is an honest sentence, and a spinner is a bug report.
The default moves with it, because a default that lies is worse than no default:
a repair script or a `psql` session inserting a row would otherwise claim work
was underway.

**No index is created here, deliberately.** The ticket asks for a partial unique
index over one live version per source and hash; the v1 migration already
created it as `uq_documents_live_source_id_sha256`, in raw SQL, and a second
index over the same columns would be a duplicate that costs a write on every
insert and answers no question the first one does not. What was missing was its
*declaration* — `askwell.db.models` now carries it, so an autogenerate run
stops proposing to drop an index every database has.

Revision ID: c3d9e1a45b76
Revises: b1f4c7d2a913
Created: 2026-08-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3d9e1a45b76"
down_revision: str | None = "b1f4c7d2a913"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = "status IN ('indexing', 'ready', 'attention', 'deleted')"
_NEW = "status IN ('queued', 'indexing', 'ready', 'attention', 'deleted')"


def upgrade() -> None:
    for table in ("sources", "documents"):
        # `op.f` marks the name as already conventional. Without it the naming
        # convention is applied a second time and the constraint comes back as
        # `ck_sources_ck_sources_status`, which the downgrade then cannot drop.
        op.drop_constraint(op.f(f"ck_{table}_status"), table, type_="check")
        op.create_check_constraint(op.f(f"ck_{table}_status"), table, _NEW)
        op.alter_column(table, "status", server_default=sa.text("'queued'"))


def downgrade() -> None:
    # Rows in the status this migration introduced have to go somewhere before
    # the old constraint can be restored, and `indexing` is where they came
    # from. Failing here instead would leave a database that cannot be
    # downgraded at all, which is not reversible in any sense worth the word.
    op.execute("UPDATE sources SET status = 'indexing' WHERE status = 'queued'")
    op.execute("UPDATE documents SET status = 'indexing' WHERE status = 'queued'")

    for table in ("sources", "documents"):
        op.alter_column(table, "status", server_default=sa.text("'indexing'"))
        op.drop_constraint(op.f(f"ck_{table}_status"), table, type_="check")
        op.create_check_constraint(op.f(f"ck_{table}_status"), table, _OLD)
