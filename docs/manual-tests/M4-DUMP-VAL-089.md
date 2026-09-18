# Manual test — M4-DUMP-VAL-089, size and time caps that abort a dump import

**Ticket:** `M4-DUMP-VAL-089` — each dump import is capped at 5 GB and 10 minutes by default,
both user-adjustable. Beyond either, the import aborts, the sandbox database is dropped, and
the reason names which cap was hit and what the current setting is.
**Version under test:** `0.4.5`
**Time:** about 30 minutes, plus a first stack build.
**Who can run it:** a browser, a terminal, `podman compose exec`.

**What is being checked.** `api/src/askwell/dump_import.py` — `get_dump_size_cap_bytes` /
`set_dump_size_cap_bytes`, `get_dump_time_cap_seconds` / `set_dump_time_cap_seconds`, and the
watchdog thread inside `_load_blocking` that enforces both while `psql` is still running.
`api/tests/test_dump_import.py` is the authoritative automated proof (three pure-Python cases
against a fake `psql`, plus `requires_db` cases for both caps against a real sandbox instance);
this document repeats the size-cap and time-cap aborts against a cold-started stack and adds
the one thing a pytest run does not show on its own — the sandbox instance's real disk usage
before and after an abort.

**Where this stops on purpose — read before reporting anything below as a defect.**

- **There is still no Add a source screen for dumps.** `web/lib/add-source.ts`'s `ROUTES` entry
  for `dump` still carries `arrives: "M4"`, so a dropped `.sql`/`.dump`/`.backup` file is shown
  in the browser as *arriving*, not queued — `M4-DUMP-FE-090` is the ticket that wires
  `import_dump_job` to a screen, and it has not landed. Step 6 below confirms this is still the
  case before working around it. Every import in this document is started directly against
  `askwell.dump_import`, the same way `M4-DUMP-ING-088`'s manual test did.
- **There is no settings screen for the caps either.** `web/app/settings/page.tsx` states
  outright that "the rest of the settings that exist today are environment variables. The
  surface for them arrives in M7." The caps this ticket adds are **not** environment
  variables — they are rows in the `settings` table, adjusted only through
  `dump_import.set_dump_size_cap_bytes`/`set_dump_time_cap_seconds` — but nothing in `web/`
  calls either function yet. "Adjustable caps in settings" is true at the function and
  audit-trail level this document exercises; there is nowhere to click yet. This is a real gap
  and is named again under Known gaps, not smoothed over.
- **No resume.** Named Out of Scope in the ticket itself — an aborted import is retried from
  scratch, never continued.

None of the above is a defect in `M4-DUMP-VAL-089` — its scope is the two caps and the abort
path, not a screen to reach them from. Sections below say which is which.

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

### 5. Confirm the sandbox instance starts clean

```
podman compose exec sandbox psql -U "$SANDBOX_POSTGRES_USER" postgres -tAc \
  "SELECT sum(pg_database_size(datname)) FROM pg_database WHERE datname NOT LIKE 'template%'"
```

**You should see:** one number, in bytes — this is the baseline you compare every later
"disk usage returns to its pre-import level" check against. Note it down.

### 6. Confirm a dropped dump file still shows as arriving, not addable

Click **Add a source** in the app, then drop a small `.sql` file anywhere on the page (any text
file ending `.sql` works — it does not need to be a real dump for this step). **You should
see:** the file listed under a block naming it as recognised but *arriving in M4*, in its own
colour, never under "queued" — `docs/ux/add-source.md` §5's "A format arriving in a later
milestone" state. This confirms the gap named above before working around it below.

---

## 1. The size cap aborts and drops the sandbox database

### 7. Set the size cap low, register a source, and attempt the import

```
podman compose exec api sh -c 'echo "CREATE TABLE widgets (id integer);" > /tmp/tiny.sql'
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
        print('default size cap bytes:', await dump_import.get_dump_size_cap_bytes(session))
        await dump_import.set_dump_size_cap_bytes(session, 1024)
        source_id = await dump_import.create_dump_source(session, 'tiny dump, tiny cap', '/tmp/tiny.sql')
    print('source_id', source_id)
    try:
        await dump_import.import_dump(factory, settings, source_id, Path('/tmp/tiny.sql'))
    except dump_import.DumpCapExceeded as exc:
        print('aborted: cap=', exc.cap, 'limit=', exc.limit, 'message=', exc)

asyncio.run(main())
"
```

