# M8 — The paid upgrade

**Goal:** Optional online AI, chosen per conversation, paid by credit, with the user told exactly what will be sent before anything is sent.

**Phase:** 7 (`../build-plan.md`) · **Depends on:** M6.5 · **Tickets:** 8 · **Estimated:** 17–25 hours of unblocked work, plus an unestimated remainder behind two open decisions

**Exit condition:** Cannot be defined until the two open decisions are answered. The unblocked portion ends with a conversation able to route to exactly one authorised destination, with the disclosure shown first, the local log unchanged, and a fallback to local mode that never blocks the user.

> **This milestone is beyond the story milestones in `../stories/README.md`, which end at M7.** It is numbered M8 here because the roadmap has a seventh stage and the tickets have to live somewhere. It is also the revenue line, and everything before it is free.

## Blocked work — do not start

Two decisions in the business case's open list gate most of this milestone.

| Decision | What it blocks | Tickets |
| -------- | -------------- | ------- |
| **Credit pricing** — rate, minimum purchase, margin over provider cost | The entire purchase and balance path, and therefore the revenue model | M8-CREDIT-BLOCKED-173, M8-CREDIT-BLOCKED-174 |
| **What online mode transmits** — the precise payload for billing and limits | Online-mode logging, and the pre-send disclosure's exact wording | M8-ONLINE-OBS-172, and the disclosure half of M8-ONLINE-FE-171 |

The constraint already recorded for the second is that local logging continues in full regardless, that online mode adds a record and never replaces one, and that what leaves should be the minimum for billing and limits — token counts, timestamps, model — never question content, answers or retrieved material. **That is a constraint, not the decision.** The precise shape still has to be written down before this work starts.

## Included epics

| Epic | Code | Covers |
| ---- | ---- | ------ |
| Online routing | `ONLINE` | Per-conversation authorisation, the provider abstraction, the marker and disclosure, logging |
| Credits | `CREDIT` | Purchase, balance, limits, exhaustion |

---

### M8-ONLINE-SEC-169 — Per-conversation egress authorisation for exactly one destination

**Type:** Story

**User Story**
- **Actor:** someone turning on online AI for one hard question.
- **User Need:** the authorisation scoped to that conversation and that destination, and nothing else.
- **Business Value:** online mode is a per-conversation choice the user makes knowingly, never a default and never a drift.
- *As someone enabling online AI for one question, I want the permission to end with that conversation, so that I cannot accidentally leave a door open.*

**Context / Background**
**Detailed Description:** Enabling online AI for a conversation authorises exactly one destination for that conversation's traffic only. The egress proxy grants it, scoped and time-bound, and revokes it when the conversation ends or the user turns it off. The sandbox has no route to the proxy at all and is unaffected. This is the mechanism the proxy was built for in M0.

**Scope**
- Scoped, time-bound authorisation of one destination per conversation.
- Revocation on conversation end, on disable, and on restart.
- Counting permitted requests separately from refusals so the local-mode figure stays meaningful.

**Out of Scope**
- The provider itself (M8-ONLINE-BE-170) and the disclosure (M8-ONLINE-FE-171).

