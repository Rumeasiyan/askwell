# Manual test — M9-FIX-BE-207, answering a table-column question teaches Askwell about that column

**Ticket:** `M9-FIX-BE-207`, issue #361. When Askwell reads a spreadsheet or CSV file and cannot
work out what a column holds, it asks you on the **Clarifications** screen. Until now, your
answer was saved but went nowhere useful. The note Askwell reads when it writes a database query
about that table stayed its own unreviewed guess, so the next question about that column ignored
what you had said.

Now your answer replaces the guess, and the next question about that table uses it. The same
holds for a date column where you choose day-first or month-first: the column is re-loaded as a
real date. An answer applies only to the column of the file it was asked about. It does not
change a column with the same name in another file, and it does not close a question about a
same-named column in another file.

**Version under test:** `0.7.55`. Run `cat VERSION` and update this line if the version has
moved on.

**Time:** about 50 minutes. Most of it is the first build and waiting for the model on CPU.

**Who can run it:** anyone with a browser and a terminal. Every Askwell screen is reached by
clicking, starting from the address in step 1. The terminal starts Askwell, adds the CSV files,
and runs a few checks that cannot be done by looking at the screen. Those steps are labelled
**Stand-in**, and each one says why no screen can do it yet.

**What is being checked.**

| Piece | File |
| ----- | ---- |
| A column question's subject is the bare column name (`st_cd`), and its evidence names the file it came from (`table_name`) | `build_candidates`, `_column_position_evidence` in `api/src/askwell/table_infer.py` |
| An answer finds that file's column note, and only that one. A question about a same-named column in another file is not closed by it | `resolve_dependencies`, `_evidence_table_name` in `api/src/askwell/reapply.py` |
| An answered date question re-loads the right column as a date, including questions saved before this change | `_date_format_overrides` in `api/src/askwell/table_load.py` |

The interface did not change. The automated proof is in `api/tests/test_reapply.py`,
`api/tests/test_table_infer.py` and `api/tests/test_table_load_db.py`. This document repeats the
behaviour on a cold-started stack, the way a person meets it.

**The one rule of this test.** Never type an address into the browser bar except the one in
step 1. Reach every screen by clicking.

### Where this stops on purpose. Read this before reporting anything as a defect.

