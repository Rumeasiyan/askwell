# Screen: Web search

Looking outside the user's own files. Behaviour and rules in `../web-search.md`; this is what the user sees.

> **This document is the specification. Any mockup is a reference.**

**Route:** the Ask surface. Web search is not a place, it is a thing that happens to one question.
**Phase:** 6.5

---

## 1. The rule this screen exists to enforce

**Askwell abstains first, then offers.** It never searches because retrieval was thin (C10).

So there is no "search the web" control in the composer, and no toggle in settings that makes it the default. The offer appears in exactly one place: **on the abstention surface**, after Askwell has said what it could not find.

The user may also escalate deliberately on a question their files *do* cover. That is still one question, still one act.

---

## 2. The offer

Rendered below the abstention statement, never above it. The abstention is the answer; this is what the user may do next.

Three options, equal weight, each with its cost stated:

| Option | Stated as |
| ------ | --------- |
| **Search the web** | sends your question out · this question only |
| **Ask a larger model** | uses credits · you have none |
| **Add a source instead** | keeps the answer in your own material |

**"Add a source" is listed deliberately.** It is the option that makes the next answer better permanently, and omitting it would make escalation look like the only way forward.

---

## 3. The answer

Web-sourced content renders in a **visually distinct region** — a dashed border in the inferred colour, headed *from the web — not your files*. It is never placed in the provenance margin.

Each result shows the **domain and page title**, the passage used, and a **retrieval timestamp**. The timestamp is not a detail: a page can change or vanish after the answer, and the date is what keeps the citation honest a month later.

### When an answer mixes both

Claims from the user's documents render normally, with the margin. Claims from the web render in the separate region. **Each claim points at its own kind of source.** They are never blurred into one list, and a web result never appears in the margin even when it supports the same point.

---

## 4. States

| State | What is shown |
| ----- | ------------- |
| **Offered** | The three options, below the abstention. Nothing has been sent |
| **Searching** | Named progress, as retrieval has. The question has left the machine and the user is told so |
| **Answered from the web** | Separate region, marked, with retrieval dates |
| **Mixed** | Both regions, each claim pointing at its own kind |
| **Nothing found on the web either** | Says so plainly. Does not fall back further |
| **Search unavailable** — offline, provider down | *"I can't reach the web right now."* The abstention still stands and is still the answer |
| **Instruction-like content fetched** | Answered normally; the trace flags it (C7). Not surfaced as an alarm — it is a mitigation, not a detection system |
| **Escalation closed** | After the turn: *"the search closed with this question — your next one starts local again"* |
| **Voice** | Not specified. Deferred with the voice work (`../web-search.md` §8) |

---

## 5. What this screen must not do

- **Never offer the web before abstaining.** The offer follows the honest answer; it does not replace it.
- **Never persist the escalation.** No conversation-level toggle, no remembered preference. Sticky egress is how a per-unit permission becomes a default.
- **Never render a web result in the provenance margin**, at any width. Below the breakpoint the margin reflows inline and web results still do not join it.
- **Never present web content as the user's own material**, in an answer, a summary, a collapsed turn, or an export.

---

## 6. Open

1. **Provider, and whether the user supplies a key or it is metered** — [#43](https://github.com/Rumeasiyan/askwell/issues/43). Note that a user-supplied key contradicts `../PRD.md` §6.
2. **Not in v1: re-asking an escalated question locally** once the user adds a relevant document (`../web-search.md` §8).
