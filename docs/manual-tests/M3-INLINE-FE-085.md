# Manual test — M3-INLINE-FE-085, inline clarification when a question blocks an answer

**Ticket:** `M3-INLINE-FE-085` — when an answer depends on an unresolved contradiction or document-identity ambiguity, the question is rendered inline in the conversation, with its evidence, instead of being left for the Clarifications queue. Answering it writes the fact and the answer completes using it. Skipping continues with the inference and the answer says which assumption it used. The user is never navigated away. `docs/ux/ask.md` §5 "Inline clarification"; `docs/ux/clarifications.md` §5 "Blocking an answer".
**Version under test:** `0.3.14`
**Time:** about 60–75 minutes, plus a first stack build and native inference startup.
**Who can run it:** a browser, a terminal, and `psql` access via `scripts/dev.sh psql`.

**What is being checked.** `api/src/askwell/inline_clarify.py` (`find_blocking`, `default_assumption`), the wiring into `api/src/askwell/ask.py` (`_await_clarification`, the `clarification`/`clarification_resolved` SSE events, `POST /ask/{id}/clarify/resolve`), and the frontend: `InlineClarification` in `web/components/ask/ask-screen.tsx`, the paused-turn state in `web/components/ask/ask-state.tsx`, and `resolveInlineClarification`/`recordInlineClarificationShown` in `web/lib/ask.ts`. Answering or skipping reuses `answerClarification`/`skipClarification` from `web/lib/clarifications.ts` — the same functions the queue screen (`M3-REVIEW-FE-074`) calls — so this walkthrough only exercises the interruption itself, not saving mechanics already covered there.

**What this is not.** Only `contradiction` and `document_identity` triggers can block (`BLOCKING_TRIGGERS` in `inline_clarify.py`). An abbreviation or a poor-scan clarification never interrupts a turn — it stays queue-only, unchanged by this ticket.

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

### 1. Bring the stack up

```
podman compose up -d
```

**You should see:** `postgres`, `redis`, `egress-proxy`, `api`, `worker` reported as started. Wait about thirty seconds.

### 2. Create the database tables

```
scripts/dev.sh db upgrade head
```

**You should see:** migration lines finish with no error.

### 3. Start native inference, on the host

```
scripts/dev.sh inference
```

Leave this running in its own terminal for the rest of this document. Wait for it to report the embedding role `ready` on its configured port.

### 4. Open the app and nominate the test folder

Open a browser at:

```
http://127.0.0.1:8000
```

**You should see:** the Askwell shell load with no sign-in prompt. If this is a genuinely fresh install you land on the welcome screen first — click through it.

Click **Settings** in the left rail, scroll to **Folders Askwell may read**, type your own path into the **Nominate a folder** field —

```
/home/you/external/quantum-plus/askwell/askwell-test-material
```

— and click **Nominate**.

**You should see:** a box appear showing that path, marked **Readable**.

### 5. Open a psql session and keep it open

```
scripts/dev.sh psql
```

Keep this terminal open for the rest of the walkthrough — used only to confirm what the app already did, never to drive it.

---

## Part A — create a real, unresolved contradiction to ask about

Contradiction detection scans one source's documents together, so both files must land in the *same* source before the queue is checked (the same ordering rule `M3-RAISE-BE-071`'s manual test documents). Write both at once, into one folder:

```bash
scripts/dev.sh run python3 - <<'PY'
import os
os.makedirs("/app/askwell-test-material/policy", exist_ok=True)
with open("/app/askwell-test-material/policy/handbook-2024.txt", "w") as f:
    f.write("Staff handbook. The notice period is 30 days for all staff.\n")
with open("/app/askwell-test-material/policy/policy-2025.txt", "w") as f:
    f.write("Updated policy. The notice period is 45 days for all staff.\n")
print("done")
PY
```

**You should see:** the script print `done`.

### 6. Add the folder as one source

Click **Ask** in the left rail.

**You should see:** the first-run, empty-corpus state — no chat box, a statement that no documents are indexed yet, and an **Add a source** button.

Click **Add a source**, point it at `.../askwell-test-material/policy`, and click **Add it**.

**You should see:** a card move to **Queued**, then progress through extraction, chunking and embedding, and settle with no red error text — both `handbook-2024.txt` and `policy-2025.txt` reach `status = 'ready'`.

### 7. Confirm the contradiction is pending, and nothing before this ticket already resolved it

```sql
SELECT subject, question, options, evidence ->> 'trigger' AS trigger, status
FROM clarifications WHERE subject LIKE '%notice period%';
```