**Acceptance Criteria**
- **Acceptance Criteria:** Enabling online AI for a conversation permits exactly one destination for that conversation. No other conversation gains access. Disabling or ending the conversation revokes it immediately. A restart does not silently restore an authorisation. Permitted requests are counted separately and are attributable to the conversation. **C1 is preserved: default-deny remains the resting state and the authorisation is explicit, scoped and revocable.**
- **Edge Cases:** Two conversations, one online and one local — the local one has no route out, verified. An in-flight request when the conversation is disabled — completed or cancelled, with either behaviour stated rather than ambiguous. An authorisation surviving a crash — revoked on restart, since a surviving authorisation nobody asked for is exactly the drift the constraint forbids.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/settings.md` §3 and §4; `../states-and-edge-cases.md` §1 online AI enabled for a conversation.
- **Validation Rules:** Authorisation is never global and never persists beyond the conversation.
- **Audit / Logging Requirements:** Enabling and revoking are decisions records naming the conversation and the destination.
- **Analytics Events:** Local counters only — the permitted count is shown in settings alongside the local-mode zero.

**Real-World Example Scenarios**
- A user enables online AI for one difficult question and, an hour later, sees in settings that exactly three outbound requests were permitted, attributable to that conversation.

**Dependencies & Assumptions**
- **Dependencies:** M0-STACK-SEC-010, M0-STACK-SEC-011, M7-SET-FE-147.
- **API / Data Touchpoints:** Proxy authorisation; `conversations.ai_backend`.
- **Assumptions:** The proxy's authorisation mechanism, designed in M0, supports per-conversation scoping without redesign.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, open a conversation and enable online AI for it. From the proxy's counters, confirm exactly one destination is permitted. Open a second conversation in local mode and confirm it cannot reach anything. Disable online AI on the first and confirm the permission is revoked immediately. Restart Askwell and confirm no permission was restored.
- **Other scenarios:** Kill the stack mid-conversation with an authorisation active and confirm it does not survive the restart.
- **Known gaps:** Nothing is actually sent yet; there is no provider.

**Effort & Granularity Check**
- **Estimate:** 4–6 hours · **Priority:** Critical
- **Labels / Component:** `phase:7`, security, `constraint:local-first`
- **Granularity:** One authorisation model. Upper bound.

---

### M8-ONLINE-BE-170 — Provider abstraction behind the inference client

**Type:** Story

**User Story**
- **Actor:** someone asking a hard question with online AI enabled.
- **User Need:** the same product behaviour, with a different model behind it.
- **Business Value:** the credit service is the business; the client must not care which backend answered.
- *As someone who turned on the bigger model for one question, I want everything else to work identically, so that online is an upgrade rather than a different product.*

**Context / Background**
**Detailed Description:** Extend the inference client with an online backend routed through the authorised destination. Retrieval, citations, abstention, tools, the trace and the audit log all behave identically; only generation changes. **Askwell never asks the user for a third-party API key and never holds one** — credits are bought from the service, which holds the provider relationship.

**Scope**
- Online backend behind the existing client interface.
- Failure handling: unreachable, refused, rate-limited, each distinguishable and each falling back to local rather than blocking.
- The backend and model recorded on every turn.

**Out of Scope**
- Credits, balance and limits — blocked.
- Any third-party key entry — forbidden.

**Acceptance Criteria**
- **Acceptance Criteria:** With online enabled, generation uses the online backend while retrieval, citations, abstention and tools behave identically. A failure falls back to local, says so, and never blocks the user. The backend and model are recorded on every turn. There is no field anywhere for a third-party key.
- **Edge Cases:** The online backend unreachable mid-answer — the turn falls back and says so rather than failing. A response that violates the citation requirement — treated exactly as a local one would be, since the constraints are not relaxed for the paid path. Online enabled while the machine is offline — the failure says the network is unavailable, which is one of the few places an offline statement is correct, because the user asked for something that needs it.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/ask.md` §5 online mode; `../states-and-edge-cases.md` §1.
- **Validation Rules:** Every constraint applies identically to the online path. No third-party key is ever requested.
- **Audit / Logging Requirements:** Backend and model on every interaction record; local logging continues in full.
- **Analytics Events:** Local counters only — nothing transmitted beyond what the blocked decision authorises.

**Real-World Example Scenarios**
- A user enables online AI for a complex multi-document question and gets a better answer with the same citations and the same abstention behaviour.

**Dependencies & Assumptions**
- **Dependencies:** M8-ONLINE-SEC-169, M0-MODEL-BE-019.
- **API / Data Touchpoints:** Inference client; `conversations.ai_backend`; `messages.trace.backend`.
- **Assumptions:** The provider exposes an interface the existing client abstraction can accommodate; if not, the abstraction is the seam that absorbs the difference.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start against a test destination. Enable online AI for a conversation and ask a question about an indexed document. Confirm the answer arrives with source cards exactly as in local mode, and that the trace names the online backend and model. Ask an uncovered question and confirm it still abstains. Disconnect the network and ask again — confirm the fallback to local with a clear statement rather than a failure.
- **Other scenarios:** Search the interface for any third-party key field — there must be none.
- **Known gaps:** No credits, no balance, no limits — blocked. What is transmitted for billing is undecided.

