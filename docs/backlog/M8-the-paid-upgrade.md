# M8 — Online AI, with your own key

**Goal:** Optional online AI, chosen per conversation, paid for by the user directly to their own provider with their own key, and Askwell tells them exactly what will be sent before anything is sent.

**Phase:** 7 (`../build-plan.md`) · **Depends on:** M6.5 · **Tickets:** 8 · **Estimated:** 20–28 hours

**Exit condition:** A conversation can route to exactly one authorised destination, using a key the user supplied, with the disclosure shown before the first send, the local log unchanged, and a fall back to local that never blocks the user.

> **This milestone is beyond the story milestones in `../stories/README.md`, which end at M7.** It is numbered M8 here because the roadmap has a seventh stage and the tickets have to live somewhere.

**The credit model was dropped on 2026-09-23** (`../decisions.md`). Askwell sells nothing. Anyone who wants a larger model brings a key from a provider they already pay, and the relationship is between them and that provider. Nothing in this milestone is blocked any more: the two decisions that gated it — credit pricing, and what online mode transmits for billing — both stopped existing with the model they served. Nothing is transmitted for billing, because there is no billing.

The constraint that survives, unchanged: local logging continues in full regardless, online mode **adds** a record and never replaces one, and a key is a secret — never logged, never in a trace, never in an export, never committed (C8).

## Included epics

| Epic | Code | Covers |
| ---- | ---- | ------ |
| Online routing | `ONLINE` | Per-conversation authorisation, the provider abstraction, the marker and disclosure, logging |
| The user's own key | `KEY` | Storing it, entering it, and what happens when the provider refuses |

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

**Human review:** copy — this ticket renders wording a user reads, specified in `docs/ux/`. The runner stops and quotes it before the pull request is merged.

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

### M8-ONLINE-OBS-172 — Online-mode logging **[UNBLOCKED 2026-08-26]**

> **Built in `0.7.42` (2026-09-24), against #255 rather than the text below.** The text below was written for the credit model. Its "transmitted record" was a billing record for Askwell's own service. That service no longer exists, so nothing is transmitted to Askwell and that record is not built. What was built is the local half: each provider request is recorded as an `online_ai_request` interaction record and on the turn's trace, by reference and never by text, and the trace's "show what was sent" shows it. The network capture stays with `M8-ONLINE-TEST-176`. Reasoning: `../decisions.md`, 2026-09-24, `M8-ONLINE-OBS-172`.

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

### M8-KEY-BE-173 — Hold the user's provider key, as a secret

**Type:** Task

**User Story**
- **Actor:** someone who already pays a provider and wants to use that account here.
- **User Need:** to give Askwell the key once and have it kept properly.
- **Business Value:** this is what replaced the credit system. It is the whole of the online path's commercial arrangement: there isn't one.
- *As someone with my own provider account, I want Askwell to hold my key the way it holds everything else about me, so that using a bigger model costs me nothing extra and tells nobody anything.*

**Context / Background**
**Detailed Description:** Store one provider key, encrypted at rest with the same mechanism as every other credential (`M7-SEC-BE-152`), and hand it to the provider abstraction (`M8-ONLINE-BE-170`) at send time. It never appears in a log line, a trace, an audit record, an error message or an export. Replacing it replaces it; removing it removes it and online mode becomes unavailable rather than silently failing at the next question.

**Scope**
- One key, encrypted at rest, decrypted only at send.
- Which provider it belongs to, so the destination the egress proxy authorises matches it (`M8-ONLINE-SEC-169`).
- Replace and remove, both taking effect immediately.
- Redaction everywhere: logs, traces, audit records, error text, exports.

**Out of Scope**
- Entering it (`M8-KEY-FE-174`).
- Several keys or several providers at once — one is enough until somebody asks for two.
- Validating the key with the provider at entry time; that is a network call before the user has agreed to one.

