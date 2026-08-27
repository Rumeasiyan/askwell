# Manual test — M1-INDEX-ING-031, structure-aware chunking

**Ticket:** `M1-INDEX-ING-031` — chunking respects headings, table boundaries and list items rather than cutting at a fixed length
**Version under test:** `0.2.12`
**Time:** about 40 minutes, plus a first stack build
**Who can run it:** anyone who can paste a line into a terminal. Everything from step 9 onward is clicking and reading in a browser; steps after that read the database, because there is no source viewer yet (see **Known gaps**).

**What is being checked.** `api/src/askwell/chunk.py` reads the headings, `[TABLE]`/`[/TABLE]` markers and list items the extractors already leave in `document_pages.text` and turns them into `chunks` rows without ever splitting a table row from its header, without duplicating a heading into every chunk's content, and without letting any chunk cross the hard maximum. Four fixtures cover the ticket's own edge cases: a table longer than the maximum (split with the header repeated), a nested list (kept together while it fits), a document with no headings at all (split at sentence boundaries), and a slide deck (one chunk per slide).

**Where this stops on purpose.** Embedding (`M1-INDEX-ING-032`) is still not built, so a document still parks at `embed` and never reaches `status = 'ready'` — chunking runs for real underneath that, and this walkthrough confirms it by reading the `chunks` table directly, not by asking a question. See **Known gaps**.

---

## Before you start

You need a terminal and Podman. All four fixtures are built by a Python script run **inside the API container image** — `python-docx` and `python-pptx` are already there for `extract_docx`/`extract_pptx`, and `AGENTS.md` says not to invoke the host's Python.

### 1. Build the test files

```
cd ~/external/quantum-plus/askwell
mkdir -p askwell-test-material
```

```bash
scripts/dev.sh run python3 - <<'PY'
from docx import Document
from pptx import Presentation
from pptx.util import Inches

OUT = "/app/askwell-test-material"

# --- rate-table.docx: a heading, then a table well over the 2,400-character
# hard maximum, so it must split by row with the header repeated on every
# part rather than cut through a row.
doc = Document()
doc.add_heading("Quarterly Rate Table", level=1)
table = doc.add_table(rows=1, cols=2)
table.rows[0].cells[0].text = "Plan"
table.rows[0].cells[1].text = "Monthly Rate"
for n in range(80):
    row = table.add_row()
    row.cells[0].text = f"Plan tier number {n}"
    row.cells[1].text = f"${99 + n}.99 per month, billed annually"
doc.save(f"{OUT}/rate-table.docx")

# --- renewal-steps.docx: a heading, then a small nested list that must stay
# in one chunk rather than being split mid-item.
doc = Document()
doc.add_heading("Renewal Steps", level=1)
doc.add_paragraph("Give notice in writing.", style="List Bullet")
doc.add_paragraph("Confirm the renewal price in writing.", style="List Bullet")
doc.add_paragraph("Sign the renewal within thirty days.", style="List Bullet")
doc.save(f"{OUT}/renewal-steps.docx")

# --- heading-free.txt: no headings at all, long enough that it must be
# split at sentence boundaries rather than mid-sentence.
sentence = "Either party may terminate this agreement on ninety days written notice. "
with open(f"{OUT}/heading-free.txt", "w") as f:
    f.write(sentence * 100)

# --- board-update.pptx: two short slides, which must land as two chunks,
# one per slide, even though both together are well under the target size.
pres = Presentation()
layout = pres.slide_layouts[1]
slide1 = pres.slides.add_slide(layout)
slide1.shapes.title.text = "Quarterly results are ahead of forecast."
slide2 = pres.slides.add_slide(layout)
slide2.shapes.title.text = "Next steps for the roadmap."
pres.save(f"{OUT}/board-update.pptx")

print("done")
PY
```

**You should see:** the script print `done` with no traceback.

```
ls -la askwell-test-material
```

**You should see:** four files: `rate-table.docx`, `renewal-steps.docx`, `heading-free.txt`, `board-update.pptx`.

| File | What it is for | What should happen |
| ---- | --------------- | ------------------- |
| `rate-table.docx` | A table with 81 rows, well over the 2,400-character hard maximum | Split into several chunks, each starting `[TABLE]` with the `Plan \| Monthly Rate` header row repeated, all sharing the heading `Quarterly Rate Table` |
| `renewal-steps.docx` | A short nested list under one heading | One chunk, heading `Renewal Steps`, all three steps present |
| `heading-free.txt` | ~7,300 characters of repeated prose, no heading at all | Several chunks, `heading` null on every one, each ending on a sentence boundary, none over 2,400 characters |
| `board-update.pptx` | Two short slides | Two chunks, one per slide, `page_from = page_to` on each |

