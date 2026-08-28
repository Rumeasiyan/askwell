# Manual test — M2-ABSTAIN-FE-055, the abstained state on Ask

**Ticket:** `M2-ABSTAIN-FE-055` — render abstention as its own state on the Ask screen: full
measure, `--ink`/`--muted`, never `--alarm`; the margin's explicit empty state; an **Add a
source** action below the abstention statement that retains the question; a collapsed abstained
turn showing no source count.
**Version under test:** `0.2.43`
**Time:** about 30 minutes, with a native inference process running; 10 minutes without one
(Part A and the layout check in Part D only).

**What is being checked.** `web/lib/ask.ts`'s `isAbstained` (a completed turn, empty answer text,
non-null `reason`); `AbstentionState` and `AddSourceAction` in
`web/components/ask/ask-screen.tsx`, wired into both `LiveTurn` and an expanded `CollapsedTurn`;
`ProvenanceMargin`'s third empty-state branch in `web/components/ask/provenance-margin.tsx`; and
`SourceCountBadge`'s "no sources" shape for a collapsed abstained turn.

**Where this stops on purpose.** No escalation offer of any kind — no "search the web", no "ask a
larger model", both are `M6.5-WEB-FE-186`, not built and must not appear even disabled (C10). No
threshold control, no trace panel (both `M5`). No streamed abstention text — the composed message
arrives whole in one `done` event, never token by token.

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
gaps" for what the rest of this document cannot prove here — abstention still requires a real
retrieval pass to trigger it.

### 5. Open Askwell

Open a browser at:

```
http://127.0.0.1:8000
```

**You should see:** the **Ask your own material** first-run page.

### 6. Add a source with a narrow, checkable topic

Click **Add a source**. Add one file whose content is about a specific, narrow topic (e.g. a
single-page PDF about a return policy, or a spreadsheet about one product). Wait for it to reach
`ready` — its row in the ingest progress list stops showing a spinner.

### 7. Return to Ask

Click **Ask** in the left strip (or the Askwell wordmark).

---

## Part A — a covered question answers normally first

### 8. Ask a question the source actually answers

Type a question you know the source covers, press **Enter**.

**You should see:** named retrieval steps, then streaming answer text, then a populated margin
with at least one source card — the ordinary answered state. This is the baseline the next step's
visual contrast depends on.

---

## Part B — the abstained state itself

### 9. Ask a question the corpus does not cover

Type a question about something clearly unrelated to what you added (e.g., if you added a return
policy, ask "What was our Q3 revenue in the Nairobi office?"). Press **Enter**.

**You should see:** named retrieval steps, then — instead of streaming answer tokens — a block of
text appears at once, in noticeably more vertical space than the answer above it got. Compare the
two turns directly on screen: the abstention is not squeezed into the same rhythm as a paragraph
of prose.

### 10. Read the abstention text

**You should see** three lines, in this order:

1. A situation statement (e.g. "Nothing in your files answers this."), in the darkest/main text
   colour (`--ink`).
2. A line naming how many passages, documents (and databases, if any) were actually searched, and
   the closest material found, in a visibly lighter/muted colour (`--muted`).
3. A next-action line ("Add the source you'd expect this in, and ask again." or similar), also
   muted.

**You should not see:** red or orange colouring anywhere in this block, an apology, a hedge
("it might be...", "possibly..."), or any answer text attempting to address the question anyway.

### 11. Compare colour against a real failure, if you can trigger one

If convenient, compare this block's colour by eye against any `--alarm`-coloured text elsewhere in
the app (for example, stop the `inference` process and ask another question to see the "assistant
unavailable" failure state). **You should see:** the abstention text and the failure text are
visibly different colours — the abstention never borrows the failure colour.

### 12. Look at the right-hand margin

**You should see:** the margin reads exactly **"No sources — nothing in your files matched."** —
not the plain "Nothing in this answer was cited." wording from an ordinary uncited answer (Part A
would show that instead if the model answered without citing anything), and not blank.

### 13. Look below the abstention text

**You should see:** exactly one control, an **Add a source** button, sitting in its own region
below all three lines of the abstention text. **You should not see** anything else in that
region — no other buttons, no search/escalation options, nothing above the abstention statement.

---

## Part C — the add-a-source action retains the question

### 14. Note the question you just asked, then click **Add a source**

**You should see:** the browser navigates to the add-source screen (`/sources/add/`).

### 15. Add a source relevant to the question you asked

Add a file that actually covers the topic from step 9's question (or, if that is impractical,
note that this step continues with a source known to still not cover it, and expect abstention
again in step 17 — call this out in your result rather than treating it as a defect). Wait for it
to reach `ready`.

