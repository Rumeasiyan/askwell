# Manual test — M1-VIEW-FE-048, context rail, back to the answer, and citation stepping

**Ticket:** `M1-VIEW-FE-048` — the source viewer's right-hand context rail: which answer
and claim sent someone here, a return control, next/previous stepping across every passage
one answer cited (including across documents), search within the source, copy passage with
source and page, and ask-about-this-source.
**Version under test:** `0.2.32`
**Time:** about 25 minutes, with native inference running throughout.
**Who can run it:** anyone who can paste a line into a terminal and use a browser.

**What is being checked.** `web/components/documents/context-rail.tsx`'s `ContextRail`,
rendered by every branch of `document-viewer.tsx` (`ready`, `converted`, `spreadsheet`,
`unsupported`). It reads the live turn straight out of `AskProvider`
(`web/components/ask/ask-state.tsx`) by a `turn`/`claim`/`chunk` query-string group that
`web/lib/citations.ts`'s `documentHref` writes onto a citation card's link — nothing here
re-fetches the answer from the server. Stepping (`stepCitations`, same file) and the
"absent rather than inert" rule for a single citation are pure functions, checkable without
a browser, but this walkthrough exercises them live end to end. "Back to answer" hands off
to `web/components/ask/ask-screen.tsx`'s `ReturnToClaim`, which scrolls to the claim and
strips the query string.

**Where this stops on purpose.** The trace panel is `M5`. Editing memory from the rail is
`M3`. Both out of scope per the ticket.

---

## Before you start

### 1. Make two files whose facts split across an answer

```
mkdir -p ~/askwell-test/context-rail
cd ~/askwell-test/context-rail
```

A warranty document with **two separate facts on two different pages**, so one document
alone produces more than one citation. `reportlab` (already vendored for the API image's
PDF handling) writes a two-page text PDF directly — no scanned-image trick needed here,
unlike `M1-VIEW-FE-047`'s manual test, since this ticket needs a real text layer to cite:

```
python3 - <<'EOF'
from reportlab.pdfgen import canvas
c = canvas.Canvas("warranty.pdf", pagesize=(612, 792))
c.drawString(72, 700, "Standard warranty covers products for two years from the purchase date.")
c.showPage()
c.drawString(72, 700, "Customers may register for a five-year extended warranty within thirty")
c.drawString(72, 680, "days of purchase by submitting the enclosed registration card.")
c.showPage()
c.save()
EOF
```

A second document with an unrelated fact, so stepping has to cross documents, not just
pages:

```
python3 - <<'EOF'
from reportlab.pdfgen import canvas
c = canvas.Canvas("returns.pdf", pagesize=(612, 792))
c.drawString(72, 700, "Unused items may be returned within forty-five days of delivery for a full refund.")
c.showPage()
c.save()
EOF
```

### 2. Point Askwell at the folder and bring up the stack

In `.env`:

```
ASKWELL_ROOTS_MOUNT=/home/<you>/askwell-test/context-rail
```

```
podman compose up -d
scripts/dev.sh db upgrade head
scripts/dev.sh inference
```

---

## Part A — cold start, add the corpus, wait for it to index

### 3. Open Askwell and add the folder

Go to `http://127.0.0.1:8000`. Click **Add a source**. Drop `~/askwell-test/context-rail`
(or add `warranty.pdf` and `returns.pdf` individually). Answer the folder question with the
folder's absolute path if asked.

**Expect:** a card for each of `warranty.pdf` and `returns.pdf` moves through *Detecting →
Where are these? → Recording → Queued*.

### 4. Wait for indexing

Go to **Library** and wait (refresh as needed) until both files show as indexed.

**Expect:** both documents reach ready.

---

## Part B — one answer, three cited passages, two documents

### 5. Ask the three-part question

Go to **Ask**. Ask:

```
What is the standard warranty length, how do I register for the extended warranty, and what is the return window for unused items?
```