### 2. Point Askwell at your files

If you have never run Askwell before:

```
cp -n .env.example .env
```

Open `.env`. Find `ASKWELL_ROOTS_MOUNT=` and set it to the folder you just created, with your own path:

```
ASKWELL_ROOTS_MOUNT=/home/you/external/quantum-plus/askwell/askwell-test-material
```

Find `POSTGRES_APP_PASSWORD` and put any word after the `=` if it is blank.

---

## Cold start

### 3. Remove any previous state

```
podman compose down -v
```

**You should see:** lines about containers and volumes being removed, or a note that there was nothing to remove.

### 4. Build the interface

```
scripts/dev.sh web-build
```

**You should see:** a Next.js build finishing with a route list and no red error text.

### 5. Run the checks

```
scripts/dev.sh check
```

**You should see:** lint, format, typecheck and test stages finish without red error text — including `api/tests/test_chunk.py` and `api/tests/test_chunk_records.py`.

### 6. Bring the stack up

```
podman compose up -d
```

**You should see:** `postgres`, `redis`, `egress-proxy`, `api`, `worker` reported as started. Wait about thirty seconds.

### 7. Create the database tables

```
scripts/dev.sh db upgrade head
```

**You should see:** migration lines finish with no error.

### 8. Nominate the folder your material is in

Open a browser at:

```
http://127.0.0.1:8000
```

Click **Settings** in the left strip, scroll to **Folders Askwell may read**, type this into the **Nominate a folder** field — with your own path —

```
/home/you/external/quantum-plus/askwell/askwell-test-material
```

— and click **Nominate**.

**You should see:** a box appear showing that path, marked **Readable**.

---

## Add the four files and watch the pipeline park honestly

### 9. Get to the add screen by clicking

Click **Ask** in the left strip.

**You should see:** the "Ask your own material" page, with an **Add a source** button.

Click **Add a source**.

**You should see:** the "Add a source" page, address bar ending in `/sources/add/`.

### 10. Drop all four files

Open your file manager at `~/external/quantum-plus/askwell/askwell-test-material`. Select all four files, drag them onto the window and release, type the folder with your own path when asked, and click **Add them**.

**You should see:** the cards move to **Queued**, then the live line settle on wording close to: *"4 files are recorded and waiting. Nothing is searchable yet: reading them needs embed, which is not built yet (M1-INDEX-ING-032). Nothing has been copied."*

This is the honest state this ticket lands in: chunking has already run underneath that sentence — the rest of this walkthrough confirms it in the database — but the pipeline still parks one stage later, at embedding, so nothing is `ready` yet.

---

## The table — never split from its header

### 11. Read the chunks for `rate-table.docx`

```
scripts/dev.sh psql
```

```sql
SELECT ordinal, page_from, page_to, heading, length(content), left(content, 40)
FROM chunks
WHERE document_id = (SELECT id FROM documents WHERE filename = 'rate-table.docx')
ORDER BY ordinal;
```

**You should see:** more than one row (the 81-row table alone is over 2,400 characters), every row's `heading` reading `Quarterly Rate Table`, and every row's `content` beginning with `[TABLE]\nPlan | Monthly Rate` — the header repeated on every part, not just the first.

```sql
SELECT count(*) FROM chunks
WHERE document_id = (SELECT id FROM documents WHERE filename = 'rate-table.docx')
  AND length(content) > 2400;
```

**You should see:** `0` — no chunk crosses the hard maximum, even for a table this size.

Confirm no row is lost across the split — every plan tier appears exactly once across all chunks:

```sql
SELECT string_agg(content, '') FROM chunks
WHERE document_id = (SELECT id FROM documents WHERE filename = 'rate-table.docx');
```

**You should see:** `Plan tier number 0` through `Plan tier number 79` each appear once in the concatenated text (scan visually, or `grep -c` the psql output for `Plan tier number`).

---

## The nested list — kept together

### 12. Read the chunk for `renewal-steps.docx`

```sql
SELECT ordinal, heading, content FROM chunks
WHERE document_id = (SELECT id FROM documents WHERE filename = 'renewal-steps.docx')
ORDER BY ordinal;
```

**You should see:** exactly one row, `heading` reading `Renewal Steps`, and `content` containing all three steps (`Give notice in writing.`, `Confirm the renewal price in writing.`, `Sign the renewal within thirty days.`) — the list was never split mid-item, and the heading text itself does not appear a second time inside `content`.

