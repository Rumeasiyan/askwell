# M2 — It says when it doesn't know

**Goal:** Abstention, partial answers, conflicting sources, deletion, and the failure states — plus the eval harness that keeps them honest.

**Phase:** 1 (`../build-plan.md`) · **Depends on:** M1 · **Tickets:** 15 · **Estimated:** 42–58 hours

**Exit condition:** A question the corpus does not cover produces an explicit, visually distinct "I don't know" naming what was searched and what would need adding; a half-covered question answers the grounded part and names the gap; a deleted document's old citations resolve to a deletion date rather than breaking; and the abstention eval subset scores at or above 0.90 with worst-of-three reported.

> **Why this is a milestone rather than part of the chat work.** Abstention and the failure states are normally folded into "the chat feature" and quietly dropped when time runs short. They are the product's central claim (C5) and they get their own demonstrable end.

## Included epics

| Epic | Code | Covers |
| ---- | ---- | ------ |
| Abstention | `ABSTAIN` | Threshold, composition, rendering, recording |
| Partial and conflicting answers | `PARTIAL` | Grounded-part answers, conflict presentation |
| Failure states | `FAIL` | Degrading to search when the assistant is unavailable |
| Deletion | `DELETE` | Tombstones, confirmation copy, deleted citations |
| Evaluation | `EVAL` | Harness, suites, pass bars, the gate |

---

### M2-ABSTAIN-RET-053 — Retrieval threshold and the abstention decision

**Type:** Story

**User Story**
- **Actor:** someone asking about something their files do not contain.
- **User Need:** the system to decide honestly that it has nothing, rather than answering from a weak match.
- **Business Value:** one confident fabrication about their own contract and the product is uninstalled.
- *As someone whose corpus has gaps I do not know about, I want Askwell to recognise when nothing matched well enough, so that a weak match does not become a confident answer.*

**Context / Background**
**Detailed Description:** Apply a threshold to reranked scores. When nothing clears it, the turn abstains and never proceeds to composition from documents. The threshold in force is stored with the turn rather than recomputed later, because recomputing gives a different number after any model or threshold change and makes the explanation wrong exactly when someone is investigating an old answer.

**Scope**
- Configurable threshold applied to reranked scores, with a default recorded as a decision.
- The abstention branch, taken before composition.
- Storage of the threshold in force and every candidate score, including the near-miss.

**Out of Scope**
- The abstention copy (M2-ABSTAIN-BE-054) and rendering (M2-ABSTAIN-FE-055).
- Threshold adjustment from a trace (M5).

**Acceptance Criteria**
- **Acceptance Criteria:** A question with no candidate above threshold abstains rather than answering. A question with a clear match answers. The threshold and all candidate scores are stored on the turn. **C5 is preserved because the abstention branch precedes composition; there is no path from a below-threshold retrieval to a document-grounded answer.**
- **Edge Cases:** Empty corpus — abstains, and the copy differs from "nothing matched" because there is nothing to match against. All candidates just below the threshold — abstains, and the near-miss is stored so the trace can explain it. One candidate barely above — answers, with the score visible. A source scoped question where the source exists but is still indexing — says so rather than abstaining generically.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/ask.md` §6; `../states-and-edge-cases.md` §2 abstention.
- **Validation Rules:** The threshold is never lowered automatically, for any reason.
- **Audit / Logging Requirements:** Abstentions are recorded in the interaction log (`../audit-log.md` §7).
- **Analytics Events:** Local abstention counter only — nothing transmitted (C1).

**Real-World Example Scenarios**
- A user asks about a policy they never added; the closest material scores 0.61 against a 0.65 threshold and Askwell abstains, with the near-miss preserved.

**Dependencies & Assumptions**
- **Dependencies:** M1-ASK-RET-036.
- **API / Data Touchpoints:** `messages.trace` threshold and hits.
- **Assumptions:** The default threshold is tuned against the eval suite in this milestone, not guessed at and left.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start with a small indexed corpus about one topic. Ask a question on a completely different topic and observe Askwell decline to answer rather than producing prose. Ask a question the corpus covers and observe a normal answer.
- **Other scenarios:** Raise the threshold in configuration and confirm previously answered questions begin abstaining, which proves the threshold is actually applied.
- **Known gaps:** The abstention message is generic until the next ticket. No trace to inspect the near-miss yet.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** Critical
- **Labels / Component:** `phase:1`, retrieval, `constraint:grounding`
- **Granularity:** One decision point and its storage.

---

### M2-ABSTAIN-BE-054 — Abstention copy that proves the search happened

**Type:** Story

**User Story**
- **Actor:** someone who has just been told Askwell does not know.
- **User Need:** evidence that it actually looked, and a next action.
- **Business Value:** a bare "I don't know" reads as a shrug; naming what was searched is what makes the user believe the tool tried and tells them what to add.
- *As someone whose question got no answer, I want to see what was searched and what would answer it, so that I know whether the problem is my files or the product.*

**Context / Background**
**Detailed Description:** The abstention message does three jobs: state the situation, prove the search happened by naming the scale of it and the nearest material, and give the next action. It never apologises, never hedges into a partial guess, never offers a general-knowledge answer, and is never coloured as a failure. The prompt lives as a versioned file like every other.

**Scope**
- Abstention composition naming the number of passages and sources searched and the nearest topic found.
- A next action: add the source you would expect this in.
- The distinct empty-corpus variant.
- Prompt file with the standing rule that general knowledge is never used for questions about the user's own material.

**Out of Scope**
- Rendering (M2-ABSTAIN-FE-055).
- Suggesting which specific file to add beyond naming the nearest topic.

**Acceptance Criteria**
- **Acceptance Criteria:** An abstention names the count of passages and sources searched and the nearest material found, and offers the add-a-source action. It contains no apology, no hedge and no general-knowledge content. The empty-corpus case reads differently from the nothing-matched case. **C5 is preserved and a test asserts the prompt's no-general-knowledge statement is present.**
- **Edge Cases:** Nothing at all was retrieved, so there is no nearest material — the message says the search found nothing close rather than inventing a nearest topic. A very large corpus — counts are accurate, not rounded to something reassuring. A question in another language — the English-only statement takes precedence over abstention.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/ask.md` §6 copy; `../states-and-edge-cases.md` §2.
- **Validation Rules:** The message must never include a caveated attempt at the answer.
- **Audit / Logging Requirements:** The abstention and its counts are in the interaction record.
- **Analytics Events:** Local counter only — nothing transmitted (C1).

