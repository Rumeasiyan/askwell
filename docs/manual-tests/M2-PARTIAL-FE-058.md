# Manual test — M2-PARTIAL-FE-058, partial rendering and the conflicting-sources presentation

**Ticket:** `M2-PARTIAL-FE-058` — render the partial state so the grounded and ungrounded parts are visually distinguishable, and render the conflicting-sources state with both positions, both citations and their dates, plus a resolve offer that (until memory exists in M3) records the choice as a pending resolution and says so.
**Version under test:** `0.2.51`
**Time:** about 50 minutes, plus a first stack build. Builds directly on `M2-PARTIAL-BE-057`'s and `M2-PARTIAL-BE-059`'s corpus fixtures — this ticket is the rendering those two manual tests said was missing.
**Who can run it:** a terminal and a browser, plus native inference running on the host.

**What is being checked.** `web/lib/answer-annotations.ts` reads the fixed `Not covered:` / `Conflicting sources on …:` / `Resolved by memory:` lines back out of the streamed answer text — the same convention `askwell.agent.partial` and `askwell.agent.conflict` compose server-side — and hands `web/components/ask/ask-screen.tsx`'s `AnsweredContent` a `cleanedText` with those lines lifted out. A partial answer shows the lifted lines as an `UncoveredBlock` with a distinct left rule; a conflict answer shows a `ConflictBanner` heading, sorts its citation cards by document date with `web/lib/document-dates.ts`'s `sortByDateAndSupersession`, and shows a `ResolveOffer` beneath the two positions. `ProvenanceMargin`/`InlineSourceCards` (`web/components/ask/provenance-margin.tsx`) pass `showDate` only for a conflict turn, so an ordinary answer's cards carry no date.

**Where this stops on purpose.** No conflict detection lives here — `M2-PARTIAL-BE-059` already produces the `Conflicting sources on …:` line; this ticket only renders it. No memory write — the resolve offer's choice is client state only, never sent anywhere, and says so on screen (M3 wires the real write).

---

## Before you start

- `.env.example` names `ASKWELL_EMBEDDING_MODEL_PATH=~/.local/share/askwell/models/bge-m3-FP16.gguf` and `ASKWELL_RETRIEVAL_SCORE_THRESHOLD=0.65`. You need both the embedding and generation models on this machine — every part below needs a real generated answer.

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

Find `POSTGRES_APP_PASSWORD` and put any word after the `=` if it is blank.

---

## Cold start

### 1. Remove any previous state

```
podman compose down -v
```

**You should see:** lines about containers and volumes being removed, or a note there was nothing to remove.

### 2. Build the interface

```
scripts/dev.sh web-build
```

**You should see:** a Next.js build finishing with a route list and no red error text.

### 3. Run the checks

```
scripts/dev.sh check
```

**You should see:** lint, format, typecheck and test stages finish without red error text, including `web/lib/answer-annotations.test.ts` and `web/lib/document-dates.test.ts`.

### 4. Bring the stack up

```
podman compose up -d
```

**You should see:** `postgres`, `redis`, `egress-proxy`, `api`, `worker` reported as started. Wait about thirty seconds.

### 5. Create the database tables

```
scripts/dev.sh db upgrade head
```

**You should see:** migration lines finish with no error.

### 6. Start native inference, on the host

```
scripts/dev.sh inference
```

Leave this running in its own terminal for the rest of this document. Wait for it to report both the embedding and generation roles `ready` on their configured ports.

### 7. Nominate the folder your material is in

Open a browser at:

```
http://127.0.0.1:8000
```

Click **Settings** in the left strip, scroll to **Folders Askwell may read**, type your own path into the **Nominate a folder** field —

```
/home/you/external/quantum-plus/askwell/askwell-test-material
```

— and click **Nominate**.

**You should see:** a box appear showing that path, marked **Readable**.

---

## Part A — the partial state: grounded and ungrounded parts visually distinct

### 8. Write a file that covers one of two things a compound question asks about

```bash
scripts/dev.sh run python3 - <<'PY'
with open("/app/askwell-test-material/supplier-agreement.txt", "w") as f:
    f.write(
        "Section 6.1 Payment. Invoices are payable within forty-five days "
        "of receipt. Late payments accrue interest at 1.5% per month.\n"
    )
print("done")
PY
```

**You should see:** the script print `done`.