**Acceptance Criteria**
- **Acceptance Criteria:** A stored key survives a restart, is used for an online turn, and appears nowhere in any log, trace, audit record or export — proved by a test that stores a known sentinel and greps every one of those outputs for it. Removing it makes online mode unavailable, stated plainly.
- **Edge Cases:** A key the provider rejects — reported as the provider rejecting it, never as Askwell being broken, and never with the key in the message. Online attempted with no key — unavailable with the reason, not an error at send. A passphrase-locked install (`M7-SEC-BE-151`) — the key is not readable until unlock, same as everything else encrypted.
- **Permissions / Roles:** Single user — no roles.
- **UI States:** None here; `M8-KEY-FE-174` owns them.
- **Validation Rules:** The key is a secret (C8). It is never a default, never in `.env.example` as a value, and never echoed back to the screen after entry.
- **Audit / Logging Requirements:** Storing, replacing or removing a key is a decisions record — the fact of it, never the value.
- **Analytics Events:** None. Nothing is transmitted about the key or its use (C1).

**Real-World Example Scenarios**
- A user pastes a key from a provider they already pay, asks two hard questions with it that month, and Askwell never learns, reports or charges anything for it.

**Dependencies & Assumptions**
- **Dependencies:** M7-SEC-BE-152, M8-ONLINE-BE-170.
- **API / Data Touchpoints:** The credential store; the provider abstraction; the egress proxy's authorised destination.
- **Assumptions:** One key covers one provider, and the provider abstraction already knows how to present it.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Store a key, restart the stack, run an online turn, then read every log, trace and export for the sentinel. It must appear in none.
- **Other scenarios:** Remove the key and confirm online mode says it is unavailable rather than failing at the next question.
- **Known gaps:** No provider-side validation at entry, deliberately.

**Effort & Granularity Check**
- **Estimate:** 3–4 hours · **Priority:** High
- **Labels / Component:** `phase:7`, `constraint:local-first`, backend
- **Granularity:** One secret, stored and redacted.

---

### M8-KEY-FE-174 — Enter, replace and remove the key, with what it is for

**Type:** Story

**Human review:** copy — this ticket renders wording a user reads, specified in `docs/ux/`. The runner stops and quotes it before the pull request is merged.

**User Story**
- **Actor:** someone deciding whether to hand over a key at all.
- **User Need:** to know what it will be used for, when, and what leaves the machine, before pasting it.
- **Business Value:** a key is the most sensitive thing the product will ever be handed, on a product whose entire pitch is that it is handed nothing.
- *As someone about to paste a provider key into a local-first product, I want to be told precisely what it will do, so that the one exception to 'nothing leaves this machine' is one I made on purpose.*

**Context / Background**
**Detailed Description:** The settings surface for the key: enter it, see that one is set without ever seeing it again, replace it, remove it. Beside it, in plain words: what the key is used for, that it is used only for a conversation the user has explicitly switched to online, that Askwell never sends anything with it without saying so first, and that the cost is between the user and their provider.

**Scope**
- Entry, masked, with no echo back after saving.
- Set-or-not-set state, never the value.
- Replace and remove.
- The statement of what it is for, and of Askwell's own non-involvement in the billing.

**Out of Scope**
- Storage and redaction (`M8-KEY-BE-173`).
- The per-conversation disclosure before a send (`M8-ONLINE-FE-171`), which is a different moment and a different sentence.

**Acceptance Criteria**
- **Acceptance Criteria:** A key can be entered, is never displayed again, and the screen states clearly that one is set. Replace and remove both work and are stated. The explanation names what is sent, when, and that Askwell takes no part in the cost.
- **Edge Cases:** Pasting whitespace or an obviously malformed value — refused at entry with the reason. Removing while a conversation is in online mode — that conversation falls back to local, saying so (`M8-KEY-FE-175`). Entering a key on a passphrase-locked install before unlock — asks for the passphrase first.
- **Permissions / Roles:** Single user — no roles.
- **UI States:** `../ux/settings.md` §9 online AI. The section already exists and is visible-and-disabled from `M7-SET-FE-150`; this fills it in.
- **Validation Rules:** The value is never rendered back, never placed in a URL, and never in a screenshot-able field after save.
- **Audit / Logging Requirements:** Each of entry, replacement and removal is a decisions record — the fact, never the value.
- **Analytics Events:** None (C1).

