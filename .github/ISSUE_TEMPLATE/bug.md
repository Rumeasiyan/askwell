---
name: Bug
about: Something behaves incorrectly
title: ''
labels: bug
assignees: Rumeasiyan
---

## What happens

<!-- Observed behaviour. Paste the exact error or output, not a paraphrase. -->

## What should happen

## Reproduce

1.
2.

## Where

- Phase / PRD section:
- Files:
- Version (`cat VERSION`):
- Deployment profile (`light` / `standard` / `accelerated` / `workstation`), if relevant:

## Constraint impact

Does this bug break one of the hard constraints in `AGENTS.md` §3? If yes, add the matching `constraint:*` label — these are not ordinary bugs.

- [ ] **C1** — a network call happened in local mode, or content left without explicit online opt-in.
- [ ] **C2** — non-`SELECT` SQL reached the driver.
- [ ] **C3** — an imported dump reached outside its sandbox database.
- [ ] **C4** — an answer contained a factual claim with no citation.
- [ ] **C5** — the system answered from general knowledge instead of abstaining.
- [ ] **C6** — an audit record was modified, lost, or the hash chain broke.
- [ ] **C7** — retrieved content was treated as instruction.
- [ ] None of the above.
