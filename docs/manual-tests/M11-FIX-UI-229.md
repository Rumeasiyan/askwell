# Manual test — M11-FIX-UI-229, the library says when a workbook sheet was not loaded as a table, and why

**Ticket:** `M11-FIX-UI-229`, issue #849.

Since `M11-FIX-ING-224`, each sheet of a spreadsheet in a folder is also loaded as a table, so a
question the text cannot answer can be answered from the sheet. Some sheets do not load. A sheet
may have no clear header row, merged header cells, or nothing in it. Or the load may cross the
size or time limit that also guards database dumps. Before this ticket that was recorded where
nothing on screen reads it. The folder said **Ready**, and a spreadsheet question that could not be
answered gave no hint why.

Now:

1. **A sheet whose load failed puts the folder in *Needs attention*.** The detail names the
   workbook, the sheet and the reason, and says the workbook's text is still searched. There is
   no **Try again** button, because the document did not fail.
2. **A sheet that was skipped is a note under the folder, not a problem.** The note says why the
   sheet was skipped and, where it helps, what to change ("give it one header row"). The folder
   stays **Ready**.
3. **Fixing it clears it.** When the workbook is indexed again and loads, its attention reason and
   its note go away.

**Version under test:** `0.9.17`. Run `cat VERSION` and update this line if the version has moved
on.

**Time:** about 45 minutes.

