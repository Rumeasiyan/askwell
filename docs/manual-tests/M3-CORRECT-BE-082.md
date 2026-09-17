# Manual test — M3-CORRECT-BE-082, one correction path for chip and memory screen

**Ticket:** `M3-CORRECT-BE-082` — a single backend path (`correct_memory_fact`/`correct_schema_note`/`delete_memory_fact`/`delete_schema_note` in `api/src/askwell/memory.py`) used by both the answer-chip correction and the memory screen, whichever gets built first: supersede rather than overwrite, queue re-processing, return an affected-material summary, write a decisions record. Deletion shares the same shape, minus the new fact.
**Version under test:** `0.3.13`
**Time:** about 30 minutes, plus a first stack build and native inference startup if this is a clean machine.
**Who can run it:** a browser, a terminal, and `scripts/dev.sh psql` / `scripts/dev.sh shell`. There is no `curl`-reachable step in this document at all — see "Where this stops on purpose" for why that is worse than `M3-STORE-BE-076`'s manual test, not the same.

**What is being checked.** The row lock (`FOR UPDATE`) that serialises two near-simultaneous corrections of the same fact, the same-value no-op (`Reprocessing(changed=False)`, nothing written, nothing queued), a real change queuing a `reapply_jobs` row and returning a named `Reprocessing` summary, deletion queuing the same shape without a new fact, correcting an already-deleted fact raising `FactNotFound`, and the ticket's own example — a fact corrected twice from two different callers leaving a clean three-value chain. `api/tests/test_memory.py` is the authoritative test of this; `docs/decisions.md`'s 2026-09-17 `M3-CORRECT-BE-082` entry records why it was built as an extension of the existing store functions rather than a new layer.

**Where this stops on purpose — read this before reporting anything below as a defect.**

Both of this ticket's own callers are still open tickets:

- **`M3-CORRECT-FE-081`** (the chip in an answer) is not built. There is no UI control anywhere in the running app that calls `correct_memory_fact`.
- **`M3-MEM-FE-083`/`-084`** (the memory screen) is not built either — this is the same gap `M3-STORE-BE-076`'s manual test already named, and it still holds.
- `correct_memory_fact`, `correct_schema_note`, `delete_memory_fact`, `delete_schema_note` are **not exposed over HTTP** — no route in `api/src/askwell/app.py` reaches any of them. `M3-STORE-BE-076`'s manual test could still reach a `DELETE /sources/{id}` route with `curl` for one step; this ticket has no equivalent route at all, for any of its four functions.
- `write_memory_fact`/`write_schema_note` (the functions this ticket does **not** touch) are exactly as reachable, or unreachable, as `M3-STORE-BE-076`'s manual test already described: answering a clarification through the real **Clarifications** screen still writes a `memory` row correctly, and nothing in the running app writes a `schema_notes` row.

None of this is a defect in this ticket — its own Out of Scope line is "the interfaces themselves." It does mean this document cannot walk a person through a screen to exercise anything this ticket actually built. What follows opens the real app to establish real state through the one path that does exist (answering a clarification), then drives the new correction path itself from a Python shell inside the running `api` container against that same real, running database — not a throwaway test database — so what gets inspected afterward is the actual effect on the actual app's data.

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

Note the source's name as shown in the Library screen; you will match it against a database row in step 7.

---

## 1. Establish a real fact through the real screen

### 6. Answer a clarification to get a real, source-attributed fact

If **Clarifications** in the sidebar shows nothing pending, seed one — substitute the source id you find here:

```
scripts/dev.sh psql <<'SQL'
SELECT id, name FROM sources WHERE status = 'ready' LIMIT 1;
SQL
```

```
scripts/dev.sh psql <<'SQL'
INSERT INTO clarifications (id, source_id, subject, question, evidence, rank, status, asked_at)
VALUES (
  '55555555-5555-5555-5555-555555555551',
  '<source id from above>',
  'test.correction_subject',
  'What does correction_subject mean?',
  '{"kind":"unavailable","reason":"seeded for M3-CORRECT-BE-082","current_inference":null}'::jsonb,
  1, 'pending', now()
);
SQL
```

Click **Clarifications** in the sidebar. **You should see:** a card for `test.correction_subject`. Type `thirty days` into its text field and click **Save**.

**You should see:** the card disappears from the pending list.

### 7. Confirm the fact and note its id

```
scripts/dev.sh psql <<'SQL'
SELECT id, subject, fact, origin, confidence, source_id FROM memory WHERE subject = 'test.correction_subject';
SQL
```