**Real-World Example Scenarios**
- "I searched 1,240 passages across 38 documents and 2 databases. The closest material was about supplier onboarding, which does not cover payment terms."

**Dependencies & Assumptions**
- **Dependencies:** M2-ABSTAIN-RET-053, M1-ASK-BE-037.
- **API / Data Touchpoints:** Retrieval counts; prompt files.
- **Assumptions:** Naming the nearest topic is derivable from the top candidate's heading without a second model call, or with a very cheap one.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start with documents about one subject. Ask about an unrelated subject. Read the message: it states nothing answers this, gives real counts, names the closest material, and offers to add a source. Confirm there is no apology and no attempt at an answer. Then remove all sources and ask again — the message is different and says there is nothing indexed.
- **Other scenarios:** Ask something the corpus half-covers and confirm this path is not taken — that is the partial path.
- **Known gaps:** It renders as ordinary prose until the next ticket. No trace showing the near-miss.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** Critical
- **Labels / Component:** `phase:1`, backend, `constraint:grounding`
- **Granularity:** One composition path and one prompt file.

---

### M2-ABSTAIN-FE-055 — The abstained state on Ask

**Type:** Story

**User Story**
- **Actor:** someone reading an answer that is not an answer.
- **User Need:** to see at a glance that this is a considered "no", not an error and not a hedged answer.
- **Business Value:** colouring abstention as a failure teaches users that the most trustworthy thing the product does is a problem.
- *As someone who values being told the truth, I want "I don't know" to look like a deliberate state, so that I read it as the product working rather than breaking.*

**Context / Background**
**Detailed Description:** Render abstention at full measure with generous space, in the ordinary text and muted tokens — never the alarm colour, never a small grey note, never an inline caveat. The margin renders its explicit empty state saying nothing in the files matched. The next action is present and obvious.

**This surface later carries the escalation offer, and its shape must anticipate that.** From Phase 6.5, `../ux/web-search.md` §2 renders three options — search the web, ask a larger model, add a source instead — **below the abstention, never above it**. The abstention is the answer; the offer is what the user may do next. This ticket therefore places the add-a-source action in the region that offer will occupy, so M6.5-WEB-FE-186 adds two siblings beside it rather than rebuilding the state. It must not leave a design in which anything could sit above the abstention statement.

**A collapsed abstained turn shows no source count** (`../ux/conversation.md` §2, `../states-and-edge-cases.md` §7.1). M1-CONV-BE-177 stores the absence and M1-CONV-FE-178 renders it; this ticket is where the abstention path actually produces it, so the two must be checked together.

**Scope**
- Abstained state rendering per the specification.
- Margin empty state for abstention specifically.
- The add-a-source action wired to the add flow with the question retained so it can be re-asked, positioned below the abstention statement in the region the escalation offer later shares.
- Confirmation that an abstained turn collapses with no source count.

**Out of Scope**
- The web-search and larger-model escalations (M6.5-WEB-FE-186). They do not exist yet and **must not be stubbed in**, because a disabled "search the web" control on the abstention surface teaches exactly the expectation C10 exists to prevent.
- Threshold adjustment (M5).
- Trace panel (M5).