**Who can run it:** anyone with a browser and a terminal on the build host. Every Askwell screen is
reached by clicking, starting from Askwell's front page. The terminal is used only to make the
test files, start Askwell, change the size limit (no screen can change it yet, #878), and read
things the interface does not show. Those steps are labelled **Stand-in**.

**What changed on disk.**

| Piece | File |
| ----- | ---- |
| Two new columns on a document: what the last sheet load failed on, and which sheets it skipped | `api/src/askwell/db/models.py`, migration `20260930_a3d9f6c2e814_document_sheet_load.py` |
| Every workbook load overwrites both columns, so a successful load clears them | `_store_outcome`, `load_workbook_tables`, `reload_source` in `api/src/askwell/table_load.py` |
| A failed sheet load counts towards the folder's *Needs attention*; the reason names each workbook | `source_status`, `coverage`, `_attention_reason`, `refresh_source`, `snapshot` in `api/src/askwell/ingest.py` |
| The library shows the failure in the attention detail and the skipped sheets as a note | `attentionCauses`, `sheetNotesFor` in `web/lib/library.ts`; `SheetNotes` in `web/components/library/library-screen.tsx` |

The reasoning, including why a skipped sheet is not attention, is in `docs/decisions.md`,
2026-09-30, "`M11-FIX-UI-229`".

---

## Read this first

**Nothing leaves this machine during this test.** No online AI, no web search.

**The size limit is shared.** The limit this test lowers also guards database dumps and CSV
files. Part E puts it back. If you stop part-way, run step 17 anyway, or every dump and CSV
import afterwards will fail.

**The limit is changed in the terminal, not in Settings.** No screen shows or changes it yet
(#878). Changing it in the terminal also skips the decisions record that changing it in the product
would write. That is expected in this test.

**The note under the folder is grey and small.** It is meant to be quiet. Look for it under the
**Kind · Added** line and the **All 4 indexed.** line, just above the **Re-index** and **Delete**
buttons.

---

## Before you start

> **Warning: the cold start below deletes everything this Askwell stack holds.** That means
> sources, memory, conversations, the audit log, settings and any stored provider key. Your
> original files are not touched. On the shared development machine, check first that nobody
> needs what the stack holds, and that no eval or build run is using the stack. If you are
> unsure, open **Settings → Your data → Export everything** first.

### 1. The test files (Stand-in)

Askwell can only read folders inside `ASKWELL_ROOTS_MOUNT` in `.env`. Check it:

```
cd ~/external/quantum-plus/askwell
grep ASKWELL_ROOTS_MOUNT .env
grep -c '^REDIS_\(API\|WORKER\|PROXY\)_PASSWORD=.' .env
```

**You should see:** a mount that contains `/tmp` (if it does not, set `ASKWELL_ROOTS_MOUNT=/tmp`),
then `3`.

The spreadsheets are made with a short script, run inside Askwell's own image. Save this as
`.run/make-229.py` in the repository folder (`.run/` is ignored by git):

```python
from pathlib import Path
import openpyxl

OUT = Path("/app/.run/m11-229")

SALES = [
    ["Department", "Q1 Revenue", "Headcount", "Avg Tenure Years"],
    ["Textiles", 482000, 34, 4.1],
    ["Logistics", 215000, 19, 2.7],
    ["Research", 903000, 27, 5.6],
]
# Numbers only: the first row reads as data, not as column names.
RAW = [[1, 2], [3, 4], [5, 6]]
# "group" spans A1:B1, so the first two columns have one name between them.
MERGED = [["group", "", "amount"], ["Anna", "x", 10], ["Ben", "y", 20]]
# 250 rows: the size limit is checked every 200 rows, so this crosses a check.
LONG = [["Item", "Amount"]] + [[f"item{i}", i] for i in range(250)]


def workbook(path: Path, sheets: dict[str, list[list[object]]], merge: dict[str, str] = {}) -> None:
    book = openpyxl.Workbook()
    for index, (title, rows) in enumerate(sheets.items()):
        sheet = book.active if index == 0 else book.create_sheet()
        sheet.title = title
        for row in rows:
            sheet.append(row)
        if title in merge:
            sheet.merge_cells(merge[title])
    path.parent.mkdir(parents=True, exist_ok=True)
    book.save(path)


main = OUT / "askwell-test-229"
workbook(
    main / "figures.xlsx",
    {"Sales": SALES, "Raw": RAW, "Merged": MERGED, "Blank": []},
    merge={"Merged": "A1:B1"},
)
workbook(main / "ledger.xlsx", {"Ledger": LONG})
workbook(main / "budget.xlsx", {"Budget": LONG})
(main / "notes.txt").write_text(
    "Office notes\n\nThe office opens at nine. Deliveries arrive on Tuesdays.\n"
)

# The same workbook with a header row on Raw. Merged and Blank are unchanged.
workbook(
    OUT / "figures-fixed.xlsx",
    {"Sales": SALES, "Raw": [["Low", "High"], *RAW], "Merged": MERGED, "Blank": []},
    merge={"Merged": "A1:B1"},
)
print(sorted(str(p.relative_to(OUT)) for p in OUT.rglob("*") if p.is_file()))
```

Then:

```
cd ~/external/quantum-plus/askwell
rm -rf .run/m11-229 /tmp/askwell-test-229 /tmp/figures-fixed.xlsx
scripts/dev.sh run python /app/.run/make-229.py
cp -r .run/m11-229/askwell-test-229 .run/m11-229/figures-fixed.xlsx /tmp/
ls /tmp/askwell-test-229
```

**You should see:** the script print five file names. Then `/tmp/askwell-test-229` holds
`budget.xlsx`, `figures.xlsx`, `ledger.xlsx` and `notes.txt`.

What each is for:

- `figures.xlsx` has one good sheet, **Sales**, and three that cannot become tables: **Raw** (no
  header row), **Merged** (a merged header cell) and **Blank** (empty). These are the *skipped*
  cases. They should give a note, not attention.
- `ledger.xlsx` and `budget.xlsx` each have one 250-row sheet. With the size limit lowered, both
  loads *fail*. Two failing workbooks show that the folder names both, not only the first.
- `notes.txt` is ordinary text, so the folder has a document that is not a spreadsheet.
- `figures-fixed.xlsx` is `figures.xlsx` with a header row added to **Raw**. It is used to show that
  fixing a sheet clears its note.

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
start, and the migration end without an error. The migration list includes `a3d9f6c2e814`.

In a **second** terminal, start the model on the host and leave it running:

```
cd ~/external/quantum-plus/askwell
scripts/dev.sh inference
```

**You should see:** the supervisor report the model and the embedding model ready.

### 3. Lower the size limit (Stand-in)

The limit's default is 5 GB, and no test file comes near it. Lower it to 1 KB so that any sheet
large enough to be checked fails:

```
cd ~/external/quantum-plus/askwell
scripts/dev.sh psql -c "INSERT INTO settings (key, value, updated_at)
  VALUES ('dump_size_cap_bytes', '1024', now())
  ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()"
scripts/dev.sh psql -tAc "SELECT value FROM settings WHERE key = 'dump_size_cap_bytes'"
```

**You should see:** `INSERT 0 1`, then `1024`.

The three small sheets of `figures.xlsx` are not affected. The limit is only checked once a sheet
has loaded 200 rows.

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

3. Click **Choose a folder**. In the folder picker, go to `/tmp`, select `askwell-test-229`, and
   confirm. If the browser asks whether to let the site see the files, allow it. ☐

   **You should see:** a card counting four files, and the question **Which folder is
   “askwell-test-229” in?** with an empty field and an **Add them** button.

4. Type `/tmp` in the field and click **Add them**. If a note says **Askwell has not been given
   this folder yet.** and offers a **Nominate …** button, click it, then click **Add them** again
   if the button is still there. ☐

   **You should see:** the card move on to recording four files, then **Queued**, then indexing
   progress. There should be no red **Not added** note.

5. Finish the welcome steps. Skipping optional steps is fine. Click **Library** in the left
   column. ☐

   **You should see:** a source named **askwell-test-229**. Wait until its line reads **All 4
   indexed.** This takes a few minutes on CPU.

## Part B — a failed sheet load needs attention

6. Look at the **askwell-test-229** row once it reads **All 4 indexed.** ☐

   **You should see:** the status at the right reads **Needs attention**, not **Ready**. All four
   files are indexed, and the folder still needs attention. **This is the ticket's main check.**
   Before `0.9.17` it read **Ready**.

   Below the line with the counts there is a **Show detail (2)** button.

7. Click **Show detail (2)**. ☐

   **You should see:** the button change to **Hide detail**, and two lines under it, in either
   order:

   - **ledger.xlsx: The sheet Ledger was not loaded as a table. Load aborted: loaded data reached
     *N* MB, over the size cap of 1.0 KB. Its text is still searched.**
   - **budget.xlsx: The sheet Budget was not loaded as a table. Load aborted: loaded data reached
     *N* MB, over the size cap of 1.0 KB. Its text is still searched.**

   *N* is a few megabytes. It is the size of the folder's whole sandbox database, not of the sheet.

   ☐ **You should not see:** a **Try again** button on either line. The documents did not fail,
   and retrying would hit the same limit. Nor should either line be red: these are shown in the
   quieter *inferred* colour.

   If only one of the two workbooks is named, that is this ticket's defect. The folder must name
   every workbook that failed.

8. At the top of the library, open the **Status** drop-down and choose **Needs attention**. ☐

   **You should see:** **askwell-test-229** still listed. Choose **Ready**: it disappears, with
   **No sources match these filters.** Set **Status** back to **All**.

9. **Stand-in.** The folder's stored reason names both workbooks. The library does not show this
   sentence, but other screens and the decisions store rely on it: ☐

   ```
   cd ~/external/quantum-plus/askwell
   scripts/dev.sh psql -tAc "SELECT status, last_error FROM sources WHERE name = 'askwell-test-229'"
   ```

   **You should see:** `attention|`, followed by one sentence per workbook, starting
   `budget.xlsx: the sheet Budget was not loaded as a table. Load aborted: …` and `ledger.xlsx:
   the sheet Ledger was not loaded as a table. Load aborted: …`. If only one workbook is named,
   the second failure did not update the reason. That is this ticket's defect.

10. **Stand-in.** The failed workbooks have no tables, and the good sheet does. All of them are in
    the folder's own sandbox database, not Askwell's (C3): ☐

    ```
    DB=$(scripts/dev.sh psql -tAc "SELECT sandbox_db FROM sources WHERE name = 'askwell-test-229'" | tr -d '[:space:]')
    echo "$DB"
    podman compose exec sandbox sh -c "psql -U \"\$POSTGRES_USER\" -d $DB -tAc \"
      SELECT table_name FROM information_schema.tables
      WHERE table_schema = 'public' ORDER BY table_name\""
    scripts/dev.sh psql -tAc "SELECT count(*) FROM information_schema.tables WHERE table_name LIKE '%xlsx%'"
    ```

    **You should see:** a database name (not `askwell`), then `figures_xlsx_sales` and **no**
    `ledger…` or `budget…` table, then `0`.

## Part C — skipped sheets are a note, not attention

11. In **Library**, look at the **askwell-test-229** row, under the counts line and above the
    **Re-index** and **Delete** buttons. ☐

    **You should see:** three short grey lines, one per skipped sheet of `figures.xlsx`:

    - **figures.xlsx: The sheet Raw was not loaded as a table: no recognisable header row: …**,
      ending **Its text is still searched; give it one header row to ask it as a table.** The
      words after *header row:* are Askwell's own reason and may vary;
    - **figures.xlsx: The sheet Merged was not loaded as a table: the header row has merged
      cells. Its text is still searched; give it one header row to ask it as a table.**
    - **figures.xlsx: The sheet Blank was not loaded as a table: the sheet is empty.** It gives
      no advice, because an empty sheet has nothing to fix.

    ☐ **You should not see:** a line about **Sales**, which loaded. The **Show detail (2)**
    count stays at 2: skipped sheets are never counted as attention.

    Before `0.9.17`, none of these lines existed.

## Part D — fixing it clears it

The ticket's edge case: a workbook indexed again successfully clears the note.

12. **Stand-in.** Put the size limit back to its default, and give **Raw** a header row on disk: ☐

    ```
    cd ~/external/quantum-plus/askwell
    scripts/dev.sh psql -c "DELETE FROM settings WHERE key = 'dump_size_cap_bytes'"
    cp /tmp/figures-fixed.xlsx /tmp/askwell-test-229/figures.xlsx
    ```

    **You should see:** `DELETE 1`. Removing the setting restores the 5 GB default.

13. Click **Library** again, or reload the page, and look at **askwell-test-229**. ☐

    **You should see:** it still reads **Needs attention**, with the same two lines under **Show
    detail (2)**. Changing the limit does not re-load anything by itself: the workbooks have to be
    indexed again.

14. On **askwell-test-229**, click **Re-index**. Read the confirmation and click **Re-index it**. ☐

    **You should see:** **Re-indexing 4 documents.** Wait until the line reads **All 4 indexed.**
    again.

15. Look at the **askwell-test-229** row. ☐

    **You should see:**
    - the status reads **Ready**;
    - no **Show detail** button;
    - two grey lines, for **Merged** and **Blank**, worded as in step 11;
    - **no** line for **Raw**. It has a header row now, so it loaded.

    If **Raw**'s line is still there, or a **Ledger** or **Budget** line remains, the note was not
    rewritten by the new load. That is this ticket's defect. If the status is still **Needs
    attention**, record what **Show detail** says.

16. **Stand-in.** The workbooks that failed now have their tables, and so does **Raw**: ☐

    ```
    podman compose exec sandbox sh -c "psql -U \"\$POSTGRES_USER\" -d $DB -tAc \"
      SELECT table_name FROM information_schema.tables
      WHERE table_schema = 'public' ORDER BY table_name\""
    scripts/dev.sh psql -tAc "SELECT status, last_error IS NULL FROM sources WHERE name = 'askwell-test-229'"
    ```

    **You should see:** `budget_xlsx_budget`, `figures_xlsx_raw`, `figures_xlsx_sales` and
    `ledger_xlsx_ledger`, then `ready|t`. If `$DB` is empty because this is a new terminal, set it
    again with the first line of step 10.

## Part E — clean-up and the rest of the product

17. **Stand-in.** Confirm the size limit is back to its default. This matters if you stopped
    early: ☐

    ```
    scripts/dev.sh psql -tAc "SELECT count(*) FROM settings WHERE key = 'dump_size_cap_bytes'"
    ```

    **You should see:** `0`. If it prints `1`, run the `DELETE` from step 12.

18. Click **Ask** in the left column. Type **What is the Amount for item42 in ledger.xlsx?** and
    press **Enter**. Wait for the answer. ☐

    **You should see:** an answer, or Askwell saying it cannot find this in your material, with no
    error. **This step does not pass or fail the ticket.** A question is only answered from a
    sheet's table when the passages come back weak (`M11-FIX-ING-224`), and a table answer has no
    citation yet (#857). Note what you saw.

19. **Stand-in.** The audit chains are still intact: ☐

    ```
    podman compose exec api askwell-verify
    ```

    **You should see:** every chain reported intact, exit status 0.

20. **Stand-in.** The load outcomes are still recorded in the decisions store, as before: ☐

    ```
    scripts/dev.sh psql -c "SELECT kind, count(*) FROM audit_decisions
      WHERE kind IN ('workbook_tables_loaded', 'workbook_tables_failed') GROUP BY kind ORDER BY kind"
    ```

    **You should see:** `workbook_tables_failed` with 2 (Part B) and `workbook_tables_loaded` with
    4 (`figures.xlsx` in Part B, all three workbooks in Part D).

---

## Result

| Part | Result | Notes |
| ---- | ------ | ----- |
| A — cold start and folder | | |
| B — failed load is attention (6 is the main check; 7 and 9 name both workbooks) | | |
| C — skipped sheets are a note | | |
| D — re-index after fixing clears both | | |
| E — clean-up, ask, verify, decisions | | |

Tester, date, browser, `cat VERSION`:

---

## Known gaps

These are deliberately not built, or belong to another ticket. Do not report them as defects of
this one.

- **No screen shows or changes the size or time limit** (#878). The failure line names the limit,
  but the only way to change it today is the terminal, as in this test. That is why the steps
  above lower and restore it by hand.
- **A large real sheet can fail the default time limit** (#862). Rows are inserted one at a time,
  so a sheet of about 100,000 rows does not finish within the default 10 minutes. With this ticket it shows as attention
  instead of silently, but it still fails.
- **The note is not on the Ask screen.** A spreadsheet question that abstains does not point at
  the library. The explanation is in **Library**, under the folder.
- **Documents are not listed one by one in the library.** The note and the attention line are
  shown on the folder's row and name the workbook, because the library has no per-document row.
- **No "Try again" for a failed sheet.** This is deliberate: retrying hits the same limit. The fix
  is the limit or the sheet, then **Re-index**.
- **A merged header, a sheet without a header row, and an empty sheet still load no table, and
  Askwell asks nothing about them.** This ticket only reports them. Loading them is out of scope.
- **A workbook indexed before workbook tables existed (`M11-FIX-ING-224`) has no tables and no
  note** until it is indexed again
  (#850, `M11-FIX-ING-230`).
- **Answering a sheet's date question reloads the workbook**, and that reload now updates the
  folder's attention too (`reload_source`). This walkthrough does not exercise that path. See
  `M11-FIX-ING-228` for how to raise a date question.
- **A table answer has no citation** (#857).
- **The Windows and macOS installers are not exercised here.** The code path is the same, and
  each platform's own walkthrough covers it.
