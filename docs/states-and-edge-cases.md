# States and edge cases

The behaviours `docs/PRD.md` specifies, expressed as **states a user can actually be in**. The PRD says what VaultQ does when things work and states several rules about what it must not do. This document covers the rest: empty, loading, partial, denied, expired, degraded, and failed.

This is the document that separates a demo from a product. It exists because "the system abstains when retrieval is below threshold" (C4) is a rule, and "the officer sees a screen that says the corpus does not cover this, with a button that tells the administrator what to ingest" is a product.

**How to use this:** every screen spec in Phase 2 must account for the states listed for its surface. A screen design that only shows the happy path is not finished.

Rows marked **⚠ DECISION** have no answer in the PRD and need one. They are collected in §8.

---

## 1. Global states

Apply on every surface.

| State | What the user sees | What the system does | Audit |
| ----- | ------------------ | -------------------- | ----- |
| **Air-gapped, normal** | Nothing. No indicator, no "offline mode" banner | This is the design point, not a degraded state. **Never render an offline warning** — it implies something is broken when the product is working exactly as sold (C1) | — |
| **Licence valid** | Nothing | — | — |
| **Licence expired, within 30-day grace** | Persistent but dismissible banner: read-only, days remaining, who to contact. Questions still work | Reads allowed. Ingestion, connection changes, and user management blocked. PRD §2 — a ministry losing access mid-week because a PO moved slowly is how the account is lost | Log entry on entering grace |
| **Licence expired, past grace** | Login blocked for all but `admin` and `auditor`. Audit log remains exportable | **The audit log must stay readable and exportable after expiry.** Withholding an auditor's records over a billing dispute is indefensible | Log entry |
| **Seat cap exceeded** | Administrator sees it on the user list; new logins for over-cap users are refused with a message naming the cap | Existing sessions are not killed mid-question | Log entry |
| **Session expired** | Return to login with the current question preserved and restored after re-auth | Losing a typed question to a token expiry is a small thing that makes people stop trusting the tool | — |
| **RBAC denial** | "You do not have access to this" — **never** a 404 pretending the thing does not exist | Officers must be able to tell the administrator what to grant them | Log entry with user, resource, role |
| **Model not loaded / llm container down** | "The assistant is unavailable" with the admin console linked for admins. Document browsing and search still work | Retrieval does not depend on the LLM. Degrade to search rather than a blank product | Log entry |
| **Disk full** | Uploads refused with a clear message. Existing corpus stays queryable | Never accept an upload that cannot be durably written | Log entry, admin alert |

---

## 2. Asking a question — chat

The core loop. Most of these states are reachable in the first five minutes of use.

| State | What the user sees | Why it matters |
| ----- | ------------------ | -------------- |
| **First run, empty corpus** | Not an empty chat box. A first-run state that says no documents are ingested yet, what VaultQ will be able to answer once they are, and — for admins — a direct path to upload | An empty chat box invites a question that will abstain, which teaches the user in their first 30 seconds that the product does not work |
| **Thinking / retrieving** | Streamed progress naming the step: searching documents, reading N sources, querying the database | On the `edge` profile at ~8 tok/s a question can take 20s+. A silent spinner for 20 seconds reads as broken |
| **Answering** | Token streaming. Citations render as they are emitted, not appended at the end | — |
| **Abstention — nothing above threshold** | An explicit "I don't know" state, visually distinct from an answer. States what was searched, and what would need to be ingested to answer it. For admins, a path to upload it. **Never a hedged half-answer** | C4. This is a first-class product state, not an error. It is the state most likely to be quietly degraded later by lowering the threshold — see `docs/success-metrics.md` §2 |
| **Partial retrieval** — some claims grounded, some not | Answer the grounded part; say plainly which part is not covered | The tempting failure is to smooth over the gap in fluent prose. C3 and C4 both forbid it |
| **Tool-call ceiling hit (8 calls)** | Return what was gathered, with an explicit note that it stopped early and why. Offer to continue as a new turn | PRD §4.3. Silently truncating reasoning and presenting the result as complete is worse than saying it stopped |
| **Conflicting sources** | Present both, with both citations and their dates. Do not silently prefer one | PRD §7 has a whole eval category for this (10 tasks, ≥ 0.75); it needs a UI, not just model behaviour |
| **Superseded document** | Answer from the current version, stating "as of the June revision" | PRD §4.1 requires this explicitly |
| **Question in an unsupported language** | Say the product is English-only in this version. Do not attempt a poor answer | v1 is English-only (PRD §1.2). The `tam` OCR hedge means Tamil text may be *in* the corpus; that must not be mistaken for Tamil support |
| **Retrieved content contains instruction-like text** | Answer normally; the trace flags it | C6. Flagged in the trace, not shown as a scary warning — this is a mitigation, not a detection system, and PRD §8 says to document the residual risk honestly rather than overclaim |
| **Very long answer** | Stream, do not truncate silently. If a limit is hit, say so | — |
| **User navigates away mid-answer** | ⚠ **DECISION** — does generation continue and complete server-side, or abort? | Continuing costs scarce CPU on `edge`; aborting loses the answer and the audit record is incomplete |

