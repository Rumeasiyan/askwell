# Manual test — M3-APPLY-ING-080, re-process what depends on an answered clarification

**Ticket:** `M3-APPLY-ING-080` — answering a clarification queues re-processing of what depends
on it: re-embedding affected chunks, promoting a matching inferred schema note to the user's
answer, and dismissing a duplicate still-pending clarification asking about the same subject.
The source stays queryable throughout; per-item progress and a visible retry on failure.
**Version under test:** `0.3.12`
**Time:** about 40 minutes, on top of an already-running stack.
**Who can run it:** a browser, and `psql` access via `scripts/dev.sh psql`.

**What is being checked.** `api/src/askwell/reapply.py` (dependency resolution, `enqueue`,
`run_job`, `retry_failed`, `cancel_pending_for_clarification`), the two new routes in
`api/src/askwell/review.py` (`GET /reapply-jobs/{id}`, `POST /reapply-jobs/{id}/retry`), and
`askwell.worker.reapply_job`/`startup` picking the job up.

**No native `llama.cpp` process runs in this environment** (the same limitation
`M1-ASK-API-038`'s and `M1-INDEX-ING-032`'s manual tests record), so a `chunk` item — the one
kind of re-processing work that calls the embedding model — fails here with
`InferenceUnavailable` rather than succeeding. That is not a gap in this walkthrough; it is the
exact "failures are visible with a retry" path the ticket's Acceptance Criteria names, exercised
for real rather than assumed. The `schema_note` and `conflict` kinds need no model and are
verified completing end to end.

**Real dependency-resolution triggers (an abbreviation Askwell noticed on its own, or two
documents it decided disagree) are slow to set up by hand** — `M3-REVIEW-FE-074`'s manual test
made the same call for the surface this one builds on. This walkthrough seeds the clarification
queue directly with `psql`, then does everything downstream of "a pending question exists" by
clicking, the way a person actually would.

---

## Part 1 — automated suite, read the output

```
scripts/dev.sh check
scripts/dev.sh test-db
```

**What you should see:** `check` passes with no network (`--network=none`) — lint, format,
typecheck, `test`. `test-db` includes `api/tests/test_reapply.py`: 18 cases against a real
Postgres — dependency resolution for all three kinds, de-duplication across two overlapping
answers, `run_job` per item kind, retry-to-exhaustion with the failure left visible, `resume`,
and undo's cancellation. At the time this was written: `test` 529 passed / 1 skipped, `test-db`
263+ passed including the 18 new cases.

---

## Part 2 — cold start, seed a clarification, watch it re-process

### Cold start

1. Bring the stack up:

   ```bash
   podman compose up -d
   ```

2. Open `http://localhost:3000` (or the port `scripts/dev.sh` prints) in a browser.

   **You should see:** the Ask screen, with the left rail showing **Ask**, **Library**,
   **Clarifications**, **Memory**, **Settings**. On a genuinely empty install you land on the
   welcome screen first — click through it, it does not gate anything below.

3. Click **Clarifications** in the left rail.

   **You should see:** "Nothing to clarify. Askwell asks when it finds something it can't work
   out — an unlabelled column, a date format, two documents that disagree." (or a list left over
   from earlier testing — either way, continue).

### Seed a source, a document, a chunk, an inferred schema note, a duplicate clarification, and the clarification that answers all of them

This is the fixture this ticket's own re-processing acts on: one source with one live document
and one chunk of real content (so a `chunk` item exists to fail against the missing model), one
*inferred* schema note on a column named `bal_cd` (so a `schema_note` item exists to promote),
and a second, independent `pending` clarification asking about the same subject from a different
source (so a `conflict` item exists to dismiss).