**Real-World Example Scenarios**
- A cautious user reads the section, decides the explanation is honest, pastes a key, and later removes it in one click when they stop needing it.

**Dependencies & Assumptions**
- **Dependencies:** M8-KEY-BE-173, M7-SET-FE-150.
- **API / Data Touchpoints:** The credential store; the settings surface.
- **Assumptions:** `M7-SET-FE-150` left the section in place to be filled rather than requiring a new one.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Cold start, open settings, read the section as a first-time reader would, enter a key, reload, and confirm it says one is set and never shows it. Remove it and confirm the section returns to its unset state.
- **Other scenarios:** Enter whitespace and confirm the refusal names the reason.
- **Known gaps:** No provider-side validation, matching `M8-KEY-BE-173`.

**Effort & Granularity Check**
- **Estimate:** 3 hours · **Priority:** High
- **Labels / Component:** `phase:7`, frontend
- **Granularity:** One settings section with three actions.

---

### M8-KEY-FE-175 — The provider refusing falls back to local and keeps working

**Type:** Story

**Human review:** copy — this ticket renders wording a user reads, specified in `docs/ux/`. The runner stops and quotes it before the pull request is merged.

**User Story**
- **Actor:** someone whose provider account ran out of quota, or whose key was revoked, mid-session.
- **User Need:** the conversation to continue locally, saying so.
- **Business Value:** refusing to answer because somebody else's provider said no, on a product that works offline for free, would be absurd.
- *As someone whose provider just said no, I want the conversation to carry on with the local model, so that it is a downgrade rather than a wall.*

**Context / Background**
**Detailed Description:** When the provider refuses — quota exhausted, key revoked, rate limited, unreachable — the conversation falls back to local AI, says so plainly in the conversation, and nothing is lost. The marker updates so later turns read as local. The reason is named: it matters to the user whether their quota ran out or their key stopped working, because the two have different fixes, and neither is Askwell's fault to claim as its own error.

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

> **Built 2026-09-25 as gate G13, and `BLOCKED` until #737.** The procedure is `../online-release-test.md`, the record `../online-test-log.md`, the automatable half `scripts/verify-online-egress.sh`. Everything that needs no send ran live and passed. The positive half (one question reaching the provider, and the capture of it) cannot run while #737 refuses every online send, so the gate records `BLOCKED` and holds the release. With this ticket all eight M8 tickets are built, but the milestone's exit condition ("a conversation can route to exactly one authorised destination") is not met until #737 is decided, so M8 has not landed. Reasoning: `../decisions.md`, 2026-09-25, `M8-ONLINE-TEST-176`.

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

---

## Opening the gate, and keeping voice

Three tickets from two product decisions made on 2026-09-25 (`../decisions.md`): the online-AI disclosure wording was approved, and Askwell is relicensed to GPLv3 so that spoken answers can ship. They are ordered on purpose — Redis is locked down before the disclosure is set, because the disclosure is the only thing still refusing every online send, and `api/tests/test_provider_key.py::test_no_online_send_is_possible_until_redis_is_authenticated` fails the build if the two land the other way round.

---

### M8-FIX-SEC-177 — Redis authentication, one user per service

**Type:** Task

**User Story**
- **Actor:** someone who has stored a provider API key.
- **User Need:** that only Askwell's own API can open a route off the machine with it.
- **Business Value:** the egress proxy is C1's enforcement point and it trusts whatever Redis says, and Redis takes writes from every container.
- *As someone who gave Askwell a paid key, I want only the part of Askwell that asked me to be able to spend it, so that a bug in document parsing cannot.*

