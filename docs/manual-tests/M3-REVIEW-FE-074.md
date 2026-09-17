# Manual test — M3-REVIEW-FE-074, save, skip, skip-all, undo, the specific confirmation

**Ticket:** `M3-REVIEW-FE-074` — saving a clarification writes the fact, marks affected material for re-processing, and confirms specifically what changed (never a generic toast); skip keeps the inference and is never re-raised; skip-all dismisses a whole group and records it; undo reverses a save within its window. `docs/ux/clarifications.md` §4 and §5.
**Version under test:** `0.3.11`
**Time:** about 30 minutes, on top of an already-running stack.
**Who can run it:** a browser, and `psql` access via `scripts/dev.sh psql`.

**What is being checked.** `web/components/clarifications/clarifications-screen.tsx` (`submit`, `handleSkip`, `handleUndo`, `SourceGroup`'s dismiss-all), the pure logic in `web/lib/clarifications.ts` (`savedConfirmation`, `isBlankAnswer`, `mergeIncoming`), and the backend it calls, `api/src/askwell/review.py` (`answer_clarification`, `skip_clarification`, `dismiss_group`, `undo_answer`).

**Where the previous ticket left off.** `M3-REVIEW-FE-073` established that Save and Skip render but do nothing when clicked. This ticket wires them up — everything below is now live.

---

## Cold start

1. Bring the stack up:

   ```bash
   podman compose up -d
   ```

2. Open `http://localhost:3000` (or the port `scripts/dev.sh` prints) in a browser.

   **You should see:** the Ask screen, with the left rail showing **Ask**, **Library**, **Clarifications**, **Memory**, **Settings**. If this is a genuinely empty install you land on the welcome screen first — click through it (it does not gate anything below).

3. Click **Clarifications** in the left rail.

   **You should see:** either "Nothing to clarify. Askwell asks when it finds something it can't work out — an unlabelled column, a date format, two documents that disagree." (a clean database) or a list left over from earlier testing. Either way, no badge count next to **Clarifications** in the rail if the queue is empty.

## Seed a queue to act on

Real triggers (abbreviation detection, a poor OCR scan, two documents disagreeing) are slow to set up by hand and are `M3-REVIEW-FE-072`/`-073`'s own territory. As `-073`'s own manual test does, seed rows directly so every action in this ticket has something concrete to act on:

```bash
scripts/dev.sh psql <<'SQL'
INSERT INTO sources (id, kind, name, status, added_at) VALUES
  ('11111111-1111-1111-1111-111111111111', 'file', 'contracts', 'ready', now()),
  ('33333333-3333-3333-3333-333333333333', 'file', 'invoices', 'ready', now())
ON CONFLICT (id) DO NOTHING;

INSERT INTO documents (id, source_id, filename, path, sha256, status) VALUES
  ('44444444-4444-4444-4444-444444444441', '11111111-1111-1111-1111-111111111111',
   'contract-a.pdf', '/tmp/contract-a.pdf', md5('a'), 'ready'),
  ('44444444-4444-4444-4444-444444444442', '11111111-1111-1111-1111-111111111111',
   'contract-b.pdf', '/tmp/contract-b.pdf', md5('b'), 'ready')
ON CONFLICT (id) DO NOTHING;

INSERT INTO clarifications (id, source_id, subject, question, options, evidence, rank, status, asked_at) VALUES
  ('22222222-2222-2222-2222-222222222221', '11111111-1111-1111-1111-111111111111',
   'students.st_cd', 'What does st_cd mean?', NULL,
   '{"kind":"column_distribution","row_count":40112,"values":[{"value":"A","count":31204},{"value":"T","count":6890},{"value":"D","count":2018}],"remainder_count":0,"current_inference":"status code"}'::jsonb,
   1, 'pending', now()),
  ('22222222-2222-2222-2222-222222222225', '11111111-1111-1111-1111-111111111111',
   'scan.pdf', 'Page 4 of scan.pdf scanned poorly and produced little text. Re-scan, or index as-is?',
   '["Re-scan","Index as-is"]'::jsonb,
   '{"kind":"poor_scan","pages":[4],"total_pages":10,"extracted_text":[{"page":4,"text":"garbled ocr text"}],"current_inference":"scan.pdf: indexed as-is."}'::jsonb,
   2, 'pending', now()),
  ('22222222-2222-2222-2222-222222222226', '11111111-1111-1111-1111-111111111111',
   'XYZ', 'XYZ appears throughout. What does it mean?', NULL,
   '{"kind":"unavailable","reason":"no locatable passage for XYZ","current_inference":null}'::jsonb,
   3, 'pending', now()),
  ('22222222-2222-2222-2222-222222222227', '11111111-1111-1111-1111-111111111111',
   'ABC', 'ABC appears throughout. What does it mean?', NULL,
   '{"kind":"unavailable","reason":"no locatable passage for ABC","current_inference":null}'::jsonb,
   4, 'pending', now()),
  ('22222222-2222-2222-2222-222222222228', '11111111-1111-1111-1111-111111111111',
   'DEF', 'DEF appears throughout. What does it mean?', NULL,
   '{"kind":"unavailable","reason":"no locatable passage for DEF","current_inference":null}'::jsonb,
   5, 'pending', now()),
  ('22222222-2222-2222-2222-222222222231', '33333333-3333-3333-3333-333333333333',
   'GRN', 'What does GRN mean?', NULL,
   '{"kind":"unavailable","reason":"no locatable passage for GRN","current_inference":null}'::jsonb,
   1, 'pending', now()),
  ('22222222-2222-2222-2222-222222222232', '33333333-3333-3333-3333-333333333333',
   'PO', 'What does PO mean?', NULL,
   '{"kind":"unavailable","reason":"no locatable passage for PO","current_inference":null}'::jsonb,
   2, 'pending', now());
SQL
```

Reload the Clarifications page.

**You should see:** a **contracts** group with 5 items and an **invoices** group with 2, 7 total at the top, and a **Clarifications** badge reading `7` in the left rail.

---

## Walkthrough

### 1. Save writes the fact and names what it is re-reading

On the **contracts** group, find the `students.st_cd` card. Its field is prefilled with `status code` (the inference). Change nothing — press **Enter** in the field, or click **Save**.

**You should see:** the card's form is replaced by a confirmation reading exactly **"Saved. Re-reading 2 documents."** (the source has two live documents and this evidence names none by itself, so the fallback count applies) with an **Undo (10s)** button counting down each second.

Check the database while the undo window is open:

```bash
scripts/dev.sh psql -c "SELECT status, answer FROM clarifications WHERE subject = 'students.st_cd';"
scripts/dev.sh psql -c "SELECT subject, fact, origin, confidence FROM memory WHERE subject = 'students.st_cd';"
scripts/dev.sh psql -c "SELECT kind FROM audit_decisions ORDER BY occurred_at DESC LIMIT 1;"
```

**You should see:** the clarification is `answered` with `answer = 'status code'`; a `memory` row exists with `fact = 'status code'`, `origin = 'clarification'`, `confidence = 1.0`; the newest `audit_decisions` row is `clarification_answered`.

### 2. The item advances without navigation

Wait past 10 seconds (or continue to the next step, which happens well within it — come back to confirm this once the window elapses).

**You should see:** once the 10s pass, the `students.st_cd` card disappears from the list on its own — no reload, no route change — and the group count and the total at the top both drop by one. The rail badge drops from 7 to 6.

### 3. Undo reverses a save cleanly

Repeat step 1 on a fresh item so there is time to act: on the `ABC` card, type `test fact for ABC` and press Enter.

**You should see:** **"Saved. Re-reading 2 documents."** and the Undo button.

Within the 10s window, click **Undo (10s)**.

**You should see:** the card returns to its normal editable state — Save/Skip buttons back, its field showing nothing prefilled (this item has `current_inference: null`) — and it does **not** leave the list.

Verify in the database:

```bash
scripts/dev.sh psql -c "SELECT status, answer FROM clarifications WHERE subject = 'ABC';"
scripts/dev.sh psql -c "SELECT count(*) FROM memory WHERE subject = 'ABC';"
scripts/dev.sh psql -c "SELECT kind FROM audit_decisions WHERE kind LIKE 'clarification%' ORDER BY occurred_at DESC LIMIT 3;"
```

**You should see:** `status = 'pending'`, `answer` is `NULL`; the `memory` count for `ABC` is `0` (the fact was deleted, not just superseded); the two most recent `clarification*` decisions are `clarification_answer_undone` then `clarification_answered` — the original record is still there, untouched, with a second record on top of it.

### 4. Skip keeps the inference and never re-raises

On the `scan.pdf` card (a discrete item — no free-text field, no Save button), click **Skip**.

**You should see:** the card's controls are replaced by **"Skipped."**, no Undo button offered for a skip. It leaves the list after about a second.

```bash
scripts/dev.sh psql -c "SELECT status, answer FROM clarifications WHERE subject = 'scan.pdf';"
scripts/dev.sh psql -c "SELECT count(*) FROM memory WHERE subject = 'scan.pdf';"
```

**You should see:** `status = 'skipped'`, `answer` is `NULL`, and no `memory` row was written — a skip is not an answer.

### 5. An empty answer is treated as a skip, and says so

On the `DEF` card (free text, no inference to prefill), leave the field empty and press **Enter** — do not type anything, including spaces.

**You should see:** the card shows **"No answer given — skipped."**, distinct wording from a deliberate Skip click, and then leaves the list the same way.

```bash
scripts/dev.sh psql -c "SELECT status FROM clarifications WHERE subject = 'DEF';"
```

**You should see:** `status = 'skipped'`.

### 6. Two saves in quick succession are both applied, in order

On the remaining `contracts` item and on `XYZ` (still pending after steps above), type an answer into each and click **Save** on both back-to-back, as fast as you can.

**You should see:** both cards independently show their own "Saved. Re-reading …" confirmation — neither answer is lost or overwrites the other.

```bash
scripts/dev.sh psql -c "SELECT kind, occurred_at FROM audit_decisions WHERE kind = 'clarification_answered' ORDER BY occurred_at;"
```

**You should see:** one `clarification_answered` row per save, in the order you clicked them.

### 7. Skip-all dismisses a group and is recorded

Switch to the **invoices** group (2 items, `GRN` and `PO`). Click **Skip all** next to its heading.

**You should see:** the button disables itself while the request is in flight, then the whole **invoices** group disappears from the page — not just its items fading, the group heading too.

```bash
scripts/dev.sh psql -c "SELECT status FROM clarifications WHERE source_id = '33333333-3333-3333-3333-333333333333';"
scripts/dev.sh psql -c "SELECT kind FROM audit_decisions WHERE kind = 'clarification_dismissed';"
```

**You should see:** both rows `status = 'dismissed'`; two separate `clarification_dismissed` decisions rows — one per item, so the dismissal rate is countable, not a single group-level record.

### 8. The queue returns to empty once everything is gone

By this point every seeded item has been answered, skipped or dismissed.

**You should see:** the Clarifications screen shows "Nothing to clarify…" again, and the rail badge is gone entirely (not `0` — absent).

---

## Known gaps

- **No transient "all answered" completion state.** `docs/ux/clarifications.md` §5 calls for a brief message naming what improved (*"5 answered. 2 tables and 14 documents re-read."*) before the screen settles back to the empty state. Reading `clarifications-screen.tsx`, the empty branch always renders `NONE_PENDING_COPY` — there is no code path that shows a one-time summary when the last pending item clears. Do not report this as a defect found during this walkthrough; it is a gap against the UX spec, tracked separately and out of this ticket's stated Acceptance Criteria (which do not mention it, only the Testing Notes' "Other scenarios" line does).
- **Undo after re-processing has actually started cannot be exercised.** `M3-APPLY-ING-080` (the re-processing consumer) has not landed, so re-processing is a no-op today — there is nothing running that undo could interrupt. The confirmation still names what *would* be re-read, honestly, per this ticket's own stated gap.
- **Re-processing itself does nothing observable.** "Re-reading N documents" is accurate about the count but no document actually gets re-read yet — that is `M3-APPLY-ING-080`'s scope, explicitly out of this ticket.
- **The reprocessing count for `column_distribution` evidence (the `students.st_cd` case) is always the source-wide document fallback**, since that evidence shape names no documents itself — confirmed as expected in step 1, not a defect.
