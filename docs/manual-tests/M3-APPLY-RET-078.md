# Manual test — M3-APPLY-RET-078, memory and schema notes retrieved alongside document chunks

**Ticket:** `M3-APPLY-RET-078` — at answer time, active `memory` facts and `schema_notes` relevant to the question are retrieved, bounded, and injected into the prompt in their own delimited, labelled blocks (`<memory-facts>`, `<schema-notes>`), separate from the retrieved documents. Confidence survives into the prompt as `[user-confirmed]` or `[inferred, confidence N%]`. Memory never bypasses grounding: retrieval only runs once a question has already cleared the abstention threshold. Which facts and notes were retrieved is recorded on the interaction (`messages.trace`, `audit_interactions`).
**Version under test:** `0.3.16`
**Time:** about an hour, plus a first stack build and native inference startup.
**Who can run it:** a browser, and `psql` access via `scripts/dev.sh psql` for the parts the app has no screen for yet — see "Where this stops on purpose".

**What is being checked.** `api/src/askwell/memory.retrieve_relevant_facts` (the bounded, ranked query over both stores); `api/src/askwell/agent/conflict.compose_conflict`'s new `retrieved_facts`/`retrieved_notes` parameters and the labelled `<memory-facts>`/`<schema-notes>` blocks they produce; `api/src/askwell/agent/prompts/conflicting_sources.v1.md`'s new section telling the model these are delimited data (C7), that `[inferred, ...]` entries are tentative, and that a disagreement between memory and a document is a conflict to present, not resolve silently; and `api/src/askwell/ask.py`'s `_run_generation`, which calls the new retrieval only after a document has already cleared the abstention threshold, and records `memory_fact_ids`/`schema_note_ids`/`memory_used` on both the message trace and the audit log.

**Where this stops on purpose — read this before reporting anything below as a defect.**

- **No screen renders which memory facts or schema notes a turn used.** `docs/ux/ask.md` §3/§4 specify a "memory chip" in the provenance margin and a "How did you get this?" trace panel; neither is built. The Memory screen (`web/app/memory/page.tsx`) is still `M3-MEM-FE-083`'s placeholder — it shows fixed copy, not a fact list. So this ticket's own Acceptance Criteria ("the prompt separates and labels...") and Audit requirement ("facts retrieved for a turn are recorded on the interaction") are checked below by reading `messages.trace`/`audit_interactions` directly, not by clicking anything — there is nothing yet to click.
- **`schema_notes` retrieval has no natural way to reach through the UI.** As `M3-STORE-BE-076`'s own manual test already found, nothing in the running app writes a schema note — there is no inference pipeline or screen action that produces one. This document exercises it, where it appears at all, by seeding rows directly, the same way that one did.
- **Citing memory or a schema note by claim** (a numbered citation the way a document passage gets one) is `M3-APPLY-BE-079`, not this ticket. The prompt tells the model plainly that this is not yet supported and it describes what memory told it in prose instead — do not report a missing memory citation as a defect here.
- **The local model's exact wording is not deterministic.** The "materially better answer" the ticket's own testing note asks for is a judgement call about the prose Askwell writes, not an exact string match — §1 below also gives an exactly-checkable proof (the trace row) alongside the readable one.

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

Create the two small files this walkthrough asks Askwell to read:

```
cat > askwell-test-material/procurement.txt <<'TXT'
The RFQ process starts on page 4 of the supplier handbook.
Every RFQ must be logged in the tracking sheet before it is sent.
TXT

cat > askwell-test-material/notice.txt <<'TXT'
Notice must be given ninety days in advance of termination.
TXT
```

`procurement.txt` uses "RFQ" twice, deliberately: `askwell.clarify`'s abbreviation trigger only raises a candidate once an unexplained all-caps term occurs at least twice in the corpus (`_MIN_ABBREVIATION_OCCURRENCES`) — one mention would never reach the Clarifications queue at all.

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

**You should see:** lint, format, typecheck and unmarked tests finish without red error text.

### 3. Bring the stack up and migrate

```
podman compose up -d
scripts/dev.sh db upgrade head
```

**You should see:** `postgres`, `redis`, `egress-proxy`, `api`, `worker` reported as started, then migration lines finishing with no error.

### 4. Start native inference, on the host

```
scripts/dev.sh inference
```

Leave this running in its own terminal for the rest of this document. Wait for it to report the embedding role `ready`.

### 5. Open the app and nominate the test folder

Open a browser at `http://127.0.0.1:8000`. **You should see:** the Askwell shell load with no sign-in prompt.

