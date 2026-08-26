# M3 — It learns my material

**Goal:** Askwell asks about what it genuinely cannot know, remembers the answers, applies them to later questions, and lets the user inspect and correct every belief it holds.

**Phase:** 2 (`../build-plan.md`) · **Depends on:** M2 · **Tickets:** 19 · **Estimated:** 56–78 hours

**Exit condition:** Adding a source with a genuine ambiguity raises at most five ranked questions with the evidence beside each; answering one visibly changes a subsequent answer; the resulting fact is inspectable, correctable from inside an answer, and deletable; and the memory eval subset scores at or above 0.85.

> **Deliberately before database work.** Memory shapes ingestion and the data model, and the database path is where it pays off most. Building databases first means rebuilding the schema-notes path afterwards.

## Included epics

| Epic | Code | Covers |
| ---- | ---- | ------ |
| Raising questions | `RAISE` | Ambiguity detection, ranking, the cap, evidence |
| Reviewing | `REVIEW` | The clarifications screen and its states |
| Storing | `STORE` | Memory, schema notes, origin, supersession, audit |
| Applying | `APPLY` | Retrieval, citation of facts, re-processing |
| Correcting | `CORRECT` | Chips in an answer, supersession, the memory screen |
| Evaluation | `EVAL` | The memory subset |

---

### M3-RAISE-BE-068 — Ambiguity detection with the three tests for asking

**Type:** Story

**User Story**
- **Actor:** someone who has just added a folder of unfamiliar exports.
- **User Need:** to be asked only about things that genuinely matter and that they can actually answer.
- **Business Value:** the failure mode to design against is asking too much; a user asked two hundred questions closes Askwell and does not come back.
- *As someone importing material I did not create, I want to be asked only about the things nobody could work out, so that answering feels worth it.*

**Context / Background**
**Detailed Description:** A candidate question is raised only when all three hold: Askwell genuinely cannot determine the answer, the answer materially changes future results, and the user plausibly knows. If any fails, infer, record the inference as low confidence, and move on. Qualifying triggers include unguessable column names, ambiguous date formats, contradictions between sources, unreadable scans, ambiguous document identity, and domain abbreviations.

**Scope**
- Candidate generation for each qualifying trigger available in M3 — abbreviations, contradictions, unreadable scans, ambiguous document identity. Column and date triggers become live when data sources arrive in M4 and the mechanism is built here.
- The three tests applied as a filter, with the reason a candidate was dropped recorded.
- Inference recorded as low confidence for everything not asked.

**Out of Scope**
- Ranking and the cap (M3-RAISE-BE-069).
- The screen (M3-REVIEW-FE-072).
- CSV and schema triggers becoming live (M4).

**Acceptance Criteria**
- **Acceptance Criteria:** A source containing a genuine ambiguity produces a candidate. A source containing only inferable things produces none. Anything not asked is recorded as an inference with low confidence and is visible in memory. Formatting, encoding and anything the user cannot answer never produces a question.
- **Edge Cases:** A source with no ambiguity at all — no questions, and the ingestion completes silently rather than inventing one. An abbreviation appearing once — filtered by the materiality test. A contradiction between a document and a superseded version — not a contradiction. A trigger firing on a document that later fails extraction — the candidate is dropped with the document.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/clarifications.md` §6 — never ask what it can infer.
- **Validation Rules:** All three tests must pass; a candidate failing any is inferred, not asked.
- **Audit / Logging Requirements:** Candidates raised and dropped are logged with the reason.
- **Analytics Events:** Local counters of candidates raised, asked and inferred — nothing transmitted (C1).

**Real-World Example Scenarios**
- Importing a set of tender documents raises one question about what RFQ means and infers everything else.

**Dependencies & Assumptions**
- **Dependencies:** M1-ADD-ING-025, M2-PARTIAL-BE-059.
- **API / Data Touchpoints:** `clarifications`, `memory`, `schema_notes`.
- **Assumptions:** Trigger detection during ingestion is cheap enough not to slow it materially; expensive detection is deferred to after indexing completes.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, add a document containing a repeated unexplained abbreviation and another that contradicts an existing document. When indexing finishes, open the clarifications screen and confirm exactly those two things were raised and nothing trivial was. Add a plain, unambiguous document and confirm no question appears.
- **Other scenarios:** Confirm inferred items appear in memory marked as guesses.
- **Known gaps:** Column and date triggers cannot fire until M4. Detection is heuristic and will both miss and over-raise; the cap and the dismissal signal are the safeguards.

**Effort & Granularity Check**
- **Estimate:** 4–6 hours · **Priority:** Critical
- **Labels / Component:** `phase:2`, backend, ingestion
- **Granularity:** Four triggers sharing one filter. Upper bound.

---

### M3-RAISE-BE-069 — Ranking and the cap of five per source

**Type:** Story

**User Story**
- **Actor:** someone who just imported a large, messy archive.
- **User Need:** the few questions that matter, not everything that could be asked.
- **Business Value:** silently generating two hundred questions is the failure mode the cap exists to prevent, and five is reviewable in under a minute.
- *As someone who imported four hundred files, I want at most a handful of questions per source, so that reviewing them is a minute rather than an afternoon.*

**Context / Background**
**Detailed Description:** Where a source produces more than five candidates, rank them: contradictions between sources first, then date-format ambiguity where the data cannot disambiguate, then unguessable columns weighted by the volume of data behind them, then abbreviations by corpus frequency, then low-confidence scans weighted by document size. Everything below the cap is inferred, recorded as low confidence, and left visible in memory. The cap is user-adjustable and defaults to five.

**Scope**
- Ranking function implementing the documented order.
- Cap enforcement per source, adjustable in settings.
- Storage of the rank so it is known which questions made the cut.
- The capped state's data: how many were not asked.

**Out of Scope**
- Displaying the ranking reason to the user, which is an open question in `../ux/clarifications.md` §8.
- Bulk patterns across similar columns, also open.

**Acceptance Criteria**
- **Acceptance Criteria:** A source producing ten candidates asks five, stores their ranks, and infers the rest. A contradiction outranks an abbreviation. Raising the cap in settings raises the number asked on the next source. The count not asked is available for the capped state.
- **Edge Cases:** Exactly five candidates — no capping message. Ties in rank — broken deterministically so two runs agree. A source producing candidates over time as ingestion progresses — the cap applies to the source overall, not per batch, so a late high-ranking contradiction can displace a lower-ranked question that has not been answered yet.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/clarifications.md` §5 capped.
- **Validation Rules:** The cap defaults to five and is never raised silently.
- **Audit / Logging Requirements:** Cap changes are decisions records.
- **Analytics Events:** Local counters of asked versus inferred — nothing transmitted (C1).

**Real-World Example Scenarios**
- A messy import produces thirty candidates; the user is asked five, three of which are contradictions, and the rest are inferred and visible.

