# Manual test — M5-LOOP-BE-115, multi-step loop with parallel calls

**Ticket:** `M5-LOOP-BE-115` — `POST /ask` now tries `askwell.agent.loop.run_tool_loop` for a
corpus that is genuinely both documents and a database: it asks the model for a JSON decision,
calls every tool the model names in one turn concurrently, feeds the results back, and repeats
until the model says it has enough. A repeated call is deduplicated; a tool error is told to the
model as data, not raised.
**Version under test:** `0.4.29` (check `cat VERSION`).
**Time:** about 60 minutes, plus a first stack build and native inference running.
**Who can run it:** a browser, a terminal, `podman compose exec`/`scripts/dev.sh psql` access,
native `llama.cpp` inference running on the host (`scripts/dev.sh inference`) — this ticket is
about what the model itself decides to call, so a walkthrough with no model loaded cannot exercise
it (unlike several `M4-RESULT-FE-*` documents, which substituted direct database writes for a
missing model).

**What is being checked.** `api/src/askwell/agent/loop.py` (`run_tool_loop`, `LoopStep`,
`LoopResult`), `api/src/askwell/agent/prompts/tool_loop.v1.md`, and the wiring into
`api/src/askwell/ask.py` (`_has_hybrid_sources`, the `loop_answer` branch in `_run_generation`).
Backed by `api/tests/test_loop.py` (the loop itself, with a fake model and fake tools) and
`api/tests/test_ask_hybrid_sources_db.py` (the gate, against real rows). This document repeats
the loop's headline behaviour — two independent lookups run together, a tool error recovers, the
answer cites both a document and a database — against a cold-started stack with a real model
deciding what to call, which the automated suite fakes.

**Where this stops on purpose — read before reporting anything below as a defect.**

- **There is no trace panel yet.** `docs/ux/trace.md` is a Phase 4 specification with nothing
  built against it in `web/` (`grep -rn "trace" web/components` finds only third-party build
  tooling) — the TRACE epic is this ticket's own named Out of Scope. "Open the trace and confirm
  the sequence" (the ticket's own Testing Notes) is done here by reading `messages.trace` back
  with `scripts/dev.sh psql`, not by clicking a panel. The retrieving-state step *labels* (`Called
  document_search.`, etc.) do render live in the browser — see §2 below — that much of "the trace
  shows named steps" is genuinely on screen.
- **A small local model's choice of which tools to call, in what order, and whether it produces
  valid SQL is not fully predictable.** The worked scenario below is built to make the hybrid path
  and a real tool error both likely, but "the model called `document_search` then
  `database_query`" and "the generated SQL was rejected" are both things the model decides, not
  something this document can force byte-for-byte. Where that matters, it is called out with what
  to do if the model chooses differently.
- **No call ceiling exists yet** — `_SAFETY_MAX_ITERATIONS` (25) is a crash guard, not the
  8-step ceiling with a **Continue** control `M5-LOOP-BE-116` will add (`docs/ux/ask.md` §5's
  "Tool ceiling hit" row has nothing behind it yet). Nothing below exercises hitting either
  bound.
- **Citations for a loop-answered turn are not wired to the provenance margin** — issue #407,
  named in `ask.py`'s own comment above the `loop_answer` branch. The model's `[1]`/`[2]` markers
  reach `messages.content` as it wrote them; no `citation` event fires and the margin stays empty
  for this turn. Confirming the answer *names* both sources in its prose is what this document
  checks; an empty margin next to it is expected, not a defect.

---

## Before you start

```
cd ~/external/quantum-plus/askwell
```

If you have never run Askwell before:

```
cp -n .env.example .env
```

Open `.env` and confirm every `?set ... in .env` placeholder has a real value. Note
`SANDBOX_POSTGRES_USER` and `SANDBOX_READONLY_PASSWORD` — used in §1 below, the same live-connection
pattern `docs/manual-tests/M4-CONN-FE-096.md` established (`api`/`worker` can reach `sandbox` by
name on the Compose network; this is not real egress).

### Make the document half of the corpus

```
mkdir -p ~/askwell-test/docs
cat > ~/askwell-test/docs/supplier-agreement.txt <<'EOF'
SUPPLIER AGREEMENT — PAYMENT TERMS

All suppliers must be paid within 30 days of the invoice date. A payment made
later than 30 days after the invoice date is a breach of this agreement and
must be reported to procurement.
EOF
```

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
banner, and the first-run empty state on the Ask screen — no composer yet, since nothing has been
added.

### 4. Add the supplier agreement, by clicking

Click **Add a source** in the rail. In the **Files** section, click **Choose files** and pick
`~/askwell-test/docs/supplier-agreement.txt`. Answer any folder-nomination prompt Askwell shows
by clicking its suggested folder. **You should see:** the file appear in the batch list, then
move to **Indexed** (or **Ready**) within a few seconds.

### 5. Stand up a database to connect to

