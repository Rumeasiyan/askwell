# Restore release test — the gate

`M7-BACKUP-TEST-159`. Run this once per release, after `docs/release-procedure.md` step 1
(version confirmed) and before step 4 (checksums) / step 5 (publish). **A failed run blocks
the release** —
`AGENTS.md` §3 rule: "a passing gate" for a release means this ran and passed, not that it
looks like it would.

This is the manual walkthrough itself, not a script to run — `M7-BACKUP-TEST-159`'s own Scope
excludes automating it. Follow it as written; it should be reproducible by someone who was not
in the room when the backup/restore code (`M7-BACKUP-BE-157`, `M7-BACKUP-BE-158`) was built.

**Record the result** in `docs/restore-test-log.md` — one entry per release, pass or fail,
per §5 below. That log is the retained artefact this gate produces.

---

## 0. Before you start

Depends on `M7-BACKUP-BE-158` (restore exists) and `M7-PACK-DEPLOY-141` (a packaged build to
restore onto — see the platform note in §3).

**The corpus fixture.** Use `eval/fixtures/corpus/` — the nine-document fixture already
maintained for the eval suite (`docs/build-plan.md` Quality gate). Reusing it means this test
exercises a corpus already known to produce a specific, checkable citation, rather than one
assembled by hand each release and drifting release to release.

Bring the release build's stack up with the built frontend:

```
podman compose up -d
scripts/dev.sh db upgrade head
scripts/dev.sh web-build
podman compose restart api
curl -s localhost:8000/health | python3 -m json.tool   # confirm "version" matches VERSION
```

A curl-only session needs a session cookie first (the interface establishes one on load; a
browser does this automatically):

```
curl -s -c /tmp/askwell-release-gate.cookies -H 'Accept: text/html' localhost:8000/ -o /dev/null
```

Use `-b /tmp/askwell-release-gate.cookies` on every call below.

---

## 1. Source machine — build the corpus and take a backup

### 1.1 Add the fixture corpus

```
curl -s -b /tmp/askwell-release-gate.cookies -X POST localhost:8000/sources \
  -H 'content-type: application/json' \
  -d '{"folder": "<absolute path to eval/fixtures/corpus>", "files": ["conflict_2025.pdf", "conflict_2026.pdf", "figures.xlsx", "handbook_a.pdf", "handbook_b.pdf", "notice_scan.pdf", "spec.docx", "store_hours_2025.pdf", "store_hours_2026.pdf"]}'
```

**Expect:** `201`, `"added": 9`. Poll until every document's `status` is `ready`:

```
scripts/dev.sh psql -c "select status, count(*) from documents group by status;"
```

### 1.2 Ask a known question and note the answer

Reuse an existing, already-validated task rather than inventing a new question each release —
`eval/suites/grounded_qa.v1.json`'s `handbook-a-notice-period` task is a good default (single
source document, unambiguous answer, no conflicting-source pair to confuse the check):

```
curl -s -b /tmp/askwell-release-gate.cookies -X POST localhost:8000/ask \
  -H 'content-type: application/json' \
  -d '{"question": "What is the standard resignation notice period at Meridian Loom?"}' \
  | python3 -m json.tool
```

**This can take minutes on CPU inference** — `/ask` does not return until the turn completes;
do not assume a hang. **Write down the exact answer text and the citation (filename + page).**
This is what §4.3 compares against after restore. If the turn abstains instead of answering,
see §4.3's note on issue #220 before assuming the corpus itself is at fault.

### 1.2a Add a memory fact

A manual fact avoids depending on the clarification loop (a separate, larger surface) just to
put something in `memory` for this gate to check:

```
curl -s -b /tmp/askwell-release-gate.cookies -X POST localhost:8000/memory/facts \
  -H 'content-type: application/json' \
  -d '{"subject": "release gate", "fact": "<a distinctive, checkable sentence naming this run>"}' \
  | python3 -m json.tool
```

### 1.3 Take a backup

