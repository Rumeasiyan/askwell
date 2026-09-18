# Manual test — M4-DUMP-SEC-091, a hostile dump destroys only its own database

**Ticket:** `M4-DUMP-SEC-091` — six hostile fixture dumps, one per attack shape (privilege
escalation, reading host files via `COPY FROM PROGRAM`, connecting to another database on the
instance, reaching the network, exhausting disk, running indefinitely). Each must fail, be
reported, and leave nothing behind except its own dropped sandbox database. Askwell's own
database, other sandbox databases, and the egress proxy's refusal counter must all be
unaffected.
**Version under test:** `0.4.5`
**Time:** about 40 minutes, plus a first stack build.
**Who can run it:** a browser, a terminal, `podman compose exec`.

**What is being checked.** `api/tests/fixtures/hostile_dumps/*.sql` (the six fixtures) run
through `askwell.dump_import.import_dump` the same way `api/tests/test_dump_containment.py`
runs them — that file is the authoritative automated proof, parametrized over all six fixtures
plus one end-to-end run of the whole suite in sequence. This document repeats that same
sequence by hand against a cold-started stack, reading the real sandbox instance's database
list and the real egress proxy's refusal counter directly, rather than through test fixtures
that stand in for them.

**Where this stops on purpose — read before reporting anything below as a defect.**

- **There is still no Add a source screen for dumps.** `web/lib/add-source.ts`'s `ROUTES`
  entry for `dump` still carries `arrives: "M4"` — `M4-DUMP-FE-090`, which wires
  `import_dump_job` to a screen, has not landed. Step 6 below confirms this directly. Every
  import in this document — the one good dump and all six hostile ones — is started from
  inside the running `api` container against `askwell.dump_import` directly, the same
  workaround `M4-DUMP-ING-088`'s and `M4-DUMP-VAL-089`'s manual tests used, because that is
  currently the only way to reach this code at all.
- **Hostile data inside an otherwise well-formed dump is out of scope**, per the ticket's own
  edge cases — a dump that loads cleanly but contains misleading rows is a SQL-validation and
  retrieval concern (C2), not a sandbox-containment one, and none of the six fixtures here
  attempt it.
- **The fixture set is not exhaustive.** Six attack shapes, chosen because they map onto six
  distinct privileges or caps the sandbox role and `dump_import` enforce. Extending it is
  ongoing work, not a gap in this ticket.

None of the above is a defect in `M4-DUMP-SEC-091` — its scope is these six fixtures and the
containment assertions around them. Sections below say which is which.

---

## Before you start

```
cd ~/external/quantum-plus/askwell
```

If you have never run Askwell before:

```
cp -n .env.example .env
```

Open `.env` and confirm every `?set ... in .env` placeholder has a real value.

---

## Cold start

### 1. Remove any previous state

```
podman compose down -v
```

**You should see:** containers and volumes reported removed, or a note there was nothing to
remove.

### 2. Run the checks

```
scripts/dev.sh check
```

**You should see:** lint, format, typecheck and unmarked tests finish with no red error text.

### 3. Bring the stack up and migrate

```
podman compose up -d
scripts/dev.sh db upgrade head
```

**You should see:** `postgres`, `sandbox`, `redis`, `egress-proxy`, `api`, `worker` all
reported created and started, migration finishing with no error.

### 4. Open the app and confirm nothing is alarmed

Open a browser at `http://127.0.0.1:8000`. **You should see:** the shell load with no alarm
banner — `database`, `sandbox`, `queue`, `egress_proxy` and `inference` all reachable.

### 5. Note the baseline: sandbox disk usage and the proxy's refusal counter

```
podman compose exec sandbox psql -U "$SANDBOX_POSTGRES_USER" postgres -tAc \
  "SELECT sum(pg_database_size(datname)) FROM pg_database WHERE datname NOT LIKE 'template%'"
curl -s localhost:8000/network
```

**You should see:** one number, in bytes, for disk usage — note it down, every hostile fixture
below is checked against it returning to this figure. The `curl` prints JSON with
`"available": true` and a `"refused"` count — note that count down too; it must not move
across every step in this document, because the sandbox network has no route to the proxy at
all (`compose.yaml`: the `sandbox` network is `internal: true`) — nothing here can add to it,
which is itself part of what this document is confirming.

