# Manual test — M2-PARTIAL-BE-059, conflicting sources

**Ticket:** `M2-PARTIAL-BE-059` — two retrieved passages with materially different values for the same asked fact produce a conflict answer naming both with citations, never silently preferring one; a single consistent set produces an ordinary answer; supersession keeps a superseded document from ever standing as an equal to the version that replaced it.
**Version under test:** `0.2.46`
**Time:** about 45 minutes, plus a first stack build. Builds on `M2-PARTIAL-BE-057`'s corpus pattern (one document, one composer question) but needs **two** documents that disagree, plus a third revision that supersedes one of them.
**Who can run it:** a terminal and a browser, plus native inference running on the host.

**What is being checked.** `api/src/askwell/ask.py`'s `_run_generation`: every non-abstained turn now composes with `askwell.agent.conflict.compose_conflict` in place of `compose_partial`. Its prompt (`api/src/askwell/agent/prompts/conflicting_sources.v1.md`) is `partial_answer.v1.md`'s content in full plus one addition — when two retrieved passages disagree on the actual value asked about, present both as ordinary cited claims, one sentence each, under a fixed line: `Conflicting sources on <the fact>:`. `split_conflict_answer` reads that line back out of the streamed text; if found, `messages.trace` and the `ask_asked` row in `audit_interactions` both get `conflict_detected: true` and `conflict_topic`. A single consistent answer parses to nothing and both records show `conflict_detected: false`, matching what they showed before this ticket. Supersession is not new code here — `askwell.retrieve` already drops a superseded document from every candidate query, so this walkthrough confirms that behaviour still holds once conflict composition sits downstream of it, rather than testing new supersession logic.

**Where this stops on purpose.** There is no rendering yet — `web/components/ask/ask-screen.tsx` does not distinguish a conflict answer from ordinary prose; that is `M2-PARTIAL-FE-058`'s territory extended, not built here. There is no memory-based resolution — `compose_conflict`'s `memory_fact` parameter exists but nothing in this milestone ever passes one, so the "Resolved by memory:" convention cannot be exercised from the running product yet (M3). This walkthrough reads the real conflict marking out of the database, the same way `M2-PARTIAL-BE-057`'s manual test read partial marking before its own rendering ticket existed.

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

**You should see:** lint, format, typecheck and test stages finish without red error text, including `api/tests/test_conflict.py` and the two new conflict cases in `api/tests/test_ask_api.py`.

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

## Part A — two documents that disagree on the same figure

### 8. Write two files that give different notice periods

```bash
scripts/dev.sh run python3 - <<'PY'
with open("/app/askwell-test-material/protocol-2019.txt", "w") as f:
    f.write(
        "Field Sampling Protocol (2019 revision). Section 4.2 Notice. "
        "Field staff must give ninety days notice before decommissioning a sensor.\n"
    )
with open("/app/askwell-test-material/protocol-2023.txt", "w") as f:
    f.write(
        "Field Sampling Protocol (2023 revision). Section 4.2 Notice. "
        "Field staff must give sixty days notice before decommissioning a sensor.\n"
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

### 10. Add both files

Open your file manager at `~/external/quantum-plus/askwell/askwell-test-material`. Drag both `protocol-2019.txt` and `protocol-2023.txt` onto the window and release, type the folder with your own path when asked, and click **Add it**.

**You should see:** two cards move to **Queued**, then progress as extraction, chunking and embedding run for real, and settle with no red error text.

### 11. Confirm both reached `ready`

```
scripts/dev.sh psql
```

```sql
SELECT filename, status FROM documents ORDER BY filename;
```

**You should see:** two rows, `protocol-2019.txt` and `protocol-2023.txt`, both `status` = `ready`. Neither has a `superseded_by` set yet.

Keep this `psql` session open in its own terminal — you will re-run queries against it through the rest of this document.

---

## Part B — a question that hits both, and the conflict branch is taken

### 12. Click **Ask** and ask the shared question

Type into the composer:

```
How much notice must field staff give before decommissioning a sensor?
```

Press Enter (or click send).

**You should see:** named progress ("Searching your files." then "Reading 2 sources."), then an answer streaming in with two citation cards, one to each protocol file. Somewhere in the streamed text, a line appears verbatim: `Conflicting sources on the notice period:` (or a close paraphrase naming the same fact — the exact wording of the label the model puts after "on" is the model's; the `Conflicting sources on` prefix and the two cited positions are fixed), followed by two sentences — one stating ninety days with a citation to `protocol-2019.txt`, one stating sixty days with a citation to `protocol-2023.txt`. Nothing on screen marks this as a conflict specially — it renders as ordinary streamed prose, which is the rendering gap this ticket's own scope excludes (`M2-PARTIAL-FE-058`).

### 13. Read the trace and confirm the turn is marked as a conflict

In the `psql` session:

```sql
SELECT trace -> 'conflict_detected' AS conflict, trace -> 'conflict_topic' AS topic
FROM messages WHERE role = 'assistant' ORDER BY created_at DESC LIMIT 1;
```

**You should see:** `conflict` = `true` and `topic` a string naming the notice period specifically — not a generic phrase like `"the sources disagree"`.

### 14. Confirm the `compose` trace step carries the same marking

```sql
SELECT step FROM messages, jsonb_array_elements(trace -> 'steps') AS step
WHERE role = 'assistant' AND step ->> 'kind' = 'compose'
ORDER BY created_at DESC LIMIT 1;
```

**You should see:** the same `conflict_detected: true` and `conflict_topic` inside this one step, alongside the ordinary `claims`, `citations`, `partial_coverage` and `uncovered_aspects` fields — a conflict answer and a partial answer are read from the same composed text independently, and this question is fully covered so `partial_coverage` should be `false` here.

### 15. Confirm the audit record agrees

```sql
SELECT payload ->> 'conflict_detected' AS conflict, payload ->> 'conflict_topic' AS topic
FROM audit_interactions WHERE kind = 'ask_asked' ORDER BY occurred_at DESC LIMIT 1;
```

**You should see:** `conflict` = `"true"` and `topic` naming the same fact as step 13 — the ticket's own "conflicts detected are recorded on the interaction" acceptance criterion, checked against the real audit store rather than only the trace.

---

## Part C — superseding one document removes the conflict, without new code to test for it

### 16. Mark the 2019 protocol as superseded by the 2023 one

There is no UI for supersession yet in this repository, so set it directly for this walkthrough:

```sql
UPDATE documents SET superseded_by = (SELECT id FROM documents WHERE filename = 'protocol-2023.txt')
WHERE filename = 'protocol-2019.txt';
```

**You should see:** `UPDATE 1`.

### 17. Ask the same question again, in a new conversation

Click **Ask**, start a new conversation if the interface does not do so automatically, and ask:

```
How much notice must field staff give before decommissioning a sensor?
```

**You should see:** named progress, then an answer citing only `protocol-2023.txt`, stating sixty days, with **no** `Conflicting sources on` line and no mention of ninety days — the superseded 2019 document is not retrieved as a candidate at all, so there is nothing left to conflict with.

### 18. Confirm the trace shows an ordinary answer, not a conflict

```sql
SELECT trace -> 'conflict_detected' AS conflict, trace -> 'conflict_topic' AS topic
FROM messages WHERE role = 'assistant' ORDER BY created_at DESC LIMIT 1;
```

**You should see:** `conflict` = `false`, `topic` = `null` — the current version answers alone, as of its own revision, exactly as the ticket's testing notes describe.

---

## Part D — passages that agree in substance but differ in wording are not a false conflict

The ticket's own edge case: over-detection is as bad as under-detection.

### 19. Add a third document restating the current figure differently

```bash
scripts/dev.sh run python3 - <<'PY'
with open("/app/askwell-test-material/field-manual.txt", "w") as f:
    f.write(
        "Field Manual, Appendix C. Before taking a sensor out of service, "
        "staff give two months' notice.\n"
    )
