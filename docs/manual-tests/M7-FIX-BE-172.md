# Manual test — M7-FIX-BE-172, a clarification has to be worth asking

**Ticket:** `M7-FIX-BE-172`. Before this change, adding the fixture corpus produced one question:
*"'PM' appears throughout. What does it mean?"* It cited two lines, "close at 8 PM" and "close at
9 PM", which make the meaning obvious. Those same two lines disagree about the closing time, and
that was not asked. Now a term has to clear a floor before it becomes a question. "PM" straight
after a clock time counts as a time of day. A term the file spells out, as in "Request for
Quotation (RFQ)", counts as already defined. A term that fails the floor is dropped, not saved for
later. The same "PM" used as jargon ("the PM signs off") is still asked. Two files that disagree
about a time are now noticed and asked about.

**Version under test:** `0.7.33`. Run `cat VERSION` and update this line if the version has moved on.

**Time:** about 45 minutes. Most of it is waiting for files to index.

**Who can run it:** anyone with a browser and a terminal. The terminal is used only to start
Askwell and to make the test files. Every Askwell screen is reached by clicking, starting from
Askwell's front page.

**What is being checked.** All of it is in `api/src/askwell/clarify.py`:

- `_detect_abbreviations`: the floor, using `_CONTEXT_READINGS`, `_defined_inline` and
  `_unresolved_occurrences`.
- `_detect_contradictions`: now also uses `_TIME_FACT_PATTERN`.

There is no screen change. The **Clarifications** screen shows what the backend raised, so this
test reads the result there.

> **Two things differ from the ticket, on purpose.** Do not report them as defects.
>
> - **The ranking was not changed.** The ticket says the ranking "chose a term definition over a
>   live factual conflict". Reading the code showed that conflicts already ranked first. The
>   store-hours conflict was never *detected*, because the conflict detector only understood
>   sentences like "X is 30 days", not "close at 8 PM". The fix is in detection. The order is
>   pinned by a test (`docs/decisions.md`, 2026-09-24, `M7-FIX-BE-172`).
> - **The ticket's `st_cd` example is a database column.** Columns are asked about by a different
>   part of Askwell (`askwell.schema_introspect`), which this ticket does not touch. Part E uses
>   `STCD` written in a document instead. That is the case the floor could wrongly silence.

**One question per source, once.** Askwell looks for questions once, when a source has finished
indexing, and never again for that source. Each part below therefore adds a **new** folder. Adding
more files to a folder that has already been added does not test anything.

---

## Before you start

> **Warning: the cold start below deletes everything this Askwell stack holds.** That means
> sources, memory, conversations, the audit log and settings. Your original files are not touched.
> On the shared development machine, check that nobody needs what the stack holds now. If you are
> unsure, use **Settings → Your data → Export everything** first.

### Test files

Askwell can only read folders inside `ASKWELL_ROOTS_MOUNT` in `.env`. Check it:

```
cd ~/external/quantum-plus/askwell
grep ASKWELL_ROOTS_MOUNT .env
```

If it is empty, or does not contain `/tmp`, set `ASKWELL_ROOTS_MOUNT=/tmp`.

Make four test folders. The first is a copy of the fixture corpus. The other three are small
text files for the edge cases:

```
rm -rf /tmp/askwell-test-172
mkdir -p /tmp/askwell-test-172
cp -r eval/fixtures/corpus /tmp/askwell-test-172/corpus

mkdir -p /tmp/askwell-test-172/quiet
printf 'The garden is watered every morning.\nVisitors sign the book at the gate.\n' \
  > /tmp/askwell-test-172/quiet/garden.txt
printf 'Tools go back in the shed after use.\nThe hose is coiled on the left hook.\n' \
  > /tmp/askwell-test-172/quiet/shed.txt

mkdir -p /tmp/askwell-test-172/jargon
printf 'The PM signs off on every change order before work starts.\n' \
  > /tmp/askwell-test-172/jargon/change-orders.txt
printf 'Send the weekly draft to the PM by Thursday.\n' \
  > /tmp/askwell-test-172/jargon/reporting.txt
printf 'The site office closes at 6 PM on Fridays.\n' \
  > /tmp/askwell-test-172/jargon/site-office.txt

mkdir -p /tmp/askwell-test-172/codes
printf 'Log each return under code STCD.\nA Request for Quotation (RFQ) is needed above the limit.\n' \
  > /tmp/askwell-test-172/codes/returns.txt
printf 'STCD applies to every refund.\nEach RFQ is filed with the buyer.\n' \
  > /tmp/askwell-test-172/codes/refunds.txt
ls -R /tmp/askwell-test-172
```