**You should see:** one row, `status = 'pending'`, `trigger = 'contradiction'`, `options` a JSON array containing both `handbook-2024.txt` and `policy-2025.txt`.

---

## Walkthrough

### 8. Ask a question the contradiction is relevant to

Still on the Ask screen, type into the composer:

```
How much notice must I give?
```

Press **Enter**.

**You should see:** the usual retrieval steps appear (*searching your files*, *reading N sources*), and then — **before any answer text streams** — an inline card appears in the conversation, in place of the answer, showing:
- a small monospace label reading `the notice period`
- the question text, e.g. *"Both handbook-2024.txt and policy-2025.txt speak to the notice period and disagree — which is current?"* (exact wording depends on `_detect_contradictions`, but it names both files)
- an evidence block beneath it showing both passages, each with its own document name, page and the conflicting figure (30 days / 45 days)
- two buttons, one per document filename (`handbook-2024.txt`, `policy-2025.txt`) — no free-text field, since this clarification carries discrete `options`
- a **Skip** button
- no **deferred** note (only one blocking ambiguity is relevant here)

Confirm you were not navigated anywhere — the address bar still reads the Ask screen, and the question you typed is still visible above the card as the live turn.

### 9. Answer it, and watch the answer complete using your choice

Click the button for **policy-2025.txt**.

**You should see:** the card is replaced by the streaming answer, which completes stating **45 days**, citing `policy-2025.txt`.

```sql
SELECT status, answer FROM clarifications WHERE subject LIKE '%notice period%';
SELECT subject, fact, origin, confidence FROM memory WHERE subject LIKE '%notice period%';
SELECT kind FROM audit_decisions ORDER BY occurred_at DESC LIMIT 2;
```

**You should see:** the clarification is `answered` with `answer = 'policy-2025.txt'`; a `memory` row exists with `fact` containing `policy-2025.txt`, `origin = 'clarification'`, `confidence = 1.0`; the newest `audit_decisions` rows include `clarification_answered` — this inline answer is recorded exactly like a queue answer, per this ticket's own Audit requirement.

### 10. Ask a related question again, and confirm you are not asked twice

Type:

```
What is the notice period for staff?
```

**You should see:** the answer streams directly, with **no inline clarification card** — the ambiguity is already resolved (`status = 'answered'`, no longer `pending`), so `find_blocking` no longer matches it. This is the ticket's own edge case: "the same ambiguity blocking a later turn — asked once, then applied."

---

## Part B — skip, and confirm the answer names its assumption

### 11. Create a second, independent contradiction

```bash
scripts/dev.sh run python3 - <<'PY'
import os
os.makedirs("/app/askwell-test-material/leave", exist_ok=True)
with open("/app/askwell-test-material/leave/leave-2023.txt", "w") as f:
    f.write("Leave policy. Annual leave is 15 days per year.\n")
with open("/app/askwell-test-material/leave/leave-2025.txt", "w") as f:
    f.write("Revised leave policy. Annual leave is 20 days per year.\n")
print("done")
PY
```

Click **Add a source** again, point it at `.../askwell-test-material/leave`, click **Add it**, and wait for both documents to settle.

Confirm it is pending before asking:

```sql
SELECT subject, status FROM clarifications WHERE subject LIKE '%annual leave%' OR subject LIKE '%leave%';
```

**You should see:** one row, `pending`.

### 12. Ask about it, then click Skip

Type:

```
How many days of annual leave do I get?
```

**You should see:** the same inline-card shape as step 8, now for annual leave, with buttons for `leave-2023.txt` and `leave-2025.txt`.

Click **Skip**.

**You should see:** the card disappears and the answer streams. Once it finishes, it ends with an appended line naming the assumption used, in the shape *"Skipped the question about \"annual leave\" — this answer assumes leave-2025.txt (20 days per year). Answer it anytime in Clarifications."* — the newer document, per `default_assumption`'s own "compare by recency" rule.

```sql
SELECT status, answer FROM clarifications WHERE subject LIKE '%annual leave%';
SELECT count(*) FROM memory WHERE subject LIKE '%annual leave%';
```

**You should see:** `status = 'skipped'`, `answer` is `NULL`; the `memory` count is `0` — a skip never writes a fact, matching the queue's own skip semantics.

### 13. Confirm the skipped item is still reachable in the queue

Click **Clarifications** in the left rail.

