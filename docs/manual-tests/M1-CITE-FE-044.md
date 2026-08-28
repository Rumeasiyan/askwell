# Manual test — M1-CITE-FE-044, hover pairing and the narrow-window inline fallback

**Ticket:** `M1-CITE-FE-044` — hovering a cited claim raises its leader and card and vice versa;
below the three-column breakpoint the margin's cards move inline under the answer, never removed,
each with a `--rule-strong` left edge carrying the claim-to-source relationship the leader carried
at width; keyboard focus produces the same pairing.
**Version under test:** `0.2.25`
**Time:** about 30 minutes, with a native inference process running; 10 minutes without one
(Part A only).

**What is being checked.** `web/lib/pairing.ts`'s `isRaised` (the pure matching rule);
`web/components/ask/leader.tsx`'s `LeaderStore.hovered`/`useHoverHandlers`/`useHoveredKey`, which
is what lets a claim span and its card — DOM siblings in different columns — raise together;
`web/components/ask/ask-screen.tsx`'s `ClaimSpan` (`tabIndex={0}`, hover and focus handlers) and
`web/components/ask/provenance-margin.tsx`'s `SourceCard` (same handlers, plus `variant="inline"`
for the below-breakpoint card list rendered by `InlineSourceCards`); and the `.ask-claim-raised`
/`.ask-card-raised` CSS in `web/app/globals.css`.

