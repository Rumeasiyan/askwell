# Manual test — M11-FIX-ING-228, a workbook's sheets ask about the columns they could not type

**Ticket:** `M11-FIX-ING-228`, issue #851.

Before this ticket, a spreadsheet added as part of a folder loaded its sheets as tables
(`M11-FIX-ING-224`) but never asked a question. A column like `03/04/2025`, which could be 3 April
or 4 March, loaded as text and nobody was asked. A question like "orders in April" then compared
text, not dates. It stayed silent because a folder is one source, and Askwell asked about each
source only once. A sheet question could have stopped every document question in the folder,
and the other way round.

Now:

1. **A sheet asks, and the question names the workbook and the sheet.** It sits in the
   **Clarifications** screen next to the folder's document questions. Each workbook is asked
   about once, and the folder's documents once, independently.
2. **All the folder's questions share one limit of five.** When a sheet question takes a place,
   the folder's document scan asks that many fewer. What it does not ask goes to **Memory** as
   Askwell's own guess, as before.
3. **Answering a sheet's date question reloads that workbook only**, in the folder's own isolated
   database (C3). The column becomes a real date. Other workbooks in the folder are not touched.
4. **Re-indexing the workbook later keeps the answer.** It is not asked again, and the column stays
   a date.

**Version under test:** `0.9.16`. Run `cat VERSION` and update this line if the version has moved
on.

**Time:** about 60 minutes for Parts A–F. Part G is optional: it rebuilds Askwell twice and adds
about 30 minutes.

**Who can run it:** anyone with a browser and a terminal on the build host. Every Askwell screen is
reached by clicking, starting from Askwell's front page. The terminal is used only to make the
test files, to start Askwell, and to read things the interface does not show, such as a column's
type inside the database. Those steps are labelled **Stand-in**.

**What changed on disk.**

| Piece | File |
| ----- | ---- |
| A sheet's questions, once per workbook, within the folder's remaining limit; the question names workbook and sheet | `raise_workbook_questions`, `_name_the_sheet`, `_insert_questions` in `api/src/askwell/table_infer.py` |
| A folder's document scan ignores sheet questions when deciding "already asked", and asks at most the limit less what is waiting | `raise_candidates`, `pending_clarifications`, `WORKBOOK_EVIDENCE_KEY` in `api/src/askwell/clarify.py` |
| Answering a date question passes the sheet's table name to the reload | `_promote_schema_note`, `_process_item` in `api/src/askwell/reapply.py` |
| Reload one workbook of a folder; every workbook load applies the folder's answered date questions | `reload_source`, `_workbook_of_table`, `load_workbook_tables` in `api/src/askwell/table_load.py` |

The reasoning, including why the key is the workbook's path and not its document, is in
`docs/decisions.md`, 2026-09-30, "`M11-FIX-ING-228`".

---

## Read this first

**Nothing leaves this machine during this test.** No online AI, no web search.

**Leave questions unanswered unless a step says to answer them.** Several checks count what is
still waiting.

**The question text shows asterisks.** For example, *"\*Placed\* in \*orders.xlsx\*, sheet
\*North\*, looks like a date…"*, with the asterisks on screen. CSV questions have always looked
like this. It is #873, not this ticket's defect. Read past the asterisks.

**"Saved. Re-reading 2 tables."** After you answer a date question, the confirmation says
2 tables even though one is reloaded. The 2 is the number of answer buttons. That is #872 and
is not this ticket's defect.

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

The spreadsheets have to hold their dates as **text**, the way an export or a hand-typed sheet
does. A spreadsheet program would usually turn `03/04/2025` into a real date cell, which Askwell
reads without asking. So they are made with a short script, run inside Askwell's own image. Save
this as `.run/make-228.py` in the repository folder (`.run/` is ignored by git):

