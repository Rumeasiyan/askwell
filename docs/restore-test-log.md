# Restore test log

Append-only. **Newest first.** One entry per release, produced by running
`docs/restore-release-test.md`. `AGENTS.md` §3: a release with a failed restore test does not
ship. This file is the retained record that it ran, not a summary written after the fact.

Format per entry:

```
## <version> - <date>

**Result:** pass | fail
**Source:** <platform>, build/commit
**Destination:** <platform> — real second machine, or same-platform simulation (name why)
**Checklist:** docs/restore-release-test.md §4 — list any unchecked box
**Artefact:** where the backup used for this run is retained
**Gaps filed:** issue links, if any
```

---

## 0.7.10 - 2026-09-23

**Result:** fail
**Source:** Linux (this build host), rebuilt image at `0.7.10`
**Destination:** Linux, same host — database wipe simulating a clean machine (no second
machine available, issue #598)
**Checklist:** `docs/restore-release-test.md` §4 — 4.1, 4.2, 4.4, 4.5 pass; 4.3 (citations) and
4.6 (re-embed correctness via repeat answer) unchecked, blocked on issue #220 (the local
model's `<think>` block exhausts the generation token budget before an answer completes, so no
citation ever existed to round-trip). Restore mechanics themselves (corpus, memory, sources,
audit chain, re-embed completion at the data layer) all verified correct.
**Artefact:** `/tmp/askwell-relgate.zip` (not retained past this session — a real release gate
should retain the artefact; noted as a gap for the next run's own storage location)
**Gaps filed:** #597 (a fresh machine's own session bootstrap trips the "existing data"
refusal, found live by this run), #598 (no second-platform machine available), #220
(pre-existing, blocks 4.3/4.6 — re-owned, not fixed here)

Full account: `docs/manual-tests/M7-BACKUP-TEST-159.md`.

---