**Acceptance Criteria**
- **Acceptance Criteria:** An abstention renders visually distinct from an answer, at full measure, without alarm colouring. The margin explicitly says it is empty because nothing matched. The add-a-source action works and the question is retained for re-asking, and sits **below** the abstention statement. Collapsing an abstained turn produces no source count, distinguishable at a glance from an answered turn.
- **Edge Cases:** An abstention immediately after a normal answer — the visual distinction is clear in sequence, not only in isolation. A narrow window — the state renders correctly with the margin inline. Abstention in a voice turn (M6) — spoken in full without softening. An abstained turn collapsed between two answered ones — the absent count reads as absent, carried by shape as well as colour.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/ask.md` §5 abstained and §6; `../ux/conversation.md` §2 and §5 for the collapsed abstained turn; `../ux/design-system.md` §2 — abstention is never the alarm colour.
- **Validation Rules:** No design change may soften abstention into a caveated guess; the specification records why to refuse. Nothing may be rendered above the abstention statement — the layout that later carries the escalation offer must make that structurally true rather than a convention (C10).
- **Audit / Logging Requirements:** None beyond M2-ABSTAIN-OBS-056.
- **Analytics Events:** Local counter only — nothing transmitted (C1).

**Real-World Example Scenarios**
- A user sees the abstention, clicks add-a-source, adds the missing policy document, and re-asks with the question already there.

**Dependencies & Assumptions**
- **Dependencies:** M2-ABSTAIN-BE-054, M1-CITE-FE-043.
- **API / Data Touchpoints:** Streaming abstention event.
- **Assumptions:** The retained question survives the navigation to add a source and back.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start with an indexed corpus. Ask a covered question and read the answer. Then ask an uncovered one. Observe the abstention rendered with more space, in ordinary type, not red, with the margin stating it is empty. Click add-a-source, add a relevant document, wait for indexing, and confirm the question is still available to re-ask — then ask it and get an answer.
- **Other scenarios:** Narrow the window and confirm the state still reads correctly. Ask a second question and confirm the abstained turn collapses with no number.
- **Known gaps:** No trace, so the near-miss is not visible to the user yet. No threshold control. **No escalation offer** — Askwell cannot search the web or reach a larger model at this point, and nothing on this screen suggests it can. That arrives in M6.5 and M8 respectively, and until it does, abstention is the end of the turn.

**Effort & Granularity Check**
- **Estimate:** 2–3 hours · **Priority:** Critical
- **Labels / Component:** `phase:1`, frontend, `constraint:grounding`
- **Granularity:** One state and one action.

---

### M2-ABSTAIN-OBS-056 — Record abstentions with scores and threshold stored, not recomputed

**Type:** Task

**User Story**
- **Actor:** the maintainer investigating why abstention rate moved.
- **User Need:** the numbers as they were at the time.
- **Business Value:** abstention rate is the operational signal that the corpus has gaps, and it is gameable; the stored scores are what make a later investigation possible.
- *As someone trying to understand a change in behaviour, I want the scores and threshold as they were, so that the explanation of an old answer is still true.*

**Context / Background**
**Detailed Description:** Abstentions are recorded in the interaction log with the retrieved candidates, their scores, the threshold in force and the near-miss. Nothing is recomputed later. A local, on-demand abstention rate is derivable from the log for the user's own copy; nothing is transmitted, because there is no telemetry.

**Scope**
- Abstention flag and detail on the interaction record.
- Local on-demand computation of abstention rate over a window.
- The rule that scores and threshold are stored values, enforced by a test.

**Out of Scope**
- Any dashboard.
- Any transmission of any number (there is none, ever).

**Acceptance Criteria**
- **Acceptance Criteria:** Every abstention is recorded with candidates, scores, threshold and the near-miss. The abstention rate can be computed locally over a window. Changing the threshold later does not alter the stored values of past turns.
- **Edge Cases:** A turn with no candidates at all — recorded with an empty candidate list rather than being omitted. A very long window — computation is bounded and reports what it covered.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** Surfaced later by the trace (M5) and by `../states-and-edge-cases.md` §6 abstention rate rising.
- **Validation Rules:** Recomputation of a stored score is a defect.
- **Audit / Logging Requirements:** This ticket is the audit requirement for abstention.
- **Analytics Events:** Local counter and rate only, computed on demand from the user's own log — nothing transmitted (C1).

**Real-World Example Scenarios**
- Six months later the user opens an old abstention and it still explains itself with the numbers that produced it.

**Dependencies & Assumptions**
- **Dependencies:** M2-ABSTAIN-RET-053, M1-ASK-OBS-041.
- **API / Data Touchpoints:** `audit_interactions`; `messages.trace`.
- **Assumptions:** Storing candidate scores per turn is affordable within the interaction store's size expectations.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, ask several questions including two that abstain. Compute the local abstention rate and confirm it reflects those two. Change the threshold in configuration, restart, and recompute — the historical turns keep their original recorded threshold.
- **Other scenarios:** Verify the log chain still passes after abstention records are written.
- **Known gaps:** No user-facing surface for the rate until settings grows in M7.

**Effort & Granularity Check**
- **Estimate:** 2–3 hours · **Priority:** High
- **Labels / Component:** `phase:1`, observability, `constraint:grounding`, `constraint:audit`
- **Granularity:** One record extension and one computation.

---

### M2-PARTIAL-BE-057 — Partial answers: answer the grounded part, name the gap

**Type:** Story

**User Story**
- **Actor:** someone who asked a two-part question where only one part is covered.
- **User Need:** the covered part answered and the uncovered part named plainly.
- **Business Value:** the tempting failure is to smooth over the gap in fluent prose, which breaks both the citation and the abstention constraints at once.
- *As someone asking a compound question, I want the part you can answer answered and the rest named as missing, so that I know exactly what I still have to find.*

**Context / Background**
**Detailed Description:** When retrieval covers some claims and not others, the answer states the grounded part with citations and explicitly names what is not covered. The ungrounded part is never smoothed into fluent prose and never filled from general knowledge. This is a distinct composition path with its own prompt handling, not a variation of the normal answer.

**Scope**
- Detection that a question has covered and uncovered aspects.
- Composition that answers the covered part and names the uncovered part.
- Marking the message as partial so the renderer and the eval can distinguish it.

**Out of Scope**
- Rendering (M2-PARTIAL-FE-058).
- Multi-step retrieval to try harder before declaring partial (M5).

**Acceptance Criteria**
- **Acceptance Criteria:** A compound question with one covered aspect produces an answer covering that aspect with citations, plus an explicit statement of what is not covered. The uncovered part contains no unsourced factual content. The message is marked partial. **C4 and C5 are both preserved: everything asserted is cited, and nothing uncovered is invented.**
- **Edge Cases:** Every aspect uncovered — this is abstention, not partial, and the branch must not blur. Every aspect covered — an ordinary answer. An aspect that is covered weakly but above threshold — answered with its citation, and the weakness is visible in the trace rather than hedged in prose.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/ask.md` §5 partial; `../states-and-edge-cases.md` §2 partial retrieval.
- **Validation Rules:** The uncovered statement names the aspect, not a generic "some information was unavailable".
- **Audit / Logging Requirements:** Partial status is on the interaction record.
- **Analytics Events:** Local counter of partial answers — nothing transmitted (C1).

**Real-World Example Scenarios**
- "You asked about payment terms and about the termination notice period. Payment terms are 45 days, from page 14. Nothing in your files covers the termination notice period for this supplier."

**Dependencies & Assumptions**
- **Dependencies:** M2-ABSTAIN-BE-054.
- **API / Data Touchpoints:** Prompt files; `messages`.
- **Assumptions:** Aspect decomposition is prompt-driven and imperfect; the eval suite measures it and the counter-metric catches uncited drift.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start with a corpus covering one of two topics. Ask a question spanning both. Read the answer: the covered half is answered with a source card, and the other half is named explicitly as not covered. Confirm no fluent bridging sentence asserts anything about the uncovered half.
- **Other scenarios:** Ask a fully uncovered version of the same question and confirm it abstains instead.
- **Known gaps:** Decomposition can miss an aspect and answer as if complete; the eval suite is what measures that.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** Critical
- **Labels / Component:** `phase:1`, backend, `constraint:grounding`
- **Granularity:** One composition branch.

