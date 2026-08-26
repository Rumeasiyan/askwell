# M1 — It answers from my documents

**Goal:** Add a PDF, watch it index, ask about it, get a cited answer, click the citation and land on the page with the passage highlighted.

**Phase:** 1 (`../build-plan.md`) · **Depends on:** M0 · **Tickets:** 37 · **Estimated:** 113–164 hours

**Exit condition:** From a clean install, a user nominates a folder, adds a scanned English PDF, watches it index, asks a question it covers, receives a streamed answer whose every factual claim carries a source card naming file and page, clicks a card and lands on the highlighted passage in under a second, and renames the file on disk to see the moved-file state rather than a deletion.

## Included epics

| Epic | Code | Covers |
| ---- | ---- | ------ |
| Adding a source | `ADD` | Path registration, add-source screen, duplicate detection, background ingestion |
| Extraction | `EXTRACT` | PDF, Office, text, OCR, failure states |
| Indexing | `INDEX` | Chunking, embedding, full-text, supersession |
| Asking | `ASK` | Retrieval, reranking, streaming, prompts, interaction records |
| Citations | `CITE` | Citation extraction, the provenance margin, the uncited-claim query |
| Source viewer | `VIEW` | In-app rendering, navigation, moved files |
| Library and first run | `LIB` | Inventory, statuses, empty states, the first ten minutes |
| Conversation | `CONV` | Stored turn summaries, collapsing past turns, expanding, suggested follow-ups |

---

### M1-ADD-ING-021 — Nominate root directories as known mounts at add time

**Type:** Story

**User Story**
- **Actor:** someone with 40 GB of case files who is not moving them anywhere.
- **User Need:** Askwell to read files where they are without being given the whole disk.
- **Business Value:** indexing in place is a stated promise on the first-run screen; the container needs a route to those files that is narrow and explicit.
- *As someone whose files live in one folder tree I do not want to reorganise, I want to nominate that tree once, so that Askwell can read it without having access to everything else.*

**Context / Background**
**Detailed Description:** Askwell indexes in place rather than copying. The API and worker run in containers, so a nominated root directory becomes a known mount rather than the container having open filesystem access. Adding a file under an unregistered root prompts to register its root first. **No screen specification currently covers path registration** — this ticket writes it against the existing add-source shape rather than inventing a new screen.

**The native directory picker is why the desktop shell exists** (`../decisions.md`, 2026-08-26). Nominating a root is one of the two paths the Tauri shell was justified by, and the other is relocating a moved file (M1-VIEW-BE-049). The shell does not exist until M7, so this ticket builds the registry and the flow against a typed or browser-selected path and **is deliberately shaped so the picker replaces only the selection step** — M7-TAURI-FE-182 swaps it in without touching the registry, the validation or the consequences of removing a root. Building the registry around a browser upload control instead would have to be undone.

**Scope**
- A registry of nominated root directories with their mount state.
- Registration flow reachable from the add-source screen when a file falls outside every known root.
- Validation that a root is readable and that registering it does not require restarting the stack where avoidable.
- Removal of a root, with the consequence stated: its sources become unreadable, not deleted.

**Out of Scope**
- Folder watching and re-indexing on change (open in `../ux/add-source.md` §6).
- The native directory dialog itself (M7-TAURI-FE-182).
- Installer-side registration (M7).
- Any file copying — there is none.

**Acceptance Criteria**
- **Acceptance Criteria:** A user can nominate a root directory and then add files from anywhere under it. A file outside every root prompts registration rather than failing obscurely. Registered roots are listed and removable. Removing a root leaves its sources listed with a stated unreadable reason rather than deleting them.
- **Edge Cases:** A root on removable media that is currently unmounted — sources under it report unavailable, distinct from moved and from deleted. A root nested inside an already-registered root — recognised and not double-registered. A root the user has no permission to read — refused at registration with the reason. A network share — permitted, with a stated warning that indexing will be slow and the share must be present at query time for the viewer.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/add-source.md` §1 states indexing is in place; §5 covers the failure states this flow inherits. `../states-and-edge-cases.md` §3 for the ingestion states.
- **Validation Rules:** A root must be an existing readable directory. A path outside every registered root is never read.
- **Audit / Logging Requirements:** Registering and removing a root are decisions records — they are source configuration changes.
- **Analytics Events:** Local counter of registered roots only — nothing transmitted (C1).

**Real-World Example Scenarios**
- A consultant nominates their client folder once and thereafter drags files in freely.
- A user drags a file from a USB drive that was never registered and is asked to nominate it, with the consequence explained.

**Dependencies & Assumptions**
- **Dependencies:** M0-SHELL-FE-017, M0-DATA-OBS-015.
- **API / Data Touchpoints:** `sources.root_path`; a roots registry in `settings` or its own store.
- **Assumptions:** **Explicit assumption, carried from the stack decision:** the user nominates roots at add time and these become known mounts, rather than the container having open filesystem access. This is safer and is the only approach that works with a virtual machine in the path on macOS and Windows.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Launch Askwell from a cold start on a machine with no sources. Go to add a source and drag in a file from an unregistered folder. Observe a prompt to nominate that folder, with a plain explanation. Accept, and observe the file proceed to indexing. Add a second file from the same folder and observe no second prompt. Open settings and see the folder listed.
- **Other scenarios:** Unmount a removable root and observe its sources reported unavailable rather than deleted. Remove a root and confirm sources say so.
- **Known gaps:** No folder watching. Registration may require a stack restart on some platforms; if so it is stated at the moment of registration rather than discovered. **Selection is by typed or browser-provided path until the desktop shell ships** — a directory cannot be chosen from a real system dialog until M7-TAURI-FE-182, and until then a path the browser will not surface must be typed. That is a known gap, not a defect.

**Effort & Granularity Check**
- **Estimate:** 4–6 hours · **Priority:** Critical
- **Labels / Component:** `phase:1`, ingestion, deployment
- **Granularity:** One registry plus one flow. Upper bound because container mount behaviour differs by platform.

---

### M1-ADD-FE-022 — Add-source screen, files route, drag-and-drop anywhere

**Type:** Story

**User Story**
- **Actor:** someone with a folder of PDFs and no patience for a wizard.
- **User Need:** to drop files onto the window and have them read.
- **Business Value:** the first source added is the whole funnel; friction here loses the user before anything else gets a chance.
- *As someone whose contracts are all PDFs, I want to drop one onto the window, so that adding material is one gesture.*

**Context / Background**
**Detailed Description:** Build the add-source screen's shape and its files route. Drag-and-drop works anywhere in the application, not only on this screen. Askwell picks the route from the file type so the user rarely chooses. The screen states once that indexing is in place, because someone about to add a large library needs to know before they start.

**Scope**
- Add-source screen with the four routes present, files route functional and the other three visibly present but arriving in M4.
- Application-wide drop target with a clear drop affordance.
- File-browse alternative.
- The in-place statement.

**Out of Scope**
- CSV, dump and connection routes (M4).
- Progress rendering (M1-ADD-ING-025).
- Clarifications raised by ingestion (M3).

**Acceptance Criteria**
- **Acceptance Criteria:** Dropping supported files anywhere in the application starts adding them. The browse alternative works. The screen states indexing is in place. The three later routes are visible and explain that they arrive later rather than being hidden.
- **Edge Cases:** A folder dropped rather than files — accepted and expanded, with a count shown before starting. A very large number of files dropped — accepted with a count and an honest estimate, not a frozen window. A drop while another add is in progress — queued, not rejected.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/add-source.md` §1, §2 and §5 (idle, dropped-detecting).
- **Validation Rules:** Type detection by content as well as extension, so a mislabelled file is handled honestly.
- **Audit / Logging Requirements:** Source added is a decisions record.
- **Analytics Events:** Local counter of sources added — nothing transmitted (C1).

**Real-World Example Scenarios**
- The user drags a folder of 60 contracts onto the Ask screen and the add flow takes over correctly, without them navigating anywhere first.

**Dependencies & Assumptions**
- **Dependencies:** M1-ADD-ING-021, M0-SHELL-FE-017.
- **API / Data Touchpoints:** `sources`, `documents`.
- **Assumptions:** The browser's drop event gives usable paths under every supported platform; where it does not, the browse path is the fallback and is stated. **The browse alternative is a placeholder for the native file dialog**, which the desktop shell provides in M7-TAURI-FE-182; this ticket keeps selection behind one seam so that swap is a replacement rather than a rewrite. It is not a file *upload* control and must never become one — Askwell indexes in place and copies nothing.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Launch cold, land on the empty state, and drag a single PDF onto the window from the desktop. Observe the drop affordance appear and the file accepted. Then drag a folder of several files and observe a count before it starts. Use the browse button and confirm the same result.
- **Other scenarios:** Drop while a previous add is running.
- **Known gaps:** Nothing is extracted or searchable yet. The other three routes do nothing. Browsing for files uses whatever the browser provides until the native dialog arrives in M7-TAURI-FE-182.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** Critical
- **Labels / Component:** `phase:1`, frontend, ingestion
- **Granularity:** One screen, one route, one global drop target.

---

### M1-ADD-BE-023 — Source and document records with content-hash duplicate detection

**Type:** Story

**User Story**
- **Actor:** someone who has the same contract in three folders.
- **User Need:** the same file recognised rather than indexed three times.
- **Business Value:** duplicate chunks pollute retrieval and make citations ambiguous.
- *As someone whose filing is not tidy, I want Askwell to notice it already has this file, so that answers do not cite the same passage three times.*

**Context / Background**
**Detailed Description:** Create source and document rows on add, computing a content hash for each file. A file whose hash already exists as a live document is recognised, linked to the existing document and not re-ingested. The database's partial unique index enforces one live version per source and hash independently of this code path.

**Scope**
- Source and document row creation with path, filename, mime, hash and added time.
- Duplicate recognition with a clear user-facing outcome linking to the existing document.
- Status transitions from queued through indexing to indexed or attention.

**Out of Scope**
- Supersession of a changed file (M1-INDEX-BE-034).
- Deletion (M2).

**Acceptance Criteria**
- **Acceptance Criteria:** Adding a file creates a document row with its path and hash. Adding the identical file again is recognised by content and links to the existing document rather than creating a second. The status reflects the real stage of processing.
- **Edge Cases:** The same content under two names — recognised as duplicate content, and both paths are shown so the user is not confused about which one is indexed. A file that changes between hashing and reading — detected and re-hashed rather than indexed inconsistently. A zero-byte file — rejected with the reason.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/add-source.md` §5 duplicate row; `../states-and-edge-cases.md` §3 duplicate.
- **Validation Rules:** Hash computed over content, never over the name or the modification time.
- **Audit / Logging Requirements:** Document added is a decisions record with the path.
- **Analytics Events:** Local counter only — nothing transmitted (C1).

**Real-World Example Scenarios**
- A user drops a folder containing both `contract.pdf` and `contract copy.pdf` with identical content; one is indexed and the other is named as already present.

**Dependencies & Assumptions**
- **Dependencies:** M1-ADD-FE-022, M0-DATA-DB-014.
- **API / Data Touchpoints:** `sources`, `documents`.
- **Assumptions:** Hashing a large file is fast enough to happen before indexing rather than during it.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, add a PDF, wait for it to be listed. Add the exact same file again from a different folder. Observe it is named as already present, linked to the existing entry, and that the library still shows one document.
- **Other scenarios:** Add a zero-byte file and read the rejection.
- **Known gaps:** A modified version of the same file is not yet handled as a supersession.

**Effort & Granularity Check**
- **Estimate:** 2–3 hours · **Priority:** High
- **Labels / Component:** `phase:1`, backend, database
- **Granularity:** One record path plus one recognition rule.

---

### M1-ADD-VAL-024 — Reject unsupported formats by name with the supported list

**Type:** Task

**User Story**
- **Actor:** someone who dropped an archive expecting it to be unpacked.
- **User Need:** to be told what happened and what would work.
- **Business Value:** a bare rejection is how someone concludes the product does not handle their material.
- *As someone whose files are a mixture of everything, I want a rejection that names the file and tells me what is supported, so that I know what to do next.*

**Context / Background**
**Detailed Description:** Unsupported formats are rejected at add time, naming the file and listing what is supported. Nothing is added. Where a route out exists — a spreadsheet exported as CSV, a MySQL dump connected to directly — the message names it. Formats supported in M1 are PDF, Word, Excel, PowerPoint, plain text, Markdown, HTML and images; CSV and dumps arrive in M4 and are named as arriving rather than as unsupported.

**Scope**
- Content-based type detection and the rejection path.
- Message naming the file, the detected type, and the supported list.
- Per-file rejection within a multi-file drop, so one bad file does not reject the batch.

**Out of Scope**
- The dump-specific refusal message (M4).
- Password-protected files, which are a failure rather than an unsupported format (M1-EXTRACT-VAL-030).

**Acceptance Criteria**
- **Acceptance Criteria:** An unsupported file is rejected by name with the supported list and nothing is added for it. Other files in the same drop proceed. A file whose extension lies about its content is judged on content.
- **Edge Cases:** An empty drop. A file type that is supported but whose content is corrupt — that is an extraction failure, not a rejection, and must be routed correctly. A type arriving in a later milestone — named as coming, not as unsupported.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/add-source.md` §5 unsupported format; `../states-and-edge-cases.md` §3.
- **Validation Rules:** Detection by content signature first, extension second.
- **Audit / Logging Requirements:** Rejections are logged; they are not decisions records because nothing changed.
- **Analytics Events:** Local counter only — nothing transmitted (C1).

**Real-World Example Scenarios**
- A user drops a zip of contracts; it is rejected by name with the supported list, and they unzip and re-drop.

**Dependencies & Assumptions**
- **Dependencies:** M1-ADD-BE-023.
- **API / Data Touchpoints:** None beyond detection.
- **Assumptions:** Content detection is reliable for the supported set.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, drag a zip file and a PDF together onto the window. Observe the zip named and rejected with the supported list, and the PDF proceeding normally. Confirm the library shows only the PDF.
- **Other scenarios:** Rename a zip to `.pdf` and drop it — still rejected on content.
- **Known gaps:** CSV and dumps report as arriving later rather than working.

**Effort & Granularity Check**
- **Estimate:** 1–2 hours · **Priority:** High
- **Labels / Component:** `phase:1`, validation
- **Granularity:** One detection and one message.

---

### M1-ADD-ING-025 — Background ingestion with per-file progress that survives navigation

**Type:** Story

**User Story**
- **Actor:** someone who added 500 files and went to make tea.
- **User Need:** ingestion that does not belong to the page they are looking at.
- **Business Value:** blocking on a page is how a large import dies when someone navigates away.
- *As someone importing a large archive, I want indexing to continue while I use the rest of Askwell, so that I am not held hostage by a progress bar.*

**Context / Background**
**Detailed Description:** Ingestion runs as a background job on the worker. Progress is per file, with a running count and a queue position and an honest estimate that acknowledges CPU embedding can take hours. Navigating away does not cancel. The source becomes askable before ingestion finishes, with partial coverage shown.

**Scope**
- Job enqueue per document with ordering and a concurrency limit suited to one laptop.
- Per-file progress and queue position, streamed to the browser.
- Partial-coverage marker so the source is askable early.
- Resume after a stack restart rather than losing queued work.

**Out of Scope**
- The extraction and embedding steps themselves (their own tickets).
- Disk budget refusal (M7).

