# Manual test — M3-MEM-FE-084, memory interactions: edit, confirm, delete, history, filter, manual add

**Ticket:** `M3-MEM-FE-084` — the six interactions `docs/ux/memory.md` §4 names on the memory screen: **Edit** (supersedes and re-processes), **Confirm** (promotes an inferred row without re-processing), **Delete** (stops the fact applying, recorded), **History** (every prior value with dates), **Filter** (inferred-only, by source, unused), and **Add a fact** (manual entry). Also closes issue #288 (a deleted correction no longer resurrects the value it superseded).
**Version under test:** `0.3.20`
**Time:** about 90–110 minutes, plus a first stack build and native inference startup.
**Who can run it:** a browser and a terminal. No `psql` needed — everything in this document is driven by clicking through the app.

**What is being checked.** `web/components/memory/memory-screen.tsx`'s row controls (Edit, Confirm, Delete, the struck-through history block), the filter bar, "Add a fact", and "Delete all memory" — calling `askwell.memory`'s `correct_fact`/`confirm_fact`/`delete_fact`/`add_manual_fact`/`delete_all_memory` via `web/lib/memory.ts` and `web/lib/memory-chips.ts`. The list and its markers were already checked in `M3-MEM-FE-083`; this document only exercises what a click on a row now does.

**Where this stops on purpose.** No bulk confirm exists (out of scope — "it risks rubber-stamping"). No export or import across machines.

---

## Before you start

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

Find `POSTGRES_APP_PASSWORD` and put any word after the `=` if it is blank. Find `ASKWELL_EMBEDDING_MODEL_PATH` and confirm it points at a model that actually exists on this machine.

---

## Cold start

### 1. Remove any previous state

```
podman compose down -v
```

**You should see:** lines about containers and volumes being removed, or a note there was nothing to remove.

### 2. Run the checks

```
scripts/dev.sh check
```

**You should see:** lint, format, typecheck and test stages finish without red error text.

```
scripts/dev.sh web-check
```

**You should see:** lint, typecheck, the test suite (including `memory.test.ts`), build, contrast and offline checks all finish without red error text.

### 3. Bring the stack up

```
podman compose up -d
```

**You should see:** `postgres`, `redis`, `egress-proxy`, `api`, `worker` reported as started. Wait about thirty seconds.

### 4. Create the database tables

```
scripts/dev.sh db upgrade head
```

**You should see:** migration lines finish with no error.

### 5. Start native inference, on the host

```
scripts/dev.sh inference
```

Leave this running in its own terminal for the rest of this document. Wait for it to report the embedding role `ready` on its configured port.

### 6. Open the app

Open a browser at:

```
http://127.0.0.1:8000
```

**You should see:** the Askwell shell load with no sign-in prompt. The left rail shows **Ask**, **Library**, **Clarifications**, **Memory**, **Settings**.

### 7. Nominate the test folder

Click **Settings** in the left rail, scroll to **Folders Askwell may read**, type your own path into the **Nominate a folder** field —

```
/home/you/external/quantum-plus/askwell/askwell-test-material
```

— and click **Nominate**.

**You should see:** a box appear showing that path, marked **Readable**.

---

## Part A — manual entry before anything else exists

### 8. Add a fact from an empty memory screen

Click **Memory** in the left rail.

**You should see:** the empty state from `M3-MEM-FE-083` — no rows — and, below where the list would be, a small link/button reading **Add a fact**.

Click **Add a fact**.

**You should see:** a form appear in place, with a **Subject** field (placeholder `Subject, e.g. RFQ`), a **What it means** text area, an **Add** button and a **Cancel** button. The **Add** button is disabled while either field is empty.

### 9. Submit a manual fact

Type into **Subject**:

```
RFQ
```

Type into **What it means**:

```
Request for Quotation
```

Click **Add**.

**You should see:** the form close, and the list now shows one card:

- A **filled** marker next to subject `RFQ`.
- The value `Request for Quotation`.
- A line reading `You told me · <today's date> · used in 0 answers` — not ochre-toned (manual entry is user-supplied, same tier as answering a clarification).
- No source name shown (a manual fact carries no source).