---

### M2-PARTIAL-FE-058 — Partial rendering and the conflicting-sources presentation

**Type:** Story

**User Story**
- **Actor:** someone whose two documents disagree.
- **User Need:** both positions shown with their dates and citations, rather than one silently chosen.
- **Business Value:** the quality gate has a whole category for conflict handling; it needs an interface, not only model behaviour.
- *As someone whose 2024 handbook and 2025 policy disagree, I want both shown with their dates, so that I decide which is current rather than the tool deciding silently.*

**Context / Background**
**Detailed Description:** Render the partial state so the grounded and ungrounded parts are visually distinguishable, and render the conflicting-sources state presenting both positions with both citations and their dates, plus an offer to resolve which writes a memory fact once memory exists in M3. Until then the offer records the user's choice as a pending resolution and says so.

**Scope**
- Partial state rendering with the uncovered part distinguishable.
- Conflicting-sources rendering with both citations and dates.
- The resolve offer, wired to memory in M3 and stated as pending until then.

**Out of Scope**
- Conflict detection in composition (M2-PARTIAL-BE-059 handles detection).
- Memory writing (M3).

**Acceptance Criteria**
- **Acceptance Criteria:** A partial answer shows the uncovered part as distinct from the answered part. A conflicting answer shows both positions with both source cards and their document dates, and never silently prefers one. The resolve offer is present.
- **Edge Cases:** Three or more conflicting sources — all presented, ordered by date. Conflict where one source is superseded — the superseded one is labelled as such rather than presented as an equal. A narrow window — both cards remain visible inline.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/ask.md` §5 partial and conflicting sources; `../states-and-edge-cases.md` §2.
- **Validation Rules:** Conflict presentation must not rank by model preference; date and supersession are the only orderings.
- **Audit / Logging Requirements:** A resolution choice, once memory exists, is a decisions record.
- **Analytics Events:** Local counter of conflicts presented — nothing transmitted (C1).

**Real-World Example Scenarios**
- The user sees 30 days from the 2024 handbook and 45 days from the 2025 policy, both cited and dated, and resolves it in one click.

**Dependencies & Assumptions**
- **Dependencies:** M2-PARTIAL-BE-057, M2-PARTIAL-BE-059, M1-CITE-FE-043.
- **API / Data Touchpoints:** Citation events with document dates.
- **Assumptions:** Document dates are available from ingestion metadata or the filename; where neither exists, the added date is used and labelled as such.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, add two documents that disagree on a value. Ask about that value. Observe both positions presented with both cards and their dates, with neither silently chosen. Click each card and confirm the passages really do disagree. Use the resolve offer and read what it says will happen.
- **Other scenarios:** Ask a partially covered question and confirm the uncovered part is visually distinct.
- **Known gaps:** Resolution does not persist a memory fact until M3; the interface says so.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** High
- **Labels / Component:** `phase:1`, frontend, `constraint:grounding`
- **Granularity:** Two states sharing the margin.

---

### M2-PARTIAL-BE-059 — Detect conflicting sources rather than choosing one

**Type:** Story

**User Story**
- **Actor:** someone relying on an answer drawn from a corpus that has changed over the years.
- **User Need:** contradictions surfaced rather than averaged away.
- **Business Value:** an unresolved contradiction answered confidently is exactly the failure this product exists to avoid.
- *As someone with years of superseding policies, I want contradictions raised, so that a confident answer is not silently choosing the wrong year.*

**Context / Background**
**Detailed Description:** During composition, detect when retrieved passages give materially different answers to the same question and take the conflict branch: present both, with citations and dates, rather than picking one. Where a memory fact resolves the conflict (from M3), it applies and is cited as memory. Where the conflict remains unresolved and blocks the answer, an inline clarification is raised in the conversation (M3).

**Scope**
- Conflict detection over retrieved candidates in composition.
- The conflict composition branch.
- A hook for memory-based resolution, active from M3.

**Out of Scope**
- The clarification itself (M3).
- Rendering (M2-PARTIAL-FE-058).

**Acceptance Criteria**
- **Acceptance Criteria:** Two retrieved passages with materially different values for the same asked fact produce a conflict answer naming both with citations. A single consistent set produces an ordinary answer. Supersession is respected — a superseded document is not presented as an equal.
- **Edge Cases:** Two passages that differ in wording but not in substance — not a conflict, and over-detection is as bad as under-detection. A conflict between a document and a memory fact — memory is cited as the resolution, once memory exists. A conflict where one side is a low-confidence OCR page — both presented with the OCR quality noted.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/ask.md` §5 conflicting sources.
- **Validation Rules:** Never silently prefer a source.
- **Audit / Logging Requirements:** Conflicts detected are recorded on the interaction.
- **Analytics Events:** Local counter only — nothing transmitted (C1).

**Real-World Example Scenarios**
- A researcher's two versions of a protocol disagree on a threshold, and the answer says so instead of averaging them.

**Dependencies & Assumptions**
- **Dependencies:** M2-PARTIAL-BE-057.
- **API / Data Touchpoints:** Prompt files; `messages.trace`.
- **Assumptions:** Detection is prompt-driven and measured by the conflicting-source eval subset with a 0.75 bar.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, add two documents that disagree on a specific figure. Ask about it and confirm the conflict branch is taken. Then supersede one with the other and ask again — the answer uses the current version and says as of that revision.
- **Other scenarios:** Add two documents that agree in substance but differ in wording and confirm no false conflict.
- **Known gaps:** No memory-based resolution until M3. Detection quality is unmeasured until the eval subset lands in this milestone.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** High
- **Labels / Component:** `phase:1`, backend, `constraint:grounding`
- **Granularity:** One detection and one branch.

