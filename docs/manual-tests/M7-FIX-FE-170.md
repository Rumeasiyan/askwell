# Manual test — M7-FIX-FE-170, conflicting sources as separate records

**Ticket:** `M7-FIX-FE-170`. When two of your files disagree, Askwell has always detected the
disagreement. It then showed both sides as one unbroken paragraph with no dates, for example
`…close at 9 PM on weekdays.Meridian Loom retail stores close at 8 PM on weekdays.` Now each side
is its own box. A box holds the claim, the file it came from, and **that file's own date**, for
example `2026 · from the file name`. It never shows the date Askwell added the file. A file with
no date of its own says **Date unknown**. Every box looks the same, so none of them reads as the
answer.

**Version under test:** `0.7.38`. Run `cat VERSION` and update this line if the version has moved on.

**Time:** about 35 minutes, most of it waiting for indexing and answers.

**Who can run it:** anyone with a browser and a file manager. Two setup steps at the start need a
terminal. After that, every step is a click in Askwell, starting from its front page.

**What is being checked.**

| Piece | File |
| ----- | ---- |
| Finding the positions in the answer text, above or below the "Conflicting sources on …" line | `layoutConflict` in `web/lib/answer-annotations.ts` |
| The boxes: claim, file and page, own date, all styled alike, in date order | `ConflictPositions` in `web/components/ask/ask-screen.tsx` |
| The date wording: year, month or day as known, where it came from, or "Date unknown" | `documentDateLabel` in `web/lib/document-dates.ts` |
| The source cards beside a conflict show the same date, no longer "Added …" | `SourceCard` in `web/components/ask/provenance-margin.tsx` |
| The document's own date, recorded by the previous ticket | `M7-FIX-BE-170a`, `GET /documents/{id}` |

