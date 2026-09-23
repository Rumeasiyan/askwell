# Manual test — M7-FIX-FE-173, the rail becomes a drawer at narrow widths

**Ticket:** `M7-FIX-FE-173` — at 390×844 the left rail sat over the content with the
composer clipped to "…atabases" and nothing on screen that dismissed it. The rail was
already a drawer below the breakpoint; what the report showed was the drawer **open**,
covering the only control that closes it. The drawer now carries its own close control in
the same corner, holds keyboard focus while open, and closes itself when the window is
widened past the breakpoint.

**Version under test:** `0.7.26`
**Time:** about 40 minutes, with a native inference process running (Part E needs a real
answer). Parts A–D need no model at all.

**What is being checked.** `web/components/shell/rail-drawer.tsx` (the drawer, its two
controls, focus handling, the widen-close) and `web/lib/drawer.ts` (the two pure rules it
uses), inside `web/components/shell/shell.tsx`. The margin's inline reflow in
`web/components/ask/ask-screen.tsx` is only re-checked, not changed.

**Two breakpoints, on purpose.** The rail is a column when the window is **768px or wider**
and a drawer below that. The provenance margin (the right-hand column of source cards on
Ask) moves inline under the answer below **1024px**. So between 768 and 1023 you should see
the rail as a column *and* the source cards under the answer. That is correct, not a
defect — `docs/decisions.md`, 2026-09-23, `M7-FIX-FE-173`.

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

Have one short document ready to add — a one- or two-page PDF or text file on a narrow
topic you can ask about (a return policy, a set of opening hours). You need it in Part E.

**About setting a width.** Part G of the master sheet says to resize the window rather than
emulate a device. Do that wherever you can. But most desktop browsers will not let a window
get narrower than about 500px, so **390 cannot be reached by dragging**. For the 390 rows,
open the browser's developer tools (`F12`), turn on the device toolbar (Chrome:
`Ctrl+Shift+M`; Firefox: `Ctrl+Shift+M`), choose **Responsive**, and type `390` × `844`
into the size boxes. Askwell decides rail-or-drawer from the width of its own window area,
so this gives the same result as a real 390px window. For 1440, 1024 and 768, use the same
boxes if you cannot drag to an exact width.

---

## Cold start

### 1. Build the interface

```
scripts/dev.sh web-build
```

**You should see:** a Next.js build finishing with a route list and no red error text.

### 2. Bring the stack up

```
podman compose up -d --force-recreate api
podman compose up -d
```

**You should see:** `postgres`, `redis`, `egress-proxy`, `api`, `worker` reported as
started. Wait about thirty seconds. (Recreating `api` makes sure it serves the build you
just made, not an older one.)

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

Leave it running. **You should see:** the process report a loaded model and stay running.
If no model is configured here, carry on — only Part E needs it.

### 5. Open Askwell at full width

Open a browser, maximise the window on a normal laptop or desktop screen (1440px or wider),
and go to:

```
http://127.0.0.1:8000
```

**You should see:** the welcome screen, step 1 — "what this is". Along the top, a thin bar
reads **Askwell** with a small coloured dot and a word beside it (**Ready**, or a reason
Askwell is not ready), and a theme control on the right. Down the left, a column listing
**Ask, Library, Clarifications, Memory, Settings**. There is **no** three-line menu button
in the top-left corner at this width.

### 6. Leave first-run

Click **Skip setup**.

**You should see:** the Ask screen. With nothing added yet it says nothing is indexed and
offers a way to add the first source — not an empty chat box. The composer at the bottom
reads **Ask about your own files and databases**.

### 7. Check the first rail click (issue #665)

This is the first rail click in this tab, so it doubles as a check on a known issue.
Click **Library** in the left column, once.

**You should see:** the Library screen. **Write down whether the first click worked or
whether nothing happened and you had to click again**, and add that as a comment on issue
#665 with your browser and version. A second click being needed is #665, not this ticket.

---

## Part A — 1440, 1024 and 768 are unchanged

The ticket puts everything from 768 upwards out of scope. These steps confirm it stayed
that way.

### 8. At 1440, walk the rail

Click **Ask**, **Library**, **Clarifications**, **Memory**, **Settings**, in turn.

**You should see:** each screen open in the middle; the clicked item in the left column is
highlighted with a coloured bar on its left edge. On **Ask** only, a third column on the
right holds the source-card area. No menu button appears in the top-left at any point.

### 9. At 1024

Set the width to 1024 (drag, or the device toolbar). Walk the five destinations again.

