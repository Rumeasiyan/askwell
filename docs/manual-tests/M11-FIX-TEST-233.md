# Manual test — M11-FIX-TEST-233, `test-db` never drops a sandbox database it did not create

**Ticket:** `M11-FIX-TEST-233`, issue #858.

Askwell keeps every imported dump, CSV and workbook sheet in its own database on a separate,
isolated Postgres instance, the **sandbox** (C3). The product names these databases
`askwell_sbx_` followed by 32 hex digits.

`scripts/dev.sh test-db` runs against that same sandbox instance. Before this ticket, its cleanup
step (`_sweep` in `api/tests/conftest_sandbox.py`) treated **every** idle `askwell_sbx_…`
database as a leftover from an earlier test run and dropped it. On a development machine, that
meant one `test-db` run could delete the tables behind the stack's imported material. The Library
still said **ready**, but the tables were gone. Any eval running at the same time lost its tables
in the middle of the run. One product test (`reclaim_orphans`) could do the same.

Now:

1. **Tests name their sandbox databases differently.** A database a test creates is called
   `askwell_test_sbx_` plus 32 hex digits. That prefix is swapped in only inside the test
   process, for the whole run (`use_test_prefix`).
2. **The cleanup drops only test-named databases.** An idle `askwell_sbx_…` database is left
   alone, however long nothing has used it. A crashed earlier test run's `askwell_test_sbx_…`
   databases are still swept.
3. **The product is unchanged.** Outside the tests, Askwell still names its databases
   `askwell_sbx_…` and still refuses any other name (`InvalidSandboxName`). The sandbox roles are
   the same (C3).

**This ticket changes no product code.** Only the test harness and tests changed. So the
walkthrough has three kinds of step:

- the usual cold start, by clicking, to give the stack some real imported tables;
- running `test-db` in the terminal, which is the thing under test (**Stand-in**: a person using
  Askwell never runs the tests);
- going back to the browser to show that the imported tables still work afterwards.

**Version under test:** `0.9.18`. This ticket does not change the version: it is tests only
(`AGENTS.md` §7). Run `cat VERSION` and update this line if the version has moved on.

**Time:** about 60 minutes. Most of that is the full `test-db` run in Part C and indexing in
Part A.

**Who can run it:** anyone with a browser and a terminal on the build host. Every Askwell screen
is reached by clicking, starting from Askwell's front page. The terminal is used to make the test
file, to start Askwell, to run the tests, and to list the databases on the sandbox, which no
screen shows. Those steps are labelled **Stand-in**.

**What changed on disk.**

| Piece | File |
| ----- | ---- |
| The test prefix `askwell_test_sbx_`, swapped into `askwell.sandbox` for the whole run | `TEST_PREFIX`, `use_test_prefix` in `api/tests/conftest_sandbox.py` |
| The cleanup matches only the test prefix, with `_` escaped so it is not a wildcard | `_sweep`, `_like_prefix` in `api/tests/conftest_sandbox.py` |
| The sweep leaves a product-named database and drops a crashed run's; the product's `LIKE` does not match test names | `test_the_sandbox_sweep_leaves_a_database_it_did_not_create`, `test_the_product_does_not_enumerate_test_sandbox_databases` in `api/tests/test_harness.py` |
| Product naming is unchanged; a product name is refused under test; `reclaim_orphans` under test leaves a product database alone | `test_the_products_own_naming_is_unchanged`, `test_names_not_from_generate_name_are_refused`, `test_reclaim_orphans_under_test_leaves_a_product_named_database_alone` in `api/tests/test_sandbox.py` |
| Product naming (not changed) | `PREFIX`, `_NAME_RE`, `generate_name`, `_validate` in `api/src/askwell/sandbox.py` |

The reasoning is in `docs/decisions.md`, 2026-09-30, "`M11-FIX-TEST-233`". It includes why the
prefix is not `askwell_sbxtest_`: the product lists its databases with
`LIKE 'askwell_sbx_%'`, and `_` there matches any character.

---

## Read this first

**Nothing leaves this machine during this test.** No online AI, no web search.

**This protects development machines, not users' machines.** Tests never run on a user's
install. The damage this ticket stops happened on the build host: to the stack's own imported
tables, and to evals.

