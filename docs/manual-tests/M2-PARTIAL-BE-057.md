# Manual test — M2-PARTIAL-BE-057, partial answers

**Ticket:** `M2-PARTIAL-BE-057` — a compound question with one covered aspect and one uncovered aspect is answered, with citations, for the covered part; the uncovered part is never guessed at, only named, in the fixed form `Not covered: <the specific aspect>.`; the turn is marked partial on the trace and the audit record. Every aspect covered composes as an ordinary answer. Every aspect uncovered stays abstention, never partial.
**Version under test:** `0.2.45`
**Time:** about 40 minutes, plus a first stack build. Builds on `M2-ABSTAIN-RET-053`'s corpus pattern (one narrow document, one clearly off-topic question) rather than reusing its files, because this ticket needs a document that covers **one** of two things a single question asks about.
**Who can run it:** a terminal and a browser, plus native inference running on the host.

**What is being checked.** `api/src/askwell/ask.py`'s `_run_generation`: once a turn has **not** abstained (`M2-ABSTAIN-RET-053`'s threshold check already passed), every non-abstained turn now composes with `askwell.agent.partial.compose_partial` in place of the plain `compose`. Its prompt (`api/src/askwell/agent/prompts/partial_answer.v1.md`) asks the model to answer, with citations, exactly what the retrieved content supports, and to write one `Not covered: <aspect>.` line for anything it does not. `split_partial_answer` reads those lines back out of the streamed text; if it finds any, the turn's `messages.trace` and the `ask_asked` row in `audit_interactions` both get `partial_coverage: true` and the list of `uncovered_aspects`. A fully-covered question parses to nothing uncovered and both records show `partial_coverage: false`, matching what they showed before this ticket.

**Where this stops on purpose.** There is no rendering yet — `web/components/ask/ask-screen.tsx` does not read `partial_coverage` or `uncovered_aspects` at all; that is `M2-PARTIAL-FE-058`. This walkthrough shows what the screen actually displays today (the `Not covered:` line arrives as ordinary streamed answer text, indistinguishable on screen from any other sentence) and reads the real partial marking out of the database, the same way `M2-ABSTAIN-RET-053`'s manual test read abstention out of the database before its own rendering ticket existed.

---

## Before you start

- `.env.example` names `ASKWELL_EMBEDDING_MODEL_PATH=~/.local/share/askwell/models/bge-m3-FP16.gguf` and `ASKWELL_RETRIEVAL_SCORE_THRESHOLD=0.65`. Only the embedding weights are strictly needed for Parts A–C; Part D needs the generation model to actually produce an answer, so have `ASKWELL_GENERATION_MODEL_PATH` pointed at whatever `Qwen3.5-4B-Q4_K_M.gguf` (or your configured generation model) is on this machine too.

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

**You should see:** lint, format, typecheck and test stages finish without red error text, including `api/tests/test_partial.py` and the three new partial-answer cases in `api/tests/test_ask_api.py`.

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

## Part A — a document covering one of two things a compound question asks about

### 8. Write a file that covers payment terms but says nothing about termination notice

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

### 11. Confirm it reached `ready`

```
scripts/dev.sh psql
```

```sql
SELECT filename, status FROM documents;
```

**You should see:** one row, `supplier-agreement.txt`, `status` = `ready`.

Keep this `psql` session open in its own terminal — you will re-run queries against it through the rest of this document.

---

## Part B — a compound question, half covered

### 12. Click **Ask** and ask about both the covered and the uncovered aspect in one question

Type into the composer:

```
What are the payment terms, and what is the termination notice period for this supplier?
```

Press Enter (or click send).