```python
from pathlib import Path
import openpyxl

OUT = Path("/app/.run/m11-228")

# Both parts of every date are 12 or less, so no row settles day-first
# against month-first. 03/04/2025 is 3 April or 4 March.
ORDERS = [
    ["Customer", "Placed", "Units"],
    ["Anna", "03/04/2025", 4],
    ["Ben", "05/06/2025", 7],
    ["Cara", "11/12/2025", 2],
]


def workbook(path: Path, sheets: dict[str, list[list[object]]]) -> None:
    book = openpyxl.Workbook()
    for index, (title, rows) in enumerate(sheets.items()):
        sheet = book.active if index == 0 else book.create_sheet()
        sheet.title = title
        for row in rows:
            sheet.append(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    book.save(path)


main = OUT / "askwell-test-228"
workbook(main / "orders.xlsx", {"North": ORDERS})
workbook(main / "returns.xlsx", {"North": ORDERS})
(main / "tender.txt").write_text(
    "Tender notes\n\n"
    "The RFQ closes on Friday. Send the RFQ to procurement. "
    "Questions about the RFQ go to the buyer. The RFQ has three lots.\n"
)

changed = OUT / "orders-changed.xlsx"
workbook(changed, {"North": [*ORDERS, ["Dev", "07/08/2025", 1]]})

cap = OUT / "askwell-test-228-cap"
workbook(cap / "ledger.xlsx", {"Jan": ORDERS, "Feb": ORDERS, "Mar": ORDERS})
(cap / "notes.txt").write_text(
    "Ledger notes\n\n"
    + "Ask the KLM desk. " * 6
    + "\n"
    + "The PQR team signs off. " * 5
    + "\n"
    + "File it with TUV. " * 4
    + "\n"
    + "Copy WXY in. " * 4
    + "\n"
)
print(sorted(str(p.relative_to(OUT)) for p in OUT.rglob("*") if p.is_file()))
```

Then:

```
cd ~/external/quantum-plus/askwell
rm -rf .run/m11-228 /tmp/askwell-test-228 /tmp/askwell-test-228-cap /tmp/orders-changed.xlsx
scripts/dev.sh run python /app/.run/make-228.py
cp -r .run/m11-228/askwell-test-228 .run/m11-228/askwell-test-228-cap .run/m11-228/orders-changed.xlsx /tmp/
ls -R /tmp/askwell-test-228 /tmp/askwell-test-228-cap
```

**You should see:** the script print six file names. Then `/tmp/askwell-test-228` holds
`orders.xlsx`, `returns.xlsx` and `tender.txt`, and `/tmp/askwell-test-228-cap` holds
`ledger.xlsx` and `notes.txt`.

What each is for:

- `orders.xlsx` and `returns.xlsx` each have a sheet **North** with an undecided `Placed` date
  column. Two workbooks with the same sheet and column names show that each is asked about
  separately, and that answering one reloads only that one.
- `tender.txt` uses `RFQ` four times without explaining it. That is a document question in the
  same folder.
- `askwell-test-228-cap` has three sheet questions (`ledger.xlsx`, sheets **Jan**, **Feb**,
  **Mar**) and four unexplained abbreviations. That is seven possible questions for a limit of
  five.

### 2. Start Askwell from nothing (Stand-in)

```
cd ~/external/quantum-plus/askwell
podman compose down -v
scripts/dev.sh build-api
scripts/dev.sh web-build
podman compose up -d
scripts/dev.sh db upgrade head
```

**You should see:** the volumes removed, both builds finish with no red error text, the containers
start, and the migration end without an error.

In a **second** terminal, start the model on the host and leave it running:

```
cd ~/external/quantum-plus/askwell
scripts/dev.sh inference
```

**You should see:** the supervisor report the model and the embedding model ready. (Indexing does
not need the answering model; only the optional Part F does.)

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

3. Click **Choose a folder**. In the folder picker, go to `/tmp`, select `askwell-test-228`, and
   confirm. If the browser asks whether to let the site see the files, allow it. ☐

   **You should see:** a card counting three files, and the question **Which folder is
   “askwell-test-228” in?** with an empty field and an **Add them** button.

4. Type `/tmp` in the field and click **Add them**. If a note says **Askwell has not been given
   this folder yet.** and offers a **Nominate …** button, click it, then click **Add them** again
   if the button is still there. ☐

   **You should see:** the card move on to recording three files, then **Queued**, then
   indexing progress. There should be no red **Not added** note.

5. Finish the welcome steps. Skipping optional steps is fine. Click **Library** in the left
   column. ☐

   **You should see:** a source named **askwell-test-228**. Wait until it and its three files say
   **ready**. This takes a few minutes on CPU.

## Part B — both kinds of question are asked, in one folder