**You should see:** four folders: `corpus` with nine files, `quiet` with two, `jargon` with three
and `codes` with two.

What each folder is for:

| Folder | Holds | Should ask |
| ------ | ----- | ---------- |
| `corpus` | The fixture corpus the ticket names | The store-hours conflict. Not "PM" |
| `quiet` | Nothing a person would need to explain | Nothing |
| `jargon` | "PM" meaning a person, twice, and "6 PM" once | What "PM" means |
| `codes` | A real code, `STCD`, and `RFQ` spelled out in full | `STCD` only |

### Start Askwell from nothing

```
podman compose down -v
scripts/dev.sh build-api
scripts/dev.sh web-build
podman compose up -d
scripts/dev.sh db upgrade head
```

**You should see:** the volumes removed, both builds finish with no red error text, Compose report
`postgres`, `redis`, `egress-proxy`, `api` and `worker` as started, and the migration end without
an error.

Do not skip `build-api`. The change is in the API's code, which is baked into its image. Without
a rebuild, Askwell runs the old code and asks about "PM" again.

In a **second** terminal, start the model on the host and leave it running:

```
scripts/dev.sh inference
```

**You should see:** the supervisor report the embedding model ready. Files do not finish indexing
without it, and Askwell only looks for questions once a source has finished indexing.

---

## Part A — cold start: the first thing Askwell asks

This is the ticket's own walkthrough. It is the one impression that decides whether a person ever
opens the queue again.

1. Open a **private or fresh-profile** browser window, so no earlier session carries over. Open
   `http://127.0.0.1:8000`. ☐

   **You should see:** the welcome screen, "Welcome to Askwell", with a **Get started** button.
   If you see the **Ask** screen instead, the stack was not cleared. Go back to **Start Askwell
   from nothing**.

2. Click **Get started** and follow the steps until one offers to add material. ☐

   **You should see:** a step with **Choose files** and **Choose a folder**.

3. Click **Choose files**. In the file picker, open `/tmp/askwell-test-172/corpus`, select all
   nine files (`Ctrl+A`) and confirm. ☐

   **You should see:** the files listed. `figures.xlsx` may appear in a separate note as
   something for a later milestone, or be accepted as a table. Either is fine; it plays no part
   in this ticket. A question **"Which folder are these files in?"** appears.

4. Type `/tmp/askwell-test-172/corpus` and click **Add them**. If a note offers
   **Nominate /tmp/askwell-test-172/corpus** (or a parent folder), click it and then click
   **Add them** again. ☐

   **You should see:** the PDFs and `spec.docx` accepted, with no red "Not added" note. Finish
   the welcome steps. If a step offers to skip, skipping is fine.

5. Click **Library** in the rail on the left. Wait until every file from the corpus is **ready**.
   `notice_scan.pdf` may say it needs attention because it is a scan. That is fine. What matters
   is that nothing still says queued or indexing. ☐

   **You should see:** `store_hours_2025.pdf` and `store_hours_2026.pdf` both ready.