```bash
scripts/dev.sh psql <<'SQL'
INSERT INTO sources (id, kind, name, status, added_at) VALUES
  ('55555555-5555-5555-5555-555555555551', 'file', 'ledger', 'ready', now()),
  ('55555555-5555-5555-5555-555555555552', 'file', 'ledger-copy', 'ready', now())
ON CONFLICT (id) DO NOTHING;

INSERT INTO documents (id, source_id, filename, path, sha256, status) VALUES
  ('66666666-6666-6666-6666-666666666661', '55555555-5555-5555-5555-555555555551',
   'balances.csv', '/tmp/balances.csv', md5('balances'), 'ready')
ON CONFLICT (id) DO NOTHING;

INSERT INTO chunks (id, document_id, ordinal, content) VALUES
  ('77777777-7777-7777-7777-777777777771', '66666666-6666-6666-6666-666666666661',
   0, 'bal_cd,amount' || chr(10) || 'A,1024.50')
ON CONFLICT (id) DO NOTHING;

INSERT INTO schema_notes (id, source_id, table_name, column_name, description, origin, confidence) VALUES
  ('88888888-8888-8888-8888-888888888881', '55555555-5555-5555-5555-555555555551',
   'balances', 'bal_cd', 'possibly a balance code', 'inferred', 0.4)
ON CONFLICT (id) DO NOTHING;

INSERT INTO clarifications (id, source_id, subject, question, options, evidence, rank, status, asked_at) VALUES
  ('99999999-9999-9999-9999-999999999991', '55555555-5555-5555-5555-555555555552',
   'bal_cd', 'What does bal_cd mean, from the copy?', NULL,
   '{"kind":"unavailable","reason":"no locatable passage for bal_cd","current_inference":null}'::jsonb,
   1, 'pending', now()),
  ('99999999-9999-9999-9999-999999999992', '55555555-5555-5555-5555-555555555551',
   'bal_cd', 'What does bal_cd mean?', NULL,
   '{"kind":"column_distribution","row_count":900,"values":[{"value":"A","count":900}],"remainder_count":0,"current_inference":"balance code"}'::jsonb,
   1, 'pending', now())
ON CONFLICT (id) DO NOTHING;
SQL
```

Reload the Clarifications page.

**You should see:** a **ledger** group with 1 item (`bal_cd`, prefilled `balance code`) and a
**ledger-copy** group with 1 item, 2 total at the top, a **Clarifications** badge reading `2` in
the left rail.

### 1. Answer the primary clarification

On the **ledger** group, find the `bal_cd` card. Leave the prefilled `balance code` as-is and
click **Save**.

**You should see:** the card's form is replaced by a confirmation reading **"Saved. Re-reading 1
document."** with an **Undo (10s)** button counting down.

### 2. The re-processing job exists and names what it is re-reading

The UI does not currently render re-processing progress (see **Known gaps**), so read this back
from the database — the record `GET /reapply-jobs/{id}` itself reads:

```bash
scripts/dev.sh psql -c \
  "SELECT id, subject, status, total_items FROM reapply_jobs WHERE subject = 'bal_cd';"
```

**You should see:** one row, `status` either `queued` or already `running`/`failed`,
`total_items = 2` — one `chunk` item (the `balances.csv` row) and one item covering either the
inferred schema note or the duplicate clarification, whichever the worker reached first; both
land inside the same job since `resolve_dependencies` found both from the one answer.

```bash
scripts/dev.sh psql -c \
  "SELECT kind, label, status, error FROM reapply_items ri JOIN reapply_jobs rj ON rj.id = ri.job_id WHERE rj.subject = 'bal_cd' ORDER BY kind;"
```

**You should see:** three items — `chunk` / `balances.csv`, `conflict` / naming the other
source, `schema_note` / `balances.bal_cd`.

### 3. The chunk item fails visibly, with its cause named — and the source stays queryable

Wait a few seconds for the worker to run the job (linear retry with backoff means the `chunk`
item takes up to about 12 seconds — three attempts at `2s`, `4s`, `6s` — before it is marked
`failed`), then re-run the item query.

**You should see:** the `chunk` item's `status = 'failed'`, its `error` naming
`InferenceUnavailable` (the same failure `M1-INDEX-ING-032`'s manual test produces for
embedding with no model running) — never silently dropped, never retried forever. The
`schema_note` and `conflict` items need no model, so both show `status = 'done'`.

While this is happening, go back to the Ask screen and ask any question.

**You should see:** the Ask screen answers (or abstains) normally — nothing about the
in-progress re-processing job blocks or slows a question, and `balances.csv` is not shown as
unavailable anywhere in the library or search.

### 4. The schema note was actually promoted, not just marked done

```bash
scripts/dev.sh psql -c \
  "SELECT table_name, column_name, description, origin, superseded_by IS NOT NULL AS superseded \
   FROM schema_notes WHERE table_name = 'balances' ORDER BY origin;"
```

**You should see:** two rows — the original `inferred` row now `superseded = true`, and a new
`origin = 'user'` row with `description = 'balance code'` (the answer text) and
`superseded = false`. Re-processing changed what Askwell actually knows, not just a job's
bookkeeping.

### 5. The duplicate clarification was dismissed, not left pending

```bash
scripts/dev.sh psql -c \
  "SELECT status FROM clarifications WHERE id = '99999999-9999-9999-9999-999999999991';"
```

