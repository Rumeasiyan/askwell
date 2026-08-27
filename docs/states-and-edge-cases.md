# States and edge cases

The behaviours `docs/PRD.md` specifies, expressed as **states a user can actually be in**. The PRD says what Askwell does when things work and states several rules about what it must not do. This document covers the rest: empty, loading, partial, denied, expired, degraded, and failed.

This is the document that separates a demo from a product. It exists because "the system abstains when retrieval is below threshold" (C5) is a rule, and "the user sees a screen saying their files do not cover this, naming what to add" is a product.

**How to use this:** every screen spec must account for the states listed for its surface. A screen design that only shows the happy path is not finished.

Every product decision this document surfaced has now been answered — see §8. When you find a new state, add it here; if it needs a decision, file it rather than picking a default.

---

## 1. Global states

Apply on every surface.

| State | What the user sees | What the system does |
| ----- | ------------------ | -------------------- |
| **Offline / no network, local mode** | Nothing. No indicator, no banner | This is the design point, not a degraded state. **Never render an offline warning** — it implies something is broken when the product is working exactly as promised (C1) |
| **Web search asked for, one question** | Named progress while the question is out; results in their own marked region; a closing note that the next question starts local | C10. Offered only after abstention, never fired automatically — that rule is what keeps abstention meaningful |
| **Web search unavailable** — offline or provider down | *"I can't reach the web right now."* The abstention still stands and is still the answer | Failing to escalate is not failing to answer. The honest answer was already given |
| **Online AI enabled for a conversation** | Clear, persistent marker on that conversation, and a statement of what will be sent *before* the first send | C1. The user must never discover after the fact that content left the machine |
| **Online credits exhausted** | The conversation falls back to local AI, saying so plainly. Nothing is lost | Refusing to answer because credit ran out, on a product that works offline for free, would be absurd |
| **First launch, nothing configured** | Guided setup: add a first source, wait for indexing, ask a first question | Install-to-first-answer is the metric most likely to kill the product (`success-metrics.md` §4) |
| **Model still downloading** | Progress with a realistic estimate. Everything else remains usable | On a slow connection this dominates first-run time |
| **Model not loaded / llm container down** | "The assistant is unavailable", with a fix path. Document browsing and search still work | Retrieval does not need the LLM. Degrade to search, not to a blank product |
| **Passphrase set, app restarted** | Prompt for the passphrase before anything decrypts | Optional feature; when on, it is what makes a stolen laptop not a data breach |
| **Log storage at 80% of budget** | Persistent dismissible notice offering export, archive or prune | `audit-log.md` §3 |
| **Log storage at hard limit** | **New ingestion refused**; asking questions keeps working | Ingestion is the biggest writer. Blocking the cheapest and most valuable operation last is what keeps the product usable |
| **Decisions store cannot be written** | The action fails, with a clear reason and what to free up | Issue #10, Option A — the only place a write failure stops an action |
| **Disk full** | Adding sources refused with a clear message. Existing material stays queryable | Never accept a source that cannot be durably written |

| **Narrow window** | Left rail becomes a drawer, reachable from a control in the app's own chrome | Hiding navigation without a way back strands the user in a product where the library is the only route to sources, memory and settings |
| **Native file dialog open** | The Tauri shell's own picker, for nominating a root directory or relocating a moved file | Indexing in place makes both core paths, and neither works well in a browser tab |

There is no licence state, no seat cap, no session expiry and no permission denial. The product is free, single-user and local — none of those states exist.

## 2. Asking a question — chat

The core loop. Most of these states are reachable in the first five minutes of use.