### 16. Return to Ask

Click **Ask** in the left strip.

**You should see:** the composer already contains the exact question you asked in step 9,
unsent — not a blank composer, not a submitted question.

### 17. Press **Enter** to re-ask it

**You should see:** if the newly added source actually covers the topic, a normal streamed answer
with citations this time. If it does not, the same abstained state as before — either outcome
confirms the question survived the round trip; only the retrieval result differs.

---

## Part D — a collapsed abstained turn shows no source count

### 18. Ask one more question (covered or not, either works) so the abstained turn from Part B collapses

Ask any other question. Once it completes, the turn from Part B (or step 17, if it re-abstained)
is no longer the live turn.

**You should see:** that turn collapsed to one line: the question (truncated), a stored summary,
and — where an answered turn shows a filled dot plus a number — an **open, slashed circle icon
next to the text "No sources"**, in a muted colour, not the provenance teal/green.

### 19. Compare it directly against a collapsed answered turn

Look at the collapsed row from Part A's question alongside this one.

**You should see:** the answered turn shows a filled circle and a number in the provenance colour;
the abstained turn shows the slashed-circle "No sources" shape in muted colour. The distinction is
visible from the icon shape alone, not only the colour — confirm this by squinting or, if
convenient, viewing the page with a greyscale browser extension or OS-level greyscale mode.

### 20. Click the collapsed abstained row to expand it

**You should see:** it re-opens the exact same abstention text from step 10, the same margin empty
copy from step 12, and the same **Add a source** button from step 13 — nothing was lost by
collapsing and re-expanding.

---

## Part E — abstention right after a normal answer reads as distinct in sequence

### 21. Scroll to view the answered turn from Part A and the abstained turn from Part B together, if both are still visible before collapsing

(If you already collapsed them in Part D, expand both by clicking their rows.)

**You should see:** even placed back to back, the two are unmistakably different — one is dense
prose with a populated margin and a numbered source badge; the other is spaced-out `--ink`/`--muted`
text with the "No sources" margin copy and no citation cards.

---

## Part F — narrow window

### 22. Narrow the browser window below roughly 1024px wide

Ask another uncovered question, or re-expand the one from Part B.

**You should see:** the abstention text and the **Add a source** button still render correctly,
full width, in the single centre column — the margin (now hidden or stacked, per the existing
narrow-window layout) does not need to be visible for the abstention statement itself to read
correctly.

---

## Known gaps

- **No escalation offer**, by design — no "search the web" or "ask a larger model" option
  anywhere on this screen, disabled or otherwise. That is `M6.5-WEB-FE-186`; its absence here is
  correct, not a defect to report.
- **No threshold control and no trace panel.** Both `M5`. The near-miss score and reason code
  exist in `messages.trace` (`M2-ABSTAIN-RET-053`) but nothing on this screen surfaces them yet.
- **No voice abstention.** `M6`. This walkthrough only covers typed questions.
- **No streamed abstention text.** The whole message (situation, proof, next action) appears at
  once when the `done` event arrives — there is no per-token reveal to watch, unlike an answered
  turn's streaming tokens. This is correct: the message was never generated token by token
  (`M2-ABSTAIN-BE-054`), so faking a stream would be pointless.
- **Whether re-asking in Part C actually answers depends on real retrieval and a real model.**
  Without `scripts/dev.sh inference` running, Parts A, B, C, D, and E cannot be exercised past the
  point retrieval or generation is needed — `InferenceUnavailable` fails the turn instead, the
  same limitation every ticket since `M0-MODEL-BE-019` has recorded.
- **No component test infra exists in this repo** (`web/package.json`'s `test` script runs
  `node --test` over `lib/*.test.ts` only). This walkthrough is the only place `AbstentionState`,
  `AddSourceAction`, and the collapsed "no sources" badge are actually exercised in a browser;
  `scripts/dev.sh web-check` only confirms the build compiles, lints, and passes `isAbstained`'s
  unit tests.
