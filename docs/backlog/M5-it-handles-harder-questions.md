# M5 — It handles harder questions

**Goal:** A question needing both a document lookup and a database query is answered correctly in one turn, with a readable trace of how it happened.

**Phase:** 4 (`../build-plan.md`) · **Depends on:** M4 · **Tickets:** 12 · **Estimated:** 34–48 hours

**Exit condition:** A question requiring a document lookup and a database query is answered correctly in one turn; the trace renders as a readable numbered sequence with timings, scores, the threshold, the query and its validation outcome; the eight-call ceiling returns what was gathered with an explicit note; and tool selection scores at or above 0.85 with worst-case reported.

## Included epics

| Epic | Code | Covers |
| ---- | ---- | ------ |
| Tools | `TOOLS` | The registry and result handling |
| The loop | `LOOP` | Multi-step reasoning, parallelism, the ceiling, step capture |
| Trace | `TRACE` | The panel, its contents, its interactions, its states |
| Evaluation | `EVAL` | Tool selection including parallel calls |

---

### M5-TOOLS-BE-113 — Tool registry with the five exposed tools

**Type:** Story

**User Story**
- **Actor:** someone asking a question that needs more than one lookup.
- **User Need:** the assistant able to reach documents, data and schema in one turn.
- **Business Value:** questions that span a contract and a database are the ones people cannot answer for themselves at all.
- *As someone whose question spans a contract and an invoice table, I want one answer rather than two searches, so that the tool does the joining.*

**Context / Background**
**Detailed Description:** The agent exposes exactly five tools: document search, database query, schema lookup, document listing, and the current date. Each has a declared shape, a bounded result size, and a recorded step in the trace. The registry is the single place a tool is added, so a sixth tool is a deliberate decision rather than an accretion.

**Scope**
- Registry with the five tools, their declared inputs and bounded outputs.
- Per-tool step recording with duration.
- Errors from a tool surfaced to the loop as recoverable rather than fatal.

**Out of Scope**
- The loop itself (M5-LOOP-BE-115).
- Any tool that writes anything — there is none, and there will not be one in v1.

**Acceptance Criteria**
- **Acceptance Criteria:** All five tools are callable and each returns a bounded result. Each call produces a trace step with a duration. A tool error is returned to the loop as a recoverable outcome, not an exception that ends the turn.
- **Edge Cases:** A tool called with invalid arguments — returns a structured error the model can react to, rather than failing the turn. A tool returning an enormous result — bounded with the truncation stated in the result, so the model knows it did not see everything. The database query tool called with no connection — returns the no-connection outcome, which routes to the right message.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** Step labels in `../ux/ask.md` §5; trace steps in `../ux/trace.md` §2.
- **Validation Rules:** The database query tool routes through the full validation chain without exception.
- **Audit / Logging Requirements:** Every tool call is a trace step; database calls also produce interaction records.
- **Analytics Events:** Local counters per tool — nothing transmitted (C1).

**Real-World Example Scenarios**
- A question about overdue invoices for a named supplier calls document search for the contract terms and database query for the invoice rows.

**Dependencies & Assumptions**
- **Dependencies:** M4-SQL-DB-107, M1-ASK-RET-036.
- **API / Data Touchpoints:** Retrieval; the SQL path; `documents`; `schema_notes`.
- **Assumptions:** Five tools is the right surface; a sixth requires a recorded decision.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start with documents and a database both present. Ask a question needing only documents and confirm only the document tools were used, visible in the step labels. Ask one needing only data and confirm the same for the database tools. Confirm the current-date tool is used when a question says "last quarter".
- **Other scenarios:** Call a tool with invalid arguments through a test and confirm a structured error rather than a failed turn.
- **Known gaps:** No loop yet, so tools are called once per turn at most.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** Critical
- **Labels / Component:** `phase:4`, backend
- **Granularity:** Five tools sharing one contract.

---

### M5-TOOLS-BE-114 — Tool results delimited as data, never instruction

**Type:** Task

**User Story**
- **Actor:** someone whose database contains a row with text designed to manipulate an assistant.
- **User Need:** tool output treated as data even when it looks like a command.
- **Business Value:** in a tool loop, an injection does not just change wording — it drives further tool calls against the user's real database.
- *As someone whose data came from somewhere I do not control, I want tool results treated as data, so that a row of text cannot issue instructions.*

