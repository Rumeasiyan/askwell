# Manual test — M11-FIX-ING-234, a 100,000-row CSV or sheet loads within the time cap

**Ticket:** `M11-FIX-ING-234`, issue #862.

Since `M11-FIX-ING-224`, each sheet of a spreadsheet in a folder is also loaded as a table, the way
a CSV is. Every row was written to the database separately, one at a time. On the build machine a
100,000-row sheet or CSV took longer than the 10-minute load limit, so it was stopped and never
became a table. The workbook was still searchable as a document, but questions about it as a table
had nothing to run against.

Now:

1. **Rows go in a thousand at a time, all in one transaction.** A 100,000-row sheet or CSV loads in
   seconds, not in more than ten minutes. Neither limit changed: 10 minutes and 5 GB.
2. **A row that cannot be loaded is still reported by its row number.** When the database refuses
   one row, its batch of a thousand is tried again row by row. That row alone is reported, and the
   other 999 load.
3. **Both limits are checked after every batch, including the last.** A batch that pushes the load
   over the size limit stops it. Nothing half-loaded is left behind.

**Version under test:** `0.9.20`. Run `cat VERSION` and update this line if the version has moved
on.

**Time:** about 60–90 minutes for Parts A–E. Most of it is Askwell indexing the 100,000-row
workbook's *text* so it can be searched, which runs before the table load and is not what this
ticket changed. Part F is optional and adds about 10 minutes.

**Who can run it:** anyone with a browser and a terminal on the build host. Every Askwell screen is
reached by clicking, starting from Askwell's front page. The terminal is used only to make the test
files, to start Askwell, and to read things the interface does not show, such as how many rows a
table holds inside the database. Those steps are labelled **Stand-in**.