**Context / Background**
**Detailed Description:** The egress proxy forwards a connection if Redis holds the right keys — `askwell:egress:permitted_host`, `askwell:egress:grant:*`, `askwell:egress:conversation:*`. Redis runs with no password and no ACL, so every service on the `internal` network can write them, including the worker, which parses untrusted documents. One `SET` from a compromised dependency opens egress, and nothing records it. Issue #730 has the full analysis.

Take option 1 of #730: Redis ACLs, one user per service. The API may write the grant keys; the proxy may read them, write its own counters and run the one `DEL` pattern it uses at startup; the worker and voice service get the queue keys only. Passwords live in `.env` like the database's (C8), `.env.example` names them in the same change, and the three installers generate them. Moving grants into Postgres was rejected — it gives the proxy a database dependency it was deliberately built without and adds latency to every `CONNECT`. Signing grants was rejected as hand-rolled authentication over a store that already has it.

**Scope**
- A Redis ACL file with one user per service and the narrowest key patterns and commands each needs.
- Every Redis client given its own user and password from the environment.
- `.env.example` updated; the Linux, Windows and macOS installers generate the passwords.
- The default user disabled, so an unauthenticated connection is refused outright.

**Out of Scope**
- Setting the online disclosure (`M8-FIX-BE-178`), which depends on this.

**Acceptance Criteria**
- **Acceptance Criteria:** An unauthenticated connection to Redis is refused. The worker and voice users cannot write any `askwell:egress:*` key — proved by a test that tries from each and is refused. The API can write grants, the proxy can read them, and everything that worked before still works: ingestion jobs, voice, web escalation, online grants.
- **Edge Cases:** An existing install upgrading — the installer generates the new passwords rather than leaving Redis open or refusing to start. A password missing from `.env` — the service fails loudly at start rather than falling back to no authentication. The proxy's startup `DEL` — still permitted, and nothing broader.
- **Permissions / Roles:** Single user, but five Redis users, one per service. That separation is the whole ticket.
- **UI States:** None.
- **Validation Rules:** No service holds a Redis permission it does not use. No password is committed (C8).
- **Audit / Logging Requirements:** A refused Redis write is logged by the refusing client. State in the closing comment how C1 was preserved — the `constraint:local-first` label requires it.
- **Analytics Events:** None.

**Real-World Example Scenarios**
- A malicious spreadsheet exploits a parsing bug in the worker and tries to set a permitted egress host. Redis refuses the write and the proxy never learns of it.

**Dependencies & Assumptions**
- **Dependencies:** M8-ONLINE-SEC-169, M7-PACK-DEPLOY-142.
- **API / Data Touchpoints:** `compose.yaml` `redis` service; every Redis client (`api`, `worker`, `voice`, `egress-proxy`); `.env.example`; the three installers under `deploy/`.
- **Assumptions:** The Redis version in use supports ACL files. If the proxy's startup `DEL` pattern cannot be expressed narrowly, say so rather than granting it broad `DEL`.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Bring the stack up from a fresh install, then `redis-cli` with no credentials and confirm refusal; as the worker user, try `SET askwell:egress:permitted_host x:443` and confirm refusal. Then ingest a file, use voice, escalate a question to the web, and confirm all still work.
- **Other scenarios:** Remove the proxy's password from `.env` and confirm the proxy refuses to start.
- **Known gaps:** None.

**Effort & Granularity Check**
- **Estimate:** 4 hours · **Priority:** Critical
- **Labels / Component:** `phase:7`, `constraint:local-first`, security, deploy
- **Granularity:** One ACL file, five clients, three installers.

---

### M8-FIX-BE-178 — The approved statement of what online AI sends

**Type:** Task

**Human review:** copy — this ticket renders wording a user reads. The runner stops and quotes it before the pull request is merged.