**You should see:** the left column still there, no menu button. On **Ask**, the
right-hand column has gone — it is not missing, it has moved under the answer (Part E
checks that with a real answer). Nothing is cut off at the right edge and there is no
sideways scrollbar at the bottom of the window.

### 10. At 768

Set the width to exactly 768. Walk the five destinations again.

**You should see:** the left column **still a column**, and **still no menu button**.
768 is the last width that keeps the column. No sideways scrollbar.

---

## Part B — 390: the drawer by pointer

### 11. Narrow to 390

Click **Ask** in the left column first. Then set the width to 390 × 844 in the device
toolbar (see "About setting a width") and look at the top bar.

**You should see:**

- The left column has disappeared entirely. The content fills the width.
- In the top-left corner, before the word **Askwell**, a small bordered button showing
  three short horizontal lines. Hovering it with a screen reader, or inspecting it, names
  it **Open navigation**.
- Nothing is covering the content. No dark wash over the screen.

### 12. The composer is whole

Still at 390, on the Ask screen, look at the composer at the bottom.

**You should see:** the placeholder begins **Ask about your own files…** at its left edge —
nothing cut off at the start, as "…atabases" was. It may wrap onto a second line; that is
fine. The composer box starts and ends inside the screen
with a small gap each side. Its send control is visible. There is no sideways scrollbar
anywhere on the page; try scrolling sideways with a trackpad and nothing moves.

### 13. Open the drawer

Click the three-line button.

**You should see:**

- A panel appears over the left of the screen, the same width as the old column, with a
  shadow along its right edge.
- The rest of the screen is dimmed by a dark wash.
- In the panel's top-left corner, **in the same place the three-line button was**, a
  bordered button showing an **×** (two crossed lines). It is named **Close navigation**.
- Below it, the same five destinations in the same order as the column at full width:
  **Ask, Library, Clarifications, Memory, Settings**. If there are unanswered
  clarifications, the same count badge sits beside **Clarifications**.
- **Ask** is highlighted as where you are, and it has a visible focus outline.

### 14. Close with the ×

Click the **×** in the panel's corner.

**You should see:** the panel and the dark wash vanish together. The three-line button is
back in the corner. You are still on Ask; nothing else changed.

### 15. Close with the dark wash

Click the three-line button again, then click anywhere on the dimmed area to the right of
the panel.

**You should see:** the panel and wash vanish, exactly as in step 14. Clicking the wash did
**not** also click whatever was underneath it (for example, it did not put the cursor in
the composer or press a button).

### 16. Every destination through the drawer

Repeat this for each of **Library**, **Clarifications**, **Memory**, **Settings**, then
**Ask**:

1. Click the three-line button.
2. Click the destination in the panel.

**You should see, each time:** the drawer closes by itself, and the screen you chose is now
showing with nothing over it. Open the drawer once more: the item you just chose is the
highlighted one. Close it with the ×.

### 17. Nothing is clipped on any screen

On each of the five screens at 390, drawer closed, scroll the whole page top to bottom.

**You should see:** every heading, button and text line fits within the width. No sideways
scrollbar on any screen. On **Library**, the filter controls wrap onto more lines rather
than running off the right edge. On **Settings**, every section can be scrolled to and
every control in it is on screen.

---

## Part C — 390: the drawer by keyboard only

Using the mouse one last time, open the drawer and choose **Library**. Then put the mouse
aside for the rest of this part. (Library, not Ask: Ask puts the cursor in the composer as
it loads, which would start the keyboard walk from the bottom of the page.)

### 18. Reach the menu button

Reload the page (`F5`), then press **Tab** once. The three-line button is the first control
in the page, so the first **Tab** lands on it.

**You should see:** a visible focus outline around the three-line button.

### 19. Open with the keyboard

Press **Enter**.

**You should see:** the drawer and dark wash appear, and the focus outline is on the
destination for the screen you are on (**Library**), not on the × and not left behind on
the page.

### 20. Focus stays inside

Press **Tab** repeatedly — at least eight times.

**You should see:** the outline walks down through **Clarifications**, **Memory** and
**Settings**, then jumps to the **×** at the top, then **Ask**, **Library**, and on down
again. It **never** lands on the theme control, the page content, or anything else on the
dimmed screen behind.

Now press **Shift+Tab** repeatedly, at least eight times.

**You should see:** the same loop in reverse — from the × it wraps to **Settings** at the
bottom. It never escapes to the page behind.

### 21. Escape closes it

Press **Escape**.

**You should see:** the drawer and wash vanish, and the focus outline is back on the
three-line button — not lost at the top of the page.

