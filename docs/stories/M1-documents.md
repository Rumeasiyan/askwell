# M1 — It answers from my documents

**Ends with:** add a PDF, ask about it, get a cited answer, click the citation and land on the page.

Phase 1 (`../build-plan.md`). Depends on M0.

> **Sample milestone.** M1.1–M1.5 below are written in full to fix the format. The remaining milestones follow once the format is agreed.

---

## M1.1 — I can add a PDF and watch it index

*As someone whose contracts are all PDFs, I want to drop one into Askwell and see it being read, so that I know it is working before I ask anything.*

**Estimate:** 3h · **Depends on:** M0.3 (app shell)

### Acceptance

- **Given** Askwell is running with no sources, **when** I drop a PDF onto the window, **then** it appears in the library with status *indexing* and a per-file progress indicator.
- **Given** a PDF is indexing, **when** I navigate to another screen and back, **then** it is still indexing — ingestion is a background job and does not belong to the page.
- **Given** indexing finishes, **when** I look at the library, **then** the source shows *indexed*, its page count, and when it was added.
- **Given** I drop a file type Askwell does not handle, **then** it is rejected by name with the supported list, and nothing is added.

### In scope
Drag-and-drop and file-browse, text-layer PDF extraction, structure-aware chunking, progress, the library row.

### Out of scope
OCR (M1.2), embedding (M1.3), CSV and dumps (M4), duplicate detection (M1.6), indexing in place vs copy — assume in place, path stored.

### Constraints
`documents.path` is stored from the start (`../architecture.md` §7). Retrofitting it after files exist means a migration on someone's own machine.

### Manual test
1. Launch Askwell from a cold start.
2. Land on the library, which is empty and invites a first source.
3. Drag `supplier-agreement-2024.pdf` onto the window.
4. **Expect:** the row appears, status *indexing*, progress moving.
5. Click *Ask*, then back to the library. **Expect:** still indexing, progress advanced.
6. Wait for completion. **Expect:** *indexed*, page count shown, added-time shown.
7. Drag a `.zip` on. **Expect:** rejected by name, supported formats listed, no row added.

**Known gaps:** the PDF is not searchable yet. Asking about it does nothing useful. Scanned PDFs extract nothing.

---

## M1.2 — A scanned PDF is read too

*As someone whose older contracts were scanned, I want those read as well, so that half my archive is not invisible.*

**Estimate:** 3h · **Depends on:** M1.1

### Acceptance

- **Given** a scanned PDF with no text layer, **when** it indexes, **then** OCR runs and the extracted text is stored per page.
- **Given** OCR yields very little text, **then** the source is marked *needs attention* with the reason, and remains indexed rather than failing.
- **Given** a page is upside down, **then** it is still read — orientation is detected.

### Out of scope
The clarification raised by poor OCR (M3), highlighting OCR text in the viewer (M1.5), Tamil OCR — the `tam` data is bundled as a hedge and is not a feature (`../PRD.md` §8).

### Manual test
1. Cold start. Add `scanned-invoice-2019.pdf`.
2. **Expect:** indexing takes visibly longer than a text PDF; it completes.
3. **Expect:** page count matches the real document.
4. Add a deliberately poor scan. **Expect:** *needs attention*, reason readable, still listed as indexed.

**Known gaps:** still not searchable. No clarification is raised about the poor scan.

---

## M1.3 — I can ask a question and get an answer from my PDF

*As someone who cannot remember which contract said what, I want to ask in plain English and get an answer, so that I stop opening files one at a time.*

**Estimate:** 3h · **Depends on:** M1.1, M0.4 (model serving)

### Acceptance