| State | What the user sees | Why it matters |
| ----- | ------------------ | -------------- |
| **First run, empty corpus** | Not an empty chat box. A first-run state that says no documents are ingested yet, what Askwell will be able to answer once files are added, and a direct path to add the first one | An empty chat box invites a question that will abstain, which teaches the user in their first 30 seconds that the product does not work |
| **Thinking / retrieving** | Streamed progress naming the step: searching documents, reading N sources, querying the database | On the `light` profile a question can take 20s+. A silent spinner for 20 seconds reads as broken |
| **Answering** | Token streaming. Citations render as they are emitted, not appended at the end | — |
| **Abstention — nothing above threshold** | An explicit "I don't know" state, visually distinct from an answer. States what was searched, and what would need to be added to answer it, with a path to add it. **Never a hedged half-answer** | C5. This is a first-class product state, not an error. It is the state most likely to be quietly degraded later by lowering the threshold — see `docs/success-metrics.md` §2 |
| **Partial retrieval** — some claims grounded, some not | Answer the grounded part; say plainly which part is not covered | The tempting failure is to smooth over the gap in fluent prose. C4 and C5 both forbid it |
| **Tool-call ceiling hit (8 calls)** | Return what was gathered, with an explicit note that it stopped early and why. Offer to continue as a new turn | `architecture.md` §10. Silently truncating reasoning and presenting the result as complete is worse than saying it stopped |
| **Conflicting sources** | Present both, with both citations and their dates. Do not silently prefer one | `build-plan.md` quality gate has a whole eval category for this (10 tasks, ≥ 0.75); it needs a UI, not just model behaviour |
| **Superseded document** | Answer from the current version, stating "as of the June revision" | `data-sources.md` §1 requires this explicitly |
| **Question in a language other than English** | Say the product is English-only in this version. Do not attempt a poor answer | v1 is English-only (`PRD.md` §8). The `tam` OCR hedge means Tamil text may be *in* the corpus; that must not be mistaken for Tamil support |
| **Retrieved content contains instruction-like text** | Answer normally; the trace flags it | C7. Flagged in the trace, not shown as a scary warning — this is a mitigation, not a detection system, and PRD §8 says to document the residual risk honestly rather than overclaim |
| **Very long answer** | Stream, do not truncate silently. If a limit is hit, say so | — |
| **User navigates away mid-answer** | Generation continues server-side and the answer is saved to the conversation | Issue #14, Option A. Costs local compute on an abandoned question — fan noise on a laptop, not a queue, since there is no other user waiting |

---

## 3. Documents and ingestion

| State | What the user sees | What the system does |
| ----- | ------------------ | -------------------- |
| **Add in progress** | Per-file progress. Navigating away does not cancel it | Ingestion is a background job (`arq`), not a request. Not an *upload*: nothing is copied anywhere |
| **A drop being read** | The count and total size at once, then "N of M" as each file's type is worked out | Only the first 4 KB of each file is read, in chunks that hand the window back — a folder of several thousand files must not freeze it |
| **A second drop while one is being read** | Queued behind the first, with its own count | Rejecting it would punish the user for Askwell being busy with their previous instruction |
| **A file named one thing and containing another** | Routed by its contents, with the disagreement stated in the name they gave it | Silence here loses a fact worth having: one of their documents is not what it says it is |
| **A program dropped among documents** | Refused by name, with the fact that nothing was run | The same instinct as C3's sandbox, applied where nothing is executed at all |
| **More files in one drop than the cap** | The number taken, and that the rest were left | A cap that truncates silently reads as "everything was added" |
| **Files queued but nothing indexed yet** | Said plainly, with what has to land before they are searchable | An honest sentence, not a progress bar that never moves |
| **Queued behind a backlog** | Position and a realistic estimate | Embedding a large corpus on CPU takes hours. An untimed spinner suggests a hang |
| **Extraction failed** (corrupt, encrypted, password-protected PDF) | The document is listed as failed with the reason. Retry available | Never silently drop it (AGENTS.md §6) |
| **PDF with no text layer anywhere, waiting on OCR** | Said plainly, naming `M1-EXTRACT-ING-028` — not failed, not indexed empty | `extract` (`M1-EXTRACT-ING-026`) detects it and parks rather than chunking nothing, which would tell retrieval a scanned contract has no content |
| **PDF with a text layer on some pages and not others** | Proceeds normally; the blank pages are recorded, not silently skipped | Per-page, not per-document — one scanned exhibit inside an otherwise digital contract must not block the rest, and the blank pages are what `M1-EXTRACT-ING-028` later reads to know which ones it owns |
| **Scanned, OCR produced little or no text** | Flag as low-confidence. It is ingested but marked; it will retrieve poorly | Distinct from failure. The document exists but is nearly invisible to search, and the user needs to know |
| **Scanned Tamil document** | Ingests via the bundled `tam` traineddata; marked as not-supported-language | `PRD.md` §8 — a hedge, not a feature. It must not appear as Tamil support |
| **Unsupported format** | Rejected **per file**, naming the file and what its contents turned out to be, with the supported list once beneath. The rest of the drop proceeds | `data-sources.md` §1 lists formats. Per file, not per drop: one archive among sixty contracts must not take the contracts with it |
| **A format whose route arrives in a later milestone** (CSV, dump) | Named as **arriving**, with the milestone — not as unsupported, and never queued | Recognised and not-yet-built are different facts. Told "unsupported", somebody whose material is mostly exports concludes the product is not for them, which is false |
| **A drop that expands to no files at all** | Said plainly: an empty folder, nothing changed, and the supported list | An empty folder is a real gesture and deserves an answer. A cancelled file dialog produces the same empty list and must stay silent — the folder count is what tells them apart |
| **Duplicate (same sha256)** | Named as already present, linked to the existing document. Not re-ingested | `documents.sha256` exists in `architecture.md` §7 for this |
| **The same content under two names** | Both paths shown — the one indexed and the one recognised — so it is clear which copy Askwell is reading | Recognition is by content across every source, because the same contract in three folders is three sources. "Already present" without saying *where* leaves someone with three copies no better off |
| **An empty file** | Rejected by name with the reason, and the rest of the drop carries on | There is nothing to index. Detected on the size rather than on the head: a head is a slice, and every empty file and every large one look alike through one |
| **A drop where every file was already indexed** | "Nothing new here" — nothing added, nothing changed on disk, library unchanged | Not "0 files queued". A count of zero next to the word *Queued* reads as a failure, and nothing failed |
| **A file that changes while Askwell is reading it** | Re-read. If it never settles, reported per file — something else is still writing to it — and nothing is recorded | A hash taken across a file being written names bytes nobody will ever read again. The identity is checked before and after the read, and the attempts are bounded so a log being appended to does not stall a whole drop |
| **New version of an existing document** | Marked superseding the old one; the old one stays queryable for history | `data-sources.md` §1: supersede, do not duplicate |
| **Embedding job failed after retries** | Visible in the library with the error and a retry | AGENTS.md §6, explicitly |
| **Document deleted** | Old citations resolve to "deleted on `<date>`" rather than breaking | Issue #11, Option A — tombstone. Content and embedding are cleared so it stops influencing retrieval; the row survives so the audit chain and old citations still resolve |
| **Empty collection** | Empty state naming what it is for and how to add to it | — |
| **File outside every nominated folder** | Asked to nominate its folder, with the consequence explained. Not a bare rejection | Askwell indexes in place, so it has to be told which folders it may open. `ux/add-source.md` §7 |
| **Folder nominated, not yet mounted** | Accepted, with the configuration line and that the stack has to come up again — said now, not discovered | A container's mounts cannot be changed while it runs. Refusing would make a fresh install unable to nominate anything |
| **Nominated folder not connected** | Its sources report **unavailable**: a drive unplugged, a share disconnected | **Never rendered as deleted, and never as moved.** A whole folder being absent is not forty files having moved, and offering to relocate each would be forty wrong questions |
| **Nominated folder cannot be read** | Named, with its permissions and SELinux labelling as the two causes | Root inside the image ignores the mode bits, so this is the case that actually bites on a Linux host |
| **Nominated folder removed** | Its sources stay listed, saying the folder was removed and that nothing was deleted | The registry tombstones rather than deletes, so "you removed this" is distinguishable from "no folder ever covered this" |
| **Folder is a network share** | Permitted, warned: indexing is slow, and the share must be connected for a citation to reopen its page | Refusing would exclude a real way of working; saying nothing would surprise someone hours in |