**User Story**
- **Actor:** someone about to send a question about confidential material to an online model.
- **User Need:** to be told exactly what will leave the machine, in words they can hold Askwell to.
- **Business Value:** online AI is built and refuses every send until this exists. The refusal is deliberate — the product never sends something it cannot describe.
- *As someone deciding whether my client's documents may leave this laptop, I want a plain, accurate statement of what goes, so that the decision is mine and informed.*

**Context / Background**
**Detailed Description:** `askwell.online.DISCLOSURE` is `None` and every online send is refused with `DISCLOSURE_UNDEFINED` until it is set (issue #737). The product owner approved the wording on 2026-09-25 (`../decisions.md`). Set it, as version `1`, to exactly:

> When you ask in this conversation, Askwell sends your online AI provider your question, the passages from your files that it found relevant to it, and any facts you have taught Askwell that bear on it. It does not send whole files, earlier questions, database rows or anything from other conversations. A question Askwell cannot answer from your files sends nothing.

The only change from #737's draft is `<provider>` replaced with "your online AI provider": the statement is one constant, and a template that renders the provider's name would be a second place for it to drift. The wording was read from the code rather than assumed — `M8-ONLINE-BE-170` sends `compose_conflict`'s system prompt and user content, which is these three things and nothing else, and the local model receives the same prompt.

**Scope**
- `DISCLOSURE` set to the approved text, version `1`.
- The tests that pinned the undecided state rewritten to pin the decided one, keeping a test that `None` still refuses every send.
- The backlog's blocked table and `../ux/` wording updated to match.

**Out of Scope**
- Changing what is sent. That is `M8-ONLINE-BE-170`'s and would need an eval run.

**Acceptance Criteria**
- **Acceptance Criteria:** An online conversation shows the approved statement before its first send, a confirmation of version `1` is accepted, and the send then goes. `test_no_online_send_is_possible_until_redis_is_authenticated` passes because Redis is authenticated, not because the test was edited.
- **Edge Cases:** A conversation that confirmed nothing — still refused with `NOT_CONFIRMED`. A future change to the statement — needs a new version and a fresh confirmation, which the existing mechanism already enforces.
- **Permissions / Roles:** Single user — no roles.
- **UI States:** The online conversation's pre-send disclosure, `M8-ONLINE-FE-171`.
- **Validation Rules:** **Do not weaken or delete the Redis-ordering guard to make this pass.** If it fails, `M8-FIX-SEC-177` has not landed, and that is the thing to fix. The text is set verbatim.
- **Audit / Logging Requirements:** Confirming the statement is a decisions record, as it already is.
- **Analytics Events:** None (C1).

**Real-World Example Scenarios**
- A solicitor switches one conversation online, reads the statement, confirms, and asks — knowing the provider saw the question and the relevant passages, not the file.

**Dependencies & Assumptions**
- **Dependencies:** M8-FIX-SEC-177, M8-ONLINE-FE-171, M8-KEY-BE-173.
- **API / Data Touchpoints:** `api/src/askwell/online.py`; `api/tests/test_online.py`, `test_ask_online.py`, `test_provider_key.py`.
- **Assumptions:** What `M8-ONLINE-BE-170` sends still matches the statement. If it has changed since #737 was written, stop and say so — a statement that has drifted from the code is worse than none.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Store a provider key, switch a conversation online, read the statement, confirm, ask, and confirm a request reaches the provider.
- **Other scenarios:** Set `DISCLOSURE` back to `None` in a test and confirm every send is refused again.
- **Known gaps:** None.

**Effort & Granularity Check**
- **Estimate:** 2 hours · **Priority:** High
- **Labels / Component:** `phase:7`, `constraint:local-first`, backend
- **Granularity:** One constant and the tests around it.

---

### M8-FIX-DOC-179 — Relicense Askwell to GPLv3, so spoken answers ship

**Type:** Task

**User Story**
- **Actor:** someone who wants to hear the answer as well as speak the question.
- **User Need:** voice both ways, in a bundle that is legally clean.
- **Business Value:** spoken answers depend on a GPLv3 library, and the product owner requires voice in both directions.
- *As someone using Askwell hands-free, I want it to answer out loud, so that voice is a real way to use it and not half of one.*

**Context / Background**
**Detailed Description:** Voice synthesis (`kokoro-onnx`) requires `phonemizer`, GPLv3+. The release licence gate (`scripts/dev.sh notices`, `M7-DOC-DOC-163`) fails on it (#619). Every alternative checked against PyPI on 2026-09-25 routes English pronunciation through espeak-ng, which is GPL as well: `espeakng` GPLv3, `piper-tts` GPL-3.0+, and `misaki`'s English extra pulls `phonemizer-fork` and `espeakng-loader`. Removing espeak would mean a dictionary-only pronunciation that handles names and jargon worst, which is what people's documents contain.

The product owner chose voice in both directions, and the only licence that ships it without that degradation is GPLv3 (`../decisions.md`, 2026-09-25). Changing to MIT was considered and does nothing: the conflict comes from GPLv3's own terms, which no permissive licence can override. Every other dependency and bundled model — Apache-2.0 and MIT throughout — is GPLv3-compatible.

**Scope**
- `LICENSE` replaced with the GPLv3 text.
- `api/pyproject.toml`, `web/package.json` and any other package metadata declaring a licence changed to `GPL-3.0-or-later`.
- `README.md`, `docs/PRD.md` and the About screen corrected to say GPLv3.
- `AGENTS.md` C9 updated: bundled material must be **GPLv3-compatible** and permit commercial use and redistribution, and must not be gated. Stated as a decision, not a quiet edit.
- The notices gate's disallow list changed: GPL-2.0-only (incompatible with GPLv3), AGPL and SSPL, non-commercial and no-derivatives terms, and unlicensed stay disallowed. GPLv3 and GPL-2.0-or-later are allowed. Its tests updated to pin both halves.
- `NOTICES.md` regenerated; the gate passes.

**Out of Scope**
- Any change to what voice does. It already works.
- Publishing a release (`AGENTS.md` §7).

**Acceptance Criteria**
- **Acceptance Criteria:** `scripts/dev.sh notices` passes with `phonemizer` listed and accepted. Every place Askwell states its own licence says GPLv3. The gate still fails on a GPL-2.0-only or AGPL dependency — proved by the existing test pattern, not assumed.
- **Edge Cases:** A dependency declaring only "GPL" with no version — flagged as unclear, not allowed by default. A bundled model with a non-commercial licence — still refused, as before.
- **Permissions / Roles:** Single user — no roles.
- **UI States:** The About screen's licence line.
- **Validation Rules:** Do not allow-list `phonemizer` by name to make the gate pass — change the rule, so the gate stays meaningful for the next dependency.
- **Audit / Logging Requirements:** None.
- **Analytics Events:** None.

**Real-World Example Scenarios**
- Someone downloads Askwell, reads GPLv3 in the About screen, and gets a product that listens and answers aloud.

**Dependencies & Assumptions**
- **Dependencies:** M7-DOC-DOC-163, M6-TTS-BE-130.
- **API / Data Touchpoints:** `LICENSE`; package metadata; `README.md`; `docs/PRD.md`; `AGENTS.md` C9; `api/src/askwell/notices.py`; `scripts/generate_notices.py`; `web/components/settings/about.tsx`.
- **Assumptions:** The GPLv3 text comes from the FSF's canonical copy, verbatim.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Run `scripts/dev.sh notices` and confirm it passes. Open Settings → About and confirm GPLv3.
- **Other scenarios:** Add a fake GPL-2.0-only package to the gate's test input and confirm it still fails.
- **Known gaps:** Not legal advice; a lawyer's review before a public release is advisable.

**Effort & Granularity Check**
- **Estimate:** 3 hours · **Priority:** High
- **Labels / Component:** `phase:7`, documentation, licensing
- **Granularity:** One licence, one gate rule, the places that state it.
