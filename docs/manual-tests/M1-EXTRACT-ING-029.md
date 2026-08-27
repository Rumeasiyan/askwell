# Manual test — M1-EXTRACT-ING-029, flag low-confidence OCR and surface it as needs attention

**Ticket:** `M1-EXTRACT-ING-029` — a badly photocopied document indexes, is flagged low confidence, and its source says so with a specific reason
**Version under test:** `0.2.10`
**Time:** about 45 minutes, plus a first stack build
**Who can run it:** anyone who can paste a line into a terminal. Everything from step 9 onward is clicking and reading in a browser.

**What is being checked.** `M1-EXTRACT-ING-028` gave every scanned page Tesseract's own recognition. This ticket adds the second half: Tesseract's own confidence for that recognition is measured, stored per page and per document, and used to flag a document that read badly — never as a failure, always still searchable — with a reason specific enough to name the file and, for a mixed document, exactly which pages. This walkthrough adds four fixtures whose expected confidence you know in advance and confirms: a good scan is never flagged, a genuinely poor scan is flagged with a readable reason, a document that is partly good and partly poor is flagged at the document level while naming only the poor pages, a document with a real text layer (no OCR at all) carries no confidence and is never flagged, the flag is visible in the running interface and not only in the database, and the cut line is configuration rather than a number baked into the code.

**Where this stops on purpose.** Chunking (`M1-INDEX-ING-031`) is still not built, so — exactly as in `M1-EXTRACT-ING-028`'s walkthrough — nothing in this pass becomes searchable and no document reaches `ready`. That does not stop the flag itself: `source_status` checks `flagged` before it checks `ready`, so a source with a poor scan in it says **needs attention** as soon as extraction finishes, independent of chunking. See **Known gaps**.

---

## Before you start

You need a terminal and Podman. All four fixtures are built by a Python script run **inside the API container image**, the same way `M1-EXTRACT-ING-028`'s walkthrough built its scanned PDFs — `AGENTS.md` says not to invoke the host's Python, and this keeps that true while still producing real JPEG-embedded PDFs with Pillow, already part of the image.

The confidence figures below were measured by running each fixture through `askwell.extract_ocr.ocr_page` directly inside this repository's own API image before writing this walkthrough, so they are what this build actually produces, not a guess. Tesseract's mean-word-confidence is nonetheless a measurement, not a constant — if your numbers land a few points either side of what is written here, that is expected; what matters is which side of **60%** (`ASKWELL_OCR_CONFIDENCE_THRESHOLD`, default `0.60`) each one falls on, which is called out for every fixture.

### 1. Build the test PDFs

```
cd ~/external/quantum-plus/askwell
mkdir -p askwell-test-material
```

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


def _jpeg(lines: list[str], font_size: int, blur: float, gray: int, quality: int) -> tuple[bytes, int, int]:
    """A rendered line of text, degraded by three independent knobs: a small
    font (the single biggest lever on confidence), a blur radius (softens
    edges the way a photocopier's own optics do) and JPEG quality (compression
    artefacts). `gray` off pure black is a faded-toner stand-in."""
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


def _page_object(number: int, xobject_number: int, content_number: int, width: int, height: int) -> bytes:
    return (
        f"<< /Type /Page /Parent 2 0 R /Resources << /XObject << /Im{number} {xobject_number} 0 R >> >> "
        f"/MediaBox [0 0 {width} {height}] /Contents {content_number} 0 R >>"
    ).encode()


