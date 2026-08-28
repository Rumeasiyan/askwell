# Manual test — M1-CITE-FE-043, the provenance margin with source cards and leaders

**Ticket:** `M1-CITE-FE-043` — the permanent right-hand margin: one card per cited claim showing
filename, page or anchor, and the exact retrieved passage, joined to its claim by a hairline
leader, arriving as claims are cited during streaming, with an explicit empty state and no
toggle.
**Version under test:** `0.2.24`
**Time:** about 30 minutes, with a native inference process running; 10 minutes without one
(Part A only).

**What is being checked.** `web/components/ask/provenance-margin.tsx`'s `ProvenanceMargin`,
rendered inside `Shell`'s permanent `<aside aria-label="Provenance">` (`shell.tsx`); one
`SourceCard` per entry in the live turn's `citations` (`AskTurn.citations`, grouped by
`applyCitation` in `web/lib/citations.ts` — one card per `chunk_id`, one `claimOrdinal` per claim
that cites it); and `web/components/ask/leader.tsx`'s `LeaderCanvas`, an SVG overlay drawing one
line per claim-to-card pair from `useLiveLeaderPairs` (`provenance-margin.tsx`).

**Where this stops on purpose.** No hover raise, no narrow-window inline fallback
(`M1-CITE-FE-044`) — the margin simply disappears below the `@5xl` breakpoint rather than
reflowing. No click-through landing page — the card and claim link to `/documents/{id}`, a route
that does not exist yet (`M1-VIEW-FE-048`). No deleted-source rendering — deletion does not exist
until `M2`.

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

**You should see:** the **Ask your own material** first-run page.

---

## Part A — the margin is present before anything is asked

### 6. Look at the right-hand edge of the window

**You should see:** a right column, separated by a vertical rule, with the muted text "Sources
appear here, beside the claims they support." It is not a drawer, not collapsed, not behind a
toggle — it occupies its own fixed-width strip beside the first-run page itself.

### 7. Add a source

Click **Add a source**. Add a PDF containing a fact you can check by eye (a stated figure, a
named term, a date). Wait for it to reach `ready` — its row in the ingest progress list stops
showing a spinner.

### 8. Return to Ask

Click **Ask** in the left strip (or the Askwell wordmark).

**You should see:** the composer, and the margin on the right still reads "Sources appear here,
beside the claims they support." — unchanged, since nothing has been asked yet in this session.

---

## Part B — cards arrive as claims are cited, during streaming

### 9. Ask a question with a known factual answer from the source you added

Click into the composer, type a question the source answers (e.g. "What is the payment term?"),
press **Enter**.

**You should see:** named retrieval steps first, then the answer's tokens appear one at a time in
the centre column.

### 10. Watch the right-hand margin while the answer is still streaming

**You should see:** a source card appear in the margin **before the answer finishes** — as soon
as the sentence carrying its citation completes, not only once the whole answer is done. Each
card shows, top line, the source's filename and a page or section label (`p. 4`, `pp. 4–6`, or,
for a non-paginated source, a slide/row/section label); below that, the exact quoted passage in
quotation marks.

### 11. Watch for the leader

**You should see:** a thin line drawn from the cited sentence in the centre column to its card in
the margin, appearing at (or shortly after) the moment the card itself appears — not before the
card exists, not permanently absent.

### 12. Let the answer finish

**You should see:** the final answer, with as many cards in the margin as there are distinct
cited passages, each with at least one leader reaching it.

### 13. Confirm one passage against the file

Pick one card, open the source PDF separately (any PDF viewer), and turn to the page the card
names. **You should see:** the quoted passage on the card really is on that page, verbatim or
near enough that partial-sentence truncation is the only difference.

---

## Part C — the two-claims-one-passage edge case

### 14. Ask a question likely to cite the same passage twice

