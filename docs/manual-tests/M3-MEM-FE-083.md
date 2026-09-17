# Manual test — M3-MEM-FE-083, the memory screen: list, confidence markers, usage count

**Ticket:** `M3-MEM-FE-083` — `/memory` renders one list of everything Askwell believes: both fact kinds (general `memory` and structural `schema_notes`), each row carrying a confidence marker (filled for user-supplied, hollow for inferred), a source, and a live usage count. Inferred facts sort first by default. A fact from a deleted source says so. Facts are never auto-deleted, never hidden. Interactions — Edit, Confirm, Delete, Filter, Add a fact — are `M3-MEM-FE-084`'s scope, out of scope here.
**Version under test:** `0.3.19`
**Time:** about 75–90 minutes, plus a first stack build and native inference startup.
**Who can run it:** a browser, a terminal, and `psql` access via `scripts/dev.sh psql` — used for setup in Part D only, because structural facts (`schema_notes`) come from CSV, dump or live-connection ingestion, and `web/lib/add-source.ts` says plainly that "CSV, database dumps and live connections arrive in M4" — there is no UI path to create one yet. Everything else in this document is driven by clicking through the app.

**What is being checked.** `web/app/memory/page.tsx` renders `MemoryScreen` (`web/components/memory/memory-screen.tsx`), which calls `GET /memory` (`askwell.memory.get_memory_screen`) and renders one card per row: the confidence marker, subject, value, origin sentence ("You told me" / "I guessed"), date, "used in N answers", a note if the row's source was deleted, and a struck-through history block if the fact has been superseded. Rows arrive already sorted inferred-first, newest-within-tier, from the server — the screen does not re-sort.

**Where this stops on purpose.** No **Edit**, **Confirm**, **Delete**, **Filter** or **Add a fact** control exists on this screen yet (`M3-MEM-FE-084`). This walkthrough confirms only what renders and in what order — not what a click on a row does, because nothing on this screen reacts to one.

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

## Part A — nothing believed yet: the teaching empty state

### 8. Click Memory before anything has been added

Click **Memory** in the left rail.

**You should see:** the address bar end in `/memory/`, a heading **Memory**, a one-line subtitle ("What Askwell believes about your material, and where each belief came from"), and — because there is nothing to review — no "guesses to review" line beneath it. Below that, a single block of text reading:

> Nothing here yet. Memory fills as Askwell asks about your material and you answer — every fact it holds will say whether you told it or it guessed.

with a link reading **Start in the clarification queue**.

Confirm there is no modal, no stuck spinner, and the rest of the app is fully usable while this is on screen.

### 9. Follow the empty-state link

Click **Start in the clarification queue**.

**You should see:** the address bar end in `/clarifications/`, landing on the clarifications screen's own empty state — confirming the memory screen's teaching copy actually goes somewhere, not a dead link.

---

## Part B — one inferred fact, one confirmed: the marker and the sort

### 10. Write a file that raises exactly one clarification

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

### 11. Add the folder as a source, by clicking through the app

Click **Ask** in the left rail, click **Add a source**, point it at `.../askwell-test-material/contracts`, and click **Add it**. Wait for it to settle (no red error text; the card stops showing progress).

### 12. Open Memory and confirm the inferred fact renders

Click **Memory** in the left rail.

**You should see:** beneath the heading, a line reading `1 guess to review`. Below it, one card:

- A **hollow** square marker (unfilled — border only, no fill) to the left of the subject `SLA`.
- The source name for the `contracts` folder, on the right of the same line.
- The guessed meaning as free text (whatever Askwell inferred for `SLA` — an abbreviation guess, not left blank).
- A line reading `I guessed · <a date> · used in 0 answers`, in the same ochre-ish tone the marker's hollow state uses (`--inferred`), not the default text colour.

Confirm the "used in 0 answers" fact is shown plainly, not hidden or flagged as a problem — `docs/ux/memory.md` §5's "unused fact" state: it may be waiting for the right question.

### 13. Answer the clarification

Click **Clarifications** in the left rail. Find the `SLA` item, answer it (e.g. "Service Level Agreement — the contracted uptime terms"), and save.

**You should see:** the standard save confirmation for that screen, and the item leave the pending list.

### 14. Return to Memory and confirm the marker flips

Click **Memory** in the left rail.

**You should see:** the "guesses to review" line is gone (nothing left to review). The `SLA` card now shows:

- A **filled** marker (solid fill, not hollow) to the left of `SLA`.
- The line reading `You told me · <today's date> · used in 0 answers` — no longer ochre-toned.
- The value updated to whatever you typed at step 13.

This confirms the confidence marker and the "You told me"/"I guessed" sentence both track `origin`, and that answering a clarification is what moves a fact from one to the other — not a separate action on this screen.

---

## Part C — the usage count moves, and a correction leaves history

### 15. Ask a question that uses the fact

Click **Ask** in the left rail and ask:

> What does SLA mean in the agreement?

**You should see:** a normal answer stream back, with at least one citation chip. Hover or click the chip referencing the `SLA` memory fact and confirm its popover shows the value you saved in step 13.

### 16. Confirm the usage count incremented

Click **Memory** in the left rail.

**You should see:** the `SLA` card now reads `used in 1 answer` (singular, not "1 answers" — confirm the wording itself, not just the number).

