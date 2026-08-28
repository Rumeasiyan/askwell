# Manual test — M1-ASK-BE-040: Generation continues server-side when the user navigates away

## What this ticket built

`POST /ask` now writes the assistant `messages` row as `running`, empty, in the same request
that starts the background task — not once generation finishes (`api/src/askwell/ask.py`).
`askwell.ask.reconcile_interrupted` runs once from `app.py`'s `lifespan`, before the first
request is served: it fails every assistant row still `running`, since nothing in the in-memory
`_turns` registry survives a restart. `Settings.generation_max_concurrent` (default 2,
`ASKWELL_GENERATION_MAX_CONCURRENT`) bounds concurrent retrieve-and-generate work through a
module-level semaphore. `GET /ask/counts` gained `abandoned`, counting rows
`reconcile_interrupted` failed.

**No browser is available in this environment**, and the frontend cannot yet rediscover a
message id after a hard page reload — `conversation_id` threading across turns is a separate,
still-open gap (issue #156). So this walkthrough proves the part that actually exists: the
backend keeps a turn alive independent of any one client connection, whether that connection
drops, reconnects, or the whole process restarts. Part 1 below is the closest thing to the
ticket's own step-by-step available today — driven with `curl` against the real session and SSE
contract, the same substitute `M1-ASK-API-038`'s own manual test used, because clicking through
a browser is not possible here. Part 3 is the automated suite, which does exercise the frontend
provider's "survives navigating away" logic (`web/lib/ask.ts`) against a stubbed backend.

**No native `llama.cpp` process runs in this environment**, the same limitation every ticket
since `M0-MODEL-BE-019` has recorded, so a real `POST /ask` here fails at generation with
`InferenceUnavailable` rather than producing real answer text. That failure is itself a
completed turn — `completed`/`stopped`/`failed` all count as "generation is over and the row
says so" for what this ticket needs to prove. The `running`-row-survives-a-restart path is
proven directly against Postgres instead (step 3 below), which does not need a real model.

## Prerequisites

- Podman installed, repo cloned, on branch `feat/m1-ask-be-040`.
- `podman compose up -d` — the stack needs Postgres.
- After pulling code, `scripts/dev.sh build-api` **and** `podman compose up -d` (`restart` reuses
  the existing image and will not pick up a rebuild).

## Part 1 — the pending row exists before any answer, and survives a dropped connection

1. Establish a session and ask a question, but cut the connection immediately instead of
   waiting for `curl` to read the response — this stands in for a user navigating away before
   the first token arrives:
   ```
   curl -s -c /tmp/cookies.txt -o /dev/null -H "accept: text/html" http://127.0.0.1:8000/
   curl -s -b /tmp/cookies.txt -X POST http://127.0.0.1:8000/ask \
     -H 'content-type: application/json' \
     -d '{"question":"How long is the notice period?"}' \
     --max-time 0.3 > /dev/null
   ```
   **What you should see:** the `curl` call itself times out or is cut off partway — that is
   the point, it mimics a browser tab closing mid-stream.

2. Confirm the row exists anyway, from a connection that had nothing to do with the request
   above:
   ```
   podman compose exec -T postgres psql -U askwell -d askwell -c \
     "SELECT role, trace->>'status' FROM messages ORDER BY created_at DESC LIMIT 2;"
   ```
   **What you should see:** two rows, `user` and `assistant`. The assistant row exists — proving
   it was written in the same request that started generation, not after — with status
   `running` if you query fast enough, or `failed` (an unavailable assistant, not this ticket's
   concern) once generation has already finished. Either way, the row was never absent.

3. Wait a couple of seconds for generation to finish (there is no model here, so it fails fast),
   then reconnect to the same message id — the "return after making coffee" step:
   ```
   MSG=$(podman compose exec -T postgres psql -U askwell -d askwell -tA -c \
     "SELECT id FROM messages WHERE role='assistant' ORDER BY created_at DESC LIMIT 1;" \
     2>/dev/null | tr -d '[:space:]')
   curl -s -b /tmp/cookies.txt "http://127.0.0.1:8000/ask/$MSG/stream"
   ```
   **What you should see:** a `done` event with a `status`, delivered immediately — not a hang,
   not a `running` row with nothing behind it. This is the ticket's validation rule ("a message
   must never remain pending with nothing generating it") holding for the ordinary case, where
   the process never restarted.

## Part 2 — the stack restarts mid-generation: failed, not stuck

This is the ticket's own named edge case, and the one a passing suite cannot show without a
running process to actually kill.

1. Insert a `running` row directly, standing in for a turn a process died in the middle of (no
   real generation can be made to run long enough to restart underneath it here, since there is
   no model — this reproduces the state a slow real generation would be in):
   ```
   podman compose exec -T postgres psql -U askwell -d askwell -c \
     "INSERT INTO conversations (id) VALUES (gen_random_uuid());"
   CONV=$(podman compose exec -T postgres psql -U askwell -d askwell -tA -c \
     "SELECT id FROM conversations ORDER BY created_at DESC LIMIT 1;" | tr -d '[:space:]')
   podman compose exec -T postgres psql -U askwell -d askwell -c \
     "INSERT INTO messages (id, conversation_id, role, content, trace) VALUES \
      (gen_random_uuid(), '$CONV', 'assistant', '', '{\"status\": \"running\", \"steps\": []}');"
   ```

2. Restart the API — this is what actually kills the process the `running` row belonged to:
   ```
   podman compose restart api
   podman compose logs api --tail 20 | grep ask_turns_reconciled
   ```
   **What you should see:** a log line naming `ask_turns_reconciled` with a `count` of at least
   1 — the reconciliation ran once at startup, before any request was served.

3. Read the row back:
   ```
   podman compose exec -T postgres psql -U askwell -d askwell -c \
     "SELECT trace->>'status', trace->>'interrupted', trace->>'reason' \
      FROM messages WHERE conversation_id = '$CONV';"
   ```
   **What you should see:** `status` is `failed`, `interrupted` is `true`, and `reason` names
   the restart (e.g. "Askwell restarted before this answer finished.") — the message is marked
   failed, never left pending forever.

4. Confirm `/ask/counts` reports it as `abandoned`, distinct from an ordinary inference failure:
   ```
   curl -s -b /tmp/cookies.txt http://127.0.0.1:8000/ask/counts
   ```
   **What you should see:** JSON with `abandoned` at least 1, and `failed` at least as large as
   `abandoned` (every abandoned turn is also counted as failed, but not every failed turn is
   abandoned).

5. Reconnect to the same id — a `running` row must never hang a reconnecting stream forever:
   ```
   curl -s -b /tmp/cookies.txt "http://127.0.0.1:8000/ask/$CONV/stream" 2>&1 | head -5
   ```
   Use the actual message id from step 1's insert, not the conversation id, if they differ —
   re-select it:
   ```
   MSG2=$(podman compose exec -T postgres psql -U askwell -d askwell -tA -c \
     "SELECT id FROM messages WHERE conversation_id = '$CONV' AND role='assistant';" \
     | tr -d '[:space:]')
   curl -s -b /tmp/cookies.txt "http://127.0.0.1:8000/ask/$MSG2/stream"
   ```
   **What you should see:** a `done` event with `status: failed`, returned immediately.

6. Clean up:
   ```
   podman compose exec -T postgres psql -U askwell -d askwell -c \
     "TRUNCATE conversations, messages, citations, audit_interactions CASCADE;"
   ```

## Part 3 — automated suite, read the output

```
scripts/dev.sh check
scripts/dev.sh test-db
```

**What you should see:** `check` — lint, format, `mypy --strict`, 425 passed / 1 skipped
(pre-existing, unrelated). `test-db` — 169 passed, up from 161: `test_ask_api.py` now covers the
pending row existing before generation runs, `reconcile_interrupted` failing a stale `running`
turn while leaving a genuinely completed one alone, idempotence on a clean database, bounded
concurrency (limit set to 1, a second turn's assistant provably untouched until the first
releases the semaphore), and the same question asked twice producing two independent completed
answers.

## Known gaps

- **Closing the tab entirely and reopening to see the completed answer — the ticket's own
  acceptance criterion — is not demonstrable.** The frontend has no way to recover a
  conversation or message id after a hard reload; `conversation_id` threading across turns is a
  separate open issue (#156, since `M1-ASK-FE-039`) and this ticket did not touch the frontend.
  What is proven here is the backend half only: a known message id reconnects correctly via
  `GET /ask/{id}/stream` whether the turn is live, finished, or was orphaned by a restart.
- **No browser was used for any step above.** Everything is `curl` against the real session/SSE
  contract, not a click-through — the same substitution `M1-ASK-API-038`'s and `M1-ASK-FE-039`'s
  own manual tests made for the same reason (no browser in this environment).
- **No real model runs here.** Every generation in this walkthrough ends `failed` at
  `InferenceUnavailable` rather than producing real answer text — a limitation recorded since
  `M0-MODEL-BE-019`. What this ticket needed to prove (the row exists before generation, survives
  a dropped connection, and a restart fails it rather than leaving it pending) does not depend
  on a real model finishing an answer.
- **Several abandoned generations at once, staying bounded, is not walked through manually
  above** — it is covered by the automated suite (`test-db`, bounded-concurrency test) instead,
  since reproducing genuine concurrent load by hand against a `curl` script would not exercise
  anything the semaphore test does not already prove more precisely.
- **No notification when an abandoned answer completes** — stated as a known gap in the ticket
  itself, not a defect.
