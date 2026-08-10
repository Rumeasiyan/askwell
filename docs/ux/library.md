# Screen: Library

Everything Askwell has read, and what state it is in.

> **This document is the specification. Any mockup is a reference.**

**Route:** `/sources`
**Phase:** 1

---

## 1. What it is for

Answering three questions quickly: what does Askwell know about, is any of it broken, and where did that citation come from.

It is a working inventory, not a file manager. The user already has a file manager and it is better than anything shipped here.

---

## 2. Shape

Grouped by source, sorted by most recently added. Each row carries name, kind, size, when added, status, and its open clarification count.

Status is a word plus a shape, never colour alone (`design-system.md` §8): *indexed · indexing · needs attention · deleted*.

**"Needs attention" is one status covering several causes** — failed extraction, poor OCR, a dead connection, a stale annotation. The row expands to the specific reason. One status keeps the list scannable; the detail is one click away.

---

## 3. Interactions

| Action | Result |
| ------ | ------ |
| Open a source | Source viewer (`source-viewer.md`) |
| Ask about this source | Ask, scoped to it |
| Re-index | Re-extracts and re-embeds. Confirms first — it can take hours |
| Delete | Tombstones. See §4 |
| Add a new version | Supersedes; history kept |
| Fix | Jumps to the specific problem — the failed file, the connection settings, the clarification |
| Filter | By kind, status, or has-open-clarifications |

---

## 4. Deletion, which is not simple

Issue #11, Option A: content and embeddings are cleared, the record survives.

Confirmation states what actually happens:

> Delete **supplier-agreement-2024.pdf**?
> The file on your disk is untouched. Askwell forgets its contents and stops using it in answers. Past answers that cited it will show it as deleted rather than breaking.

Three facts a user needs and would otherwise guess wrong: **their original file is safe**, the content is genuinely gone from Askwell, and old citations degrade honestly instead of vanishing.

Deleted sources stay listed, greyed, filterable out. The record is what makes an old citation resolve at all.

Deleting a source removes its schema notes. **General memory learned from it survives** — an abbreviation is still true after the file it came from is gone (`../memory-and-clarification.md` §7).

---

## 5. States

| State | What is shown |
| ----- | ------------- |
| **Empty** | What a source is and the four ways to add one. An invitation, never "no items" |
| **Indexing** | Progress inline; already-askable marked |
| **All healthy** | Plain list. No dashboard, no charts — this is not a place to linger |
| **Needs attention** | Affected sources first, with the reason and a fix |
| **Connection dead** | Last successful check, the error, reconnect |
| **Stale annotations** | A described table or column no longer exists in the live schema |
| **Deleted, filtered in** | Greyed, deletion date, not openable |

---

## 6. Open

1. **Collections.** The data model has them; whether v1 exposes grouping or ships a flat list is unresolved. A flat list is simpler and probably right until someone has enough sources to need otherwise.
2. **Per-source storage** — showing how much index each source costs, which matters once the log and index budgets bite.
