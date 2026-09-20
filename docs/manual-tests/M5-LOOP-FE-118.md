# Manual test — M5-LOOP-FE-118, step labels for multi-step turns

**Ticket:** `M5-LOOP-FE-118` — extends `M5-LOOP-BE-117a`'s live per-call `step` events all the
way to the screen. `api/src/askwell/ask.py`'s `_tool_call_step` now names both phases of a call
(`"Searching your files."` on `start`, `"Searched your files."` — or, on failure, `"…That didn't
work — trying another way."` — on `end`), each event carrying the same `call_id` across its
`start` and `end`. `web/lib/ask.ts::applyAskEvent` keys on that `call_id`: a step with one is
updated in place (`start` replaced by `end` for the same call); a step without one (retrieval,
SQL, the generic loop-progress lines) is always appended, unchanged from before this ticket.
`ask-screen.tsx`'s `LiveTurn` renders every live step joined by `" · "`, so two calls dispatched
together — each its own entry, each updated independently — read as concurrent, not a queue.

**Version under test:** check `cat VERSION` (`0.4.34` at the time this document was written —
this ticket's own changes are present on disk but not yet committed to a numbered release; treat
the working tree, not a tag, as what is under test).
**Time:** about 40 minutes, plus a first stack build and native inference running.
**Who can run it:** a browser with developer tools, a terminal, `podman compose exec`/
`scripts/dev.sh psql` access, native `llama.cpp` inference running on the host
(`scripts/dev.sh inference`). Like the rest of this epic, a real model's own choice of which
tools to call, and how many, cannot be forced turn by turn.

**Where this stops on purpose — read before reporting anything below as a defect.**

- **No trace panel.** Every step is read back with `psql` against `messages.trace`, or watched
  live in the browser's own developer tools against the SSE stream — `docs/ux/trace.md`'s
  rendered panel is a later ticket, and explicitly Out of Scope for this one.
- **Live per-call steps only render on a hybrid (document + database) corpus.** They come from
  `run_tool_loop`, which `askwell.ask._has_hybrid_sources` only tries when the corpus is
  genuinely both — a documents-only or database-only corpus still uses the older, single-shot
  retrieval path and its own pre-existing `step` events (`_label_for_sources`, etc.), which this
  ticket does not change. The cold-start setup below builds a hybrid corpus for that reason.
- **Source-scoped wording (`querying sales-2024`) is not built.** Every label names the
  operation (`Searching your files.`) but never a specific source name — `ToolCallEvent.
  arguments` carries only IDs the observer cannot resolve to a name without an extra database
  read, filed as issue #422 rather than guessed at. The worked example in the ticket's own
  description (`querying sales-2024`) is aspirational; do not fail this document over it.
- **A small local model does not reliably call two tools in the same turn, or run past 20
  seconds, on command.** §1 and §2 use a corpus and questions built to make each likely, with a
  documented fallback if the model chooses otherwise, same approach as every prior ticket in
  this epic.
