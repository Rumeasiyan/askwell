# Manual test — M1-EXTRACT-ING-028, OCR fallback with orientation detection

**Ticket:** `M1-EXTRACT-ING-028` — a scanned PDF with no text layer is read via OCR, upside-down pages included
**Version under test:** `0.2.9`
**Time:** about 45 minutes, plus a first stack build
**Who can run it:** anyone who can paste a line into a terminal. Everything from step 9 onward is clicking and reading in a browser.

**What is being checked.** A 2009 scan has no text layer at all, so `M1-EXTRACT-ING-026`'s extraction alone would record it as pages with nothing in them. This walkthrough adds a scanned PDF whose page contents you know in advance and confirms — against the database, because no screen shows extracted text or the scanned image yet (see **Known gaps**) — that OCR read it, an upside-down page still reads right-side up, a mixed text-layer-plus-scan document only pays the OCR cost on the scanned page, a photograph page with no text is recorded rather than failing its document, and a document that is nothing but such photographs fails cleanly instead of indexing empty.

**Where this stops on purpose.** OCR is real as of this version, but the next stage — chunking, `M1-INDEX-ING-031` — is not, so nothing becomes searchable and no source reaches **Ready**. That is not a defect; see **Known gaps**.

---

## Before you start

You need a terminal and Podman. Building the digital (text-layer) fixture reuses `M1-EXTRACT-ING-026`'s plain-`printf` trick — no library needed. The *scanned* fixtures need pixels with rendered text, which `printf` cannot produce, so those are built by a Python script run **inside the API container image**, the same way `scripts/dev.sh run` runs anything else — `AGENTS.md` says not to invoke the host's Python, and this keeps that true while still building real JPEG-embedded PDFs with Pillow, which is already part of the image because `extract_ocr.py` and its tests depend on it.

### 1. Build the test PDFs

```
cd ~/external/quantum-plus/askwell
mkdir -p askwell-test-material
```

Build the scanned and mixed fixtures with the container's own Python and Pillow:

```bash
scripts/dev.sh run python3 - <<'PY'
import io
from PIL import Image, ImageDraw, ImageFont

OUT = "/app/askwell-test-material"
FONT = ImageFont.load_default(size=36)


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


def _jpeg(lines: list[str], rotate: int = 0) -> tuple[bytes, int, int]:
    image = Image.new("RGB", (1000, 300 + 60 * max(len(lines) - 1, 0)), "white")
    draw = ImageDraw.Draw(image)
    for index, line in enumerate(lines):
        draw.text((20, 40 + index * 60), line, fill="black", font=FONT)
    if rotate:
        image = image.rotate(rotate, expand=True)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    return buffer.getvalue(), *image.size


def scanned_pdf(path: str, lines: list[str], rotate: int = 0) -> None:
    """One page, image only, no text layer — a scanner's real output."""
    jpeg, width, height = _jpeg(lines, rotate)
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        f"<< /Type /Page /Parent 2 0 R /Resources << /XObject << /Im1 5 0 R >> >> "
        f"/MediaBox [0 0 {width} {height}] /Contents 4 0 R >>".encode(),
    ]
    content = f"q {width} 0 0 {height} 0 0 cm /Im1 Do Q".encode()
    objects.append(b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream")
    objects.append(
        f"<< /Type /XObject /Subtype /Image /Width {width} /Height {height} "
        f"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode "
        f"/Length {len(jpeg)} >>\nstream\n".encode() + jpeg + b"\nendstream"
    )
    open(f"{OUT}/{path}", "wb").write(_obj_pdf(objects))


def two_page_scanned_pdf(path: str, page1_lines: list[str], page2_lines: list[str]) -> None:
    """Two image-only pages sharing one /Pages tree — a mixed-content scan
    (some usable pages, one blank photograph)."""
    jpeg1, w1, h1 = _jpeg(page1_lines)
    jpeg2, w2, h2 = _jpeg(page2_lines)
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>",
        f"<< /Type /Page /Parent 2 0 R /Resources << /XObject << /Im1 7 0 R >> >> "
        f"/MediaBox [0 0 {w1} {h1}] /Contents 5 0 R >>".encode(),
        f"<< /Type /Page /Parent 2 0 R /Resources << /XObject << /Im2 8 0 R >> >> "
        f"/MediaBox [0 0 {w2} {h2}] /Contents 6 0 R >>".encode(),
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


def mixed_source_pdf(path: str) -> None:
    """Page 1 has a real vector text layer; page 2 is image-only. The
    ticket's own edge case: OCR runs only on the page that needs it."""
    jpeg, width, height = _jpeg(["The supplier warrants the goods", "for twelve months."])
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>",
        b"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 8 0 R >> >> "
        b"/MediaBox [0 0 612 792] /Contents 5 0 R >>",
        f"<< /Type /Page /Parent 2 0 R /Resources << /XObject << /Im1 7 0 R >> >> "
        f"/MediaBox [0 0 {width} {height}] /Contents 6 0 R >>".encode(),
    ]
    text_content = (
        b"BT /F1 12 Tf 72 700 Td (Either party may terminate on ninety days written notice.) Tj ET"
    )
    objects.append(b"<< /Length %d >>\nstream\n" % len(text_content) + text_content + b"\nendstream")
    image_content = f"q {width} 0 0 {height} 0 0 cm /Im1 Do Q".encode()
    objects.append(b"<< /Length %d >>\nstream\n" % len(image_content) + image_content + b"\nendstream")
    objects.append(
        f"<< /Type /XObject /Subtype /Image /Width {width} /Height {height} "
        f"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode "
        f"/Length {len(jpeg)} >>\nstream\n".encode() + jpeg + b"\nendstream"
    )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    open(f"{OUT}/{path}", "wb").write(_obj_pdf(objects))


scanned_pdf("scan-upright.pdf", ["Either party may terminate on ninety", "days written notice."])
scanned_pdf(
    "scan-upside-down.pdf",
    ["Either party may terminate on ninety", "days written notice to the other side."],
    rotate=180,
)
two_page_scanned_pdf(
    "scan-with-blank-photo.pdf",
    ["Either party may terminate on ninety", "days written notice."],
    [],
)
scanned_pdf("scan-nothing-anywhere.pdf", [])
mixed_source_pdf("mixed-source.pdf")
print("done")
PY
```

**You should see:** the script print `done` with no traceback. Confirm the files landed:

```
ls -la askwell-test-material
```

**You should see:** five `.pdf` files: `scan-upright.pdf`, `scan-upside-down.pdf`, `scan-with-blank-photo.pdf`, `scan-nothing-anywhere.pdf`, `mixed-source.pdf`.

| File | What it is for | What OCR should do with it |
| ---- | --------------- | ---------------------------------- |
| `scan-upright.pdf` | An ordinary scanned page, right-side up, 1 page | Reads back the exact two lines of text; `ocr_derived = true` |
| `scan-upside-down.pdf` | The same page baked in at 180° rotation — a scanner does not know it fed a page in backwards | Orientation detected and corrected before recognition; text reads identically to the upright version |
| `scan-with-blank-photo.pdf` | Page 1 has real text; page 2 is a blank white image — a photograph with nothing on it | Page 1 reads its text; page 2 records `has_text = false`, `text = NULL` — recorded, not a failure |
| `scan-nothing-anywhere.pdf` | One page, blank image, nothing to read anywhere in the document | OCR is given a fair try and finds nothing; the whole document fails cleanly (C5), not indexed empty |
| `mixed-source.pdf` | Page 1 is a real text layer (vector), page 2 is a scanned image | Page 1 is read by ordinary extraction, not OCR; only page 2 costs an OCR pass; `ocr_derived = true` |

### 2. Point Askwell at your files

If you have never run Askwell before:

```
cp -n .env.example .env
```

Open `.env` in any text editor. Find `ASKWELL_ROOTS_MOUNT=` and set it to the folder you just created, with your own path:

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

**You should see:** migration lines, including one mentioning `ocr_derived`.

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

## An ordinary scanned page

### 9. Get to the add screen by clicking

Click **Ask** in the left strip.

**You should see:** the "Ask your own material" page, with an **Add a source** button.

Click **Add a source**.

