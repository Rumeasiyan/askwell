# Manual test — M3-RAISE-BE-070, check memory before raising any question

**Ticket:** `M3-RAISE-BE-070` — before any of the four M3 triggers' candidates becomes a question, `memory` and `schema_notes` are checked for a current fact on the same subject. A match suppresses the question outright (the existing fact applies, nothing is asked, nothing new is inferred over it); a superseded fact is ignored in favour of whatever superseded it; matching is exact only, never fuzzy.
**Version under test:** `0.3.3`
**Time:** about 60–75 minutes, plus a first stack build and native inference startup. Builds on `M3-RAISE-BE-068`'s triggers and `M3-RAISE-BE-069`'s ranking — this ticket only adds the pre-raise lookup on top of a pipeline those tickets' own manual tests already exercise individually.
**Who can run it:** a terminal, `psql` access via `scripts/dev.sh psql`, and native inference running on the host.

**What is being checked.** `askwell.clarify.raise_candidates` (`api/src/askwell/clarify.py`) now calls `_known_facts` on every candidate's subject, across all four triggers together, before the pass/fail tests ever run. `_known_facts` looks in `memory` first (`subject`, `fact`, any `origin`, any `confidence`, `superseded_by IS NULL`), then in `schema_notes` for whatever is left (`table_name` or `column_name` matching, `superseded_by IS NULL`). Anything found is removed from the candidate list entirely — no `clarifications` row, no `memory` inference — and logged instead as a `clarification_suppressed` decisions record naming the fact that was applied. Everything else about the pipeline (ranking, the cap, the abbreviation stoplist) is unchanged from `M3-RAISE-BE-069`.

**Where this stops on purpose.** There is no `/clarifications` screen, no way to answer or skip a question by clicking anything, and no `GET`/`POST` route for the `clarifications` table at all yet — confirmed by `gh issue view 257`, still open as of this version, which names exactly this gap and re-owns it ahead of `M3-REVIEW-FE-072`. "Answering" a question in this walkthrough therefore means doing by hand, in `psql`, what the eventual answer route will do: mark the `clarifications` row `answered` and write the resulting fact to `memory` — the same two statements `api/tests/test_clarify.py`'s own `test_a_second_source_with_the_same_abbreviation_asks_nothing` uses. This is not a shortcut around "click, don't call an endpoint"; there is nothing to click yet, and inventing a screen for this walkthrough would test something that does not exist.

---

## Before you start

- `.env.example` names `ASKWELL_EMBEDDING_MODEL_PATH=~/.local/share/askwell/models/bge-m3-FP16.gguf`. A document only reaches `status = 'ready'` — the trigger that fires `raise_candidates` — once it has been chunked and embedded, so the embedding model needs to be on this machine even though nothing here asks a question of the generation model.

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

### 2. Run the checks

```
scripts/dev.sh check
```

**You should see:** lint, format, typecheck and test stages finish without red error text.

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

### 6. Nominate the folder your material is in

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

### 7. Open a psql session and keep it open

```
scripts/dev.sh psql
```

Keep this terminal open for the rest of the walkthrough — every check below runs a query in it.

---

## Part A — a question gets raised, then answered, the way the ticket's own scenario expects

### 8. Write a file with a repeated, uncommon abbreviation

```bash
scripts/dev.sh run python3 - <<'PY'
text = "The RFQ closes Friday at noon. Another RFQ follows next week. RFQ terms are attached."
with open("/app/askwell-test-material/tender-one.txt", "w") as f:
    f.write(text + "\n")
print("done")
PY
```

**You should see:** the script print `done`. `RFQ` occurs three times, is not in the common-abbreviation stoplist (`PDF`, `HTML`, `USA`, and similar), and is not yet in `memory`.

### 9. Add the file by clicking through the app

Click **Ask** in the left strip.

**You should see:** the "Ask your own material" page's first-run, empty-corpus state — no chat box, a statement that no documents are indexed yet, and an **Add a source** button.

Click **Add a source**.

**You should see:** the "Add a source" page, address bar ending in `/sources/add/`.

Open your file manager at `~/external/quantum-plus/askwell/askwell-test-material`. Drag `tender-one.txt` onto the window and release, type the folder with your own path when asked, and click **Add it**.

