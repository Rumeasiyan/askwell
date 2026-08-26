# Usage

How to actually run a design session with this template, screen by screen. For repo
structure/conventions see `README.md`; for contributor rules see `AGENTS.md`.

## 1. Clone for a new project

This repo is meant to be cloned per project, not built on top of directly.

```bash
git clone https://github.com/Rumeasiyan/ui-design-lab.git my-project
cd my-project
rm -rf .git && git init   # detach from this repo's history
pnpm install
pnpm dev
```

Open the URL Vite prints (default `http://localhost:5173`).

## 2. What you're looking at

The app (`src/App.tsx`) is one screen with three parts:

- **Top tab bar** (`DirectionToggle`) — one tab per registered direction. Click a tab,
  or press its number key (`1`-`9`), to view that direction full-screen. Press `G` (or
  click "All N") to switch to a grid showing every direction at once, side-by-side. Once
  there are more than 6 directions, a filter input appears — type to narrow the tabs
  shown by label/subtitle (shortcuts still work on the full, unfiltered set).
- **Screen nav** (`ScreenNav`) — a second bar under the direction tab bar, shown only
  when the active direction has more than one screen. Click a screen name to switch to
  it; switching direction always resets to that direction's first screen.
- **Center pane** (`DeviceFrame`) — renders the active screen inside a frame at mobile
  (390px), tablet (834px), or desktop (100%) width. Switch width with the mobile/tablet/
  desktop buttons top-right.
- **Right sidebar** (`TweakBar`) — sliders/toggles for the tunable CSS custom
  properties in `src/tokens.css`: radius, gap, font scale, motion on/off, motion
  duration, reveal distance. These edit the live `:root` styles in the browser, so
  changes apply instantly to whichever direction is showing — nothing is saved until
  you use "Copy CSS".

Grid view has no TweakBar/device-frame controls — it's for comparing directions at a
glance, not tuning.

## 3. Prompting for a direction

Start from **[`PROMPT_TEMPLATE.md`](PROMPT_TEMPLATE.md)** — the actual fill-in-the-blanks
prompt pattern (Aesthetic/Reference/Intent/Guardrails) plus a full worked example, not
just the rules below. It also covers turning a filled-in prompt into registered
directions via `scripts/new-direction.mjs`.

Each direction is a self-contained page. When prompting an AI agent (or building by
hand) to create one, the two rules that make the harness work are:

1. **Every visual value binds to a `var(--token-name)` from `src/tokens.css`.** Don't
   hardcode a hex color, a border-radius, a font — add a CSS custom property to
   `tokens.css` and reference it. If the TweakBar or "Copy CSS" needs to touch a value
   that isn't a token yet, add it to `tokens.css` **and** to `TweakBar.tsx`'s `FIELDS`
   array — both, or the slider and the export drift out of sync silently.
2. **Each direction commits fully to one aesthetic.** Don't blend two visual languages
   in a single `Page.tsx` — the whole point of side-by-side comparison is that each tab
   is a distinct, coherent bet.
3. **Never use placeholder images, icons, or stock art.** If the design calls for an
   image, generate a real one first (see "Generating supporting assets" below) — a gray
   box or stock photo can't be judged for feel, which is the whole point of reviewing a
   direction.

`src/directions/v1/Page.tsx` is the placeholder — replace its contents, it's not meant
to ship as-is.

## 4. Adding a new direction

```bash
node scripts/new-direction.mjs v2 --label "V2" --sub "Short description"
```

Creates `src/directions/v2/Page.tsx` (registered as that direction's default "home"
screen) and registers the direction in `src/lib/directions.ts` in one step — it appears
in the tab bar and grid view automatically, no manual wiring needed. Number-key
shortcut defaults to the next unused digit (1-9); pass `--key` to override.

Then fill in `Page.tsx` per your prompt's Aesthetic/Placement (see
[`PROMPT_TEMPLATE.md`](PROMPT_TEMPLATE.md)), binding every visual value to a
`var(--token-name)` from `tokens.css`.

## 4a. Adding a screen to a direction

If a direction is more than one view (e.g. a flow: Home → Detail → Settings), add
screens beyond the default one:

```bash
node scripts/new-screen.mjs v2 detail --label "Detail"
```

Creates `src/directions/v2/screens/detail.tsx` and appends it to `v2`'s `screens` array
in `src/lib/directions.ts`. As soon as a direction has 2+ screens, `ScreenNav` appears
under the tab bar to switch between them (see section 2). There's no routing/URL per
screen — it's local component state in `App.tsx`, reset to the first screen whenever you
switch directions.

## 5. Tuning by eye

With a direction open (not grid view):

1. Drag TweakBar sliders / flip toggles — the page updates live.
2. When it looks right, click **Copy CSS**. This copies a `:root { ... }` block with
   the current values of every tunable token to your clipboard.
3. Paste that block over the equivalent properties in `src/tokens.css` to make the
   tuning permanent (the TweakBar only edits the live DOM — a page refresh reverts to
   whatever `tokens.css` says).
4. **Reset** reverts the TweakBar (and the live page) back to `tokens.css`'s values,
   discarding un-copied tuning.

## 6. Generating supporting assets

Image and video generation are invoked from the CLI, not the browser UI — see
`README.md`'s "Image generation" / "Video generation" sections for commands and current
verification status. **Images are not optional if a direction's design calls for one —
generate a real image via `scripts/imagegen.mjs` (wraps `codex exec`'s image tool, no
separate API key needed) rather than leaving a placeholder.** Video generation defaults
to `manual` mode (no API call) and stays optional/opt-in per the constraint in
`AGENTS.md`.

## 7. Wrapping up a session

There's no "export the whole app" step — a direction's `Page.tsx` plus the relevant
slice of `tokens.css` *is* the deliverable. Once a direction is settled:

- Make sure its final tuning has been copied into `tokens.css` (step 5).
- Hand off / reuse `Page.tsx` and the token values directly in the target project.

## Keyboard reference

| Key | Action |
|---|---|
| `1`-`9` | Jump to the direction registered with that key |
| `G` | Toggle all-directions grid view |

Shortcuts are disabled while focus is inside a text input/textarea.
