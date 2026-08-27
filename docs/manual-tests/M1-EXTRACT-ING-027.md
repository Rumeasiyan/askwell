# Manual test — M1-EXTRACT-ING-027, Word, PowerPoint, spreadsheet, text, Markdown and HTML extraction

**Ticket:** `M1-EXTRACT-ING-027` — extract from six non-PDF formats, with a page-equivalent anchor per format
**Version under test:** `0.2.8`
**Time:** about 45 minutes, plus a first stack build
**Who can run it:** anyone who can paste a line into a terminal. Everything from "Nominate the folder" onward is clicking and reading in a browser.

**What is being checked.** A citation to "slide 12" or "sheet Budget, row 4" only means something if extraction produced that exact pointer. This walkthrough adds one file of each of the six formats this ticket covers, watches Askwell read every one, and confirms — against the database, because no screen shows extracted text or the source viewer yet (see **Known gaps**) — that the right `anchor_kind`, the right per-anchor label, and the right structural markers landed. It also adds a spreadsheet with nothing in it and confirms Askwell fails it with a reason rather than indexing it empty, and a Word document with a tracked change and confirms the presence of the revision is logged rather than silently absorbed.

**Where this stops on purpose.** Extraction is real as of this version, but the next stage — chunking, `M1-INDEX-ING-031` — is not, so nothing becomes searchable and no source reaches **Ready**. That is not a defect; see **Known gaps**, and the same note in `M1-EXTRACT-ING-026`'s manual test.

---

## Before you start

You need a terminal and Podman. You do not need Node, or Python on the host — `AGENTS.md` §5 says not to invoke the host's Python (it is 3.14; this project targets 3.12). Every fixture file below is instead built by the API image's own Python, which already carries `python-docx`, `python-pptx`, `openpyxl` and `beautifulsoup4` as real dependencies of the code under test — the same libraries `extract_docx.py`, `extract_pptx.py` and `extract_xlsx.py` import.

### 1. Build the API image, if you have not already

```bash
cd ~/external/quantum-plus/askwell
scripts/dev.sh build
```

**You should see:** a Podman build finishing with no red error text.

### 2. Generate seven test files, using the container's own Python

