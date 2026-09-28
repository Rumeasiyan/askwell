# Manual test — M9-FIX-FE-204, choosing the current document is remembered, and only the real positions are boxed

**Ticket:** `M9-FIX-FE-204`, issues #728 and #727. It fixes two separate defects.

1. **"Which one is current?" saved nothing (#728).** When two files disagree, Askwell shows both
   sides and asks which one is current. Clicking a file used to say *"Noted … as current. This is
   not saved yet — Askwell will remember it once memory ships."* Memory shipped long ago, and the
   choice was lost when the tab closed. Now the choice is saved as a memory fact. It appears on
   the **Memory** screen as something **you told** Askwell, and the next question on the same
   topic is answered from the chosen file. Choosing the other file later **replaces** the fact.
   It does not add a second one. The offer now shows each file once, in the same order as the
   boxes above it.
2. **An unrelated sentence could be boxed as one side of the disagreement (#727).** When the
   model writes the two sides *above* the "Conflicting sources on …" line, Askwell used to box
   every cited sentence above that line, including ones about something else. Now it boxes
   sentences above the line only when there are exactly two. If it cannot tell which sentences
   are the two sides, the answer is shown as ordinary text under the conflict heading.

**Version under test:** `0.7.52`. Run `cat VERSION` and update this line if the version has
moved on.

**Time:** about 40 minutes. Most of it is waiting for the model to answer on CPU.

**Who can run it:** anyone with a browser and a terminal. Every Askwell screen is reached by
clicking, starting from the address Askwell opens at. The terminal starts Askwell and runs checks
that cannot be done by looking. Those checks are labelled **Stand-in**.

**What is being checked.**

| Piece | File |
| ----- | ---- |
| The offer: one button per file, in date order, with saving, saved and failed states | `ResolveOffer` in `web/components/ask/ask-screen.tsx`; `conflictChoices` and `resolveConflict` in `web/lib/conflict-resolution.ts` |
| The save: builds the fact from the stored answer and the files it cited, and supersedes an earlier choice | `api/src/askwell/conflict_resolution.py`, `POST /ask/{message_id}/resolve-conflict` |
| Which sentences above the conflict line are boxed | `layoutConflict` in `web/lib/answer-annotations.ts` |

**The one rule of this test.** Never type an address into the browser bar except the first one in
step 1. Reach every screen by clicking.

> **Known defects you may see on the way. Do not report them against this ticket.**
>
> - **The first click on an item in the left column after a fresh load sometimes does nothing**
>   (#665). Click it again.
> - **"Resolved using what you told Askwell" can appear under an answer that used no memory at
>   all** (#776). That is why this test checks memory use in **How did you get this?**, not by
>   that line alone.
> - **An answer can show "Not covered: None." or "Resolved by memory: None."** (#781).
> - **An answer can flag a conflict or a gap about something you did not ask** (#775).

---

## Before you start

> **Warning: the cold start below deletes everything this Askwell stack holds.** That means
> sources, memory, conversations, the audit log and settings. Your original files are not
> touched. On the shared development machine, check that nobody needs what the stack holds now.
> If you are unsure, use **Settings → Your data → Export everything** first.

### A. A folder to add

Askwell can only read folders inside `ASKWELL_ROOTS_MOUNT` in `.env`. Check it:

```
cd ~/external/quantum-plus/askwell
grep ASKWELL_ROOTS_MOUNT .env
```

If it is empty, or does not cover `/tmp`, set `ASKWELL_ROOTS_MOUNT=/tmp`. Then copy the fixture
corpus into a folder Askwell can read:

```
rm -rf /tmp/askwell-test-204
mkdir -p /tmp/askwell-test-204/one/corpus
cp eval/fixtures/corpus/* /tmp/askwell-test-204/one/corpus/
ls /tmp/askwell-test-204/one/corpus
```

**You should see:** nine files, including `store_hours_2025.pdf` and `store_hours_2026.pdf`.

The two files this test is about:

| File | Page | Says |
| ---- | ---- | ---- |
| `store_hours_2026.pdf` | 1 | *"Meridian Loom retail stores close at **9 PM** on weekdays."* That is the whole file |
| `store_hours_2025.pdf` | 1 | *"Meridian Loom retail stores close at **8 PM** on weekdays."* That is the whole file |

Neither file has a date inside it. Askwell takes each one's year from its file name.

### B. Start Askwell from nothing

```
podman compose down -v
scripts/dev.sh web-build
scripts/dev.sh build-api
podman compose up -d
scripts/dev.sh db upgrade head
```

**You should see:** the volumes removed, both builds finish with no red error text, the
containers start, and the migration finish with no error. Do not skip either build. This fix is
in both the interface and the API, and without the builds you are testing the old version.

In a **second** terminal, start the model on the host and leave it running:

```
scripts/dev.sh inference
```

**You should see:** the supervisor report that the model and the embedding model are ready.

---

## Part A — first run and adding the files

1. Open a **private or fresh-profile** browser window at full width, so no earlier session
   carries over. Go to `http://127.0.0.1:8000`. ☐

   **You should see:** **Welcome to Askwell**, a **Skip setup** button top right, and a **Get
   started** button. Down the left, a column listing **Ask, Library, Clarifications, Memory,
   Settings**. If you see the Ask screen instead, the stack was not cleared. Go back to *Before
   you start*, B.

2. Click **Get started**. On the passphrase step, click **Not now**, then **Continue**. ☐

   **You should see:** step 3, about the model, with an add box showing **Choose files** and
   **Choose a folder**.

3. Wait until the model section says the model is ready, then click **Continue** without adding
   anything. ☐

   **You should see:** step 4, beginning *"Ready. Add something to ask about"*.

4. Click **Memory** in the left column. ☐

   **You should see:** a screen headed **Memory**, with *"What Askwell believes about your
   material, and where each belief came from."* under it, and the empty message *"Nothing here
   yet. Memory fills as Askwell asks about your material and you answer…"*. There are no fact
   rows. Remember this. Every row you see later was written during this test.

5. Click **Library** in the left column, then **Add a source** in the panel. ☐

   **You should see:** a screen headed **Add a source**, with a **Files** panel holding **Choose
   files** and **Choose a folder**.

6. Click **Choose a folder**. Open `/tmp/askwell-test-204/one`, select `corpus` and confirm. If
   the browser asks whether to upload the files, confirm. Nothing leaves this machine. When asked
   which folder `corpus` is in, type `/tmp/askwell-test-204/one` and click **Add them**. If a
   note offers **Nominate**, click it, then **Add them** again. ☐

   **You should see:** a note headed **Queued**, and no red **Not added** note.

7. Click **Library** in the left column. ☐

   **You should see:** one row, **corpus**. Wait until it reads **Ready** and the line under it
   reads **All 9 indexed.** On a CPU-only machine this can take several minutes.

---

## Part B — the conflict, and only its two sides boxed

8. Click **Ask** in the left column. Type exactly this and press **Enter**: ☐

   ```
   What are the store hours?
   ```

   **You should see**, once the answer finishes (allow a minute or two on CPU):

   - A small heading beginning **Conflicting sources on**, followed by a short topic, for example
     `Conflicting sources on store hours`. Write the topic down exactly. It is called
     **the topic** below.
   - **Two** separate outlined boxes under it. One says *"…close at 9 PM on weekdays."*, then
     `store_hours_2026.pdf · p. 1`, then `2026 · from the file name`. The other says *"…close at
     8 PM on weekdays."*, then `store_hours_2025.pdf · p. 1`, then `2025 · from the file name`.
     The 2026 box is on top.
   - Under the boxes: *"Which one is current for **the topic**? Askwell will remember your
     answer."* and **exactly two buttons**: `store_hours_2026.pdf · 2026` first, then
     `store_hours_2025.pdf · 2025`. The dates can take a second to load, and the buttons can
     swap once while they do.

   If there is no **Conflicting sources on** heading, the model did not flag a conflict this
   time. Ask the same question again.

9. Look closely at every box. ☐

   **You should see:** every box holds a sentence about the stores' **closing time**. **No box
   holds a sentence about anything else** — a notice period, a password rotation, a payment term.
   A box about something else is #727's defect, and a failure of this ticket. Write down the
   whole answer exactly as shown.

   If the answer has a third cited sentence and it is shown as ordinary text above or below the
   boxes, not in a box of its own, that is correct.

10. Look at the buttons again. ☐

    **You should see:** each file name **once**. The same file name on two buttons is #728's
    defect, and a failure of this ticket. The button order matches the box order.

---

## Part C — choose 2026, and see it in Memory

11. Click `store_hours_2026.pdf · 2026`. ☐

    **You should see:** for a moment, both buttons greyed out and the one you clicked reading
    `store_hours_2026.pdf · 2026 — saving…`. Then the buttons are replaced by:

    *"Saved to memory: store_hours_2026.pdf is current for **the topic**. Askwell will use this
    the next time you ask about it."*, followed by two links, **See it in Memory** and **Choose
    again**.

    The words *"This is not saved yet"* or *"once memory ships"* must **not** appear anywhere.

12. Click **See it in Memory**. ☐

    **You should see:** the **Memory** screen, with **one** row. The row's small heading is
    **the topic**. Its text reads:

    *"store_hours_2026.pdf is the current document for **the topic**, not store_hours_2025.pdf."*

    Under it: **You told me** · today's date · **used in 0 answers**. The row has **Edit** and
    **Delete** buttons, and no **Confirm** button. No source name is shown at the top right of
    the row.

    The link opens the screen, not the row itself. That is expected; see *Known gaps*.

---

## Part D — the next answer uses it

13. Click **Ask** in the left column. ☐

    **You should see:** the same conversation you left, with the store-hours answer still there.

14. Type exactly the same question again and press **Enter**: ☐

    ```
    What are the store hours?
    ```

    **You should see:** an answer saying the stores close at **9 PM** on weekdays, citing
    `store_hours_2026.pdf`, **p. 1**. There are **no** two boxes for 9 PM against 8 PM, and no
    **Which one is current?** offer. The answer may add a line such as *"Resolved using what you
    told Askwell: …"*, and it may show a small chip holding the fact.

    If the answer still shows the conflict boxes, go on to step 15 before deciding. The
    model may have ignored a fact it was given.

15. Under this new answer, click **How did you get this?** ☐

    **You should see:** a panel whose steps include **Checked your memory — 1 fact, 0 schema
    notes**. Under that step, a chip reading *"**the topic** = store_hours_2026.pdf is the
    current document for …"*. Click **Close**.

    This is the ticket's proof that the next answer **used** the fact. It is a failure if the
    step says **0 facts**, or is missing. If it says **1 fact** but step 14 still showed the
    conflict boxes, the save and the lookup worked and the model ignored the fact. Record the
    answer, ask once more, and report it separately, not against this ticket.

---

## Part E — choose the other one: replaced, not added

16. Scroll up to the **first** store-hours answer, from step 8. If it is collapsed, click it to
    expand it. ☐

    **You should see:** its two boxes, and under them the saved line from step 11 with **See it
    in Memory** and **Choose again**. If instead it shows *"Which one is current…"* with both
    buttons, the page was reloaded at some point. That is #782, not a failure. Carry on from
    step 18.

17. Click **Choose again**. ☐

    **You should see:** the two buttons back, in the same order as before.

18. Click `store_hours_2025.pdf · 2025`. ☐

    **You should see:** `— saving…` after that button's name for a moment, then *"Saved to memory: store_hours_2025.pdf
    is current for **the topic**…"*.

19. Click **See it in Memory**. ☐

    **You should see:** still **one** row, not two. Its text now reads:

    *"store_hours_2025.pdf is the current document for **the topic**, not store_hours_2026.pdf."*

    Under it, **You told me** · today's date, and below that, set off by a thin line on the left,
    the earlier 2026 sentence **struck through**, with its date. The earlier choice is kept as
    history. It is not a second active fact.

20. Click **Ask** in the left column. Type the same question again and press **Enter**: ☐

    ```
    What are the store hours?
    ```

    **You should see:** an answer saying **8 PM**, citing `store_hours_2025.pdf`, **p. 1**.
    Open **How did you get this?** under it. **Checked your memory** shows **1 fact**, and its
    chip names `store_hours_2025.pdf` as current. **9 PM** must not be given as the answer.

---

## Part F — the same choice twice writes nothing

21. Scroll up to the first store-hours answer again. Click **Choose again**, then click
    `store_hours_2025.pdf · 2025` — the one already chosen. ☐

    **You should see:** *"Saved to memory: store_hours_2025.pdf is current for **the topic**…"*,
    exactly as before. The interface says the same thing whether or not anything was written.

22. Click **See it in Memory**. ☐

    **You should see:** exactly as in step 19. **One** row, the 2025 sentence, and **one**
    struck-through 2026 line. No second 2025 line, struck through or not.

23. **Stand-in** — confirm what the database holds: ☐

    ```
    scripts/dev.sh psql -c "SELECT origin, source_id IS NULL AS no_source, superseded_by IS NULL AS active, left(fact, 70) AS fact FROM memory ORDER BY created_at;"
    ```

    **You should see:** exactly **two** rows, both `clarification`, both `no_source = t`. The
    2026 one is `active = f`; the 2025 one is `active = t`. A third row means step 21 wrote a
    duplicate, which is a failure.

---

## Part G — when saving fails

24. Scroll up to the first store-hours answer. Click **Choose again**, so the two buttons show.
    Do not click either yet. ☐

25. **Stand-in** — stop the API, so the save cannot reach it: ☐

    ```
    podman compose stop api
    ```

26. Without reloading the page, click `store_hours_2026.pdf · 2026`. ☐

    **You should see:** the buttons stay on screen. Under them, a line beginning
    *"store_hours_2026.pdf was not saved as current."*, then the browser's own reason (Firefox and
    Chrome word it differently, for example *"Failed to fetch"*), then *"Choose again to retry."*
    It must **not** say *"Saved to memory"*.

27. **Stand-in** — start the API again, and wait for it to answer: ☐

    ```
    podman compose start api
    curl -s -o /dev/null -w '%{http_code}\n' localhost:8000/health
    ```

    **You should see:** `200`. Repeat the `curl` line every few seconds until it does.

28. Click `store_hours_2026.pdf · 2026` again. ☐

    **You should see:** *"Saved to memory: store_hours_2026.pdf is current for **the topic**…"*.
    Click **See it in Memory**. One row, now naming `store_hours_2026.pdf`, with **two**
    struck-through lines under it: the 2025 choice and the first 2026 choice.

---

## Part H — the automated checks

The #727 layout depends on how the model happens to write its answer, so it cannot be produced
on demand by clicking. The four cases are covered by unit tests on the exact answer text.

29. **Stand-in** — run the suites: ☐

    ```
    scripts/dev.sh check
    scripts/dev.sh web-check
    scripts/dev.sh test-db
    ```

    **You should see:** all three finish with no failures. The tests for this ticket:

    - `web/lib/answer-annotations.test.ts`, four new tests: *an unrelated cited paragraph above
      the positions is never boxed* (#727's own reproduction, "Payment is due in 45 days" above
      two notice periods); *three cited sentences above a last conflict line stay prose*; *text
      under a last-looking conflict line keeps the lines above as prose*; and *two listed
      positions above the line are boxed even with text after it*, which keeps the fix for #643.
    - `web/lib/conflict-resolution.test.ts`: a document cited for two positions is offered once,
      and the buttons follow the boxes' date order.
    - `api/tests/test_conflict_resolution.py`: the choice writes a user fact for the topic; the
      next question finds it; choosing the other supersedes; the same choice twice writes
      nothing; the write is logged; a conflict line naming no topic uses the question instead;
      and a document the answer did not cite, an answer with no conflict, and an unknown answer
      are each refused.
    - `api/tests/test_conflict_resolution_api.py`: the route needs a session and a document id.
    - No existing test was weakened, skipped or deleted. No abstention test or retrieval
      threshold changed (C5).

---

## Teardown

```
podman compose exec api askwell-verify
podman compose down -v
rm -rf /tmp/askwell-test-204
```

**You should see:** both audit chains reported intact before the wipe. Stop the inference process
in the second terminal with `Ctrl+C`.

---

## What counts as a failure

- Any box under **Conflicting sources on** holding a sentence that is not about the thing in
  conflict.
- The same file name on two buttons, or buttons in a different order from the boxes.
- *"This is not saved yet"* or *"once memory ships"* anywhere.
- *"Saved to memory"* shown when the save failed, or nothing shown at all when it failed.
- No row on **Memory** after a choice, a row marked **I guessed**, or a row naming a file the
  answer did not cite.
- Two active rows for the topic after choosing, then choosing the other.
- A new row, or a new struck-through line, after choosing the same file twice.
- **Checked your memory — 0 facts** on the answer after a choice.

## Known gaps — not defects in this ticket

- **After a reload, the old answer asks "Which one is current?" again**, with both buttons, even
  though the choice is saved (#782). Choosing again is harmless: the same file writes nothing,
  and the other file replaces the fact.
- **See it in Memory opens the Memory screen, not the row.** The Memory screen has no link to a
  single fact. Recorded in `docs/decisions.md`, 2026-09-28.
- **Saving the same file twice says "Saved to memory" both times.** Nothing is written the
  second time; the interface does not say so.
- **The model can ignore the fact.** The fact reaches the next answer's instructions, which step
  15 shows. Whether a small local model then answers from it is model behaviour, not this
  ticket.
- **Some real conflicts are now shown as prose, not boxes.** A three-way conflict whose line
  comes last, and two unbulleted sides followed by more text, read as ordinary text under the
  **Conflicting sources on** heading. Less easy to read, never wrong. Recorded in
  `docs/decisions.md`, 2026-09-28, and in `docs/states-and-edge-cases.md`, Ask.
- **One rare layout can still box the wrong sentence**: exactly two cited sentences above the
  conflict line, one unrelated, with the real second side written above them without a citation
  and nothing after the line. Fixing it needs the prompt change in #774, which also carries the
  eval run. Do not try to produce it by hand.
- **"Resolved using what you told Askwell" is not proof by itself** that memory was used (#776).
  Use **How did you get this?**
- **"used in N answers" on the Memory row may stay at 0** after an answer that used the fact. It
  counts answers whose text cited the fact by number, not answers that merely read it.
- **The first click on a left-column item sometimes does nothing** (#665).