**Do not restart the `worker` container between Part B and Part D.** When the worker starts, the
product's own clean-up (`reclaim_orphans`) drops every `askwell_sbx_…` database that no source in
the stack claims. Part B creates one such database on purpose, as a stand-in for an eval's. A
worker restart would drop it and make Part D look like a failure of this ticket. That worker
behaviour is a separate problem, filed as #885.

**Run no other `test-db` at the same time**, by hand or from the build queue. Check with
`podman ps --format '{{.Names}} {{.Command}}' | grep pytest` before Part C; it should print
nothing. The cleanup drops any test database with no open connection at that moment, and cannot
tell a crashed run's database from a live run's that is between connections (#886). The other run
would fail partway through, and look like a flaky test.

**A skip is not a pass.** `test-db` fails rather than skips when it lacks something
(`AGENTS.md` §6). Any skip in Part C is a defect.

**Record the counts you see.** The numbers below were true when this ticket landed. A later
ticket may add tests, so a higher count is fine. A lower one, or any failure, is not.

---

## Before you start

> **Warning: the cold start below deletes everything this Askwell stack holds.** That means
> sources, memory, conversations, the audit log, settings and any stored provider key, and every
> database on the sandbox. Your original files are not touched. On the shared development
> machine, check first that nobody needs what the stack holds, and that **no eval and no build
> queue is using the stack**. If you are unsure, open **Settings → Your data → Export
> everything** first.

### 1. The test file (Stand-in)

Askwell can only read folders inside `ASKWELL_ROOTS_MOUNT` in `.env`. Check it, and check that
Redis has its three passwords:

```
cd ~/external/quantum-plus/askwell
grep ASKWELL_ROOTS_MOUNT .env
grep -c '^REDIS_\(API\|WORKER\|PROXY\)_PASSWORD=.' .env
```

**You should see:** a mount that contains `/tmp` (if it does not, set `ASKWELL_ROOTS_MOUNT=/tmp`),
then `3`.

The folder holds one workbook. Its **Placed** column holds dates as text that could be read
day-first or month-first, so Askwell asks about it. Answering that question later (Part D) makes
Askwell rewrite the table **inside its sandbox database**. That is the on-screen proof that the
database survived the test run. Save this as `.run/make-233.py` in the repository folder
(`.run/` is ignored by git):

```python
from pathlib import Path
import openpyxl

OUT = Path("/app/.run/m11-233/askwell-test-233")

# Both parts of every date are 12 or less, so no row settles day-first
# against month-first. 03/04/2025 is 3 April or 4 March.
ROWS = [
    ["Customer", "Placed", "Units"],
    ["Anna", "03/04/2025", 4],
    ["Ben", "05/06/2025", 7],
    ["Cara", "11/12/2025", 2],
]

book = openpyxl.Workbook()
sheet = book.active
sheet.title = "North"
for row in ROWS:
    sheet.append(row)
OUT.mkdir(parents=True, exist_ok=True)
book.save(OUT / "orders.xlsx")
print(sorted(p.name for p in OUT.iterdir()))
```

Then:

```
cd ~/external/quantum-plus/askwell
rm -rf .run/m11-233 /tmp/askwell-test-233
scripts/dev.sh run python /app/.run/make-233.py
cp -r .run/m11-233/askwell-test-233 /tmp/
ls /tmp/askwell-test-233
```

**You should see:** the script print `['orders.xlsx']`, then `orders.xlsx`.

### 2. Start Askwell from nothing (Stand-in)

```
cd ~/external/quantum-plus/askwell
podman compose down -v
scripts/dev.sh build-api
scripts/dev.sh web-build
podman compose up -d
scripts/dev.sh db upgrade head
```

**You should see:** the volumes removed, both builds finish with no red error text, the
containers start, and the migration end without an error. The stack must stay up for the whole
test: `test-db` needs it.

In a **second** terminal, start the model on the host and leave it running:

```
cd ~/external/quantum-plus/askwell
scripts/dev.sh inference
```

**You should see:** the supervisor report the model and the embedding model ready.

---

## Part A — cold start, first run, and some real imported tables

1. Open a **private or fresh-profile** browser window. Type `http://127.0.0.1:8000` in the
   address bar and press **Enter**. ☐

   **You should see:** the welcome screen, **Welcome to Askwell**, with a **Get started** button.
   If you see the **Ask** screen instead, the stack was not cleared. Go back to *Before you
   start*, step 2.

2. Click **Get started** and follow the steps until one offers to add material. Set a passphrase
   if asked, and write it down. ☐

   **You should see:** a step with an **Add a source** box, offering **Choose files** and
   **Choose a folder**.

3. Click **Choose a folder**. In the folder picker, go to `/tmp`, select `askwell-test-233`, and
   confirm. If the browser asks whether to let the site see the files, allow it. ☐

   **You should see:** a card counting one file, and the question **Which folder is
   “askwell-test-233” in?** with an empty field and an **Add them** button.

4. Type `/tmp` in the field and click **Add them**. If a note says **Askwell has not been given
   this folder yet.** and offers a **Nominate …** button, click it, then click **Add them** again
   if the button is still there. ☐

   **You should see:** the card move on to recording the file, then **Queued**, then indexing
   progress. There should be no red **Not added** note.

5. Finish the welcome steps. Skipping optional steps is fine. Click **Library** in the left
   column. ☐

   **You should see:** a source named **askwell-test-233**. Wait until it and `orders.xlsx` say
   **ready**. This takes a few minutes on CPU.

6. Click **Clarifications** in the left column. ☐

   **You should see:** a group headed **askwell-test-233** with a question about **Placed** in
   **orders.xlsx**, sheet **North**, and two buttons, **DD/MM/YYYY (day first)** and
   **MM/DD/YYYY (month first)**. The question text shows asterisks around the names; that is
   #873, not this ticket.

   **Do not answer it yet.** Part D answers it after the test run.

## Part B — what is on the sandbox before the test run (Stand-in)

7. List the stack's sandbox databases and which source owns each: ☐

   ```
   cd ~/external/quantum-plus/askwell
   DB=$(scripts/dev.sh psql -tAc "SELECT sandbox_db FROM sources WHERE name = 'askwell-test-233'" | tr -d '[:space:]')
   echo "$DB"
   podman compose exec sandbox sh -c "psql -U \"\$POSTGRES_USER\" -d postgres -tAc \"
     SELECT datname FROM pg_database WHERE datname LIKE 'askwell%' ORDER BY datname\""
   ```

   **You should see:** a name starting `askwell_sbx_` followed by 32 letters and digits. Then a
   list containing that same name. Write the name down.

8. Add two stand-in databases. The first plays an **eval's** database: product-named, idle,
   claimed by no source in this stack. The second plays a **crashed earlier test run's**
   leftover: ☐

   ```
   EVAL_DB=askwell_sbx_$(cat /proc/sys/kernel/random/uuid | tr -d -)
   CRASH_DB=askwell_test_sbx_$(cat /proc/sys/kernel/random/uuid | tr -d -)
   echo "$EVAL_DB $CRASH_DB"
   podman compose exec sandbox sh -c "psql -U \"\$POSTGRES_USER\" -d postgres \
     -c 'CREATE DATABASE \"$EVAL_DB\"' -c 'CREATE DATABASE \"$CRASH_DB\"'"
   ```

   **You should see:** the two names, then `CREATE DATABASE` twice. Write both names down. Keep
   this terminal open: the next steps use `$DB`, `$EVAL_DB` and `$CRASH_DB`. If you open a new
   terminal, set the three variables again by hand from what you wrote down.

## Part C — run the tests (Stand-in)

9. Run the ticket's own tests first: ☐

   ```
   scripts/dev.sh test-db tests/test_harness.py tests/test_sandbox.py \
     -k "sandbox_sweep or enumerate_test_sandbox or reclaim_orphans_under_test"
   ```

   **You should see:** `3 passed`, no failures and no skips. The first line of the pytest summary
   may say how many were deselected; that is expected.

   Then the tests that need no database, which include the naming checks:

   ```
   scripts/dev.sh test tests/test_sandbox.py -k "prefix or naming or not_from_generate_name"
   ```

   **You should see:** every selected test pass, no failures and no skips. At the time of
   writing that is `11 passed`.

10. Check the crashed-run stand-in is already gone, and the eval stand-in is not: ☐

    ```
    podman compose exec sandbox sh -c "psql -U \"\$POSTGRES_USER\" -d postgres -tAc \"
      SELECT datname FROM pg_database WHERE datname IN ('$DB', '$EVAL_DB', '$CRASH_DB') ORDER BY datname\""
    ```

    **You should see:** exactly two names, `$DB` and `$EVAL_DB` (both start `askwell_sbx_`).
    `$CRASH_DB` is gone: step 9's run swept it, because no test run had used it.

    **Fail if:** `$DB` or `$EVAL_DB` is missing. That is the bug #858 describes. **Also fail
    if:** `$CRASH_DB` is still there. A crashed run's leftovers must still be cleaned up.

11. Run the whole database-backed suite: ☐

    ```
    scripts/dev.sh test-db
    ```

    **You should see:** it end with `passed` and no `failed`, `error` or `skipped`. When this
    ticket landed that was `1097 passed`. This is the longest step. Write the count down.

12. Look at the sandbox again: ☐

    ```
    podman compose exec sandbox sh -c "psql -U \"\$POSTGRES_USER\" -d postgres -tAc \"
      SELECT datname FROM pg_database WHERE datname IN ('$DB', '$EVAL_DB') ORDER BY datname;
      SELECT 'test databases: ' || count(*) FROM pg_database WHERE datname LIKE 'askwell\\_test\\_sbx\\_%';
      SELECT 'product-named: ' || count(*) FROM pg_database WHERE datname LIKE 'askwell\\_sbx\\_%'\""
    ```

    **You should see:**
    - both `$DB` and `$EVAL_DB`. **This is the ticket's main check.** Before this ticket, the full
      run dropped both;
    - **test databases:** some number, possibly more than 0. These are databases the run just
      made and did not drop itself. They are swept at the start of the next run (step 13);
    - **product-named:** `2`, the same as in step 7 plus the eval stand-in. No test database
      has a name starting `askwell_sbx_`.

13. Run step 9's first command again, then step 12's command again: ☐

    **You should see:** `3 passed`, then **test databases: 0**, and both `$DB` and `$EVAL_DB`
    still listed. The leftovers from step 11 were swept; nothing else was.

## Part D — the imported table still works after the test run

14. Go back to the browser window. Reload the page. Click **Library**. ☐

    **You should see:** **askwell-test-233** and `orders.xlsx` still **ready**, with no
    attention note. (Before this ticket they also said **ready** after a `test-db` run, even
    though the table was gone. The next step is what tells the two apart.)

15. Click **Clarifications**. On the **Placed** question for **orders.xlsx**, click
    **DD/MM/YYYY (day first)**. ☐

    **You should see:**
    - the item confirm **Saved. Re-reading 2 tables.** with an **Undo** link for ten seconds.
      The "2" is #872; one table is reloaded;
    - a progress line, **Re-reading Placed…**, then **Re-reading Placed — N of M done. The
      source stays searchable.**, which goes away when it finishes (a few seconds);
    - the question gone from the list.

    Do **not** click **Undo**. If the progress line reports a failure, or never finishes, record
    it: the reload writes into the folder's sandbox database, and it fails when that database is
    missing.

16. Click **Memory** in the left column. Find **orders.xlsx:North.Placed**. ☐

    **You should see:** the row labelled **You told me**, reading **DD/MM/YYYY (day first)**.

17. **Stand-in.** The table in the folder's sandbox database really was rewritten: ☐

    ```
    podman compose exec sandbox sh -c "psql -U \"\$POSTGRES_USER\" -d $DB -tAc \"
      SELECT data_type FROM information_schema.columns
      WHERE table_name = 'orders_xlsx_north' AND column_name = 'placed';
      SELECT customer, placed FROM orders_xlsx_north ORDER BY customer\""
    ```

    **You should see:** `date`, then `Anna|2025-04-03`, `Ben|2025-06-05`, `Cara|2025-12-11`.
    If psql says `database "askwell_sbx_…" does not exist`, the test run dropped it. That is this
    ticket's defect.

## Part E — the product's own naming is unchanged (Stand-in)

18. Outside the tests, ask Askwell's own code for a new name, and give it a test-style name: ☐

    ```
    scripts/dev.sh run python -c "
    from askwell import sandbox
    print(sandbox.PREFIX, sandbox.generate_name())
    try:
        sandbox._validate('askwell_test_sbx_' + 'a' * 32)
    except sandbox.InvalidSandboxName as e:
        print('refused:', e)
    "
    ```

    **You should see:** `askwell_sbx_ askwell_sbx_` followed by 32 letters and digits. Then
    `refused: 'askwell_test_sbx_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' is not a name generate_name()
    produced — refusing to build SQL from it.` The product still makes only `askwell_sbx_`
    names and refuses a test name (C3).

19. The sandbox roles are the same as before: ☐

    ```
    podman compose exec sandbox sh -c "psql -U \"\$POSTGRES_USER\" -d postgres -tAc \"
      SELECT rolname, rolsuper, rolcreatedb FROM pg_roles WHERE rolname LIKE 'askwell%' ORDER BY rolname\""
    ```

    **You should see:** the instance superuser first, with `t|t` (`askwell_sandbox` unless
    `SANDBOX_POSTGRES_USER` in `.env` renames it). Then `askwell_sandbox_owner|f|f` and
    `askwell_sandbox_readonly|f|f`: neither can act as superuser or create a database. No role
    has `test` in its name.

## Part F — clean up (Stand-in)

20. Drop the eval stand-in, and confirm the audit chains are intact: ☐

    ```
    podman compose exec sandbox sh -c "psql -U \"\$POSTGRES_USER\" -d postgres \
      -c 'DROP DATABASE IF EXISTS \"$EVAL_DB\"'"
    podman compose exec api askwell-verify
    ```

    **You should see:** `DROP DATABASE`, then every chain reported intact, exit status 0.

    Then, in **Library**, remove **askwell-test-233** if nobody needs it, and delete
    `/tmp/askwell-test-233` and `.run/m11-233`.

---

## Result

| Part | Result | Notes |
| ---- | ------ | ----- |
| A — cold start, a folder with a workbook | | |
| B — sandbox before, two stand-ins | | |
| C — tests pass; stack and eval databases kept, crashed run's swept (12 is the main check) | | |
| D — the answered question rewrites the table after the run | | |
| E — product naming and roles unchanged | | |
| F — clean up, audit chains intact | | |

Tester, date, browser, `cat VERSION`, `test-db` count from step 11:

---

## Known gaps

These are deliberately not built, or belong to another ticket. Do not report them as defects of
this one.

- **A worker restart still drops an eval's sandbox databases** (#885). The product's own
  `reclaim_orphans` runs when the `worker` container starts and drops every `askwell_sbx_…`
  database no source in the stack claims. An eval's databases are claimed by the eval's database,
  not the stack's. This ticket only stops the *tests* from dropping them.
- **No screen shows the sandbox databases**, so Parts B, C and E are terminal steps. A missing
  database shows on screen only when something reads or rewrites its table, as in step 15.
- **The Library still says ready when a folder's sandbox database has gone.** Nothing checks
  that the database exists. This ticket removes the usual way it disappeared on a development
  machine; it does not add a check.
- **A test run's own sandbox databases stay until the next run**, as step 12 shows. They are
  swept at the start of the next `test-db` run.
- **Running an eval at the same time as `test-db` is not exercised here.** Step 8's stand-in
  database plays the eval's. #858's caution not to run `test-db` during an eval no longer
  applies, but #885 still means the worker must not restart during one.
- **Two `test-db` runs at once can still break each other** (#886). The cleanup reads "no
  connection right now" as "old", so a second run can drop a first run's database between two of
  its tests. This predates this ticket, which kept the same age check and only narrowed which
  names it looks at.
- **The main database's test databases are unchanged.** They are named `askwell_test_…` on the
  main Postgres instance, a different instance, and were never affected by #858.
- **"Saved. Re-reading 2 tables."** The count is the number of answer buttons (#872).
- **Asterisks show in question text** (#873).
- **The Windows and macOS installers are not exercised here.** No product code changed.