6. Click **Clarifications** in the left column. ☐

   **You should see:** one group headed **askwell-test-228**, with **3 questions** beside it and
   a **Skip all** link. The three questions are:

   - subject **Placed**, reading *"\*Placed\* in \*orders.xlsx\*, sheet \*North\*, looks like a
     date in DD/MM/YYYY or MM/DD/YYYY — which is it? For example: 03/04/2025, 05/06/2025,
     11/12/2025."*;
   - subject **Placed** again, reading the same but with **returns.xlsx**;
   - subject **RFQ**, the document question, asking what `RFQ` means, with the passages from
     `tender.txt` under it.

   Under each **Placed** question: **3 rows. Values: 03/04/2025 (1) · 05/06/2025 (1) ·
   11/12/2025 (1)**, and two buttons, **DD/MM/YYYY (day first)** and **MM/DD/YYYY (month
   first)**. There is no text box.

   **This is the ticket's main check.** Before `0.9.16`, only **RFQ** appeared. If either
   **Placed** question is missing, or **RFQ** is missing, record which and stop: everything after
   this depends on it.

   ☐ **You should not see:** a question that says *"orders_xlsx_north"* or any other internal
   table name. It names the file and the sheet.

7. Click **Memory** in the left column. Find the rows whose subject starts `orders.xlsx:North`. ☐

   **You should see:** a row **orders.xlsx:North.Placed**, labelled **I guessed**. Its text starts
   *Inferred type:* and says the column *does not disambiguate between day-first (DD/MM) and
   month-first (MM/DD)*. A matching row exists for **returns.xlsx:North.Placed**. Do not change
   either row.

8. **Stand-in.** Both columns are text for now, and both tables are in the folder's own sandbox
   database, not Askwell's: ☐

   ```
   cd ~/external/quantum-plus/askwell
   DB=$(scripts/dev.sh psql -tAc "SELECT sandbox_db FROM sources WHERE name = 'askwell-test-228'" | tr -d '[:space:]')
   echo "$DB"
   podman compose exec sandbox sh -c "psql -U \"\$POSTGRES_USER\" -d $DB -tAc \"
     SELECT table_name, data_type FROM information_schema.columns
     WHERE column_name = 'placed' ORDER BY table_name\""
   scripts/dev.sh psql -tAc "SELECT count(*) FROM information_schema.tables WHERE table_name LIKE '%xlsx%'"
   ```

   **You should see:** a database name (not `askwell`), then `orders_xlsx_north|text` and
   `returns_xlsx_north|text`, then `0`: no workbook table exists in Askwell's own database (C3).

## Part C — answering a sheet's date question

9. Click **Clarifications**. On the **Placed** question that names **orders.xlsx**, click
   **DD/MM/YYYY (day first)**. ☐

   **You should see:**
   - the item confirm **Saved. Re-reading 2 tables.** with an **Undo** link for ten seconds. The
     "2" is #872; one table is reloaded;
   - a progress line above the list, **Re-reading Placed…**, then **Re-reading Placed — N of M
     done. The source stays searchable.**, which goes away when it finishes (a few seconds);
   - the group now reads **2 questions**: the **returns.xlsx** **Placed** question and **RFQ**
     are still there.

   Do **not** click **Undo**.

10. Click **Memory**. Find **orders.xlsx:North.Placed** again. ☐

    **You should see:** the row now labelled **You told me**, reading **DD/MM/YYYY (day first)**.
    **returns.xlsx:North.Placed** is still **I guessed**. There is only one active row for
    **orders.xlsx:North.Placed**. If an **I guessed** row sits next to your answer, that is this
    ticket's defect.

11. **Stand-in.** The answered workbook's column is a date, read day-first, and the other
    workbook's is untouched: ☐

    ```
    podman compose exec sandbox sh -c "psql -U \"\$POSTGRES_USER\" -d $DB -tAc \"
      SELECT table_name, data_type FROM information_schema.columns
      WHERE column_name = 'placed' ORDER BY table_name;
      SELECT customer, placed FROM orders_xlsx_north ORDER BY customer;
      SELECT obj_description('orders_xlsx_north'::regclass, 'pg_class')\""
    ```

    **You should see:**
    - `orders_xlsx_north|date` and `returns_xlsx_north|text`;
    - `Anna|2025-04-03`, `Ben|2025-06-05`, `Cara|2025-12-11`. Day first means `03/04/2025` is
      **3 April**. If Anna shows `2025-03-04`, the answer was applied the wrong way round;
    - `askwell workbook: orders.xlsx`. The table still says which workbook it belongs to.

    If `$DB` is empty because this is a new terminal, set it again with the first line of
    step 8.