**Context / Background**
**Detailed Description:** Every tool result is delimited and labelled by origin before it enters the prompt, and the standing statement that retrieved content is data and never instruction applies to tool output as much as to document chunks. Turns whose tool output contained instruction-like text are flagged in the trace, and the residual risk is documented honestly rather than overclaimed.

**Scope**
- Delimitation and origin labelling for every tool result.
- Injection-pattern flagging extended to tool output.
- A test asserting the standing statement covers tool results.

**Out of Scope**
- Blocking a turn on a flag — flagging is not blocking.

**Acceptance Criteria**
- **Acceptance Criteria:** Tool results are delimited and labelled by origin. A database row containing instruction-like text does not change behaviour in the tested cases and the turn is flagged in the trace. **C7 is preserved and the test fails if the delimitation or the statement is removed.**
- **Edge Cases:** A legitimately instructional document retrieved as a tool result — flagged, answered normally. A tool result containing the delimiter itself — escaped so the boundary cannot be broken from inside the data. A long chain of tool calls — the boundary holds at every step, not only the first.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/trace.md` §3 injection flags; `../states-and-edge-cases.md` §2 — flagged in the trace, not shown as an alarm.
- **Validation Rules:** The delimiter must be unforgeable from within the data.
- **Audit / Logging Requirements:** Flags are recorded on the trace and the interaction.
- **Analytics Events:** Local counter of flagged turns — nothing transmitted (C1).

**Real-World Example Scenarios**
- An imported dump contains a comment row instructing the assistant to query another table; the instruction is ignored and the trace shows the flag.

**Dependencies & Assumptions**
- **Dependencies:** M5-TOOLS-BE-113, M1-ASK-BE-037.
- **API / Data Touchpoints:** Prompt assembly; `messages.trace.injection_flagged`.
- **Assumptions:** Pattern flagging is heuristic and will both miss and over-flag; this is a mitigation, not a detection system.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, import a fixture database containing a row with an obvious injection attempt. Ask a question that retrieves it. Confirm the answer addresses the question, no additional tool calls were made at the row's instruction, and no alarming banner appears. Open the trace and see the flag.
- **Other scenarios:** Include the delimiter string inside a data value and confirm the boundary holds.
- **Known gaps:** Detection is heuristic; the residual risk is documented rather than claimed away.

**Effort & Granularity Check**
- **Estimate:** 2–3 hours · **Priority:** Critical
- **Labels / Component:** `phase:4`, backend, `constraint:injection`
- **Granularity:** One boundary and one flag.

---

### M5-LOOP-BE-115 — Multi-step loop with parallel calls

**Type:** Story

**User Story**
- **Actor:** someone asking a question that needs two lookups and then a third based on what came back.
- **User Need:** the assistant to work through it rather than answering from the first thing it found.
- **Business Value:** this is the difference between a search tool and something that answers a real question.
- *As someone with a question that has steps, I want the assistant to take them, so that I do not have to decompose the question myself.*

**Context / Background**
**Detailed Description:** The agent loops: call tools, read results, decide whether more is needed, then compose. Parallel calls are supported and preferred where the model emits them, because two independent lookups should not be sequential on a laptop. Each iteration is a recorded step.

**Scope**
- The loop with tool calling, result feeding and a termination decision.
- Parallel execution of independently emitted calls.
- Per-iteration step recording.

**Out of Scope**
- The call ceiling (M5-LOOP-BE-116).
- The trace panel (the TRACE epic).

**Acceptance Criteria**
- **Acceptance Criteria:** A question needing a document lookup and a database query is answered correctly in one turn. Independently emitted calls run in parallel and the trace shows overlapping durations. The loop terminates when the model has enough, not on a fixed count.
- **Edge Cases:** A tool error mid-loop — the model is told and can try another approach, and the trace records both. A loop that would not terminate — bounded by the ceiling in the next ticket. A model emitting the same call twice — deduplicated, with the duplication recorded.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/ask.md` §5 retrieving with named steps.
- **Validation Rules:** Every database call in every iteration goes through the full validation chain.
- **Audit / Logging Requirements:** Every iteration is a trace step; database steps also produce interaction detail.
- **Analytics Events:** Local counters of steps per turn — nothing transmitted (C1).

**Real-World Example Scenarios**
- "Which suppliers are we paying later than our contract allows?" retrieves contract terms from documents and payment dates from the database, then composes one answer citing both.