**Acceptance Criteria**
- **Acceptance Criteria:** Progress advances per file and continues while the user navigates elsewhere and returns. A queue estimate is shown and is honest rather than optimistic. The source is marked askable with partial coverage before all files finish. A stack restart resumes rather than loses the queue.
- **Edge Cases:** A single enormous file — progress within the file, not just between files, so it does not look hung. A job that fails — visible with its error and a retry, never silently dropped. The machine sleeps mid-import — the queue resumes on wake.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/add-source.md` §5 indexing and partly-indexed; `../states-and-edge-cases.md` §3 upload in progress and queued behind a backlog.
- **Validation Rules:** Concurrency is bounded so the machine remains usable — this laptop is also running the user's browser.
- **Audit / Logging Requirements:** Job start, completion and failure are logged; source status changes are decisions records.
- **Analytics Events:** Local counters for documents ingested and failed — nothing transmitted (C1).

**Real-World Example Scenarios**
- A user imports 500 papers, goes to Ask, and gets answers from the first 80 while the rest continue.

**Dependencies & Assumptions**
- **Dependencies:** M0-STACK-DEPLOY-009, M1-ADD-BE-023.
- **API / Data Touchpoints:** Queue; `documents.status`; streaming progress surface.
- **Assumptions:** Server-sent streaming is adequate for progress; no bidirectional channel is needed until voice.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, drop a folder of a dozen PDFs, and watch per-file progress with a running count. Navigate to Ask, wait, and return to the library — progress has advanced. Stop the stack mid-import, start it again, and confirm the remaining files resume rather than restarting from the beginning.
- **Other scenarios:** Add one very large PDF and confirm progress moves within the file.
- **Known gaps:** No estimate accuracy guarantee on first run, since there is no throughput history. Disk budget refusal is not implemented.

**Effort & Granularity Check**
- **Estimate:** 4–6 hours · **Priority:** Critical
- **Labels / Component:** `phase:1`, ingestion, backend
- **Granularity:** Queue, progress, partial coverage, resume. Upper bound.

---

### M1-EXTRACT-ING-026 — PDF text-layer extraction

**Type:** Story

**User Story**
- **Actor:** someone whose contracts are digital PDFs.
- **User Need:** the text read accurately with page numbers preserved.
- **Business Value:** page numbers are half of every citation; extraction that loses them makes the citation loop impossible.
- *As someone who needs to cite page 14 of a contract, I want extraction to keep the page a passage came from, so that the citation lands somewhere real.*

**Context / Background**
**Detailed Description:** Extract text from PDFs with a text layer using pypdfium2. PyMuPDF was rejected because it is AGPL and would force Askwell off Apache-2.0; the accepted cost is that passage-level coordinates are harder, which is why scanned-page highlighting starts at page level. Extraction preserves page boundaries, reading order, and enough structure for the chunker to find headings.

**Scope**
- Page-by-page text extraction with page numbers retained.
- Reading-order handling for multi-column layouts, with a stated limit.
- Page count recorded on the document.
- Detection of a PDF with no usable text layer, handing off to OCR.

**Out of Scope**
- OCR itself (M1-EXTRACT-ING-028).
- Chunking (M1-INDEX-ING-031).
- Passage-level coordinate mapping for highlighting (M1-VIEW-FE-046 handles the text-layer case; scans stay page-level).

**Acceptance Criteria**
- **Acceptance Criteria:** A text-layer PDF yields text per page with correct page numbers and a page count matching the document. A PDF with no text layer is identified and routed to OCR rather than indexed empty.
- **Edge Cases:** A PDF with a text layer on some pages only — mixed handling per page, not per document. A PDF with rotated pages — text extracted in the correct orientation. A PDF with embedded fonts that produce unusable characters — treated as no usable text and routed to OCR. A 900-page document — extracted with progress rather than one long silence.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** Progress per file (M1-ADD-ING-025); failure states in `../ux/add-source.md` §5.
- **Validation Rules:** A page yielding no text is recorded as such rather than skipped, so the OCR decision is per page.
- **Audit / Logging Requirements:** Extraction outcome per document is logged.
- **Analytics Events:** Local counter only — nothing transmitted (C1).

**Real-World Example Scenarios**
- A 200-page supply agreement extracts with page numbers matching the printed footer numbering the user sees.

**Dependencies & Assumptions**
- **Dependencies:** M1-ADD-ING-025.
- **API / Data Touchpoints:** `documents.page_count`; extracted text handed to chunking.
- **Assumptions:** pypdfium2 covers extraction and page rendering for OCR; the licence position is the reason and is recorded in the decision log.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, add a digital PDF whose content you know. When indexing completes, open the library and confirm the page count matches the real document. Open the source viewer and confirm page 14 shows the text you expect.
- **Other scenarios:** Add a mixed PDF with scanned and digital pages and confirm both are handled.
- **Known gaps:** Multi-column reading order is best-effort. Nothing is searchable yet.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** Critical
- **Labels / Component:** `phase:1`, ingestion
- **Granularity:** One format, one extractor.

---

### M1-EXTRACT-ING-027 — Word, PowerPoint, spreadsheet, text, Markdown and HTML extraction

**Type:** Story

**User Story**
- **Actor:** someone whose archive is not all PDFs.
- **User Need:** their Word documents and slide decks read too.
- **Business Value:** an archive that is half invisible is not worth keeping the product for.
- *As someone whose reports are Word files and whose proposals are slide decks, I want those read as well, so that the answer is not silently limited to my PDFs.*

**Context / Background**
**Detailed Description:** Extract from Office and text formats using the format-specific libraries chosen at scaffold: Word, PowerPoint and Excel each have their own, with plain text, Markdown and HTML handled directly. Structure matters more than raw text — headings, table boundaries, slide boundaries and list items are what the chunker needs. Excel here is a document-style read; spreadsheets as queryable data arrive in M4.

**Scope**
- Extraction for each format with structural markers preserved.
- A page-equivalent anchor per format: page for Word where paginated, slide number for decks, sheet and row for spreadsheets, heading anchor for text and Markdown and HTML.
- Recording which anchor kind a document uses, so the viewer knows how to land.

**Out of Scope**
- Spreadsheet as a queryable table (M4).
- Multi-sheet and merged-cell semantics, which are an open question (`../data-sources.md` §8) — this ticket extracts what it can and records the limitation.

**Acceptance Criteria**
- **Acceptance Criteria:** Each format yields text with its structural markers and an anchor the viewer can use. A document from each format can be added and reaches indexed. The anchor kind is recorded per document.
- **Edge Cases:** A Word document with tracked changes — the accepted text is used and the presence of revisions is noted. A deck with speaker notes — included and labelled. An HTML file with scripts and navigation — content extracted, chrome discarded. A Markdown file with front matter — treated as metadata, not prose.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/source-viewer.md` §2 rendering table.
- **Validation Rules:** A document yielding no text at all is a failure with a reason, never an empty indexed document.
- **Audit / Logging Requirements:** Extraction outcome per document is logged.
- **Analytics Events:** Local counter only — nothing transmitted (C1).

**Real-World Example Scenarios**
- A researcher adds a slide deck and later gets an answer citing slide 12 rather than an unusable character offset.

**Dependencies & Assumptions**
- **Dependencies:** M1-EXTRACT-ING-026.
- **API / Data Touchpoints:** Extracted text and anchors; `documents`.
- **Assumptions:** Word pagination is approximate and the anchor is honest about that rather than claiming a page number it cannot guarantee.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, add one file of each supported non-PDF type. Watch each reach indexed. Open each in the source viewer and confirm the content is readable and structured — headings look like headings, tables are intact.
- **Other scenarios:** Add an HTML page saved from a browser and confirm the navigation chrome is not in the extracted text.
- **Known gaps:** Merged cells and multi-sheet workbooks are handled crudely and flagged. Excel is not queryable until M4.

**Effort & Granularity Check**
- **Estimate:** 4–6 hours · **Priority:** High
- **Labels / Component:** `phase:1`, ingestion
- **Granularity:** Six formats sharing one structural contract. Upper bound.

---

### M1-EXTRACT-ING-028 — OCR fallback with orientation detection

**Type:** Story

**User Story**
- **Actor:** someone whose older contracts were scanned in 2009.
- **User Need:** those read too.
- **Business Value:** half the archive being invisible is the most common reason a document tool feels useless on a real corpus.
- *As someone whose older contracts were scanned, I want those read as well, so that half my archive is not invisible.*

**Context / Background**
**Detailed Description:** Pages with no usable text layer are rendered to images and passed through Tesseract with orientation detection, so an upside-down page is still read. Text is stored per page. The Tamil traineddata is bundled as a hedge, not a feature — it is not tested, not advertised, and a Tamil scan is marked as a not-supported language.

**Scope**
- Page rendering for OCR and the OCR pass itself.
- Orientation and script detection before recognition.
- Per-page text storage with the same anchors as text-layer extraction.
- Marking a document as OCR-derived so later screens can show the source image beside the text.

**Out of Scope**
- Low-confidence flagging (M1-EXTRACT-ING-029).
- The clarification raised by a poor scan (M3).
- Mapping OCR text back to pixel regions — scans highlight at page level, and passage-level on scans is a separate later story.

**Acceptance Criteria**
- **Acceptance Criteria:** A scanned PDF with no text layer produces text per page. A page scanned upside down is read correctly. Page count matches the real document. The document is marked as OCR-derived.
- **Edge Cases:** A page that is a photograph with no text — produces nothing and is recorded as such rather than failing the document. A mixed document — OCR runs only on the pages that need it. A very large scan — memory bounded so the machine stays usable. Tamil text — recognised via the bundled data and marked as an unsupported language, never presented as Tamil support.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../states-and-edge-cases.md` §3 scanned and scanned-Tamil rows.
- **Validation Rules:** OCR runs per page, decided per page.
- **Audit / Logging Requirements:** OCR invocation and per-page outcome are logged.
- **Analytics Events:** Local counter only — nothing transmitted (C1).

**Real-World Example Scenarios**
- A 2009 scanned invoice indexes visibly more slowly than a digital PDF, then completes with a correct page count.

**Dependencies & Assumptions**
- **Dependencies:** M1-EXTRACT-ING-026.
- **API / Data Touchpoints:** Per-page text; `documents.ocr_confidence` set in the next ticket.
- **Assumptions:** OCR runs on CPU inside the worker container and is slow but acceptable; it is not a candidate for the native process.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, add a scanned PDF. Observe indexing takes visibly longer than a digital one and completes. Check the library page count against the real document. Add a scan with several upside-down pages and confirm those pages produce sensible text in the viewer.
- **Other scenarios:** Add a photo with no text and confirm the document still completes.
- **Known gaps:** No confidence flag yet. No clarification raised. Highlighting on scans will be page-level.

**Effort & Granularity Check**
- **Estimate:** 4–6 hours · **Priority:** Critical
- **Labels / Component:** `phase:1`, ingestion
- **Granularity:** Render, orient, recognise, store. Upper bound.

---

### M1-EXTRACT-ING-029 — Flag low-confidence OCR and surface it as needs attention

**Type:** Story

**User Story**
- **Actor:** someone with a badly photocopied document in their archive.
- **User Need:** to be told the document is nearly invisible to search rather than discovering it through a wrong answer.
- **Business Value:** a poor scan that is silently indexed produces confidently incomplete answers with nothing to explain them.
- *As someone with one terrible photocopy among good scans, I want to be told it read badly, so that I understand why answers about it are thin.*

**Context / Background**
**Detailed Description:** OCR confidence is recorded per document. Where it is low, the document is still indexed — it is not a failure — but it is flagged, the source shows needs attention with the specific reason, and the source viewer later shows the extracted text beside the image so the user can see the gap.

**Scope**
- Confidence measurement and storage.
- Threshold below which a document is flagged, with the threshold as configuration.
- Source status becoming needs attention with a specific expandable reason.

**Out of Scope**
- The clarification asking whether to re-scan (M3).
- The viewer's side-by-side rendering (M1-VIEW-FE-047).

**Acceptance Criteria**
- **Acceptance Criteria:** A poor scan indexes, is flagged low confidence, and its source shows needs attention with a readable reason. A good scan is not flagged. The document remains searchable either way.
- **Edge Cases:** A document that is partly good and partly poor — flagged at document level with the poor pages named. Confidence unavailable for a text-layer document — no flag, not a false one.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/library.md` §2 needs-attention expansion; `../ux/add-source.md` §5 poor OCR; `../states-and-edge-cases.md` §3.
- **Validation Rules:** Low confidence is never treated as a failure.
- **Audit / Logging Requirements:** The flag is logged with the measured confidence.
- **Analytics Events:** Local counter of flagged documents — nothing transmitted (C1).

**Real-World Example Scenarios**
- A user adds twenty scans, one flagged, and re-scans that one from the original rather than wondering why an answer was incomplete.

**Dependencies & Assumptions**
- **Dependencies:** M1-EXTRACT-ING-028.
- **API / Data Touchpoints:** `documents.ocr_confidence`, `sources.status`, `sources.last_error`.
- **Assumptions:** A single document-level confidence figure is enough for v1; per-page detail is retained for the viewer.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, add a deliberately poor scan alongside a clean one. When indexing finishes, open the library and observe the poor one's source marked needs attention. Expand the row and read the specific reason. Confirm the document is still listed as indexed rather than failed.
- **Other scenarios:** Confirm the clean scan carries no flag.
- **Known gaps:** No clarification is raised. The viewer does not yet show the image beside the text.

**Effort & Granularity Check**
- **Estimate:** 2–3 hours · **Priority:** High
- **Labels / Component:** `phase:1`, ingestion, frontend
- **Granularity:** One measurement and one status path.

---

### M1-EXTRACT-VAL-030 — Extraction failure states: corrupt, encrypted, password-protected

**Type:** Story

**User Story**
- **Actor:** someone whose folder contains one password-protected PDF.
- **User Need:** to be told which file failed and why, with a way forward.
- **Business Value:** a silently dropped document is an invisible hole in every future answer.
- *As someone importing a mixed folder, I want failures named individually, so that I know exactly what Askwell does not have.*

**Context / Background**
**Detailed Description:** Extraction failures are listed per file with the reason and a retry. A password-protected PDF prompts for the password, which is not stored unless the user asks. Nothing is ever silently dropped. A failed document leaves the source in needs attention with the file named.

**Scope**
- Failure classification: corrupt, encrypted, password-protected, unreadable on disk.
- Per-file failure display with reason and retry.
- Password prompt with explicit opt-in storage.

**Out of Scope**
- Repairing corrupt files.
- Credential encryption at rest (M4 covers the passphrase-derived key for database credentials; a stored PDF password uses the same mechanism when it exists).