---

## 3. Documents and ingestion

| State | What the user sees | What the system does |
| ----- | ------------------ | -------------------- |
| **Upload in progress** | Per-file progress. Navigating away does not cancel it | Ingestion is a background job (`arq`), not a request |
| **Queued behind a backlog** | Position and a realistic estimate | Embedding a large corpus on CPU takes hours. An untimed spinner suggests a hang |
| **Extraction failed** (corrupt, encrypted, password-protected PDF) | The document is listed as failed with the reason. Retry available | Never silently drop it (AGENTS.md §6) |
| **Scanned, OCR produced little or no text** | Flag as low-confidence. It is ingested but marked; it will retrieve poorly | Distinct from failure. The document exists but is nearly invisible to search, and the admin needs to know |
| **Scanned Tamil document** | Ingests via the bundled `tam` traineddata; marked as not-supported-language | PRD §1.2 — a hedge, not a feature. It must not appear as Tamil support |
| **Unsupported format** | Rejected at upload with the supported list | PRD §4.1 lists formats |
| **Duplicate (same sha256)** | Named as already present, linked to the existing document. Not re-ingested | `documents.sha256` exists in PRD §6 for this |
| **New version of an existing document** | Marked superseding the old one; the old one stays queryable for history | PRD §4.1: supersede, do not duplicate |
| **Embedding job failed after retries** | Visible in the admin console with the error and a retry | AGENTS.md §6, explicitly |
| **Document deleted** | ⚠ **DECISION** — do past answers citing it break, keep a tombstone, or is deletion blocked while cited? | Audit immutability (C5) means the citation in the audit record cannot be erased. What the user sees when clicking it is undefined |
| **Empty collection** | Empty state naming what it is for and how to add to it | — |

---

## 4. Database question-answering

Highest-risk surface. The customer's production database is on the other side.

| State | What the user sees | What the system does |
| ----- | ------------------ | -------------------- |
| **No connections configured** | Empty state; database questions say so rather than abstaining generically | Abstaining as if the corpus lacks it is misleading — the data exists, it just is not connected |
| **Connection wizard: credentials pass the write probe** | Refused, naming which permission was detected | PRD §4.2 — the wizard refuses write-capable credentials. Not a warning, a refusal |
| **Connection dead at query time** | "The database is unreachable", not a generic failure. Admins see the connection error | Customer DBs go down independently of VaultQ |
| **Generated SQL rejected by `sqlglot`** | The user sees a normal "I could not answer that safely" and the SQL is **shown**, since disclosure is unconditional | C2. The rejection is logged with the offending SQL — this is the signal that a prompt change has degraded generation, and it must be visible |
| **`EXPLAIN` dry-run fails** | Same as above; the query is not executed | PRD §4.2 flow |
| **Query exceeds `statement_timeout` (30s)** | "The query took too long", with the SQL and a suggestion to narrow it | PRD §4.2 safety layer 4 |
| **`LIMIT` auto-injected** | Result is labelled as showing the first N of possibly more, with the injected limit visible in the SQL | PRD §4.2 safety layer 3. A silently truncated result an analyst believes is complete is a wrong answer with no warning attached |
| **Zero rows** | "No matching records" — with the SQL, so the analyst can see whether the question or the query was wrong | Distinct from an error and from abstention |
| **Restricted columns stripped** | The answer does not mention them. ⚠ **DECISION** — is the user told restricted columns exist? | C7 says the model cannot see them. Telling the user "3 columns are hidden from you" leaks their existence; not telling them means a confusing incomplete answer |
| **Very large result** | Paginated, with the row count | — |
| **Schema drift** — annotated table or column no longer exists | Admin console flags stale annotations | Otherwise the model is prompted with a schema that no longer matches reality |