---

## A heading-free document — split at sentence boundaries

### 13. Read the chunks for `heading-free.txt`

```sql
SELECT ordinal, heading, length(content), right(content, 20) FROM chunks
WHERE document_id = (SELECT id FROM documents WHERE filename = 'heading-free.txt')
ORDER BY ordinal;
```

**You should see:** several rows, `heading` **null** on every one (there was never a heading to carry), every `length(content)` at or under 2,400, and every `content` ending on a full stop (`right(content, 20)` should end in `notice.` or similar) rather than partway through a sentence.

### 14. Confirm no chunk exceeds the hard maximum here either

```sql
SELECT count(*) FROM chunks
WHERE document_id = (SELECT id FROM documents WHERE filename = 'heading-free.txt')
  AND length(content) > 2400;
```

**You should see:** `0`.

---

## A slide deck — one chunk per slide

### 15. Read the chunks for `board-update.pptx`

```sql
SELECT ordinal, page_from, page_to, content FROM chunks
WHERE document_id = (SELECT id FROM documents WHERE filename = 'board-update.pptx')
ORDER BY ordinal;
```

**You should see:** exactly two rows — one containing `Quarterly results are ahead of forecast.` with `page_from = page_to = 1`, one containing `Next steps for the roadmap.` with `page_from = page_to = 2`. The two slides are never merged into a single chunk, even though together they are far under the 1,600-character target — `documents.anchor_kind = 'slide'` is the reason, confirmed here rather than assumed.

---

## Ordinals, and nothing empty

### 16. Confirm chunk order matches document order

```sql
SELECT document_id, ordinal FROM chunks ORDER BY document_id, ordinal;
```

**You should see:** for every `document_id`, `ordinal` running `0, 1, 2, …` with no gap and no repeat — the property a source viewer will later rely on to let someone step through a document in order.

### 17. Confirm no chunk is empty

```sql
SELECT count(*) FROM chunks WHERE btrim(content) = '';
```

**You should see:** `0`.

---

## The count is logged

### 18. Confirm chunk counts per document are logged

```
podman compose logs api worker | grep chunk_completed
```

**You should see:** four lines, one per file, each carrying `filename` and `chunks` — the `chunks` figure on each line matching the row count you read for that document in steps 11, 12, 13 and 15. This is the ticket's own analytics requirement: a local counter in the log, nothing transmitted (C1).

---

## Tidy up

```
rm -rf ~/external/quantum-plus/askwell/askwell-test-material
podman compose down -v
```

Then blank the `ASKWELL_ROOTS_MOUNT=` line in `.env` if you do not want to keep it.

---

## Known gaps

These are deliberately not built, or already recorded elsewhere. Do not report them as defects.

1. **There is no source viewer or library row yet.** `web/app/library/page.tsx` is still its own placeholder (unchanged since `M1-EXTRACT-ING-029`'s walkthrough). The ticket's own testing note — "read the source card" / "inspect the chunks through the source viewer" — has nothing to click yet, so this walkthrough reads `chunks` with `scripts/dev.sh psql` instead, exactly as that note allows: "before that path exists, inspect the chunks through the source viewer and confirm the same" is read here as "confirm the same in the table the viewer will eventually read from." The viewer itself is out of this ticket's scope (`M1-VIEW-FE-047` and later).
2. **Nothing is retrievable and no document reaches `ready`.** Embedding (`M1-INDEX-ING-032`) is still declared but not installed, so every document in this walkthrough parks at `embed` and stays `status = 'queued'` even though its chunks are real and correct underneath. This is the same honest-parking behaviour `M1-EXTRACT-ING-029`'s walkthrough recorded for the stage before this one, one stage further along.
3. **Chunk size (1,600 target / 2,400 hard maximum) is not evaluated.** The ticket's own testing note says so directly: tuning these numbers waits for the eval suite in M2. This walkthrough checks the *rules* (nothing crosses the maximum, a table survives with its header, a sentence is never orphaned), not whether these particular numbers are the right ones.
4. **A rate table that spans a real page break was not exercised.** All four fixtures are single-page or single-anchor documents; `extract_docx`'s own "approximate page" caveat (no true page break without an author-inserted one) means a table split across two genuine PDF pages is a case this walkthrough did not build a fixture for. `chunk.py`'s own table-splitting logic works from `document_pages.text` per page already, so a multi-page table is actually a multi-page-*document* case for `extract_pdf`/`extract_docx` to have merged correctly before chunking ever sees it — worth a fixture in a future extraction-side walkthrough, not this one.