**Acceptance Criteria**
- **Acceptance Criteria:** Each failure kind is reported distinctly with the file named. Retry re-attempts. A password-protected file prompts, and supplying the correct password completes ingestion. Declining leaves the file listed as failed rather than removing it.
- **Edge Cases:** A file that disappears between add and extraction — reported as missing at the recorded path, distinct from corrupt. A file that fails intermittently — retry works and the earlier failure remains visible in history. A wrong password — reported as wrong, with another attempt allowed.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/add-source.md` §5 extraction failed and password-protected; `../states-and-edge-cases.md` §3 extraction failed.
- **Validation Rules:** A password is never written to disk unless the user explicitly asks, and never appears in a log.
- **Audit / Logging Requirements:** Failures are logged with the reason; a stored password is a decisions record of a configuration change, without the value.
- **Analytics Events:** Local counter of failures — nothing transmitted (C1).

**Real-World Example Scenarios**
- A user imports a folder of 200 files, three fail, and the library names all three with distinct reasons instead of showing 197 as if that were all of them.

**Dependencies & Assumptions**
- **Dependencies:** M1-EXTRACT-ING-026, M1-EXTRACT-ING-027.
- **API / Data Touchpoints:** `documents.status`, `sources.last_error`.
- **Assumptions:** Storage of a document password reuses the credential encryption path when it lands in M4; until then, storage is not offered.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, add a folder containing a good PDF, a truncated corrupt PDF and a password-protected one. Watch the good one index. Observe the corrupt one listed as failed with a readable reason and a retry. Observe the protected one prompting for a password; enter the wrong one and read the message, then the right one and watch it complete.
- **Other scenarios:** Delete a file from disk after adding but before extraction and confirm the reported reason is missing rather than corrupt.
- **Known gaps:** No repair. Password storage is unavailable until credential encryption exists.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** High
- **Labels / Component:** `phase:1`, validation, ingestion
- **Granularity:** Four failure kinds sharing one display path.

---

### M1-INDEX-ING-031 — Structure-aware chunking

**Type:** Story

**User Story**
- **Actor:** someone asking about a figure that sits in a table.
- **User Need:** the table row to arrive with its header.
- **Business Value:** a chunk that splits a table row from its header is a defect, and it produces numerically wrong answers that read as confident.
- *As someone whose contracts contain rate tables, I want a retrieved row to carry its column headings, so that the number means what the answer says it means.*

**Context / Background**
**Detailed Description:** Chunking respects headings, table boundaries and list items rather than cutting at a fixed length. Every chunk retains its source document, page or anchor, section heading and ingestion timestamp. Chunk ordinals preserve document order so the viewer can step through them.

**Scope**
- Chunker respecting headings, tables and lists, with a target size and a hard maximum.
- Metadata on every chunk: document, ordinal, page range, heading.
- Tests covering a table, a nested list and a long heading-free run.

**Out of Scope**
- Embedding (M1-INDEX-ING-032).
- Full-text column (M1-INDEX-DB-033).

**Acceptance Criteria**
- **Acceptance Criteria:** A table is not split from its header. A heading is carried on every chunk beneath it. Chunks record their page range. A long section with no headings is split at sentence boundaries rather than mid-sentence.
- **Edge Cases:** A table longer than the maximum chunk size — split with the header repeated on each part. A document with no headings at all — chunked by size with sentence boundaries respected. A single paragraph longer than the maximum — split with overlap so a sentence is never orphaned. A slide deck — one chunk per slide unless a slide is very long.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** Chunks surface as the retrieved passage in `../ux/ask.md` §3.
- **Validation Rules:** No chunk may exceed the hard maximum. No chunk may be empty.
- **Audit / Logging Requirements:** Chunk counts per document are logged.
- **Analytics Events:** Local counter only — nothing transmitted (C1).

**Real-World Example Scenarios**
- A retrieved passage shown in a source card reads as a complete table row with its headings, so the user can verify the figure without opening the file.

**Dependencies & Assumptions**
- **Dependencies:** M1-EXTRACT-ING-027.
- **API / Data Touchpoints:** `chunks`.
- **Assumptions:** Structural markers from extraction are reliable enough to chunk against; where they are absent, size-based chunking with sentence boundaries is the documented fallback.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, add a PDF containing a rate table and a headed report. After indexing, ask a question whose answer is in the table (available once M1-ASK is complete) and read the source card — the passage includes the header row. Before that path exists, inspect the chunks through the source viewer and confirm the same.
- **Other scenarios:** Add a heading-free document and confirm chunks break at sentence ends.
- **Known gaps:** Nothing is retrievable yet. Chunk size tuning is not evaluated until the eval suite in M2.

**Effort & Granularity Check**
- **Estimate:** 4–6 hours · **Priority:** Critical
- **Labels / Component:** `phase:1`, ingestion, retrieval
- **Granularity:** One chunker with three structural rules. Upper bound because the table case carries the correctness.

---

### M1-INDEX-ING-032 — Embedding batches with retry and visible failure

**Type:** Story

**User Story**
- **Actor:** someone whose large import stalled overnight.
- **User Need:** failures visible with a retry rather than a silently incomplete index.
- **Business Value:** an ingestion failure the user cannot see is a permanent invisible gap in every answer.
- *As someone who imported four hundred papers, I want any embedding failure shown with a retry, so that I am not unknowingly searching two hundred of them.*

**Context / Background**
**Detailed Description:** Chunks are embedded in batches through the native inference process. Failures retry with backoff and, on exhaustion, surface in the library with the error and a retry action. The embedding dimension follows the configured model. Batch size is bounded so the machine stays usable.

**Scope**
- Batched embedding with a bounded batch size and backoff retry.
- Persistent failure state per document with a retry action.
- Re-embed path used by later re-processing.

**Out of Scope**
- Reranking (M1-ASK-RET-036).
- Re-processing triggered by memory changes (M3).

**Acceptance Criteria**
- **Acceptance Criteria:** Chunks receive embeddings of the configured dimension. A transient failure retries and succeeds. A persistent failure is visible in the library with the error and a retry that works. **Nothing is ever silently dropped.**
- **Edge Cases:** The inference process goes down mid-batch — the batch is retried, not lost, and the document is not marked indexed. A dimension mismatch against the column — refused at startup rather than per batch. An empty chunk — impossible by the chunker's rule, and rejected here as a second line.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../states-and-edge-cases.md` §3 embedding job failed; `../ux/library.md` §5 needs attention.
- **Validation Rules:** A document is marked indexed only when every chunk has an embedding.
- **Audit / Logging Requirements:** Batch failures are logged with the reason; the final failure state is visible in the library.
- **Analytics Events:** Local counters for chunks embedded and batches failed — nothing transmitted (C1).

**Real-World Example Scenarios**
- The user's machine sleeps mid-import, the inference process restarts, and embedding resumes rather than leaving half the corpus unsearchable.

**Dependencies & Assumptions**
- **Dependencies:** M1-INDEX-ING-031, M0-MODEL-BE-019.
- **API / Data Touchpoints:** `chunks.embedding`; inference client.
- **Assumptions:** The embedding model is served by the same native process as generation.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, add several documents and watch them reach indexed. Stop the inference process mid-import, observe the library show the affected source as needing attention rather than as indexed, restart the process, use the retry action and watch it complete.
- **Other scenarios:** Confirm a document with one failed chunk is not marked indexed.
- **Known gaps:** No re-embed on model change; that is a configuration change plus a manual re-index until M7.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** Critical
- **Labels / Component:** `phase:1`, ingestion, retrieval
- **Granularity:** Batch, retry, surface. Self-contained.

---

### M1-INDEX-DB-033 — Full-text column population and index

**Type:** Task

**User Story**
- **Actor:** someone searching for a reference number.
- **User Need:** exact-token matching alongside meaning-based search.
- **Business Value:** dense retrieval alone fails on precisely what people search for — reference numbers, codes, proper nouns.
- *As someone looking for invoice INV-2024-0917, I want an exact match to be found, so that the search is not defeated by the thing being unusual.*

**Context / Background**
**Detailed Description:** Populate and index the full-text column on every chunk as part of ingestion. The English configuration is used; the Tamil-aware configuration exists as a hedge and is not exercised. The index must support the lexical half of hybrid retrieval at corpus sizes of hundreds of thousands of chunks on a laptop.

**Scope**
- Full-text column population during ingestion and re-population on re-index.
- Index creation and a check that queries use it.
- Handling of tokens like reference numbers that default tokenising would split badly.

**Out of Scope**
- Fusion with dense results (M1-ASK-RET-035).

**Acceptance Criteria**
- **Acceptance Criteria:** Every indexed chunk has a populated full-text value. A lexical query for a reference number present in a document matches its chunk. The query plan uses the index rather than scanning at corpus scale.
- **Edge Cases:** A chunk of pure numbers or codes — still tokenised usefully. A very long chunk — indexed without error. Re-indexing a document repopulates rather than duplicating.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** None directly.
- **Validation Rules:** A chunk without a full-text value is not considered indexed.
- **Audit / Logging Requirements:** None beyond ingestion logging.
- **Analytics Events:** None.

**Real-World Example Scenarios**
- A user searches for a contract number and finds it, where a purely semantic search would have returned five similar contracts and not that one.

**Dependencies & Assumptions**
- **Dependencies:** M1-INDEX-ING-031, M0-DATA-DB-013.
- **API / Data Touchpoints:** `chunks.content_tsv`.
- **Assumptions:** English configuration for v1; Tamil configuration untested and unadvertised.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, add a document containing a distinctive reference number. After indexing, use the library's search-within-source (or the Ask path once available) to find that exact string and confirm it is found.
- **Other scenarios:** Re-index the document and confirm no duplicate entries.
- **Known gaps:** Fusion with dense results does not exist yet, so lexical results are not yet part of an answer.

**Effort & Granularity Check**
- **Estimate:** 2–3 hours · **Priority:** High
- **Labels / Component:** `phase:1`, database, retrieval
- **Granularity:** One column, one index, one tokenising decision.

---

### M1-INDEX-BE-034 — Supersede a changed document rather than duplicating it

**Type:** Story

**User Story**
- **Actor:** someone who has just been sent the June revision of a contract.
- **User Need:** the new version to replace the old in answers while the old stays available for history.
- **Business Value:** answers can say "as of the June revision" rather than presenting two contradictory contracts as equals.
- *As someone whose contracts get revised, I want the new version to take over, so that today's answer reflects today's contract.*

**Context / Background**
**Detailed Description:** Re-adding a file whose content differs from an indexed document at the same path, or an explicitly offered new version, supersedes rather than duplicates. The old document keeps its chunks and its citations resolve to it; retrieval prefers the live version. Supersession is distinct from deletion and the two must never be conflated.

**Scope**
- Supersession detection and the offer to supersede.
- Retrieval excluding superseded versions while old citations still resolve.
- The superseded banner data for the source viewer.

**Out of Scope**
- Deletion and tombstones (M2).
- Answer wording that names the revision (M2-PARTIAL, answer composition).

**Acceptance Criteria**
- **Acceptance Criteria:** Adding a changed version of an existing document offers supersession, not duplication. After superseding, retrieval returns the new version. An answer produced before the supersession still resolves its citation to the old version. The partial unique index prevents two live versions.
- **Edge Cases:** A file at a new path with the same content as an existing document — recognised as a duplicate, not a new version. A file at the same path with different content — offered as a new version. Superseding a document that is itself superseded — chains correctly rather than orphaning. Declining supersession — both exist, and the user is told that answers may cite either.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/add-source.md` §5 new version; `../ux/source-viewer.md` §4 superseded banner; `../states-and-edge-cases.md` §3.
- **Validation Rules:** `superseded_by` is for versions; `deleted_at` is the tombstone. Never reuse one for the other.
- **Audit / Logging Requirements:** Supersession is a decisions record naming both versions.
- **Analytics Events:** Local counter only — nothing transmitted (C1).

**Real-World Example Scenarios**
- A user adds `supplier-agreement-2024-rev2.pdf` over the original; a question about payment terms returns the new figure, and last month's answer still opens the old document.

**Dependencies & Assumptions**
- **Dependencies:** M1-ADD-BE-023, M1-INDEX-ING-032.
- **API / Data Touchpoints:** `documents.version`, `documents.superseded_by`.
- **Assumptions:** Content hash plus path is enough to recognise a revision; where it is not, the user is asked rather than guessed at.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, add a document and ask a question about a value in it, noting the answer. Edit the file on disk to change that value, add it again, and accept the supersession offer. Ask the same question and observe the new value. Scroll back to the earlier answer and click its citation — it opens the old version with a banner saying it was replaced.
- **Other scenarios:** Decline supersession and read the stated consequence.
- **Known gaps:** Answers do not yet phrase the revision date in prose. No automatic detection of a changed file on disk without re-adding.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** High
- **Labels / Component:** `phase:1`, backend, database
- **Granularity:** One state transition and its retrieval consequence.

---

### M1-ASK-RET-035 — Hybrid retrieval with reciprocal rank fusion

**Type:** Story

**User Story**
- **Actor:** someone asking a question that mixes a concept and a code.
- **User Need:** both kinds of matching contributing to one result set.
- **Business Value:** dense-only retrieval fails on reference numbers; lexical-only fails on paraphrase. The product needs both.
- *As someone asking "what did we agree with Meridian about late payment", I want both the meaning and the name to count, so that the right passage surfaces.*

**Context / Background**
**Detailed Description:** Retrieval runs a dense cosine search over the vector column and a lexical search over the full-text column, then fuses the two ranked lists with reciprocal rank fusion. Scores and the threshold in force are retained for the trace, because the abstention explanation depends on showing the near-miss and recomputing later would give a different number.

**Scope**
- Dense search, lexical search, fusion, and a configurable candidate count.
- Retention of per-candidate scores and the threshold in force at query time.
- Scoping retrieval to a single source when the user asked from a source context.

**Out of Scope**
- Reranking (M1-ASK-RET-036).
- The abstention decision itself (M2).
- Memory and schema notes in retrieval (M3, M4).

**Acceptance Criteria**
- **Acceptance Criteria:** A question returns fused candidates with scores. A reference number present in one chunk retrieves that chunk. A paraphrased question retrieves the semantically matching chunk. Scores and threshold are captured for the trace. Superseded and deleted documents are excluded.
- **Edge Cases:** Empty corpus — returns nothing, cleanly, for the abstention path to handle. A question shorter than a word — handled without error. A corpus of one document — fusion still works. Two chunks with identical content from different documents — both returned rather than deduplicated away, since the citation differs.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** Feeds the retrieving state in `../ux/ask.md` §5.
- **Validation Rules:** Scores are stored as measured, never recomputed later.
- **Audit / Logging Requirements:** Chunks retrieved with scores go into the interaction record (`../audit-log.md` §7).
- **Analytics Events:** Local counter only — nothing transmitted (C1).

**Real-World Example Scenarios**
- A question naming a supplier and a concept returns the contract clause rather than the five other contracts that mention late payment.

**Dependencies & Assumptions**
- **Dependencies:** M1-INDEX-ING-032, M1-INDEX-DB-033.
- **API / Data Touchpoints:** `chunks`, `documents`; scores into `messages.trace`.
- **Assumptions:** Fusion weighting is tuned against the eval suite in M2, not guessed at now.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start with a small indexed corpus. Ask a question containing an exact reference number and confirm the answer's source card is the chunk containing it. Ask a paraphrased question with none of the document's wording and confirm the correct passage is still cited.
- **Other scenarios:** Delete a document (once M2 lands) and confirm it stops being retrieved.
- **Known gaps:** No reranking, so ordering is fusion-only. No abstention threshold applied yet. No memory or schema notes.

**Effort & Granularity Check**
- **Estimate:** 4–6 hours · **Priority:** Critical
- **Labels / Component:** `phase:1`, retrieval
- **Granularity:** Two searches and one fusion. Upper bound; the correctness of everything downstream rests here.

---

### M1-ASK-RET-036 — Reranking pass over the top candidates

**Type:** Story

**User Story**
- **Actor:** someone whose question is answered by the fourth-ranked passage.
- **User Need:** the genuinely relevant passage promoted to the top.
- **Business Value:** the cited passage is what the user checks; a nearly-right passage in position one undermines trust faster than a slow answer.
- *As someone checking the source card against my question, I want the top passage to be the one that actually answers it, so that the citation earns its place.*

**Context / Background**
**Detailed Description:** A cross-encoder reranker runs over the fused top candidates, served by the same native inference process. Reranked scores are what the threshold is applied to. The candidate count is bounded to keep latency inside the budget on a standard profile.

**Scope**
- Reranking over a bounded candidate set, with the count configurable by profile.
- Reranked scores stored alongside the fusion scores for the trace.
- Graceful degradation to fusion order if the reranker is unavailable, stated in the trace.

**Out of Scope**
- Threshold application and abstention (M2).

**Acceptance Criteria**
- **Acceptance Criteria:** Reranking reorders candidates and the new order is used. Both score sets are retained. With the reranker unavailable, retrieval still returns fusion-ordered results and the trace says so rather than silently pretending.
- **Edge Cases:** Fewer candidates than the rerank window — handled without padding. A rerank that takes longer than the retrieval budget on a light profile — bounded and reported in timings. All candidates scoring near-identically — order is stable rather than arbitrary between runs.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** Step labels in `../ux/ask.md` §5; timings in `../ux/trace.md` §2.
- **Validation Rules:** Reranked scores are the ones the threshold is applied to; the two score kinds are never mixed.
- **Audit / Logging Requirements:** Rerank duration and scores in the trace and the interaction record.
- **Analytics Events:** Local counter only — nothing transmitted (C1).

**Real-World Example Scenarios**
- On a corpus of similar contracts, the passage from the right supplier is promoted above four passages from the wrong ones.

**Dependencies & Assumptions**
- **Dependencies:** M1-ASK-RET-035, M0-MODEL-BE-019.
- **API / Data Touchpoints:** Inference client; trace.
- **Assumptions:** The reranker shares the native process; if it ever needs its own, the inference client is the seam.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start with a corpus of several similar documents. Ask a question that is genuinely answered by only one of them and confirm the top source card is that one. Stop the inference process's reranking capability (or configure it off) and repeat — an answer still comes back, with the trace noting reranking was skipped.
- **Other scenarios:** Confirm run-to-run ordering is stable for the same question.
- **Known gaps:** No threshold, so a weak best match still becomes an answer until M2.

**Effort & Granularity Check**
- **Estimate:** 2–3 hours · **Priority:** High
- **Labels / Component:** `phase:1`, retrieval
- **Granularity:** One pass plus one degradation path.

---

### M1-ASK-BE-037 — Answer composition prompt as a versioned file with retrieved content delimited

**Type:** Story

**User Story**
- **Actor:** someone whose ingested document contains a line telling the assistant to ignore its instructions.
- **User Need:** retrieved content treated as material to read, never as an instruction to follow.
- **Business Value:** prompt injection through an ingested document otherwise drives real tool calls against the user's real database.
- *As someone who did not write every document in my corpus, I want retrieved text treated as data, so that a document cannot give Askwell orders.*

**Context / Background**
**Detailed Description:** The answer composition prompt lives as a versioned file, never inline in application logic. It delimits retrieved content clearly and states that retrieved content is data and never instruction. Turns whose retrieved content contained instruction-like patterns are flagged in the trace — a mitigation, not a detection system, and the residual risk is documented honestly rather than overclaimed.

**Scope**
- Prompt file with delimitation and the data-not-instruction statement.
- Instruction-like pattern flagging into the trace.
- A prompt version identifier recorded on every interaction, so a change is attributable.

**Out of Scope**
- Abstention wording (M2).
- Tool-use prompting (M5).
- Any user-facing warning about injection — it is flagged in the trace, not shown as an alarm.

**Acceptance Criteria**
- **Acceptance Criteria:** The prompt exists as a file with a version identifier, and no system prompt text appears in application logic. Retrieved content is delimited. A document containing an instruction-like line does not change the assistant's behaviour in the observed cases, and the turn is flagged in the trace. **C7 is preserved by the delimitation and the standing statement, both of which are covered by a test that fails if either is removed.**
- **Edge Cases:** A document that legitimately contains instructional prose, such as a policy manual — flagged but answered normally, since flagging is not blocking. A very long retrieved set — delimitation survives truncation. A prompt change without an eval run — blocked by the eval gate in M2.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../states-and-edge-cases.md` §2 retrieved content contains instruction-like text — answer normally, flag in the trace.
- **Validation Rules:** A test asserts the data-not-instruction statement is present in the prompt file.
- **Audit / Logging Requirements:** Prompt version and the injection flag are recorded on the interaction and in the trace.
- **Analytics Events:** Local counter of flagged turns — nothing transmitted (C1).