---

## 5. Voice

| State | What the user sees / hears | Notes |
| ----- | -------------------------- | ----- |
| **Microphone permission denied** | Voice mode disabled with an explanation and a path to re-enable in the browser | Browser permission, not something VaultQ can fix |
| **No speech detected** | Silent timeout back to idle. No error sound | Silero VAD (PRD §4.4) |
| **STT confidence low** | Show the transcription and ask for confirmation before answering | Answering the wrong question confidently is worse than one extra tap |
| **TTS unavailable** | Answer is delivered as text with a note that the voice is unavailable | Voice is a mode, not a separate product (PRD §4.4) — falling back to text is correct |
| **WebSocket drops mid-turn** | Reconnect; if the answer completed server-side, deliver it in the conversation | The turn is in the audit log regardless |
| **Latency budget missed** | ⚠ **DECISION** — silently slow, or a visible indicator? | PRD §4.4: users abandon voice permanently after two bad tries |
| **User speaks over the answer** | ⚠ **DECISION** — barge-in supported, or does the answer finish? | Barge-in is significant work; without it, long answers feel unusable |

---

## 6. Administration and audit

| State | What the user sees | Notes |
| ----- | ------------------ | ----- |
| **First-run, no users beyond the installer** | Guided setup: create admin, create a collection, connect a source | The Deployer's 2-hour install budget (PRD §3) includes this |
| **Audit export, large range** | Job with progress and a download when ready, not a blocking request | Ministry-scale audit exports are not a synchronous operation |
| **Audit log write fails** | ⚠ **DECISION** — does the action proceed unlogged, or fail? | If the audit log is the reason procurement approved the purchase, an unlogged action is arguably worse than a refused one. C5 is silent on this |
| **Attempted `UPDATE`/`DELETE` on `audit_events`** | Fails at the database; surfaced as a critical alert | C5. The application role has no such grant — if this ever fires, something is badly wrong |
| **Model swap in progress** | Assistant unavailable, with expected duration. Retrieval still works | PRD §4.5 allows swapping without redeploying |
| **Hardware below profile floor at install** | Installer refuses and names the shortfall | PRD §5.3 — refuse rather than deploy something that gets blamed on the product |
| **Abstention rate rising** | Dashboard surfaces it with the unanswered questions driving it | PRD §4.5. The list of what was asked and not found *is* the ingestion backlog |

---

## 7. Empty states, collected

Every one of these is a real screen someone will see on day one, and each is an opportunity to teach the product rather than show a blank box:

| Surface | Empty state must say |
| ------- | -------------------- |
| Chat, no corpus | Nothing ingested yet; what will be possible once it is |
| Document list | What a collection is for; how to upload |
| Collection, no documents | Same, scoped |
| Database connections | What connecting enables; that credentials must be read-only |
| Schema annotations | Why annotations matter more than a model upgrade (PRD §4.2) — this is the single highest-leverage thing an administrator can do, and nobody will do it unless told |
| Conversation history | — |
| Audit log, filtered to nothing | Distinguish "no events" from "filter excludes everything" |
| Usage dashboard, pre-traffic | What will appear once questions are asked |

---

## 8. Decisions this document surfaced

None of these have an answer in `docs/PRD.md`. Each is a product decision, not an implementation detail. Ordered by how much rework a late answer causes.

1. **Audit log write failure — proceed unlogged, or fail the action?** (§6) Affects the transaction boundary of every audited operation. Cheapest to decide before any of them are written. C5's spirit says fail; nothing states it.
2. **Document deletion vs. audit immutability** (§3) Past answers cite chunks; the audit record cannot be erased (C5). Tombstone, block-while-cited, or broken citation links — this shapes the `documents` and `chunks` schema, so it must be settled before Phase 5 migrations.
3. **Restricted columns — acknowledge or conceal?** (§4) Concealment is more secure and more confusing. Affects both the answer composition prompt and the SQL disclosure UI.
4. **Voice barge-in** (§5) Significant Phase 4 scope. Without it, long answers on `edge` are painful; with it, Phase 4 grows past its reduced 1.5-week estimate.
5. **Generation on navigate-away — continue or abort?** (§2) CPU is scarce on `edge`; the audit record is incomplete if aborted.
6. **Voice latency-miss indicator** (§5) Smallest of the six, but PRD §4.4 says two bad tries lose the user permanently.

Items 1 and 2 should be answered before Phase 5 (data model). Items 3–6 before their respective phases.
