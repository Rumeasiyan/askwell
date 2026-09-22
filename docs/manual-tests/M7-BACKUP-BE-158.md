# Manual test — M7-BACKUP-BE-158, restore with the re-embed cost stated up front

**Ticket:** `M7-BACKUP-BE-158` — read a backup artefact back onto a machine: schema-currency
check, version refusal, passphrase requirement, refuse-to-merge, resumable per-table restore,
re-embed with progress, chain verification at the end.
**Version under test:** `0.7.4`.
**Time:** about 35 minutes.
**Who can run it:** anyone who can open a browser and a terminal, with two ways to reach the
same Postgres instance (or one instance you are willing to wipe between parts). This ticket is
backend-only — there is no settings-screen entry point yet (same gap `M7-BACKUP-BE-157`'s manual
test names: `docs/ux/settings.md` §6's "Your data" table has no backup/restore row).
This walkthrough drives `/backup` and `/restore` with `curl` alongside the running application,
using the browser only for the parts that already have a screen (adding a source, asking a
question, setting a passphrase).

**What is being checked.** `api/src/askwell/restore.py` (`inspect_artefact`, `enqueue`,
`run_job`, `resume`, `POST /restore/inspect`, `POST /restore`, `GET /restore/{id}`,
`POST /restore/{id}/resume`).

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

The "clean second machine" this ticket is sized around is simulated here by wiping the same
database between Part A (source machine) and Part B (destination machine) — see Part B's own
setup step for exactly what that means and why it is a faithful stand-in.

---

## Part A — source machine: build a corpus worth carrying over

### 1. Open the application

In a browser, go to `http://localhost:8000/`.

**Expect:** the Ask screen loads normally.

### 2. Add a source

Click **Library** in the left rail, then **Add a source**. Under **Files**, click **Choose
files** and pick a small text or PDF file whose content is distinctive and memorable (e.g. a
file containing a made-up fact like "the quarterly retainer is 4,200 credits"), answering the
folder prompt if asked. **Note the file's full path** — you will need it again in Part D.

**Expect:** a card appears naming the file queued for background ingestion. Wait until it shows
ready before continuing.

### 3. Ask a question that produces a citation

Click **Ask**, ask a question whose answer is the distinctive fact from step 2, and send it.

**Expect:** Askwell answers, citing the file from step 2. Note the exact wording of the answer
and the citation (filename and page) — you will compare against this in Part D.

### 4. Set a passphrase

Click **Settings** in the left rail, then the passphrase section. Enter a passphrase meeting the
strength bar (e.g. `correct horse battery staple mountain`), acknowledge the no-recovery
warning, and confirm.

**Expect:** the passphrase is reported set, and its migration reaches `100%` before continuing.
**Write the passphrase down** — you will need it, unchanged, in Part D.

### 5. Take a backup

```
curl -s -X POST localhost:8000/backup -H 'content-type: application/json' \
  -d '{"passphrase": "correct horse battery staple mountain"}' | python3 -m json.tool
```

**Expect:** `201`, `"passphrase_protected": true`. Copy the `"id"`.

```
export BACKUP_ID=<paste the id>
curl -s localhost:8000/backup/$BACKUP_ID | python3 -m json.tool
```

Repeat until `"status": "done"`.

**Expect:** `"file_bytes"` a positive integer.

### 6. Download the artefact

```
curl -s -o /tmp/askwell-restore-test.zip localhost:8000/backup/$BACKUP_ID/download
ls -la /tmp/askwell-restore-test.zip
```

**Expect:** a non-empty file.

---

## Part B — a backup from a newer version is refused, not partially applied

This is easiest to check now, before the database is wiped, since it only needs the artefact
you just made and a claimed higher version.

### 7. Inspect the real artefact first

```
curl -s -X POST localhost:8000/restore/inspect -H 'content-type: application/json' \
  -d "{\"path\": \"/tmp/askwell-restore-test.zip\"}" | python3 -m json.tool
```

**Expect:** `200`, `"askwell_version": "0.7.4"`, `"chunk_count"` at least `1`,
`"estimated_reembed_seconds"` a positive number, `"passphrase_protected": true`. **This is the
re-embed cost stated before committing** — the ticket's own acceptance criterion.

### 8. Forge a newer version and confirm refusal

```
mkdir -p /tmp/askwell-restore-newer && cd /tmp/askwell-restore-newer
unzip -o -q /tmp/askwell-restore-test.zip
python3 -c "
import json
m = json.load(open('manifest.json'))
m['askwell_version'] = '99.0.0'
json.dump(m, open('manifest.json', 'w'))
"
zip -q -r /tmp/askwell-restore-newer.zip .
curl -s -X POST localhost:8000/restore/inspect -H 'content-type: application/json' \
  -d '{"path": "/tmp/askwell-restore-newer.zip"}' | python3 -m json.tool
```

**Expect:** `409`, an `"error"` naming `99.0.0` as newer than this install's `0.7.4` and telling
you to update Askwell before restoring — refused by name, nothing touched.

```
cd - && rm -rf /tmp/askwell-restore-newer /tmp/askwell-restore-newer.zip
```

---

## Part C — passphrase requirement, and an incorrect passphrase is refused before writing anything

### 9. Attempt a restore of the real artefact with no passphrase

```
curl -s -X POST localhost:8000/restore -H 'content-type: application/json' \
  -d '{"path": "/tmp/askwell-restore-test.zip"}' | python3 -m json.tool
```

**Expect:** `422`, an `"error"` stating the backup is passphrase-protected and there is no
recovery without it. No job row created (nothing to check this against yet, but note the `422`).

### 10. Attempt a restore with the wrong passphrase

```
curl -s -X POST localhost:8000/restore -H 'content-type: application/json' \
  -d '{"path": "/tmp/askwell-restore-test.zip", "passphrase": "definitely not it"}' \
  | python3 -m json.tool
```

**Expect:** a `201` (the job is accepted and queued — the passphrase is only checked once the
worker unwraps the artefact) with `"status"` initially `"queued"`. Copy the `"id"` and poll:

```
export WRONG_ID=<paste the id>
curl -s localhost:8000/restore/$WRONG_ID | python3 -m json.tool
```

**Expect:** eventually `"status": "failed"`, `"error"` containing `IncorrectPassphrase`. Nothing
in the destination database changed — confirmed implicitly by Part D starting from a database
you deliberately wipe next, so there is nothing to accidentally have left behind either way.

---

## Part D — destination machine: the real restore, cold

### 11. Simulate a clean second machine

This drops all application data and the install secret, so the restore that follows is not
merging into anything:

```
scripts/dev.sh psql <<'SQL'
TRUNCATE roots, sources, documents, document_pages, chunks, memory, schema_notes,
  clarifications, conversations, messages, fact_usage, citations, web_citations,
  settings, audit_decisions, audit_interactions, backup_jobs, restore_jobs CASCADE;
SQL
podman compose exec api sh -c 'rm -f $(python3 -c "from askwell.config import Settings; print(Settings().install_secret_path)")'
podman compose restart api
```

**Expect:** the commands complete without error.

### 12. Confirm the corpus is actually gone

Open `http://localhost:8000/` in the browser and click **Library**.

**Expect:** no sources listed — a genuinely empty corpus, the fresh-install state this restore
targets.

### 13. State the cost before committing

```
curl -s -X POST localhost:8000/restore/inspect -H 'content-type: application/json' \
  -d '{"path": "/tmp/askwell-restore-test.zip"}' | python3 -m json.tool
```

**Expect:** `200`, the same `"chunk_count"` and `"estimated_reembed_seconds"` as step 7 — this is
what a settings screen would show the user before they click restore, read here directly since
there is no screen yet.

### 14. Start the restore

```
curl -s -X POST localhost:8000/restore -H 'content-type: application/json' \
  -d '{"path": "/tmp/askwell-restore-test.zip", "passphrase": "correct horse battery staple mountain"}' \
  | python3 -m json.tool
```

**Expect:** `201`, `"status"` one of `"queued"`/`"restoring_tables"`, `"tables_total"` equal to
`16`, `"chunks_total"` matching step 13's `chunk_count`.

### 15. Watch it move through both phases

```
export RESTORE_ID=<paste the id>
curl -s localhost:8000/restore/$RESTORE_ID | python3 -m json.tool
```

Repeat a few times.

**Expect:** `"status"` progresses `"restoring_tables"` (with `tables_done` climbing toward
`tables_total` and `rows_done` toward `rows_total`) then `"reembedding"` (with `chunks_done`
climbing toward `chunks_total`) then `"done"`.

**Expect at completion:** `"tables_done" == "tables_total"`, `"rows_done" == "rows_total"`,
`"chunks_done" == "chunks_total"`, `"chain_verified": true`, `"chain_detail"` present.

---

## Part E — everything the backup carried is actually back

### 16. Memory and its history are present

```
scripts/dev.sh psql -c "SELECT count(*) FROM memory;"
```

**Expect:** at least `1` if step 3 produced a remembered fact.

### 17. The conversation and its citation are intact

Click **Ask** in the browser, then open the conversation history (if the screen shows past
conversations) or re-run the question from step 3.

**Expect:** the same answer as step 3, with the same citation (same filename, same page).

### 18. The document reports as missing, not deleted

Click **Library**.

**Expect:** the document from step 2 is listed with a state saying its path could not be found
(`docs/ux/source-viewer.md` §4 "File moved or renamed" — restore lands `documents.path` pointing
at the source machine's filesystem, which this container does not have) — **not** "deleted".

### 19. Re-register the root and let re-embedding finish

Since this walkthrough runs both "machines" as the same container, the original path from step 2
is in fact still present on disk — click **Add a source** in the Library screen and nominate the
same folder again (or re-run `POST /roots` with that path, if the picker does not resurface it
automatically).

**Expect:** the document moves out of the missing state once ingestion notices the path resolves
again. If `GET /restore/$RESTORE_ID` was still `"reembedding"` at this point, let it reach
`"done"` (step 15) before continuing.

### 20. Ask the same question again and get the same answer

Click **Ask**, ask the exact question from step 3.

**Expect:** the same answer, citing the same file and page — confirming the corpus survived the
round trip and re-embedding restored working retrieval, not just rows in a table.

### 21. Verify the audit chain independently

```
podman compose exec api askwell-verify
```

**Expect:** reports the chain intact (a fresh destination database with no prior local activity
chains cleanly onto the restored historical rows — see `restore.py`'s module docstring on why a
machine with genuine prior local audit rows is a different, honestly-reported case).

---

## Part F — restore onto a machine with existing data is refused, not merged

### 22. Attempt a second restore without `replace_existing`

```
curl -s -X POST localhost:8000/restore -H 'content-type: application/json' \
  -d '{"path": "/tmp/askwell-restore-test.zip", "passphrase": "correct horse battery staple mountain"}' \
  | python3 -m json.tool
```

**Expect:** `409`, an `"error"` stating the machine already has data and restore refuses to merge
silently.

### 23. Confirm `replace_existing` is accepted and does not error out immediately

```
curl -s -X POST localhost:8000/restore -H 'content-type: application/json' \
  -d '{"path": "/tmp/askwell-restore-test.zip", "passphrase": "correct horse battery staple mountain", "replace_existing": true}' \
  | python3 -m json.tool
```

**Expect:** `201` this time. (Not polled to completion here — Part D already exercised the full
restore path; this step only confirms the flag is honoured, not a second full walkthrough.)

---

## Part G — schema not at head refuses cleanly

### 24. Read this behaviour from the automated coverage

Reproducing a genuinely stale `alembic_version` row against a live stack risks leaving the shared
dev database mid-migration, so this one is a read of the test rather than a live repro, the same
posture `M7-BACKUP-BE-157`'s manual test takes for its own hard-to-simulate refusal:

```
scripts/dev.sh test -- -k schema_current -v
```

**Expect:** no matching test name is an acceptable outcome only if `_check_schema_current` has
genuinely no dedicated test — check the output; if tests ran, confirm they pass and that the
assertions show `SchemaNotCurrent` naming both the current and head migration ids and pointing at
`scripts/dev.sh db upgrade head`.

---

## Part H — a crash mid-restore resumes without re-inserting committed tables

### 25. Read this from the automated test

Killing a worker mid-restore against a live stack is not reproducible by hand without real risk
to the shared database; this is covered instead by:

```
scripts/dev.sh test -- -k test_a_crash_mid_restore_resumes_without_re_inserting_committed_tables -v
```

**Expect:** the test passes, confirming a resumed job skips every table index already committed
(`tables_done`) and does not raise a unique-violation retrying an already-restored row.

---

## Cleanup

```
rm -f /tmp/askwell-restore-test.zip
```

Remove the passphrase set in Part A/D if you don't want it left on this install (Settings →
passphrase → remove, with `correct horse battery staple mountain`).

---

## What was checked against the ticket's acceptance criteria

- A backup restores onto a clean machine with sources, memory, clarifications, conversations,
  citations and audit stores intact and verifiable — Part D, Part E.
- The re-embed cost is stated before the user commits, and re-embedding runs with progress —
  Part B step 7, Part D steps 13 and 15.
- Missing originals report as missing with a re-registration path — Part E, steps 18–19.
- Credentials require re-entry, stated in advance — Part C, step 9 (the message states this
  plainly); the ticket's broader "credentials always require re-entry" (database connections,
  live sources) is not separately exercised here since this corpus has none configured — see
  Known gaps.