12. **Stand-in.** The record is the same as for a CSV question, and it names the workbook: ☐

    ```
    scripts/dev.sh psql -c "SELECT kind, payload->>'subject' AS subject, payload->>'workbook' AS workbook,
      payload->'tables' AS tables FROM audit_decisions
      WHERE kind IN ('table_clarification_raised', 'clarification_capped', 'table_column_reloaded')
      ORDER BY occurred_at"
    ```

    **You should see:** two `table_clarification_raised` rows, subject `Placed`, one with
    workbook `orders.xlsx` and one with `returns.xlsx`. After them, one `table_column_reloaded`
    row, workbook `orders.xlsx`, tables `["orders_xlsx_north"]`. There are no
    `clarification_capped` rows for this folder.

## Part D — the workbook changes and is indexed again

The ticket's second edge case: a workbook re-indexed after its question was answered.

13. **Stand-in.** Change the workbook on disk, the way someone adding a row would: ☐

    ```
    cp /tmp/orders-changed.xlsx /tmp/askwell-test-228/orders.xlsx
    ```

    It now has a fourth row, `Dev`, placed `07/08/2025`.

14. Click **Library**. On **askwell-test-228**, click **Re-index**. Read the confirmation and
    click **Re-index it**. ☐

    **You should see:** **Re-indexing 3 documents.** Wait until the source and its three files say
    **ready** again.

15. Click **Clarifications**. ☐

    **You should see:** still **2 questions** for **askwell-test-228**: the **returns.xlsx**
    **Placed** question and **RFQ**. There is **no** new question about **orders.xlsx**, and
    **RFQ** appears only once. A second **orders.xlsx** question means the workbook was asked
    twice. That is this ticket's defect.

16. Click **Memory**. ☐

    **You should see:** **orders.xlsx:North.Placed** still **You told me**, **DD/MM/YYYY (day
    first)**, and no **I guessed** row beside it.

17. **Stand-in.** The reloaded table kept the answer and has the new row: ☐

    ```
    podman compose exec sandbox sh -c "psql -U \"\$POSTGRES_USER\" -d $DB -tAc \"
      SELECT data_type FROM information_schema.columns
      WHERE table_name = 'orders_xlsx_north' AND column_name = 'placed';
      SELECT customer, placed FROM orders_xlsx_north ORDER BY customer\""
    ```

    **You should see:** `date`, then four rows, ending `Dev|2025-08-07`.

## Part E — one limit for the whole folder

18. Click **Library**, then **Add a source**, then **Choose a folder**. Pick
    `/tmp/askwell-test-228-cap` and confirm. When asked **Which folder is
    “askwell-test-228-cap” in?**, type `/tmp` and click **Add them**. ☐

    **You should see:** two files recorded and queued. Wait in **Library** until
    **askwell-test-228-cap** and both files say **ready**.

19. Click **Clarifications**. Look at the **askwell-test-228-cap** group. ☐

    **You should see:**
    - **5 questions**, no more. That is the limit, shared by the sheets and the document;
    - three **Placed** questions naming **ledger.xlsx**, one each for sheets **Jan**, **Feb**
      and **Mar**. The sheets load first, so they take their places first;
    - two abbreviation questions from `notes.txt`: **KLM** and **PQR**, the two used most;
    - the note **Asking about the 5 that matter most. Askwell inferred the rest — you can review
      them in Memory.** with a **Review in Memory** link.

    The **askwell-test-228** group from Part C is unchanged, at **2 questions**. Each folder has
    its own limit.

