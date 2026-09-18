# Manual test — M4-CSV-ING-094, loading a CSV into the sandbox as a real table

**Ticket:** `M4-CSV-ING-094` — after parsing and clarification, a CSV loads into the sandbox
database as a real table with the confirmed types. Rows that fail to load are reported by row
number, never dropped silently. Answering a `date_format` clarification reloads the affected
column. Schema notes exist for the table and its columns.
**Version under test:** `0.4.6` (check `cat VERSION`).
**Time:** about 45 minutes, plus a first stack build.
**Who can run it:** a browser, a terminal, and `podman compose exec`.

**What is being checked.** `api/src/askwell/table_load.py` (`create_table_source`,
`process_table_source`, `load_source`, `reload_source`, `sql_type_for`, `cast_value`,
`normalise_identifier`); `api/src/askwell/worker.py`'s `import_table_job`;
`api/src/askwell/reapply.py`'s wiring from an answered `date_format` clarification to
`table_load.reload_source`. `api/tests/test_table_load.py` and
`api/tests/test_table_load_db.py` are the authoritative automated proof; this document repeats
the create/load/reload/report-failures behaviour against a cold-started stack.

**Where this stops on purpose — read before reporting anything below as a defect.**

- **There is no Add a source screen path that reaches this code.** `api/src/askwell/sources.py`
  has no route that inserts a `kind = 'csv'` row or enqueues `import_table_job` — the only
  `sources` insert path in that file is the file/document batch shape (`AddRequest`). Dropping
  a CSV through the running app today still shows the "later" state `M4-CSV-ING-093`'s own
  manual test documented; that has not changed. Part A below confirms this is still true, then
  Part B exercises `table_load` directly, started from inside the `api` container — the same
  situation `M4-DUMP-ING-088`'s manual test documented for dump import before its own screen
  landed.
- **No `GET /sources` route exists.** Every row check below reads `sources` with `psql`
  directly.
- **Query execution is out of scope.** The ticket's own scope line says so; the SQL-generation
  epic (`M4-SCHEMA-ING-100` onward) is what will let a question actually run against a loaded
  table. "Ask an aggregate question about it" from the ticket's own testing notes is answered
  here by connecting to the sandbox database directly with `psql` and reading the loaded rows,
  not by asking Askwell a question — the same limit `M4-DUMP-ING-088`'s document names for
  dumps.

None of the above is a defect in `M4-CSV-ING-094` — its scope is create/load/reload/report,
not the screen or the query path.

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
`SANDBOX_POSTGRES_PASSWORD`, `SANDBOX_OWNER_PASSWORD` and `SANDBOX_READONLY_PASSWORD`.

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
including `api/tests/test_table_load.py`'s casting and identifier tests.

### 3. Bring the stack up, migrate, and run the database-backed tests

```
podman compose up -d
scripts/dev.sh db upgrade head
scripts/dev.sh test-db
```

**You should see:** `postgres`, `sandbox`, `redis`, `egress-proxy`, `api`, `worker` all
reported created and started, migration finishing with no error, and
`api/tests/test_table_load_db.py`'s six scenarios (clean load, identifier normalisation,
malformed rows, empty file, size cap, date-format reload) passing.

### 4. Open the app and confirm nothing is alarmed

Open a browser at `http://127.0.0.1:8000`. **You should see:** the shell load with no alarm
banner — `database`, `sandbox`, `queue`, `egress_proxy` and `inference` all reachable.

---

## Part A — cold start through the app: confirm a CSV still does not reach this code today

### 5. Nominate the test folder

Click **Settings** in the left rail, scroll to **Folders Askwell may read**, type a path into
the **Nominate a folder** field —

```
/home/you/external/quantum-plus/askwell/askwell-test-material
```

— and click **Nominate**. **You should see:** a box appear showing that path, marked
**Readable**. (Create the folder on the host first if it does not exist, and confirm
`ASKWELL_ROOTS_MOUNT` in `.env` points at its parent — same as any prior manual test that
nominates a folder.)