def scanned_pdf(path: str, lines: list[str], *, font_size: int, blur: float = 0.0, gray: int = 0, quality: int = 90) -> None:
    """One image-only page — a scanner's real output, degraded to taste."""
    jpeg, width, height = _jpeg(lines, font_size, blur, gray, quality)
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        _page_object(1, 5, 4, width, height),
    ]
    content = f"q {width} 0 0 {height} 0 0 cm /Im1 Do Q".encode()
    objects.append(b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream")
    objects.append(
        f"<< /Type /XObject /Subtype /Image /Width {width} /Height {height} "
        f"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode "
        f"/Length {len(jpeg)} >>\nstream\n".encode() + jpeg + b"\nendstream"
    )
    open(f"{OUT}/{path}", "wb").write(_obj_pdf(objects))


def mixed_confidence_pdf(path: str) -> None:
    """Two image-only pages, degraded by different amounts — the ticket's own
    edge case: partly good, partly poor, flagged at the document level with
    the poor page named and the good one left alone."""
    jpeg1, w1, h1 = _jpeg(
        ["Either party may terminate on ninety", "days written notice."],
        font_size=9, blur=0.5, gray=60, quality=30,
    )
    jpeg2, w2, h2 = _jpeg(
        ["The supplier warrants the goods", "for twelve months."],
        font_size=9, blur=1.0, gray=100, quality=25,
    )
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>",
        _page_object(1, 7, 5, w1, h1),
        _page_object(2, 8, 6, w2, h2),
    ]
    c1 = f"q {w1} 0 0 {h1} 0 0 cm /Im1 Do Q".encode()
    c2 = f"q {w2} 0 0 {h2} 0 0 cm /Im2 Do Q".encode()
    objects.append(b"<< /Length %d >>\nstream\n" % len(c1) + c1 + b"\nendstream")
    objects.append(b"<< /Length %d >>\nstream\n" % len(c2) + c2 + b"\nendstream")
    objects.append(
        f"<< /Type /XObject /Subtype /Image /Width {w1} /Height {h1} "
        f"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode "
        f"/Length {len(jpeg1)} >>\nstream\n".encode() + jpeg1 + b"\nendstream"
    )
    objects.append(
        f"<< /Type /XObject /Subtype /Image /Width {w2} /Height {h2} "
        f"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode "
        f"/Length {len(jpeg2)} >>\nstream\n".encode() + jpeg2 + b"\nendstream"
    )
    open(f"{OUT}/{path}", "wb").write(_obj_pdf(objects))


