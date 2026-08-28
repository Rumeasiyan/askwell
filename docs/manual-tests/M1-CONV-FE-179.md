# Manual test — M1-CONV-FE-179, expanding a past turn, a source count, and paging

**Ticket:** `M1-CONV-FE-179` — a collapsed past turn expands in place with its stored answer
and margin; clicking its source count expands it and scrolls to the margin; expansion is
independent per turn; long conversations page older turns in on scroll with a visible
boundary, never a silent truncation; all of the above from the keyboard.
**Version under test:** `0.2.36`
**Time:** about 30 minutes, with native inference running throughout.
**Who can run it:** anyone who can paste a line into a terminal and use a browser.

**What is being checked.** `web/components/ask/ask-screen.tsx`'s `CollapsedTurn` (now
interactive: click/Enter/Space toggles its own `expanded` state, rendering `AnswerProse` and
`InlineSourceCards` beneath the row) and `SourceCountBadge`'s new `onClick` (expand-and-
scroll, as a nested real `<button>`), plus `TurnList`'s windowing over
`web/lib/ask.ts`'s `conversationWindow` and `CONVERSATION_PAGE_SIZE` (twenty).

**Where this stops on purpose.** Editing a past question and re-asking, and suggested
follow-ups, are other tickets — see **Known gaps**.

---

## Before you start

### 1. Make a source with several separable facts

```
mkdir -p ~/askwell-test/conv-179
cd ~/askwell-test/conv-179
python3 - <<'EOF'
from reportlab.pdfgen import canvas
c = canvas.Canvas("suppliers.pdf", pagesize=(612, 792))
c.drawString(72, 700, "Meridian Supply is on standard thirty-day payment terms.")
c.showPage()
c.drawString(72, 700, "Northgate Traders is on standard thirty-day payment terms as well.")
c.showPage()
c.drawString(72, 700, "Delta Fabrication has a rush-order surcharge of twelve percent.")
c.showPage()
c.save()
EOF
```

### 2. Point Askwell at the folder and bring up the stack

In `.env`:

```
ASKWELL_ROOTS_MOUNT=/home/<you>/askwell-test/conv-179
```

```
podman compose up -d
scripts/dev.sh db upgrade head
scripts/dev.sh inference
```

---

## Part A — cold start, add the source, ask five questions

### 3. Open Askwell and add the source

Go to `http://127.0.0.1:8000`. Click **Add a source**. Drop `~/askwell-test/conv-179` (or
add `suppliers.pdf` directly). Wait on **Library** until it shows as ready.

### 4. Go to Ask and ask five questions in sequence

Go to **Ask** and ask each of these, waiting for each to finish streaming before asking the
next:

1. `What are Meridian's payment terms?`
2. `What are Northgate's payment terms?`
3. `Does Delta charge extra for rush orders?`
4. `Which of these suppliers has a late invoice?` (the document says nothing about this —
   expect an abstention, no source count)
5. `What are Meridian's terms again?`

**Expect:** after question 5 finishes, turns 1–4 are collapsed rows (question, one-line
summary, source count or "No sources" for turn 4) and turn 5 renders full, live, with its
own margin.

---

## Part B — expand a collapsed turn in place

### 5. Click the second collapsed turn (Northgate)

Click anywhere on its row (not the source-count number).

**Expect:** the row opens **in place** — directly beneath it, its stored answer text
appears (the same answer it streamed the first time, word for word), followed by its own
provenance margin/inline source cards (a card naming `suppliers.pdf`), followed by a
**Collapse** button. Every other row — turns 1, 3, 4, and the live turn 5 — is unchanged:
still collapsed (or still live), not expanded, not re-ordered, not re-styled.

### 6. Click through a card and come back

Click one of the source cards under the expanded Northgate turn.

