"""Grant the application role `DELETE` on `audit_interactions`, and nowhere
else.

`docs/audit-log.md` §4 and §8, ticket `M7-LOG-BE-154`.

`20260827_a8208099ef38`'s own v1 schema revoked `UPDATE`, `DELETE` and
`TRUNCATE` on both audit tables from `askwell_app`, uniformly — at the time,
nothing in the application had a legitimate reason to remove a row from
either, and "the app cannot rewrite history" was the whole guarantee C6
makes. This ticket is the first legitimate reason: a rolling retention
window that prunes interactions after they are exported. Decisions are never
pruned (`docs/audit-log.md` §8, this ticket's own Out of Scope) and keep the
original grant untouched — `SELECT, INSERT` only, forever.

**Why a grant change rather than an application-level exception.** The whole
point of enforcing C6 with a database grant, rather than only application
code, is that a bug cannot bypass it. Loosening the grant is the only way to
make `askwell.retention.prune`'s `DELETE` legal at all — and it is scoped as
narrowly as the feature that needs it: `audit_interactions` gains `DELETE`
alone, not `UPDATE` or `TRUNCATE`, so a pruned record can be removed but
never silently rewritten in place, and the table cannot be emptied in one
statement outside of `prune`'s own `WHERE occurred_at < :cutoff`.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c3a91f5e7d02"
down_revision: str | None = "bb5cfc0e8e91"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "askwell_app"


def upgrade() -> None:
    op.execute(f"GRANT DELETE ON audit_interactions TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE DELETE ON audit_interactions FROM {APP_ROLE}")
