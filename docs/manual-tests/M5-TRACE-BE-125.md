# Manual test — M5-TRACE-BE-125, serve a stored trace to the browser

**Ticket:** `M5-TRACE-BE-125` — `GET /ask/{message_id}/trace` serves `messages.trace` over HTTP
for the first time, verbatim (C4 — never recomputed), including `trace_rotated` and
`steps_truncated`. A turn still running is served from a new `_Turn.trace_steps` accessor
instead of the database row, which does not exist until the turn ends.

**Version under test:** `0.4.35` (check `cat VERSION`).
**Time:** about 45 minutes, plus a first stack build and native inference running.
**Who can run it:** a browser, a terminal, `scripts/dev.sh psql` access, native `llama.cpp`
inference running on the host (`scripts/dev.sh inference`) — §1–§3 read what a real model
actually did; §4–§6 read the route against hand-inserted rows and work with no model at all.

**What is being checked.** `api/src/askwell/ask.py` — `_Turn.trace_steps`, the `trace_steps =
turn.trace_steps` alias in `_run_generation`, and the new `ask_trace` route — backed by six new
cases in `api/tests/test_ask_api.py`. This document repeats the headline behaviour — a finished
turn's route response matches its stored row exactly, an abstained turn's threshold and
near-miss scores survive the round trip, a running turn is readable before any row exists, an
unknown id is a 404, a message with no trace yet is a valid empty trace, and a rotated trace
says so — against a cold-started stack and the real HTTP route, which the automated suite
exercises through `TestClient` instead.

**Where this stops on purpose — read before reporting anything below as a defect.**

- **Nothing renders this in the browser.** `docs/ux/trace.md`'s panel is `M5-TRACE-FE-119`,
  explicitly Out of Scope here and still unbuilt. Calling the route with `curl` in this document
  is not a workaround standing in for a UI action — it *is* the deliverable this ticket ships;
  there is no click path to it yet.
- **§4 and §6 use hand-inserted rows, not a real model turn.** A message with `trace IS NULL`
  (a turn that failed before `_run_generation` ever wrote one) and a trace already marked
  `trace_rotated: true` are both states nothing in the browser can currently be driven into on
  demand — the automated suite proves them the same way, with a literal `INSERT`, and this
  document does too.
- **A live 51-step trace, and driving a real model through a long enough tool chain to be
  guaranteed still running when the route is called, are not reliably drivable through the
  browser on a small local model.** §3 uses a database question that in practice takes long
  enough to catch mid-flight; if it finishes before you can call the route, see the note there.

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

### Make a document corpus with one fact and one deliberate near-miss