**Real-World Example Scenarios**
- A PDF harvested from the web contains a hidden line instructing the assistant to reveal its prompt; the answer is unaffected and the trace shows the flag.

**Dependencies & Assumptions**
- **Dependencies:** M1-ASK-RET-036.
- **API / Data Touchpoints:** Prompt files; `messages.trace.injection_flagged`.
- **Assumptions:** Pattern flagging is heuristic and will both miss and over-flag; this is stated rather than presented as protection.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, add a document containing an obvious injection attempt among ordinary content. Ask a question that retrieves that passage. Observe the answer addresses the question normally with no leaked instructions, and no scary banner. Open the trace and see the turn flagged.
- **Other scenarios:** Remove the standing statement from the prompt file and confirm a test fails.
- **Known gaps:** Flagging is heuristic. There is no protection against an injection that does not match a pattern, and the documentation says so.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** Critical
- **Labels / Component:** `phase:1`, backend, `constraint:injection`
- **Granularity:** One prompt file, one flag, one test.

---

### M1-ASK-API-038 — Server-sent answer streaming with named retrieval steps

**Type:** Story

**User Story**
- **Actor:** someone on a modest laptop waiting twenty seconds for an answer.
- **User Need:** to see that work is happening and what kind.
- **Business Value:** a silent spinner for twenty seconds reads as broken and is when people give up.
- *As someone whose machine takes its time, I want to see what Askwell is doing, so that I can tell working from hung.*

**Context / Background**
**Detailed Description:** Answers stream over server-sent streaming, along with named retrieval step labels emitted before the first token and updated throughout. A bidirectional channel is deliberately not used — one-way streaming reconnects on its own and covers everything up to voice in M6.

**Scope**
- Streaming endpoint emitting step labels, tokens, citation events and completion.
- Reconnection behaviour that resumes a stream in progress rather than restarting the answer.
- A stop signal that ends generation and marks the answer partial.

**Out of Scope**
- The Ask screen rendering (M1-ASK-FE-039).
- Voice transport (M6).

**Acceptance Criteria**
- **Acceptance Criteria:** Step labels arrive before the first token. Tokens stream at their real pace. A dropped connection reconnects and continues rather than restarting. Stop ends generation and the stored answer is marked partial.
- **Edge Cases:** The client disconnects entirely — generation continues server-side and the answer is saved. A very long answer — streamed without truncation, and if a limit is reached it is stated. The inference process dies mid-stream — the stream ends with a stated failure and the partial answer is kept.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/ask.md` §5 retrieving, streaming, stop; `../states-and-edge-cases.md` §2 thinking, answering, very long answer.
- **Validation Rules:** Step labels name the real step, never a generic placeholder.
- **Audit / Logging Requirements:** The interaction record captures the full answer including a partial one, marked as such.
- **Analytics Events:** Local counters for answers started, completed and stopped — nothing transmitted (C1).

**Real-World Example Scenarios**
- A user asks a question, sees "searching your files" then "reading 4 sources", and the first token arrives three seconds later.

**Dependencies & Assumptions**
- **Dependencies:** M1-ASK-BE-037.
- **API / Data Touchpoints:** Streaming endpoint; `messages`.
- **Assumptions:** One-way streaming is sufficient through M5; voice adds the only bidirectional channel.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, ask a question and watch the step labels appear within a second, then tokens. Mid-answer, disconnect the network interface briefly and reconnect — the answer continues. Ask again and press stop mid-answer — generation ends and the partial answer is marked partial in the conversation.
- **Other scenarios:** Close the browser tab mid-answer, reopen, and find the completed answer in the conversation.
- **Known gaps:** No citation rendering yet. No abstention. Reconnect resumes the stream but does not replay tokens already sent.

**Effort & Granularity Check**
- **Estimate:** 4–6 hours · **Priority:** Critical
- **Labels / Component:** `phase:1`, api, backend
- **Granularity:** One transport with four event kinds. Upper bound.

---

### M1-ASK-FE-039 — Ask screen: composer, the live turn, streaming and step labels

**Type:** Story

**User Story**
- **Actor:** someone who cannot remember which contract said what.
- **User Need:** to ask in plain English and watch the answer arrive.
- **Business Value:** this is the screen that decides whether anyone keeps Askwell.
- *As someone who currently opens files one at a time, I want to type a question and get an answer, so that I stop hunting.*

**Context / Background**
**Detailed Description:** Build the Ask screen in its three-column form: left rail, centre column at a 68–75 character measure, and the provenance margin reserved. The composer submits on Enter with a newline on Shift-Enter. Step labels render during retrieval, tokens stream, and the margin is present even before it is populated.

**This ticket builds the *live turn*, not the conversation.** `../ux/conversation.md` is a separate specification: past turns collapse to a question, a stored one-line summary and a source count, while the live turn keeps its full margin. That behaviour is the `CONV` epic (M1-CONV-BE-177 onwards) and is deliberately not folded in here — a single question and answer is enough to prove the answer path, and collapsing needs stored summaries and citation counts that do not exist yet. What this ticket must do is render the live turn in a container that the collapse behaviour can later wrap, rather than assuming one answer is all there will ever be.

**The composer carries a mic control from Phase 1**, disabled with its reason until voice ships (`../ux/ask.md` §4). That is M1-ASK-FE-039a, immediately after this one, and the reason it is not deferred to M6 is that the composer must not be rebuilt later to make room for it.

**Scope**
- Composer, the live turn, streaming render, step labels.
- Reserved margin rendering its explicitly empty state.
- A turn container that later collapses without being rewritten.
- Keyboard entry to the screen from anywhere.

**Out of Scope**
- The mic control (M1-ASK-FE-039a).
- Collapsing past turns, stored summaries, suggested follow-ups (M1-CONV-BE-177 through M1-CONV-FE-180).
- Source cards and leaders (M1-CITE-FE-043).
- Abstention rendering (M2).
- Memory chips (M3), SQL disclosure (M4), trace (M5), voice (M6).

**Acceptance Criteria**
- **Acceptance Criteria:** A typed question submits and an answer streams into the live turn. Step labels appear before the first token. The margin is visible and states it is empty rather than being hidden. The measure is within the specified range. A second question renders as a second turn — unstyled by the collapse rules, which arrive in the `CONV` epic — rather than replacing the first.
- **Edge Cases:** A submitted empty question — no request is made. A question submitted while one is running — **queued, not interleaved** (`../ux/conversation.md` §5); one answer at a time and nothing silently dropped. Navigating away mid-answer and back — the completed answer is present. Several turns — scrolling stays smooth, and they stack until collapsing lands.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/ask.md` §2, §4, §5 (retrieving, streaming, answered); `../ux/conversation.md` §5 (single turn — "it is `ask.md`"); `../ux/design-system.md` §4.
- **Validation Rules:** Non-English questions get the English-only statement rather than a poor answer (`../ux/ask.md` §5).
- **Audit / Logging Requirements:** Every question and answer is an interaction record.
- **Analytics Events:** Local counter of questions asked — nothing transmitted (C1).

**Real-World Example Scenarios**
- The user asks about payment terms, sees the steps, watches the answer stream, and reads the correct figure.

**Dependencies & Assumptions**
- **Dependencies:** M1-ASK-API-038, M0-SHELL-FE-017.
- **API / Data Touchpoints:** Streaming endpoint; `conversations`, `messages`.
- **Assumptions:** The margin's geometry supports fifty cards in a long conversation; if it does not, the open question in `../ux/ask.md` §8 is answered before M2.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Launch cold with an indexed PDF present. Land on Ask. Type a question about the document and press Enter. Observe step labels within a second, then streaming tokens, then a complete answer. Confirm the margin is on screen and says it is empty. Navigate to the library and back — the answer is still there.
- **Other scenarios:** Ask a question in another language and read the English-only statement.
- **Known gaps:** The answer is ungrounded until the next ticket lands — no sources are shown and nothing can be checked. This state must not ship to a user; M1-CITE-BE-042 and M1-CITE-FE-043 follow immediately. Past turns do not collapse and there are no follow-up suggestions; both are the `CONV` epic. The mic control is not present until M1-ASK-FE-039a.

**Effort & Granularity Check**
- **Estimate:** 4–6 hours · **Priority:** Critical
- **Labels / Component:** `phase:1`, frontend
- **Granularity:** One screen with three regions and one live turn. Upper bound; the conversation behaviour was split out precisely to keep it there.

---

### M1-ASK-FE-039a — Mic control in the composer, disabled with its reason until voice ships

**Type:** Story

**User Story**
- **Actor:** someone who wonders, on day one, whether they will be able to talk to this.
- **User Need:** to see that voice is part of the product and to be told plainly when it arrives.
- **Business Value:** the composer is the most-used control in Askwell, and adding a button to it four phases later means rebuilding and re-testing it. Reserving the space now costs an hour; retrofitting it costs the composer.
- *As someone who dictates rather than types when their hands are full, I want to see that voice exists and is coming, so that I am not left guessing whether the product will ever suit how I work.*

**Context / Background**
**Detailed Description:** `../ux/ask.md` §4 puts a mic control in the composer **from Phase 1**, disabled, stating its own reason — the composer is not rebuilt later to make room for it. This ticket adds the control, its disabled presentation, and the statement that voice arrives with the voice phase. It does no audio work of any kind.

The disabled state must read as *not yet* rather than *broken*. `../ux/design-system.md` §6 forbids apologetic copy; the control says what it will do and when, in Askwell's own voice.

**Scope**
- The mic control in the composer, at its final position and size.
- Disabled presentation consistent with the design system, with a reason available on hover and on keyboard focus.
- Copy naming voice as arriving later, not as unavailable or failed.
- The seam that M6-VUI-FE-132 enables, so the voice phase changes state rather than layout.

**Out of Scope**
- Any audio capture, permission request, transport or synthesis — all of M6.
- The level meter and the stop control (M6-VUI-FE-132, M6-VUI-FE-133).
- Escalating a web search by voice — not specified, deferred with the voice work (`../web-search.md` §8).

**Acceptance Criteria**
- **Acceptance Criteria:** The composer renders a mic control in every state the composer has. It is visibly disabled, is skipped by tab order or focusable-and-explained rather than silently inert, and states why on hover and on focus. Activating it does nothing and requests no microphone permission. The composer's layout is identical to what it will be once voice is enabled — enabling voice in M6 changes state, not geometry.
- **Edge Cases:** A screen reader reaching the control — it is announced as disabled with the reason, not as an unlabelled button. The window narrowed past the breakpoint — the control stays in the composer rather than being dropped, because dropping it would mean re-solving the layout in M6. A user clicking it repeatedly — nothing happens, no error, no permission prompt.
- **Permissions / Roles:** Single user — no roles. Not applicable. **No microphone permission is requested** — asking for a device before the feature exists is exactly the kind of surprise this product cannot afford.
- **UI States:** `../ux/ask.md` §4 (mic control, present from Phase 1, disabled with its reason); `../ux/voice.md` for what it becomes; `../ux/design-system.md` §6 for the copy.
- **Validation Rules:** The control may never be hidden rather than disabled — a control that appears in M6 is a layout change, which is the thing this ticket exists to prevent.
- **Audit / Logging Requirements:** None. Nothing happens.
- **Analytics Events:** None.

