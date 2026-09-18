-- M4-DUMP-SEC-091: a dump that tries to grow its sandbox database without
-- bound. `askwell.dump_import`'s size cap (M4-DUMP-VAL-089) is what actually
-- stops this — the test sets that cap low before importing this fixture, the
-- same way test_dump_import.py's own cap tests do, so this aborts quickly
-- rather than the suite needing to actually fill a disk.
CREATE TABLE bloat (payload text);
INSERT INTO bloat (payload)
SELECT repeat('x', 1000) FROM generate_series(1, 2000000);
