# Manual test — M7-SET-BE-145a: a user-supplied model, and which model answered

**Ticket:** `M7-SET-BE-145a` — a persisted user-supplied model selection that overrides the
profile default, the swap performed against the real inference process, restoring the previous
model on a failed swap, and a `model_identity` recorded on every message.
**Version under test:** `0.7.1` (`docs/BRAIN.md`).

## What this ticket built

`api/src/askwell/model_select.py` (new): `validate_model_file` rejects a candidate path at
selection time — not absolute, not a file, unreadable, or not starting with the GGUF magic
bytes — with the reason in the response. `select_user_model` validates, then asks the host
inference supervisor to swap (`POST /model/select`), and only persists the new setting
(`model.user_model_path`, `model.active_source`) if the swap actually succeeded. `GET /model`
reports what is active right now, derived from those settings, never guessed from the loaded
file's name. `reapply_user_model` runs once at API startup to put a persisted selection back in
front of the inference process after a restart. Every `POST /ask` and every TTS turn now stamps
the assistant message with `model_identity` (`{"source": ..., "display_name": ...}`) at the same
insert that already exists for the pending row — new `messages.model_identity` column,
migration `a1c2e5f6b3d4`. `deploy/inference/askwell-inference`'s `Supervisor.swap_model` performs
the real swap: it stops the running `llama-server` child, lets the crash-recovery loop start the
new model, and on failure restarts the previous one and names why.

## Where this stops on purpose

There is no settings-screen control for any of this — `M7-SET-FE-146` builds it, and
`web/components/settings/` has no model-swap control yet. There is no per-answer marker for an
unvalidated model either — `M7-SET-FE-146a` builds that. Both are exercised through the API
directly below, which is the only surface this ticket built (`UI States: None` is this ticket's
own scope line). Reading `model_identity` back has no HTTP surface either — no ticket has yet
added it to a messages-listing endpoint — so it is read with `psql`, the same substitute
`M1-CONV-BE-177`'s and `M1-CITE-TEST-045`'s manual tests already use for a column with no API of
its own.

---

## Before you start

```
cd ~/external/quantum-plus/askwell
```

If you have never run Askwell before:

```
cp -n .env.example .env
```

Open `.env`, find `POSTGRES_APP_PASSWORD`, and put any word after the `=` if it is blank.

This ticket's code is not yet in the running `api` image on a stack that was already up before
you pulled it — rebuild, or the routes and column below will not exist:

```
scripts/dev.sh build-api
podman compose up -d --force-recreate api
scripts/dev.sh db upgrade head
```

**You should see:** the migration output ends with `a1c2e5f6b3d4` and no error.

You will also need a second model file to select. This machine has no second *generation*
model bundled, so make one by copying the model already in use — a copy is still a real,
loadable GGUF file, so selecting it exercises a genuine swap rather than a fixture:

```
cp ~/.local/share/askwell/models/Qwen3.5-4B-Q4_K_M.gguf \
   ~/.local/share/askwell/models/qwen-copy.gguf
```

---

## Cold start

### 1. Bring the stack up and open Askwell

```
podman compose up -d
```

**You should see:** `postgres`, `redis`, `sandbox`, `voice`, `egress-proxy`, `inference-bridge`,
`api`, `worker` reported as started.

```
scripts/dev.sh inference
```

**You should see:** the supervisor start on the host and report `generation`, `embedding`, and
`reranking` all reaching `ready`, against the shipped `Qwen3.5-4B-Q4_K_M.gguf`
(`ASKWELL_INFERENCE_MODEL_PATH` in `.env`). This can take a few minutes on the first cold load —
wait for `ready` before continuing. Leave this running in its own terminal for the rest of the
walkthrough.

Open a browser to `http://127.0.0.1:8000`.

**You should see:** the app loads — first-run or the composer, depending on whether a source has
been added before. Click through into **Settings**.

