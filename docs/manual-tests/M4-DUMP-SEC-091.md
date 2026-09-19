# Manual test — M4-DUMP-SEC-091, a hostile dump destroys only its own database

**Ticket:** `M4-DUMP-SEC-091` — six hostile fixture dumps attempt privilege escalation, reading
host files through `COPY ... FROM PROGRAM`, connecting to another database in the instance,
reaching the network, exhausting disk, and running indefinitely. Each must fail, be reported,
and leave nothing behind except a dropped sandbox database.
**Version under test:** `0.4.22`
**Time:** about 25 minutes, plus a first stack build.
**Who can run it:** a browser, a terminal, `podman compose exec`.

**What is being checked.** `api/tests/test_dump_containment.py` is the authoritative automated
proof — the six fixtures plus the whole-suite-in-sequence case run against a real sandbox
instance under `scripts/dev.sh test-db`, and a static topology assertion runs under every
`scripts/dev.sh test`. This document repeats a representative slice of the hostile fixtures by
hand against a cold-started stack, using the same `askwell.dump_import.import_dump` entry point
the automated suite uses (there is still no Add a source screen for dumps — `M4-DUMP-FE-090`
names the gap and step 6 below confirms it before working around it).

**What this does not check, and why — issue #389.** The ticket's acceptance criterion "no
network request escapes, confirmed against the proxy's refusal counter, which must not increase
for the sandbox" needs a real egress proxy and the Redis it reports through. `scripts/dev.sh
test-db` brings up only Postgres, so the automated suite cannot read
`askwell.network.read_activity` before/after a hostile import — faking it would only prove a
mock was read correctly. Step 12 below is the actual check, against the real proxy this stack
already has running. The fixture set is not exhaustive and is extended whenever a new attack
shape is thought of — this is containment, not a guarantee against every possible dump.

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

**You should see:** lint, format, typecheck and unmarked tests finish with no red error text —
including the topology assertion, `test_sandbox_network_has_no_route_to_the_proxy_or_the_internet`,
which needs no running stack at all.

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

### 5. Load a good dump and index some documents

```
podman compose exec api sh -c 'printf "CREATE TABLE ledger (id integer primary key, note text);\nINSERT INTO ledger VALUES (1, %s);\n" "'"'"'a good export'"'"'" > /run/askwell/good.sql'
podman compose exec api python3 -c "
import asyncio
from pathlib import Path
from askwell.config import load_settings
from askwell.db.engine import build_engine, session_factory
from askwell import dump_import

async def main():
    settings = load_settings()
    engine = build_engine(settings)
    factory = session_factory(engine)
    async with factory() as session:
        source_id = await dump_import.create_dump_source(session, 'a good export', '/run/askwell/good.sql')
        await session.commit()
    tables = await dump_import.import_dump(factory, settings, source_id, Path('/run/askwell/good.sql'))
    print('good source_id', source_id, 'tables', tables)

asyncio.run(main())
"
```

**You should see:** `tables ['ledger']`. This is the ticket's own cold-start walkthrough state
— "one good dump already imported" — that every hostile attempt below runs alongside.

### 6. Confirm a dropped dump file still shows as arriving, not addable

Click **Add a source** in the app, then drop a small `.sql` file anywhere on the page. **You
should see:** the file listed under a block naming it as recognised but *arriving in M4*, never
under "queued" — `docs/ux/add-source.md` §5's "A format arriving in a later milestone" state.
This confirms the gap named above before working around it in the steps below.

### 7. Note the sandbox instance's baseline disk usage

```
podman compose exec sandbox sh -c 'psql -U "$POSTGRES_USER" postgres -tAc "
  SELECT sum(pg_database_size(datname)) FROM pg_database WHERE datname NOT LIKE '"'"'template%'"'"'"'
```

**You should see:** one number, in bytes. Note it down — every hostile attempt below must
return to this figure (plus ordinary WAL/catalog churn) once its sandbox database is dropped.

---

## 1. Privilege escalation — refused at the role level

### 8. Attempt a dump that tries to create itself a superuser role

```
podman compose exec api sh -c 'printf "CREATE ROLE askwell_hostile_escalation LOGIN SUPERUSER PASSWORD %s;\n" "'"'"'x'"'"'" > /run/askwell/escalate.sql'
podman compose exec api python3 -c "
import asyncio
from pathlib import Path
from askwell.config import load_settings
from askwell.db.engine import build_engine, session_factory
from askwell import dump_import

async def main():
    settings = load_settings()
    engine = build_engine(settings)
    factory = session_factory(engine)
    async with factory() as session:
        source_id = await dump_import.create_dump_source(session, 'privilege escalation', '/run/askwell/escalate.sql')
        await session.commit()
    try:
        await dump_import.import_dump(factory, settings, source_id, Path('/run/askwell/escalate.sql'))
    except dump_import.DumpImportFailed as exc:
        print('failed as expected:', exc)

asyncio.run(main())
"
```

**You should see:** `failed as expected:` naming a permission error — `askwell_sandbox_owner`
has no `CREATEROLE`/`SUPERUSER` and Postgres refuses the statement outright.

### 9. Confirm it is reported and left no trace

```
podman compose exec api sh -c 'psql "$ASKWELL_DATABASE_URL" -c "
  SELECT status, sandbox_db, last_error FROM sources WHERE name = '"'"'privilege escalation'"'"'"'
