# Screen: Memory

Everything Askwell believes about the user's material, and where each belief came from.

> **This document is the specification. Any mockup is a reference.**

**Route:** `/memory`
**Entry points:** left rail, any memory chip in an answer, after answering clarifications.
**Phase:** 2

---

## 1. What it is for

`../memory-and-clarification.md` §5 commits to this: **every fact is visible, editable and deletable.** A memory the user cannot inspect is a system that gets mysteriously worse and cannot be debugged.

This screen is that promise. It is also the only place the user can see what Askwell *guessed* — which is where wrong answers come from long before anyone notices.

---

## 2. Shape

One list, grouped by subject. Two kinds of fact, visually distinct but in the same list:

- **Structural** — attached to a table or column. *`invoices.st_cd` — invoice status: O=open, P=paid, W=written off*
- **General** — free-standing. *RFQ means Request for Quotation* · *the 2025 policy supersedes the 2024 handbook*

Every row carries the **confidence marker** (`design-system.md` §7): filled green if the user supplied it, hollow ochre if Askwell inferred it.

**Default sort puts inferred facts first.** They are the ones worth reviewing; confirmed facts are settled. Sorting alphabetically would bury exactly what the screen exists to surface.

---

## 3. A row

```
▪ invoices.st_cd                                    sales-2024
  Invoice status: O=open, P=paid, W=written off
  You told me · 3 June · used in 12 answers          [Edit] [Delete]

▫ invoices.amount_gbp                               sales-2024
  Amounts in pounds sterling
  I guessed · from the column name · used in 4 answers  [Confirm] [Edit] [Delete]
```

**"Used in N answers" is the number that makes this screen worth opening.** A wrong fact used once is a nuisance; used in forty answers it has been quietly corrupting results for weeks, and the count is the only way to notice.

Inferred facts get **Confirm** as well as Edit — one click to promote a good guess, which is far cheaper than retyping it and is how the inferred pile gets cleared.

---

## 4. Interactions

| Action | Result |
| ------ | ------ |
| Edit | In place. Saving supersedes the old fact and re-processes what depends on it |
| Confirm | Inferred → user-supplied. No re-processing; the content did not change |
| Delete | Stops applying immediately. Recorded in the decisions log |
| History | Every prior value with dates. Memory supersedes, never overwrites |
| Filter | Inferred only · by source · unused |
| Add a fact | Manual entry, for someone who wants to tell Askwell something before being asked |

**Manual entry matters more than it looks.** A user who has learned what memory does will want to front-load their own vocabulary rather than wait to be asked, and refusing that would be perverse.

---

## 5. States

| State | What is shown |
| ----- | ------------- |
| **Empty** | What memory is and that it fills as Askwell asks. Names the clarification queue as the way to start |
| **Populated, nothing inferred** | Clean list. The good state |
| **Inferred pending review** | Those first, with a count. Not an alarm — guessing is normal and often right |
| **Edited, re-processing** | Per-fact progress. Sources stay queryable |
| **Fact from a deleted source** | Structural facts go with the source. General facts survive and say so: *learned from a source you deleted* |
| **Conflicting facts** | Later wins, earlier shown struck through in history. Never silently discarded |
| **Unused fact** | Filterable. Not deleted automatically — a fact used zero times may just be waiting for the right question |

---

## 6. What this screen must not do

- **Never auto-delete.** Not unused facts, not old ones, not low-confidence ones. Automatic expiry silently discards something the user supplied, which is worse than holding a stale fact they can see.
- **Never hide inferences.** The ochre pile is uncomfortable and it is the honest state. Showing only confirmed facts would make Askwell look more certain than it is.
- **Never present memory as learning or training.** It is a list of facts, retrieved like any other. That framing is what makes it inspectable and reversible.

---

## 7. Open

1. **Bulk confirm** for a run of inferences from one import. Fast, and it risks rubber-stamping — probably needs the facts visible while confirming rather than a single button.
2. **Export and import** across machines (`../memory-and-clarification.md` §9). Not v1.