`"passphrase"` on `/backup` only matters if content-at-rest encryption is already enabled
(Settings → passphrase, `content_encryption.set_passphrase` — a separate feature from backup
itself); it decrypts content before archiving it, and passing one when encryption was never
enabled does nothing (`preflight.passphrase_protected` stays `false`, silently). Passphrase
protection was already exercised exhaustively by `M7-BACKUP-BE-158`'s own manual test — this
gate does not need to repeat it every release. Skip setting one unless specifically re-checking
that path:

```
curl -s -b /tmp/askwell-release-gate.cookies -X POST localhost:8000/backup \
  -H 'content-type: application/json' -d '{}' \
  | python3 -m json.tool
```

Poll `GET /backup/{id}` until `"status": "done"`, then download:

```
curl -s -b /tmp/askwell-release-gate.cookies -o /tmp/askwell-release-gate.zip \
  localhost:8000/backup/<id>/download
```

---

## 2. Previous release's backup — the real upgrade path

Before wiping for the clean-machine restore, also keep a backup taken under the **previous**
released version, if one exists from that release's own gate run
(`docs/restore-test-log.md`'s last `artefact` entry). If none was retained, note that as a gap
in this run's log entry rather than skipping the check silently — this is the scenario the
ticket calls "the real upgrade path," and it is the one most likely to break silently on a
schema change.

Restoring it is exercised in §3 alongside the current-version artefact (`replace_existing` a
second time, same target, after the current-version restore's own checks in §4 pass) — confirm
`POST /restore/{id}` for the previous-release artefact reaches `"status": "done"` and
`GET /restore/{id}` reports no schema-refusal error. A schema change that breaks restore from
the previous version fails here, which is the point (`AGENTS.md` "Real-World Example
Scenarios").

---

## 3. Destination — a clean machine, cross-platform where the platforms allow

**Cross-platform is the normal case, not a stretch goal.** If a second machine of a different
platform (e.g. build on Linux, restore on macOS or Windows) is available, use it — install the
release build there fresh, following `docs/installing.md` exactly, then run §3.2 onward.

**If a second machine is not available** (the situation this build host is actually in — no
Windows or macOS hardware, the same gap `docs/manual-tests/M7-PACK-DEPLOY-140.md`/`141.md`
already carry for install verification, issues #590/#592), simulate a clean machine on the same
platform by wiping application data — **do not skip the check, name the substitution**:

```
scripts/dev.sh psql <<'SQL'
TRUNCATE roots, sources, documents, document_pages, chunks, memory, schema_notes,
  clarifications, conversations, messages, fact_usage, citations, web_citations,
  settings, audit_decisions, audit_interactions, backup_jobs, restore_jobs CASCADE;
SQL
podman compose exec api sh -c 'rm -f $(python3 -c "from askwell.config import Settings; print(Settings().install_secret_path)")'
podman compose restart api
```

**Expect:** Library shows no sources — a genuinely empty corpus.

**A fresh session cookie is needed after this wipe** — the previous one signed against a
`session_secret` that no longer exists. Re-run the `curl -c ... -H 'Accept: text/html'` step
from §0 before continuing.

**Simulated-clean-machine-only:** the artefact must be reachable from *both* the `api` and
`worker` containers — `/restore/inspect` reads it from `api`, the actual restore job runs in
`worker`. A single-host simulation with no shared bind mount for `/tmp` needs it copied into
both explicitly:

```
podman cp /tmp/askwell-release-gate.zip askwell-api-1:/tmp/askwell-release-gate.zip
podman cp /tmp/askwell-release-gate.zip askwell-worker-1:/tmp/askwell-release-gate.zip
```

A real second machine does not have this problem — the artefact is simply present on it.

### 3.1 Inspect before committing

```
curl -s -b /tmp/askwell-release-gate.cookies -X POST localhost:8000/restore/inspect \
  -H 'content-type: application/json' -d '{"path": "/tmp/askwell-release-gate.zip"}' \
  | python3 -m json.tool
```

**Expect:** `200`, `askwell_version` matching the source machine, `chunk_count` at least `9`,
`estimated_reembed_seconds` positive.

### 3.2 Restore

```
curl -s -b /tmp/askwell-release-gate.cookies -X POST localhost:8000/restore \
  -H 'content-type: application/json' \
  -d '{"path": "/tmp/askwell-release-gate.zip"}' \
  | python3 -m json.tool
```

(Add `"passphrase"` only if §1.3 actually set one.)

**Expect a `409` here today** — "This machine already has data" — even on a genuinely wiped
database. This is issue **#597**: the wipe-and-restart in §3 itself establishes a session on
its first request, which writes a `settings` row (`session_secret`) that
`_existing_data_present` cannot distinguish from real prior activity. Until #597 is fixed, add
`"replace_existing": true` to the request body to proceed — this is not confirming a real
overwrite on a genuinely clean machine, and every gate run should say so in its log entry
rather than let the flag's own "confirm replacing it" language imply otherwise.

Poll `GET /restore/{id}` — **the restore itself also clears and regenerates `settings`, which
invalidates whatever session cookie was used to start it.** Re-issue a fresh cookie (§0's step)
before polling if the previous one starts returning `"No session."`.

**Expect at completion:** `tables_done == tables_total`, `rows_done == rows_total`,
`chunks_done == chunks_total`, `chain_verified: true`.

---

## 4. Verification checklist — everything the backup carried is actually back

- [ ] **4.1 Corpus.** `Library` lists all 9 documents. The originals report as missing-path
      rather than deleted (`docs/ux/source-viewer.md` §4) if the destination cannot see the
      source machine's filesystem — **this is the normal case, exercise it deliberately**
      rather than re-registering the same path first to paper over it. Only once this is
      confirmed, re-register the folder and let re-embedding clear the missing state.
- [ ] **4.2 Memory.** `SELECT count(*) FROM memory;` returns at least the facts stored on the
      source machine, and their history (superseded/current) survived — not just the latest
      row.
- [ ] **4.3 Conversations and citations.** Ask the exact question from §1.2 again. The answer
      text and citation (filename + page) match what was written down — confirming the corpus
      round-tripped and re-embedding restored *working retrieval*, not just rows in a table.
      **Known confound:** issue #220 (the local model's `<think>` block is never stripped and
      can exhaust `Settings.generation_max_tokens` before an answer completes) can prevent a
      question from ever producing a citation to check, independent of anything restore does.
      If a turn abstains where it should answer, first confirm the *same* question also fails
      identically pre-backup on the source machine — if it does, this is #220, not a restore
      defect, and the fallback check is: `chunks.embedding IS NOT NULL` for every row
      (`SELECT count(*) FROM chunks WHERE embedding IS NOT NULL`) matches `chunks_total`,
      proving re-embedding ran even though a live answer could not be produced. Record which
      case applied in the log entry rather than silently checking the box either way.
- [ ] **4.4 Sources.** `Library` lists the source with its original document count.
- [ ] **4.5 Audit chain.** `podman compose exec api askwell-verify` reports the chain intact.
      On a genuinely clean destination this must pass; on a destination that already had real
      local audit activity before a `replace_existing` restore, `chain_verified: false` is the
      *expected*, correctly-reported outcome (issue #574) — not a failure of this gate, but
      note it in the log entry rather than silently treating it as pass.
- [ ] **4.6 Re-embed correctness, not just completion.** §4.3 already covers this, but confirm
      explicitly: the answer after restore is not merely present, it matches pre-backup output.
      A re-embed that "completes" while producing different retrieval results is the failure
      mode this ticket exists to catch (`AGENTS.md` Real-World Example Scenarios).

**Any unchecked box fails the run.** Record it as `fail` in §5 with the specific box — do not
average partial success into a pass.

---

## 5. Recording the result

Append one entry to `docs/restore-test-log.md`, newest first, following its own format.
Include: date, `VERSION`, platforms actually used (source/destination), whether destination was
a real second machine or a same-platform simulation (and why), pass/fail against §4's
checklist, the retained artefact's location, and any gap filed as an issue.

**A `fail` entry blocks the release** — do not proceed to `docs/release-procedure.md` step 4
(checksums) until a passing entry for this `VERSION` exists.
