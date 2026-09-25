# Manual test — M7-QA-TEST-168, the release checklist and the regression walkthrough

**Ticket:** `M7-QA-TEST-168`. One checklist that gathers every release gate, one manual
walkthrough script from a cold install through every milestone's headline path, and one place
to record the result per release.

**Version under test:** whatever `cat VERSION` prints. Every place below that expects a version
expects that value.

**Time:** about 30 minutes for Parts A–D (the documents themselves), and about half a day for
Part E (a dry run of the walkthrough on the development stack). Part F takes 20 minutes.

**Who can run it:** anyone who can paste a line into a terminal and click around a browser.
Parts A, B and F are terminal and reading. Part E is almost all clicking.

**What was built.** This ticket's deliverable is documents, not code:

| File | What it is |
| ---- | ---------- |
| `docs/release-checklist.md` | The twelve gates G1–G12, each with a pass condition, how to run it, and where its evidence lives |
| `docs/release-walkthrough.md` | Gate G11: the manual regression script, sections W0–W9, one per milestone headline path |
| `docs/release-log.md` | The per-release record: one entry per version, `Decision: release` or `held` |
| `docs/release-procedure.md` step 3d | Refuses to checksum anything until the log says `Decision: release` for that exact version |
| `api/tests/test_release_checklist.py` | 21 tests that fail if the documents drift from the eval suites, the build plan or the screens, if the outbound count is read with a bare `curl`, or if the walkthrough runs a repository script |

**What this test proves, and what it does not.** It proves the checklist says what the ticket
requires, that a later edit cannot quietly weaken it, and that every walkthrough step can
actually be reached by clicking in today's product. **It is not a release run.** Executing the
checklist for a real release is separate work (the ticket says so) and today it would end
`held` — see Part F.

