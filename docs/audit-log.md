# Audit log

What VaultQ records, where, and what happens when it cannot.

Resolves issue #10 (write failure → fail the action) and reconciles it with a product that is free, local, and running on somebody's laptop.

---

## 1. Why this needed redesigning

The original design had one append-only log with one job: prove to a government auditor who asked what. Enforcement was Postgres grants — no `UPDATE` or `DELETE` for the application role.

Two things broke that.

**The user now owns the machine.** They own the disk, the database and the container. "Append-only" enforced by a grant stops *the application* from rewriting history. It does not stop the person, and claiming otherwise is the kind of overclaim the security section already warns against elsewhere.

**Fail-closed on a laptop is a footgun.** Issue #10 chose Option A — audit write fails, the action fails — and that is right, because an unlogged action is worse than a refused one. But applied to one big log on a personal machine, it means **a full disk stops VaultQ working entirely**. For a free tool, that is the moment someone uninstalls.

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
3. **Hard limit** — **refuse new ingestion first.** Ingestion is by far the biggest writer, and stopping it keeps asking questions working, which is what the user actually opened VaultQ to do.
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

---

## 5. Export

The log is the user's own record and must be exportable — interactions and decisions, with the hash chain and a verification tool.

Export is a background job with progress, not a blocking request. A year of interactions is not a synchronous operation.

Exporting the interaction window is also the archive path in §3: export, verify, then prune.

---

## 6. Online AI mode

When a conversation uses online AI (`PRD.md` §6), that fact is recorded in the interaction log — which backend, which model, and that content left the machine.

Issue #10 also established that online-mode logging connects to our service, for billing and usage limits. **What is sent is not yet designed**, and it is the one place where this document's local-only assumption does not hold. Constraints:

- Local logging continues in full regardless. Online mode adds a record; it never replaces one.
- What leaves should be the minimum for billing and limits — token counts, timestamps, model. Not question content, not answers, not retrieved material.

This is deferred with the rest of stage 7 and needs its own decision before that work starts. Flagged here rather than left to be discovered.

---

## 7. What is recorded

**Decisions:** clarification answers, corrections to memory, source added/removed/reconfigured, settings changed, log budget changed, document deleted (with reason — this is what an old citation resolves to under issue #11's tombstone).

**Interactions:** question asked, answer produced, chunks retrieved with scores, SQL generated and whether it was accepted or rejected by validation, rows returned, duration, backend used, abstentions, tool-ceiling stops.

Rejected SQL is recorded deliberately. It is the signal that a prompt change has degraded generation, and it is invisible unless logged.

**Traces:** everything else, capped.

---

## 8. Open

1. **Default log budget.** Needs a number. Too small and users lose history they wanted; too large and VaultQ is a bad guest on a laptop.
2. **Default interaction retention window.** Same tension.
3. **What online mode transmits** (§6). Needed before stage 7.
