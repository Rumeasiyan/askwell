# Manual test — M3-STORE-OBS-077, clarification answers written as decisions records in one transaction

**Ticket:** `M3-STORE-OBS-077` — every memory change (an answer, a correction, a deletion, a skip, a dismissal) writes its `audit_decisions` record in the same database transaction as the change itself, so the two can never diverge. An induced audit-write failure must prevent the memory change. The chain must verify after a run of these operations. C6 (append-only by grant, chained, never called immutable) must hold throughout.
**Version under test:** `0.3.10`
**Time:** about 45 minutes, plus a first stack build and native inference startup.
**Who can run it:** a browser, a terminal, `psql` access via `scripts/dev.sh psql`, and `curl`. Several steps use `curl` directly against the API, not the browser — see "Where this stops on purpose" for why.

**What is being checked.** `api/src/askwell/review.py`: `answer_clarification`, `skip_clarification`, `dismiss_group`, `undo_answer`, and the two new functions this ticket adds in `api/src/askwell/memory.py`: `delete_memory_fact`, `delete_schema_note`. `api/tests/test_review.py` is the authoritative test of the transactional guarantee, including a test that runs this ticket's own manual walkthrough verbatim (`test_the_decisions_chain_covers_a_cold_start_walkthrough`) and a fail-closed test (`test_answering_fails_closed_when_the_decisions_record_cannot_be_written`) — this document repeats both against a real running stack, not a disposable test database, plus the live app's exception handling and `askwell-verify` command, which the pytest run cannot exercise.

**Where this stops on purpose — read this before reporting anything below as a defect.**

- **The Clarifications screen's Save and Skip buttons render but do nothing.** `web/components/clarifications/clarifications-screen.tsx` lays out the anatomy (`M3-REVIEW-FE-073`) but wiring them to `POST /clarifications/{id}/answer` and `/skip` is `M3-REVIEW-FE-074`'s own territory, and that ticket has not landed — there is no `onClick` on either button and `web/lib/clarifications.ts` has no answer/skip/dismiss/undo call at all. Clicking **Save** or **Skip** in the running app visibly does nothing. This document therefore drives the four write actions (answer, skip, dismiss-group, undo) through `curl` against the live, already-registered routes (`api/src/askwell/app.py` → `register_review`) rather than pretending a button exists.
- **`correct_memory_fact`, `correct_schema_note`, `delete_memory_fact` and `delete_schema_note` are not exposed over HTTP at all**, and have no caller anywhere in the running application — not even `undo_answer`, which deletes the memory row with its own inline `DELETE` rather than calling `delete_memory_fact`. The only way to exercise them against a real database is `scripts/dev.sh run` invoking the function directly, or the test suite. §2 below does the former for the walkthrough's "correct one" step.
- **There is no memory or schema-notes screen.** `web/app/memory/page.tsx` is still the `M3-MEM-FE-084` placeholder — nothing renders a fact, a correction, a deletion or a history view. Everything a fact looked like before or after these operations is read from `psql` in this document, not from a screen.
- **Answering a clarification still writes `memory` with `review.py`'s own inline `INSERT`, not `askwell.memory.write_memory_fact`** (issue #282, pre-existing, not this ticket's scope). This only matters if two answers land on the *same* subject; the walkthrough below uses three distinct subjects, so it does not surface here.

None of this is a defect in this ticket — its scope is the transactional guarantee and the five record shapes, not wiring a frontend that belongs to other tickets. Sections below say which is which.

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

Find `POSTGRES_APP_PASSWORD` and put any word after the `=` if it is blank. Find `ASKWELL_EMBEDDING_MODEL_PATH` and confirm it points at a model that actually exists on this machine. Confirm `ASKWELL_ENVIRONMENT=development` — the last section below needs the dev-mode error detail that setting turns on.

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

### 6. Confirm the Clarifications screen loads

Click **Clarifications** in the sidebar. **You should see:** either "nothing pending" copy, or a list grouped by source with a count. This confirms the surface this ticket's writes eventually feed is reachable before seeding anything into it.

---

## 1. The cold-start walkthrough this ticket names: answer three, correct one

### 7. Seed one source and three pending clarifications

