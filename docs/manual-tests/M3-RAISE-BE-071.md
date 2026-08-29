# Manual test — M3-RAISE-BE-071, capture the evidence that makes a question answerable

**Ticket:** `M3-RAISE-BE-071` — every raised clarification carries real evidence pulled from the source at raise time, never a paraphrase: an abbreviation and an ambiguous document identity each get sample passages, a contradiction gets both passages with their dates, a poor scan gets its extracted text — plus the current inference stored alongside for prefill, and evidence bounded in size.
**Version under test:** `0.3.2`
**Time:** about 45 minutes, plus a first stack build
**Who can run it:** a terminal and a browser, plus native inference running on the host for the embedding step. No generation model is needed — nothing in this ticket asks a question of the model.

**What is being checked.** `M3-RAISE-BE-068` built four triggers (`askwell.clarify`) that each raise a `clarifications` row once a source has nothing left outstanding. This ticket gives every raised row a real `evidence` column instead of the counts-only version `068` shipped: `_detect_abbreviations` and `_detect_document_identity` attach up to two sample passages (document, page, bounded text); `_detect_contradictions` attaches both conflicting passages with their own page and the document's `added_at` date; `_detect_unreadable_scans` attaches the extracted text of the low-confidence pages plus an explicit `"page_images": "not available"`, since nothing in the pipeline captures page images. `raise_candidates` merges each candidate's `inferred_fact` into its evidence as `current_inference`, `None` where there is nothing safe to guess. Every passage is bounded to 500 characters. Evidence that cannot be located (`_unavailable_evidence`) still raises the question rather than dropping it.

**Where this stops on purpose.** There is no rendering and no API route yet — `web/` has nothing under a clarifications page, and `api/src/askwell/main.py` exposes no clarifications endpoint. That is `M3-REVIEW-FE-073` and whatever backend route it needs. This walkthrough builds a corpus that trips all four triggers in one pass and reads the real `evidence` column straight out of the database, the same way earlier tickets read fields with no rendering yet.

---

## Before you start

- `.env.example` names `ASKWELL_EMBEDDING_MODEL_PATH=~/.local/share/askwell/models/bge-m3-FP16.gguf`. Only the embedding weights are needed — this ticket never calls the generation model.
- `ASKWELL_OCR_CONFIDENCE_THRESHOLD` defaults to `0.60`; this walkthrough relies on that default, so leave it unset in `.env` unless you changed it for another test.

```
cd ~/external/quantum-plus/askwell
mkdir -p askwell-test-material
```

If you have never run Askwell before:

```
cp -n .env.example .env
```

Open `.env`. Find `ASKWELL_ROOTS_MOUNT=` and set it to the folder above, with your own path:

```
ASKWELL_ROOTS_MOUNT=/home/you/external/quantum-plus/askwell/askwell-test-material
```

Find `POSTGRES_APP_PASSWORD` and put any word after the `=` if it is blank.

---

## Cold start

### 1. Remove any previous state

```
podman compose down -v
```

**You should see:** lines about containers and volumes being removed, or a note there was nothing to remove.

### 2. Build the interface

```
scripts/dev.sh web-build
```

**You should see:** a Next.js build finishing with a route list and no red error text.

### 3. Run the checks

```
scripts/dev.sh check
```

**You should see:** lint, format, typecheck and test stages finish without red error text, including `api/tests/test_clarify.py`'s evidence tests.

### 4. Bring the stack up

```
podman compose up -d
```

**You should see:** `postgres`, `redis`, `egress-proxy`, `api`, `worker` reported as started. Wait about thirty seconds.

### 5. Create the database tables

```
scripts/dev.sh db upgrade head
```

**You should see:** migration lines finish with no error, including `20260830_a4d9e2f6c831_memory_inferred_origin`.

### 6. Start native inference, on the host

```
scripts/dev.sh inference
```

Leave this running in its own terminal for the rest of this document. Wait for it to report the embedding role `ready` on its configured port.

### 7. Nominate the folder your material is in

Open a browser at:

