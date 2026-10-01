# Manual test — M11-FIX-BE-231, an answer from a workbook's sheet cites the workbook

**Ticket:** `M11-FIX-BE-231`, issue #857. Related: #896, #901, #904, #905, #906.

Since `M11-FIX-ING-224` (`0.9.12`), each sheet of a spreadsheet in a folder is also loaded as a
table. When a question's passages find nothing, Askwell tries the sheet's table instead, and the
answer shows a results table and its query. Until this ticket, that answer cited nothing. The
citation is the only check the person has (C4), so a right number with no source was still a gap.

Now:

1. **An answer from particular rows cites those rows.** Each row is its own source card in the
   margin. Opening one shows the workbook with that row highlighted.
2. **An answer from many rows at once cites the sheet, not a row.** This covers a total or a
   smallest-value question, a tie Askwell cannot settle, and an answer of more than ten rows.
3. **A row the answer did not return is never cited.** If two rows could have produced the
   answer and Askwell cannot tell which one did, the sheet is cited instead.
4. **If the table and the workbook disagree, nothing is cited.** The answer still shows. Askwell
   does not show a passage that contradicts it.
5. **Some sheet questions that used to say "Nothing in your files answers this" now answer.** The
   model sometimes wrote a stray tag before its reasoning, and the query that came after it was
   thrown away (#901).

**Version under test:** `0.9.24`. Run `cat VERSION` and update this line if the version has moved
on.

**Time:** about 60–75 minutes. Most of it is the cold start and indexing two spreadsheets on CPU.

**Who can run it:** anyone with a browser and a terminal on the build host. Every Askwell screen is
reached by clicking, starting from Askwell's front page. The terminal is used to make the test
files, to reset the stack, to change one table by hand for Part E, and to read what the screen does
not show. Those steps are labelled **Stand-in**.

**What changed on disk.**

| Piece | File |
| ----- | ---- |
| Which rows of a one-table read were returned: the query rewritten on its `sqlglot` tree to add the table's whole row, with no `ORDER BY`/`LIMIT` | `api/src/askwell/sql/provenance.py` |
| Rows matched to the workbook's `Sheet, row N` anchors and cited; the sheet cited when rows cannot be named; nothing when the live workbook no longer holds a row | `api/src/askwell/sheet_citations.py` |
| Which workbook and sheet a table holds, read from its comment and its `Loaded as table …` note | `workbook_tables`, `sheet_of_table`, `live_workbook` in `api/src/askwell/table_load.py` |
| The citations streamed to the screen and stored with the answer | `_run_sql_turn`, `_finish_sql_turn` in `api/src/askwell/ask.py` |
| A reasoning block after a stray tag is dropped, and a fenced query after a sentence is found | `_extract_query` in `api/src/askwell/agent/sql_generate.py` |
| Tests | `api/tests/test_sql_provenance.py`, `test_sheet_citations.py`, `test_sheet_citations_db.py`, `test_sql_generate.py` |

The reasoning, including why rows are found by a second read rather than by matching the answer's
values, is in `docs/decisions.md`, 2026-10-01, "`M11-FIX-BE-231`".

---

## Read this first

**Nothing leaves this machine during this test.** No online AI, no web search. If Askwell offers
to search the web after an abstention, do not accept it.

**A sheet is only ever a fallback.** Askwell searches the workbook's text first and reaches the
table only if that finds nothing. Which way a question goes depends on the model and cannot be
forced from the screen. Each step says how to tell which way it went:

- **Answered from the sheet:** while it runs, a step reads **Checking your connected
  databases.** When it finishes, the answer is one line starting **Found …**, with a results table
  under it and a **Show query** button. **This is the path this ticket changed.**
- **Answered from the text:** the answer is a normal sentence with no results table and no
  **Show query**. That path already cited its sources before this ticket.

If a step's question is answered from the text, write **text** in its box, ask it once more in
the same words, and if it still goes to the text, move on. That is #818, not a defect of this
ticket. Steps 13, 15 and 18 use the eval suite's own questions, which reached the sheet in the
recorded eval runs. Those are the main checks.

**Use a window at least 1,400 pixels wide.** At that width source cards appear in a column to the
right of the answer, called *the margin* below. On a narrower window the same cards appear under
the answer. Both are fine; the steps say "the margin" for either.

---

## Before you start

> **Warning: the cold start below deletes everything this Askwell stack holds.** That means
> sources, memory, conversations, the audit log, settings and any stored provider key. Your
> original files are not touched. On the shared development machine, check first that nobody
> needs what the stack holds, and that no eval or build queue is using the stack. If you are
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

The test folder holds two workbooks. `figures.xlsx` is the eval suite's own, copied unchanged.
`staff.xlsx` is made by a short script run inside Askwell's own image. Save this as
`.run/make-231.py` in the repository folder (`.run/` is ignored by git):

```python
from pathlib import Path

import openpyxl

OUT = Path("/app/.run/m11-231")

# Beta and Gamma tie on the smallest headcount. Alpha and Delta share a site.
TEAMS = [
    ["Team", "Headcount", "Site"],
    ["Alpha", 8, "Leeds"],
    ["Beta", 5, "York"],
    ["Gamma", 5, "Hull"],
    ["Delta", 11, "Leeds"],
]
# Twelve rows: more than the ten an answer cites one by one.
PARTS = [["Part", "Bin"]] + [[f"P-{n:02d}", f"B{n}"] for n in range(1, 13)]

book = openpyxl.Workbook()
teams = book.active
teams.title = "Teams"
for row in TEAMS:
    teams.append(row)
parts = book.create_sheet("Parts")
for row in PARTS:
    parts.append(row)
OUT.mkdir(parents=True, exist_ok=True)
book.save(OUT / "staff.xlsx")
print(sorted(p.name for p in OUT.iterdir()))
```

Then:

```
cd ~/external/quantum-plus/askwell
rm -rf .run/m11-231 /tmp/askwell-test-231
scripts/dev.sh run python /app/.run/make-231.py
mkdir -p /tmp/askwell-test-231
cp eval/fixtures/corpus/figures.xlsx .run/m11-231/staff.xlsx /tmp/askwell-test-231/
ls /tmp/askwell-test-231
```

**You should see:** the script print `['staff.xlsx']`, then `figures.xlsx  staff.xlsx`.

What is in them, so you can check answers by eye:

`figures.xlsx`, one sheet, **Quarterly Department Figures**:

| Row | Department | Q1 Revenue | Headcount | Avg Tenure Years |
| --- | ---------- | ---------- | --------- | ---------------- |
| 2 | Textiles | 482000 | 34 | 4.1 |
| 3 | Logistics | 215000 | 19 | 2.7 |
| 4 | Research | 903000 | 27 | 5.6 |
| 5 | Retail | 118000 | 41 | 1.9 |
| 6 | Design | 76000 | 12 | 3.3 |

`staff.xlsx`, two sheets. **Teams**: Alpha 8 Leeds (row 2), Beta 5 York (row 3), Gamma 5 Hull
(row 4), Delta 11 Leeds (row 5). **Parts**: `P-01` to `P-12`, in bins `B1` to `B12`.

### 2. Start from nothing (Stand-in)

```
cd ~/external/quantum-plus/askwell
cat VERSION
podman compose down -v
scripts/dev.sh build
scripts/dev.sh web-build
podman compose up -d
podman compose ps
```

**You should see:** `0.9.24` (or later), the volumes removed, both builds finish with no red error
text, and the containers listed as running or healthy, with `migrate` exited with code 0.

In a **second** terminal, start the model on the host and leave it running:

```
cd ~/external/quantum-plus/askwell
scripts/dev.sh inference
```

**You should see:** the supervisor report the model and the embedding model ready.

---

## Part A — first run and the spreadsheets

1. Open a **private or fresh-profile** browser window. Type `http://127.0.0.1:8000` in the
   address bar and press **Enter**. ☐

   **You should see:** the welcome screen, **Welcome to Askwell**, with a **Get started** button.
   If you see the **Ask** screen instead, the stack was not cleared. Go back to *Before you
   start*, step 2.

2. Click **Get started** and follow the steps until one offers to add material. Set a passphrase
   if asked, and write it down. ☐

   **You should see:** a step with an **Add a source** box, offering **Choose files** and
   **Choose a folder**.

3. Click **Choose a folder**. In the folder picker, go to `/tmp`, select `askwell-test-231`, and
   confirm. If the browser asks whether to let the site see the files, allow it. ☐

   **You should see:** a card counting two files, and the question **Which folder is
   “askwell-test-231” in?** with an empty field and an **Add them** button.

4. Type `/tmp` in the field and click **Add them**. If a note says **Askwell has not been given
   this folder yet.** and offers a **Nominate …** button, click it, then click **Add them** again
   if the button is still there. ☐

   **You should see:** the card move on to recording two files, then **Queued**, then indexing
   progress. There should be no red **Not added** note.

5. Finish the welcome steps. Skipping optional steps is fine. Click **Library** in the left
   column. ☐

   **You should see:** a source named **askwell-test-231**. Wait until it and both its files say
   **ready**. This takes a few minutes on CPU. The source reads **Ready**, not **Needs
   attention**, and there is no grey note under it saying a sheet was not loaded as a table.

6. Click **Memory** in the left column. Find the rows whose subject starts with **figures.xlsx:**
   or **staff.xlsx:**. ☐

   **You should see:** three table rows, each with no column name after the sheet:

   - **figures.xlsx:Quarterly Department Figures**, reading **Loaded as table `…`, 5 row(s), 4
     column(s).**
   - **staff.xlsx:Teams**, reading **Loaded as table `…`, 4 row(s), 3 column(s).**
   - **staff.xlsx:Parts**, reading **Loaded as table `…`, 12 row(s), 2 column(s).**

   **Write down the three table names** between the backticks. Part E uses the first. This is
   also what the ticket reads to know which sheet a table holds; if a row is missing, its sheet
   cannot be cited.

7. Click **Clarifications** in the left column. ☐

   **You should see:** no question about any column of these sheets. If there is one, leave it
   unanswered: answering it reloads that workbook's tables mid-test.

## Part B — before asking: a document answer still cites as before

8. Click **Ask** in the left column. In the box at the bottom, type **What was the Textiles
   department's Q1 revenue, per the department figures?** and press **Enter**. ☐

   **You should see:** an answer naming **482000** (or **482,000**). Note whether it came from
   the text or the sheet (see *Read this first*).

   - **From the text:** a sentence, with a card in the margin naming **figures.xlsx**.
   - **From the sheet:** **Found 1 row: …482000.**, a results table, **Show query**, and a card
     in the margin naming **figures.xlsx** — this ticket's change, checked in detail from step 9.

   ☐ **You should not see:** an answer with no card at all.

## Part C — one row, cited and opened

9. Type **How many people work in the Logistics department, per the department figures?** and
   press **Enter**. Watch the steps while it runs. ☐

   **You should see:** at some point the step **Checking your connected databases.** Then the
   answer **Found 1 row: headcount 19.** (the column name may be written differently), a results
   table with one cell, **19**, and a **Show query** button.

   This question reached the sheet in both recorded eval runs. If it answers from the text
   instead, record that and go on to step 15, which uses a second eval question.

10. Look at the margin. ☐

    **You should see:** exactly **one** card. Its top line reads **figures.xlsx · p. 3**. Under it,
    in quotation marks, a passage that contains **Logistics | 215000 | 19 | 2.7**. The passage
    may show the other departments' rows too; that is the whole passage the row is in.

    **This is the ticket's main check.** Before `0.9.24`, a sheet answer had no card.

    ☐ **You should not see:** a card for any other file, or more than one card. "p. 3" for a
    spreadsheet row is a known display gap (#905); the row itself is checked next.

11. Click **Show query**. ☐

    **You should see:** a `SELECT` reading from the table whose name you wrote down in step 6,
    with a filter on **Logistics**. A `LIMIT` may be highlighted; Askwell adds it to every query.

12. Click the card in the margin. ☐

    **You should see:** a page titled **figures.xlsx**, showing the sheet as a table, with the row
    **Logistics | 215000 | 19 | 2.7** highlighted. Under the table, the line **Quarterly Department
    Figures, row 3**. Beside it, a way back to the answer.

    The spreadsheet's row 3 is Logistics (see the table under *Before you start*). If a different
    row is highlighted, the citation points at a row the answer did not come from, which is the
    defect C4 rules out.

13. Click the way back to the answer, then type **How many people work in the Design department,
    per the department figures?** and press **Enter**. ☐

    **You should see:** **Found 1 row: headcount 12.**, a results table showing **12**, and one
    card, **figures.xlsx · p. 6**, whose passage contains **Design | 76000 | 12 | 3.3**. Clicking
    it highlights the **Design** row, labelled **Quarterly Department Figures, row 6**.

    **This is the second main check.** Before this ticket, this exact question said **Nothing in
    your files answers this.** in every run (#901): the model's query was thrown away.

14. Under the Design answer, click **How did you get this?** ☐

    **You should see:** a list of steps including **Nothing in your files — tried your tables**
    and **Queried your database — 1 row**. The answer was reached through the sheet, not the text.

15. Type **How many employees are in the Retail department, per the department figures?** and press
    **Enter**. ☐

    **You should see:** an answer naming **41**. Record whether it came from the text or the
    sheet.

    - **From the sheet:** one card, **figures.xlsx · p. 5**, passage containing **Retail | 118000 |
      41 | 1.9**.
    - **From the text:** in the recorded eval runs this question usually goes to the text. If the
      answer then has **no card at all**, that is #904 (a text answer with no marker is stored
      uncited), not this ticket. Record it.

## Part D — when no single row can be named

16. Type **Which teams in staff.xlsx are based at the Leeds site?** and press **Enter**. ☐

    **If it reached the sheet, you should see:** **Found 2 rows.**, a results table listing
    **Alpha** and **Delta**, and **two** cards in the margin, **staff.xlsx · p. 2** and
    **staff.xlsx · p. 5**. Clicking the first highlights **Alpha | 8 | Leeds**, labelled **Teams,
    row 2**; the second highlights **Delta | 11 | Leeds**, labelled **Teams, row 5**.

    ☐ **You should not see:** a card that opens on **Beta** or **Gamma**. They were not in the
    answer.

17. Type **What is the smallest headcount of any team in staff.xlsx?** and press **Enter**. ☐

    **If it reached the sheet, you should see:** an answer of **5**, a results table, and **one**
    card naming **staff.xlsx**. Its top line ends in a page *range* (such as **pp. 1–18**), not a
    single page: it cites the sheet.

    Click it. **You should see:** **staff.xlsx** open, with row 1, **Team | Headcount | Site**,
    highlighted, labelled **Teams, row 1**.

    **This is the tie check.** Beta and Gamma both have 5. Whether the query took the smallest
    value (a total-style answer) or one row ordered by headcount, Askwell cannot say which of the
    two rows the answer came from, so it must cite the sheet. ☐ **You should not see:** a card
    opening on **Beta** or on **Gamma**. Either would claim a row the answer did not name.

18. Type **What is the total headcount across all departments in the department figures?** and
    press **Enter**. ☐

    **If it reached the sheet, you should see:** **133** (34 + 19 + 27 + 41 + 12), a results table,
    and one card naming **figures.xlsx** with a page range. Opening it highlights the header row,
    **Department | Q1 Revenue | Headcount | Avg Tenure Years**, labelled **Quarterly Department
    Figures, row 1**.

    A total comes from every row, so the sheet is cited, not five rows. ☐ **You should not see:**
    five cards, one per department.

19. Type **List every part number in the Parts sheet of staff.xlsx.** and press **Enter**. ☐

    **If it reached the sheet, you should see:** **Found 12 rows.**, a results table of `P-01` to
    `P-12`, and **one** card naming **staff.xlsx** with
    a page range. Twelve rows is more than the ten Askwell cites one by one, so it cites the sheet.

    Click the card. **You should see:** **staff.xlsx** open with a header row highlighted. **At
    `0.9.24` this is the Teams header, Team | Headcount | Site, not the Parts header.** That is
    #906: the sheet citation lands on the start of the passage, which in a small workbook is the
    first sheet. Record what you see; it is not this ticket's defect.

    ☐ **You should not see:** twelve cards.

## Part E — the table and the workbook disagree

This covers the ticket's "re-indexed since its tables loaded" edge case. A real install reaches it
when a workbook is edited and only part of the reload succeeds; here the table is changed by hand,
which has the same effect: the table says one thing, the workbook another.

20. **Stand-in.** Change Logistics' headcount in the table only, not in the file: ☐

    ```
    cd ~/external/quantum-plus/askwell
    DB=$(scripts/dev.sh psql -tAc "SELECT sandbox_db FROM sources WHERE name = 'askwell-test-231'" | tr -d '[:space:]')
    T=<the figures.xlsx table name from step 6>
    podman compose exec sandbox sh -c "psql -U \"\$POSTGRES_USER\" -d $DB -tAc \"
      SELECT column_name FROM information_schema.columns WHERE table_name = '$T' ORDER BY ordinal_position\""
    ```

    **You should see:** four column names, such as `department`, `q1_revenue`, `headcount`,
    `avg_tenure_years`. Use the first and third in the next command if they differ:

    ```
    podman compose exec sandbox sh -c "psql -U \"\$POSTGRES_USER\" -d $DB -c \"
      UPDATE $T SET headcount = 20 WHERE department = 'Logistics'\""
    ```

    **You should see:** `UPDATE 1`.

21. In the browser, type **How many people work in the Logistics department, per the department
    figures?** again and press **Enter**. ☐

    **If it reached the sheet, you should see:** **Found 1 row: headcount 20.**, and **no card in
    the margin**.

    The workbook still says 19. A card would show a passage contradicting the answer, so none is
    shown. ☐ **You should not see:** a card for **figures.xlsx**, whether a row or the sheet.

    The answer itself, 20, is what the table holds; the mismatch is the point of this step.

22. **Stand-in.** Put the table back: ☐

    ```
    podman compose exec sandbox sh -c "psql -U \"\$POSTGRES_USER\" -d $DB -c \"
      UPDATE $T SET headcount = 19 WHERE department = 'Logistics'\""
    ```

    **You should see:** `UPDATE 1`.

23. Ask the Logistics question once more. ☐

    **You should see:** **19** again, with the single card **figures.xlsx · p. 3** from step 10.

## Part F — what was stored

24. **Stand-in.** The citations were stored with the answers, and each one quotes a row that
    answer returned (C4): ☐

    ```
    cd ~/external/quantum-plus/askwell
    scripts/dev.sh psql -tAc "SELECT left(u.content, 60), c.quoted_span
      FROM messages m
      JOIN messages u ON u.conversation_id = m.conversation_id AND u.role = 'user'
        AND u.created_at = (SELECT max(created_at) FROM messages
                            WHERE conversation_id = m.conversation_id AND role = 'user'
                              AND created_at < m.created_at)
      LEFT JOIN citations c ON c.message_id = m.id
      WHERE m.role = 'assistant' ORDER BY m.created_at"
    ```

    **You should see:** one line per answer, with the question on the left. Against each sheet
    answer:

    - Logistics (steps 9 and 23): `Logistics | 215000 | 19 | 2.7`.
    - Design (step 13): `Design | 76000 | 12 | 3.3`.
    - Leeds (step 16): two lines, `Alpha | 8 | Leeds` and `Delta | 11 | Leeds`.
    - Smallest headcount, total, parts (steps 17–19): one line each, with nothing after the `|`. A
      sheet citation has no quoted row.
    - Logistics at 20 (step 21): one line with nothing after the `|`, meaning no citation.

    ☐ **You should not see:** `Beta`, `Gamma`, or any row the answer's results table did not show.

25. **Stand-in.** The audit chains are still intact: ☐

    ```
    podman compose exec api askwell-verify
    ```

    **You should see:** every chain reported intact, exit status 0.

---

## Result

| Part | Result | Notes |
| ---- | ------ | ----- |
| A — first run, both workbooks loaded as three tables | | |
| B — a text answer still cites | | |
| C — one row cited and opened (10, 12); Design answers at all (13) | | |
| D — two rows (16); tie (17); total (18); more than ten (19) | | |
| E — table and workbook disagree: no card (21), restored (23) | | |
| F — stored citations quote only returned rows; audit chains intact | | |

Tester, date, browser, `cat VERSION`, and for each of steps 8, 9, 13, 15–19, 21 and 23 whether the
answer came from the **text** or the **sheet**:

---

## Known gaps

These are deliberately not built, or belong to another ticket. Do not report them as defects of
this one.

- **A sheet question often goes to the text, not the sheet** (#818). The sheet is tried only after
  the text finds nothing. A step answered from the text does not test this ticket; record it.
- **The card says "p. 3", not "Quarterly Department Figures, row 3"** (#905). The row's label
  appears in the viewer, under the table, not on the card. A spreadsheet has no pages; the number
  is the row's position in the workbook.
- **A sheet citation opens on the first sheet's header in a small workbook with several sheets**
  (#906), as step 19 shows. The card names the right file; the viewer lands on the wrong sheet.
- **The card's quote is the whole passage, not just the row.** The row is highlighted when the card
  is opened.
- **A text answer with no citation marker is stored with no citation** (#904). This is why
  `figures-retail-headcount-paraphrase` can still score 0.5 in the eval. It is the text path, not
  the sheet path.
- **Only folders' sheets are cited.** An imported database dump, CSV or live connection has no
  passages to cite, so its answers stay uncited, as before.
- **A date column loaded from a non-ISO cell** (such as `05/01/2024`, typed as a date after a
  clarification) does not match its row's text, and such a row is cited as nothing. So is a row
  with a cell containing ` | `. Recorded as accepted in `docs/decisions.md`.
- **"A sheet with no passage left"** and **"a workbook re-indexed since its tables loaded"** are
  covered by `api/tests/test_sheet_citations_db.py`. Neither can be reached from the screen without
  editing Askwell's own database; Part E covers the visible half (the table and workbook
  disagreeing).
- **Each cited sheet answer reads the sheet a second time**, through the same checks and the
  read-only role as the first. It is recorded in the audit log as its own query. That is
  intended, not a duplicate.
- **`grounded_qa.v1` is not part of this walkthrough.** Its before and after are in
  `docs/BRAIN.md`; a clean re-run on the final tree is #896.
- **The Windows and macOS installers are not exercised here.** The code path is the same, and each
  platform's own walkthrough covers it.
