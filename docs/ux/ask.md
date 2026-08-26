# Screen: Ask

The core loop and the screen that decides whether anyone keeps Askwell. Everything else supports it.

> **This document is the specification. Any mockup is a reference.** Where they disagree, this wins, or the mockup is wrong and gets redrawn.

**Route:** `/` — also the first screen after setup.
**Entry points:** app launch, "Ask about this" from a source, keyboard `⌘K` from anywhere.

---

## 1. What it is for

One person asking questions about their own files and getting answers they can check.

Success is that they trust the answer enough to act on it without opening the source — while always being able to. Those pull against each other, and the provenance margin is how both are served at once: the evidence is present without being in the way.

---

## 2. Layout

Three columns (`design-system.md` §4). Left: sources, memory, settings. Centre: the conversation, 68–75ch. Right: the provenance margin, 300px.

The margin is the point. It is populated or explicitly empty; it is never hidden and never collapses to a toggle.

---

## 3. Data on screen

| Element | Source |
| ------- | ------ |
| Answer prose | Agent output, streamed |
| Source cards | `chunks` joined to `documents` — filename, page, heading, exact passage |
| Memory facts used | `memory` / `schema_notes` retrieved for this turn |
| Generated SQL | The validated query, always shown for a database answer |
| Trace | Per-step record behind "How did you get this?" |
| Backend marker | `local` or `online` for this conversation |

---

## 4. Interactions

| Action | Result |
| ------ | ------ |
| Type, `Enter` | Submit. `Shift+Enter` newline |
| **Mic control** | Opens voice mode (`voice.md`). Present from Phase 1, disabled with its reason until Phase 5 — the composer is not rebuilt later to make room for it |
| Hover a cited claim | Its leader and card raise |
| Click a claim or card | Opens the source at that page, passage highlighted |
| Click a memory chip | Popover: the fact, its origin, **Correct** and **Delete** |
| **Correct** | Inline edit; on save supersedes the fact and re-processes what depends on it |
| Expand SQL | Full query, `LIMIT` visible if injected |
| "How did you get this?" | Trace panel |
| Stop | Ends generation; partial answer kept and marked partial |
| Navigate away mid-answer | Generation continues server-side and completes (#14) |

### Suggested follow-ups

Up to three, after an answer, derived from what was just answered. They **fill the composer rather than sending** — the point is to lower the cost of the next question, not to ask it for the user. Specified in `conversation.md` §3.

### Correction from inside the answer

When an answer used a memory fact, it appears as a chip: `st_cd = student status code`. Clicking it offers correction in place.

This is the highest-value interaction in the product and must not be moved to a settings screen. The moment a user notices Askwell is wrong is the only moment they will reliably fix it, and it is here. Making them navigate elsewhere means it never gets fixed and the wrong fact poisons every later answer.

---

## 5. States

Every one of these ships. A screen with only the answered state is not finished.

| State | What is shown |
| ----- | ------------- |
| **First run, no sources** | Not an empty chat box. What Askwell will be able to answer once files are added, and one action: **Add your first source**. An empty input invites a question that will abstain, teaching the user in thirty seconds that the product does not work |
| **Empty, sources exist** | Input focused, plus three questions generated from what was actually ingested — real filenames, real column names. Not generic prompts |
| **Retrieving** | Named steps: *searching your files · reading 4 sources · querying `sales`*. On a slow local model this can run 20s+, and an unlabelled spinner reads as broken |
| **Streaming** | Tokens appear at their real pace. Cards enter the margin as claims are cited, leader drawing on arrival |
| **Answered** | Full answer, populated margin, memory chips, trace available |
| **Abstained** | See §6. The escalation offer renders below it, never above (`web-search.md` §2) |
| **Partial** | Grounded part answered; the ungrounded part named explicitly as not covered. Never smoothed into fluent prose |
| **Conflicting sources** | Both presented with both citations and their dates. Never silently prefers one. Offers to resolve, which writes a memory fact |
| **Tool ceiling hit** | What was gathered, plus a note that it stopped after 8 steps, plus **Continue** |
| **Inline clarification** | When the answer depends on an unresolved ambiguity, ask here, in the conversation. The one place a clarification interrupts |
| **Model unavailable** | "The assistant is unavailable." Search across sources still works — degrade to search, not to a blank product |
| **Deleted source cited** | Card renders as *deleted on 3 June*, greyed, not clickable (#11) |
| **Unvalidated model** | Persistent marker on every answer produced by a user-supplied model, naming that citations and abstention are unverified for it. Not an error state — the user chose this knowingly (`settings.md` §2) |
| **Answered from the web** | Separate region, marked as not-your-material, never in the margin (`web-search.md` §3) |
| **Several turns** | Past turns collapse (`conversation.md`). The live turn keeps its margin |
| **Online mode** | Persistent marker on the conversation. Before the first send, exactly what will leave the machine |
| **Credits exhausted** | Falls back to local, says so, continues. Never blocks — the product works offline for free |
| **Past latency budget (voice)** | Indicator appears, only once passed (#15) |
| **Non-English question** | States that Askwell handles English in this version. Does not attempt a poor answer |

---

## 6. Abstention

The most important state on the screen, and the one most likely to be quietly degraded later.

**Rendering.** Full measure, generous space, `--ink` and `--muted`. Not an error colour, not a small grey note, not an inline caveat. The margin renders its empty state: *no sources — nothing in your files matched*.

**Copy.**

> **Nothing in your files answers this.**
> I searched 1,240 passages across 38 documents and 2 databases. The closest material was about *supplier onboarding*, which does not cover payment terms.
> Add the source you'd expect this in, and ask again.

Three jobs: state the situation, prove the search actually happened, give the next action. The middle part is what stops abstention feeling like a shrug — a user who sees what *was* searched believes the tool tried.

**Never:** apologise, hedge into a partial guess, offer a general-knowledge answer "in case it helps", or colour it as a failure.

**Design pressure to resist.** This state will attract requests to soften it, and the softening is always the same: let the model answer anyway with a caveat. That breaks C5. If abstention rate is complained about, the fix is ingestion or the threshold — and lowering the threshold is itself tracked as a failure signature (`../success-metrics.md` §2).

---

## 7. Performance

| Budget | Target |
| ------ | ------ |
| First step label visible | < 400ms of submit |
| First answer token | < 3s on `standard` |
| Full answer p50 | < 20s |

Past 20s the retrieval labels keep updating so progress stays visible. The user must always be able to tell "working" from "hung" — that distinction decides whether they wait or give up.

---

## 8. Open

1. **Suggested questions on the empty state** need generating from the corpus without an expensive model call at load.
2. **Long conversations** — when the margin has fifty cards, does it scroll with the conversation or virtualise per answer? Affects the leader geometry.