```
http://127.0.0.1:8000
```

Click **Settings** in the left strip, scroll to **Folders Askwell may read**, type your own path into the **Nominate a folder** field —

```
/home/you/external/quantum-plus/askwell/askwell-test-material
```

— and click **Nominate**.

**You should see:** a box appear showing that path, marked **Readable**.

---

## Part A — build one corpus that trips all four triggers

Everything lands in a single **Add a source** batch, so one scan of the finished source raises all four kinds of question at once — the same thing a real cold-start import would do.

### 8. Write the abbreviation, document-identity and contradiction fixtures

```bash
scripts/dev.sh run python3 - <<'PY'
OUT = "/app/askwell-test-material"

with open(f"{OUT}/glossary.txt", "w") as f:
    f.write(
        "The NRV adjustment is applied at month end. "
        "Finance recalculates the NRV adjustment every quarter, "
        "and any variance is booked against the reserve.\n"
    )

with open(f"{OUT}/vendor-contract-v1.txt", "w") as f:
    f.write(
        "Vendor Services Agreement. This is the first draft circulated "
        "for review, covering scope of work and delivery milestones.\n"
    )

with open(f"{OUT}/vendor-contract-v2-FINAL.txt", "w") as f:
    f.write(
        "Vendor Services Agreement. This is the executed version, "
        "covering scope of work, delivery milestones and signatures.\n"
    )

with open(f"{OUT}/renewal-policy-2024.txt", "w") as f:
    f.write("Section 4. The renewal term is 30 days from the notice date.\n")

with open(f"{OUT}/renewal-policy-2025.txt", "w") as f:
    f.write("Section 4. The renewal term is 45 days from the notice date.\n")

print("done")
PY
```

**You should see:** the script print `done`.

### 9. Add the poor-scan fixture

```bash
scripts/dev.sh run python3 - <<'PY'
import io
from PIL import Image, ImageDraw, ImageFont

OUT = "/app/askwell-test-material"


def _obj_pdf(objects: list[bytes]) -> bytes:
    body = bytearray(b"%PDF-1.7\n")
    offsets = []
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(body))
        body += f"{number} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_offset = len(body)
    body += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        body += f"{offset:010d} 00000 n \n".encode()
    body += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n".encode()
    body += f"startxref\n{xref_offset}\n%%EOF".encode()
    return bytes(body)


def _jpeg(lines, font_size, blur, gray, quality):
    font = ImageFont.load_default(size=font_size)
    image = Image.new("RGB", (1000, 300 + 60 * max(len(lines) - 1, 0)), "white")
    draw = ImageDraw.Draw(image)
    for index, line in enumerate(lines):
        draw.text((20, 40 + index * 60), line, fill=(gray, gray, gray), font=font)
    if blur:
        from PIL import ImageFilter

        image = image.filter(ImageFilter.GaussianBlur(radius=blur))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality)
    return buffer.getvalue(), *image.size


def scanned_pdf(path, lines, *, font_size, blur=0.0, gray=0, quality=90):
    jpeg, width, height = _jpeg(lines, font_size, blur, gray, quality)
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            f"<< /Type /Page /Parent 2 0 R /Resources << /XObject << /Im1 5 0 R >> >> "
            f"/MediaBox [0 0 {width} {height}] /Contents 4 0 R >>"
        ).encode(),
    ]
    content = f"q {width} 0 0 {height} 0 0 cm /Im1 Do Q".encode()
    objects.append(b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream")
    objects.append(
        f"<< /Type /XObject /Subtype /Image /Width {width} /Height {height} "
        f"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode "
        f"/Length {len(jpeg)} >>\nstream\n".encode() + jpeg + b"\nendstream"
    )
    open(f"{OUT}/{path}", "wb").write(_obj_pdf(objects))


scanned_pdf(
    "poor-scan.pdf",
    ["Either party may terminate on ninety", "days written notice."],
    font_size=9, blur=1.0, gray=100, quality=25,
)
print("done")
PY
```

**You should see:** the script print `done`.