**Dependencies & Assumptions**
- **Dependencies:** M3-RAISE-BE-068.
- **API / Data Touchpoints:** `clarifications.rank`.
- **Assumptions:** Five is the number most likely to be wrong; the dismissal signal is what would catch it, and there is no telemetry, so the cap is deliberately conservative.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, add a source engineered to produce many candidates. Open clarifications and count — five, with a statement that the rest were inferred and where to review them. Follow that route to memory and confirm the inferred items are there. Raise the cap in settings, add a similar source, and confirm more are asked.
- **Other scenarios:** Run the same import twice and confirm the same five are chosen.
- **Known gaps:** The ranking reason is not shown. Bulk patterns are asked individually.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** Critical
- **Labels / Component:** `phase:2`, backend
- **Granularity:** One ranking and one cap.

---

### M3-RAISE-BE-070 — Check memory before raising any question

**Type:** Task

**User Story**
- **Actor:** someone adding their fourth source that uses the same abbreviation.
- **User Need:** never to be asked the same thing twice.
- **Business Value:** asking twice is how the feature becomes annoying rather than useful.
- *As someone who already told Askwell what RFQ means, I want never to be asked again, so that the loop feels like it is learning rather than forgetting.*

**Context / Background**
**Detailed Description:** Before a candidate becomes a question, memory and schema notes are checked. A fact already known suppresses the question and is applied instead. The same subject across two sources is one question, asked once. A superseded fact does not resurrect the question; the current fact applies.

**Scope**
- Memory lookup by subject before raising.
- Suppression with the applied fact recorded on the source so the user can see it was applied rather than asked.
- Handling of skipped questions: not raised again for that source.

**Out of Scope**
- Cross-machine memory import (not v1).

**Acceptance Criteria**
- **Acceptance Criteria:** A subject already in memory produces no question and the existing fact is applied. Adding a second source with the same abbreviation asks nothing. A skipped question is not raised again for that source. A superseded fact is applied in its current form.
- **Edge Cases:** A subject in memory with low confidence from an inference — still suppresses the question but is surfaced in memory for review, because asking about your own guess is different from asking about the user's material. A near-match subject that is not the same thing — must not suppress; false suppression is worse than a duplicate question.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/clarifications.md` §6 — never ask twice.
- **Validation Rules:** Memory is checked before every question is raised, without exception.
- **Audit / Logging Requirements:** Suppressions are logged with the fact applied.
- **Analytics Events:** Local counter of suppressed questions — nothing transmitted (C1).

**Real-World Example Scenarios**
- The user answers one question about an abbreviation and the next three imports never mention it.

**Dependencies & Assumptions**
- **Dependencies:** M3-RAISE-BE-069, M3-STORE-BE-076.
- **API / Data Touchpoints:** `memory`, `schema_notes`, `clarifications.status`.
- **Assumptions:** Subject matching is exact or near-exact; fuzzy matching risks false suppression and is not used.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, add a source that raises a question about an abbreviation, and answer it. Add a second source using the same abbreviation. Open clarifications and confirm nothing was asked about it. Open memory and confirm the fact is there and marked as applied.
- **Other scenarios:** Skip a question, re-index the same source, and confirm it is not asked again.
- **Known gaps:** Near-synonym subjects are treated as different and may be asked separately.

**Effort & Granularity Check**
- **Estimate:** 2–3 hours · **Priority:** High
- **Labels / Component:** `phase:2`, backend
- **Granularity:** One lookup and one suppression rule.

---

### M3-RAISE-BE-071 — Capture the evidence that makes a question answerable

**Type:** Story

**User Story**
- **Actor:** someone looking at a question about a column they have never seen.
- **User Need:** the actual data beside the question.
- **Business Value:** "what does this mean?" is a quiz; the same question with the value distribution beside it is usually self-answering, and people do not do exams.
- *As someone being asked about my own data, I want to see the values and counts, so that I remember the answer instead of guessing.*

**Context / Background**
**Detailed Description:** Every question stores its evidence: the value distribution and row count for a column, the passage and page for a document ambiguity, the two conflicting passages with their dates for a contradiction, the page images and extracted text for a poor scan. The current inference is stored alongside so the user can see what happens if they skip.

**Scope**
- Evidence capture per trigger kind, stored with the question.
- The current inference stored as the prefill.
- Bounded evidence size so a question record stays small.

**Out of Scope**
- Rendering (M3-REVIEW-FE-073).

**Acceptance Criteria**
- **Acceptance Criteria:** Each raised question carries evidence appropriate to its kind and the current inference. A contradiction carries both passages and both dates. Evidence is bounded in size.
- **Edge Cases:** A column with thousands of distinct values — the top values plus a count of the remainder, not everything. A passage longer than the bound — truncated with a way to open the source. Evidence that cannot be captured — the question is still raised with a statement that no evidence is available, rather than being dropped.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/clarifications.md` §3 anatomy.
- **Validation Rules:** Evidence must be real data from the source, never a paraphrase.
- **Audit / Logging Requirements:** Evidence is part of the clarification record.
- **Analytics Events:** None.

**Real-World Example Scenarios**
- A question about a status code shows A, T and D with their counts, and the user answers in three seconds.

**Dependencies & Assumptions**
- **Dependencies:** M3-RAISE-BE-068.
- **API / Data Touchpoints:** `clarifications.evidence`.
- **Assumptions:** Column distributions become available in M4; the shape is built here so that work is only the query.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, add a document with a contradiction against an existing one. Open clarifications and read the question — both passages are shown with their dates, and the current inference is prefilled. Click through to one passage and confirm it is real.
- **Other scenarios:** Raise a poor-scan question and confirm the extracted text is shown.
- **Known gaps:** Column distributions are unavailable until M4.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** High
- **Labels / Component:** `phase:2`, backend
- **Granularity:** Four evidence kinds sharing one storage shape.

---

### M3-REVIEW-FE-072 — Clarifications screen as a single reviewable list

**Type:** Story

**Human review:** copy — this ticket renders wording a user reads, specified in `docs/ux/`. The runner stops and quotes it before the pull request is merged.

**User Story**
- **Actor:** someone opening the clarification queue for the first time.
- **User Need:** to see how much there is before starting.
- **Business Value:** a one-at-a-time flow hides the end, which is exactly what makes people abandon it; answering three of five is a good outcome the design should make easy.
- *As someone with limited patience, I want to see the whole list at once, so that I can decide to do it now and know when I am finished.*

**Context / Background**
**Detailed Description:** A single list, newest source first, grouped by source, with a count per group and a total at the top. Not a wizard, not a modal queue, not one at a time. Each item is answerable in place with no navigation and no confirmation step. The screen must feel finishable.

**Scope**
- Grouped list with counts and total.
- Entry from the left rail count badge and from a prompt after ingestion finishes.
- Answer in place with no navigation.

**Out of Scope**
- The item anatomy (M3-REVIEW-FE-073) and the actions (M3-REVIEW-FE-074).
- Inline clarification in a conversation (M3-INLINE-FE-085).

**Acceptance Criteria**
- **Acceptance Criteria:** Pending questions appear grouped by source with counts and a total. The badge in the rail shows the count and is not a modal, an alarm or a red dot implying something is broken. Items are answerable without leaving the list.
- **Edge Cases:** Questions arriving while the screen is open during ongoing ingestion — they appear without disrupting an in-progress answer. A very long list despite the cap, from many sources — grouping keeps it navigable. Nothing pending — the teaching empty state, not "no items".
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/clarifications.md` §2, §5 (none pending, pending, ingestion still running); `../states-and-edge-cases.md` §6.
- **Validation Rules:** The screen must never block startup, ingestion or asking.
- **Audit / Logging Requirements:** None for viewing.
- **Analytics Events:** Local counter of queue opens — nothing transmitted (C1).

