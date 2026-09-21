# Manual test — M7-LOG-BE-155, log export as a background job, with the chain and a verifier

**Ticket:** `M7-LOG-BE-155` — a background export job with progress, producing an open-format
file containing both audit stores and the hash chain, with a standalone verifier bundled
alongside it that a third party can run without Askwell installed.
**Version under test:** `0.6.7`.
**Time:** about 25 minutes.
**Who can run it:** anyone who can open a browser and a terminal, and a second machine (or a
second directory with no Askwell checkout on `PYTHONPATH`) to prove the verifier is really
standalone. This ticket is backend-only: `web/components/settings/storage.tsx`'s "Export and
prune" entry point still renders as disabled, stating it is not built yet (`docs/BRAIN.md`,
issue #487 Option 1 unclaimed) — there is no click-through for starting an export yet, so this
walkthrough drives `/log-export` with `curl` from a terminal alongside the running application,
the same pattern `M7-LOG-BE-153`'s manual test uses for its own not-yet-wired backend checks.

**What is being checked.** `api/src/askwell/log_export.py` (`enqueue`, `run_job`, `resume`,
`POST /log-export`, `GET /log-export/{id}`, `GET /log-export/{id}/download`) and
`api/src/askwell/log_export_verifier.py` (the bundled `verify.py` source).

---

## Before you start

Bring the stack up with the built frontend, since the API serves `web/out`, not live source:

```
cd ~/external/quantum-plus/askwell
podman compose up -d
scripts/dev.sh db upgrade head
scripts/dev.sh web-build
podman compose restart api
```

Confirm the app is answering before starting:

```
curl -s localhost:8000/health | python3 -m json.tool
```

**Expect:** a 200 response reporting the API healthy.

---

## Part A — cold start, use Askwell normally so there is something to export

### 1. Open the application

In a browser, go to `http://localhost:8000/`.

**Expect:** the Ask screen loads normally.

### 2. Add a source

Click **Library** in the left rail, then **Add a source**. Under **Files**, click **Choose
files** and pick any small text or PDF file from this machine, answering the folder prompt if
asked.

**Expect:** a card appears naming the file queued for background ingestion.

### 3. Ask a question, in the same browser tab

Click **Ask**, type any question, and send it.

**Expect:** Askwell answers or abstains — either way, an interaction row now exists to export.
Note the rough time — you'll use it in Part D.

---

## Part B — start an export in the background and keep using Askwell

### 4. Start a full export

In the terminal:

```
curl -s -X POST localhost:8000/log-export -H 'content-type: application/json' -d '{}' | python3 -m json.tool
```