### 17. Correct the fact from the chip, and confirm history appears here

Click **Ask**, and re-open the same answer from step 15 (or ask the same question again to get a fresh chip). Open the `SLA` chip's popover and click **Correct**. Enter a different value, e.g. "Service-Level Agreement: the uptime and response-time terms in a vendor contract", and save.

**You should see:** the chip's popover close with no error.

Click **Memory** in the left rail.

**You should see:** the `SLA` card now shows the corrected value as its main text, still with a **filled** marker (a correction is user-supplied, same as answering). Beneath the metadata line, a struck-through block appears showing the previous value — the one from step 13 — with its own date, visually distinct (line-through) from the live value above it. Confirm the old value is still legible (not just an ellipsis or a generic "1 earlier version" placeholder) and that nothing was silently discarded.

---

## Part D — a structural fact, and what happens when its source is deleted

**Why `psql` here.** `docs/ux/memory.md` §2 requires structural facts (`schema_notes`) to render alongside general ones, but the ingestion paths that produce them — CSV, database dump, live connection — are not wired into the UI yet (`web/lib/add-source.ts` states this directly: "CSV, database dumps and live connections arrive in M4"). This part seeds one directly so the *rendering* can be checked now, rather than skipping it and reporting a gap that is really just sequencing.

### 18. Find the `contracts` source's id

```
scripts/dev.sh psql
```

```sql
SELECT id, name FROM sources WHERE name ILIKE '%contracts%';
```

**You should see:** one row. Copy its `id`.

### 19. Insert one inferred structural fact against that source

Still in `psql`, using the id from step 18:

```sql
INSERT INTO schema_notes (source_id, table_name, column_name, description, origin, confidence)
VALUES ('<the id from step 18>', 'invoices', 'st_cd', 'invoice status code: O=open, P=paid, W=written off', 'inferred', 0.4);
```

**You should see:** `INSERT 0 1`. Exit `psql` (`\q`).

### 20. Confirm it renders on Memory, sorted with the other inferred facts

Click **Memory** in the left rail.

**You should see:** a `1 guess to review` line reappear (the `st_cd` note is inferred and unreviewed). Its card sits above the (now confirmed, filled-marker) `SLA` card — inferred-first sort holds across both fact kinds, not just within one. The card shows:

- A **hollow** marker next to subject `invoices.st_cd` (structural facts identify themselves by a table-qualified subject; there is no separate icon or label distinguishing "structural" from "general" beyond that).
- The `contracts` source name.
- The description text from step 19.
- `I guessed · <date> · used in 0 answers`.

### 21. Delete the source and confirm the structural fact disappears with it

Click **Library** in the left rail, find `contracts`, and delete it. Confirm the deletion when prompted.

**You should see:** the source leave the library list.

Click **Memory** in the left rail.

**You should see:** the `invoices.st_cd` card is **gone** — `docs/ux/memory.md` §5: a structural fact goes with its source. The `SLA` card is **still present**, now showing a line reading `learned from a source you deleted` beneath its usage line — a general fact survives its source's deletion and says so.

### 22. Confirm the survived fact is still otherwise normal

On the same `SLA` card, confirm the filled marker, the corrected value from step 17, its struck-through history, and its usage count are all unchanged by the deletion — the deleted-source note is additional information, not a replacement for the rest of the row.

---

## Cleanup

```
podman compose down -v
```

Restore `.env` if you changed anything beyond what **Before you start** asked for.

---

## Known gaps

- **No interaction works on this screen.** No **Edit**, **Confirm**, **Delete**, **Filter**, or **Add a fact** control exists — all of `M3-MEM-FE-084`'s scope. Do not report a missing button here as a defect of this ticket.
- **Structural facts cannot be created through the app yet.** `web/lib/add-source.ts` names CSV, database dumps and live connections as "M4" — the only ingestion paths that produce `schema_notes`. Part D seeds one with `psql` to test rendering only; this is not a substitute for testing the real ingestion-to-clarification-to-memory path for structural facts, which cannot happen until that ingestion work lands.
- **No explicit visual grouping by subject, and no badge distinguishing structural from general facts.** `docs/ux/memory.md` §2 describes "one list grouped by subject" with the two kinds "visually distinct but together"; the implementation instead returns one row per subject already (with its own history nested in, per a comment in `askwell/memory.py`), and the only cue that a row is structural is its table-qualified subject text (`invoices.st_cd` vs. `SLA`) — there is no colour, icon or section header. This may be the intended reading of "grouped by subject" rather than a gap; flagged here so it is not mistaken for an oversight if a reviewer expected literal group headers.
- **Filtering (inferred only / by source / unused) is not built.** Named in `docs/ux/memory.md` §4 as an interaction, so out of scope here regardless.
- **Hundreds-of-facts navigability is not exercised.** The acceptance criteria's "list stays navigable with grouping and filtering" at scale depends on filtering, which does not exist yet; this document does not attempt to seed hundreds of rows because there is no way to make the list "stay navigable" differently than it already renders (a plain scrolling list) until filtering ships.
- **Manual entry ("Add a fact") is not exercised**, by design — it is `M3-MEM-FE-084`'s own scope, named explicitly in `docs/ux/memory.md` §4.
