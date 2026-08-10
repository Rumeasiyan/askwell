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
- Deployment profile (`edge` / `standard` / `institution`), if relevant:

## Constraint impact

Does this bug break one of the hard constraints in `AGENTS.md` §3? If yes, add the matching `constraint:*` label — these are not ordinary bugs.

- [ ] **C1** — the system made a network call at runtime, or an air-gapped install behaved differently.
- [ ] **C2 / C7** — non-`SELECT` SQL reached the driver, or a restricted column was visible to the model.
- [ ] **C3** — an answer contained a factual claim with no citation.
- [ ] **C4** — the system answered from world-knowledge instead of abstaining.
- [ ] **C5** — an audit event was modified or deleted.
- [ ] **C6** — retrieved content was treated as instruction.
- [ ] None of the above.
