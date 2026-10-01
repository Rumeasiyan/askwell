# Manual test — M11-FIX-ING-230, workbooks indexed before `0.9.12` get their tables without being re-indexed

**Ticket:** `M11-FIX-ING-230`, issues #850 and #895.

Since `M11-FIX-ING-224` (`0.9.12`), each sheet of a spreadsheet in a folder is also loaded as a
table, so questions about it can be answered from the sheet. That load only happened when a
workbook was indexed. Someone who added spreadsheets on `0.9.11` or earlier, and then upgraded,
had no tables at all. Nothing told them to re-index, and re-indexing re-reads and re-embeds every
file, which takes hours on a CPU.

Now, every time the worker starts:

1. **A workbook that has never had its sheets loaded gets them loaded.** Only the tables. Its
   searchable text and embeddings are left as they are, and the Library shows no indexing.
2. **It happens once per workbook.** A workbook whose sheets were all skipped (no header row, for
   example) is not read again at the next start.
3. **A workbook that cannot be reached right now waits.** If its folder is not there (an unplugged
   drive) or the table database is still starting, nothing is recorded, nothing is marked failed,
   and it is tried at the next start.
4. **A folder whose table database has gone missing gets a new one.** If the sandbox's data is
   lost but Askwell's own database is kept, the folder's workbooks pointed at tables that did not
   exist. Askwell now notices this at start, forgets the old tables, and loads them again, once.

**Version under test:** `0.9.22`. Run `cat VERSION` and update this line if the version has moved
on.

**Time:** about 90–120 minutes. Most of it is building two versions of Askwell and indexing the
test files on the old one. Parts D–F are quick once the upgrade has been done.

**Who can run it:** anyone with a browser and a terminal on the build host. Every Askwell screen is
reached by clicking, starting from Askwell's front page. The terminal is used to make the test
files, to install the old version and upgrade from it, to unplug the "drive", and to read things the
interface does not show, such as which decisions were recorded. Those steps are labelled
**Stand-in**.

**This test installs a real old version.** The only honest way to have "a workbook indexed before
`0.9.12`" is to index it on `0.9.11` and then upgrade, which is what a user does. The old version
is the `v0.9.11` tag, checked out in a separate folder so the repository is not touched.

**What changed on disk.**