**You should see:** exactly one row — `test.correction_subject | thirty days | clarification | 1.000 | <the source id from step 6>`. Copy the printed `id`; it is `<fact_id>` for every step below.

---

## 2. Drive the correction path itself, against this same real fact

There is no button anywhere in the app for what happens next, so this runs inside the running `api` container's own Python, against the same database the app you just used is reading from — not a disposable test database.

### 8. Open a Python shell inside the running API container

```
scripts/dev.sh shell
python
```

Inside that Python shell:

```python
import asyncio, uuid
from askwell.db.engine import session_scope
from askwell.memory import correct_memory_fact, delete_memory_fact, FactNotFound

FACT_ID = uuid.UUID("<fact_id from step 7>")

async def correct_from_chip():
    async with session_scope() as session:
        outcome = await correct_memory_fact(session, fact_id=FACT_ID, fact="thirty days")
        print("same-value:", outcome)
        await session.commit()

asyncio.run(correct_from_chip())
```

**You should see:** printed output whose `reprocessing` field reads `changed=False`, `count=0`, and whose `reapply_job_id` is `None` — correcting to the identical value you already have is a no-op.

```
scripts/dev.sh psql <<'SQL'
SELECT count(*) FROM memory WHERE subject = 'test.correction_subject';
SELECT count(*) FROM reapply_jobs;
SELECT kind FROM audit_decisions ORDER BY occurred_at;
SQL
```

**You should see:** still exactly one `memory` row for the subject, zero `reapply_jobs` rows, and the decisions log showing only `memory_written` from step 6 — nothing new was recorded for a no-op.

### 9. A real correction, standing in for the chip

Back in the same Python shell:

```python
async def correct_for_real():
    async with session_scope() as session:
        outcome = await correct_memory_fact(session, fact_id=FACT_ID, fact="forty-five days")
        print("from chip:", outcome)
        await session.commit()
        return outcome.fact_id

new_fact_id = asyncio.run(correct_for_real())
print(new_fact_id)
```

**You should see:** `reprocessing.changed` is `True` and `reapply_job_id` is not `None` if the seeded source has at least one ready document with a chunk (see the note below if it does not); note the printed `new_fact_id`.

> If your test folder's only document has not finished chunking, or the source has no live chunks, `reprocessing.count` will correctly be `0` and `reapply_job_id` will be `None` — a sourceless or chunkless subject genuinely has nothing to re-process, and that is `test_correcting_a_sourceless_fact_has_nothing_to_reprocess`'s own case, not a bug in this walkthrough.

```
scripts/dev.sh psql <<'SQL'
SELECT id, fact, superseded_by FROM memory WHERE subject = 'test.correction_subject' ORDER BY created_at;
SELECT id, subject, source_id, memory_id, status, total_items FROM reapply_jobs ORDER BY created_at;
SQL
```

**You should see:** two rows in `memory` — the original now carrying `superseded_by` pointing at `new_fact_id`, and `new_fact_id` itself active with `superseded_by <null>` and `fact = 'forty-five days'`. If reprocessing queued, one `reapply_jobs` row naming `test.correction_subject`, the source id from step 6, and `memory_id = new_fact_id`.

### 10. A second correction of the same fact, standing in for the memory screen

This is the ticket's own Real-World Example — the same fact corrected a second time, from what stands in for a different caller:

```python
async def correct_again():
    async with session_scope() as session:
        outcome = await correct_memory_fact(session, fact_id=new_fact_id, fact="sixty days")
        print("from memory screen:", outcome)
        await session.commit()

asyncio.run(correct_again())
```

```
scripts/dev.sh psql <<'SQL'
SELECT id, fact, superseded_by FROM memory WHERE subject = 'test.correction_subject' ORDER BY created_at;
SQL
```

**You should see: three rows, forming a clean chain** — `thirty days` points at the second row's id, that second row (`forty-five days`) points at the third, and the third (`sixty days`) has `superseded_by <null>`. Exactly one active row for the subject. This is what "correcting the same fact twice from different screens shows three values in order" means today: the same function, called twice, produces the chain the finished screens will later trigger by the same route.

### 11. Correcting an already-deleted fact is refused

Substitute the id from step 10's third row (`sixty days`, the currently active one) for `<active id from step 10>`:

```python
ACTIVE_ID = uuid.UUID("<active id from step 10>")

async def delete_and_retry():
    async with session_scope() as session:
        outcome = await delete_memory_fact(session, fact_id=ACTIVE_ID)
        print("deleted:", outcome)
        await session.commit()
    async with session_scope() as session:
        try:
            await correct_memory_fact(session, fact_id=ACTIVE_ID, fact="anything")
        except FactNotFound as error:
            print("refused, as expected:", error)
        else:
            print("DID NOT RAISE — this is a defect")

asyncio.run(delete_and_retry())
```

