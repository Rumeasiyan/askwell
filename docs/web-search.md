# Web search

Askwell can search the web. **It does so only when the user asks, for one question at a time, and never because retrieval came up short.**

That sentence is the whole design. Everything below follows from it.

---

## 1. Why the rule matters more than the feature

Askwell's most-tested behaviour is abstention: when the user's files do not cover a question, it says so (C5). That is useful because it is *informative* — it tells the user something true about what they have.

A tool that quietly reaches the web when retrieval is thin destroys that. "I don't know" stops happening, so it stops meaning anything, and the user loses the one signal that told them their corpus had a gap. The abstention rate — which `success-metrics.md` §2 treats as the key operational number — would go to zero for the wrong reason.

So web search is an **escalation the user performs**, not a fallback the system takes.

Askwell abstains first, plainly, exactly as it did before. Then it offers to look further. The user chooses.

---

## 2. The flow

1. User asks a question.
2. Retrieval runs against their own material. Nothing clears the threshold.
3. **Askwell abstains** — states what was searched, what the closest material was, and what would need adding (`ux/ask.md` §6). Unchanged.
4. Alongside that, two escalations are offered: **search the web**, or **ask a larger model** (online AI).
5. If the user picks web search, the question goes out. Results come back into a **separate region**, never the provenance margin.
6. The escalation closes with the turn. The next question starts local again.

**The user may also escalate without abstention** — asking the web about something their files *do* cover, deliberately. That is fine; it is still a per-question act.

---

## 3. What is never done

| Never | Why |
| ----- | --- |
| Search because retrieval scored low | Destroys abstention (C5, C10) |
| Search because the user seems dissatisfied | Same, with extra steps |
| Carry the setting to the next question | C1 requires egress to be per-unit and deliberate |
| Blend web results into the provenance margin | The margin is for material the user owns and can open (C10) |
| Chunk, embed or index web results | They are not the user's corpus; they belong to the turn that fetched them |
| Use web results to answer a question about the user's own documents | If the answer is meant to be about their contract, the web cannot supply it |

---

## 4. How results are shown

Web results render in their own region, visually distinct from the provenance margin, and carry:

- **The source**, as a domain and page title, with the full URL available.
- **A retrieval timestamp.** A page can change or vanish after the answer; a document on disk cannot. The date is what makes the citation honest a month later.
- **A not-your-material marker**, using the same visual language as an unvalidated model — a state the user opted into knowingly.

A claim drawn from the web is cited as such in the answer text. **An answer may mix both**, and when it does, each claim points at whichever kind of source it came from — never a blur of the two.

`ux/ask.md` and `ux/web-search.md` carry the screen-level behaviour.

---

## 5. Untrusted content, at higher stakes

C7 says retrieved content is data and never instruction. That applies to documents and to web pages identically — but the user *chose* their documents, and did not choose a page written to contain instructions.

- Fetched content is delimited exactly as document content is, and the system prompt's statement is unchanged.
- The trace flags instruction-like patterns in fetched content, as it does for documents.
- Fetches are capped: a small number of results, a size limit per page, a timeout. A page that exceeds them is dropped rather than truncated into the prompt.
- Fetched content is never persisted into `chunks`, so a hostile page cannot influence a future answer it was not part of.

This is a mitigation, not a solution, and the residual risk is documented rather than overclaimed — the same honesty `architecture.md` §9 already applies to prompt injection.

---

## 6. Provider

Behind an interface, like the TTS engine, so it can be swapped without touching the answer path.

**Open:** which provider, and whether the user supplies their own key or it is metered through credits like online AI. Metered is more consistent with the "you never hand Askwell an API key" promise in `PRD.md` §6; the user's own key is cheaper to ship. Needs a decision before the work starts.

---

## 7. What it does to the metrics

`success-metrics.md` §2 puts abstention in a 5–20% band and pairs it with citation correctness. Web search does not change the band, because **abstention still fires first**. What it adds is a new number worth watching:

**Escalation rate** — how often a user, having been told their files do not cover something, chooses to search the web. Rising steadily means the corpus has a gap the user has stopped trying to fill by adding sources. That is a signal about ingestion, not about search.

---

## 8. Open

1. **Provider and billing model** (§6).
2. **Settled: no escalation from voice in v1.** Sending a question out is a deliberate act, and a spoken command is the weakest possible confirmation of deliberateness — a misheard phrase would leak a question off the machine, which is the one failure this product cannot afford. Voice abstains and says the escalation is available on screen.
3. **Not in v1: noticing that an escalated question became locally answerable.** Genuinely attractive, and it needs a mechanism for re-testing old questions against a changed corpus that does not exist yet. Deferred with the memory re-ask work.