Click **Settings**, scroll to **Folders Askwell may read**, and nominate:

```
/home/you/external/quantum-plus/askwell/askwell-test-material
```

Click **Add a source** in the sidebar, choose that folder, and wait for the **Library** screen to show both `procurement.txt` and `notice.txt` as **Ready**.

---

## 1. The ticket's own walkthrough: a taught abbreviation changes the next answer

### 6. Wait for the abbreviation to be raised as a clarification

Click **Clarifications** in the sidebar. Ingestion runs its ambiguity scan once a source has nothing left outstanding, so this can take a few seconds after both files show **Ready**; refresh the screen if nothing shows yet.

**You should see:** one card whose subject is `RFQ`, with a question like "What does RFQ mean?" and evidence quoting the passage from `procurement.txt`.

### 7. Ask about it before teaching Askwell anything

Go to the **Ask** screen (route `/`) and click into the question box. Type:

```
What does RFQ mean?
```

Press `Enter`.

**You should see:** an answer that never states what RFQ stands for. Depending on retrieval, this is either Askwell abstaining outright ("Found nothing in your files answers this," or similar), or an answer that quotes the passage about the RFQ process without expanding the term — Askwell has no source for the expansion yet, so C5 (abstention over invention) means it does not guess one. Either is the expected "before" state; note which one you saw.

### 8. Answer the clarification through the real Clarifications screen

Return to **Clarifications**, open the `RFQ` card, type into its text field:

```
Request for Quotation
```

Click **Save**.

**You should see:** the card disappears from the pending list (or the count above it decreases by one).

### 9. Ask the identical question again

Go back to **Ask** and ask, exactly as before:

```
What does RFQ mean?
```

**You should see:** an answer that now says RFQ stands for Request for Quotation — a materially better answer than step 7's, using only what you just taught it (C5 is still satisfied: this is a taught fact, not an invented one).

### 10. Confirm it on the record, not just on screen

```
scripts/dev.sh psql <<'SQL'
SELECT m.id, m.trace->'memory_fact_ids' AS memory_fact_ids,
       m.trace->'schema_note_ids' AS schema_note_ids,
       m.trace->'memory_used' AS memory_used
FROM messages m
WHERE m.role = 'assistant'
ORDER BY m.created_at DESC
LIMIT 1;
SQL
```

**You should see:** `memory_fact_ids` holding one UUID (the fact you just taught), `schema_note_ids` an empty array, `memory_used` equal to `1`. This is the ticket's own Audit/Logging Requirement — the fact retrieved for this turn, recorded on the interaction, not merely reflected in prose.

```
scripts/dev.sh psql <<'SQL'
SELECT payload->'memory_fact_ids' AS memory_fact_ids, payload->'schema_note_ids' AS schema_note_ids
FROM audit_interactions
ORDER BY id DESC
LIMIT 1;
SQL
```

**You should see:** the same fact id, on the audit record as well as the message trace — both writes this ticket adds, in the same turn.

---

## 2. Edge case: a memory fact that contradicts a document produces a conflict, never a silent preference

### 11. Seed a fact that disagrees with `notice.txt`

`notice.txt` says notice is ninety days. Nothing in the running app writes a plain, unprompted "correction" memory fact outside of answering a clarification about a question Askwell actually asked — so this one is seeded directly, the same way `M3-STORE-BE-076`'s manual test seeds rows the app itself has no writer for yet:

```
scripts/dev.sh psql <<'SQL'
INSERT INTO memory (id, subject, fact, origin, confidence)
VALUES (gen_random_uuid(), 'notice period', 'Notice must be given sixty days in advance', 'correction', 1.0);
SQL
```

### 12. Ask the question the two now disagree on

On the **Ask** screen:

```
How much notice must be given?
```

**You should see:** an answer that presents **both** positions rather than picking one — a line reading `Conflicting sources on <the notice period>:` followed by one sentence citing `notice.txt`'s ninety days `[1]`, and one sentence describing what you just told Askwell (sixty days), in prose, attributed to memory rather than given a fabricated citation number.

### 13. Confirm the conflict was real, not a coincidence of wording

```
scripts/dev.sh psql <<'SQL'
SELECT trace->'conflict_detected' AS conflict_detected, trace->'conflict_topic' AS conflict_topic,
       trace->'memory_fact_ids' AS memory_fact_ids
FROM messages WHERE role = 'assistant' ORDER BY created_at DESC LIMIT 1;
SQL
```

