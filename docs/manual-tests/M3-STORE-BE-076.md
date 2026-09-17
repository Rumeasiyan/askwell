# Manual test — M3-STORE-BE-076, memory and schema notes with origin, confidence and supersession

**Ticket:** `M3-STORE-BE-076` — a dedicated write-side module (`askwell.memory`) for two stores: `memory` (general facts) and `schema_notes` (attached to a source, table and column). Both carry origin, confidence, supersession and creation time. A correction supersedes rather than overwrites; an inference is discarded outright if an active user-supplied fact already covers the same subject/position; retrieval orders user-origin before inferred, newer before older.
**Version under test:** `0.3.9`
**Time:** about 45 minutes, plus a first stack build and native inference startup.
**Who can run it:** a browser, a terminal, and `psql` access via `scripts/dev.sh psql`. Two steps use `curl` directly against the API, not the browser — see "Where this stops on purpose" for why.

**What is being checked.** `api/src/askwell/memory.py`: `write_memory_fact`, `correct_memory_fact`, `get_active_memory_facts`, `write_schema_note`, `correct_schema_note`, `get_active_schema_notes`, and the discard/supersession rules each enforces. `api/tests/test_memory.py` is the authoritative test of this module — this walkthrough runs it directly (against a real, disposable database) for everything the running app itself cannot exercise yet, and reads `docs/decisions.md`'s 2026-09-17 entries and `CHANGELOG.md`'s `0.3.8`/`0.3.9` sections, which record why.

**Where this stops on purpose — read this before reporting anything below as a defect.**

`askwell.memory` has almost no caller in the running application yet:

- Answering a clarification (`api/src/askwell/review.py`, `answer_clarification`) writes straight into `memory` with its own hand-rolled `INSERT`, not `write_memory_fact` — this predates this ticket (`M3-REVIEW-BE-072a`) and is filed as issue **#282**, deliberately not rewired here per `AGENTS.md` §4's "touches more than three files, agree first." Practically: answering a clarification through the real UI does produce a correctly-shaped row (origin `clarification`, confidence `1.000`), because `review.py`'s own constant happens to match this module's, but a **second** answer for the same subject will **not** supersede the first the way `write_memory_fact` would — it will sit active alongside it. That is `review.py`'s gap, not this module's; §2 below shows it.
- `write_schema_note` has **no caller anywhere in the app.** Nothing writes an inferred or user schema note today — `schema_notes` is read (`api/src/askwell/clarify.py`, the suppression check) but never written outside this module's own tests and migrations. §3 below seeds rows directly to exercise the store and the delete-source cascade.
- `DELETE /sources/{source_id}` (`api/src/askwell/sources.py`, `delete_source_route`) exists and is what removes schema notes on source deletion, but **no button in the web app calls it.** The Library screen's per-row **Delete** button calls `DELETE /documents/{document_id}` (`M2-DELETE-FE-062`), a different, document-level route. Deleting a whole source is only reachable by calling the API directly — §3 uses `curl` for exactly that one action and names it as a gap rather than pretending a button exists.
- `correct_memory_fact`/`correct_schema_note` and `get_active_memory_facts`/`get_active_schema_notes` are not exposed over HTTP at all.

None of this is a defect in this ticket — the store is scoped to "writing and superseding for both stores," and wiring it into the clarification/schema-inference flows is out of scope (tracked separately). It does mean most of this ticket is verifiable only through its own test suite and direct database inspection, not by clicking. Sections below say which is which.

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

Click **Add a source** in the sidebar, choose that folder, and wait for the **Library** screen to show at least one file as **Ready**. Any small text file works — nothing here depends on its content.

---

## 1. What the real UI still writes correctly (and what it does not)

### 6. Get a pending clarification to answer

If **Clarifications** in the sidebar shows nothing pending, seed one:

```
scripts/dev.sh psql <<'SQL'
SELECT id FROM sources WHERE status = 'ready' LIMIT 1;
SQL
```

Copy the `id` printed, then (substituting it below):

```
scripts/dev.sh psql <<'SQL'
INSERT INTO clarifications (id, source_id, subject, question, evidence, rank, status, asked_at)
VALUES (
  '33333333-3333-3333-3333-333333333331',
  '<source id from above>',
  'test.subject_one',
  'What does subject_one mean?',
  '{"kind":"unavailable","reason":"seeded for M3-STORE-BE-076","current_inference":null}'::jsonb,
  1, 'pending', now()
);
SQL
```

