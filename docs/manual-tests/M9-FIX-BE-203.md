# Manual test — M9-FIX-BE-203, re-indexing works, including for cited documents

**Ticket:** `M9-FIX-BE-203`, issues #719 and #720. It fixes two separate defects.

1. **A cited document could not be re-indexed (#719).** When a file had been cited in any
   answer, **Re-index** left it at **Needs attention**. The detail read
   `violates foreign key constraint "fk_citations_chunk_id_chunks"`, and the old text stayed
   in the index. Askwell refused to throw away a passage an answer still points at, which is
   right, and then gave up, which is not. Now a passage nothing cites is thrown away as before.
   A passage an answer cites is kept with its exact text, so the old answer still has what it
   quoted, but it is taken out of search. Askwell can no longer find it or answer from it.
2. **Re-index could leave a file queued forever (#720).** A file with no entry in Askwell's
   work queue was marked **Queued** by a re-index, and nothing ever picked it up. Now the
   re-index puts it in the queue.

**Version under test:** `0.7.51`. Run `cat VERSION` and update this line if the version has
moved on.

**Time:** about 45 minutes. Most of it is waiting for the model to answer on CPU.

**Who can run it:** anyone with a browser and a terminal. Every Askwell screen is reached by
clicking, starting from the address Askwell opens at. The terminal starts Askwell, changes the
file the way an editor would, and runs checks that cannot be done by looking. The checks are
labelled **Stand-in**.

**What is being checked.**

- `api/src/askwell/chunk.py`, `run`. It deletes only the passages nothing cites. It retires
  the cited ones: they keep their text, lose both ways of being searched, and get a
  `superseded_at` date.
- `api/src/askwell/db/models.py`, `Chunk.superseded_at`, and the new migration
  `20260928_e1c5a8f3b207_chunk_superseded_at.py`. Includes a check constraint that refuses a
  retired passage that can still be searched.
- Every reader that means "the file as it is now" skips retired passages: `retrieve.py`,
  `ask.py`, `embed.py`, `suggestions.py`, `clarify.py`, `reapply.py`, `restore.py` and
  `backup.py`.
- `api/src/askwell/ingest.py`, `reindex_source`. It now queues a file that had no queue entry.

**The one rule of this test.** Never type an address into the browser bar except the first
one in step 1. Reach every screen by clicking.

---

## Before you start

> **Warning: the cold start below deletes everything this Askwell stack holds.** That means
> sources, memory, conversations, the audit log and settings. Your original files are not
> touched. On the shared development machine, check that nobody needs what the stack holds
> now. If you are unsure, use **Settings → Your data → Export everything** first.

### A. A folder to add

Askwell can only read folders inside `ASKWELL_ROOTS_MOUNT` in `.env`. Check it:

```
cd ~/external/quantum-plus/askwell
grep ASKWELL_ROOTS_MOUNT .env
```

If it is empty, or does not cover `/tmp`, set `ASKWELL_ROOTS_MOUNT=/tmp`. Then make one
folder from the fixture corpus. `store_hours.pdf` starts as the 2026 edition. It is the file
you will "edit" later.

```
rm -rf /tmp/askwell-test-203
mkdir -p /tmp/askwell-test-203/one/shop
cp eval/fixtures/corpus/store_hours_2026.pdf /tmp/askwell-test-203/one/shop/store_hours.pdf
cp eval/fixtures/corpus/handbook_b.pdf /tmp/askwell-test-203/one/shop/
find /tmp/askwell-test-203 -type f
```

**You should see:** two lines, ending `shop/store_hours.pdf` and `shop/handbook_b.pdf`.

What is in them, so you can check the answers:

| File | Page | Says |
| ---- | ---- | ---- |
| `store_hours.pdf`, before the edit | 1 | *"Meridian Loom retail stores close at **9 PM** on weekdays."* That is the whole file |
| `store_hours.pdf`, after the edit | 1 | *"Meridian Loom retail stores close at **8 PM** on weekdays."* That is the whole file |
| `handbook_b.pdf`, never edited | 4 | Production database credentials are rotated every **forty-five days** |

### B. Start Askwell from nothing

```
podman compose down -v
scripts/dev.sh web-build
scripts/dev.sh build-api
podman compose up -d
scripts/dev.sh db upgrade head
```

**You should see:** the volumes removed, both builds finish with no red error text, the
containers start, and the migration finish with no error. Do not skip the API build. This fix
is in the API, and without the build you are testing the old version.

**Stand-in** — confirm the new migration ran:

```
scripts/dev.sh psql -c "SELECT version_num FROM alembic_version;"
```

**You should see:** `e1c5a8f3b207`, or a later revision if other work has landed since.

In a **second** terminal, start the model on the host and leave it running:

```
scripts/dev.sh inference
```

**You should see:** the supervisor report that the model and the embedding model are ready.

---

## Part A — first run and adding the folder

1. Open a **private or fresh-profile** browser window at full width, so no earlier session
   carries over. Go to `http://127.0.0.1:8000`. ☐

   **You should see:** **Welcome to Askwell**, a **Skip setup** button top right, and a
   **Get started** button. Down the left, a column listing **Ask, Library, Clarifications,
   Memory, Settings**. If you see the Ask screen instead, the stack was not cleared. Go back
   to *Before you start*, B.

2. Click **Get started**. On the passphrase step, click **Not now**, then **Continue**. ☐

   **You should see:** step 3, about the model, with an add box showing **Choose files** and
   **Choose a folder**.

   Leave the passphrase off for this test. Part D reads the kept passage straight from the
   database, and with a passphrase it is stored encrypted.

3. Wait until the model section says the model is ready, then click **Continue** without
   adding anything. ☐

   **You should see:** step 4, beginning *"Ready. Add something to ask about"*, which tells
   you to open **Library** in the rail and choose **Add a source**.

4. Click **Library** in the left column, then **Add a source** in the panel. ☐

   **You should see:** a screen headed **Add a source**, with a **Files** panel holding
   **Choose files** and **Choose a folder**.

5. Click **Choose a folder**. Open `/tmp/askwell-test-203/one`, select `shop` and confirm.
   If the browser asks whether to upload the files, confirm. Nothing leaves this machine.
   When asked *"Which folder is “shop” in?"*, type `/tmp/askwell-test-203/one` and click
   **Add them**. If a note offers **Nominate**, click it, then **Add them** again. ☐

   **You should see:** a note headed **Queued**, and no red **Not added** note.

6. Click **Library** in the left column. ☐

   **You should see:** one row, **shop**. Wait until it reads **Ready** and the line under it
   reads **All 2 indexed.** On a CPU-only machine this can take a few minutes. The row also
   has two small buttons, **Re-index** and **Delete**.

---

## Part B — two answers that cite the files

7. Click **Ask** in the left column. Type exactly this and press **Enter**: ☐

   ```
   What time do Meridian Loom retail stores close on weekdays?
   ```

   **You should see:** progress lines while it searches and reads, then an answer saying the
   stores close at **9 PM** on weekdays. On CPU, allow a minute or two. In the right-hand
   margin, a source card naming **store_hours.pdf**, **p. 1**, whose quoted passage reads
   *"Meridian Loom retail stores close at 9 PM on weekdays."*

   If the answer says Askwell could not find this in your files, the file is not indexed yet.
   Go back to step 6 and wait for **Ready**.

8. Type exactly this and press **Enter**: ☐

   ```
   How often are Meridian Loom production database credentials rotated?
   ```

   **You should see:** an answer saying **every forty-five days**, with a source card naming
   **handbook_b.pdf**, **p. 4**. The first answer, from step 7, collapses above it.

   Both files have now been cited. Before this fix, both would fail to re-index.

---

## Part C — edit the file and re-index

9. **Edit the file.** In the terminal, save the 2025 edition over `store_hours.pdf`. A real
   user would open the file, change "9 PM" to "8 PM" and save it. This has the same effect: ☐

   ```
   cp eval/fixtures/corpus/store_hours_2025.pdf /tmp/askwell-test-203/one/shop/store_hours.pdf
   pdftotext /tmp/askwell-test-203/one/shop/store_hours.pdf - | head -1
   ```

   **You should see:** *"Meridian Loom retail stores close at 8 PM on weekdays."* If
   `pdftotext` is not installed, skip the second line.

   `handbook_b.pdf` is left as it is. Askwell does not notice the edit by itself. That is
   what **Re-index** is for.

10. Click **Library** in the left column. On the **shop** row, click **Re-index**. ☐

    **You should see:** the button replaced by *"Re-index shop? Askwell reads every file in it
    again from scratch — extracting, chunking and embedding. On a large source this can take
    hours, and answers about it may be thin until it finishes."* with **Re-index it** and
    **Not now**.

11. Click **Re-index it**. ☐

    **You should see:** *"Re-indexing 2 documents."* The row's status changes to **Queued** or
    **Indexing**, and the line under it names what is being read.

12. Wait, without clicking anything, until the row settles. On CPU, allow a few minutes. ☐

    **You should see:** **Ready**, **All 2 indexed.**, and **no Show detail** button.

    This is the ticket's first acceptance criterion. **Failure looks like this:** the row
    reads **Needs attention** and has a **Show detail (…)** button. Click it. If the detail
    mentions `fk_citations_chunk_id_chunks` or `ForeignKeyViolation`, the fix is missing or
    the API image was not rebuilt. Write down the exact text.

    If the row stays **Queued** for more than ten minutes with the line *"… queued."* and
    never moves to **Indexing**, that is #720's defect. Record it.

---

## Part D — the old answers still open, and the new text is what Askwell answers from

13. Click **Ask** in the left column. ☐

    **You should see:** the same conversation you left, with both questions still there.
    Navigating around the left column does not start a new conversation.

14. Click the collapsed first turn, the store-hours question, to expand it. ☐

    **You should see:** the full answer from step 7, still saying **9 PM**, and its margin
    card still naming **store_hours.pdf**, **p. 1**, with the passage *"… close at 9 PM on
    weekdays."* No error. The answer records what the file said when the question was asked.
    It is not silently rewritten to say 8 PM. That is C4: a past citation is never repointed
    at different text.

15. Click **How did you get this?** under that first answer. ☐

    **You should see:** a panel headed **How did you get this?** that loads its steps and
    shows the cited passage from **store_hours.pdf**. It does not say the trace could not be
    loaded. Click **Close**.

16. Click the **store_hours.pdf** source card in that first answer. ☐

    **You should see:** the document viewer, headed **store_hours.pdf**, open at page 1. The
    page shows the file **as it is now**: *"… close at 8 PM on weekdays."* Above the page, a
    note reads *"The exact passage could not be pinpointed on this page — showing the cited
    page instead."*

    That note is the current, known behaviour for a passage the edit removed. The ticket's
    edge case asks for the citation to say the passage was **replaced**, and on what date.
    That wording is not built yet: see *Known gaps*, #778. What this ticket must guarantee is
    that the viewer **opens**: no error page, no blank screen, no "document not found". If
    you get any of those, that is a failure of this ticket.

17. Click **Ask** in the left column. Expand the second turn, the credentials question, and
    click its **handbook_b.pdf** source card. ☐

    **You should see:** the viewer on **handbook_b.pdf**, page 4, with the forty-five-days
    passage highlighted, and **no** "could not be pinpointed" note. That file did not change,
    so its old citation lands on exactly the same text.

18. Click **Ask** in the left column. Type exactly this and press **Enter**: ☐

    ```
    What time do Meridian Loom retail stores close on weekdays?
    ```

    **You should see:** an answer saying **8 PM**, citing **store_hours.pdf**, **p. 1**, with
    the passage *"… close at 8 PM on weekdays."*

    **9 PM must not appear anywhere in this answer or its margin**, and there must be no
    **Conflicting sources** heading. Askwell keeps the old 9 PM passage only so the old answer
    can show it. It must never find that passage in a search or answer from it. If 9 PM shows
    up here, that is a C4 failure of this ticket. Write down the answer exactly.

19. **Stand-in** — confirm what the database holds after the re-index: ☐

    ```
    scripts/dev.sh psql -c "SELECT d.filename, count(*) FILTER (WHERE c.superseded_at IS NULL) AS live, count(*) FILTER (WHERE c.superseded_at IS NOT NULL) AS retired, count(*) FILTER (WHERE c.superseded_at IS NOT NULL AND (c.embedding IS NOT NULL OR c.content_tsv IS NOT NULL)) AS retired_but_searchable FROM chunks c JOIN documents d ON d.id = c.document_id GROUP BY d.filename ORDER BY d.filename;"
    scripts/dev.sh psql -c "SELECT d.filename, c.superseded_at IS NOT NULL AS retired, left(c.content, 60) AS passage FROM citations ci JOIN chunks c ON c.id = ci.chunk_id JOIN documents d ON d.id = c.document_id ORDER BY d.filename, retired DESC;"
    ```

    **You should see:**

    - First query: a row each for `handbook_b.pdf` and `store_hours.pdf`. Each has at least
      one `live` passage. `retired` is at least **1** for each, one for every passage the
      step 7 and 8 answers cited. **`retired_but_searchable` is 0 on both rows.**
    - Second query: one line per citation. The step 7 and step 8 citations are `retired = t`,
      and their passages still read *"Meridian Loom retail stores close at 9 PM…"* and the
      forty-five-days text. The step 18 citation is `retired = f` and reads *"… 8 PM…"*. No
      passage is empty.

---

## Part E — a file with no queue entry is not left queued (#720)

The state behind #720 cannot be produced by clicking. It has been seen after a restore, and
that cause is #779. So this part creates it by hand, then walks the re-index by clicking.

20. **Stand-in** — remove `handbook_b.pdf`'s entry from the work queue: ☐

    ```
    scripts/dev.sh psql -c "DELETE FROM ingest_jobs WHERE document_id = (SELECT id FROM documents WHERE filename = 'handbook_b.pdf');"
    ```

    **You should see:** `DELETE 1`.

21. Click **Library** in the left column. On the **shop** row, click **Re-index**, then
    **Re-index it**. ☐

    **You should see:** *"Re-indexing 2 documents."* Two, not one. The file with no queue
    entry is included.

22. Wait until the row settles, as in step 12. ☐

    **You should see:** **Ready**, **All 2 indexed.**, and no **Show detail** button. Before
    this fix, the row would stay **Queued**, with *"1 file is queued."*, for as long as you
    waited.

23. **Stand-in** — confirm both files have a finished job and the older retirements kept
    their dates: ☐

    ```
    scripts/dev.sh psql -c "SELECT d.filename, d.status, j.state, j.stage FROM documents d LEFT JOIN ingest_jobs j ON j.document_id = d.id ORDER BY d.filename;"
    scripts/dev.sh psql -c "SELECT d.filename, left(c.content, 50) AS passage, c.superseded_at FROM chunks c JOIN documents d ON d.id = c.document_id WHERE c.superseded_at IS NOT NULL ORDER BY c.superseded_at;"
    ```

    **You should see:**

    - First query: two rows, both `ready`, both `done` at stage `embed`. No blank `state`.
    - Second query: the passages retired in Part C, the 9 PM one and the handbook one, still
      carry their **Part C** time. This re-index did not reset them. The 8 PM passage that
      step 18 cited now appears too, retired with a **later** time. No new `handbook_b.pdf`
      row appears, because nothing cited the handbook passages Part C wrote, so this
      re-index deleted them instead.

24. Click **Ask** in the left column. Expand the first turn and the step 18 turn in turn, and
    click each **store_hours.pdf** card. ☐

    **You should see:** both open the viewer on page 1 with no error. The step 18 citation
    is now highlighted normally, because the file still says 8 PM. The step 7 citation shows
    the *"could not be pinpointed"* note, as in step 16.

---

## Part F — the automated checks

25. **Stand-in** — run the suites: ☐

    ```
    scripts/dev.sh check
    scripts/dev.sh test-db
    ```

    **You should see:** both finish with no failures. On the run that closed #719 and #720,
    `test-db` reported 982 passed, 0 failed. The tests for this ticket:

    - `api/tests/test_chunk_records.py`, five new tests: a cited passage is retired with its
      text intact; an uncited passage is deleted; a second re-index keeps the first retirement
      date; a cited document re-indexed through `ingest.process` gets past the chunk stage;
      and the database refuses a retired passage that still has an embedding or search
      vector. With `chunk.py` reverted, three fail with the original
      `ForeignKeyViolation ... fk_citations_chunk_id_chunks`.
    - `api/tests/test_ingest_records.py::test_reindexing_a_document_with_no_job_row_gives_it_one`
      for #720.
    - `api/tests/test_reapply.py::test_run_job_does_not_re_embed_a_chunk_a_re_index_retired_after_it_was_queued`.
      A re-apply queued before a re-index must not try to make a retired passage searchable
      again.
    - No abstention test and no retrieval threshold was changed (C5).

---

## Teardown

```
podman compose exec api askwell-verify
podman compose down -v
rm -rf /tmp/askwell-test-203
```

**You should see:** both audit chains reported intact before the wipe. Stop the inference
process in the second terminal with `Ctrl+C`.

---

## Known gaps

These are deliberate or belong to other issues. Do not report them as defects of this
ticket.

- **An old citation whose passage was replaced does not say "replaced".** Opening it shows
  the file as it is now with *"The exact passage could not be pinpointed on this page —
  showing the cited page instead."* The ticket's edge case asks for it to show as removed,
  per `docs/ux/ask.md` §5 and `docs/ux/source-viewer.md` §4 *Superseded*. The server now
  records the replacement date, but the viewer does not read it yet. That is #778, and it is
  listed in `docs/states-and-edge-cases.md`, Ask. The card in the old answer is also not
  greyed out, unlike a deleted source's card.
- **Nothing in the interface shows the retired passage's stored text.** The old answer's card
  and **How did you get this?** show what was saved with the answer. Only step 19's database
  check shows that the passage row itself kept its text.
- **Askwell does not notice an edited file by itself.** The user must press **Re-index**.
  Watching folders for changes is not part of this ticket.
- **Re-index re-reads the whole source, not just the edited file.** Unchanged files are
  re-chunked too, and any of their passages an answer cites are retired and replaced by
  identical new ones, which is what step 23 shows for `handbook_b.pdf`. Keeping unchanged
  passages was option 3 in #719, and it was rejected in `docs/decisions.md`, 2026-09-28.
- **Retired passages take disk space.** Each re-index of a cited document keeps its cited
  passages. The per-source storage figure counts them on purpose. There is no clean-up.
- **What emptied the work queue in the first place** is not fixed here. A restore does not
  bring back `ingest_jobs`. That is #779. Part E creates the state by hand.
- **A rare race.** If an answer cites a passage while that same file is being re-chunked, the
  chunk stage can hit the old foreign-key error once. The job's normal retry handles it, and
  this is recorded in `docs/decisions.md`. Do not try to reproduce it by hand.
- **The first click on a rail item sometimes does nothing** (#665). Record it there.
