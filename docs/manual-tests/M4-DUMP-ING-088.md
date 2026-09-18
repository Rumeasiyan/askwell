# Manual test — M4-DUMP-ING-088, importing a PostgreSQL dump into a per-source sandbox database

**Ticket:** `M4-DUMP-ING-088` — create a fresh sandbox database for a dump source, load the
dump as the restricted owner role, introspect its schema on success, drop the database and
report the reason on any failure. Two imports cannot see each other. The load never touches
Askwell's own database.
**Version under test:** `0.4.4`
**Time:** about 45 minutes, plus a first stack build.
**Who can run it:** a browser, a terminal, `podman compose exec`, and `.env` open in a text
editor for `TEST_SANDBOX_OWNER_PASSWORD`/`SANDBOX_OWNER_PASSWORD` (step 6 types it in
directly, the same reason `M4-DUMP-DEPLOY-087`'s document did).

**What is being checked.** `api/src/askwell/dump_import.py` (`create_dump_source`,
`import_dump`, `reclaim_interrupted`); `api/src/askwell/worker.py`'s `import_dump_job` and
`_reclaim_sandbox_orphans`. `api/tests/test_dump_import.py` is the authoritative automated
proof of the load/introspect/drop logic against a fake `psql` and against the real sandbox
instance; this document repeats the load-and-drop behaviour against a cold-started stack and
adds the one thing a pytest run cannot show — what a second, independent import actually sees
(or does not see) of the first.

**Where this stops on purpose — read before reporting anything below as a defect.**

- **There is no Add a source screen for dumps yet.** `web/app/sources/add/page.tsx` and the
  `POST /sources` route (`api/src/askwell/sources.py`) only accept the file/CSV batch shape
  (`AddRequest`, a folder plus relative paths) — nothing in `web/` or in the API routes calls
  `dump_import.create_dump_source` or enqueues `import_dump_job`. The screen copy and warning
  in `docs/ux/add-source.md` §3 describe a flow that does not exist in code yet; that is
  `M4-DUMP-FE-090`, explicitly out of this ticket's scope. Every dump import in this document
  is started directly, from inside the running `api` container, because that is the only way
  to reach this ticket's code today — the same situation `M4-DUMP-DEPLOY-087`'s manual test
  documented for the sandbox itself.
- **No `GET /sources` route exists.** `api/src/askwell/sources.py` only registers
  `POST /sources`, `POST /sources/{id}/reindex` and `DELETE /sources/{id}` — every row check
  below reads `sources` with `psql` directly rather than through an API a library screen would
  eventually call.
- **No caps yet.** `M4-DUMP-VAL-089` has not landed, so nothing here refuses a 6 GB dump or
  one that has been loading for twenty minutes — "Known gaps" below, not a defect.
- **Nothing can be asked about an imported dump yet.** Schema introspection here returns table
  *names* only (`_introspect_blocking` in `dump_import.py`); `M4-SCHEMA-ING-100` builds real
  column/type/relationship introspection, and the SQL query path (C2) that would let you ask a
  question against the sandbox database does not exist yet either. "Import, then ask a
  question that only works if two sources share data" in the ticket's own testing notes is
  answered here by *connecting to the sandbox database directly with `psql` as the sealed
  owner role* and confirming the connection itself is refused — that is the real isolation
  boundary (`askwell.sandbox.seal_owner`), and it is what a query path would rely on once one
  exists.

None of the above is a defect in `M4-DUMP-ING-088` — its scope is create/load/introspect/drop,
not the screen, the caps, or asking questions. Sections below say which is which.

---

## Before you start

```
cd ~/external/quantum-plus/askwell
```

If you have never run Askwell before:

```
cp -n .env.example .env
```

Open `.env` and confirm every `?set ... in .env` placeholder has a real value, in particular
`SANDBOX_POSTGRES_PASSWORD`, `SANDBOX_OWNER_PASSWORD` and `SANDBOX_READONLY_PASSWORD`. **Note
the value of `SANDBOX_OWNER_PASSWORD`** — step 10 types it in directly, for the same reason
`M4-DUMP-DEPLOY-087`'s document gives: the running containers only ever hold the sandbox
instance's superuser connection, never the owner role's own password.

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

### 4. Confirm `psql` shipped in the API image

```
podman compose exec api psql --version
```

**You should see:** a real version line (`psql (PostgreSQL) 15.x`), not "command not found" —
`api/Dockerfile` installs `postgresql-client` specifically so `dump_import._load_blocking` has
something to shell out to.

### 5. Open the app and confirm nothing is alarmed

Open a browser at `http://127.0.0.1:8000`. **You should see:** the shell load with no alarm
banner — `database`, `sandbox`, `queue`, `egress_proxy` and `inference` all reachable.

---

## 1. A valid dump loads and its schema is introspected

### 6. Prepare a small dump on the host and copy it into the container

```
cat > /tmp/good-dump.sql <<'EOF'
CREATE TABLE customers (id integer primary key, name text);
CREATE TABLE orders (id integer primary key, customer_id integer references customers(id), shipped_late boolean);
INSERT INTO customers VALUES (1, 'Ravenholt Textiles'), (2, 'Blue Anchor Supply');
INSERT INTO orders VALUES (101, 1, true), (102, 1, false), (103, 2, false);
EOF
podman compose cp /tmp/good-dump.sql api:/tmp/good-dump.sql
```

**You should see:** no error from either command.

### 7. Register the source and run the import, exactly as `import_dump_job` would

```
podman compose exec api python3 -c "
import asyncio
from pathlib import Path
from askwell.config import load_settings
from askwell.db.engine import build_engine, session_factory
from askwell import dump_import
from askwell.db.engine import session_scope

async def main():
    settings = load_settings()
    engine = build_engine(settings)
    factory = session_factory(engine)
    async with session_scope(factory) as session:
        source_id = await dump_import.create_dump_source(session, 'colleague export A', '/tmp/good-dump.sql')
    print('source_id', source_id)
    tables = await dump_import.import_dump(factory, settings, source_id, Path('/tmp/good-dump.sql'), report=lambda done, total: print('progress', done, '/', total))
    print('tables', tables)

asyncio.run(main())
"
```

**You should see:** one or more `progress N / TOTAL` lines (the dump above is small enough
that you may only see the final `progress TOTAL / TOTAL`), then `tables ['customers',
'orders']`, in that order — the alphabetical order `_introspect_blocking`'s query asks for.
Note the printed `source_id`; steps 8–9 use it.

### 8. Confirm the source row is ready, with its sandbox database recorded

There is no `GET /sources` listing route yet — `api/src/askwell/sources.py` only exposes
`POST /sources`, `POST /sources/{id}/reindex` and `DELETE /sources/{id}`, none of which list —
so read the row directly:

```
podman compose exec api psql "$ASKWELL_DATABASE_URL" -c \
  "SELECT name, kind, status, sandbox_db FROM sources WHERE name = 'colleague export A'"
```

**You should see:** `kind` = `dump`, `status` = `ready`, `sandbox_db` non-null — matching
`dump_import.import_dump`'s final `UPDATE sources SET status = 'ready', ...`.

### 9. Confirm the decisions record

```
podman compose exec api psql "$ASKWELL_DATABASE_URL" -c \
  "SELECT kind, payload FROM audit_decisions WHERE payload->>'source_id' = '<source_id from step 7>' ORDER BY created_at"
```

**You should see:** three rows in order — `dump_import_started`, then `source_added` (from
`create_dump_source`, logged first since it runs before the import call) may appear before
`dump_import_started` depending on which step ran first above; the two that matter for this
ticket are `dump_import_started` (payload has `source_id` and `database`) and
`dump_import_succeeded` (payload's `tables` field reads `["customers", "orders"]`). This is
the acceptance criterion "import start, outcome and drop are decisions records" (ticket
"Audit / Logging Requirements") holding on a real run, not a fixture.

### 10. Confirm the load never touched Askwell's own database

```
podman compose exec api psql "$ASKWELL_DATABASE_URL" -c "\dt"
```

**You should see:** the usual Askwell tables (`sources`, `documents`, `messages`, …) — no
`customers` or `orders` table anywhere in this list. The dump landed only in the sandbox
database named in `sandbox_db` (step 8), never here.

---

## 2. Two imports cannot see each other

### 11. Import a second, unrelated dump

```
cat > /tmp/second-dump.sql <<'EOF'
CREATE TABLE customers (id integer primary key, secret_note text);
INSERT INTO customers VALUES (1, 'this must never be visible from the first import');
EOF
podman compose cp /tmp/second-dump.sql api:/tmp/second-dump.sql
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
        source_id = await dump_import.create_dump_source(session, 'colleague export B', '/tmp/second-dump.sql')
    print('source_id', source_id)
    tables = await dump_import.import_dump(factory, settings, source_id, Path('/tmp/second-dump.sql'))
    print('tables', tables)

asyncio.run(main())
"
```

**You should see:** `tables ['customers']` — the same table *name* as the first import, in a
different database. Note this second `source_id`.

### 12. Confirm the two sandbox databases are distinct

```
podman compose exec api psql "$ASKWELL_DATABASE_URL" -c \
  "SELECT name, sandbox_db FROM sources WHERE kind = 'dump' ORDER BY name"
```

**You should see:** two rows, `colleague export A` and `colleague export B`, each with a
different `sandbox_db` value — "one database per source" (C3) holding, not two sources
sharing a schema namespace inside one database.

### 13. Confirm the owner role cannot reconnect to the first import's database

This is the isolation the ticket's testing notes ask for ("neither can see the other"), proven
the way it actually holds — `askwell.sandbox.seal_owner` revokes `CONNECT` on a database the
moment its load succeeds, so the *same* owner role that just loaded the second dump cannot even
open a session to the first's database, regardless of what query it tried to run:

```
podman compose exec api sh -c '
DB1=$(psql "$ASKWELL_DATABASE_URL" -tAc "SELECT sandbox_db FROM sources WHERE name = '"'"'colleague export A'"'"'")
psql "postgresql://askwell_sandbox_owner:<SANDBOX_OWNER_PASSWORD from .env>@sandbox:5432/$DB1" -c "SELECT 1"
'
```

**You should see:** a connection refusal — `FATAL: permission denied for database "..."` or
similar — not a prompt, not a row back. If this instead connects and returns `1`, that is a
real defect: the second import's role could reach the first import's data.

### 14. Drop both sandbox databases to leave the instance clean

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
        rows = (await session.execute(text(\"SELECT sandbox_db FROM sources WHERE kind = 'dump' AND sandbox_db IS NOT NULL\"))).scalars().all()
        for db in rows:
            await sandbox.drop_database(session, admin_url, db)

asyncio.run(main())
"
```

**You should see:** no error. This is cleanup, not part of the acceptance criteria.

---

## 3. A broken dump leaves no partial database behind

### 15. Import a dump that fails partway through

```
cat > /tmp/broken-dump.sql <<'EOF'
CREATE TABLE partial_data (id integer primary key, name text);
INSERT INTO partial_data VALUES (1, 'this row loads fine');
THIS LINE IS NOT VALID SQL AND WILL FAIL;
EOF
podman compose cp /tmp/broken-dump.sql api:/tmp/broken-dump.sql
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
        source_id = await dump_import.create_dump_source(session, 'a broken export', '/tmp/broken-dump.sql')
    print('source_id', source_id)
    try:
        await dump_import.import_dump(factory, settings, source_id, Path('/tmp/broken-dump.sql'))
    except dump_import.DumpImportFailed as exc:
        print('failed as expected:', exc)

asyncio.run(main())
"
```

**You should see:** `failed as expected:` followed by a reason naming the syntax error
(`psql`'s own stderr, e.g. `syntax error at or near "THIS"`) — not a bare exit code, because
`_load_blocking` only falls back to `psql exited with status N` when `psql` said nothing on
stderr.

### 16. Confirm the source is marked for attention, with the reason kept, and no database remains

```
podman compose exec api psql "$ASKWELL_DATABASE_URL" -c \
  "SELECT status, sandbox_db, last_error FROM sources WHERE name = 'a broken export'"
```

**You should see:** `status` = `attention`, `sandbox_db` = `NULL`, `last_error` containing the
same syntax-error text step 15 printed. This is the acceptance criterion "a dump that fails to
load leaves no partial database behind and reports the reason" — including the edge case
"partially loads then errors" (`partial_data` and its one row were committed by `psql` before
the broken statement, and the whole database was still dropped, not left half-populated).

```
podman compose exec api psql "$ASKWELL_DATABASE_URL" -tAc \
  "SELECT 1 FROM audit_decisions WHERE kind = 'dump_import_failed' AND payload->>'reason' LIKE '%THIS%'"
```

**You should see:** `1` — the failure is a decisions record, reason included, not just a
database-column update.

---

## 4. An interrupted import is reclaimed at worker startup

This is the edge case the ticket names directly — "An import interrupted by a stack restart —
the partial database is reclaimed" — and it is worth proving against the real worker startup
path (`worker._reclaim_sandbox_orphans`) rather than only the unit-level function it calls.

### 17. Simulate the exact state a killed worker leaves behind

A real race (kill the worker mid-`psql`) is timing-dependent to hit reliably by hand, so this
step reproduces the state directly — a sandbox database that exists, and a `sources` row still
claiming it with `status = 'indexing'` — which is exactly what `import_dump` leaves behind if
the process dies between creating the database and either sealing or dropping it:

```
podman compose exec api python3 -c "
import asyncio, uuid
from askwell.config import load_settings
from askwell.db.engine import build_engine, session_factory, session_scope
from askwell import sandbox
from sqlalchemy import text

async def main():
    settings = load_settings()
    engine = build_engine(settings)
    factory = session_factory(engine)
    admin_url = settings.sandbox_database_url.get_secret_value()
    name = sandbox.generate_name()
    source_id = uuid.uuid4()
    async with session_scope(factory) as session:
        await sandbox.create_database(session, admin_url, name)
        await session.execute(text(\"INSERT INTO sources (id, kind, name, sandbox_db, status) VALUES (:id, 'dump', 'interrupted mid-load', :db, 'indexing')\"), {'id': source_id, 'db': name})
    print('source_id', source_id, 'database', name)

asyncio.run(main())
"
```

**You should see:** `source_id ... database sbx_...` (or whatever prefix `generate_name()`
uses) printed with no error. Note both values.

### 18. Restart the worker and let startup reclaim it

```
podman compose restart worker
sleep 5
podman compose logs worker --tail 30
```

**You should see:** a `worker_resumed` (or equivalent startup) log line whose
`sandbox_orphans_reclaimed` count is at least 1 — `worker.py`'s `_reclaim_sandbox_orphans`
calling `dump_import.reclaim_interrupted` as part of ordinary startup, unprompted.

### 19. Confirm the source and the database

```
podman compose exec api psql "$ASKWELL_DATABASE_URL" -c \
  "SELECT status, sandbox_db, last_error FROM sources WHERE name = 'interrupted mid-load'"
```

**You should see:** `status` = `attention`, `sandbox_db` = `NULL`, `last_error` = `Import was
interrupted and needs to be retried.` (the literal string `reclaim_interrupted` writes).

```
podman compose exec api psql "$ASKWELL_SANDBOX_DATABASE_URL" -c "\l" | grep '<database from step 17>'
```

**You should see:** no output — the database from step 17 no longer exists in the sandbox
instance's own catalogue. "The partial database is reclaimed" holding, on a real restart.

---

## 5. A dump that creates a role or tablespace

### 20. Confirm the restricted owner role cannot create a role, and the refusal is reported

```
cat > /tmp/role-dump.sql <<'EOF'
CREATE ROLE sneaky_role LOGIN PASSWORD 'whatever';
CREATE TABLE t (id integer);
EOF
podman compose cp /tmp/role-dump.sql api:/tmp/role-dump.sql
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
        source_id = await dump_import.create_dump_source(session, 'tries to create a role', '/tmp/role-dump.sql')
    try:
        await dump_import.import_dump(factory, settings, source_id, Path('/tmp/role-dump.sql'))
    except dump_import.DumpImportFailed as exc:
        print('refused:', exc)

asyncio.run(main())
"
```

**You should see:** `refused:` naming a permission error (`permission denied to create role` or
similar) — `ON_ERROR_STOP=1` means the whole load aborts at that statement rather than skipping
it and continuing with `t`, and §3's drop-on-failure path handles the rest the same as any
other failed load. This is the ticket's edge case "A dump that creates roles or tablespaces —
refused or ignored by the restricted role, and the outcome is reported" — refused, in this
build.

---

## Known gaps

Not defects — deliberately not built by this ticket:

- **No Add a source screen reaches this code.** `M4-DUMP-FE-090` builds it; every import above
  was started directly against `askwell.dump_import`.
- **No size or time cap.** `M4-DUMP-VAL-089` adds the 5 GB / 10-minute limits
  `docs/ux/add-source.md` §5 describes ("Dump too large / too slow"). A huge dump run today
  simply runs long.
- **No querying.** Schema introspection here is table names only; typed columns, keys and
  relationships are `M4-SCHEMA-ING-100`, and the SQL path that would let a question actually
  reach a sandbox database (C2) has not landed. Isolation in §2 above is therefore proven at
  the connection level (`seal_owner`), not by asking a question that would only succeed if
  isolation had failed — that specific proof has to wait for the query path to exist.
- **MySQL/SQL Server dumps and the "both routes out" refusal copy** belong to the add-source
  screen (`M4-DUMP-FE-090`), not this module. `api/src/askwell/filetypes.py` already routes a
  `.sql`/`.dump`/`.backup` file to `Route.DUMP` regardless of the actual dialect inside it —
  nothing here refuses a MySQL dump by name yet; it would simply fail to load under
  `ON_ERROR_STOP=1` and be reported and dropped like any other broken dump (§3's path), not
  with the dialect-aware message the UX spec asks for.