### 7. Answer it through the real screen

Click **Clarifications**. **You should see:** a card for `test.subject_one`. Type `first answer` into its text field and click **Save**.

**You should see:** the card disappears from the pending list (or the count above it decreases by one).

### 8. Confirm the fact it wrote

```
scripts/dev.sh psql <<'SQL'
SELECT subject, fact, origin, confidence, superseded_by FROM memory WHERE subject = 'test.subject_one';
SQL
```

**You should see:** exactly one row — `test.subject_one | first answer | clarification | 1.000 | <null>`. This matches the ticket's own acceptance criterion: answering a clarification writes a fact with origin `clarification` and full confidence.

### 9. Show the gap: a second answer for the same subject does not supersede

Seed a second pending clarification for the *same* subject and answer it too:

```
scripts/dev.sh psql <<'SQL'
INSERT INTO clarifications (id, source_id, subject, question, evidence, rank, status, asked_at)
VALUES (
  '33333333-3333-3333-3333-333333333332',
  '<same source id as step 6>',
  'test.subject_one',
  'What does subject_one really mean?',
  '{"kind":"unavailable","reason":"seeded for M3-STORE-BE-076","current_inference":null}'::jsonb,
  2, 'pending', now()
);
SQL
```

Answer it through the **Clarifications** screen the same way, typing `second answer`.

```
scripts/dev.sh psql <<'SQL'
SELECT fact, origin, superseded_by FROM memory WHERE subject = 'test.subject_one' ORDER BY created_at;
SQL
```

**You should see: two active rows** — `first answer` with `superseded_by` still `<null>`, and `second answer` also with `superseded_by <null>`. Neither points at the other. This is issue **#282**'s gap, not a new defect: `write_memory_fact`, if `review.py` called it, would have retired `first answer` the moment `second answer` was written (that exact behaviour is `test_a_second_user_origin_write_supersedes_not_double_actives` in §2 below). It is expected, documented and out of scope to fix here.

---

## 2. What only the test suite can show: supersession, discard, correction

Everything this ticket actually adds — `correct_memory_fact`, the inference-discard rule, retrieval precedence, the schema-note equivalents — has no route to click through. Run the module's own tests against a real, disposable database:

```
scripts/dev.sh test-db api/tests/test_memory.py -v
```

**You should see:** every test named below reported `PASSED`, nothing skipped:

| Test | What it proves, mapped to the ticket |
| ---- | ------------------------------------ |
| `test_answering_a_clarification_writes_a_full_confidence_user_fact` | AC: clarification answer → origin `clarification`, confidence `1.000` |
| `test_correcting_supersedes_and_the_old_value_stays_readable` | AC: correction supersedes, old value stays readable |
| `test_two_contradicting_user_answers_the_later_supersedes_both_visible` | Edge case: two contradicting user answers, later supersedes, both visible |
| `test_a_second_user_origin_write_supersedes_not_double_actives` | The exact behaviour §1 step 9 showed is *missing* from the real UI path today |
| `test_correcting_a_fact_that_no_longer_exists_raises` | `FactNotFound` on a stale id |
| `test_correcting_an_already_superseded_fact_raises` | Edge case: a fact superseded twice — chain resolves correctly, re-correcting the old one fails rather than forking the chain |
| `test_correcting_an_inferred_fact_is_rejected` | `CannotCorrectInference` — nothing to "correct" about a guess |
| `test_an_inference_never_overwrites_a_user_supplied_fact` | AC: inference never overwrites a user-supplied fact |
| `test_an_inference_for_a_new_subject_is_stored` | An inference is only discarded when it collides, not always |
| `test_retrieval_orders_later_before_earlier_within_the_same_origin` | Retrieval precedence: later over earlier |
| `test_retrieval_orders_user_before_inferred_regardless_of_recency` | Retrieval precedence: user over inferred |
| `test_general_memory_survives_a_deleted_source_and_says_so` | Edge case: a fact whose source no longer exists |
| `test_a_fact_with_no_source_is_not_labelled_as_from_a_deleted_source` | The deleted-source label does not leak onto unrelated facts |
| `test_writing_and_correcting_a_schema_note`, `test_a_second_user_origin_note_supersedes_not_double_actives`, `test_correcting_an_inferred_schema_note_is_rejected` | The schema-note store mirrors every rule above |
| `test_deleting_a_source_removes_its_schema_notes_but_not_general_memory` | AC: deleting a source removes its schema notes and leaves general memory |