6. Wait another 30 seconds, then click **Clarifications** in the rail. ☐

   **You should see:** a page headed **Clarifications**, with a count underneath, for example
   **1 question pending**. The questions are grouped under the corpus source. **The first
   card** has:

   - the subject, in small typewriter text: `meridian loom retail stores close`
   - the question: **Sources disagree on meridian loom retail stores close:
     \*store_hours_2025.pdf\* says 8 PM; \*store_hours_2026.pdf\* says 9 PM. Which is current?**
     (The asterisks around the filenames may show as plain `*`. That is existing behaviour, not
     this ticket.)
   - two evidence lines underneath: one starting `store_hours_2025.pdf says 8 PM`, with a date
     in brackets and the sentence "Meridian Loom retail stores close at 8 PM on weekdays."; and
     one starting `store_hours_2026.pdf says 9 PM`, with the 9 PM sentence
   - two buttons to choose from: `store_hours_2025.pdf` and `store_hours_2026.pdf`

7. Read every card on the page, top to bottom. ☐

   **You should see:** **no card anywhere whose subject is `PM`** and no question containing
   "What does it mean?" about PM. **This is the ticket's main check.** A `PM` card at any
   position is a defect.

   Other cards below the conflict are allowed if they are about something else, for example
   poor scan quality on `notice_scan.pdf`. Write down what they are. When this change was built,
   the conflict was the only question, so anything extra is worth a note, but it is not a
   defect of this ticket unless it is about PM.

8. Click **Memory** in the rail. Look through the facts listed. ☐

   **You should see:** nothing for `PM`: no fact, and no "not asked" guess. A term that fails the
   floor is **dropped**, not recorded as a question Askwell chose not to ask. A `PM` entry here,
   even a low-confidence one, is a defect.

## Part B — answer it, and see the empty queue

9. Click **Clarifications** in the rail. On the store-hours card, click
   `store_hours_2026.pdf`. ☐

   **You should see:** the card confirm that it was saved, with an **Undo** offered for a few
   seconds. Do not click Undo.

10. Answer or **Skip** any other cards so that nothing is pending, then click **Clarifications**
    in the rail again to reload the page. ☐

    **You should see:** no pending count, and the sentence: *"Nothing to clarify. Askwell asks
    when it finds something it can't work out — an unlabelled column, a date format, two
    documents that disagree."* This is the correct empty state. It is not an error.

## Part C — nothing worth asking stays empty

The ticket warns: an empty queue is a correct outcome and must not be padded.

11. Click **Library** in the rail, then **Add a source**. Click **Choose files**, open
    `/tmp/askwell-test-172/quiet`, select both files and confirm. Type
    `/tmp/askwell-test-172/quiet` under "Which folder are these files in?" and click
    **Add them**. ☐

    **You should see:** both files accepted.

12. Click **Library**. Wait until `garden.txt` and `shed.txt` are ready. Wait another 30 seconds,
    then click **Clarifications**. ☐

    **You should see:** the same "Nothing to clarify" sentence as step 10. There is no group for
    the `quiet` source and no count in the rail. Any question about these two files is a defect:
    it is padding.

## Part D — "PM" used as jargon is still asked

This is the case the ticket says to watch, because it is where the floor will be wrong. The
word is the same as in Part A, but here it means a person.

13. Click **Library**, then **Add a source**, then **Choose files**. Open
    `/tmp/askwell-test-172/jargon`, select all three files and confirm. Type
    `/tmp/askwell-test-172/jargon` and click **Add them**. ☐

14. Click **Library**. Wait until all three files are ready. Wait another 30 seconds, then click
    **Clarifications**. ☐

    **You should see:** **1 question pending**, in one group for the `jargon` source. The card
    has the subject `PM` and the question **'PM' appears throughout. What does it mean?** Under
    it are one or two quoted passages. There is an empty answer box with **Save** and **Skip**
    beside it.

    If there is no PM card, the floor has silenced the thing the loop exists for. **That is a
    defect.**

