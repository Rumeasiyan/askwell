# Audit log

What Askwell records, where, and what happens when it cannot.

Resolves issue #10 (write failure → fail the action) and reconciles it with a product that is free, local, and running on somebody's laptop.

---

## 1. Why this needed redesigning

The original design had one append-only log with one job: prove to a government auditor who asked what. Enforcement was Postgres grants — no `UPDATE` or `DELETE` for the application role.

Two things broke that.

**The user now owns the machine.** They own the disk, the database and the container. "Append-only" enforced by a grant stops *the application* from rewriting history. It does not stop the person, and claiming otherwise is the kind of overclaim the security section already warns against elsewhere.

**Fail-closed on a laptop is a footgun.** Issue #10 chose Option A — audit write fails, the action fails — and that is right, because an unlogged action is worse than a refused one. But applied to one big log on a personal machine, it means **a full disk stops Askwell working entirely**. For a free tool, that is the moment someone uninstalls.

Both are solved by splitting the log by what it is actually for.

---

## 2. Three stores

| Store | Holds | Size | Retention | Write failure |
| ----- | ----- | ---- | --------- | ------------- |
| **Decisions** (`audit_decisions`) | Clarification answers, corrections, source configuration, settings changes, memory edits | Kilobytes | **Forever.** Never pruned, never rotated | **Fail the action** |
| **Interactions** (`audit_interactions`) | Questions, answers, chunks retrieved, SQL executed, row counts, durations, which AI backend | Grows steadily | Rolling window, user-configurable, archived on export | **Fail the action** |
| **Traces** (file ring buffer) | Full tool traces, prompts, token detail | Largest, fastest-growing | Capped ring buffer, oldest dropped | **Never fail** |

The reasoning is that Option A's guarantee only means something for the first two, and the store that must never lose a write is the one measured in kilobytes. A disk cannot realistically fill to the point where a few hundred bytes of decision record cannot be written — so the strict guarantee holds in practice instead of becoming a support ticket.

Traces are debugging aids. Losing one is an inconvenience. Bricking the product because one could not be written is absurd, so they fail open and are capped.

**The decisions store overlaps the memory system deliberately.** A clarification answer is both a memory fact and an audit record — the same event. They are written together, in one transaction, and `memory-and-clarification.md` treats the decisions log as the history of how memory reached its current state.

---

## 3. Disk protection

Fail-closed only works if the disk never actually fills. Staged, so the product degrades in the right order:

1. **Budget at install.** Log storage is capped — a GB figure or a share of free disk, user-adjustable.
2. **80% of budget** — warn in the UI. Offer export, archive, or prune of the interaction window. Not a modal; a persistent, dismissible notice.
3. **Hard limit** — **refuse new ingestion first.** Ingestion is by far the biggest writer, and stopping it keeps asking questions working, which is what the user actually opened Askwell to do.
4. **Only when the decisions store itself cannot write** does an action fail.

Stage 3 is the important one. The instinct is to block everything at the limit; blocking the cheapest, most valuable operation last is what keeps the product usable while the user sorts out disk space.

---

## 4. Tamper-evidence instead of tamper-proofing

Both database-backed stores use a **hash chain**: each record stores the hash of the previous record plus its own contents. Altering or removing a record breaks the chain from that point, and a verification pass reports where.

This gives an honest guarantee:

- **The application never rewrites history.** No `UPDATE`/`DELETE` grant for the app role, which defends against bugs — the realistic threat.
- **Manual tampering is detectable.** Not preventable. The user has root on their own machine and always will.

Which is genuinely useful: a consultant who needs to show a client what was asked of a confidential corpus can produce a log that is verifiable rather than merely asserted.

**Do not describe this as immutable.** It is tamper-evident. The difference is the whole point.

**A legitimate prune (§8) is not tampering, and verification says so.** Deleting the oldest run of interaction records is, from the chain's own shape, indistinguishable from someone deleting them by hand — that is exactly what the chain-integrity check exists to catch. Each prune records the hash the surviving chain now starts from (`interactions_pruned`, in the decisions store, which is never pruned), and `askwell.audit.verify` checks a broken-looking start against that recorded boundary before reporting it as a break. A chain that starts there reports intact, with a note explaining the prune, rather than `MISSING_GENESIS`.