Ask something that plausibly restates or re-cites the same fact within one answer (e.g. "What is
the payment term, and can you confirm it again in different words?"). If the model does not
naturally produce this, accept whatever it actually produces and move to step 16 with a note that
this case was not exercised.

### 15. If two claims did cite the same chunk

**You should see:** exactly **one card** for that passage, not two duplicate cards — and **two
leaders** reaching it, one from each cited sentence in the centre column.

---

## Part D — a question with no factual claims

### 16. Ask something with no citable factual content

Ask a question that draws a conversational, non-factual response (e.g. "Thanks, that's helpful.")
or a question the model answers without citing anything.

**You should see:** the margin explicitly reads "Nothing in this answer was cited." — not blank,
not the first-run copy from step 6 (that copy is only for before any turn has completed), and
still occupying its column.

---

## Part E — a long passage truncates, with a way to see it in full

### 17. Find a card whose passage is long (over roughly 220 characters)

If none of the passages above were long, ask a question likely to retrieve a longer paragraph.

**You should see:** the passage cut off with a trailing "…" and a **See full passage** control
beneath it.

### 18. Click **See full passage**

**You should see:** the full passage replaces the truncated text, and the control now reads
**Show less**.

### 19. Click **Show less**

**You should see:** the passage returns to its truncated form.

---

## Part F — the provenance colour is reserved

### 20. Look across the whole screen — composer, buttons, links, the margin

**You should see:** the teal/green provenance colour (`--provenance`, `design-system.md` §3)
appears only on: the filename/page line of each source card, and its left border accent. It does
not appear on the **Ask** button, the sidebar, the status dot's "Ready" state (a different colour
happens to be visually close — compare directly against a card's border rather than judging by
eye alone), or any other control.

---

## Part G — click a card

### 21. Click anywhere on a source card (not the "See full passage" control)

**You should see:** the browser navigates to `/documents/{id}` — since that route is not built
yet (`M1-VIEW-FE-048`), expect a 404 or the app's own not-found page, not a JavaScript error and
not a silent no-op. This confirms the link target is wired to the right document id and page
query string (visible in the address bar: `?page=N` matching the card's page label), not that a
viewer opens — there is no viewer yet.

---

## Known gaps

- **No hover raise.** Hovering a claim or a card does nothing beyond the browser's own link
  hover — `ask.md` §4's "hover a cited claim, its leader and card raise" is `M1-CITE-FE-044`, not
  this ticket.
- **No narrow-window fallback.** Below the `@5xl` container-query breakpoint the margin
  disappears entirely (`shell.tsx`'s existing `hidden … @5xl:block`) rather than reflowing inline
  under each answer. Also `M1-CITE-FE-044`.
- **No real click-through landing.** The card and claim link to `/documents/{id}?page=N`, which
  is the correct target per this ticket's Out of Scope line ("the click is wired here to the
  route") but there is no page there yet to land on — `M1-VIEW-FE-048`.
- **No deleted-source rendering.** A card for a document whose source has been deleted does not
  render as *deleted, greyed* — deletion does not exist anywhere in the product until `M2`, so
  this edge case from the ticket's own Acceptance Criteria cannot be exercised.
- **Fifty-card virtualisation is moot, not solved.** `ask.md` §8 settles this by ruling it out:
  past turns collapse (`M1-CONV-FE-180`, not yet built), so only the live turn's margin is ever
  shown and a fifty-card margin cannot occur under the current build. There is nothing to test
  here beyond confirming this document doesn't invent a scenario the app cannot reach.
- **No component test infra exists in this repo** (`web/package.json`'s `test` script runs
  `node --test` over `lib/*.test.ts` only — `citations.test.ts` and `claims.test.ts` cover the
  pure merge/segmentation logic, not rendering). This walkthrough is the only place the card
  markup, leader geometry, and truncation control are actually exercised in a browser;
  `scripts/dev.sh web-check` only confirms the build compiles and lints clean.
- **If no native `llama.cpp` process is available**, Parts B through G are unreachable —
  generation fails with `InferenceUnavailable` before any token or citation event streams, the
  same limitation every ticket since `M0-MODEL-BE-019` has recorded. Only Part A (the empty
  states) can be confirmed.