- **No screen can add a CSV file yet** (#344). On **Add a source**, the **Spreadsheet or CSV**
  panel says **Arrives in M4**. Part B confirms that is still true. Part C then adds the file from
  the terminal, using the same code the background worker runs. Everything after that is done by
  clicking.
- **Every database question on the shipped model is refused** (#789). The model's thinking text
  is sent where the query should be, and Askwell's SQL safety check correctly refuses it. So in
  Part F the answer is a refusal, not a list of store codes. Part F checks that your answer
  **reached** the query step, which is what this ticket fixed. Whether the query then runs is
  #789's job.

> **Known defects you may see on the way. Do not report them against this ticket.**
>
> - **The first click on an item in the left column after a fresh load sometimes does nothing**
>   (#665). Click it again.
> - **After you answer a CSV question, the note under it reads "Saved. Re-reading 0 tables in
>   this source."** (#790). The count is wrong, and the work does happen. Part E and Part G check
>   the result on the **Memory** screen instead.
> - **Each answer also adds a second row on the Memory screen, titled only with the column name
>   (`st_cd`, `ord_dt`), with no file name next to it** (#791). After Part H there are two
>   `st_cd` rows like that, with nothing saying which file each is about.
> - **The Library row for a loaded CSV says "Nothing in this source yet."** (#792). The table is
>   there; the line counts documents only.
> - **The question text shows asterisks around the column name**, for example `*st_cd*`. That is
>   existing behaviour on every question, not this ticket.

---

## Before you start

> **Warning: the cold start below deletes everything this Askwell stack holds.** That means
> sources, memory, conversations, the audit log and settings. Your original files are not
> touched. On the shared development machine, check that nobody needs what the stack holds now.
> If you are unsure, use **Settings → Your data → Export everything** first.

### A. The files to add

Askwell can only read folders inside `ASKWELL_ROOTS_MOUNT` in `.env`. Check it:

```
cd ~/external/quantum-plus/askwell
grep ASKWELL_ROOTS_MOUNT .env
```

If it is empty, or does not cover `/tmp`, set `ASKWELL_ROOTS_MOUNT=/tmp`. Then make the two test
files:

```
rm -rf /tmp/askwell-test-207
mkdir -p /tmp/askwell-test-207
printf 'order_id,st_cd,amount,ord_dt\n1001,014,120.50,03/04/2026\n1002,22,80.00,05/04/2026\n1003,B7,45.25,03/06/2026\n1004,014,300.00,07/05/2026\n1005,C3,19.99,09/08/2026\n1006,22,64.10,11/10/2026\n' \
  > /tmp/askwell-test-207/orders.csv
printf 'return_id,st_cd,ord_dt,reason\nR1,22,02/03/2026,damaged\nR2,B7,04/05/2026,wrong size\nR3,014,06/07/2026,damaged\nR4,C3,08/09/2026,late\nR5,22,10/11/2026,damaged\n' \
  > /tmp/askwell-test-207/returns.csv
chcon -R -t container_file_t /tmp/askwell-test-207
cat /tmp/askwell-test-207/orders.csv
```

**You should see:** the six orders printed with a header line. The `chcon` line lets the
containers read `/tmp` on a machine with SELinux turned on. If it says `Operation not
supported`, your machine does not use SELinux and you can ignore it.

Why these files look the way they do:

| Column | Why Askwell has to ask |
| ------ | ---------------------- |
| `st_cd` in both files | Mixes numbers (`014`, `22`) with codes (`B7`, `C3`), so no single type fits. This is the abbreviated column the ticket is about. It means **store code** |
| `ord_dt` in both files | Every date could be read day-first or month-first (`03/04/2026` is 3 April or 4 March). In `orders.csv` the dates are **day-first** |

`order_id`, `amount`, `return_id` and `reason` are clear, so Askwell asks nothing about them.

### B. Start Askwell from nothing

```
podman compose down -v
scripts/dev.sh web-build
scripts/dev.sh build-api
podman compose up -d
scripts/dev.sh db upgrade head
```

**You should see:** the volumes removed, both builds finish with no red error text, the
containers start, and the migration finish with no error. Do not skip the API build. This fix is
in the API, and without the build you are testing the old code.

In a **second** terminal, start the model on the host and leave it running:

```
scripts/dev.sh inference
```

**You should see:** the supervisor report that the model and the embedding model are ready.

---

## Part A — first run

1. Open a **private or fresh-profile** browser window at full width, so no earlier session
   carries over. Go to `http://127.0.0.1:8000`. ☐

   **You should see:** **Welcome to Askwell**, a **Skip setup** button top right, and a **Get
   started** button. Down the left, a column listing **Ask, Library, Clarifications, Memory,
   Settings**. If you see the Ask screen instead, the stack was not cleared. Go back to *Before
   you start*, B.

2. Click **Get started**. On the passphrase step, click **Not now**, then **Continue**. ☐

   **You should see:** the next step, about the model.

   Do not set a passphrase in this test. The check in step 17 reads a record that a passphrase
   would encrypt.

3. Wait until the model section says the model is ready, then click **Continue** without adding
   anything. ☐

   **You should see:** a step beginning *"Ready. Add something to ask about"*.

4. Click **Memory** in the left column. ☐

   **You should see:** a screen headed **Memory**, with the empty message *"Nothing here yet.
   Memory fills as Askwell asks about your material and you answer…"*. No rows. Every row you
   see later was written during this test.

5. Click **Clarifications** in the left column. ☐

   **You should see:** no questions, and no number next to **Clarifications** in the left column.

---

## Part B — a CSV still cannot be added from a screen

6. Click **Library** in the left column, then **Add a source**. ☐

   **You should see:** a screen headed **Add a source**. Among its panels is one titled
   **Spreadsheet or CSV**, marked **Arrives in M4**. That is why Part C uses the terminal. If this
   panel now lets you choose a file, #344 has landed: add `orders.csv` through it instead of step
   7, and note in your results that you did.

---

## Part C — add `orders.csv` (Stand-in)

**Stand-in, because no screen reaches CSV loading yet (#344).** This runs the same function the
background worker runs for a new CSV: it reads the file, raises its questions, and loads it into
a sealed database of its own.

7. In the first terminal, run: ☐

   ```bash
   podman compose exec api python3 -c "
   import asyncio
   from askwell.config import load_settings
   from askwell.db.engine import build_engine, session_factory, session_scope
   from askwell import table_load

   async def main():
       settings = load_settings()
       factory = session_factory(build_engine(settings))
       path = '/tmp/askwell-test-207/orders.csv'
       async with session_scope(factory) as session:
           source_id = await table_load.create_table_source(session, 'orders', path)
       print('source_id', source_id)
       for r in await table_load.process_table_source(factory, settings, source_id, path):
           print('table', r.sql_table_name, 'rows', r.row_count, 'failed', len(r.failed_rows))

   asyncio.run(main())
   "
   ```

   **You should see:** `source_id` followed by an id, then `table orders_csv rows 6 failed 0`.

8. Back in the browser, click **Library** in the left column. ☐

   **You should see:** a row named **orders**, marked **Ready**, with a line starting
   **Spreadsheet · Added**. Under it, the line *"Nothing in this source yet."* is wrong: the
   table did load. That is #792, not this ticket.

9. Look at the left column. ☐

   **You should see:** the number **2** next to **Clarifications**. If it has not appeared, click
   **Clarifications**. The screen picks up new questions on its own.

---

## Part D — before answering: Askwell's own guess

10. Click **Memory** in the left column. ☐

    **You should see:** one row for each column of `orders.csv`, each marked **I guessed**, with
    **orders** as its source. Find the row titled **orders.csv.st_cd**. Its text reads:

    > Inferred type: string (67% confidence). no single type reaches 80% agreement (best:
    > integer at 67%).

    This is the guess the ticket is about. Before this fix, it stayed like this whatever you
    answered.

11. Click **Clarifications** in the left column. ☐

    **You should see:** a group headed **orders**, with two questions:

    - **st_cd**: *"st_cd no single type reaches 80% agreement (best: integer at 67%). What is
      it?"*, with *"6 rows. Values: 014 (2) · 22 (1) · B7 (1) · C3 (1)"* under it, and a text box
      to type an answer.
    - **ord_dt**: *"ord_dt looks like a date in DD/MM/YYYY or MM/DD/YYYY — which is it? For
      example: 03/04/2026, 05/04/2026, 03/06/2026."*, with two buttons, **DD/MM/YYYY (day
      first)** and **MM/DD/YYYY (month first)**.

    **Fail if:** either question is missing, or either one is titled `orders.csv: st_cd` or
    `orders.csv: ord_dt`. That old title is the bug.

---

## Part E — answer the `st_cd` question

This is the ticket's cold-start walkthrough.

12. In the **st_cd** question's text box, type exactly this and click **Save**: ☐

    ```
    Store code: the branch that took the order.
    ```

    **You should see:** the question replaced by a note beginning **Saved.**, with an **Undo**
    link counting down from 10 seconds. The note says *"Re-reading 0 tables in this source."*;
    that count is #790 (see *Known defects*). **Do not click Undo.** A line reading *"Re-reading
    st_cd — 0 of 1 done. The source stays searchable."* may appear and then go.

13. Wait 30 seconds, then click **Memory** in the left column. ☐

    **You should see:** the row **orders.csv.st_cd** now marked **You told me**, with the text
    *"Store code: the branch that took the order."* Under it, the earlier guess from step 10
    appears struck through.

    **Fail if:** **orders.csv.st_cd** still says **I guessed**. That is exactly the bug #361
    describes. Wait another minute and click **Memory** again before recording a failure: the
    change is made by a background job.

    You will also see a separate row titled **st_cd**, with the same text and no source next to
    it. That row existed before this fix too. It is #791.

14. On the same screen, check the other `orders.csv` rows. ☐

    **You should see:** **orders.csv.order_id**, **orders.csv.amount** and **orders.csv.ord_dt**
    still marked **I guessed**. One answer changed one column.

---

## Part F — the next question about the table uses the answer

15. Click **Ask** in the left column. Type exactly this and press **Enter**: ☐

    ```
    What does st_cd mean in the orders table, and which st_cd values appear?
    ```

    **You should see, with the shipped model:** after up to two minutes, an answer beginning
    *"Askwell could not safely run the query it generated for your database:"*. That is #789,
    not this ticket.

    **If #789 has been fixed by the time you run this:** the answer names the store codes `014`,
    `22`, `B7` and `C3`, and may describe `st_cd` as a store code. Record which one you saw.

16. Under the answer, click **How did you get this?** ☐

    **You should see:** a step **Looked up schema**, then a step starting **Generated SQL was
    rejected** (with the shipped model), or a step saying the database was queried (if #789 is
    fixed).

    **Fail if:** the answer says no connected database could answer, or that nothing matched.
    That would mean the question never reached the `orders` table at all.

17. **Stand-in: what the query step was given.** The screen shows that the schema was looked up
    but not which notes were used. Askwell's decision log records that, so read it: ☐

    ```
    scripts/dev.sh psql -c "WITH last AS (SELECT payload FROM audit_decisions WHERE kind = 'sql_generated' ORDER BY occurred_at DESC LIMIT 1) SELECT n.table_name, n.column_name, n.origin, n.description FROM last, jsonb_array_elements_text(last.payload->'schema_note_ids') AS nid JOIN schema_notes n ON n.id = nid::uuid;"
    ```

    **You should see:** a row reading `orders.csv | st_cd | user | Store code: the branch that
    took the order.` Other `orders.csv` rows may be listed as well, marked `inferred`.

    **This is the acceptance criterion.** Your answer is what Askwell gave the model for `st_cd`
    when it wrote the query.

    **Fail if:** `st_cd` is listed as `inferred` with the text from step 10, or the query returns
    `(0 rows)` while step 16 showed **Looked up schema**.

---

## Part G — a date answer re-loads only its own file's column

This Part adds a second file with the same two column names. It checks the two ways the fix
could have reached too far: answering one file's question must not close the other file's
question, and must not change the other file's column.

18. **Stand-in, for the same reason as step 7.** Add `returns.csv`: ☐

    ```bash
    podman compose exec api python3 -c "
    import asyncio
    from askwell.config import load_settings
    from askwell.db.engine import build_engine, session_factory, session_scope
    from askwell import table_load

    async def main():
        settings = load_settings()
        factory = session_factory(build_engine(settings))
        path = '/tmp/askwell-test-207/returns.csv'
        async with session_scope(factory) as session:
            source_id = await table_load.create_table_source(session, 'returns', path)
        print('source_id', source_id)
        for r in await table_load.process_table_source(factory, settings, source_id, path):
            print('table', r.sql_table_name, 'rows', r.row_count, 'failed', len(r.failed_rows))

    asyncio.run(main())
    "
    ```

    **You should see:** `table returns_csv rows 5 failed 0`.

19. In the browser, click **Clarifications** in the left column. ☐

    **You should see:** the number **3** next to **Clarifications**. The **orders** group has one
    question left (**ord_dt**). A new **returns** group has two (**st_cd** and **ord_dt**). The
    `returns` **st_cd** question shows *"5 rows. Values: 22 (2) · 014 (1) · B7 (1) · C3 (1)"*.

20. In the **orders** group, on the **ord_dt** question, click **DD/MM/YYYY (day first)**. ☐

    **You should see:** the **orders** question replaced by a note beginning **Saved.**
    **Do not click Undo.**

21. Wait 30 seconds and look at the **returns** group on the same screen. ☐

    **You should see:** both **returns** questions still there, **st_cd** and **ord_dt**,
    unanswered. The number next to **Clarifications** reads **2**.

    **Fail if:** the **returns** **ord_dt** question has gone. Answering the `orders` date
    question closed another file's question. This is the second loosening the ticket forbids.
    Reload the screen once by clicking **Memory** and then **Clarifications** before recording a
    failure.

22. Click **Memory** in the left column. ☐

    **You should see:**

    - **orders.csv.ord_dt** marked **You told me**, reading *"DD/MM/YYYY (day first)"*.
    - **orders.csv.st_cd** still marked **You told me** with your store-code answer. The date
      answer did not undo it.
    - **returns.csv.st_cd** and **returns.csv.ord_dt** still marked **I guessed**.

23. **Stand-in: the column really is a date now.** No screen shows a loaded table's column types,
    so read the sealed databases directly: ☐

    ```
    scripts/dev.sh psql -tAc "SELECT name, sandbox_db FROM sources WHERE name IN ('orders', 'returns') ORDER BY name"
    ```

    This prints two lines, `orders|<database>` and `returns|<database>`. Run the next command
    twice: once with the `orders` database name in place of `<database>`, once with the `returns`
    one.

    ```
    podman compose exec sandbox sh -c 'psql -U "$POSTGRES_USER" -d "$1" -c "$2"' _ <database> \
      "SELECT table_name, column_name, data_type FROM information_schema.columns WHERE column_name = 'ord_dt'"
    ```

    **You should see:** `orders_csv | ord_dt | date` for the `orders` database, and
    `returns_csv | ord_dt | text` for the `returns` one. Then, with the `orders` database name:

    ```
    podman compose exec sandbox sh -c 'psql -U "$POSTGRES_USER" -d "$1" -c "$2"' _ <database> \
      "SELECT order_id, ord_dt FROM orders_csv ORDER BY order_id LIMIT 2"
    ```

    **You should see:** `1001 | 2026-04-03` and `1002 | 2026-04-05`. That is 3 April and
    5 April: read day-first, as you answered.

    **Fail if:** `orders_csv.ord_dt` is still `text` two minutes after step 20, or the first date
    reads `2026-03-04`.

---

## Part H — a column whose note is gone: the answer attaches to nothing else

The ticket's edge case is a column that no longer exists. For a CSV there is no step that finds
a vanished column and marks its note stale. That rule exists only for database dumps and live
connections (see *Known gaps*). What this fix must guarantee is narrower. When the note for the
column is no longer there, the answer must not land on a different column instead.

24. **Stand-in: retire the `returns` `st_cd` note,** as if that column had been removed. No
    screen can do this: ☐

    ```
    scripts/dev.sh psql -c "UPDATE schema_notes SET superseded_by = id WHERE table_name = 'returns.csv' AND column_name = 'st_cd' AND superseded_by IS NULL"
    ```

    **You should see:** `UPDATE 1`.

25. Click **Memory** in the left column. ☐

    **You should see:** no **returns.csv.st_cd** row any more. **returns.csv.return_id**,
    **returns.csv.ord_dt** and **returns.csv.reason** are still there, marked **I guessed**.

26. Click **Clarifications** in the left column. In the **returns** group, on **st_cd**, type
    `Store code.` and click **Save**. ☐

    **You should see:** a note beginning **Saved.** **Do not click Undo.**

27. Wait 30 seconds, then click **Memory** in the left column. ☐

    **You should see:**

    - still no **returns.csv.st_cd** row;
    - **returns.csv.return_id**, **returns.csv.ord_dt** and **returns.csv.reason** still marked
      **I guessed**, with their text unchanged;
    - **orders.csv.st_cd** still reading *"Store code: the branch that took the order."*, not
      *"Store code."*

    There is now a second row titled **st_cd** with no source, reading *"Store code."* That is
    #791.

    **Fail if:** any `returns.csv` row has changed to **You told me**, or **orders.csv.st_cd**
    now reads *"Store code."*

---

## Part I — the answers survive a restart

28. In the first terminal: ☐

    ```
    podman compose restart api worker
    ```

    Wait about 20 seconds, then reload the browser tab and click **Memory** in the left column.

    **You should see:** exactly what step 27 showed. **orders.csv.st_cd** and
    **orders.csv.ord_dt** are still marked **You told me**.

29. Click **Clarifications** in the left column. ☐

    **You should see:** one question left, **returns** **ord_dt**, and the number **1** next to
    **Clarifications**. Nothing you answered has come back.

---

## Clean up

```
podman compose down -v
rm -rf /tmp/askwell-test-207
```

Put `ASKWELL_ROOTS_MOUNT` in `.env` back to what it was, if you changed it.

---

## Known gaps

Deliberately not built by this ticket. Do not report these as defects.

- **No screen adds a CSV or spreadsheet** (#344). The **Spreadsheet or CSV** panel on **Add a
  source** says **Arrives in M4**, which is why steps 7 and 18 use the terminal.
- **Database questions are refused on the shipped model** (#789). This ticket made your answer
  reach the query step, which step 17 proves. The query itself failing is #789.
- **The answer confirmation says "0 tables in this source"** (#790), and the end-of-session
  summary on **Clarifications** can undercount tables for the same reason.
- **The Memory row an answer writes has lost its file** (#791). Each answer adds a row titled
  with the bare column name and no source. Two files' answers about `st_cd` or `ord_dt` sit side
  by side, and nothing says which file each is about. Correcting such a row on the Memory screen
  does not reach the column note. Correct the **orders.csv.st_cd** row instead.
- **A CSV column that disappears is not marked stale.** The rule that marks a vanished column's
  note stale belongs to database dumps and live connections, when they are re-read. A CSV is
  loaded once, and no screen re-reads it. Part H checks what this ticket owns: an answer about a
  column with no note attaches to nothing else.
- **An abbreviated column whose values are all one type raises no question** (#793). For a CSV,
  Askwell asks about a column only when it cannot tell what type it holds, or which way round its
  dates are. A `st_cd` column holding only numbers loads as a number and is never asked about,
  whatever its name. The fixture mixes codes with numbers for that reason. Dumps and live
  connections do get a question about a cryptic column name. CSVs do not yet, and #361 did not
  name it.
- **The Library row for a loaded CSV says "Nothing in this source yet."** (#792).
- **Questions about a database's own columns work as before.** The questions Askwell asks about
  dump and live-connection columns already used the bare column name. Where two tables in one
  database share a column name, one answer still reaches both. That existing behaviour is
  recorded in `docs/decisions.md` (2026-09-28) and was not changed here.
