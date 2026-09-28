# Manual test — M9-FIX-BE-206, answers worked out in several steps still report conflicts, gaps and memory

**Ticket:** `M9-FIX-BE-206`, issue #409. When your library holds **both** documents and a
database, Askwell answers a question in several steps. It searches the documents, queries the
database, reads what came back, and decides whether it needs more. Until now, an answer produced
that way was less honest than a simple one:

- It never said when two of your files disagreed.
- It never named the part of the question it could not answer.
- It never used, or showed, anything you had taught Askwell on the **Memory** screen.

Now it does all three, the same way a simple answer does. The same holds when Askwell stops
early because it reached its limit of eight steps. The note that it stopped early is now its own
paragraph under the answer, instead of being glued onto the last line.

**Version under test:** `0.7.54`. Run `cat VERSION` and update this line if the version has
moved on.

**Time:** about 60 minutes. Most of it is waiting for files to index and for the model to answer
on CPU. Answers worked out in steps are slower than simple ones: allow up to three minutes each.

**Who can run it:** anyone with a browser and a terminal. Every Askwell screen is reached by
clicking, starting from the address in step 1. The terminal starts Askwell, prepares the test
files, and runs a few checks that cannot be done by looking at the screen. Those checks are
labelled **Stand-in**.

**What is being checked.**

| Piece | File |
| ----- | ---- |
| Memory is looked up before the steps start and handed to every step, including the forced answer at the eight-step limit | `run_tool_loop` (`memory_facts`, `schema_notes`, `LoopResult.memory_start`) in `api/src/askwell/agent/loop.py` |
| The step-by-step prompt asks for the same "Conflicting sources on …:" and "Not covered: …" lines a simple answer uses | `api/src/askwell/agent/prompts/tool_loop.v2.md` (replaces `tool_loop.v1.md`) |
| The finished answer is checked for a conflict, uncovered parts and memory citations, and the results are saved on the message, the audit record and the memory usage count | the loop branch of `_run_generation`, and `_cite_claim`'s new `facts_start`, in `api/src/askwell/ask.py` |
| The stopped-early note starts a new paragraph | `_CEILING_NOTE` in `api/src/askwell/agent/loop.py` |

The interface did not change. It already reads the two fixed lines out of any answer and already
shows memory chips, whichever path produced the answer.

**The one rule of this test.** Never type an address into the browser bar except the one in
step 1. Reach every screen by clicking.

**How to tell an answer was worked out in steps.** While Askwell is working, a line of progress
steps appears under your question. A step-by-step answer shows **Working through this in
steps.**, followed by steps such as **Searching your files.** / **Searched your files.** and
**Querying your database.** / **Queried your database.** If the progress line instead ends with
**Answered from your database.**, the question never reached the step-by-step path. That is
#408, not this ticket. Each Part below says what to do when it happens.