**Real-World Example Scenarios**
- A user evaluating three local AI tools sees the mic control, hovers it, reads that speaking to Askwell arrives in a later version, and files that as a plan rather than a gap.
- The voice phase arrives and the composer is not touched beyond enabling the control, so nothing that worked before needs re-testing.

**Dependencies & Assumptions**
- **Dependencies:** M1-ASK-FE-039.
- **API / Data Touchpoints:** None.
- **Assumptions:** The control's final size and position are known from `../ux/voice.md` and will not change when voice ships; if they do, this ticket has not done its job.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Launch cold and land on Ask. Look at the composer and see the mic control beside the send affordance. Hover it and read a sentence saying speaking to Askwell arrives later — not an error, not an apology. Click it and confirm nothing happens and no browser microphone prompt appears. Tab through the composer with the keyboard and confirm the control is announced with its reason rather than being an unlabelled dead stop.
- **Other scenarios:** Narrow the window and confirm the control is still in the composer. Compare the composer against the voice specification's illustration and confirm the geometry already matches.
- **Known gaps:** No voice of any kind. No microphone access. Voice escalation of a web search is unspecified and deferred (`../web-search.md` §8).

**Effort & Granularity Check**
- **Estimate:** 1–2 hours · **Priority:** Medium
- **Labels / Component:** `phase:1`, frontend
- **Granularity:** One disabled control and its copy. Small by design — the whole point is that it is cheap now and expensive later.

---

### M1-ASK-BE-040 — Generation continues server-side when the user navigates away

**Type:** Task

**User Story**
- **Actor:** someone who asked a slow question and went to check the library.
- **User Need:** the answer to be there when they come back.
- **Business Value:** on a slow local model the user will navigate away; losing the answer teaches them to sit and stare instead.
- *As someone who asked something that takes half a minute, I want to be able to do something else meanwhile, so that waiting is not the interaction.*

**Context / Background**
**Detailed Description:** Generation is not tied to the client connection. When the browser disconnects, generation continues and the completed answer is written to the conversation. This costs local compute on an abandoned question — fan noise on a laptop, not a queue, since there is no other user waiting.

**Scope**
- Generation lifetime decoupled from the client connection.
- Completed answers written to the conversation regardless of client presence.
- Re-attachment on return showing the completed answer.

**Out of Scope**
- Cancellation policy beyond the explicit stop control.

**Acceptance Criteria**
- **Acceptance Criteria:** Navigating away mid-answer and returning shows the completed answer. Closing the tab entirely and reopening shows the same. Explicit stop still ends generation.
- **Edge Cases:** The stack restarts mid-generation — the answer is lost and the message is marked failed rather than left permanently pending. Several abandoned generations at once — bounded so the machine stays usable. The user asks the same question again while the first is still running — both complete, both appear.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/ask.md` §4 navigate away; `../states-and-edge-cases.md` §2.
- **Validation Rules:** A message must never remain in a pending state with nothing generating it.
- **Audit / Logging Requirements:** The interaction record is written on completion regardless of client presence.
- **Analytics Events:** Local counter of abandoned generations — nothing transmitted (C1).

**Real-World Example Scenarios**
- The user asks a question, goes to make coffee with the laptop lid open, and returns to a finished answer.

**Dependencies & Assumptions**
- **Dependencies:** M1-ASK-API-038.
- **API / Data Touchpoints:** `messages`; streaming endpoint.
- **Assumptions:** Bounded concurrency is acceptable on a single-user machine.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, ask a question that takes a while, and immediately navigate to the library. Wait, then return to Ask. The answer is complete in the conversation. Repeat, this time closing the browser tab entirely, then reopen Askwell — the answer is there.
- **Other scenarios:** Restart the stack mid-generation and confirm the message is marked failed rather than pending forever.
- **Known gaps:** There is no notification when an abandoned answer completes.

**Effort & Granularity Check**
- **Estimate:** 2–3 hours · **Priority:** High
- **Labels / Component:** `phase:1`, backend
- **Granularity:** One lifetime change plus its failure case.

---

### M1-ASK-OBS-041 — Interaction records for every question and answer

**Type:** Story

**User Story**
- **Actor:** a consultant who may need to show a client what was asked of a confidential corpus.
- **User Need:** a complete, verifiable record of questions and answers.
- **Business Value:** the log is the user's own record and is one of the reasons a professional can justify using the tool at all.
- *As someone who may have to account for what I did with a client's material, I want every question recorded, so that I can produce the record if asked.*

**Context / Background**
**Detailed Description:** Every question and answer writes an interaction record: the question, the answer, the chunks retrieved with their scores, duration, the backend and model used, and whether the turn abstained. Rejected SQL, tool-ceiling stops and abstentions join later as those features arrive. The record is hash-chained and a write failure fails the action.

**Scope**
- Interaction record written transactionally with the answer.
- Fields: question, answer, retrieved chunks with scores, duration, backend, model.
- Trace written to the ring buffer separately, failing open.

**Out of Scope**
- Retention window and pruning (M7).
- Export (M7).

**Acceptance Criteria**
- **Acceptance Criteria:** Asking a question produces one interaction record containing the retrieved chunk identifiers and scores, the duration, and the backend and model. An induced audit write failure fails the answer rather than producing an unlogged one. A trace write failure does not fail the answer.
- **Edge Cases:** A stopped answer — recorded as partial. An abandoned answer — recorded on completion. An answer that failed mid-generation — recorded with the failure. A very large retrieved set — the record stores identifiers and scores, not full text; full text belongs to the rotating trace.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** Consumed by the trace screen in M5 and the log export in M7.
- **Validation Rules:** The record and the answer are written in one transaction.
- **Audit / Logging Requirements:** This ticket is the audit requirement. **C6 is preserved: the record is chained and the application role has no update or delete grant.**
- **Analytics Events:** Local counters derived from the log, computed on demand — nothing transmitted (C1).

**Real-World Example Scenarios**
- Months later the user exports the log to show which passages were consulted for a piece of advice.

**Dependencies & Assumptions**
- **Dependencies:** M0-DATA-OBS-015, M1-ASK-API-038.
- **API / Data Touchpoints:** `audit_interactions`; trace ring buffer; `messages.trace`.
- **Assumptions:** Storing identifiers and scores rather than full retrieved text keeps the interaction store within a sane size for years of use.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, ask three questions. Run the log verification and observe an intact chain covering three interaction records. Make the interaction table unwritable and ask a fourth — the answer fails with a stated reason rather than appearing unlogged. Make the trace directory unwritable and ask again — the answer succeeds.
- **Other scenarios:** Stop an answer and confirm the record marks it partial.
- **Known gaps:** No retention window, no export, no viewer for the log. SQL and tool fields are unpopulated until M4 and M5.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** Critical
- **Labels / Component:** `phase:1`, observability, `constraint:audit`
- **Granularity:** One record with one transactional rule.

---

### M1-CITE-BE-042 — Claim-level citation extraction into the citations table

**Type:** Story

**User Story**
- **Actor:** someone who has to be right about a client's contract.
- **User Need:** every factual claim tied to the passage it came from, as data rather than as prose.
- **Business Value:** a constraint that cannot be queried cannot be enforced or measured, and the counter-metric tracks uncited claims at one hundred percent.
- *As someone whose advice rests on these answers, I want each claim tied to a stored citation, so that "is anything here uncited" is a question with an answer.*

**Context / Background**
**Detailed Description:** As an answer is composed, each factual claim is associated with the chunk it came from and written to the citations table with a claim ordinal and the quoted span. Citations are real rows, not fields inside the trace blob, because the trace rotates and citations must not. Memory facts used in an answer are recorded separately in the fact usage table when memory arrives in M3.

**Scope**
- Claim segmentation and association with retrieved chunks.
- Citation rows with message, chunk, claim ordinal and quoted span.
- Streaming citation events so cards can render as claims are emitted rather than appended at the end.

**Out of Scope**
- The margin rendering (M1-CITE-FE-043).
- Memory fact usage (M3).
- The uncited-claim query (M1-CITE-TEST-045).

**Acceptance Criteria**
- **Acceptance Criteria:** An answer with three factual claims produces three citation rows referencing real chunks with quoted spans that appear in those chunks. Citation events stream during generation. Citations survive trace rotation. **C4 is preserved because the citation is stored as queryable data at composition time, not reconstructed later.**
- **Edge Cases:** A claim supported by two passages — two citations for one claim ordinal. A sentence that is not a factual claim, such as a restatement of the question — no citation, and it must not be counted as an uncited claim. A quoted span that cannot be located exactly in the chunk — the citation resolves to the chunk without the span rather than being dropped. A deleted document's chunk — the citation still resolves, because the foreign key is deliberately not cascade-delete.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/ask.md` §3 and §5; `../ux/design-system.md` §1 — an uncited claim is visibly wrong because nothing sits beside it.
- **Validation Rules:** Every claim classified as factual must carry at least one citation, or the answer is a defect.
- **Audit / Logging Requirements:** Citations are durable rows and are not part of the rotating trace.
- **Analytics Events:** Local counter of claims and citations — nothing transmitted (C1).

**Real-World Example Scenarios**
- An answer states a 45-day payment term and the stored citation points at the exact clause on page 14.

**Dependencies & Assumptions**
- **Dependencies:** M1-ASK-BE-037, M1-ASK-API-038.
- **API / Data Touchpoints:** `citations`; streaming citation events.
- **Assumptions:** Claim segmentation is prompt-driven and imperfect; the eval suite in M2 is what measures it, and the counter-metric is what catches regression.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, ask a question with a known factual answer. When the answer completes, open the source viewer through the library and confirm the passage the citation names really does contain the stated fact. Ask a second question and confirm the number of source cards matches the number of factual claims.
- **Other scenarios:** Force trace rotation and confirm the citations still resolve.
- **Known gaps:** Nothing renders the citations yet. No systematic check that every claim is cited — that arrives in M1-CITE-TEST-045.

**Effort & Granularity Check**
- **Estimate:** 4–6 hours · **Priority:** Critical
- **Labels / Component:** `phase:1`, backend, `constraint:grounding`
- **Granularity:** Segmentation, association, persistence, streaming. Upper bound; this is the ticket where the product's central claim becomes true.

---

### M1-CITE-FE-043 — The provenance margin with source cards and leaders

**Type:** Story

**User Story**
- **Actor:** someone deciding whether to act on an answer without opening the file.
- **User Need:** the evidence beside the claim, always, without clicking anything.
- **Business Value:** citations behind a toggle make provenance a disclosure you click, which contradicts the thing being sold.
- *As someone about to rely on an answer, I want the source sitting next to the claim, so that checking is a glance rather than a decision.*

**Context / Background**
**Detailed Description:** Render the permanent right-hand margin: one card per cited claim showing filename, page or anchor, and the exact retrieved passage, joined to its claim by a hairline leader. Cards enter as claims are cited during streaming. The margin is never hidden, never a toggle, and renders an explicit empty state when there is nothing to show. Cards use the reserved provenance colour, which appears on nothing that is not traceable.

**Scope**
- Card rendering with filename, page or anchor, and passage.
- Leader geometry connecting claim to card, drawn on arrival.
- Explicit empty state.
- Deleted-source card rendering as deleted and greyed, once deletion exists in M2.

**Out of Scope**
- Click-through to the viewer (M1-VIEW-FE-048 covers the landing; the click is wired here to the route).
- Hover pairing and the narrow-window fallback (M1-CITE-FE-044).
- Memory chips (M3), SQL disclosure (M4).

**Acceptance Criteria**
- **Acceptance Criteria:** Each cited claim has a card showing filename, page and the exact passage. Cards appear as the answer streams rather than all at the end. The margin is present in every state, populated or explicitly empty. The provenance colour is used on nothing else.
- **Edge Cases:** Two claims citing the same passage — one card, two leaders, rather than a duplicate. Fifty cards in a long conversation — the margin stays usable; if virtualisation is needed the open question in `../ux/ask.md` §8 is settled here. A very long passage — truncated in the card with a clear way to see it in full. A card for a document whose file has moved — still rendered; the moved state appears on click.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/ask.md` §2, §3, §5; `../ux/design-system.md` §1 and §2.
- **Validation Rules:** The margin must never be collapsible or conditional.
- **Audit / Logging Requirements:** None beyond the citation rows.
- **Analytics Events:** Local counter of card clicks — nothing transmitted (C1).

**Real-World Example Scenarios**
- An answer names three figures and three cards sit beside them naming the file and page for each, so the user acts without opening anything.

**Dependencies & Assumptions**
- **Dependencies:** M1-CITE-BE-042, M1-ASK-FE-039.
- **API / Data Touchpoints:** Citation stream events; `citations` joined to `chunks` and `documents`.
- **Assumptions:** Leader geometry is achievable with the streaming render without layout thrash; if not, cards still render and the leader degrades rather than the card disappearing.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Launch cold with an indexed PDF. Ask a question it covers. Watch cards enter the margin as claims are cited, each naming the file and a page and showing a passage. Open the PDF separately and confirm that passage really is on that page. Ask a question with no factual claims and confirm the margin says it is empty rather than disappearing.
- **Other scenarios:** Have one answer cite the same passage twice and confirm one card with two leaders.
- **Known gaps:** No hover pairing yet, no narrow-window behaviour, no click-through landing. Deleted-source rendering waits for deletion to exist.

**Effort & Granularity Check**
- **Estimate:** 4–6 hours · **Priority:** Critical
- **Labels / Component:** `phase:1`, frontend, `constraint:grounding`
- **Granularity:** One region with one entry animation and one empty state. Upper bound — this is the product's signature.

---

### M1-CITE-FE-044 — Hover pairing and the narrow-window inline fallback

**Type:** Story

**User Story**
- **Actor:** someone reading a five-claim answer on a laptop screen.
- **User Need:** to know which card belongs to which claim, and to keep the cards when the window is small.
- **Business Value:** citations are not conditional on window width; removing them at a breakpoint would quietly break C4 on the most common screen size.
- *As someone working on a small screen, I want the sources still present when the window is narrow, so that the product's promise does not depend on my monitor.*

**Context / Background**
**Detailed Description:** Hovering a cited claim raises its leader and its card; hovering a card raises its claim. Below the three-column breakpoint, cards move inline beneath the answer rather than being removed. Nothing is ever hidden by width.

**The line that joins a claim to its card carries information, so it is `--rule-strong`, not `--rule`** (`../ux/design-system.md` §2 and §8). At width that is the claim leader; below the breakpoint, where there is no room for a leader, the card's left edge carries the same relationship and takes the same token. A decorative hairline at the contrast of a divider would lose which source belongs to which claim, which is the whole content of the pairing.

**There is no phone.** Askwell installs as a desktop application, so this behaviour serves a window someone has made narrow beside another window — not a small screen.

**Scope**
- Hover pairing in both directions with a clear raised state, the leader drawn in `--rule-strong`.
- Inline card layout below the breakpoint, preserving order and content, with a `--rule-strong` left edge carrying the relationship the leader carried at width.
- Keyboard focus parity, so pairing works without a mouse.

**Out of Scope**
- Click-through (M1-VIEW-FE-048).

**Acceptance Criteria**
- **Acceptance Criteria:** Hovering a claim raises exactly its leader and card and no others. Hovering a card raises its claim. Narrowing the window moves cards inline with none removed and gives each card a `--rule-strong` left edge. Keyboard focus produces the same pairing. The leader and the inline edge both measure at least 3:1 against their ground **in both themes**, checked rather than assumed (`../ux/design-system.md` §8).
- **Edge Cases:** A claim with two cards — both raise. Overlapping leaders in a dense answer — the raised one is unambiguous. The window resized mid-hover — the pairing survives the reflow rather than dropping. Dark theme — the leader is still visible, which is the failure `--rule-strong` exists to prevent.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/ask.md` §4 and §5; `../ux/design-system.md` §1, §2 (`--rule-strong`), §4 (the breakpoint), §8 (measured contrast).
- **Validation Rules:** No breakpoint may remove a card. A line conveying which claim belongs to which source may never be styled with `--rule`.
- **Audit / Logging Requirements:** None.
- **Analytics Events:** None.