**Real-World Example Scenarios**
- After an import the user sees a badge showing four, opens it, and finishes in ninety seconds.

**Dependencies & Assumptions**
- **Dependencies:** M3-RAISE-BE-069, M0-SHELL-FE-017.
- **API / Data Touchpoints:** `clarifications`.
- **Assumptions:** The badge alone is sufficient prompting; no modal and no repeated nagging.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, add a source that raises questions. Watch the badge appear in the left rail. Open the screen and see the questions grouped by source with counts and a total. Navigate away and back and confirm nothing was lost. Confirm no modal ever appeared and nothing blocked asking a question.
- **Other scenarios:** With nothing pending, open the screen and read the teaching empty state.
- **Known gaps:** Items are not yet answerable — that is the next two tickets.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** Critical
- **Labels / Component:** `phase:2`, frontend
- **Granularity:** One list and one badge.

---

### M3-REVIEW-FE-073 — One question's anatomy with its evidence

**Type:** Story

**Human review:** copy — this ticket renders wording a user reads, specified in `docs/ux/`. The runner stops and quotes it before the pull request is merged.

**User Story**
- **Actor:** someone reading a question about their own data.
- **User Need:** the subject, the question, the evidence and the current guess, all visible at once.
- **Business Value:** showing the evidence is what makes this answerable in five seconds instead of being an exam.
- *As someone being asked about a column, I want the values in front of me, so that the answer comes to me rather than being recalled.*

**Context / Background**
**Detailed Description:** Render each item per the specified anatomy: subject in mono naming the exact table and column or filename and page; the question in serif, one sentence, plain language; the evidence in mono — value distribution, row count, the passage; a free-text answer field prefilled with the inference; the current inference shown with the hollow inferred marker so the consequence of skipping is visible; and Skip carrying equal weight to Save.

**Scope**
- Item rendering per the anatomy, including type and colour roles from the design system.
- Discrete-option buttons where the choice is discrete, such as date formats or which of two documents is current.
- The inferred marker showing what happens on skip.

**Out of Scope**
- Save and skip behaviour (M3-REVIEW-FE-074).

**Acceptance Criteria**
- **Acceptance Criteria:** Each item shows subject, question, evidence, prefilled answer and the current inference with its marker. Discrete choices render as buttons rather than a text field. Skip is visually equal to Save.
- **Edge Cases:** No evidence available — the item says so rather than showing an empty block. A very long passage as evidence — truncated with a link to the source. A question with no inference — the field is empty and the marker is absent rather than showing a fake guess.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/clarifications.md` §3; `../ux/design-system.md` §2 and §3 for the inferred colour and the serif-versus-mono rule.
- **Validation Rules:** Evidence is displayed verbatim from the source.
- **Audit / Logging Requirements:** None for rendering.
- **Analytics Events:** None.

**Real-World Example Scenarios**
- A date-format question offers two buttons rather than asking the user to type a format string.

**Dependencies & Assumptions**
- **Dependencies:** M3-REVIEW-FE-072, M3-RAISE-BE-071.
- **API / Data Touchpoints:** `clarifications.evidence`, `options`.
- **Assumptions:** Discrete options are known at raise time for date formats and document identity.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, add a source raising both a free-text and a discrete question. Open clarifications and read both. Confirm the free-text one shows the value evidence and a prefilled guess in the inferred colour, and the discrete one shows buttons. Confirm Skip does not look like a lesser option.
- **Other scenarios:** Confirm a question with no evidence still renders sensibly.
- **Known gaps:** Nothing saves yet. The ranking reason is not shown.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** High
- **Labels / Component:** `phase:2`, frontend
- **Granularity:** One item template with two input kinds.

---

### M3-REVIEW-FE-074 — Save, skip, skip-all, undo, and the specific confirmation

**Type:** Story

**User Story**
- **Actor:** someone who has just answered a question.
- **User Need:** to see that answering did something.
- **Business Value:** the user must see that answering changed something, or they stop answering — and that is the entire feedback loop the feature depends on.
- *As someone who just told Askwell what a column means, I want to see what that changed, so that answering the next one feels worthwhile.*

**Context / Background**
**Detailed Description:** Saving writes the fact, marks affected material for re-processing, advances, and confirms specifically what changed — naming the tables or documents being re-read, not a generic toast. Skip keeps the inference as low confidence and does not raise it again for that source. Skip-all dismisses the group and is recorded, because dismissal is a tracked signal. Undo is available briefly after saving.

**Scope**
- Save, skip, skip-all-for-a-source and undo.
- The specific confirmation naming what is being re-processed.
- Advancement to the next item without navigation.

**Out of Scope**
- The re-processing itself (M3-APPLY-ING-080).
- Memory storage mechanics (M3-STORE-BE-076).

**Acceptance Criteria**
- **Acceptance Criteria:** Saving writes the fact and shows a confirmation naming what is being re-read. Skipping keeps the inference and does not re-raise. Skip-all dismisses the group and records the dismissal. Undo within the window reverses the save cleanly, including the re-processing trigger.
- **Edge Cases:** Undo after re-processing has already started — re-processing is reversed or re-run against the reverted fact, never left applying a fact that no longer exists. Saving an empty answer — treated as a skip, with that stated. Two saves in quick succession — both applied in order.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/clarifications.md` §4 and §5 (all answered, answered-re-processing); `../states-and-edge-cases.md` §6 clarification answered.
- **Validation Rules:** The confirmation must name the affected material specifically.
- **Audit / Logging Requirements:** Every answer, skip and dismissal is a decisions record, written in the same transaction as the memory fact.
- **Analytics Events:** Local counters of answered, skipped and dismissed — nothing transmitted (C1).

**Real-World Example Scenarios**
- "Saved. Re-reading 3 tables that use this column." — and the user answers the next four because the first one visibly did something.