**You should see:** `status = 'dismissed'`. Reload the Clarifications page — the
**ledger-copy** group is gone; the queue badge, which read `2` before step 1, now reads `0` and
disappears (the primary item cleared on its own 10-second timer per `M3-REVIEW-FE-074`, and this
one was dismissed as a side effect of answering the other).

### 6. The failed chunk item can be retried, and retrying actually re-runs it

```bash
JOB=$(scripts/dev.sh psql -tA -c "SELECT id FROM reapply_jobs WHERE subject = 'bal_cd';" | tr -d '[:space:]')
curl -s -X POST "http://127.0.0.1:8000/reapply-jobs/$JOB/retry"
```

**What you should see:** `{"id":"<job>","requeued":1}`. Re-check the items after a few seconds:

```bash
scripts/dev.sh psql -c \
  "SELECT kind, status, attempts, error FROM reapply_items WHERE job_id = '$JOB' AND kind = 'chunk';"
```

**You should see:** `attempts` reset then climbing again, and `status = 'failed'` once more with
the same `InferenceUnavailable` cause — a real retry against a real (still down) dependency, not
a no-op button.

### 7. Undo during re-processing cancels what has not run yet

Seed one more clarification and answer it, this time undoing within the window before the
worker can finish:

```bash
scripts/dev.sh psql <<'SQL'
INSERT INTO clarifications (id, source_id, subject, question, options, evidence, rank, status, asked_at) VALUES
  ('99999999-9999-9999-9999-999999999993', '55555555-5555-5555-5555-555555555551',
   'ttl_cd', 'What does ttl_cd mean?', NULL,
   '{"kind":"unavailable","reason":"no locatable passage for ttl_cd","current_inference":null}'::jsonb,
   2, 'pending', now());
INSERT INTO chunks (id, document_id, ordinal, content) VALUES
  ('77777777-7777-7777-7777-777777777772', '66666666-6666-6666-6666-666666666661',
   1, 'ttl_cd' || chr(10) || 'T');
SQL
```

Reload Clarifications, answer `ttl_cd` with any text, then within the 10-second Undo window
click **Undo**.

**You should see:** the card returns to its editable state and stays in the list (per
`M3-REVIEW-FE-074`'s own undo behaviour).

```bash
scripts/dev.sh psql -c \
  "SELECT ri.status, ri.error FROM reapply_items ri JOIN reapply_jobs rj ON rj.id = ri.job_id \
   WHERE rj.subject = 'ttl_cd';"
```

**You should see:** the item's `status = 'failed'`, `error` reading
`cancelled: answer undone` — the pending `chunk` item was cancelled outright rather than left
to run against a fact `undo_answer` had already deleted.

### 8. Clean up the rows this created

```bash
scripts/dev.sh psql -c \
  "TRUNCATE reapply_items, reapply_jobs, clarifications, schema_notes, chunks, documents, sources, memory, audit_decisions CASCADE;"
```

---

## Known gaps

- **No UI surface for re-processing progress.** `docs/ux/clarifications.md` §5's "Answered,
  re-processing … Per-item progress" and the equivalent state in `docs/ux/memory.md` §5 are not
  built. `web/components/clarifications/clarifications-screen.tsx` shows the one-time
  `savedConfirmation` toast (`"Saved. Re-reading N documents."`) and nothing further — there is
  no polling of `GET /reapply-jobs/{id}` anywhere in `web/`, and no retry button wired to
  `POST /reapply-jobs/{id}/retry`. Both routes exist and were exercised directly above; the
  frontend for them is not part of this ticket's stated scope (`phase:2`, backend) and is not
  reported as a defect here.
- **A `chunk` item cannot be verified succeeding in this environment**, only failing correctly
  — there is no running inference model. `M1-INDEX-ING-032`'s Part B (running `scripts/dev.sh
  inference` with a real embedding model up) covers the same call, `InferenceClient.embed`; a
  future run with the model up would additionally confirm `chunks.embedding` actually changes
  value, which this walkthrough could not check.
- **Dependency resolution is approximate on purpose**, per the ticket's own Assumption: every
  chunk of an affected document is queued, not a text-matched subset, and a `schema_note`/
  `conflict` match is exact-subject-name only. This walkthrough's fixture was built to land in
  exactly one document and one schema position, so it does not exercise the "answer affecting
  thousands of chunks" edge case — `test_reapply.py`'s automated suite covers de-duplication
  under overlap, not scale.
