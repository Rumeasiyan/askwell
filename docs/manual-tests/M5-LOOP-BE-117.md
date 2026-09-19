# Manual test — M5-LOOP-BE-117, the trace's step sequence and its rotation

**Ticket:** `M5-LOOP-BE-117` — `messages.trace` carries every step kind with duration and
per-kind detail (retrieval with query/threshold/scored hits, schema lookup with its source,
SQL with the query/validation outcome/rejection reason/injected limit/row count, compose with
the claim count), plus `backend`, `stopped_early` and `injection_flagged` on the trace as a
whole. The file ring buffer (`askwell.traces.TraceRing`) now actually rotates
`messages.trace.steps` with it, and a trace larger than the per-turn bound (50 steps) is
truncated with that fact stated on the trace itself, never silently.

**Version under test:** check `cat VERSION` (`0.4.31` at the time this document was written).
**Time:** about 60 minutes, plus a first stack build and native inference running.
**Who can run it:** a browser, a terminal, `podman compose exec`/`scripts/dev.sh psql` access,
native `llama.cpp` inference running on the host (`scripts/dev.sh inference`) — like
`M5-LOOP-BE-115`/`-116`, several sections below read what a real model actually did, so nothing
in §1–§3 works against a stack with no model loaded. §4–§6 read the trace store directly and
work with no model at all.

**What is being checked.** `api/src/askwell/traces.py` (`TraceRing.write`/`prune`, the new
`TraceWriteResult.dropped`); `api/src/askwell/ask.py` (`_run_generation`'s trace-step
assembly for the retrieve/schema/sql/compose kinds, `_bound_trace_steps`/`TRACE_STEP_BOUND`,
`_trim_rotated_traces`); `api/src/askwell/agent/sql_generate.py`
(`GeneratedQuery.schema_lookup_ms`). Backed by `api/tests/test_traces.py` (the ring buffer
itself — round-trip, an unwritable directory, the oldest traces dropped first, an interrupted
write leaving nothing corrupt, `prune()` reporting the actual dropped ids) and
`api/tests/test_ask_sql.py`/`test_ask_api.py` (the schema step's source and duration on both an
executed and a rejected query, `_trim_rotated_traces` clearing `steps` while leaving
`status`/`backend` intact, a no-op confirmed when nothing rotated). This document repeats the
headline behaviour — every step kind actually appears with real numbers, a rejected query is
recorded rather than hidden, and rotation trims the DB column exactly when the file store drops
a trace, never before and never leaving the two disagreeing — against a cold-started stack,
which the automated suite fakes.

**Where this stops on purpose — read before reporting anything below as a defect.**

- **There is no trace panel.** `docs/ux/trace.md` describes the rendered panel;
  `M5-TRACE-FE-119` (Out of Scope for this ticket) builds it. Every step below is read back with
  `psql` against `messages.trace`, not clicked open in a browser.
- **A small local model does not reliably produce every step kind on command.** The corpus and
  questions below are built to make retrieval, schema lookup, SQL and composition each likely,
  but nothing forces a real model to touch every path in one document. Where a step's presence
  depends on what the model chooses to do, that is called out.
- **Forcing a rejected query, a query-time failure, or 50+ real steps through a real model is
  not reliably drivable through the browser.** §4 and §6 reproduce those against the real code
  directly (a scripted call, and a hand-inserted row) rather than depending on a model
  cooperating on cue — the same shape `M5-LOOP-BE-116.md` used for its own "nothing gathered"
  edge case.

---

## Before you start

```
cd ~/external/quantum-plus/askwell
```

If you have never run Askwell before:

```
cp -n .env.example .env
```

Open `.env` and confirm every `?set ... in .env` placeholder has a real value.

### Make a document corpus with one distinct, quotable fact

```
mkdir -p ~/askwell-test/docs
cat > ~/askwell-test/docs/meridian-agreement.txt <<'EOF'
SUPPLIER AGREEMENT — MERIDIAN CORP — PAYMENT TERMS

Meridian Corp must be paid within 30 days of the invoice date. Contact for
disputes: meridian-ap@example.test. Standard order minimum: $2500.
EOF
```

**You should see:** one `.txt` file in `~/askwell-test/docs`.

---

## Cold start

### 1. Remove any previous state

```
podman compose down -v
```