**Real-World Example Scenarios**
- A user who has snapped Askwell to half their screen to read a contract alongside it sees the cards beneath each answer rather than losing them, with each card's edge still pointing at its claim.

**Dependencies & Assumptions**
- **Dependencies:** M1-CITE-FE-043.
- **API / Data Touchpoints:** None.
- **Assumptions:** The inline arrangement is legible for up to a handful of cards per answer; beyond that it scrolls.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, ask a question producing several cited claims. Hover each claim in turn and confirm only its card raises. Hover a card and confirm its claim raises. Drag the window narrow past the breakpoint and confirm every card is still on screen, now inline. Widen again and confirm they return to the margin.
- **Other scenarios:** Tab through the answer with the keyboard and confirm the same pairing. Switch to the dark theme and repeat the narrow-window check, confirming the card edges are still clearly visible. Measure the leader and the inline edge against their ground in both themes.
- **Known gaps:** Touch behaviour is minimal; this is a desktop application and there is no phone target.

**Effort & Granularity Check**
- **Estimate:** 2–3 hours · **Priority:** High
- **Labels / Component:** `phase:1`, frontend, `constraint:grounding`
- **Granularity:** One interaction and one layout rule, both using tokens that already exist from M0-FOUND-FE-003.

---

### M1-CITE-TEST-045 — The query that proves no answer contains an uncited claim

**Type:** Story

**User Story**
- **Actor:** the maintainer checking that the product's central claim still holds after a prompt change.
- **User Need:** a query, not an impression.
- **Business Value:** the counter-metric tracks sampled answers where every factual claim traces to a chunk or a memory fact at one hundred percent; without a query that number cannot exist.
- *As someone about to change the answer prompt, I want a query that tells me whether any claim went uncited, so that a regression is caught rather than felt.*

**Context / Background**
**Detailed Description:** Build the query and the checking routine that, over a sample of stored answers, identifies factual claims with no corresponding citation row or fact usage row. This is the instrument behind the counter-metric that must be reported alongside abstention rate, because falling abstention with falling citation correctness is the failure signature and either number alone looks fine.

**Scope**
- Claim-to-citation reconciliation over stored answers.
- A reported figure and a list of offending answers with the uncited claim quoted.
- A test that fails when the figure drops below the bar on the eval corpus.

**Out of Scope**
- The abstention rate itself (M2).
- A user-facing dashboard — there is none, and there is no telemetry.

**Acceptance Criteria**
- **Acceptance Criteria:** Running the check over stored answers produces a percentage and names any answer with an uncited factual claim. Deliberately removing a citation row makes the check fail and names that answer. The check runs offline with no network access.
- **Edge Cases:** An answer that is entirely abstention — no claims, and it must count as compliant rather than as a failure. A claim citing a memory fact rather than a document — compliant once fact usage exists in M3, and until then those answers are excluded and the exclusion is stated. A partial answer — the grounded part must be cited; the explicitly ungrounded part is not a violation.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** None — this is an instrument, not a screen.
- **Validation Rules:** An uncited factual claim is a defect, never a documented limitation.
- **Audit / Logging Requirements:** Check results are recorded alongside eval runs.
- **Analytics Events:** Local only — nothing transmitted (C1).

**Real-World Example Scenarios**
- A prompt change improves fluency and starts merging two facts into one uncited sentence; the check catches it before the change lands.

**Dependencies & Assumptions**
- **Dependencies:** M1-CITE-BE-042, M1-ASK-OBS-041.
- **API / Data Touchpoints:** `citations`, `fact_usage`, `messages`.
- **Assumptions:** Claim identification for checking uses the same segmentation as composition, so the check measures citation coverage rather than segmentation disagreement.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start with a small indexed corpus. Ask five questions with known factual answers. Run the check and observe it reports full coverage. Delete one citation row directly and run it again — the check names that answer and quotes the now-uncited claim.
- **Other scenarios:** Ask a question that abstains and confirm it does not count as a violation.
- **Known gaps:** Memory-backed claims are excluded until M3. Segmentation errors can produce false positives, which is why offending claims are quoted rather than only counted.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** Critical
- **Labels / Component:** `phase:1`, test, `constraint:grounding`, `eval`
- **Granularity:** One reconciliation plus one test.

---

### M1-VIEW-FE-046 — Source viewer: in-app PDF at the cited page with the passage highlighted

**Type:** Story

**User Story**
- **Actor:** someone checking an answer against the contract.
- **User Need:** one click that lands on the page with the passage highlighted, quickly.
- **Business Value:** if checking costs more than re-reading the source, people stop checking and the central promise quietly dies.
- *As someone checking an answer, I want one click to put me on the page with the passage highlighted, so that checking is cheap enough that I actually do it.*

**Context / Background**
**Detailed Description:** Render PDFs in-app with a locally bundled renderer, scrolled to the cited page with the passage highlighted. Handing off to the operating system's viewer was rejected: it loses the highlight, loses the way back, and on some systems starts a program that takes ten seconds. The cited page loads first and the rest streams, so a large document never means a whole-document wait. Scanned pages highlight at page level.

**Scope**
- In-app PDF rendering with the bundled renderer, no external assets.
- Landing on the cited page with the passage highlighted for text-layer documents.
- Page-level highlight for scanned pages, stated in the interface rather than silently approximate.
- Cited page first, remainder streaming.

**Out of Scope**
- Non-PDF renderings (M1-VIEW-FE-047).
- Context rail and citation stepping (M1-VIEW-FE-048).
- Passage-level highlighting on scans — a separate later story.

**Acceptance Criteria**
- **Acceptance Criteria:** Clicking a source card opens the document at the cited page with the passage highlighted in under a second for a typical document. A 300-page PDF shows the cited page without waiting for the whole file. A scanned page highlights at page level and says so. No external network request is made to render.
- **Edge Cases:** The passage cannot be located exactly — falls back to the page with a note that the exact passage could not be pinpointed, because honest degradation beats a wrong highlight. An unrenderable PDF — extracted text with a note and an open-in-system-app option. A document whose file is missing — handled by M1-VIEW-BE-049.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/source-viewer.md` §2 and §4 (loaded at citation, loading a large PDF, passage not locatable, unrenderable).
- **Validation Rules:** No renderer asset may be fetched from a remote host (C1).
- **Audit / Logging Requirements:** Opening a source is an interaction-adjacent event and is logged; it is not a decision.
- **Analytics Events:** Local counter of citations opened — nothing transmitted (C1).

**Real-World Example Scenarios**
- The user clicks a card, lands on page 14 with the clause highlighted, reads the surrounding paragraph, and accepts the answer.

**Dependencies & Assumptions**
- **Dependencies:** M1-CITE-FE-043, M1-EXTRACT-ING-026.
- **API / Data Touchpoints:** Document bytes from the registered root; `chunks.page_from`, `page_to`.
- **Assumptions:** Passage coordinates are derived from the text layer; where the extractor cannot supply them, the fallback is page-level with a stated note. This is the accepted cost of the licence decision.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Launch cold, ask a question about an indexed PDF, and click the first source card. The document opens at the right page with the passage highlighted, quickly. Repeat with a 300-page document and confirm the cited page appears without a long wait. Repeat with a scanned document and confirm the page is highlighted with a note that it is page-level.
- **Other scenarios:** Disconnect the network and repeat — rendering is unaffected.
- **Known gaps:** No way back to the answer yet, no citation stepping, no non-PDF rendering. Scanned passages are page-level only.

**Effort & Granularity Check**
- **Estimate:** 4–6 hours · **Priority:** Critical
- **Labels / Component:** `phase:1`, frontend, `constraint:grounding`, `constraint:local-first`
- **Granularity:** One renderer, one landing behaviour, two degradations. Upper bound.

---

### M1-VIEW-FE-047 — Non-PDF renderings and OCR text beside scans

**Type:** Story

**User Story**
- **Actor:** someone whose answer cited a slide deck and an image.
- **User Need:** to land somewhere useful for every format, not only PDFs.
- **Business Value:** a citation that cannot be followed is decoration, whatever the file type.
- *As someone whose sources are a mixture of formats, I want every citation to open somewhere I can read, so that the checking habit is not format-dependent.*

**Context / Background**
**Detailed Description:** Render Word, PowerPoint, text, Markdown and HTML as converted text with structure preserved and the heading anchored. Render spreadsheets as a table scrolled to the highlighted row. Render images with the OCR text alongside, which is how someone discovers that a bad scan is why an answer was wrong.

**Scope**
- Converted-text rendering with structure and heading anchoring.
- Table rendering with row highlight for spreadsheet sources.
- Image rendering with OCR text alongside.
- Unrenderable fallback with an open-in-system-app option.

**Out of Scope**
- Database result rendering (M4).
- Editing anything — the viewer is read-only.

**Acceptance Criteria**
- **Acceptance Criteria:** Each supported non-PDF format opens at the cited anchor with the cited content visible and marked. An image source shows the OCR text beside the image. An unrenderable file shows extracted text with a note and the option to open it externally.
- **Edge Cases:** A converted document with no headings — lands at the chunk position by offset with a note. A spreadsheet with thousands of rows — virtualised, landing on the cited row. An image with no OCR text at all — shown with a plain statement that nothing was read from it.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/source-viewer.md` §2 rendering table and §4 poor OCR and unrenderable.
- **Validation Rules:** No rendering may fetch a remote asset.
- **Audit / Logging Requirements:** As M1-VIEW-FE-046.
- **Analytics Events:** Local counter only — nothing transmitted (C1).

**Real-World Example Scenarios**
- A user clicks a card citing a scanned page, sees the OCR text beside the image, and realises the scan garbled a figure.

**Dependencies & Assumptions**
- **Dependencies:** M1-VIEW-FE-046, M1-EXTRACT-ING-027, M1-EXTRACT-ING-029.
- **API / Data Touchpoints:** Extracted text and anchors; document bytes.
- **Assumptions:** Converted text is adequate for reading around a passage; fidelity to the original layout is not promised for Office formats.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start with a corpus containing a Word file, a deck, a spreadsheet and a scanned image. Ask questions that cite each, and click through. Confirm each opens at the right place with the cited content marked, and that the image shows the OCR text alongside.
- **Other scenarios:** Open an unrenderable file and confirm the fallback plus the external option.
- **Known gaps:** Office layout fidelity is not preserved. Database results are not renderable until M4.

**Effort & Granularity Check**
- **Estimate:** 4–6 hours · **Priority:** High
- **Labels / Component:** `phase:1`, frontend
- **Granularity:** Four rendering kinds sharing one anchor contract. Upper bound.

---

### M1-VIEW-FE-048 — Context rail, back to the answer, and citation stepping

**Type:** Story

**User Story**
- **Actor:** someone three clicks deep in a 300-page PDF.
- **User Need:** an obvious way back and a way to step through the other cited passages.
- **Business Value:** losing the way back is how someone ends up lost and stops following citations at all.
- *As someone checking several claims in one answer, I want to step between the cited passages and get back to the answer, so that checking three things is not three round trips.*

**Context / Background**
**Detailed Description:** The viewer's right-hand context rail names which answer sent the user here and which claim it supported, with a clear return. Next and previous citation controls step through every passage cited in that answer without returning first. Search within the source and an ask-about-this-source action complete the rail.

**Scope**
- Context rail with originating answer, claim and return control.
- Next and previous citation stepping across documents where the answer cited more than one.
- Search within the source; copy passage with source and page appended; ask scoped to this source.

**Out of Scope**
- Trace panel (M5).
- Editing memory from here (M3).

**Acceptance Criteria**
- **Acceptance Criteria:** The rail names the originating answer and claim. Return goes to the exact answer and claim, not the top of the conversation. Stepping moves to the next cited passage, including across documents. Copying a passage includes the source and page.
- **Edge Cases:** Arriving from the library rather than an answer — the rail shows source context instead of an answer, with no broken return. An answer with one citation — stepping controls are absent rather than inert. A cited document that was superseded — the banner shows and stepping still works.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/source-viewer.md` §2 context rail and §3 interactions; §4 superseded.
- **Validation Rules:** Return must restore the conversation scroll position at the originating claim.
- **Audit / Logging Requirements:** None beyond viewer opens.
- **Analytics Events:** Local counter of citation steps — nothing transmitted (C1).

**Real-World Example Scenarios**
- A user checks all four cited passages for one answer in about fifteen seconds and returns to exactly where they were.

**Dependencies & Assumptions**
- **Dependencies:** M1-VIEW-FE-046, M1-VIEW-FE-047.
- **API / Data Touchpoints:** `citations` for the originating answer.
- **Assumptions:** The conversation retains enough state to restore the exact claim position after navigation.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, ask a question whose answer cites three passages across two documents. Click the first card. Read the rail — it names the answer and the claim. Step to the next citation twice, crossing into the second document. Press return and confirm you land on the originating answer at the right claim, not at the top.
- **Other scenarios:** Open a source from the library and confirm the rail adapts with no broken return.
- **Known gaps:** No trace access from here. No memory correction from here until M3.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** High
- **Labels / Component:** `phase:1`, frontend
- **Granularity:** One rail and one stepping behaviour.

---

### M1-VIEW-BE-049 — The moved-or-renamed file state, distinct from deleted

**Type:** Story

**User Story**
- **Actor:** someone who reorganised their folders last week.
- **User Need:** to be told the file moved and offered to relocate it, not told it was deleted.
- **Business Value:** indexing in place makes stale paths normal rather than exceptional; treating a moved file as deleted is both wrong and alarming.
- *As someone who tidies their filing occasionally, I want Askwell to say which path is missing and offer to find it, so that reorganising does not look like data loss.*

**Context / Background**
**Detailed Description:** When a document's recorded path no longer resolves, the document is marked missing since a timestamp — not deleted. The viewer names the missing path and offers relocation. Relocation is a manual file pick in v1; where the content hash matches, relocation is confirmed automatically rather than trusted blindly.

**The relocate flow is the second reason the desktop shell exists** (`../decisions.md`, 2026-08-26) — picking a moved file is exactly what a browser tab is poor at. As with root registration, this ticket builds the detection, the hash verification and the repair against whatever selection the browser can offer, keeping the selection step behind one seam so **M7-TAURI-FE-182 substitutes the native dialog without touching the verification or the state machine**.

**Scope**
- Missing detection at open time and during a periodic check.
- The missing state on the document and the source's needs-attention reason.
- Relocation with hash verification, updating the stored path.

**Out of Scope**
- Automatic folder watching (open in `../ux/add-source.md` §6).
- Deletion and tombstones (M2).

**Acceptance Criteria**
- **Acceptance Criteria:** Renaming an indexed file on disk and then clicking its citation produces a message naming the old path and offering relocation, never a deletion message. Relocating to the correct file verifies the hash and restores normal viewing. Relocating to a different file is refused with the hash mismatch named.
- **Edge Cases:** The whole root is unmounted — reported as the root being unavailable rather than every document being missing individually. The file returns to its original path on its own — the missing state clears on the next open. A file moved and also modified — hash mismatch, so the user is offered supersession instead of relocation.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/source-viewer.md` §4 file moved or renamed; `../ux/library.md` §5 needs attention.
- **Validation Rules:** Missing and deleted are separate states and must never be conflated. `missing_since` is set, never `deleted_at`.
- **Audit / Logging Requirements:** Relocation is a decisions record naming both paths.
- **Analytics Events:** Local counter of missing documents — nothing transmitted (C1).