There is no "guesses to review" line — nothing here is inferred.

### 10. Ask a question that uses the manual fact

Click **Ask** in the left rail and ask:

> What does RFQ mean?

**You should see:** an answer that uses the term, with a citation chip. Open the chip's popover and confirm it shows `Request for Quotation`.

### 11. Confirm the usage count moved

Click **Memory** in the left rail.

**You should see:** the `RFQ` card now reads `used in 1 answer`.

---

## Part B — editing supersedes, and history shows both values

### 12. Edit the RFQ fact

On the `RFQ` card, click **Edit**.

**You should see:** the value text replaced by a text area pre-filled with `Request for Quotation`, a **Save** button (disabled while the text area is empty) and a **Cancel** button.

### 13. Change the value and save

Clear the text area and type:

```
Request for Quotation — a formal ask for supplier pricing on specified goods or services
```

Click **Save**.

**You should see:** the edit form close, a line appear beneath the card reading something like `Re-checking 1 item.` or `Re-reading N document(s).` (the re-processing confirmation naming what was just queued — exact wording depends on what depends on `RFQ`; for a fact with nothing depending on it yet it may read `Nothing to re-process.`), and the card's main text update to the new value.

### 14. Confirm history now shows both values

Still on the `RFQ` card, confirm a struck-through block now appears beneath the metadata line, showing:

```
Request for Quotation · <today's date>
```

with a line-through style, visually distinct from the live (non-struck) value above it.

**You should see:** the old value is fully legible — not truncated, not replaced by a placeholder like "1 earlier version" — and the new value is what you typed at step 13.

### 15. Edit again and confirm two entries in order

Click **Edit** again, change the value once more to:

```
RFQ — Request for Quotation, the formal document soliciting supplier pricing
```

and **Save**.

