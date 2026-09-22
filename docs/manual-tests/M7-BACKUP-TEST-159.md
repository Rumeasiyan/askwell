# Manual test — M7-BACKUP-TEST-159, the restore release gate's first real run

**Ticket:** `M7-BACKUP-TEST-159` — a documented, repeatable restore gate: back up a representative
corpus, restore onto a clean machine, verify corpus/memory/conversations/citations/audit chain,
record pass or fail. This is the first execution of `docs/restore-release-test.md` against a
real running stack, produced while writing that procedure — not a rehearsal of it.
**Version under test:** `0.7.10`, single Linux build host (no second machine available — see
issue #598).
**Time:** about 40 minutes, most of it CPU-bound local generation (see the citation-check gap
below).

**What is being checked.** `docs/restore-release-test.md` itself, end to end, against
`api/src/askwell/backup.py`/`restore.py` (already built and manually tested individually by
`M7-BACKUP-BE-157`/`-158`) — this ticket's own job is proving the *procedure* works as written
for someone who did not build the restore code, not re-proving the restore code itself.

---

## What was actually run

1. Rebuilt the API image (`scripts/dev.sh build-api`) so the running stack reported `0.7.10`,
   matching `VERSION` — the stack was stale at `0.7.4` before this.
2. Registered `eval/fixtures/corpus/` as a root and added its 9 documents via `POST /sources`
   (`ASKWELL_ROOTS_MOUNT` pointed at the repo root for this session). All 9 reached `ready`.
3. Added one manual memory fact via `POST /memory/facts` (§1.2's "known question" substitute
   for the memory checklist item — see the gap below for why a document-grounded fact could not
   serve the same purpose here).
4. `POST /backup` with no passphrase (see the gap on passphrase below) — `done` at
   `tables_total: 16`, `chunk_count: 15`, `file_bytes: 23002`. Downloaded the artefact.
5. Wiped the database (`docs/restore-release-test.md` §3's `TRUNCATE`/install-secret-removal
   sequence) and restarted the API — simulating a clean machine on the same host.
6. `POST /restore/inspect` confirmed `askwell_version: "0.7.10"`, `chunk_count: 15` — matching
   the source side.
7. `POST /restore` with no `replace_existing` was refused: **"This machine already has data."**
   on a database with every table genuinely empty except one `settings` row — the session
   signing secret, written by the very first request the wiped API served. Filed as
   **issue #597**: a fresh machine's own session bootstrap trips the "existing data" refusal
   before a user has done anything, which means a plain restore will not actually work on a real
   clean install once the interface has loaded once (every installer's own last step). Worked
   around here with `replace_existing: true`, which is what any real user would also have to do
   today — recorded as a defect in the procedure's assumption, not a defect in this run.
8. `POST /restore` with `replace_existing: true` reached `status: done`:
   `tables_done: 16/16`, `chunks_done: 15/15`, `chain_verified: true`.

---

## Verification checklist (`docs/restore-release-test.md` §4)

- [x] **4.1 Corpus.** All 9 documents present, `status: ready`, `document_pages: 44`,
      `chunks: 15` — matching the backup manifest exactly. **Not exercised**: the missing-path
      state, since source and destination share one container's filesystem (the same limitation
      `docs/manual-tests/M7-BACKUP-BE-158.md`'s own "Known gaps" names for the identical reason).
- [x] **4.2 Memory.** The manual fact from step 3 is present with its exact subject and text
      after restore.
- [ ] **4.3 Conversations and citations — partial.** `conversations: 3`, `messages: 6` survived
      restore intact (row-for-row match against the source side). **Citations did not** —
      `citations.jsonl` in the backup artefact was empty (`0` bytes), because none of the three
      `/ask` attempts against the corpus during this walkthrough produced a completed, cited
      answer: the local model (`Qwen3.5-4B-Q4_K_M.gguf`, CPU inference, `balanced` profile)
      repeatedly exhausted `Settings.generation_max_tokens` (1024) inside its own `<think>`
      block before emitting a delimited answer, and the turn was scored as abstained rather than
      answered. This is **issue #220**, already open and unrelated to backup/restore — its
      `<think>` block is never stripped, and on a small, CPU-bound generation budget that means
      it can consume the entire budget before the actual answer starts. Re-owned rather than
      fixed here (`AGENTS.md` §9: resolve, re-own, or escalate) — it is a generation-quality
      issue, not a backup/restore one. The restore mechanics were still exercised correctly
      (0 citations backed up, 0 citations restored — the row count matches on both sides, which
      is what a citation check can actually prove until #220 is fixed).
- [x] **4.4 Sources.** `Library`'s equivalent (`sources` table) shows 1 source, 9 documents,
      matching pre-backup.
- [x] **4.5 Audit chain.** `podman compose exec api askwell-verify` reports both stores intact
      (`audit_decisions: 20 records, chain intact.` `audit_interactions: 3 records, chain
      intact.`) independently of the restore job's own `chain_verified: true`/`chain_detail`.
- [ ] **4.6 Re-embed correctness — not verified by re-asking.** Same root cause as 4.3: with no
      completed answer on either side of the restore, the "ask again, get the same answer" check
      could not run. Substituted with a data-level equivalent instead: `chunks_done` (15)
      matches `chunk_count` from both `/backup` and `/restore/inspect`, and `chunks.embedding`
      is non-null for all 15 rows post-restore (`SELECT count(*) FROM chunks WHERE embedding IS
      NOT NULL` = 15) — proving re-embedding actually ran and completed, not merely that the job
      reported `done`. This is a weaker check than the ticket's own stated one and is recorded
      as a gap, not silently treated as equivalent.

## §2 — previous release's backup, restored onto this one

**Not run.** This is the first entry in `docs/restore-test-log.md` — no prior release's own
gate artefact exists to restore. `docs/restore-release-test.md` §2 already names this as an
acceptable, honestly-recorded gap rather than a reason to skip the check silently; the next
release's gate run is the first that can actually exercise it, using this run's own retained
artefact as the "previous release" side.

## §3 — cross-platform

**Not run for real.** Single Linux build host, no Windows or macOS hardware — the destination
was a same-platform database wipe, not a genuinely separate machine. Filed as **issue #598**,
the restore-gate-specific counterpart to the install walkthrough's own #590/#592.

---

## Two real, previously-unknown defects this run found

1. **Issue #597** — the session-bootstrap-trips-existing-data-check defect above. This is the
   headline finding of this run: it means the "refuse to merge silently" protection
   (`docs/decisions.md`'s restore design) currently cannot distinguish a machine with real prior
   activity from a machine that has only ever loaded the interface once, which is every machine.
2. A small doc bug carried into this run from copying `docs/manual-tests/M7-BACKUP-BE-158.md`'s
   own commands verbatim: `scripts/dev.sh db psql <<'SQL' ...` is not a valid invocation —
   `scripts/dev.sh db` is alembic-only (`scripts/dev.sh db upgrade head`, etc.); the psql shell
   is `scripts/dev.sh psql` with no `db` prefix. Fixed in both `M7-BACKUP-BE-158.md` and
   `docs/restore-release-test.md` in this same change — too small for its own issue
   (`AGENTS.md` §8 "too small for an issue"), but worth naming here since it means `-158`'s own
   manual test, as written, was never actually runnable verbatim.

---

## Result

**Fail**, per `docs/restore-release-test.md` §4's own rule ("any unchecked box fails the run —
do not average partial success into a pass"): 4.3 and 4.6 are unchecked. Everything restore
itself is responsible for came back correct — corpus, memory, sources, the audit chain, and
re-embedding actually running to completion (verified at the data layer). What did not verify
is the ticket's own explicit acceptance criterion that citations reproduce and are checked,
and that cannot be honestly marked passed when no citation existed to round-trip in either
direction. The blocker is issue **#220** (pre-existing, not introduced by backup/restore), plus
**#597** (found by this run) for the practical "every real restore needs `replace_existing`"
defect. **A real release should not ship as gate-passed on this evidence alone** — the next
gate run, after #220 is fixed (or after confirming a working answer through some other model
configuration), is what should actually pass or fail against the full checklist. Recorded in
`docs/restore-test-log.md` as `fail`, with both blockers named.
