# Screen: Conversation

Multi-turn asking. The Ask surface is a conversation, not a series of unrelated questions.

> **This document is the specification. Any mockup is a reference.**

**Route:** `/` — the same surface as `ask.md`, once more than one turn exists.
**Phase:** 1

---

## 1. What it is for

Most real use is follow-up. *"Which suppliers are on non-standard terms?"* then *"why was Meridian given 45 days?"* then *"are any of them late?"* — each question leaning on the last.

A list of full answers stacked vertically becomes unreadable by the fourth turn, and scrolling back past three provenance margins to find what you asked is worse than useless.

---

## 2. Shape

**Past turns collapse. The live turn does not.**

A collapsed turn shows:

- The question, in full, on one line — truncated with an ellipsis if it must be.
- A one-line summary of what answered it.
- **A source count**, in the provenance colour.

The live turn renders exactly as `ask.md` describes, margin and all.

**The source count is not decoration.** Collapsing must never hide *that* a claim was grounded, only the detail of it. A turn that shows no count is a turn that abstained, and that must remain visible at a glance — it is how a user notices a run of unanswerable questions and thinks to add a source.

Expanding a past turn restores its full answer and its margin in place.

---

## 3. Interactions

| Action | Result |
| ------ | ------ |
| Click a collapsed turn | Expands in place with its full margin. Others stay collapsed |
| Ask a new question | Previous live turn collapses; new turn renders full |
| Click a source count | Expands the turn and scrolls to its margin |
| Suggested follow-up | Fills the composer rather than sending — the user still chooses |

### Suggested follow-ups

After an answer, up to three suggestions derived from what was just answered — *"show me Meridian's open invoices"*, *"how did you get this?"*

They fill the composer, they do not send. A suggestion that fires immediately takes the decision away, and the point is to lower the cost of the next question rather than to ask it for them.

---

## 4. Time and grouping

Turns are separated by a simple divider: *earlier today*, *yesterday*, a date. No timestamp per turn — the interval matters, the clock time does not.

---

## 5. States

| State | What is shown |
| ----- | ------------- |
| **Single turn** | No collapsing, no dividers. It is `ask.md` |
| **Several turns** | Past collapsed, live full |
| **A past turn abstained** | Collapsed with no source count and the summary saying so. Visibly different from an answered turn |
| **A past turn used the web** | Collapsed with its web marker retained (`web-search.md`). Never shown as if it came from the user's files |
| **A past turn cited a since-deleted source** | Count reflects what was cited then. Expanding shows the tombstone |
| **Long conversation** | Older turns page in on scroll. **Never truncate silently** |
| **Expanded past turn** | Full answer and margin, in place |
| **New question while an answer streams** | Queued, not interleaved. One answer at a time |

---

## 6. What this screen must not do

- **Never summarise away the citation count.** Grounding stays visible even when the answer is not.
- **Never re-run a past turn** to produce its summary. The summary is stored with the turn; recomputing it later against a changed corpus would make history unreliable.
- **Never collapse the live turn.** The answer being read keeps its evidence beside it.

---

## 7. Open

1. **How far back before paging.** Unspecified; needs real conversations to answer.
2. **Editing a past question and re-asking.** Attractive, and it raises what happens to the turns that followed it. Not v1.