**Dependencies & Assumptions**
- **Dependencies:** M5-TOOLS-BE-114.
- **API / Data Touchpoints:** Tool registry; `messages.trace.steps`.
- **Assumptions:** Parallel execution is safe because no tool writes anything.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start with both a document corpus and an imported database. Ask a question that genuinely requires both. Watch the step labels name each lookup as it happens. Read the answer and confirm it cites both a document passage and a query result. Open the trace and confirm the sequence, and that two independent lookups overlapped in time.
- **Other scenarios:** Force a tool error mid-loop and confirm the turn recovers rather than failing.
- **Known gaps:** No ceiling yet, so a pathological question could loop for a long time.

**Effort & Granularity Check**
- **Estimate:** 4–6 hours · **Priority:** Critical
- **Labels / Component:** `phase:4`, backend
- **Granularity:** One loop with parallel dispatch. Upper bound.

---

### M5-LOOP-BE-116 — The eight-call ceiling, with what was gathered and a way to continue

**Type:** Story

**User Story**
- **Actor:** someone whose question sent the assistant round in circles.
- **User Need:** to be told it stopped early rather than being handed a confident partial result.
- **Business Value:** silently truncating reasoning and presenting the result as complete is worse than saying it stopped.
- *As someone whose question turned out to be harder than it looked, I want to be told the assistant stopped early, so that I know the answer is incomplete.*

**Context / Background**
**Detailed Description:** A hard ceiling of eight tool calls per turn. On reaching it, the turn returns what was gathered with an explicit note that it stopped early and why, and offers to continue as a new turn. The trace shows the steps taken and what it was about to do.

**Scope**
- Ceiling enforcement at eight calls.
- Composition of a stopped-early answer from what was gathered, with citations for what is grounded.
- A Continue action that starts a new turn carrying the accumulated context.
- Trace recording of the stop and the pending intent.

**Out of Scope**
- Raising the ceiling — it is fixed in v1.

**Acceptance Criteria**
- **Acceptance Criteria:** A turn reaching eight calls stops, returns what it gathered with citations, and states that it stopped early and why. Continue starts a new turn that makes progress rather than repeating. The trace shows what it was about to do. Nothing is presented as complete when it is not.
- **Edge Cases:** The ceiling reached with nothing useful gathered — the turn says so rather than composing from nothing, which is closer to abstention. Continue reaching the ceiling again — the same treatment, without an infinite chain, and after a second stop the user is told the question may need narrowing. A parallel batch that would cross the ceiling — the batch is truncated at eight and the truncation is recorded.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/ask.md` §5 tool ceiling hit with Continue; `../ux/trace.md` §5 tool ceiling; `../states-and-edge-cases.md` §2.
- **Validation Rules:** A stopped-early answer must never omit the note.
- **Audit / Logging Requirements:** Tool-ceiling stops are recorded in the interaction log.
- **Analytics Events:** Local counter of ceiling stops — nothing transmitted (C1).

**Real-World Example Scenarios**
- A vague question about "everything about this supplier" stops after eight steps, returns the four things it found with citations, and offers to continue.

**Dependencies & Assumptions**
- **Dependencies:** M5-LOOP-BE-115.
- **API / Data Touchpoints:** `messages.trace.stopped_early`.
- **Assumptions:** Eight is the right ceiling for a local model on a laptop; changing it is a recorded decision.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, ask a deliberately broad question over a corpus and a database. Watch the steps accumulate and confirm the turn stops at eight with what was gathered plus an explicit note. Press Continue and confirm the next turn makes progress rather than starting over. Open the trace and read what it was about to do when it stopped.
- **Other scenarios:** Ask a question that hits the ceiling with nothing useful and confirm the response is honest rather than composed from nothing.
- **Known gaps:** The ceiling is not adjustable in v1.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** Critical
- **Labels / Component:** `phase:4`, backend
- **Granularity:** One ceiling, one composition path, one continue action.

---

### M5-LOOP-BE-117 — Capture the step sequence into the trace

**Type:** Task

**User Story**
- **Actor:** someone who wants to know where eight seconds went.
- **User Need:** each step recorded with what it did, what came back and how long it took.
- **Business Value:** on a local model the user is waiting, and knowing where the time went is the difference between "this is slow" and "the model is slow, retrieval was instant".
- *As someone waiting on my own laptop, I want the timings, so that I know what to blame and whether to change anything.*

**Context / Background**
**Detailed Description:** Populate the trace with its defined shape: an ordered step sequence with kind, duration and per-kind detail — retrieval with query, threshold and hits with scores; schema lookup with the source; SQL with the generated query, the validation outcome, the rejection reason, the injected limit and the row count; composition with the claim count. Plus the backend and model, whether it stopped early, and whether injection was flagged. Traces rotate; citations and fact usage do not.

**Scope**
- Trace population for every step kind.
- Backend, model, stopped-early and injection-flag fields.
- Trimming of `messages.trace` in step with the rotating ring buffer.

**Out of Scope**
- Rendering (M5-TRACE-FE-119).

**Acceptance Criteria**
- **Acceptance Criteria:** Every turn produces a trace matching the defined shape with durations for each step. Scores and the threshold are stored as measured. A rejected query appears with its reason. When the ring buffer rotates, the trace is trimmed while the answer's citations remain resolvable.
- **Edge Cases:** A turn with a single step — a valid one-step trace, not an empty one. A turn that failed mid-answer — steps up to the failure plus the error. A trace larger than the per-turn bound — truncated with the truncation stated inside the trace.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/trace.md` §2 and §3.
- **Validation Rules:** Scores and thresholds are stored, never recomputed.
- **Audit / Logging Requirements:** Traces fail open — a trace write failure never fails an action.
- **Analytics Events:** Local counters only — nothing transmitted (C1).

