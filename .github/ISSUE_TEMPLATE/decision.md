---
name: Open decision
about: A question that must be answered before work can proceed
title: ''
labels: blocked:decision
assignees: Rumeasiyan
---

<!-- Do not pick a default and proceed. That is how a build accumulates decisions nobody made. -->

## The question

<!-- One sentence. -->

## What it blocks

<!-- Which phase, which task, and what happens if work proceeds on the wrong assumption. -->

## Options

### Option A —

- Cost:
- Benefit:

### Option B —

- Cost:
- Benefit:

## Recommendation

<!-- Pick one and say why. A question with no recommendation puts the whole analysis back on the reader. -->

## Where it surfaced

- PRD section (if this is a `docs/PRD.md` §11 item, say which number):
- Files:

---

**When answered:** the answer goes in `docs/decisions.md` as an entry, the `docs/PRD.md` §11 item is struck, and `docs/BRAIN.md`'s blocker list is updated — all three in the same change, or the next session reads a different answer depending on which file it opens.
