# Manual test — M3-CORRECT-FE-081, memory chips in an answer, with correct and delete

**Ticket:** `M3-CORRECT-FE-081` — memory chips in an answer, with correct and delete
**Version under test:** `0.3.18`
**Time:** about 25 minutes, plus a first stack build
**Who can run it:** anyone who can drag a file and read a screen. No terminal needed except one `psql` check at the end.

**What is being checked.** When an answer used a memory fact — something you told Askwell earlier, in a clarification — it renders as a clickable chip right next to the sentence that used it. Clicking the chip opens a popover with the fact, where it came from, and **Correct** and **Delete**. Correcting it supersedes the fact (never overwrites it) and queues re-processing of whatever depended on it, and the popover says what is being re-read before you close it.

**Why this ticket matters more than its size suggests.** The moment someone notices Askwell got something wrong is the only moment they will reliably fix it. If fixing it means leaving the answer to find a settings screen, most people never make the trip, and the wrong fact keeps poisoning every later answer. This interaction has to work right here, inline.

**The one thing to watch for throughout.** A correction must never edit the old fact in place — it must create a new row and mark the old one superseded. The `psql` check in step 9 is what confirms that actually happened, not just that the screen changed.

---

## Before you start

### 1. Make a file to test with

```
mkdir -p ~/askwell-test/memory-chip
cd ~/askwell-test/memory-chip
printf '%s\n' '%PDF-1.7' 'The st_cd column on the roster table records enrollment status.' > roster-notes.pdf
```

### 2. Point Askwell at the folder

In `.env`:

```
ASKWELL_ROOTS_MOUNT=/home/<you>/askwell-test
```

Then:

```
podman compose up -d
scripts/dev.sh db upgrade head
```

### 3. Open Askwell

`http://127.0.0.1:8000`.

---

## The walkthrough

### 4. Cold start: add the source

You land on **Ask your own material** with **Nothing added yet**. Click **Add a source**, drag in `roster-notes.pdf`, and answer the folder question with the path to `memory-chip`.

**Expect:** the card moves through its stages to **Queued**, then to indexed once processing finishes (check the library screen if you want to watch it happen). Return to Ask once the source shows as askable.

### 5. Ask a question that triggers a clarification, and answer it wrong on purpose

In the composer, type:

```
What does st_cd mean on the roster?
```

Press Enter. Because `st_cd` is not explained anywhere obvious in the file, expect an inline clarification to appear beneath your question, asking what `st_cd` means.

**Expect:** a small card with the subject `st_cd`, a question, and either an input box or a set of option buttons.

Answer it — deliberately with something **wrong**, to set up the correction later:

```
student code
```

Press Enter or click Save.

**Expect:** the clarification card disappears, and the turn continues to an answer.

### 6. Ask the question again and see the wrong chip

Once the first answer completes, ask the same question again:

```
What does st_cd mean on the roster?
```

**Expect:** the answer now states the meaning using what you just told it, and somewhere in the answer prose you see a small chip reading:

```
st_cd = student code
```

The chip sits directly after the sentence that used it, not off in a sidebar. It has a small marker dot before the text — filled if you supplied it, hollow if guessed.

### 7. Click the chip and read the popover

Click the chip.

**Expect:** a small popover opens beside the chip, showing:
- A label, **Memory fact** (not **Schema note**, since this came from a clarification about a plain fact, not a table/column).
- The subject and value: **st_cd — student code**.
- A line stating **You told me**, a date, and **used in 1 answer**.
- Two buttons: **Correct** and **Delete**.

Click elsewhere on the page (outside the popover) — **expect** it closes. Click the chip again to reopen it before continuing.

### 8. Correct the fact

Click **Correct**.

**Expect:** the fact/value area becomes an editable text box pre-filled with `student code`, with **Save** and **Cancel** buttons beneath it.

Clear the box and type:

```
student status code
```

