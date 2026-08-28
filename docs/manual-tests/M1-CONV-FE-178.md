# Manual test — M1-CONV-FE-178, past turns collapse, an abstained turn shows no source count

**Ticket:** `M1-CONV-FE-178` — the Ask screen's conversation view: past turns shrink to
question, stored summary, and source count; the live turn stays full; time dividers between
turns; an abstained collapsed turn is visibly different, with no count.
**Version under test:** `0.2.35`
**Time:** about 20 minutes, with native inference running throughout.
**Who can run it:** anyone who can paste a line into a terminal and use a browser.

**What is being checked.** `web/components/ask/ask-screen.tsx`'s `AskScreen`, specifically
`TurnRow`, `CollapsedTurn`, `SourceCountBadge`, `TurnDivider`, and `LiveTurn` — plus
`web/lib/ask.ts`'s `liveTurnId` (which turn renders full) and `dividerLabel` (the
*earlier today* / *yesterday* / date text between turns). The stored summary and source
count themselves come from the server's `done` event (`M1-CONV-BE-177`) and are not
recomputed here — this ticket only renders what arrives.

**Where this stops on purpose.** Expanding a collapsed turn back to its full answer is
`M1-CONV-FE-179` — not built yet, see **Known gaps**.

---

## Before you start

### 1. Make a source with two separable facts, and one it does not cover

```
mkdir -p ~/askwell-test/conv-178
cd ~/askwell-test/conv-178
python3 - <<'EOF'
from reportlab.pdfgen import canvas
c = canvas.Canvas("suppliers.pdf", pagesize=(612, 792))
c.drawString(72, 700, "Meridian Supply is on standard thirty-day payment terms.")
c.showPage()
c.drawString(72, 700, "Northgate Traders is on standard thirty-day payment terms as well.")
c.showPage()
c.save()
EOF
```

This document says nothing about invoice numbers or late payments — that gap is used
deliberately in step 7 to produce an abstained turn.

### 2. Point Askwell at the folder and bring up the stack

In `.env`:

```
ASKWELL_ROOTS_MOUNT=/home/<you>/askwell-test/conv-178
```

```
podman compose up -d
scripts/dev.sh db upgrade head
scripts/dev.sh inference
```

---

## Part A — cold start, one turn, no collapsing

### 3. Open Askwell and add the source

Go to `http://127.0.0.1:8000`. Click **Add a source**. Drop `~/askwell-test/conv-178` (or
add `suppliers.pdf` directly). Answer the folder question with the folder's absolute path if
asked.

**Expect:** a card for `suppliers.pdf` moves through its states to indexed.

### 4. Wait for indexing

Go to **Library** and wait (refresh as needed) until `suppliers.pdf` shows as ready.

### 5. Go to Ask and ask the first question

Go to **Ask**. Ask:

```
What are Meridian's payment terms?
```

Wait for the answer to finish streaming.

**Expect:** the screen looks exactly like a single-answer screen (`ask.md`) — the question,
the full answer prose with cited claims, the provenance margin (or inline source cards below
the three-column width) beside/under it. **No divider anywhere, and nothing on the screen is
collapsed** — there is only one turn.

---

## Part B — a second question collapses the first

### 6. Ask a second question

Ask:

```
What are Northgate's payment terms?
```

**Expect, the instant it is submitted:**
- The first turn (Meridian) shrinks to **one row**: the question text on the left (in
  `--muted`, truncated if long), a short summary in the middle, and a small filled dot plus
  a number on the right, that number in the provenance colour (a muted teal/green, distinct
  from body text).
- No divider appears between the two turns (same day, no calendar boundary — `dividerLabel`
  returns `null` for same-day turns).
- The second turn (Northgate) renders in full below it — question, streaming steps, the
  answer as it arrives, and its own provenance margin/inline cards once citations arrive.

**Expect, on the collapsed row specifically:** the provenance colour appears **only** on the
source-count number — the question text and the summary text are plain `--muted`/default
ink, not tinted.

### 7. Ask a question the document does not cover

Ask:

```
Which of these suppliers has a late invoice?
```

**Expect:**
- The Northgate turn (previously live) now collapses the same way the Meridian turn did:
  question, summary, count.
- The new turn streams and finishes by abstaining (no citations) — Askwell says it cannot
  answer this from what is indexed.
- Once it finishes and a further action would collapse it (see step 8), it will show the
  abstained collapsed shape. Confirm now, while it is still live, that the answer text says
  it cannot find an answer in what's indexed, not a guess.

### 8. Ask one more question, to actually see the abstained turn collapsed

Ask anything answerable again, e.g.:

```
What are Meridian's terms again?
```

**Expect:** the late-invoice turn (step 7) is now collapsed, and its row is **visibly
different from the two answered rows above it without reading any text**:
- In place of the filled dot + number, it shows an **open circle with a diagonal slash**
  and the words **"No sources"**, in ordinary (not provenance-coloured) text.
- The summary text itself also reads as an abstention (e.g. names that nothing indexed
  answered the question), but the shape difference (dot+number vs. slashed circle) is the
  part that must be visible at a glance, per the ticket.

