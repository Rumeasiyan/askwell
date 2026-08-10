# Design system

Tokens and rules for every Askwell surface. Values carry their reasoning, because a deliberate choice with no recorded reason gets "tidied" by the next person.

**Read `../states-and-edge-cases.md` before designing any screen.** A screen with only a happy path is not finished.

---

## 1. Direction

**Askwell is an instrument, not a chatbot.**

The templated answer for an AI product is a centred chat column, grey bubbles, a violet accent, sources as small numbered pills behind a "Sources" toggle. Rejected deliberately: it makes citations a disclosure you click, and this product's central claim is that every answer is traceable. A design where the evidence is hidden by default contradicts the thing being sold.

The reference world is not chat. It is the **annotated document** — a critical edition, where the text and its apparatus sit side by side and the apparatus is never optional.

### The signature: the provenance margin

Answers render in a text column with a permanent right-hand margin carrying source cards, each aligned to the claim it supports and joined by a hairline leader. Hovering a claim raises its card.

Not a popover, not a drawer, not a toggle. **The margin is always there.** Its consequence is that an uncited claim is visibly wrong — it sits in the column with nothing beside it and nothing pointing at it. The layout enforces C4 rather than trusting the model to.

When Askwell abstains, the margin is empty *and says so*. Emptiness is the honest signal, so it is shown rather than collapsed away.

---

## 2. Colour encodes epistemics

The palette's job is to say **how Askwell knows a thing**. This is the rule that makes the system coherent, and it is a hard rule, not a guideline.

| Token | Light | Dark | Means |
| ----- | ----- | ---- | ----- |
| `--provenance` | `#2F6B62` | `#5FA99B` | **Traceable to a source.** Citations, source cards, leaders, quoted passages, the SQL that produced a number |
| `--inferred` | `#8A6A22` | `#C9A34E` | **Askwell guessed.** Low-confidence memory, inferred CSV types, uninspected OCR, anything the user has not confirmed |
| `--ink` | `#232722` | `#E4E7E1` | Askwell's own words and all primary text |
| `--paper` | `#E9EBE7` | `#191C1A` | Ground. Cool grey-green, blotting paper — not the warm cream every AI tool uses |
| `--surface` | `#F3F4F1` | `#222623` | Raised: cards, inputs, the margin rail |
| `--rule` | `#C9CDC6` | `#333833` | Hairlines, leaders, dividers |
| `--muted` | `#6B716A` | `#9AA096` | Labels, metadata, timestamps |
| `--alarm` | `#8C3A2E` | `#D9705F` | Failures only. Never for abstention |

**`--provenance` is reserved.** It appears on nothing that is not traceable to a source. Buttons are not this colour. Links in the chrome are not this colour. Because it is spent nowhere else, the colour itself comes to mean "you can check this" — and a user learns that in about a day without being told.

**`--inferred` is the honesty colour.** Any fact Askwell derived rather than being told carries it. An ochre-marked column description means "I guessed this — correct me", which is what drives the clarification loop from the answer surface.

**Abstention is not `--alarm`.** Not knowing is correct behaviour, not a failure. It renders in `--ink` and `--muted` with more space than an answer would get. Colouring it red teaches users that the most trustworthy thing the product does is a problem.

---

## 3. Type says who is speaking

Two families, and which one is used carries meaning.

| Role | Stack | Used for |
| ---- | ----- | -------- |
| **Text** | `Charter, "Bitstream Charter", Georgia, "Iowan Old Style", serif` | Language: answers, document excerpts, questions asked of the user |
| **Apparatus** | `ui-monospace, "SF Mono", "Cascadia Mono", Consolas, monospace` | Everything the machine says about itself: labels, metadata, citations, SQL, traces, counts, timestamps, all UI chrome |

The rule: **serif is for language, mono is for evidence and machinery.** A user reading an answer is reading prose; a user reading a citation, a row count or a generated query is reading an instrument. The typeface makes that switch without a label.

It also solves a real problem — this interface is dense with SQL, traces and tabular results, so mono is a first-class face here, not a code-block afterthought.

No web fonts. Everything is bundled or system (C1), and a font that fails to load offline is a broken interface on the exact machine this product is for.

### Scale

Fifth-based, tightened at the top for a dense desktop tool.