> **Known defects you may see on the way. Do not report them against this ticket.**
>
> - **The first click on an item in the left column after a fresh load sometimes does nothing**
>   (#665). Click it again.
> - **A step-by-step answer shows no source cards in the margin, and its two conflicting sides
>   carry no file name under them** (#407). This ticket did not wire citations for step-by-step
>   answers to your files. The text may show bracketed numbers such as `[3]`. For the same
>   reason there is no **"Which one is current?"** offer under a step-by-step conflict: that offer
>   needs the file names.
> - **"Resolved using what you told Askwell" can appear under an answer that used no memory at
>   all** (#776). That is why this test checks memory in **How did you get this?**, not by that
>   line alone.
> - **An answer can show "Not covered: None."** (#781), **or flag a conflict or a gap about
>   something you did not ask** (#775).
> - **A question that mentions the database can be answered from the database alone, skipping
>   the documents** (#408). See *How to tell an answer was worked out in steps*, above.

---

## Before you start

> **Warning: the cold start below deletes everything this Askwell stack holds.** That means
> sources, memory, conversations, the audit log and settings. Your original files are not
> touched. On the shared development machine, check that nobody needs what the stack holds now.
> If you are unsure, use **Settings → Your data → Export everything** first.

### A. The files to add

Askwell can only read folders inside `ASKWELL_ROOTS_MOUNT` in `.env`. Check it:

```
cd ~/external/quantum-plus/askwell
grep ASKWELL_ROOTS_MOUNT .env
```

If it is empty, or does not cover `/tmp`, set `ASKWELL_ROOTS_MOUNT=/tmp`. Then copy the fixture
corpus into a folder Askwell can read, and build a small database dump from the fixture SQL:

```
rm -rf /tmp/askwell-test-206
mkdir -p /tmp/askwell-test-206/docs/corpus /tmp/askwell-test-206/db
cp eval/fixtures/corpus/* /tmp/askwell-test-206/docs/corpus/
{ echo "-- PostgreSQL database dump"; cat eval/fixtures/sql/schema.sql eval/fixtures/sql/seed.sql; } \
  > /tmp/askwell-test-206/db/shop.sql
chcon -R -t container_file_t /tmp/askwell-test-206
ls /tmp/askwell-test-206/docs/corpus /tmp/askwell-test-206/db
```

**You should see:** nine files in `corpus`, including `conflict_2025.pdf`, `conflict_2026.pdf`
and `handbook_a.pdf`, and one file, `shop.sql`, in `db`. The `chcon` line lets the containers
read `/tmp` on a machine with SELinux turned on. If it says `Operation not supported`, your
machine does not use SELinux and you can ignore it.

The first line of `shop.sql` marks it as a PostgreSQL dump. Without it Askwell cannot tell which
database produced the file.

What the files say, so you can check the answers:

| Where | Says |
| ----- | ---- |
| `conflict_2025.pdf`, page 1 | *"As of March 2025, Meridian Loom's standard product return window is **thirty days**."* |
| `conflict_2026.pdf`, page 1 | *"As of January 2026, Meridian Loom's standard product return window is **forty-five days**."* |
| `conflict_2025.pdf` and `conflict_2026.pdf`, page 5 | Gift cards **never expire**. Both years agree. This is deliberately **not** a conflict |
| `handbook_a.pdf` | The standard resignation notice period is **sixty-three days** |
| `shop.sql`, table `customers` | **10** customers. **3** are `premium` tier (Bob Diaz, Elin Karlsson, Hugo Silva). **2** are `enterprise` tier (Dev Patel, Ines Moreau) |
| anywhere | Nothing names Meridian Loom's **head of procurement**. That part of Part D is uncovered on purpose |

### B. Start Askwell from nothing

```
podman compose down -v
scripts/dev.sh web-build
scripts/dev.sh build-api
podman compose up -d
scripts/dev.sh db upgrade head
```

**You should see:** the volumes removed, both builds finish with no red error text, the
containers start, and the migration finish with no error. Do not skip the API build. This fix is
in the API, and without the build you are testing the old code.

In a **second** terminal, start the model on the host and leave it running:

```
scripts/dev.sh inference
```

**You should see:** the supervisor report that the model and the embedding model are ready.

---

## Part A — first run

1. Open a **private or fresh-profile** browser window at full width, so no earlier session
   carries over. Go to `http://127.0.0.1:8000`. ☐

   **You should see:** **Welcome to Askwell**, a **Skip setup** button top right, and a **Get
   started** button. Down the left, a column listing **Ask, Library, Clarifications, Memory,
   Settings**. If you see the Ask screen instead, the stack was not cleared. Go back to *Before
   you start*, B.

2. Click **Get started**. On the passphrase step, click **Not now**, then **Continue**. ☐

   **You should see:** the next step, about the model.

3. Wait until the model section says the model is ready, then click **Continue** without adding
   anything. ☐

   **You should see:** a step beginning *"Ready. Add something to ask about"*.

4. Click **Memory** in the left column. ☐

   **You should see:** a screen headed **Memory**, with the empty message *"Nothing here yet.
   Memory fills as Askwell asks about your material and you answer…"*. No fact rows. Every row
   you see later was written during this test.

---

## Part B — add the documents and the database

Step-by-step answers only happen when the library holds **both** documents and a database. This
Part builds that library.

5. Click **Library** in the left column, then **Add a source**. ☐

   **You should see:** a screen headed **Add a source**, with a **Files** panel (**Choose files**
   and **Choose a folder**), a **Database dump** panel, and a **Connect a database** panel.

6. In the **Files** panel, click **Choose a folder**. Open `/tmp/askwell-test-206/docs`, select
   `corpus` and confirm. If the browser asks whether to upload the files, confirm. Nothing leaves
   this machine. When asked which folder `corpus` is in, type `/tmp/askwell-test-206/docs` and
   click **Add them**. If a note offers **Nominate**, click it, then **Add them** again. ☐

   **You should see:** a note headed **Queued**, and no red **Not added** note.

7. Click **Library** in the left column, then **Add a source** again. In the **Database dump**
   panel, click **Choose a dump file** and pick `/tmp/askwell-test-206/db/shop.sql`. When asked
   *"Which folder is “shop.sql” in?"*, type `/tmp/askwell-test-206/db` and click **Import**. If a
   note offers **Nominate**, click it, then **Import** again. ☐

   **You should see:** the button read **Importing…**, then a note about importing `shop` into a
   sealed database, then a note headed **Imported**: *"shop loaded into its own sealed
   database."* If you see a red note headed **This import did not finish**, write down the
   reason it gives and stop. Nothing below can pass without the database.

8. Click **Library** in the left column. ☐

   **You should see:** a **corpus** row and a **shop** row. Wait until **corpus** reads **Ready**
   with **All 9 indexed.** under it, and **shop** reads **Ready**. On a CPU-only machine the
   documents can take several minutes. Do not start Part C before both are **Ready**: while one is
   still indexing, Askwell does not treat the library as mixed, and the question goes the simple
   way instead.

---

## Part C — a step-by-step answer over conflicting documents reports the conflict

This is the ticket's cold-start walkthrough: a question that needs a document lookup **and** a
database lookup, where the documents disagree.

9. Click **Ask** in the left column. Type exactly this and press **Enter**: ☐

   ```
   What is Meridian Loom's standard product return window, and how many customers are in the customers table?
   ```

   **You should see, while it works:** **Working through this in steps.**, then at least one
   **Searched your files.** and at least one **Queried your database.**

   If the progress line ends with **Answered from your database.** and the answer only gives a
   number of customers, that is #408. Ask this instead, which leads with the documents:
   `According to my documents, what is the standard product return window, and how many rows does the customers table have?`

10. Read the finished answer. ☐

    **You should see:**

    - A small heading beginning **Conflicting sources on**, followed by a short topic about the
      return window, for example `Conflicting sources on standard product return window`.
    - **Two** outlined boxes under it. One says the return window is **thirty days** (the 2025
      position). The other says it is **forty-five days** (the 2026 position). Neither is
      presented as the answer and the other as a footnote.
    - Somewhere in the answer, that the customers table has **10** customers.
    - No file name under either box, and no **"Which one is current?"** offer. That is #407 (see
      *Known defects*), not this ticket.

    **A failure of this ticket looks like:** a single return window stated as the answer (only
    thirty, or only forty-five, or an average), with no **Conflicting sources on** heading. That
    is exactly what step-by-step answers did before this fix. If it happens, ask the same
    question once more. The model decides how to write the answer, and one miss can be the
    model. Two misses in a row is a defect: report it with the whole answer copied out.

11. Under the answer, click **How did you get this?** ☐

    **You should see:** a side panel headed **How did you get this?** listing the steps taken,
    including at least one document search and one database query. There is **no** line
    beginning **Checked your memory** — you have not taught Askwell anything yet. Press **Escape**
    to close it.

**Stand-in:** check that the conflict was recorded on the message, not only drawn on screen:

```
scripts/dev.sh psql -c "SELECT trace->>'loop_stopped_reason' AS loop, trace->>'conflict_detected' AS conflict, trace->>'conflict_topic' AS topic, trace->>'partial_coverage' AS partial, trace->>'memory_used' AS memory FROM messages WHERE role = 'assistant' ORDER BY created_at DESC LIMIT 1;"
```

**You should see:** `loop` reads `answered` (the answer really was worked out in steps — an
empty `loop` means it went another way), `conflict` reads `true`, `topic` names the return
window, `partial` reads `false`, `memory` reads `0`. Before this fix `conflict` was always
`false` on this path.

---

## Part D — a step-by-step answer with an uncovered part names it

12. Click **Ask** in the left column if you are not already there. In the same conversation,
    type exactly this and press **Enter**: ☐

    ```
    What is the standard resignation notice period at Meridian Loom, how many premium-tier customers are in the database, and who is Meridian Loom's head of procurement?
    ```

    **You should see, while it works:** **Working through this in steps.**, then file searches
    and database queries as in step 9. If it ends with **Answered from your database.**, ask it
    again with *"According to my documents and my database,"* in front.

13. Read the finished answer. ☐

    **You should see:**

    - The notice period stated as **sixty-three days**.
    - **3** premium-tier customers. Naming them (Bob Diaz, Elin Karlsson, Hugo Silva) is fine
      but not required.
    - Below the answer, set apart by a thin line down its left edge, a block headed **Not
      covered by your files**, with a line about Meridian Loom's **head of procurement**.
    - **No name** given for a head of procurement anywhere in the answer. A name is invention,
      which breaks C5: report it.
    - Under the block, the existing partial-answer offer, now reached from a step-by-step
      answer: an option to add a source, **Search the web** and **Ask a larger model**. Do
      **not** click any of them. Web search is something you choose, never something Askwell
      does for you (C10), and this test does not need it.

    **A failure of this ticket looks like:** no **Not covered by your files** block, and the
    answer silently leaving out the procurement part, or saying *"some information was
    unavailable"* without naming it. As in step 10, one miss can be the model. Ask again; two
    misses in a row is a defect.

**Stand-in:**

```
scripts/dev.sh psql -c "SELECT trace->>'loop_stopped_reason' AS loop, trace->>'partial_coverage' AS partial, trace->'uncovered_aspects' AS uncovered, trace->>'conflict_detected' AS conflict FROM messages WHERE role = 'assistant' ORDER BY created_at DESC LIMIT 1;"
```

**You should see:** `loop` reads `answered`, `partial` reads `true`, `uncovered` is a list with
one entry naming the head of procurement, and `conflict` reads `false`.

---

## Part E — a fact you taught Askwell is used, and cited, in a step-by-step answer

14. Click **Memory** in the left column. Click **Add a fact**. ☐

    **You should see:** *"Tell Askwell something before it asks."*, a **Subject, e.g. RFQ** box, a
    **What it means, e.g. Request for Quotation** box, and **Add** and **Cancel** buttons.

15. In the subject box type `GC`. In the second box type `gift card`. Click **Add**. ☐

    **You should see:** the form close and one row for **GC** appear, ending in **used in 0
    answers**.

16. Click **Ask** in the left column. Type exactly this and press **Enter**: ☐

    ```
    Does a Meridian Loom GC ever expire, and how many enterprise-tier customers are in the database?
    ```

    **You should see, while it works:** **Working through this in steps.**, then file searches
    and database queries. If it ends with **Answered from your database.**, ask it again with
    *"According to my documents and my database,"* in front.

17. Read the finished answer. ☐

    **You should see:**

    - That gift cards **never expire**.
    - **2** enterprise-tier customers.
    - **No Conflicting sources on** heading. Both years say gift cards never expire, only in
      different words, and that is not a conflict. A conflict heading here is a failure: report
      it.
    - If the answer explains what **GC** means, a small chip right after that sentence reading
      **GC = gift card**. Click the chip: a popover opens saying you told Askwell this. Press
      **Escape** to close it.

    Whether the model writes a sentence explaining **GC** is its choice. The prompt allows memory
    to be cited only for what a term means, never for a fact from your files. A chip is expected
    in most runs, but its absence alone is not a failure. Step 18 is the check that does not
    depend on the model's wording.

18. Under the answer, click **How did you get this?** ☐

    **You should see:** a line reading **Checked your memory — 1 fact, 0 schema notes**, and under
    it the **GC = gift card** fact, shown the same way as a chip. Before this fix, a step-by-step
    answer never looked at memory, and this line never appeared. Press **Escape** to close the
    panel.

19. Click **Memory** in the left column. ☐

    **You should see:** the **GC** row now ends in **used in 1 answer** — **only if** step 17
    showed the chip. If there was no chip, it still reads **used in 0 answers**, which is correct:
    the count is of answers that **cited** the fact, not ones that merely looked at it.

**Stand-in:**

```
scripts/dev.sh psql -c "SELECT trace->>'loop_stopped_reason' AS loop, trace->>'memory_used' AS memory, trace->'memory_fact_ids' AS facts, trace->>'conflict_detected' AS conflict, (SELECT count(*) FROM fact_usage u WHERE u.message_id = m.id) AS cited FROM messages m WHERE role = 'assistant' ORDER BY created_at DESC LIMIT 1;"
```

**You should see:** `loop` reads `answered`, `memory` reads `1`, `facts` holds one id,
`conflict` reads `false`, and `cited` reads `1` if there was a chip or `0` if there was not.
Before this fix `memory` was always `0` and `facts` always `[]` on this path.

**Stand-in:** check that the audit record carries the same values, not the old hardcoded ones:

```
scripts/dev.sh psql -c "SELECT payload->>'conflict_detected' AS conflict, payload->>'partial' AS partial, payload->'memory_fact_ids' AS facts, payload->>'tool_ceiling' AS ceiling FROM audit_interactions WHERE kind = 'ask_asked' ORDER BY occurred_at DESC LIMIT 3;"
```

**You should see:** three rows, newest first, for Parts E, D and C: `false / false / [one id] /
false`, then `false / true / [] / false`, then `true / false / [] / false`.

---

## Part F — an answer stopped at the eight-step limit keeps the same checks

Askwell stops a step-by-step answer after eight lookups and answers with what it found. That
answer must still report conflicts and gaps. Whether a real model reaches eight lookups depends
on the model, so this Part invites it rather than forcing it.

20. Click **Ask** in the left column. Type exactly this and press **Enter**: ☐

    ```
    For each of these Meridian Loom policies, give the 2025 value and the 2026 value separately: return window, express shipping fee, loyalty points, Loomwear Sensor trade-in credit, gift card expiry, support first-response time, affiliate commission, warehouse restock. Then, for each of the ten customers in the database, give their tier and how many orders they placed.
    ```

    **You should see, while it works:** many **Searched your files.** and **Queried your
    database.** steps.

21. Read the finished answer. ☐

    **If the progress line ends with Stopped after 8 steps for this question.**, you should see:

    - Whatever facts it found, stated normally.
    - A **Conflicting sources on** heading if it found both years of any policy that changed
      (most of them did — only the gift card did not).
    - A **Not covered by your files** block for any part it did not reach, if the model named
      them.
    - As a **separate last paragraph**, not glued onto the line above it: *"Askwell stopped after
      reaching its 8-step limit for this question — this is what it found before then, not a
      complete answer."* If a **Not covered by your files** block is present, that sentence must
      **not** appear inside it.

    **If Askwell answered in fewer than eight steps**, that is allowed. The model decided it had
    enough. Skip to the stand-in below and run the automated check instead.

**Stand-in (only if the eight-step limit was reached):**

```
scripts/dev.sh psql -c "SELECT trace->>'loop_stopped_reason' AS loop, trace->>'stopped_early' AS early, trace->>'conflict_detected' AS conflict, trace->>'partial_coverage' AS partial, trace->'uncovered_aspects' AS uncovered FROM messages WHERE role = 'assistant' ORDER BY created_at DESC LIMIT 1;"
```

**You should see:** `loop` reads `tool_ceiling`, `early` reads `true`, and `conflict`/`partial`
match what step 21 showed on screen. `uncovered` must not contain the words *"Askwell stopped
after reaching its 8-step limit"*.

**Stand-in (if the limit was not reached):** run the two tests that drive a stopped answer with a
scripted model. The first checks that the forced answer at the limit still sees memory. The
second needs the stack up, and checks that a stopped answer still gets the conflict and gap
checks and keeps the stopped-early note out of the gap:

```
scripts/dev.sh test -k "forced_compose_at_the_ceiling_still_sees_memory"
scripts/dev.sh test-db -k "ceiling_still_runs_the_same_checks"
```

**You should see:** `1 passed` from each, and no failures or skips.

---

## Part G — the earlier Parts still hold after a restart

22. In the first terminal: ☐

    ```
    podman compose restart api worker
    ```

    Wait about 20 seconds, then reload the browser tab.

23. Click **Memory** in the left column. ☐

    **You should see:** the **GC** row still there, with the same **used in** count as step 19.

24. Click **Ask**. Find the Part C question in the conversation (scroll up if needed). ☐

    **You should see:** the Part C answer still shows the **Conflicting sources on** heading and
    both boxes, and the Part D answer still shows **Not covered by your files**. Both are read
    back from the saved answer, not recomputed.

---

## Clean up

```
podman compose down -v
rm -rf /tmp/askwell-test-206
```

Put `ASKWELL_ROOTS_MOUNT` in `.env` back to what it was, if you changed it.

---

## Known gaps

Deliberately not built by this ticket. Do not report these as defects.

- **No citations to your files for a step-by-step answer** (#407). The answer's `[N]` markers
  are not turned into source cards, so the margin stays empty, the conflict boxes carry no file
  name or date, and the **"Which one is current?"** offer does not appear. Memory citations
  **are** wired, because they need only a known range of numbers; mapping a tool result's number
  back to a page is the separate job #407 owns.
- **No Continue button after the eight-step limit.** The API offers to continue a stopped
  answer, but nothing in the interface sends it yet. Part F checks the stopped answer only.
- **A database-only answer still skips these checks.** When the progress line ends with
  **Answered from your database.**, the answer did not go step by step and gets no conflict,
  gap or memory checks. That path is #408's, and #409 did not name it.
- **Inline clarifications do not pause a step-by-step answer.** A simple answer can stop and
  ask you a question mid-answer. A step-by-step one cannot. #409 did not name it, and pausing
  mid-way through several lookups is its own design.
- **A step-by-step answer can be used even when every lookup failed** (#786). It can now draw on
  memory in that case. The fix recommended there is one condition.
- **The prompt change has not been measured** (#787). `AGENTS.md` §4 requires an eval run for a
  prompt change. The step-by-step prompt has never had one, before or after this ticket, and the
  tool-selection suite does not pass memory in, so it measures the prompt, not the memory wiring.
  The automated tests named in Part F and in `api/tests/test_ask_api.py` cover the wiring.
- **Whether the model writes the two fixed lines, and cites memory, is its choice.** This ticket
  made the step-by-step prompt ask for them and made Askwell read them back. A small local model
  will sometimes not write them. Parts C–E say how many misses count as a defect.