Confirm the newest turn (Meridian, again) is the one rendering in full with its own margin,
and every earlier turn — including the abstained one sitting between two answered ones — is
collapsed.

---

## Part C — long question truncation

### 9. Ask a question long enough to overflow one line

Ask something clearly over one line at the screen's width, e.g.:

```
Considering everything you know about Meridian Supply's payment terms, their standard invoicing cycle, and how that compares to Northgate Traders' own terms, which of the two would you say is more favourable to us as the buyer and why?
```

Wait for it to finish, then ask a short throwaway question to collapse it.

**Expect:** the long question's collapsed row shows **one line only**, ending in an ellipsis
(`…`) — it does not wrap to a second or third line. Hovering the truncated text (desktop) may
show the full question as a tooltip (`title` attribute); this is a bonus check, not the
acceptance criterion — the criterion is that it stays on one line.

---

## Part D — dark theme, abstained turn still distinguishable

### 10. Switch to dark theme

Use the theme toggle in the shell header. Re-check the abstained turn from step 8.

**Expect:** the slashed-circle "No sources" shape is still clearly present and distinguishable
from a dot+number row in the dark theme — the distinction is carried by shape, not only by a
colour that could wash out.

---

## Part E — a question asked mid-stream queues, does not interleave

### 11. Ask a question, then immediately ask another before it finishes

Ask a question that will take a few seconds to answer, and while it is still streaming
(steps/tokens visible), immediately type and submit a second question.

**Expect:** the second question appears as its own turn immediately, in a muted "waiting"
state (**"Waiting for the question ahead of it."**), stacked below the first — it does not
interrupt or interleave with the streaming answer above it. Once the first turn finishes, it
collapses and the second turn starts streaming in its place as the new live turn.

---

## Part F — time divider (requires waiting or clock skip)

### 12. Confirm the divider text between different days

This step cannot be walked in a single sitting without leaving the machine running
overnight. If you can wait: leave Askwell running, come back a day later, and ask another
question.

**Expect:** a divider reading **"yesterday"** appears above the new turn, sitting between it
and the last turn from the previous day. If several days have passed, the label is instead a
date such as **"March 5"**.

If you cannot wait, this can be sanity-checked at the unit level instead — `dividerLabel` in
`web/lib/ask.ts` is covered by `web/lib/ask.test.ts`; run `scripts/dev.sh web-run test` and
confirm the divider-label tests pass. This does not substitute for the human walkthrough
above; it only confirms the pure function backing it is correct while the multi-day scenario
is impractical to walk live.

---

## What was checked against the ticket's acceptance criteria

- Single turn: no collapsing, no dividers, screen matches `ask.md` exactly — Part A, step 5.
- Second question collapses the first to question/summary/count, second renders full with
  margin — Part B, step 6.
- The count is in the provenance colour and nothing else on the collapsed row is — Part B,
  step 6.
- A collapsed turn that abstained shows no count, distinguishable at a glance (shape, not
  only colour) — Part B, step 8; Part D, step 10.
- The live turn is never collapsed — every part, by construction (only the most recent/
  running turn ever renders via `LiveTurn`).
- Long question truncates to one line rather than wrapping — Part C, step 9.
- Abstained turn sitting between two answered turns reads as absent, not broken — Part B,
  step 8.
- New question mid-stream queues rather than interleaving — Part E, step 11.
- Time divider text — Part F, step 12 (live walkthrough where practical, unit test as
  fallback).
- No rendering fetches a remote asset — open the browser's network panel during any part
  above; every request should be to `127.0.0.1:8000` only (C1).

## Known gaps

Do not report these as defects — they are out of this ticket's scope by its own description:

- **Collapsed turns cannot be expanded yet.** Clicking a collapsed row, or its source count,
  does nothing beyond default browser behaviour — `CollapsedTurn` in `ask-screen.tsx` renders
  a static `<article>`, not a button, and there is no click handler. This is `M1-CONV-FE-179`,
  explicitly split out by this ticket's own scope line. Once a collapsed turn's detail is
  wanted, it is genuinely unreachable until that ticket lands.
- **No paging of long conversations.** `conversation.md` §7 settles on twenty turns before
  paging; nothing in `ask-screen.tsx` limits the rendered list length yet — a long session
  renders every turn. Not a defect for this ticket, which only covers the collapse shape.
- **No suggested follow-ups after an answer.** `conversation.md` §3's suggestion row is
  `M1-CONV-FE-180` — not present on any turn in this walkthrough.
- **No web-search marker on a collapsed turn.** `conversation.md` §5's "a past turn used the
  web" state is `M6.5-WEB-FE-192` — this walkthrough's source is a local PDF only, so that
  state cannot occur yet regardless.
- **A turn citing a since-deleted source was not exercised.** Reproducing it requires
  deleting an indexed document mid-session and is not central to this ticket's own collapse
  behaviour; `sourceCount` is simply whatever the stored `done` event carried, unaffected by
  later deletion, per `conversation.md` §5.
