#!/bin/bash
# Create Askwell's two non-owner database roles.
#
# Runs once, from the Postgres image's initialisation hook, on an empty data
# directory. It is here rather than in the migration because these roles need
# passwords, and a password in a migration is a password in the repository (C8).
#
# The split is deliberate:
#   this script   creates the roles and sets their credentials
#   the migration grants and revokes — which is where C6 actually lives
#
# Both halves are idempotent, and the migration creates either role if it is
# somehow absent, so a database that missed this hook still gets a correct
# permission model. What it would not get is a usable password, and it says so.

set -euo pipefail

if [ -z "${POSTGRES_APP_PASSWORD:-}" ]; then
    echo "FATAL: POSTGRES_APP_PASSWORD is not set." >&2
    echo "Askwell does not connect as the table owner: an owner bypasses its" >&2
    echo "own grants, which would make the audit log's append-only guarantee" >&2
    echo "decorative. Copy .env.example to .env and set it." >&2
    exit 1
fi

psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set ON_ERROR_STOP=1 <<SQL
DO \$\$
BEGIN
    -- The application. Owns nothing, so the grants in the migration are real.
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'askwell_app') THEN
        CREATE ROLE askwell_app LOGIN PASSWORD '${POSTGRES_APP_PASSWORD}';
    ELSE
        ALTER ROLE askwell_app LOGIN PASSWORD '${POSTGRES_APP_PASSWORD}';
    END IF;

    -- Read-only, and independent of the application role. Its real use arrives
    -- with SQL execution against the user's own data: model-generated SQL is
    -- parsed and rejected by sqlglot AND runs as a role that cannot write,
    -- because one check is not a guarantee (C2).
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'askwell_readonly') THEN
        CREATE ROLE askwell_readonly LOGIN PASSWORD '${POSTGRES_READONLY_PASSWORD:-$POSTGRES_APP_PASSWORD}';
    ELSE
        ALTER ROLE askwell_readonly LOGIN PASSWORD '${POSTGRES_READONLY_PASSWORD:-$POSTGRES_APP_PASSWORD}';
    END IF;
END
\$\$;

GRANT CONNECT ON DATABASE "$POSTGRES_DB" TO askwell_app, askwell_readonly;
SQL

echo "askwell_app and askwell_readonly created."