**Real-World Example Scenarios**
- A user renames a contract folder; the library shows needs attention, and relocating the root fixes every affected document.

**Dependencies & Assumptions**
- **Dependencies:** M1-VIEW-FE-046, M1-ADD-ING-021.
- **API / Data Touchpoints:** `documents.path`, `documents.missing_since`, `sources.status`.
- **Assumptions:** Relocation is manual in v1; automatic re-discovery within a registered root is a later improvement and is stated as a known gap. The selection step is provisional until the native dialog lands in M7-TAURI-FE-182.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, add a PDF, ask a question about it, and confirm the citation opens. Quit Askwell, rename the file on disk, and start again. Click the same card. Observe a message saying the file has moved, naming the old path, with a relocate action — and confirm it does not say deleted. Relocate to the renamed file and confirm the viewer opens normally.
- **Other scenarios:** Relocate to a different document and confirm refusal on hash mismatch.
- **Known gaps:** Relocation is manual file-picking, through the browser's own control until M7-TAURI-FE-182 replaces it with the native dialog. No folder watching. Bulk relocation of a moved root may not exist yet.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** High
- **Labels / Component:** `phase:1`, backend, frontend
- **Granularity:** One state, one detection, one repair.

---

### M1-LIB-FE-050 — Library list with status and needs-attention expansion

**Type:** Story

**User Story**
- **Actor:** someone with twenty sources who wants to know if any of them are broken.
- **User Need:** a scannable inventory that expands to the specific problem.
- **Business Value:** one status keeps the list scannable; the detail one click away is what makes it fixable.
- *As someone with a growing corpus, I want one list telling me what Askwell knows and what is wrong, so that I can fix the broken thing without hunting.*

**Context / Background**
**Detailed Description:** Build the library: grouped by source, most recently added first, each row carrying name, kind, size, added time, status and open clarification count. Status is a word plus a shape, never colour alone. Needs attention is one status covering several causes and the row expands to the specific reason with a fix action. Interactions include open, ask-about-this-source, re-index with confirmation, and filter.

**Scope**
- Source list with the row fields and status rendering.
- Needs-attention expansion with the specific reason and a fix that jumps to the right place.
- Re-index with a confirmation that says it can take hours.
- Filters by kind, status and has-open-clarifications.

**Out of Scope**
- Deletion (M2), clarification counts becoming non-zero (M3), connection statuses (M4).
- Per-source storage size, which is an open question in `../ux/library.md` §6.

**Acceptance Criteria**
- **Acceptance Criteria:** Every added source appears with its fields and correct status. A source with a failed document shows needs attention and expands to name that document with a retry. Re-index confirms before starting. Filters work. Status is distinguishable without colour.
- **Edge Cases:** A source with a hundred documents — the row summarises and expands rather than listing all inline. A source indexing right now — progress inline and marked already-askable. Every source healthy — a plain list with no dashboard and no charts.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/library.md` §2, §3, §5; `../ux/design-system.md` §8 for status shape.
- **Validation Rules:** Status must never be conveyed by colour alone.
- **Audit / Logging Requirements:** Re-index is a decisions record.
- **Analytics Events:** Local counters of sources by status — nothing transmitted (C1).

**Real-World Example Scenarios**
- A user returns after an overnight import, sees one source needing attention, expands it, and retries the three failed files.

**Dependencies & Assumptions**
- **Dependencies:** M1-ADD-ING-025, M1-EXTRACT-VAL-030, M1-EXTRACT-ING-029.
- **API / Data Touchpoints:** `sources`, `documents`.
- **Assumptions:** A flat list is right until someone has enough sources to need grouping; collections were deliberately removed.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, add a mixed folder including one corrupt file. Go to the library. Observe the source listed with its kind, size and added time, and a needs-attention status. Expand the row, read the specific reason naming the corrupt file, and use the fix action. Filter to needs-attention only and confirm the list narrows.
- **Other scenarios:** Trigger a re-index and confirm the warning about duration appears before it starts.
- **Known gaps:** No deletion. Clarification counts are always zero. No connections. No per-source storage figure.

**Effort & Granularity Check**
- **Estimate:** 4–6 hours · **Priority:** High
- **Labels / Component:** `phase:1`, frontend
- **Granularity:** One list with one expansion and three filters. Upper bound.

---

### M1-LIB-FE-051 — Empty states that teach rather than say "no items"

**Type:** Story

**User Story**
- **Actor:** someone who has just installed Askwell and has nothing in it.
- **User Need:** to be told what will be possible and given one action.
- **Business Value:** an empty chat box invites a question that will abstain, teaching the user in thirty seconds that the product does not work.
- *As someone who has just installed this, I want the empty screens to tell me what to do, so that my first move is the right one.*

**Context / Background**
**Detailed Description:** Build the empty states collected in `../states-and-edge-cases.md` §7 for the surfaces that exist in M1: Ask with no corpus, the library with no sources, conversation history, and the memory screen's pre-population state where it is reachable. Each names what the surface is for and offers the one action that moves the user forward.

**Scope**
- Ask empty state with no sources: what will be possible, and one action to add a first source.
- Ask empty state with sources present: focused input plus three suggested questions generated from what was actually ingested — real filenames and real terms, not generic prompts.
- Library empty state naming the four ways to add a source.
- Conversation history empty state.

**Out of Scope**
- Memory, clarification and connection empty states, which arrive with their screens.
- The first-run sequence itself (M1-LIB-FE-052).

**Acceptance Criteria**
- **Acceptance Criteria:** With no sources, Ask shows the teaching state and one action rather than an input inviting a doomed question. With sources, Ask shows three suggestions naming real files or real terms from the corpus. The library empty state names all four routes, with the two arriving later marked as such.
- **Edge Cases:** Sources exist but none are indexed yet — the suggestion state says so rather than suggesting questions nothing can answer. A corpus too small to generate three suggestions — fewer are shown rather than padded with generic ones. Suggestions must be generated without an expensive model call at exactly the moment the machine is busy indexing.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/ask.md` §5 first-run and empty; `../ux/library.md` §5 empty; `../states-and-edge-cases.md` §7.
- **Validation Rules:** No empty state may read "no items".
- **Audit / Logging Requirements:** None.
- **Analytics Events:** Local counter only — nothing transmitted (C1).

**Real-World Example Scenarios**
- After indexing three contracts, the user returns to Ask and sees a suggestion naming one of their own files, which is what makes the first question happen.

**Dependencies & Assumptions**
- **Dependencies:** M1-ASK-FE-039, M1-LIB-FE-050.
- **API / Data Touchpoints:** `sources`, `documents`, `chunks` for suggestion generation.
- **Assumptions:** Suggestions are derived from headings, filenames and frequent terms rather than a model call, which is what makes them cheap at load.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Install fresh with nothing added. Open Ask and confirm it teaches rather than presenting an empty input. Follow the single action to add a source, add a PDF, wait for indexing, then return to Ask and confirm three suggestions naming real content from that file. Click one and confirm it asks the question.
- **Other scenarios:** Add a source and open Ask before indexing finishes — the state says indexing rather than suggesting.
- **Known gaps:** Suggestions are heuristic and may be dull. Memory and clarification empty states do not exist yet.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** High
- **Labels / Component:** `phase:1`, frontend
- **Granularity:** Four states plus one cheap generator.

---

### M1-LIB-FE-052 — First-run sequence: what this is, machine check, model, first question

**Type:** Story

**User Story**
- **Actor:** someone in the first ten minutes after downloading a free tool.
- **User Need:** a visible path to a first answer with the end in sight.
- **Business Value:** install-to-first-answer is the metric most likely to kill the product quietly, and a free download has no sunk cost holding anyone.
- *As someone who has just downloaded this and has not decided to trust it, I want a short visible path to my first answer, so that I find out whether it works before I lose patience.*

**Context / Background**
**Detailed Description:** Four steps shown as a list from the start: what this is, check the machine, get the model, add something and ask. Two facts are stated on the first screen rather than discovered later — it works offline, and files stay where they are. The machine check warns and continues below the floor. The model step is the unavoidable wait and is honest about size and time, and sources can be added while it runs.

**Scope**
- The four-step sequence with the list visible from the start.
- Machine check surfacing the profile with what to expect, warning and continuing below the floor.
- Model acquisition step with real progress, size and estimate, resumable and cancellable, and a manual-file path for an offline or badly connected machine.
- Parallel source adding during the model step.
- The passphrase offer, once, skippable, with the consequence of skipping stated.
- Skip-setup path straight to Ask.

**Out of Scope**
- The hardware probe implementation itself (M7-PROBE) — this screen consumes whatever the probe reports and falls back to the standard profile with a statement when it cannot.
- Account, email, sign-in, demo corpus, feature tour and telemetry consent — none of these exist and none may be added.

**Acceptance Criteria**
- **Acceptance Criteria:** The sequence shows all four steps from the start. The machine check reports a profile and what to expect. Below the floor it warns and allows continuing. The model step shows real progress and a real estimate and can be cancelled and resumed. Sources can be added during the model step. The first answer explicitly points out the citation. There is no account, no email field, no sample corpus and no telemetry dialogue anywhere.
- **Edge Cases:** No disk space — refused before the download with the space needed. Download failed — a retry plus the manual model file path, which is the install route for the users who need Askwell most. Returning before finishing — resumes where it stopped rather than restarting. Model ready but no sources — says "ready, add something to ask about" rather than showing an empty chat box.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/first-run.md` §2, §3, §4, §5; `../states-and-edge-cases.md` §1 model downloading and below-floor hardware.
- **Validation Rules:** The model step must never begin without confirming disk space.
- **Audit / Logging Requirements:** Profile selection and passphrase decisions are decisions records.
- **Analytics Events:** Local counters only — nothing transmitted (C1). No consent dialogue, because there is nothing to consent to.
- **C1 note:** the model acquisition step is the one download in the product and it is user-initiated at install; it is not a runtime network call, and after install the manual-file path makes even that avoidable.

**Real-World Example Scenarios**
- A user on a slow connection adds their contracts while the model downloads and asks their first question four minutes after the download finishes.
- An air-gapped user places the model file manually and never makes a network request at all.

**Dependencies & Assumptions**
- **Dependencies:** M1-LIB-FE-051, M1-CITE-FE-043, M0-MODEL-DEPLOY-018.
- **API / Data Touchpoints:** `settings`; the roots registry; the inference process state.
- **Assumptions:** The probe exists in a basic form by M1 or the sequence falls back to the standard profile with a stated reason; the full probe lands in M7.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Install onto a machine that has never run Askwell. Observe the four steps listed. Read the first screen and confirm it states offline operation and in-place indexing. Continue to the machine check and read the profile and what to expect. At the model step, start the download, then add a PDF while it runs and watch both progress bars. When the model lands, ask the generated first question and observe the answer with its citation explicitly pointed out. Restart Askwell and confirm the sequence does not appear again.
- **Other scenarios:** Cancel the download and resume. Simulate a full disk and confirm refusal before download. Use the manual model file path with the network disabled and confirm the whole sequence completes.
- **Known gaps:** The hardware probe may be approximate until M7. Suggested first questions are heuristic. No passphrase enforcement exists yet — the offer stores the preference, and encryption at rest lands in M7.

**Effort & Granularity Check**
- **Estimate:** 4–6 hours · **Priority:** Critical
- **Labels / Component:** `phase:1`, frontend, deployment
- **Granularity:** Four steps sharing one sequence. Upper bound; splitting would ship a partial first run, which is the worst place to ship a partial anything.

---

### M1-CONV-BE-177 — Store a one-line summary and a source count with every turn

**Type:** Story

**User Story**
- **Actor:** someone on the fourth question of a conversation, scrolling back to find what they asked second.
- **User Need:** each past turn to describe itself accurately, in a way that does not change afterwards.
- **Business Value:** the collapsed view is only trustworthy if what it says about a turn is what was true when the turn happened; a summary recomputed later against a changed corpus makes the user's own history unreliable.
- *As someone whose conversations run to a dozen questions, I want each past turn to carry the summary it earned at the time, so that scrolling back tells me what actually happened rather than what would happen now.*

**Context / Background**
**Detailed Description:** `../ux/conversation.md` §2 collapses a past turn to three things: the question, a one-line summary of what answered it, and a source count in the provenance colour. §6 is explicit that **the summary is stored with the turn and never recomputed** — re-running a past turn to produce its label would make the record of a conversation depend on the state of the corpus at the moment someone scrolled.

This ticket produces both values at composition time and writes them with the turn. The source count is derived from the citation rows that turn actually produced, so it is a count of evidence rather than an estimate. **A turn that abstained gets no count at all** — not zero, absent — because §2 makes the absence itself the signal that a run of questions went unanswered.

**Scope**
- A one-line summary generated once, at composition time, and stored on the turn.
- A source count stored with the turn, derived from its citation rows.
- The distinction between "no sources" and "abstained", stored explicitly rather than inferred from a count of zero.
- Both values immutable once written, alongside the answer they describe.

**Out of Scope**
- Rendering (M1-CONV-FE-178).
- Suggested follow-ups (M1-CONV-FE-180).
- Any re-summarisation, re-scoring or backfill of past turns — deliberately, and permanently.
- The web marker on a turn that used web search (M6.5-WEB-FE-192).

**Acceptance Criteria**
- **Acceptance Criteria:** Composing an answer writes a one-line summary and a source count with the turn, in the same transaction as the answer. Reading a turn back later returns the stored values without any model call. Deleting a source that a past turn cited does **not** change that turn's stored count. Adding new sources does not change any past turn's summary.
- **Edge Cases:** An answer that abstained — a summary is stored saying so, and **no source count is stored**, distinguishable from a stored count of zero. A partial answer — the count reflects the grounded part and the summary names the gap. A turn stopped mid-generation — the partial answer's summary describes what was produced and is marked partial rather than being omitted. Summary generation itself fails — the turn stores a fallback derived from the question rather than blocking the answer, and the failure is logged; an answer must never fail because its label could not be written. A conflicting-sources answer — the count includes both sides, since both were cited.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** Consumed by `../ux/conversation.md` §2 and §5; `../states-and-edge-cases.md` §7.1.
- **Validation Rules:** A stored summary is never overwritten. A source count is never recomputed on read. An abstained turn must have no count, not a zero.
- **Audit / Logging Requirements:** The summary and count are part of the interaction record (M1-ASK-OBS-041), written with it rather than beside it. Summary-generation failures are logged with the reason.
- **Analytics Events:** Local counter of turns per conversation — nothing transmitted (C1).

**Real-World Example Scenarios**
- A user asks six questions about a supplier contract, then deletes the contract. Scrolling back, the earlier turns still say they cited three sources, and expanding one shows the tombstone — the history is honest about what it had at the time.
- A user adds a new source that would have answered question two. Question two's summary still says the files did not cover it, because that is what happened.

**Dependencies & Assumptions**
- **Dependencies:** M1-CITE-BE-042, M1-ASK-OBS-041.
- **API / Data Touchpoints:** `messages` or the turn record; `citations`; the interaction record.
- **Assumptions:** A one-line summary can be produced cheaply enough at composition time not to add noticeable latency to an answer the user is already waiting for; if it cannot, it is produced immediately after streaming completes rather than being deferred to read time.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start with two indexed PDFs. Ask three questions that the documents cover and one they plainly do not. Restart Askwell entirely. Return to the conversation and confirm each of the first three turns carries a short description of its answer and a number of sources, and that the fourth carries a description saying the files did not cover it and **no number at all**. Delete one of the PDFs and reload — confirm the earlier counts are unchanged.
- **Other scenarios:** Stop an answer mid-stream and confirm the turn still gets a summary, marked partial. Add a new document and confirm no past summary changes.
- **Known gaps:** Nothing renders these values yet — that is M1-CONV-FE-178. Summaries are not editable by the user and there is no plan for that. Turns that used web search carry no web marker until M6.5.

**Effort & Granularity Check**
- **Estimate:** 2–3 hours · **Priority:** High
- **Labels / Component:** `phase:1`, backend, `constraint:grounding`
- **Granularity:** Two stored values and one rule about never recomputing them. Small because composition already knows both.

---

### M1-CONV-FE-178 — Past turns collapse; an abstained turn shows no source count

**Type:** Story

**User Story**
- **Actor:** someone four questions into following a thread through their contracts.
- **User Need:** the conversation to stay readable as it grows, without losing sight of which answers were grounded.
- **Business Value:** a stack of full answers with three provenance margins between the user and the question they are looking for is worse than useless by the fourth turn — and the product's central claim is exactly what a careless collapse would hide first.
- *As someone whose questions build on each other, I want past turns to shrink to a line I can scan, so that a long conversation stays navigable.*

**Context / Background**
**Detailed Description:** `../ux/conversation.md` §2: **past turns collapse, the live turn does not.** A collapsed turn shows the question in full on one line (truncated with an ellipsis if it must be), the stored one-line summary, and the source count in the provenance colour. The live turn renders exactly as `../ux/ask.md` describes, margin and all.

**The source count is not decoration.** Collapsing may hide the detail of the evidence, never the fact that evidence existed. A turn showing no count is a turn that abstained, and §2 requires that to be visible at a glance — it is how a user notices a run of unanswerable questions and thinks to add a source instead of asking a fifth time.

Turns are separated by simple dividers — *earlier today*, *yesterday*, a date. §4: no per-turn timestamp, because the interval matters and the clock time does not.

**Scope**
- Collapsed presentation: question, stored summary, source count in `--provenance`.
- The live turn rendering uncollapsed with its full margin.
- The previous live turn collapsing when a new question is asked.
- The abstained variant: no count, and a summary that says so, visibly different from an answered turn at a glance.
- Time dividers between turns.

**Out of Scope**
- Expanding a collapsed turn and paging (M1-CONV-FE-179).
- Suggested follow-ups (M1-CONV-FE-180).
- Generating or storing the summary and count (M1-CONV-BE-177).
- The web marker on a collapsed turn (M6.5-WEB-FE-192).

**Acceptance Criteria**
- **Acceptance Criteria:** With one turn present, nothing collapses and no dividers appear — the screen is exactly `../ux/ask.md`. Asking a second question collapses the first to question, summary and count, and renders the second in full with its margin. The count is in the provenance colour and nothing else on the collapsed row is. A collapsed turn that abstained shows **no count**, and the difference from an answered turn is apparent without reading the summary. The live turn is never collapsed.
- **Edge Cases:** A question longer than one line — truncated with an ellipsis, with the full text available on expansion, never wrapped to three lines. A turn that abstained sitting between two answered turns — the absent count reads as absent rather than as a rendering failure; **shape as well as colour carries it** (`../ux/design-system.md` §8, colour is never the only signal). A partial answer — collapsed with its count and a summary naming the gap. A turn citing a source deleted since — the count reflects what was cited then (`../ux/conversation.md` §5). A new question asked while an answer streams — queued, not interleaved; the streaming turn stays live and collapses only when its own answer completes.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/conversation.md` §2, §4, §5; `../states-and-edge-cases.md` §7.1; `../ux/design-system.md` §2 for `--provenance` being reserved.
- **Validation Rules:** A collapsed turn may never omit its source count when one was stored. `--provenance` appears on the count and on nothing else in the collapsed row — it is reserved, and spending it elsewhere is how it stops meaning "you can check this".
- **Audit / Logging Requirements:** None — this is presentation over values already recorded.
- **Analytics Events:** Local counter of turns per conversation — nothing transmitted (C1).