**Real-World Example Scenarios**
- An old abstention still explains itself with the numbers that produced it, months after the threshold changed.

**Dependencies & Assumptions**
- **Dependencies:** M5-LOOP-BE-116, M0-DATA-OBS-015.
- **API / Data Touchpoints:** `messages.trace`; the trace ring buffer.
- **Assumptions:** The defined trace shape covers every step kind through M6; voice adds a step kind and extends it.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, ask a multi-step question, then inspect the stored trace through the log. Confirm each step with its duration, the retrieval scores and threshold, and the query with its validation outcome. Force the ring buffer to rotate and confirm the trace is gone while the answer's citations still open the right pages.
- **Other scenarios:** Make the trace directory unwritable and confirm answers still work.
- **Known gaps:** No rendering yet.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** Critical
- **Labels / Component:** `phase:4`, backend, observability
- **Granularity:** One structure with five step kinds.

---

### M5-LOOP-FE-118 — Step labels for multi-step turns

**Type:** Story

**User Story**
- **Actor:** someone watching a twenty-second answer.
- **User Need:** labels that keep changing so progress stays visible.
- **Business Value:** the user must always be able to tell working from hung, and that distinction decides whether they wait or give up.
- *As someone waiting on a slow local model, I want to see the steps as they happen, so that I know it is working.*

**Context / Background**
**Detailed Description:** Extend the retrieval step labels of M1 to a multi-step turn: each tool call produces a named label as it starts, and parallel calls are shown as concurrent rather than as a queue. Labels keep updating past the twenty-second mark so progress remains visible.

**Scope**
- Streamed labels per step, named for the real operation.
- Concurrent rendering for parallel calls.
- Continued updating past the performance budget.

**Out of Scope**
- The trace panel.