### 6. Write a small CSV into it

```bash
scripts/dev.sh run python3 - <<'PY'
import os
os.makedirs("/app/askwell-test-material/sales", exist_ok=True)
with open("/app/askwell-test-material/sales/people.csv", "w") as f:
    f.write("Name,Amount\nAnna,10\nBen,20\n")
print("done")
PY
```

**You should see:** the script print `done`.

### 7. Add it through the app

Click **Library**, then **Add source**. Choose **Files**, click **Browse**, and select the
`sales` folder (or drag it onto the screen).

**You should see:** `people.csv` listed with the same **later** state
`M4-CSV-ING-093`'s manual test recorded — naming that Askwell reads CSVs from a later
milestone, nothing added now. It is not shown as ingesting, queued, or ready.

### 8. Confirm nothing landed in the database from that click

```
podman compose exec api psql "$ASKWELL_DATABASE_URL" -tAc "SELECT count(*) FROM sources WHERE kind = 'csv'"
```

**You should see:** `0`.

---

## Part B — the module itself: create, load, report failures, reload

### 9. A clean CSV loads as a real table with the confirmed types

```bash
podman compose exec api python3 -c "
import asyncio
from pathlib import Path
from askwell.config import load_settings
from askwell.db.engine import build_engine, session_factory, session_scope
from askwell import table_load

async def main():
    settings = load_settings()
    engine = build_engine(settings)
    factory = session_factory(engine)
    csv_path = Path('/tmp/people.csv')
    csv_path.write_text('Name,Amount\nAnna,10\nBen,20\n')
    async with session_scope(factory) as session:
        source_id = await table_load.create_table_source(session, 'people', str(csv_path))
    print('source_id', source_id)
    results = await table_load.process_table_source(factory, settings, source_id, str(csv_path))
    for r in results:
        print('table', r.sql_table_name, 'rows', r.row_count, 'failed', len(r.failed_rows))

asyncio.run(main())
"
```

**You should see:** `source_id ...` then `table people_csv rows 2 failed 0`. Note the
`source_id` — used again in step 12.

### 10. Confirm the source row, the loaded table, and the schema note

```
podman compose exec api psql "$ASKWELL_DATABASE_URL" -c \
  "SELECT status, sandbox_db FROM sources WHERE name = 'people'"
```

**You should see:** `status` = `ready`, `sandbox_db` non-null. Note that database name as
`$DB`, then:

```
podman compose exec api psql "$ASKWELL_DATABASE_URL" -c \
  "SELECT column_name, origin, description FROM schema_notes WHERE source_id = '<source_id from step 9>' AND column_name IS NULL"
```

**You should see:** one row, `origin` = `inferred`, `description` reading
`Loaded as table \`people_csv\`, 2 row(s), 2 column(s).` — the table-level note the ticket's
own acceptance criterion asks for ("Schema notes exist for the table").

```
podman compose exec api psql "postgresql://askwell_sandbox_owner:<SANDBOX_OWNER_PASSWORD from .env>@sandbox:5432/<DB from above>" \
  -c "SELECT name, amount FROM people_csv ORDER BY name"
```

**You should see:** `Anna | 10` and `Ben | 20`, `amount` printed as a plain integer — it loaded
as `bigint`, not `text`.

### 11. A column name that is not a valid identifier is normalised, with the original kept as a schema note

```bash
podman compose exec api python3 -c "
import asyncio
from pathlib import Path
from askwell.config import load_settings
from askwell.db.engine import build_engine, session_factory, session_scope
from askwell import table_load

async def main():
    settings = load_settings()
    engine = build_engine(settings)
    factory = session_factory(engine)
    csv_path = Path('/tmp/export.csv')
    csv_path.write_text('Reference #,Amount\nA1,10\nA2,20\n')
    async with session_scope(factory) as session:
        source_id = await table_load.create_table_source(session, 'export', str(csv_path))
    print('source_id', source_id)
    results = await table_load.process_table_source(factory, settings, source_id, str(csv_path))
    print('table name', results[0].sql_table_name)

asyncio.run(main())
"
```