**You should see:** containers and volumes reported removed, or a note there was nothing to
remove.

### 2. Bring the stack up, migrate, and start native inference

```
podman compose up -d
scripts/dev.sh db upgrade head
```

**You should see:** `postgres`, `sandbox`, `redis`, `egress-proxy`, `api`, `worker` all reported
created and started; migration finishing with no error.

In a separate terminal, on the host:

```
scripts/dev.sh inference
```

**You should see:** the inference process logging that it is listening on its socket. Leave it
running for the rest of this document.

### 3. Open Askwell as a first-time user

Open a browser at `http://127.0.0.1:8000`. **You should see:** the shell load with no alarm
banner, and the first-run empty state on the Ask screen.

### 4. Add the supplier agreement, by clicking

Click **Add a source**. In the **Files** section, click **Choose files** and select
`meridian-agreement.txt`. Answer any folder-nomination prompt by clicking its suggested folder.
**You should see:** the file appears in the batch list and moves to **Indexed** (or **Ready**)
within a few seconds.

### 5. Stand up a database to connect to

Plays the part of a database the user already runs, same pattern as `M5-LOOP-BE-115.md` and
`M5-LOOP-BE-116.md`.

```
podman compose exec sandbox psql -U "$(grep ^SANDBOX_POSTGRES_USER .env | cut -d= -f2)" -d postgres <<'SQL'
CREATE DATABASE trace_test OWNER askwell_sandbox_owner;
SQL
```

**You should see:** `CREATE DATABASE`.

```
podman compose exec sandbox psql -U askwell_sandbox_owner -d trace_test <<'SQL'
CREATE TABLE payments (
    supplier text not null,
    invoice_date date not null,
    paid_date date not null
);
INSERT INTO payments VALUES
    ('Meridian Corp', '2026-06-01', '2026-07-16');
GRANT CONNECT ON DATABASE trace_test TO askwell_sandbox_readonly;
GRANT USAGE ON SCHEMA public TO askwell_sandbox_readonly;
GRANT SELECT ON payments TO askwell_sandbox_readonly;
SQL
```

**You should see:** `CREATE TABLE`, `INSERT 0 1`, three `GRANT`s.

```
grep ^SANDBOX_READONLY_PASSWORD .env
```

Note the readonly password.

### 6. Connect to it, by clicking

Still on **Add a source**, in the **Connect a database** section: Engine `PostgreSQL`, Host
`sandbox`, Port `5432`, Database `trace_test`, User `askwell_sandbox_readonly`, Password (from
step 5). Click **Connect**.

**You should see:** a queued/ready confirmation naming `trace_test`; the library shows it as
**Ready** after a few seconds.

---

## 1. A database question produces a schema step and a sql step, in order, with real numbers

### 7. Ask a question that names the connected database

Go to **Ask**. In the composer, type:

```
According to the database, how many days late was Meridian Corp actually paid?
```

Click **Ask** (or press Enter).

**You should see, while it is working:** the step "Checking your connected databases." and,
once it answers, prose stating a number of days (30 June invoice, 16 July paid — 15 days late)
or the query's own result.

### 8. Find the message id and read the schema step

```
scripts/dev.sh psql -c "SELECT id FROM messages WHERE role = 'assistant' ORDER BY id DESC LIMIT 1;"
```

Note the `id` — call it `$MSG_ID`.

```
scripts/dev.sh psql -c "
SELECT step->>'kind', step->>'ms', step->>'source_id'
FROM messages, jsonb_array_elements(trace->'steps') AS step
WHERE id = '$MSG_ID' AND step->>'kind' = 'schema';
"
```

**You should see:** one row, `kind` reading `schema`, `ms` a real (non-zero, non-null) number,
and `source_id` a UUID matching the `trace_test` connection's own source id
(`SELECT id FROM sources WHERE name = 'trace_test';` to confirm). This is the step
`M5-LOOP-BE-117` added — previously nothing recorded the schema-notes lookup at all.

### 9. Read the sql step and confirm it comes after the schema step

```
scripts/dev.sh psql -c "
SELECT ordinality, step->>'kind', step->>'outcome'
FROM messages, jsonb_array_elements(trace->'steps') WITH ORDINALITY AS t(step, ordinality)
WHERE id = '$MSG_ID'
ORDER BY ordinality;
"
```

