# Manual test — M1-ASK-FE-039a, mic control in the composer

**Ticket:** `M1-ASK-FE-039a` — a mic control sits in the composer from Phase 1, at its final position and size, visibly disabled with its reason available on hover and keyboard focus, requests no microphone permission, and does not change the composer's layout.
**Version under test:** `0.2.21`
**Time:** about 20 minutes.
**Who can run it:** a browser. No native inference, no reranker, no source material needed — the control renders regardless of whether any source exists or any question has been asked.

**What is being checked.** `web/components/ask/ask-screen.tsx`'s `MicControl`, rendered inside `Composer`, beside the **Ask** button. `aria-disabled="true"` (not the `disabled` attribute) so the button stays in tab order; a CSS-only tooltip (`web/app/globals.css`, `.ask-mic-reason`) shown on `:hover` and `:focus-visible` reads the fixed string `"Voice arrives with the voice release. Type for now."`. No `getUserMedia` call, no click handler, no permission prompt exists anywhere in this component.

**Where this stops on purpose.** This ticket does no audio work. There is no way to trigger a browser microphone permission prompt from this build at all — that is the thing being confirmed, not a gap in the walkthrough.

---

## Before you start

```
cd ~/external/quantum-plus/askwell
```

If you have never run Askwell before:

```
cp -n .env.example .env
```

Open `.env`, find `POSTGRES_APP_PASSWORD`, and put any word after the `=` if it is blank. No folder needs to be nominated for this walkthrough — the mic control renders on the empty first-run screen too.

---

## Cold start

### 1. Build the interface

```
scripts/dev.sh web-build
```

**You should see:** a Next.js build finishing with a route list and no red error text.

### 2. Bring the stack up

```
podman compose up -d
```

**You should see:** `postgres`, `redis`, `egress-proxy`, `api`, `worker` reported as started. Wait about thirty seconds.

### 3. Create the database tables

```
scripts/dev.sh db upgrade head
```

**You should see:** migration lines finish with no error.

### 4. Open Askwell

Open a browser at:

```
http://127.0.0.1:8000
```

**You should see:** the **Ask your own material** first-run page — no composer yet, since no source has been added.

---

## Part A — the control is present before any source exists

### 5. Look for the mic control on the first-run screen

The first-run screen (`hasSources === false`) shows only the welcome copy and an **Add a source** button — `AskScreen` does not render `Composer` in this state, so there is no mic control to see yet. This is expected: the composer, and the control inside it, appears once a source exists.

### 6. Add a source

Click **Add a source**.

**You should see:** the "Add a source" page, address bar ending in `/sources/add/`.

Add any single file (drag it onto the window, or use the folder-nomination flow) and wait for it to leave the queue.

### 7. Return to Ask

Click **Ask** in the left strip.

**You should see:** the composer now rendered — a text box reading "Ask about your own files and databases", and beside it, to the right, two controls side by side: a small square button and the **Ask** button.

---

## Part B — the control's appearance and position

### 8. Look at the square button left of "Ask"

**You should see:** a small (32px) square outlined button showing a microphone glyph, in a muted grey — not black, not red, no strikethrough through the icon. It sits directly to the left of the **Ask** button, both bottom-aligned with the text box.

### 9. Hover the mouse over it

**You should see:** a small dark tooltip appear above the button reading exactly:

> Voice arrives with the voice release. Type for now.

Not an apology ("sorry, not available"), not an error ("voice unavailable") — a statement of what happens and when.

### 10. Move the mouse away

**You should see:** the tooltip disappear.

### 11. Click the mic button

**You should see:** nothing happens. No browser microphone-permission prompt appears, no error message, no change to the page. Click it five more times in a row.

**You should see:** still nothing — no permission prompt, no error, no state change, on any click.

---

## Part C — keyboard and screen-reader reachability

### 12. Click into the question text box, then press `Tab`

**You should see:** focus move to the mic button — a visible focus ring appears around it, and the same tooltip from step 9 appears (triggered by `:focus-visible`, not just hover).

**With a screen reader running** (if available): the control is announced as a button named "Voice input", disabled. It is not skipped over as if absent, and it is not announced as an unlabelled control — the accessible name and disabled state are both present.

### 13. Press `Tab` again

**You should see:** focus move to the **Ask** button next — the mic control did not trap focus, and it did not silently vanish from the tab sequence either; it took exactly one stop.

---

## Part D — geometry holds when the window narrows

### 14. Narrow the browser window well past a typical mobile breakpoint (e.g. resize to around 375px wide)

**You should see:** the mic control still sits inside the composer, beside **Ask** — it is not dropped, hidden, or moved to a separate row or menu. The composer may wrap or resize around it, but the control itself stays put.

---

## Part E — the control survives a turn in progress

### 15. Type a question and submit it (`Enter`, or click **Ask**)

**You should see:** the question appear as a turn below the composer, and named retrieval steps begin (or, with no native inference running, the turn end `failed` with an "unavailable" reason — expected, and unrelated to this ticket).

### 16. Look at the composer again while the turn is in progress, and after it finishes

**You should see:** the mic control is still present, in the same position, in the same disabled state, throughout — nothing about a running or finished turn changes it.

---

## Known gaps

- **No voice of any kind.** No audio capture, no `getUserMedia`, no transport, no synthesis. This is the whole point of the ticket, not a defect to report.
- **No microphone permission is ever requested by this build.** Confirmed by clicking repeatedly in Part B — if a browser permission prompt ever appears from this control, that is a real regression, not expected behaviour arriving early.
- **The level meter and stop control do not exist.** Both are `M6-VUI-FE-132`/`M6-VUI-FE-133`, out of scope here.
- **Voice escalation of a web search is unspecified and deferred** (`docs/web-search.md` §8) — nothing in this control relates to it.
- **No component test infra exists in this repo** (`web/package.json`'s `test` script runs `node --test` over `lib/*.test.ts` only, no DOM/jsdom) — the same gap `M1-ASK-FE-039`'s manual test recorded. This walkthrough is the only place the button's rendered markup, tab order and tooltip behaviour are actually exercised; `scripts/dev.sh web-check` only confirms the static HTML contains the button, `aria-disabled="true"`, and the reason text, not that a real browser tabs to it or shows the tooltip on focus.
- **No real screen reader was used to write this document** — step 12's screen-reader expectation is derived from the `aria-disabled`/`aria-describedby` markup in `ask-screen.tsx`, not from an actual run with assistive technology; run it with one if available and correct this note if the announcement differs.