**Expect:** a `201` body naming a `"status"` of `"queued"` or `"running"`, an `"id"` (a UUID —
copy it, you'll reuse it below), `"decisions_total"` and `"interactions_total"` as integers,
and `"file_bytes": null` — nothing has finished yet.

### 5. Poll its progress while continuing to use Askwell

```
export JOB_ID=<paste the id from step 4>
curl -s localhost:8000/log-export/$JOB_ID | python3 -m json.tool
```

While it is still `"running"` (a fresh install's log is small, so this may complete in well
under a second — repeat the `curl` a few times immediately after step 4 if you want to catch
it mid-run), **switch back to the browser and ask a second question**.

**Expect:** the answer streams normally — the export running in the background does not block
or slow down asking. Re-run the `curl` in step 5 until `"status"` reads `"done"`.

**Expect at completion:** `"decisions_done"` equal to `"decisions_total"`, `"interactions_done"`
equal to `"interactions_total"`, and `"file_bytes"` a positive integer.

---

## Part C — download the file and verify it on a machine with no Askwell installed

### 6. Download the export

```
curl -s -o /tmp/askwell-export.zip localhost:8000/log-export/$JOB_ID/download
unzip -l /tmp/askwell-export.zip
```

**Expect:** the archive lists `manifest.json`, `decisions.jsonl`, `interactions.jsonl`, and
`verify.py`.

### 7. Run the bundled verifier somewhere Askwell's own dependencies are not importable

Copy the zip to a directory outside this checkout (or to a second machine) and run it with the
plain system `python3` — not through `scripts/dev.sh`, which is the point:

```
mkdir -p /tmp/askwell-verify && cd /tmp/askwell-verify
unzip -o /tmp/askwell-export.zip
python3 verify.py .
```

**Expect:** output naming each store, e.g. `decisions: N records, chain intact.` and
`interactions: N records, chain intact.`, and an exit code of `0` (check with `echo $?`). No
import error, no network access, no mention of `askwell`, `sqlalchemy` or `pydantic` — `verify.py`
is a single self-contained file with only the standard library.

### 8. Tamper with one record and re-run the verifier

```
python3 - <<'PY'
import json
lines = open("decisions.jsonl").read().splitlines()
row = json.loads(lines[0])
row["payload"] = {"tampered": True}
lines[0] = json.dumps(row)
open("decisions.jsonl", "w").write("\n".join(lines) + "\n")
PY
python3 verify.py .
```

**Expect:** exit code `1`, and output naming the specific record id and that its stored hash no
longer matches what its contents hash to — wording to the effect of "were altered after
export" — not a generic failure.

---

## Part D — a date-filtered export

### 9. Export only from a cutoff just before the question in step 3

Pick a timestamp a minute or two before you asked the question in step 3 (adjust to your own
clock):

```
curl -s -X POST localhost:8000/log-export -H 'content-type: application/json' \
  -d '{"since": "2026-09-21T00:00:00Z"}' | python3 -m json.tool
```

Poll `GET /log-export/<id>` as in step 5 until `"status"` is `"done"`, then download and
extract it as in step 6.

**Expect:** `manifest.json`'s `"since"` matches what you sent, and its
`stores.decisions.first_prev_hash` is **not** the all-zero genesis value (`"0"` × 64) — this
export starts partway through the real chain, not at its beginning.

### 10. Verify the filtered export

```
python3 verify.py <the extracted directory>
```

**Expect:** the chain reports intact, and the output additionally prints a note that this
export is date-filtered — that it proves nothing was altered or removed *within* the window,
not that nothing was ever removed before the window started.

### 11. Try `since` after `until`

```
curl -s -X POST localhost:8000/log-export -H 'content-type: application/json' \
  -d '{"since": "2026-09-21T00:00:00Z", "until": "2026-01-01T00:00:00Z"}'
```

**Expect:** a `400` naming that `since` must not be after `until`. No job row is created.

---

## Part E — export while a passphrase is set

### 12. Set a passphrase through the real screen

Click **Settings** in the left rail, then the passphrase section. Enter a passphrase meeting
the strength bar (e.g. `correct horse battery staple mountain`), acknowledge the no-recovery
warning, and confirm.

**Expect:** the passphrase is reported set.

### 13. Try exporting without acknowledging

```
curl -s -X POST localhost:8000/log-export -H 'content-type: application/json' -d '{}' | python3 -m json.tool
```

**Expect:** a `400` body with `"passphrase_enabled": true` and wording that the export is
written decrypted, outside the passphrase's protection, and must be acknowledged before it is
written. No job row is created.

### 14. Export with acknowledgement

```
curl -s -X POST localhost:8000/log-export -H 'content-type: application/json' \
  -d '{"acknowledged_decrypted_export": true}' | python3 -m json.tool
```

**Expect:** `201`, a job created as in step 4. Poll it to `"done"`, download it, and confirm
(`grep` or open the file) that `decisions.jsonl`/`interactions.jsonl` contain plain readable
JSON, not ciphertext — the export is genuinely decrypted regardless of the passphrase, as
warned.

---

## Part F — export at the log budget limit still works

### 15. Push the log budget to its hard limit

```
curl -s -X POST localhost:8000/log-budget -H 'content-type: application/json' -d '{"budget_bytes": 1}'
curl -s localhost:8000/log-budget | python3 -m json.tool
```

**Expect:** `"stage": "hard_limit"`.

### 16. Start an export anyway

```
curl -s -X POST localhost:8000/log-export -H 'content-type: application/json' -d '{}' | python3 -m json.tool
```

**Expect:** `201`, exactly as in step 4 — the hard limit refuses new *ingestion*
(`log_export.py` does not call `enforce_ingestion_allowed` anywhere), export is unaffected.
Poll it to `"done"`.

### 17. Restore the budget

```
curl -s -X POST localhost:8000/log-budget -H 'content-type: application/json' \
  -d '{"budget_bytes": 2147483648}'
```

**Expect:** `"stage": "ok"` again, so the stack is left normal for whoever uses it next.

---

## Part G — downloading a job that does not exist, or is not finished

### 18. Download an unknown id

```
curl -s -o /dev/null -w '%{http_code}\n' localhost:8000/log-export/$(python3 -c 'import uuid;print(uuid.uuid4())')/download
```

**Expect:** `404`.

### 19. Read a still-running or just-created job's status route with a bad id

```
curl -s -o /dev/null -w '%{http_code}\n' localhost:8000/log-export/not-a-uuid
```

**Expect:** `422` — FastAPI's own path-parameter validation rejects a non-UUID before the
route body runs.

---

## Cleanup

Remove the passphrase set in Part E if you don't want it left on this install (Settings →
passphrase → remove, with the passphrase you set). Delete the scratch files:

```
rm -rf /tmp/askwell-export.zip /tmp/askwell-verify
```

---

## What was checked against the ticket's acceptance criteria

- Runs in the background with progress, produces a file in an open format containing the
  records and the chain — Part B.
- The bundled verifier confirms the chain on another machine without Askwell installed — Part
  C, step 7, run with plain `python3` against a directory with no `askwell` package reachable.
- A date-range export works — Part D.
- Export is possible at the log budget limit — Part F.
- Interrupted export is restartable and no partial file is presented as complete — covered by
  `api/tests/test_log_export.py::test_a_rerun_after_interruption_leaves_no_stale_partial_file`
  (every file lands at `<name>.tmp` and is renamed only once complete); not re-exercised by
  hand here since it requires killing the worker mid-write, which this walkthrough's cold-start
  path cannot trigger safely against a shared dev stack.
- Export with a passphrase set warns before writing decrypted — Part E.
- The chain must be included, or it is not an export — Part C, step 6's file listing, and the
  verifier itself failing without `manifest.json`.
- Export is a decisions record naming the range — implied by
  `test_enqueue_writes_a_decisions_record_naming_the_range`; not separately queried by hand
  here, since Part D/E's own `curl` responses already confirm the range accepted matches what
  was requested.

## Known gaps

- **No settings-screen entry point.** `web/components/settings/storage.tsx`'s "Export and
  prune" still renders disabled and unwired — starting, watching progress, and downloading an
  export all happen through `curl` in this walkthrough rather than by clicking, because there
  is nothing to click yet. The frontend ticket that wires this up is unstarted and currently
  unclaimed (`docs/BRAIN.md`'s "Next" line, issue #487 Option 1).
- **A genuinely large export (a year of interactions) was not generated for this walkthrough.**
  A fresh dev install's log is kilobytes. The streamed-to-disk, batched-query design
  (`_BATCH_SIZE = 2000`, module docstring) is read and exercised at small scale here and at
  larger synthetic scale in `test_log_export.py`, but this document does not itself prove
  memory stays flat across a multi-hundred-thousand-row export.
- **Interrupted-export restart (Part crash-mid-write) is not exercised by hand** — see the note
  under "What was checked" above. Covered by an automated test instead.
- **No `list` or `delete` route for past exports.** The ticket's own scope is the job, the
  format and the verifier; a history view is explicitly left to whichever settings ticket needs
  one (`log_export.py`'s own docstring on `register_log_export`).
- **The exported file itself is never encrypted or protected**, by design — the passphrase (if
  any) only protects data at rest inside Askwell; once exported it is a plain file, and Part E's
  warning is the entire mitigation. Stated in the ticket's own "Known gaps".
