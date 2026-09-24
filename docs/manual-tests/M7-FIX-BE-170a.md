# Manual test — M7-FIX-BE-170a, a document's own date

**Ticket:** `M7-FIX-BE-170a`. Before this change, the only date Askwell kept for a document was
the date it was added. Two versions of a handbook added in the same minute got the same date, and
a 2024 file added after a 2026 file looked newer. Now each document gets its own date. It comes
from the file's metadata if the file has one, otherwise from a date in the file's name, otherwise
it is left empty. The date keeps its precision, so a year stays a year and is never shown as
1 January. Askwell also records where the date came from.

**Version under test:** `0.7.37`. Run `cat VERSION` and update this line if the version has moved on.

**Time:** about 40 minutes, most of it waiting for indexing.

**Who can run it:** anyone with a browser, a file manager and a terminal. Every Askwell screen is
reached by clicking from Askwell's front page. This ticket adds no new text to any screen. The
conflict card that shows the date is `M7-FIX-FE-170`. There are two ways to see this ticket's
work:

- **On screen:** when two sources disagree, Askwell now lists the newer document first. Before
  this change it listed the one added last first. Part A tests this by adding the newer file
  *first*, so the old ordering and the new ordering give different results.
- **In the browser's developer tools, and in clearly marked Terminal steps:** these show the
  date, precision and source Askwell recorded. No screen shows them yet, so the Terminal steps
  are the only place to read them. The Terminal steps only read data, except in Part C. Part C
  clears the dates first so that a re-index has to fill them in again.

**What is being checked.**

| Piece | File |
| ----- | ---- |
| The rules: metadata, then filename, then nothing; precision; future dates; plausible years | `api/src/askwell/document_date.py` |
| PDF `/ModDate` then `/CreationDate`, read from the PDF that extraction already has open | `api/src/askwell/extract_pdf.py` (`_metadata_date`) |
| Word, PowerPoint and Excel `docProps/core.xml`, modified before created; text files use the filename only | `api/src/askwell/extract.py` |
| The three columns and their consistency check | `api/src/askwell/db/models.py`, migration `d4a7e92b1f35` |
| `document_date`, `document_date_precision`, `document_date_source` beside `added_at` | `GET /documents/{id}` in `api/src/askwell/documents.py` |
| Order of conflicting source cards | `sortByDateAndSupersession` in `web/lib/document-dates.ts` |