15. Read the quoted passages on the PM card. ☐

    **You should see:** passages from `change-orders.txt` and/or `reporting.txt` only ("The PM
    signs off…", "…to the PM by Thursday"). **Not** `site-office.txt` ("closes at 6 PM"). That
    line answers the question for its own use of PM, and a question must never quote the line
    that answers it.

16. Type `Project manager` in the answer box and press **Enter**. ☐

    **You should see:** the card confirm the answer was saved. Click **Memory** in the rail. A
    fact for `PM` now reads `Project manager`. This is the first `PM` entry in Memory. It came
    from the user's answer, not from a guess.

## Part E — a real code is asked, and a term the file defines is not

17. Click **Library**, then **Add a source**, then **Choose files**. Open
    `/tmp/askwell-test-172/codes`, select both files and confirm. Type
    `/tmp/askwell-test-172/codes` and click **Add them**. ☐

18. Click **Library**. Wait until both files are ready. Wait another 30 seconds, then click
    **Clarifications**. ☐

    **You should see:** **1 question pending**, in one group for the `codes` source. The card's
    subject is `STCD`, and the question is **'STCD' appears throughout. What does it mean?** The
    quoted passages contain "code STCD" and "STCD applies to every refund".

    **There is no card for `RFQ`.** `returns.txt` spells it out as "Request for Quotation
    (RFQ)", so asking would ask the user what their own file already says. An `RFQ` card is a
    defect. A missing `STCD` card is also a defect: that is a genuine domain code, and it must
    still be asked.

19. Click **Memory** in the rail. ☐

    **You should see:** no entry for `RFQ`. It was dropped, not recorded as a guess.

20. Click **Clarifications** and click **Skip** on the `STCD` card. ☐

    **You should see:** the card confirm it was skipped. With nothing else pending, reloading the
    page shows the "Nothing to clarify" sentence again.

## Part F — the answer is used (optional, needs the generation model)

This re-walks the Ask path, so a regression there shows up on this ticket rather than in someone's
install. Skip it if no generation model is configured.

21. Click **Ask** in the rail. Type `What time do Meridian Loom retail stores close on weekdays?`
    and send it. ☐

    **You should see:** an answer that cites `store_hours_2026.pdf` and/or
    `store_hours_2025.pdf`, and reflects that the 2026 file was chosen as current in step 9. An
    answer with no citation at all is a defect (C4), but it belongs to the answer path, not this
    ticket. Record it and file it.

---

## Cleanup

```
rm -rf /tmp/askwell-test-172
```

Stop the inference process with `Ctrl+C`. Leave the stack running or run `podman compose down`
as you prefer. Do not use `-v` unless you mean to clear it again.

---

## Known gaps

These are not built by this ticket. Do not report them as defects.

- **Conflicts written in words are not noticed.** `conflict_2025.pdf` and `conflict_2026.pdf`
  disagree on eight facts, but they write numbers as words ("thirty days"). The detector only
  reads digits, so none of those is asked. Tracked as issue #705.
- **Only "AM" and "PM" are recognised from context.** Another everyday all-caps word used in its
  everyday sense ("OK" is already on a fixed list, but for example "TBC") is still asked. Adding
  one is deliberate work, and it should come with a test proving that the jargon use of the same
  word is still asked.
- **"8PM" with no space is not treated as a time.** It is not counted as a use of "PM" at all,
  so it neither triggers nor suppresses a question. Only "8 PM" (with a space) is read as a time
  of day.
- **A phrase can accidentally look like a definition.** Any bracketed term whose surrounding
  words happen to start with its letters counts as defined, for example "send to the finance
  queue (FQ)". This is the known edge of the floor (`docs/decisions.md`, 2026-09-24).
- **An inline definition is not copied into Memory.** "Request for Quotation (RFQ)" stops the
  question, but no `RFQ` fact appears in Memory. The definition is found through the passage
  that holds it when you ask.
- **Database columns such as `st_cd` are outside this ticket.** Column questions come from
  `askwell.schema_introspect`, and the floor does not touch them.
- **A folder is scanned for questions only once.** Adding files to a folder that already has
  questions does not raise new ones. That is existing behaviour from `M3-RAISE-BE-068`, not this
  ticket.
- **Asterisks around filenames in the conflict question** may show as literal `*`. That
  predates this ticket.
- **An unrelated test-order failure** (`test_inline_clarify` fails when `test_schema_introspect`
  runs first) was found while verifying this ticket. It predates the change and is tracked as
  issue #706. It does not affect this walkthrough.