```
ls -la askwell-test-material
```

**You should see:** six files — `glossary.txt`, `vendor-contract-v1.txt`, `vendor-contract-v2-FINAL.txt`, `renewal-policy-2024.txt`, `renewal-policy-2025.txt`, `poor-scan.pdf`.

### 10. Get to the add screen by clicking

Click **Ask** in the left strip.

**You should see:** the "Ask your own material" page's first-run, empty-corpus state — a statement that no documents are indexed yet, and an **Add a source** button.

Click **Add a source**.

**You should see:** the "Add a source" page, address bar ending in `/sources/add/`.

### 11. Add all six files in one batch

Open your file manager at `~/external/quantum-plus/askwell/askwell-test-material`. Select all six files, drag them onto the window together and release, type the folder with your own path when asked, and click **Add them**.

**You should see:** six cards move to **Queued**, then progress as extraction, chunking and embedding run for real. One of the six (`poor-scan.pdf`) settles with a flagged line naming it a poor scan; the other five settle with no red error text.

### 12. Wait for the source to finish

```
scripts/dev.sh psql
```

```sql
SELECT filename, status, ocr_confidence FROM documents ORDER BY filename;
```

**You should see:** six rows, every `status` = `ready`, `poor-scan.pdf` the only row with `ocr_confidence` filled in and below `0.60`.

Keep this `psql` session open in its own terminal — you will re-run queries against it through the rest of this document.

```sql
SELECT status FROM sources;
```