> **Two known defects affect re-indexing. Do not report them against this ticket.**
>
> - Re-indexing a document that an answer has cited fails at the `chunk` stage (#719). This test
>   re-indexes only a source that nothing has cited (Part C), so you should not hit it.
> - A document with no `ingest_jobs` row stays **Queued** after a re-index (#720). Documents
>   added during this test all have that row.
>
> **A third defect affects navigation.** Once any source exists, no plain link opens **Add a
> source** (#712). This test reaches it through the offer under an abstention, as
> `docs/manual-tests/M7-QA-TEST-168.md` does.

---

## Before you start

1. Build both halves, start the stack and apply the migration:

   ```
   cd ~/external/quantum-plus/askwell
   scripts/dev.sh build-api
   scripts/dev.sh web-build
   podman compose up -d --force-recreate api worker
   scripts/dev.sh db upgrade head
   ```

   **You should see:** both builds finish with no red error text. Compose reports the containers
   as started. The migration output ends without an error. If it names `d4a7e92b1f35`, the new
   columns were just added. If it prints nothing, they were already there.

2. Open `.env` and find `ASKWELL_ROOTS_MOUNT`. That is the folder Askwell is allowed to read.
   Call it **the roots folder** below. Inside it, create three new folders: `dates-new`,
   `dates-old` and `dates-mixed`.

3. Copy files from the repository's `eval/fixtures/corpus/` folder into those folders with your
   file manager, renaming as shown. Every file in one folder must have different contents.
   Askwell keeps only one copy of identical content per source, so two renamed copies of the
   same PDF in one folder would test nothing.

   | Folder | File to create | Copied from / contents |
   | ------ | -------------- | ---------------------- |
   | `dates-new` | `store_hours_2026.pdf` | `store_hours_2026.pdf`, not renamed |
   | `dates-old` | `store_hours_2025.pdf` | `store_hours_2025.pdf`, not renamed |
   | `dates-mixed` | `spec_2026.docx` | `spec.docx`, renamed |
   | `dates-mixed` | `figures.xlsx` | `figures.xlsx`, not renamed |
   | `dates-mixed` | `report_1234.pdf` | `handbook_a.pdf`, renamed |
   | `dates-mixed` | `invoice_20500.pdf` | `handbook_b.pdf`, renamed |
   | `dates-mixed` | `notes.txt` | a new text file containing `Notes with no date anywhere.` |
   | `dates-mixed` | `minutes_2025_03.txt` | a new text file containing `March minutes.` |
   | `dates-mixed` | `minutes_2025-03_final_2025-03-14.txt` | a new text file containing `Minutes of the fourteenth.` |
   | `dates-mixed` | `budget_2024_vs_2025.txt` | a new text file containing `Two budgets compared.` |
   | `dates-mixed` | `budget_2025-26.txt` | a new text file containing `A financial year.` |
   | `dates-mixed` | `plan_2031.txt` | a new text file containing `A plan for the future.` |

   `spec.docx` is a useful test file because its properties say it was created and last saved
   on **23 December 2013**. That date comes from the template the fixture was generated from, not
   from anything real. It shows why the source field exists: file metadata is a claim, and here
   the claim is wrong.

4. **Start from nothing that repeats these files.** Open `http://127.0.0.1:8000`, click
   **Library** in the left rail, and read the list. If any source contains `store_hours_2025.pdf`
   or `store_hours_2026.pdf`, for example an earlier copy of `eval/fixtures/corpus`, it will add
   extra source cards in Part A. Delete that source with **Delete**, then **Delete it**. The
   confirmation says your original files are not touched. It is better to run this test on a
   test install.

---

## Part A — two versions, added in the wrong order

The newer file is added **first**, and the older file a minute later. Ordering by when files
were added would put the 2025 file on top. Ordering by the documents' own dates puts 2026 on top.

1. Open a **private or fresh-profile** browser window at `http://127.0.0.1:8000`. ☐

   **You should see:** either **Welcome to Askwell** or the **Ask** screen with **Ask**,
   **Library**, **Clarifications**, **Memory** and **Settings** in the left rail. If you see the
   welcome page, click **Skip setup** at its top right.

2. Reach **Add a source**. If the library is empty, the **Ask** screen shows **Nothing added
   yet** and an **Add a source** button. Click it. If the library is not empty, type
   `What was the population of Lisbon in 1900?` into Ask and press Enter. Wait for the
   **Not covered by your files** region, then click **Add a source** under it. ☐

   **You should see:** a page headed **Add a source** with a **Files** box containing
   **Choose files** and **Choose a folder**.

3. Click **Choose a folder** and choose `dates-new`. If the page asks **Which folder are these
   files in?**, type the full path to `dates-new`. ☐

   **You should see:** a card listing `store_hours_2026.pdf` that moves to queued.

4. Click **Library** in the rail. Wait until the `dates-new` source reads as indexed. ☐

   **You should see:** the source's row with one document and no **Needs attention** mark.
   **Wait at least one full minute after this** so that the two `added_at` times are clearly
   apart.

5. Add `dates-old` the same way as steps 2 and 3. Click **Ask** in the rail, ask the Lisbon
   question, and click **Add a source** under the answer. Choose `dates-old`. Click **Library**
   and wait until it reads as indexed. ☐

   **You should see:** two sources in the Library, `dates-new` and `dates-old`, each indexed.
   The 2025 file is now the one added most recently.

6. Open the browser's developer tools, go to the **Network** tab and clear it. Type
   `documents` into its filter box. Leave it open. ☐

7. Click **Ask** in the rail. Type `What time do Meridian Loom retail stores close on weekdays?`
   and press Enter. ☐

   **You should see:** an answer that states **both** closing times, 8 PM and 9 PM, each cited.
   The margin beside the answer has one card for each file, and each card has a date line that
   begins **Added**. That **Added** line means Askwell has treated this as a conflict. If the
   answer names only one time, or the cards have no **Added** line, the model did not flag a
   conflict and the card order is not being tested. Ask the same question again.

8. Look at the order of the two cards once they stop moving. They can swap once, within about a
   second, while the dates load. ☐

   **You should see:** `store_hours_2026.pdf` **above** `store_hours_2025.pdf`, even though the
   2025 file was added later. This is the core check. Before this version, 2025 was on top.

   Both cards still say **Added** with today's date. That is correct for this ticket. That line
   is when Askwell read the file, and it is labelled as that. Showing the document's own date on
   the card is `M7-FIX-FE-170`.

9. If the window is narrow and the cards appear **below** the answer, not in a margin beside it,
   check their order there too. Otherwise, make the window narrower until they move below the
   answer. ☐

   **You should see:** the same order, 2026 first. The cards below the answer and the cards in
   the margin must never disagree.

10. In the developer tools **Network** tab, click each request whose name is a long ID, for
    example `7f3c…`, and open its **Response** or **Preview**. There are two, one for each card. ☐

    **You should see**, for `store_hours_2026.pdf`:

    ```
    "added_at": "2026-09-24T…",
    "document_date": "2026",
    "document_date_precision": "year",
    "document_date_source": "filename",
    ```

    For `store_hours_2025.pdf`, you should see the same, but with `"2025"`. Check three things:

    - `document_date` is exactly `"2026"`. **It is not `"2026-01-01"`.** A year date must never
      leave Askwell as a full date.
    - `added_at` is today's date, and it is a separate field.
    - Neither file has a date in its metadata, so both dates come from the filename.

---

## Part B — metadata, filenames, and numbers that are not dates

1. Add `dates-mixed` the way you added `dates-old` in Part A step 5: ask the Lisbon question,
   click **Add a source**, then click **Choose a folder**. Click **Library** and wait until all
   ten files are indexed. ☐

   **You should see:** the `dates-mixed` source listing ten documents, none marked **Needs
   attention**. A file whose date could not be read must still index normally.

2. **Terminal — read the recorded dates.** No screen lists them, so read them from Askwell's
   database. This command only reads data:

   ```
   scripts/dev.sh psql -c "SELECT d.filename, d.document_date, d.document_date_precision AS precision, d.document_date_source AS source, d.added_at::date AS added FROM documents d JOIN sources s ON s.id = d.source_id WHERE s.root_path LIKE '%dates-%' AND d.deleted_at IS NULL ORDER BY d.filename"
   ```

   ☐

   **You should see** this table. Blank means empty (null):

   | filename | document_date | precision | source | Why |
   | -------- | ------------- | --------- | ------ | --- |
   | `budget_2024_vs_2025.txt` | | | | Two different years, equally specific. Askwell does not guess |
   | `budget_2025-26.txt` | | | | `2025-26` is a financial year, not a month. Month 26 does not exist |
   | `figures.xlsx` | `2026-08-28` | `day` | `metadata` | The spreadsheet's document properties |
   | `invoice_20500.pdf` | | | | `20500` is not a year |
   | `minutes_2025-03_final_2025-03-14.txt` | `2025-03-14` | `day` | `filename` | Two dates. The more specific wins |
   | `minutes_2025_03.txt` | `2025-03-01` | `month` | `filename` | Stored as the first of the month. The precision says only the month is real |
   | `notes.txt` | | | | Neither metadata nor a date in the name |
   | `plan_2031.txt` | | | | A year in the future is ignored |
   | `report_1234.pdf` | | | | 1234 is before 1900, so it is not treated as a year |
   | `spec_2026.docx` | `2013-12-23` | `day` | `metadata` | Metadata wins over the `2026` in the name, even when the metadata is wrong |
   | `store_hours_2025.pdf` | `2025-01-01` | `year` | `filename` | From Part A |
   | `store_hours_2026.pdf` | `2026-01-01` | `year` | `filename` | From Part A |

   The `added` column is today on every row. **No row's `document_date` may equal `added`
   unless the file itself says so.** On a day run, `figures.xlsx` says 28 August 2026, not today.
   A blank row that shows today's date would mean the ingest date was used as a fallback. That
   is the failure this ticket exists to prevent.

   `report_1234.pdf` and `invoice_20500.pdf` are blank only if `handbook_a.pdf` and
   `handbook_b.pdf` still have no `/Info` dates. If a regenerated fixture has gained them, those
   two rows show that date with source `metadata`. That is correct, and neither row shows `1234`
   or `20500` as a year.

3. **Terminal — confirm the database refuses a date with no precision.** ☐

   ```
   scripts/dev.sh psql -c "UPDATE documents SET document_date = '2026-01-01' WHERE filename = 'notes.txt'"
   ```

   **You should see:** an error naming the check `ck_documents_document_date_complete`, and `UPDATE 0` is
   **not** printed. Nothing changes. A date without a precision and a source cannot be stored.

---

## Part C — existing documents get a date on re-index

The ticket requires existing documents to be backfilled on re-index, with no fresh corpus. To
recreate a document indexed before this version, clear the three columns for `dates-mixed`, then
re-index it from the Library. Nothing in `dates-mixed` has been cited, so #719 does not apply.

1. **Terminal — clear the dates for `dates-mixed` only.** ☐

   ```
   scripts/dev.sh psql -c "UPDATE documents d SET document_date = NULL, document_date_precision = NULL, document_date_source = NULL FROM sources s WHERE s.id = d.source_id AND s.root_path LIKE '%dates-mixed%'"
   ```

   **You should see:** `UPDATE 10`. Run the Part B step 2 query again. The `dates-mixed` rows are
   all blank, and the two `store_hours` rows are unchanged.

2. In the browser, click **Library** in the rail. On the `dates-mixed` row, click **Re-index**. ☐

   **You should see:** the text "Re-index dates-mixed? Askwell reads every file in it again from
   scratch — extracting, chunking and embedding. …" with **Re-index it** and **Not now**.

3. Click **Re-index it**. ☐

   **You should see:** "Re-indexing 10 documents." The row's state changes, then reads indexed
   again. Nothing is marked **Needs attention**.

4. Run the Part B step 2 query again. ☐

   **You should see:** the `dates-mixed` rows match the Part B table again, with the same values
   and nulls. The dates were filled in by re-indexing, not left over from before.

---

## Part D — the migration reverses (optional, terminal only)

This removes the three columns and every recorded document date, then adds the columns back
empty. Run it only on a test install.

1. ☐

   ```
   scripts/dev.sh db downgrade -1
   scripts/dev.sh db upgrade head
   ```

   **You should see:** both commands finish without an error. Run the Part B step 2 query again.
   Every `document_date` is blank. **None** has been filled in from `added_at`. Re-index
   `dates-mixed` as in Part C to restore its dates.

2. In the browser, click **Ask** and ask the Part A store-hours question again. ☐

   **You should see:** both dates are now unknown, so the conflict cards stay in the order the
   answer cited them. Neither is placed first because it was added later. Re-index `dates-new`
   and `dates-old` to restore the Part A order. They have now been cited, so they may stop at
   **Needs attention** because of #719. Their dates are still written, because the date is
   recorded before the step that fails.

---

## What counts as a failure

- In Part A step 8, `store_hours_2025.pdf` appears above `store_hours_2026.pdf` after the cards
  settle.
- The cards below the answer and the cards in the margin are in different orders.
- `document_date` leaves the API as `"2026-01-01"` when its precision is `year`.
- A row whose `document_date` equals its `added_at` date when the file has neither metadata nor a
  date in its name.
- Any file in `dates-mixed` that fails to index or is marked **Needs attention** because of its
  name or metadata.
- A row in Part B that does not match the table, other than the fixture caveat for
  `report_1234.pdf` and `invoice_20500.pdf`.

## Known gaps — not defects in this ticket

- **No screen shows the document's own date.** The conflict card still says **Added …**. That
  is the ingest date, labelled as the ingest date. Showing the document's date, "Date unknown"
  for a null, and the year without a day for year precision all belong to `M7-FIX-FE-170`. The
  conflict state also still reads as one run-on sentence (#643).
- **Metadata is a claimed date.** `spec_2026.docx` in Part B is dated 2013 because its template
  says so. A PDF re-exported in 2026 from a 2019 original says 2026. The `source` field lets the
  interface say where a date came from. It does not make the date true. No user-editable date
  exists yet. The ticket leaves that for a later refinement.
- **Some edge cases cannot be produced by hand without tools.** These are a PDF with a real
  `/CreationDate` or `/ModDate`, a PDF whose `/CreationDate` is in the future, and a corrupt PDF
  `/Info` block or corrupt `docProps/core.xml`. The fixture corpus has no such file, and making
  one needs a PDF editor. They are covered by `api/tests/test_document_date.py` and
  `api/tests/test_document_date_records.py`, for example
  `test_a_pdf_with_a_creation_date_and_no_date_in_its_name_is_dated_from_metadata`,
  `test_a_future_pdf_creation_date_is_ignored_for_the_filename` and
  `test_a_corrupt_pdf_info_block_falls_through_and_never_fails_the_ingest`. If you have a real
  PDF with document properties, such as one printed to PDF from a word processor, put it in
  `dates-mixed` with no date in its name. It should show that day with source `metadata`.
- **Modified wins over created.** For a file that has both, the date shown is when it was last
  saved, not when it was first created. This is deliberate, and `docs/decisions.md` records why:
  resaving an old version is how a new version usually comes to exist.
- **Dates in the document's text are not read.** "As of January 2026" inside `conflict_2026.pdf`
  does not date that file. It still gets `2026` from its filename. Reading dates from text is
  out of scope.
- **Only three filename shapes are recognised.** These are `YYYY`, `YYYY-MM` and `YYYY-MM-DD`,
  with `-` or `_` used consistently. `24-09-2026`, `Sept 2026` and `20260924` are not read.
  This is conservative on purpose.
- **Documents indexed before this version have no date until their source is re-indexed.** For a
  source that has been cited, re-indexing currently stops at **Needs attention** (#719), although
  the date is still written. A document with no `ingest_jobs` row stays **Queued** (#720).
- **Reaching Add a source after the first source needs the abstention offer** (#712).