**You should see:** a card move to **Queued**, then progress as extraction, chunking and embedding run for real, and settle with no red error text.

### 10. Confirm the document reached `ready` and the question was raised

In the `psql` session:

```sql
SELECT filename, status FROM documents WHERE filename = 'tender-one.txt';
```

**You should see:** one row, `status` = `ready`.

```sql
SELECT subject, question, status FROM clarifications;
```

**You should see:** one row — `subject` = `RFQ`, `question` = `'RFQ' appears throughout. What does it mean?`, `status` = `pending`. Nothing suppressed anything here — this is the ordinary path, unaffected by this ticket, confirming the baseline before the suppression checks that follow.

### 11. Answer it, the way the eventual answer route will

No screen exists to click through for this (see "Where this stops on purpose"). Do what the route will do, directly:

```sql
UPDATE clarifications SET status = 'answered', answer = 'Request for Quotation' WHERE subject = 'RFQ';
INSERT INTO memory (id, subject, fact, origin) VALUES (gen_random_uuid(), 'RFQ', 'Request for Quotation', 'manual');
```

**You should see:** both statements report `UPDATE 1` and `INSERT 0 1`.

```sql
SELECT subject, fact, origin FROM memory WHERE subject = 'RFQ';
```

**You should see:** one row — `RFQ`, `Request for Quotation`, `manual`.

---

## Part B — a second source using the same abbreviation asks nothing

### 12. Write a second file using the same abbreviation

```bash
scripts/dev.sh run python3 - <<'PY'
text = "Please review the RFQ before Monday. The RFQ is attached to this email."
with open("/app/askwell-test-material/tender-two.txt", "w") as f:
    f.write(text + "\n")
print("done")
PY
```

**You should see:** the script print `done`.

### 13. Add it the same way as step 9, and wait for it to settle

### 14. Confirm nothing was asked about `RFQ` for this source

```sql
SELECT count(*) FROM clarifications c
JOIN documents d ON d.source_id = c.source_id
WHERE d.filename = 'tender-two.txt';
```

**You should see:** `0`. This is the ticket's own acceptance criterion — "adding a second source with the same abbreviation asks nothing."

### 15. Confirm the suppression itself was recorded, naming the fact applied

```sql
SELECT payload->>'subject', payload->>'applied_fact', payload->>'trigger'
FROM audit_decisions
WHERE kind = 'clarification_suppressed';
```

**You should see:** one row — `RFQ`, `Request for Quotation`, `abbreviation`. This is the record that lets a user see the fact was applied rather than silently dropped, and it is the audit trail the ticket's own Audit / Logging Requirement asks for.

### 16. Confirm the local suppressed counter

`RaiseResult.suppressed` is not stored as its own table row — it is returned to the caller and logged on the same structured line as `raised`/`inferred`/`dropped`/`capped`. Confirm it in the API logs:

```
podman compose logs api --since 5m | grep clarifications_raised
```

**You should see:** a line for `tender-two.txt`'s source with `suppressed=1`.

---

## Part C — a low-confidence inference still suppresses, but stays visible for review

### 17. Write a third file with a different, fresh abbreviation

```bash
scripts/dev.sh run python3 - <<'PY'
text = "The SOW must be signed. SOW terms apply to both parties. SOW review is pending."
with open("/app/askwell-test-material/tender-three.txt", "w") as f:
    f.write(text + "\n")
print("done")
PY
```

### 18. Before adding it, insert a low-confidence guess for the same subject, as if an earlier ranking had capped it

```sql
INSERT INTO memory (id, subject, fact, origin, confidence)
VALUES (gen_random_uuid(), 'SOW', 'guessed meaning of SOW, unreviewed', 'inferred', 0.3);
```

**You should see:** `INSERT 0 1`.

### 19. Add `tender-three.txt` the same way as step 9, and wait for it to settle

### 20. Confirm the question was suppressed despite the existing fact being only a guess

```sql
SELECT count(*) FROM clarifications c
JOIN documents d ON d.source_id = c.source_id
WHERE d.filename = 'tender-three.txt';
```

**You should see:** `0` — the ticket's own edge case: a low-confidence inference still suppresses the question. Asking about the user's own material twice is the failure being prevented, and that holds even when the existing answer is only Askwell's own guess.

```sql
SELECT subject, fact, origin, confidence FROM memory WHERE subject = 'SOW';
```