**Expect:** the answer addresses all three facts. The provenance margin shows citation
cards for `warranty.pdf` (at least two — one per page) and `returns.pdf`. If the model
folds two of the three facts into one cited sentence and only two cards appear, ask again
with the three facts split across three separate sentences ("First, ... Second, ... Third,
...") until three distinct cards show — the point of this walkthrough is the stepping
behaviour, not this exact phrasing.

### 6. Click the first citation card

Click the `warranty.pdf` card for the two-year warranty length.

**Expect:** you land on `/documents/?id=...&turn=...&claim=...&chunk=...`, `warranty.pdf`
open at page 1, the two-year sentence marked.

### 7. Read the rail's origin block

Look at the right-hand rail (**Source context**).

**Expect:**
- A small heading **"From your question"** above the exact question text you typed.
- A small heading **"Supporting the claim"** above the specific sentence from the answer
  that this passage supports (the two-year-warranty sentence, in quotes) — not the whole
  answer.
- A **"Back to answer"** button/link below that.

### 8. Read the stepper

**Expect:** a row reading **"Previous citation"**, a position count (**"1 of 3"** — or "1
of 2" if only two cards resulted from step 5), and **"Next citation"**. **Previous
citation** is visibly disabled (you are at the first passage).

### 9. Step forward within the same document

Click **Next citation**.

**Expect:** the URL's `chunk` parameter changes, `warranty.pdf` re-renders at page 2, the
extended-warranty sentence is marked, the rail's **"Supporting the claim"** text updates to
that sentence, and the position reads **"2 of 3"**. Both **Previous citation** and **Next
citation** are enabled.

### 10. Step forward across documents

Click **Next citation** again.

**Expect:** the document changes — the page now titled `returns.pdf`, at page 1, the
forty-five-day sentence marked. The rail's filename/source context follows the document
change (this is the ticket's own scope line: stepping "across documents where the answer
cited more than one"). Position reads **"3 of 3"**. **Next citation** is now visibly
disabled — present, but unclickable, not removed from the layout.

### 11. Return to the answer

Click **Back to answer**.

**Expect:** you land back on `/`, the query string is stripped (URL settles back to plain
`/`), and the page has scrolled to — and the browser's focus/highlight lands on — the exact
sentence about the forty-five-day return window inside the original answer, not the top of
the conversation and not a different claim. The full three-fact answer is still visible
above and below it, and the provenance margin still shows all three cards.

---

## Part C — a single-citation answer, stepper absent

### 12. Ask a question with exactly one fact to cite

Ask:

```
How long is the standard warranty?
```

**Expect:** the answer cites only `warranty.pdf` page 1 — one card in the margin.

### 13. Click through

Click the citation card.

**Expect:** the rail shows the origin block (question, claim, Back to answer) as before,
but **no stepper row at all** — no Previous/Next buttons, not even disabled ones. This is
the ticket's own edge case: "an answer with one citation — stepping controls are absent
rather than inert."

---

## Part D — the rail's other controls

Still on the page from step 13 (or step 6):

### 14. Search within the source

In the rail, find **"Search this source"**. Type a word that appears on the current page
(e.g. `warranty`) and press Enter, or click **Find**.

**Expect:** the browser's own in-page find behaviour jumps to/highlights that word on the
page (this uses the browser's native find, so it behaves like `Ctrl+F` would, not a custom
highlight).

### 15. Copy passage

Click **Copy passage**.

**Expect:** the button's label changes to **"Copied"** for about two seconds, then reverts.
Paste (e.g. into a text editor) — the clipboard contains the quoted passage text followed
by an em dash, the filename, and the page number, e.g.:
`"Standard warranty covers products for two years from the purchase date." — warranty.pdf, p. 1`

### 16. Ask about this source

Click **Ask about this source**.

**Expect:** you land back on **Ask**, the composer is empty (no question text was
pre-filled), and directly above the textarea a line reads **"Scoped to warranty.pdf"** with
a **Clear** link beside it. Type a question and submit — the answer should search only
`warranty.pdf`, not `returns.pdf` (ask something only `returns.pdf` would answer, e.g. the
return window, and confirm Askwell abstains or answers from general reasoning rather than
citing `returns.pdf`, since it is out of scope).

---

## Part E — arriving without a live turn: no broken return

### 17. Simulate a reload mid-viewer

From the state after step 6 (viewing `warranty.pdf` with a full rail), reload the browser
tab (`F5` / `Cmd+R`).

**Expect:** `AskProvider`'s in-memory conversation is gone (a hard reload always drops
client state that was never persisted — expected, not a bug). The rail no longer shows the
question/claim/Back-to-answer block; instead it shows a plain **"Source"** heading with just
the filename and page number. No broken link, no error, and no stepper (there is no turn to
step within).

**Note:** the ticket's edge case "arriving from the library rather than an answer" cannot
currently be walked end-to-end through the UI — see **Known gaps** below. Step 17
substitutes the one reachable way to reach the rail's no-turn fallback and checks the same
code path (`ContextRail`'s `turn === null` branch).

---

## Part F — a superseded source, banner and stepping both still work

This edge case ("a cited document that was superseded — the banner shows and stepping still
works") needs a document versioning decision the frontend's **Add a source** flow does not
yet surface (see **Known gaps**). To reach the state, replace the file on disk and re-add it
by calling the same endpoint the browser's own drop calls, choosing to supersede:

### 18. Change the file and re-index it as a new version

```
cd ~/askwell-test/context-rail
python3 - <<'EOF'
from reportlab.pdfgen import canvas
c = canvas.Canvas("warranty.pdf", pagesize=(612, 792))
c.drawString(72, 700, "Standard warranty now covers products for three years from the purchase date.")
c.showPage()
c.drawString(72, 700, "Customers may register for a five-year extended warranty within thirty")
c.drawString(72, 680, "days of purchase by submitting the enclosed registration card.")
c.showPage()
c.save()
EOF
curl -s -X POST http://127.0.0.1:8000/sources \
  -H 'Content-Type: application/json' \
  -d '{"folder": "/home/<you>/askwell-test/context-rail", "files": ["warranty.pdf"], "version_decisions": {"warranty.pdf": "supersede"}}'
```

Wait for the new `warranty.pdf` to finish indexing (**Library**, refresh until ready).

### 19. Reopen the old citation

Use the browser's back button (or re-click the original citation link from the answer in
step 6/9, if the tab still has that turn live) to reopen the **old** `warranty.pdf` version
at the two-year-warranty passage.

**Expect:** a banner above the document reads **"This version was replaced [on <date>].
Open the current version (warranty.pdf)"**, linking to the new document. The old page still
renders underneath it with the two-year sentence marked (old answers still resolve to what
they actually cited), and if that citation was part of a multi-citation answer, the
stepper still works — step to the next/previous citation and confirm it still navigates,
unaffected by this one card's document being superseded.

---

## What was checked against the ticket's acceptance criteria

- The rail names the originating answer (question) and claim — Part B, step 7.
- Return goes to the exact answer and claim, not the top of the conversation — Part B,
  step 11.
- Stepping moves to the next cited passage, including across documents — Part B, steps
  9–10.
- Copying a passage includes the source and page — Part D, step 15.
- Edge case: arriving without an answer in scope shows plain source context, no broken
  return — Part E.
- Edge case: a single-citation answer has no stepper, absent rather than disabled — Part C.
- Edge case: a superseded cited document shows the banner and stepping still works — Part F.
- No rendering fetches a remote asset — open the browser's network panel once during Part B
  or D; every request should be to `127.0.0.1:8000` only.

## Known gaps

Do not report these as defects — they are pre-existing gaps this ticket depends on but does
not itself close:

- **The library has no link into the document viewer yet.** Reading
  `web/components/library/library-screen.tsx`, no row opens `/documents/?id=...` — the only
  way in is a citation card, which is why Part E reloads the tab instead of the ticket's own
  "arriving from the library" scenario. `ContextRail`'s own comment in
  `context-rail.tsx` names this directly: "No `turn` query parameter (the library, **once
  it links here**) ... both fall through to plain source context." The fallback code this
  ticket built is exercised (Part E); the library entry point it is written for is not
  built yet. Worth its own follow-up issue if one is not already open.
- **The Add-a-source flow has no UI for the version decision.** `api/src/askwell/sources.py`'s
  `AddRequest.version_decisions` and its docstring describe an "offered again, not guessed
  at" prompt for a changed file, but no component in `web/components/add/` sends anything
  but an empty `version_decisions`. Part F reaches the superseded state with a direct
  `curl` to `/sources` rather than through **Add a source**, because that is currently the
  only way to reach it at all. This is the same endpoint the browser's own directory-drop
  call hits — no bytes are uploaded, same as the ordinary flow — but it is not something a
  non-technical user could do today, which is itself a gap worth its own issue.
- **Return-scroll precision was checked visually, not pixel-measured.** "Restore the exact
  scroll position" (Validation Rules) was checked as "the claim sentence is on screen and
  visually distinguished after return," not by comparing scroll offsets — this repo has no
  component test harness (`web/package.json`'s `test` script has no DOM/jsdom) to assert
  that more precisely, same limitation noted in `M1-VIEW-FE-047`'s manual test.
- **`window.find` search behaviour is browser-dependent.** It is deprecated in some
  browsers' own documentation, though still implemented; Part D's search step should be run
  in the same browser the rest of this walkthrough uses, and a browser where it is entirely
  absent will show the input disabled — that is the ticket's own graceful-degradation path,
  not a defect.
