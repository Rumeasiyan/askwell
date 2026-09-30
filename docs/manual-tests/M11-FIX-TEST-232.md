# Manual test — M11-FIX-TEST-232, `grounded_qa.v1` runs to the end on a fresh database

**Ticket:** `M11-FIX-TEST-232`, issue #859 (option 1).

`grounded_qa.v1` is one of Askwell's measurement suites. It indexes a small set of test files
(the *fixture corpus*, `eval/fixtures/corpus/`, nine files about a made-up retailer called
Meridian Loom), then asks forty questions and scores the answers.

Before this ticket, the suite never finished on a fresh database. Indexing the corpus makes
Askwell raise one clarification: two of the files disagree about when Meridian Loom's stores
close. The first question that read from the corpus then waited for someone to answer that
clarification. The suite never answers, so it waited forever. Every number recorded for this
suite so far was taken on a database where someone had already dealt with it.

Now:

1. **After indexing, the suite skips every clarification still waiting on the corpus.** It uses
   the same skip a person gets by clicking **Skip** in **Clarifications**, so each skip leaves the
   same audit record.
2. **Only the corpus's own clarifications are skipped.** Questions waiting on any other source are
   left alone, so running the suite on a database you use does not empty your review queue.
3. **The result says how many were skipped.** The summary prints *clarifications skipped after
   seeding: N*, and the result file carries `"clarifications_skipped": N`.
4. **Running it again on the same database works.** The corpus is already indexed, every file
   comes back as a duplicate, nothing is waiting, and the count is `0`.

The suite itself did not change: same forty questions, same scoring, and no abstention test was
touched (C5).

**Version under test:** `0.9.21`. Run `cat VERSION` and update this line if the version has moved
on.

**Time:** about 60 minutes with a graphics card, most of it waiting for the suite (it took about
32 minutes when this ticket landed). On CPU only, the suite takes several hours. Part E runs it a
second time and is optional.

**Who can run it:** anyone with a browser and a terminal on the build host. Running a measurement
suite is not something an Askwell user does, so those steps happen in the terminal and are
labelled **Stand-in**. Everything Askwell shows about the result is checked by clicking, starting
from Askwell's front page.

**What changed on disk.**

| Piece | File |
| ----- | ---- |
| The suite skips the corpus's waiting clarifications after indexing, and counts them | `skip_pending_clarifications`, `run_grounded_suite` in `eval/grounded.py` |
| Indexing reports which sources hold the corpus, including one indexed earlier | `seed_corpus` in `eval/grounded.py` |
| The count in the result file and the printed summary | `clarifications_skipped` in `SuiteRunReport.to_dict` and `format_summary`, `eval/results.py` |
| The skip itself (unchanged, reused) | `skip_clarification` in `api/src/askwell/review.py` |
| Tests | five in `eval/tests/test_grounded.py`, two in `eval/tests/test_results.py` |

The reasoning, including why the skip is limited to the corpus's own sources when the ticket said
"every pending clarification", is in `docs/decisions.md`, 2026-09-30, "`M11-FIX-TEST-232`".

---

## Read this first

**Nothing leaves this machine during this test.** No online AI, no web search. The suite talks to
the model over a local socket and to Askwell's database over the stack's internal network.