**Where this stops on purpose.** No click-through landing page — that is `M1-VIEW-FE-048`, unchanged
from `M1-CITE-FE-043`. No touch/tap pairing — Askwell is a desktop application; there is no phone
target (ticket's own Known gap).

---

## Before you start

```
cd ~/external/quantum-plus/askwell
```

If you have never run Askwell before:

```
cp -n .env.example .env
```

Open `.env`, find `POSTGRES_APP_PASSWORD`, and put any word after the `=` if it is blank.

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

**You should see:** `postgres`, `redis`, `egress-proxy`, `api`, `worker` reported as started. Wait
about thirty seconds.

### 3. Create the database tables

```
scripts/dev.sh db upgrade head
```

**You should see:** migration lines finish with no error.

### 4. Start native inference

```
scripts/dev.sh inference
```

Leave this running in its own terminal. **You should see:** the process report a loaded model and
stay running. If no model is configured in this environment, skip to **Part A** and read "Known
gaps" for what the rest of this document cannot prove here.

### 5. Open Askwell

Open a browser at:

```
http://127.0.0.1:8000
```

**You should see:** the **Ask your own material** first-run page, window wide (at least
1300px — wide enough for the three-column layout with the right-hand margin visible).

### 6. Add a source

Click **Add a source**. Add a PDF containing at least two separate facts you can check by eye (two
distinct stated figures, terms, or dates, ideally on different pages). Wait for it to reach
`ready` — its row in the ingest progress list stops showing a spinner. Click **Ask** in the left
strip to return.

---

## Part A — get an answer with more than one cited claim

### 7. Ask a question likely to produce two or more cited sentences

Type a question that draws on both facts you noted (e.g. "What is the payment term, and what is
the renewal notice period?"), press **Enter**, and let it finish.

**You should see:** the answer in the centre column with at least two distinct cited sentences,
and, in the right-hand margin, one source card per cited passage, each joined to its claim by a
thin `--rule-strong` leader (carried over from `M1-CITE-FE-043`).

---

## Part B — hovering a claim raises exactly its card

### 8. Move the mouse over one cited sentence in the centre column (not clicking)

**You should see:** that sentence's background lift slightly (`--surface`, via `.ask-claim-raised`),
and, at the same moment, its card in the margin lift and gain a shadow
(`.ask-card-raised[data-raised="true"]`) — a small upward shift plus a drop shadow. The leader line
to that card thickens and turns the provenance teal/green (`--provenance`).

### 9. While still hovering, look at every other card in the margin

**You should see:** no other card is raised — only the one paired to the hovered claim. If two
cited sentences share the same source (see step 12), only that shared card raises when either
sentence is hovered — not otherwise.

### 10. Move the mouse off the sentence

**You should see:** the claim's background and the card's raised state both return to normal.

---

## Part C — hovering a card raises its claim

### 11. Move the mouse over a source card in the margin (not clicking, not the "See full passage" control if present)

**You should see:** the card itself lift with its shadow, and the claim sentence it supports in the
centre column raise its background — the same pairing as Part B, driven from the other side.

---

## Part D — a claim with two cards

### 12. If the answer produced two cards for one sentence (or ask a question likely to force it, e.g. "What is the payment term, and can you confirm it again?")

If the model does not naturally produce two cards for one claim, note this in your result and
continue to Part E.

**You should see:** hovering that one claim raises **both** of its cards at once, not only the
first or the most recent.

---

## Part E — the narrow-window inline fallback

### 13. Drag the browser window narrower, past roughly 1100–1300px, watching the right-hand margin as you go

**You should see:** at some point the margin column disappears and the same source cards reappear
**inline, directly beneath the answer text**, in the same order they had in the margin. No card is
missing — count them against what the margin held in Part A before narrowing.

### 14. Look at the left edge of each inline card

**You should see:** a 2px left border in a grey-green tone (`--rule-strong`), not the teal/green
`--provenance` bar the margin cards had at width. This is deliberate — `provenance-margin.tsx`'s
`SourceCard` switches `edgeToken` by `variant`, and it is the ticket's own point: below the
breakpoint there is no leader, so the edge itself must carry the claim-to-source relationship, and
`--rule-strong` is the token reserved for exactly that (never the decorative `--rule`).

### 15. With the window still narrow, hover a claim in the centre column

**You should see:** no crash, no leader line drawn (there is nothing to draw one to — the margin
column and its `LeaderCanvas` SVG are both hidden below the breakpoint), and the claim's own
background-raise (step 8's `.ask-claim-raised` effect) still happens on the sentence itself. The
inline card does not visibly raise — it does not participate in the leader-line registry at this
width (`SourceCard`'s `variant="inline"` never calls `useCardRef`).

### 16. Widen the window back past the breakpoint

**You should see:** the inline card list disappears, the margin column reappears with the same
cards in the same order, and hovering a claim raises its margin card and leader again exactly as
in Part B.

### 17. Resize the window narrow while a new answer is still streaming (ask another question, then drag narrow mid-stream)

**You should see:** the cards arriving during streaming appear inline as each is cited, the same
"arrives during streaming, not only at the end" behaviour `M1-CITE-FE-043` established for the
margin — nothing breaks or freezes the layout mid-reflow.

---

## Part F — keyboard focus produces the same pairing

### 18. Widen the window back past the breakpoint. Click once into the composer, then press Tab repeatedly

**You should see:** focus moves through the page's controls and eventually lands on a cited claim
span (each is `tabIndex={0}`) — a visible focus outline appears on it. At that exact moment, the
same raise happens as with mouse hover: the claim's background lifts, its card lifts and gains a
shadow, and the leader thickens and turns `--provenance`.

### 19. Continue tabbing past the claim, onto its card's link

**You should see:** the card's link receiving focus keeps the card raised (the claim link's
`onFocus`/`onBlur` in `ClaimSpan`, and the card link's own `onFocus`/`onBlur` in `SourceCard`, both
drive the same shared `hovered` key) — no flicker-off between leaving the claim and entering the
card.

### 20. Tab away from the card entirely

**You should see:** both the claim and the card return to their normal, unraised state.

---

## Part G — measure the contrast, both themes

### 21. At width, with the theme in light mode, use a browser colour-contrast tool (devtools' built-in contrast checker, or a picker plus a calculator) on the leader line against the page background

**You should see:** a ratio at or above 3:1. `docs/ux/design-system.md` §8 records this pair
(`--rule-strong` on `--paper`) as measured at **3.37:1** in light mode.

### 22. Narrow the window, and measure the inline card's left edge against the card background

**You should see:** a ratio at or above 3:1. §8 records `--rule-strong` on `--surface` at
**3.67:1** in light mode.

### 23. Switch to dark theme (the theme toggle in the app's chrome) and repeat steps 21–22

**You should see:** both still at or above 3:1. §8 records the leader at **3.45:1**
(`--rule-strong` on `--paper`) and the inline edge at **3.08:1** (`--rule-strong` on `--surface`)
in dark mode — the tightest pair in the whole palette, called out in §8 as the floor the theme was
tuned against. Confirm the leader and the inline edge are both still visibly distinct from their
background by eye, not just present.

---

## Known gaps

- **No click-through landing.** Clicking a claim or a card link still navigates to
  `/documents/{id}`, which has no page behind it yet (`M1-VIEW-FE-048`) — unchanged from
  `M1-CITE-FE-043`.
- **No touch/tap pairing.** Askwell is a desktop application; there is no phone target, so tap
  behaviour is not exercised (ticket's own Known gap).
- **Overlapping leaders in a very dense answer.** `leader.tsx`'s `LeaderCanvas` draws the raised
  line last so it sits on top of any others it overlaps, but this walkthrough does not force a
  document dense enough to reliably produce overlapping leaders — take this as reviewed by reading
  `LeaderCanvas`'s sort, not independently exercised in the browser.
- **No component test infra exists in this repo** (`web/package.json`'s `test` script runs
  `node --test` over `lib/*.test.ts` only). `web/lib/pairing.test.ts` covers `isRaised`'s matching
  logic in isolation — five cases: nothing hovered, claim raises its card, card raises its claim, a
  claim with two cards raises both, and hovering one claim never raises an unrelated claim's card.
  It does not exercise the DOM, the CSS raise classes, the leader geometry, or the breakpoint
  reflow — this walkthrough is the only place those are exercised. `scripts/dev.sh web-check` only
  confirms the build compiles and lints clean.
- **If no native `llama.cpp` process is available**, Parts A through G are unreachable — generation
  fails with `InferenceUnavailable` before any token or citation event streams, the same limitation
  every ticket since `M0-MODEL-BE-019` has recorded. Only the empty-margin state from
  `M1-CITE-FE-043`'s Part A can be confirmed.