```
mkdir -p ~/askwell-test/docs
cat > ~/askwell-test/docs/meridian-agreement.txt <<'EOF'
SUPPLIER AGREEMENT — MERIDIAN CORP — PAYMENT TERMS

Meridian Corp must be paid within 30 days of the invoice date. Standard order
minimum: $2500.
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

Plays the part of a database the user already runs, same pattern as `M5-LOOP-BE-117.md`.

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

### 7. Get a session cookie for the terminal calls below

```
curl -s -c /tmp/trace-cookies.txt -o /dev/null -H "accept: text/html" http://127.0.0.1:8000/
```

**You should see:** no output (the response was discarded) and `/tmp/trace-cookies.txt` now
exists — every `curl` call below reuses it with `-b`. A call with no cookie fails with `401 No
session.` rather than the row it asked for, which is worth doing once so a blank response later
isn't mistaken for the route itself failing:

```
curl -s http://127.0.0.1:8000/ask/00000000-0000-0000-0000-000000000000/trace
```

**You should see:** `{"error":"No session.", ...}` with no `-b` supplied — confirms the cookie is
what makes every call after this one work.

---

## 1. A finished turn's route response matches its stored row exactly

### 8. Ask a question answerable only from the document

In the browser, on the Ask screen, type:

```
What is Meridian Corp's standard order minimum?
```

**You should see:** an answer citing the $2500 minimum from the supplier agreement.

### 9. Find the message id

```
scripts/dev.sh psql -tAc "SELECT id FROM messages WHERE role = 'assistant' ORDER BY id DESC LIMIT 1;"
```

Note the id — call it `$MSG_ID`.

```
export MSG_ID=<the id you just read>
```

### 10. Call the route and compare it to the stored row, field by field

```
curl -s -b /tmp/trace-cookies.txt "http://127.0.0.1:8000/ask/$MSG_ID/trace"
```

```
scripts/dev.sh psql -c "SELECT trace FROM messages WHERE id = '$MSG_ID';"
```

**You should see:** the `curl` response's `steps` array — every step object, in order, with the
same `kind`s, durations and per-kind detail (`query`, `threshold`, `hits`, `claims`,
`citations`) — matching the `trace->'steps'` value `psql` printed, character for character.
`status` reads `completed` and `backend` names the real `.gguf` model loaded, in both. Nothing
in the route's response was recomputed from the answer text or the citations table — it is the
same JSON blob `psql` is reading, served back unchanged.

---

## 2. An abstained turn round-trips its threshold and near-miss scores

### 11. Ask something the document doesn't cover

```
What does the agreement say about a supplier named Nonexistent Corp?
```

**You should see:** an abstention — Askwell states it found nothing in your files.

### 12. Find the new message id and call the route

```
scripts/dev.sh psql -tAc "SELECT id FROM messages WHERE role = 'assistant' ORDER BY id DESC LIMIT 1;"
export MSG_ID2=<the id you just read>
curl -s -b /tmp/trace-cookies.txt "http://127.0.0.1:8000/ask/$MSG_ID2/trace"
```

**You should see:** a `retrieve` step whose `threshold` reads `0.65` (unless
`ASKWELL_RETRIEVAL_SCORE_THRESHOLD` was changed in `.env`) and whose `hits` array's scores are
all below that threshold, plus an `abstain` step whose `reason_code` reads `below_threshold` —
the exact numbers that produced the abstention, not a threshold read from current configuration.
Reopening this old answer six months from now, after the default threshold has changed, must
still show the threshold as it was *then* — this is what proves it does.

---

## 3. A turn still running is served from its own steps, not a database row

### 13. Start a database question in the background and capture its stream

```
curl -s -b /tmp/trace-cookies.txt -N -X POST http://127.0.0.1:8000/ask \
  -H 'content-type: application/json' \
  -d '{"question":"According to the database, how many days late was Meridian Corp actually paid?"}' \
  > /tmp/trace-stream.txt &
sleep 1
```

### 14. Read the message id off the stream while it is still running

```
grep -m1 -o '"message_id": *"[0-9a-f-]*"' /tmp/trace-stream.txt
export MSG_ID3=<the uuid printed above>
```

**You should see:** a message id — every event carries it, including the first `step`, so it is
available before the turn has finished.

### 15. Call the route immediately, before the background turn ends

```
curl -s -b /tmp/trace-cookies.txt "http://127.0.0.1:8000/ask/$MSG_ID3/trace"
```

**You should see:** `"status": "running"` and a non-empty `steps` array (at minimum, "Checking
your connected databases.") — read from `_Turn.trace_steps` directly, since `_run_generation`
has not written `messages.trace` yet. `trace_rotated` reads `false`.

**If the turn had already finished by the time you called this** (a fast model, or the SQL
answer resolving from the file instead of the database): repeat steps 13–15 — the timing is
what varies, not the behaviour; re-run the background call and issue step 15's `curl` sooner.

### 16. Wait for it to finish and confirm the story matches

```
wait
curl -s -b /tmp/trace-cookies.txt "http://127.0.0.1:8000/ask/$MSG_ID3/trace"
```

**You should see:** `"status": "completed"` now, with a superset of the steps step 15 showed —
the same turn, read from the database this time because it is no longer in the running registry,
not a different one.

---

## 4. An unknown message id is a 404

### 17. Call the route with an id nothing ever used

```
curl -s -o /dev/null -w '%{http_code}\n' -b /tmp/trace-cookies.txt \
  "http://127.0.0.1:8000/ask/11111111-2222-3333-4444-555555555555/trace"