**You should see:** the `schema` step's ordinality strictly less than the `sql` step's — schema
lookup happens before the query that needs it, matching `docs/ux/trace.md` §2's own worked
example ("Looked up schema" before "Queried").

### 10. Confirm the executed query's own detail: the query text, row count, and the injected limit

```
scripts/dev.sh psql -c "
SELECT step->>'outcome', step->>'rows', step->>'limit_injected', step->'query'
FROM messages, jsonb_array_elements(trace->'steps') AS step
WHERE id = '$MSG_ID' AND step->>'kind' = 'sql';
"
```

**You should see (if the query executed):** `outcome` reading `executed`, `rows` a real count,
`limit_injected` a real number (the `LIMIT` Askwell added, not one the model wrote), and
`query` the actual generated SQL text, ending in the injected `LIMIT` clause.

**If the model instead answered from the document** (the payment term is in the file too, and a
small model may prefer it): re-ask a question that can only be answered from the database, e.g.
"What does the `payments` table say about when Meridian Corp was actually paid?", and repeat
steps 8–10.

---

## 2. A document question produces a retrieve step with real scores and the threshold in force

### 11. Ask a question answerable only from the document

```
What is Meridian Corp's standard order minimum?
```

**You should see:** an answer citing the $2500 minimum from the supplier agreement.

### 12. Find this new message id and read the retrieve step

```
scripts/dev.sh psql -c "SELECT id FROM messages WHERE role = 'assistant' ORDER BY id DESC LIMIT 1;"
```

Note the new `id` — call it `$MSG_ID2` (it must differ from `$MSG_ID`).

```
scripts/dev.sh psql -c "
SELECT step->>'query', step->>'threshold', jsonb_array_length(step->'hits') AS hit_count
FROM messages, jsonb_array_elements(trace->'steps') AS step
WHERE id = '$MSG_ID2' AND step->>'kind' = 'retrieve';
"
```

**You should see:** `query` reading back the question you typed, `threshold` a decimal (`0.65`
unless `ASKWELL_RETRIEVAL_SCORE_THRESHOLD` was changed in `.env`), and `hit_count` greater than
zero.

### 13. Confirm every hit carries its own chunk id and score

```
scripts/dev.sh psql -c "
SELECT jsonb_array_elements(step->'hits')
FROM messages, jsonb_array_elements(trace->'steps') AS step
WHERE id = '$MSG_ID2' AND step->>'kind' = 'retrieve';
"
```

**You should see:** one row per retrieved passage, each a `{"chunk_id": ..., "score": ...}`
object — the score is the same comparable value the abstention decision itself was made
against (`askwell.retrieve.candidate_score`), not the raw fused RRF value, per the ticket's own
Validation Rule that scores are stored as measured, never recomputed later.

### 14. Confirm the compose step carries the claim count

```
scripts/dev.sh psql -c "
SELECT step->>'claims', step->>'citations'
FROM messages, jsonb_array_elements(trace->'steps') AS step
WHERE id = '$MSG_ID2' AND step->>'kind' = 'compose';
"
```

**You should see:** `claims` a positive integer (at least one sentence in the answer carried a
citation marker) and `citations` a count of citation rows written for it.

### 15. Confirm the top-level backend, model and flags

```
scripts/dev.sh psql -c "
SELECT trace->'backend', trace->>'stopped_early', trace->>'injection_flagged'
FROM messages WHERE id = '$MSG_ID2';
"
```

**You should see:** `backend` reading `{"mode": "local", "model": "<the .gguf filename stem>"}`
— the model actually loaded, read from `Settings.inference_model_path`, never hardcoded;
`stopped_early` reading `false`; `injection_flagged` reading `false` (nothing in this corpus
looks instruction-like).

---

## 3. A rejected query is recorded, not hidden

### 16. Ask a question that only a write could answer

```
Delete the row for Meridian Corp from the database.
```

**You should see:** a plain-language refusal — Askwell will not run a write.

### 17. Confirm the rejection reason is on the trace

```
scripts/dev.sh psql -c "SELECT id FROM messages WHERE role = 'assistant' ORDER BY id DESC LIMIT 1;"
```

Note the id as `$MSG_ID3`.