**You should see:** the same one row from step 18, unchanged — still `inferred`, still `confidence = 0.300`, still sitting in `memory` for review. Suppressing the question is a different thing from resolving the guess; the guess remains visibly a guess.

---

## Part D — a superseded fact does not resurrect the question, and the current wording is what gets applied

### 21. Write a fourth file with another fresh abbreviation

```bash
scripts/dev.sh run python3 - <<'PY'
text = "The MOU expires in June. MOU renewal is automatic. MOU terms are unchanged."
with open("/app/askwell-test-material/tender-four.txt", "w") as f:
    f.write(text + "\n")
print("done")
PY
```

### 22. Insert a retired fact and a current one that supersedes it

```sql
WITH new_fact AS (
    INSERT INTO memory (id, subject, fact, origin)
    VALUES (gen_random_uuid(), 'MOU', 'Memorandum of Understanding, current wording', 'manual')
    RETURNING id
)
INSERT INTO memory (id, subject, fact, origin, superseded_by)
SELECT gen_random_uuid(), 'MOU', 'a retired guess, wrong', 'inferred', id FROM new_fact;
```

**You should see:** the statement complete with no error (`INSERT 0 1` for the nested insert).

### 23. Add `tender-four.txt` the same way as step 9, and wait for it to settle

### 24. Confirm the question was suppressed using the current wording, not the retired one

```sql
SELECT count(*) FROM clarifications c
JOIN documents d ON d.source_id = c.source_id
WHERE d.filename = 'tender-four.txt';
```

**You should see:** `0`.

```sql
SELECT payload->>'applied_fact' FROM audit_decisions
WHERE kind = 'clarification_suppressed' AND payload->>'subject' = 'MOU';
```

**You should see:** `Memorandum of Understanding, current wording` — never `a retired guess, wrong`. The `superseded_by IS NULL` filter in `_known_facts` is what makes this hold.

---

## Part E — a subject known only in `schema_notes` still suppresses

### 25. Write a fifth file with another fresh abbreviation

```bash
scripts/dev.sh run python3 - <<'PY'
text = "The PIC is responsible for sign-off. PIC approval is required. PIC review follows."
with open("/app/askwell-test-material/tender-five.txt", "w") as f:
    f.write(text + "\n")
print("done")
PY
```

### 26. Insert a `schema_notes` row naming the same subject, unrelated to this source

`schema_notes` is not scoped to a source for lookup purposes — this row can belong to any source at all, including one that has nothing to do with `tender-five.txt`. In the `psql` session, find any existing `source_id` to attach it to:

```sql
SELECT id FROM sources LIMIT 1;
```

Use that id below in place of `<some-source-id>`:

```sql
INSERT INTO schema_notes (id, source_id, table_name, description, origin)
VALUES (gen_random_uuid(), '<some-source-id>', 'PIC', 'Person In Charge', 'user');
```

**You should see:** `INSERT 0 1`.

### 27. Add `tender-five.txt` the same way as step 9, and wait for it to settle

### 28. Confirm the question was suppressed from the `schema_notes` match

```sql
SELECT count(*) FROM clarifications c
JOIN documents d ON d.source_id = c.source_id
WHERE d.filename = 'tender-five.txt';
```

**You should see:** `0`.

```sql
SELECT payload->>'applied_fact' FROM audit_decisions
WHERE kind = 'clarification_suppressed' AND payload->>'subject' = 'PIC';
```

**You should see:** `Person In Charge` — the `schema_notes.description` column, reached because `memory` had nothing for `PIC` and the fallback lookup ran.

---

## Part F — a near-miss subject is not suppressed

### 29. Insert a fact for a subject that is close to, but not the same as, an abbreviation about to appear

```sql
INSERT INTO memory (id, subject, fact, origin) VALUES (gen_random_uuid(), 'POS', 'Point of Sale', 'manual');
```

### 30. Write a file using a different, merely similar-looking token

```bash
scripts/dev.sh run python3 - <<'PY'
text = "The POC is the single contact. POC details are below. POC availability varies."
with open("/app/askwell-test-material/tender-six.txt", "w") as f:
    f.write(text + "\n")
print("done")
PY
```

`POC` and `POS` are different strings — exact-match only, per the ticket's own Assumption, so this must not suppress.

