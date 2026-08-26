# Story backlog

How work is broken down, and the rules a story must satisfy before it is one.

**Nothing here is built until `build-plan.md` Phase 0 lands.** These describe what gets built, in what order, not what exists.

---

## 1. What a story must be

| Rule | Why |
| ---- | --- |
| **A user story** — *As someone with …, I want …, so that …* | If it cannot be phrased from the user's side, it is a task, not a story, and its value is unstated |
| **Three hours or less** | Longer means it was not understood well enough to split. A story that resists splitting is usually a horizontal layer wearing a costume |
| **Vertically sliced** | It ends in something a person can see and use. "Build the ingest pipeline" is not a story; "I can add a PDF and watch it index" is |
| **Its click-path already exists** | Every step needed to reach it has shipped. This is the constraint that produces the ordering for free, and it forces a walking skeleton |
| **Given/When/Then acceptance** | Observable outcomes, not implementation claims |
| **Explicit out-of-scope** | The line that stops a three-hour story becoming a day |
| **A manual test path** | See §3 |

### The role

Askwell is single-user, so the role is almost always the same person. Writing *"As a user"* every time says nothing, so stories name the situation instead — *as someone whose contracts are all PDFs*, *as someone who has just imported a database nobody documented*. The situation is what makes the value checkable.

---

## 2. Milestones

Each ends in something demonstrable. Numbered because they are genuinely sequential — a later milestone's stories cannot be reached until an earlier one has shipped.

| Milestone | Ends with | Phase |
| --------- | --------- | ----- |
| **M0 — It runs** | Askwell starts on a clean machine and says it is ready | 0 |
| **M1 — It answers from my documents** | Add a PDF, ask about it, get a cited answer, click through to the page | 1 |
| **M2 — It says when it doesn't know** | Abstention, partial answers, the empty and failed states | 1 |
| **M3 — It learns my material** | Clarifications raised, answered, remembered, applied, correctable | 2 |
| **M4 — It answers from my data** | CSV and dump import, live connections, SQL shown | 3 |
| **M5 — It handles harder questions** | Multi-step answers with a readable trace | 4 |
| **M6 — I can speak to it** | Voice in, voice out, stop control | 5 |
| **M7 — Someone else can install it** | Installer, updates, backup and tested restore, export | 6 |

**M2 is deliberately its own milestone.** Abstention and the failure states are usually folded into "the chat feature" and then quietly dropped when time runs short. They are the product's central claim (C5) and they get their own demonstrable end.

---

## 3. Every story ships with a manual test

**From a cold start, walking the whole path as a user would.** Launch the app, navigate, click. Never "go to `/sources/add`", never "call the endpoint".

This catches broken navigation, lost state and dead ends that direct-jump testing never sees. It also means every story re-walks the earlier path, so a regression upstream surfaces on the next story instead of in someone's install.

Write **observable outcomes**: *"the answer shows supplier-agreement-2024.pdf, page 14"* is testable by looking. *"the citation is persisted correctly"* is not.

Each test ends with **known gaps** — what is deliberately not built yet, so it is not reported as a defect.

**A story is done when its manual test passes, not when the code compiles.**

---

## 4. Ordering

Dependency order is checked against the **click-path**, not the milestone number. Grouping and sequence are different things: a story sitting in M4 whose path runs through an M2 screen is misordered regardless of its label.

---

## 5. The unglamorous work is in the backlog

None of it is in `PRD.md` and all of it is required to ship. It lives in M7 and is written as stories like everything else: installer, update delivery, backup with a **tested restore**, export and delete, log budget enforcement, crash reporting that respects C1, the licence and notices file, and the support boundary.

Discovering this a week before release is how releases slip.

---

## 6. Estimates

Story estimates are in hours and are optimistic by construction. **Apply 1.3–1.5× past M1** — testing finds defects and defects become work. A total quoted without a rework multiplier is a number nobody should plan against.