### 9. Get to the add screen by clicking

Click **Ask** in the left strip.

**You should see:** the "Ask your own material" page's first-run, empty-corpus state — no chat box, a statement that no documents are indexed yet, and an **Add a source** button.

Click **Add a source**.

**You should see:** the "Add a source" page, address bar ending in `/sources/add/`.

### 10. Add the file

Open your file manager at `~/external/quantum-plus/askwell/askwell-test-material`. Drag `supplier-agreement.txt` onto the window and release, type the folder with your own path when asked, and click **Add it**.

**You should see:** a card move to **Queued**, then progress as extraction, chunking and embedding run for real, and settle with no red error text.

### 11. Click **Ask** and ask a compound question, half covered

Type into the composer:

```
What are the payment terms, and what is the termination notice period for this supplier?
```

Press Enter (or click send).

**You should see:** named progress ("Searching your files." then "Reading 1 source."), then an answer streaming in that states the payment term (forty-five days) as ordinary prose with a citation card to `supplier-agreement.txt`. Below that prose, a **visually separate block** appears: a heading reading "Not covered by your files", set off by a left-edge rule distinct from the answer text above it, holding one line naming the termination notice period. The `Not covered:` prefix itself does not appear on screen — it has been lifted out and replaced by the heading.

### 12. Confirm the block is not just plain prose

Look closely at the block from step 11: its text is a visibly muted colour compared with the answer prose above it, and it sits behind a rule on its left edge (the same device the source cards use for "this is apparatus, not something the model asserted"). This is the ticket's core acceptance criterion — a screenshot of just this block, with no surrounding context, should still be readable as "the tool is telling you something is missing," not as more of the answer.

---

## Part B — the conflicting-sources state: both positions, both dates, never a silent preference

### 13. Write two files that disagree on the same figure, with different ages

```bash
scripts/dev.sh run python3 - <<'PY'
with open("/app/askwell-test-material/protocol-2019.txt", "w") as f:
    f.write(
        "Field Sampling Protocol (2019 revision). Section 4.2 Notice. "
        "Field staff must give ninety days notice before decommissioning a sensor.\n"
    )
print("done")
PY
```

**You should see:** the script print `done`.

Add it the same way as step 10 (drag onto the **Add a source** page, confirm the folder, click **Add it**), and wait for it to settle.

Wait at least one full minute — the two documents' `Added` dates must differ visibly on screen later — then write and add the second:

```bash
scripts/dev.sh run python3 - <<'PY'
with open("/app/askwell-test-material/protocol-2023.txt", "w") as f:
    f.write(
        "Field Sampling Protocol (2023 revision). Section 4.2 Notice. "
        "Field staff must give sixty days notice before decommissioning a sensor.\n"
    )
print("done")
PY
```

Add it the same way, and wait for it to settle.

### 14. Confirm both reached ready

```
scripts/dev.sh psql
```

```sql
SELECT filename, status FROM documents ORDER BY filename;
```

**You should see:** `protocol-2019.txt` and `protocol-2023.txt`, both `status` = `ready`. Keep this session open for later parts.

### 15. Ask the question both documents answer

Click **Ask**, start a new conversation, and ask:

```
How much notice must field staff give before decommissioning a sensor?
```

**You should see:** named progress, then an answer streaming in with two citation cards. Above the two positions, a heading reads "Conflicting sources on the notice period" (or a close paraphrase of the topic — the fixed part is the "Conflicting sources on" prefix). It renders in ink, not as a red or alarmed colour — a real conflict is a normal product state here, not an error. Below the heading, two cited sentences appear: one stating ninety days citing `protocol-2019.txt`, one stating sixty days citing `protocol-2023.txt`. Neither is presented as more likely correct than the other — no bolding, no "(likely)" label, no ordering that implies preference beyond date.

### 16. Confirm both source cards show their date, and the newer one leads

Look at the two citation cards, whether in the right-hand margin (wide window) or inline beneath the answer (narrow window — see Part D). Each card now shows an "Added <date>" line beneath the passage — a line that does not appear on an ordinary, non-conflicting answer's cards. The card for `protocol-2023.txt` (added second, so newer) appears **before** the card for `protocol-2019.txt` in the list — newest first, per the date-and-supersession ordering, not the order the model happened to cite them.

### 17. Confirm the resolve offer is present