```
scripts/dev.sh psql -c "
SELECT step->>'outcome', step->>'reason', step->'query'
FROM messages, jsonb_array_elements(trace->'steps') AS step
WHERE id = '$MSG_ID3' AND step->>'kind' = 'sql';
"
```

**You should see (if the model actually generated a `DELETE` for validation to reject):**
`outcome` reading `rejected`, `reason` naming which C2 check failed (e.g. `not_select`), and
`query` the actual rejected SQL text — never blanked out. This is `docs/ux/trace.md` §3's own
"Rejected SQL is recorded and shown" requirement: the signal that a prompt change degraded
generation would otherwise be invisible.

**If the model declined to write any SQL at all** (a small model may simply refuse in prose,
never reaching validation): this is a legitimate outcome — nothing here forces the model to
attempt a query. `api/tests/test_ask_sql.py`'s own rejected-query cases are the authoritative
proof that a rejection is recorded when one occurs; this step is exploratory against a real
model, not the only proof.

---

## 4. The ring buffer rotates, and `messages.trace` is trimmed with it — citations survive

### 18. Shrink the trace cap so the next few writes force a rotation

```
podman compose exec api sh -c 'echo ASKWELL_TRACE_MAX_BYTES=4096 >> /app/.env'
podman compose restart api worker
```

Wait a few seconds for the containers to report healthy again (`podman compose ps`).

### 19. Note which messages exist before rotation

```
scripts/dev.sh psql -c "SELECT id FROM messages WHERE role = 'assistant' ORDER BY id;"
```

`$MSG_ID2` (the document-answered turn from §2) should still be in this list.

### 20. Ask a few more questions to push the ring buffer over its new, tiny cap

Ask, one at a time, waiting for each to finish:

```
What is Meridian Corp's dispute contact?
```

```
When must Meridian Corp be paid according to the agreement?
```

```
Summarize everything the agreement says about Meridian Corp.
```

**You should see:** three ordinary answers.

### 21. Confirm the oldest trace file rotated out

```
scripts/dev.sh psql -c "SELECT id, trace->>'trace_rotated' AS rotated FROM messages WHERE id = '$MSG_ID2';"
```

**You should see:** `rotated` reading `true` — `$MSG_ID2`'s trace file aged out of the 4 KB
`TraceRing` once later turns' traces pushed the directory over the cap, and
`_trim_rotated_traces` cleared this row's `trace.steps` in the same step, per the ticket's own
Acceptance Criterion.

### 22. Confirm the rest of the trace survived — only `steps` was cleared

```
scripts/dev.sh psql -c "
SELECT trace->>'status', trace->'backend', trace->'steps'
FROM messages WHERE id = '$MSG_ID2';
"
```

**You should see:** `status` and `backend` still populated exactly as before rotation, `steps`
reading `[]` — a reopened old turn still renders its status and backend, it just lost the
step-by-step debugging detail, matching the ticket's own "old abstention still explains itself
with the numbers that produced it" framing for what does *not* rotate (see next step).

### 23. Confirm the answer's citations still resolve — they do not rotate

Reopen the conversation in the browser (scroll up to the "order minimum" turn from §2, or
reload the Ask screen). **You should see:** the answer text and its citation card for
`meridian-agreement.txt` still render — `citations` is a real table, untouched by the trace
ring buffer, per this ticket's own Acceptance Criterion ("the answer's citations remain
resolvable").

Confirm the same directly:

```
scripts/dev.sh psql -c "SELECT chunk_id FROM citations c JOIN messages m ON m.id = c.message_id WHERE m.id = '$MSG_ID2';"
```

**You should see:** at least one row — the citation row is independent of `trace.steps` having
just been cleared.

### 24. Undo the cap change

```
podman compose exec api sh -c "sed -i '/ASKWELL_TRACE_MAX_BYTES=4096/d' /app/.env"
podman compose restart api worker
```

---

## 5. A trace larger than the per-turn bound is truncated, and says so

Reproduces the 50-step bound (`TRACE_STEP_BOUND` in `api/src/askwell/ask.py`) directly, since
driving a real model through 51 real steps in one turn is not a reliable thing to ask a
question into being.

### 25. Run the scripted repro inside the API container

