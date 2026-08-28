# Manual test — M1-ASK-API-038: Server-sent answer streaming with named retrieval steps

## What this ticket built

`api/src/askwell/ask.py` — `POST /ask`, `GET /ask/{message_id}/stream`, `POST
/ask/{message_id}/stop`. A question starts a background generation task that outlives the HTTP
request that started it; the stream any browser watches only tails it. `InferenceClient` gained
`stream_generate`, over llama.cpp's own SSE `/completion` response.

**No native `llama.cpp` process runs in this environment**, the same limitation every ticket
since `M0-MODEL-BE-019` has recorded, so Part 2 below shows the honest failure path — retrieval
running for real, generation failing with `InferenceUnavailable` — rather than a real answer.
Part 3 (automated) exercises the full path, tokens and citations included, against a stubbed
`InferenceClient`.

## Prerequisites

- Podman installed, repo cloned, on branch `feat/m1-ask-api-038`.
- `podman compose up -d` — the stack needs Postgres for `/ask` to do anything.
- After pulling code changes, `scripts/dev.sh build-api` **and** `podman compose up -d` (not
  `restart` — `restart` reuses the container's existing image and will not pick up a rebuild).

## Part 1 — automated suite, read the output

```
scripts/dev.sh test
scripts/dev.sh test-db
```

**What you should see:** `test` passes with no network (`--network=none`); `test-db` includes
`api/tests/test_ask_api.py`, which asserts the ticket's own acceptance criteria against a real
Postgres — step labels before the first token, a citation resolved to the chunk it names, a
stop flag marking the stored answer partial, and a browser disconnect mid-answer not stopping
generation. At the time this was written: 425 passed / 1 skipped (`test`), 161 passed
(`test-db`).

## Part 2 — against the real stack, no model running

1. Establish a session and ask a question:
   ```
   curl -s -c /tmp/cookies.txt -o /dev/null -H "accept: text/html" http://127.0.0.1:8000/
   curl -s -b /tmp/cookies.txt -X POST http://127.0.0.1:8000/ask \
     -H 'content-type: application/json' \
     -d '{"question":"How long is the notice period?"}'
   ```
   **What you should see:** a `step` event (`"label": "Searching your files."`) arrives before
   a `done` event whose `status` is `"failed"` and whose `reason` names the assistant as
   unavailable — retrieval ran for real against Postgres (there is nothing to find in an empty
   corpus, which is not what failed this) and generation failed cleanly rather than hanging.

2. Confirm the turn is durable — a fresh psql connection, not the request that asked:
   ```
   podman compose exec -T postgres psql -U askwell -d askwell -c \
     "SELECT role, trace->>'status' FROM messages ORDER BY created_at DESC LIMIT 2;"
   ```
   **What you should see:** two rows, `user` and `assistant`, the assistant's `trace` status
   `failed`.

3. Reconnect to the same turn, and again after the API process restarts (clearing the in-memory
   turn registry, exercising the database fallback):
   ```
   MSG=$(podman compose exec -T postgres psql -U askwell -d askwell -tA -c \
     "SELECT id FROM messages WHERE role='assistant' ORDER BY created_at DESC LIMIT 1;" \
     2>/dev/null | tr -d '[:space:]')
   curl -s -b /tmp/cookies.txt "http://127.0.0.1:8000/ask/$MSG/stream"

   podman compose restart api
   curl -s -c /tmp/cookies.txt -o /dev/null -H "accept: text/html" http://127.0.0.1:8000/
   curl -s -b /tmp/cookies.txt "http://127.0.0.1:8000/ask/$MSG/stream"
   ```
   **What you should see:** the same `done` event both times — once served from the live
   registry, once read back from `messages` after the restart.

4. An unknown id, for both surfaces that take one:
   ```
   curl -s -o /dev/null -w "%{http_code}\n" -b /tmp/cookies.txt \
     http://127.0.0.1:8000/ask/00000000-0000-0000-0000-000000000000/stream
   curl -s -o /dev/null -w "%{http_code}\n" -b /tmp/cookies.txt -X POST \
     http://127.0.0.1:8000/ask/00000000-0000-0000-0000-000000000000/stop
   ```
   **What you should see:** `404` both times.

5. Clean up the rows this created:
   ```
   podman compose exec -T postgres psql -U askwell -d askwell -c \
     "TRUNCATE conversations, messages, citations, audit_interactions CASCADE;"
   ```

## What this does not prove

Whether a real model's tokens actually arrive at their generation pace, whether a real
generation actually cites correctly, and whether the standing "retrieved content is data"
statement holds against a real model are all outside what this environment can run —
`InferenceClient.stream_generate` is exercised against `llama.cpp`'s documented `/completion`
SSE contract and against a stub in the test suite, not against a running model here.
