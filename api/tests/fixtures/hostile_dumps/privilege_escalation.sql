-- M4-DUMP-SEC-091: a dump that tries to make the owner role a superuser.
-- `askwell_sandbox_owner` is created NOSUPERUSER by deploy/sandbox/10-roles.sh
-- and cannot grant itself what it does not have.
ALTER ROLE askwell_sandbox_owner SUPERUSER;