**You should see:** the history block now shows **two** struck-through entries, most recent superseded value first (or in the server's chosen order — confirm it is consistent, not reshuffled), each with its own date:

```
Request for Quotation — a formal ask for supplier pricing on specified goods or services · <date>
Request for Quotation · <date>
```

---

## Part C — an inferred fact: Confirm without re-processing, then edit after confirming

### 16. Write a file that raises exactly one clarification

```bash
scripts/dev.sh run python3 - <<'PY'
import os
os.makedirs("/app/askwell-test-material/contracts", exist_ok=True)
with open("/app/askwell-test-material/contracts/agreement.txt", "w") as f:
    f.write("The SLA applies to all vendors. The SLA renews annually. The SLA covers uptime.\n")
print("done")
PY
```

**You should see:** the script print `done`.

### 17. Add the folder as a source

Click **Ask** in the left rail, click **Add a source**, point it at `.../askwell-test-material/contracts`, and click **Add it**. Wait for it to settle (no red error text; the card stops showing progress).

### 18. Open Memory and confirm the inferred fact appears with a Confirm button

Click **Memory** in the left rail.

**You should see:** a `1 guess to review` line, and a new card for subject `SLA` with a **hollow** marker, the `contracts` source name, and three buttons: **Confirm**, **Edit**, **Delete** — Confirm shown only because this row is inferred (compare the `RFQ` card, which shows only Edit and Delete).

### 19. Click Confirm and watch the marker flip with no re-processing message

Click **Confirm** on the `SLA` card.

**You should see:** the card update in place —

- The marker changes from **hollow** to **filled**.
- The metadata line changes from `I guessed · …` to `You told me · …`.
- A small note appears reading `Confirmed.` — **not** a re-processing message like "Re-checking N items." (the content did not change, so nothing was queued).
- The `1 guess to review` line disappears from the page header (nothing left to review).
- The value text is unchanged — whatever Askwell had originally guessed for `SLA`.
- The **Confirm** button is gone from this card now (it is no longer inferred); **Edit** and **Delete** remain.

### 20. Click Confirm again on an already-user fact (idempotency)

This card no longer shows a Confirm button, so instead re-open the same request through the API path the UI itself would hit on a race: click **Edit** then **Cancel** (no change) to confirm the card is otherwise stable, then move on — a second confirm attempt is exercised structurally in `api/tests/test_memory.py`, not reachable twice from this UI once the button disappears. Note this as expected, not a gap.

### 21. Edit the now-confirmed fact and check the order in history

Click **Edit** on the `SLA` card, change the value to:

```
Service-Level Agreement: the contracted uptime and response-time terms with a vendor
```

and **Save**.

**You should see:** a re-processing note this time (the corrected value now has a dependent — the earlier confirm did not create one, but the edit's own dependency resolution may, depending on what has been asked so far; if it reads `Nothing to re-process.` that is consistent since nothing has queried `SLA` yet). The card's value updates, and the history block shows exactly **one** struck-through entry — the pre-edit (post-confirm) value, with its own date. This is the ticket's own edge case: *confirming a fact then editing it — two records, correct order* — confirm the live row is the edited text and the single history entry is what Confirm had left in place, not an intermediate state that got lost.

---

## Part D — deleting a fact used in past answers keeps the usage row

### 22. Use the SLA fact in an answer

Click **Ask** and ask:

> What does SLA mean in the agreement?

**You should see:** an answer citing the `SLA` fact via a chip.

### 23. Confirm the usage count, then delete the fact

Click **Memory**. Confirm the `SLA` card now reads `used in 1 answer`.

Click **Delete** on the `SLA` card.

**You should see:** the card disappear from the list immediately, and no error text. `1 guess to review` (if present) is unaffected — `SLA` was not inferred at the point of deletion.

### 24. Confirm the fact no longer applies to a new question

Click **Ask** and ask the same question again:

> What does SLA mean in the agreement?

**You should see:** the answer either abstains on `SLA` specifically or answers without a chip for it — confirm no chip citing the deleted `SLA` fact appears in this new answer. (If retrieval still surfaces the underlying document text some general answer may still come back; the check here is the absence of the fact-citation chip, not the absence of the word "SLA" from prose.)

### 25. Confirm the earlier answer's chip still works (history not rewritten)

Return to the answer from step 22 (scroll up in the same conversation, or however the app exposes prior turns in this session). Open the `SLA` chip from that earlier answer.

**You should see:** the popover still opens and still shows the fact's value at the time it was cited — it does not error, and it does not silently vanish — confirming the ticket's edge case: *deleting a fact used in past answers — those answers keep their fact usage rows so history is not rewritten.*

---

## Part E — the three filters

### 26. Filter to inferred-only

Write a second file to get a second inferred fact:

```bash
scripts/dev.sh run python3 - <<'PY'
with open("/app/askwell-test-material/contracts/second.txt", "w") as f:
    f.write("The MOU sets out preliminary terms before the main contract.\n")
print("done")
PY
```

Wait for it to be picked up (re-open **Ask** and confirm the source shows no pending progress), then click **Memory**.

**You should see:** the list now contains `RFQ` (user-supplied), `SLA` (user-supplied, via confirm), and `MOU` (inferred) — three rows. A `1 guess to review` line is back.

At the top of the list, confirm a filter bar with two checkboxes — **Inferred only**, **Unused** — and a **Source** dropdown.

Check **Inferred only**.

**You should see:** the list narrow to just the `MOU` card. A count reading `1 of 3` appears next to the filters. Uncheck it and confirm all three rows return.

### 27. Filter by source

Check the **Source** dropdown.

**You should see:** it lists the `contracts` source (the only one with rows attached — `RFQ`, being manual, has no source and so does not gate the dropdown's presence, but also will not appear when a specific source is selected).

Select `contracts`.

**You should see:** the list narrow to `SLA` and `MOU` (both from that source) — `RFQ` drops out, since it has no source. Confirm the count reads `2 of 3`. Reset the dropdown to **All** and confirm all three return.

### 28. Filter to unused

Check **Unused**.

**You should see:** the list narrow to rows with `used in 0 answers` — `RFQ` was used once and `SLA` was used once (step 22) and deleted-and-reasked did not add a new usage to a since-deleted row, so at this point only `MOU` (never queried) should remain, showing `1 of 3`. Uncheck it afterward.

### 29. Combine two filters

Check both **Inferred only** and select the `contracts` source together.

**You should see:** the list still shows only `MOU` (the only row satisfying both), and the count still reads correctly against the total. Clear both filters before continuing.

---

## Part F — manual entry on a duplicate subject is offered as a correction

### 30. Try to add a fact for a subject that already exists

Click **Add a fact**. Type subject:

```
RFQ
```

and any text in the meaning field, e.g.:

```
Some other definition
```

Click **Add**.

**You should see:** the form does **not** close. Instead, a message appears in place of the Add/Cancel buttons:

> Askwell already knows RFQ: RFQ — Request for Quotation, the formal document soliciting supplier pricing. Correct it instead?

with two buttons: **Correct it** and **Never mind**.

### 31. Correct it

Click **Correct it**.

**You should see:** the form close, and the `RFQ` card's value update to `Some other definition`, with a new struck-through history entry added for the value it replaced. Confirm no second `RFQ` row was created — the list still has exactly one card per subject.

### 32. Never mind

Repeat step 30 (subject `RFQ` again), but this time click **Never mind**.

**You should see:** the duplicate warning close and the form return to its normal Subject/What it means state (not fully dismissed — you can still edit and resubmit, or click **Cancel** to close it outright). Click **Cancel** to close it.

---

## Part G — delete-all-memory, with the named-count confirmation

### 33. Open delete-all

Click **Memory** and note the current row count (should be 3: `RFQ`, `SLA`, `MOU`). Scroll to the bottom of the list.

**You should see:** a link/button reading **Delete all memory**, in an alarm colour.

Click it.

**You should see:** a confirmation block appear reading exactly (count matching what you saw):

> Delete all 3 facts Askwell has learned? This cannot be undone.

with an alarm-coloured **Delete all 3** button and a **Cancel** button. (Confirm the wording names the count and states it cannot be undone — this ticket's own Validation Rule.)

### 34. Cancel first, to confirm nothing happens

Click **Cancel**.

**You should see:** the confirmation close, and all three rows still present, unchanged.

### 35. Confirm for real

Click **Delete all memory** again, then click **Delete all 3**.

**You should see:** the confirmation close, and the list return to the empty state from `M3-MEM-FE-083` — no rows, the "Nothing here yet…" copy, the **Add a fact** control still present (it is not part of the list).

---

## Cleanup

```
podman compose down -v
```

Restore `.env` if you changed anything beyond what **Before you start** asked for.

---

## Known gaps

- **No bulk confirm.** Named out of scope in the ticket itself — "it risks rubber-stamping" — each inferred fact is confirmed individually, one click per row. Not tested here as a defect.
- **No export or import across machines.** Named out of scope — not v1.
- **Step 20's idempotent re-confirm is not exercised through the UI.** Once a fact is confirmed, its Confirm button disappears, so a second click cannot be driven by clicking; `already_confirmed` is covered instead by `api/tests/test_memory.py`. This is a UI reachability limit, not a defect — there is no legitimate path for a user to click Confirm twice on the same row without a race the UI cannot simulate.
- **Reprocessing label wording (`Re-checking N items.` vs. `Re-reading N document(s).` vs. `Nothing to re-process.`) is data-dependent** — which one appears at steps 13, 19 and 21 depends on what already depends on that subject in this run. This document describes the possibilities rather than a single fixed string; do not report a variance among these three as a defect on its own — only report it if the label contradicts what was actually queued (e.g. it claims "Nothing to re-process" while an answer visibly changes).
- **No visual grouping by subject beyond one row per subject, and no icon distinguishing structural from general facts** — carried over from `M3-MEM-FE-083`'s own known gap; unchanged by this ticket.
- **Structural fact (`schema_notes`) editing is exercised by `api/tests/test_memory.py` but not by this document** — creating a structural fact still requires `psql` seeding (no CSV/dump/live-connection UI yet, per `M3-MEM-FE-083`), and this document only re-uses that seam where the general-fact path already covers the same interactions (edit, confirm, delete, history). If a structural-fact-specific UI regression is suspected, seed one via `scripts/dev.sh psql` as `M3-MEM-FE-083` Part D does, then repeat Parts B and C against it.