```
scripts/dev.sh psql <<'SQL'
INSERT INTO sources (id, kind, name, status, added_at)
VALUES ('55555555-5555-5555-5555-555555555551', 'file', 'obs-077-contracts', 'ready', now());

INSERT INTO clarifications (id, source_id, subject, question, evidence, rank, status, asked_at)
VALUES
  ('55555555-5555-5555-5555-555555555552', '55555555-5555-5555-5555-555555555551',
   'obs077.rfq', 'What does RFQ mean in these files?',
   '{"kind":"unavailable","reason":"seeded for M3-STORE-OBS-077","current_inference":null}'::jsonb,
   1, 'pending', now()),
  ('55555555-5555-5555-5555-555555555553', '55555555-5555-5555-5555-555555555551',
   'obs077.po', 'What does PO mean in these files?',
   '{"kind":"unavailable","reason":"seeded for M3-STORE-OBS-077","current_inference":null}'::jsonb,
   2, 'pending', now()),
  ('55555555-5555-5555-5555-555555555554', '55555555-5555-5555-5555-555555555551',
   'obs077.grn', 'What does GRN mean in these files?',
   '{"kind":"unavailable","reason":"seeded for M3-STORE-OBS-077","current_inference":null}'::jsonb,
   3, 'pending', now());
SQL
```

Click **Clarifications** again (or reload). **You should see:** a group for `obs-077-contracts` with a count of `3`, and three cards — `obs077.rfq`, `obs077.po`, `obs077.grn` — each with its question. This is as far as the UI takes you; Save does nothing (see "Where this stops on purpose"), so the answers themselves go through the same route Save would call.

### 8. Answer all three through the live route

```
curl -s -X POST http://127.0.0.1:8000/clarifications/55555555-5555-5555-5555-555555555552/answer \
  -H 'content-type: application/json' -d '{"answer":"Request for Quotation"}'

curl -s -X POST http://127.0.0.1:8000/clarifications/55555555-5555-5555-5555-555555555553/answer \
  -H 'content-type: application/json' -d '{"answer":"Purchase Order"}'

curl -s -X POST http://127.0.0.1:8000/clarifications/55555555-5555-5555-5555-555555555554/answer \
  -H 'content-type: application/json' -d '{"answer":"Goods Received Note"}'
```

**You should see:** three JSON bodies, each `{"id": "...", "status": "answered", "memory_id": "..."}`. Note the `memory_id` from the *third* response — the GRN one — you need it for the next step.

Reload **Clarifications**. **You should see:** the group is gone (or its count is `0`) — the three cards you just answered no longer show as pending.

### 9. Correct the third answer

There is no route for this — call `correct_memory_fact` directly, substituting the `memory_id` from step 8's third response:

```
scripts/dev.sh run python -c "
import asyncio, uuid
from askwell.config import load_settings
from askwell.db.engine import build_engine, session_factory
from askwell.memory import correct_memory_fact

async def main():
    engine = build_engine(load_settings())
    factory = session_factory(engine)
    async with factory() as session:
        await correct_memory_fact(
            session,
            fact_id=uuid.UUID('<memory_id from step 8, third answer>'),
            fact='Goods Receipt Note',
        )
        await session.commit()
    await engine.dispose()

asyncio.run(main())
"
```

**You should see:** the command exits with no error output.

### 10. Confirm the four facts and their shape

```
scripts/dev.sh psql <<'SQL'
SELECT subject, fact, origin, confidence, superseded_by IS NOT NULL AS superseded
FROM memory ORDER BY created_at;
SQL
```

**You should see:** four rows — `obs077.rfq | Request for Quotation | clarification | 1.000 | f`, `obs077.po | Purchase Order | clarification | 1.000 | f`, `obs077.grn | Goods Received Note | clarification | 1.000 | t`, `obs077.grn | Goods Receipt Note | correction | 1.000 | f`. The GRN subject has two rows because the correction superseded rather than overwrote — the old value is still readable.

### 11. Confirm the decisions chain names all four events

```
scripts/dev.sh psql <<'SQL'
SELECT kind, payload FROM audit_decisions
WHERE kind IN ('clarification_answered', 'memory_superseded')
ORDER BY occurred_at;
SQL
```

**You should see:** four rows in this order — three `clarification_answered` (RFQ, then PO, then GRN, each with a `subject` and `memory_id` in its payload), then one `memory_superseded` naming the GRN fact's old and new ids. This is the ticket's own acceptance criterion made visible: every memory change has a corresponding decisions record.

### 12. Verify the chain is intact

```
podman compose exec api askwell-verify
```

**You should see:** a line for `audit_decisions` reading `chain intact` (it will report a count of every record in the database, not just these four — this is a shared store, not a per-test one), and a line for `audit_interactions`. Neither should report a break.

---

## 2. Undo: its own record, not a deletion of the original

### 13. Seed and answer a fresh clarification