**Effort & Granularity Check**
- **Estimate:** 4–6 hours · **Priority:** High
- **Labels / Component:** `phase:7`, backend, `constraint:local-first`
- **Granularity:** One backend behind an existing interface. Upper bound.

---

### M8-ONLINE-FE-171 — Persistent conversation marker, and the pre-send disclosure **[partly blocked]**

**Type:** Story

**User Story**
- **Actor:** someone who enabled online AI last week and has forgotten.
- **User Need:** a marker they cannot miss, and a statement of what will be sent before the first send.
- **Business Value:** the user must never discover after the fact that content left the machine.
- *As someone who enabled this once, I want the conversation to say so permanently, so that I never send something confidential by accident.*

**Context / Background**
**Detailed Description:** A persistent marker on any conversation using online AI, and a statement of exactly what will be sent **before** the first send — not after, not on purchase. **The exact wording of that statement is blocked** on the decision about what online mode transmits; the marker, the placement, the timing and the requirement that it precede the first send are not blocked and can be built now with the payload text pending.

**Scope**
- Persistent, unmissable marker on an online conversation.
- Pre-send disclosure shown before the first send, with a confirmation.
- Per-conversation control — there is no global setting to forget about.
- Placeholder payload text that refuses to send until the decision is recorded.

**Out of Scope**
- The exact payload wording — **blocked**.
- Purchase and balance — blocked.

**Acceptance Criteria**
- **Acceptance Criteria:** An online conversation carries a persistent marker visible without scrolling. The disclosure appears before the first send and requires confirmation. There is no global online setting. **Until the payload decision is recorded, the disclosure states that the payload is not yet defined and the send is refused** — the product must never send something it cannot describe.
- **Edge Cases:** Switching a conversation from local to online mid-thread — the disclosure appears again before the first online send, and earlier local turns are marked as local. A conversation resumed weeks later — the marker is still there, and the disclosure is not repeated because it was already confirmed for that conversation. Online enabled but a question that abstains — nothing is sent beyond what the disclosure covered, and the trace shows it.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/ask.md` §5 online mode; `../ux/settings.md` §3; `../states-and-edge-cases.md` §1.
- **Validation Rules:** No send may occur before the disclosure is shown and confirmed. No global toggle.
- **Audit / Logging Requirements:** The confirmation is a decisions record naming the conversation.
- **Analytics Events:** Local only.

**Real-World Example Scenarios**
- A user opens an old conversation, sees the online marker, and switches to a new local one before asking about a confidential matter.

**Dependencies & Assumptions**
- **Dependencies:** M8-ONLINE-BE-170. **Payload wording blocked on the open decision about what online mode transmits.**
- **API / Data Touchpoints:** `conversations.ai_backend`.
- **Assumptions:** None about the payload. The refusal-until-defined behaviour is the deliberate safeguard against shipping a vague disclosure.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, open a conversation and enable online AI. Confirm the disclosure appears before anything is sent and that, while the payload decision is open, it says so and refuses to send. Confirm the marker is visible on the conversation and remains after navigating away and back. Confirm there is no global online setting in settings.
- **Other scenarios:** Switch a local conversation to online mid-thread and confirm the disclosure appears again.
- **Known gaps:** The payload wording is blocked, and sending is deliberately refused until it is decided.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours for the unblocked portion · **Priority:** Critical
- **Labels / Component:** `phase:7`, frontend, `blocked:decision`, `constraint:local-first`
- **Granularity:** Marker and timing now; wording when unblocked.

---

### M8-ONLINE-OBS-172 — Online-mode logging **[BLOCKED]**

**Type:** Spike

**User Story**
- **Actor:** someone who used online AI and wants to know what was recorded and where.
- **User Need:** the local record complete, and the transmitted record minimal and knowable.
- **Business Value:** this is the one place the local-only assumption does not hold, and it is flagged deliberately rather than left to be discovered.
- *As someone who paid for one online answer, I want to know exactly what left my machine, so that the exception is bounded rather than open-ended.*

**Context / Background**
**Detailed Description:** **Blocked on the open decision about what online mode transmits.** The constraints are already recorded: local logging continues in full regardless; online mode adds a record and never replaces one; what leaves should be the minimum for billing and limits — token counts, timestamps, model — and never question content, answers or retrieved material. **The precise shape must be written down before this work starts. Do not pick a default.**

**Scope**
- Nothing while blocked.
- When unblocked: the transmitted record's exact fields, the local record of what was transmitted, and a user-visible view of both.

**Out of Scope**
- Any implementation while blocked. Any transmission of content, under any circumstance.

**Acceptance Criteria**
- **Acceptance Criteria:** Cannot be accepted while blocked. When unblocked: the local interaction record is complete and unchanged in shape; the transmitted record contains only the decided fields; the user can see exactly what was transmitted for each online turn; and a network capture confirms nothing beyond it left the machine.
- **Edge Cases:** Deferred with the decision, except one that is already fixed: a failure to transmit a billing record must never fail the user's answer, because the local record is the one that carries the guarantee.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/settings.md` §3 and §4.
- **Validation Rules:** Never question content, never answers, never retrieved material.
- **Audit / Logging Requirements:** The transmitted record is itself recorded locally.
- **Analytics Events:** This is billing, not analytics, and the distinction must be maintained in both the design and the wording.