**Do not set a passphrase in the welcome steps.** Part A skips setup on purpose. A passphrase
lock stops the suite from reading the database, and that is a different problem (#576).

**Indexing is paused while the suite indexes.** Part B stops Askwell's background indexer while
the suite runs, and starts it again afterwards. The suite indexes the corpus itself, one file at
a time. If the background indexer picks up one of those files first, the suite stops with
*"fixture … failed to ingest: unclaimable"*. That would be a clash between two indexers, not
this ticket's defect. While the indexer is stopped, Askwell may say that indexing is not running.
That is expected.

**The corpus lives at a path only the suite can see.** The suite runs in its own container and
indexes `/app/eval/fixtures/corpus`. Askwell's own screens list that folder and its files, but
Askwell cannot open the files themselves. Opening a cited page from an answer may therefore fail
in Part D. That is not this ticket's defect.

---

## Before you start

> **Warning: the cold start below deletes everything this Askwell stack holds.** That means
> sources, memory, conversations, the audit log, settings and any stored provider key. Your
> original files are not touched. On the shared development machine, check first that nobody
> needs what the stack holds, and that no eval or build queue is using the stack. If you are
> unsure, open **Settings → Your data → Export everything** first.

### 1. Start Askwell from nothing (Stand-in)

```
cd ~/external/quantum-plus/askwell
podman compose down -v
scripts/dev.sh build-api
scripts/dev.sh web-build
podman compose up -d
scripts/dev.sh db upgrade head
```

**You should see:** the volumes removed, both builds finish with no red error text, the containers
start, and the migration end without an error. This is the *freshly migrated database* the ticket
is about. Nothing has been indexed into it.

In a **second** terminal, start the model on the host and leave it running:

```
cd ~/external/quantum-plus/askwell
scripts/dev.sh inference
```

**You should see:** the supervisor report the model and the embedding model ready. The suite
needs both.

### 2. Note the result files that already exist (Stand-in)

```
ls eval/results/ | grep grounded_qa
```

**You should see:** a list of earlier result files, or nothing. Write down the newest name so you
can tell your run's file apart in Part B.

---

## Part A — cold start: Askwell is empty

1. Open a **private or fresh-profile** browser window. Type `http://127.0.0.1:8000` in the
   address bar and press **Enter**. ☐

   **You should see:** the welcome screen, **Welcome to Askwell**, with a **Get started** button
   and a **Skip setup** button at the top right. If you see the **Ask** screen instead, the stack
   was not cleared. Go back to *Before you start*, step 1.

2. Click **Skip setup**. ☐

   **You should see:** the **Ask** screen, with the left column listing **Ask**, **Library**,
   **Clarifications**, **Memory** and **Settings**. **Clarifications** has no number next to it.

3. Click **Library** in the left column. ☐

   **You should see:** no sources. The page explains that *Nothing has been added yet, so there is
   nothing to ask about*, and lists the ways to add one.

4. Click **Clarifications** in the left column. ☐

   **You should see:** *Nothing to clarify. Askwell asks when it finds something it can't work
   out — an unlabelled column, a date format, two documents that disagree.*

Leave this browser window open.

## Part B — the suite runs to the end on the fresh database

5. **Stand-in.** Stop the background indexer (see *Read this first*): ☐

   ```
   cd ~/external/quantum-plus/askwell
   podman compose stop worker
   ```

   **You should see:** the worker container stop.

6. **Stand-in, long.** Run the suite: ☐

   ```
   scripts/dev.sh eval --suite grounded_qa.v1
   ```

   **You should see:**
   - the command run for a while with no output while it indexes and asks. Do nothing: this step
     must need no manual action. That is the ticket's main check;
   - the command **finish on its own** and print a summary starting:

     ```
     suite: grounded_qa.v1 (grounded-document-qa)
     model: <model file name>  profile: balanced
     runs per task: 3
     clarifications skipped after seeding: 1
     pass_bar: 0.85  mean: …  worst-of-3: …
     ```

     then one line per question, and finally `written to /app/eval/results/grounded_qa.v1-<date
     and time>.json`.

   Write down the mean, the worst-of-3 and the file name. When this ticket landed, a fresh
   database scored **mean 0.82, worst 0.75** with Qwen3.5-4B on a graphics card. Your numbers can
   differ. This ticket makes the run finish; it does not change the score.

   **If it is still running after an hour on a graphics card** (or far longer than usual on CPU),
   it is waiting for an answer. That is exactly the defect this ticket fixes. Record it, press
   **Ctrl+C**, and still do step 7 before you stop.

   **If the count is not `1`,** record the number you saw. The corpus's two store-hours files are
   what raise the one clarification. A different count means the corpus or the clarification
   rules changed, which is worth reporting but is not necessarily this ticket's defect. `0` on a
   fresh database is suspicious: go on to step 11 to see whether a question was raised at all.

   If any per-question line ends with `errors: [...]`, copy it into your notes.

7. **Stand-in.** Start the background indexer again: ☐

   ```
   podman compose start worker
   ```

   **You should see:** the worker container start.

8. **Stand-in.** The result file records the count: ☐

   ```
   ls eval/results/ | grep grounded_qa
   python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(d['suite'], d['clarifications_skipped'], d['category_mean'], d['category_worst'])" eval/results/<the new file name>
   ```

   **You should see:** one file newer than the one you noted in *Before you start*, step 2. Then a
   line like `grounded_qa.v1 1 0.825 0.75`: the suite name, the number of clarifications skipped,
   the mean and the worst case. If the second value is missing and Python stops with
   `KeyError: 'clarifications_skipped'`, the file does not record the count. That is this
   ticket's defect.

## Part C — what Askwell shows after the run

Go back to the browser window from Part A.

9. Click **Library** in the left column. Reload the page if it still shows no sources. ☐

   **You should see:** one source named **corpus**, with nine files: `conflict_2025.pdf`,
   `conflict_2026.pdf`, `figures.xlsx`, `handbook_a.pdf`, `handbook_b.pdf`, `notice_scan.pdf`,
   `spec.docx`, `store_hours_2025.pdf` and `store_hours_2026.pdf`. Each says **ready**. This is
   what the suite indexed. It indexed through Askwell's normal add-and-index path, which is why it
   appears here like any source you add yourself.

   If the source is shown as needing attention because its files cannot be found, note it and
   continue. See *Read this first*: the files are at a path only the suite's container can see.

10. Click **Clarifications** in the left column. ☐

    **You should see:** *Nothing to clarify…*, the same as in step 4, and no number next to
    **Clarifications** in the left column. The store-hours question the corpus raised was skipped
    by the suite, so nothing is waiting.

    **You should not see:** a group headed **corpus** with a question about when Meridian Loom's
    stores close. If it is there, the suite did not skip it. Record the question text exactly.

11. **Stand-in.** The question was raised, and then skipped through the same path a person's skip
    takes: ☐

    ```
    scripts/dev.sh psql -c "SELECT c.subject, c.status, s.name FROM clarifications c JOIN sources s ON s.id = c.source_id"
    scripts/dev.sh psql -c "SELECT kind, payload->>'subject' AS subject FROM audit_decisions WHERE kind LIKE 'clarification%' ORDER BY occurred_at"
    ```

    **You should see:**
    - one row: `meridian loom retail stores close | skipped | corpus`. There are no `pending`
      rows and no `answered` rows;
    - in the second list, a `clarification_raised` row with that subject, and after it one
      `clarification_skipped` row with the same subject. There may also be
      `clarification_dropped` rows for words like `PM` and `VPN`. Those are candidates Askwell
      decided not to ask about, and they are not this ticket's.

    The number of `clarification_skipped` rows must equal the count from step 6.

12. Click **Memory** in the left column. ☐

    **You should see:** nothing labelled **You told me**. A skip is not an answer, so the suite
    adds no remembered fact. Rows labelled **I guessed** may exist for the corpus. They come from
    indexing and are not this ticket's.

13. Click **Settings** in the left column. Scroll to **Your data** and click **Verify the log**. ☐

    **You should see:** **Decisions — chain intact** and **Interactions — chain intact**, each
    with a number of records checked. The suite's skip wrote into the audit log the same way a
    person's skip does, and the log is still whole.

## Part D — asking about the corpus no longer waits (informative)

This part shows, in the product, the pause the suite used to get stuck on. **It does not pass or
fail the ticket.** The model's wording varies, and a wrong answer here is a quality question for
other tickets.

14. Click **Ask** in the left column. Type **How many paid holiday days do Meridian Loom employees
    accrue per calendar year?** and press **Enter**. Wait for the answer. ☐

    **You should see:** an answer, not a question back to you. It should say **eleven**, citing
    **handbook_a.pdf**. Before this ticket, on a fresh database, a question like this one would
    stop and ask you about the store-closing clarification first, because it was still waiting on
    the corpus. That is the same wait the suite could not get past.

    If Askwell instead says it cannot find this in your material, note it: that is an abstention,
    not a pause. If it asks you a question instead of answering, record the question. That is this
    ticket's defect only if the question is about the store-closing clarification from step 11.

## Part E — optional: run it again on the same database

The ticket's second edge case: a run on a database that already has the corpus.

15. **Stand-in, long.** Run the suite a second time. The worker can stay running, because every
    file is already indexed and there is nothing for the background indexer to pick up: ☐

    ```
    scripts/dev.sh eval --suite grounded_qa.v1
    ```

    **You should see:** the run finish on its own again. It starts answering sooner, because no
    file is indexed again. The summary says **clarifications skipped after seeding: 0**. Record
    the mean and worst-of-3.

16. Click **Library**. ☐

    **You should see:** still one source, **corpus**, with the same nine files. It is not added a
    second time.

17. **Stand-in.** Nothing was skipped a second time: ☐

    ```
    scripts/dev.sh psql -tAc "SELECT count(*) FROM audit_decisions WHERE kind = 'clarification_skipped'"
    ```

    **You should see:** `1`, the same as after Part B.

## Part F — the tests, and C5 unchanged (Stand-in)

18. Run the eval harness's own tests: ☐

    ```
    scripts/dev.sh run pytest /app/eval/tests -c /app/eval/pyproject.toml
    ```

    **You should see:** no `FAILED` lines. There are exactly five `ERROR` lines, all in
    `eval/tests/test_runner.py`, each a `ValidationError` for missing sandbox settings. Those errors
    are older than this ticket and are filed as #883. Any other `ERROR`, or any `FAILED`, is a
    defect.

19. Run only this ticket's tests, which include the edge case of a corpus that raises no
    clarification: ☐

    ```
    scripts/dev.sh run pytest /app/eval/tests/test_grounded.py /app/eval/tests/test_results.py -c /app/eval/pyproject.toml -k "clarification or seed_corpus or corpus_sources or skip"
    ```

    **You should see:** `7 passed, 18 deselected`. The seven are, in `test_grounded.py`:
    - `test_every_pending_clarification_on_the_corpus_is_skipped`
    - `test_a_corpus_that_raises_no_clarification_skips_nothing`
    - `test_no_corpus_sources_means_no_query`
    - `test_seed_corpus_names_the_sources_holding_the_corpus`
    - `test_the_grounded_run_skips_after_seeding_and_records_the_count`

    and, in `test_results.py`, `test_skipped_clarifications_are_in_the_file_and_the_summary` and
    `test_a_report_that_skipped_no_clarifications_keeps_its_old_shape`. A higher `passed` count is
    fine if a later ticket added matching tests; any `failed` is not.

20. No abstention test, suite file or prompt changed with this ticket (C5): ☐

    ```
    git diff aefd6960 -- eval/suites/ api/src/askwell/agent/prompts/
    ```

    **You should see:** no output. `aefd6960` is the last commit before this ticket.

---

## Result

| Part | Result | Notes |
| ---- | ------ | ----- |
| A — cold start, empty | | |
| B — suite finishes with no manual step; count printed and in the file (6 is the main check) | | mean / worst / file: |
| C — nothing waiting; one raised, one skipped; log intact | | |
| D — asking does not wait (informative) | | |
| E — re-run: count 0, no duplicate source (optional) | | |
| F — tests; C5 unchanged | | |

Tester, date, graphics card or CPU, `cat VERSION`:

---

## Known gaps

These are deliberately not built, or belong to another ticket. Do not report them as defects of
this one.

- **The other suites that index the same corpus still hang on a fresh database.**
  `abstention.v1`, `conflicting_sources.v1`, `tool_selection` and `web_escalation` do the same
  indexing without the skip. That is #881. Do not run them on the fresh database from this test
  and expect them to finish.
- **Only the corpus's own clarifications are skipped.** On a development database where *other*
  sources have waiting clarifications and retrieval reaches them, a question can still pause. A
  fresh database is the supported case. This is recorded in `docs/decisions.md`.
- **The suite measures grounding with no memory at all.** It skips rather than answers, so
  nothing in the result depends on remembered answers. Answered clarifications are measured by
  `memory_apply.v1`, separately.
- **There is no command that creates the fresh database for you.** This test uses a cold start of
  the whole stack. When the ticket landed, the run used a separate database created by hand
  (`askwell_eval232`). Either works; neither is scripted.
- **The background indexer has to be stopped during a first run on the stack's own database**
  (Part B). The suite indexes the corpus itself and does not coordinate with the indexer.
- **The corpus's files cannot be opened from Askwell's screens.** They live inside the suite's
  container (see *Read this first*).
- **Result files from before `0.9.21` have no `clarifications_skipped` key,** and neither does any
  other suite's result file. That is deliberate, so no other result file changes shape.
- **Five eval-harness tests error before they start** (`eval/tests/test_runner.py`), #883.
- **The suite's score is below its pass bar of 0.85** on a fresh database (0.82 when this ticket
  landed). This ticket makes the number trustworthy, not higher.