**A CSV cannot be added from any screen yet** (#339, #344). The **Add a source** screen lists a CSV
as *for a later milestone* and adds nothing. So the CSV half of this ticket is driven in Part D by a
**Stand-in** script that calls the same loader the add flow will call. Part D also shows the screen
refusing the CSV, so that nobody mistakes the refusal for this ticket's defect.

**What changed on disk.**

| Piece | File |
| ----- | ---- |
| Rows cast in Python, then inserted 1,000 at a time with `executemany`, each batch under its own savepoint, all in one transaction; a refused batch retried row by row | `_insert_rows_blocking`, `BATCH_ROWS` in `api/src/askwell/table_load.py` |
| Time and size limits checked after every batch, including the last; the every-200-rows size poll is gone | `_check_caps` in `api/src/askwell/table_load.py` |
| CSVs and workbook sheets share the path | `_load_table`, called from `_load_inferences` (CSV) and `_load_workbook_tables` (sheets) |
| Tests: a 100k CSV, a 100k sheet, a batch with one refused row and one uncastable row, a batch that crosses the size limit, the time limit still stopping a sheet | `api/tests/test_table_load_db.py` |

The reasoning, including why `executemany` and not `COPY`, is in `docs/decisions.md`, 2026-10-01,
"`M11-FIX-ING-234`".

---

## Read this first

**Nothing leaves this machine during this test.** No online AI, no web search.

**The limits are not changed during Parts A–E.** If a previous test lowered the size or time limit,
the cold start below resets it. Part F lowers the size limit on purpose and puts it back.

**Leave clarification questions unanswered.** `mixed.xlsx` may raise a question about its
**amount** column, because two of its values are not ordinary numbers. Answering it would reload
the sheet and change what Part C checks.

---

## Before you start

> **Warning: the cold start below deletes everything this Askwell stack holds.** That means
> sources, memory, conversations, the audit log, settings and any stored provider key. Your
> original files are not touched. On the shared development machine, check first that nobody
> needs what the stack holds, and that no eval or build queue is using the stack. If you are
> unsure, open **Settings → Your data → Export everything** first.

### 1. The test files (Stand-in)

Askwell can only read folders inside `ASKWELL_ROOTS_MOUNT` in `.env`. Check it, and check that
Redis has its three passwords:

```
cd ~/external/quantum-plus/askwell
grep ASKWELL_ROOTS_MOUNT .env
grep -c '^REDIS_\(API\|WORKER\|PROXY\)_PASSWORD=.' .env
```

**You should see:** a mount that contains `/tmp` (if it does not, set `ASKWELL_ROOTS_MOUNT=/tmp`),
then `3`.

The workbooks are made with a short script, run inside Askwell's own image. Save this as
`.run/make-234.py` in the repository folder (`.run/` is ignored by git):

```python
from pathlib import Path

import openpyxl

OUT = Path("/app/.run/m11-234")


def workbook(path: Path, title: str, rows: list[list[object]]) -> None:
    book = openpyxl.Workbook(write_only=True)
    sheet = book.create_sheet(title)
    for row in rows:
        sheet.append(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    book.save(path)


folder = OUT / "askwell-test-234"

# The ticket's size: 100,000 data rows under one header row.
workbook(
    folder / "large.xlsx",
    "Ledger",
    [["name", "amount"]] + [[f"row{i}", i] for i in range(100_000)],
)

# 2,500 rows, so three batches. Row 1202 (counting the header) holds a whole
# number too big for the database; row 1502 holds a word. Both are in the
# second batch.
mixed: list[list[object]] = [[f"row{i}", i] for i in range(2_500)]
mixed[1_200] = ["row1200", "99999999999999999999"]
mixed[1_500] = ["row1500", "oops"]
workbook(folder / "mixed.xlsx", "Amounts", [["name", "amount"], *mixed])

print(sorted(str(p.relative_to(OUT)) for p in OUT.rglob("*") if p.is_file()))
```

Then:

```
cd ~/external/quantum-plus/askwell
rm -rf .run/m11-234 /tmp/askwell-test-234
scripts/dev.sh run python /app/.run/make-234.py
cp -r .run/m11-234/askwell-test-234 /tmp/
ls -la /tmp/askwell-test-234
```

**You should see:** the script print `['askwell-test-234/large.xlsx',
'askwell-test-234/mixed.xlsx']`. Then `/tmp/askwell-test-234` holds both files. `large.xlsx` is
around 2 MB.

Also make an ordinary CSV on the host, for Part D's screen check:

```
printf 'name,amount\nrow0,0\nrow1,1\n' > /tmp/ledger-234.csv
```

### 2. Start Askwell from nothing (Stand-in)

This ticket's loader only reaches the running stack after a rebuild. `docs/BRAIN.md` records that
the stack was not rebuilt when the ticket landed.

```
cd ~/external/quantum-plus/askwell
cat VERSION
podman compose down -v
scripts/dev.sh build-api
scripts/dev.sh web-build
podman compose up -d
scripts/dev.sh db upgrade head
```

**You should see:** `0.9.20` (or later), the volumes removed, both builds finish with no red error
text, the containers start, and the migration end without an error.

In a **second** terminal, start the model on the host and leave it running:

```
cd ~/external/quantum-plus/askwell
scripts/dev.sh inference
```

**You should see:** the supervisor report the model and the embedding model ready. Indexing needs
the embedding model.

---

## Part A — cold start, first run, and the folder

1. Open a **private or fresh-profile** browser window. Type `http://127.0.0.1:8000` in the
   address bar and press **Enter**. ☐

   **You should see:** the welcome screen, **Welcome to Askwell**, with a **Get started** button.
   If you see the **Ask** screen instead, the stack was not cleared. Go back to *Before you
   start*, step 2.

2. Click **Get started** and follow the steps until one offers to add material. Set a passphrase
   if asked, and write it down. ☐

   **You should see:** a step with an **Add a source** box, offering **Choose files** and
   **Choose a folder**.

3. Click **Choose a folder**. In the folder picker, go to `/tmp`, select `askwell-test-234`, and
   confirm. If the browser asks whether to let the site see the files, allow it. ☐

   **You should see:** a card counting two files, and the question **Which folder is
   “askwell-test-234” in?** with an empty field and an **Add them** button.

4. Type `/tmp` in the field and click **Add them**. If a note says **Askwell has not been given
   this folder yet.** and offers a **Nominate …** button, click it, then click **Add them** again
   if the button is still there. ☐

   **You should see:** the card move on to recording two files, then **Queued**, then indexing
   progress. There should be no red **Not added** note.

5. Finish the welcome steps. Skipping optional steps is fine. Click **Library** in the left
   column. ☐

   **You should see:** a source named **askwell-test-234**. `mixed.xlsx` is ready within a few
   minutes. `large.xlsx` takes much longer: its 100,000 rows are indexed as searchable text first,
   and on CPU that can take half an hour or more. Wait until the source's line reads **All 2
   indexed.**

   The table load itself happens at the very end of each workbook's indexing and takes seconds.
   If a workbook sits at the same progress for a long time, check Part E, step 15 before calling
   it stuck.

## Part B — the 100,000-row sheet becomes a table

6. Look at the **askwell-test-234** row once it reads **All 2 indexed.** ☐

   **You should see:** the status at the right reads **Ready**.

   ☐ **You should not see:** **Needs attention**, or a **Show detail** button under the counts
   line. Before `0.9.20`, `large.xlsx` produced **Show detail (1)** with the line **large.xlsx:
   The sheet Ledger was not loaded as a table. Load aborted: running for 600.… s, over the time
   cap of 600.0s. Its text is still searched.** Seeing that line now is this ticket's defect.

7. Click **Memory** in the left column. Find the row for **large.xlsx:Ledger**, the one without a
   column name after it. ☐

   **You should see:** its text reads **Loaded as table `large_xlsx_ledger`, 100000 row(s),
   2 column(s).** There is no sentence about rows that failed. **This is the ticket's main
   check on screen.** Before `0.9.20`, there was no such row, because the table was never
   created.

8. **Stand-in.** The table holds every row, and it is in the folder's own isolated sandbox
   database, not in Askwell's (C3): ☐

   ```
   cd ~/external/quantum-plus/askwell
   DB=$(scripts/dev.sh psql -tAc "SELECT sandbox_db FROM sources WHERE name = 'askwell-test-234'" | tr -d '[:space:]')
   echo "$DB"
   podman compose exec sandbox sh -c "psql -U \"\$POSTGRES_USER\" -d $DB -tAc \"
     SELECT count(*), sum(amount) FROM large_xlsx_ledger\""
   scripts/dev.sh psql -tAc "SELECT count(*) FROM information_schema.tables WHERE table_name LIKE '%xlsx%'"
   ```

   **You should see:** a database name (not `askwell`), then `100000|4999950000`, then `0`. The
   `0` means no workbook table exists in Askwell's own database.

   The sum is 0 + 1 + … + 99,999. A different sum means rows were lost or duplicated. A count
   under 100,000 is this ticket's defect.

## Part C — one bad row in a batch

`mixed.xlsx` has 2,500 rows. In the second batch of a thousand, one value is too big for the
database and one is a word in a column of numbers.

9. Still in **Memory**, find the row for **mixed.xlsx:Amounts**, the one without a column name
   after it. ☐

   **You should see:** **Loaded as table `mixed_xlsx_amounts`, 2498 row(s), 2 column(s). 2 row(s)
   failed to load.**

   If it reads **2500 row(s)** with no failed rows, the **amount** column was loaded as text, not
   as numbers. Check its column row, **mixed.xlsx:Amounts.amount**. If the inferred type there is
   text, the test file did not do its job. Record it and go on: Part D checks the same batch
   behaviour on a CSV, with row numbers.

   If it reads anything below **2498 row(s)**, the good rows around the bad ones did not load.
   That is this ticket's defect.

10. **Stand-in.** Exactly the two bad rows are missing, and their neighbours are there: ☐

    ```
    podman compose exec sandbox sh -c "psql -U \"\$POSTGRES_USER\" -d $DB -tAc \"
      SELECT count(*) FROM mixed_xlsx_amounts;
      SELECT string_agg(name, ',' ORDER BY name) FROM mixed_xlsx_amounts
      WHERE name IN ('row1199', 'row1200', 'row1201', 'row1499', 'row1500', 'row1501')\""
    ```

    **You should see:** `2498`, then `row1199,row1201,row1499,row1501`. No `row1200` and no
    `row1500`.

    The screens never show *which* sheet rows failed, only how many (see Known gaps). The row
    numbers are checked on a CSV in Part D, which goes through the same code.

## Part D — the CSV half

11. Click **Library**, then **Add a source** at the top of the page. Click **Choose files**, go to
    `/tmp`, and select `ledger-234.csv`. ☐

    **You should see:** a grey note headed **1 file for a later milestone**, with the line
    **ledger-234.csv — a CSV file. Askwell reads these from M4; nothing was added for it now.**
    Nothing is queued.

    This is not this ticket's defect. There is no screen that adds a CSV as a table yet (#339,
    #344). The next step calls the loader directly, the way the add flow will.

12. **Stand-in.** Load a 100,000-row CSV under the default limits, and time it: ☐

    ```
    cd ~/external/quantum-plus/askwell
    podman compose exec api python3 -c "
    import asyncio, time
    from pathlib import Path
    from askwell.config import load_settings
    from askwell.db.engine import build_engine, session_factory, session_scope
    from askwell import table_load

    async def main():
        settings = load_settings()
        factory = session_factory(build_engine(settings))
        path = Path('/tmp/m234-large/ledger.csv')
        path.parent.mkdir(exist_ok=True)
        path.write_text('name,amount\n' + ''.join(f'row{i},{i}\n' for i in range(100_000)))
        async with session_scope(factory) as session:
            source_id = await table_load.create_table_source(session, 'ledger-100k', str(path))
        start = time.monotonic()
        [r] = await table_load.process_table_source(factory, settings, source_id, str(path))
        print('table', r.sql_table_name, 'rows', r.row_count, 'failed', len(r.failed_rows),
              'seconds', round(time.monotonic() - start, 1))

    asyncio.run(main())
    "
    ```

    **You should see:** `table ledger_csv rows 100000 failed 0 seconds N`, where *N* is a few
    seconds (2.9 on the build host when the ticket landed). Anything over a minute is worth
    recording. Before `0.9.20` this ran for ten minutes and ended in `TableCapExceeded` with
    **over the time cap of 600.0s**.

13. **Stand-in.** One bad row in a batch is reported by its row number, and the rest of the batch
    loads: ☐

    ```
    podman compose exec api python3 -c "
    import asyncio
    from pathlib import Path
    from askwell.config import load_settings
    from askwell.db.engine import build_engine, session_factory, session_scope
    from askwell import table_load

    async def main():
        settings = load_settings()
        factory = session_factory(build_engine(settings))
        rows = [f'row{i},{i}' for i in range(2_500)]
        rows[1_200] = 'row1200,99999999999999999999'
        rows[1_500] = 'row1500,oops'
        path = Path('/tmp/m234-mixed/ledger.csv')
        path.parent.mkdir(exist_ok=True)
        path.write_text('name,amount\n' + '\n'.join(rows) + '\n')
        async with session_scope(factory) as session:
            source_id = await table_load.create_table_source(session, 'ledger-mixed', str(path))
        [r] = await table_load.process_table_source(factory, settings, source_id, str(path))
        print('rows', r.row_count)
        for f in r.failed_rows:
            print('failed row', f.row_number, f.reason)

    asyncio.run(main())
    "
    ```

    **You should see:** `rows 2498`, then two lines, in this order:

    - `failed row 1202 …`, with a reason that says the value is **out of range** (the database
      refused it);
    - `failed row 1502 …`, with a reason that mentions `oops` (Askwell refused it before it
      reached the database).

    Row 1 is the header, so the 1,201st data row is row 1202. A different number, a missing line,
    or `rows` below 2498 is this ticket's defect.

    This is the existing row-failure behaviour from `M4-CSV-ING-094`, now inside a batch. Its own
    automated test still passes unchanged.

14. Reload the page and click **Library**. ☐

    **You should see:** two new sources, **ledger-100k** and **ledger-mixed**, each **Ready**.
    Under each there may be **Nothing in this source yet.** That wording is wrong for a loaded
    table, but it is #792, not this ticket's defect.

## Part E — nothing else moved

15. **Stand-in.** The worker recorded both workbook loads as successes and none as failures: ☐

    ```
    podman compose logs worker 2>&1 | grep -E 'workbook_tables_(loaded|failed)'
    ```

    **You should see:** two `workbook_tables_loaded` lines, one naming `large.xlsx` and one naming
    `mixed.xlsx`, each with `"tables": 1`. There should be no `workbook_tables_failed` line.

    If you came here from step 5 because `large.xlsx` looked stuck: no line yet means it is still
    indexing its text, and the table load has not started. Wait and check again.

16. **Stand-in.** The limits were not raised to make this pass: ☐

    ```
    scripts/dev.sh psql -tAc "SELECT key, value FROM settings WHERE key LIKE 'dump_%cap%'"
    ```

    **You should see:** no rows. Nothing overrode the defaults, which are 5 GB and 600 seconds.

17. **Stand-in.** The audit chains are still intact: ☐

    ```
    podman compose exec api askwell-verify
    ```

    **You should see:** every chain reported intact, exit status 0.

## Part F — optional: a batch that crosses the size limit

The ticket's second edge case. The size limit is set just above an empty sandbox database, so the
first batches of a load fit and a later one pushes it over.

18. **Stand-in.** Find how big an empty sandbox database is: ☐

    ```
    podman compose exec sandbox sh -c "psql -U \"\$POSTGRES_USER\" -d postgres -tAc \"
      SELECT pg_database_size('template1')\""
    ```

    **You should see:** a number of bytes, several million. Call it *E*. A new sandbox database is
    copied from `template1`, so it starts at about this size.

19. **Stand-in.** Set the limit to *E* plus 512 KB, and load 20,000 rows of about 130 bytes each,
    about 2.6 MB in all. Replace `E` in the first line with the number from step 18: ☐

    ```
    CAP=$((E + 524288))
    scripts/dev.sh psql -c "INSERT INTO settings (key, value, updated_at)
      VALUES ('dump_size_cap_bytes', '$CAP', now())
      ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()"
    podman compose exec api python3 -c "
    import asyncio
    from pathlib import Path
    from askwell.config import load_settings
    from askwell.db.engine import build_engine, session_factory, session_scope
    from askwell import table_load

    async def main():
        settings = load_settings()
        factory = session_factory(build_engine(settings))
        path = Path('/tmp/m234-wide/wide.csv')
        path.parent.mkdir(exist_ok=True)
        path.write_text('name\n' + ''.join('x' * 100 + f'{i}\n' for i in range(20_000)))
        async with session_scope(factory) as session:
            source_id = await table_load.create_table_source(session, 'wide-234', str(path))
        try:
            await table_load.process_table_source(factory, settings, source_id, str(path))
            print('loaded - the size limit did not stop it')
        except table_load.TableCapExceeded as error:
            print('stopped on', error.cap, '-', error)

    asyncio.run(main())
    "
    ```

    **You should see:** `INSERT 0 1`, then `stopped on size - Load aborted: loaded data reached …,
    over the size cap of ….` If it prints `loaded`, the limit was not checked between batches,
    and that is this ticket's defect.

20. Reload the page and click **Library**. ☐

    **You should see:** a source **wide-234** with **Needs attention**. No table was left behind
    for it: Part F's stand-in dropped its sandbox database on the way out.

21. **Stand-in.** Put the limit back: ☐

    ```
    scripts/dev.sh psql -c "DELETE FROM settings WHERE key = 'dump_size_cap_bytes'"
    scripts/dev.sh psql -tAc "SELECT sandbox_db IS NULL FROM sources WHERE name = 'wide-234'"
    ```

    **You should see:** `DELETE 1`, then `t`. The `t` confirms the failed load's database is gone.

---

## Result

| Part | Result | Notes |
| ---- | ------ | ----- |
| A — cold start and folder | | |
| B — 100k-row sheet is a table (7 and 8 are the main checks) | | |
| C — bad rows in a sheet's batch | | |
| D — CSV: 100k rows in seconds; bad rows by number (12, 13) | | |
| E — logs, limits unchanged, audit chains | | |
| F — batch crosses the size limit (optional) | | |

Tester, date, browser, `cat VERSION`, and the seconds printed in step 12:

---

## Known gaps

These are deliberately not built, or belong to another ticket. Do not report them as defects of
this one.

- **A CSV cannot be added from any screen.** The add screen lists it as *for a later milestone*
  (#339, #344). Part D drives the loader directly for that reason.
- **Neither limit was raised,** and neither can be changed from a screen (#878). A table that
  really is bigger than 5 GB, or slower than 10 minutes, is still stopped. That is the limit
  working.
- **Which sheet rows failed is not shown anywhere on screen,** only how many (the Memory note in
  step 9). The row numbers exist in the loader's result, and for CSVs they are checked in step 13.
- **The time limit is checked after each batch, not after each row,** so a load can run up to one
  batch (about 30 ms on the build host) past it. This is recorded in `docs/decisions.md`.
- **A very small size limit now stops even a tiny table,** because the limit is checked after the
  last batch too. Only tests set limits that small. `M11-FIX-UI-229`'s manual test relied on the
  old gap and needs its setup changed (#890).
- **Indexing a 100,000-row workbook's text is slow on CPU.** That is the search index, not the
  table load, and this ticket did not change it.
- **Library says "Nothing in this source yet." under a loaded CSV** (#792).
- **A table answer has no citation** (#857). Asking questions of the new table is not part of this
  test.
- **The Windows and macOS installers are not exercised here.** The code path is the same, and each
  platform's own walkthrough covers it.