**Real-World Example Scenarios**
- Deferred with the decision.

**Dependencies & Assumptions**
- **Dependencies:** **Blocked on the open decision about what online mode transmits.** Also M8-ONLINE-BE-170.
- **API / Data Touchpoints:** `audit_interactions`; the credit service.
- **Assumptions:** None may be made.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Not applicable while blocked. When unblocked, it must include enabling online AI, asking a question, reading the local record of what was transmitted, and confirming with an independent network capture that nothing beyond it was sent.
- **Known gaps:** The entire transmitted-record design.

**Effort & Granularity Check**
- **Estimate:** Not estimable while blocked. A spike to draft the payload and its rationale is 2–3 hours. · **Priority:** Critical
- **Labels / Component:** `phase:7`, `blocked:decision`, observability, `constraint:local-first`, `constraint:audit`
- **Granularity:** Blocked. Do not start.

---

### M8-CREDIT-BLOCKED-173 — Credit purchase **[BLOCKED]**

**Type:** Spike

**User Story**
- **Actor:** someone who wants to buy a small amount of online AI.
- **User Need:** to buy credits without a subscription and without handing over an API key.
- **Business Value:** this is the entire revenue line, and everything before it is free.
- *As someone who occasionally needs a bigger model, I want to buy a small amount of credit, so that I pay for what I use rather than subscribing.*

**Context / Background**
**Detailed Description:** **Blocked on the open credit-pricing decision** — rate, minimum purchase, and margin over provider cost. That decision determines whether the free-first bet works, and building the purchase path against a guessed price means building the wrong thing. The one thing already settled is that credits are bought from the service, which holds the provider relationship and the usage limits, so a stolen third-party key never becomes the user's problem.

**Scope**
- Nothing while blocked.
- When unblocked: account creation, purchase, receipt, and the relationship between an account and a local install.

**Out of Scope**
- Any implementation while blocked. Any account requirement for the free product — there is none and there must never be one.

**Acceptance Criteria**
- **Acceptance Criteria:** Cannot be accepted while blocked. When unblocked: purchase must not require an account for the free product, must state the price before purchase, and must not make the local product depend on the service in any way.
- **Edge Cases:** Deferred, except one already fixed: the free product must continue to work identically for someone who never buys anything, forever.
- **Permissions / Roles:** Single user — no roles. Not applicable. A credit account is not a product role.
- **UI States:** `../ux/settings.md` §3.
- **Validation Rules:** No licence key, no seat cap, no trial, ever.
- **Audit / Logging Requirements:** Purchases are decisions records locally.
- **Analytics Events:** Paying users are observable by necessity, and that observation says nothing about the free majority — which must be stated wherever those numbers are used.

**Real-World Example Scenarios**
- Deferred with the decision.

**Dependencies & Assumptions**
- **Dependencies:** **Blocked on the open credit-pricing decision.**
- **API / Data Touchpoints:** The credit service.
- **Assumptions:** None may be made. A guessed price would shape the purchase flow, the minimum, and the limit interface all at once.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Not applicable while blocked. When unblocked it must begin with a fresh install that has never bought anything and confirm the free product is unaffected.
- **Known gaps:** Everything.

