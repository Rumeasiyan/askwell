# Manual test — M3-REVIEW-BE-072a, the clarifications API

**Ticket:** `M3-REVIEW-BE-072a` — expose pending clarifications over HTTP: `GET /clarifications` grouped by source with per-group and total counts, `POST /clarifications/{id}/answer` writing a `memory` row (`origin = 'clarification'`) and a decisions record in one transaction, `POST /clarifications/{id}/skip` writing neither. All three require a session.
**Version under test:** `0.3.4`
**Time:** about 45–60 minutes, plus a first stack build and native inference startup.
**Who can run it:** a terminal, `curl`, and `psql` access via `scripts/dev.sh psql`.

**What is being checked.** `api/src/askwell/review.py`, registered by `register_review` in `api/src/askwell/app.py`. `list_pending` runs one SQL query ordered by `sources.added_at DESC, clarifications.rank ASC NULLS LAST, clarifications.asked_at ASC` and folds adjacent rows into groups in Python. `answer_clarification` and `skip_clarification` both lock the target row with `SELECT ... FOR UPDATE` before checking its status.

**Where this stops on purpose.** No screen calls this API yet — `M3-REVIEW-FE-072`, `-073`, `-074` are out of scope for this ticket and unbuilt as of this version (confirmed by searching `web/` for `/clarifications`). Steps 1–9 below add a real source through the running app, by clicking, exactly as a user would; from there this walkthrough calls the endpoints directly with `curl`, the same way `M3-RAISE-BE-069`'s manual test used `psql` directly for a surface with no UI path yet. This is not a shortcut around "click, don't call an endpoint" — there is no button to click for this ticket's own surface.

---

## Before you start

```
cd ~/external/quantum-plus/askwell
mkdir -p askwell-test-material
cp -n .env.example .env
```

Open `.env`. Find `ASKWELL_ROOTS_MOUNT=` and set it to the folder above, with your own path:

```
ASKWELL_ROOTS_MOUNT=/home/you/external/quantum-plus/askwell/askwell-test-material
```

Find `POSTGRES_APP_PASSWORD` and put any word after the `=` if it is blank. Find `ASKWELL_EMBEDDING_MODEL_PATH` and confirm it points at a model that actually exists on this machine — a document only reaches `status = 'ready'` (the point at which clarifications get raised) once it is chunked and embedded.

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

**You should see:** lint, format, typecheck and test stages finish without red error text, `test_review.py` and `test_review_api.py` included in the total.

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

Leave this running in its own terminal. Wait for it to report the embedding role `ready` on its configured port.

### 6. Open the app and let it hand you a session

Open a browser at:

```
http://127.0.0.1:8000
```

**You should see:** the Askwell shell load with no prompt to sign in — the first page load silently receives a session cookie (`docs/architecture.md`, `api/src/askwell/middleware.py`).

### 7. Nominate the test folder

Click **Settings** in the left strip, scroll to **Folders Askwell may read**, type your own path into the **Nominate a folder** field —

```
/home/you/external/quantum-plus/askwell/askwell-test-material
```

— and click **Nominate**.

**You should see:** a box appear showing that path, marked **Readable**.

### 8. Write two small files that each raise one clarification

```bash
scripts/dev.sh run python3 - <<'PY'
import os
os.makedirs("/app/askwell-test-material/contracts", exist_ok=True)
os.makedirs("/app/askwell-test-material/invoices", exist_ok=True)
with open("/app/askwell-test-material/contracts/agreement.txt", "w") as f:
    f.write("The SLA applies to all vendors. The SLA renews annually. The SLA covers uptime.\n")
with open("/app/askwell-test-material/invoices/statement.txt", "w") as f:
    f.write("The PO covers Q1 spend. The PO was approved. The PO number is on file.\n")
print("done")
PY
```

**You should see:** the script print `done`.

### 9. Add each folder as its own source, by clicking through the app

Click **Ask** in the left strip.

**You should see:** the "Ask your own material" page's first-run, empty-corpus state — no chat box, a statement that no documents are indexed yet, and an **Add a source** button.

Click **Add a source**. Point it at `.../askwell-test-material/contracts` and click **Add it**. Wait for it to settle (no red error text). Repeat: click **Add a source** again, point it at `.../askwell-test-material/invoices`, click **Add it**, and wait for it to settle.