This plays the part of "a database the user already runs" — inside `sandbox`, the only Postgres
instance `api`/`worker` can reach by name (`docs/manual-tests/M4-CONN-FE-096.md`'s own pattern).

```
podman compose exec sandbox psql -U "$(grep ^SANDBOX_POSTGRES_USER .env | cut -d= -f2)" -d postgres <<'SQL'
CREATE DATABASE loop_test OWNER askwell_sandbox_owner;
SQL
```

**You should see:** `CREATE DATABASE`.

```
podman compose exec sandbox psql -U askwell_sandbox_owner -d loop_test <<'SQL'
CREATE TABLE payments (
    supplier text not null,
    invoice_date date not null,
    paid_date date not null
);
INSERT INTO payments VALUES
    ('Acme Corp', '2026-06-01', '2026-07-16'),
    ('Globex Ltd', '2026-06-01', '2026-06-20');
GRANT CONNECT ON DATABASE loop_test TO askwell_sandbox_readonly;
GRANT USAGE ON SCHEMA public TO askwell_sandbox_readonly;
GRANT SELECT ON payments TO askwell_sandbox_readonly;
SQL
```

**You should see:** `CREATE TABLE`, `INSERT 0 2`, three `GRANT`s. Acme was paid 45 days after
invoice — a breach of the 30-day term in the document; Globex was paid on time.

Note the readonly password:

```
grep ^SANDBOX_READONLY_PASSWORD .env
```

### 6. Connect to it, by clicking

Still on **Add a source**, in the **Connect a database** section: Engine `PostgreSQL`, Host
`sandbox`, Port `5432` (unchanged), Database `loop_test`, User `askwell_sandbox_readonly`,
Password (the value from step 5). Click **Connect**.

**You should see:** the button read "Connecting…" briefly, then a queued/ready confirmation
naming `loop_test`. Give it a few seconds, then check the library shows it as **Ready** — a
question asked while it is still indexing will not be treated as hybrid (`_has_hybrid_sources`'s
own "still indexing does not count yet" rule, `api/tests/test_ask_hybrid_sources_db.py`).

---

## 1. A question needing both a document and a database is answered in one turn

### 7. Ask the hybrid question

Go to **Ask**. In the composer (placeholder "Ask about your own files and databases"), type:

```
Which suppliers are we paying later than our contract allows?
```

Click **Ask** (or press Enter).

**You should see, while it is working:** named steps appear and join with " · " as they land —
at minimum `Checking your connected databases.` and `Working through this in steps.`, followed by
`Called document_search.` and/or `Called database_query.` as the model's tool calls come back.
This is the live, on-screen half of "the trace shows named steps" — no panel needed to see it.

**You should see, once it answers:** a prose answer stating that Acme Corp (or whichever supplier
you seeded as late) was paid outside the 30-day term, naming both the 30-day figure and the actual
gap between invoice and payment dates, with bracketed markers like `[1]` and `[2]` in the text.
The provenance margin stays empty for this turn — expected, see "Where this stops on purpose".

**If instead you see `Answered from your database.` with no document-related step:** the model
decided this was answerable from `_run_sql_turn` alone before the loop ever ran (`ask.py` tries
that path first, on every turn, and only falls through to the loop if it returns `None`). Ask a
follow-up in the same conversation that explicitly requires the contract wording, e.g. "What does
our contract say the payment term is, and which supplier breaks it?" — a question that names both
halves explicitly is markedly more likely to make a small model reach for both tools.

### 8. Confirm the answer actually cites both kinds of source

Read the answer text itself (not the margin, which is empty). **You should see:** a number tied to
the 30-day term (from the document) and a number tied to how late the payment was (from the
database), in the same answer — not one half silently dropped.

---

## 2. The trace: two independent calls in the same iteration, overlapping in time

### 9. Find the message id

```
scripts/dev.sh psql -c "SELECT id, content FROM messages WHERE role = 'assistant' ORDER BY id DESC LIMIT 1;"
```

Note the `id` — call it `$MSG_ID`.

### 10. Read back the loop's own steps

```
scripts/dev.sh psql -c "
SELECT step->>'iteration' AS iteration,
       step->>'tool' AS tool,
       step->>'outcome' AS outcome,
       step->>'started_offset_ms' AS started_ms,
       step->>'duration_ms' AS duration_ms,
       step->>'deduplicated' AS deduplicated
FROM messages, jsonb_array_elements(trace->'steps') AS step
WHERE id = '$MSG_ID' AND step->>'kind' = 'tool'
ORDER BY (step->>'result_index')::int;
"
```

**You should see:** one row per tool call the loop actually made. If the model called
`document_search` and `database_query` together (§1's ordinary case), both rows carry the same
`iteration` and their `[started_ms, started_ms + duration_ms]` ranges overlap — that overlap *is*
"the trace shows overlapping durations", the ticket's own acceptance criterion, read directly
rather than through a panel that does not exist yet.

### 11. Confirm the top-level trace records how the loop ended

```
scripts/dev.sh psql -c "SELECT trace->>'loop_iterations', trace->>'loop_stopped_reason' FROM messages WHERE id = '$MSG_ID';"
```

**You should see:** `loop_stopped_reason` reading `answered` — the loop stopped because the model
said it had enough, not because anything counted turns for it (the ticket's own "terminates when
the model has enough, not on a fixed count").

---

## 3. A tool error mid-loop is told to the model, and the turn recovers

### 12. Take away the database's read permission

```
podman compose exec sandbox psql -U askwell_sandbox_owner -d loop_test <<'SQL'
REVOKE SELECT ON payments FROM askwell_sandbox_readonly;
SQL
```

**You should see:** `REVOKE`. `loop_test` is still connected and still `ready` — nothing about
the source itself changed, only whether a query against it can actually read anything.

### 13. Ask a question that needs the database again

In the same conversation, ask:

```
Check the database again — exactly how many days late was Acme Corp paid, according to our
contract's 30-day term?
```

**You should see:** the turn still finishes with a plain-language answer — not a 500, not a blank
response. It should say something to the effect of not being able to read the payment records
right now (a permissions failure surfaces from `askwell.sql_execute` as a query-time failure the
loop's `database_query` tool call gets back as a `ToolError`), while still being able to restate
the 30-day contract term from the document if the model reaches for `document_search` again.
Exactly how the model phrases the recovery varies; what must hold is that the turn **completes**
rather than failing outright.

### 14. Confirm the error reached the model as data, not a crash

```
scripts/dev.sh psql -c "
SELECT step->>'tool', step->>'outcome', step->>'iteration'
FROM messages, jsonb_array_elements(trace->'steps') AS step
WHERE id = (SELECT id FROM messages WHERE role = 'assistant' ORDER BY id DESC LIMIT 1)
  AND step->>'kind' = 'tool'
ORDER BY (step->>'result_index')::int;
"
```

**You should see:** a `database_query` row whose `outcome` is not `ok` (a rejection/failure
outcome, not `ok`), and — if the model tried again afterwards — a later row for the same or a
different tool at a higher `iteration` number, evidence the loop kept going rather than stopping
dead on the failed call. This is the same shape `api/tests/test_loop.py`'s
`test_a_tool_error_mid_loop_is_told_to_the_model_and_the_turn_recovers` locks in with a fake tool
and a scripted model response; here it is a real permissions failure and a real model deciding
what to do next.

**If the `outcome` column instead reads `ok`:** the model did not call `database_query` again for
this question — re-ask more directly ("query the database for Acme Corp's payment date") so it
does, since the point being checked is what happens *when the call is made*, not that it is made.

### 15. Restore the permission (cleanup for step 16)

```
podman compose exec sandbox psql -U askwell_sandbox_owner -d loop_test <<'SQL'
GRANT SELECT ON payments TO askwell_sandbox_readonly;
SQL
```

---

## 4. Clean up

```
podman compose down -v
rm -rf ~/askwell-test
```

**You should see:** no error.

---

## Known gaps

Not defects — deliberately not built by this ticket, or not demonstrable in this environment:

- **No trace panel.** `docs/ux/trace.md` is unbuilt; §2 above reads `messages.trace` directly
  with `psql` rather than clicking a panel, per this ticket's own Out of Scope line.
- **No call ceiling.** `_SAFETY_MAX_ITERATIONS` (25) exists only to stop a genuinely runaway loop
  from consuming the request forever; there is no user-visible "stopped after 8 steps" state or
  **Continue** control yet (`M5-LOOP-BE-116`, `docs/ux/ask.md` §5's "Tool ceiling hit" row).
  Nothing above deliberately drives a question toward that many iterations.
- **No citations for a loop-answered turn.** The model's `[N]` markers land in the answer text as
  written; no `citation` event fires and the provenance margin stays empty for these turns
  (issue #407, named directly in `ask.py`). §1 above checks the prose names both sources; it does
  not check margin cards, because there are none for this path yet.
- **Deduplication (the same call emitted twice) is not exercised by hand here.** Reliably making
  a real small local model ask for the identical tool call twice, on purpose, inside one turn is
  not something a question can be worded to force — `api/tests/test_loop.py`'s
  `test_a_duplicate_call_is_not_re_executed` and
  `test_two_identical_calls_in_the_same_turn_are_deduplicated_too` are the authoritative proof for
  this behaviour, with a scripted model response that repeats a call on purpose.
- **Only one hybrid corpus shape was exercised** — one document, one live-connected database. A
  dump-backed database source behaves identically as far as the loop is concerned (`database_query`
  runs the same checked pipeline regardless of `sources.kind`), so this is a coverage choice, not
  a gap in the mechanism.
- **The exact sequence of tool calls a real model chooses is not something this document can
  pin down byte-for-byte** — see "Where this stops on purpose". What is checked is the properties
  the ticket cares about (parallel calls overlap, a repeat is deduplicated, an error recovers,
  the loop stops when the model says so), not one specific transcript.