**You should see:** the "Add a source" page, address bar ending in `/sources/add/`.

### 10. Drop the scanned PDF

Open your file manager at `~/external/quantum-plus/askwell/askwell-test-material`. Drag `scan-upright.pdf` onto the window and release.

**You should see:** a card move through **Detecting** to **Where are these?**, showing **"1 × a PDF document"**.

Type the folder, with your own path, and click **Add them**:

```
/home/you/external/quantum-plus/askwell/askwell-test-material
```

**You should see:** the phase change to **Queued**.

### 11. Watch it take visibly longer than a digital PDF

OCR renders the page to an image and runs Tesseract on it, which is slower than reading an existing text layer. Watch the live line under the queued note.

**You may briefly see:** "Indexing scan-upright.pdf." holding for noticeably longer than the plain-text case in `M1-EXTRACT-ING-026`'s walkthrough did for a comparable file — this is the OCR pass running, not a stall.

**You should then see:** the line settle on wording close to: *"1 file is recorded and waiting. Nothing is searchable yet: reading them needs chunk, which is not built yet (M1-INDEX-ING-031). Nothing has been copied."*

### 12. Confirm the page count and OCR'd text landed

Nothing in the interface shows extracted text or the source image yet (see **Known gaps**), so this is checked directly against the database.

```
scripts/dev.sh psql
```

```sql
SELECT id, filename, page_count, ocr_derived, status FROM documents WHERE filename = 'scan-upright.pdf';
```

**You should see:** one row, `page_count` equal to **1**, `ocr_derived` equal to **`t`**, `status` equal to **`queued`** — not `ready`, because chunking has not run.

Copy the `id` and use it below:

```sql
SELECT page_number, has_text, text FROM document_pages WHERE document_id = '<id>';
```

**You should see:** one row, `has_text` as `t`, and `text` reading exactly:

```
Either party may terminate on ninety
days written notice.
```

That is the ticket's headline acceptance criterion: a scanned PDF with no text layer produces text per page, with the real page count.

---

## An upside-down page

### 13. Drop the rotated scan

Back in the browser, add `scan-upside-down.pdf` the same way, answering the folder question the same way.

```sql
SELECT text FROM document_pages WHERE document_id = (SELECT id FROM documents WHERE filename = 'scan-upside-down.pdf');
```

**You should see:** one row reading exactly:

```
Either party may terminate on ninety
days written notice to the other side.
```

— right-side up and correctly worded, even though the page was baked in rotated 180° and the PDF itself carries no `/Rotate` hint a scanner would never have written. This is the ticket's own title: orientation detection ran before recognition and corrected it.

---

## A photograph with no text, alongside a real page

### 14. Drop the mixed scan

Add `scan-with-blank-photo.pdf`.

```sql
SELECT page_number, has_text, text FROM document_pages
  WHERE document_id = (SELECT id FROM documents WHERE filename = 'scan-with-blank-photo.pdf')
  ORDER BY page_number;
```

**You should see:** two rows — page 1 with `has_text = t` and the same two lines of text as step 12, page 2 with `has_text = f` and `text` as `NULL`.

```sql
SELECT status FROM documents WHERE filename = 'scan-with-blank-photo.pdf';
```

**You should see:** `queued`, not a failure — the blank photograph page is recorded as having nothing, and the document as a whole still proceeds. That is the ticket's own edge case: "a page that is a photograph with no text — produces nothing and is recorded as such rather than failing the document."

---

## A document that is nothing but a blank photograph

### 15. Drop the all-blank scan

Add `scan-nothing-anywhere.pdf`.

**You should see:** the live line eventually stop mentioning this file as still queued — the worker retries it and gives up (see `MAX_ATTEMPTS` in `api/src/askwell/ingest.py`), which takes longer than the other files in this walkthrough. Give it a minute or two.

```sql
SELECT j.state, j.error FROM ingest_jobs j
  JOIN documents d ON d.id = j.document_id
  WHERE d.filename = 'scan-nothing-anywhere.pdf';
```

**You should see:** `state` as **`failed`**, and `error` mentioning that no text was found. Unlike the mixed-page case in step 14, a document that is *only* unreadable pages — even after every page was given a fair OCR try — is the same "nothing to say" failure every other extractor reports (C5), not indexed as if it had content. This is expected, not a defect.