If any of these is not `PASSED`, stop — that is a real regression, not a gap.

---

## 3. Delete-source cascade, seen from the database directly

Since nothing writes a schema note in the running app, and nothing in the web UI deletes a whole source, this section seeds both directly and drives the one action (`DELETE /sources/{id}`) only reachable via `curl`.

### 10. Seed a schema note and a source-attributed memory fact

```
scripts/dev.sh psql <<'SQL'
INSERT INTO sources (id, kind, name, status, added_at)
VALUES ('44444444-4444-4444-4444-444444444441', 'file', 'cascade-test-source', 'ready', now());

INSERT INTO schema_notes (id, source_id, table_name, column_name, description, origin, confidence)
VALUES (
  '44444444-4444-4444-4444-444444444442',
  '44444444-4444-4444-4444-444444444441',
  'students', 'st_cd', 'student status code', 'user', 1.0
);

INSERT INTO memory (id, subject, fact, origin, confidence, source_id)
VALUES (
  '44444444-4444-4444-4444-444444444443',
  'test.cascade_subject', 'learned from cascade-test-source', 'clarification', 1.0,
  '44444444-4444-4444-4444-444444444441'
);
SQL
```

### 11. Confirm both are visible before deleting anything

```
scripts/dev.sh psql <<'SQL'
SELECT table_name, column_name, description FROM schema_notes WHERE source_id = '44444444-4444-4444-4444-444444444441';
SELECT subject, fact FROM memory WHERE subject = 'test.cascade_subject';
SQL
```

**You should see:** one `schema_notes` row (`students`, `st_cd`, `student status code`) and one `memory` row (`test.cascade_subject`, `learned from cascade-test-source`).

### 12. Delete the source — the one step with no button, via `curl`

```
curl -X DELETE http://127.0.0.1:8000/sources/44444444-4444-4444-4444-444444444441
```

**You should see:** a JSON body like `{"deleted": true, "source_id": "4444...", "documents_deleted": 0}`.

### 13. Confirm the note is gone and the memory fact survived, labelled

```
scripts/dev.sh psql <<'SQL'
SELECT count(*) FROM schema_notes WHERE source_id = '44444444-4444-4444-4444-444444444441';
SELECT m.subject, m.fact, s.name, s.status, s.deleted_at IS NOT NULL AS source_deleted
FROM memory m JOIN sources s ON s.id = m.source_id
WHERE m.subject = 'test.cascade_subject';
SQL
```

**You should see:** the schema-note count is `0`, and the memory row still reads `test.cascade_subject | learned from cascade-test-source | cascade-test-source | deleted | t` — the joined shape `get_active_memory_facts` returns (`source_name = 'cascade-test-source'`, `source_deleted = true`), confirmed here as the raw join since no screen renders it yet.

### 14. Clean up

```
scripts/dev.sh psql <<'SQL'
DELETE FROM clarifications WHERE subject = 'test.subject_one';
DELETE FROM memory WHERE subject IN ('test.subject_one', 'test.cascade_subject');
SQL
```

---

## Known gaps

- **Answering the same subject twice through the real UI does not supersede** (§1 step 9) — `review.py`'s `answer_clarification` bypasses `write_memory_fact` entirely. Filed as issue **#282**; deliberately not fixed by this ticket.
- **No caller writes a `schema_notes` row anywhere in the app.** `write_schema_note` exists and is fully tested, but there is no inference pipeline or UI action that produces a schema note today. §3 exercises the store only via seeded rows.
- **No button deletes a whole source.** `DELETE /sources/{id}` exists and is what this ticket's "deleting a source" acceptance criterion depends on, but it is reachable only via direct API call, never through the Library screen (which deletes individual documents, a different route).
- **`correct_memory_fact`, `correct_schema_note`, `get_active_memory_facts`, `get_active_schema_notes` are not exposed over HTTP.** Verified here only through `test-db` and raw SQL.
- **No memory screen.** `M3-MEM-FE-083`, not built — there is nowhere in the app to see history, a struck-through old value, or a "learned from a deleted source" label rendered as UI.
- **Import/export across machines is not v1** — out of scope per the ticket itself.
