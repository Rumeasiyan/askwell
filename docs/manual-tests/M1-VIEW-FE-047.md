# Manual test — M1-VIEW-FE-047, non-PDF renderings and OCR text beside scans

**Ticket:** `M1-VIEW-FE-047` — converted-text rendering (Word, PowerPoint, text, Markdown,
HTML), spreadsheet table rendering, image/scan rendering with OCR text alongside, and the
unrenderable fallback.
**Version under test:** `0.2.31`
**Time:** about 30 minutes, with native inference running throughout.
**Who can run it:** anyone who can paste a line into a terminal and use a browser.

**What is being checked.** `web/components/documents/document-viewer.tsx` routes a
document to one of four renderers by `web/lib/document-format.ts`'s `documentFormat(mime)`:
`ConvertedTextView` (`.docx`, `.pptx`, `.txt`, `.md`, `.html`), `SpreadsheetView` (`.xlsx`),
the existing PDF renderer's own OCR-panel branch for a scanned page, and
`UnrenderableFallback` for anything none of those claim. This ticket did not add a fifth
renderer for standalone image files — reading the code (`api/src/askwell/extract.py`) shows
there is no image extractor at all; "image" in this ticket's scope is a **scanned PDF
page**, whose OCR panel this ticket adds inside the existing PDF branch of
`document-viewer.tsx`, not a new file type.

**Where this stops on purpose.** Database result rendering is `M4`, out of scope
(`Out of Scope` line, ticket). `M1-VIEW-FE-046`'s own PDF-render-and-highlight path is
retested only as much as sharing `PageNav`/`UnrenderableFallback`/`highlightSpan`
(`web/components/documents/viewer-shared.tsx`) requires.

---

## Before you start

### 1. Make files to test with

```
mkdir -p ~/askwell-test/renderings
cd ~/askwell-test/renderings
```

A Markdown file with a real heading, to exercise heading anchoring:

```
cat > handbook.md <<'EOF'
# Leave policy

Staff accrue two days of leave per month worked, capped at twenty-four days.

# Expense policy

Receipts are required for any claim over twenty dollars.
EOF
```

A Word file with **no heading style used at all**, to exercise the no-headings edge case —
open a word processor (or `python3` with `python-docx`, already vendored for the API image;
any `.docx` writer works) and save a short, unstyled two-paragraph document as
`policy.docx`, e.g.:

```
python3 - <<'EOF'
from docx import Document
d = Document()
d.add_paragraph("The office closes at 6pm on weekdays.")
d.add_paragraph("Visitors must sign in at reception before entering.")
d.save("policy.docx")
EOF
```

A PowerPoint deck with a couple of slides, to exercise per-slide anchoring:

```
python3 - <<'EOF'
from pptx import Presentation
p = Presentation()
layout = p.slide_layouts[1]
s1 = p.slides.add_slide(layout)
s1.shapes.title.text = "Onboarding"
s1.placeholders[1].text_frame.text = "New starters get a laptop on day one."
s2 = p.slides.add_slide(layout)
s2.shapes.title.text = "Security"
s2.placeholders[1].text_frame.text = "Badges are required past the lobby."
p.save("onboarding.pptx")
EOF
```

A spreadsheet with enough rows to make virtualisation visible, and one distinctive row to
cite:

```
python3 - <<'EOF'
import openpyxl
wb = openpyxl.Workbook()
ws = wb.active
ws.append(["supplier", "amount"])
for i in range(1, 2000):
    ws.append([f"Vendor {i}", i])
ws.append(["Meridian Textiles", 48250])
for i in range(2001, 3000):
    ws.append([f"Vendor {i}", i])
wb.save("ledger.xlsx")
EOF
```

A scanned-looking PDF page, to exercise the OCR panel — a PDF page that is a single
embedded image with no text layer. If you have a scanner or phone-scan app, scan any page
of text to PDF; otherwise render a page of text to an image and place it alone in a PDF, so
pdf.js's own text layer comes back empty and this ticket's OCR branch fires:

```
python3 - <<'EOF'
from PIL import Image, ImageDraw
img = Image.new("RGB", (1000, 1300), "white")
d = ImageDraw.Draw(img)
d.text((60, 60), "Contract renews annually unless\nterminated with ninety days notice.", fill="black")
img.save("scan_page.pdf", "PDF")
EOF
```

An unrenderable file, to exercise the fallback — a legacy binary format nothing here
extracts:

```
cp /dev/null legacy.doc  # any pre-2007 .doc/.xls/.ppt on hand also works; a header-only stub is enough to prove the fallback, not to prove extraction
```

### 2. Point Askwell at the folder and bring up the stack

In `.env`:

```
ASKWELL_ROOTS_MOUNT=/home/<you>/askwell-test/renderings
```

```
podman compose up -d
scripts/dev.sh db upgrade head
scripts/dev.sh inference
```

---

## Part A — cold start, add the corpus, wait for it to index

### 3. Open Askwell and add the folder

Go to `http://127.0.0.1:8000`. Click **Add a source** (from Ask's first-run state, or the
left rail's **Library**). Drop the whole `~/askwell-test/renderings` folder, or add each
file individually. Answer the folder question with the folder's absolute path if asked.

**Expect:** a card for each of `handbook.md`, `policy.docx`, `onboarding.pptx`,
`ledger.xlsx`, `scan_page.pdf` and `legacy.doc` moves through *Detecting → Where are
these? → Recording → Queued*.

### 4. Wait for indexing

Go to **Library** and wait (refresh as needed) until every file except `legacy.doc` shows
as indexed. `legacy.doc` is expected to fail — `askwell.extract.UnsupportedForExtraction`
names pre-2007 binary Office as a known gap (issue #121) — confirm its row shows a named
failure reason, not a silent drop or a crash.

**Expect:** five of six documents reach ready; `legacy.doc` shows a failure state naming
that Askwell does not read older binary Office formats yet.

---

## Part B — Markdown, real heading anchoring

### 5. Ask a question that cites the Markdown file

Go to **Ask**. Ask: `What is the leave accrual policy?`

**Expect:** the answer cites `handbook.md`, with a citation card showing "Leave policy" (or
similar heading text) as its anchor label.

### 6. Click through to the source

Click the citation card.

**Expect:** you land on `/documents/?id=...`, titled `handbook.md`. Below the title, a
second heading reads **"Leave policy"** — the real Markdown heading, read from
`anchor_label`, not a generic "Section 1". The passage about leave accrual is visible and
marked (`<mark>`) inside the body text. `Previous`/`Next` page-nav buttons are present.

### 7. Step to the next section

Click **Next**.

**Expect:** the heading changes to **"Expense policy"** and the body shows the expense
paragraph, unmarked (no highlight — this section was not the cited one).

---

## Part C — Word file with no headings at all, the offset-fallback edge case

### 8. Ask a question that cites the Word file

Ask: `What time does the office close?`

**Expect:** the answer cites `policy.docx`.

### 9. Click through

Click the citation card.

**Expect:** `policy.docx` opens. In place of a heading, a note reads **"This document has
no headings here — showing the passage at its position in the document."** — the ticket's
own edge case ("a converted document with no headings — lands at the chunk position by
offset with a note"). The office-hours sentence is visible and marked.

---

## Part D — PowerPoint, per-slide anchoring

### 10. Ask a question that cites the deck

Ask: `What do new starters get on day one?`

**Expect:** the answer cites `onboarding.pptx`.

### 11. Click through

Click the citation card.

**Expect:** `onboarding.pptx` opens with heading **"Slide 1"** (or the real slide anchor
label python-pptx produced), the laptop sentence visible and marked. Click **Next**:
heading becomes **"Slide 2"**, showing the badges sentence, unmarked.

---

## Part E — spreadsheet, table with row highlight, virtualised

### 12. Ask a question that cites the ledger

Ask: `What amount is recorded for Meridian Textiles?`

**Expect:** the answer cites `ledger.xlsx`, naming the "Meridian Textiles" row.

### 13. Click through

Click the citation card.

**Expect:** `ledger.xlsx` opens as a scrollable table, not a text dump. The cited row
(Meridian Textiles, 48250) is visible, distinctly styled (`ask-row-highlight`), and
scrolled into view without you scrolling manually — the table did not open at row 1 with
~2,900 rows above the citation. Scroll the table up and down through the ~3,000 rows: rows
render and unrender as you scroll (check the browser's dev tools element inspector — the
live row count in the DOM stays in the few dozens, not 3,000) rather than the whole sheet
sitting in the DOM at once.

---

## Part F — scanned page, OCR text alongside

### 14. Ask a question the scan answers

Ask: `How long is the contract renewal notice period?`

**Expect:** the answer cites `scan_page.pdf`, or abstains if OCR on your machine read the
rendered text too poorly to match — if it abstains, open the document directly from
**Library** instead and skip to step 15.

### 15. Click through (or open directly)

**Expect:** the page image renders on the left, exactly as `M1-VIEW-FE-046`'s PDF renderer
already does. A note reads *"This page is a scan, so the citation points to the whole page
rather than to a passage on it."* Beside the image, a panel titled **"What Askwell read
from this page"** shows the OCR'd text — the ninety-days sentence, in some near-legible
form (OCR on a synthetic image is not guaranteed word-perfect; that it produced readable
text roughly matching the source is what to check, not an exact match).

### 16. Confirm a genuinely low-confidence read is flagged

If the OCR read poorly (garbled words), a note above the panel should read *"This scan read
poorly — Askwell has low confidence in the text below."* If your synthetic scan happened to
read cleanly, this note will correctly be absent — do not report its absence as a defect
unless the text is visibly garbled and the note is still missing.

---

## Part G — unrenderable file, extracted-text fallback plus external open

### 17. Open the file that failed extraction

`legacy.doc` never reached `ready`, so it will not be cited by an answer. Open it directly:
go to **Library**, find its row, and open it (or navigate to it the way a failed-source row
in this build lets you — click through from the row itself).

**Expect:** the viewer shows `legacy.doc`'s filename, a note that Askwell does not render
this format in the viewer yet (`document-viewer.tsx`'s `"unsupported"` state message), and
a button **"Open in system app"** linking to `/documents/{id}/file`. Click it — the raw
file downloads or opens in the browser's own handler, proving the link is real rather than
decorative.

---

## What was checked against the ticket's acceptance criteria

- Converted-text formats open at the cited anchor with content visible and marked —
  Parts B, C, D (Markdown with a real heading, Word with none, PowerPoint per-slide).
- A converted document with no headings lands at the chunk position with a note, not a
  guessed heading — Part C, step 9.
- A spreadsheet source opens as a table scrolled to the cited row, row marked, virtualised
  rather than fully mounted — Part E.
- An image (scanned page) source shows OCR text beside the image — Part F, step 15.
- A poor OCR read is flagged, not presented as equally reliable — Part F, step 16.
- An unrenderable file shows a note and an open-in-system-app option — Part G.
- No rendering fetches a remote asset — every screenshot/network check across Parts B–G
  should show requests only to `127.0.0.1:8000` (open the browser's network panel once
  during Part E or F to confirm; nothing here differs by format so one spot-check covers
  all of them).

## Known gaps

Do not report these as defects — they are out of scope for this ticket or stated
limitations of the extractors it depends on:

- **Office layout fidelity is not preserved.** `.docx`/`.pptx` render as converted text,
  never the original page or slide layout — the ticket's own stated assumption.
- **Database result rendering** is `M4`, not built yet.
- **Standalone image files (`.jpg`, `.png`, …) have no extractor.** `api/src/askwell/extract.py`
  dispatches on seven media types and none of them is an image type — "image" in this
  ticket is a scanned PDF page, covered by Part F. Adding a standalone-image source will
  fail extraction with "Askwell has no extractor for ...", which is `UnsupportedForExtraction`
  working as designed, not this ticket's gap to close.
- **`.docx` heading anchoring never actually anchors to a heading.** Reading
  `api/src/askwell/extract_docx.py`, its `Anchor.label` is only ever `None` or
  `"page N (approximate)"` — style-based headings are folded into `#`-prefixed body text,
  never lifted into `anchor_label`. Every `.docx` citation will show the "no headings here"
  note from Part C regardless of whether the source document actually has heading styles.
  This is a real gap worth its own issue (not filed as part of writing this test — filing it
  is a decision for whoever picks the follow-up up), not something to fix by editing this
  test to hide it.
- **Legacy binary Office (`.doc`, `.xls`, `.ppt`) never reaches the viewer as a citation** —
  extraction fails first, tracked as issue #121. Part G opens it directly from the library
  instead, which is the only way to reach the unrenderable-fallback path with the files this
  test builds.
- **OCR text quality on a synthetic test image is not representative** of a real scanned
  document — Part F accepts "roughly readable", not exact-match, and a real low-confidence
  scan is needed to see the poor-OCR note fire reliably.
- **No component test infrastructure exists in this repo** (`web/package.json`'s `test`
  script has no DOM/jsdom) — `ConvertedTextView`, `SpreadsheetView` and the OCR-panel branch
  of `document-viewer.tsx` are exercised here, live, and by `scripts/dev.sh web-check`'s
  build/lint/typecheck, not by an automated component test.