> **Four known defects affect this walkthrough. Do not report them against this ticket.**
>
> - **Ordinary answer text runs sentences together** with no space between them (#726). You may
>   see this in any prose around the boxes. It is not the boxes.
> - **The model sometimes repeats placeholder text** from its instructions, such as
>   `Not covered: <the specific thing…>` (#663). It can appear above or below the boxes.
> - **When the conflict line comes last, an unrelated cited paragraph above the positions can be
>   put in a box too** (#727). The fixture questions below do not trigger this, but a question of
>   your own might.
> - **Once any source exists, no plain link opens Add a source** (#712). This test reaches it
>   through the offer under a "not covered" answer, as `M7-FIX-BE-170a.md` does.

---

## Before you start

1. Build both halves and start the stack:

   ```
   cd ~/external/quantum-plus/askwell
   scripts/dev.sh build-api
   scripts/dev.sh web-build
   podman compose up -d --force-recreate
   scripts/dev.sh db upgrade head
   ```

   **You should see:** both builds finish with no red error text. Compose reports the containers
   as started. The migration finishes without an error. Native inference must also be running on
   the host (`scripts/dev.sh inference`), because every part below needs a real generated answer.

2. Open `.env` and find `ASKWELL_ROOTS_MOUNT`. That is the folder Askwell is allowed to read.
   Call it **the roots folder** below. Use your file manager to create these folders and files
   inside it:

   | Folder | File | Contents |
   | ------ | ---- | -------- |
   | `corpus` | every file in the repository's `eval/fixtures/corpus/` | copied, not renamed |
   | `hours-undated` | `store_hours_draft.txt` | a new text file containing `Meridian Loom retail stores close at 10 PM on weekdays.` |
   | `hours-same` | `store_hours_memo_2026.txt` | a new text file containing the two lines below |

   The two lines for `store_hours_memo_2026.txt`:

   ```
   The opening section says Meridian Loom retail stores close at 7 PM on weekdays.
   The appendix says Meridian Loom retail stores close at 11 PM on weekdays.
   ```

   `store_hours_draft.txt` has no date in its name. A text file has no date properties either, so
   Askwell has no date for it. That is the point of that file.

3. **Start with no other copy of these files.** If you have run Askwell before, open
   `http://127.0.0.1:8000`, click **Library** in the left rail and read the list. Delete any
   source that already contains `store_hours_2025.pdf` or `store_hours_2026.pdf`: click
   **Delete**, then **Delete it**. The confirmation says your original files are not touched.
   Extra copies add extra boxes and cards, and the counts below would not match. A test install
   is better.

---

## Part A — two versions, two boxes

This is the ticket's own scenario. The 2026 file says stores close at 9 PM. The 2025 file says
8 PM.

1. Open a **private or fresh-profile** browser window at `http://127.0.0.1:8000`. ☐

   **You should see:** either **Welcome to Askwell** or the **Ask** screen, with **Ask**,
   **Library**, **Clarifications**, **Memory** and **Settings** in the left rail. If you see the
   welcome page, click **Skip setup** at its top right.

2. Reach **Add a source**. If the library is empty, the **Ask** screen shows **Nothing added
   yet** and an **Add a source** button. Click it. If the library is not empty, type
   `What was the population of Lisbon in 1900?` into the box at the bottom and press Enter. Wait
   for the **Not covered by your files** region, then click **Add a source** under it. ☐

   **You should see:** a page headed **Add a source**, with a **Files** box containing
   **Choose files** and **Choose a folder**.

3. Click **Choose a folder** and choose the `corpus` folder. If the page asks **Which folder are
   these files in?**, type the full path to `corpus`. ☐

   **You should see:** a card listing the nine files, each moving to queued.

4. Click **Library** in the rail. Wait until the `corpus` source reads as indexed. ☐

   **You should see:** the source's row with nine documents and no **Needs attention** mark.

5. Click **Ask** in the rail. Type `What are the store hours?` and press Enter. ☐

   **You should see**, once the answer finishes:

   - A small heading beginning **Conflicting sources on**, followed by a short topic, for example
     `Conflicting sources on store hours`. It is in normal text colour, not red.
   - **Two separate boxes** under the heading, one above the other, each with a thin outline.
     There is visible space between them. They are **not** one paragraph.
   - In one box: `Meridian Loom retail stores close at 9 PM on weekdays.`, then
     `store_hours_2026.pdf · p. 1`, then `2026 · from the file name`.
   - In the other box: `Meridian Loom retail stores close at 8 PM on weekdays.`, then
     `store_hours_2025.pdf · p. 1`, then `2025 · from the file name`.
   - Under the boxes: **Which one is current?** and one button for each file.

   If there is no **Conflicting sources on** heading and the answer names only one time, the model
   did not flag a conflict this time, and this ticket has nothing to render. Ask the same question
   again. If the heading appears but the two times are still in one paragraph with no boxes, that
   is a failure.

6. Look at the order of the two boxes and at the dates. The date lines can take up to a second to
   appear, and the boxes can swap once while they load. ☐

   **You should see:** the **2026** box above the **2025** box. The newer document comes first.
   The dates say **2026** and **2025**, not `1 January 2026` and not today's date. Only the
   year is in the file name, so only the year is shown.

7. Compare the two boxes closely. ☐

   **You should see:** the same outline, the same text size, the same colours and the same layout
   in both. Neither box is bold, highlighted, larger, marked "current" or "recommended", or
   written as the answer with the other as a footnote.

8. Hold the mouse over the claim text in the top box. Then press Tab until the keyboard focus
   reaches that claim. ☐

   **You should see:** both times, the matching source card in the margin to the right is
   highlighted, and a line joins it to the claim. The top box's claim pairs with the
   `store_hours_2026.pdf` card and the bottom box's claim pairs with the `store_hours_2025.pdf`
   card.

9. Read the source cards in the margin. ☐

   **You should see:** two cards, 2026 first. Under each file name there is a date line that
   matches its box, `2026 · from the file name` or `2025 · from the file name`. **No card says
   "Added".** The date the file was added is still on the document's own page. The ticket moved it
   off the cards on purpose.

10. Make the browser window narrower until the source cards move from the margin to below the
    answer. ☐

    **You should see:** the boxes are still two separate boxes, still 2026 first, with the same
    dates. The cards below the answer are in the same order as the boxes, with the same dates and
    no "Added". Widen the window again.

11. Click the `store_hours_2026.pdf` card in the margin. The file line inside a box is a label, not
    a link. The card is where you open the document. ☐

    **You should see:** the document opens at page 1, showing the 9 PM sentence. Use the browser's
    Back button to return. The answer and its two boxes are still there.

12. Under **Which one is current?**, click `store_hours_2026.pdf`. ☐

    **You should see:** the buttons are replaced by `Noted store_hours_2026.pdf as current for
    <topic>. This is not saved yet — Askwell will remember it once memory ships.` This control has
    not changed in this ticket. The wording is wrong now that memory has shipped. That is #728,
    not a defect in this ticket.

---

## Part B — three sources, one with no date

This adds a third version with no date anywhere. It checks two edge cases at once. Three
disagreeing sources are all shown in parallel, and a file with no date says so. It does not show
the date it was added.

1. Click **Ask** in the rail. Ask the Lisbon question from Part A step 2, and click **Add a
   source** under the answer. Click **Choose a folder** and choose `hours-undated`. Click
   **Library** and wait until it reads as indexed. ☐

   **You should see:** a `hours-undated` source with one document and no **Needs attention** mark.

2. Click **Ask** in the rail. Type `What are the store hours?` and press Enter. ☐

   **You should see:** the **Conflicting sources on** heading and **three** boxes, all styled the
   same, in this order:

   | Box | Claim | File | Date line |
   | --- | ----- | ---- | --------- |
   | 1 | …close at 9 PM on weekdays. | `store_hours_2026.pdf · p. 1` | `2026 · from the file name` |
   | 2 | …close at 8 PM on weekdays. | `store_hours_2025.pdf · p. 1` | `2025 · from the file name` |
   | 3 | …close at 10 PM on weekdays. | `store_hours_draft.txt` | `Date unknown` |

   Dated files come first, newest first. A file with no date goes after them. The model may leave
   one source out of its answer. If so, there are two boxes. Ask again. If a source is left out
   every time, record which one, but it is not a failure of this ticket. Detection belongs to
   `M2-PARTIAL-BE-059`.

3. Look closely at the `store_hours_draft.txt` box. ☐

   **You should see:** exactly **Date unknown**, with nothing after it. **It must not show
   today's date, "Added …", or any other date.** Askwell added this file a few minutes ago. If
   that date appears anywhere on this box or its margin card, it is the failure this ticket
   exists to prevent.

4. Read the margin cards. ☐

   **You should see:** three cards in the same order as the boxes. The `store_hours_draft.txt`
   card says **Date unknown**. No card says "Added".

5. Look under the boxes. ☐

   **You should see:** **Which one is current?** with three buttons, one for each file.

---

## Part C — one document that contradicts itself

A document that disagrees with itself is a conflict too. Each of its positions gets its own box,
and each box names the same file.

1. Click **Library** in the rail. On the `hours-undated` row, click **Delete**, then
   **Delete it**. ☐

   **You should see:** the `hours-undated` source is gone. `corpus` is still there.

2. Add `hours-same` the way you added `hours-undated` in Part B step 1. Wait until it is
   indexed. ☐

3. Click **Ask** in the rail. Type `What are the store hours?` and press Enter. ☐

   **You should see:** the **Conflicting sources on** heading and several boxes. Two of them name
   `store_hours_memo_2026.txt`, one saying 7 PM and one saying 11 PM. Each shows the date line
   `2026 · from the file name`. The two memo boxes are separate and styled like every other box.
   They are **not** merged into one box.

   Whether the model treats the memo's two lines as two positions depends on the model. If it
   cites only one of them, the memo has one box. Ask once more. If it still has one box, record
   it and move on. This layout is also covered by the unit test `two conflicting claims become
   two positions, not one run of prose` in `web/lib/answer-annotations.test.ts`.

4. Look under the boxes. ☐

   **You should see:** **Which one is current?** The same file name may appear on two buttons.
   That is #728, not a defect in this ticket.

---

## Part D — an answer with no conflict is unchanged

1. Type `What is the standard resignation notice period at Meridian Loom?` and press Enter. ☐

   **You should see:** an ordinary answer saying **sixty-three days**, cited to `handbook_a.pdf`.
   There is no **Conflicting sources on** heading, no boxes and no **Which one is current?**
   control. The margin card has **no date line at all**. Dates appear only on a conflict's cards.

2. Reload the page, then scroll up to the store-hours answer from Part C. ☐

   **You should see:** it still shows its heading and separate boxes. It may be collapsed as an
   earlier turn. If so, click it to expand it. The boxes come from the answer's own text, so a
   stored answer lays out the same way as a new one.

---

## What counts as a failure

- A conflict answer with a **Conflicting sources on** heading whose positions still run together
  as one paragraph.
- Any box, card or date line showing the date a file was **added**, including on a file with no
  date of its own.
- A year-only date shown as a full day, for example `1 January 2026`.
- Boxes that differ in style, or one box marked or worded as the preferred answer.
- Boxes in any order other than newest dated first, then undated, once the dates have loaded.
- Boxes and margin cards in different orders, or with different dates.
- Hovering or focusing a claim in a box does not highlight its card.
- A non-conflict answer showing boxes, dates on its cards, or the resolve control.
- A document's two contradicting positions, both cited, merged into one box.

## Known gaps — not defects in this ticket

- **"Which one is current?" saves nothing.** The ticket assumed it writes a memory fact. It does
  not. It keeps the choice for the open tab only, and its wording says memory has not shipped.
  The same file name can appear on two buttons, and the buttons are not in date order (#728).
- **Where a date came from is shown, not whether it is true.** A PDF re-saved in 2026 from a 2019
  original says 2026 `from the file's properties`. This is why the source is shown
  (`M7-FIX-BE-170a`).
- **Documents indexed before `0.7.37` show "Date unknown"** until their source is re-indexed.
  Re-indexing a cited document currently stops at **Needs attention** (#719), although the date is
  still written.
- **Positions the model writes neither directly after nor directly before the conflict line**
  are shown as ordinary prose, as before this ticket. This is recorded in `docs/decisions.md`.
- **A memory fact against a document** (the prompt's memory-versus-document case) has only one
  cited side, so it stays as prose rather than one box beside prose, which would make the
  document look preferred. This is deliberate.
- **Space between sentences is lost in ordinary answer prose** (#726). The boxes avoid this, but
  prose around them does not.
- **Placeholder text the model echoes** (#663) can still appear near the boxes.
- **An unrelated cited paragraph can be boxed** when the model writes the conflict line last
  (#727).
- **Reaching Add a source after the first source needs the abstention offer** (#712).