**You should see:** no model-swap control anywhere in Settings. This is the expected, checked-for
state (see "Known gaps"), not something to report.

### 2. Establish a session for the API calls below

```
curl -s -c /tmp/ck.txt -o /dev/null -H "accept: text/html" http://127.0.0.1:8000/
```

Every `curl` call in the rest of this walkthrough carries `-b /tmp/ck.txt`.

---

## Part A — the shipped model is what a fresh install reports and stamps

### 3. Confirm `/model` reports the shipped default

```
curl -s -b /tmp/ck.txt http://127.0.0.1:8000/model | jq
```

**You should see:**

```json
{
  "source": "shipped",
  "display_name": "Qwen3.5-4B-Q4_K_M",
  "user_model_path": null
}
```

(`display_name` comes from `models_catalog.spec_for_tier` for `ASKWELL_PROFILE=balanced` — it
may read differently if `.env` sets a different profile, but `source` must still be `"shipped"`.)

### 4. Ask a question through the interface and confirm the answer is stamped

In the browser, in the composer, ask any question (for example: "What can you help me with?")
and wait for the answer to finish streaming.

**You should see:** an answer (or an abstention — either is fine, this ticket does not care
which) appear in the chat.

Now read what was actually recorded:

```
scripts/dev.sh psql -c \
  "SELECT model_identity FROM messages WHERE role = 'assistant' ORDER BY created_at DESC LIMIT 1;"
```

**You should see:** `{"source": "shipped", "display_name": "Qwen3.5-4B-Q4_K_M"}` — the same
identity `/model` reported in step 3, captured at the moment the question was asked.

---

## Part B — a bad path is rejected at selection, with the reason, not at the next question

### 5. A relative path is rejected

```
curl -s -b /tmp/ck.txt -X POST http://127.0.0.1:8000/model/select \
  -H 'Content-Type: application/json' \
  -d '{"model_path": "models/qwen-copy.gguf"}' | jq
```

**You should see:** HTTP 422, and an `error` naming that the path is not absolute — not a stack
trace, not a generic 500.

### 6. A path that does not exist is rejected

```
curl -s -b /tmp/ck.txt -X POST http://127.0.0.1:8000/model/select \
  -H 'Content-Type: application/json' \
  -d '{"model_path": "/tmp/does-not-exist.gguf"}' | jq
```

**You should see:** HTTP 422, `error` stating no file exists at that path.

### 7. A file that is not a GGUF model is rejected

```
echo "not a model" > /tmp/not-a-model.txt
curl -s -b /tmp/ck.txt -X POST http://127.0.0.1:8000/model/select \
  -H 'Content-Type: application/json' \
  -d '{"model_path": "/tmp/not-a-model.txt"}' | jq
```

**You should see:** HTTP 422, `error` stating the file does not start with the `GGUF` magic
bytes Askwell's inference engine requires.

### 8. None of the rejected attempts changed anything

```
curl -s -b /tmp/ck.txt http://127.0.0.1:8000/model | jq
```

**You should see:** unchanged from step 3 — still `"source": "shipped"`, still
`"user_model_path": null`. A rejected selection never reaches persistence.

---

## Part C — a real swap succeeds, is used for the next answer, and survives a restart

### 9. Select the copied model

```
curl -s -b /tmp/ck.txt -X POST http://127.0.0.1:8000/model/select \
  -H 'Content-Type: application/json' \
  -d '{"model_path": "'"$HOME"'/.local/share/askwell/models/qwen-copy.gguf"}' | jq
```

**You should see:** this takes a while (the supervisor stops the running model and loads the new
file — the same cold-load time as step 1). `"ok": true`, `"reason": null`,
`"model_path"` echoing the full path, and HTTP 200. Watch the `scripts/dev.sh inference`
terminal from step 1: it should show the generation role restart and reach `ready` again against
`qwen-copy.gguf`.

### 10. Confirm `/model` now reports the user-supplied file

```
curl -s -b /tmp/ck.txt http://127.0.0.1:8000/model | jq
```

