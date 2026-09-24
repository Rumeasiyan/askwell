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

No release has been run against this checklist yet.