Below the two cited positions, a line reads "Which one is current?" with one button per source, each labelled with its filename (`protocol-2019.txt`, `protocol-2023.txt`). Click the button for `protocol-2023.txt`.

**You should see:** the buttons disappear, replaced by a line reading "Noted protocol-2023.txt as current for the notice period. This is not saved yet — Askwell will remember it once memory ships." This is a client-side note only — nothing is sent anywhere (open your browser's network panel if you want to confirm no request fires on the click).

### 18. Confirm the choice does not survive a refresh

Reload the page.

**You should see:** the turn, once re-expanded or re-asked, shows the "Which one is current?" buttons again rather than the "Noted…" line — the pending-resolution choice was never persisted, exactly as the ticket's own scope says ("records the user's choice as a pending resolution ... until memory ships"), and step 17's note is honest about that rather than implying the choice was kept.

---

## Part C — three or more sources, and a superseded one demoted rather than shown as an equal

### 19. Add a third document restating the current figure

```bash
scripts/dev.sh run python3 - <<'PY'
with open("/app/askwell-test-material/field-manual.txt", "w") as f:
    f.write(
        "Field Manual, Appendix C. Before taking a sensor out of service, "
        "staff must give one hundred and twenty days notice.\n"
    )
print("done")
PY
```

Add it the same way as before, and confirm it reaches `status` = `ready` via the same query as step 14.

### 20. Mark the 2019 protocol as superseded by the 2023 one

```sql
UPDATE documents SET superseded_by = (SELECT id FROM documents WHERE filename = 'protocol-2023.txt')
WHERE filename = 'protocol-2019.txt';
```

**You should see:** `UPDATE 1`.

### 21. Ask the same question again, in a new conversation

```
How much notice must field staff give before decommissioning a sensor?
```

**You should see:** an answer citing all three documents (assuming the model surfaces all three as disagreeing — if it composes only two into the conflict, that is model behaviour outside this ticket's scope; re-run once if the first attempt only retrieves two). All three cards appear, each showing its date. The card for `protocol-2019.txt` shows, in addition to its "Added" date, a second line reading "Superseded" (with a date, if `superseded_at` is set) — visually distinct from the plain "Added" line on the other two cards. It sits **last** in the card order regardless of its actual added date — demoted, not presented as an equal to the two current positions.

### 22. Narrow the browser window and confirm both cards stay visible inline

Narrow the window below roughly three columns' width (the point where the right-hand provenance margin disappears — resize until you see the layout collapse to a single column).

**You should see:** the same cards, with the same dates and the same "Conflicting sources on" heading, now rendered inline beneath the answer text instead of in a side margin. Nothing about the conflict — heading, positions, dates, supersession label, resolve offer — disappears or becomes unreachable at this width.

---

## Cleanup

```
podman compose down -v
```

Restore `.env` if you changed anything beyond what **Before you start** asked for.

---

## Known gaps

- **No memory write.** The resolve offer (steps 17–18) never persists past a page refresh or a new tab — `ResolveOffer`'s state is component-local React state, not sent to the server. This is by design until M3 ships a memory store; the on-screen note in step 17 says so. Do not report the lack of persistence as a defect.
- **Conflict detection itself is out of scope here.** Whether the model actually produces a `Conflicting sources on …:` line for a given pair of passages is `M2-PARTIAL-BE-059`'s concern (prompt-driven, and can mis-detect in either direction, per that ticket's own known gaps). This walkthrough assumes detection succeeds, as it did when this document was written; if it does not on a given run, that is a model/prompt issue to file separately, not a rendering defect.
- **No low-confidence OCR notation exercised.** The ticket's edge case — a conflict where one side is a low-confidence OCR page, noted as such — depends on an OCR-flag path this walkthrough's typed-text material never exercises.
- **The undated-document tier is not exercised.** `sortByDateAndSupersession` sorts a document with no known `addedAt` between dated and superseded documents, but every document in this walkthrough has an `added_at` from ingestion, so that middle tier is never actually shown on screen here.
- **The single-source "conflict" edge case is not reachable.** `ResolveOffer` only renders its buttons once at least two citations exist on the turn (`citations.length < 2` renders nothing) — this is consistent with a conflict needing at least two sources to disagree, and is not a gap, but is worth knowing if a future conflict-composition change ever produces a conflict topic with only one citation attached.