### 31. Add it the same way as step 9, and wait for it to settle

### 32. Confirm `POC` was asked about, not suppressed

```sql
SELECT subject, status FROM clarifications c
JOIN documents d ON d.source_id = c.source_id
WHERE d.filename = 'tender-six.txt';
```

**You should see:** one row — `POC`, `pending`. A near-match subject that is not the same thing must not suppress a real question; false suppression is worse than a duplicate one, and this confirms `_known_facts` never does substring or fuzzy matching.

---

## Part G — a skipped question is not raised again for its own source

This exercises `raise_candidates`'s pre-existing "does this source already have a clarification row" guard (`M3-RAISE-BE-068`), which is what actually makes a skip permanent — this ticket did not need to touch it, but the ticket's own Testing Notes ask for it directly, so it is confirmed here.

### 33. Write a seventh file with one more fresh abbreviation

```bash
scripts/dev.sh run python3 - <<'PY'
text = "The KPI targets reset quarterly. KPI review happens monthly. KPI data is attached."
with open("/app/askwell-test-material/tender-seven.txt", "w") as f:
    f.write(text + "\n")
print("done")
PY
```

### 34. Add it the same way as step 9, and wait for it to settle

### 35. Skip the question the way the eventual skip route will

```sql
UPDATE clarifications SET status = 'skipped' WHERE subject = 'KPI';
```

**You should see:** `UPDATE 1`.

### 36. Add more material with the same abbreviation into the same source

Drag a second file into the same source (use **Add a source** again and point it at the same folder path used for `tender-seven.txt`, or add a file directly beside it and re-nominate the same folder if your source is folder-scoped):

```bash
scripts/dev.sh run python3 - <<'PY'
text = "KPI targets increased again this quarter. New KPI data follows."
with open("/app/askwell-test-material/tender-seven-b.txt", "w") as f:
    f.write(text + "\n")
print("done")
PY
```

Add `tender-seven-b.txt` into the same source as `tender-seven.txt` and wait for it to settle.

### 37. Confirm `KPI` was not asked about again for that source

```sql
SELECT count(*) FROM clarifications c
WHERE c.source_id = (SELECT source_id FROM documents WHERE filename = 'tender-seven.txt');
```

**You should see:** `1` — still just the original, now-skipped `KPI` row. No second row appears for the same source, skipped or otherwise.

---

## Cleanup

```
podman compose down -v
```

Restore `.env` if you changed anything beyond what **Before you start** asked for.

---

## Known gaps

- **No screen renders any of this, and no route answers or skips a question yet.** `docs/ux/clarifications.md`'s whole review screen and issue [#257](https://github.com/Rumeasiyan/askwell/issues/257) (`GET /clarifications`, plus the answer/skip mutation routes) are both open, unrelated to this ticket's scope, and confirmed still open as of this version. This walkthrough writes directly to `clarifications` and `memory` in `psql` to stand in for those routes — do not report the absence of a clickable answer/skip flow as a defect of this ticket.
- **`M3-STORE-BE-076` (a dedicated write-side module for origin/confidence/supersession mechanics) is not built.** The columns this ticket's lookup needs (`memory.subject`/`fact`/`superseded_by`, `schema_notes.table_name`/`column_name`/`description`/`superseded_by`) already exist from the initial schema migration, so Part D and Part E's manual inserts work today, but nothing enforces the shape of a superseding write outside this walkthrough's own hand-built SQL — a future write-side bug in `M3-STORE-BE-076` could violate the invariant this ticket relies on without this test catching it.
- **The "one question, applied to all matching columns" idea from `docs/ux/clarifications.md` §8** is unrelated to this ticket and not built — every subject here is matched and suppressed individually.
- **Analytics event is a log line, not a dashboard.** The ticket's own Analytics Events line ("local counter of suppressed questions") is satisfied by `RaiseResult.suppressed` and the `clarifications_raised` structured log line (step 16) — there is no UI surface showing a running total, and none is expected until the Memory screen (`M3-MEM-FE-083`) exists.
- **Near-synonym subjects are treated as different, by design** (the ticket's own Known Gap) — `POC`/`POS` in Part F demonstrates the mechanism, not a defect; a genuine synonym pair asked twice is expected behaviour, not a bug to file.
