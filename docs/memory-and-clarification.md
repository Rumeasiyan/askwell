# Clarification and memory

The subsystem that makes VaultQ improve on your material over time. `PRD.md` §5 calls this the differentiator; this is how it works.

**The core idea:** when VaultQ ingests a source and hits something it genuinely cannot know, it asks the user, and stores the answer permanently. Every future ingest and every future question uses it.

This is the answer to a problem the old design had and never solved. It said schema annotations move text-to-SQL accuracy more than any model upgrade — which is true — and then relied on an administrator voluntarily sitting down to write hundreds of them. Nobody ever does. Asking at the moment of ambiguity, about one specific thing, with the file open, is the only version of this that actually gets populated.

---

## 1. When to ask, and when not to

**The failure mode to design against is asking too much.** A user importing 500 files who is asked 200 questions closes VaultQ and does not come back. Every question must earn its place.

Ask **only** when all three hold:

1. **VaultQ genuinely cannot determine the answer.** Not "is unsure" — cannot know. `st_cd` is unguessable. `created_at` is not.
2. **The answer materially changes future results.** A column that will never be queried does not deserve a question.
3. **The user plausibly knows.** They know what their own abbreviation means. They do not know why a PDF's text layer is corrupt.

If any fails, infer, record the inference as low confidence, and move on.

### What qualifies

| Trigger | Example question |
| ------- | ---------------- |
| Unguessable column name | "`st_cd` appears in `students`, values A/T/D. What does it mean?" |
| Ambiguous CSV type | "`dt_reg` looks like a date in DD/MM/YYYY. Correct, or is it MM/DD?" |
| Contradiction between sources | "The 2024 handbook says 30 days, the 2025 policy says 45. Which is current?" |
| Unreadable scan | "Pages 4–7 of *contract-final.pdf* scanned poorly and produced little text. Re-scan, or index as-is?" |
| Ambiguous document identity | "Three files look like versions of the same contract. Is *v3-FINAL-2.pdf* the current one?" |
| Domain abbreviation in text | "'RFQ' appears throughout. Request for Quotation?" |

### What does not

- Anything inferable from context, naming convention, or a foreign key.
- Formatting, encoding, or anything the user has no way to answer.
- Preferences that can have a sensible default.
- Anything already in memory — **always check memory first**. Asking twice is how the feature becomes annoying rather than useful.

---

## 2. When the asking happens

**Not blocking.** Ingestion completes; questions queue.

The alternative — a modal per question during import — was rejected. Import is when the user is least willing to be interrupted, and blocking on a question means a 500-file import stalls indefinitely because they walked away.

So:

1. Source is added. Ingestion runs. Anything ambiguous is recorded as a **pending clarification** and ingestion continues with a best-effort inference.
2. The source becomes queryable immediately, with a visible marker that it has open questions.
3. Pending clarifications surface as a reviewable list — batched, dismissible, answerable whenever the user feels like it.
4. Answering one **re-processes what depends on it**: re-embed affected chunks, update schema notes, re-resolve the contradiction.

**Answering is always optional.** VaultQ works without it, just less well. A user who never answers a single question still has a functioning product — the loop is an upgrade path, not a gate.

### One exception

If a question blocks something the user is doing *right now* — they ask a question whose answer depends on an unresolved contradiction — ask inline, in that conversation, as part of the answer. That is a moment where the question is obviously relevant and the user is already engaged.

---

## 3. What gets stored

Two stores, different shapes and different lifetimes.

### `schema_notes` — structural facts

Attached to a source, a table, a column. What the thing means. Embedded and retrieved alongside the schema when generating SQL.

`origin` distinguishes `user` (they told us) from `inferred` (we guessed). **User-supplied always wins** and is never silently overwritten by a later inference.

### `memory` — general facts

Not tied to a schema object. Abbreviations, conventions, which of two conflicting sources is authoritative, project vocabulary, preferences about how the user wants things treated.

Retrieved alongside document chunks so it informs prose answers too, not just SQL.

### Both carry

| Field | Purpose |
| ----- | ------- |
| `origin` | `clarification` (asked and answered) or `correction` (user corrected an answer) |
| `confidence` | User-supplied facts are certain. Inferences are not, and the difference must survive into the prompt. |
| `superseded_by` | Facts change. Memory is corrected by superseding, never by overwriting — the old value stays visible in history. |
| `created_at` | Recency breaks ties between conflicting facts. |

---

## 4. Correction is a first-class path

The user must be able to correct VaultQ **from inside an answer**, at the moment they notice it is wrong. That is the only moment they reliably will.

An answer showing "using: `st_cd` = student status code" with an edit control next to it turns a wrong answer into a permanent improvement in one click. Making them navigate to a settings screen to fix it means it never gets fixed.

A correction supersedes the prior fact, is recorded in the decisions audit (`audit-log.md`), and re-processes anything derived from it.

---

## 5. Memory is not retraining

VaultQ does not fine-tune anything. Memory is retrieved and injected into the prompt as facts, exactly like a document chunk.

This matters for three reasons: it is inspectable (the user can read everything VaultQ believes about their data), it is reversible (delete a fact and it stops applying immediately), and it is portable (memory survives a model swap, because it was never in the model).

**Every fact is visible, editable and deletable.** A memory the user cannot inspect is a system that gets mysteriously worse and cannot be debugged.

---

## 6. Memory feeds retrieval, and that is the point

At answer time, relevant memory is retrieved alongside document chunks and schema notes. All three go into the prompt, clearly separated and clearly labelled as to origin.

**Memory does not bypass grounding.** A fact from memory used in an answer is cited as such — "based on what you told me on 12 March" — the same way a document claim cites its page. C4 (citations) applies to memory exactly as it applies to documents, and C5 (abstention) is unaffected: memory explaining what a column means does not license inventing what is in it.

---

## 7. Failure and edge cases

| Situation | Behaviour |
| --------- | --------- |
| User never answers anything | Product works on inferences. Pending list stays; no nagging. |
| User answers wrongly | It is treated as truth — they own their data. Correctable later; the audit trail shows the change. |
| Two answers contradict | Later supersedes earlier. Both visible in history. |
| Source deleted | Its `schema_notes` go with it. General `memory` survives — an abbreviation learned from a deleted file is still true. |
| Same question, different sources | Asked once. Memory is checked before every question is raised. |
| Huge import, many ambiguities | Cap questions per source. Rank by how much each would improve results, ask about the top few, infer the rest. **Silently generating 200 questions is the failure mode this cap exists to prevent.** |
| Model changes | Memory is unaffected — it was never in the model. |

---

## 8. Open

1. **The per-source question cap.** Needs a number, and the ranking function that decides which ambiguities matter most. Guessing here directly determines whether the feature is delightful or intolerable.
2. **Does memory ever expire?** A fact from three years ago about a source since deleted may be stale. Current design says no automatic expiry — superseding is manual. Revisit with real usage.
3. **Import/export of memory.** Users with multiple machines, or reinstalling, will want it. Not v1, but the storage shape should not make it hard.