---

## A mixed text-layer and scanned document

### 16. Drop the mixed-source PDF

Add `mixed-source.pdf`.

```sql
SELECT page_number, has_text, text FROM document_pages
  WHERE document_id = (SELECT id FROM documents WHERE filename = 'mixed-source.pdf')
  ORDER BY page_number;
```

**You should see:** two rows — page 1 with text reading exactly `Either party may terminate on ninety days written notice.` (its real text layer, extracted the ordinary way), page 2 with text reading the two OCR'd lines from step 12's fixture.

```sql
SELECT ocr_derived FROM documents WHERE filename = 'mixed-source.pdf';
```

**You should see:** `t` — the document is marked OCR-derived because at least one page needed it, even though page 1 never touched Tesseract. That is the stated edge case: "a mixed document — OCR runs only on the pages that need it," confirmed here by the fact that page 1's text is a clean sentence with no recognition artefacts, and by the log line in the next step showing only one OCR page ran.

---

## What the logs recorded

### 17. Confirm OCR invocation and per-page outcome are logged

```
podman compose logs api worker | grep -E "ocr_page_completed|ocr_osd_skipped"
```

**You should see:** one `ocr_page_completed` line per OCR'd page across the five files (four from the single-scan files, one from `mixed-source.pdf`'s second page — five in total, not six, because `scan-with-blank-photo.pdf`'s first page and `mixed-source.pdf`'s first page are read by ordinary text extraction, not OCR). Each line names `document_id`, `filename`, `has_text`, `rotation`, `language`, and `supported`. The `scan-upside-down.pdf` line should show `rotation` as `180`. Every line here should show `language` as `eng` and `supported` as `true` — none of this walkthrough's fixtures exercise the Tamil hedge, which is why it is not tested here (see **Known gaps**).

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

1. **No screen shows a document's page count, extracted text, or the scanned image beside it.** The library page (`web/app/library/page.tsx`) is still its own placeholder, and the source viewer that would show a scan next to its OCR'd text is `M1-EXTRACT-ING-029` (confidence) and the later source-viewer work. Steps 12–16 above check the same facts directly against Postgres instead.
2. **Nothing is searchable and no source reaches `ready`.** Chunking (`M1-INDEX-ING-031`) and embedding (`M1-INDEX-ING-032`) are still declared but not installed, so every document in this walkthrough parks at `chunk` and stays `queued`.
3. **The `/sources/add/` progress sentence still names `chunk`, never `ocr`, for every file in this walkthrough** — correctly, this time. `M1-EXTRACT-ING-028` removed the `awaiting: ocr` job state entirely: OCR now runs inline inside `extract`, so a scanned PDF parks at `chunk` exactly like a digital one, and the inaccuracy `M1-EXTRACT-ING-026`'s walkthrough found (issue #118) can no longer occur for this reason. Issue #124 (the frontend never reading `state.awaiting` at all) remains open for whatever stage parks separately next.
4. **Low-confidence flagging is not built.** `documents.ocr_confidence` does not exist yet; that is `M1-EXTRACT-ING-029`, explicitly out of this ticket's scope. Nothing here checks OCR quality, only that text came back.
5. **The Tamil hedge (`tam` traineddata) is not exercised in this walkthrough.** Building a fixture with real Tamil script by hand is disproportionate to what this manual pass can add beyond `extract_ocr.py`'s own module docstring and its automated coverage; step 17 confirms every fixture used here reads as `eng`/`supported=true`, which is what should happen for non-Tamil scans.
6. **Passage-level highlighting on scans is out of scope**, stated in the ticket itself — scans highlight at page level only, and there is no highlighting UI yet regardless (gap 1).
7. **A 900-page scan with bounded memory is not exercised here**, for the same reason building one by hand is disproportionate elsewhere in this repo's manual tests. `extract_ocr.RENDER_SCALE` and the one-page-at-a-time render/OCR/discard loop in `extract_ocr.ocr_page` are what keep memory bounded, and are documented in the module rather than demonstrated by hand.