def digital_pdf(path: str, line: str) -> None:
    """A real vector text layer — OCR never runs, so it never has a confidence
    to flag on. `M1-EXTRACT-ING-029`'s own edge case: no flag, not a false one."""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 5 0 R >> >> "
        b"/MediaBox [0 0 612 792] /Contents 4 0 R >>",
    ]
    content = f"BT /F1 12 Tf 72 700 Td ({line}) Tj ET".encode()
    objects.append(b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    open(f"{OUT}/{path}", "wb").write(_obj_pdf(objects))


clean_lines = ["Either party may terminate on ninety", "days written notice."]
scanned_pdf("clean-scan.pdf", clean_lines, font_size=36)
scanned_pdf("poor-scan.pdf", clean_lines, font_size=9, blur=1.0, gray=100, quality=25)
mixed_confidence_pdf("mixed-confidence.pdf")
digital_pdf("digital-no-ocr.pdf", "This contract has a real, machine-written text layer.")
print("done")
PY
```

**You should see:** the script print `done` with no traceback.

```
ls -la askwell-test-material
```

**You should see:** four `.pdf` files: `clean-scan.pdf`, `poor-scan.pdf`, `mixed-confidence.pdf`, `digital-no-ocr.pdf`.

| File | What it is for | What should happen |
| ---- | --------------- | ------------------- |
| `clean-scan.pdf` | A crisp, large-font scan — measured at about **96%** confidence | Indexed, never flagged |
| `poor-scan.pdf` | Small font, faded, blurred, heavily compressed — measured at about **34%** confidence | Indexed, flagged low confidence, page 1 named as the poor page |
| `mixed-confidence.pdf` | Two pages, each degraded by a different amount: page 1 measured at about **68%** (above the threshold on its own), page 2 at about **34%** (below it) | The document's own average (~51%) falls below the threshold, so the whole document is flagged — but only page 2 is named as poor |
| `digital-no-ocr.pdf` | A real text layer, no image at all | Indexed normally; OCR never runs, so there is no confidence to flag on |

### 2. Point Askwell at your files

If you have never run Askwell before:

```
cp -n .env.example .env
```

Open `.env`. Find `ASKWELL_ROOTS_MOUNT=` and set it to the folder you just created, with your own path:

```
ASKWELL_ROOTS_MOUNT=/home/you/external/quantum-plus/askwell/askwell-test-material
```

Find `POSTGRES_APP_PASSWORD` and put any word after the `=` if it is blank. Leave `ASKWELL_OCR_CONFIDENCE_THRESHOLD` unset for now — its default of `0.60` is what every expectation below assumes.

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

**You should see:** lint, format, typecheck and test stages finish without red error text.

### 6. Bring the stack up

```
podman compose up -d
```

**You should see:** `postgres`, `redis`, `egress-proxy`, `api`, `worker` reported as started. Wait about thirty seconds.

### 7. Create the database tables

```
scripts/dev.sh db upgrade head
```

**You should see:** migration lines, including one mentioning per-page OCR confidence (revision `9a1c6e4f2b57`).

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

## A good scan — never flagged

### 9. Get to the add screen by clicking

Click **Ask** in the left strip.

**You should see:** the "Ask your own material" page, with an **Add a source** button.

Click **Add a source**.

**You should see:** the "Add a source" page, address bar ending in `/sources/add/`.

### 10. Drop the clean scan

Open your file manager at `~/external/quantum-plus/askwell/askwell-test-material`. Drag `clean-scan.pdf` onto the window and release, type the folder with your own path when asked, and click **Add them**.

**You should see:** the card move to **Queued**, then the live line settle on wording close to: *"1 file is recorded and waiting. Nothing is searchable yet: reading them needs chunk, which is not built yet (M1-INDEX-ING-031). Nothing has been copied."*

**You should not see:** any line about a file scanning poorly. Nothing appears under the queued note beyond the line above — this is the negative case the rest of the walkthrough is checked against.

### 11. Confirm no confidence was flagged, in the database

```
scripts/dev.sh psql
```

```sql
SELECT filename, ocr_derived, ocr_confidence, status FROM documents WHERE filename = 'clean-scan.pdf';
```

**You should see:** one row, `ocr_derived` as `t`, `ocr_confidence` in the **0.90s**, `status` as `queued` (not `ready` — chunking has not run; see **Known gaps**).

---

## A poor scan — flagged, and never treated as a failure

### 12. Drop the poor scan

Back in the browser, add `poor-scan.pdf` the same way.

**You should see:** under the queued note, a new line appear — this is `Flagged` rendering `flaggedSentence` live, in the running interface, not only in the database — reading close to: *"poor-scan.pdf scanned poorly (about 34% confidence) — page 1 read worst. It is indexed and searchable, but answers about it may be thin."*

That sentence is the ticket's headline acceptance criterion, checked in the interface itself: a poor scan is flagged with a specific, readable reason, and the wording states plainly that it is indexed, not failed.

### 13. Confirm it against the database

```sql
SELECT filename, ocr_confidence, status FROM documents WHERE filename = 'poor-scan.pdf';
```

**You should see:** `ocr_confidence` in the **0.30s**, `status` as `queued` — the same status a perfectly good file gets at this stage of the pipeline, because a flag is not a failure.

```sql
SELECT page_number, ocr_confidence FROM document_pages
  WHERE document_id = (SELECT id FROM documents WHERE filename = 'poor-scan.pdf');
```

**You should see:** one row, page 1, with the same confidence figure — the per-page table the aggregate was built from.

### 14. Confirm the source itself says needs attention

```sql
SELECT status, last_error FROM sources WHERE id = (
  SELECT source_id FROM documents WHERE filename = 'poor-scan.pdf'
);
```

**You should see:** `status` as `attention`, and `last_error` reading close to: *"1 file scanned poorly and may be hard to search."* This is `sources.status` and `sources.last_error`, the two fields the ticket names in its API/data touchpoints — the source-level flag exists even though no screen renders a source row yet (see **Known gaps**).

---

## A document that is partly good and partly poor

### 15. Drop the mixed-confidence document

Add `mixed-confidence.pdf`.

**You should see:** a new `Flagged` line appear for it, naming only **page 2** — close to: *"mixed-confidence.pdf scanned poorly (about 51% confidence) — page 2 read worst. It is indexed and searchable, but answers about it may be thin."*

**You should not see** page 1 named anywhere in that line, even though it contributed to the average that got the document flagged — page 1's own confidence (~68%) is above the threshold on its own.

### 16. Confirm at the page level

```sql
SELECT page_number, ocr_confidence FROM document_pages
  WHERE document_id = (SELECT id FROM documents WHERE filename = 'mixed-confidence.pdf')
  ORDER BY page_number;
```

**You should see:** two rows — page 1 in the **0.60s**, page 2 in the **0.30s**.

```sql
SELECT ocr_confidence FROM documents WHERE filename = 'mixed-confidence.pdf';
```

**You should see:** the document-level figure in the **0.50s** — the mean of the two pages, and the reason the whole document is flagged even though one page alone would not have been. This is the ticket's own edge case: "a document that is partly good and partly poor — flagged at document level with the poor pages named," confirmed here by the fact that only page 2 was named in step 15 while both pages contributed to the average.

---

## A real text layer — no OCR, no flag, not a false one

### 17. Drop the digital document

Add `digital-no-ocr.pdf`.

**You should see:** no `Flagged` line for it, ever — before or after this step, `state.flagged` never grows for this file.

### 18. Confirm confidence is genuinely absent, not zero

```sql
SELECT ocr_derived, ocr_confidence FROM documents WHERE filename = 'digital-no-ocr.pdf';
```

**You should see:** `ocr_derived` as `f` and `ocr_confidence` as **`NULL`** — not `0`, which would read as the worst possible scan rather than as "OCR never ran here." That distinction is the ticket's own stated edge case: "confidence unavailable for a text-layer document — no flag, not a false one."

---

## The threshold is configuration, not a number in the code

### 19. Raise the cut line and watch a previously-clean file get flagged

Nothing about `clean-scan.pdf` needs to be re-added: the confidence figure is already stored, and the flag is computed live from configuration each time the queue is read. Open `.env`, add or edit:

```
ASKWELL_OCR_CONFIDENCE_THRESHOLD=0.99
```

Restart the two containers that read configuration:

```
podman compose restart api worker
```

Back in the browser, reload `/sources/add/`.

**You should see:** `clean-scan.pdf` — measured at about 96% confidence, comfortably above the *default* 60% cut line — now appear in the `Flagged` list too, because 96% is below the *new* 99% cut line. Nothing about the file changed; only the configuration did.

### 20. Put the threshold back

Edit `.env` again, remove or reset the `ASKWELL_OCR_CONFIDENCE_THRESHOLD` line, then:

```
podman compose restart api worker
```

Reload the page. **You should see:** `clean-scan.pdf` drop out of the `Flagged` list again.

---

## What the logs and the audit store recorded

### 21. Confirm the measured confidence is logged, not just stored

```
podman compose logs api worker | grep extract_pdf_completed
```

**You should see:** one line per document added in this walkthrough, each carrying `ocr_confidence` — `null` for `digital-no-ocr.pdf`, a number for the other three, matching what step 11/13/16/18 read from the database.

### 22. Confirm the source's move to needs attention is in the decisions store

```sql
SELECT kind, payload FROM audit_decisions WHERE kind = 'source_status_changed' ORDER BY occurred_at DESC LIMIT 5;
```

**You should see:** at least one row with `payload->>'to'` equal to `attention` and `payload->>'flagged'` greater than `0` — `docs/audit-log.md` §2 puts a source becoming askable, or needing attention, in the decisions store, and this is that change, recorded once rather than once per file.

---

## Tidy up

```
rm -rf ~/external/quantum-plus/askwell/askwell-test-material
podman compose down -v
```

Then blank the `ASKWELL_ROOTS_MOUNT=` and `ASKWELL_OCR_CONFIDENCE_THRESHOLD=` lines in `.env` if you do not want to keep them.

---

## Known gaps

These are deliberately not built, or already recorded elsewhere. Do not report them as defects.

1. **The library page (`web/app/library/page.tsx`) is still its own placeholder.** The ticket's acceptance criterion — "the source shows needs attention" — is genuinely true in the data (`sources.status`, `sources.last_error`, steps 14 and 22) and is genuinely visible in the running interface (the `Flagged` list under a queued batch on `/sources/add/`, steps 12 and 15), but there is no library row yet to expand the way `docs/ux/library.md` §2 describes. That row, and the source viewer showing the scanned image beside the extracted text, are `M1-VIEW-FE-047` and later library work, both explicitly out of this ticket's scope.
2. **Nothing is searchable and no document reaches `ready`.** Chunking (`M1-INDEX-ING-031`) and embedding (`M1-INDEX-ING-032`) are still declared but not installed, so every document in this walkthrough parks at `chunk` and stays `status = 'queued'` even once flagged. The flag itself does not wait for this — `source_status` checks `flagged` ahead of `ready == total` for exactly that reason — but "indexed" in the acceptance criteria and "queued" in the database describing the same document is this build's honest state, the same known gap `M1-EXTRACT-ING-028`'s walkthrough recorded.
3. **The re-scan clarification is not built.** `M3`, named out of scope in the ticket itself. Nothing here offers to ask the user whether to re-scan a flagged file.
4. **`documents_flagged`, the local counter named in the ticket's analytics requirement, is only checked here via `/ingest`'s JSON payload (`podman compose logs`, `scripts/dev.sh psql`) rather than through a rendered number in the interface** — there is no dashboard yet to show it on. It is present in `snapshot()`'s output (`api/src/askwell/ingest.py`), confirmed to move in steps 12 and 15, and is local-only per C1 as its own comment states.
5. **A genuinely bad real-world scan was not used.** These fixtures are synthetic degradations (small font, blur, JPEG quality) tuned to land reliably on either side of the 60% cut line rather than an actual photocopier's output, for the same reason `M1-EXTRACT-ING-028`'s walkthrough built its scans by script rather than sourcing paper: reproducibility across machines matters more here than realism, and the measured percentages in step 1's table are what this build's own Tesseract actually produced from them.