---

### M2-FAIL-FE-060 — Degrade to search when the assistant is unavailable

**Type:** Story

**User Story**
- **Actor:** someone whose inference process died mid-afternoon.
- **User Need:** to still be able to find things in their own documents.
- **Business Value:** retrieval does not need the assistant; degrading to search rather than to a blank product is the difference between an inconvenience and an uninstall.
- *As someone whose assistant has stopped working, I want to still search my files, so that Askwell is degraded rather than useless.*

**Context / Background**
**Detailed Description:** When the assistant is unavailable, Ask states that plainly with a fix path and offers search across sources, returning ranked passages with their citations. This uses the retrieval path, which does not need the model for lexical search and can use cached embeddings for dense search of an already-embedded corpus. Ingestion that needs embedding is refused with a stated reason rather than failing silently.

**Scope**
- Assistant-unavailable state on Ask with a fix path.
- Search across sources returning cited passages, using retrieval without composition.
- Ingestion behaviour while the assistant is down: extraction and chunking continue, embedding queues rather than fails.

**Out of Scope**
- Automatic repair of the process.
- Model swap (M7).

**Acceptance Criteria**
- **Acceptance Criteria:** With the assistant stopped, Ask says so and offers search. Search returns ranked passages with file and page. Adding a document during the outage extracts and chunks, and embedding resumes when the assistant returns. Nothing reports success that did not happen.
- **Edge Cases:** The assistant is restarting — the state says restarting rather than unavailable. Dense search unavailable because embeddings need the model for the query — lexical search still works and the interface says results are keyword-only. The assistant returns mid-session — the interface recovers without a reload.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/ask.md` §5 model unavailable; `../states-and-edge-cases.md` §1 model not loaded and §6 model swap.
- **Validation Rules:** A document is not marked indexed while its embeddings are pending.
- **Audit / Logging Requirements:** Outages are logged with cause and duration.
- **Analytics Events:** Local counter only — nothing transmitted (C1).

**Real-World Example Scenarios**
- A user's laptop runs out of memory and the assistant dies; they keep working by searching their contracts by keyword until they restart it.

**Dependencies & Assumptions**
- **Dependencies:** M0-MODEL-BE-020, M1-ASK-RET-035, M1-ADD-ING-025.
- **API / Data Touchpoints:** Retrieval; health surface.
- **Assumptions:** Query embedding needs the model, so dense search degrades; lexical search is genuinely independent.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start with an indexed corpus. Stop the inference process. Open Ask and read the message — the assistant is unavailable, with a fix, and search is offered. Search for a term you know is in a document and confirm ranked passages with file and page. Add a new document during the outage and confirm it extracts and waits for embedding. Restart the assistant and confirm both the interface and the queued embedding recover.
- **Other scenarios:** Confirm the interface shows a restarting state during the restart rather than flapping between available and unavailable.
- **Known gaps:** Search is keyword-oriented during an outage. There is no repair button; the fix is described.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** High
- **Labels / Component:** `phase:1`, frontend, retrieval
- **Granularity:** One degraded mode across two surfaces.

---

### M2-DELETE-BE-061 — Tombstoned deletion that clears content and embedding

**Type:** Story

**User Story**
- **Actor:** someone removing a client's files after the engagement ended.
- **User Need:** the content genuinely gone from Askwell while old citations still resolve honestly.
- **Business Value:** deletion that breaks the audit trail is unacceptable; deletion that leaves content influencing retrieval is worse.
- *As someone whose obligation to a former client is to stop holding their material, I want deletion to actually remove the content, so that it stops appearing in answers.*

**Context / Background**
**Detailed Description:** Deleting a document clears its chunk content and embedding and sets a tombstone with a date and reason, while the rows survive so old citations resolve to "deleted on that date". The database check that a cleared chunk has no embedding enforces this independently of the code. Deleting a source removes its schema notes; general memory learned from it survives, because an abbreviation is still true after the file it came from is gone.

**Scope**
- Document and source deletion clearing content and embedding in one statement.
- Tombstone with date and reason; the row retained.
- Schema-note removal on source deletion, with general memory preserved.
- Retrieval excluding tombstoned material.

**Out of Scope**
- The confirmation copy and the deleted citation card (M2-DELETE-FE-062).
- Full application reset (M7).

**Acceptance Criteria**
- **Acceptance Criteria:** After deletion, the document's content no longer appears in any answer and its chunks carry no embedding. Old citations resolve to a deletion date rather than breaking. The user's original file on disk is untouched. Deleting a source removes its schema notes and leaves general memory intact. **C6 is preserved: nothing is removed from the audit stores; the deletion itself is a decisions record.**
- **Edge Cases:** Deleting a document with pending ingestion — the job is cancelled and the tombstone applies. Deleting a source mid-import — the import stops and partial material is tombstoned rather than left half-indexed. Deleting a superseded version — permitted; the live version is unaffected. Re-adding a previously deleted file — treated as a new document, not a resurrection.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/library.md` §4; `../ux/source-viewer.md` §4 deleted source; `../states-and-edge-cases.md` §3 document deleted.
- **Validation Rules:** `deleted_at` is the tombstone and `superseded_by` is for versions; never reuse one for the other.
- **Audit / Logging Requirements:** Deletion with its reason is a decisions record (`../audit-log.md` §7).
- **Analytics Events:** Local counter only — nothing transmitted (C1).

**Real-World Example Scenarios**
- A consultant deletes a former client's folder; questions stop returning it, and an answer from March still opens to say the source was deleted in September.