**You should see:** `default size cap bytes: 5368709120` (5 GB, the ticket's stated default),
then `aborted: cap= size limit= 1024.0 message= Import aborted: loaded data reached ...MB, over
the size cap of 1.0 KB.` The reported "loaded data" figure will be several megabytes even
though `/tmp/tiny.sql` itself is a few dozen bytes — this is the ticket's own edge case ("a
dump that is small on disk but expands beyond the cap when loaded — measured on loaded size,
not file size") holding: a freshly created sandbox database's own catalogue already exceeds a
1 KB cap before a single row of the dump is fed in, and the message is honest about that.

### 8. Confirm the source, the decisions record, and the setting change are all recorded

```
podman compose exec api psql "$ASKWELL_DATABASE_URL" -c \
  "SELECT status, sandbox_db, last_error FROM sources WHERE name = 'tiny dump, tiny cap'"
```

**You should see:** `status` = `attention`, `sandbox_db` = `NULL`, `last_error` naming the size
cap, matching step 7's printed message.

```
podman compose exec api psql "$ASKWELL_DATABASE_URL" -c \
  "SELECT kind, payload FROM audit_decisions WHERE kind IN ('dump_cap_changed', 'dump_import_failed') ORDER BY created_at DESC LIMIT 5"
```

**You should see:** a `dump_import_failed` row whose payload has `"cap": "size"`, and a
`dump_cap_changed` row whose payload reads `{"cap": "size", "previous": 5368709120, "new":
1024}` — the cap change itself is a decisions record, not a silent write (ticket's own
"Audit / Logging Requirements").

### 9. Confirm disk usage returned to its pre-import level

```
podman compose exec sandbox psql -U "$SANDBOX_POSTGRES_USER" postgres -tAc \
  "SELECT sum(pg_database_size(datname)) FROM pg_database WHERE datname NOT LIKE 'template%'"
```

**You should see:** the same number as step 5 (or within a few dozen kilobytes of ordinary
WAL/catalog churn) — the sandbox database created for this import was dropped, not left behind
part-loaded. This is the acceptance criterion "disk usage returns to its pre-import level after
an abort" checked against the real instance, not inferred from a row disappearing.

---

## 2. The time cap aborts a statement that is still running, without waiting for it

### 10. Set the time cap low against a dump that runs an intentionally slow statement

```
podman compose exec api sh -c 'echo "SELECT pg_sleep(5);" > /tmp/slow.sql'
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
        print('default time cap seconds:', await dump_import.get_dump_time_cap_seconds(session))
        await dump_import.set_dump_size_cap_bytes(session, 5 * 1024**3)
        await dump_import.set_dump_time_cap_seconds(session, 2)
        source_id = await dump_import.create_dump_source(session, 'slow dump, tiny time cap', '/tmp/slow.sql')
    started = time.monotonic()
    try:
        await dump_import.import_dump(factory, settings, source_id, Path('/tmp/slow.sql'))
    except dump_import.DumpCapExceeded as exc:
        elapsed = time.monotonic() - started
        print('aborted after', round(elapsed, 1), 's: cap=', exc.cap, 'message=', exc)

asyncio.run(main())
"
```

**You should see:** `default time cap seconds: 600.0` (10 minutes, the ticket's stated
default), then `aborted after` a number **well under 5** — the dump's own statement is
`pg_sleep(5)`, so anything close to or over 5 means the cap waited for the statement to finish
rather than terminating it. `message=` should read `Import aborted: running for 2.0s, over the
time cap of 2.0s.` — this is the ticket's own edge case "an abort during a long-running
statement — the statement is terminated rather than waited on" observed directly, not inferred.

### 11. Confirm the source names the time cap, and disk usage returned to baseline

```
podman compose exec api psql "$ASKWELL_DATABASE_URL" -c \
  "SELECT status, sandbox_db, last_error FROM sources WHERE name = 'slow dump, tiny time cap'"
```

**You should see:** `status` = `attention`, `sandbox_db` = `NULL`, `last_error` naming the time
cap (`... over the time cap of 2.0s.`), never the size cap — the size cap was reset to 5 GB in
step 10 specifically so this abort is unambiguously the time cap's doing.

```
podman compose exec sandbox psql -U "$SANDBOX_POSTGRES_USER" postgres -tAc \
  "SELECT sum(pg_database_size(datname)) FROM pg_database WHERE datname NOT LIKE 'template%'"
```

**You should see:** the same baseline figure as step 5 again.

---

## 3. Both caps exceeded at once — the size cap is the one reported

### 12. Set both caps to something a fresh, empty sandbox database will already fail

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
        await dump_import.set_dump_size_cap_bytes(session, 1)
        await dump_import.set_dump_time_cap_seconds(session, 0.001)
        source_id = await dump_import.create_dump_source(session, 'both caps at once', '/tmp/tiny.sql')
    try:
        await dump_import.import_dump(factory, settings, source_id, Path('/tmp/tiny.sql'))
    except dump_import.DumpCapExceeded as exc:
        print('reported cap:', exc.cap)

asyncio.run(main())
"
```

**You should see:** `reported cap: size` — never `time`, even though the time cap (0.001s) is
just as impossible to meet. This is the ticket's edge case "an import that hits both caps at
once — reports the one hit first": the size check runs before the time check on every poll,
and the very first poll happens before a single byte is fed to `psql`.

### 13. Reset both caps to their defaults before moving on

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

**You should see:** no error. This is cleanup, not part of the acceptance criteria.

---

## 4. Raising a cap changes the very next import's outcome

### 14. Re-run the size-cap dump from step 7 with the default cap in force

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
        source_id = await dump_import.create_dump_source(session, 'tiny dump, default cap', '/tmp/tiny.sql')
    tables = await dump_import.import_dump(factory, settings, source_id, Path('/tmp/tiny.sql'))
    print('tables', tables)

asyncio.run(main())
"
```

**You should see:** `tables ['widgets']` — the exact same dump file that aborted in step 7
now loads to completion, with nothing changed except the cap. This is the acceptance criterion
"adjusting a cap in settings changes the behaviour of the next import", confirmed by contrast
rather than by reading the setting back.

```
podman compose exec api psql "$ASKWELL_DATABASE_URL" -c \
  "SELECT status, sandbox_db FROM sources WHERE name = 'tiny dump, default cap'"
```

**You should see:** `status` = `ready`, `sandbox_db` non-null.

### 15. Clean up the surviving sandbox database

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
            await sandbox.drop_database(session, admin_url, db)

asyncio.run(main())
"
```

**You should see:** no error. This is cleanup, not part of the acceptance criteria.

---

## 5. Non-positive caps are refused

### 16. Confirm a zero or negative cap is rejected rather than silently accepted

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
        try:
            await dump_import.set_dump_size_cap_bytes(session, 0)
        except ValueError as exc:
            print('size cap refused:', exc)
        try:
            await dump_import.set_dump_time_cap_seconds(session, 0)
        except ValueError as exc:
            print('time cap refused:', exc)

asyncio.run(main())
"
```

**You should see:** both `... refused:` lines print, and neither call is followed by a
`dump_cap_changed` decisions record for the value `0` — a cap of zero would abort every import
before it starts, which is not what "user-adjustable" is meant to permit.

---

## Known gaps

Not defects — deliberately not built by this ticket, or not built at all yet:

- **No settings screen reaches either cap.** `web/app/settings/page.tsx` names M7 as when
  environment-derived settings get a surface, and these two caps are not environment settings
  in the first place — they need their own control, on their own timeline, and nothing tracks
  that yet. Filed as a follow-up (`AGENTS.md` §8) rather than left implicit: **issue needed** —
  a settings-screen control for `dump_size_cap_bytes`/`dump_time_cap_seconds`, since without one
  "user-adjustable" only holds for someone willing to run Python inside the container.
- **No Add a source screen reaches `import_dump` at all.** `M4-DUMP-FE-090` builds it; step 6
  above shows the current, honest state — a dropped dump file is shown as arriving, not queued.
- **No resume.** An aborted import is a single attempt; retrying means adding the source again
  from scratch. Named Out of Scope in the ticket itself.
- **Loaded-size measurement is approximate between polls**, by design (`CAP_POLL_SECONDS =
  2.0`) — a size cap can be exceeded for up to two seconds before a poll notices, which is the
  ticket's own stated trade-off ("Assumptions: loaded size can be measured continuously without
  materially slowing the import"), not a defect in what this document exercises.
