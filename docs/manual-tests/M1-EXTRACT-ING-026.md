# Manual test — M1-EXTRACT-ING-026, PDF text-layer extraction

**Ticket:** `M1-EXTRACT-ING-026` — extract text from a text-layer PDF, page by page, with page numbers preserved
**Version under test:** `0.2.7`
**Time:** about 40 minutes, plus a first stack build
**Who can run it:** anyone who can paste a line into a terminal. Everything from step 10 onward is clicking and reading in a browser.

**What is being checked.** A citation to "page 14" only means something if extraction kept page 14 as page 14. This walkthrough adds a PDF whose page-by-page contents you know in advance, watches Askwell read it, and confirms — against the database, because no screen shows extracted text yet (see **Known gaps**) — that the page count and the per-page text line up with what was written. It also adds a PDF with nothing on any page and confirms Askwell notices rather than indexing it empty, and a PDF where only some pages have text and confirms the other pages are still on record rather than silently dropped.

**Where this stops on purpose.** Extraction is real as of this version, but the next stage — chunking, `M1-INDEX-ING-031` — is not, so nothing becomes searchable and no source reaches **Ready**. That is not a defect; see **Known gaps**.

---

## Before you start

You need a terminal and Podman. You do not need Python, Node, or anything else — including for building the test PDFs: the script below is plain `bash`, on purpose, because `AGENTS.md` says not to invoke the host's Python.

### 1. Build three test PDFs by hand

PDF is a plain-text format underneath its binary streams, so a real, parseable PDF can be built with nothing but `printf` and byte counting — no library, no network fetch, no host Python. Paste this whole block into the terminal and press Enter:

```bash
mkdir -p ~/askwell-test/material
cd ~/askwell-test/material

mkpdf() {
  out="$1"; shift
  pages=("$@")
  count=${#pages[@]}
  font_number=$((3 + count))
  : > "$out"
  printf '%%PDF-1.7\n' >> "$out"

  declare -a offsets
  objnum=1

  add_obj() {
    offsets[$objnum]=$(wc -c < "$out")
    printf '%s 0 obj\n' "$objnum" >> "$out"
    printf '%s' "$1" >> "$out"
    printf '\nendobj\n' >> "$out"
    objnum=$((objnum + 1))
  }

  kids=""
  for ((i = 0; i < count; i++)); do kids="$kids $((3 + i)) 0 R"; done

  add_obj "<< /Type /Catalog /Pages 2 0 R >>"
  add_obj "<< /Type /Pages /Kids [$kids] /Count $count >>"

  for ((i = 0; i < count; i++)); do
    content_number=$((font_number + 1 + i))
    add_obj "<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 $font_number 0 R >> >> /MediaBox [0 0 612 792] /Contents $content_number 0 R >>"
  done

  add_obj "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"

  for page in "${pages[@]}"; do
    if [ -z "$page" ]; then
      content=""
    else
      content="BT /F1 12 Tf 72 700 Td ($page) Tj ET"
    fi
    len=${#content}
    offsets[$objnum]=$(wc -c < "$out")
    printf '%s 0 obj\n<< /Length %s >>\nstream\n%s\nendstream\nendobj\n' "$objnum" "$len" "$content" >> "$out"
    objnum=$((objnum + 1))
  done

  xref_offset=$(wc -c < "$out")
  total=$objnum
  printf 'xref\n0 %s\n0000000000 65535 f \n' "$total" >> "$out"
  for ((n = 1; n < objnum; n++)); do
    printf '%010d 00000 n \n' "${offsets[$n]}" >> "$out"
  done
  printf 'trailer\n<< /Size %s /Root 1 0 R >>\nstartxref\n%s\n%%%%EOF' "$total" "$xref_offset" >> "$out"
}

mkpdf digital-3page.pdf \
  "Page one of the supply agreement. Either party may terminate on ninety days written notice." \
  "Page two of the supply agreement. The supplier warrants the goods for twelve months." \
  "Page three of the supply agreement. Governing law is the law of the buyers principal place of business."

mkpdf blank-2page.pdf "" ""

mkpdf mixed-3page.pdf \
  "Cover sheet: internal routing note, page one has text." \
  "" \
  "Signature page: page three also has text."

cd ~
```

**You should see:** no output at all. Silence is success.

Open your file manager and confirm `askwell-test/material` holds three files: `digital-3page.pdf`, `blank-2page.pdf`, `mixed-3page.pdf`.

| File | What it is for | What extraction should do with it |
| ---- | --------------- | ---------------------------------- |
| `digital-3page.pdf` | An ordinary digital contract, 3 pages, each with distinct text you can check against | 3 pages recorded, all three usable, page count = 3 |
| `blank-2page.pdf` | Every page has an empty content stream — no text anywhere | Both pages recorded as having no text; the document parks for OCR rather than indexing empty |
| `mixed-3page.pdf` | Page 1 and 3 have text, page 2 does not | All 3 pages recorded; page 2 is `has_text = false` and pages 1 and 3 are not — mixed handling per page, not per document |