**Acceptance Criteria**
- **Acceptance Criteria:** Each tool call produces a label as it starts, naming the real operation and the source where relevant. Parallel calls render concurrently. Labels keep updating on a long turn. The first label appears within the stated budget of submitting.
- **Edge Cases:** A very fast turn — labels appear and clear without flicker. A turn that stops early — the labels end with the stop rather than hanging. A tool error — the label reflects the retry or the change of approach rather than freezing.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/ask.md` §5 retrieving and §7 performance budgets.
- **Validation Rules:** A label must name the real step, never a generic placeholder.
- **Audit / Logging Requirements:** None beyond the trace.
- **Analytics Events:** Local counter only — nothing transmitted (C1).

**Real-World Example Scenarios**
- The user sees "searching your files", then "querying sales-2024", then "reading 2 documents", and knows exactly where the wait is going.

**Dependencies & Assumptions**
- **Dependencies:** M5-LOOP-BE-117, M1-ASK-FE-039.
- **API / Data Touchpoints:** The streaming endpoint's step events.
- **Assumptions:** Step events arrive fast enough that labels are not misleadingly behind.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, ask a question needing several steps and watch the labels. Confirm the first appears almost immediately, that they name real sources, and that two parallel lookups appear at once rather than in sequence. Ask a broad question that runs past twenty seconds and confirm labels keep changing.
- **Other scenarios:** Ask a trivial question and confirm labels do not flicker.
- **Known gaps:** Labels are transient and not recorded separately from the trace.

**Effort & Granularity Check**
- **Estimate:** 2–3 hours · **Priority:** High
- **Labels / Component:** `phase:4`, frontend
- **Granularity:** One label stream extension.

---

### M5-TRACE-FE-119 — Trace panel: a readable narrative over expandable raw detail

**Type:** Story

**User Story**
- **Actor:** two people at once — someone opening this out of curiosity, and someone debugging why a question keeps missing.
- **User Need:** a readable sequence at the top, raw detail underneath.
- **Business Value:** a trace that only serves the debugger is useless to the first audience, and one that only serves curiosity is useless when something is actually wrong.
- *As someone whose answer looked wrong, I want to see what happened in plain language, so that I can understand it without knowing what an embedding is.*

**Context / Background**
**Detailed Description:** A panel over Ask, not a page, opened from the toggle under any answer. A numbered vertical sequence of steps in the order they happened, each showing what it did, what came back and how long it took, with raw detail expandable underneath. Layered depth, not two modes. Timings always visible.

**Scope**
- Panel over Ask with the numbered step sequence.
- Per-step summary line and duration.
- Expandable raw detail per step.
- Open and close from the answer toggle.

**Out of Scope**
- Contents detail (M5-TRACE-FE-120) and interactions (M5-TRACE-FE-121).

**Acceptance Criteria**
- **Acceptance Criteria:** The toggle under an answer opens the panel. Steps are numbered in the order they happened with a plain-language summary and a duration. Raw detail expands underneath rather than in a separate mode. Closing returns to the conversation unchanged.
- **Edge Cases:** A turn with fifteen steps — the panel scrolls and stays readable. A step with no detail worth expanding — no expander rather than an empty one. Opening the trace while an answer is still streaming — shows steps so far and updates.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/trace.md` §1 and §2.
- **Validation Rules:** Timings are always visible, never behind an expander.
- **Audit / Logging Requirements:** None for viewing.
- **Analytics Events:** Local counter of trace opens — nothing transmitted (C1).

**Real-World Example Scenarios**
- A user opens the trace once, understands that retrieval was instant and the model was slow, and stops assuming the product is broken.

**Dependencies & Assumptions**
- **Dependencies:** M5-LOOP-BE-117, M1-ASK-FE-039.
- **API / Data Touchpoints:** `messages.trace`.
- **Assumptions:** A panel over Ask is right rather than a route, because the user is investigating one answer and must not lose their place.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, ask a multi-step question, and open the trace from the toggle under the answer. Read the numbered steps and confirm each is understandable without technical knowledge and shows a duration. Expand one and read the raw detail. Close it and confirm you are back at the same answer.
- **Other scenarios:** Open the trace mid-stream and confirm it updates.
- **Known gaps:** Contents are minimal until the next ticket. No threshold control yet.

**Effort & Granularity Check**
- **Estimate:** 4–6 hours · **Priority:** High
- **Labels / Component:** `phase:4`, frontend
- **Granularity:** One panel with one layered pattern. Upper bound.

---

### M5-TRACE-FE-120 — Trace contents: scores, threshold, memory, SQL, limits, flags, ceiling, backend

**Type:** Story

**User Story**
- **Actor:** someone trying to understand an abstention.
- **User Need:** the scores and the threshold together, because either alone is meaningless.
- **Business Value:** the abstention trace is the most useful trace there is, and its value is showing the near-miss.
- *As someone who was told nothing answered my question, I want to see how close it came, so that I know whether to add a file or rephrase.*

**Context / Background**
**Detailed Description:** Render everything the trace must contain: retrieved passages with scores, the threshold in force, memory facts used, the generated query with whether validation accepted it — **including rejected SQL, shown, because it is the signal that generation has degraded** — the injected limit, injection flags, the tool-ceiling stop, and the backend and model.

**Scope**
- Rendering for each required item with the type and colour roles from the design system.
- Rejected SQL rendered with its reason.
- Injection flags rendered as information, not as an alarm.
- Backend and model shown per turn.

**Out of Scope**
- Score presentation refinement, which is an open question in `../ux/trace.md` §6 — raw scores with the threshold beside them is the starting point.

