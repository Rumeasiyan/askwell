# Prompt template — starting a design session

Copy the template below, fill in the four fields, hand it to an AI coding agent working
in this repo (or use it as your own brief).

## The pattern

```text
Aesthetic: [family] — [5-8 vocabulary terms]
Reference: [screenshot or image path] — match feel, not content.
Intent: [what this should feel like and why]
Guardrails: always [constants]. Never [bans].
```

- **Aesthetic** — name the visual family (e.g. "print-tech x data", "brutalist-editorial
  B&W") plus 5-8 concrete vocabulary terms, not vibes. "Clean and modern" is not a
  vocabulary term; "topographic line illustration, mono data callouts, film-strip ticks"
  is.
- **Reference** — a real screenshot or image, with an explicit instruction to match
  *feel*, not content. Without this line an agent will often copy the reference's literal
  subject matter instead of its visual language.
- **Intent** — the emotional/functional goal, tied to a real outcome ("a founder should
  think X within 3 seconds"), not just an adjective.
- **Guardrails** — explicit allow/ban lists. Vague taste doesn't transfer; a concrete
  "never gradient, never Inter-only" does.

## Multi-direction session template

For generating several directions at once (the harness's core use case — see
`src/lib/directions.ts` and the `DirectionToggle` tab bar), wrap the pattern in this
shared-base structure:

```text
Build [what you're building].
Conversion/functional goal: [the one thing this page/screen must accomplish].

Intent: [shared intent across ALL directions — what it should feel like and why].

Guardrails — always: [constants shared across all directions].
Never: [bans shared across all directions].

Create N versions, one per direction below. Same intent and guardrails for all of them.
Do NOT blend directions — each version commits fully to its own aesthetic.

--- DIRECTION 1 (v1) — [Direction Name] ---
Aesthetic: [family] — [5-8 vocabulary terms]
Reference: [path/description] — read it before designing; match feel, not content.
Placement: [where the key visual/content sits and how it composes with the layout]

--- DIRECTION 2 (v2) — [Direction Name] ---
...
```

## Worked example (Kestrel, condensed — full transcript in the notes repo)

```text
Build a landing page for "Kestrel" — an AI analytics platform for small startups.
Conversion goal: book a demo. Primary CTA on every version is "Book a demo"; it must
appear in the hero and repeat at the end of the page.

Intent: a small team's unfair advantage. Should feel like serious, crafted intelligence
— calm and confident — not loud SaaS hype. A founder should think "these people actually
understand data" within 3 seconds.

Guardrails — always: one monumental image anchors the page; imagery is processed, never
raw (halftone, dither, grain, ASCII, linework); technical marginalia (coordinates, IDs,
ruler ticks, timestamps); type at extremes — monumental display or tiny mono labels,
little middle; near-monochrome ground with a single warm accent.
Never: purple gradients, glossy 3D SaaS blobs, untextured stock photography,
rounded-everything friendliness, icon-grid feature rows, Inter/system-font-only
typography, evenly-distributed colorful palettes.

Create 5 versions, one per direction below. Same intent and guardrails for all five.
Do NOT blend directions — each version commits fully to its own aesthetic.

--- DIRECTION 1 (v1) — Print-Tech Paper ---
Aesthetic: print-tech x data — pale sage ground, topographic line illustration, mono
data callouts, transaction-ID chips, film-strip ticks, grotesk display.

--- DIRECTION 2 (v2) — Data-as-Texture ---
Aesthetic: cinematic data-texture — clouds rendered from amber binary characters, dark
teal sky, data-as-material, golden accent CTAs, mono labels.

--- DIRECTION 3 (v3) — Vast Quiet Cinematic ---
Aesthetic: editorial minimalism x cinematic — vast B&W mountain photography, mist
atmosphere, tiny centered sans, extreme whitespace, quiet CTA.

--- DIRECTION 4 (v4) — Dither Mono ---
Aesthetic: brutalist-editorial B&W — heavy bitmap dither, stark studio dark, giant
cropped footer wordmark, clean sans body, high contrast.

--- DIRECTION 5 (v5) — Classical Remix ---
Aesthetic: classical x white editorial — grainy classical figure illustration, serif
italic emphasis word, white ground with thin orbit lines, blue pill CTA, trust logo row.
```

## Turning a filled-in prompt into this harness's directions

1. Fill in the template above with your project's specifics.
2. For each direction block, run:
   ```bash
   node scripts/new-direction.mjs v1 --label "V1" --sub "Print-Tech Paper"
   ```
   (creates `src/directions/v1/Page.tsx` and registers it in `src/lib/directions.ts` —
   see `scripts/new-direction.mjs --help`.)
3. Fill in each `Page.tsx` per its Aesthetic/Placement, binding every visual value to a
   `var(--token-name)` from `src/tokens.css` (add new tokens if a direction needs a
   value not yet tunable — see `USAGE.md` section 3).
4. For hero imagery, use `scripts/imagegen.mjs` (or the manual/video-API paths in
   `scripts/videogen/`) per direction's described visual.
