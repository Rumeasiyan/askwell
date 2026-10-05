# Writing the Askwell manual

The manual is for the person using Askwell on their own computer. It is not developer documentation. This file is the manual's equivalent of `AGENTS.md`: read it before changing a chapter.

## The one rule

**The manual describes how Askwell works now.** Present tense, current behaviour only.

It is not the changelog, the decision log or a test script. It never says what Askwell used to do, what changed, when or why, and its prose carries no version numbers, milestone names or ticket references. When a flow changes, rewrite the step. Do not annotate it ("Since 0.9…", "Previously…", "Now…").

Something that is not built yet is described as what happens today, in the words the screen uses: "CSV files are not read yet", not "CSV support arrives in a later release". Never promise a feature.

`api/tests/test_manual.py` enforces the mechanical part of this rule: it fails on a version number, a milestone name (`M4`) or a ticket reference (`#123`, `M11-FIX-…`) in a chapter.

## Chapters

- One chapter per **task the user performs** ("Add a folder of documents"), not per screen or feature. Order follows a new user's first day.
- Each chapter is an HTML fragment in `chapters/`, named `NN-slug.html`, starting with one `<h2>`. No `<html>`, `<head>` or inline styles: `manual.css` styles everything.
- Steps are an ordered list (`<ol>`). Name controls exactly as the screen labels them, in `<b>`: **Add a source**, **Nominate**. A word the screen shows in capitals is still written as it is in the source code, not shouted.
- Short paragraphs. Say what the user will see after each step, so they know it worked.
- A note the reader must not miss: `<p class="note">`. A warning about losing data or exposing it: `<p class="warn">`.
- A screenshot: `<figure><img src="screenshots/NAME.png" alt="…"><figcaption>…</figcaption></figure>`. The alt text describes what the picture shows.

## Screenshots

Every illustration is a real screenshot, taken by `scripts/manual/shots.mjs` from the **demo stack** (`scripts/manual/demo-stack.sh`). That stack has its own empty database and a demo home folder, `/tmp/anna`, holding only the fictional Meridian Loom documents from `eval/fixtures/corpus`. Never capture from the development stack or from anyone's real files, and never edit a screenshot by hand.

Screenshots use the light theme at 1280 pixels wide. They show the part of the screen a step is about, not the whole window, where the script can select it.

## The manifest and the drift test

`manifest.json` lists, for each chapter, its title, the screenshots it uses, and its **UI anchors**: what the steps tell the reader to look for. An anchor is one of:

- `{"route": "/library/"}`: a page the reader is sent to. It must exist under `web/app/`.
- `{"label": "Nominate"}`: a control or heading the reader is told to find. That exact text must appear in the source under `web/components/` or `web/app/`.
- `{"id": "root-path"}`: an element id the screenshot script relies on.

`api/tests/test_manual.py`, which runs in `scripts/dev.sh test`, fails when an anchor no longer exists in `web/`, when a chapter or screenshot is missing or unlisted, or when `askwell-manual.html` was not rebuilt after a chapter changed. A screen change that breaks a documented step therefore breaks the build. Fix the chapter, its anchors and its screenshot in the same change.

## When to update it

A change that alters a flow the user sees updates, in the same change:

1. the chapter that describes it;
2. its anchors in `manifest.json`;
3. its screenshots (`scripts/dev.sh manual-shots`);
4. the built manual (`scripts/dev.sh manual`).

## Building

```
scripts/dev.sh manual-shots   # demo stack up, capture every screenshot, demo stack down
scripts/dev.sh manual         # chapters -> askwell-manual.html (committed) and build/askwell-manual.pdf
```

Both run on the host, not in a container: they drive the Chrome already installed there (headless). `manual-shots` also needs the native inference process (`scripts/dev.sh inference`) and stops the development stack while it runs. Set `ASKWELL_MANUAL_CHROME` if Chrome is not on the `PATH` as `google-chrome` or `chromium`.

`askwell-manual.html` is committed so its history shows exactly what readers were given. The PDF is built from it and is not committed.

## Look

The manual uses Askwell's own design tokens (`docs/ux/design-system.md`): paper `#e9ebe7`, ink `#232722`, provenance green `#2f6b62` for links and the left rule of notes, the serif text face for prose and the monospace app face for headings, labels and code. No web fonts: the PDF uses what the machine building it has.