**Acceptance Criteria**
- **Acceptance Criteria:** An abstention trace shows every candidate with its score and the threshold, making the near-miss visible. A database turn shows the query, the validation outcome and the injected limit. A flagged turn shows the flag without alarming language. The backend and model are named.
- **Edge Cases:** A turn with no retrieval — the retrieval step is absent rather than shown empty. A rejected query with a long reason — rendered fully rather than truncated, since it is the diagnostic. A turn using memory heavily — facts listed with their origin markers.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/trace.md` §3 in full; `../ux/design-system.md` §3 mono for machinery.
- **Validation Rules:** Scores are always shown with the threshold beside them.
- **Audit / Logging Requirements:** None for viewing.
- **Analytics Events:** None.

**Real-World Example Scenarios**
- An abstention trace shows the right passage at 0.61 under a 0.65 threshold, which explains an abstention that otherwise looks broken.

**Dependencies & Assumptions**
- **Dependencies:** M5-TRACE-FE-119, M4-SQL-OBS-108, M3-APPLY-BE-079.
- **API / Data Touchpoints:** `messages.trace` in full.
- **Assumptions:** Raw cosine scores are meaningless to most users, and a star rating would be a lie about precision; raw with the threshold beside it is the least wrong option and is flagged as not obviously right.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, ask a question that abstains near the threshold. Open the trace and read the scores with the threshold — confirm the near-miss is legible. Ask a database question that is rejected by validation and confirm the trace shows the query and the rejection reason. Ask a question that uses a memory fact and confirm the fact is listed with its origin.
- **Other scenarios:** Trigger the injection flag and confirm it renders as information.
- **Known gaps:** Score presentation is raw and acknowledged as unresolved.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** High
- **Labels / Component:** `phase:4`, frontend, `constraint:grounding`
- **Granularity:** Eight content kinds in one panel.

---

### M5-TRACE-FE-121 — Trace interactions: expand, click through, copy

**Type:** Story

**User Story**
- **Actor:** someone who has found the problem in the trace.
- **User Need:** to act on it without leaving.
- **Business Value:** the trace is where a wrong belief is discovered; making the fix reachable from there is the difference between noticing and correcting.
- *As someone who has just spotted a wrong fact in the trace, I want to fix it right there, so that finding it and fixing it are one action.*

**Context / Background**
**Detailed Description:** Expanding a step shows full text, full query and full scores. Clicking a passage opens the source viewer at that position. Clicking a memory fact opens the same popover as in an answer, with correct and delete. Copy trace produces plain text suitable for a bug report.

**Scope**
- Expand, click-passage, click-fact and copy-trace.
- Copy output as plain text with no styling.
- Returning to the trace after visiting the source viewer.

**Out of Scope**
- Threshold adjustment (M5-TRACE-FE-122).

**Acceptance Criteria**
- **Acceptance Criteria:** Expanding shows full detail. Clicking a passage opens the viewer at that position with a way back. Clicking a fact opens the correct-and-delete popover. Copy produces readable plain text containing the steps, scores, threshold and query.
- **Edge Cases:** A passage from a deleted document — renders as deleted, not clickable, consistent with the answer's cards. Copying a very long trace — truncated with the truncation stated in the copied text. A fact deleted since the turn — the popover says so rather than offering to correct something that no longer exists.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/trace.md` §4.
- **Validation Rules:** Copied text must not contain credentials; generated SQL never carries them.
- **Audit / Logging Requirements:** A correction from here is a decisions record like any other.
- **Analytics Events:** Local counter of trace copies — nothing transmitted (C1).

**Real-World Example Scenarios**
- A user copies a trace into an issue and the maintainer can see the scores, the threshold and the query without asking for anything else.

**Dependencies & Assumptions**
- **Dependencies:** M5-TRACE-FE-120, M3-CORRECT-FE-081, M1-VIEW-FE-048.
- **API / Data Touchpoints:** Source viewer routes; `memory`.
- **Assumptions:** Returning from the viewer restores the trace panel rather than closing it.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, ask a question that uses both a document and a memory fact. Open the trace, expand the retrieval step and read the full passage text. Click a passage and confirm the viewer opens at that position, then return and confirm the trace is still open. Click the memory fact, correct it, and confirm the correction takes effect. Copy the trace and paste it into a text editor to confirm it is readable.
- **Other scenarios:** Delete the cited document and reopen the trace — the passage renders as deleted.
- **Known gaps:** No threshold control yet.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** Medium
- **Labels / Component:** `phase:4`, frontend
- **Granularity:** Four interactions on an existing panel.