**You should see:**

```json
{
  "source": "user_supplied",
  "display_name": "qwen-copy.gguf",
  "user_model_path": "/home/.../.local/share/askwell/models/qwen-copy.gguf"
}
```

### 11. Ask another question and confirm the new answer is stamped with the new model

In the browser, ask a second question.

**You should see:** the answer streams normally — a copy of the same weights answers exactly as
well as the original.

```
scripts/dev.sh psql -c \
  "SELECT model_identity FROM messages WHERE role = 'assistant' ORDER BY created_at DESC LIMIT 1;"
```

**You should see:** `{"source": "user_supplied", "display_name": "qwen-copy.gguf"}` — distinct
from the row in step 4, on the same conversation.

### 12. Confirm the swap was recorded as a decision

```
podman compose exec api askwell-verify
```

**You should see:** the decisions chain reports intact, no tamper warnings.

```
scripts/dev.sh psql -c \
  "SELECT kind, payload->>'ok' FROM audit_decisions WHERE kind = 'model_swap_requested' ORDER BY id DESC LIMIT 1;"
```

**You should see:** one row, `model_swap_requested`, `ok` = `t`.

### 13. Restart the API and confirm the selection survives

```
podman compose restart api
```

Wait about ten seconds, then:

```
curl -s -c /tmp/ck.txt -o /dev/null -H "accept: text/html" http://127.0.0.1:8000/
curl -s -b /tmp/ck.txt http://127.0.0.1:8000/model | jq
```

**You should see:** still `"source": "user_supplied"`, still pointing at `qwen-copy.gguf` — the
setting was never touched by the restart. Give it a minute if `/model` briefly reports `"none"`
right after the restart — `reapply_user_model` runs in the background and needs the supervisor
to finish re-confirming readiness first.

```
podman compose exec -T postgres psql -U askwell -d askwell -c \
  "SELECT kind FROM audit_decisions WHERE kind = 'model_reapplied' ORDER BY id DESC LIMIT 1;"
```

**You should see:** one row, `model_reapplied` — the restart's own swap, recorded the same way a
manual one is.

Ask a third question in the browser.

**You should see:** the answer's `model_identity` (check with the same `psql` query as step 11)
still reads `"source": "user_supplied"` — the model actually used after the restart matches what
`/model` reports, not just the stored setting.

---

## Part D — a failed swap leaves the previous model loaded and serving, and names why

### 14. Point the generation role at a file that is a real GGUF but the wrong kind of model

`bge-m3-FP16.gguf` is a genuine GGUF file — it passes `validate_model_file` — but it is an
embedding model, not a causal generation model, so `llama-server` will refuse to serve it in the
generation role:

```
curl -s -b /tmp/ck.txt -X POST http://127.0.0.1:8000/model/select \
  -H 'Content-Type: application/json' \
  -d '{"model_path": "'"$HOME"'/.local/share/askwell/models/bge-m3-FP16.gguf"}' | jq
```

**You should see:** this takes a little while — the supervisor tries the new file, fails, then
reloads the previous one. `"ok": false`, and `"reason"` naming what failed (`llama-server`'s own
rejection, or a load failure) and that the previous model was restored. HTTP 409.

### 15. Confirm the previous model is still the one active and still answering

```
curl -s -b /tmp/ck.txt http://127.0.0.1:8000/model | jq
```

**You should see:** still `"source": "user_supplied"`, still `qwen-copy.gguf` — a failed swap
never overwrote the setting that was working. Watch the `scripts/dev.sh inference` terminal:
it should show the generation role back at `ready` against `qwen-copy.gguf`, not stuck at
`crashed` or `unavailable`.

Ask a fourth question in the browser.

**You should see:** it answers normally — the role was never left down by the failed swap.

```
scripts/dev.sh psql -c \
  "SELECT model_identity FROM messages WHERE role = 'assistant' ORDER BY created_at DESC LIMIT 1;"
```

