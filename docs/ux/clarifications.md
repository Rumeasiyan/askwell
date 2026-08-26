# Screen: Clarifications

Where Askwell asks what it could not work out, and where the memory that makes it better gets written.

> **This document is the specification. Any mockup is a reference.**

**Route:** `/clarifications`
**Entry points:** count badge in the left rail; a prompt after ingestion finishes; inline in an answer when a question blocks it (`ask.md` §5).

---

## 1. What it is for

Turning the things Askwell genuinely cannot know into permanent facts, without becoming a chore.

**The failure mode this screen is designed against is its own success.** Every question raised is a small tax on the user. A user who opens this and sees forty questions closes it and never returns, and the feature that was the reason to choose Askwell becomes the reason to uninstall it. Capped at 5 per source (`../memory-and-clarification.md` §8), and the screen must feel finishable.

---

## 2. Shape

A single reviewable list, newest source first, grouped by source. Not a wizard, not a modal queue, not one-at-a-time.

The user must be able to see how much there is before starting. A one-at-a-time flow hides the end, which is exactly what makes people abandon it — and answering three of five is a perfectly good outcome that the design should make easy rather than treating as incomplete.

Each item is answerable in place. No navigation, no confirmation step.

---

## 3. Anatomy of one question

```
┌──────────────────────────────────────────────────────────┐
│ ▪ students.st_cd                          sales-2024.sql │
│                                                          │
│   What does st_cd mean?                                  │
│   40,112 rows. Values: A (31,204) · T (6,890) · D (2,018)│
│                                                          │
│   ┌────────────────────────────────────────────────────┐ │
│   │ Student status code: A=active, T=transferred…      │ │
│   └────────────────────────────────────────────────────┘ │
│                                                          │
│   [ Save ]  [ Skip ]              I guessed: status code │
└──────────────────────────────────────────────────────────┘
```

| Part | Rule |
| ---- | ---- |
| Subject | Mono. The exact table.column or filename and page |
| Question | Serif, one sentence, plain language |
| **Evidence** | The actual data — value distribution, row count, the passage. Mono |
| Answer field | Free text, prefilled with the inference where there is one |
| Current inference | Shown with the hollow `--inferred` marker, so the user sees what happens if they skip |
| Skip | Equal weight to Save. Skipping is a legitimate answer |

**Showing the evidence is what makes this answerable.** "What does `st_cd` mean?" is a quiz. The same question with the value distribution beside it is usually self-answering — a user sees A/T/D with those counts and remembers immediately. Without the data the screen is an exam, and people do not do exams.

---

## 4. Interactions

| Action | Result |
| ------ | ------ |
| Type an answer, `Enter` | Saves, writes the fact, marks affected material for re-processing, advances |
| Skip | Keeps the inference as low-confidence. Not raised again for this source |
| Skip all for a source | Dismisses the group. Recorded — the dismissal rate is a tracked signal |
| Choose an offered option | Where options are discrete (date formats, which of two documents is current), offer buttons rather than a text field |
| Undo | Available for 10s after saving |

### After saving

Confirm what changed, specifically: *"Saved. Re-reading 3 tables that use `st_cd`."*

Not a generic toast. The user needs to see that answering did something, or they will not answer the next one. This is the entire feedback loop that makes the feature worth having.

---

## 5. States

| State | What is shown |
| ----- | ------------- |
| **None pending** | Not "no items". *"Nothing to clarify. Askwell asks when it finds something it can't work out — an unlabelled column, a date format, two documents that disagree."* Teaches the feature to someone who has not met it |
| **Pending** | Grouped by source, count per group, total at top |
| **Ingestion still running** | Questions appear as they are raised. The source is already queryable |
| **All answered** | Brief completion state naming what improved: *"5 answered. 2 tables and 14 documents re-read."* Then back to the empty state |
| **Answered, re-processing** | Per-item progress. The source stays queryable throughout |
| **Blocking an answer** | Rendered inline in the conversation instead (`ask.md` §5) — never bounce the user here mid-question |
| **Capped** | If a source produced more than 5 candidates, say so: *"Asking about the 5 that matter most. Askwell inferred the rest — you can review them in Memory."* Honest about what was not asked, and routes to where it can be corrected |

---

## 6. What this screen must never do

- **Never block.** Not on ingestion, not on asking a question, not on startup. Answering is always optional (`../memory-and-clarification.md` §2).
- **Never nag.** A badge with a count. No modal on launch, no repeated prompting, no red dot that implies something is broken. Nothing is broken; Askwell is working without the answers.
- **Never ask twice.** Memory is checked before any question is raised. The same abbreviation across two sources is one question.
- **Never ask what it can infer.** `created_at` is not a question. Every avoidable question spends credit that the genuinely ambiguous ones need.

---

## 7. Why this screen exists at all

The old design asserted that schema annotations improve answers more than a model upgrade, then expected someone to sit down and write hundreds of them voluntarily. Nobody ever does.

This screen is the version that works: one specific question, at the moment of ambiguity, with the data in front of the user, answerable in five seconds. That is the whole difference between a feature that populates and one that does not.

---

## 8. Open

1. **Settled: the ranking is not shown.** Explaining why a question made the top five spends the user's attention on Askwell's bookkeeping rather than on the answer it needs. The cap is already stated honestly when it bites (§5, capped state); that is the disclosure that matters.
2. **Settled: one question, applied to all matching columns, with the set named.** Five columns called `*_cd` across three tables is one thing the user knows and five questions they will resent. The question states which columns it covers and the answer applies to all of them — and each remains individually editable in Memory afterwards, so a wrong generalisation is cheap to undo.