**You should see:** `conflict_detected` is `true`, `conflict_topic` names the notice period, and `memory_fact_ids` includes the fact you seeded in step 11.

---

## 3. Edge case: a large memory store is bounded, not fully injected

### 14. Seed more matching facts than the cap

```
scripts/dev.sh psql <<'SQL'
INSERT INTO memory (id, subject, fact, origin, confidence)
SELECT gen_random_uuid(), 'notice period detail ' || g, 'Notice detail number ' || g, 'manual', 1.0
FROM generate_series(1, 6) AS g;
SQL
```

Six new rows, each matching "notice" — combined with the one from step 11, more than `RELEVANT_FACT_LIMIT` (5) now match the same question.

### 15. Ask the same question a third time

```
How much notice must be given?
```

### 16. Confirm the count, not just that it still answered

```
scripts/dev.sh psql <<'SQL'
SELECT jsonb_array_length(trace->'memory_fact_ids') AS facts_used
FROM messages WHERE role = 'assistant' ORDER BY created_at DESC LIMIT 1;
SQL
```

**You should see:** `facts_used` is `5`, never `7` — bounded, per the ticket's own edge case, even though seven rows in `memory` now match the question.

### 17. Clean up the seeded rows

```
scripts/dev.sh psql <<'SQL'
DELETE FROM memory WHERE subject LIKE 'notice period%';
SQL
```

---

## 4. Edge case: no relevant memory is an honest empty list, not an empty labelled block

### 18. Ask something nothing in memory bears on

```
What does the procurement handbook say about anything unrelated to RFQ or notice?
```

(Any question whose words do not match `RFQ`, `notice`, or the subjects seeded above works — the point is a genuine lexical miss.)

**You should see:** an ordinary answer, with no "Resolved by memory" or "Conflicting sources" line appended.

```
scripts/dev.sh psql <<'SQL'
SELECT trace->'memory_fact_ids' AS memory_fact_ids, trace->'memory_used' AS memory_used
FROM messages WHERE role = 'assistant' ORDER BY created_at DESC LIMIT 1;
SQL
```

**You should see:** `memory_fact_ids` is `[]` and `memory_used` is `0` — a plain, honest absence, matching `api/tests/test_ask_api.py::test_a_question_with_no_relevant_memory_records_none_used`, which is what actually proves the prompt itself never grows an empty `<memory-facts>` block for this case (not observable from the UI, since nothing renders the prompt).

---

## 5. C5 preserved: an abstained turn never retrieves memory at all

### 19. Ask something nothing in the corpus answers

```
What is the capital of France?
```

**You should see:** Askwell abstains — it does not answer from general knowledge just because a memory fact happens to exist about something else.

```
scripts/dev.sh psql <<'SQL'
SELECT trace->'memory_fact_ids' AS memory_fact_ids, trace->'steps' AS steps
FROM messages WHERE role = 'assistant' ORDER BY created_at DESC LIMIT 1;
SQL
```

**You should see:** `memory_fact_ids` is `[]`, and no `"kind": "memory_retrieve"` entry appears anywhere in `steps` — retrieval was never called, not merely called and empty. This matches `_run_generation`'s own structure: the memory lookup sits inside the `else` branch taken only once a document has cleared the abstention threshold.

---

## Known gaps

- **No screen shows which memory facts or schema notes a turn used.** `docs/ux/ask.md`'s memory chip and trace panel are both specified but not built — every check above that needs to see a retrieved id reads `messages.trace`/`audit_interactions` directly.
- **The Memory screen is still a placeholder** (`web/app/memory/page.tsx`, `M3-MEM-FE-083`) — it does not list facts, origins or confidence, so there is no way to browse what Askwell has learned by clicking.
- **`schema_notes` retrieval is exercised only by seeding rows.** No inference pipeline or screen writes a schema note yet (`M3-STORE-BE-076`'s own gap, unchanged by this ticket) — §2–§4 above all seed `memory`, never `schema_notes`, because there is no natural way to get one into the database through the app.
- **Citing memory or a schema note as a numbered source is not built** — that is `M3-APPLY-BE-079`. The model is expected to describe what memory told it in prose, never invent a citation number for it; this is correct behaviour, not a bug.
- **Retrieval is lexical full-text, not embedding similarity** (issue #292) — a fact that is semantically related but shares no words with the question will not be found. This is a known, open limitation, not something this ticket claims to fix.
- **The local model's answer wording is not deterministic.** §1's "materially better answer" is a readable judgement call; the trace check in the same section is what makes the same scenario exactly verifiable.