**Dependencies & Assumptions**
- **Dependencies:** M3-REVIEW-FE-073, M3-STORE-BE-076, M3-STORE-OBS-077.
- **API / Data Touchpoints:** `clarifications.answer`, `status`; `memory`; `audit_decisions`.
- **Assumptions:** The affected-material count is computable quickly enough to appear in the confirmation immediately.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, add a source that raises questions. Open clarifications, answer the first, and read the confirmation naming what is being re-read. Watch the item advance. Skip the second and confirm it disappears without complaint. Use skip-all on a group and confirm it clears. Answer another and press undo within the window — confirm the fact is gone from memory.
- **Other scenarios:** Answer all questions and read the completion state naming what improved.
- **Known gaps:** Re-processing may be a no-op until M3-APPLY-ING-080 lands; the confirmation still names what would be re-read and says so.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** Critical
- **Labels / Component:** `phase:2`, frontend
- **Granularity:** Four actions and one confirmation.

---

### M3-REVIEW-FE-075 — Clarification screen states: none pending, capped, re-processing

**Type:** Story

**Human review:** copy — this ticket renders wording a user reads, specified in `docs/ux/`. The runner stops and quotes it before the pull request is merged.

**User Story**
- **Actor:** someone who has never met the clarification feature.
- **User Need:** the empty state to teach what it is for.
- **Business Value:** an empty state saying "no items" wastes the one moment the feature could explain itself.
- *As someone who opened this screen out of curiosity, I want it to tell me what it does, so that I recognise it when it fires.*

**Context / Background**
**Detailed Description:** Build the remaining states: none pending, which teaches the feature; ingestion still running, where questions appear as they are raised and the source is already queryable; all answered, with a brief completion naming what improved; answered and re-processing, with per-item progress while the source stays queryable; and capped, which is honest about what was not asked and routes to memory.

**Scope**
- All five states with their copy.
- Per-item re-processing progress.
- The capped state's route to the memory screen.

**Out of Scope**
- The inline-in-conversation state (M3-INLINE-FE-085).

**Acceptance Criteria**
- **Acceptance Criteria:** With nothing pending, the screen teaches the feature rather than reporting emptiness. During ingestion, questions appear as raised. After answering everything, a completion state names what improved and then returns to the empty state. The capped state states how many were inferred and links to memory.
- **Edge Cases:** Re-processing that fails — surfaced with the reason and a retry rather than a stuck progress indicator. All questions skipped rather than answered — the completion state says so honestly rather than congratulating. Ingestion raising a question after the user reached the completion state — it appears without a jarring reset.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/clarifications.md` §5 in full.
- **Validation Rules:** The screen never blocks and never nags.
- **Audit / Logging Requirements:** None beyond the actions.
- **Analytics Events:** Local counters only — nothing transmitted (C1).

**Real-World Example Scenarios**
- A user finishes a queue and reads "5 answered. 2 tables and 14 documents re-read", which is what makes them answer the next batch.

**Dependencies & Assumptions**
- **Dependencies:** M3-REVIEW-FE-074, M3-APPLY-ING-080.
- **API / Data Touchpoints:** `clarifications.status`; re-processing job state.
- **Assumptions:** Per-item re-processing progress is available from the job system.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** On a fresh install with nothing added, open clarifications and read the teaching empty state. Add a source with many candidates and watch questions appear while indexing runs. Confirm the capped statement appears and follow its link to memory. Answer everything and read the completion state.
- **Other scenarios:** Force a re-processing failure and confirm it is visible with a retry.
- **Known gaps:** Ranking reasons are not shown.

**Effort & Granularity Check**
- **Estimate:** 2–3 hours · **Priority:** High
- **Labels / Component:** `phase:2`, frontend
- **Granularity:** Five states.

---

### M3-STORE-BE-076 — Memory and schema notes with origin, confidence and supersession

**Type:** Story

**User Story**
- **Actor:** someone who told Askwell something and then changed their mind.
- **User Need:** corrections that supersede rather than overwrite, with the old value still visible.
- **Business Value:** memory is inspectable, reversible and portable precisely because it is a list of facts rather than anything trained.
- *As someone whose understanding of my own data evolves, I want corrections to supersede rather than erase, so that I can see how a belief changed.*

**Context / Background**
**Detailed Description:** Two stores with different shapes: schema notes attached to a source, table and column, and general memory not tied to a schema object. Both carry origin, confidence, supersession and creation time. User-supplied always outranks inferred and is never silently overwritten. Correction supersedes; it never updates in place. Memory does not expire and superseding is manual.

**Scope**
- Writing and superseding for both stores.
- Origin, confidence and creation-time semantics.
- Retrieval-time precedence: user over inferred, later over earlier.
- Schema notes removed with their source; general memory surviving.

**Out of Scope**
- The memory screen (M3-MEM-FE-083).
- Import and export across machines — not v1.

**Acceptance Criteria**
- **Acceptance Criteria:** Answering a clarification writes a fact with origin clarification and full confidence. Correcting supersedes and the old value remains readable in history. An inference never overwrites a user-supplied fact. Deleting a source removes its schema notes and leaves general memory.
- **Edge Cases:** Two contradicting user answers — the later supersedes and both remain visible. A fact superseded twice — the chain resolves to the newest. A fact whose source no longer exists — general memory survives and says it came from a deleted source. An inference arriving for a subject that already has a user fact — discarded rather than stored as a competing low-confidence entry.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/memory.md` §5 states; `../states-and-edge-cases.md` §6 memory fact superseded.
- **Validation Rules:** Never overwrite in place; supersession only. Automatic expiry is forbidden.
- **Audit / Logging Requirements:** Every write, supersession and deletion is a decisions record.
- **Analytics Events:** Local counter of facts held — nothing transmitted (C1).

**Real-World Example Scenarios**
- A user corrects a status code meaning six weeks later, and the memory screen shows the old value struck through in history.

**Dependencies & Assumptions**
- **Dependencies:** M0-DATA-DB-013, M3-RAISE-BE-068.
- **API / Data Touchpoints:** `memory`, `schema_notes`.
- **Assumptions:** The storage shape should not make cross-machine export hard later, even though export is not v1.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, answer a clarification, and confirm the fact appears in memory as user-supplied. Correct it and confirm the new value applies while the old one is visible in history. Delete the source it came from and confirm a general fact survives, labelled as learned from a deleted source, while a structural note goes.
- **Other scenarios:** Force an inference for a subject with a user fact and confirm it is discarded.
- **Known gaps:** No screen yet. No export.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** Critical
- **Labels / Component:** `phase:2`, backend, database
- **Granularity:** Two stores sharing one supersession rule.

---

### M3-STORE-OBS-077 — Clarification answers written as decisions records in one transaction

**Type:** Task

**User Story**
- **Actor:** someone who wants to know how Askwell came to believe something.
- **User Need:** the history of how memory reached its current state.
- **Business Value:** the decisions store deliberately overlaps memory — a clarification answer is both a memory fact and an audit record, and they are the same event.
- *As someone auditing my own tool, I want the history of every belief, so that I can see when and why it changed.*