**You should see:** `table name export_csv`. Then:

```
podman compose exec api psql "$ASKWELL_DATABASE_URL" -c \
  "SELECT column_name, description FROM schema_notes WHERE source_id = '<source_id above>' AND column_name = 'Reference #'"
```

**You should see:** one row whose `description` names both the physical column
(`reference` or similar) and the original header `Reference #` — so a question that uses the
spreadsheet's own header text still resolves to the right column.

### 12. Rows that fail to cast are reported by row number, never dropped

```bash
podman compose exec api python3 -c "
import asyncio
from pathlib import Path
from askwell.config import load_settings
from askwell.db.engine import build_engine, session_factory, session_scope
from askwell import table_load

async def main():
    settings = load_settings()
    engine = build_engine(settings)
    factory = session_factory(engine)
    csv_path = Path('/tmp/sales.csv')
    good_rows = '\n'.join(f'person{i},{i * 10}' for i in range(1, 10))
    csv_path.write_text(f'name,amount\n{good_rows}\nBen,oops\n')
    async with session_scope(factory) as session:
        source_id = await table_load.create_table_source(session, 'sales', str(csv_path))
    results = await table_load.process_table_source(factory, settings, source_id, str(csv_path))
    r = results[0]
    print('row_count', r.row_count)
    for f in r.failed_rows:
        print('failed row', f.row_number, f.reason)

asyncio.run(main())
"
```

**You should see:** `row_count 9`, then `failed row 11 ...` with a reason mentioning `oops` —
row 1 is the header, so the tenth data row is row 11. The table still loaded the nine good
rows; nothing aborted.

### 13. An empty file is refused with the reason, and nothing is created in the sandbox

```bash
podman compose exec api python3 -c "
import asyncio
from pathlib import Path
from askwell.config import load_settings
from askwell.db.engine import build_engine, session_factory, session_scope
from askwell import table_load

async def main():
    settings = load_settings()
    engine = build_engine(settings)
    factory = session_factory(engine)
    csv_path = Path('/tmp/empty.csv')
    csv_path.write_text('')
    async with session_scope(factory) as session:
        source_id = await table_load.create_table_source(session, 'empty', str(csv_path))
    print('source_id', source_id)
    try:
        await table_load.process_table_source(factory, settings, source_id, str(csv_path))
    except table_load.EmptyTable as exc:
        print('refused as expected:', exc)

asyncio.run(main())
"
```

**You should see:** `refused as expected: the file has no rows or columns to load`. Then:

```
podman compose exec api psql "$ASKWELL_DATABASE_URL" -c \
  "SELECT status, sandbox_db FROM sources WHERE name = 'empty'"
```

**You should see:** `sandbox_db` is `NULL` — the load never reached the sandbox at all, so
there is nothing to drop.

### 14. Answering a date-format clarification reloads the affected column as a real date

```bash
podman compose exec api python3 -c "
import asyncio
from pathlib import Path
from askwell.config import load_settings
from askwell.db.engine import build_engine, session_factory, session_scope
from askwell import table_load
from sqlalchemy import text

async def main():
    settings = load_settings()
    engine = build_engine(settings)
    factory = session_factory(engine)
    csv_path = Path('/tmp/registrations.csv')
    csv_path.write_text('name,registered\nAnna,03/04/2026\nBen,05/06/2026\n')
    async with session_scope(factory) as session:
        source_id = await table_load.create_table_source(session, 'registrations', str(csv_path))
    await table_load.process_table_source(factory, settings, source_id, str(csv_path))
    async with session_scope(factory) as session:
        db = (await session.execute(text('SELECT sandbox_db FROM sources WHERE id = :id'), {'id': source_id})).scalar_one()
        clar = (await session.execute(text(\"SELECT id, options FROM clarifications WHERE source_id = :id AND evidence->>'trigger' = 'date_format'\"), {'id': source_id})).one()
    print('source_id', source_id, 'database', db, 'clarification_id', clar[0], 'options', clar[1])

asyncio.run(main())
"
```