```

**You should see:** `404`.

---

## 5. A message with no trace yet is a valid empty trace, not a 404

Reproduces the ticket's own named edge case — a turn that failed before `_run_generation` ever
wrote a trace — with a hand-inserted row, the same substitution the automated suite makes for a
state nothing in the browser can currently be driven into.

### 18. Insert a message with `trace IS NULL`

```
scripts/dev.sh psql -tAc "
INSERT INTO conversations (id) VALUES (gen_random_uuid())
RETURNING id;
"
```

Note the printed id as `$CONV_ID`.

```
export CONV_ID=<the id you just read>
scripts/dev.sh psql -tAc "
INSERT INTO messages (id, conversation_id, role, content)
VALUES (gen_random_uuid(), '$CONV_ID', 'assistant', '')
RETURNING id;
"
```

Note the printed id as `$MSG_ID4`.

### 19. Call the route

```
export MSG_ID4=<the id you just read>
curl -s -b /tmp/trace-cookies.txt "http://127.0.0.1:8000/ask/$MSG_ID4/trace"
```

**You should see:** exactly `{"steps":[],"steps_truncated":false,"trace_rotated":false}` and an
HTTP `200`, not a `404` — the message exists, it simply never got a trace written.

---

## 6. A rotated trace says so, rather than 404ing or returning an empty object

### 20. Insert a message with a trace already marked rotated

```
scripts/dev.sh psql -tAc "
INSERT INTO conversations (id) VALUES (gen_random_uuid())
RETURNING id;
"
export CONV_ID2=<the id you just read>
scripts/dev.sh psql -tAc "
INSERT INTO messages (id, conversation_id, role, content, trace)
VALUES (
  gen_random_uuid(), '$CONV_ID2', 'assistant', 'Ninety days.',
  '{\"steps\": [], \"steps_truncated\": false, \"trace_rotated\": true, \"status\": \"completed\", \"backend\": {\"mode\": \"local\", \"model\": \"qwen3-8b-q4km\"}}'::jsonb
)
RETURNING id;
"
```

Note the printed id as `$MSG_ID5`.

### 21. Call the route

```
export MSG_ID5=<the id you just read>
curl -s -b /tmp/trace-cookies.txt "http://127.0.0.1:8000/ask/$MSG_ID5/trace"
```

**You should see:** `"trace_rotated": true`, `"steps": []`, and `"status": "completed"` — the
old summary and backend still readable, just no step-by-step detail, matching this ticket's
Acceptance Criterion that a rotated trace answers with the flag set rather than a `404` or an
empty object.

---

## 7. Clean up

```
podman compose down -v
rm -rf ~/askwell-test /tmp/trace-cookies.txt /tmp/trace-stream.txt
```

**You should see:** no error.

---

## Known gaps

Not defects — deliberately not built by this ticket, or not demonstrable in this environment:

- **No trace panel renders any of this.** `docs/ux/trace.md`'s panel is `M5-TRACE-FE-119`,
  explicitly Out of Scope for this ticket. Every response above is read with `curl`, not opened
  in a browser — there is no click path to a trace yet.
- **§5 and §6 use hand-inserted rows rather than a real model turn**, for the same reason the
  automated suite does: nothing in the browser today can be driven into "failed before any trace
  was written" or "the file ring buffer already rotated this one out" on demand. `M5-LOOP-BE-117`
  is what actually rotates a trace through real use (see `docs/manual-tests/M5-LOOP-BE-117.md`
  §4 for that walkthrough); this document only proves the route's response shape for a trace
  already in that state.
- **Catching a turn genuinely mid-flight (§3) depends on model speed and tool choice**, which a
  typed question cannot force byte-for-byte — the same caveat every prior ticket in this epic's
  manual test has carried. If the model answers the database question from the document instead
  of routing to SQL, the turn may finish before the background `curl` can be caught running;
  re-running steps 13–15 is the fix, not a defect in the route.
- **A trace larger than the 50-step per-turn bound (`_bound_trace_steps`) is not reproduced live
  here.** `docs/manual-tests/M5-LOOP-BE-117.md` §5 already reproduces that bound directly against
  `_bound_trace_steps`, and this ticket's own route calls the identical function for a running
  turn's steps — nothing about serving them over HTTP changes what gets truncated or when.