**Context / Background**
**Detailed Description:** A clarification answer, a correction, a deletion of a fact and a threshold change are all decisions records. Each is written in the same transaction as the memory change so the two can never diverge. The decisions store is never pruned, at any budget, because it is kilobytes and it is the product.

**Scope**
- Transactional write of memory change plus decisions record.
- Record shapes for answer, correction, deletion, skip and dismissal.
- Verification that the chain covers memory history.

**Out of Scope**
- Export (M7).

**Acceptance Criteria**
- **Acceptance Criteria:** Every memory change has a corresponding decisions record written in the same transaction. An induced audit failure prevents the memory change. The chain verifies after a series of memory operations. **C6 is preserved: append-only by grant, chained, and never called immutable.**
- **Edge Cases:** Undo of a save — recorded as its own decision, not by removing the original record. A batch of skips — one record each, so the dismissal signal is countable. A correction made from inside an answer — the same record shape as one made on the memory screen.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** None directly; surfaced by history in `../ux/memory.md` §4.
- **Validation Rules:** No memory write may occur without its decisions record.
- **Audit / Logging Requirements:** This ticket is the audit requirement.
- **Analytics Events:** None.

**Real-World Example Scenarios**
- The memory screen's history view is built directly from these records rather than from a parallel structure that could drift.

**Dependencies & Assumptions**
- **Dependencies:** M3-STORE-BE-076, M0-DATA-OBS-015.
- **API / Data Touchpoints:** `audit_decisions`, `memory`, `schema_notes`.
- **Assumptions:** The decisions store stays in the kilobytes, which is what makes fail-closed practical.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, answer three clarifications and correct one. Run log verification and confirm an intact chain covering four decisions. Make the decisions table unwritable and try to answer another — the answer fails with a stated reason and no fact is written.
- **Other scenarios:** Confirm undo produces its own record rather than deleting one.
- **Known gaps:** No history screen until M3-MEM-FE-084. No export until M7.

**Effort & Granularity Check**
- **Estimate:** 2–3 hours · **Priority:** Critical
- **Labels / Component:** `phase:2`, observability, `constraint:audit`
- **Granularity:** One transactional rule and five record shapes.

---

### M3-APPLY-RET-078 — Retrieve memory and schema notes alongside document chunks

**Type:** Story

**User Story**
- **Actor:** someone who explained an abbreviation last month.
- **User Need:** that explanation applied to today's question without being asked again.
- **Business Value:** compounding value is the whole claim; this is the ticket where it starts compounding.
- *As someone who taught Askwell my vocabulary, I want it used in every later answer, so that the product gets better on the same files.*

**Context / Background**
**Detailed Description:** At answer time, relevant memory and schema notes are retrieved alongside document chunks. All three go into the prompt, clearly separated and clearly labelled as to origin, with confidence carried through so a user fact and a guess are distinguishable to the model. Memory does not bypass grounding.

**Scope**
- Memory and schema-note retrieval by relevance to the question.
- Prompt assembly with the three kinds separated and labelled, retaining the data-not-instruction boundary.
- Confidence surviving into the prompt.

**Out of Scope**
- Citation of facts (M3-APPLY-BE-079).
- Schema retrieval for SQL generation (M4).

**Acceptance Criteria**
- **Acceptance Criteria:** A question whose terms match a stored fact retrieves it, and the answer reflects it. The prompt separates and labels documents, memory and schema notes. Inferred facts are marked as such to the model. **C7 is preserved — memory is data in the prompt like any other retrieved content, and the standing statement is unchanged.**
- **Edge Cases:** A stored fact contradicting a retrieved document — presented as a conflict rather than silently preferring memory. A large memory store — retrieval is bounded, not everything injected. No relevant memory — the prompt says so rather than including an empty labelled block that reads as a fact.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/ask.md` §3 memory facts used.
- **Validation Rules:** Memory never licenses inventing content; abstention is unaffected by the presence of a fact.
- **Audit / Logging Requirements:** Facts retrieved for a turn are recorded on the interaction.
- **Analytics Events:** Local counter only — nothing transmitted (C1).

**Real-World Example Scenarios**
- After the user explains an abbreviation, a question using it returns the right passages instead of nothing.

**Dependencies & Assumptions**
- **Dependencies:** M3-STORE-BE-076, M1-ASK-RET-036.
- **API / Data Touchpoints:** `memory`, `schema_notes`, prompts.
- **Assumptions:** Facts are embedded on write so they can be retrieved by relevance.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, ask a question using an abbreviation Askwell does not know and note the poor answer or abstention. Answer the clarification explaining it. Ask the same question again and observe a materially better answer. This before-and-after is the whole point and must be visible without inspecting anything internal.
- **Other scenarios:** Store a fact contradicting a document and confirm a conflict rather than silent preference.
- **Known gaps:** Facts are not yet cited as sources — that is the next ticket. No schema-driven SQL until M4.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** Critical
- **Labels / Component:** `phase:2`, retrieval, `constraint:grounding`
- **Granularity:** One retrieval addition and one prompt change.

---

### M3-APPLY-BE-079 — Cite memory facts and record fact usage

**Type:** Story

**User Story**
- **Actor:** someone reading an answer shaped by something they said in March.
- **User Need:** to see which belief shaped the answer.
- **Business Value:** the constraint that every claim carries a citation applies to memory exactly as it applies to documents, and the usage count is what makes a wrong belief noticeable.
- *As someone whose answers depend on facts I supplied, I want to see which fact was used, so that I can correct it when it is wrong.*

**Context / Background**
**Detailed Description:** A claim resting on a memory fact cites it as such — attributing it to what the user said and when — the same way a document claim cites its page. Each use is recorded in the fact usage table, which feeds the "used in N answers" count that makes the memory screen worth opening.

**Scope**
- Fact citation in composition with attribution and date.
- Fact usage rows per message and fact.
- The uncited-claim check extended to accept fact-backed claims.

**Out of Scope**
- The chip interaction (M3-CORRECT-FE-081).
- The memory screen count rendering (M3-MEM-FE-083).

**Acceptance Criteria**
- **Acceptance Criteria:** An answer using a memory fact attributes it to the user and the date it was supplied. A fact usage row is written per fact per message. The uncited-claim check counts a fact-backed claim as cited. **C4 is preserved for memory-derived claims, not only document-derived ones.**
- **Edge Cases:** A fact used to interpret a document rather than to assert anything — recorded as used, but the claim still cites the document, because memory explaining what a term means does not license inventing what is in the document. A fact that was superseded between retrieval and composition — the version used is the one recorded. A deleted fact — old usage rows survive so history is not rewritten.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/ask.md` §3 and §4 memory chips.
- **Validation Rules:** A claim asserting content must cite a document; a claim resting on a definition cites the fact.
- **Audit / Logging Requirements:** Fact usage is durable and does not rotate with traces.
- **Analytics Events:** Local counter only — nothing transmitted (C1).