**You should see:** named progress ("Searching your files." then "Reading 1 source."), then an answer streaming in that states the payment term (forty-five days) with a citation card to `supplier-agreement.txt`. Somewhere after that sentence, a further line of plain text appears verbatim: `Not covered: the termination notice period for this supplier.` (or a close paraphrase naming that same aspect — the exact wording is the model's, only the `Not covered:` prefix and one line per gap are fixed). Nothing on screen marks this line as special — it renders as ordinary answer text, which is the gap `M2-PARTIAL-FE-058` exists to close.

### 13. Read the trace and confirm the turn is marked partial

In the `psql` session:

```sql
SELECT trace -> 'partial_coverage' AS partial, trace -> 'uncovered_aspects' AS uncovered
FROM messages WHERE role = 'assistant' ORDER BY created_at DESC LIMIT 1;
```

**You should see:** `partial` = `true` and `uncovered` a JSON array containing at least one string naming the termination notice period specifically — not a generic phrase like `"some information"`.

### 14. Confirm the `compose` trace step carries the same marking

```sql
SELECT step FROM messages, jsonb_array_elements(trace -> 'steps') AS step
WHERE role = 'assistant' AND step ->> 'kind' = 'compose'
ORDER BY created_at DESC LIMIT 1;
```

**You should see:** the same `partial_coverage: true` and `uncovered_aspects` array inside this one step, alongside the ordinary `claims` and `citations` counts — this is `M2-PARTIAL-FE-058`'s and the eval suite's intended read path, distinct from re-parsing the answer's own prose.

### 15. Confirm the audit record agrees

```sql
SELECT payload ->> 'partial' AS partial, payload -> 'uncovered_aspects' AS uncovered,
       payload ->> 'abstained' AS abstained
FROM audit_interactions WHERE kind = 'ask_asked' ORDER BY occurred_at DESC LIMIT 1;
```

**You should see:** `partial` = `"true"`, `abstained` = `"false"` — a partial answer is not an abstention, even though both are "the model did not just answer everything asked" — and `uncovered` naming the same gap as step 13.

---

## Part C — the fully uncovered version of the same question abstains instead

The ticket's own edge case: decomposition must not blur "nothing covered" into a partial answer with an empty covered half.

### 16. Ask only the uncovered half

In the same conversation, type:

```
What is the termination notice period for this supplier?
```

Send it.

**You should see:** named progress appear and then disappear, and no `Not covered:` prose — either an abstention message (if `M2-ABSTAIN-BE-054`/`FE-055`'s copy is what your build's `web/` renders) or, on this repository's current `web/`, the same "no answer text appears" gap `M2-ABSTAIN-RET-053`'s manual test already documents. Either way, no citation card appears.

### 17. Confirm it abstained rather than went partial

```sql
SELECT trace -> 'partial_coverage' AS partial, trace -> 'status' AS status, source_count
FROM messages WHERE role = 'assistant' ORDER BY created_at DESC LIMIT 1;
```

**You should see:** `partial` = `false` (never `true` on an abstained turn — the ticket's own edge case, and `test_every_aspect_uncovered_still_abstains_rather_than_going_partial` in `api/tests/test_ask_api.py` is what pins this in CI), `status` = `"completed"`, and `source_count` **`NULL`**, matching `M2-ABSTAIN-RET-053`'s "absent, not zero" convention.

---

## Part D — a fully covered question composes exactly as an ordinary answer

### 18. Ask only the covered half

Type:

```
What are the payment terms for this supplier?
```

Send it.

**You should see:** the answer streaming in, citing `supplier-agreement.txt`, stating forty-five days. No `Not covered:` line anywhere in the answer.

### 19. Confirm nothing is marked partial

```sql
SELECT trace -> 'partial_coverage' AS partial, trace -> 'uncovered_aspects' AS uncovered
FROM messages WHERE role = 'assistant' ORDER BY created_at DESC LIMIT 1;
```

**You should see:** `partial` = `false`, `uncovered` = `[]` — an ordinary answer, composed and stored exactly as it would have been before this ticket existed.

---

## Cleanup

```
podman compose down -v
```

Restore `.env` if you changed anything beyond what **Before you start** asked for.

---

## Known gaps

- **No rendering.** `web/components/ask/ask-screen.tsx` does not read `partial_coverage` or `uncovered_aspects`. The `Not covered:` line in step 12 is ordinary streamed prose with no visual distinction, no separate region, and no source-card treatment — `docs/ux/ask.md` §5's **Partial** state (grounded part answered, ungrounded part named, never smoothed into fluent prose) is not yet built on screen. That is `M2-PARTIAL-FE-058`.
- **Aspect decomposition is prompt-driven and can miss an aspect**, exactly as the ticket's own "Known gaps" note says — a genuinely compound question can come back answered as if it were single-aspect, with no `Not covered:` line at all. This walkthrough cannot exercise that failure mode on demand; the eval suite is what measures it, not this document.
- **Reasoning-model `<think>` output is not stripped before `Not covered:` lines are parsed.** Filed as [#220](https://github.com/Rumeasiyan/askwell/issues/220): with the shipped generation model, the model can rehearse the `Not covered:` line inside a `<think>` block before writing it for real, and `split_partial_answer` — which reads the whole streamed text, not just what is meant to be shown — picks up every rehearsal as a separate entry. If step 13's `uncovered` array in your run has more than one entry naming the same aspect, that is this known gap, not a new defect. It is pre-existing in the wider pipeline (`segment_claims`'s citation markers carry the same exposure) and not scoped to this ticket.
- **No online-AI path.** This ticket, like the rest of Phase 1–2, only exercises local inference. Partial-answer composition against a cloud model is out of scope until that phase exists.