```bash
mkdir -p ~/askwell-test/material
scripts/dev.sh run python3 -c "
import docx
from docx.oxml.ns import qn
from pptx import Presentation
from pptx.util import Inches
import openpyxl

out = '.manual-test-fixtures'
import os
os.makedirs(out, exist_ok=True)

# 1. contract.docx — heading, list, table, an explicit page break (approximate
# page anchors), plus a paragraph after the break.
d = docx.Document()
d.add_heading('Renewal Terms', level=1)
d.add_paragraph('Either party may terminate on ninety days written notice.')
d.add_paragraph('First priority item', style='List Bullet')
d.add_paragraph('Second priority item', style='List Bullet')
t = d.add_table(rows=2, cols=2)
t.rows[0].cells[0].text = 'Item'; t.rows[0].cells[1].text = 'Price'
t.rows[1].cells[0].text = 'Widget'; t.rows[1].cells[1].text = '9.99'
d.add_page_break()
d.add_paragraph('Governing law is the law of the buyers principal place of business.')
d.save(f'{out}/contract.docx')

# 2. revisions.docx — one accepted tracked insertion. python-docx has no API
# for this, so the <w:ins> is built by hand, exactly as Word itself writes it.
r = docx.Document()
r.add_paragraph('Ordinary paragraph with no changes.')
p = r.add_paragraph()
ins = p._p.makeelement(qn('w:ins'), {qn('w:id'): '1', qn('w:author'): 'Reviewer'})
run = p.add_run('Inserted during review.')
run._r.getparent().remove(run._r)
ins.append(run._r)
p._p.append(ins)
r.save(f'{out}/revisions.docx')

# 3. deck.pptx — two slides, the first with speaker notes.
pres = Presentation()
s1 = pres.slides.add_slide(pres.slide_layouts[6])
box = s1.shapes.add_textbox(Inches(1), Inches(1), Inches(6), Inches(1))
box.text_frame.text = 'Quarterly results are ahead of forecast.'
s1.notes_slide.notes_text_frame.text = 'Mention the pricing change before questions.'
s2 = pres.slides.add_slide(pres.slide_layouts[6])
box2 = s2.shapes.add_textbox(Inches(1), Inches(1), Inches(6), Inches(1))
box2.text_frame.text = 'Next steps: renew the supply agreement by June.'
pres.save(f'{out}/deck.pptx')

# 4. figures.xlsx — two sheets, plus one merged range on the first (the
# 'handled crudely' known gap).
wb = openpyxl.Workbook()
budget = wb.active
budget.title = 'Budget'
budget.append(['Item', 'Cost'])
budget.append(['Widgets', 42])
budget.merge_cells('A4:B4')
budget['A4'] = 'Merged note spanning two columns'
notes = wb.create_sheet('Notes')
notes.append(['Remember to renew the lease.'])
wb.save(f'{out}/figures.xlsx')

# 5. blank.xlsx — a workbook with nothing in any cell, for the
# nothing-extractable failure path.
wb2 = openpyxl.Workbook()
wb2.save(f'{out}/blank.xlsx')

# 6. note.md — YAML front matter plus one heading.
with open(f'{out}/note.md', 'w') as f:
    f.write('---\ntitle: Renewal notice\nstatus: draft\n---\n')
    f.write('# Renewal\n\nEither party may terminate on ninety days written notice.\n')

# 7. note.txt — plain, no heading at all.
with open(f'{out}/note.txt', 'w') as f:
    f.write('Just a plain note about the renewal date, no structure at all.')

# 8. page.html — a saved-looking page: script, nav chrome, title, real content.
with open(f'{out}/page.html', 'w') as f:
    f.write('<html><head><title>Supply Agreement — internal copy</title>'
            '<script>console.log(1)</script></head><body>'
            '<nav><a href=\"/\">Home</a><a href=\"/about\">About</a></nav>'
            '<h1>Terms</h1><p>Either party may terminate on ninety days written notice.</p>'
            '</body></html>')

print('done')
"
```

**You should see:** the line `done` after the build finishes.

### 3. Move the fixtures out of the repository and into your material folder

```bash
mv api/.manual-test-fixtures/* ~/askwell-test/material/
rm -rf api/.manual-test-fixtures
ls ~/askwell-test/material
```

**You should see:** `blank.xlsx  contract.docx  deck.pptx  figures.xlsx  note.md  note.txt  page.html  revisions.docx` and a clean `git status` back in the repository (nothing new under `api/`).

| File | Format this ticket covers | What extraction should do with it |
| ---- | -------------------------- | ---------------------------------- |
| `contract.docx` | Word | Heading as `# Renewal Terms`, bullets as `- …`, table as `[TABLE]…[/TABLE]`, an explicit page break splitting it into two approximate "pages" |
| `revisions.docx` | Word, tracked-changes edge case | Accepted text only; the presence of the insertion is logged, not injected into the text |
| `deck.pptx` | PowerPoint | One anchor per slide, labelled "Slide 1" / "Slide 2"; slide 1's speaker notes included and labelled `[Speaker notes]` |
| `figures.xlsx` | Excel, document-style | One anchor per non-empty row, labelled `<sheet>, row <n>`, across both sheets; the merged cell logged as a known gap |
| `blank.xlsx` | Excel, empty-document edge case | No anchor has any text at all → the document fails with a reason |
| `note.md` | Markdown | Front matter excluded; one anchor labelled "Renewal" |
| `note.txt` | Plain text | One anchor, no label — nothing to anchor to more specifically |
| `page.html` | HTML | `<script>`, `<nav>` and `<title>` discarded; one anchor labelled "Terms" |

### 4. Point Askwell at your files

```bash
cp -n .env.example .env
```

Open `.env` in any text editor. Find `ASKWELL_ROOTS_MOUNT=` and set it — replacing `you` with your own username:

```
ASKWELL_ROOTS_MOUNT=/home/you/askwell-test/material
```

Find `POSTGRES_APP_PASSWORD` and put any word after the `=` if it is blank.

---

## Cold start

### 5. Remove any previous state

```bash
podman compose down -v
```

**You should see:** lines about containers and volumes being removed, or a note that there was nothing to remove.

### 6. Build the interface

```bash
scripts/dev.sh web-build
```

**You should see:** a Next.js build finishing with a route list and no red error text.

### 7. Run the checks

```bash
scripts/dev.sh check
```

**You should see:** lint, format, typecheck and test stages finish without red error text. This exercises the new `test_extract_docx.py`, `test_extract_pptx.py`, `test_extract_xlsx.py`, `test_extract_text.py` and `test_extract_office_records.py` without a database — the same structural rules (heading prefixes, table markers, speaker-note labelling, front-matter stripping, chrome discarding) this walkthrough checks by hand next.

### 8. Bring the stack up

```bash
podman compose up -d
```

**You should see:** `postgres`, `redis`, `egress-proxy`, `api`, `worker` reported as started. Wait about thirty seconds.

### 9. Create the database tables

```bash
scripts/dev.sh db upgrade head
```

**You should see:** migration lines, including one mentioning `extraction_anchors` or `anchor_kind`.

### 10. Nominate the folder your material is in

Open a browser at:

```
http://127.0.0.1:8000
```

Click **Settings** in the left strip, scroll to **Folders Askwell may read**, type this into the **Nominate a folder** field — with your own username —

```
/home/you/askwell-test/material
```

— and click **Nominate**.

**You should see:** a box appear showing that path, marked **Readable**.

---

## Add all seven files and watch extraction run

### 11. Get to the add screen by clicking

Click **Ask** in the left strip.

**You should see:** the "Ask your own material" page, with an **Add a source** button.

Click **Add a source**.

**You should see:** the "Add a source" page, address bar ending in `/sources/add/`.

### 12. Drop all seven files at once

Open your file manager at `~/askwell-test/material`. Select all eight files (`Ctrl+A`) and drag them onto the window together.

**You should see:** eight cards, each moving through **Detecting** to **Where are these?**, correctly describing each one's kind — "a Word document" for the two `.docx` files, "a PowerPoint presentation" for `deck.pptx`, "a spreadsheet" for the two `.xlsx` files, "a Markdown document" for `note.md`, "plain text" for `note.txt`, "an HTML page" for `page.html`.

Type the folder, with your own username, and click **Add them**:

```
/home/you/askwell-test/material
```

**You should see:** the phase change to **Queued**, and under the queued note a live line describing the queue.

### 13. Watch the line settle

**You should then see:** the live line settle on wording close to: *"7 files are recorded and waiting. Nothing is searchable yet: reading them needs chunk, which is not built yet (M1-INDEX-ING-031). Nothing has been copied."* — seven, not eight: `blank.xlsx` fails extraction outright and is not among the "recorded and waiting" count (confirmed against the database in step 18).

That wording naming **chunk** is the same signal `M1-EXTRACT-ING-026`'s walkthrough checks: extraction ran and the pipeline moved past it, to the next stage that does not exist yet.

---

## Confirm each format landed correctly

### 14. Open a database shell

```bash
scripts/dev.sh psql
```

### 15. Word — headings, list, table, approximate pages

```sql
SELECT id, anchor_kind, page_count, status FROM documents WHERE filename = 'contract.docx';
```

**You should see:** `anchor_kind` = `page`, `page_count` = `2`, `status` = `queued` (not `ready` — chunking has not run).

```sql
SELECT page_number, anchor_label, left(text, 80) FROM document_pages WHERE document_id = (SELECT id FROM documents WHERE filename = 'contract.docx') ORDER BY page_number;
```