### 2. Point Askwell at your files

```
cd ~/external/quantum-plus/askwell
```

If you have never run Askwell before:

```
cp -n .env.example .env
```

Open `.env` in any text editor. Find `ASKWELL_ROOTS_MOUNT=` and set it — replacing `you` with your own username:

```
ASKWELL_ROOTS_MOUNT=/home/you/askwell-test/material
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

**You should see:** lint, format, typecheck and test stages finish without red error text. This exercises `test_extract_pdf.py`'s page-usability rules without a database — a page of replacement characters is not usable, a page of ordinary prose is, a few stray replacement characters among real text stay usable.

### 6. Bring the stack up

```
podman compose up -d
```

**You should see:** `postgres`, `redis`, `egress-proxy`, `api`, `worker` reported as started. Wait about thirty seconds.

### 7. Create the database tables

```
scripts/dev.sh db upgrade head
```

**You should see:** migration lines, including one mentioning `document_pages`.

### 8. Nominate the folder your material is in

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

## Add the digital PDF and watch extraction run

### 9. Get to the add screen by clicking

Click **Ask** in the left strip.

**You should see:** the "Ask your own material" page, with an **Add a source** button.

Click **Add a source**.

**You should see:** the "Add a source" page, address bar ending in `/sources/add/`.

### 10. Drop the digital PDF

Open your file manager at `~/askwell-test/material`. Drag `digital-3page.pdf` onto the window and release.

**You should see:** a card move through **Detecting** to **Where are these?**, showing **"1 × a PDF document"**.

Type the folder, with your own username, and click **Add them**:

```
/home/you/askwell-test/material
```

**You should see:** the phase change to **Queued**, and under the queued note a live line describing the queue.

### 11. Watch the line change as extraction runs

Extraction on a 3-page file finishes in well under a second, so watch closely — you may need to reload once or twice, or add a second, larger source alongside it to slow things down enough to see the transition. What you are confirming across the two states below is that **something ran** between "queued" and "recorded and waiting for chunk": that something is extraction.

**You may briefly see:** "Indexing digital-3page.pdf." while the `extract` stage is running.

**You should then see:** the line settle on wording close to: *"1 file is recorded and waiting. Nothing is searchable yet: reading them needs chunk, which is not built yet (M1-INDEX-ING-031). Nothing has been copied."*

That sentence naming **chunk** rather than **extract** is the point: extraction is the stage this ticket built, and the pipeline has moved past it to the next stage that does not exist yet. If the sentence instead named `extract` and `M1-EXTRACT-ING-026`, extraction would not have run, and that is a defect.

> **A known inaccuracy in this same sentence, already filed as [#118](https://github.com/Rumeasiyan/askwell/issues/118):** the wording above is what you will see for `digital-3page.pdf`, and it is correct for that file. But the *same* wording is shown for `blank-2page.pdf` in step 13 below, where it is wrong — that file is actually parked waiting for OCR (`M1-EXTRACT-ING-028`), not chunking. The screen does not yet distinguish the two. Do not re-report this — it is what step 13 asks you to notice.

### 12. Confirm the page count and page text landed, page by page

Nothing in the interface shows extracted text yet (see **Known gaps**), so this is checked directly against the database — the same database the screen you just watched is reading from.

```
scripts/dev.sh psql
```

At the `psql` prompt, find the document:

```sql
SELECT id, filename, page_count, status FROM documents WHERE filename = 'digital-3page.pdf';
```

**You should see:** one row, `page_count` equal to **3**, and `status` equal to **`queued`** — not `ready`, because chunking has not run (see **Known gaps**).

Copy the `id` value from that row and use it below in place of `<id>`:

```sql
SELECT page_number, has_text, left(text, 60) FROM document_pages WHERE document_id = '<id>' ORDER BY page_number;
```

**You should see:** three rows. Page 1's text should begin with "Page one of the supply agreement.", page 2's with "Page two of the supply agreement.", page 3's with "Page three of the supply agreement." — matching, in order, the strings written into the file in step 1. All three should show `has_text` as `t`.

This is the ticket's own acceptance criterion, run for real: page numbers that match what a person reading the printed pages would call them, and a page count matching the document.

Leave `psql` open or type `\q` to exit — either is fine for what follows.

---

## A PDF with no text anywhere

### 13. Drop the blank PDF

Back in the browser, click **Choose files** on the add screen (or drag again) and add `blank-2page.pdf`, answering the folder question the same way.

**You should see:** it reach **Queued**, and the live line describe one more file recorded and waiting — worded the same as step 11's, which is the inaccuracy noted above.

Confirm what actually happened via `psql`:

```sql
SELECT id, filename, page_count, status FROM documents WHERE filename = 'blank-2page.pdf';
SELECT j.state, j.stage, j.awaiting FROM ingest_jobs j JOIN documents d ON d.id = j.document_id WHERE d.filename = 'blank-2page.pdf';
```

**You should see:** `page_count` equal to **2**, and the job row's `state` as **`parked`**, `awaiting` as **`ocr`** — the document is recognised as having no usable text layer and handed to the not-yet-built OCR ticket (`M1-EXTRACT-ING-028`), not indexed as if it had nothing to say.

```sql
SELECT page_number, has_text, text FROM document_pages WHERE document_id = (SELECT id FROM documents WHERE filename = 'blank-2page.pdf') ORDER BY page_number;
```

**You should see:** two rows, both with `has_text` as `f` and `text` as `NULL` — recorded, not skipped. That distinction is exactly what lets the OCR ticket later find these two pages without having to re-open the PDF and re-decide anything.

---

## A PDF that is only partly text

### 14. Drop the mixed PDF

Add `mixed-3page.pdf` the same way.

```sql
SELECT page_number, has_text, left(text, 60) FROM document_pages WHERE document_id = (SELECT id FROM documents WHERE filename = 'mixed-3page.pdf') ORDER BY page_number;
```

**You should see:** three rows — page 1 with text beginning "Cover sheet:" and `has_text = t`; page 2 with `text = NULL` and `has_text = f`; page 3 with text beginning "Signature page:" and `has_text = t`.

That is the ticket's stated edge case — "a PDF with a text layer on some pages only — mixed handling per page, not per document" — confirmed against a real row per page rather than the document being routed to OCR wholesale, or the blank page being silently dropped.

---

## What the logs recorded

### 15. Confirm extraction outcome is logged per document

```
podman compose logs api worker | grep extract_pdf_completed
```

**You should see:** one JSON line per PDF you added, each naming the `document_id`, `filename`, total `pages`, and `pages_with_text` — 3/3 for the digital PDF, 2/0 for the blank one, 3/2 for the mixed one. This is the "extraction outcome per document is logged" requirement.

---

## Tidy up

```
rm -rf ~/askwell-test
podman compose down -v
```

Then blank the `ASKWELL_ROOTS_MOUNT=` line in `.env` if you do not want to keep it.

---

## Known gaps

These are deliberately not built, or already recorded elsewhere. Do not report them as defects.

1. **No screen shows a document's page count or its extracted text.** The library page (`web/app/library/page.tsx`) is still its own placeholder — that surface, and the source viewer the ticket's own testing notes describe ("open the source viewer and confirm page 14 shows the text you expect"), are `M1-VIEW-FE-046` and later work. Steps 12–14 above check the same facts directly against Postgres instead, which is the same data those screens will eventually read.
2. **Nothing is searchable and no source reaches `ready`.** Extraction is the first real pipeline stage; chunking (`M1-INDEX-ING-031`) and embedding (`M1-INDEX-ING-032`) are still declared but not installed, so every document in this walkthrough parks at `chunk` (or `ocr`, for the text-less PDF) and stays `queued`, never `ready`. This is `M1-ADD-ING-025`'s documented pipeline shape, not a regression.
3. **The progress sentence on `/sources/add/` cannot yet tell "waiting for chunk" apart from "waiting for OCR"** — filed as [#118](https://github.com/Rumeasiyan/askwell/issues/118) and exercised in step 13. The API's `/ingest` snapshot has the correct per-batch `awaiting` stage and ticket; the frontend does not read it yet.
4. **Multi-column reading order is best-effort and not exercised here.** The ticket states this as a known limit rather than something this ticket solves, and building a genuinely multi-column PDF by hand is out of proportion to what a manual walkthrough can add beyond the module's own documented limitation (`api/src/askwell/extract_pdf.py`'s module docstring).
5. **Rotated pages and the embedded-font "unusable characters" edge case are not re-verified manually here.** Both are covered by automated tests that construct the exact byte-level cases: `test_a_rotated_page_is_read_in_the_correct_orientation` (`api/tests/test_ingest_records.py`) builds a page with `/Rotate 90` and confirms it reads correctly, and `test_a_page_of_replacement_characters_is_not_usable` / `test_a_few_replacement_characters_among_real_text_stay_usable` (`api/tests/test_extract_pdf.py`) cover the junk-character threshold. Reproducing a font subset that actually degrades to `U+FFFD` by hand, outside a test harness, is not something a person can reliably do with a text editor.
6. **A 900-page document with visible progress is not exercised here**, for the same reason as (4) — building one by hand is disproportionate. `ingest.py`'s `_reporter` and the per-page `await report(...)` call inside `extract_pdf.run` are what make this work, and are covered by `test_progress_moves_inside_a_single_enormous_file` and `test_progress_writes_are_throttled` in `api/tests/test_ingest_records.py`.
