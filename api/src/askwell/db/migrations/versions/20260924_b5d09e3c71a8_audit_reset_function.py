"""Add `askwell_reset_audit()`: the one path that can empty the audit tables.

Ticket `M7-DATA-BE-159a`, issue #523, `AGENTS.md` §3 C6.

`askwell_app` has no `UPDATE`, `DELETE` or `TRUNCATE` on either audit table
(`a8208099ef38`'s `_grant_privileges`), which is what makes "the application
never rewrites history" a grant rather than an intention. It also made reset
impossible: a user-confirmed "destroy everything" could never destroy the
audit stores, and a reset that cannot finish is worse than none. C6's own text
already allows this deletion — the user owns the machine — so the fix is a
privilege exactly as wide as that one act, not a broader grant.

**Three layers, each narrow on its own.**

1. A dedicated `NOLOGIN` role, `askwell_audit_reset`, holding `SELECT` and
   `TRUNCATE` on the two audit tables and nothing else. It owns the function,
   so even a bug in the function body cannot reach any other table. It cannot
   log in, so no credential for it exists anywhere (C8).
2. `askwell_reset_audit()` is `SECURITY DEFINER` as that role, with
   `EXECUTE` revoked from `PUBLIC` and granted to `askwell_app` alone — so
   `askwell_readonly`, the role model-generated SQL runs as (C2), cannot call
   it at all.
3. The function refuses unless the newest decisions record is a
   `reset_requested` inserted by the *current* transaction (`xmin` is the
   transaction's own id). A caller therefore cannot empty the audit tables
   without first recording, in the same transaction, that it is doing so —
   and a stray `SELECT askwell_reset_audit()` from anywhere else is refused.
   The advisory lock is the one `askwell.audit.record` takes, so nothing can
   append between the check and the truncate.

`search_path` is pinned and every table is schema-qualified: a `SECURITY
DEFINER` function that resolves names through the caller's path can be
steered at a lookalike object.

**Rejected:** granting `askwell_app` `TRUNCATE` (every code path would then
hold it — C6 would be advisory); a second, elevated connection used only by
reset (a second credential inside the application, sitting next to every
other path — option 2 of #523); one definer function truncating *every*
table (the non-audit tables need no elevated privilege — `askwell_app` can
already `DELETE` them — so elevating them too widens the privilege for
nothing).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b5d09e3c71a8"
down_revision: str | None = "e8b3f61a92d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "askwell_app"
RESET_ROLE = "askwell_audit_reset"
AUDIT_TABLES = ("audit_decisions", "audit_interactions")
FUNCTION = "public.askwell_reset_audit()"


def upgrade() -> None:
    # Created here rather than in the initialisation hook: it has no password
    # and never logs in, so there is nothing for the hook (C8) to hold. Roles
    # are cluster-wide, hence the existence check.
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{RESET_ROLE}') THEN
                CREATE ROLE {RESET_ROLE} NOLOGIN;
            END IF;
        END
        $$;
        """
    )
    op.execute(f"GRANT USAGE ON SCHEMA public TO {RESET_ROLE}")
    for table in AUDIT_TABLES:
        op.execute(f"GRANT SELECT, TRUNCATE ON public.{table} TO {RESET_ROLE}")

    op.execute(
        f"""
        CREATE FUNCTION {FUNCTION} RETURNS void
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        AS $$
        DECLARE
            newest_kind text;
            newest_xmin xid;
        BEGIN
            PERFORM pg_advisory_xact_lock(hashtext('audit_decisions'));
            SELECT kind, xmin INTO newest_kind, newest_xmin
              FROM public.audit_decisions
             ORDER BY occurred_at DESC, id DESC
             LIMIT 1;
            IF newest_kind IS DISTINCT FROM 'reset_requested'
               OR newest_xmin IS DISTINCT FROM pg_current_xact_id()::xid THEN
                RAISE EXCEPTION
                    'the audit tables can only be cleared by a reset recorded in this transaction'
                    USING ERRCODE = 'insufficient_privilege';
            END IF;
            TRUNCATE public.audit_decisions, public.audit_interactions;
        END
        $$
        """
    )
    op.execute(f"ALTER FUNCTION {FUNCTION} OWNER TO {RESET_ROLE}")
    op.execute(f"REVOKE ALL ON FUNCTION {FUNCTION} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {FUNCTION} TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"DROP FUNCTION IF EXISTS {FUNCTION}")
    for table in AUDIT_TABLES:
        op.execute(f"REVOKE SELECT, TRUNCATE ON public.{table} FROM {RESET_ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {RESET_ROLE}")
    # The role is deliberately not dropped, the same as `a8208099ef38`'s: it is
    # cluster-wide, and another database on the same server may still hold
    # grants to it.