**Dependencies & Assumptions**
- **Dependencies:** M0-DATA-DB-014, M1-INDEX-ING-032.
- **API / Data Touchpoints:** `documents.deleted_at`, `deleted_reason`; `chunks`; `schema_notes`.
- **Assumptions:** Clearing content is sufficient; the row footprint that remains is metadata, not material.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, add a document, ask a question about it and note the answer and its citation. Delete the document from the library. Ask the same question again and confirm Askwell no longer answers from it. Scroll back to the earlier answer and click its card — it says the source was deleted, with the date. Check the file on disk — it is still there, untouched.
- **Other scenarios:** Delete a source mid-import and confirm nothing is left half-indexed.
- **Known gaps:** No undo. Re-adding creates a fresh document rather than restoring the old one.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** Critical
- **Labels / Component:** `phase:1`, backend, database, `constraint:audit`
- **Granularity:** One state transition with three consequences.

---

### M2-DELETE-FE-062 — Deletion confirmation and the deleted-source citation card

**Type:** Story

**User Story**
- **Actor:** someone about to delete a source and unsure what that means.
- **User Need:** three facts stated before they commit: their file is safe, the content is genuinely gone, and old citations degrade honestly.
- **Business Value:** a user who fears deletion will hoard broken sources; a user who fears their originals will not use the product at all.
- *As someone about to delete a source, I want to know exactly what happens to my file and my old answers, so that I can do it without worrying.*

**Context / Background**
**Detailed Description:** The confirmation names the source and states the three facts. Deleted sources stay listed, greyed and filterable out, because the record is what makes an old citation resolve at all. In an answer, a card for a deleted source renders as deleted with the date, greyed and not clickable.

**Scope**
- Deletion confirmation copy and flow from the library.
- Greyed deleted rows in the library with a filter.
- Deleted-source card rendering in the margin.
- Deleted-source state in the source viewer.

**Out of Scope**
- Bulk deletion.
- Delete-all-memory and reset (M7).