Click **Save**.

**Expect:** the box closes back to display mode, and a confirmation line appears naming what is being re-read — something like **Re-reading 1 document.** (or **Re-checking 1 item.** / **Nothing to re-process.**, depending on what actually depended on this fact — record exactly which line you saw). The displayed value updates to **student status code**.

### 9. Confirm the correction superseded rather than overwrote

```
scripts/dev.sh psql
```

```sql
SELECT id, subject, fact, origin, superseded_by FROM memory WHERE subject = 'st_cd' ORDER BY created_at;
```

**Expect:** **two** rows for `st_cd` — the original (`fact = 'student code'`, `superseded_by` pointing at the new row's id) and the new one (`fact = 'student status code'`, `origin = 'correction'`, `superseded_by IS NULL`). If there is only one row, or the original's `fact` column itself changed, that is the defect this ticket exists to prevent — corrections must never overwrite.

Also check the decision was logged:

```sql
SELECT event_type, payload FROM decisions ORDER BY recorded_at DESC LIMIT 1;
```

**Expect:** a row for the supersession, naming the old and new fact ids and the subject.

### 10. Ask the question a third time and confirm the answer actually changed

Back in the browser, ask once more:

```
What does st_cd mean on the roster?
```

**Expect:** the new answer uses **student status code**, not the original wrong meaning, and the chip beside it now reads `st_cd = student status code`.

### 11. Delete the fact from a chip

Click the new chip, then click **Delete** in the popover.

**Expect:** no confirmation dialog interrupts you (this ticket's delete is immediate) — the popover shows a line such as **Deleted. Nothing to re-process.** (or a re-reading count, if something still depended on it), and the fact/value display area disappears since there is nothing active left to show.

### 12. Confirm the fact stopped applying

Ask the question a fourth time:

```
What does st_cd mean on the roster?
```

**Expect:** the answer no longer states a meaning sourced from that fact — either it abstains on that specific point, or it answers from the document alone without a memory chip attached. It must not still say "student status code" as if the fact were live.

---

## Edge cases named in the ticket

### 13. A fact used in several answers

Repeat step 6's question (or a differently-worded one that still cites the same fact) two more times before correcting anything, so the same fact is used in three separate answers, producing three separate chips (one per claim, per the ticket's own "same fact cited twice produces two chips" rule — this is expected, not a bug).

Open any one of the three chips.

**Expect:** the popover's usage line reads **used in 3 answers** — one shared count across all chips pointing at the same fact, not per-chip. Correct the fact from this chip.

**Expect:** the confirmation still only names what actually depends on it now (documents/items to re-read), not "3 answers" — re-processing targets dependencies, not the historical answer count.

### 14. A chip whose fact was superseded by something else in the meantime

With a fact still showing in an old, already-rendered answer on screen (don't refresh — scroll back up to an earlier turn in this conversation that still shows an old chip for `st_cd`, before you deleted it), click that older chip.

**Expect:** the popover shows the **current** value (the corrected or deleted state, not the value it had when that old answer was composed), plus a note reading **This answer used an earlier version. Shown above is the current one.**

### 15. A schema-note chip

If your corpus includes a live database connection with a table Askwell has written a schema note about (out of scope to set up fresh here if you don't already have one — skip this step if you don't), ask a question that surfaces a schema-note chip and click it.

**Expect:** the same popover shape, but labelled **Schema note** instead of **Memory fact**, and the subject reads as `table.column` rather than a bare word.

---

## Known gaps

- No history view from the popover — seeing every past version of a fact is the memory screen's job (`M3-MEM-FE-083`), not this one.
- No way to add a brand-new fact from a chip — chips only ever act on a fact that already exists and was already used in this answer.
- The local corrections-from-chip counter (this ticket's Analytics Events line) is in-memory only and never transmitted (C1) — there is nothing to inspect for it beyond watching the interaction work; it does not persist across a reload.