**You should see:** two rows. Row 1's `anchor_label` reads `page 1 (approximate)`, its text begins `# Renewal Terms`, and further down the same text contains `- First priority item` and `[TABLE]`. Row 2's `anchor_label` reads `page 2 (approximate)`, its text is the governing-law paragraph. "Approximate" appearing in both labels is deliberate — the ticket's own assumption is that Word pagination here is honest about not being a true page number.

### 16. Word — tracked changes noted, not injected

```sql
SELECT left(text, 80) FROM document_pages WHERE document_id = (SELECT id FROM documents WHERE filename = 'revisions.docx');
```

**You should see:** text containing both `Ordinary paragraph with no changes.` and `Inserted during review.`, with no editorial mark such as `[INSERTED]` around the second sentence — the accepted text, exactly as the ticket's edge case asks, with no invented annotation in the passage itself.

```bash
podman compose logs api worker | grep extract_docx_completed | grep revisions.docx
```

**You should see:** a JSON line naming `revisions.docx` with `has_revisions` equal to `true` — the presence of the tracked change recorded as a fact about the document, separately from the text. Run the same grep for `contract.docx` and confirm `has_revisions` is `false` there.

### 17. PowerPoint — one anchor per slide, notes labelled

```sql
SELECT id, anchor_kind, page_count FROM documents WHERE filename = 'deck.pptx';
```

**You should see:** `anchor_kind` = `slide`, `page_count` = `2`.

```sql
SELECT page_number, anchor_label, text FROM document_pages WHERE document_id = (SELECT id FROM documents WHERE filename = 'deck.pptx') ORDER BY page_number;
```

**You should see:** row 1 labelled `Slide 1`, its text containing `Quarterly results are ahead of forecast.`, `[Speaker notes]`, and `Mention the pricing change before questions.` on separate lines. Row 2 labelled `Slide 2`, text `Next steps: renew the supply agreement by June.`, with no `[Speaker notes]` block — slide 2 has none.

### 18. Excel — one row per anchor, across sheets, and the empty workbook failing

```sql
SELECT id, anchor_kind, page_count, status FROM documents WHERE filename = 'figures.xlsx';
```

**You should see:** `anchor_kind` = `sheet_row`, `page_count` = `4` (two data rows plus the merged-cell row on `Budget`, plus one row on `Notes`), `status` = `queued`.

```sql
SELECT anchor_label, text FROM document_pages WHERE document_id = (SELECT id FROM documents WHERE filename = 'figures.xlsx') ORDER BY page_number;
```

**You should see:** four rows labelled `Budget, row 1` (`Item | Cost`), `Budget, row 2` (`Widgets | 42`), `Budget, row 4` (the merged note — row 3 is absent because it was empty and rows are numbered by their real position in the sheet, not renumbered), and `Notes, row 1`.

```bash
podman compose logs api worker | grep extract_xlsx_completed | grep figures.xlsx
```

**You should see:** a JSON line with `merged_ranges` equal to `1` — the merged cell logged as a known gap, per the ticket's own out-of-scope note, rather than silently producing a wrong or duplicated value.

Now the empty workbook:

```sql
SELECT status FROM documents WHERE filename = 'blank.xlsx';
SELECT error FROM ingest_jobs WHERE document_id = (SELECT id FROM documents WHERE filename = 'blank.xlsx');
```

**You should see:** `status` is not `ready` (it should read `failed`), and `error` contains wording close to *"could not find any text"* — this is the ticket's own validation rule: a document yielding no text at all is a failure with a reason, never an empty indexed document. Confirm the same thing in the browser: back on `/sources/add/`, `blank.xlsx`'s card should show a failed state with that reason visible, not silently vanish from the list.

### 19. Markdown — front matter excluded

```sql
SELECT anchor_kind, page_count FROM documents WHERE filename = 'note.md';
SELECT anchor_label, text FROM document_pages WHERE document_id = (SELECT id FROM documents WHERE filename = 'note.md');
```

**You should see:** `anchor_kind` = `heading`, one row labelled `Renewal`, whose text contains `Either party may terminate` but does **not** contain `title: Renewal notice` or `status: draft` — the front matter treated as metadata, not prose, exactly as the ticket's edge case states.

