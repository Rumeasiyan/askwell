# Manual test — M7-BACKUP-BE-157, backup that excludes what can be regenerated

**Ticket:** `M7-BACKUP-BE-157` — a backup job producing one portable artefact with a manifest,
excluding model weights, the trace ring buffer and the vector index, stating the re-embed cost
at backup time.
**Version under test:** `0.6.8`.
**Time:** about 20 minutes.
**Who can run it:** anyone who can open a browser and a terminal. This ticket is backend-only —
there is no settings-screen entry point yet (`docs/ux/settings.md` §6's "Your data" table has no
backup row; `docs/BRAIN.md`'s M7 entry for this ticket confirms it). This walkthrough drives
`/backup` with `curl` alongside the running application, the same pattern `M7-LOG-BE-155`'s
manual test uses for its own not-yet-wired backend checks.

**What is being checked.** `api/src/askwell/backup.py` (`estimate`, `enqueue`, `run_job`,
`resume`, `GET /backup/estimate`, `POST /backup`, `GET /backup/{id}`,
`GET /backup/{id}/download`).

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

**Expect:** a `200` response reporting the API healthy.

---

## Part A — cold start, use Askwell normally so there is something to back up

### 1. Open the application

In a browser, go to `http://localhost:8000/`.

**Expect:** the Ask screen loads normally.

### 2. Add a source

Click **Library** in the left rail, then **Add a source**. Under **Files**, click **Choose
files** and pick any small text or PDF file from this machine, answering the folder prompt if
asked.

**Expect:** a card appears naming the file queued for background ingestion. Wait until it shows
ready before continuing, so there is at least one embedded chunk to exclude from the backup.

### 3. Ask a question, so there is a memory or conversation row too

Click **Ask**, type any question about the file you just added, and send it.

**Expect:** Askwell answers or abstains — either way, a conversation row now exists to back up.

---

## Part B — check the estimate before committing

### 4. Read the pre-flight estimate

```
curl -s localhost:8000/backup/estimate | python3 -m json.tool
```

**Expect:** a `200` body with `"chunk_count"` at least `1`, `"estimated_reembed_seconds"` a
positive number, `"estimated_size_bytes"` a positive integer, `"passphrase_protected": false`,
`"user_files_included": false`, and a `"user_files_statement"` reading to the effect that your
own files are not included because Askwell never copies them.

---

## Part C — take a backup and watch it run

### 5. Start a backup

```
curl -s -X POST localhost:8000/backup | python3 -m json.tool
```

**Expect:** a `201` body naming a `"status"` of `"queued"` or `"running"`, an `"id"` (a UUID —
copy it, you'll reuse it below), `"tables_total"` equal to `15`, and `"file_bytes": null` —
nothing has finished yet.

### 6. Poll its progress while continuing to use Askwell

```
export JOB_ID=<paste the id from step 5>
curl -s localhost:8000/backup/$JOB_ID | python3 -m json.tool
```

While it is still `"running"` (a fresh install's corpus is tiny, so this may complete in well
under a second — repeat the `curl` a few times immediately after step 5 if you want to catch it
mid-run), **switch back to the browser and ask a second question**.

**Expect:** the answer streams normally — the backup running in the background does not block or
slow down asking. Re-run the `curl` in step 6 until `"status"` reads `"done"`.

**Expect at completion:** `"tables_done"` equal to `"tables_total"`, `"rows_done"` equal to
`"rows_total"`, `"chunk_count"` at least `1`, and `"file_bytes"` a positive integer.

---

## Part D — download the artefact and inspect it

### 7. Download and unzip

```
curl -s -o /tmp/askwell-backup.zip localhost:8000/backup/$JOB_ID/download
mkdir -p /tmp/askwell-backup && cd /tmp/askwell-backup
unzip -o /tmp/askwell-backup.zip
ls
```

**Expect:** one `.jsonl` file per table (`roots.jsonl`, `sources.jsonl`, `documents.jsonl`,
`document_pages.jsonl`, `chunks.jsonl`, `memory.jsonl`, `schema_notes.jsonl`,
`clarifications.jsonl`, `conversations.jsonl`, `messages.jsonl`, `fact_usage.jsonl`,
`citations.jsonl`, `settings.jsonl`, `audit_decisions.jsonl`, `audit_interactions.jsonl`) plus
`manifest.json`. **No `traces/` directory and no file with "weight" in its name.**

### 8. Confirm the size is far smaller than a full index would be

```
du -h /tmp/askwell-backup.zip
```

**Expect:** kilobytes to low megabytes for a fresh-install corpus of one small document — not
the tens-of-gigabytes figure the ticket's Business Value cites for a corpus that included model
weights and the vector index.

### 9. Read the manifest

```
python3 -m json.tool manifest.json
```

**Expect:** `"askwell_version"` matching `VERSION` (`0.6.8`), a `"generated_at"` timestamp,
`"chunk_count"` and `"estimated_reembed_seconds"` matching what step 6 last reported,
`"passphrase_protected": false`, `"user_files_included": false`, the same
`"user_files_statement"` as step 4, and an `"excluded"` object naming `"model_weights"`,
`"trace_ring_buffer"` and `"vector_index"` each with a one-line reason.

### 10. Confirm the vector column is genuinely gone, not just hidden

```
python3 -c "
import json
lines = open('chunks.jsonl').read().splitlines()
row = json.loads(lines[0])
assert 'embedding' not in row, 'embedding leaked into the backup'
assert 'content' in row and row['content']
print('chunk content present, embedding absent — OK')
"
```

**Expect:** `chunk content present, embedding absent — OK`, and no `AssertionError`.

### 11. Confirm the manifest's per-table counts match what you inspected

```
python3 -c "
import json
manifest = json.load(open('manifest.json'))
print(manifest['tables']['chunks'])
print(manifest['tables']['memory'])
"
```

**Expect:** `chunks`' `"excluded_columns"` lists `"embedding"` and `"record_count"` matches the
line count of `chunks.jsonl`; `memory`'s `"record_count"` is at least `1` if step 3 produced a
remembered fact (memory writes depend on what the assistant chose to remember — `0` is a valid
outcome here, not a defect, if nothing was memorable).

---

## Part E — a backup with a passphrase set

### 12. Set a passphrase through the real screen

Click **Settings** in the left rail, then the passphrase section. Enter a passphrase meeting the
strength bar (e.g. `correct horse battery staple mountain`), acknowledge the no-recovery
warning, and confirm.

**Expect:** the passphrase is reported set, and its migration reaches `100%` before continuing.

### 13. Check the estimate states protection plainly

```
curl -s localhost:8000/backup/estimate | python3 -m json.tool
```

**Expect:** `"passphrase_protected": true`.

### 14. Take a backup and confirm the manifest agrees

```
curl -s -X POST localhost:8000/backup | python3 -m json.tool
```

**Expect:** `201`, `"passphrase_protected": true` in the response body. Poll
`GET /backup/$JOB_ID` (as in step 6) to `"status": "done"`, download and unzip it, then:

```
python3 -c "import json; print(json.load(open('manifest.json'))['passphrase_protected'])"
```

**Expect:** `True`. The encrypted `chunks.content` values land in `chunks.jsonl` still
encrypted — this ticket does not decrypt them, it only carries whatever is already in the
column.

---

## Part F — a migration in progress refuses the backup

### 15. Start a passphrase change and, before it finishes, try to back up

This is timing-sensitive on a small corpus — a change/remove migration on a handful of chunks
may finish before the next request lands. If step 16 comes back `201` instead of `409`, that is
the migration having already finished, not a defect; re-run against a larger corpus if you want
to reliably catch the window.

In the browser, start changing or removing the passphrase set in Part E. Immediately, in the
terminal:

```
curl -s -o /dev/null -w '%{http_code}\n' -X POST localhost:8000/backup
```

**Expect:** `409` if the migration is still running when the request lands, with a JSON body
naming that a content-encryption migration is already in progress. No job row is created.

---

## Part G — insufficient disk space refuses before starting

### 16. Simulate a full disk by pointing `backup_dir` somewhere with no room

This one is closest to the automated coverage in `api/tests/test_backup.py::
test_insufficient_space_is_refused_before_starting`, which monkeypatches `shutil.disk_usage`
directly — there is no supported way to make a real filesystem report near-zero free space
without actually filling it, so this step is a read of that test's assertions rather than a
live repro:

```
scripts/dev.sh test -- -k test_insufficient_space_is_refused_before_starting -v
```

**Expect:** the test passes, and its assertions show `enqueue` raising `InsufficientSpace` with
`needed_bytes > 0` and `free_bytes` matching the simulated near-zero value, before any table is
read.

---

## Part H — downloading a job that does not exist, or is not finished

### 17. Download an unknown id

```
curl -s -o /dev/null -w '%{http_code}\n' localhost:8000/backup/$(python3 -c 'import uuid;print(uuid.uuid4())')/download
```

**Expect:** `404`.

### 18. Read a status route with a malformed id

```
curl -s -o /dev/null -w '%{http_code}\n' localhost:8000/backup/not-a-uuid
```

**Expect:** `422` — FastAPI's own path-parameter validation rejects a non-UUID before the route
body runs.

---

## Cleanup

Remove the passphrase set in Part E if you don't want it left on this install (Settings →
passphrase → remove, with the passphrase you set). Delete the scratch files:

```
rm -rf /tmp/askwell-backup.zip /tmp/askwell-backup
```

---

## What was checked against the ticket's acceptance criteria

- One artefact containing everything except weights, traces and the vector index — Part D.
- The artefact carries a manifest and the version — Part D, step 9.
- The re-embed cost is estimated and stated, at estimate time and again on the finished job —
  Part B and Part C, step 6.
- The backup states plainly that the user's own files are not included — Part B, step 4, and
  Part D, step 9.
- Backup during ingestion is taken at a consistent point, never a torn snapshot — this
  walkthrough does not itself trigger a mid-ingestion backup by hand (timing it against a
  background ingest job reliably is impractical at dev-corpus scale); covered by
  `test_backup.py`'s `REPEATABLE READ` reasoning in the module docstring, not re-verified here.
- Backup with a passphrase set includes the encrypted content as encrypted, stated at backup
  time — Part E.
- Insufficient space is refused before starting, with the space needed named — Part G (via the
  automated test, for the reason stated there).
- The artefact is internally consistent, no half-written table — implied by the `.tmp`-then-
  rename pattern in `backup.py`'s module docstring; not independently re-verified here since
  reproducing a mid-write crash requires killing the worker, which this walkthrough's cold-start
  path cannot trigger safely against a shared dev stack.
- Backup is a decisions record — implied by
  `test_backup.py::test_enqueue_writes_a_decisions_record_naming_the_job`; not separately
  queried by hand here, since Part C's own `curl` responses already confirm the job that was
  created.
- Migration in progress refuses the backup — Part F, timing-sensitive as noted there.

## Known gaps

- **No settings-screen entry point.** `docs/ux/settings.md` §6's "Your data" table has no backup
  row yet — starting, watching progress, and downloading a backup all happen through `curl` in
  this walkthrough rather than by clicking, because there is nothing to click yet.
- **Restore is not built.** This ticket is backup only (`M7-BACKUP-BE-158` is restore, explicitly
  out of scope here). A backup with no tested restore is not yet a backup — the ticket's own
  Testing Notes say so; this document only exercises the write side.
- **A genuinely large corpus (months of documents and conversations) was not generated for this
  walkthrough.** A fresh dev install's corpus is small. The keyset-paginated, batched streaming
  design (`_BATCH_SIZE = 2000`, module docstring) is exercised at small scale here and at larger
  synthetic scale in `test_backup.py`, but this document does not itself prove memory stays flat
  across a multi-hundred-thousand-row backup.
- **Mid-ingestion consistency and mid-write crash recovery are not exercised by hand** — see the
  notes under "What was checked" above. Covered by automated tests and the module docstring's
  reasoning instead.
- **The re-embed cost is a stated estimate, not a measurement** (`ESTIMATED_CHUNKS_PER_SECOND =
  5.0` in `backup.py`) — no native inference process is available in this environment to
  benchmark against. This walkthrough confirms the number is present and consistent between the
  estimate and the finished job, not that it is accurate against real hardware.
- **The artefact itself is never separately encrypted as a file** — a passphrase-protected
  backup carries already-encrypted `chunks.content` values as-is; nothing in this ticket
  encrypts the zip or the other tables' contents beyond what was already encrypted at rest.