---

### M5-TRACE-FE-122 — Threshold adjustment from an abstention trace, with the consequence stated

**Type:** Story

**User Story**
- **Actor:** someone looking at a near-miss and wondering whether to loosen the threshold.
- **User Need:** the control, with the honest consequence attached.
- **Business Value:** lowering the threshold is the one change that makes the abstention number look better while breaking the product's central claim; forbidding it is wrong because it is the user's product, and making it frictionless is how the product quietly stops being trustworthy.
- *As someone whose question nearly matched, I want to be able to loosen the threshold and to be told exactly what that costs, so that it is a decision rather than a slider.*

**Context / Background**
**Detailed Description:** From an abstention trace showing a near-miss, offer the threshold control with the consequence stated in plain terms — that lowering it makes Askwell answer from weaker matches, meaning more answers and more of them wrong. The change is recorded in the decisions log. Not hidden, not forbidden, never frictionless.

**Scope**
- The control offered only from an abstention trace showing a near-miss.
- Consequence copy naming the actual scores involved.
- Decisions record on change; the same control also reachable in settings with the same warning.

**Out of Scope**
- Any automatic threshold tuning — there is none, ever.

**Acceptance Criteria**
- **Acceptance Criteria:** The control appears only on an abstention trace with a near-miss. The consequence is stated with the real numbers. Changing it writes a decisions record. The same warning appears wherever the threshold is reachable. There is no frictionless slider anywhere.
- **Edge Cases:** An abstention with no near-miss — no control, because loosening would not have helped and offering it would be misleading. A user lowering it repeatedly — each change is recorded, and the guard test in the eval suite catches a default lowered without a decision. Raising the threshold — permitted with the opposite consequence stated.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/trace.md` §4 adjusting the threshold; `../ux/settings.md` §2 with the same warning.
- **Validation Rules:** The threshold may never be adjusted automatically or as a side effect of anything else.
- **Audit / Logging Requirements:** Every threshold change is a decisions record with the old and new values.
- **Analytics Events:** Local counter only — nothing transmitted (C1).

**Real-World Example Scenarios**
- A user reads that the closest passage scored 0.61 against a 0.65 threshold, understands the trade, and decides to add the missing document instead.

**Dependencies & Assumptions**
- **Dependencies:** M5-TRACE-FE-120, M2-ABSTAIN-OBS-056.
- **API / Data Touchpoints:** `settings`; `audit_decisions`.
- **Assumptions:** Past turns keep their recorded threshold, so old traces stay truthful after a change.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, ask a question that abstains with a near-miss. Open the trace and confirm the control appears with the consequence stated using the real scores. Lower the threshold and re-ask the question — confirm it now answers. Open an older abstention trace and confirm it still shows the threshold that was in force at the time. Check the decisions log for the change.
- **Other scenarios:** Ask a question that abstains with no near-miss and confirm no control is offered.
- **Known gaps:** There is no guidance on what a good threshold is, deliberately — the eval suite is the instrument, not intuition.

**Effort & Granularity Check**
- **Estimate:** 2–3 hours · **Priority:** High
- **Labels / Component:** `phase:4`, frontend, `constraint:grounding`
- **Granularity:** One control with one consequence.

---

### M5-TRACE-FE-123 — Trace states, including the rotated-away trace

**Type:** Story

**User Story**
- **Actor:** someone opening the trace on an answer from four months ago.
- **User Need:** an honest explanation that the debugging detail has rotated while the important records survive.
- **Business Value:** traces are a capped ring buffer by design, and a broken panel would look like data loss when it is deliberate.
- *As someone revisiting an old answer, I want to be told the detailed trace has been cleared and that the sources are still there, so that I do not think something is broken.*

**Context / Background**
**Detailed Description:** Build the remaining trace states: normal, abstention, partial, tool ceiling, failed mid-answer, online backend, and trace unavailable after rotation. The unavailable state states plainly that the detailed trace has been cleared and that the answer and its sources are still in the log — the important records survive and only the debugging detail rotates.

**Scope**
- All seven states with their copy.
- The unavailable state distinguishing rotation from an error.
- The online-backend state marked with what was sent, ready for M8.

**Out of Scope**
- The online backend itself (M8).

**Acceptance Criteria**
- **Acceptance Criteria:** Each state renders distinctly. The unavailable state states that the trace was cleared and that the answer and its sources remain, and the answer's citations still open. A failed turn shows the steps up to the failure and then the error.
- **Edge Cases:** A partially rotated trace — treated as unavailable rather than shown incomplete and misleading. An answer whose citations were also lost — impossible by design, since citations are a real table and do not rotate, and a test asserts this. A turn with an online backend before M8 — the state exists and is unreachable.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/trace.md` §5 in full.
- **Validation Rules:** Rotation must never break a citation.
- **Audit / Logging Requirements:** None for viewing.
- **Analytics Events:** None.