**Real-World Example Scenarios**
- An answer notes it used the user's definition of a status code, dated to when they gave it.

**Dependencies & Assumptions**
- **Dependencies:** M3-APPLY-RET-078, M1-CITE-BE-042.
- **API / Data Touchpoints:** `fact_usage`, `citations`.
- **Assumptions:** Distinguishing an interpreting fact from an asserting fact is prompt-driven and is measured by the memory eval subset.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, answer a clarification, then ask a question that depends on it. Confirm the answer names the fact and when it was supplied. Ask two more such questions, then open memory (once it exists) and confirm the count says three.
- **Other scenarios:** Run the uncited-claim check over these answers and confirm they pass.
- **Known gaps:** Chips are not interactive yet. The memory screen does not exist yet.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** Critical
- **Labels / Component:** `phase:2`, backend, `constraint:grounding`
- **Granularity:** One citation kind and one usage record.

---

### M3-APPLY-ING-080 — Re-process what depends on an answered clarification

**Type:** Story

**User Story**
- **Actor:** someone who has just explained what a term means.
- **User Need:** the material that depends on it re-read, so the next answer is actually better.
- **Business Value:** answering that changes nothing is answering that stops happening.
- *As someone who answered a question, I want the affected material re-read, so that the improvement is real rather than promised.*

**Context / Background**
**Detailed Description:** Answering a clarification queues re-processing of what depends on it: re-embedding affected chunks, updating schema notes, and re-resolving a contradiction. The source stays queryable throughout. Progress is per item and failures are visible with a retry.

**Scope**
- Dependency resolution: which chunks, notes and conflicts depend on a given fact.
- Re-processing jobs with per-item progress.
- The source remaining queryable during re-processing.

**Out of Scope**
- Full re-index of a source, which is a separate library action.

**Acceptance Criteria**
- **Acceptance Criteria:** Answering a clarification queues re-processing that names the affected material. The source answers questions throughout. When re-processing completes, a question that previously depended on the ambiguity returns a better answer. Failures are visible with a retry.
- **Edge Cases:** An answer affecting thousands of chunks — batched, with progress, and the machine stays usable. Two answers affecting overlapping material — de-duplicated rather than re-processed twice. Undo during re-processing — the work is reverted or re-run against the reverted fact.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/clarifications.md` §5 answered-re-processing; `../ux/memory.md` §5 edited-re-processing.
- **Validation Rules:** The source is never taken out of service for re-processing.
- **Audit / Logging Requirements:** Re-processing runs are logged; the triggering answer is already a decisions record.
- **Analytics Events:** Local counter only — nothing transmitted (C1).

**Real-World Example Scenarios**
- The user resolves a contradiction between two policies and the next question about it answers from the current one, saying so.

**Dependencies & Assumptions**
- **Dependencies:** M3-STORE-BE-076, M1-INDEX-ING-032.
- **API / Data Touchpoints:** Queue; `chunks`; `schema_notes`.
- **Assumptions:** Dependency resolution is approximate and errs toward re-processing more rather than less.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, add two contradicting documents, ask about the disputed value and observe the conflict. Answer the clarification naming which is current. Watch the re-processing progress and confirm you can still ask questions during it. When it finishes, ask again and observe a single answer from the current source with the reasoning visible.
- **Other scenarios:** Answer a fact affecting many chunks and confirm the machine remains usable.
- **Known gaps:** Dependency resolution may re-process more than strictly necessary.

**Effort & Granularity Check**
- **Estimate:** 4–6 hours · **Priority:** Critical
- **Labels / Component:** `phase:2`, ingestion, backend
- **Granularity:** Dependency resolution plus jobs plus progress. Upper bound.

---

### M3-CORRECT-FE-081 — Memory chips in an answer, with correct and delete

**Type:** Story

**User Story**
- **Actor:** someone who has just noticed Askwell believes something wrong.
- **User Need:** to fix it right there.
- **Business Value:** the moment a user notices Askwell is wrong is the only moment they will reliably fix it, and it is here. Making them navigate elsewhere means it never gets fixed and the wrong fact poisons every later answer.
- *As someone reading an answer built on a wrong assumption, I want to correct it without leaving the answer, so that it actually gets corrected.*

**Context / Background**
**Detailed Description:** When an answer used a memory fact it appears as a chip. Clicking it opens a popover showing the fact, its origin and date, with Correct and Delete. Correct edits in place; saving supersedes the fact and re-processes what depends on it. This is the highest-value interaction in the product and must not be moved to a settings screen.

**Scope**
- Chip rendering for facts used in an answer.
- Popover with the fact, origin, date, Correct and Delete.
- Inline edit and save, wired to supersession and re-processing.

**Out of Scope**
- The memory screen (M3-MEM-FE-083).
- Adding a new fact from here.

**Acceptance Criteria**
- **Acceptance Criteria:** Every fact used in an answer appears as a chip. Clicking shows the fact, its origin and date. Correcting supersedes and triggers re-processing, with the confirmation naming what is being re-read. Deleting stops the fact applying immediately.
- **Edge Cases:** A fact used in several answers — correcting from any one of them affects all future answers, and the popover says how many answers used it. A fact already superseded since the answer was written — the popover shows the current version and notes the answer used an earlier one. A chip for a schema note rather than a general fact — same interaction, different subject rendering.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/ask.md` §4 correction from inside the answer.
- **Validation Rules:** Correction supersedes; it never overwrites.
- **Audit / Logging Requirements:** Correction and deletion are decisions records.
- **Analytics Events:** Local counter of corrections from answers — nothing transmitted (C1).

**Real-World Example Scenarios**
- A user sees a chip stating a wrong meaning for a code, clicks it, fixes it in one edit, and the next answer is right.

**Dependencies & Assumptions**
- **Dependencies:** M3-APPLY-BE-079, M3-STORE-BE-076, M3-APPLY-ING-080.
- **API / Data Touchpoints:** `fact_usage`, `memory`, `schema_notes`.
- **Assumptions:** The popover fits the conversation column without displacing the provenance margin.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, answer a clarification with a deliberately wrong meaning. Ask a question that uses it and observe the chip. Click it, read the fact and its origin, choose Correct, fix it, and save. Read the confirmation naming what is being re-read. Ask the question again and confirm the answer changed.
- **Other scenarios:** Delete a fact from a chip and confirm the next answer no longer uses it.
- **Known gaps:** No history view from the popover; that is on the memory screen.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** Critical
- **Labels / Component:** `phase:2`, frontend
- **Granularity:** One chip, one popover, two actions.

---

### M3-CORRECT-BE-082 — Correction path: supersede, re-process, record

