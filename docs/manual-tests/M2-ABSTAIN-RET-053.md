# Manual test — M2-ABSTAIN-RET-053, the retrieval threshold and the abstention decision

**Ticket:** `M2-ABSTAIN-RET-053` — a configurable threshold applied to `candidate_score()`, compared before `compose()` ever runs; a question with no candidate above threshold abstains, a question with a clear match answers; the threshold in force and every candidate's score (including the near-miss) are stored on the turn.
**Version under test:** `0.2.41`
**Time:** about 45 minutes, plus a first stack build. Needs the `bge-m3` embedding weights (see **Before you start**); the reranker weights are not required — every scenario below is exercised on dense score alone, matching Part C of `docs/manual-tests/M1-ASK-RET-036.md`.
**Who can run it:** a terminal and a browser, plus native inference running on the host.

**What is being checked.** `api/src/askwell/ask.py`'s `_run_generation`: after `retrieve()` returns, every candidate's `candidate_score()` is computed, the best one is compared against `RetrievalResult.threshold`, and — if nothing clears it — an `abstain` trace step is written and generation stops before `compose()` is ever called. The threshold and every candidate's score are written into `messages.trace`'s `retrieve` step (`hits`), not recomputed later, and into `audit_interactions` (`abstained`, `threshold`, `retrieved_chunks`).

**Where this stops on purpose.** There is no abstention *copy* yet — `_abstain_reason` in `api/src/askwell/ask.py` already returns three distinct reason codes (`empty_corpus`, `below_threshold`, `source_indexing`) and a plain-English sentence for each, but nothing in `web/components/ask/ask-screen.tsx` reads them; that is `M2-ABSTAIN-BE-054` (copy) and `M2-ABSTAIN-FE-055` (rendering). This walkthrough shows what the screen actually does today when a turn abstains — which is close to nothing — and reads the real reason and scores out of the database instead, the way `M1-ASK-RET-036`'s manual test read reranking's own facts.

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

Confirm the threshold this run starts at:

```
grep ASKWELL_RETRIEVAL_SCORE_THRESHOLD .env
```

**You should see:** `ASKWELL_RETRIEVAL_SCORE_THRESHOLD=0.65` (or nothing, in which case the code's own default of `0.65` — `api/src/askwell/config.py`'s `retrieval_score_threshold` field — is in force). Part D below changes this deliberately; note the starting value so you can put it back.

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

**You should see:** lint, format, typecheck and test stages finish without red error text, including `api/tests/test_ask_api.py`'s threshold and abstention tests and `api/tests/test_retrieve.py`'s `candidate_score` tests.

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

## Part A — a corpus about one narrow topic, through the browser

### 8. Write one file with a clear, narrow fact

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

### 9. Get to the add screen by clicking

Click **Ask** in the left strip.

**You should see:** the "Ask your own material" page's first-run, empty-corpus state — no chat box, a statement that no documents are indexed yet, and an **Add a source** button.

Click **Add a source**.

**You should see:** the "Add a source" page, address bar ending in `/sources/add/`.

### 10. Add the file

Open your file manager at `~/external/quantum-plus/askwell/askwell-test-material`. Drag `notice-period.txt` onto the window and release, type the folder with your own path when asked, and click **Add it**.

**You should see:** a card move to **Queued**, then progress as extraction, chunking and embedding run for real, and settle with no red error text.

### 11. Confirm it reached `ready`

```
scripts/dev.sh psql
```

```sql
SELECT filename, status FROM documents;
```

**You should see:** one row, `notice-period.txt`, `status` = `ready`.

Keep this `psql` session open in its own terminal — you will re-run queries against it through the rest of this document.

---

## Part B — a clear match answers

### 12. Click **Ask** and ask the question the corpus actually covers

Type into the composer:

```
How much notice is required to terminate the agreement?
```

Press Enter (or click send).

**You should see:** named progress ("Searching your files." then "Reading 1 source." or similar), then the answer streaming in as text, citing `notice-period.txt`. This is the ordinary answered path — no abstention.

### 13. Read the stored threshold and score for this turn

In the `psql` session:

```sql
SELECT trace -> 'steps' FROM messages WHERE role = 'assistant' ORDER BY created_at DESC LIMIT 1;
```

**You should see:** a `retrieve` step containing `"threshold": 0.65` and a `hits` array with one entry whose `score` is a number **at or above** `0.65`. An `abstain` step is **absent** from the list — the acceptance criterion's "a question with a clear match answers."

### 14. Confirm the interaction log agrees

```sql
SELECT abstained, threshold, citation_count FROM audit_interactions
WHERE event_type = 'ask_asked' ORDER BY created_at DESC LIMIT 1;
```

**You should see:** `abstained = false`, `threshold = 0.65`, `citation_count` ≥ 1.

---

## Part C — a question the corpus does not cover abstains

### 15. Ask something the one document has nothing to do with

In the same conversation, type:

```
What is the capital of France?
```

Send it.

**You should see:** named progress appear and then disappear — the same "Searching your files." step briefly, then nothing streams as tokens. **No answer text ever appears.** The turn ends with the question shown and a blank space beneath it: no citations, no follow-up suggestions, no error banner. This is the "no abstention copy yet" gap named above — the turn correctly stopped short of composing an answer, but nothing on screen says why yet.

### 16. Confirm, from the database, that this was a real abstention and not a silent failure

```sql
SELECT content, summary, source_count, trace -> 'status' AS status
FROM messages WHERE role = 'assistant' ORDER BY created_at DESC LIMIT 1;
```

