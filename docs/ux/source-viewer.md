# Screen: Source viewer

Where a citation lands. The screen that makes "you can check this" true rather than claimed.

> **This document is the specification. Any mockup is a reference.**

**Route:** `/sources/:id?page=14&chunk=…`
**Entry points:** any citation card, any claim, the library.
**Phase:** 1

---

## 1. What it is for

C4 makes every claim carry a citation. A citation nobody can follow is decoration, so this screen is what converts the constraint into something real.

It has one job: **land on the passage, highlighted, in under a second**, so checking an answer is cheap enough that people actually do it. If checking costs more than re-reading the source themselves, they stop trusting the citations and the product's central claim quietly dies.

---

## 2. Shape

Document on the left, context on the right.

- **Document pane** — the source, at the cited position, with the retrieved passage highlighted. Not an extract: the real document, so the user can read around it. A passage that looks wrong in isolation and right in context is exactly the case this must handle.
- **Context rail** — which answer sent them here, the claim it supported, and *back to the answer*. Losing the way back is how someone ends up lost in a 300-page PDF.

### What renders where

| Kind | Rendering |
| ---- | --------- |
| PDF | Rendered in-app, scrolled to the page, passage highlighted |
| Word, PowerPoint, text, HTML, Markdown | Converted text with structure preserved, heading anchored |
| Spreadsheet, CSV | The table, scrolled to the row, row highlighted |
| Database | The table with the query's rows, plus the query |
| Image | The image, with the OCR text alongside so the user can see what was read |

**PDF renders in-app rather than opening the OS viewer.** Handing off loses the highlight, loses the way back, and on some systems opens a program that takes ten seconds to start. This is the cost of the citation loop being credible and it is worth paying.

The image case matters more than it looks: showing OCR text beside the scan is how someone discovers that a bad scan is why an answer was wrong.

---

## 3. Interactions

| Action | Result |
| ------ | ------ |
| Back to answer | Returns to the exact answer and claim |
| Next / previous citation | Steps through every passage cited in that answer without going back |
| Search within source | Plain text find |
| Ask about this source | Ask, scoped |
| Open in system app | Available, secondary. Some people want their own PDF tool |
| Copy passage | With source and page appended |

---

## 4. States

| State | What is shown |
| ----- | ------------- |
| **Loaded at citation** | Passage highlighted, position visible in the document |
| **Loading a large PDF** | Cited page first, rest streams. Never a whole-document wait |
| **Deleted source** | *"Deleted on 3 June. Askwell no longer has the contents."* The citation resolves honestly instead of breaking (#11) |
| **File moved or renamed** | Askwell indexed in place, so the path can go stale. Say which path is missing and offer to relocate — do not treat it as deleted |
| **Superseded** | Banner: this version was replaced on *date*, with a link to current. Old answers cited the old version and must still resolve to it |
| **Poor OCR** | Flagged, with the extracted text shown beside the image so the user can see the gap |
| **Passage not locatable** | Falls back to the page with a note that the exact passage could not be pinpointed. Honest degradation beats a wrong highlight |
| **Unrenderable** | Extracted text with a note, plus open-in-system-app |

**File moved is the common one.** Indexing in place is the right default for a personal corpus and it makes stale paths inevitable. Treating a moved file as deleted would be wrong and alarming.

---

## 5. Open

1. **Settled: pdf.js, bundled locally.** Recorded in `../architecture.md` §1. It renders offline with no service, it is the same engine the browser already ships so behaviour matches what users expect from a PDF, and `pypdfium2` supplies the text and coordinates on the extraction side. No CDN, ever (C1).
2. **Settled: scanned pages highlight at page level in v1.** Mapping OCR output back to pixel regions needs per-word bounding boxes carried through extraction, and getting it slightly wrong highlights the wrong sentence — which is worse than highlighting the page, because a confident wrong highlight is a citation that lies. Passage-level highlighting on scans is separate later work.
3. **Open: per-source index size display** (`library.md`) once the storage budget bites.
