-- M4-DUMP-SEC-091: a dump that tries to never finish loading. The time cap
-- (M4-DUMP-VAL-089) is what actually stops this, via the watchdog thread in
-- `_load_blocking` that kills the client rather than waiting out the
-- statement — the test sets that cap low before importing this fixture.
SELECT pg_sleep(999999);