| Token | Size / line | Use |
| ----- | ----------- | --- |
| `--t-display` | 28 / 34 | Screen titles only |
| `--t-title` | 20 / 28 | Section headings |
| `--t-body` | 16 / 26 | Answer prose. Generous leading — answers are read, not scanned |
| `--t-ui` | 14 / 20 | Chrome, controls |
| `--t-meta` | 12.5 / 18 | Citations, metadata, labels |
| `--t-micro` | 11 / 16 | Timestamps, counts. Uppercase, `0.08em` tracking |

Answer prose sets at a **68–75 character measure**. Wider is measurably harder to read and this product asks people to read carefully.

---

## 4. Space and shape

4px base. Steps: `4 8 12 16 24 32 48 64`.

- **Radius: 3px**, everywhere. Near-square reads as instrument; pill shapes read as consumer chat. One exception: circular avatars/status dots.
- **Borders over shadows.** A 1px `--rule` is the default separator. Shadow only for genuinely floating things (menus, dialogs) — an interface that is mostly flat makes the few raised things mean something.
- **Controls: 32px** standard height, 24px compact, **44px minimum for any primary action.** Desktop-first, but a trackpad on a laptop is not a mouse on a desk.
- **Focus: 2px `--provenance` outline, 2px offset**, never removed. Keyboard navigation is not optional.

### Layout

```
┌────────────┬─────────────────────────────┬───────────────────┐
│  sources   │  conversation               │  provenance       │
│  240px     │  flexible, 68–75ch measure  │  300px            │
│            │                             │                   │
│  library   │  question                   │  ┌─────────────┐  │
│  memory    │  answer ─────────────────── │──│ contract.pdf│  │
│  settings  │  ...text with claims...   ╲ │  │ p.14        │  │
│            │                            ╲│  │ "…passage…" │  │
│            │                             │  └─────────────┘  │
└────────────┴─────────────────────────────┴───────────────────┘
```

Below 1100px the provenance rail moves under each answer as an inline block rather than disappearing. **It is never removed** — that would make citations conditional on window width.

---

## 5. Motion

Sparing. This is a tool someone uses for hours.

| What | Duration | Why |
| ---- | -------- | --- |
| Token streaming | — | Natural pace, no easing. Faked smoothing hides real slowness the user should feel |
| Leader draw, claim → card | 180ms ease-out | The one deliberate flourish. It shows the connection being made |
| Card hover raise | 120ms | — |
| Panel open | 160ms ease-out | — |
| Progress past latency budget | fade in 200ms | Appears only once the budget is missed (#15) |

`prefers-reduced-motion` removes all of it including the leader draw, which then renders statically. Nothing is only communicated by movement.

**No skeleton shimmer.** Ingestion and answering have real, knowable progress; a shimmering placeholder is a decoration that pretends to be information.

---

## 6. Voice

Sentence case. Plain verbs. Second person for the user's own things ("your files"), first person for Askwell's state ("I could not find this in your files").

First person is deliberate and narrow: Askwell says "I" **only** when reporting the limits of its own knowledge. Everywhere else the interface is impersonal. A tool that says "I'm sorry!" constantly is grating; one that says "I don't know" precisely is trustworthy.

- Abstention: *"Nothing in your files answers this. Add the source you'd expect it in, and ask again."* — states the situation, gives the action. Never apologises.
- Failure: what happened, then what to do. No apology, no blame, no exclamation mark.
- Empty states are invitations, never blank. Every one names the thing and the first action.
- Actions keep their name end to end. "Add source" produces "Source added", never "Upload complete".

Never: "Oops", "Uh oh", "Something went wrong", "AI-powered", "seamlessly", "simply".

---

## 7. Components that carry meaning

Three are not generic and must not be reskinned into standard patterns.

**Source card** — the margin unit. Filename in mono, page or table, then the exact retrieved passage in serif. Left edge is a 2px `--provenance` bar. Clicking opens the source at that position.

**Claim leader** — a hairline from a cited claim to its card. `--rule` at rest, `--provenance` on hover of either end.

**Confidence marker** — a 6px square before any memory fact. Filled `--provenance` if the user supplied it, hollow `--inferred` if Askwell guessed. Small, everywhere, and it is how a user learns at a glance which facts they own.

---

## 8. Accessibility floor

Not a checklist item; the target user works in this for hours.

- Text contrast ≥ 4.5:1, UI ≥ 3:1, in both themes. `--provenance` and `--inferred` are tuned to pass on `--paper` and `--surface`.
- **Colour is never the only signal.** The confidence marker differs in fill as well as hue; abstention is stated in words, not implied by tone.
- Full keyboard path through ask → read answer → open citation → correct a fact. That is the core loop and it must not require a pointer.
- Respects the OS light/dark setting, with a manual override.
