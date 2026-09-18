-- M4-DUMP-SEC-091: a dump that tries to reach another database on the same
-- sandbox instance via psql's own \connect meta-command. `postgres` is the
-- instance's maintenance database, locked down instance-wide by
-- deploy/sandbox/10-roles.sh (PUBLIC's CONNECT revoked); the owner role's own
-- per-database CONNECT grant (askwell.sandbox.create_database) names only the
-- database it was created for. With --set ON_ERROR_STOP=1, a failed \connect
-- aborts the script the same as a failed statement.
\connect postgres
SELECT 1;