podman compose exec api sh -c 'psql "$ASKWELL_DATABASE_URL" -c "
  SELECT payload FROM audit_decisions WHERE kind = '"'"'dump_import_failed'"'"' ORDER BY occurred_at DESC LIMIT 1"'
```

`$ASKWELL_DATABASE_URL` is expanded inside the container, not your own shell — it is built by
`compose.yaml` from `.env`'s `POSTGRES_APP_PASSWORD` and is not itself a line in `.env`, so it
is never set on the host. Same reasoning for `$SANDBOX_POSTGRES_USER` below, which is a
container's own `POSTGRES_USER`.

**You should see:** `status` = `attention`, `sandbox_db` = `NULL`, `last_error` matching step
8's printed reason, and an `audit_decisions` row recording the same reason.

```
podman compose exec sandbox sh -c 'psql -U "$POSTGRES_USER" postgres -tAc "
  SELECT sum(pg_database_size(datname)) FROM pg_database WHERE datname NOT LIKE '"'"'template%'"'"'"'
```

**You should see:** the same figure as step 7 — the failed attempt's sandbox database is gone.

---

## 2. Reading a host file through `COPY ... FROM PROGRAM`

### 10. Attempt a dump that tries to read `/etc/passwd` off the sandbox host

```
podman compose exec api sh -c 'printf "CREATE TABLE stolen (line text);\nCOPY stolen FROM PROGRAM %s;\n" "'"'"'cat /etc/passwd'"'"'" > /run/askwell/readfile.sql'
podman compose exec api python3 -c "
import asyncio
from pathlib import Path
from askwell.config import load_settings
from askwell.db.engine import build_engine, session_factory
from askwell import dump_import

async def main():
    settings = load_settings()
    engine = build_engine(settings)
    factory = session_factory(engine)
    async with factory() as session:
        source_id = await dump_import.create_dump_source(session, 'read host file', '/run/askwell/readfile.sql')
        await session.commit()
    try:
        await dump_import.import_dump(factory, settings, source_id, Path('/run/askwell/readfile.sql'))
    except dump_import.DumpImportFailed as exc:
        print('failed as expected:', exc)

asyncio.run(main())
"
```

**You should see:** `failed as expected:` naming a permission error — `COPY ... FROM PROGRAM`
needs `pg_execute_server_program` membership, which the owner role does not have
(`deploy/sandbox/10-roles.sh`).

### 11. Confirm the good source and the main database are untouched

```
podman compose exec api sh -c 'psql "$ASKWELL_DATABASE_URL" -c "
  SELECT status, sandbox_db FROM sources WHERE name = '"'"'a good export'"'"'"'
```

**You should see:** `status` = `ready`, `sandbox_db` still the database created in step 5 — the
hostile attempt in steps 8–10 changed nothing about it.

---

## 3. The network leg — the proxy's refusal counter, against the real stack

### 12. Attempt a dump that tries to reach the network, and read the proxy's own counter

`/network` needs the session cookie the browser already holds from step 4 — a bare `curl`
gets back `"No session."` (`api/src/askwell/middleware.py`, `OPEN_PATHS` exempts only
`/health`). Open a new tab, in the same browser, at `http://127.0.0.1:8000/network`.

**You should see:** JSON naming a refused-request count. Note the number down.

```
podman compose exec api sh -c 'printf "CREATE TABLE net_probe (line text);\nCOPY net_probe FROM PROGRAM %s;\n" "'"'"'curl -s http://169.254.169.254/latest/meta-data/ -o /dev/null; echo done'"'"'" > /run/askwell/network.sql'
podman compose exec api python3 -c "
import asyncio
from pathlib import Path
from askwell.config import load_settings
from askwell.db.engine import build_engine, session_factory
from askwell import dump_import

async def main():
    settings = load_settings()
    engine = build_engine(settings)
    factory = session_factory(engine)
    async with factory() as session:
        source_id = await dump_import.create_dump_source(session, 'reach the network', '/run/askwell/network.sql')
        await session.commit()
    try:
        await dump_import.import_dump(factory, settings, source_id, Path('/run/askwell/network.sql'))
    except dump_import.DumpImportFailed as exc:
        print('failed as expected:', exc)

asyncio.run(main())
"
```

**You should see:** `failed as expected:` naming a permission error — the same
`pg_execute_server_program` refusal as step 10, before the attempt ever reaches a network call
(the sandbox network has no route to the proxy at all; see the topology test).

Reload the same `/network` tab.

**You should see:** the same refused-request count as before this section — it must not have
moved. This is the acceptance criterion `test_dump_containment.py` cannot check without the
proxy up (issue #389); here, with the real stack running, it can.

---

## Known gaps

Not defects — deliberately not built by this ticket, or not built at all yet:

- **No Add a source screen reaches `import_dump` at all.** `M4-DUMP-FE-090` builds it; step 6
  above shows the current, honest state — a dropped dump file is shown as arriving, not queued.
- **The automated suite cannot check the proxy's refusal counter** (issue #389). A static
  topology assertion (`test_sandbox_network_has_no_route_to_the_proxy_or_the_internet`) catches
  the regression that would make the counter move; the counter itself is checked here, by hand,
  against the real stack (step 12).
- **The fixture set is not exhaustive.** Six named attack shapes, not a guarantee against every
  possible dump — extended whenever a new one is thought of.