**Effort & Granularity Check**
- **Estimate:** Not estimable while blocked. · **Priority:** High
- **Labels / Component:** `phase:7`, `blocked:decision`
- **Granularity:** Blocked. Do not start.

---

### M8-CREDIT-BLOCKED-174 — Spending limit and balance **[BLOCKED]**

**Type:** Spike

**User Story**
- **Actor:** someone worried about an unexpected bill.
- **User Need:** a limit they set, so a bad afternoon cannot produce a surprise.
- **Business Value:** credits are bought in advance with a limit the user sets, which is what makes the cost predictable.
- *As someone who has been surprised by a usage bill before, I want a limit I set myself, so that the worst case is bounded by my own number.*

**Context / Background**
**Detailed Description:** **Blocked on the open credit-pricing decision.** The balance display, the limit, and the behaviour as the limit approaches all depend on the unit of pricing, which is undecided. The one settled behaviour is what happens at exhaustion, which is unblocked and is its own ticket.

**Scope**
- Nothing while blocked.
- When unblocked: balance display, the user-set limit, and warnings as it approaches.

**Out of Scope**
- Any implementation while blocked.

**Acceptance Criteria**
- **Acceptance Criteria:** Cannot be accepted while blocked. When unblocked: the limit is set by the user, is honoured, and its approach is warned about before it is reached rather than at it.
- **Edge Cases:** Deferred.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/settings.md` §3.
- **Validation Rules:** A limit the user sets is never exceeded.
- **Audit / Logging Requirements:** Limit changes are decisions records.
- **Analytics Events:** Local only.

**Real-World Example Scenarios**
- Deferred with the decision.

**Dependencies & Assumptions**
- **Dependencies:** **Blocked on the open credit-pricing decision**, and on M8-CREDIT-BLOCKED-173.
- **API / Data Touchpoints:** The credit service.
- **Assumptions:** None may be made.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Not applicable while blocked.
- **Known gaps:** Everything.

**Effort & Granularity Check**
- **Estimate:** Not estimable while blocked. · **Priority:** High
- **Labels / Component:** `phase:7`, `blocked:decision`
- **Granularity:** Blocked. Do not start.

---

### M8-CREDIT-FE-175 — Credits exhausted falls back to local and keeps working

**Type:** Story

**User Story**
- **Actor:** someone whose credit ran out mid-session.
- **User Need:** the conversation to continue locally, saying so.
- **Business Value:** refusing to answer because credit ran out, on a product that works offline for free, would be absurd.
- *As someone who has run out of credit, I want the conversation to carry on with the local model, so that running out is a downgrade rather than a wall.*

**Context / Background**
**Detailed Description:** When credit is exhausted, the conversation falls back to local AI, says so plainly, and nothing is lost. The marker on the conversation updates to reflect that later turns were local. This behaviour is settled and does not depend on the pricing decision, so it can be built and tested against a simulated exhaustion.

**Scope**
- Fallback on exhaustion with a plain statement in the conversation.
- Per-turn backend recording so a mixed conversation is accurate.
- The marker updating to reflect the mixed state.

**Out of Scope**
- Balance and limits — blocked.
- Purchase — blocked.

**Acceptance Criteria**
- **Acceptance Criteria:** Simulated exhaustion causes the next turn to answer locally with a plain statement, and nothing is lost. The conversation records which turns used which backend. The marker reflects a mixed conversation accurately. The user is never blocked from asking.
- **Edge Cases:** Exhaustion mid-answer — the turn completes on whichever backend started it, or restarts locally with that stated; either is acceptable but it must be stated rather than ambiguous. Exhaustion while the machine is also offline — the local model still works, which is the whole point. Credit restored later — the conversation does not silently return to online; the user chooses.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** `../ux/ask.md` §5 credits exhausted; `../states-and-edge-cases.md` §1 online credits exhausted.
- **Validation Rules:** Exhaustion never blocks an answer.
- **Audit / Logging Requirements:** The backend per turn is on the interaction record.
- **Analytics Events:** Local only.

**Real-World Example Scenarios**
- A user runs out mid-afternoon, keeps working with the local model, and buys more the next day.

**Dependencies & Assumptions**
- **Dependencies:** M8-ONLINE-BE-170. Testable against simulated exhaustion without the blocked pricing work.
- **API / Data Touchpoints:** `conversations.ai_backend`; `messages.trace.backend`.
- **Assumptions:** Exhaustion can be simulated for testing without the credit service existing.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start against a test destination with simulated credit. Enable online AI for a conversation, ask two questions, then simulate exhaustion. Ask a third and confirm it is answered locally with a plain statement in the conversation. Confirm the marker reflects that the conversation is now mixed and that the trace names the backend per turn. Confirm nothing was lost.
- **Other scenarios:** Simulate exhaustion mid-answer and confirm the stated behaviour rather than an ambiguous one.
- **Known gaps:** Real exhaustion cannot be tested without the credit service, which is blocked.

**Effort & Granularity Check**
- **Estimate:** 2–3 hours · **Priority:** High
- **Labels / Component:** `phase:7`, frontend
- **Granularity:** One fallback path.

---

### M8-ONLINE-TEST-176 — Online-mode release test: only the authorised destination

**Type:** Story

**User Story**
- **Actor:** the maintainer publishing the first release that can send anything.
- **User Need:** proof that only the authorised destination is reachable and only in the authorised conversation.
- **Business Value:** the moment the product can send anything is the moment its central claim becomes testable in a new way, and it must be tested rather than reasoned about.
- *As someone shipping the first version that can talk to the internet, I want the boundary proven, so that the exception stays an exception.*

**Context / Background**
**Detailed Description:** Extend the release test suite: with online AI enabled for one conversation, verify with an independent network capture that the only traffic leaving is to the authorised destination, that it stops when the conversation is disabled, that a local conversation in the same session sends nothing, and that the sandbox sends nothing under any circumstance.

**Scope**
- The online-mode release test procedure with an independent capture.
- Verification of scoping, revocation and sandbox isolation.
- A recorded result per release, added to the release checklist.

**Out of Scope**
- Testing the billing payload — blocked with its decision.

**Acceptance Criteria**
- **Acceptance Criteria:** With online enabled for one conversation, the capture shows traffic only to the authorised destination. A concurrent local conversation produces none. Disabling stops it immediately. The sandbox produces none. The result is recorded and a failure blocks the release.
- **Edge Cases:** A dependency making an unexpected request while online is enabled — it must still be refused, because the authorisation is for one destination, not for the internet. Traffic to a name that resolves to the authorised address but is a different service — treated as unauthorised, since the authorisation is specific. A retry storm against an unreachable destination — bounded, and the bound is verified.
- **Permissions / Roles:** Single user — no roles. Not applicable.
- **UI States:** None.
- **Validation Rules:** Only the authorised destination, only for the authorised conversation.
- **Audit / Logging Requirements:** The test result is part of the release record.
- **Analytics Events:** None.

**Real-World Example Scenarios**
- The test finds that a dependency's request slipped through while online was enabled, which is exactly the class of failure the proxy exists to prevent.

**Dependencies & Assumptions**
- **Dependencies:** M8-ONLINE-SEC-169, M8-ONLINE-BE-170, M7-OFFLINE-TEST-145, M7-QA-TEST-168.
- **API / Data Touchpoints:** Proxy counters; independent capture.
- **Assumptions:** The cable-unplugged test remains the primary release gate for local mode; this is an additional gate, not a replacement.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** On a clean machine with a capture running at the interface, install and use Askwell locally for a session, confirming nothing leaves. Then enable online AI for one conversation and ask a question. Confirm the capture shows traffic only to the authorised destination. In a second conversation left in local mode, ask a question and confirm nothing leaves. Import a dump and confirm the sandbox sends nothing. Disable online AI and confirm traffic stops immediately.
- **Other scenarios:** Trigger a dependency request while online is enabled and confirm it is still refused.
- **Known gaps:** The billing payload is not tested because it is not decided.

**Effort & Granularity Check**
- **Estimate:** 4–6 hours · **Priority:** Critical
- **Labels / Component:** `phase:7`, test, security, `constraint:local-first`
- **Granularity:** One procedure with one independent verification. Upper bound.