> **Four walkthrough steps were corrected while writing this test**, because they described
> something the product does not have. W1.1 named a "health surface" (there is none; readiness
> is the absence of a status banner, plus `/health`). W2.3 said "point it at a model file"
> (there is no picker; the file goes at a stated path and **Verify the file** checks it). W3.9
> said "reopen it from the conversation list" (there is no such list, #199). W9.4–W9.5 implied
> a backup button (there is none, #615). The **[net]** reads also changed from
> reading `/network` with a bare curl, which answers `No session.`, to Settings → Network activity.
> If you find another step like these in Part E, that is a defect in the walkthrough. Fix the
> step or file an issue. Do not work around it silently.

---

## Part A — the guard tests pass

1. In a terminal:

   ```
   cd ~/external/quantum-plus/askwell
   scripts/dev.sh test -k test_release_checklist
   ```

   **You should see:** the last line reads `21 passed, … deselected` with no `failed`.

## Part B — the tests catch a weakened safety bar

This is the ticket's sharpest edge case: a 1.00 category scoring 0.9 must read as a failure,
not a number. Prove that editing the checklist to make it a number is caught.

1. Take a copy of the checklist so you can put it back exactly:

   ```
   cp docs/release-checklist.md /tmp/release-checklist.backup.md
   ```

2. Open `docs/release-checklist.md` in any text editor. Find the row that begins
   `| SQL safety | \`sql_safety.v1\` | 10 |`. Replace everything after the `10 |` on that line
   with `` `PASS` if mean ≥ 0.90 | `` and save.

3. Run the tests again:

   ```
   scripts/dev.sh test -k test_release_checklist
   ```

   **You should see:** at least one test `FAILED`, including
   `test_the_strict_categories_are_pass_or_fail_not_a_number`. The last line says
   `… failed, … passed`.

4. Put the file back and run the tests once more:

   ```
   cp /tmp/release-checklist.backup.md docs/release-checklist.md
   scripts/dev.sh test -k test_release_checklist
   ```

   **You should see:** `21 passed` again.

5. Repeat steps 2–4 with the **Tasks** column instead: change the `grounded_qa.v1` row's `40`
   to `39`.

   **You should see:** at least `test_each_row_matches_its_suite_file` and
   `test_the_eval_table_has_eight_categories_and_165_tasks` fail. Restore the file and see
   `21 passed`.

## Part C — read the checklist as the person releasing

Open `docs/release-checklist.md` and read it top to bottom as someone who has never seen it.
Tick each line you can confirm by looking.

1. **How to read a result.** ☐
   **You should see:** the sentence "Every gate is pass or fail. None is a number." and, in bold,
   "SQL safety at 0.9 is a `FAIL`." A table of four marks: `PASS`, `FAIL`, `BLOCKED`, `ACCEPTED`.
   `BLOCKED` says **Blocked** under Release, with "A release does not go out unmeasured".

2. **The four rules.** ☐
   **You should see:** numbered 1–4. Rule 1: a gate that cannot run blocks the release, and
   the eval runner being down is the example. Rule 2: "An intermittent failure is a failure."
   Rule 3: a result belongs to one `VERSION`. Rule 4: an accepted known issue needs an issue
   number, a reason, and a follow-up, or the gate is `FAIL`.

3. **What can never be accepted.** ☐
   **You should see:** a bulleted list naming SQL safety, web escalation discipline and
   abstention; the offline gate; the restore gate; and a security finding against C1–C10.

4. **The gate table.** ☐
   **You should see:** twelve rows, G1 to G12, each with all five columns filled: #, Gate,
   Pass condition, How to run it, Evidence lives in. The gates are: version and changelog,
   automated checks, eval, offline, restore, security review, performance, licence and
   notices, support boundary, artefacts and cold install, the walkthrough, open defects. That
   covers every gate the ticket's description names.

5. **The eval table (G3).** ☐
   **You should see:** eight rows. The Tasks column adds up to 165 (40 + 15 + 10 + 40 + 10 +
   25 + 15 + 10). The SQL safety and web escalation discipline rows say **pass-or-fail**. They
   do not give a number to meet. The abstention row says it is never accepted and never
   improved by lowering the retrieval threshold. Below the table, a paragraph in bold says
   `eval/bench.py` exits 0 for a scored suite even when it is below its bar.

6. **Check that last claim is true.** ☐ In the terminal:

   ```
   grep -n '"pass_bar"' eval/suites/*.json
   ```

   **You should see:** nine lines. `sql_safety.v1.json` and `web_escalation.v1.json` show
   `1.0`. `smoke.v1.json` is the harness check the checklist says is not a category. The other
   six match the bars in the checklist's eval table.

7. **Time.** ☐
   **You should see:** a table estimating about two working days on one platform, and the
   sentence telling you to split the checklist if a release needs more than two days, and to
   record that split in `docs/decisions.md`.

## Part D — the record and the procedure

1. Open `docs/release-log.md`. ☐
   **You should see:** it says append-only, newest first. A format block with one row per gate,
   including eight separate `G3 Eval — …` rows, two of them marked `PASS / FAIL only`. A line
   headed **Accepted known issues** and one headed **Held because**. At the bottom: "No release
   has been run against this checklist yet."

2. Open `docs/release-procedure.md` and scroll to **3d. The release checklist**. ☐
   **You should see:** it comes before **4. Generate checksums**, and says in bold not to
   proceed to step 4 until an entry for this exact `VERSION` reads `Decision: release`.

3. Open `docs/release-walkthrough.md`. ☐
   **You should see:** sections W0 to W9, each heading ending in the milestone it walks: M7,
   M0, M7, M1, M2, M3/M4, M5, M6, M6.5, M7. The rule "A step that fails and then passes on a
   retry is marked **`FAIL`**". The **Keeping this current** section says M8's steps are
   appended when M8 lands.

---

## Part E — dry run of the walkthrough on the development stack

The real run is on the release artefact, on a clean machine, with the cable out. There is no
installable artefact yet (#559), so this is a **dry run**: every walkthrough step walked by
clicking on the development stack, to prove each one can be reached and reads the way the
script says. A step that cannot be reached, or whose Expect column does not match the screen,
is a defect in `docs/release-walkthrough.md`.

**Keep score** in a scratch copy, not in the repository:

```
cp docs/release-walkthrough.md /tmp/walkthrough-dryrun.md
```

Mark each step in `/tmp/walkthrough-dryrun.md` as you go. W0 is `BLOCKED` in a dry run (no
artefact, #559). Mark it and move on.

**You need** a small set of your own material in one folder under the folder Askwell may
read (`ASKWELL_ROOTS_MOUNT` in `.env`): a text PDF of a few pages, a scanned PDF with no text
layer, a CSV with a column named just `status` or `amount`, and a small `.sql` dump. Two PDFs
that disagree on one fact (for W4.3) can be two short documents you write and print to PDF.

### E1 — cold start (W1)

> **Warning:** `down -v` deletes every volume of this stack: every indexed source, every
> memory fact, every conversation and the audit log on this development machine. Take a
> backup first (`docs/restore-release-test.md` §1.3) if any of it matters.

1. Remove all previous state, build the interface, and bring the stack up:

   ```
   podman compose down -v
   podman compose up -d
   scripts/dev.sh db upgrade head
   scripts/dev.sh web-build
   podman compose up -d --force-recreate api
   ```

   **You should see:** services reported started, migration lines from the second command, and
   a web build with no red error text. Wait about thirty seconds before continuing.

2. **W1.1.** Run `curl -s localhost:8000/health`.
   **You should see:** JSON whose `version` is what `cat VERSION` prints, and a `components` list in which
   `database`, `queue`, `worker` and `inference` each say `"state":"reachable"`. If the version
   says anything else, the API container is serving an old build; repeat the last command
   above.

3. **W1.2.** Run `ss -ltn`, the OS's own port listing. The walkthrough uses it rather than
   `scripts/verify-localhost-binding.sh` because an installed machine has no repository (#717).
   **You should see:** Askwell's ports (8000, and the inference port) bound to `127.0.0.1` or
   `[::1]` only. None on `0.0.0.0`, `*` or `[::]`.

### E2 — first run (W2)

4. Open a **private** browser window at `http://127.0.0.1:8000`.
   **You should see:** a page headed **Welcome to Askwell**, with the subtitle "A personal AI
   over your own files, on this machine." and step 1, **What this is**. It is not a chat box.
   The step's text includes **It works offline.** and **Your files stay where they are.**
   There is a **Skip setup** link at the top right.

5. **W2.1.** Click **Get started**.
   **You should see:** step 2, **Check the machine**, with the question "Set a passphrase?"
   and two buttons, **Set a passphrase** and **Not now**.

6. **W2.2.** Click **Not now**.
   **You should see:** it moves on. Nothing asks about a passphrase again. Click **Continue**
   if it is shown.

7. **W2.3.** Step 3, **Get the model**. Do not press **Download**.
   **You should see:** a line beginning "On a slow or air-gapped connection: download … yourself
   and place it at exactly this path, then verify it —", followed by a file path in a grey box,
   and a **Verify the file** button. Press **Verify the file**.
   **You should see:** the button reads **Checking…** briefly, then the step reports the model
   as in place. On this development machine the model file is usually already there, so this
   step passes without copying anything. A real release run copies the file in from removable
   media first. If the step says the file is missing or wrong, that is the verification
   working. Copy the right file to that path and press the button again.

8. Continue to step 4, **Add something and ask**.
   **You should see:** "Ready. Add something to ask about — …" with the add box still open.

9. **W2.4.** Click **Settings** in the left rail.
   **You should see:** a page headed **Settings**. The first section is **Model and speed**,
   naming the model file in use and the probed tier. Write down the tier.

10. **W1.3 / W2.5 [net].** Scroll down to **Privacy and security**, then **Network activity**.
    **You should see:** a line reading "**N** outbound requests permitted · **M** refused,
    measured by the egress proxy". Write both numbers in the dry-run copy. This is the baseline
    for every later **[net]** step.

### E3 — it answers from my documents (W3)

11. **W3.1.** Click **Ask** in the rail.
    **You should see:** not an empty chat box. A panel reading **Nothing added yet**, "There is
    nothing to ask about until you add a source…", and an **Add a source** button.
    Before clicking it, click **Library** in the rail once.
    **You should see:** "Nothing has been added yet", the four ways to add a source, and an
    **Add a source** button. **Today this is wrong:** **Database dump** and **Connect a
    database** both say "(arriving later)", but both are built. That is #722. It is not a
    walkthrough step, so it does not change any W mark. Do not file it again. Click **Ask**.

12. **W3.2.** Click **Add a source**.
    **You should see:** a page headed **Add a source**, "Nothing added on this machine yet", and
    in bold "Askwell indexes your files where they are." A **Files** box with **Choose files**
    and **Choose a folder**. Click **Choose a folder** and choose the folder holding the text
    PDF and the scan. If the page asks **Which folder are these files in?**, type the folder's
    full path.
    **You should see:** a card listing both files and moving to queued.

13. **W3.3.** Click **Library** in the rail.
    **You should see:** "Every source you have added, and what state it is in." Both files are
    listed, and each one's state changes until it reads as indexed. Click the scan's row to
    open its detail.
    **You should see:** a page count and text. It is not empty. The scan was read by OCR.

14. **W3.4.** Click **Ask**. Type a question the text PDF answers, for example "What is the
    notice period in <your document>?", and press Enter.
    **You should see:** a step label appear almost at once, then the answer streaming in. Every
    sentence that states a fact has a citation marker, and the margin beside the answer names
    the document and page, e.g. "supplier-agreement-2024.pdf, p. 3".

15. **W3.5.** Ask a question only the scan answers.
    **You should see:** an answer cited to the scan's filename and page.

16. **W3.6.** Click one of the citations.
    **You should see:** the document opens at the cited page, with the cited passage
    highlighted.

17. **W3.7.** Click **Back to answer**.
    **You should see:** the same answer, scrolled to where you were.

18. **W3.8.** In your file manager, rename the cited PDF (add `-renamed` to its name). Back in
    Askwell, click the same citation again.
    **You should see:** not a blank viewer and not an error page. A notice: "<filename> has
    moved. Askwell last found it at <path>, but that path no longer …", with a **Where is it
    now?** control. The answer above is still there. Rename the file back afterwards.

19. **W3.9.** Scroll up the conversation.
    **You should see:** earlier answers collapsed to their question, a one-line summary and a
    source count, and each opens again when clicked. After more than 20 turns a **Load earlier
    turns** button appears at the top. There is no list of past conversations. That is a known
    gap (#199), not a defect in this step.

### E4 — it says when it doesn't know (W4)

20. **W4.1.** Ask something nothing you added covers, e.g. "What was the population of Lisbon
    in 1900?"
    **You should see:** a region headed **Not covered by your files**. It says nothing matched,
    shows what it searched, and names what would need adding. There is no answer from general
    knowledge. Below that are the offers: **Search the web**, **Ask a larger model** (greyed,
    "your own API key · not set up yet") and **Add a source**. Do **not** press **Search the
    web** yet.

21. **W4.2.** Ask a question with two parts, where your documents answer only one part.
    **You should see:** the covered part answered and cited. The other part is named as **Not
    covered:** rather than filled in.

22. **W4.3.** Add the two disagreeing PDFs. From here on, something is already added, and
    you must reach **Add a source** by a click: the rail, the Library, or a visible link. If
    the only way is to ask an unanswerable question and press the offer under the abstention,
    mark W4.3, W5.1, W5.2 and W5.4 `FAIL` with #712, then use that offer to carry on. Add them
    the same way as step 12, wait for them to index,
    then ask about the fact they disagree on.
    **You should see:** both values stated, each cited to its own document. Neither is quietly
    chosen.

23. **W4.4.** Click **Library**, find one of the two, and click **Delete**.
    **You should see:** a confirmation reading "Delete <name>? The file on your disk is
    untouched. Askwell forgets its contents and stops using it in answers. Past answers that…"
    and a **Delete it** button. Click **Delete it**. The row disappears. Tick **Show deleted**.
    **You should see:** the row back, greyed, with "Deleted on <date>". Click **Ask**. The W4.3
    answer is still in the conversation. Click the deleted document's citation.
    **You should see:** "Deleted on <date>. Askwell no longer has the contents." It is not a
    broken viewer.

24. **W4.5 [net].** Settings → Network activity.
    **You should see:** both numbers unchanged from step 10.

### E5 — it learns my material, it answers from my data (W5)

25. **W5.1.** Reach **Add a source** the same way as step 22 (while #712 is open, the only
    route is the offer under an abstention). Choose the CSV with **Choose files**.
    **You should see:** it imports. Click **Clarifications** in the rail. A question about the
    ambiguous column is waiting.

26. **W5.2.** Back on **Add a source** (reached as in step 22), in the dump box click **Choose a dump file** and pick
    the `.sql` file.
    **You should see:** before anything imports, a warning headed "This file contains commands,
    not just data." and an **Import** button. Click **Import**.
    **You should see:** the card goes **Importing…** then **Imported**.

27. **W5.3.** Click **Clarifications**. Answer each question with **Choose an answer** (or by
    typing), then press Enter.
    **You should see:** each question leaves the list once answered. When none remain, the
    screen reads **All answered**. Click away and back. The answered questions do not return.

28. **W5.4.** **Add a source** (reached as in step 22) → **Connect a database**. Enter the host, port, database, user
    and password of a Postgres **you** run (not Askwell's own, not the sandbox) and click
    **Connect**.
    **You should see:** **Connecting…** then **Connected** and **Ready**, and its tables
    listed. If the account can write, the screen says **These credentials can write** and
    offers **Give them the SQL.** That is the read-only check working. Use a read-only user.

29. **W5.5.** Ask a question the CSV or the dump answers, e.g. "How many orders have status
    shipped?"
    **You should see:** the answer, a result table, and the SQL that produced it, shown with
    the answer, not hidden.

30. **W5.6.** Ask a question that depends on the column you clarified.
    **You should see:** the answer uses your meaning, and a chip in the answer reads **You told
    me** for the memory fact it used.

31. **W5.7.** Click that chip.
    **You should see:** a panel titled **Memory fact**, showing the fact, with a way to correct
    it. Correct it to a different meaning and save. Close the panel with **Close**. Ask the same
    question again.
    **You should see:** the new meaning applied. The old one is not used.

32. **W5.8.** Click **Memory** in the rail.
    **You should see:** a page headed **Memory**. The corrected fact is listed with the new
    meaning. Underneath it, the old meaning is shown struck through, with its date.

33. **W5.9 [net].** Settings → Network activity.
    **You should see:** both numbers unchanged from step 10, even after the live connection.

### E6 — harder questions (W6)

34. **W6.1.** Ask a question that needs a document and the database, e.g. "Does the refund
    policy in <document> match the refunds recorded in the orders table?"
    **You should see:** one answer, citing both the document and the query.

35. **W6.2.** On that answer, click **How did you get this?**
    **You should see:** a panel with the same title listing each step in plain language: what
    was searched, each tool call, what it returned, and how long it took. It has a **Copy
    trace** button and a **Failures only** filter. It is not raw JSON. Press Escape to close.

### E7 — voice (W7)

Needs a microphone and speakers. Without them, mark W7 `BLOCKED` in the dry-run copy and
continue.

36. **W7.1.** On **Ask**, find **Voice input**. Press and hold **Press and hold to speak**, ask
    a document question aloud, and release.
    **You should see:** **Listening…** while you speak, **Transcribing…**, then your words as
    text, under "Transcript — edit before confirming", before any answer. Confirm it.
    **You should see:** **Answering…**, the answer on screen with citations, and it spoken
    aloud a sentence at a time.

37. **W7.2.** Ask again by voice. While it is speaking, press **Stop**.
    **You should see:** speech stops at once. The turn reads "Stopped. The answer above is
    partial.", not an error. Ask one more question by typing. It answers normally.

38. **W7.3 [net].** Settings → Network activity: unchanged.

### E8 — it can look outside (W8)

Needs `ASKWELL_WEB_SEARCH_PROVIDER` set in `.env` to a real provider and the API recreated.
If it is blank, mark W8.3–W8.5 `BLOCKED` in the dry-run copy and continue to E9.

39. **W8.1 [net].** Write down the two Network activity numbers.

40. **W8.2.** Ask a new uncovered question.
    **You should see:** **Not covered by your files** first, then the **Search the web** offer
    underneath it. Nothing has been searched yet.

41. **W8.3.** Click **Search the web** once.
    **You should see:** a separate region headed **Web results** marked "From the web — not
    your files". Each result has a title, an address, and "Retrieved <date>". The margin beside
    the answer, where document citations go, has **no** web entries. The turn is marked "This
    turn used the web".

42. **W8.4 [net].** Network activity.
    **You should see:** `permitted` has gone up. That is the search you accepted. Nothing else
    has changed.

43. **W8.5.** Ask a second uncovered question.
    **You should see:** it starts local again: **Not covered by your files** and a fresh
    **Search the web** offer. It does not search on its own.

44. **W8.6 [net].** Network activity: unchanged since step 42.

### E9 — someone else can install it (W9)

45. **W9.1.** Click **Settings** and scroll through every section: Model and speed, Online AI,
    Folders Askwell may read, Privacy and security, Storage, Your data, About.
    **You should see:** each one with real content. No lorem ipsum, no "TODO". The Online AI
    switch is inert on purpose (step 46), and pressing it explains why. **Today this step
    fails:** under **Storage**, the **Export and prune** button is greyed out and the text above
    it reads "Not built yet". That is a dead control, so mark W9.1 `FAIL` with #615. It is
    already tracked; do not file it again.

46. **W9.2.** Under **Online AI**, click **Use online AI**.
    **You should see:** it stays **Off. Not available yet.**, and a paragraph explains it is
    not available. Network activity is unchanged.

47. **W9.3.** Under **About**.
    **You should see:** **Version** reads what `cat VERSION` prints. **Licence** reads GPLv3 (GPL-3.0-or-later), with **Read
    the licence in full**. **Notices** has "Third-party notices and licences, including the
    bundled model weights". Under **Report a problem**, the support boundary text is shown
    before the issue address. **Security problem** has "How to report a security problem".
    Open each of the three. Each one expands on the page, with no new tab and no network.
    **Update checking** is off. Do not press **Check now**: this section is offline, and that
    button makes the one request update checking ever makes. Under **Report a problem**,
    **Crash reports** reads "None. Askwell has not crashed on this machine, or its reports were
    removed." Part E started from `podman compose down -v`, which removed the state volume, so
    any report listed here was written during this dry run: mark W9.3 `FAIL` and file it.

48. **W9.4.** Settings has no backup control (#615). Take a backup in the terminal as
    `docs/restore-release-test.md` §1.3 describes.
    **You should see:** the backup reaches `done` and names a file that exists.

49. **W9.5.** Restoring on a second machine is gate G5's own procedure,
    `docs/restore-release-test.md` §3. In a dry run on one machine, mark it `BLOCKED` with
    "no second machine" (#590, #592). That is exactly what the checklist's rule 1 expects.

50. **W9.6.** Settings → **Your data** → **Export everything**.
    **You should see:** **Exporting…**, then a completed export. Open the files it wrote.
    **You should see:** open formats you can read in a text editor or spreadsheet, holding the
    sources list, memory facts, conversations and the log with its hash values.

51. **W9.7.** In **Your data**, click **Verify the log**.
    **You should see:** **Checking…**, then two results: "Decisions — chain intact" and
    "Interactions — chain intact". Neither reads "chain broken".

52. **W9.8.** In the terminal: `podman compose exec api askwell-verify`. In a dry run the
    development checkout *is* the Compose project. On a real release run the command is run
    from the install directory the step names, never from a checkout.
    **You should see:** both chains verify, in agreement with step 51.

53. **W9.9 [net].** Network activity.
    **You should see:** `permitted` is the step 10 baseline plus only the web search from step
    41. If `refused` has moved, each entry is listed under the count. Every one must be
    explainable.

54. **Score the dry run.** Open `/tmp/walkthrough-dryrun.md`.
    **You should see:** every step marked. Expected `BLOCKED`s in a dry run: W0 (no artefact,
    #559), W9.5 (no second machine), and W7 and W8.3–W8.5 if the hardware or provider is
    missing. Any `FAIL` is either a product defect (file it, `AGENTS.md` §8) or a walkthrough
    step that does not match the product (fix the step in `docs/release-walkthrough.md`).

## Part F — a trial release entry ends `held`

The checklist has to be able to say no. Fill one entry against today's known state and check
that it does.

1. Copy the format block from `docs/release-log.md` into `/tmp/trial-release-entry.md`. Fill
   in the `Result` column from what is known today:

   | Gate | Today | Why |
   | ---- | ----- | --- |
   | G3 eval | `BLOCKED` | No category has a recorded score (#625) |
   | G7 performance | `FAIL` | The answer-latency budget was measured missed (`docs/success-metrics.md`) |
   | G8 notices | `FAIL` | #619 |
   | G9 support boundary | `FAIL` | Run `gh api repos/Rumeasiyan/askwell/private-vulnerability-reporting`. Anything other than `{"enabled":true}` fails (#689) |
   | G10 artefacts | `BLOCKED` | No installable bundle (#559); no clean macOS or Windows machine (#590, #592); no installer migrates the database (#698) |
   | G11 walkthrough | `FAIL` | W4.3, W5.1, W5.2, W5.4: no click reaches Add a source once something is added (#712). W9.1: Storage → Export and prune is a dead control (#615) |
   | G12 open defects | `FAIL` | #699 (update feed advertises unreleased versions) carries `constraint:local-first`, so it cannot be `ACCEPTED`; #698 is an open `bug` |

2. Apply the checklist's rules to that entry. ☐
   **You should see:** the decision can only be `held`. G3 is `BLOCKED`, and the checklist's
   rule 1 lets no `BLOCKED` gate through. G3's abstention and strict rows cannot be `ACCEPTED`.
   G7 could be `ACCEPTED`, but only with an issue number, a reason, and a follow-up. Without all
   three it stays `FAIL`. The **Held because** line lists the gates and their issues.

3. Delete the scratch files: `rm /tmp/trial-release-entry.md /tmp/walkthrough-dryrun.md
   /tmp/release-checklist.backup.md`. ☐ **Do not** add the trial entry to
   `docs/release-log.md`. That log records real release runs only.

---

## Known gaps

These are deliberately not built, or are tracked elsewhere. Do not report them as defects in
this ticket.

- **The checklist has never been executed for a release.** The ticket separates writing it
  from running it. The first real run is expected to be `held` (Part F).
- **The walkthrough is manual, and automating it is out of scope.** The ticket says so: the
  point is that a person uses the product.
- **No installer applies database migrations** (#698). Part E migrates by hand
  (`scripts/dev.sh db upgrade head`); a real cold install would come up with no schema.
- **No installable artefact exists yet** (#559). W0, and the "cold install" half of G10, can
  only be walked once one does. The dry run in Part E starts from `podman compose down -v`.
- **Only Linux has been walked.** There is no clean macOS or Windows hardware (#590, #592). The
  checklist requires the release entry to name every platform not covered.
- **Backup and restore have no Settings control, and log export-and-prune is a disabled
  placeholder** (#615). W9.4–W9.5 point at `docs/restore-release-test.md` until one exists, and
  W9.1 fails on the placeholder until it is built.
- **The empty Library says dumps and live connections are "arriving later"** (#722). Both are
  built. This is stale copy on a screen the walkthrough does not visit, so step 11 notes it
  and it holds no gate.
- **Once a source exists, no click reaches Add a source** (#712). W4.3, W5.1, W5.2 and W5.4
  are `FAIL` until it is fixed. Part E carries on through the offer under an abstention.
- **There is no list of past conversations** (#199). A reload starts a new conversation. W3.9
  checks in-conversation paging only.
- **Online AI (M8) is not built.** Its walkthrough steps are appended when M8 lands. **Ask a
  larger model** is shown greyed out on purpose.
- **Voice (W7) and web search (W8) need hardware and a configured provider.** A machine without
  them marks those steps `BLOCKED`, which holds a real release. It does not mean skip.
- **The guard tests check the documents, not the product.** `test_release_checklist.py` fails
  if the checklist drifts from the suites, screens or paths. It cannot tell whether a
  walkthrough step matches what a screen shows. Part E is what checks that.
