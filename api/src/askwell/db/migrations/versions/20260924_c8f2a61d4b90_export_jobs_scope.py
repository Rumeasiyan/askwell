"""Add `export_jobs.scope`: a log export, or everything.

Ticket `M7-DATA-FE-160`, `docs/ux/settings.md` §6.

"Export everything" is the log export plus the rest of what Askwell holds —
sources, memory, clarifications, conversations — in the same zip, beside the
same chain and the same standalone verifier. It is the same job with more
files in it, not a second job type: one table, one worker entry point, one
download route, one passphrase acknowledgement. `scope` is what tells
`askwell.log_export.run_job` which of the two to write.

`'log'` is the server default so every existing row, and every existing
caller that never names a scope, keeps meaning exactly what it meant.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c8f2a61d4b90"
down_revision: str | None = "b5d09e3c71a8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "export_jobs",
        sa.Column("scope", sa.String(length=16), server_default=sa.text("'log'"), nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_export_jobs_scope"), "export_jobs", "scope IN ('log', 'everything')"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_export_jobs_scope"), "export_jobs", type_="check")
    op.drop_column("export_jobs", "scope")