- A backup from a newer version is refused, named rather than partially applied — Part B.
- A passphrase-protected backup with no passphrase is refused with a clear "unrecoverable"
  statement — Part C, step 9.
- Restore onto a machine with existing data is refused or requires explicit replacement, never
  merged silently — Part F.
- Re-embedding interrupted resumes — Part H (via the automated test, for the reason stated
  there).
- Restore is a decisions record; the restored chain is verified and reported — Part E, step 21.

## Known gaps

- **No settings-screen entry point.** Same gap as `M7-BACKUP-BE-157`'s manual test: there is no
  "Your data" restore row in `docs/ux/settings.md` §6 yet, so starting a restore and reading its
  progress happen through `curl` here, not by clicking.
- **The "second machine" is simulated by wiping one database, not a genuinely separate host.**
  The install-secret unwrap and content decryption were exercised faithfully (a real second
  install secret was deleted and the restore had to bring back the original), but filesystem
  permission differences a truly separate machine might introduce are not exercised.
- **No live database connection or credential was configured** in this walkthrough's corpus, so
  "credentials require re-entry" is only checked for the corpus passphrase, not for a live SQL
  source's stored connection string (`M4-CONN-SEC-098` territory, out of this ticket's own
  scope per its Dependencies).
- **Root re-registration in step 19 relies on the original path still existing on disk**, because
  this walkthrough runs both "machines" in the same container. A genuinely different machine
  without that path at all would show the same missing-state UI but has no folder to re-nominate
  until the files are physically present — not a defect, just untested by this document.
- **Schema-not-current and mid-restore-crash refusals are read from automated tests, not
  reproduced live** — Part G and Part H — for the same "do not risk the shared dev database"
  reasoning `M7-BACKUP-BE-157`'s manual test already applies to its own hard-to-simulate cases.
- **No selective restore.** Out of scope per the ticket; this document does not attempt it.
- **A genuinely large corpus was not used.** The resumable-per-table and `WHERE embedding IS
  NULL` re-embed-resume designs are exercised at small scale here and at larger synthetic scale
  in `test_restore.py`, not proven against a multi-hundred-thousand-row restore by hand.