**Expect:** you land on `suppliers.pdf` with the cited page highlighted. Use the browser's
back control (or the context rail's own return path) to come back to Ask.

**Expect:** you are back at the same point in the conversation — the Northgate turn is
still expanded, in the same scroll position, not reset to the top and not re-collapsed.

### 7. Collapse it again

Click the **Collapse** button under the expanded Northgate turn (or click the row itself
again).

**Expect:** the answer and margin disappear; the row returns to its one-line collapsed
shape. Nothing else on the screen moves.

---

## Part C — a source count expands and scrolls to the margin

### 8. Click the source count on a different collapsed turn (Meridian, turn 1)

Scroll so that turn 1's collapsed row and its would-be margin are not both already in
view, then click the small dot-and-number on the right of its row (not the row's question
or summary text).

**Expect:** the turn expands (answer and margin appear, same as Part B) **and** the view
scrolls so the newly-revealed margin is brought into view — you should not have to scroll
manually to find it. Clicking the source count again while it is already expanded scrolls
to the margin again without collapsing it.

---

## Part D — expanding during a live stream

### 9. Ask a sixth question, and while it streams, expand an old turn

Ask:

```
Summarise everything you told me about these three suppliers.
```

While its steps/tokens are visibly still arriving, click the collapsed Delta turn (turn 3)
to expand it.

**Expect:** the Delta turn opens in place exactly as before, and **the live turn keeps
streaming, undisturbed** — tokens keep appearing in the sixth turn's answer, its steps line
and Stop control behave normally, and nothing about the live turn re-renders from scratch
or stalls because another turn expanded.

---

## Part E — several turns expanded at once

### 10. Expand two more collapsed turns without collapsing the first

With Delta (turn 3) still expanded from Part D, also expand Meridian (turn 1) if you
collapsed it in step 8, and the abstained turn (turn 4).

**Expect:** all three stay expanded simultaneously — expanding one never collapses another.
The abstained turn (turn 4), when expanded, shows its own stored answer (the "cannot answer
this from what's indexed" text) and **no** source-card margin, since it has no citations —
not an empty box, nothing rendered there at all beyond the text.

---

## Part F — keyboard parity

### 11. Tab to a collapsed row and expand it with the keyboard only

Click into the page once (e.g. the composer), then press `Tab` repeatedly until focus
visibly lands on a collapsed turn's row (it is a focusable `role="button"`). Press `Enter`.

**Expect:** the turn expands, identically to a mouse click.

### 12. Collapse it with `Space`

With focus still on that same row, press `Space`.

**Expect:** the page does not scroll (the space keypress is intercepted, not left to the
browser's default scroll-on-space) and the turn collapses.

### 13. Tab to a source count and activate it with the keyboard

Tab until focus lands on a source-count control on a different collapsed turn (it is a
nested real `<button>`, so it takes its own tab stop after the row). Press `Enter`.

**Expect:** that turn expands and its margin scrolls into view, the same as clicking it.

---

## Part G — narrow window, margin reflows inline

### 14. Narrow the browser window below the three-column breakpoint

Resize the window (or use devtools' responsive mode) until the provenance margin `<aside>`
disappears from the shell (`@5xl` breakpoint).

### 15. Expand a collapsed turn at this width

Click a collapsed turn.

**Expect:** its source cards appear **inline**, directly under its answer text (not in a
side column, since there is none at this width), each card showing a complete filename,
page/heading label, and passage — not truncated or cut off — with a visible left edge in
`--rule-strong` (not `--provenance`, since there is no leader line to justify the
provenance colour at this width).

---

## Part H — paging a long conversation

### 16. Ask enough further questions to exceed twenty turns

Ask short throwaway questions (e.g. `What are Meridian's terms?` repeated, or vary the
wording) until the conversation holds more than twenty turns in total. This is tedious by
hand; the fastest way is to keep asking short answerable questions and count as you go, or
accept it will take fifteen-plus questions.

### 17. Scroll to the top of the conversation

**Expect:** once you scroll near the top, a boundary row reading **"Load earlier turns"**
appears above the oldest visible turn, and scrolling it into view (or clicking it) reveals
the next batch of twenty older turns rather than doing nothing. Repeat until every turn
that was ever asked in this session is visible.

### 18. Confirm the genuine end

Once every turn has loaded, check the boundary row again.

**Expect:** it now reads **"Start of this conversation"** — not silence, not an infinitely
spinning loader, not an empty space where the button used to be. This is the same row,
re-labelled, so a user scrolling up always finds *something* there rather than a
conversation that quietly stops having a beginning.

---

## What was checked against the ticket's acceptance criteria

- Clicking a collapsed turn expands it in place with its full stored answer and margin,
  and no other turn changes state — Part B, step 5.
- Clicking a source count expands the turn and brings its margin into view — Part C,
  step 8.
- An expanded past turn can be collapsed again — Part B, step 7.
- Independent expansion — several turns expanded at once, expanding one never collapses
  another — Part E, step 10.
- Expanding a past turn while a new answer streams: both render, live turn undisturbed —
  Part D, step 9.
- A turn whose citation is a since-deleted source — **not exercised**, see Known gaps.
- A very long expanded answer / preserved scroll position — covered incidentally in step 6
  (returning from a card click preserves position); not stress-tested with an
  exceptionally long answer.
- Reflowed margin below the breakpoint, complete and with `--rule-strong` edges — Part G,
  step 15.
- Paging loads older turns with a visible boundary; genuinely-no-more says so rather than
  stopping silently; never renders a shorter conversation as if it were the whole one —
  Part H, steps 17–18.
- Keyboard parity for expand, collapse, and source-count activation — Part F,
  steps 11–13.
- No rendering fetches a remote asset — open the browser's network panel during any part
  above; every request should be to `127.0.0.1:8000` only (C1).
- An expanded turn shows exactly what was stored, never a regenerated answer — by
  construction, checked in Part B step 5 (answer text matches what streamed originally) —
  `CollapsedTurn` renders `turn.answer` from in-memory state, never re-issues `/ask`.

## Known gaps

Do not report these as defects — they are out of this ticket's scope, or the repo's current
state, by its own description:

- **A turn citing a since-deleted source was not exercised, and cannot render its
  tombstone yet.** `conversation.md` §5 and `states-and-edge-cases.md` §7.1 both call for
  expanding such a turn to show a greyed, unclickable tombstone card. Reading
  `web/components/ask/provenance-margin.tsx`'s `SourceCard`, there is no tombstone branch —
  it always renders a live `Link` to the document. That rendering is `M2-DELETE-FE-062`,
  explicitly out of this ticket's scope; until it lands, deleting a cited source mid-session
  and re-expanding the turn would show a normal (and likely broken) card, not a tombstone.
- **Paging failure is not exercised.** The ticket's edge case "paging fails to load older
  turns — says so and offers to retry" cannot occur in the current build: `TurnList`'s
  `revealMore` only grows an in-memory window (`conversationWindow`, `lib/ask.ts`) over
  turns `AskProvider` already holds — there is no network request to fail, since nothing yet
  threads a `conversation_id` across turns to page against the server (`ask-screen.tsx`'s
  own comment on `TurnList`, referencing issue #156). A failure state has nothing to test
  against until that reload path exists.
- **No suggested follow-ups.** `conversation.md` §3's suggestion row after an answer is
  `M1-CONV-FE-180` — not present on any turn in this walkthrough.
- **No web-search marker on a collapsed or expanded turn.** `conversation.md` §5's "a past
  turn used the web" state is a later ticket; this walkthrough's source is a local PDF
  only, so that state cannot occur regardless.
- **Editing a past question and re-asking is not built**, deliberately — `conversation.md`
  §7 defers it to usage evidence, not v1.
- **The twenty-turn page size is a starting guess**, not a measured value
  (`conversation.md` §7) — do not read step 16's "more than twenty" threshold as itself
  validated against real usage.
