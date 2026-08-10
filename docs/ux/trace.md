# Screen: Trace

"How did you get this?" — the full working behind one answer.

> **This document is the specification. Any mockup is a reference.**

**Route:** panel over Ask, not a page.
**Entry points:** the toggle under any answer.
**Phase:** 4

---

## 1. What it is for

Two audiences with one design.

**Most users open this once**, out of curiosity or because an answer looked wrong, and need to understand it without knowing what an embedding is. **A few open it constantly** — the developer or analyst debugging why a question keeps missing.

Serving both means **layered depth, not two modes**: a readable narrative at the top, raw detail expandable underneath. A trace that only serves the second audience is useless to the first, and one that only serves the first is useless when something is actually wrong.

---

## 2. Shape

A vertical sequence of steps, top to bottom, in the order they happened. Each step: what it did, what came back, how long it took.

```
1  Searched your files                                    340 ms
   "Meridian payment terms" → 8 passages, top score 0.81
   ▸ show all 8 with scores

2  Read 2 documents                                       120 ms
   supplier-agreement-2024.pdf p.14 · procurement-policy-v3.docx p.6
   ▸ show retrieved text

3  Looked up schema                                        40 ms
   invoices · used your note on st_cd
   ▸ show schema sent to the model

4  Queried sales-2024                                     240 ms
   7 rows · LIMIT 1000 added by Askwell
   ▸ show query and validation

5  Wrote the answer                                      8.2 s
   3 claims, all cited
```

Numbered because this genuinely is a sequence and the order carries meaning — step 4 could not have happened before step 3.

**Timings are always visible.** On a local model the user is waiting, and knowing where the eight seconds went is the difference between "this is slow" and "the model is slow, retrieval was instant".

---

## 3. What must be in it

| Item | Why |
| ---- | --- |
| Retrieved passages **with scores** | The only way to see a near-miss — the right passage at 0.61 under a 0.65 threshold explains an abstention that otherwise looks broken |
| The threshold in force | Meaningless scores without it |
| Memory facts used | Which belief shaped this answer |
| Generated SQL, and whether validation accepted it | **Rejected SQL is recorded and shown.** It is the signal that a prompt change has degraded generation, and it is invisible unless surfaced (`../audit-log.md` §7) |
| Injected `LIMIT` | A truncated result mistaken for a complete one is a wrong answer with no warning attached |
| Injection flags | Where retrieved content contained instruction-like text (C7). Flagged here, not as an alarm in the answer |
| Tool-ceiling stop | If it stopped at 8 steps, this is where the user sees what was skipped |
| Backend | Local or online, and which model |

---

## 4. Interactions

| Action | Result |
| ------ | ------ |
| Expand a step | Raw detail: full text, full query, full scores |
| Click a passage | Source viewer at that position |
| Click a memory fact | Popover with correct and delete |
| Copy trace | Plain text, for a bug report |
| Adjust threshold | **From an abstention trace only** — see below |

### Adjusting the threshold from here

When an abstention trace shows a near-miss, offering the threshold control is genuinely useful and genuinely dangerous. `../success-metrics.md` §2 names lowering the threshold as the one change that makes the abstention number look better while breaking C5.

So it is offered with the consequence stated, not as a slider:

> The closest passage scored 0.61, just under the 0.65 threshold. Lowering the threshold makes Askwell answer from weaker matches — more answers, more of them wrong.

The change is recorded in the decisions log. Not hidden, not forbidden — it is the user's product — but never a frictionless slider, because the frictionless version is how the product quietly stops being trustworthy.

---

## 5. States

| State | What is shown |
| ----- | ------------- |
| **Normal answer** | Full sequence |
| **Abstention** | The most useful trace there is: what was searched, best scores, threshold, and the near-miss if any |
| **Partial** | Which claims were grounded and which were not |
| **Tool ceiling** | Steps taken, plus what it was about to do |
| **Failed mid-answer** | Steps up to the failure, then the error |
| **Online backend** | Marked, with what was sent |
| **Trace unavailable** | Traces are a capped ring buffer (`../audit-log.md` §2). Old ones are gone: *"The detailed trace for this answer has been cleared. The answer and its sources are still in your log."* — the important records survive; only the debugging detail rotates |

---

## 6. Open

1. **Score presentation.** Raw cosine numbers are meaningless to most users, and a five-star rendering is a lie about precision. Currently raw with the threshold beside it; not obviously right.
2. **Retention default** for the trace buffer, tied to the log budget.