print("done")
PY
```

Add it the same way as step 10 (drag onto the **Add a source** page, confirm the folder, click **Add it**), and confirm it reaches `status` = `ready` via the same `psql` query as step 11.

### 20. Ask the question again, in a new conversation

```
How much notice must field staff give before decommissioning a sensor?
```

**You should see:** an answer citing `protocol-2023.txt` and `field-manual.txt` together, stating sixty days (or "two months," restated as consistent by the model) with **no** `Conflicting sources on` line — sixty days and two months are the same substance stated differently, not a disagreement on the actual value.

### 21. Confirm the trace agrees

```sql
SELECT trace -> 'conflict_detected' AS conflict
FROM messages WHERE role = 'assistant' ORDER BY created_at DESC LIMIT 1;
```

**You should see:** `conflict` = `false`. If this instead reads `true`, that is a real defect against this ticket's own edge case, not a known gap — file it rather than working around it.

---

## Cleanup

```
podman compose down -v
```

Restore `.env` if you changed anything beyond what **Before you start** asked for.

---

## Known gaps

- **No rendering.** `web/components/ask/ask-screen.tsx` does not read `conflict_detected` or `conflict_topic`. The `Conflicting sources on` line and its two positions in step 12 are ordinary streamed prose with no visual distinction, no side-by-side layout, and no per-position OCR-quality note — `docs/ux/ask.md` §5's **Conflicting sources** state (both presented with both citations and their dates, never silently preferring one, offering to resolve) is not yet built on screen. That is `M2-PARTIAL-FE-058`'s scope, extended to cover conflicts, and has not landed as of this version.
- **No memory-based resolution.** `compose_conflict`'s `memory_fact` parameter and the `Resolved by memory:` convention `split_conflict_answer` already reads back are both inert — nothing in this milestone calls `compose_conflict` with a memory fact, because there is no memory store yet to supply one from (M3). Part C's supersession update is the only way this walkthrough can make a previously-conflicting question resolve to one answer; it is not memory resolution and does not exercise that code path.
- **No low-confidence OCR notation exercised.** The ticket's edge case — "a conflict where one side is a low-confidence OCR page — both presented with the OCR quality noted" — depends on the prompt's OCR-flag instruction but this walkthrough's material is typed text, not a scanned page, so that branch is not exercised here.
- **Detection is prompt-driven and can mis-detect**, exactly as the ticket's own "Known gaps" note says — a genuine substance disagreement can come back composed as a single position with no `Conflicting sources on` line, or (per Part D) two differently-worded but consistent passages can occasionally be flagged as conflicting depending on model output. This walkthrough cannot exercise that failure mode on demand; the conflicting-source eval subset (0.75 bar) is what measures it, and it does not exist yet in this milestone.
- **No online-AI path.** This ticket, like the rest of Phase 1–2, only exercises local inference. Conflict composition against a cloud model is out of scope until that phase exists.