| Piece | File |
| ----- | ---- |
| At worker start: a folder whose sandbox database no longer exists has it cleared, its inferred sheet notes retired, and a `sandbox_database_lost` decision recorded | `forget_lost_databases` in `api/src/askwell/table_load.py` |
| At worker start: every live, `ready` workbook with no `workbook_tables_loaded` or `workbook_tables_failed` decision (newer than its folder's last `sandbox_database_lost`) has its tables loaded | `backfill_workbook_tables`, `_workbooks_without_tables` in `api/src/askwell/table_load.py` |
| Before each workbook: the sandbox is checked reachable, the workbook re-read as still live, and the file checked as present; any of those failing records nothing | the same function |
| Both called from worker start, after orphan reclaim; the backfill in its own `try` | `_reclaim_sandbox_orphans` in `api/src/askwell/worker.py` |
| Tests: backfill and second start, all-skipped not rescanned, failed/deleted/superseded/unfinished left alone, deleted between scan and load, sandbox down, lost database recovered once, unreadable file deferred | `api/tests/test_table_load_db.py` |

The reasoning, including why a failed load is not retried at every start, is in
`docs/decisions.md`, 2026-10-01, "`M11-FIX-ING-230`".

---

## Read this first

**Nothing leaves this machine during this test,** except one step that downloads the old
version's frontend packages from the package registry (Before you start, step 3). No online AI, no
web search.

**Leave clarification questions unanswered** until Part D tells you to look at them. Answering
one reloads that workbook and changes what later parts check.

**Do not click Re-index** on any folder during this test. Re-indexing loads the tables the old way,
through ordinary indexing, and hides whether the start-up backfill did it.

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
`.run/make-230.py` in the repository folder (`.run/` is ignored by git):

```python
from pathlib import Path

import openpyxl

OUT = Path("/app/.run/m11-230")

FIGURES = [
    ["Department", "Q1 Revenue", "Headcount", "Avg Tenure Years"],
    ["Textiles", 482000, 34, 4.1],
    ["Logistics", 215000, 19, 2.7],
    ["Research", 903000, 27, 5.6],
]
# Numbers only: the first row reads as data, not as column names, so the
# sheet is skipped and the workbook ends up with no tables at all.
RAW = [[1, 2], [3, 4], [5, 6]]
# Both parts of every date are 12 or less: 03/04/2025 is 3 April or 4 March.
ORDERS = [
    ["Customer", "Placed", "Units"],
    ["Anna", "03/04/2025", 4],
    ["Ben", "05/06/2025", 7],
    ["Cara", "11/12/2025", 2],
]
STOCK = [["Item", "Count"], ["bolts", 120], ["nuts", 340], ["washers", 75]]


def workbook(path: Path, sheets: dict[str, list[list[object]]]) -> None:
    book = openpyxl.Workbook()
    for index, (title, rows) in enumerate(sheets.items()):
        sheet = book.active if index == 0 else book.create_sheet()
        sheet.title = title
        for row in rows:
            sheet.append(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    book.save(path)


main = OUT / "askwell-test-230"
workbook(main / "figures.xlsx", {"Figures": FIGURES})
workbook(main / "raw.xlsx", {"Raw": RAW})
workbook(main / "orders.xlsx", {"North": ORDERS})
workbook(OUT / "askwell-test-230-usb" / "stock.xlsx", {"Stock": STOCK})
print(sorted(str(p.relative_to(OUT)) for p in OUT.rglob("*") if p.is_file()))
```

Then:

```
cd ~/external/quantum-plus/askwell
rm -rf .run/m11-230 /tmp/askwell-test-230 /tmp/askwell-test-230-usb /tmp/away-230
scripts/dev.sh run python /app/.run/make-230.py
cp -r .run/m11-230/askwell-test-230 .run/m11-230/askwell-test-230-usb /tmp/
ls /tmp/askwell-test-230 /tmp/askwell-test-230-usb
```

**You should see:** the script print four file names. Then `/tmp/askwell-test-230` holds
`figures.xlsx`, `orders.xlsx` and `raw.xlsx`, and `/tmp/askwell-test-230-usb` holds `stock.xlsx`.

What each is for:

- `figures.xlsx` — one ordinary sheet, **Figures**. It should get a table after the upgrade.
- `raw.xlsx` — one sheet with no header row. It should get *no* table, a note saying why, and must
  not be read again at every start.
- `orders.xlsx` — a **Placed** column whose dates could be day-first or month-first. After the
  upgrade it should raise a question, as a newly added workbook does.
- `askwell-test-230-usb/stock.xlsx` — stands for a folder on a USB drive. It is moved away before
  the upgrade, so it cannot be reached at the first start.

### 2. A copy of the old version (Stand-in)

```
cd ~/external/quantum-plus/askwell
git worktree add ../askwell-0911 v0.9.11
cp .env ../askwell-0911/.env
cat ../askwell-0911/VERSION
```

**You should see:** `Preparing worktree (detached HEAD …)`, then `0.9.11`.

### 3. Start the old version from nothing (Stand-in)

The old version uses the same stack name, containers and volumes as the current one. That is the
point: the upgrade later keeps this data.

```
cd ~/external/quantum-plus/askwell-0911
podman compose down -v
scripts/dev.sh build
scripts/dev.sh web-install
scripts/dev.sh web-build
podman compose up -d
```

**You should see:** the volumes removed, both builds finish with no red error text, the frontend
packages install, and the containers start. `podman compose ps` lists them as running or healthy,
and `migrate` as exited with code 0.

If `podman compose up` stops on a missing variable, compare `.env` with this folder's
`.env.example` and add the one it names. That is the old version's own requirement, not this
ticket's defect.

In a **second** terminal, start the model on the host and leave it running. It has to be the old
copy's, because the stack reads the model's state from that folder:

```
cd ~/external/quantum-plus/askwell-0911
scripts/dev.sh inference
```

**You should see:** the supervisor report the model and the embedding model ready.

---

## Part A — on the old version, add the spreadsheets

1. Open a **private or fresh-profile** browser window. Type `http://127.0.0.1:8000` in the
   address bar and press **Enter**. ☐

   **You should see:** the welcome screen, **Welcome to Askwell**, with a **Get started** button.
   If you see the **Ask** screen instead, the stack was not cleared. Go back to *Before you
   start*, step 3.

2. Click **Get started** and follow the steps until one offers to add material. Set a passphrase
   if asked, and write it down: the upgrade keeps it. ☐

   **You should see:** a step with an **Add a source** box, offering **Choose files** and
   **Choose a folder**.

3. Click **Choose a folder**. In the folder picker, go to `/tmp`, select `askwell-test-230`, and
   confirm. If the browser asks whether to let the site see the files, allow it. ☐

   **You should see:** a card counting three files, and the question **Which folder is
   “askwell-test-230” in?** with an empty field and an **Add them** button.

4. Type `/tmp` in the field and click **Add them**. If a note says **Askwell has not been given
   this folder yet.** and offers a **Nominate …** button, click it, then click **Add them** again
   if the button is still there. ☐

   **You should see:** the card move on to recording three files, then **Queued**, then indexing
   progress. There should be no red **Not added** note.

5. Finish the welcome steps. Skipping optional steps is fine. Click **Library** in the left
   column. ☐

   **You should see:** a source named **askwell-test-230**. Wait until it and its three files say
   **ready**. This takes a few minutes on CPU.

6. Still in **Library**, click **Add a source** at the top of the page. Add the folder
   `askwell-test-230-usb` from `/tmp` the same way as steps 3 and 4. ☐

   **You should see:** a second source, **askwell-test-230-usb**, with one file. Wait until it
   says **ready**.

7. Click **Memory** in the left column. Look for any row whose subject starts with
   **figures.xlsx:**, **raw.xlsx:**, **orders.xlsx:** or **stock.xlsx:**. ☐

   **You should see:** none. `0.9.11` never loaded a sheet as a table, so there is nothing that
   says **Loaded as table …**. This is the state an upgrading user is in.

8. Click **Clarifications** in the left column. ☐

   **You should see:** no question about **Placed**. `0.9.11` did not ask about sheet columns.
   There may be other questions about the workbooks' text; leave them.

9. **Stand-in.** Record how many times each file has been indexed, and confirm there is no sheet
   table anywhere yet: ☐

   ```
   cd ~/external/quantum-plus/askwell-0911
   scripts/dev.sh psql -tAc "SELECT d.filename, count(j.id) FROM documents d
     LEFT JOIN ingest_jobs j ON j.document_id = d.id GROUP BY 1 ORDER BY 1"
   scripts/dev.sh psql -tAc "SELECT name, sandbox_db FROM sources ORDER BY name"
   scripts/dev.sh psql -tAc "SELECT count(*) FROM audit_decisions WHERE kind LIKE 'workbook_tables_%'"
   ```

   **You should see:** four lines, `figures.xlsx|1`, `orders.xlsx|1`, `raw.xlsx|1`,
   `stock.xlsx|1`. **Write these numbers down;** Part B checks they have not changed. Then both
   sources with an empty database name after the `|`. Then `0`.

## Part B — upgrade, with one folder "unplugged"

10. **Stand-in.** Unplug the "drive": move the USB folder out of reach. Then stop the old version
    and its model, keeping its data. ☐

    ```
    mkdir -p /tmp/away-230
    mv /tmp/askwell-test-230-usb /tmp/away-230/
    cd ~/external/quantum-plus/askwell-0911
    podman compose down
    ```

    In the second terminal, press **Ctrl+C** to stop the model.

    **You should see:** the containers stopped and removed. **No** `-v`: the volumes, and so
    everything Askwell holds, are kept.

11. **Stand-in.** Install the current version over it and start it: ☐

    ```
    cd ~/external/quantum-plus/askwell
    cat VERSION
    scripts/dev.sh build
    scripts/dev.sh web-build
    podman compose up -d
    ```

    In the second terminal:

    ```
    cd ~/external/quantum-plus/askwell
    scripts/dev.sh inference
    ```

    **You should see:** `0.9.22` (or later), both builds finish, the containers start, and
    `migrate` exit with code 0. It runs every migration added since `0.9.11` against the kept
    data. The model reports ready.

12. Go back to the browser and reload the page. If it asks for the passphrase, enter the one from
    step 2. Click **Library**. ☐

    **You should see:** both sources still there, **askwell-test-230** with three files and
    **askwell-test-230-usb** with one. No indexing progress appears on either: nothing is re-read
    or re-embedded. **askwell-test-230** reads **Ready**.

    Under **askwell-test-230**, above the **Re-index** and **Delete** buttons, one short grey
    line: **raw.xlsx: The sheet Raw was not loaded as a table: no recognisable header row: …**,
    ending **Its text is still searched; give it one header row to ask it as a table.** The words
    after *header row:* are Askwell's own reason and may vary.

    ☐ **You should not see:** **Needs attention** on **askwell-test-230**, or a **Show detail**
    button under it. Either means a workbook's load was recorded as failed.

13. Click **Memory**. Find the rows whose subject starts with **figures.xlsx:Figures**. ☐

    **You should see:** a row **figures.xlsx:Figures**, with no column name after it, reading
    **Loaded as table `figures_xlsx_figures`, 3 row(s), 4 column(s).** Next to it, one row per
    column, such as **figures.xlsx:Figures.Q1 Revenue**. There is a matching
    **orders.xlsx:North** row with **3 row(s), 3 column(s)**.

    **This is the ticket's main check.** Before `0.9.22` these rows did not appear after an
    upgrade until the workbook was re-indexed.

    ☐ **You should not see:** any **raw.xlsx:** or **stock.xlsx:** row. `raw.xlsx` has no table;
    `stock.xlsx` could not be reached.

14. Click **Clarifications**. ☐

    **You should see:** a group headed **askwell-test-230** containing a question with subject
    **Placed**, reading *"\*Placed\* in \*orders.xlsx\*, sheet \*North\*, looks like a date in
    DD/MM/YYYY or MM/DD/YYYY — which is it? …"*, with the buttons **DD/MM/YYYY (day first)** and
    **MM/DD/YYYY (month first)**. The asterisks on screen are a known display gap from
    `M11-FIX-ING-228`. Do not answer it.

    A workbook loaded at start is asked about exactly as a newly added one would be.

15. **Stand-in.** Nothing was re-indexed, the tables are in the folder's own sandbox database,
    and none is in Askwell's (C3): ☐

    ```
    cd ~/external/quantum-plus/askwell
    scripts/dev.sh psql -tAc "SELECT d.filename, count(j.id) FROM documents d
      LEFT JOIN ingest_jobs j ON j.document_id = d.id GROUP BY 1 ORDER BY 1"
    DB=$(scripts/dev.sh psql -tAc "SELECT sandbox_db FROM sources WHERE name = 'askwell-test-230'" | tr -d '[:space:]')
    echo "$DB"
    podman compose exec sandbox sh -c "psql -U \"\$POSTGRES_USER\" -d $DB -tAc \"
      SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY 1\""
    scripts/dev.sh psql -tAc "SELECT count(*) FROM information_schema.tables WHERE table_name LIKE '%xlsx%'"
    ```

    **You should see:** the same four counts you wrote down in step 9, then a database name (not
    `askwell`), then `figures_xlsx_figures` and `orders_xlsx_north` and nothing else, then `0`.

    A higher count in the first lines means a workbook was re-indexed, which the ticket says must
    not happen.

16. **Stand-in.** What the worker did at start, and what it recorded: ☐

    ```
    podman compose logs worker 2>&1 | grep -E 'workbook_tables_backfilled|workbook_backfill_deferred|sandbox_database_lost'
    scripts/dev.sh psql -tAc "SELECT kind, payload->>'workbook', payload->>'tables' FROM audit_decisions
      WHERE kind LIKE 'workbook_tables_%' ORDER BY occurred_at"
    ```

    **You should see:** in the logs, three `workbook_tables_backfilled` lines (`tables` 1, 1 and
    0), and one `workbook_backfill_deferred` line with `reason` **file not readable**. That last
    one is `stock.xlsx`. No `sandbox_database_lost` line: nothing was lost.

    In the decisions, three `workbook_tables_loaded` rows, for `figures.xlsx`, `orders.xlsx` and
    `raw.xlsx`, the last with `[]`. **No** row for `stock.xlsx`, and **no**
    `workbook_tables_failed` row at all. A failed row for `stock.xlsx` means an unreachable file
    was recorded as the workbook's failure, which would stop it ever loading.

## Part C — once only, and the "drive" plugged back in

17. **Stand-in.** Restart the worker without changing anything, as the next launch would: ☐

    ```
    cd ~/external/quantum-plus/askwell
    podman compose restart worker
    sleep 30
    podman compose logs --since 1m worker 2>&1 | grep -E 'workbook_tables_backfilled|workbook_backfill_deferred'
    scripts/dev.sh psql -tAc "SELECT payload->>'workbook', count(*) FROM audit_decisions
      WHERE kind = 'workbook_tables_loaded' GROUP BY 1 ORDER BY 1"
    ```

    **You should see:** only one log line, `workbook_backfill_deferred` for `stock.xlsx` again.
    Then `figures.xlsx|1`, `orders.xlsx|1`, `raw.xlsx|1`. Still one each.

    **This is the second main check.** A `workbook_tables_backfilled` line for `raw.xlsx`, or a
    count of 2, means a workbook whose sheets were all skipped is being read at every start.

18. Reload the browser page and click **Library**. ☐

    **You should see:** **askwell-test-230** still **Ready**, with the same single grey line about
    **raw.xlsx**. **askwell-test-230-usb** is listed. It may say its folder cannot be found; that
    is the unplugged drive, not this ticket. It must **not** show a **Show detail** line saying
    **stock.xlsx** failed to load as a table. Don't open its file while it is away.

19. **Stand-in.** Plug the "drive" back in, and start the worker again: ☐

    ```
    mv /tmp/away-230/askwell-test-230-usb /tmp/
    podman compose restart worker
    sleep 30
    podman compose logs --since 1m worker 2>&1 | grep -E 'workbook_tables_backfilled|workbook_backfill_deferred'
    ```

    **You should see:** one `workbook_tables_backfilled` line, for `stock.xlsx`, with `tables` 1.
    No `workbook_backfill_deferred` line.

20. Reload the page and click **Memory**. ☐

    **You should see:** a new row **stock.xlsx:Stock** reading **Loaded as table
    `stock_xlsx_stock`, 3 row(s), 2 column(s).** The file waited for its drive rather than being
    written off.

21. Click **Ask** in the left column. Type **What was the Q1 revenue for Research in
    figures.xlsx?** and press **Enter**. ☐

    **You should see:** an answer naming **903,000** (or **903000**), citing **figures.xlsx**.
    Record whether the answer came from the sheet's text or from the table; the screen may not say
    which, and both are acceptable for this ticket. If it abstains, record it and go on: questions
    not reaching the table is #818, not this ticket's defect. This step checks that the upgraded
    install still answers from the upgraded workbook.

## Part D — the table database is lost, and the sandbox is slow to start

This covers the folder half of #895 and the ticket's first edge case. It removes
**askwell-test-230**'s sandbox database by hand, as losing the sandbox's volume would, with the
sandbox also down at the next start.

22. **Stand-in.** Stop the worker, drop the folder's database, and stop the sandbox: ☐

    ```
    cd ~/external/quantum-plus/askwell
    DB=$(scripts/dev.sh psql -tAc "SELECT sandbox_db FROM sources WHERE name = 'askwell-test-230'" | tr -d '[:space:]')
    echo "$DB"
    podman compose stop worker
    podman compose exec sandbox sh -c "psql -U \"\$POSTGRES_USER\" -d postgres -c 'DROP DATABASE $DB WITH (FORCE)'"
    podman compose stop sandbox
    ```

    **You should see:** the database name from step 15, then `DROP DATABASE`, and both containers
    stop.

23. **Stand-in.** Start the worker while the sandbox is still down: ☐

    ```
    podman compose start worker
    sleep 30
    podman compose logs --since 1m worker 2>&1 | grep -E 'sandbox_reclaim_deferred|workbook_backfill_deferred|sandbox_database_lost|workbook_tables_backfilled'
    scripts/dev.sh psql -tAc "SELECT count(*) FROM audit_decisions
      WHERE kind IN ('workbook_tables_failed', 'sandbox_database_lost')"
    ```

    **You should see:** one `sandbox_reclaim_deferred` line, and none of the others. Then `0`.

    A sandbox that is not up yet is a reason to wait, not a fact about the files. A
    `workbook_tables_failed` count above 0 is this ticket's defect.

24. Reload the page and click **Library**. ☐

    **You should see:** **askwell-test-230** still reads **Ready**, with no **Show detail**
    button. Nothing was marked failed while the sandbox was down.

25. **Stand-in.** Start the sandbox, then the worker again, as the next launch would: ☐

    ```
    podman compose start sandbox
    sleep 20
    podman compose restart worker
    sleep 30
    podman compose logs --since 1m worker 2>&1 | grep -E 'sandbox_database_lost|workbook_tables_backfilled'
    scripts/dev.sh psql -tAc "SELECT sandbox_db FROM sources WHERE name = 'askwell-test-230'"
    ```

    **You should see:** one `sandbox_database_lost` line naming the database from step 22, then
    three `workbook_tables_backfilled` lines, for `figures.xlsx`, `orders.xlsx` and `raw.xlsx`.
    Then a database name that is **different** from step 22's: the folder got a new one.

26. Reload the page and click **Memory**. ☐

    **You should see:** **figures.xlsx:Figures** and **orders.xlsx:North** still read **Loaded as
    table …**, the same as in step 13, once each. There is not a second copy of either row.

27. Click **Clarifications**. ☐

    **You should see:** still exactly one **Placed** question naming **orders.xlsx**. Reloading
    the workbook did not ask it a second time.

28. **Stand-in.** The recovery happens once, not at every start: ☐

    ```
    podman compose restart worker
    sleep 30
    podman compose logs --since 1m worker 2>&1 | grep -E 'sandbox_database_lost|workbook_tables_backfilled'
    DB=$(scripts/dev.sh psql -tAc "SELECT sandbox_db FROM sources WHERE name = 'askwell-test-230'" | tr -d '[:space:]')
    podman compose exec sandbox sh -c "psql -U \"\$POSTGRES_USER\" -d $DB -tAc \"
      SELECT 'figures', count(*) FROM figures_xlsx_figures UNION ALL
      SELECT 'orders', count(*) FROM orders_xlsx_north\""
    ```

    **You should see:** no log lines. Then `figures|3` and `orders|3`.

## Part E — nothing else moved

29. **Stand-in.** The audit chains are still intact: ☐

    ```
    podman compose exec api askwell-verify
    ```

    **You should see:** every chain reported intact, exit status 0. The old version's records and
    the new version's are one chain.

30. **Stand-in.** Remove the old version's copy: ☐

    ```
    cd ~/external/quantum-plus/askwell
    git worktree remove --force ../askwell-0911
    git worktree list
    ```

    **You should see:** only the repository folder listed.

---

## Result

| Part | Result | Notes |
| ---- | ------ | ----- |
| A — old version, spreadsheets added, no tables | | |
| B — upgrade: tables appear, nothing re-indexed (13 and 15 are the main checks) | | |
| C — once only (17); unplugged drive waits, then loads (19, 20); Ask still answers (21) | | |
| D — lost database with sandbox down: deferred (23), then rebuilt once (25–28) | | |
| E — audit chains, cleanup | | |

Tester, date, browser, `cat VERSION`, and in step 21 whether the answer came from text or table:

---

## Known gaps

These are deliberately not built, or belong to another ticket. Do not report them as defects of
this one.

- **Nothing on screen says the tables were loaded at start.** The upgrade is silent by design: the
  tables, notes and questions simply appear, as for a newly added workbook.
- **A workbook whose load failed is not retried at start.** It shows as **Needs attention**, and
  **Re-index** retries it, as for any failed load. Retrying at every start would repeat, say, a
  time-limit failure at every launch (`docs/decisions.md`).
- **The sandbox going down in the instant between its check and a load** records that workbook as
  failed. Re-indexing recovers it. Accepted in `docs/decisions.md`; not something a manual test can
  aim at.
- **A workbook deleted between the start's scan and its load** is covered by an automated test
  only. The window is milliseconds and cannot be hit by hand.
- **An imported database dump or CSV whose sandbox database is lost** still says **Ready** and
  answers nothing. Only folders are repaired, because their tables can be rebuilt from the
  workbooks; a dump's cannot (#895, kept open for that half). A CSV cannot be added from a screen
  yet in any case (#339, #344).
- **The first start after upgrading is slower** by the time the old workbooks take to load. The
  queue waits; nothing is lost. Later starts do one query.
- **Spreadsheet questions often do not reach the table yet** (#818). Step 21 records which path
  answered; this ticket only makes sure the table exists.
- **The question text shows asterisks** around names (step 14). That is `M11-FIX-ING-228`'s known
  display gap.
- **`grounded_qa.v1` is not part of this walkthrough.** It was run against the stack's own
  database when the ticket landed; the result is in `docs/BRAIN.md`. On the build machine the
  stack's worker mounts only `/tmp`, so the eval corpus folder under the repository is deferred as
  *file not readable* at start. A user's install mounts the home folder (`M11-FIX-BE-227`) and does
  not have this gap.
- **The Windows and macOS installers are not exercised here.** The code path is the same, and each
  platform's own walkthrough covers it.