```
scripts/dev.sh run python - <<'PY'
from askwell.ask import _bound_trace_steps

steps = [{"kind": "retrieve", "ms": i} for i in range(60)]
bounded, truncated = _bound_trace_steps(steps)
assert len(bounded) == 50
assert truncated is True
print("OK: 60 steps bounded to 50, steps_truncated=True")

steps_ok = [{"kind": "retrieve", "ms": i} for i in range(50)]
bounded_ok, truncated_ok = _bound_trace_steps(steps_ok)
assert len(bounded_ok) == 50
assert truncated_ok is False
print("OK: exactly 50 steps left untouched, steps_truncated=False")
PY
```

**You should see:** both `OK:` lines — a turn's own step count past the bound is capped, and
the truncation is stated (`steps_truncated: true`) rather than the extra steps silently
vanishing, matching this ticket's own named edge case.

---

## 6. A single-step trace is a valid one-step trace, not an empty one

### 26. Ask a question that abstains immediately

```
What does our contract say about a supplier named Nonexistent Corp?
```

**You should see:** an abstention — Askwell states it found nothing.

### 27. Confirm the trace has real content, not an empty shell

```
scripts/dev.sh psql -c "SELECT id FROM messages WHERE role = 'assistant' ORDER BY id DESC LIMIT 1;"
```

Note the id as `$MSG_ID4`.

```
scripts/dev.sh psql -c "
SELECT jsonb_array_length(trace->'steps') AS step_count, trace->'steps'->0->>'kind' AS first_kind
FROM messages WHERE id = '$MSG_ID4';
"
```

**You should see:** `step_count` at least `1` and `first_kind` reading `retrieve` — even a turn
that abstained immediately recorded the retrieval attempt that led to the abstention (query,
threshold, whatever it found below threshold), matching this ticket's own edge case: "a turn
with a single step — a valid one-step trace, not an empty one."

---

## 7. Traces fail open — an unwritable trace directory never fails an answer

### 28. Make the trace directory unwritable

```
podman compose exec api chmod 000 /var/lib/askwell/traces
```

**You should see:** no error (a mode-000 directory can still be `chmod`'d back).

### 29. Ask a question anyway

```
What is Meridian Corp's dispute contact?
```

**You should see:** an ordinary, complete answer — no error surfaced to the browser.

### 30. Confirm the API logged the failure rather than swallowing it silently

```
podman compose logs api --tail 50 | grep trace_write_failed
```

**You should see:** at least one `trace_write_failed` log line — the failure is visible to
someone reading logs, per `docs/audit-log.md` §2's own "fails open" contract, even though it
never reached the user.

### 31. Restore the directory's permissions

```
podman compose exec api chmod 755 /var/lib/askwell/traces
```

---

## 8. Clean up

```
podman compose down -v
rm -rf ~/askwell-test
```

**You should see:** no error.

---

## Known gaps

Not defects — deliberately not built by this ticket, or not demonstrable in this environment:

- **No trace panel.** `docs/ux/trace.md`'s rendered panel is `M5-TRACE-FE-119`, explicitly Out
  of Scope here. Every step above is read with `psql` against `messages.trace`, not opened in a
  browser.
- **Whether a real model touches every step kind in one document is not guaranteed.** §1–§3's
  fallback guidance exists because a small local model's own choice of tool, and whether it
  attempts a write at all, is not something a typed question can force byte-for-byte — the same
  caveat `M5-LOOP-BE-115.md`/`M5-LOOP-BE-116.md` already recorded for tool choice generally.
- **The 50-step truncation (§5) is exercised with a scripted call to `_bound_trace_steps`, not a
  real 51-step model turn.** Driving a real model through that many genuine steps in one
  question, on a two-source corpus, is not reliably drivable through the browser.
- **A turn that failed mid-answer** (the ticket's own "steps up to the failure plus the error"
  edge case) is covered by `api/tests/test_ask_api.py`'s audit-write-failure cases, not
  reproduced live here — forcing a mid-generation crash against a real model on demand is not a
  typed question either.
- **No live cold-start verification was performed while writing this document** — it was
  authored by reading `api/src/askwell/ask.py`, `api/src/askwell/traces.py`,
  `api/src/askwell/agent/sql_generate.py` and their tests directly, following the same gap
  several prior tickets in this epic recorded (`docs/BRAIN.md`'s `M5-LOOP-BE-115`/`-116`/`-117`
  entries, issue #376) — no inference bridge serving a model in that environment. Run this
  document against a real cold start before relying on it as proof rather than a script.
