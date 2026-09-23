# Manual test — M7-FIX-FE-169, the composer belongs below the conversation

**Ticket:** `M7-FIX-FE-169` — the Ask screen drew the question box at the top of the centre
column and the answers beneath it, so the conversation read backwards. The box now sits last
in the column, below what it produced, as `docs/ux/screens-reference.html` draws it. Input,
buttons and answers share one right edge.

**Version under test:** `0.7.25`
**Time:** about 30 minutes, with a native inference process running.

**What is being checked.** `web/components/ask/ask-screen.tsx`:

- `AskScreen` — `<Composer />` is now the last thing in the column, after the turn list.
- `Composer` — wrapped in a bar pinned to the bottom of the scrolling column (a thin rule
  along its top edge, the page's own background colour behind it), with everything inside in
  one box at the answer width (`.ask-measure`, `web/app/globals.css`). Clicking **Ask** now
  puts the cursor back in the box, the same as pressing `Enter` always did.
- `followsNewTurn` (`web/lib/ask.ts`) — when a *new question* is added, the column scrolls to
  the end so it sits directly above the box. It does **not** scroll while an answer is
  streaming in, and does not scroll on first load.

**Where this stops on purpose.** Nothing about what the composer *does* changed — `Enter`
sends, `Shift+Enter` makes a new line, suggestions fill without sending. Where the margin cards
sit vertically is `M7-FIX-FE-171`'s, not this ticket's.

**The product decision this tests is settled.** The composer goes at the bottom (product owner,
2026-09-23). If something here looks wrong, report the code as the defect — do not propose
moving the box back to the top or editing the mockup.

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

You will add five small files that already live in the repository, under
`eval/fixtures/corpus/`:

- `conflict_2025.pdf` and `conflict_2026.pdf` — two versions of the same company policies
  that disagree with each other
- `spec.docx` — a one-page product specification for the "Loomwear Sensor Mk3"
- `store_hours_2025.pdf` and `store_hours_2026.pdf` — one line each about store closing times

You will need a ruler, or the straight edge of a sheet of paper, for the "one right edge"
checks.

---

## Cold start

### 1. Build the interface

```
scripts/dev.sh web-build
```

**You should see:** a Next.js build finishing with a route list and no red error text.

### 2. Bring the stack up, fresh

```
podman compose up -d --force-recreate api
podman compose up -d
```

The first line matters: without it the running `api` container can keep serving the interface
from before step 1, and you will be testing the old layout without knowing it.

**You should see:** `postgres`, `redis`, `egress-proxy`, `api`, `worker` reported as started.
Wait about thirty seconds.

### 3. Create the database tables

```
scripts/dev.sh db upgrade head
```

**You should see:** migration lines finish with no error.

### 4. Start native inference

In a second terminal:

```
scripts/dev.sh inference
```

Leave it running. **You should see:** it report a loaded model and stay running. Without this,
Parts A–B still work, but every question after that will fail to answer, and Parts C–H need
real answers.

### 5. Open Askwell

Open a browser at:

```
http://127.0.0.1:8000
```

Make the browser window wide — maximised on a normal laptop screen, or at least about 1300
pixels across — so you can see a narrow column of links on the left, the main column in the
middle, and a panel headed with source cards on the right.

**You should see one of three things:**

- **Welcome to Askwell**, with four numbered steps — this appears on a machine that has never
  indexed anything. Click **Skip setup** in its top-right corner. (The wizard is other tickets'
  territory; skipping it is the fastest honest route to Ask.)
- **Ask your own material** — go to step 6.
- The Ask screen with a question box already showing — sources already exist on this machine.
  Go to step 7 and read "If you already had sources" there.

---

## Part A — nothing added yet

### 6. The empty first-run page has no question box, on purpose

On **Ask your own material**:

**You should see:** a heading, a paragraph, and a bordered box saying **Nothing added yet**
with an **Add a source** button. **No question box anywhere** — there is nothing to ask about
yet, and that is unchanged by this ticket. Do not report it as the composer being missing.

### 7. Add the five files

Click **Add a source**. On the add screen, click **Choose files**, go to your copy of the
repository, open `eval/fixtures/corpus/`, and select the five files listed in "Before you
start". Confirm the selection.

**You should see:** the five files listed with progress; within a minute or two each reaches a
finished state (no spinner beside it).

Click **Ask** in the left-hand column of links.

*If you already had sources:* that is fine, but earlier conversations may already be on screen.
Reload the page; if old questions are still there, the checks in Part B still apply to the
bottom of the column, and Part C will simply start with more above it.

---

## Part B — no questions asked yet

### 8. Where the box is, before anything is asked

**You should see, reading down the middle column:**

1. A small grey line: `Askwell 0.7.25 · nothing leaves this machine`. **Check the number reads
   `0.7.25`** — if it reads anything older, step 2's first line did not take; stop and redo it.
2. A small label **From what you have added**, then up to three clickable questions built from
   your files (real words from them — "Mk3", "return window" or similar). If this label is
   missing, the files may still be indexing; you would instead see "Still indexing what you
   added…". Wait and reload.
3. A thin horizontal line across the column, and directly under it the question box, with the
   grey hint text **Ask about your own files and databases**.
4. Under the box, on the right: a microphone control and an **Ask** button, which looks dimmed.

**Also check:** the question box is visible **without scrolling**, and a blinking text cursor is
already inside it. Type one letter without clicking anything first — it should appear in the
box. Delete it.

### 9. One right edge, empty state

Hold your ruler or paper edge vertically against the screen, lined up with the right-hand edge
of the question box.

**You should see:**

- The right edge of the **Ask** button lines up with the right edge of the box, on the same
  vertical line.
- None of the suggested questions above run past that line.
- The thin rule above the box runs wider than the box — that is expected; it is the floor of
  the whole column, not part of the box.

For reference, on a 1600-pixel-wide window the box, the button and answer text all end about
858 pixels from the left of the window. Before this ticket, the box, the button row and the
suggestions ended at three different places.

---

## Part C — ask two questions, one each way

### 10. Ask the first question with the keyboard

Click in the box if the cursor is not already there. Type:

```
What is the standard product return window?
```

Press **Enter**.

**You should see:**

- The suggested questions disappear.
- Your question appears **above** the box, followed by a short working label, then an answer
  arriving word by word.
- The box stays at the bottom of the column, empty, with the text cursor still blinking inside
  it. **Do not click anything.** Type one letter — it lands in the box. Delete it.

This question deliberately touches the two files that disagree, so a good answer names both
figures (thirty days in 2025 per `conflict_2025.pdf`, forty-five days in 2026 per
`conflict_2026.pdf` — check the numbers against the source cards, not against this document)
and shows cards for both files in the right-hand panel. If instead Askwell says it found
nothing, that is a known answer-quality problem, not this ticket — see Known gaps — and the
layout checks below still apply.

### 11. Ask the second question with the button

Wait for the first answer to finish. Type:

```
How long does the Loomwear Sensor Mk3 battery last on one charge?
```

This time **click the Ask button** instead of pressing Enter.

**You should see:**

- The first exchange shrinks to a shorter summary above; the new question and its answer appear
  below it and directly above the box.
- The text cursor is **back in the box**, not left on the button. Type a letter to prove it,
  then delete it. (Before this ticket, the cursor stayed on the button after a click.)
- The answer should say eleven hours and cite `spec.docx`.

### 12. Read the column top to bottom

Scroll to the very top of the middle column, then read slowly down to the bottom.

**You should see, in this order:** the version line → your first question and its answer →
your second question and its answer → the thin rule → the question box → the microphone and
**Ask** button. Nothing comes after the button. At no point do you pass an empty question box
on your way down to the newest answer.

### 13. One right edge, with answers

Line your ruler up with the right edge of the question box again.

**You should see:** the longest lines of answer text above end on (or just short of) the same
line as the box and the **Ask** button. Answer paragraphs never run past the box's edge, and the
box never reaches past the answer text.

---

## Part D — the leaders

This needs the right-hand panel, so keep the window wide (step 5).

### 14. Hover a cited claim

Scroll so the second answer (the battery one) is in view. Move the mouse over the sentence in
the answer that carries a citation.

**You should see:** a thin line (the "leader") appear from that sentence across to its card in
the right-hand panel, and the card highlight. The line runs **mostly sideways** — left to right
with a modest slope — not a steep diagonal from high on the right down past an empty box to the
bottom. Do the same on the first answer's claims.

The cards themselves still stack from the top of the right-hand panel rather than lining up
level with their sentences, so on a claim far down the column the line will slope more. That is
`M7-FIX-FE-171`'s area (see Known gaps); report a leader as wrong only if it crosses over the
question box, or points at the wrong card.

---

## Part E — a long conversation

### 15. Make the window short

Un-maximise the browser and drag its bottom edge up until the window is only about half the
height of your screen. Keep it wide.

**You should see:** the question box is still on screen, pinned to the bottom of the window,
with the thin rule above it. The answers are cut off above it.

### 16. Scroll through the answers

Scroll the middle column up and down.

**You should see:** answer text slides **underneath** the box and disappears behind it — you
never see words showing through the box or its band. The box itself does not move.

In the top-right corner, click **Dark**, scroll again, then click **Light** and scroll once
more. The same should hold in both themes: the band behind the box is solid, the same
colour as the page.

### 17. Ask a question that produces a long answer, and scroll up while it streams

Ask:

```
Summarise every policy that changed between 2025 and 2026.
```

Press **Enter**. As soon as the answer starts arriving, scroll **up** to read your first
question.

**You should see:**

- When you pressed Enter, the column jumped down so the new question sat just above the box.
- Once you scroll up, the page **stays where you put it** while the answer keeps arriving — it
  does not keep dragging you back down with every new word.
- The box stays at the bottom of the window the whole time, however long the answer grows.

### 18. Ask while an answer is still arriving

Scroll back to the bottom. Ask something, and while its answer is still arriving, type a second
question and press **Enter**.

**You should see:** the second question is accepted (it is not refused, and the box is never
greyed out), it appears waiting below the first, the column scrolls to show it, and the cursor
stays in the box.

Restore the window to full size.

---

## Part F — keyboard order

### 19. Tab from the top of the screen

Click once on the small grey version line at the top of the middle column (this puts the
keyboard's starting point at the top without selecting a control). Press **Tab** repeatedly,
watching where the focus outline goes.

**You should see, in order:** any links or buttons inside the conversation (citation markers,
**How did you get this?**, follow-up suggestions, and so on) from top to bottom → the question box → the
microphone control → the **Ask** button (skipped while it is dimmed and the box is empty) → the
right-hand panel's cards. The question box comes **after** the conversation, never before it.
Nothing jumps back up to the conversation from the box.

Press **Shift+Tab** from the question box. **You should see:** focus move back up into the last
answer's controls — the reverse of the same order.

Before this ticket the box came first in this order; now it comes last, which is the change
being tested. Focus still starts *in* the box when the screen opens (step 8), so nobody has to
tab through a long conversation to start typing.

---

## Part G — the other ways text reaches the box

### 20. A suggestion fills the box at the bottom

At the end of an answer, under **Follow up**, click one of the suggested questions (if the
answer shows none, skip to step 21).

**You should see:** the question appear inside the box at the bottom, **not sent** — the
cursor is in the box and you still have to press Enter. The page does not jump to the top.

Clear the box (select all, delete).

### 21. "Ask about this source" from the Library

Click **Library** in the left-hand column. Click `spec.docx` to open it. In the panel beside
the document, click **Ask about this source**.

**You should see:** you land back on Ask, with the box at the bottom and a small line directly
above the text inside the box reading **Scoped to spec.docx** and a **Clear** link. The
**Clear** link and the **Ask** button both stay within the box's right edge (ruler again).

Click **Clear**. **You should see:** the "Scoped to" line disappears; nothing is sent.

### 22. "Back to answer" still lands on the right sentence

Hover the battery answer's cited sentence and click its card in the right-hand panel to open
the source. In the source view, click **Back to answer**.

**You should see:** you return to Ask with the **battery sentence** scrolled into view — not
dropped at the bottom of the column beside the box. (Arriving on Ask must not trigger the
"scroll to newest" behaviour; only a newly asked question does.)

---

## Part H — narrow window

### 23. Narrow the window

Drag the window's side edge in until it is about 900 pixels wide, or narrower, so the
right-hand panel disappears (and, narrower still, the left column of links becomes a menu
button).

**You should see:** the source cards now appear inline under each answer instead of in a side
panel. The question box is still last in the column, still pinned to the bottom, still with
the cursor available in it, and its right edge still lines up with the answer text and the
**Ask** button. The box never gets wider than the answer text.

---

## Known gaps

These are known and are not defects of this ticket.

- **Source cards stack from the top of the right-hand panel** rather than sitting level with
  the sentence they support, so leaders to claims far down the column still slope. Where the
  cards sit is `M7-FIX-FE-171`'s scope. This ticket only removed the empty question box the
  leaders used to cross (step 14).
- **The band behind the box is the page's own colour, not the slightly darker grey drawn in
  `docs/ux/screens-reference.html`.** Deliberate: the question box itself is that darker grey,
  and would disappear into a band of the same colour. Recorded in `docs/decisions.md`
  (2026-09-23, `M7-FIX-FE-169`). Do not report the colour difference against the mockup.
- **The empty first-run page has no question box** (step 6). There is nothing to ask about until
  a source exists; that page is `FirstRun`'s and was not changed.
- **The model sometimes echoes template text** — lines such as "Not covered: <the specific
  thing…>", or a "Resolved by memory" note with no memory behind it. Filed as issue #663.
  Answer content is not what this ticket tests.
- **An answerable question can come back as "nothing in your files"** — for example a question
  about Mk3 firmware updates, which `spec.docx` does answer. Tracked on issue #625. If it
  happens in steps 10–11, rephrase or carry on; the layout checks still apply to an abstention.
- **No automated check of the layout itself.** The frontend tests run only over `web/lib/*.ts`;
  there is no component-rendering harness in the repo. Only the "scroll on a new question, not
  on a streamed word, not on first load" rule (`followsNewTurn`) has unit tests. This
  walkthrough is the check for position, right edge, focus and tab order.
- **Not tried with a screen reader.** Part F checks keyboard order only. The reading order is
  now conversation first, question box last, which matches the visual order; whether a screen
  reader user finds the box easily after a long conversation has not been assessed by one.