**Real-World Example Scenarios**
- A user asks about supplier terms, then about one supplier, then about that supplier's invoices. The first two shrink to scannable lines while the third keeps its margin, and the whole thread fits on one screen.
- Three consecutive turns show no source count. The user notices the run, realises the relevant folder was never added, and adds it — which is exactly the behaviour the absent count exists to produce.

**Dependencies & Assumptions**
- **Dependencies:** M1-CONV-BE-177, M1-ASK-FE-039, M1-CITE-FE-043.
- **API / Data Touchpoints:** The stored turn summary and count.
- **Assumptions:** The stored summary is short enough to sit on one line at the specified measure; if it is not, it is truncated in the same way the question is rather than the row growing.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start with an indexed PDF. Ask one question and confirm the screen looks exactly like the single-answer screen — no collapsing, no divider. Ask a second and watch the first shrink to one line carrying the question, a short description and a number in the provenance colour, while the second answer streams with its margin intact. Ask a third question the documents plainly do not cover; when it collapses, confirm it carries no number and that you can tell at a glance it is different from the other two without reading the words. Leave Askwell overnight, return, ask another question and confirm a divider reading *yesterday* separates the old turns.
- **Other scenarios:** Ask a very long question and confirm the collapsed row truncates rather than wrapping. Switch to the dark theme and confirm the abstained turn is still distinguishable. Ask a new question while an answer is streaming and confirm it queues rather than interleaving.
- **Known gaps:** Collapsed turns cannot yet be expanded — that is the next ticket, and until it lands the detail is genuinely unreachable, which is why the two ship together. No paging of very long conversations yet. No follow-up suggestions. A turn that used web search has no marker until M6.5.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** High
- **Labels / Component:** `phase:1`, frontend, `constraint:grounding`
- **Granularity:** One collapsed presentation and one transition. The expansion half is split out to keep this at the bound.

---

### M1-CONV-FE-179 — Expanding a past turn, clicking a source count, and paging a long conversation

**Type:** Story

**User Story**
- **Actor:** someone who wants to re-read the evidence behind an answer they got ten minutes ago.
- **User Need:** to open a past turn back up, in place, with its margin.
- **Business Value:** collapsing without expanding does not compress a conversation, it deletes it. The evidence has to be one click away or the citation stops being checkable, which is C4.
- *As someone who wants to check where an earlier figure came from, I want to open that turn back up where it sits, so that I do not lose my place in the thread.*

**Context / Background**
**Detailed Description:** `../ux/conversation.md` §3. Clicking a collapsed turn expands it **in place**, with its full answer and its full margin, and leaves every other turn collapsed. Clicking a collapsed turn's source count expands it *and* scrolls to its margin. §5: older turns page in on scroll and are **never truncated silently** — a conversation that quietly stops having a beginning is a conversation the user cannot trust.

Expansion restores what was stored, not what would be produced now. A citation to a since-deleted source expands to the tombstone (M2-DELETE-FE-062), which is the honest thing rather than a gap.

**Scope**
- Expand in place on clicking a collapsed turn, restoring answer and margin.
- Expand-and-scroll-to-margin on clicking the source count.
- Independent expansion: expanding one turn collapses nothing else.
- Re-collapsing an expanded past turn.
- Paging older turns in on scroll, with a visible boundary rather than a silent end.
- Keyboard parity: a collapsed turn is focusable and expands from the keyboard.

**Out of Scope**
- Editing a past question and re-asking — not v1 (`../ux/conversation.md` §7).
- Suggested follow-ups (M1-CONV-FE-180).
- Deletion and tombstones themselves (M2-DELETE-FE-062).

**Acceptance Criteria**
- **Acceptance Criteria:** Clicking a collapsed turn expands it in place with the full answer and the full margin, and no other turn changes state. Clicking a source count expands the turn and brings its margin into view. An expanded past turn can be collapsed again. Scrolling to the top of a long conversation loads older turns and shows that it is doing so; when there are genuinely no more, it says so rather than simply stopping. Every one of these works from the keyboard.
- **Edge Cases:** Expanding a past turn **while a new answer is streaming** — both render; the live turn keeps streaming and is not disturbed. Several past turns expanded at once — permitted; the user chose it. A turn whose citation points at a since-deleted source — expands showing the tombstone card, greyed and not clickable, not an empty margin. A very long expanded answer pushing the live turn off screen — the user's scroll position is preserved rather than jumping. Expanding while the window is below the breakpoint — the margin reflows inline for that turn, with its `--rule-strong` edges, and is still complete. Paging fails to load older turns — says so and offers to retry; **never renders a shorter conversation as if it were the whole one**.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/conversation.md` §3, §5; `../states-and-edge-cases.md` §7.1; `../ux/design-system.md` §4 for the reflowed margin.
- **Validation Rules:** A conversation is never silently truncated. An expanded turn shows exactly what was stored, never a regenerated answer.
- **Audit / Logging Requirements:** None — reading stored records.
- **Analytics Events:** Local counter of expansions — nothing transmitted (C1).

**Real-World Example Scenarios**
- A user reads a number in a summary from three questions ago, clicks the source count, lands on the card, clicks through to the page, and returns to the same place in the thread.
- A user scrolls back through forty turns, sees the paging boundary load more, and reaches the actual first question rather than a truncation.

**Dependencies & Assumptions**
- **Dependencies:** M1-CONV-FE-178, M1-CITE-FE-043, M1-CITE-FE-044.
- **API / Data Touchpoints:** Stored turns and their citation rows; a paged read of the conversation.
- **Assumptions:** How far back a conversation runs before paging is unspecified in `../ux/conversation.md` §7 and needs real conversations to answer; a conservative page size is chosen and the number is recorded so it can be tuned rather than rediscovered.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start with an indexed corpus. Ask five questions in sequence. Click the second collapsed turn and watch it open in place with its answer and its source cards, while the others stay collapsed. Click one of its cards and land on the highlighted page; come back and confirm you are still at the same point in the conversation. Collapse it again. Click a third turn's source number and confirm it opens *and* the margin is brought into view. Now ask a sixth question and, while it is streaming, expand an old turn — confirm the streaming answer is unaffected.
- **Other scenarios:** Ask enough questions to trigger paging, scroll to the top, and confirm older turns load with a visible boundary. Narrow the window and expand a past turn, confirming its cards appear inline and complete. Expand a turn citing a document you have since deleted and confirm the tombstone.
- **Known gaps:** Past questions cannot be edited or re-asked — deliberately not v1. The page size is a guess until there are real conversations to measure. Suggested follow-ups arrive in the next ticket.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** High
- **Labels / Component:** `phase:1`, frontend
- **Granularity:** One expansion, one scroll target and one paging rule, over presentation that already exists.

---

### M1-CONV-FE-180 — Suggested follow-ups that fill the composer rather than sending

**Type:** Story

**User Story**
- **Actor:** someone who has just read an answer and can feel there is a next question but has not phrased it yet.
- **User Need:** a cheap start on the next question, without it being asked for them.
- **Business Value:** most real use is follow-up, and the cost of phrasing the second question is where a conversation stops. Lowering that cost is worth doing; removing the decision is not.
- *As someone who has just learned that one supplier is on non-standard terms, I want a suggested next question I can edit before sending, so that following the thread is cheap but still mine.*

**Context / Background**
**Detailed Description:** `../ux/conversation.md` §3: after an answer, up to three suggestions derived from what was just answered — *"show me Meridian's open invoices"*, *"how did you get this?"*. **They fill the composer; they do not send.** A suggestion that fires immediately takes the decision away, and the point is to lower the cost of the next question rather than to ask it for the user.

That distinction is the whole ticket. Everything else here is presentation.

**Scope**
- Up to three suggestions rendered after a completed answer, derived from that answer.
- Clicking one places its text in the composer, focused and editable, with the cursor at the end.
- Suggestions clear when the next question is submitted.
- Keyboard reachability for each suggestion.

**Out of Scope**
- Any automatic sending, under any circumstance.
- Suggestions on the abstention surface — that surface offers escalations instead, and mixing the two would blur an offer to look outside with an offer to ask more (`../ux/web-search.md` §2, M6.5-WEB-FE-186).
- Suggestions during streaming.

**Acceptance Criteria**
- **Acceptance Criteria:** After a completed answer, up to three suggestions appear, each clearly derived from that answer rather than generic. Clicking one fills the composer with its text, focused and editable, and **sends nothing**. Editing the filled text and pressing Enter sends the edited version. Submitting any question clears the suggestions. Every suggestion is reachable and activatable from the keyboard.
- **Edge Cases:** An answer that supports no sensible follow-up — **fewer than three, or none at all**; three suggestions are a maximum, not a quota, and padding produces generic filler that trains the user to ignore the whole row. An abstained answer — no suggestions; the abstention surface has its own offers. A partial answer — suggestions may address the gap, since that is genuinely the useful next question. A suggestion clicked while the composer already has text — the user is not silently overwritten; the existing draft is preserved or replacement is explicit. Suggestion generation fails — nothing renders, and the answer is unaffected; this is an accelerator and must never be able to break an answer.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/conversation.md` §3; `../ux/ask.md` §4 "Suggested follow-ups".
- **Validation Rules:** **A suggestion may never dispatch a question.** No configuration, shortcut or double-click may make it do so.
- **Audit / Logging Requirements:** A question originating from a suggestion is recorded as an ordinary question; nothing distinguishes it, because the user sent it.
- **Analytics Events:** Local counter of suggestions used — nothing transmitted (C1).

**Real-World Example Scenarios**
- A user reads that Meridian has 45-day terms, clicks *"show me Meridian's open invoices"*, changes it to *"show me Meridian's overdue invoices"*, and sends — which is exactly the behaviour filling rather than sending is for.
- An answer about a single date produces no useful follow-up, so no row appears, and the user does not learn to ignore a row of filler.

**Dependencies & Assumptions**
- **Dependencies:** M1-CONV-FE-178, M1-ASK-FE-039.
- **API / Data Touchpoints:** The completed answer; the composer.
- **Assumptions:** Suggestions can be produced after streaming completes without delaying the answer the user is reading; if generation is slow, the row appears late rather than the answer arriving late.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start with an indexed contract. Ask a question with a substantive answer. When it finishes, read the suggestions and confirm they are about *this* answer rather than generic prompts. Click one and watch the text land in the composer with the cursor in it — and confirm nothing was sent. Edit a word and press Enter; confirm the edited question is what was asked. Then ask a question the corpus cannot answer and confirm no suggestions appear beneath the abstention.
- **Other scenarios:** Type a draft, then click a suggestion, and confirm your draft is not silently destroyed. Tab to a suggestion and activate it from the keyboard. Ask a question with a very narrow answer and confirm fewer than three, or none, rather than padding.
- **Known gaps:** Suggestions are heuristic and will sometimes be poor; they are cheap to ignore because they never send. None on the abstention surface — that surface gets its escalation offers in M6.5.

**Effort & Granularity Check**
- **Estimate:** 2–3 hours · **Priority:** Medium
- **Labels / Component:** `phase:1`, frontend
- **Granularity:** One row of controls and one rule about what they must not do. Small.