### 20. Plain text — one anchor, no label

```sql
SELECT anchor_kind, page_count FROM documents WHERE filename = 'note.txt';
SELECT anchor_label, text FROM document_pages WHERE document_id = (SELECT id FROM documents WHERE filename = 'note.txt');
```

**You should see:** `anchor_kind` = `heading`, one row, `anchor_label` is `NULL`, text is the full sentence you wrote into the file — a plain file has nothing more specific to anchor to, and the label says so by being absent rather than inventing one.

### 21. HTML — chrome discarded, real content kept

```sql
SELECT anchor_kind FROM documents WHERE filename = 'page.html';
SELECT anchor_label, text FROM document_pages WHERE document_id = (SELECT id FROM documents WHERE filename = 'page.html');
```

**You should see:** `anchor_kind` = `heading`, one row labelled `Terms`, text containing `Either party may terminate on ninety days written notice.` and **not** containing `Home`, `About`, `console.log`, or `Supply Agreement — internal copy` (the `<title>`) — confirming the ticket's own extra scenario: an HTML page saved from a browser has its navigation chrome and metadata discarded, keeping only what a reader actually sees.

Leave `psql` open or type `\q` to exit — either is fine for what follows.

---

## What the logs recorded

### 22. Confirm extraction outcome is logged per document, for every format

```bash
podman compose logs api worker | grep -E "extract_docx_completed|extract_pptx_completed|extract_xlsx_completed|extract_text_completed"
```

**You should see:** one JSON line per document you added (seven successful ones — `blank.xlsx` fails before this log line, its outcome is the `error` column you already read in step 18), each naming the `document_id` and `filename`. This is the "extraction outcome per document is logged" requirement, for every format this ticket adds.

---

## Tidy up

```bash
rm -rf ~/askwell-test
podman compose down -v
```

Then blank the `ASKWELL_ROOTS_MOUNT=` line in `.env` if you do not want to keep it.

---

## Known gaps

These are deliberately not built, or already recorded elsewhere. Do not report them as defects.

1. **No screen shows a document's extracted text or renders it structurally.** The source viewer (`docs/ux/source-viewer.md` §2, "Converted text with structure preserved, heading anchored") is `M1-VIEW-FE-046` and later work — the same gap `M1-EXTRACT-ING-026`'s manual test already records for PDF. Steps 15–21 above check the same facts directly against Postgres instead.
2. **Nothing is searchable and no source reaches `ready`** except `blank.xlsx`, which fails outright. Chunking (`M1-INDEX-ING-031`) and embedding (`M1-INDEX-ING-032`) are still declared but not installed, so every other document in this walkthrough parks at `chunk` and stays `queued`. This is `M1-ADD-ING-025`'s documented pipeline shape, not a regression.
3. **Legacy binary Office (`.doc`, `.xls`, `.ppt`) is not exercised here.** It is covered by an automated test instead (`test_a_legacy_binary_word_file_fails_by_name_rather_than_crashing`, `api/tests/test_extract_office_records.py`) and is a named, tracked gap — issue #121 — not something this ticket builds.
4. **Multi-sheet and merged-cell semantics beyond what is logged are out of scope**, per the ticket's own text and `docs/data-sources.md` §8. Step 18 confirms the merge is *logged*, not that it is resolved into a correct value — resolving it is future work, not this ticket's.
5. **The "queued vs parked-for-OCR" wording gap** noted in `M1-EXTRACT-ING-026`'s manual test (issue #118) does not apply here — none of these seven formats is ever parked for OCR, so the ambiguous sentence never appears for them.
6. **The exact `page_count` for `figures.xlsx` in step 18 depends on `openpyxl` reading the merged range's stored row as non-empty**, which is what the module's own docstring says happens (the value lives in the top-left cell). If your local run shows `page_count = 3` instead of `4`, treat that as a signal the merge landed differently rather than assuming the number `4` above is load-bearing — check `anchor_label`s for `Budget, row 4` specifically before concluding anything is wrong.