20. Click **Review in Memory**. ☐

    **You should see:** rows for **TUV** and **WXY**, each labelled **I guessed**, each reading
    *'…' appears throughout. What does it mean? Not asked — ranked 3 of 4* (for **TUV**; **WXY**
    reads *4 of 4*) *for this source, with 3 question(s) already waiting, below the cap of 5.*
    The ranking counts only the four document candidates; the three sheet questions are the
    ones *already waiting*. The words *with 3 question(s) already waiting* are new in this
    ticket. They say why a document question was
    not asked when the folder raised fewer than five of its own.

    If a sixth question appears in step 19, or **TUV**/**WXY** are asked rather than in Memory,
    the limit is not shared. Report it with the list you saw.

## Part F — the rest of the product still holds (informative)

21. Click **Ask** in the left column. Type **What does the Placed column in orders.xlsx
    contain?** and press **Enter**. Wait for the answer. ☐

    **You should see:** an answer, or Askwell saying it cannot find this in your material, with
    no error. **This step does not pass or fail the ticket.** A question is only answered from a
    sheet's table when the passages come back weak (`M11-FIX-ING-224`), and a table answer has no
    citation yet (#857). If there is an answer, click **How did you get this?** and note whether
    it used passages or a table. That note is useful for #857, but it is not a result here.

22. **Stand-in.** The audit chains are still intact after all this: ☐

    ```
    podman compose exec api askwell-verify
    ```

    **You should see:** every chain reported intact, exit status 0.

23. **Stand-in, long (about an hour).** The ticket's grounding check: `abstention.v1` does not
    regress: ☐

    ```
    scripts/dev.sh eval --suite abstention.v1
    ```

    **You should see:** a mean no lower than the **0.53** recorded in `docs/BRAIN.md` for
    `0.9.16`. That is still far below the C5 bar of 0.90. That gap is #769 and #814 and is not
    this ticket's; this step checks only that nothing got worse. Record the result file's name.

## Part G — optional: a folder asked about before this change

The ticket's first edge case: a folder whose document questions were raised by `0.9.15`, when
its workbook was never asked. This rebuilds Askwell at `0.9.15`, then upgrades it.

24. **Stand-in.** Build `0.9.15` and start it from nothing: ☐

    ```
    cd ~/external/quantum-plus/askwell
    git worktree add /tmp/askwell-0.9.15 5d13b10d
    (cd /tmp/askwell-0.9.15 && scripts/dev.sh build-api)
    podman compose down -v && podman compose up -d && scripts/dev.sh db upgrade head
    rm -rf /tmp/askwell-test-228 && cp -r .run/m11-228/askwell-test-228 /tmp/
    ```

    **You should see:** the build finish, and the stack start.

25. Repeat steps 1–5 in a new private window. Then click **Clarifications**. ☐

    **You should see:** the **askwell-test-228** group with **1 question**, **RFQ**. Neither
    workbook asks. This is the old behaviour.

26. **Stand-in.** Upgrade to this ticket's build, keeping the data: ☐

    ```
    cd ~/external/quantum-plus/askwell
    scripts/dev.sh build-api
    podman compose up -d --force-recreate api worker
    git worktree remove /tmp/askwell-0.9.15
    ```

27. Reload the page. Click **Library**, then on **askwell-test-228** click **Re-index**, then
    **Re-index it**. Wait for **ready**. Click **Clarifications**. ☐

    **You should see:** **3 questions**: **RFQ**, still only once, and the two **Placed**
    questions naming **orders.xlsx** and **returns.xlsx**. An old folder does not ask about its
    documents again, and its workbooks are asked about.

---

## Result

| Part | Result | Notes |
| ---- | ------ | ----- |
| A — cold start and folder | | |
| B — both kinds asked (6 is the main check) | | |
| C — date answer reloads one workbook | | |
| D — re-index keeps the answer, no second question | | |
| E — one limit per folder | | |
| F — verify, abstention | | |
| G — upgrade from 0.9.15 (optional) | | |

Tester, date, browser, `cat VERSION`:

---

## Known gaps

These are deliberately not built, or belong to another ticket. Do not report them as defects of
this one.

- **A merged header still skips its sheet.** It loads no table and asks nothing. Out of scope.
- **A capped sheet question is never asked later**, even after the folder's waiting questions are
  answered. This is the same as every capped question (#249). It is recorded as
  `clarification_capped` with its workbook, and its column stays text.
- **The limit applies in loading order.** In a folder's first indexing, workbooks load before the
  folder's documents are scanned, so sheet questions take places first (Part E). This is
  recorded in `docs/decisions.md`.
- **A document question is not suppressed by a sheet's own notes, and a sheet question is not
  checked against Memory first.** For example, a folder where you already explained a `Placed`
  column elsewhere is still asked about this workbook's `Placed`. See the decision entry.
- **Only date questions reload the table.** Answering a sheet's mixed-number or blank-header
  question writes the answer to Memory, as a CSV's does. The table itself does not change.
- **Documents added to a folder after it was scanned are not scanned for questions.** That is
  incremental re-ingestion, and it is still open. A *workbook* added later is asked about when it
  loads.
- **A workbook indexed before `0.9.12` has no tables, so it asks nothing** until it is re-indexed
  (#850, `M11-FIX-ING-230`).
- **"Saved. Re-reading 2 tables."** The count is the number of answer buttons (#872).
- **Asterisks show in question text** (#873).
- **A table answer has no citation** (#857).
- **The Windows and macOS installers are not exercised here.** The code path is the same, and
  each platform's own walkthrough covers it.