**Type:** Task

**User Story**
- **Actor:** someone correcting a belief from anywhere in the product.
- **User Need:** one consistent behaviour regardless of where the correction started.
- **Business Value:** two correction paths that behave differently is how a fact ends up half-corrected.
- *As someone correcting Askwell, I want the same thing to happen whether I do it from an answer or the memory screen, so that I can trust either.*

**Context / Background**
**Detailed Description:** One backend path handles correction wherever it originates: supersede the prior fact, record a decisions entry with origin correction, queue re-processing of dependents, and return what is being re-processed so the caller can confirm specifically. Deletion follows the same shape, minus the new fact.

**Scope**
- A single correction path used by both the chip and the memory screen.
- Deletion path sharing the same dependency handling.
- The affected-material summary returned to the caller.

**Out of Scope**
- The interfaces themselves.

**Acceptance Criteria**
- **Acceptance Criteria:** Correcting from a chip and from the memory screen produce identical results. Both supersede rather than overwrite. Both queue re-processing and return the affected-material summary. Both write decisions records.
- **Edge Cases:** Correcting a fact that has already been deleted — refused with a clear reason. Correcting to the same value — no supersession and no re-processing, and the interface says nothing changed. Correcting during re-processing of a previous correction — serialised, not interleaved.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** Both callers' confirmation copy.
- **Validation Rules:** Supersession only; never update in place.
- **Audit / Logging Requirements:** Every correction and deletion is a decisions record.
- **Analytics Events:** Local counter only — nothing transmitted (C1).

**Real-World Example Scenarios**
- A user corrects the same fact twice from different screens and the history shows a clean chain of three values.

**Dependencies & Assumptions**
- **Dependencies:** M3-STORE-BE-076, M3-APPLY-ING-080.
- **API / Data Touchpoints:** `memory`, `schema_notes`, `audit_decisions`.
- **Assumptions:** One path is genuinely sufficient for both callers.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, correct a fact from an answer chip. Then correct the same fact again from the memory screen. Open its history and confirm three values in order with dates. Confirm re-processing ran both times.
- **Other scenarios:** Correct to an identical value and confirm nothing is queued.
- **Known gaps:** No bulk correction.

**Effort & Granularity Check**
- **Estimate:** 2–3 hours · **Priority:** High
- **Labels / Component:** `phase:2`, backend
- **Granularity:** One shared path.

---

### M3-MEM-FE-083 — Memory screen: the list, confidence markers and the usage count

**Type:** Story

**Human review:** copy — this ticket renders wording a user reads, specified in `docs/ux/`. The runner stops and quotes it before the pull request is merged.

**User Story**
- **Actor:** someone whose answers have started feeling subtly wrong.
- **User Need:** to read everything Askwell believes about their material.
- **Business Value:** a memory the user cannot inspect is a system that gets mysteriously worse and cannot be debugged.
- *As someone debugging my own tool, I want to read every belief it holds, so that I can find the wrong one.*

**Context / Background**
**Detailed Description:** One list grouped by subject, with structural and general facts visually distinct but together. Every row carries the confidence marker — filled for user-supplied, hollow for inferred — and the usage count. The default sort puts inferred facts first, because those are the ones worth reviewing and sorting alphabetically would bury exactly what the screen exists to surface.

**Scope**
- The list with grouping, both fact kinds, confidence markers and source attribution.
- The usage count per fact.
- Default sort placing inferred first.
- The empty state and the states for facts from deleted sources, conflicting facts and unused facts.

**Out of Scope**
- Interactions (M3-MEM-FE-084).
- Bulk confirm, which is an open question.

**Acceptance Criteria**
- **Acceptance Criteria:** Every stored fact appears with its origin marker, source and usage count. Inferred facts sort first by default. A fact from a deleted source says so. The empty state teaches what memory is and names the clarification queue as the way to start.
- **Edge Cases:** Hundreds of facts — the list stays navigable with grouping and filtering. A fact used zero times — shown, never auto-deleted, because it may be waiting for the right question. Conflicting facts — the later one shown with the earlier struck through in history rather than discarded.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/memory.md` §2, §3, §5; `../ux/design-system.md` §2 for the confidence colours.
- **Validation Rules:** Never auto-delete. Never hide inferences.
- **Audit / Logging Requirements:** None for viewing.
- **Analytics Events:** Local counter only — nothing transmitted (C1).

**Real-World Example Scenarios**
- A user sees a guessed fact used in forty answers and realises it has been corrupting results for weeks.

**Dependencies & Assumptions**
- **Dependencies:** M3-APPLY-BE-079, M3-STORE-BE-076.
- **API / Data Touchpoints:** `memory`, `schema_notes`, `fact_usage`.
- **Assumptions:** The usage count is a live join rather than a denormalised counter, so it survives deletions and answers the which-answers question.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** On a fresh install, open memory and read the teaching empty state. Add a source, answer one clarification and let others be inferred. Return to memory: confirm the inferred facts sort first with the hollow marker, the answered one carries the filled marker, and each shows a usage count. Ask a question that uses one and confirm its count increases.
- **Other scenarios:** Delete a source and confirm structural facts go while general ones remain, labelled.
- **Known gaps:** No editing yet. No bulk confirm.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** High
- **Labels / Component:** `phase:2`, frontend
- **Granularity:** One list with four states.

---

### M3-MEM-FE-084 — Memory interactions: edit, confirm, delete, history, filter, manual add

**Type:** Story

**User Story**
- **Actor:** someone who wants to tell Askwell their vocabulary before being asked.
- **User Need:** to add, promote, edit and remove facts directly.
- **Business Value:** a user who has learned what memory does will want to front-load their own vocabulary, and refusing that would be perverse.
- *As someone who knows my own jargon, I want to tell Askwell up front, so that the first import is already better.*

**Context / Background**
**Detailed Description:** Edit in place, superseding on save. Confirm promotes an inferred fact to user-supplied in one click without re-processing, because the content did not change. Delete stops the fact applying immediately and is recorded. History shows every prior value with dates. Filters cover inferred-only, by source, and unused. Manual entry adds a fact directly.

**Scope**
- Edit, confirm, delete, history, three filters, manual add.
- Confirmation copy for delete-all-memory, with the count and that it cannot be undone.

**Out of Scope**
- Bulk confirm of a run of inferences — open, and it risks rubber-stamping.
- Export and import across machines — not v1.

**Acceptance Criteria**
- **Acceptance Criteria:** Editing supersedes and re-processes. Confirm promotes without re-processing. Delete stops the fact applying immediately. History shows prior values with dates. Each filter narrows correctly. Manual entry creates a user-supplied fact that applies to the next question.
- **Edge Cases:** Confirming a fact then editing it — two records, correct order. Deleting a fact used in past answers — those answers keep their fact usage rows so history is not rewritten. Manual entry duplicating an existing subject — offered as a correction rather than creating a competing fact.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/memory.md` §4 and §6 — never auto-delete, never hide inferences, never present memory as training.
- **Validation Rules:** Deleting all memory requires a confirmation naming the count.
- **Audit / Logging Requirements:** Every action is a decisions record.
- **Analytics Events:** Local counters only — nothing transmitted (C1).

