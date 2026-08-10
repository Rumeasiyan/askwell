---
name: Task
about: A unit of build work
title: ''
labels: ''
assignees: Rumeasiyan
---

<!-- The reader has not seen the conversation this came from. No "as discussed". -->

## What

<!-- One or two sentences. What gets built or changed. -->

## Why it matters

<!-- The concrete consequence of not doing this. Not "this is important". -->

## Where it surfaced

<!-- File paths, PRD section numbers, commit SHAs. Enough that someone can find it without asking. -->

- PRD section:
- Phase:
- Files:

## Done when

<!-- Observable, not "the implementation is finished". What command is run and what does it return? -->

- [ ]

## Constraint check

Tick every one this work touches, and add the matching `constraint:*` label. **An issue with a `constraint:*` label cannot be closed without a comment stating how the constraint was preserved.**

- [ ] **C1 sovereignty** — could this introduce a runtime network call, or something not bundled at build time?
- [ ] **C2 / C7 SQL safety** — does this touch SQL generation, validation, database roles, or column visibility?
- [ ] **C3 / C4 grounding** — does this touch citations, retrieval thresholds, or abstention behaviour?
- [ ] **C5 audit** — does this touch the audit log or its grants?
- [ ] **C6 injection** — does this touch how retrieved content reaches the model?
- [ ] None of the above.

## Version impact

<!-- See AGENTS.md §7. -->

- [ ] MAJOR (breaking)
- [ ] MINOR (backward-compatible feature)
- [ ] PATCH (bug or security fix)
- [ ] None (docs, tests, refactor, formatting)
