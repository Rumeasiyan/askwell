# M9 — It is ready to ship

**Goal:** The release blockers found by the triage of 2026-09-28 fixed, so the product does what it says for a real user on a clean machine.

**Phase:** 7 (`../build-plan.md`) · **Depends on:** M8 · **Tickets:** 16 · **Estimated:** 55 hours

**Exit condition:** Installable downloads for Linux, Windows and macOS are built by CI, a fresh install on Linux works end to end without a manual step, answers read as prose with every claim cited, the clarification loop and conflict resolution actually remember, the audit chain holds through prune and restore, and every test that exists runs.

> **Where these came from.** Every ticket in M0–M8 was built, and the build's own audit agents filed what they found on the way: about 230 issues, 69 of them bugs. The queue builds this directory, never the tracker, so none of those would ever have been fixed. On 2026-09-28 the open bugs were triaged. Eight were already fixed and were closed after checking the code or the live stack. The fourteen tickets below are the ones that stop the product doing what it claims. Each names its issues, which hold the full evidence. They are ordered by harm: install first, then what every user sees, then correctness, then safety, then the test suite. That way, whatever fits in the remaining build budget is the part that matters most.
>
> **Deliberately not here:** cosmetic and copy issues, anything that needs Windows or Mac hardware (#590, #592), code signing (`M7-TAURI-DEPLOY-184a`), branch protection (#623, a GitHub setting only the owner can change), and the abstention eval (#625). The eval is run by the orchestrating session rather than a build agent, because it takes longer on CPU than an agent session lasts.

---

### M9-FIX-DEPLOY-200 — A fresh install has a schema, an upgrade migrates, and purge really purges

**Type:** Task

**User Story**
- **Actor:** someone installing Askwell for the first time, or upgrading it.
- **User Need:** an install that works on first launch.
- **Business Value:** found by the release triage of 2026-09-28; without it the product does not do what it claims for a real user.

**Context / Background**
**Detailed Description:** The installers never run database migrations, so a fresh install starts with no schema and an upgrade never migrates. `uninstall --purge-data` leaves the database volumes behind while saying it removed them, which breaks the credentials of the next install. Full evidence, file paths and the options already weighed are in #698, #700 — read them before starting, and follow the recommendation there unless the code has changed since.

**Scope**
- The three installers run `alembic upgrade head` after the stack is up, on install and on upgrade.
- `--purge-data` removes the database volumes it claims to, and says so truthfully.

**Out of Scope**
- Anything not named in #698, #700. A new problem found on the way becomes its own issue, not part of this change.

**Acceptance Criteria**
- **Acceptance Criteria:** A fresh Linux install reaches a working Ask screen with no manual step. An upgrade applies pending migrations. Install → purge → install works with new credentials.
- **Edge Cases:** A migration that fails — the installer stops and names it, never reports success. An upgrade with no pending migrations — a no-op, not an error.
- **Permissions / Roles:** Single user — no roles.
- **UI States:** As named in #698, #700.
- **Validation Rules:** An installer never reports a step it did not perform. Do not weaken, skip or delete an existing test to make this pass.
- **Audit / Logging Requirements:** Unchanged unless #698, #700 says otherwise. Any `constraint:*` label on #698, #700 must be answered in the closing comment: how the constraint was preserved.
- **Analytics Events:** None (C1).

**Dependencies & Assumptions**
- **Dependencies:** M7-PACK-DEPLOY-139, M7-PACK-DEPLOY-140, M7-PACK-DEPLOY-141.
- **API / Data Touchpoints:** As named in #698, #700.
- **Assumptions:** The issue's diagnosis still holds. If the code has moved on, re-verify first and say what changed.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** On a clean Linux user account, install, open the app, add a folder, ask a question. Then purge and install again.
- **Known gaps:** Close #698, #700 with what was verified, the command run and what it returned.

**Effort & Granularity Check**
- **Estimate:** 4 hours · **Priority:** Critical
- **Labels / Component:** `phase:7`, deploy
- **Granularity:** The fix named in #698, #700, and its tests.

---

### M9-FIX-BE-215 — An answer that covers nothing is an abstention, and nothing internal leaks into it

**Type:** Task

**User Story**
- **Actor:** someone asking about something their files do not cover, but come close to.
- **User Need:** a plain "nothing in your files answers this", with what to add — not prose that half-answers it.
- **Business Value:** C5 is the promise the product is built on, and its first measurement (2026-09-28) was **0.07 against a pass bar of 0.90**.

**Context / Background**
**Detailed Description:** Issue #769 has the full evidence. In short: near-miss questions retrieve passages above threshold, so the turn skips the formal abstention path and the model writes its refusal as prose — `Not covered: …` — which the user sees instead of the abstention surface. The same answers leak raw prompt delimiters (`<retrieved-content index="1" chunk_id="…">` and the passage text), spam citation markers with no claim attached (`[1] [2] … [15]`), and repeat `Not covered:` lines. The model is mostly *not* inventing; the product is presenting a correct refusal in the wrong shape and leaking internals while it does.

**Do not lower the retrieval threshold.** `AGENTS.md` C5 forbids it: it would move the number while making the product worse (`../success-metrics.md` §2).

**Scope**
- An answer with no grounded, cited claim, whose content is entirely `Not covered` lines, becomes an abstention: routed through `compose_abstention` with the aspects the model named, so the user gets the full abstention surface.
- Any delimiter block (`<retrieved-content …>`, `<tool-result>`, `<web-content>`, `<memory-facts>`, `<schema-notes>`) stripped from answer text before it is stored or shown.
- A citation marker rendered only when attached to a claim.
- Duplicate `Not covered:` lines collapsed.
- `abstention.v1` run **with and without** `ASKWELL_GENERATION_THINKING_DIRECTIVE`, both results recorded in `../BRAIN.md`'s Eval baseline section — `0.7.21` (#629) may have caused the delimiter echo, and nobody knows yet.

**Out of Scope**
- The threshold.
- Partial answers that genuinely answer part of the question — those stay answers, with their uncovered part named.

**Acceptance Criteria**
- **Acceptance Criteria:** `abstention.v1` is re-run and its score recorded honestly, pass or fail. No answer in `abstention.v1` or `grounded_qa.v1` contains a delimiter tag or an unattached citation marker. A question the corpus does not answer shows the abstention surface, with its escalation offers.
- **Edge Cases:** An answer with one real cited claim and one `Not covered` line — stays a partial answer, not an abstention. `grounded_qa.v1` — must not regress; an answerable question must not start abstaining. Report its score before and after.
- **Permissions / Roles:** Single user — no roles.
- **UI States:** `../ux/ask.md` §5 Abstained and Partial; `../states-and-edge-cases.md` §2.
- **Validation Rules:** Do not weaken, skip or re-score `abstention.v1`, and do not lower the pass bar or the threshold. If the bar is still not met, record the real number and file what remains — an honest 0.6 is worth more than a manufactured 0.9. C7: delimiter content is never shown to the user.
- **Audit / Logging Requirements:** Unchanged.
- **Analytics Events:** None (C1).

**Real-World Example Scenarios**
- A user asks for the termination notice period; the handbook only has the resignation notice. They see "Nothing in your files answers this", the closest material named, and an offer to add a source — not a paragraph about resignation.

**Dependencies & Assumptions**
- **Dependencies:** M2-ABSTAIN-BE-054, M2-PARTIAL-BE-057, M2-EVAL-TEST-064.
- **API / Data Touchpoints:** `api/src/askwell/ask.py` `_run_generation`; `api/src/askwell/agent/partial.py`; `api/src/askwell/agent/abstain.py`; `eval/`.
- **Assumptions:** The eval suite finishes within a build session on this host (it took about thirty minutes on 2026-09-28).

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Ask "What is the notice period for terminating an employee?" against `eval/fixtures/corpus` and confirm the abstention surface.
- **Other scenarios:** `scripts/dev.sh eval --suite abstention.v1` and `--suite grounded_qa.v1`, before and after, with and without the directive.
- **Known gaps:** Close #769 and #625 with the recorded numbers.

**Effort & Granularity Check**
- **Estimate:** 6 hours · **Priority:** Critical
- **Labels / Component:** `phase:7`, `constraint:grounding`, `constraint:injection`, `eval`, backend
- **Granularity:** One routing rule, one strip, one eval comparison.

---

### M9-FIX-FE-201 — Add a source is reachable after the first one

**Type:** Task

**User Story**
- **Actor:** someone adding their second folder.
- **User Need:** to add more material without reinstalling.
- **Business Value:** found by the release triage of 2026-09-28; without it the product does not do what it claims for a real user.

**Context / Background**
**Detailed Description:** Once anything has been added, there is no clickable way to add another source — the welcome copy says 'from the rail', and the rail has no such entry. The library is the only route to sources and it has no add control. Full evidence, file paths and the options already weighed are in #712 — read it before starting, and follow the recommendation there unless the code has changed since.

**Scope**
- A visible 'Add a source' control, reachable by clicking from the Library and wherever the copy promises it.
- The copy corrected to name where it actually is.

**Out of Scope**
- Anything not named in #712. A new problem found on the way becomes its own issue, not part of this change.

**Acceptance Criteria**
- **Acceptance Criteria:** With one source already indexed, a user can reach the add-source flow by clicking only, from the landing page.
- **Edge Cases:** No sources at all — the first-run path still works. Narrow window — reachable through the drawer.
- **Permissions / Roles:** Single user — no roles.
- **UI States:** As named in #712.
- **Validation Rules:** Every screen named in copy is reachable by clicking (`docs/manual-tests/master-sheet.md` Part A). Do not weaken, skip or delete an existing test to make this pass.
- **Audit / Logging Requirements:** Unchanged unless #712 says otherwise. Any `constraint:*` label on #712 must be answered in the closing comment: how the constraint was preserved.
- **Analytics Events:** None (C1).

**Dependencies & Assumptions**
- **Dependencies:** M1-ADD-FE-022, M7-FIX-FE-173.
- **API / Data Touchpoints:** As named in #712.
- **Assumptions:** The issue's diagnosis still holds. If the code has moved on, re-verify first and say what changed.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Add one folder, then from the landing page add a second by clicking only.
- **Known gaps:** Close #712 with what was verified, the command run and what it returned.

**Effort & Granularity Check**
- **Estimate:** 2 hours · **Priority:** Critical
- **Labels / Component:** `phase:7`, frontend
- **Granularity:** The fix named in #712, and its tests.

---

### M9-FIX-BE-202 — Answers read as prose, not run-ons and prompt fragments

**Type:** Task

**User Story**
- **Actor:** anyone reading an answer.
- **User Need:** an answer that reads as written sentences.
- **Business Value:** found by the release triage of 2026-09-28; without it the product does not do what it claims for a real user.

**Context / Background**
**Detailed Description:** Every multi-claim answer drops the space between cited sentences, so answers render as run-ons. Separately the model echoes the prompt's own templates verbatim — `Not covered: <the specific thing…>`, `Resolved by memory: <the fact…>` — and they render as answer content. Full evidence, file paths and the options already weighed are in #726, #663 — read them before starting, and follow the recommendation there unless the code has changed since.

**Scope**
- Spacing preserved between cited sentences.
- Template placeholders detected and never rendered as content; if the model emits one, it is dropped rather than shown.

**Out of Scope**
- Anything not named in #726, #663. A new problem found on the way becomes its own issue, not part of this change.

**Acceptance Criteria**
- **Acceptance Criteria:** A three-claim answer renders with normal spacing. No answer ever shows a `<…>` template placeholder.
- **Edge Cases:** A claim that genuinely ends without punctuation — still separated. A template echoed inside a real sentence — only the template is removed.
- **Permissions / Roles:** Single user — no roles.
- **UI States:** As named in #726, #663.
- **Validation Rules:** Any prompt change needs an eval run recorded in `docs/BRAIN.md` (`AGENTS.md` §4). C4: removing a template must never remove a real citation. Do not weaken, skip or delete an existing test to make this pass.
- **Audit / Logging Requirements:** Unchanged unless #726, #663 says otherwise. Any `constraint:*` label on #726, #663 must be answered in the closing comment: how the constraint was preserved.
- **Analytics Events:** None (C1).

**Dependencies & Assumptions**
- **Dependencies:** M1-ASK-BE-037.
- **API / Data Touchpoints:** As named in #726, #663.
- **Assumptions:** The issue's diagnosis still holds. If the code has moved on, re-verify first and say what changed.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Ask a question that produces three cited claims and a partial answer; read it as a first-time reader.
- **Known gaps:** Close #726, #663 with what was verified, the command run and what it returned.

**Effort & Granularity Check**
- **Estimate:** 3 hours · **Priority:** Critical
- **Labels / Component:** `phase:7`, `constraint:grounding`, backend
- **Granularity:** The fix named in #726, #663, and its tests.

---

### M9-FIX-BE-203 — Re-indexing works, including for cited documents

**Type:** Task

**User Story**
- **Actor:** someone who edited a file and pressed Re-index.
- **User Need:** the index to reflect the file.
- **Business Value:** found by the release triage of 2026-09-28; without it the product does not do what it claims for a real user.

**Context / Background**
**Detailed Description:** Re-indexing a document that has been cited fails at the chunk stage on `fk_citations_chunk_id_chunks`. Re-index also silently does nothing for documents that have no `ingest_jobs` row, and leaves them 'queued' forever. Full evidence, file paths and the options already weighed are in #719, #720 — read them before starting, and follow the recommendation there unless the code has changed since.

**Scope**
- Re-index of a cited document succeeds, and earlier answers' citations still resolve — to a tombstone if the passage is gone, never to an error.
- Documents with no job row get one, or are reported, never left queued.

**Out of Scope**
- Anything not named in #719, #720. A new problem found on the way becomes its own issue, not part of this change.

**Acceptance Criteria**
- **Acceptance Criteria:** Re-indexing a cited document succeeds and its old answers still open. No document stays 'queued' after a re-index.
- **Edge Cases:** A passage that no longer exists after re-index — its old citation shows as removed, per `docs/ux/ask.md` §5 'Deleted source cited'.
- **Permissions / Roles:** Single user — no roles.
- **UI States:** As named in #719, #720.
- **Validation Rules:** C4: a past citation is never silently broken or repointed at different text. Do not weaken, skip or delete an existing test to make this pass.
- **Audit / Logging Requirements:** Unchanged unless #719, #720 says otherwise. Any `constraint:*` label on #719, #720 must be answered in the closing comment: how the constraint was preserved.
- **Analytics Events:** None (C1).

**Dependencies & Assumptions**
- **Dependencies:** M1-ADD-ING-021.
- **API / Data Touchpoints:** As named in #719, #720.
- **Assumptions:** The issue's diagnosis still holds. If the code has moved on, re-verify first and say what changed.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Ask a question citing a document, edit that document, re-index, then reopen the old answer.
- **Known gaps:** Close #719, #720 with what was verified, the command run and what it returned.

**Effort & Granularity Check**
- **Estimate:** 3 hours · **Priority:** Critical
- **Labels / Component:** `phase:7`, `constraint:grounding`, backend
- **Granularity:** The fix named in #719, #720, and its tests.

---

### M9-FIX-FE-204 — Resolving a conflict remembers the answer, and the right sentence is boxed

**Type:** Task

**User Story**
- **Actor:** someone told which of two documents is current.
- **User Need:** Askwell to remember the choice.
- **Business Value:** found by the release triage of 2026-09-28; without it the product does not do what it claims for a real user.

**Context / Background**
**Detailed Description:** "Which one is current?" writes no memory fact and says memory has not shipped — memory shipped in M3. The conflict layout can also box an unrelated cited sentence as a conflicting position when the conflict line comes last. Full evidence, file paths and the options already weighed are in #728, #727 — read them before starting, and follow the recommendation there unless the code has changed since.

**Scope**
- Choosing a current document writes a memory fact and says so.
- Only the actual conflicting positions are boxed.

**Out of Scope**
- Anything not named in #728, #727. A new problem found on the way becomes its own issue, not part of this change.

**Acceptance Criteria**
- **Acceptance Criteria:** Choosing the current document writes a fact visible on the Memory screen and used by the next answer. An unrelated trailing sentence is never boxed as a position.
- **Edge Cases:** Choosing, then choosing the other — the fact is superseded, not duplicated.
- **Permissions / Roles:** Single user — no roles.
- **UI States:** As named in #728, #727.
- **Validation Rules:** C4: a position is boxed only if it is one of the conflicting claims. Do not weaken, skip or delete an existing test to make this pass.
- **Audit / Logging Requirements:** Unchanged unless #728, #727 says otherwise. Any `constraint:*` label on #728, #727 must be answered in the closing comment: how the constraint was preserved.
- **Analytics Events:** None (C1).

**Dependencies & Assumptions**
- **Dependencies:** M7-FIX-FE-170.
- **API / Data Touchpoints:** As named in #728, #727.
- **Assumptions:** The issue's diagnosis still holds. If the code has moved on, re-verify first and say what changed.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Ask 'What are the store hours?' against `eval/fixtures/corpus`, choose 2026, check Memory, then ask again.
- **Known gaps:** Close #728, #727 with what was verified, the command run and what it returned.

**Effort & Granularity Check**
- **Estimate:** 3 hours · **Priority:** Critical
- **Labels / Component:** `phase:7`, `constraint:grounding`, frontend
- **Granularity:** The fix named in #728, #727, and its tests.

---

### M9-FIX-BE-205 — A passphrase does not stop new files being indexed

**Type:** Task

**User Story**
- **Actor:** someone who turned on the passphrase.
- **User Need:** to keep adding files after setting it.
- **Business Value:** found by the release triage of 2026-09-28; without it the product does not do what it claims for a real user.

**Context / Background**
**Detailed Description:** The worker never unlocks, so once a passphrase is set new-document ingestion breaks — not only background connection jobs. Full evidence, file paths and the options already weighed are in #508 — read it before starting, and follow the recommendation there unless the code has changed since.

**Scope**
- The worker receives the unlocked state the API has, without the passphrase leaving the machine or being written to disk.

**Out of Scope**
- Anything not named in #508. A new problem found on the way becomes its own issue, not part of this change.

**Acceptance Criteria**
- **Acceptance Criteria:** With a passphrase set and Askwell unlocked, adding a folder indexes it. Locked, ingestion waits and says why.
- **Edge Cases:** Restart while unlocked — locked again until the passphrase is entered. Wrong passphrase — nothing decrypts.
- **Permissions / Roles:** Single user — no roles.
- **UI States:** As named in #508.
- **Validation Rules:** The passphrase is never logged, stored in plain text, or sent anywhere (C1, C8). Do not weaken, skip or delete an existing test to make this pass.
- **Audit / Logging Requirements:** Unchanged unless #508 says otherwise. Any `constraint:*` label on #508 must be answered in the closing comment: how the constraint was preserved.
- **Analytics Events:** None (C1).

**Dependencies & Assumptions**
- **Dependencies:** M7-SEC-BE-151.
- **API / Data Touchpoints:** As named in #508.
- **Assumptions:** The issue's diagnosis still holds. If the code has moved on, re-verify first and say what changed.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Set a passphrase, restart, unlock, add a folder, confirm it indexes.
- **Known gaps:** Close #508 with what was verified, the command run and what it returned.

**Effort & Granularity Check**
- **Estimate:** 3 hours · **Priority:** Critical
- **Labels / Component:** `phase:7`, `constraint:local-first`, backend
- **Granularity:** The fix named in #508, and its tests.

---

### M9-FIX-BE-206 — Questions the tool loop answers keep memory, partial coverage and conflict detection

**Type:** Task

**User Story**
- **Actor:** anyone asking a multi-step question.
- **User Need:** the same honesty about gaps and conflicts as a simple question.
- **Business Value:** found by the release triage of 2026-09-28; without it the product does not do what it claims for a real user.

**Context / Background**
**Detailed Description:** Any question the tool loop grounds on loses memory facts, partial-coverage detection and conflict detection — not just hybrid ones. The loop path bypasses the answer composition that carries them. Full evidence, file paths and the options already weighed are in #409 — read it before starting, and follow the recommendation there unless the code has changed since.

**Scope**
- The loop's grounded answers go through the same composition as a single-step answer.

**Out of Scope**
- Anything not named in #409. A new problem found on the way becomes its own issue, not part of this change.

**Acceptance Criteria**
- **Acceptance Criteria:** A multi-step question over conflicting documents reports the conflict. One with an uncovered part names it. Relevant memory facts are cited.
- **Edge Cases:** A loop that stops at the eight-call ceiling — still reports what it has, with the same checks.
- **Permissions / Roles:** Single user — no roles.
- **UI States:** As named in #409.
- **Validation Rules:** C4 and C5 hold on every path, not only the simple one. Any prompt change needs an eval run. Do not weaken, skip or delete an existing test to make this pass.
- **Audit / Logging Requirements:** Unchanged unless #409 says otherwise. Any `constraint:*` label on #409 must be answered in the closing comment: how the constraint was preserved.
- **Analytics Events:** None (C1).

**Dependencies & Assumptions**
- **Dependencies:** M5-LOOP-BE-115.
- **API / Data Touchpoints:** As named in #409.
- **Assumptions:** The issue's diagnosis still holds. If the code has moved on, re-verify first and say what changed.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Ask a question needing two lookups against the fixture corpus's conflicting documents.
- **Known gaps:** Close #409 with what was verified, the command run and what it returned.

**Effort & Granularity Check**
- **Estimate:** 4 hours · **Priority:** Critical
- **Labels / Component:** `phase:7`, `constraint:grounding`, backend
- **Granularity:** The fix named in #409, and its tests.

---

### M9-FIX-BE-207 — Answering a table-column clarification teaches Askwell about that column

**Type:** Task

**User Story**
- **Actor:** someone who answered what a column means.
- **User Need:** the answer to be used.
- **Business Value:** found by the release triage of 2026-09-28; without it the product does not do what it claims for a real user.

**Context / Background**
**Detailed Description:** Table-column clarification answers never promote to a schema note, because the subject format does not match. The clarification loop — the differentiator — silently does nothing for tables. Full evidence, file paths and the options already weighed are in #361 — read it before starting, and follow the recommendation there unless the code has changed since.

**Scope**
- A column clarification answer becomes a schema note the next database question uses.

**Out of Scope**
- Anything not named in #361. A new problem found on the way becomes its own issue, not part of this change.

**Acceptance Criteria**
- **Acceptance Criteria:** Answering 'what does st_cd mean' produces a schema note, and the next question about that table uses it.
- **Edge Cases:** A column that no longer exists — the note is marked stale, per the existing rule.
- **Permissions / Roles:** Single user — no roles.
- **UI States:** As named in #361.
- **Validation Rules:** The fix aligns the subject format; it does not loosen matching to the point of attaching an answer to the wrong column. Do not weaken, skip or delete an existing test to make this pass.
- **Audit / Logging Requirements:** Unchanged unless #361 says otherwise. Any `constraint:*` label on #361 must be answered in the closing comment: how the constraint was preserved.
- **Analytics Events:** None (C1).

**Dependencies & Assumptions**
- **Dependencies:** M3-RAISE-BE-071.
- **API / Data Touchpoints:** As named in #361.
- **Assumptions:** The issue's diagnosis still holds. If the code has moved on, re-verify first and say what changed.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Add a CSV with an abbreviated column, answer its clarification, then ask about that column.
- **Known gaps:** Close #361 with what was verified, the command run and what it returned.

**Effort & Granularity Check**
- **Estimate:** 3 hours · **Priority:** Critical
- **Labels / Component:** `phase:7`, `constraint:grounding`, backend
- **Granularity:** The fix named in #361, and its tests.

---

### M9-FIX-SEC-208 — Log pruning works on a real install, and restore does not fork the audit chain

**Type:** Task

**User Story**
- **Actor:** someone whose log reaches its retention window, or who restores a backup.
- **User Need:** the log to behave as `docs/audit-log.md` says.
- **Business Value:** found by the release triage of 2026-09-28; without it the product does not do what it claims for a real user.

**Context / Background**
**Detailed Description:** `log_prune` deletes `audit_interactions` as `askwell_app`, which has no DELETE grant — prune fails on every real install; the dev database carries a drifted grant that hides it. Separately the startup version record forks the audit chain on every clean-machine restore. Full evidence, file paths and the options already weighed are in #682, #697 — read them before starting, and follow the recommendation there unless the code has changed since.

**Scope**
- Prune gets a narrowly scoped privilege for that path only, the pattern `M7-DATA-BE-159a` used for reset.
- The startup record does not fork the chain after a restore.
- Tests run under a connection restricted exactly as `askwell_app` is.

**Out of Scope**
- Anything not named in #682, #697. A new problem found on the way becomes its own issue, not part of this change.

**Acceptance Criteria**
- **Acceptance Criteria:** Prune removes interactions past the window on a real install. `askwell-verify` reports an intact chain after a restore. An ordinary path still cannot DELETE from an audit table.
- **Edge Cases:** The dev database's drifted grant — corrected by migration, so dev and real installs agree.
- **Permissions / Roles:** Single user — no roles.
- **UI States:** As named in #682, #697.
- **Validation Rules:** C6: the application never rewrites history as a side effect; only the named, recorded prune may delete. Do not weaken, skip or delete an existing test to make this pass.
- **Audit / Logging Requirements:** Unchanged unless #682, #697 says otherwise. Any `constraint:*` label on #682, #697 must be answered in the closing comment: how the constraint was preserved.
- **Analytics Events:** None (C1).

**Dependencies & Assumptions**
- **Dependencies:** M7-LOG-BE-154, M7-UPDATE-FE-162, M7-BACKUP-BE-158.
- **API / Data Touchpoints:** As named in #682, #697.
- **Assumptions:** The issue's diagnosis still holds. If the code has moved on, re-verify first and say what changed.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Set retention to one month with older interactions present, prune, verify the chain. Back up, restore on a fresh stack, verify the chain.
- **Known gaps:** Close #682, #697 with what was verified, the command run and what it returned.

**Effort & Granularity Check**
- **Estimate:** 4 hours · **Priority:** Critical
- **Labels / Component:** `phase:7`, `constraint:audit`, backend
- **Granularity:** The fix named in #682, #697, and its tests.

---

### M9-FIX-SEC-209 — Redis refuses the placeholder passwords, and the licence gate refuses what it cannot read

**Type:** Task

**User Story**
- **Actor:** someone who copied `.env.example` by hand.
- **User Need:** their install to be as locked down as a generated one.
- **Business Value:** found by the release triage of 2026-09-28; without it the product does not do what it claims for a real user.

**Context / Background**
**Detailed Description:** Redis accepts the public `change-me` placeholder passwords, so a hand-copied `.env` undoes the per-service ACL. Separately the licence gate passes free-text AGPL, GPL-2.0-only and non-commercial licences it does not recognise. Full evidence, file paths and the options already weighed are in #750, #755 — read them before starting, and follow the recommendation there unless the code has changed since.

**Scope**
- The stack refuses to start with any placeholder secret, naming which.
- The licence gate treats an unrecognised licence string as a failure to review, not a pass.

**Out of Scope**
- Anything not named in #750, #755. A new problem found on the way becomes its own issue, not part of this change.

**Acceptance Criteria**
- **Acceptance Criteria:** Starting with a placeholder Redis password fails loudly. A dependency declaring 'GNU Affero' in free text fails the gate.
- **Edge Cases:** A genuinely new permissive licence the gate does not know — fails and is reviewed, which is the correct default.
- **Permissions / Roles:** Single user — no roles.
- **UI States:** As named in #750, #755.
- **Validation Rules:** C1 and C9: a default is never the insecure option. Do not weaken, skip or delete an existing test to make this pass.
- **Audit / Logging Requirements:** Unchanged unless #750, #755 says otherwise. Any `constraint:*` label on #750, #755 must be answered in the closing comment: how the constraint was preserved.
- **Analytics Events:** None (C1).

**Dependencies & Assumptions**
- **Dependencies:** M8-FIX-SEC-177, M7-DOC-DOC-163.
- **API / Data Touchpoints:** As named in #750, #755.
- **Assumptions:** The issue's diagnosis still holds. If the code has moved on, re-verify first and say what changed.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Copy `.env.example` to `.env` unchanged and bring the stack up; it must refuse.
- **Known gaps:** Close #750, #755 with what was verified, the command run and what it returned.

**Effort & Granularity Check**
- **Estimate:** 3 hours · **Priority:** Critical
- **Labels / Component:** `phase:7`, `constraint:local-first`, security
- **Granularity:** The fix named in #750, #755, and its tests.

---

### M9-FIX-BE-210 — The update check advertises only released versions

**Type:** Task

**User Story**
- **Actor:** someone who agreed to update checks.
- **User Need:** to be told about real releases only.
- **Business Value:** found by the release triage of 2026-09-28; without it the product does not do what it claims for a real user.

**Context / Background**
**Detailed Description:** The update feed reads `main`'s `VERSION`, which moves on every merged ticket, so it advertises versions that were never released. Full evidence, file paths and the options already weighed are in #699 — read it before starting, and follow the recommendation there unless the code has changed since.

**Scope**
- The feed reads published releases, not a branch.

**Out of Scope**
- Anything not named in #699. A new problem found on the way becomes its own issue, not part of this change.

**Acceptance Criteria**
- **Acceptance Criteria:** With no published release newer than the running one, no update is shown, however far `main` has moved.
- **Edge Cases:** No releases published at all — nothing shown, never an error.
- **Permissions / Roles:** Single user — no roles.
- **UI States:** As named in #699.
- **Validation Rules:** C1: the request, its destination and its payload are unchanged; only what it reads is. Do not weaken, skip or delete an existing test to make this pass.
- **Audit / Logging Requirements:** Unchanged unless #699 says otherwise. Any `constraint:*` label on #699 must be answered in the closing comment: how the constraint was preserved.
- **Analytics Events:** None (C1).

**Dependencies & Assumptions**
- **Dependencies:** M7-UPDATE-BE-161.
- **API / Data Touchpoints:** As named in #699.
- **Assumptions:** The issue's diagnosis still holds. If the code has moved on, re-verify first and say what changed.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Point the check at a repository with no newer release and confirm nothing is shown.
- **Known gaps:** Close #699 with what was verified, the command run and what it returned.

**Effort & Granularity Check**
- **Estimate:** 2 hours · **Priority:** Critical
- **Labels / Component:** `phase:7`, `constraint:local-first`, backend
- **Granularity:** The fix named in #699, and its tests.

---

### M9-FIX-DEPLOY-211 — The model settings see the real models folder, and first run names the user's own path

**Type:** Task

**User Story**
- **Actor:** someone swapping or placing a model.
- **User Need:** the settings to see the files that are there.
- **Business Value:** found by the release triage of 2026-09-28; without it the product does not do what it claims for a real user.

**Context / Background**
**Detailed Description:** The api container cannot see the models directory, so model swap, alternatives and the expected path all read a path that does not exist. First-run's manual placement names the container path (`/models/…`) rather than the folder on the user's machine. Full evidence, file paths and the options already weighed are in #660, #668 — read them before starting, and follow the recommendation there unless the code has changed since.

**Scope**
- The models directory mounted read-only into the api container.
- First run shows the host path.

**Out of Scope**
- Anything not named in #660, #668. A new problem found on the way becomes its own issue, not part of this change.

**Acceptance Criteria**
- **Acceptance Criteria:** Settings lists the model files actually present. First run's placement instruction names a folder that exists on the user's machine.
- **Edge Cases:** No models directory yet — says where to create it.
- **Permissions / Roles:** Single user — no roles.
- **UI States:** As named in #660, #668.
- **Validation Rules:** The mount is read-only; nothing in the api writes model files (C9 verification stays at selection). Do not weaken, skip or delete an existing test to make this pass.
- **Audit / Logging Requirements:** Unchanged unless #660, #668 says otherwise. Any `constraint:*` label on #660, #668 must be answered in the closing comment: how the constraint was preserved.
- **Analytics Events:** None (C1).

**Dependencies & Assumptions**
- **Dependencies:** M7-SET-BE-145a, M7-OFFLINE-DEPLOY-144.
- **API / Data Touchpoints:** As named in #660, #668.
- **Assumptions:** The issue's diagnosis still holds. If the code has moved on, re-verify first and say what changed.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Place a second model file, open Settings, and swap to it.
- **Known gaps:** Close #660, #668 with what was verified, the command run and what it returned.

**Effort & Granularity Check**
- **Estimate:** 3 hours · **Priority:** Critical
- **Labels / Component:** `phase:7`, deploy
- **Granularity:** The fix named in #660, #668, and its tests.

---

### M9-FIX-FE-212 — The trace tells taught facts from inferred ones, and the first click works

**Type:** Task

**User Story**
- **Actor:** someone reading how an answer was produced.
- **User Need:** an accurate trace and a responsive rail.
- **Business Value:** found by the release triage of 2026-09-28; without it the product does not do what it claims for a real user.

**Context / Background**
**Detailed Description:** The trace calls inferred memory facts 'facts you taught Askwell', contradicting the approved online disclosure. Separately the first rail click after a fresh load is dropped — no navigation, no request. Full evidence, file paths and the options already weighed are in #760, #665 — read them before starting, and follow the recommendation there unless the code has changed since.

**Scope**
- Inferred and taught facts labelled as what they are.
- The first rail click navigates.

**Out of Scope**
- Anything not named in #760, #665. A new problem found on the way becomes its own issue, not part of this change.

**Acceptance Criteria**
- **Acceptance Criteria:** A trace citing an inferred fact says it was inferred. The first click after load navigates every time.
- **Edge Cases:** A fact that was inferred and later confirmed — shown as taught.
- **Permissions / Roles:** Single user — no roles.
- **UI States:** As named in #760, #665.
- **Validation Rules:** Wording must agree with `docs/decisions.md` 2026-09-25's approved disclosure. Do not weaken, skip or delete an existing test to make this pass.
- **Audit / Logging Requirements:** Unchanged unless #760, #665 says otherwise. Any `constraint:*` label on #760, #665 must be answered in the closing comment: how the constraint was preserved.
- **Analytics Events:** None (C1).

**Dependencies & Assumptions**
- **Dependencies:** M5-TRACE-FE-120, M7-FIX-FE-173.
- **API / Data Touchpoints:** As named in #760, #665.
- **Assumptions:** The issue's diagnosis still holds. If the code has moved on, re-verify first and say what changed.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Load the app fresh and click Library once; then open a trace that used an inferred fact.
- **Known gaps:** Close #760, #665 with what was verified, the command run and what it returned.

**Effort & Granularity Check**
- **Estimate:** 2 hours · **Priority:** Critical
- **Labels / Component:** `phase:7`, frontend
- **Granularity:** The fix named in #760, #665, and its tests.

---

### M9-TEST-TEST-213 — Every test that exists actually runs, in any order

**Type:** Task

**User Story**
- **Actor:** whoever next trusts a green CI run.
- **User Need:** green to mean tested.
- **Business Value:** found by the release triage of 2026-09-28; without it the product does not do what it claims for a real user.

**Context / Background**
**Detailed Description:** Three web test files are never run — `setup`, `answer-annotations` and `storage` are missing from `web/package.json`'s test list. Three API tests pass or fail depending on run order: `test_sources_api` needs `/var/lib/askwell`, `test_inline_clarify` leaks a clarification cap through the settings table, and `test_provider_key`'s cleanup fails after `test_ask_online`. Full evidence, file paths and the options already weighed are in #724, #696, #706, #752 — read them before starting, and follow the recommendation there unless the code has changed since.

**Scope**
- The missing web test files run in CI.
- The order-dependent tests fixed so each passes alone and in the full suite.

**Out of Scope**
- Anything not named in #724, #696, #706, #752. A new problem found on the way becomes its own issue, not part of this change.

**Acceptance Criteria**
- **Acceptance Criteria:** Every `*.test.ts` file runs. Each named API test passes run on its own and in the full suite.
- **Edge Cases:** A test that turns out to be failing once it actually runs — fix the code if it is a real bug, not the test.
- **Permissions / Roles:** Single user — no roles.
- **UI States:** As named in #724, #696, #706, #752.
- **Validation Rules:** A test that needs something it has not got fails; it does not skip (`AGENTS.md` §6). Do not weaken, skip or delete an existing test to make this pass.
- **Audit / Logging Requirements:** Unchanged unless #724, #696, #706, #752 says otherwise. Any `constraint:*` label on #724, #696, #706, #752 must be answered in the closing comment: how the constraint was preserved.
- **Analytics Events:** None (C1).

**Dependencies & Assumptions**
- **Dependencies:** M0-FOUND-TEST-005.
- **API / Data Touchpoints:** As named in #724, #696, #706, #752.
- **Assumptions:** The issue's diagnosis still holds. If the code has moved on, re-verify first and say what changed.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Run each named test file on its own, then the full suites.
- **Known gaps:** Close #724, #696, #706, #752 with what was verified, the command run and what it returned.

**Effort & Granularity Check**
- **Estimate:** 3 hours · **Priority:** Critical
- **Labels / Component:** `phase:7`, test
- **Granularity:** The fix named in #724, #696, #706, #752, and its tests.

---
### M9-REL-DEPLOY-214 — Downloadable releases for Linux, Windows and macOS, built in CI

**Type:** Task

**User Story**
- **Actor:** someone who wants to try Askwell and has never heard of Podman or cargo.
- **User Need:** a download for their operating system.
- **Business Value:** the product owner has authorised a release once the build is done (`../decisions.md`, 2026-09-28). Nothing today produces anything to release: `web/src-tauri/tauri.conf.json` has `"bundle": {"active": false}`, and no workflow runs `cargo tauri build`.

**Context / Background**
**Detailed Description:** Issue #559 has the full analysis. Its recommendation was Linux-only; widen it to all three platforms, because GitHub Actions provides Linux, Windows and macOS runners and this build host has only Linux. The build then produces the Windows and macOS downloads without that hardware, and the product owner will test them by hand once the build is done.

A workflow triggered by a version tag (and runnable by hand) that, per platform, builds the Tauri shell with bundling enabled, exports the container images, and assembles the artefact tree each installer (`M7-PACK-DEPLOY-139`/`140`/`141`) already expects, then generates `SHA256SUMS` with `scripts/release-checksums.sh`. Unsigned, as decided. Model weights are not bundled; the installers fetch or place them as they already do (`M7-OFFLINE-DEPLOY-144`).

**Scope**
- A release workflow with a Linux, a Windows and a macOS job.
- Tauri bundling enabled; unsigned.
- Container images exported alongside, in the layout the installers expect.
- Checksums generated; artefacts attached to a **draft** GitHub release. The workflow never publishes on its own.

**Out of Scope**
- Signing or notarisation (decided against, 2026-09-28).
- Publishing. A person, or the orchestrating session on instruction, turns the draft into a release.
- Bundling model weights.

**Acceptance Criteria**
- **Acceptance Criteria:** Running the workflow on a test tag produces a draft release with one artefact per platform and a `SHA256SUMS` that verifies them. The Linux artefact installs on a clean Linux account with `deploy/linux/install.sh` and reaches a working Ask screen.
- **Edge Cases:** One platform's job fails — the draft is not created with a partial set; the failure names the platform. A re-run for the same tag — replaces the draft rather than duplicating it.
- **Permissions / Roles:** Single user — no roles.
- **UI States:** None.
- **Validation Rules:** No secret in the workflow beyond GitHub's own token (C8). Nothing is published automatically (`AGENTS.md` §7).
- **Audit / Logging Requirements:** None.
- **Analytics Events:** None (C1). The built app still makes no outbound call.

**Dependencies & Assumptions**
- **Dependencies:** M7-PACK-DEPLOY-139, M7-PACK-DEPLOY-140, M7-PACK-DEPLOY-141, M7-OFFLINE-DEPLOY-144.
- **API / Data Touchpoints:** `.github/workflows/`; `web/src-tauri/tauri.conf.json`; `scripts/release-checksums.sh`; `docs/release-procedure.md` §2 and §5.
- **Assumptions:** GitHub-hosted macOS and Windows runners are available to this repository. If they are not, say so and build Linux only, rather than faking the other two.

**Testing Notes / Scenarios**
- **Cold-start manual walkthrough:** Run the workflow on a throwaway tag, download the Linux artefact to a clean account, verify its checksum, install it, and ask a question. Delete the throwaway draft afterwards.
- **Other scenarios:** Break the Windows job deliberately and confirm no partial draft appears.
- **Known gaps:** The Windows and macOS artefacts are built but not proven to install until the product owner's own testing (#590, #592). Close #559 with what was verified.

**Effort & Granularity Check**
- **Estimate:** 6 hours · **Priority:** Critical
- **Labels / Component:** `phase:7`, deploy
- **Granularity:** One workflow, three jobs, one draft release.

---