**You should see:** `deleted:` printed with a `reprocessing` field (queued the same way a correction would, since the underlying subject/source is the same); then `refused, as expected: ...` — never `DID NOT RAISE`.

```
scripts/dev.sh psql <<'SQL'
SELECT count(*) FROM memory WHERE subject = 'test.correction_subject' AND superseded_by IS NULL;
SELECT kind FROM audit_decisions WHERE occurred_at > now() - interval '10 minutes' ORDER BY occurred_at;
SQL
```

**You should see:** zero active rows for the subject (the whole chain is now superseded or deleted), and the decisions log carrying `memory_superseded` entries for each correction plus one `memory_deleted` — every correction and the deletion each left its own record.

### 12. Exit and clean up

```python
exit()
```

```
scripts/dev.sh psql <<'SQL'
DELETE FROM reapply_items WHERE job_id IN (SELECT id FROM reapply_jobs WHERE subject = 'test.correction_subject');
DELETE FROM reapply_jobs WHERE subject = 'test.correction_subject';
DELETE FROM memory WHERE subject = 'test.correction_subject';
DELETE FROM clarifications WHERE subject = 'test.correction_subject';
SQL
```

---

## 3. What only the test suite shows: the row lock and the schema-note equivalents

The one behaviour this walkthrough cannot demonstrate by hand is the `FOR UPDATE` lock serialising two corrections that arrive genuinely concurrently — that needs two transactions held open at once, which a single psql/Python session cannot produce. Schema-note correction and deletion mirror memory's shape exactly and are equally unreachable from any screen (nothing writes a schema note in the running app at all, per `M3-STORE-BE-076`'s own manual test). Run the module's tests against a real, disposable database for both:

```
scripts/dev.sh test-db api/tests/test_memory.py -v
```

**You should see:** every test below reported `PASSED`, nothing skipped:

| Test | What it proves, mapped to the ticket |
| ---- | ------------------------------------ |
| `test_correcting_to_the_same_value_is_a_no_op` | Edge case: correcting to the same value — no supersession, nothing queued |
| `test_correcting_a_sourceless_fact_has_nothing_to_reprocess` | A manual fact with no `source_id` resolves to nothing to re-process, honestly |
| `test_correcting_a_fact_queues_reprocessing_of_its_source` | AC: a real change queues re-processing and returns the affected-material summary |
| `test_correcting_the_same_fact_twice_leaves_a_clean_three_value_chain` | The ticket's own Real-World Example, exactly as walked above |
| `test_deleting_a_fact_also_queues_reprocessing` | "Deletion follows the same shape, minus the new fact" |
| `test_correcting_a_schema_note_to_the_same_description_is_a_no_op`, `test_correcting_a_schema_note_queues_reprocessing_of_its_source` | The schema-note half of the same path, including the schema-note dependency filter (§2 of `docs/decisions.md`'s entry for this ticket) |
| `test_correcting_an_already_deleted_fact_is_refused_with_a_clear_reason` | Edge case: correcting an already-deleted fact — refused with a clear reason |

If any of these is not `PASSED`, stop — that is a real regression, not a gap.

---

## Known gaps

- **No chip and no memory screen call this path yet.** `M3-CORRECT-FE-081` and `M3-MEM-FE-083`/`-084` are open tickets — "correcting from a chip and from the memory screen produce identical results" is true of the two Python calls this walkthrough made, standing in for those callers, not yet observable through any UI.
- **None of `correct_memory_fact`, `correct_schema_note`, `delete_memory_fact`, `delete_schema_note` are exposed over HTTP.** There is no route to exercise them with `curl` either, unlike `M3-STORE-BE-076`'s one `DELETE /sources/{id}` step.
- **The `FOR UPDATE` serialisation cannot be demonstrated by hand** — verified only by `api/tests/test_memory.py`'s use of a real Postgres row lock, not by this document.
- **A schema-note correction can leave a genuinely stale inferred note unpromoted** when it happens to share the corrected column's name on a different table — documented in `docs/decisions.md`'s 2026-09-17 entry for this ticket as an accepted trade-off, not a defect.
- **No bulk correction** — the ticket's own stated gap.
- **`write_memory_fact`/`write_schema_note`'s own reachability gaps are unchanged from `M3-STORE-BE-076`'s manual test** — answering a clarification through the real screen still writes correctly, and nothing in the app writes a schema note yet. This ticket did not touch either of those write paths.
