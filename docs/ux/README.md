# Screen specifications

`design-system.md` first — tokens, the colour rules, and the layout every screen inherits.

| Screen | Spec | Phase |
| ------ | ---- | ----- |
| First run | [`first-run.md`](first-run.md) | 1 |
| Add source | [`add-source.md`](add-source.md) | 1 · 3 |
| Library | [`library.md`](library.md) | 1 |
| **Ask** — the core loop | [`ask.md`](ask.md) | 1 |
| Source viewer — where a citation lands | [`source-viewer.md`](source-viewer.md) | 1 |
| Clarifications | [`clarifications.md`](clarifications.md) | 2 |
| Memory | [`memory.md`](memory.md) | 2 |
| Trace | [`trace.md`](trace.md) | 4 |
| Voice | [`voice.md`](voice.md) | 5 |
| Settings | [`settings.md`](settings.md) | 1 → 6 |

Visual reference: [`screens-reference.html`](screens-reference.html) — Ask answered, Ask abstained, Clarifications. Also published as an artifact.

**The written spec is the specification. The mockup is a reference.** Where they disagree the spec wins, or the mockup is redrawn. Images acquire authority they have not earned, which is why this is repeated in every screen document.

Every screen accounts for the states in [`../states-and-edge-cases.md`](../states-and-edge-cases.md). A happy path is not a finished screen.

## The three screens that carry the product

- **Ask** — and within it, the abstention state. The design pressure to soften abstention into a caveated guess will come, and `ask.md` §6 records why to refuse.
- **Source viewer** — makes "you can check this" true rather than claimed. If following a citation is slow, people stop checking and the central promise quietly dies.
- **Clarifications** — the differentiator, and the feature most able to destroy itself by asking too much.
