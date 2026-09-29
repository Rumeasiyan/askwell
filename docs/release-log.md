# Release log

Append-only. **Newest first.** Each release gets one entry, produced by running
`docs/release-checklist.md`. The release does not ship until an entry for its exact
`VERSION` reads `Decision: release` (`M7-QA-TEST-168`).

Evidence that the per-gate logs do not already hold goes in `docs/release-evidence/<version>/`,
committed alongside the entry: the eval result JSON, the performance result JSON, and the
filled-in walkthrough copies. `eval/results/` is gitignored because it holds development runs.
Release evidence is kept on purpose, so it is written somewhere that is not ignored.

Format per entry:

```
## <version> - <date>

**Decision:** release | held
**Commit:** <SHA every gate ran against>
**Schema revision:** <`alembic heads` on the release commit — the revision a rollback to this release targets (`docs/rollback-and-incidents.md` §1.1)>
**Platforms:** released: <list> · walked: <list> · not covered: <list, with reason>

| Gate | Result | Evidence |
| ---- | ------ | -------- |
| G1 Version and changelog | PASS / FAIL / BLOCKED / ACCEPTED | ... |
| G2 Automated checks | | CI run URL, command summary lines |
| G3 Eval — grounded_qa.v1 | | mean / worst-of-3, file |
| G3 Eval — abstention.v1 | | mean / worst-of-3, file |
| G3 Eval — conflicting_sources.v1 | | mean / worst-of-3, file |
| G3 Eval — text_to_sql.v1 | | mean / worst-of-3, file |
| G3 Eval — sql_safety.v1 | PASS / FAIL only | file |
| G3 Eval — tool_selection.v1 | | mean / worst-of-3, file |
| G3 Eval — memory_apply.v1 | | mean / worst-of-3, file |
| G3 Eval — web_escalation.v1 | PASS / FAIL only | file |
| G4 Offline | | docs/offline-test-log.md entry |
| G5 Restore | | docs/restore-test-log.md entry |
| G6 Security review | | docs/security-review-log.md entry |
| G7 Performance | | files, p50/p95 cold and warm |
| G8 Licence and notices | | exit code, NOTICES.md commit |
| G9 Support boundary | | `gh api` output verbatim |
| G10 Artefacts and cold install | | per platform |
| G11 Walkthrough | | per platform: PASS, or failing step numbers + issues |
| G12 Open defects | | each open `bug` issue and its disposition |
| G13 Online mode | | docs/online-test-log.md entry, capture file |

**Accepted known issues:** none | per issue: #<n> — why shipping with it is acceptable — the
follow-up that removes it (docs/release-checklist.md, rule 4)
**Held because:** (only when held) the gates that failed or were blocked, with their issues
```

---

## 0.9.0 - 2026-09-29

**Decision:** release — as a **GitHub pre-release (beta)**, by the product owner's decision of 2026-09-29 (`docs/decisions.md`). **Most gates below were not run.** That is recorded as *not run*, never as passed, and shipping a beta on that basis was an explicit choice, not an oversight. `1.0.0` must run this checklist in full.
**Commit:** `3176f25479ba870a53b5da6e60033ccd3c91121d` (tag `v0.9.0`)
**Schema revision:** `f4b8d2c6a915`
**Platforms:** released: Linux x86-64, Windows x86-64, macOS arm64 · walked: none · not covered: all three cold installs (no clean machine on the build host; Windows and macOS hardware, #590 and #592)

| Gate | Result | Evidence |
| ---- | ------ | -------- |
| G1 Version and changelog | PASS | `VERSION` 0.9.0; `CHANGELOG.md` 0.9.0 entry; tag matched `VERSION` in release run 36516502370 |
| G2 Automated checks | PASS | CI green on #820 and #822; `scripts/dev.sh check` passed on the release commit's parents |
| G3 Eval — grounded_qa.v1 | FAIL | mean 0.74 / worst-of-3 0.66, bar 0.85; `docs/BRAIN.md` Eval baseline (#817, #818) |
| G3 Eval — abstention.v1 | FAIL | mean 0.53 / worst-of-3 0.40, bar 0.90; `docs/BRAIN.md` Eval baseline (#769, #814) |
| G3 Eval — conflicting_sources.v1 | NOT RUN | — |
| G3 Eval — text_to_sql.v1 | NOT RUN | — |
| G3 Eval — sql_safety.v1 | NOT RUN | — |
| G3 Eval — tool_selection.v1 | NOT RUN | — |
| G3 Eval — memory_apply.v1 | NOT RUN | — |
| G3 Eval — web_escalation.v1 | NOT RUN | — |
| G4 Offline | NOT RUN | no machine on the build host that can be disconnected (#598) |
| G5 Restore | NOT RUN | — |
| G6 Security review | NOT RUN for this release | last full review `0.7.18` (`docs/security-review-log.md`) |
| G7 Performance | NOT RUN | — |
| G8 Licence and notices | PASS | `scripts/dev.sh notices` exit 0, "no disallowed or unclear licences found"; `NOTICES.md` in #820 |
| G9 Support boundary | NOT RUN | — |
| G10 Artefacts and cold install | PARTIAL | artefacts built for all three platforms by release run 36516502370, `SHA256SUMS` verified to cover all three; no cold install run on any platform |
| G11 Walkthrough | NOT RUN | — |
| G12 Open defects | ACCEPTED as beta | open bugs not dispositioned one by one; the two measured shortfalls and the platform gap are stated in the release notes |
| G13 Online mode | NOT RUN | needs a real provider key |

**Accepted known issues:** #769, #814 — abstention below its bar. The release notes explain the near-miss failure and tell users to check the citation. Follow-up: C5 work toward `1.0.0`, starting with the 9B model on the GPU profile. #817, #818 — question routing between documents and spreadsheets. Follow-up: one routing fix. #590, #592 — Windows and macOS untested. Follow-up: the product owner's own testing of these artefacts.