- **Given** an indexed PDF, **when** I ask a question it covers, **then** an answer streams token by token.
- **Given** a question is running, **then** named retrieval steps appear before the first token — *searching your files*, *reading 2 sources*.
- **Given** the model is slow, **then** the steps keep updating so working is distinguishable from hung.
- **Given** I navigate away mid-answer, **when** I return, **then** the answer completed and is in the conversation (#14).

### In scope
Embedding, hybrid retrieval, reranking, the answer path, streaming, step labels.

### Out of scope
Citations (M1.4) — **the answer is ungrounded at this point and that is temporary**. Abstention (M2.1). Memory (M3). Databases (M4).

### Constraints
C4 is not satisfied until M1.4. This story must not ship to anyone as a usable state — it exists to make the answer path demonstrable before citations are wired, and M1.4 follows immediately.

### Manual test
1. Cold start. Confirm the PDF from M1.1 is still indexed.
2. Go to Ask. Type *"What payment terms did we agree with Meridian Foods?"*
3. **Expect:** step labels within a second; first token within a few seconds; answer streams.
4. **Expect:** the answer states 45 days — the value that is actually in the document.
5. Ask again, navigate away immediately, come back. **Expect:** the answer completed.

**Known gaps:** no sources shown. No way to check the answer. If the corpus does not cover the question the model will invent something — abstention is M2.1.

---

## M1.4 — I can see where an answer came from

*As someone who has to be right about a client's contract, I want every claim to show its source, so that I can check it rather than trust it.*

**Estimate:** 3h · **Depends on:** M1.3

### Acceptance

- **Given** an answer with claims from documents, **then** each cited claim has a source card in the right margin showing filename, page and the exact retrieved passage.
- **Given** an answer is on screen, **then** the margin is present — populated or explicitly empty. **It is never hidden and never a toggle.**
- **Given** I hover a claim, **then** its leader and card highlight.
- **Given** the window narrows below the three-column breakpoint, **then** cards move inline beneath each answer. **They are not removed** — citations are not conditional on window width.
- **Given** an answer is stored, **then** its citations are rows in `citations`, queryable, not buried in trace JSON.

### Out of scope
Clicking through to the document (M1.5). Memory chips (M3). SQL disclosure (M4).

### Constraints
**C4.** This is the story where the product's central claim becomes true. The `citations` table is what makes "did any answer contain an uncited claim?" answerable, which `../success-metrics.md` §2 tracks at 100%.

### Manual test
1. Cold start. Ask the M1.3 question again.
2. **Expect:** answer streams, and cards appear in the margin as claims are cited.
3. **Expect:** each card shows `supplier-agreement-2024.pdf`, a page number, and a passage that really is on that page — open the file separately and check.
4. Hover a claim. **Expect:** its leader and card highlight; others do not.
5. Narrow the window. **Expect:** cards move inline, none disappear.

**Known gaps:** cards are not clickable yet. Nothing verifies that *every* claim is cited — that check arrives with the eval suite.

---

## M1.5 — I can click a citation and land on the page

*As someone checking an answer, I want one click to put me on the page with the passage highlighted, so that checking is cheap enough that I actually do it.*

**Estimate:** 3h · **Depends on:** M1.4

### Acceptance

- **Given** a source card, **when** I click it, **then** the document opens at that page with the passage highlighted, in under a second.
- **Given** I am in the viewer, **then** there is an obvious way back to the answer I came from.
- **Given** an answer cited several passages, **then** I can step through them without returning to the answer.
- **Given** the file has been moved or renamed on disk, **then** the viewer says which path is missing and offers to relocate it — **not** that the document was deleted.

### Out of scope
Deleted-source tombstones (M2.4). OCR text beside scans (M1.6). Database results (M4).

### Constraints
Indexing in place makes stale paths normal, so the missing-file state is required here, not later (`../ux/source-viewer.md` §4).

### Manual test
1. Cold start. Ask the question. Click the first source card.
2. **Expect:** the PDF opens at page 14, passage highlighted, quickly.
3. **Expect:** the way back is visible without hunting.
4. Step to the next citation. **Expect:** it moves to the other cited passage.
5. Quit Askwell, rename the PDF on disk, restart, click the card again.
6. **Expect:** *"this file has moved"* naming the old path, with a relocate action — **not** *deleted*.

**Known gaps:** relocate may be manual file-picking. Scanned PDFs highlight at page level, not passage level.