**Acceptance Criteria**
- **Acceptance Criteria:** The confirmation names the source and states all three facts. After deletion the row remains, greyed, and can be filtered out. A card citing a deleted source renders as deleted with the date, greyed and not clickable. The viewer states the deletion date if reached another way.
- **Edge Cases:** Deleting a source that is currently open in the viewer — the viewer updates to the deleted state rather than showing stale content. A conversation containing many deleted citations — all render consistently. Filtering deleted out and then adding a new source — the filter does not hide the new one.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/library.md` §4 and §5 deleted-filtered-in; `../ux/ask.md` §5 deleted source cited; `../ux/source-viewer.md` §4 deleted source.
- **Validation Rules:** The confirmation must state that the original file is untouched.
- **Audit / Logging Requirements:** As M2-DELETE-BE-061.
- **Analytics Events:** Local counter only — nothing transmitted (C1).

**Real-World Example Scenarios**
- A user hesitates over deleting, reads that their file on disk is untouched, and proceeds.

**Dependencies & Assumptions**
- **Dependencies:** M2-DELETE-BE-061, M1-LIB-FE-050, M1-CITE-FE-043.
- **API / Data Touchpoints:** `documents.deleted_at`; citation resolution.
- **Assumptions:** Greying plus a filter is enough; a separate archive view is not needed.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start with an answer that cites a document. Go to the library, choose delete, and read the confirmation — confirm all three facts are stated. Confirm the deletion. See the row greyed. Filter deleted out and confirm it disappears from the list. Return to the earlier answer and see the card rendered as deleted with the date, not clickable.
- **Other scenarios:** Delete a source while its viewer is open and confirm the viewer updates.
- **Known gaps:** No undo, no bulk delete, no archive view.

**Effort & Granularity Check**
- **Estimate:** 2–3 hours · **Priority:** High
- **Labels / Component:** `phase:1`, frontend
- **Granularity:** One confirmation and three renderings.

---

### M2-EVAL-TEST-063 — Port the eval harness and make it run offline

**Type:** Task

**User Story**
- **Actor:** the maintainer about to change a prompt.
- **User Need:** a repeatable measurement rather than an impression.
- **Business Value:** prompt engineering without an eval gate is guessing, and small models are exactly where guessing fails.
- *As someone about to change how answers are composed, I want a suite I can run before and after, so that I know whether I improved it or broke it.*

**Context / Background**
**Detailed Description:** A draft benchmark script exists outside this repository and should be ported rather than rewritten. The harness runs a named suite against the configured model, runs each task three times, and reports mean and worst-of-three, because a single malformed output fails an entire turn and errors compound. It runs with no network access.

**Scope**
- Harness with suite selection, three runs per task, mean and worst-case reporting.
- A results format recorded in the build state document for before-and-after comparison.
- Offline operation with a locally available model.

**Out of Scope**
- The suites themselves (M2-EVAL-TEST-064 onward).
- The CI gate (M2-EVAL-DEPLOY-067).

**Acceptance Criteria**
- **Acceptance Criteria:** The harness runs a named suite and reports mean and worst-of-three per category. It runs with the network disabled. Results are recorded in a comparable format.
- **Edge Cases:** The model is unavailable — the run fails clearly rather than reporting zeros as if measured. A task that times out — recorded as a failure with the reason, not silently skipped. Nondeterministic output — the three-run design is the answer, and variance is reported. **A suite whose bar is 1.00** — SQL safety, and later web escalation discipline — reports pass or fail rather than a mean that reads as nearly fine, because "0.97 on ten tasks" is a failure that looks like a score.
- **Assumption, stated:** the harness must be able to run a suite with **no network access at all** and still exercise the web-search path, because M6.5's suite asserts that Askwell *does not* reach the web. That suite needs no provider, only a machine with the network down and an assertion about what was refused.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** None.
- **Validation Rules:** A suite may never be run once and reported as if run three times.
- **Audit / Logging Requirements:** Runs are recorded with model, prompt version and date.
- **Analytics Events:** None.

**Real-World Example Scenarios**
- A prompt change shows a mean improvement and a worst-case regression, and is rejected on the worst case.

**Dependencies & Assumptions**
- **Dependencies:** M1-ASK-BE-037, M0-MODEL-BE-019.
- **API / Data Touchpoints:** The answer path; prompt versions.
- **Assumptions:** The existing draft script is a usable starting point; porting is cheaper than rewriting.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start with a small fixture corpus indexed. Run the harness against a tiny suite. Observe per-task results, three runs each, with mean and worst-case. Disconnect the network and run again — identical behaviour.
- **Other scenarios:** Stop the model and run — the harness fails clearly.
- **Known gaps:** No real suites yet. No gate. Scoring for some categories is manual until the suites define it. Eight categories totalling 165 tasks are planned (`../build-plan.md`); three exist by the end of this milestone.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** Critical
- **Labels / Component:** `phase:1`, test, `eval`
- **Granularity:** One harness.

---

### M2-EVAL-TEST-064 — Grounded document QA suite

**Type:** Task

**User Story**
- **Actor:** the maintainer choosing whether a model can be a profile default.
- **User Need:** forty grounded questions with known answers over a fixture corpus.
- **Business Value:** no model becomes a profile default without passing the gate, and this is its largest category.
- *As someone deciding whether a smaller model is good enough for the light profile, I want a repeatable grounded-QA score, so that the decision is measured.*

**Context / Background**
**Detailed Description:** Build a fixture corpus and forty grounded document questions with known answers and known source passages, scored on answer correctness and on whether the cited passage is the right one. Bar: 0.85 mean and 0.70 worst-of-three. All English.

**Scope**
- Fixture corpus covering digital PDFs, a scan, an Office document and a table.
- Forty tasks with expected answers and expected source passages.
- Scoring covering both answer and citation correctness.

**Out of Scope**
- Abstention, conflict, SQL, tool and memory categories — their own tickets.

**Acceptance Criteria**
- **Acceptance Criteria:** The suite runs and reports mean and worst-case. Citation correctness is scored, not only answer text. The fixture corpus is committed and reproducible.
- **Edge Cases:** A task whose answer appears in two places — both accepted as correct citations. A task depending on a table — included deliberately, because that is where chunking fails. A scanned-source task — included, because OCR quality is a real variable.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** None.
- **Validation Rules:** Fixture documents must not contain material that could be answered from general knowledge, or the suite measures the wrong thing.
- **Audit / Logging Requirements:** Results recorded with model and prompt version.
- **Analytics Events:** None.

**Real-World Example Scenarios**
- A chunking change improves mean grounded QA but drops the table questions, which the suite makes visible.

**Dependencies & Assumptions**
- **Dependencies:** M2-EVAL-TEST-063.
- **API / Data Touchpoints:** The answer path; `citations`.
- **Assumptions:** Forty tasks is enough to detect a meaningful regression at this scale.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, index the fixture corpus through the normal add flow rather than a shortcut, then run the suite. Observe forty tasks, three runs each, with mean and worst-case per category and a list of failures with their expected and actual citations.
- **Other scenarios:** Deliberately break chunking and confirm the table tasks fail.
- **Known gaps:** English only. No adversarial or long-context tasks.

**Effort & Granularity Check**
- **Estimate:** 4–6 hours · **Priority:** Critical
- **Labels / Component:** `phase:1`, test, `eval`, `constraint:grounding`
- **Granularity:** One corpus and forty tasks. Upper bound.

---

### M2-EVAL-TEST-065 — Abstention subset with the 0.90 bar

**Type:** Task

**User Story**
- **Actor:** the maintainer under pressure to reduce the abstention rate.
- **User Need:** a hard test that fails when abstention is weakened.
- **Business Value:** hallucination in this category is disqualifying, and this suite is the thing that stops a well-meaning threshold change breaking the product.
- *As someone who will one day be tempted to lower the threshold, I want a test that fails when I do, so that the temptation is caught.*

**Context / Background**
**Detailed Description:** Fifteen unanswerable questions over the fixture corpus, scored on whether the system abstains and whether the abstention names what was searched. Bar: 0.90, and this is the category where a failure is disqualifying rather than a regression. **These tests must not be weakened to make a change pass, and the retrieval threshold must not be lowered to improve the number.**

**Scope**
- Fifteen unanswerable tasks, including near-misses where relevant material exists but does not answer the question.
- Scoring for abstention and for the presence of the search evidence.
- A guard test asserting the threshold default has not been lowered without a recorded decision.

**Out of Scope**
- Partial-answer scoring, which belongs with the grounded suite.

**Acceptance Criteria**
- **Acceptance Criteria:** The suite reports a score against the 0.90 bar. A deliberately weakened abstention branch fails it. Lowering the threshold default without a decision-log entry fails the guard test.
- **Edge Cases:** A near-miss task where a passage scores just under threshold — must abstain and must show the near-miss. A task where the corpus is empty — the empty-corpus variant is asserted separately. A hedged partial answer — scored as a failure, not a partial credit.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** None.
- **Validation Rules:** A hedged answer counts as a hallucination for scoring purposes.
- **Audit / Logging Requirements:** Results recorded with threshold in force.
- **Analytics Events:** None.

**Real-World Example Scenarios**
- A prompt change makes answers more helpful and starts guessing on two unanswerable questions; the suite fails and the change is rejected.

**Dependencies & Assumptions**
- **Dependencies:** M2-EVAL-TEST-064, M2-ABSTAIN-BE-054.
- **API / Data Touchpoints:** The answer path; threshold configuration.
- **Assumptions:** Fifteen tasks at a 0.90 bar means at most one failure is tolerable, which is the intended severity.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start with the fixture corpus indexed. Run the abstention subset and read the score. Then lower the threshold in configuration and run it again — the score should drop and the guard test should fail, demonstrating the suite is actually sensitive to the thing it exists to protect.
- **Other scenarios:** Modify the abstention prompt to allow a caveated guess and confirm the suite fails.
- **Known gaps:** English only. Fifteen tasks is a small sample and the bar is set high to compensate.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** Critical
- **Labels / Component:** `phase:1`, test, `eval`, `constraint:grounding`
- **Granularity:** Fifteen tasks and one guard.

---

### M2-EVAL-TEST-066 — Conflicting-source subset and worst-case reporting discipline

**Type:** Task

**User Story**
- **Actor:** the maintainer comparing two models.
- **User Need:** conflict handling measured, and worst-case reported beside mean everywhere.
- **Business Value:** a model at 0.90 mean with 0.55 worst-case is worse in production than a steady 0.80.
- *As someone choosing a default model, I want the worst case reported beside the mean, so that I do not ship something that fails badly one turn in three.*

**Context / Background**
**Detailed Description:** Ten conflicting-source tasks with a 0.75 bar, scored on whether both positions are presented with citations and dates and neither is silently preferred. Alongside them, make worst-of-three reporting mandatory in the harness output for every category, with a summary that refuses to print a mean without its worst case.

**Scope**
- Ten conflict tasks over fixture documents that genuinely disagree.
- Scoring for both-presented, both-cited and no-silent-preference.
- Harness output that always pairs mean with worst case.

**Out of Scope**
- Memory-based conflict resolution scoring (M3's memory subset).

**Acceptance Criteria**
- **Acceptance Criteria:** The subset reports against the 0.75 bar. Every category's output shows mean and worst case together. A silently preferred source scores zero for that task.
- **Edge Cases:** A conflict where one document is superseded — correct behaviour is to answer from the current version and say so, and the task scores that rather than conflict presentation. A false conflict on wording — scored as a failure of over-detection.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** None.
- **Validation Rules:** The harness must not emit a mean without a worst case.
- **Audit / Logging Requirements:** Results recorded per run.
- **Analytics Events:** None.

**Real-World Example Scenarios**
- Two models score the same mean; one has a much worse worst case and is rejected.

**Dependencies & Assumptions**
- **Dependencies:** M2-EVAL-TEST-064, M2-PARTIAL-BE-059.
- **API / Data Touchpoints:** The answer path.
- **Assumptions:** Conflict scoring can be automated by checking for both expected citations and both values.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start with the fixture corpus. Run the conflict subset and read the results, confirming each task reports mean and worst case. Inspect one failing task's output and confirm the failure reason is legible.
- **Other scenarios:** Attempt to print a mean-only summary and confirm the harness refuses.
- **Known gaps:** Ten tasks is a small sample. Over-detection is scored but not deeply covered.

**Effort & Granularity Check**
- **Estimate:** 2–3 hours · **Priority:** High
- **Labels / Component:** `phase:1`, test, `eval`
- **Granularity:** Ten tasks and one reporting rule.

---

### M2-EVAL-DEPLOY-067 — Run the eval gate on a capable runner

**Type:** Task

**User Story**
- **Actor:** the maintainer merging a prompt change.
- **User Need:** the suite running where a model can actually be loaded.
- **Business Value:** any prompt change requires an eval run, and a gate that cannot execute is not a gate.
- *As someone merging a change to a prompt, I want the eval suite to run automatically somewhere capable, so that the rule is enforced rather than remembered.*

**Context / Background**
**Detailed Description:** The 165-task gate needs a model and time, which hosted runners do not comfortably provide. Run it on a self-hosted runner or by manual dispatch, with a cached small model, triggered when a prompt file or the retrieval configuration changes. The run posts its results for comparison, and a change that touches a prompt without a run is blocked.

**Scope**
- Workflow triggered by prompt or retrieval-configuration changes, dispatchable manually.
- Model caching so a run does not re-download.
- A check that blocks a prompt change with no recorded run.
- Results published in a comparable form for the before-and-after record.

**Out of Scope**
- Running the full gate on every push — it is too slow and this is deliberate.
- The remaining suites, which arrive with their features in M3, M4, M5 and M6.5.

**Acceptance Criteria**
- **Acceptance Criteria:** Changing a prompt file triggers the eval workflow. The run loads a cached model without downloading it. Results are recorded in a comparable format. A prompt change with no run is blocked from merging.
- **Edge Cases:** The runner is offline — the change is blocked rather than merged unmeasured, and the block explains why. A run that fails for infrastructure reasons — distinguishable from a run that failed on scores. A change touching a prompt only in a comment — still runs; there is no reliable way to know a comment is harmless.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** None.
- **Validation Rules:** The gate's pass bars are those in `../build-plan.md` and may not be lowered to make a change pass.
- **Audit / Logging Requirements:** Every run's results are recorded with model, prompt version and date.
- **Analytics Events:** None.

**Real-World Example Scenarios**
- A prompt tweak lands with before-and-after numbers attached, so six months later it is clear whether it helped.

**Dependencies & Assumptions**
- **Dependencies:** M2-EVAL-TEST-063, M2-EVAL-TEST-065, M0-FOUND-DEPLOY-006.
- **API / Data Touchpoints:** None.
- **Assumptions:** A self-hosted runner or manual dispatch is acceptable for a single-maintainer project; if neither is available, the gate is run locally and its results are pasted into the change, which is stated as the fallback.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Change a prompt file on a branch and push. Observe the eval workflow trigger. Watch it load the cached model and run the suites, then read the published results. Push a second change to the same prompt without a run available and confirm the merge is blocked with a readable reason.
- **Other scenarios:** Dispatch the workflow manually against the main branch and confirm it produces a baseline.
- **Known gaps:** Only three of the **eight** gate categories exist so far — grounded QA, abstention and conflicting sources. Memory application arrives in M3, text-to-SQL and SQL safety in M4, tool selection in M5, and **web escalation discipline in M6.5** (M6.5-EVAL-TEST-194, 10 tasks at 1.00 with no exceptions). The workflow is written so a category is added by naming a suite, not by editing the gate. The runner is a single machine and its results are not reproducible across hardware; the model and settings are recorded so comparisons stay honest.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** High
- **Labels / Component:** `phase:1`, deployment, test, `eval`
- **Granularity:** One workflow and one block rule.