- **Citations for a loop-answered turn** are a separate, already-tracked follow-up (issue #407)
  and are not exercised here.

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
banner, and the first-run empty state on the Ask screen. Open the browser's developer tools now
(e.g. F12) and switch to its Network tab — you will use it in §1.

### 4. Add the supplier agreement, by clicking

Click **Add a source**. In the **Files** section, click **Choose files** and select
`meridian-agreement.txt`. Answer any folder-nomination prompt by clicking its suggested folder.
**You should see:** the file appears in the batch list and moves to **Indexed** (or **Ready**)
within a few seconds.

### 5. Stand up a database to connect to

Plays the part of a database the user already runs, same pattern as the rest of this epic.

```
podman compose exec sandbox psql -U "$(grep ^SANDBOX_POSTGRES_USER .env | cut -d= -f2)" -d postgres <<'SQL'
CREATE DATABASE steplabels_test OWNER askwell_sandbox_owner;
SQL
```

**You should see:** `CREATE DATABASE`.

```
podman compose exec sandbox psql -U askwell_sandbox_owner -d steplabels_test <<'SQL'
CREATE TABLE payments (
    supplier text not null,
    invoice_date date not null,
    paid_date date not null
);
INSERT INTO payments VALUES
    ('Meridian Corp', '2026-06-01', '2026-07-16');
GRANT CONNECT ON DATABASE steplabels_test TO askwell_sandbox_readonly;
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
`sandbox`, Port `5432`, Database `steplabels_test`, User `askwell_sandbox_readonly`, Password
(from step 5). Click **Connect**.

**You should see:** a queued/ready confirmation naming `steplabels_test`; the library shows it
as **Ready** after a few seconds. The corpus is now hybrid — one document, one connected
database — which is what routes a question through `run_tool_loop` at all.

---

## 1. A hybrid question's labels appear as each step starts, name the real operation, and show parallel calls concurrently

### 7. Ask a question that plausibly needs both the document and the database

Go to **Ask**. In the composer, type:

```
Using both the agreement and the database, is Meridian Corp actually being paid within the
required 30 days?
```

Click **Ask** (or press Enter) and immediately start watching the line under the composer — do
not look away for the first second.

**You should see, within about 400ms of clicking Ask:** the first label appear (e.g. `Working
through this in steps.` or `Searching your files.`) — never a bare, unlabelled spinner. This is
the ticket's own performance budget (`docs/ux/ask.md` §7, "first step label visible < 400ms of
submit").

### 8. Confirm a label names the real operation, not a generic placeholder

Keep watching. **You should see** labels drawn from the real tool being called, never a raw tool
name or a generic "working…": `Searching your files.` / `Searched your files.` for
`document_search`, `Querying your database.` / `Queried your database.` for `database_query`
(also `Looking up your database schema.` / `Looked up your database schema.` for `schema_lookup`,
and `Listing your documents.` / `Listed your documents.` for `document_listing`, if the model
uses either).

### 9. Confirm a call's label updates in place rather than appending a second line

Watch one label specifically as its call finishes. **You should see** the starting wording
(`Searching your files.`) replaced by the finished wording (`Searched your files.`) in the same
position in the line — the line does not grow by one extra segment when a call that already has
a visible label finishes. Compare against §11 below if this is hard to catch live.

### 10. Confirm two calls dispatched together render as concurrent, not a queue

If the model called both tools in the same turn: **you should see**, for a moment, two labels
both showing their *starting* wording at once, joined by `" · "` (e.g. `Searching your files. ·
Querying your database.`), before either shows its finished wording — proof they are two live
entries rather than one waiting behind the other. Each then flips to its own finished wording
independently, not both at the same instant.

**If the model only used one tool** (a small model may decide the document alone answers it, or
vice versa): re-ask, naming the tool you want it to prefer, e.g. "Check the `payments` table in
the connected database, and separately check what the agreement says the terms should be" — or
accept a single-call turn, confirm just the one label's start-to-finish transition, and continue
to §2 regardless. §11's scripted repro proves the concurrent-rendering property either way.

### 11. Confirm the trace recorded one step per call, matching what you saw

```
scripts/dev.sh psql -c "SELECT id FROM messages WHERE role = 'assistant' ORDER BY id DESC LIMIT 1;"
```

Note the `id` as `$MSG_ID`.

```
scripts/dev.sh psql -c "
SELECT step->>'tool', step->>'deduplicated', step->>'outcome'
FROM messages, jsonb_array_elements(trace->'steps') AS step
WHERE id = '$MSG_ID' AND step->>'kind' = 'tool';
"
```

**You should see:** one row per tool call the model actually made this turn (`document_search`
and/or `database_query`), `deduplicated` reading `false` for each. The row count here should
match the number of distinct labels you watched resolve in §8–§10 (the trace itself records only
the finished step per call, not a separate row for its `start`).

---

## 2. Labels keep changing past the twenty-second mark

### 12. Ask a broad question likely to take several tool calls

```
Walk through everything you can find about Meridian Corp — the agreement terms, the actual
payment history in the database, and whether they match — and explain any discrepancy.
```

Click **Ask**. On a slow local model this plausibly runs past 20 seconds before the answer
starts streaming (`docs/ux/ask.md` §5's own "this can run 20s+" note).

**You should see:** the label line keeps changing — a new tool label, `Continuing where it left
off.`, or eventually `Stopped after 8 steps for this question.` if the model hits the loop's
call ceiling — never a label frozen unchanged for the whole wait. An unlabelled or static spinner
past 20 seconds is the exact "hung" impression this ticket exists to prevent.

**If the turn answers in under 20 seconds:** re-ask, or ask a second, broader follow-up in the
same style, until one genuinely runs long — or accept that this local model and corpus are fast
enough that the budget was never at risk, and move to §3.

---

## 3. Edge cases from the ticket itself

### 13. A very fast turn — labels appear and clear without flicker

Ask a trivial question the hybrid corpus can answer in one call or none, e.g.:

```
What is today's date?
```

**You should see:** if a label appears at all, it appears once, briefly, and disappears cleanly
when the answer starts streaming — no label appearing then instantly being replaced by a
different, contradictory one, and no label lingering after the answer is already visible
(`LiveTurn` in `ask-screen.tsx` only renders the step line while `isRetrieving || isStreaming`
is true, i.e. only while the turn is still running).

### 14. A turn that stops early — labels end with the stop, not hanging

Ask a question likely to run for several seconds (reuse §12's question). While it is still
showing step labels, click **Stop** underneath the composer.

**You should see:** the step line disappears (or freezes on its last value) and is replaced by
`Stopped. The answer above is partial.` — the labels do not keep changing after the stop, and no
label is left implying work is still happening.

### 15. A tool error — the label reflects the retry, not a freeze

Hard to force from the UI alone (every tool in this corpus is expected to succeed against a
healthy sandbox). Confirm the wording exists instead:

```
grep -n "trying another way" api/src/askwell/ask.py
```

**You should see:** the line building `f"{starting} That didn't work — trying another way."` for
any `end` event whose `outcome` is not `"ok"` — e.g. `Querying your database. That didn't work —
trying another way.` — rather than the label simply freezing on its starting wording. §16 proves
this against the real code without needing a real failure.

### 16. Run the scripted repro directly against the real step-mapping code

No model or stack access needed — this is `api/tests/test_ask_tool_step_labels.py`, run live.

```
scripts/dev.sh test api/tests/test_ask_tool_step_labels.py
```

**You should see:** all 5 tests pass, including
`test_an_end_names_the_failed_call_as_a_change_of_approach_not_a_freeze` and
`test_the_call_id_and_phase_travel_so_the_frontend_can_key_on_them` — the two properties §9's
"in place" claim and §15's failure wording rest on when a real failure cannot be triggered live.

### 17. Confirm the frontend's own in-place-update logic with its unit tests

```
scripts/dev.sh web-run npx vitest run web/lib/ask.test.ts
```

**You should see:** the suite pass, including whatever cases cover `applyAskEvent`'s `call_id`
branch (a `start` and an `end` sharing a `call_id` collapsing to one entry; two different
`call_id`s staying two entries; a step with no `call_id` always appending).

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

- **No trace panel.** Every step here is read back with `psql` or watched live against the raw
  SSE stream; `docs/ux/trace.md`'s rendered panel is a later, separate ticket.
- **Source-scoped wording is not built** (e.g. `querying sales-2024`) — every label names the
  operation only, never a specific source name (issue #422).
- **Live per-call steps only exist on a hybrid corpus.** A documents-only or database-only
  corpus never reaches `run_tool_loop` and so never shows this ticket's concurrent, in-place-
  updating labels — it uses the pre-existing single-shot retrieval labels instead, unchanged by
  this ticket.
- **Whether a real model calls more than one tool in the same turn, or runs past 20 seconds, is
  not guaranteed on command.** §1 and §2's fallback guidance exists because a small local
  model's own choice of tool use and pacing cannot be forced byte-for-byte, same caveat every
  prior ticket in this epic recorded.
- **The exact wall-clock gap between a call's start and its end, or between two parallel calls,
  is not something the browser lets you measure precisely** — watching the label line is good
  enough to see the transition and the concurrency; `test_loop.py`'s
  `test_a_batchs_starts_all_arrive_before_any_of_its_ends` (exercised indirectly by §16's sibling
  suite `test_loop.py`, not reproduced again here since `M5-LOOP-BE-117a.md`'s §3 already covers
  it) is the actual proof of the server-side ordering contract.
- **Citations for a loop-answered turn** are a separate, already-tracked follow-up (issue #407)
  and are not exercised here.
- **No live cold-start verification was performed while writing this document** — it was
  authored by reading `api/src/askwell/ask.py`, `web/lib/ask.ts`, `web/components/ask/
  ask-state.tsx` and `web/components/ask/ask-screen.tsx` directly, plus the sibling
  `M5-LOOP-BE-117a.md` this ticket extends, following the same gap several prior tickets in this
  epic recorded (`docs/BRAIN.md`'s `M5-LOOP-BE-115`/`-116`/`-117`/`-117a` entries, issue #376) —
  no inference bridge serving a model in that environment. Run this document against a real cold
  start before relying on it as proof rather than a script.
