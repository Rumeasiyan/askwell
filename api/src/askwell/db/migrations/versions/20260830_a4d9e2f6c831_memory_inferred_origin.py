"""Widen `memory.origin` to include `inferred`.

`docs/backlog/M3-it-learns-my-material.md` ticket `M3-RAISE-BE-068`.

**The check as written could not store what the ticket requires.** A
candidate that fails one of the three tests for asking is inferred instead
of asked and "recorded as an inference with low confidence... visible in
memory" (the ticket's own Acceptance Criteria) — but `memory.origin` only
allowed `clarification`, `correction` and `manual`, none of which is true of
a fact nobody was ever asked about. `schema_notes.origin` already
distinguishes `user` from `inferred`, and `docs/architecture.md`'s own
standing note ("User-supplied `schema_notes` and `memory` outrank inferred
ones") assumes `memory` carries the same distinction — the origin list
simply never caught up. `docs/decisions.md`, 2026-08-30, has the full
reasoning.

Revision ID: a4d9e2f6c831
Revises: 5f3a7c1e9d42
Created: 2026-08-30
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a4d9e2f6c831"
down_revision: str | None = "5f3a7c1e9d42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = "origin IN ('clarification', 'correction', 'manual')"
_NEW = "origin IN ('clarification', 'correction', 'manual', 'inferred')"


# `op.f()` on both the drop and the create. The name is already final — the v1
# schema created it with `op.f("ck_memory_origin")` — and without the marker
# Alembic's naming convention applies `ck_%(table_name)s_%(constraint_name)s`
# again and looks for `ck_memory_ck_memory_origin`, which has never existed.
#
# The drop is the one that actually failed here, and it fails as
# `UndefinedObject` rather than as anything mentioning naming. It takes down
# every database test at setup, so 276 tests report a fault whose cause is one
# missing marker in a file none of them mention.
def upgrade() -> None:
    op.drop_constraint(op.f("ck_memory_origin"), "memory", type_="check")
    op.create_check_constraint(op.f("ck_memory_origin"), "memory", _NEW)


def downgrade() -> None:
    op.drop_constraint(op.f("ck_memory_origin"), "memory", type_="check")
    op.create_check_constraint(op.f("ck_memory_origin"), "memory", _OLD)
