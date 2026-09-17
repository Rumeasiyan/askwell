# Manual test — M3-REVIEW-FE-073, one question's anatomy with its evidence

**Ticket:** `M3-REVIEW-FE-073` — each clarification item renders subject, question, evidence, a prefilled answer field and the current inference with its hollow marker, per `docs/ux/clarifications.md` §3. Discrete choices render as buttons. Skip carries equal weight to Save. Save/Skip behaviour is `-074`'s own scope — both buttons are inert here.
**Version under test:** `0.3.7`
**Time:** about 20 minutes, on top of an already-running stack (this walkthrough assumes `M3-REVIEW-FE-072`'s cold start already happened once).
**Who can run it:** a browser, and `psql` access via `scripts/dev.sh psql`.

**What is being checked.** `web/components/clarifications/clarifications-screen.tsx`'s `ClarificationItemRow` and `EvidenceBlock`, and the pure formatting they call in `web/lib/clarifications.ts` (`evidenceDisplay`, `currentInference`, `rowCountLabel`).

**Where this stops on purpose.** Save and Skip do nothing when clicked — no request fires, no confirmation copy, no undo. That is `M3-REVIEW-FE-074`.

---

## Real triggers vs. seeded evidence

The `abbreviation`, `unreadable_scan` and `document_identity` triggers are reachable end to end by following `M3-REVIEW-FE-072`'s own walkthrough (Part B/C) — that gets you `passage`-kind evidence with a free-text field, and a `document_identity` item with discrete file-choice buttons. `contradiction` evidence needs two sources genuinely disagreeing on a number, which is slower to set up by hand. `column_distribution` has no trigger wired to it at all yet (M4's own column-ambiguity work) — nothing in the running app produces it today.

To see every evidence kind at once without waiting on triggers, seed rows directly:

```bash
scripts/dev.sh psql <<'SQL'
INSERT INTO sources (id, kind, name, status, added_at) VALUES
  ('11111111-1111-1111-1111-111111111111', 'file', 'contracts', 'ready', now())
ON CONFLICT (id) DO NOTHING;

INSERT INTO clarifications (id, source_id, subject, question, options, evidence, rank, status, asked_at) VALUES
  ('22222222-2222-2222-2222-222222222221', '11111111-1111-1111-1111-111111111111',
   'students.st_cd', 'What does st_cd mean?', NULL,
   '{"kind":"column_distribution","row_count":40112,"values":[{"value":"A","count":31204},{"value":"T","count":6890},{"value":"D","count":2018}],"remainder_count":0,"current_inference":"status code"}'::jsonb,
   1, 'pending', now()),
  ('22222222-2222-2222-2222-222222222225', '11111111-1111-1111-1111-111111111111',
   'scan.pdf', 'Page 4 of scan.pdf scanned poorly and produced little text. Re-scan, or index as-is?',
   '["Re-scan","Index as-is"]'::jsonb,
   '{"kind":"poor_scan","pages":[4],"total_pages":10,"extracted_text":[{"page":4,"text":"garbled ocr text"}],"page_images":"not available","current_inference":"scan.pdf: indexed as-is. 1 of 10 page(s) scanned poorly, below the materiality threshold to ask about."}'::jsonb,
   2, 'pending', now()),
  ('22222222-2222-2222-2222-222222222226', '11111111-1111-1111-1111-111111111111',
   'XYZ', 'XYZ appears throughout. What does it mean?', NULL,
   '{"kind":"unavailable","reason":"no locatable passage for XYZ","current_inference":null}'::jsonb,
   3, 'pending', now());
SQL
```

## Walkthrough

### 1. Open the screen

Click **Clarifications** in the left rail.

**You should see:** three cards under the `contracts` group.

### 2. The free-text item with a real guess

The `students.st_cd` card:

- Subject `students.st_cd` in mono.
- Question in serif: *What does st_cd mean?*
- Evidence in mono: `40,112 rows. Values: A (31,204) · T (6,890) · D (2,018)`.
- A text field already containing `status code`.
- Beside Save/Skip, a small hollow square in ochre (`--inferred`) followed by `I guessed: status code`.

### 3. The discrete item

The `scan.pdf` card:

- Evidence line naming how many of how many pages scanned poorly, then the extracted (garbled) text with its page number.
- **Two buttons**, `Re-scan` and `Index as-is` — no text field.
- The inference line names what happens if skipped.

### 4. The no-evidence item

The `XYZ` card:

- Evidence line reads `No evidence available — no locatable passage for XYZ.` rather than an empty block.
- Text field is empty (nothing to prefill).
- **No inference line at all** — there is nothing safe to guess, so the marker is absent rather than showing a fake one. Confirm this is genuinely blank, not a marker with empty text.

### 5. Skip is not visually secondary

On any card, compare Save and Skip: same fill, same border, same height, same font size. Neither reads as the "real" button and the other as an afterthought.

### 6. Clean up

```bash
scripts/dev.sh psql <<'SQL'
DELETE FROM clarifications WHERE source_id = '11111111-1111-1111-1111-111111111111';
DELETE FROM sources WHERE id = '11111111-1111-1111-1111-111111111111';
SQL
```

---

## Known gaps

- **Truncation itself is not exercised by this walkthrough.** `_bound_text` (`api/src/askwell/clarify.py`) runs when a real detector writes evidence, not on display — a seeded row bypasses it, so this doc cannot demonstrate a passage actually being cut to 500 chars without a real abbreviation trigger producing one that long. Not a defect; a limit of testing via seeded rows rather than the real detection path.

- **No link from a passage to its source.** The ticket's edge case calls for a long passage to be "truncated with a link to the source." Truncation is real — `_bound_text` in `api/src/askwell/clarify.py` caps any passage at `EVIDENCE_PASSAGE_MAX_CHARS` (500) server-side, ending it with `…` — but the link is not: no evidence shape carries a `document_id`, only a filename string, so the truncated text renders unclickable. Tracked as #280.
- **Save and Skip do nothing.** `M3-REVIEW-FE-074`.
- **`column_distribution` has no real trigger yet.** M4's own column-ambiguity work; only reachable today via the seeded row above.