**You should see:** the `annual leave` item is gone from **Pending** (it is `skipped`, not `pending`) — it does not reappear there, and it is not re-asked if you repeat the same question (re-run step 12's question and confirm no card appears this time).

---

## Part C — two blocking ambiguities in one turn: only one interrupts, the other is named as deferred

### 14. Ask a question relevant to both remaining unresolved ambiguities

By this point `notice period` is answered and `annual leave` is skipped, so create one more fresh contradiction to pair with a document-identity ambiguity in a single question. Reuse the same `policy` source's shape, this time as a document-identity case (two versions of the same document, one clearly superseding the other):

```bash
scripts/dev.sh run python3 - <<'PY'
import os
os.makedirs("/app/askwell-test-material/contract", exist_ok=True)
with open("/app/askwell-test-material/contract/agreement-v1.txt", "w") as f:
    f.write("Contract terms. Payment is due within 30 days.\n")
with open("/app/askwell-test-material/contract/agreement-v2-FINAL.txt", "w") as f:
    f.write("Contract terms. Payment is due within 15 days, superseding the earlier agreement.\n")
print("done")
PY
```

Add `.../askwell-test-material/contract` as its own source the same way, wait for it to settle, and confirm in `psql` that a `document_identity` clarification with `subject` around `contract` (or `agreement`) is `pending`.

```sql
SELECT subject, evidence ->> 'trigger' AS trigger, status FROM clarifications WHERE status = 'pending';
```

**You should see:** at least one `pending` row for the contract source. (If `notice period` or `annual leave` produced a further residual row, that is fine — Part C only needs one document-identity row to be pending alongside it is not required; this part can also be exercised any time two relevant `pending` rows exist for the same question. If only one is pending, skip to step 16 and treat this part as covered by step 8's single-match case; note this in your run notes rather than forcing a second contradiction.)

### 15. Ask a question naming both subjects, if you have two pending rows relevant to it

```
What are the contract terms and the notice period?
```

**You should see:** exactly **one** inline card (the higher-ranked trigger — `contradiction` outranks `document_identity` per `clarify.py`'s own `_TRIGGER_PRIORITY`, so a contradiction wins if both are pending and relevant), plus a line near the Skip/Save row reading **"1 more waiting in Clarifications"** (or the correct count, pluralised, if more than one is deferred).

Resolve the card (answer or skip, either is fine).

**You should see:** the answer completes, and if you skipped, the appended assumption note is followed by a second line naming the deferred count, e.g. *"1 more unresolved question about your files is waiting in Clarifications."*

Click **Clarifications** and confirm the deferred item is still `pending` there — not lost, not silently resolved.

---

## Part D — navigating away while a question is pending never loses it

### 16. Trigger another blocking clarification, then leave without answering

Ask a question that will hit a still-pending relevant contradiction or document-identity row (reuse one from above if any remain `pending`, or repeat Part A/C with a fresh pair of files if everything so far has been resolved).

Once the inline card appears, **do not click anything on it**. Click **Clarifications** in the left rail instead.

**You should see:** you land on the Clarifications screen normally — no confirmation dialog, no block on navigating.

Click **Ask** to return.

**You should see:** the same conversation, with the inline card for that turn still showing, unresolved and interactive, exactly as you left it. The turn is still paused server-side, not abandoned.

```sql
SELECT status FROM clarifications WHERE id = (
  SELECT id FROM clarifications ORDER BY asked_at DESC LIMIT 1
);
```

**You should see:** `status = 'pending'` — the question was never lost or silently re-answered by navigating away, matching the ticket's own edge case.

Resolve the card now (answer or skip) to leave the system clean for anyone testing after you.

---

## Known gaps

- **Deferred-count phrasing depends on live triggers.** Part C's exact deferred count is only reproducible if you keep two genuinely relevant `pending` rows in play at once; the walkthrough above notes the fallback if ingestion order or an earlier step already resolved one. This is a setup-fragility note about this manual test, not a defect in the ticket.
- **No inline "Stop" control on the card itself.** Stopping mid-clarification (the same **Stop** available while an answer is streaming) is not exposed from the inline card — the only ways out are answering, skipping, or navigating away, matching Part D. `api/src/askwell/ask.py`'s `_await_clarification` docstring says this is accepted: the turn simply stays paused, not lost, until the browser returns or explicitly stops the turn from elsewhere.
- **The local inline-clarification counter (`getInlineClarificationsShownCount` in `web/lib/ask.ts`) has no visible UI surface.** It increments on every card shown (C1: local only, nothing transmitted), but nothing on screen displays it — confirmed by reading the file, not exercised visually in this walkthrough.
- **Multiple simultaneous blocking ambiguities beyond two are untested here.** The ticket's own stated known gap ("multiple simultaneous blocking ambiguities may defer the second to the queue") is exercised for exactly two; a third relevant pending row is expected to also defer, per `find_blocking`'s `matches[1:]` behaviour, but was not separately walked.