**You should see:** `source_id ... database ... clarification_id ... options ['DD/MM/YYYY (day
first)', 'MM/DD/YYYY (month first)']`. Note the `database` name as `$DB`. Confirm the column
loaded as text, unresolved:

```
podman compose exec api psql "postgresql://askwell_sandbox_owner:<SANDBOX_OWNER_PASSWORD from .env>@sandbox:5432/<DB from above>" \
  -c "SELECT data_type FROM information_schema.columns WHERE table_name = 'registrations_csv' AND column_name = 'registered'"
```

**You should see:** `text` — the day/month order is undecided, so `sql_type_for` refused to
guess.

Now answer the clarification and reload:

```bash
podman compose exec api python3 -c "
import asyncio
import uuid
from askwell.config import load_settings
from askwell.db.engine import build_engine, session_factory, session_scope
from askwell.review import answer_clarification
from askwell import table_load

CLARIFICATION_ID = uuid.UUID('<clarification_id from above>')
SOURCE_ID = uuid.UUID('<source_id from above>')
DAY_FIRST_OPTION = 'DD/MM/YYYY (day first)'

async def main():
    settings = load_settings()
    engine = build_engine(settings)
    factory = session_factory(engine)
    async with session_scope(factory) as session:
        await answer_clarification(session, CLARIFICATION_ID, DAY_FIRST_OPTION)
    await table_load.reload_source(factory, settings, SOURCE_ID)

asyncio.run(main())
"
```

**You should see:** no error printed. Then:

```
podman compose exec api psql "postgresql://askwell_sandbox_owner:<SANDBOX_OWNER_PASSWORD from .env>@sandbox:5432/<DB from above>" \
  -c "SELECT data_type FROM information_schema.columns WHERE table_name = 'registrations_csv' AND column_name = 'registered'" \
  -c "SELECT name, registered FROM registrations_csv ORDER BY name"
```

**You should see:** `data_type` now `date`, and the two rows read `Anna | 2026-04-03` and
`Ben | 2026-06-05` — `03/04/2026` cast as 3 April (day-first, the option answered), not 4 March.

### 15. Confirm the reload itself is a decisions record

```
podman compose exec api psql "$ASKWELL_DATABASE_URL" -tAc \
  "SELECT 1 FROM audit_decisions WHERE kind = 'table_column_reloaded' AND payload->>'source_id' = '<source_id from step 14>'"
```

**You should see:** `1`.

---

## Cleanup

```
podman compose down -v
```

Restore `.env` if you changed anything beyond what **Before you start** asked for.

---

## Known gaps

- **Not wired to the Add source screen.** No route in `sources.py` inserts a `kind = 'csv'`
  row or enqueues `import_table_job` — a CSV dropped through the running app still shows the
  `later` state (Part A). Wiring that up is not part of this ticket's own scope, and is the
  same gap `M4-DUMP-ING-088`'s manual test recorded for dumps before `M4-DUMP-FE-090`.
- **No query path exists yet.** "Ask the mean of a column grouped by condition" from the
  ticket's own real-world scenario cannot be exercised — the SQL-generation epic
  (`M4-SCHEMA-ING-100` onward, C2) has not landed. This document reads loaded rows with `psql`
  as the sealed owner role instead, which proves the data loaded correctly but is not the
  product experience.
- **Merged headers are flagged, not resolved** — named in the ticket itself as a known gap of
  `table_infer`, unchanged by this ticket.
- **Very wide files may load slowly** — a reload rebuilds the whole table row by row rather
  than altering one column in place (`docs/decisions.md`, 2026-09-18 entry for this ticket) —
  named as an accepted trade-off, not a defect.
- **One table per CSV, one table per sheet for a workbook** is stated in the ticket as an
  assumption, not verified end-to-end for a multi-sheet `.xlsx` in this document — `infer_xlsx`
  is exercised by `api/tests/test_table_infer.py`, but no `.xlsx` walkthrough is included here.