**You should see:** both sources listed with no error state, each showing its file processed.

### 10. Confirm both documents reached `ready` and each raised one clarification

```
scripts/dev.sh psql
```

```sql
SELECT filename, status FROM documents ORDER BY filename;
```

**You should see:** two rows, both `status = 'ready'`.

```sql
SELECT s.name, c.subject, c.status FROM clarifications c
JOIN sources s ON s.id = c.source_id ORDER BY s.added_at DESC;
```

**You should see:** two rows, both `status = 'pending'` — one with subject `SLA` under the `contracts` source, one with subject `PO` under the `invoices` source. Keep this `psql` session open.

---

## Part A — `GET /clarifications`: grouped, counted, newest source first

### 11. Fetch the list, carrying the session cookie your browser holds

Open a second terminal. Export the cookie value shown in your browser's dev tools (Application → Cookies → the `askwell_session` cookie at `127.0.0.1:8000`):

```bash
curl -s --cookie "askwell_session=<paste the value>" http://127.0.0.1:8000/clarifications | python3 -m json.tool
```

**You should see:** JSON with two groups. The `invoices` group (added second, so newest) appears first, then `contracts`. Each group carries `source_id`, `source_name`, `count: 1`, and an `items` array of one object with `id`, `subject`, `question`, `options`, and `evidence` populated (not `null`). `total` is `2`.

### 12. Confirm a request with no cookie is refused, not silently allowed

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/clarifications
```

**You should see:** `401`.

---

## Part B — answering writes `memory` and a decisions record, together

### 13. Note the `contracts` item's id from step 11's output, then answer it

```bash
curl -s --cookie "askwell_session=<paste the value>" \
  -X POST http://127.0.0.1:8000/clarifications/<contracts item id>/answer \
  -H "Content-Type: application/json" \
  -d '{"answer": "SLA means Service Level Agreement."}' | python3 -m json.tool
```

**You should see:** `{"id": "<same id>", "status": "answered", "memory_id": "<a uuid>"}`.

### 14. Confirm the memory row and the decisions record both exist

In the `psql` session:

```sql
SELECT subject, fact, origin, confidence FROM memory WHERE subject = 'SLA';
```

**You should see:** one row — `fact = 'SLA means Service Level Agreement.'`, `origin = 'clarification'`, `confidence = 1.000`.

```sql
SELECT kind, payload FROM audit_decisions WHERE kind = 'clarification_answered';
```

**You should see:** one row, `payload` containing the clarification id, subject `SLA`, and the matching `memory_id`.

### 15. Confirm it no longer appears in the pending list

```bash
curl -s --cookie "askwell_session=<paste the value>" http://127.0.0.1:8000/clarifications | python3 -m json.tool
```

**You should see:** only the `invoices` group now, `total: 1`. The `contracts` group is gone entirely, not shown as an empty group — the acceptance criterion's edge case for a source with nothing pending.

### 16. Confirm answering it again is refused, not written twice

```bash
curl -s -o /dev/null -w "%{http_code}\n" --cookie "askwell_session=<paste the value>" \
  -X POST http://127.0.0.1:8000/clarifications/<contracts item id>/answer \
  -H "Content-Type: application/json" -d '{"answer": "second try"}'
```

**You should see:** `409`.

```sql
SELECT count(*) FROM memory WHERE subject = 'SLA';
```

**You should see:** `1` — still one row, not two.

---

## Part C — skipping writes no memory, and is not final

### 17. Skip the `invoices` item (note its id from step 15's output)

```bash
curl -s --cookie "askwell_session=<paste the value>" \
  -X POST http://127.0.0.1:8000/clarifications/<invoices item id>/skip | python3 -m json.tool
```

**You should see:** `{"id": "<same id>", "status": "skipped"}`.

### 18. Confirm no memory row was written for it

```sql
SELECT count(*) FROM memory WHERE subject = 'PO';
```

**You should see:** `0`.

### 19. Confirm the list is now empty

```bash
curl -s --cookie "askwell_session=<paste the value>" http://127.0.0.1:8000/clarifications | python3 -m json.tool
```

**You should see:** `{"groups": [], "total": 0}`.

### 20. Confirm a skipped item can still be answered — skipping is not final

```bash
curl -s --cookie "askwell_session=<paste the value>" \
  -X POST http://127.0.0.1:8000/clarifications/<invoices item id>/answer \
  -H "Content-Type: application/json" \
  -d '{"answer": "PO means Purchase Order."}' | python3 -m json.tool