```
scripts/dev.sh psql <<'SQL'
INSERT INTO clarifications (id, source_id, subject, question, evidence, rank, status, asked_at)
VALUES ('55555555-5555-5555-5555-555555555555', '55555555-5555-5555-5555-555555555551',
  'obs077.undo_test', 'What does this mean?',
  '{"kind":"unavailable","reason":"seeded for M3-STORE-OBS-077","current_inference":null}'::jsonb,
  4, 'pending', now());
SQL

curl -s -X POST http://127.0.0.1:8000/clarifications/55555555-5555-5555-5555-555555555555/answer \
  -H 'content-type: application/json' -d '{"answer":"a first pass"}'
```

**You should see:** `{"id": "...5555", "status": "answered", "memory_id": "..."}`. Note the `memory_id`.

### 14. Undo it

```
curl -s -X POST http://127.0.0.1:8000/clarifications/55555555-5555-5555-5555-555555555555/undo \
  -H 'content-type: application/json' -d '{"memory_id":"<memory_id from step 13>"}'
```

**You should see:** `{"id": "...5555", "status": "pending"}`.

### 15. Confirm the fact is gone and the original record is untouched

```
scripts/dev.sh psql <<'SQL'
SELECT count(*) FROM memory WHERE subject = 'obs077.undo_test';
SELECT status, answer FROM clarifications WHERE id = '55555555-5555-5555-5555-555555555555';
SELECT kind FROM audit_decisions
WHERE payload->>'clarification_id' = '55555555-5555-5555-5555-555555555555' ORDER BY occurred_at;
SQL
```

**You should see:** the fact count is `0`, the clarification is back to `pending` with `answer` null, and there are **two** decisions records for this clarification: `clarification_answered` then `clarification_answer_undone` — the original record was not deleted or rewritten; undo added a second one, exactly as the ticket's own edge case requires.

---

## 3. A batch of skips: one record each

### 16. Seed two more pending items on the same source and dismiss the group

```
scripts/dev.sh psql <<'SQL'
INSERT INTO clarifications (id, source_id, subject, question, evidence, rank, status, asked_at)
VALUES
  ('66666666-6666-6666-6666-666666666661', '55555555-5555-5555-5555-555555555551',
   'obs077.dismiss_a', 'Question A?',
   '{"kind":"unavailable","reason":"seeded","current_inference":null}'::jsonb, 5, 'pending', now()),
  ('66666666-6666-6666-6666-666666666662', '55555555-5555-5555-5555-555555555551',
   'obs077.dismiss_b', 'Question B?',
   '{"kind":"unavailable","reason":"seeded","current_inference":null}'::jsonb, 6, 'pending', now());
SQL

curl -s -X POST http://127.0.0.1:8000/sources/55555555-5555-5555-5555-555555555551/clarifications/dismiss
```

**You should see:** `{"dismissed": ["6666...661", "6666...662"]}`.

### 17. Confirm one record per item

```
scripts/dev.sh psql <<'SQL'
SELECT count(*) FROM audit_decisions
WHERE kind = 'clarification_dismissed'
AND payload->>'clarification_id' IN ('66666666-6666-6666-6666-666666666661', '66666666-6666-6666-6666-666666666662');
SQL
```

**You should see:** `2` — one record per dismissed item, so the count is a countable signal rather than one record for the whole batch.

---

## 4. Deletion: `delete_memory_fact`/`delete_schema_note`, test-suite only

Neither function has a caller anywhere in the running app (see "Where this stops on purpose"), so this section runs the module's own tests against a real, disposable database rather than seeding through the live one.

### 18. Run the module's deletion tests

```
scripts/dev.sh test-db api/tests/test_memory.py -v -k delet
scripts/dev.sh test-db api/tests/test_review.py -v
```

**You should see:** every test reported `PASSED`, including (names may vary slightly, match on intent if so):

| Test | What it proves |
| ---- | --------------- |
| a delete-memory-fact test in `test_memory.py` | `delete_memory_fact` removes the active row and writes `memory_deleted` with a snapshot (subject, fact, origin) in the same transaction |
| a delete-schema-note test in `test_memory.py` | `delete_schema_note` mirrors the above for `schema_notes` |
| `test_the_decisions_chain_covers_a_cold_start_walkthrough` | this document's §1, run as a test: three answers plus a correction, chain intact, four records in order |
| `test_undo_deletes_the_memory_fact_and_records_its_own_decision` | this document's §2 |
| `test_dismissing_a_group_writes_one_record_per_item` | this document's §3 |
| `test_answering_fails_closed_when_the_decisions_record_cannot_be_written` | this document's §5, below |