**A reset is the one path that empties both stores, and only a reset can.** The user owns the machine and can always delete their data; a confirmed reset is that deletion, not the application rewriting history behind their back. `askwell_app` still has no `UPDATE`, `DELETE` or `TRUNCATE` on either audit table. The audit tables are emptied only by `askwell_reset_audit()`. That is a `SECURITY DEFINER` function owned by `askwell_audit_reset`, a `NOLOGIN` role that holds nothing but `SELECT, TRUNCATE` on the two tables. The function refuses unless the newest decisions record is a `reset_requested` written in the caller's own transaction. The whole reset is one transaction. It ends by appending `reset_performed` as the genesis record of a fresh decisions chain, so the act of resetting survives the reset (`M7-DATA-BE-159a`, `docs/decisions.md` 2026-09-24). Once that transaction commits, reset also deletes the trace files, which are the third store. It deletes them only after the commit because a file delete cannot be rolled back. Both reset records name the files about to go (`M7-DATA-FE-160`).

---

## 5. Export

The log is the user's own record and must be exportable — interactions and decisions, with the hash chain and a verification tool.

Export is a background job with progress, not a blocking request. A year of interactions is not a synchronous operation.

Exporting the interaction window is also the archive path in §3: export, verify, then prune.

---

## 6. Online AI mode

When a conversation uses online AI (`PRD.md` §6), that fact is recorded in the interaction log — which backend, which model, and that content left the machine.

**Nothing is sent to Askwell.** This section used to say online mode would connect to our own service for billing and usage limits. That service was dropped with the credit tier (issue #255, `decisions.md` 2026-09-23). The user brings their own provider key, and the only thing that leaves is the provider request itself. What that request carries is issue #737.

**Each provider request is recorded locally** (`M8-ONLINE-OBS-172`), as its own `online_ai_request` interaction record, next to the turn's `ask_asked` record and in the same transaction. The `ask_asked` record keeps its shape. Online mode adds a record and never replaces one. The record holds:

- where it went, the model, and when;
- the exact size of the body sent, in bytes;
- whether the body left at all. It did not only when the connection was never made. A request the provider refused still left;
- how it ended: answered, stopped by the user, or the failure's reason code, with the provider's status code;
- what the body was made of, **by reference**: the prompt version, that the question was included, the passage chunk ids, the memory fact and schema note ids, and whether a clarification answer was included.

It never holds the text of the question, the passages or the answer. Those are already stored, encrypted when a passphrase is set, and a second plaintext copy here would sit outside that encryption. The same entry is on the turn's trace, where "show what was sent" reads it.

---

## 7. What is recorded

**Decisions:** clarification answers, corrections to memory, source added/removed/reconfigured, settings changed, log budget changed, document deleted (with reason — this is what an old citation resolves to under issue #11's tombstone).

**Interactions:** question asked, answer produced, chunks retrieved with scores, SQL generated and whether it was accepted or rejected by validation, rows returned, duration, backend used, abstentions, partial answers with the aspects named as not covered, tool-ceiling stops.

Rejected SQL is recorded deliberately. It is the signal that a prompt change has degraded generation, and it is invisible unless logged.

**Traces:** everything else, capped.

---

## 8. Settled defaults

**Log storage budget: 2 GB, or 5% of free disk, whichever is smaller.** User-adjustable.

Two gigabytes holds a very large amount of text — years of interactions for a normal user — while staying a polite guest on a laptop that is not primarily Askwell's. The 5% clause is what stops a 2 GB default being rude on an already-full 128 GB machine.

**Interaction retention: 12 months**, then archived on export and pruned. Long enough that "what did I ask about this client last year" works; short enough that the store does not grow without limit.

**Decisions and memory are never pruned**, at any budget. They are kilobytes and they are the product.

## 9. Open

1. ~~**What online mode transmits** (§6) — [#45](https://github.com/Rumeasiyan/askwell/issues/45).~~ Settled, then made moot: #45 fixed four billing fields, and the billing service they were for was dropped (#255). Nothing is transmitted to Askwell. The local record of each provider request is §6 (`M8-ONLINE-OBS-172`). What the provider itself receives is #737.
