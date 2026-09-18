-- M4-DUMP-SEC-091: a dump that tries to read the host's files through a
-- program invoked by COPY FROM PROGRAM. Only pg_execute_server_program may
-- do this, and the owner role is not a member of it.
CREATE TABLE stolen (line text);
COPY stolen FROM PROGRAM 'cat /etc/passwd';