### 6. Confirm a dropped dump file still shows as arriving, not addable

Click **Add a source** in the app, then drop any file ending `.sql` anywhere on the page — it
does not need to be a real dump for this step. **You should see:** the file listed under a
block naming it as recognised but *arriving in M4*, in its own colour, never under "queued"
(`docs/ux/add-source.md` §5's "A format arriving in a later milestone" state). This confirms
the gap named above before working around it in every step that follows.

---

## 1. Import one good dump first, so there is something for the attacks to leave alone

### 7. Import a small, legitimate dump

```
podman compose exec api sh -c 'cat > /tmp/good.sql <<EOF
CREATE TABLE widgets (id integer primary key, name text);
INSERT INTO widgets VALUES (1, '"'"'left-handed smoke shifter'"'"');
EOF'
podman compose exec api python3 -c "
import asyncio
from pathlib import Path
from askwell.config import load_settings
from askwell.db.engine import build_engine, session_factory, session_scope
from askwell import dump_import

async def main():
    settings = load_settings()
    engine = build_engine(settings)
    factory = session_factory(engine)
    async with session_scope(factory) as session:
        source_id = await dump_import.create_dump_source(session, 'good dump for containment', '/tmp/good.sql')
    tables = await dump_import.import_dump(factory, settings, source_id, Path('/tmp/good.sql'))
    print('tables', tables, 'source_id', source_id)

asyncio.run(main())
"
```

**You should see:** `tables ['widgets']` and a printed `source_id` — note it down, later steps
confirm this source is untouched by everything that follows.

```
podman compose exec api psql "$ASKWELL_DATABASE_URL" -c \
  "SELECT status, sandbox_db FROM sources WHERE name = 'good dump for containment'"
```

**You should see:** `status` = `ready`, `sandbox_db` non-null — note the database name down as
`GOOD_DB`.

---

## 2. Run each hostile fixture and confirm it fails safely

Copy each fixture out of the repo so it can be read inside the container. Run this once:

```
podman compose cp api/tests/fixtures/hostile_dumps/. api:/tmp/hostile/
```

**You should see:** no error — six `.sql` files now sit at `/tmp/hostile/` inside the `api`
container.

### 8. Privilege escalation — a dump that tries to make its own role superuser

```
podman compose exec api python3 -c "
import asyncio
from pathlib import Path
from askwell.config import load_settings
from askwell.db.engine import build_engine, session_factory, session_scope
from askwell import dump_import

async def main():
    settings = load_settings()
    engine = build_engine(settings)
    factory = session_factory(engine)
    async with session_scope(factory) as session:
        source_id = await dump_import.create_dump_source(session, 'hostile: privilege escalation', '/tmp/hostile/privilege_escalation.sql')
    try:
        await dump_import.import_dump(factory, settings, source_id, Path('/tmp/hostile/privilege_escalation.sql'))
        print('DID NOT FAIL — this is a release blocker')
    except dump_import.DumpImportFailed as exc:
        print('failed safely:', exc)

asyncio.run(main())
"
```

**You should see:** `failed safely:` followed by a reason mentioning the role not having
permission to alter itself into a superuser. If you instead see `DID NOT FAIL`, stop — the
ticket's own validation rule names this a release blocker, not a known issue.

### 9. Reading host files via `COPY FROM PROGRAM`

Repeat step 8's script with `'hostile: read host files'` and
`/tmp/hostile/read_host_files_copy_program.sql`. **You should see:** `failed safely:` with a
reason naming insufficient privilege to execute a server-side program.

### 10. Connecting to another database on the instance

Repeat with `'hostile: connect elsewhere'` and
`/tmp/hostile/connect_to_another_database.sql`. **You should see:** `failed safely:` with a
reason naming the `\connect` (to `postgres`, the instance's maintenance database) failing.

### 11. Reaching the network

Repeat with `'hostile: reach network'` and `/tmp/hostile/reach_network.sql`. **You should
see:** `failed safely:` with a reason naming insufficient privilege to execute a server-side
program — the same privilege step 9 hit, which is why this dump never even reaches the
sandbox network's absent route to the outside.

### 12. Exhausting disk — with the size cap set low first

```
podman compose exec api python3 -c "
import asyncio
from pathlib import Path
from askwell.config import load_settings
from askwell.db.engine import build_engine, session_factory, session_scope
from askwell import dump_import

async def main():
    settings = load_settings()
    engine = build_engine(settings)
    factory = session_factory(engine)
    async with session_scope(factory) as session:
        await dump_import.set_dump_size_cap_bytes(session, 1024)
        source_id = await dump_import.create_dump_source(session, 'hostile: exhaust disk', '/tmp/hostile/exhaust_disk.sql')
    try:
        await dump_import.import_dump(factory, settings, source_id, Path('/tmp/hostile/exhaust_disk.sql'))
        print('DID NOT FAIL — this is a release blocker')
    except dump_import.DumpCapExceeded as exc:
        print('failed safely: cap=', exc.cap, 'message=', exc)

asyncio.run(main())
"
```

**You should see:** `failed safely: cap= size message=` naming the size cap — this is
`M4-DUMP-VAL-089`'s cap doing the stopping, exercised here end to end through a fixture file
rather than a synthetic string.

### 13. Running indefinitely — with the time cap set low first

```
podman compose exec api python3 -c "
import asyncio, time
from pathlib import Path
from askwell.config import load_settings
from askwell.db.engine import build_engine, session_factory, session_scope
from askwell import dump_import

async def main():
    settings = load_settings()
    engine = build_engine(settings)
    factory = session_factory(engine)
    async with session_scope(factory) as session:
        await dump_import.set_dump_time_cap_seconds(session, 0.3)
        source_id = await dump_import.create_dump_source(session, 'hostile: run indefinitely', '/tmp/hostile/run_indefinitely.sql')
    started = time.monotonic()
    try:
        await dump_import.import_dump(factory, settings, source_id, Path('/tmp/hostile/run_indefinitely.sql'))
        print('DID NOT FAIL — this is a release blocker')
    except dump_import.DumpCapExceeded as exc:
        print('failed safely after', round(time.monotonic() - started, 1), 's: cap=', exc.cap)

asyncio.run(main())
"
```

**You should see:** `failed safely after` a number well under the fixture's own
`pg_sleep(999999)`, `cap= time` — the watchdog thread terminated the client rather than
waiting the statement out.

### 14. Reset both caps to their defaults

```
podman compose exec api python3 -c "
import asyncio
from askwell.config import load_settings
from askwell.db.engine import build_engine, session_factory, session_scope
from askwell import dump_import

async def main():
    settings = load_settings()
    engine = build_engine(settings)
    factory = session_factory(engine)
    async with session_scope(factory) as session:
        await dump_import.set_dump_size_cap_bytes(session, dump_import.DEFAULT_DUMP_SIZE_CAP_BYTES)
        await dump_import.set_dump_time_cap_seconds(session, dump_import.DEFAULT_DUMP_TIME_CAP_SECONDS)

asyncio.run(main())
"
```

**You should see:** no error. Cleanup, not part of the acceptance criteria.

---

## 3. Each failure was reported, not just raised

### 15. Confirm every hostile source is left in `attention`, with a reason, and no claimed database

```
podman compose exec api psql "$ASKWELL_DATABASE_URL" -c \
  "SELECT name, status, sandbox_db, last_error FROM sources WHERE name LIKE 'hostile:%' ORDER BY name"
```

**You should see:** six rows, every `status` = `attention`, every `sandbox_db` = `NULL`, every
`last_error` non-empty and naming what actually failed — never a bare `NULL` or generic
"import failed" with no reason.

### 16. Confirm each failure has its own audit record

```
podman compose exec api psql "$ASKWELL_DATABASE_URL" -c \
  "SELECT payload->>'source_id', payload->>'reason' FROM audit_decisions WHERE kind = 'dump_import_failed' ORDER BY created_at"
```

**You should see:** one row per hostile source, `reason` matching `last_error` from step 15 —
the ticket's own "Audit / Logging Requirements": each attempt logged with what was attempted
and how it failed.

---

## 4. Nothing hostile left a trace behind

### 17. Confirm only the good source's database survived

```
podman compose exec sandbox psql -U "$SANDBOX_POSTGRES_USER" postgres -tAc \
  "SELECT datname FROM pg_database WHERE datname NOT LIKE 'template%' AND datname != 'postgres'"
```

**You should see:** exactly one database that isn't `postgres`'s own bookkeeping —
`GOOD_DB` from step 7. None of the six hostile fixtures' databases appear; each was dropped on
failure, never left half-loaded and reachable.

### 18. Confirm sandbox disk usage returned to baseline

```
podman compose exec sandbox psql -U "$SANDBOX_POSTGRES_USER" postgres -tAc \
  "SELECT sum(pg_database_size(datname)) FROM pg_database WHERE datname NOT LIKE 'template%'"
```

**You should see:** step 5's baseline figure plus roughly `GOOD_DB`'s own size from step 7 —
no extra growth from any of the six hostile attempts (`exhaust_disk.sql`'s bloat table in
particular must not appear here).

### 19. Confirm the good source still answers

```
podman compose exec sandbox psql -U askwell_sandbox_readonly -h sandbox -d "GOOD_DB" -c \
  "SELECT id, name FROM widgets"
```

Substitute `GOOD_DB` for the real database name from step 7; enter `SANDBOX_READONLY_PASSWORD`
from `.env` when prompted. **You should see:** the single `left-handed smoke shifter` row —
the source imported before the attacks is completely unaffected by everything run against it
since.

### 20. Confirm Askwell's own database carries nothing extra

```
podman compose exec api psql "$ASKWELL_DATABASE_URL" -c \
  "SELECT count(*) FROM documents; SELECT count(*) FROM chunks; SELECT count(*) FROM memory; SELECT count(*) FROM conversations;"
```

**You should see:** whatever these counted before you started this document (`0` each on a
freshly migrated stack) — none of the six hostile fixtures write to any table outside
`sources` and `audit_decisions`, which is exactly what a normal, successful import also
touches.

### 21. Confirm the egress proxy's refusal counter has not moved

```
curl -s localhost:8000/network
```

**You should see:** the same `"refused"` count noted in step 5. This is the acceptance
criterion in the ticket's own words — the sandbox has no route to the proxy at all, so a
count that has not moved is not "nothing got through", it is "nothing had anywhere to go".

### 22. Clean up

```
podman compose exec api python3 -c "
import asyncio
from askwell.config import load_settings
from askwell.db.engine import build_engine, session_factory, session_scope
from askwell import sandbox
from sqlalchemy import text

async def main():
    settings = load_settings()
    engine = build_engine(settings)
    factory = session_factory(engine)
    admin_url = settings.sandbox_database_url.get_secret_value()
    async with session_scope(factory) as session:
        rows = (await session.execute(text(\"SELECT sandbox_db FROM sources WHERE sandbox_db IS NOT NULL\"))).scalars().all()
        for db in rows:
            await sandbox.drop_database(session, admin_url, db, reason='manual_test_cleanup')

asyncio.run(main())
"
```

**You should see:** no error. Cleanup, not part of the acceptance criteria.

---

## Known gaps

Not defects — deliberately not built by this ticket, or not built at all yet:

- **No Add a source screen reaches `import_dump` for hostile or good dumps alike.**
  `M4-DUMP-FE-090` builds it; step 6 above shows the current, honest state — a dropped dump
  file is shown as arriving, not queued. Every import in this document is started directly
  against `askwell.dump_import`.
- **The fixture set is not exhaustive.** Six attack shapes were chosen to map onto six
  distinct privileges or caps the sandbox enforces. It is extended whenever a new attack shape
  is thought of, and this document's scope is containment, not a guarantee against every
  possible dump — stated in the ticket itself.
- **Hostile data inside a well-formed dump is out of scope.** A dump that loads cleanly but
  contains misleading rows is caught, if at all, by SQL validation on the query path (C2), not
  by anything this document exercises.
- **No UI failure reporting exists to check against `docs/ux/add-source.md` §5 directly**,
  for the same reason as the first gap above — the "Dump too large / too slow" and general
  failure states that document describes have no screen to render them on yet. This document
  confirms the underlying reporting (`sources.last_error`, `audit_decisions`) that such a
  screen would read from.
- **No test here crashes the sandbox instance itself** to confirm the ticket's own edge case
  "the instance restarts and the other sandbox databases survive" — none of the six fixtures
  attempt an instance-level crash, and reproducing one safely by hand is out of scope for this
  document.