**You should see:** `{"source": "user_supplied", "display_name": "qwen-copy.gguf"}` — the
model that actually answered, not the one that was briefly requested and failed.

### 16. Confirm the failed swap was recorded too

```
scripts/dev.sh psql -c \
  "SELECT kind, payload->>'ok' FROM audit_decisions WHERE kind = 'model_swap_requested' ORDER BY id DESC LIMIT 1;"
```

**You should see:** the newest row, `ok` = `f` — a rejected swap is still a decisions record
(`docs/audit-log.md`), same as an accepted one.

---

## Part E — restore the shipped model (cleanup, and a second look at the "no model" edge case)

### 17. Swap back to the shipped model

```
curl -s -b /tmp/ck.txt -X POST http://127.0.0.1:8000/model/select \
  -H 'Content-Type: application/json' \
  -d '{"model_path": "'"$HOME"'/.local/share/askwell/models/Qwen3.5-4B-Q4_K_M.gguf"}' | jq
```

**You should see:** `"ok": true`. Note that `/model` afterward still reports `"source":
"user_supplied"` — selecting the shipped file's path through this endpoint is indistinguishable
from selecting any other file, by the ticket's own validation rule that the shipped/user-supplied
distinction is written, never guessed from a file name. Restoring the actual default requires
clearing `model.user_model_path`/`model.active_source` directly, since no "revert to shipped"
control exists yet:

```
scripts/dev.sh psql -c "DELETE FROM settings WHERE key IN ('model.user_model_path', 'model.active_source');"
curl -s -b /tmp/ck.txt http://127.0.0.1:8000/model | jq
```

**You should see:** `"source": "shipped"` again.

### 18. Confirm the "no model loaded" edge case, without needing to actually stop the supervisor

Read `active_model_identity` (`api/src/askwell/model_select.py`): when
`read_inference_state(...).usable` is false, it returns `{"source": "none", "display_name":
null}` before it ever looks at the persisted setting, and `POST /ask`'s own insert calls this at
the same point on every turn. This is exercised directly (not by stopping your only running
supervisor mid-walkthrough) in `api/tests/test_model_select.py`'s
`active_model_identity`-reading tests:

```
scripts/dev.sh test -k test_model_select
```

**You should see:** all cases pass, including the one asserting `"source": "none"` when the
inference state file reports not-usable.

---

## Cleanup

```
rm -f ~/.local/share/askwell/models/qwen-copy.gguf /tmp/not-a-model.txt /tmp/ck.txt
```

---

## Known gaps

Deliberately not built by this ticket — do not report these as defects:

- **No settings-screen control.** Everything above goes through `curl` because
  `M7-SET-FE-146` has not landed. There is nothing to click.
- **No persistent per-answer marker.** An answer produced by an unvalidated, user-supplied model
  carries `model_identity` in the database but nothing in the interface says so —
  `M7-SET-FE-146a`.
- **No HTTP listing of `model_identity` per message.** Reading it back requires `psql`, same as
  `sql_result` and `trace` before any ticket exposed those either.
- **A model too large for probed RAM is accepted, not blocked**, per the ticket's own edge case —
  this walkthrough does not exercise `size_warning` because no oversized-but-loadable file was
  available in this environment; it is covered directly in
  `api/tests/test_model_select.py::test_size_warning*` (or nearest matching test name — see the
  file).
- **A swap requested mid-answer queues rather than races** (the ticket's own edge case, backed by
  holding every `generation_semaphore` permit for the swap's duration) — not exercised manually
  above, since reliably timing a `curl` against a live in-flight generation is not repeatable by
  hand; it is covered by the automated suite's concurrency-focused cases in
  `api/tests/test_model_select.py` and `api/tests/test_model_swap_host.py`.
- **The size and mid-swap concurrency behaviour above are covered by the automated suite, not
  this manual walkthrough** — `scripts/dev.sh test -k test_model_select or test_model_swap_host`.