**Real-World Example Scenarios**
- Before importing a database, the user manually adds five vocabulary facts and the import raises two questions instead of five.

**Dependencies & Assumptions**
- **Dependencies:** M3-MEM-FE-083, M3-CORRECT-BE-082.
- **API / Data Touchpoints:** `memory`, `schema_notes`, `audit_decisions`.
- **Assumptions:** Manual entry uses the same fact shape as a clarification answer, differing only in origin.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, open memory and manually add a fact defining a term. Ask a question using that term and confirm the answer reflects it and shows the chip. Return to memory, confirm the usage count is one, edit the fact, and confirm the history shows both values. Confirm an inferred fact with one click and watch its marker change without a re-processing message. Delete a fact and confirm the next answer no longer uses it. Filter to inferred-only and confirm the list narrows.
- **Other scenarios:** Use delete-all-memory and read the confirmation naming the count.
- **Known gaps:** No bulk confirm. No export or import.

**Effort & Granularity Check**
- **Estimate:** 4–6 hours · **Priority:** High
- **Labels / Component:** `phase:2`, frontend
- **Granularity:** Six interactions on one list. Upper bound.

---

### M3-INLINE-FE-085 — Inline clarification when a question blocks an answer

**Type:** Story

**User Story**
- **Actor:** someone whose question depends on an unresolved contradiction.
- **User Need:** to be asked here, now, in the conversation.
- **Business Value:** this is the one moment where the question is obviously relevant and the user is already engaged; bouncing them to another screen mid-question is the wrong trade.
- *As someone asking about a value two of my documents disagree on, I want to be asked which is current right here, so that I get my answer in one interaction.*

**Context / Background**
**Detailed Description:** When an answer depends on an unresolved ambiguity, the clarification is rendered inline in the conversation rather than in the queue. Answering it writes the fact, re-processes, and completes the answer. This is the only place a clarification interrupts, and the user is never bounced to the clarifications screen mid-question.

**Scope**
- Inline clarification rendering in the conversation with its evidence.
- Answer-in-place completing the pending answer.
- Skip continuing with the inference and saying so in the answer.

**Out of Scope**
- The queue screen (M3-REVIEW-FE-072).

**Acceptance Criteria**
- **Acceptance Criteria:** A blocking ambiguity renders the question inline with its evidence. Answering writes the fact and the answer completes using it. Skipping continues with the inference and the answer says which assumption it used. The user is never navigated away.
- **Edge Cases:** Two blocking ambiguities in one turn — asked together rather than in sequence, or the second is deferred to the queue and the answer says so. The user navigates away without answering — the question moves to the queue rather than being lost. The same ambiguity blocking a later turn — asked once, then applied.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/ask.md` §5 inline clarification; `../ux/clarifications.md` §5 blocking-an-answer — never bounce the user mid-question.
- **Validation Rules:** Only a genuinely blocking ambiguity may interrupt.
- **Audit / Logging Requirements:** The answer is a decisions record like any other clarification answer.
- **Analytics Events:** Local counter of inline clarifications — nothing transmitted (C1).

**Real-World Example Scenarios**
- A user asks about a notice period, is asked inline which policy is current, answers, and the answer completes with the right figure — all in one exchange.

**Dependencies & Assumptions**
- **Dependencies:** M3-REVIEW-FE-074, M2-PARTIAL-BE-059, M3-APPLY-ING-080.
- **API / Data Touchpoints:** `clarifications`, `memory`, the streaming answer.
- **Assumptions:** Blocking can be determined before composition rather than discovered mid-answer.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, add two documents that disagree on a value. Ask about it. Observe the question appearing inline in the conversation with both passages as evidence, and confirm you were not navigated anywhere. Answer it and watch the answer complete using your choice. Ask a related question and confirm you are not asked again.
- **Other scenarios:** Skip the inline question and confirm the answer states the assumption it used.
- **Known gaps:** Multiple simultaneous blocking ambiguities may defer the second to the queue.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** High
- **Labels / Component:** `phase:2`, frontend, backend
- **Granularity:** One inline state and one completion path.

---

### M3-EVAL-TEST-086 — Memory application eval subset

**Type:** Task

**User Story**
- **Actor:** the maintainer who has just built the differentiator.
- **User Need:** proof that a stored fact actually changes a later answer and that a superseded fact stops applying.
- **Business Value:** without this category the differentiator has no test at all.
- *As someone who has just built the feature the product is sold on, I want it measured, so that a later change cannot silently break it.*

**Context / Background**
**Detailed Description:** Fifteen tasks with a 0.85 bar, verifying that a stored fact changes a later answer, that a superseded fact stops applying, that memory is cited when used, and that memory does not license inventing content. Runs three times with worst-case reported.

**Scope**
- Fifteen tasks covering application, supersession, citation of facts and the no-invention boundary.
- Fixture facts and questions.
- Integration into the gate.

**Out of Scope**
- Schema-note-driven SQL accuracy, which belongs to the text-to-SQL category in M4.

**Acceptance Criteria**
- **Acceptance Criteria:** The subset reports against the 0.85 bar with worst-case beside mean. Removing memory retrieval makes it fail. A task where memory is present but the document does not support a claim must still abstain — memory must not license invention.
- **Edge Cases:** A fact that should be superseded but is not applied correctly — scored as a failure distinct from a general application failure, so the cause is legible. A task where the correct behaviour is to ignore an irrelevant fact.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** None.
- **Validation Rules:** Do not weaken these tasks to make a change pass.
- **Audit / Logging Requirements:** Results recorded with model and prompt version.
- **Analytics Events:** None.

**Real-World Example Scenarios**
- A retrieval change quietly stops injecting memory; the subset drops from 0.9 to 0.2 and the change is rejected.

**Dependencies & Assumptions**
- **Dependencies:** M3-APPLY-BE-079, M2-EVAL-TEST-063.
- **API / Data Touchpoints:** The answer path; `memory`.
- **Assumptions:** Fixture facts can be seeded through the normal clarification path so the test exercises the real route.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, index the fixture corpus, seed the fixture facts by answering clarifications, then run the memory subset. Read the score and the failures. Delete all memory and run again — the score should collapse, which proves the subset measures what it claims to.
- **Other scenarios:** Supersede a fixture fact and confirm the supersession tasks now pass and the original-value tasks now fail.
- **Known gaps:** Fifteen tasks is a small sample. English only.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** Critical
- **Labels / Component:** `phase:2`, test, `eval`
- **Granularity:** Fifteen tasks in an existing harness.
