# Manual test — M9-FIX-BE-202, answers read as prose, not run-ons and prompt fragments

**Ticket:** `M9-FIX-BE-202`, issues #726 and #663. It fixes two separate defects.

1. **Run-ons (#726).** In an answer with more than one cited sentence, the space between the
   sentences was lost on screen. The saved text was fine, but the screen showed
   *"…every forty-five days.The incident response team…"*. A blank line between two cited
   paragraphs disappeared the same way. Now each sentence is followed by a space, as written,
   and a paragraph break stays a paragraph break.
2. **Prompt fragments (#663).** The local model sometimes copies a line from its own
   instructions instead of filling it in, for example
   `Not covered: <the specific thing that was asked and not found>.` or
   `Resolved by memory: <the fact that was in conflict>.` Those lines used to show up as part
   of the answer. The worst case was *"Resolved using what you told Askwell: <the fact…>"*
   when the user had told Askwell nothing. Now any `<the …>`-shaped placeholder is removed
   before the answer is shown or saved. A "Not covered" or "Resolved by memory" line left
   naming nothing is not shown at all. A citation is never removed along with it.

**Version under test:** `0.7.50`. Run `cat VERSION` and update this line if the version has
moved on.

**Time:** about 40 minutes. Most of it is waiting for the model to answer on CPU.

**Who can run it:** anyone with a browser and a terminal. Every Askwell screen is reached by
clicking, starting from the address Askwell opens at. The terminal only starts Askwell and
runs checks that cannot be done by looking. Those steps are labelled **Stand-in**.

**What is being checked.**

- `web/lib/claims.ts`, `proseParts`, and `AnswerProse` in `web/components/ask/ask-screen.tsx`.
  These put back the space or blank line in front of each cited sentence and keep paragraph
  breaks on screen.
- `api/src/askwell/agent/placeholders.py`, new. It removes copied placeholders while the
  answer streams, before it is stored. `api/src/askwell/ask.py` wires it in.
- `api/src/askwell/agent/partial.py` and `api/src/askwell/agent/conflict.py`: a label line
  left empty is not treated as a gap or as a resolution.
- `web/lib/answer-annotations.ts`: the same rules applied in the browser. The conflict heading
  reads **Conflicting sources** with no topic when the topic was a placeholder.

**The one thing you cannot make happen on purpose.** Whether the model copies a placeholder
is up to the model. On the runs made when this ticket was built, it did not. So this walk
checks that **no** `<…>` placeholder is ever on screen, and that nothing else is lost. It
does not show one being removed. Part E, a **Stand-in**, shows the removal directly.

**The one rule of this test.** Never type an address into the browser bar except the first
one in step 1. Reach every screen by clicking.

---

## Before you start

> **Warning: the cold start below deletes everything this Askwell stack holds.** That means
> sources, memory, conversations, the audit log and settings. Your original files are not
> touched. On the shared development machine, check that nobody needs what the stack holds
> now. If you are unsure, use **Settings → Your data → Export everything** first.

### A. Two folders to add

Askwell can only read folders inside `ASKWELL_ROOTS_MOUNT` in `.env`. Check it:

```
cd ~/external/quantum-plus/askwell
grep ASKWELL_ROOTS_MOUNT .env
```

If it is empty, or does not cover `/tmp`, set `ASKWELL_ROOTS_MOUNT=/tmp`. Then make two
folders from the fixture corpus:

```
rm -rf /tmp/askwell-test-202
mkdir -p /tmp/askwell-test-202/one/security /tmp/askwell-test-202/two/store-hours
cp eval/fixtures/corpus/handbook_b.pdf /tmp/askwell-test-202/one/security/
cp eval/fixtures/corpus/store_hours_2025.pdf eval/fixtures/corpus/store_hours_2026.pdf \
   /tmp/askwell-test-202/two/store-hours/
find /tmp/askwell-test-202 -type f
```

**You should see:** three lines, ending `security/handbook_b.pdf`,
`store-hours/store_hours_2025.pdf` and `store-hours/store_hours_2026.pdf`.

What is in them, so you can check the answers:

| File | Page | Says |
| ---- | ---- | ---- |
| `handbook_b.pdf` | 3 | The incident response team must be notified within **three hours** of a suspected breach |
| `handbook_b.pdf` | 4 | Production database credentials are rotated every **forty-five days** |
| `handbook_b.pdf` | 6 | Passwords must be at least **eighteen characters**, no reuse of the last ten |
| `store_hours_2025.pdf` | 1 | Retail stores close at **8 PM** on weekdays |
| `store_hours_2026.pdf` | 1 | Retail stores close at **9 PM** on weekdays |

Nothing in any of them mentions parking. Part C relies on that.

### B. Start Askwell from nothing

```
podman compose down -v
scripts/dev.sh web-build
scripts/dev.sh build-api
podman compose up -d
scripts/dev.sh db upgrade head
```

**You should see:** the volumes removed, both builds finish with no red error text, the
containers start, and the migration finish with no error. Do not skip either build. Part of
this fix is in the interface and part is in the API. Without both builds you are testing the
old version.

In a **second** terminal, start the model on the host and leave it running:

```
scripts/dev.sh inference
```

**You should see:** the supervisor report that the model and the embedding model are ready.

---

## Part A — first run and adding the material

1. Open a **private or fresh-profile** browser window at full width, so no earlier session
   carries over. Go to `http://127.0.0.1:8000`. ☐

   **You should see:** **Welcome to Askwell**, a **Skip setup** button top right, and a
   **Get started** button. Down the left, a column listing **Ask, Library, Clarifications,
   Memory, Settings**. If you see the Ask screen instead, the stack was not cleared. Go back
   to *Before you start*, B.

2. Click **Get started**. On the passphrase step, click **Not now**, then **Continue**. ☐

   **You should see:** step 3, about the model, with an add box showing **Choose files** and
   **Choose a folder**.

3. Wait until the model section says the model is ready, then click **Continue** without
   adding anything. ☐

   **You should see:** step 4, beginning *"Ready. Add something to ask about"*, which tells
   you to open **Library** in the rail and choose **Add a source**.

4. Click **Library** in the left column, then **Add a source** in the panel. ☐

   **You should see:** a screen headed **Add a source**, with a **Files** panel holding
   **Choose files** and **Choose a folder**.

5. Click **Choose a folder**. Open `/tmp/askwell-test-202/one`, select `security` and confirm.
   If the browser asks whether to upload the files, confirm. Nothing leaves this machine.
   When asked *"Which folder is “security” in?"*, type `/tmp/askwell-test-202/one` and click
   **Add them**. If a note offers **Nominate**, click it, then **Add them** again. ☐

   **You should see:** a note headed **Queued**, and no red **Not added** note.

6. Click **Library** in the left column. At top right, click **Add a source**. Repeat step 5
   with `/tmp/askwell-test-202/two`, selecting `store-hours`. ☐

   **You should see:** another **Queued** note.

7. Click **Library** in the left column. ☐

   **You should see:** two rows, **one** and **two**. Wait until both read **Ready**. On a
   CPU-only machine this can take a few minutes.

---

## Part B — three cited sentences, spaced normally

This is the ticket's first acceptance criterion and the case #726 was closed on.

8. Click **Ask** in the left column. Type exactly this and press **Enter**: ☐

   ```
   How often are Meridian Loom production database credentials rotated, how quickly must the incident response team be notified, and how long must a password be?
   ```

   **You should see:** progress lines while it searches and reads, then an answer arriving
   a few words at a time. On CPU, allow a minute or two.

9. When the answer has finished, read it slowly as if you had never seen Askwell. ☐

   **You should see:** three sentences, close to:

   *"Meridian Loom rotates production database credentials every forty-five days. The
   incident response team must be notified within three hours of a suspected breach.
   Meridian Loom's password policy requires a minimum length of eighteen characters…"*

   The wording will vary. What must hold:

   - **Every full stop is followed by a space** before the next sentence. Look at each join.
     `days.The` or `breach.Meridian` with no space is the defect this ticket fixes. If you
     see one, write down the exact text. That is a failure.
   - No `[1]`, `[2]` or `[3]` markers appear in the text. They become source links.
   - No `<` or `>` characters appear anywhere in the answer.
   - Source cards in the right-hand margin name **handbook_b.pdf** with **p. 4**, **p. 3** and
     **p. 6**, one card for each fact the answer gives.

   If the model wrote the facts as a list or as one long sentence, there is nothing to check
   for spacing. Ask the same question again with **Enter** until you get three separate
   sentences, or note that you could not.

10. Hover over each sentence in turn, then click the first one. ☐

    **You should see:** each sentence highlights on its own, never two at once, and never
    only part of a sentence. Clicking a sentence highlights the source card it came from.
    This confirms the fix did not shift which sentence goes with which citation. That
    matters for C4: a citation attached to the wrong sentence is as bad as none.

11. Select the whole answer with the mouse, copy it, and paste it into any text editor. ☐

    **You should see:** the same sentences, still separated by spaces. The spacing is in the
    text itself, not only in how it looks on screen.

---

## Part C — a partial answer

This is the ticket's cold-start scenario, *"three cited claims and a partial answer"*. A
partial answer is where the model is told to write `Not covered: …`, so it is where #663's
placeholder showed up.

12. In the same conversation, type exactly this and press **Enter**: ☐

    ```
    How often are Meridian Loom production database credentials rotated, and how many parking spaces does the Cedarbrook office have?
    ```

    **You should see:** an answer that states the credentials are rotated every forty-five
    days, with a source card for **handbook_b.pdf**, **p. 4**. Below it, a separate block with
    a thin rule down its left edge, headed **Not covered by your files**, with one line in
    lighter text about the **number of parking spaces**.

13. Read that block closely. ☐

    **You should see:**

    - The line names parking spaces in ordinary words.
    - It does **not** read *"<the specific thing that was asked and not found>"*, or anything
      else inside `< >`.
    - The words **Not covered:** do not appear inside the answer text above the block. That
      label becomes the block's heading.
    - The block is not empty. A heading with nothing under it is a failure.

    If the model answered without a **Not covered by your files** block, it treated the
    question as fully answered or refused it outright. That is model behaviour, not this
    ticket's. Note it and ask again once. See *Known gaps* for #775.

14. Scroll up and look at the answer from step 9 again. ☐

    **You should see:** it is unchanged. Still three spaced sentences, still three cards.

---

## Part D — conflicting sources

The conflict answer uses the other two templates, `Conflicting sources on <…>:` and
`Resolved by memory: <…>`. #726 was first seen on this question as well.

15. Type exactly this and press **Enter**: ☐

    ```
    What time do Meridian Loom retail stores close on weekdays?
    ```

    **You should see:** a heading above the answer reading **Conflicting sources on …**
    followed by what is in conflict, for example *"… weekday closing time"*. Below it, **two
    separate blocks**, one saying **8 PM** and citing **store_hours_2025.pdf**, one saying
    **9 PM** and citing **store_hours_2026.pdf**. Each card's date reads **Date unknown**,
    because neither file states a date. Under the two blocks, an offer to choose which one is
    current.

16. Check the heading and the space around the blocks. ☐

    **You should see:**

    - The heading never shows `<` or `>`. If the model left the topic as a placeholder, the
      heading reads just **Conflicting sources**, with nothing after it. That is correct.
    - There is **no** line reading *"Resolved using what you told Askwell: …"*. You have told
      Askwell nothing about store hours, so that line must not appear. If it appears with
      `<the fact…>` in it, that is a failure of this ticket. If it appears with ordinary words
      in it, that is #776, not this ticket. Record it there.
    - Any sentence before, between or after the two blocks is separated from the next by a
      space or a line break, never joined as in `weekdays.Meridian`.

    If the answer picks one time and does not present a conflict, that is model behaviour.
    Note it and move on. The conflict display itself is `M7-FIX-FE-170`'s test.

17. Click one of the two options in the offer to choose the current file. ☐

    **You should see:** a note beginning *"Noted store_hours_… as current for …"*. If the
    heading in step 16 had no topic, the note reads *"Noted store_hours_… as current."* with
    no *"for"* and no stray space before the full stop.

---

## Part E — the removal itself, the stored text, and the automated checks

18. **Stand-in** — show a copied placeholder being removed. The model will not do this on
    demand, so this runs the same function the API runs while it streams, on the text the
    model produced in #663: ☐

    ```
    scripts/dev.sh run python -c '
    from askwell.agent.placeholders import strip_placeholders as s
    print(repr(s("Credentials rotate every forty-five days [1].\nNot covered: <the specific thing that was asked and not found>.\nResolved by memory: <the fact that was in conflict>.")))
    print(repr(s("The window is <the fact> thirty days [2].")))
    print(repr(s("If x < 5 then use <think> and <a href=\"y\">.")))
    print(repr(s("Passwords need eighteen characters [3]. Not covered: <the")))
    '
    ```

    **You should see:** exactly these four lines:

    ```
    'Credentials rotate every forty-five days [1].\nNot covered:.\nResolved by memory:.'
    'The window is thirty days [2].'
    'If x < 5 then use <think> and <a href="y">.'
    'Passwords need eighteen characters [3]. Not covered:'
    ```

    Line by line:

    1. Both placeholders are gone, and the `[1]` citation is kept. The empty `Not covered:.`
       and `Resolved by memory:.` lines are left for the next stage, which does not show them.
       Part C step 13 and Part D step 16 checked that on screen.
    2. A placeholder inside a real sentence is the only thing removed. The sentence and its
       `[2]` are kept, with a single space where the placeholder was. This is the ticket's
       second edge case.
    3. A comparison and two tags are left alone. Only the `<the …>` shape is removed.
    4. A placeholder the model started and never finished, cut off at the end of the answer,
       is removed, and `[3]` is kept.

19. **Stand-in** — confirm nothing Askwell saved contains a placeholder: ☐

    ```
    scripts/dev.sh psql -c "SELECT count(*) AS answers, count(*) FILTER (WHERE content ~* '<(the|a|an|one|your|some|each|any)[ \t]') AS with_placeholder FROM messages WHERE role = 'assistant';"
    ```

    **You should see:** `answers` equal to the number of questions you asked (3, plus any you
    asked again), and `with_placeholder` equal to **0**.

20. **Stand-in** — the automated checks: ☐

    ```
    scripts/dev.sh check
    scripts/dev.sh test-db
    scripts/dev.sh web-check
    ```

    **You should see:** all three finish with no failures. The ones for this ticket:

    - `api/tests/test_placeholders.py`: 27 cases. They include #663's real output, streaming
      the answer in pieces of every size from 1 to 1,000 characters, tags and comparisons left
      alone, and a check that reads every placeholder in `api/src/askwell/agent/prompts/*.md`,
      so a new template cannot slip past.
    - Within those: `test_no_citation_marker_is_ever_removed` and
      `test_claims_and_their_indices_survive_stripping`, both C4, and
      `test_an_echoed_resolution_line_claims_no_memory_fact` and
      `test_a_real_not_covered_line_is_still_read`, which check the empty-line rules.
      `api/tests/test_conflict.py` and `api/tests/test_partial.py` gained a case each for the
      same rules.
    - `test_an_echoed_prompt_template_is_never_streamed_stored_or_counted` in
      `api/tests/test_ask_api.py`, which runs under `test-db`. A fake model sends a
      placeholder split across several pieces. The test checks that it is not in what was
      streamed, what was stored or the trace, that the turn is not marked partial, and that
      the real sentence keeps its citation.
    - `web/lib/claims.test.ts`: three claims with spacing, a blank line between cited
      paragraphs, a last sentence with no full stop, uncited sentences in between, and
      sentence numbering matching the server.
    - `web/lib/answer-annotations.test.ts`, which now runs as part of `pnpm test`. It was
      never listed there before this ticket.

---

## Teardown

```
podman compose exec api askwell-verify
podman compose down -v
rm -rf /tmp/askwell-test-202
```

**You should see:** both audit chains reported intact before the wipe. Stop the inference
process in the second terminal with `Ctrl+C`.

---

## Known gaps

These are deliberate or belong to other issues. Do not report them as defects of this
ticket.

- **The live walk cannot force a placeholder.** The model decides whether to copy one. Parts
  B–D prove none reaches the screen on these runs. Part E proves the removal. If you do catch
  the model copying one on screen, that **is** a defect of this ticket. Write down the
  question and the exact text.
- **The prompts are unchanged.** Stopping the model from copying templates in the first
  place, by giving it worked examples in the prompts, is #774. It needs an eval run and was
  deliberately left out, so this ticket needed no eval run.
- **Conflicts and "Not covered" lines about things the question never asked.** Seen on this
  ticket's walk: the model presents a conflict or a gap about an unrelated fact. That is #775,
  with #769 and #774 on the same prompt.
- **A "Resolved by memory" line in ordinary words, with no memory behind it**, still shows as
  *"Resolved using what you told Askwell: …"*. This ticket removes only the `<…>` template
  version. The made-up concrete version is #776.
- **A conflict whose topic was a placeholder has no topic on screen.** The heading reads just
  **Conflicting sources**. That is the chosen behaviour (`docs/states-and-edge-cases.md`,
  Ask). The two positions are still shown, because the conflict is real even when the model
  did not name it.
- **Answers from an earlier session cannot be reopened.** A refresh starts a new
  conversation (issue 156), so the browser's own clean-up of answers stored before `0.7.50`
  cannot be seen by clicking. `web/lib/answer-annotations.test.ts` covers it.
- **An answer that quotes document text shaped like a placeholder loses that text**, for
  example a quoted *"<the old rate> was replaced"*. Any `<`, then *the*, *a*, *your* or a
  similar word, then more words and `>`, is removed from the answer. The shape was kept
  narrow on purpose, and the trade-off is recorded in `docs/decisions.md`, 2026-09-28. A
  real case from someone's material should become a new issue.
- **The first click on a rail item sometimes does nothing** (#665). Record it there.
