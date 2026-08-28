# Manual test — M2-ABSTAIN-BE-054, abstention copy that proves the search happened

**Ticket:** `M2-ABSTAIN-BE-054` — `askwell.agent.abstain.compose_abstention` builds the three-part abstention message (state the situation, prove the search happened with real counts and the nearest topic, give the next action), for the three reason codes `M2-ABSTAIN-RET-053` already computes; the standing no-general-knowledge rule lives in `api/src/askwell/agent/prompts/abstention.v1.md`.
**Version under test:** `0.2.42`
**Time:** about 45 minutes, plus a first stack build. Needs the `bge-m3` embedding weights (see **Before you start**); the reranker weights are not required.
**Who can run it:** a terminal and a browser, plus native inference running on the host.

**What is being checked.** `api/src/askwell/ask.py`'s `_run_generation`, on the abstain branch: `_abstain_reason` returns the real reason code plus real passage/document/database counts (`_SEARCH_EXTENT_SQL`, scoped identically to what `retrieve()` actually searched), the nearest scored candidate's own `heading` (or `filename` if it has none) is passed as `nearest_heading`, and `askwell.agent.abstain.compose_abstention` renders one of three messages from those inputs — no second model call. That composed text is what `messages.content` now stores for an abstained turn (previously empty string, per `M2-ABSTAIN-RET-053`'s own manual test).

**Where this stops on purpose.** There is still no rendering. `web/components/ask/ask-screen.tsx`'s `turn.answer` is only ever appended to from `token` SSE events, and an abstained turn emits none — `compose_abstention`'s output reaches `messages.content` in the database but never reaches the browser. `M2-ABSTAIN-FE-055` is what streams or otherwise renders it. This walkthrough reads the real composed message out of the database, the same way `M2-ABSTAIN-RET-053`'s manual test read scores and reason codes before any copy existed.

---

## Before you start

- `.env.example` names `ASKWELL_EMBEDDING_MODEL_PATH=~/.local/share/askwell/models/bge-m3-FP16.gguf` and `ASKWELL_RETRIEVAL_SCORE_THRESHOLD=0.65`. Only the embedding weights are needed for this document.

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

**You should see:** lint, format, typecheck and test stages finish without red error text, including `api/tests/test_abstain.py` (the composition unit tests) and `api/tests/test_ask_api.py`'s abstention tests (`test_no_candidate_above_threshold_abstains_rather_than_answering`, `test_all_candidates_below_threshold_abstains_with_the_near_miss_stored`, `test_a_source_scoped_question_against_a_still_indexing_source_says_so`).

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

Leave this running in its own terminal for the rest of this document. Wait for it to report the embedding role `ready` on the port from `ASKWELL_EMBEDDING_PORT`.

---

## Part A — the empty-corpus message, before anything is indexed

### 7. Open the app with nothing added yet

Open a browser at:

```
http://127.0.0.1:8000
```

Click **Ask** in the left strip.

**You should see:** the "Ask your own material" page's first-run, empty-corpus state — no chat box, a statement that no documents are indexed yet, and an **Add a source** button. This screen is `web/`'s own pre-first-question empty state, not the composed abstention message this ticket adds — there is no conversation yet for it to belong to.

### 8. Start a conversation anyway, from a source-scoped question

This ticket's empty-corpus variant is exercised the same way `M2-ABSTAIN-RET-053`'s was: a question scoped to a source with nothing indexed under it. Insert one directly, since the UI's own empty-corpus screen does not offer a way to ask a scoped question with no source yet added:

```
scripts/dev.sh psql
```

```sql
INSERT INTO sources (id, kind, name) VALUES (gen_random_uuid(), 'file', 'placeholder') RETURNING id;
```

**You should see:** one UUID printed. Copy it — call it `SOURCE_ID` below.

### 9. Ask a source-scoped question against it, without adding any document

```bash
curl -N -s -X POST http://127.0.0.1:8000/ask \
  -H 'Content-Type: application/json' \
  -d "{\"question\": \"What does it say?\", \"source_id\": \"SOURCE_ID\"}" | head -40
```

(Replace `SOURCE_ID` with the UUID from step 8. This is a direct API call rather than a click, because the UI has no path to a source-scoped question with zero documents under it — every source the browser can create already has at least one file attached by the time it is askable.)

**You should see:** an SSE stream ending in a `done` event with a `message_id`. No `token` events anywhere in it — matching Part C's browser behaviour below, no answer text ever streams for an abstained turn.

### 10. Read the composed message from the database

```sql
SELECT content FROM messages WHERE id = 'MESSAGE_ID';
```

(Replace `MESSAGE_ID` with the `done` event's value.)

**You should see** exactly:

```
Nothing in your files answers this — nothing is indexed yet.
Add a source, and ask again.
```

No apology, no hedge, no counts, no "closest material" sentence — the empty-corpus variant has no search to prove happened.

---

## Part B — a corpus about one narrow topic, through the browser

### 11. Write one file with a clear, narrow fact

```bash
scripts/dev.sh run python3 - <<'PY'
with open("/app/askwell-test-material/notice-period.txt", "w") as f:
    f.write(
        "Section 4.2 Termination. Either party may terminate this agreement by "
        "giving ninety days' written notice to the other party.\n"
    )
print("done")
PY
```

**You should see:** the script print `done`.

### 12. Nominate the folder your material is in

Click **Settings** in the left strip, scroll to **Folders Askwell may read**, type your own path into the **Nominate a folder** field —

```
/home/you/external/quantum-plus/askwell/askwell-test-material
```

— and click **Nominate**.

**You should see:** a box appear showing that path, marked **Readable**.

### 13. Get to the add screen and add the file

Click **Ask** in the left strip, then **Add a source**.

**You should see:** the "Add a source" page, address bar ending in `/sources/add/`.

Open your file manager at `~/external/quantum-plus/askwell/askwell-test-material`. Drag `notice-period.txt` onto the window and release, type the folder with your own path when asked, and click **Add it**.

**You should see:** a card move to **Queued**, then progress as extraction, chunking and embedding run for real, and settle with no red error text.

### 14. Confirm it reached `ready`

In the `psql` session:

```sql
SELECT filename, status FROM documents WHERE filename = 'notice-period.txt';
```

**You should see:** one row, `status` = `ready`.

---

## Part C — a question the corpus does not cover abstains, with real counts and a named near miss

### 15. Click **Ask** and ask something the one document has nothing to do with

```
What is the capital of France?
```

Send it.

**You should see:** named progress appear ("Searching your files." then "Nothing in your files answers this.") and then disappear — no answer text ever appears. The turn ends with the question shown and a blank space beneath it: no citations, no follow-up suggestions, no error banner. This is the known gap named above: the turn correctly composed real copy server-side, but nothing on screen shows it yet.

### 16. Read the composed message from the database

```sql
SELECT content, source_count FROM messages WHERE role = 'assistant' ORDER BY created_at DESC LIMIT 1;
```

**You should see:** `source_count` is `NULL`, not `0`, and `content` reads:

```
Nothing in your files answers this.
I searched 1 passage across 1 document. The closest material was about notice-period.txt, which does not cover this.
Add the source you'd expect this in, and ask again.
```

(The nearest material names `notice-period.txt` because the one chunk this file produced has no `heading` — `_run_generation` falls back to `filename`, per `compose_abstention`'s own contract. A file whose extractor produces headed sections would name the section instead.)

### 17. Confirm the abstain trace step and reason code are still there

```sql
SELECT trace -> 'steps' FROM messages WHERE role = 'assistant' ORDER BY created_at DESC LIMIT 1;
```

**You should see:** the `abstain` step with `"reason_code": "below_threshold"`, unchanged from `M2-ABSTAIN-RET-053` — this ticket only changed what `content` holds, not the trace shape.

---

## Part D — a question the corpus half-covers is not abstention

### 18. Ask the question the corpus actually answers

```
How much notice is required to terminate the agreement?
```

Send it.

**You should see:** the ordinary answered path — named progress, then the answer streaming in as text, citing `notice-period.txt`. This is the ticket's "Other scenarios" note: confirm the abstention path is not taken here.

### 19. Confirm in the database that no abstention copy was composed

```sql
SELECT content FROM messages WHERE role = 'assistant' ORDER BY created_at DESC LIMIT 1;
```

**You should see:** `content` holding the real streamed answer text (containing "ninety days"), not any of the three abstention templates above.

---

## Part E — the standing no-general-knowledge rule survives in the prompt file

### 20. Read the prompt file directly

```bash
grep -A2 "General knowledge is never used" api/src/askwell/agent/prompts/abstention.v1.md
```

**You should see:** the sentence "General knowledge is never used to answer a question about the user's own material." followed by its explanation. `api/tests/test_abstain.py::test_c5_standing_statement_present_in_prompt_file` asserts this same text is present, and `test_c5_fails_if_standing_statement_removed` proves that test would actually fail if the sentence were edited out — this file is the one place C5's abstention wording is written down for this ticket, not duplicated into application code (`AGENTS.md` §4: "All prompts live in `api/src/askwell/agent/prompts/` as versioned files").

---

## Known gaps

- **No rendering.** `web/components/ask/ask-screen.tsx`'s `turn.answer` only ever grows from `token` SSE events, and an abstained turn's `_run_generation` never emits one — the composed message this ticket adds reaches `messages.content` but not the browser. An abstained turn still renders as a question with nothing beneath it, exactly as `M2-ABSTAIN-RET-053`'s manual test found before this ticket. That is `M2-ABSTAIN-FE-055`, explicitly out of this ticket's scope.
- **Part A's empty-corpus scenario needs a direct `curl`, not a click.** The browser's own "Ask your own material" empty state (step 7) covers the no-conversation-yet case, but there is no UI path to a source-scoped question against a source with zero documents — every source the add flow creates already has a document attached. Reproducing the `empty_corpus` reason code for a source-scoped question therefore needs the source inserted directly and the question sent by `curl`, matching how `M2-ABSTAIN-RET-053`'s own manual test never exercised `source_indexing` through the UI either.
- **The near-miss heading in Part C is whatever the real extractor happens to produce**, not a chosen value. `notice-period.txt` here has no heading so falls back to its filename; a document whose chunks carry real section headings would name one of those instead, and this document does not attempt to force that case.
- **No trace viewer.** Every count and message in this document was read with `psql`, not a rendered trace panel, matching the same gap in `M2-ABSTAIN-RET-053`'s manual test.
