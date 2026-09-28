"""Add `askwell_prune_interactions()`: the one path that can delete interactions.

Ticket `M9-FIX-SEC-208`, issue #682, `AGENTS.md` §3 C6.

`askwell.log_prune` deleted from `audit_interactions` on the app's own
session, and `askwell_app` has no `DELETE` on either audit table
(`a8208099ef38`'s `_grant_privileges`). So a prune was refused with
`permission denied` on every real install. The tests connected as the
superuser owner, and the shared development database carried a `DELETE` grant
no migration ever made, so nothing showed it. Same shape as #523, and the
same fix `b5d09e3c71a8` made for reset: a privilege exactly as wide as the
one recorded act, not a broader grant.

**Three layers, each narrow on its own.**

1. A dedicated `NOLOGIN` role, `askwell_audit_prune`, holding `SELECT` and
   `DELETE` on `audit_interactions` and `SELECT` on `audit_decisions`. Nothing
   else: it cannot delete a decisions record, and it cannot touch any other
   table. It owns the function, so a bug in the function body stays inside
   those grants. It cannot log in, so no credential for it exists (C8).
2. `askwell_prune_interactions()` is `SECURITY DEFINER` as that role, with
   `EXECUTE` revoked from `PUBLIC` and granted to `askwell_app` alone.
   `askwell_readonly`, the role model-generated SQL runs as (C2), cannot call
   it.
3. The function takes no arguments. It refuses unless the newest decisions
   record is an `interactions_pruned` inserted by the *current* transaction,
   and it deletes only what that record says: rows older than its `cutoff`.
   The number deleted must equal its `pruned_count`, and the newest deleted
   row's hash must equal its `boundary_hash`. Otherwise it raises and the
   transaction, record included, rolls back. So the record `audit.verify`
   relies on to explain the gap is the same record that authorised it, and
   it cannot describe a different gap from the one made.

The advisory locks are the ones `askwell.audit.record` takes, in the order
`log_prune.run_job` takes them (interactions, then decisions). Nothing can
append between the check and the delete.

**The development database's drifted grant.** The same migration revokes
`UPDATE`, `DELETE` and `TRUNCATE` on both audit tables from `askwell_app`
again. On a real install that is a no-op, because they were never granted. On
the development stack it removes the stray `DELETE` that hid the bug, so both
agree.

**Rejected:** granting `askwell_app` `DELETE` on `audit_interactions` (every
code path would then hold it, and C6 would become a convention; option 2 of
#682). Reusing `askwell_audit_reset` (it holds `TRUNCATE` on both tables, far
wider than a prune needs). Passing the cutoff as an argument (a caller could
then delete a range the record does not describe).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f4b8d2c6a915"
down_revision: str | None = "e1c5a8f3b207"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "askwell_app"
PRUNE_ROLE = "askwell_audit_prune"
AUDIT_TABLES = ("audit_decisions", "audit_interactions")
FUNCTION = "public.askwell_prune_interactions()"


def upgrade() -> None:
    # Roles are cluster-wide, hence the existence check. No password: it never
    # logs in, so there is nothing for the initialisation hook (C8) to hold.
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{PRUNE_ROLE}') THEN
                CREATE ROLE {PRUNE_ROLE} NOLOGIN;
            END IF;
        END
        $$;
        """
    )
    op.execute(f"GRANT USAGE ON SCHEMA public TO {PRUNE_ROLE}")
    op.execute(f"GRANT SELECT ON public.audit_decisions TO {PRUNE_ROLE}")
    op.execute(f"GRANT SELECT, DELETE ON public.audit_interactions TO {PRUNE_ROLE}")

    op.execute(
        f"""
        CREATE FUNCTION {FUNCTION} RETURNS integer
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        AS $$
        DECLARE
            newest_kind text;
            newest_xmin xid;
            newest_payload jsonb;
            prune_cutoff timestamptz;
            deleted integer;
            newest_deleted_hash text;
        BEGIN
            PERFORM pg_advisory_xact_lock(hashtext('audit_interactions'));
            PERFORM pg_advisory_xact_lock(hashtext('audit_decisions'));
            SELECT kind, xmin, payload INTO newest_kind, newest_xmin, newest_payload
              FROM public.audit_decisions
             ORDER BY occurred_at DESC, id DESC
             LIMIT 1;
            IF newest_kind IS DISTINCT FROM 'interactions_pruned'
               OR newest_xmin IS DISTINCT FROM pg_current_xact_id()::xid THEN
                RAISE EXCEPTION
                    'interactions can only be deleted by a prune recorded in this transaction'
                    USING ERRCODE = 'insufficient_privilege';
            END IF;

            prune_cutoff := (newest_payload->>'cutoff')::timestamptz;
            WITH gone AS (
                DELETE FROM public.audit_interactions
                 WHERE occurred_at < prune_cutoff
             RETURNING id, hash, occurred_at
            )
            SELECT count(*), (array_agg(hash ORDER BY occurred_at DESC, id DESC))[1]
              INTO deleted, newest_deleted_hash
              FROM gone;

            IF deleted IS DISTINCT FROM (newest_payload->>'pruned_count')::integer
               OR newest_deleted_hash IS DISTINCT FROM newest_payload->>'boundary_hash' THEN
                RAISE EXCEPTION
                    'the prune record does not describe the rows its cutoff would delete'
                    USING ERRCODE = 'insufficient_privilege';
            END IF;
            RETURN deleted;
        END
        $$
        """
    )
    op.execute(f"ALTER FUNCTION {FUNCTION} OWNER TO {PRUNE_ROLE}")
    op.execute(f"REVOKE ALL ON FUNCTION {FUNCTION} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {FUNCTION} TO {APP_ROLE}")

    # Issue #682: the development database carried a `DELETE` grant on
    # `audit_interactions` that no migration made. Re-stating the v1 revoke
    # brings every database to the same grants; on a real install it changes
    # nothing.
    for table in AUDIT_TABLES:
        op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON public.{table} FROM {APP_ROLE}")


def downgrade() -> None:
    # The revoke is not undone: the grant it removes was never one a
    # migration made, and restoring drift is not a downgrade.
    op.execute(f"DROP FUNCTION IF EXISTS {FUNCTION}")
    op.execute(f"REVOKE SELECT, DELETE ON public.audit_interactions FROM {PRUNE_ROLE}")
    op.execute(f"REVOKE SELECT ON public.audit_decisions FROM {PRUNE_ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {PRUNE_ROLE}")
    # The role is deliberately not dropped, the same as `b5d09e3c71a8`'s: it is
    # cluster-wide, and another database on the same server may still hold
    # grants to it.
