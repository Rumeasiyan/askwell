# Design lab

A harness for comparing UI design directions side by side, in the browser, with live token tuning.

Vendored from [ui-design-lab](https://github.com/Rumeasiyan/ui-design-lab) (MIT) and adapted for Askwell. Its own `AGENTS.md`, `LICENSE`, `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `CHANGELOG.md`, `DECISIONS.md` and `.github/` were removed — Askwell's versions at the repo root govern here.

---

## What this is, and what it is not

**It is a design tool.** It never ships. Nothing in `design-lab/` becomes part of Askwell's installable product, and no code here is reused by `web/` or `api/`.

**It is not the design system.** [`../docs/ux/design-system.md`](../docs/ux/design-system.md) is the source of truth. `src/tokens.css` is seeded from it so directions render in Askwell's real palette, type and spacing rather than in invented values.

**Screen specifications live in [`../docs/ux/`](../docs/ux/), and they win.** Ten screens are already specified in writing. A direction explored here that contradicts a spec means either the spec changes deliberately — with a note in `../docs/decisions.md` — or the direction is wrong. Images acquire authority they have not earned; the written spec is the specification.

## Constraints that do and do not apply

**C1 does not apply to this directory.** `scripts/imagegen.mjs` and `scripts/videogen/` call external AI providers. That is fine — this is a tool run on the maintainer's machine during design work, not something a user installs. **It must never be read as precedent for runtime network calls in the product**, where C1 is absolute.

**C9 does not apply either.** No model is bundled from here.

Everything else in [`../AGENTS.md`](../AGENTS.md) §3 stands. In particular, a direction that hides citations behind a toggle, colours abstention as an error, or makes the provenance margin collapsible is contradicting C4 and C5 and is not a valid direction however good it looks.

## Running it

Requires Node 22+ and pnpm — the same package manager Askwell chose, and this directory is pnpm-only by a `preinstall` guard.

```
cd design-lab
pnpm install
pnpm dev
```

`pnpm build`, `pnpm lint`, `pnpm preview` also work.

**This is a separate workspace, not a monorepo package.** Askwell's own frontend arrives at `web/` in Phase 0 with its own manifest. The two do not share dependencies and must not be wired together.

## How a session works

Full walkthrough in [`USAGE.md`](USAGE.md); the prompt pattern is in [`PROMPT_TEMPLATE.md`](PROMPT_TEMPLATE.md).

Briefly: each *direction* is a self-contained aesthetic bet in `src/directions/<name>/Page.tsx`, registered by `node scripts/new-direction.mjs`. Switch with the tab bar or number keys, press `G` for a grid of all of them, tune tokens live in the right sidebar, and "Copy CSS" exports the tuned values.

Two rules make the harness work:

1. **Every visual value binds to a token** in `src/tokens.css`. No hardcoded hex, radius or font. If the TweakBar needs to touch a value, add it to both `tokens.css` and `TweakBar.tsx`'s `FIELDS` array — both, or the slider and the export drift apart silently.
2. **Each direction commits fully to one aesthetic.** Blending two visual languages in one page defeats the comparison.

And one from `USAGE.md` worth repeating: **never use placeholder images or stock art.** A grey box cannot be judged for feel, which is the entire point.

## Where Askwell's design currently stands

A direction is already chosen and recorded in [`../docs/ux/design-system.md`](../docs/ux/design-system.md): **instrument, not chatbot**. Its signature is a permanent provenance margin — source cards aligned to the claim they support, joined by a hairline leader, never a toggle — so that an uncited claim is visibly wrong. Colour encodes epistemics: one reserved hue means "traceable", another means "Askwell guessed". Serif is language, mono is machinery.

Three screens have a visual reference in [`../docs/ux/screens-reference.html`](../docs/ux/screens-reference.html): Ask answered, Ask abstained, Clarifications. **Seven have written specs and no visual** — first run, add source, library, source viewer, memory, trace, settings — and those are where this lab earns its place.

The existing direction is a decision with recorded reasoning, not a default. Explore alternatives against it rather than around it, and if one wins, say why in `../docs/decisions.md`.

## Status

One direction, **`instrument`**, with **36 screens** — every surface Askwell has, including the states that usually get skipped: didn't-know, partial answers, conflicting sources, refused queries, moved files, deleted sources, poor OCR, mic denied, assistant down, locked, near-limit storage.

Run `pnpm dev` and press `1`, or use the screen bar to move between them.

### Screens

| Group | Screens |
| ----- | ------- |
| Asking | answered · working · didn't know · partial & conflict · asks you first · nothing yet |
| Asking your data | answered with SQL shown · refused |
| Following a citation | source viewer · moved & deleted |
| Adding material | choose · reading · CSV review · dump sandbox · connect database · library |
| The differentiator | clarifications · clarifications empty · memory |
| Showing the working | trace · trace near-miss · how it's going · history |
| Voice | voice · edge cases |
| Getting started | what it is · this machine · model · locked · assistant down |
| Settings | model · privacy · storage · your data · online AI · about |

### Adding an alternative

`instrument` is a decision with recorded reasoning, not a default. To test something against it:

```
node scripts/new-direction.mjs v2 --label "V2" --sub "What you are betting on"
```

Then press `G` to see both side by side under identical content. If the alternative wins, say why in `../docs/decisions.md` and update `../docs/ux/design-system.md` — do not leave the two disagreeing.