---

## 4. Database question-answering

Highest-risk surface. The customer's production database is on the other side.

| State | What the user sees | What the system does |
| ----- | ------------------ | -------------------- |
| **No connections configured** | Empty state; database questions say so rather than abstaining generically | Abstaining as if the corpus lacks it is misleading — the data exists, it just is not connected |
| **Connection wizard: credentials pass the write probe** | Refused, naming which permission was detected | `data-sources.md` §4 — the wizard refuses write-capable credentials. Not a warning, a refusal |
| **Connection dead at query time** | "The database is unreachable", not a generic failure. Admins see the connection error | Customer DBs go down independently of Askwell |
| **Generated SQL rejected by `sqlglot`** | The user sees a normal "I could not answer that safely" and the SQL is **shown**, since disclosure is unconditional | C2. The rejection is logged with the offending SQL — this is the signal that a prompt change has degraded generation, and it must be visible |
| **`EXPLAIN` dry-run fails** | Same as above; the query is not executed | `data-sources.md` §4 |
| **Query exceeds `statement_timeout` (30s)** | "The query took too long", with the SQL and a suggestion to narrow it | `data-sources.md` §4 layer 4 |
| **`LIMIT` auto-injected** | Result is labelled as showing the first N of possibly more, with the injected limit visible in the SQL | `data-sources.md` §4 layer 3. A silently truncated result an analyst believes is complete is a wrong answer with no warning attached |
| **Zero rows** | "No matching records" — with the SQL, so the analyst can see whether the question or the query was wrong | Distinct from an error and from abstention |
| **Very large result** | Paginated, with the row count | — |
| **Schema drift** — annotated table or column no longer exists | Admin console flags stale annotations | Otherwise the model is prompted with a schema that no longer matches reality |

---

## 5. Voice