**Real-World Example Scenarios**
- A user opens a six-month-old answer's trace, reads that the detail was cleared, and clicks the still-working citation instead.

**Dependencies & Assumptions**
- **Dependencies:** M5-TRACE-FE-122, M2-ABSTAIN-FE-055, M5-LOOP-BE-116.
- **API / Data Touchpoints:** Trace ring buffer; `citations`.
- **Assumptions:** The trace retention default is tied to the log budget, which is an open item resolved with the budget work in M7.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, produce an answer of each kind — normal, abstention, partial, ceiling — and open each trace to confirm the state renders correctly. Then force the ring buffer to rotate past the first answer, open its trace, and read the unavailable message. Click that answer's citation and confirm it still opens the right page.
- **Other scenarios:** Interrupt a turn to produce a failed trace and confirm the steps up to the failure are shown.
- **Known gaps:** The online-backend state is unreachable until M8. Trace retention default is settled with the log budget in M7.

**Effort & Granularity Check**
- **Estimate:** 2–3 hours · **Priority:** Medium
- **Labels / Component:** `phase:4`, frontend
- **Granularity:** Seven states.

---

### M5-EVAL-TEST-124 — Tool selection eval suite, including parallel calls

**Type:** Task

**User Story**
- **Actor:** the maintainer accepting the agent loop.
- **User Need:** tool selection measured, including whether parallel calls are used where they should be.
- **Business Value:** a single malformed tool call fails an entire agent turn and errors compound, which is exactly why worst-case matters most in this category.
- *As someone accepting a multi-step loop, I want tool selection measured with the worst case, so that a model that fails one turn in three is not shipped.*

**Context / Background**
**Detailed Description:** Twenty-five tasks with a 0.85 bar, covering choosing the right tool, choosing more than one where needed, emitting independent calls in parallel, recovering from a tool error, and stopping when enough has been gathered. Three runs with worst-case reported.

**Scope**
- Twenty-five tasks across the named behaviours.
- Scoring on tool choice and on the final answer, separately, so a right answer by the wrong route is visible.
- Integration into the gate.

**Out of Scope**
- Latency measurement, which belongs to the performance work.

**Acceptance Criteria**
- **Acceptance Criteria:** The suite reports against the 0.85 bar with worst-case beside mean. Tool choice and final answer are scored separately. Removing parallel dispatch fails the parallel tasks specifically.
- **Edge Cases:** A task with two acceptable tool routes — both scored correct. A task where the correct behaviour is to use no tool at all, such as a question about the current date — included. A task designed to tempt an unnecessary database call.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** None.
- **Validation Rules:** Do not weaken these tasks to make a change pass.
- **Audit / Logging Requirements:** Results recorded with model and prompt version.
- **Analytics Events:** None.

**Real-World Example Scenarios**
- A model upgrade improves mean tool selection and worsens the worst case, which the suite makes visible before it becomes a default.

**Dependencies & Assumptions**
- **Dependencies:** M5-LOOP-BE-116, M4-EVAL-TEST-112.
- **API / Data Touchpoints:** The loop; the tool registry.
- **Assumptions:** Tool choice is inspectable from the trace, so scoring does not need special instrumentation.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, index the fixture corpus and import the fixture database, then run the tool suite. Read the two scores per task and the worst case. Disable parallel dispatch and re-run — the parallel tasks must fail, proving the suite measures it.
- **Other scenarios:** Introduce a tool error deliberately and confirm the recovery tasks still pass.
- **Known gaps:** Twenty-five tasks over one fixture pair. English only. Latency is not scored here.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** Critical
- **Labels / Component:** `phase:4`, test, `eval`
- **Granularity:** Twenty-five tasks in the existing harness.