```

**You should see:** `{"id": "<same id>", "status": "answered", "memory_id": "<a uuid>"}` — no error, and afterward:

```sql
SELECT subject, origin FROM memory WHERE subject = 'PO';
```

**You should see:** one row, `origin = 'clarification'`.

---

## Part D — a deleted source's clarifications disappear from the list

### 21. Write and add a third source with its own clarification

```bash
scripts/dev.sh run python3 - <<'PY'
import os
os.makedirs("/app/askwell-test-material/memo", exist_ok=True)
with open("/app/askwell-test-material/memo/note.txt", "w") as f:
    f.write("The MOU applies here. The MOU was signed. The MOU expires next year.\n")
print("done")
PY
```

Add it the same way as step 9, pointed at `.../askwell-test-material/memo`, and wait for it to settle.

### 22. Confirm it shows up pending

```bash
curl -s --cookie "askwell_session=<paste the value>" http://127.0.0.1:8000/clarifications | python3 -m json.tool
```

**You should see:** one group, `source_name` for the `memo` source, `count: 1`, `total: 1`.

### 23. Delete that source through the app

Click **Sources** in the left strip (or wherever the source list is reachable from **Settings**), find the `memo` source, and click its delete action. Confirm the delete.

**You should see:** the source removed from the visible list.

### 24. Confirm its clarification no longer appears, even though the row still exists

```bash
curl -s --cookie "askwell_session=<paste the value>" http://127.0.0.1:8000/clarifications | python3 -m json.tool
```

**You should see:** `{"groups": [], "total": 0}`.

```sql
SELECT s.status, c.status FROM clarifications c
JOIN sources s ON s.id = c.source_id
JOIN documents d ON d.source_id = s.id AND d.filename = 'note.txt';
```

**You should see:** one row, source `status = 'deleted'`, clarification `status = 'pending'` — the row survives (a soft delete), it is simply excluded from the join.

---

## Part E — malformed input is rejected before it reaches the database

### 25. A non-UUID id

```bash
curl -s -o /dev/null -w "%{http_code}\n" --cookie "askwell_session=<paste the value>" \
  -X POST http://127.0.0.1:8000/clarifications/not-a-uuid/skip
```

**You should see:** `422`.

### 26. An empty answer

```bash
curl -s -o /dev/null -w "%{http_code}\n" --cookie "askwell_session=<paste the value>" \
  -X POST http://127.0.0.1:8000/clarifications/11111111-1111-1111-1111-111111111111/answer \
  -H "Content-Type: application/json" -d '{"answer": ""}'
```

**You should see:** `422`.

### 27. A well-formed id that does not exist

```bash
curl -s -o /dev/null -w "%{http_code}\n" --cookie "askwell_session=<paste the value>" \
  -X POST http://127.0.0.1:8000/clarifications/11111111-1111-1111-1111-111111111111/skip
```

**You should see:** `404`.

---

## Cleanup

```
podman compose down -v
```

Restore `.env` if you changed anything beyond what **Before you start** asked for.

---

## Known gaps

- **No screen renders any of this.** `M3-REVIEW-FE-072`, `-073`, `-074` are unbuilt as of this version — this walkthrough verifies the data and routes those screens will read and write, not any UI on top of them. Do not report the absence of a clarifications screen as a defect of this ticket.
- **Undo and skip-all are not exercised**, by design — `M3-REVIEW-FE-074` owns that interaction; this ticket exposes only single-item answer and skip.
- **Re-processing after an answer is not exercised.** `M3-APPLY-ING-080` (re-running whatever depended on an answered clarification) is out of scope for this ticket; step 14 confirms the `memory` row and decisions record land, not that anything downstream reacts to them yet.
- **Pagination is not exercised** — deliberately absent from the API, since the queue is capped at five per source by `M3-RAISE-BE-069`, so this was never expected to need it.
- **Concurrent double-answer is not exercised.** `review.py`'s own docstring notes the `SELECT ... FOR UPDATE` lock exists to prevent two simultaneous requests from both writing a fact for one answer; this walkthrough is sequential and confirms the *sequential* refusal (step 16), not the concurrent race itself.
