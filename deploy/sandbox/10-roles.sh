#!/bin/bash
# Lock down the sandbox instance and create its two fixed roles.
#
# Runs once, from the Postgres image's initialisation hook, on an empty data
# directory. Two things happen here:
#
#   1. PUBLIC's default CONNECT is revoked on `template1` and `postgres` —
#      the two databases that exist before `askwell.sandbox` ever runs, and
#      the only two nothing else here locks down. This does **not** protect a
#      database `create_database` creates later: `CREATE DATABASE` does not
#      copy `template1`'s ACL onto what it creates, verified by creating one
#      and inspecting `pg_database.datacl` — a null ACL, which means "the
#      built-in default applies" and that default is PUBLIC has CONNECT. So
#      `create_database` revokes CONNECT on its own database explicitly,
#      itself, immediately after creating it; what happens here is
#      independent of that and only closes the two pre-existing databases.
#   2. `askwell_sandbox_owner` and `askwell_sandbox_readonly` are created,
#      restricted the same way `deploy/postgres/10-roles.sh` restricts
#      `askwell_app`: no superuser, no way to create more roles or more
#      databases. Dump content runs as the owner (C3) — NOCREATEDB matters
#      here specifically, because a dump that could create a database could
#      make itself a second, unmonitored one to hide in.
#
# "No large-object access" covers two different APIs. `lo_import`/`lo_export`
# read and write the *server's* filesystem and are already restricted to
# superusers and the `pg_read_server_files`/`pg_write_server_files` roles by
# Postgres itself since v11 — the revokes below are belt-and-suspenders
# against a future version changing that default, not a gap being closed
# (one check is not a guarantee, the same reasoning C2 applies to `sqlglot`).
# The client-side large-object API — `lo_creat`, `lo_open`, `lo_read`,
# `lo_write` and the rest — is genuinely open to any role by default: it
# stores arbitrary binary data inside `pg_largeobject`, not on disk, so
# Postgres does not restrict it on its own. That is what the revokes on those
# functions are actually for.

set -euo pipefail

if [ -z "${SANDBOX_OWNER_PASSWORD:-}" ]; then
    echo "FATAL: SANDBOX_OWNER_PASSWORD is not set." >&2
    echo "Copy .env.example to .env and set it. It is never committed (C8)." >&2
    exit 1
fi
if [ -z "${SANDBOX_READONLY_PASSWORD:-}" ]; then
    echo "FATAL: SANDBOX_READONLY_PASSWORD is not set." >&2
    echo "Copy .env.example to .env and set it. It is never committed (C8)." >&2
    exit 1
fi


# "postgres", not "$POSTGRES_DB": this instance carries no per-application
# database of its own — every database it holds beyond the three Postgres
# always creates (postgres, template0, template1) is one askwell.sandbox
# created for an imported source, and the superuser's home for doing that
# is the ordinary maintenance database.
psql --username "$POSTGRES_USER" --dbname postgres --set ON_ERROR_STOP=1 <<SQL
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'askwell_sandbox_owner') THEN
        CREATE ROLE askwell_sandbox_owner LOGIN PASSWORD '${SANDBOX_OWNER_PASSWORD}'
            NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
    ELSE
        ALTER ROLE askwell_sandbox_owner LOGIN PASSWORD '${SANDBOX_OWNER_PASSWORD}'
            NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'askwell_sandbox_readonly') THEN
        CREATE ROLE askwell_sandbox_readonly LOGIN PASSWORD '${SANDBOX_READONLY_PASSWORD}'
            NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
    ELSE
        ALTER ROLE askwell_sandbox_readonly LOGIN PASSWORD '${SANDBOX_READONLY_PASSWORD}'
            NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
    END IF;
END
\$\$;

-- Closes the two databases that exist before this script runs. Does not
-- reach any database askwell.sandbox creates afterwards — see the module
-- comment above for why, and askwell.sandbox.create_database for where that
-- is actually handled.
REVOKE CONNECT ON DATABASE template1 FROM PUBLIC;
REVOKE CONNECT ON DATABASE postgres FROM PUBLIC;

-- Filesystem large objects: belt-and-suspenders, see the module comment.
REVOKE EXECUTE ON FUNCTION pg_catalog.lo_import(text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION pg_catalog.lo_import(text, oid) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION pg_catalog.lo_export(oid, text) FROM PUBLIC;

-- Client-side large objects: not restricted by Postgres itself, and this is
-- what actually restricts them. Run against template1 deliberately: unlike
-- `pg_database.datacl` above, function privileges live in `pg_proc`, a
-- per-database catalog that `CREATE DATABASE` physically copies from its
-- template — so a revoke made here, once, is present in every database
-- askwell.sandbox creates afterwards. Verified by creating a database from
-- this template1 and confirming `lo_creat`/`lo_import` are both refused in
-- it without repeating either revoke.
-- Every pg_catalog.lo_* / lo* function that exists on this version, checked
-- against a running pg18 instance rather than assumed — AGENTS.md §4.
\c template1
REVOKE EXECUTE ON FUNCTION pg_catalog.lo_creat(integer) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION pg_catalog.lo_create(oid) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION pg_catalog.lo_open(oid, integer) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION pg_catalog.lo_close(integer) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION pg_catalog.lo_unlink(oid) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION pg_catalog.lo_lseek(integer, integer, integer) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION pg_catalog.lo_lseek64(integer, bigint, integer) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION pg_catalog.lo_tell(integer) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION pg_catalog.lo_tell64(integer) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION pg_catalog.lo_truncate(integer, integer) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION pg_catalog.lo_truncate64(integer, bigint) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION pg_catalog.lo_get(oid) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION pg_catalog.lo_get(oid, bigint, integer) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION pg_catalog.lo_put(oid, bigint, bytea) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION pg_catalog.lo_from_bytea(oid, bytea) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION pg_catalog.loread(integer, integer) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION pg_catalog.lowrite(integer, bytea) FROM PUBLIC;
SQL

echo "askwell_sandbox_owner and askwell_sandbox_readonly created; template1 and postgres locked to PUBLIC."