**You should see:** one row, `status` = `attention` — the poor scan is the reason (`docs/states-and-edge-cases.md`'s flagged-but-searchable state), and this is also the moment `raise_candidates` runs, once, across the whole source.

---

## Part B — an abbreviation question carries real sample passages

### 13. Read the abbreviation clarification

```sql
SELECT subject, question, evidence FROM clarifications WHERE subject = 'NRV';
```

**You should see:** one row. `question` reads close to `'NRV' appears throughout. What does it mean?`. `evidence` is a JSON object with `"kind": "passage"`, `"occurrences": 2`, a `"samples"` array containing at least one entry with `"document": "glossary.txt"`, a `"page"` value, and `"text"` containing the real sentence `The NRV adjustment is applied at month end.` — not a summary or paraphrase of it. `"current_inference"` is `null`: an unexplained abbreviation has no safe guess.

---

## Part C — a document-identity question carries the newest file's own opening passage

### 14. Read the document-identity clarification

```sql
SELECT subject, question, options, evidence FROM clarifications WHERE subject = 'vendor contract';
```

**You should see:** one row. `question` names both files and asks whether `vendor-contract-v2-FINAL.txt` is current. `options` lists both filenames. `evidence` has `"kind": "passage"` with one sample whose `"document"` is `vendor-contract-v2-FINAL.txt` (the newer of the two by `added_at`) and whose `"text"` is that file's real opening sentence, `Vendor Services Agreement. This is the executed version, covering scope of work, delivery milestones and signatures.`

---

## Part D — a contradiction question carries both passages with their dates

### 15. Read the contradiction clarification

```sql
SELECT subject, question, options, evidence FROM clarifications WHERE subject = 'the renewal term';
```

**You should see:** one row. `question` reads close to `Sources disagree on the renewal term: *renewal-policy-2024.txt* says 30 days; *renewal-policy-2025.txt* says 45 days. Which is current?`. `options` lists both filenames. `evidence` has `"kind": "contradiction"` and a `"passages"` array with **two** entries, one per file — each carrying its own `"page"`, a `"value"` of `"30 days"` or `"45 days"`, a `"date"` (an ISO date, the two dates distinct if you did not add both files in the same instant), and `"text"` containing the real sentence around the match, e.g. `Section 4. The renewal term is 30 days from the notice date.` `"current_inference"` is `null`: a real, unresolved contradiction is never silently resolved to one side.

---

## Part E — a poor-scan question carries the real extracted text, and names what it does not have

### 16. Read the poor-scan clarification

```sql
SELECT subject, question, evidence FROM clarifications WHERE subject = 'poor-scan.pdf';
```

**You should see:** one row. `question` reads close to `Page 1 of *poor-scan.pdf* scanned poorly and produced little text. Re-scan, or index as-is?`. `evidence` has `"kind": "poor_scan"`, `"pages": [1]`, a `"total_pages"` count, `"page_images": "not available"` (nothing in the pipeline captures page images, stated here rather than silently omitted), and an `"extracted_text"` array. If Tesseract recovered any real text from the degraded page, that array has one entry with `"page": 1` and a `"text"` value that is genuinely garbled OCR output — not clean prose, since the fixture is deliberately near-unreadable. `"current_inference"` is **not** `null` here: it reads close to `poor-scan.pdf: indexed as-is. 1 of 1 page(s) scanned poorly, below the materiality threshold to ask about.` — a poor scan does have a safe default, unlike an abbreviation or a contradiction.

### 17. Confirm the edge case: evidence that cannot be captured still raises the question

If step 16's `extracted_text` came back empty (Tesseract found nothing at all on the degraded page — plausible depending on the exact rendering your Pillow/Tesseract versions produce), `evidence` instead has `"kind": "unavailable"` and a `"reason"` string naming the page and file, e.g. `no text extracted from page 1 of 'poor-scan.pdf'`. Either way the row in step 16 exists — the ticket's own edge case is that missing evidence never causes the question to be dropped, only its `evidence.kind` to change.

---

## Part F — every raised row's evidence is bounded, never the whole passage

### 18. Confirm no stored passage text exceeds the bound

```sql
SELECT subject,
       (evidence ->> 'samples')::jsonb AS samples,
       (evidence -> 'passages')::jsonb AS passages,
       (evidence -> 'extracted_text')::jsonb AS extracted_text
FROM clarifications;
```

Look at every `"text"` value across all four rows.

**You should see:** none longer than 500 characters. Since none of this walkthrough's fixture sentences are anywhere near that long, every one should be well short of the bound and end with the original sentence's own punctuation, not a truncation mark — the truncation path itself is exercised by `api/tests/test_clarify.py`'s longer-than-500-char cases, not practically reachable by hand here without a much longer fixture file.

---

## Part G — the audit trail agrees

### 19. Confirm each raise is recorded in the decisions store

```sql
SELECT payload ->> 'trigger' AS trigger, payload ->> 'subject' AS subject
FROM audit_decisions WHERE kind = 'clarification_raised' ORDER BY subject;
```

**You should see:** four rows — `abbreviation`/`NRV`, `contradiction`/`the renewal term`, `document_identity`/`vendor contract`, `unreadable_scan`/`poor-scan.pdf` — matching the four rows read in Parts B–E.

---

## Cleanup

```
podman compose down -v
```

Restore `.env` if you changed anything beyond what **Before you start** asked for.

---

## Known gaps

- **No rendering and no API route.** `M3-REVIEW-FE-073` has not landed: there is no clarifications screen, and nothing under `api/src/askwell/main.py` serves the `clarifications` table over HTTP yet. Every row in this walkthrough is read directly out of Postgres.
- **No ranking or five-per-source cap.** The `Clarification.rank` column exists in the model but nothing in this ticket populates it — that is a separate, later piece of `M3-RAISE-BE-068`'s own scope, not this ticket's.
- **Column-distribution evidence is untestable by hand.** `column_distribution_evidence` exists and is unit-tested (`api/tests/test_clarify.py`), but no trigger in this build calls it — no data source exposes a column yet. It arrives with M4; this walkthrough cannot exercise it against a real column because there is no real column to point it at.
- **Tesseract's exact output on the poor-scan fixture is not deterministic across machines.** Step 16/17 both cover the two ways it can land (some garbled text, or none at all) rather than asserting one, per `M1-EXTRACT-ING-029`'s own note that Tesseract's confidence is a measurement, not a constant.
- **No online-AI path.** Like the rest of Phase 1–2, this ticket's evidence capture only exercises local extraction and OCR. It never calls a generation model at all.