### 22. Choose a destination by keyboard

Press **Enter** to open the drawer, **Tab** to **Memory**, press **Enter**.

**You should see:** the Memory screen, the drawer closed, and the focus outline on the
three-line button — not lost somewhere inside a panel that no longer exists.

### 23. Close by keyboard using the ×

Open the drawer with **Enter**, **Tab** until the × has the outline, press **Enter**.

**You should see:** the drawer closes and focus returns to the three-line button.

---

## Part D — widening while the drawer is open

### 24. From 390 to 1024 with the drawer open

At 390, open the drawer (leave it open). Now change the width in the device toolbar to
1024.

**You should see:** the drawer and its dark wash are **gone** — not floating over the
content. The left column is back in its normal place, the three-line button is gone, and
the screen is fully usable: click into the composer and type a letter.

### 25. Narrow again

Change the width back to 390.

**You should see:** the three-line button returns and the drawer is **closed**. It does not
spring back open on its own.

### 26. The same by dragging a real window

Turn the device toolbar off. Drag the browser window narrower until the left column
disappears and the three-line button appears in the top-left (somewhere below 768; your
browser may stop you around 500, which is fine). Open the drawer. Now drag the window wider
until the column comes back.

**You should see:** the moment the column reappears, the drawer and wash are gone. There is
no instant where the panel sits on top of the column, and no leftover dark wash. Drag
narrow again: the drawer stays closed.

---

## Part E — the source cards at the same widths (needs inference)

Skip this part if step 4 could not load a model, and mark it `N/V` in your notes.

### 27. Add your document

At full width, click **Library** in the left column, then **Add a source**. Add the
document you prepared. Wait until its row stops showing progress and reads as ready.

### 28. Ask a question it answers

Click **Ask**. Type a question your document answers (e.g. "What time does the store open
on Saturdays?"). Press **Enter** and wait for the answer to finish.

**You should see, at 1440:** the answer in the middle, with source cards in the right-hand
column naming your document and page, and lines joining claims to cards.

### 29. The same answer at 1024 and 768

Set the width to 1024, then 768.

**You should see, at both:** the right-hand column gone and the **same source cards shown
under the answer**, each naming your document and page. Nothing cut off at the right, no
sideways scrollbar, no card drawn over the answer text. At 768 the left rail is still a
column beside all of this.

### 30. The same answer at 390

Set the width to 390 × 844.

**You should see:** the answer text wrapping to the width, the source cards under it, the
composer whole at the bottom, no sideways scrollbar. Click a source card: the document
opens at the cited page.

### 31. The trace panel at 390

Go back (browser back, or open the drawer and choose **Ask**). Under the answer, click
**How did you get this?**

**You should see:** the trace panel open and readable at this width. Press **Escape**: it
closes. (Tab walking out of the trace panel is a known issue — see Known gaps.)

---

## Part F — record the master sheet

Fill `docs/manual-tests/master-sheet.md` Part G rows G1–G7 for all four widths from what you
saw above. G1 at 390 is steps 13–16; G2 is step 12; G3 is Part E; G4 is step 31; G5 and G6
are step 17; G7 is Parts B and C.

---

## Known gaps

- **390 needs device emulation.** Desktop browser windows do not shrink that far, so the
  390 rows are checked with the developer tools' responsive mode. The drawer itself (steps
  13–26) also works in any real window narrower than 768, and step 26 checks that by
  dragging.
- **The packaged desktop window is not tested here.** The widen-close follows Askwell's own
  window area rather than the browser viewport specifically so it holds in the Tauri
  window, but that shell needs a packaged build (master sheet, #559).
- **The first rail click in a fresh tab may be dropped** — issue #665. Found while building
  this ticket, reproduced on `main` before it, column and drawer alike, only seen so far in
  headless Chrome. Step 7 is the hand check that issue asks for; record the result there.
- **Tab walks out of the trace panel** into the Ask screen behind it — issue #666. The
  drawer's focus trap was not extended to it.
- **After a widen-close, keyboard focus is not put anywhere in particular.** The control it
  would return to has just disappeared, so focus falls back to the page. Deliberate and
  recorded in `docs/decisions.md`; only matters to a keyboard user who resizes the window
  with the drawer open.
- **No swipe gesture.** Askwell is a desktop application; the drawer opens from its button
  only. Not a defect.
- **No component-level test of the drawer.** The web test runner covers `lib/*.ts` only,
  so the Tab-wrap and "control has gone" rules are tested in `web/lib/drawer.test.ts`, and
  everything visual is covered by this walkthrough alone.