If any of these is not `PASSED`, stop — that is a real regression, not a gap.

---

## 5. Fail-closed: an induced audit failure must prevent the memory change

### 19. Revoke the app role's write grant on `audit_decisions`

```
scripts/dev.sh psql <<'SQL'
REVOKE INSERT ON audit_decisions FROM askwell_app;
SQL
```

### 20. Seed one more pending clarification and try to answer it

```
scripts/dev.sh psql <<'SQL'
INSERT INTO clarifications (id, source_id, subject, question, evidence, rank, status, asked_at)
VALUES ('77777777-7777-7777-7777-777777777771', '55555555-5555-5555-5555-555555555551',
  'obs077.failclosed', 'What does this mean?',
  '{"kind":"unavailable","reason":"seeded for M3-STORE-OBS-077","current_inference":null}'::jsonb,
  7, 'pending', now());
SQL

curl -s -w '\n%{http_code}\n' -X POST http://127.0.0.1:8000/clarifications/77777777-7777-7777-7777-777777777771/answer \
  -H 'content-type: application/json' -d '{"answer":"should not stick"}'
```

**You should see:** HTTP status `500`, and a JSON body reading `{"error": "Askwell hit an error it did not expect.", "path": "/clarifications/.../answer", "exception": "..."}` — in development mode the stated reason names the database permission error (something containing `permission denied for table audit_decisions`), not a bare failure with no explanation.

### 21. Confirm no fact was written and the clarification is still pending

```
scripts/dev.sh psql <<'SQL'
SELECT count(*) FROM memory WHERE subject = 'obs077.failclosed';
SELECT status, answer FROM clarifications WHERE id = '77777777-7777-7777-7777-777777777771';
SQL
```

**You should see:** the fact count is `0`, and the clarification is still `pending` with `answer` null. The failed decisions-record write rolled back the whole transaction, including the `UPDATE clarifications` and the `INSERT INTO memory` that were about to commit alongside it — the memory change did not happen without its audit record.

### 22. Restore the grant

```
scripts/dev.sh psql <<'SQL'
GRANT INSERT ON audit_decisions TO askwell_app;
SQL
```

**Confirm the app is healthy again:**

```
curl -s -X POST http://127.0.0.1:8000/clarifications/77777777-7777-7777-7777-777777777771/answer \
  -H 'content-type: application/json' -d '{"answer":"now it sticks"}'
```

**You should see:** `{"id": "...771", "status": "answered", "memory_id": "..."}` — the same route that failed a moment ago now succeeds once the grant is back, confirming step 20's failure was the induced permission error and nothing else was broken by it.

### 23. Verify the chain once more, end to end

```
podman compose exec api askwell-verify
```

**You should see:** both stores still report `chain intact`. The revoked grant produced a rejected write, not a corrupted one — there is nothing in the chain from the failed attempt to break it, because nothing from that attempt was ever committed.

---

## Clean up

```
scripts/dev.sh psql <<'SQL'
DELETE FROM memory WHERE subject LIKE 'obs077.%';
DELETE FROM clarifications WHERE subject LIKE 'obs077.%';
DELETE FROM sources WHERE id = '55555555-5555-5555-5555-555555555551';
SQL
```

---

## Known gaps

- **The Clarifications screen's Save and Skip buttons are not wired.** `M3-REVIEW-FE-074` has not landed; every write in this document went through `curl` against the live route, not a click. This is not a defect in `M3-STORE-OBS-077` — it is a different, not-yet-built ticket.
- **`correct_memory_fact`, `correct_schema_note`, `delete_memory_fact` and `delete_schema_note` have no HTTP route and no caller in the running app.** §1 step 9 and §4 exercise them directly (a one-off script, and the test suite) rather than through the API, because there is currently no other way to reach them.
- **No memory or schema-notes screen exists.** `web/app/memory/page.tsx` is still `M3-MEM-FE-084`'s placeholder — nothing in this walkthrough was ever visible as a fact, a correction, or a history entry in the app itself; every confirmation in this document reads `psql` directly.
- **Dismiss-group and undo have no button anywhere in the web app** — both are reachable only via the routes this document calls with `curl`.
- **Answering the same subject twice through the real UI does not supersede** (issue #282, `M3-STORE-BE-076`'s own gap, unrelated to this ticket) — irrelevant here because the walkthrough uses three distinct subjects, but worth knowing if this document's steps are adapted to reuse one.
- **No export.** Out of scope per the ticket itself; arrives in M7.