**You should see:** `content` = empty string, `status` = `"completed"` (not `"failed"` — abstaining is not an error), and `source_count` is **`NULL`**, not `0` — the ticket's own "absent, not zero" distinction (`test_an_abstained_answer_stores_no_source_count_at_all`).

### 17. Read the near-miss (or its absence) and the reason code

```sql
SELECT trace -> 'steps' FROM messages WHERE role = 'assistant' ORDER BY created_at DESC LIMIT 1;
```

**You should see:** a `retrieve` step with `"threshold": 0.65` and a `hits` array. Because the corpus has only one narrow document, expect either an empty `hits` array (dense search found nothing worth returning) or one entry whose `score` is clearly **below** `0.65` — the near-miss the ticket's edge case requires be stored, not discarded. Immediately after it, an `abstain` step with `"reason_code": "below_threshold"` (or `"empty_corpus"` if `hits` came back empty).

### 18. Confirm the interaction log records the abstention too

```sql
SELECT abstained, threshold, citation_count, retrieved_chunks FROM audit_interactions
WHERE event_type = 'ask_asked' ORDER BY created_at DESC LIMIT 1;
```

**You should see:** `abstained = true`, `threshold = 0.65`, `citation_count = 0`, and `retrieved_chunks` containing whatever candidate scores were computed for this question (possibly empty) — C6's audit record, queryable without opening a trace file.

---

## Part D — raising the threshold turns a previously answered question into an abstention

This is the ticket's own "Other scenarios" note: proof the threshold is actually applied, not merely stored and ignored.

### 19. Stop native inference and the stack

In the inference terminal, `Ctrl-C`. Then:

```
podman compose down
```

(No `-v` this time — keep the indexed document.)

### 20. Raise the threshold past the score Part B's question scored

Open `.env`, find `ASKWELL_RETRIEVAL_SCORE_THRESHOLD=0.65`, and raise it well past the score you read in step 13 — `0.99` is safe regardless of what that score was:

```
ASKWELL_RETRIEVAL_SCORE_THRESHOLD=0.99
```

### 21. Bring the stack back up with the new threshold

```
podman compose up -d
scripts/dev.sh inference
```

Wait for the embedding role to report `ready` again, and for the browser at `http://127.0.0.1:8000` to load.

### 22. Ask the exact same question that answered in Part B

```
How much notice is required to terminate the agreement?
```

**You should see:** the same "no answer appears" behaviour as Part C — progress steps, then a blank turn. The question that produced a real, cited answer under `0.65` now abstains under `0.99`, with nothing about the corpus or the question having changed.

### 23. Confirm in the database

```sql
SELECT trace -> 'steps' FROM messages WHERE role = 'assistant' ORDER BY created_at DESC LIMIT 1;
```

**You should see:** `"threshold": 0.99` on the `retrieve` step, the same candidate `score` you recorded in step 13 (retrieval itself is unchanged — only the comparison moved), and now an `abstain` step with `"reason_code": "below_threshold"`.

### 24. Put the threshold back

Restore `.env` to the value you noted in **Before you start** (`0.65`), then repeat step 21 so the stack is left in its normal configuration.

---

## Part E — the threshold is never lowered automatically

There is no code path in `api/src/askwell/ask.py` or `api/src/askwell/retrieve.py` that adjusts `Settings.retrieval_score_threshold` at runtime — it is read once, from configuration, at process startup (`api/src/askwell/config.py load_settings()`, consumed by `register_ask`), and every trace and audit row above shows the exact value in force for that turn, not a live reference to a setting that could later change under it. This validation rule (**never lowered automatically, for any reason**) is confirmed by reading the code rather than by an action to take — there is nothing in the running product that could lower it, since nothing writes to it at all.

---

## Known gaps

- **No abstention copy or visual state.** `_abstain_reason` in `api/src/askwell/ask.py` computes a correct reason code and sentence for all three cases the ticket names (`empty_corpus`, `below_threshold`, `source_indexing`), but `web/components/ask/ask-screen.tsx` never reads `reason` for a `completed` turn with no citations — only for `failed`. An abstained turn renders as a question with nothing beneath it, not the "explicit I don't know state, visually distinct from an answer" `docs/states-and-edge-cases.md` §2 describes. That is `M2-ABSTAIN-BE-054` and `M2-ABSTAIN-FE-055`, both explicitly out of this ticket's scope.
- **No trace viewer.** Every score and reason code in this document was read with `psql`, not a rendered trace panel — matching the same gap `M1-ASK-RET-036`'s manual test recorded; no trace UI exists yet (`M2`/`M4`).
- **The `source_indexing` reason code is not exercised end-to-end here.** `api/tests/test_ask_api.py::test_a_source_scoped_question_against_a_still_indexing_source_says_so` covers it by inserting a `documents` row directly, bypassing the real ingest pipeline's timing window — reproducing it by clicking through the UI would need catching a source between "added" and "first chunk embedded," a race this document does not attempt to force.
- **The near-miss score in Part C is whatever the real embedding model happens to compute**, not a chosen value — unlike the ticket's own "0.61 against 0.65" example. If your corpus or off-topic question lands the score exactly at the boundary rather than clearly below it, that is a property of `bge-m3`'s real output on this input, not a defect in the threshold comparison itself.
- **No deployment-profile variation.** `retrieval_score_threshold` is one global default; a profile-specific override does not exist, so this document cannot show a `light`-profile threshold differing from a `full`-profile one.