| State | What the user sees / hears | Notes |
| ----- | -------------------------- | ----- |
| **Microphone permission denied** | Voice mode disabled with an explanation and a path to re-enable in the browser | Browser permission, not something Askwell can fix |
| **No speech detected** | Silent timeout back to idle. No error sound | Silero VAD (`build-plan.md` Phase 5) |
| **STT confidence low** | Show the transcription and ask for confirmation before answering | Answering the wrong question confidently is worse than one extra tap |
| **TTS unavailable** | Answer is delivered as text with a note that the voice is unavailable | Voice is a mode, not a separate product (`build-plan.md` Phase 5) — falling back to text is correct |
| **WebSocket drops mid-turn** | Reconnect; if the answer completed server-side, deliver it in the conversation | The turn is in the audit log regardless |
| **Latency budget missed** | An indicator appears, only once the budget is already passed | Issue #15, Option B. Costs nothing on a healthy turn; prevents the user concluding it has hung and retrying |
| **User speaks over the answer** | No barge-in. A visible stop control ends the answer | Issue #13, Option B — solves "I cannot escape this answer" at a fraction of the cost |

---

## 6. Settings, memory and the log

There is no administrator. These are the user's own settings.

| State | What the user sees | Notes |
| ----- | ------------------ | ----- |
| **Pending clarifications waiting** | A count, not a modal. Reviewable whenever they choose | Never block on questions (`memory-and-clarification.md` §2) |
| **Clarification answered** | Confirmation of what changed, and that affected material is being re-processed | The user must see that answering did something, or they stop answering |
| **Memory inspection** | Every fact Askwell believes, with origin, date and an edit or delete control | A memory the user cannot inspect is a system that gets mysteriously worse and cannot be debugged |
| **Memory fact superseded** | Old value visible in history, not erased | Corrections supersede; they never overwrite |
| **Log export, large range** | Background job with progress and a download when ready | A year of interactions is not a synchronous operation |
| **Log verification finds a broken hash chain** | Reported plainly, naming where the chain breaks | C6 is tamper-*evident*. This is that evidence, and it must be surfaced, not swallowed |
| **Model swap in progress** | Assistant unavailable with expected duration. Retrieval still works | — |
| **Hardware below the `light` floor at install** | Warned, with what to expect, and allowed to continue | **Warn, do not refuse.** Refusing made sense for a paid deployment that could be blamed on the vendor; for a free download it is just a lost user |
| **Abstention rate rising** | Surfaced with the unanswered questions driving it | That list is what to add next |

## 7. Empty states, collected

Every one of these is a real screen someone will see on day one, and each is an opportunity to teach the product rather than show a blank box:

| Surface | Empty state must say |
| ------- | -------------------- |
| Chat, no corpus | Nothing ingested yet; what will be possible once it is |
| Document list | What a collection is for; how to upload |
| Collection, no documents | Same, scoped |
| Database connections | What connecting enables; that credentials must be read-only |
| Memory, before anything is learned | What the clarification loop will do, and that answering questions makes answers better |
| Conversation history | — |
| Audit log, filtered to nothing | Distinguish "no events" from "filter excludes everything" |
| Usage dashboard, pre-traffic | What will appear once questions are asked |

---

## 7.1 Conversation states

| State | What is shown |
| ----- | ------------- |
| **Past turn collapsed** | Question, one-line summary, source count in the provenance colour |
| **Past turn that abstained** | Collapsed with **no source count**, summary saying so — visibly different at a glance |
| **Past turn that used the web** | Keeps its web marker when collapsed. Never shown as if it came from the user's files |
| **Past turn citing a deleted source** | Count reflects what was cited then; expanding shows the tombstone |
| **New question while an answer streams** | Queued, not interleaved |

## 8. Decisions this document surfaced — all now answered

| Was | Answer | Issue |
| --- | ------ | ----- |
| Audit write failure — proceed unlogged or fail? | Fail the action, but only the tiny decisions store carries that guarantee; traces fail open (`audit-log.md`) | [#10](https://github.com/Rumeasiyan/askwell/issues/10) |
| Document deletion vs audit immutability | Tombstone | [#11](https://github.com/Rumeasiyan/askwell/issues/11) |
| Restricted columns — acknowledge or conceal? | Moot. Single-user removed roles entirely | [#12](https://github.com/Rumeasiyan/askwell/issues/12) |
| Voice barge-in in v1? | No. Stop control instead | [#13](https://github.com/Rumeasiyan/askwell/issues/13) |
| Generation on navigate-away | Continue server-side | [#14](https://github.com/Rumeasiyan/askwell/issues/14) |
| Voice latency-miss indicator | Yes, past budget only | [#15](https://github.com/Rumeasiyan/askwell/issues/15) |

**When you find a new state this document does not list, add it here in the same change** — and if it needs a product decision, file it rather than picking a default.
