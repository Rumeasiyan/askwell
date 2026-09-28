# Manual test — M9-TEST-TEST-213, every test that exists actually runs, in any order

**Ticket:** `M9-TEST-TEST-213`, issues #724, #696, #706 and #752.

This ticket changes **no product code**. It changes which tests run and what state they start
from, so that a green run means something was tested:

1. **Every web test file runs (#724).** `web/package.json`'s `test` script used to name its
   files one by one, and `lib/setup.test.ts` and `lib/storage.test.ts` were missing from the list,
   so they never ran. (`lib/answer-annotations.test.ts` was on #724's list too, but had been added
   since.) The script is now the pattern `'**/*.test.ts'`, so a file cannot be left off
   (`docs/decisions.md`, 2026-09-28).
2. **The clarification cap no longer leaks between API test modules (#706).**
   `test_schema_introspect.py` sets the cap to 1 and never cleared it, so
   `test_inline_clarify.py` failed when it ran afterwards. Both modules now clear the `settings`
   table (#706 option 3).
3. **Two fixes already on `main`, re-verified (#696, #752).** `test_sources_api.py` now keeps
   every path it touches under its own temporary folder (`_owned_state`), so it no longer needs
   `/var/lib/askwell`. `test_provider_key.py`'s cleanup uses `TRUNCATE sources CASCADE`, so
   citations left by `test_ask_online.py` no longer break it.

The walkthrough has two halves. **Part A** is the ticket's own acceptance: run each named test on
its own, in the order that used to break it, and then the full suites. **Part B** is the usual
cold start, by clicking, through the three screens whose helpers are now tested for the first
time: the welcome download size, **Settings → Storage**, and an answer where two sources
disagree. Because no product code changed, Part B is a regression walk. It checks that the
behaviour those newly run tests describe is what the screen actually shows.

**Version under test:** `0.7.60`. This ticket does not change the version: it is tests and test
configuration only (`AGENTS.md` §7). Run `cat VERSION` and update this line if the version has
moved on.

**Time:** about 40 minutes. The full database-backed suite takes most of Part A. Part B waits
for two PDFs to index and one local answer on CPU.

**Who can run it:** anyone with a browser and a terminal. Part A runs entirely in the terminal,
because running a test suite is not something a user of Askwell does. Those steps are labelled
**Stand-in**. Every screen in Part B is reached by clicking, starting from Askwell's front page.

**What is being checked.**

| Piece | File |
| ----- | ---- |
| The web test script | `web/package.json`, `"test"` |
| Newly run: download sizes and the "no disk space" reply | `web/lib/setup.test.ts` → `web/lib/setup.ts` |
| Newly run: whether the log budget is capped by free disk | `web/lib/storage.test.ts` → `web/lib/storage.ts` |
| Conflict and "not covered" lines in an answer | `web/lib/answer-annotations.test.ts` → `web/lib/answer-annotations.ts` |
| Cap cleanup | `_TABLES` in `api/tests/test_schema_introspect.py` and `api/tests/test_inline_clarify.py` |
| Already fixed, re-verified | `_owned_state` in `api/tests/test_sources_api.py`; `_clean` in `api/tests/test_provider_key.py` |

---

## Read this first

**The test database is not your Askwell database.** `scripts/dev.sh test-db` creates a fresh
database for each run and drops it afterwards. Nothing in Part A touches the sources, memory or
settings of the Askwell you use in Part B, and a leak between test modules (#706) could never
reach a real install. It only made the test results depend on order.

**A skip is not a pass.** `AGENTS.md` §6 says a test that needs something it has not got fails;
it does not skip. At the time of writing, `scripts/dev.sh check` reports **1 skipped**. That is
`test_extract_common.py`, which skips when the suite runs as root. It is filed as #806 and is
outside this ticket. Any **other** skip, in any suite, is a defect.

**Record the counts you see.** The numbers below were true when this ticket landed. A later
ticket may add tests, so a higher count is fine. A lower one, or any `fail` above `0`, is not.

---

## Before you start

> **Warning: Part B starts from a cold start, which deletes everything this Askwell stack
> holds.** That means sources, memory, conversations, the audit log, settings and any stored
> provider key. Your original files are not touched. On the shared development machine, check
> that nobody needs what the stack holds now. If you are unsure, open **Settings → Your data →
> Export everything** first.

### 1. Two test documents (Stand-in)

Askwell can only read folders inside `ASKWELL_ROOTS_MOUNT` in `.env`. Check it:

```
cd ~/external/quantum-plus/askwell
grep ASKWELL_ROOTS_MOUNT .env
grep -c '^REDIS_\(API\|WORKER\|PROXY\)_PASSWORD=.' .env
```

**You should see:** a mount that contains `/tmp` (if it does not, set `ASKWELL_ROOTS_MOUNT=/tmp`),
then `3`.

```
rm -rf /tmp/askwell-test-213 && mkdir -p /tmp/askwell-test-213
cp eval/fixtures/corpus/conflict_2025.pdf eval/fixtures/corpus/conflict_2026.pdf /tmp/askwell-test-213/
ls /tmp/askwell-test-213
```

**You should see:** `conflict_2025.pdf` and `conflict_2026.pdf`. Page 1 of the first says the
return window at Meridian Loom is thirty days "as of March 2025". Page 1 of the second says
forty-five days "as of January 2026".

### 2. Start Askwell from nothing (Stand-in)

```
podman compose down -v
scripts/dev.sh build-api
scripts/dev.sh build-web
scripts/dev.sh web-build
podman compose up -d
scripts/dev.sh db upgrade head
```

**You should see:** the volumes removed, the three builds finish with no red error text, the
containers start, and the migration end without an error. The stack must be up for Part A's
database-backed tests as well as for Part B.

In a **second** terminal, start the model on the host and leave it running:

```
cd ~/external/quantum-plus/askwell
scripts/dev.sh inference
```

**You should see:** the supervisor report the model and the embedding model ready.

---

## Part A — every test runs, alone and in any order (Stand-in)

### Web tests (#724)

1. List every web test file that exists: ☐

   ```
   find web -name '*.test.ts' -not -path '*/node_modules/*' | sort
   find web -name '*.test.ts' -not -path '*/node_modules/*' | wc -l
   ```

   **You should see:** a list that includes `web/lib/setup.test.ts`,
   `web/lib/storage.test.ts` and `web/lib/answer-annotations.test.ts`, and a count of `39`.
   Write the count down.

2. Look at the test script: ☐

   ```
   grep '"test"' web/package.json
   ```

   **You should see:** exactly
   `"test": "node --test --experimental-strip-types '**/*.test.ts'",`. There is no list of
   file names, and the pattern is in single quotes.

3. Run each of the three named files on its own: ☐

   ```
   scripts/dev.sh web-run node --test --experimental-strip-types lib/setup.test.ts
   scripts/dev.sh web-run node --test --experimental-strip-types lib/storage.test.ts
   scripts/dev.sh web-run node --test --experimental-strip-types lib/answer-annotations.test.ts
   ```

   **You should see:** each run end with `# fail 0` and `# skipped 0`. The first reports
   `# tests 6`, the second `# tests 2`. The third reports every test in the file passing.

4. Run the whole frontend check: ☐

   ```
   scripts/dev.sh web-check
   ```

   **You should see:** typecheck, lint, tests and build all pass. In the tests section:
   `# tests 592` (or more), `# pass` equal to that, `# fail 0`, `# skipped 0`. Before this ticket
   it read `584`.

5. Prove that a new file is picked up without anyone listing it. Create a test that must fail: ☐

   ```
   cat > web/lib/zz-canary-213.test.ts <<'EOF'
   import assert from "node:assert/strict";
   import { test } from "node:test";
   test("canary 213 must be run", () => { assert.fail("the glob found me"); });
   EOF
   scripts/dev.sh web-run pnpm test 2>&1 | tail -12
   ```

   **You should see:** `not ok` for `canary 213 must be run`, the message `the glob found me`, and
   `# fail 1`. If it says `# fail 0`, the pattern is not finding new files, and that is a defect.

6. Remove the canary and confirm it is gone: ☐

   ```
   rm web/lib/zz-canary-213.test.ts
   git status --short web/lib
   ```

   **You should see:** no line mentioning `zz-canary-213`.

### API tests, each on its own and in the order that broke it

7. Confirm the folder #696 depended on does not exist in the image: ☐

   ```
   scripts/dev.sh run test -d /var/lib/askwell; echo "exit $?"
   ```

   **You should see:** `exit 1`. The folder is absent, so the next step is a real test of #696
   and not a lucky pass.

8. `test_sources_api.py` alone (#696): ☐

   ```
   scripts/dev.sh test-db tests/test_sources_api.py
   ```

   **You should see:** every test passes, including
   `test_a_successful_add_is_committed_and_survives_the_request` and
   `test_a_postgresql_dump_is_queued_and_committed`. There is no `FileNotFoundError` and no
   skip.

9. The clarification cap, in the order that broke it and in reverse (#706): ☐

   ```
   scripts/dev.sh test-db tests/test_schema_introspect.py tests/test_inline_clarify.py
   scripts/dev.sh test-db tests/test_inline_clarify.py tests/test_schema_introspect.py
   scripts/dev.sh test-db tests/test_inline_clarify.py
   scripts/dev.sh test-db tests/test_schema_introspect.py
   ```

   **You should see:** all four runs pass with `0 failed`. In particular,
   `test_two_blocking_ambiguities_defer_the_second` passes in the first run. Before this ticket
   it failed there with `assert 0 == 1`.

10. The provider-key cleanup, in the order that broke it and alone (#752): ☐

    ```
    scripts/dev.sh test-db tests/test_online.py tests/test_ask_online.py tests/test_provider_key.py
    scripts/dev.sh test-db tests/test_provider_key.py
    ```

    **You should see:** both runs pass, with no `errors` and no `IntegrityError` mentioning
    `citations`.

11. The full suites: ☐

    ```
    scripts/dev.sh check
    scripts/dev.sh test-db
    ```

    **You should see:** `check` ends with lint, format, typecheck and tests passing, and the
    summary line reads `1320 passed, 1 skipped` (or more passed). The one skip is #806 (see
    *Read this first*). `test-db` ends with `1028 passed` (or more), `0 failed`, `0 errors`, and
    no skips.

12. Confirm the test runs left nothing behind in your working tree: ☐

    ```
    git status --short
    ```

    **You should see:** no new files that the steps above created. (Files already modified on
    the branch you are testing may show. That is fine.)

---

## Part B — cold start, by clicking, through the screens the new tests describe

1. Open a **private or fresh-profile** browser window. Type `http://127.0.0.1:8000` in the
   address bar and press **Enter**. ☐

   **You should see:** the welcome screen, "Welcome to Askwell", with a **Get started** button.
   If you see the **Ask** screen instead, the stack was not cleared: go back to *Before you
   start*, step 2.

2. Click **Get started** and follow the steps. Set a passphrase if asked, and write it down. ☐

   **You should see:** if a step offers the one-time model download, it shows its size in GB
   with one decimal place, for example "3.0 GB to download once". It never shows "0 MB" or a raw
   byte count. If you start the download, the progress reads "*x* of *y*" in the same units.
   (On a machine where the model is already in place, this step may not appear at all. That is
   correct, and it is not a failure.) This is `formatBytes`, from `lib/setup.test.ts`.

3. At the step headed **Add a source**, click **Choose files**. In the file picker, open
   `/tmp/askwell-test-213`, select both PDFs and confirm. When asked **"Which folder are these
   files in?"**, type `/tmp/askwell-test-213` and click **Add them**. If a note offers to
   nominate the folder (or a parent), click it and then click **Add them** again. Finish the
   welcome steps. Skipping an optional step is fine. ☐

   **You should see:** both files accepted, with no red "Not added" note, and then the **Ask**
   screen.

4. Click **Library** in the left column. Wait until both files say **ready**. ☐

   **You should see:** `conflict_2025.pdf` and `conflict_2026.pdf`, both ready.

5. Click **Settings** in the left column, then scroll to the **Storage** heading. ☐

   **You should see:** under **Index size per source**, one row per PDF, each with a size such
   as "1 MB". Neither size reads "0 MB" (a tiny index rounds up to 1 MB) and neither reads
   "Unknown". Under **Log storage budget**: "Current use: *x* of *y*".

6. Under **Log storage budget**, type `5000` in the box next to **GB** and click **Change
   budget**. ☐

   **You should see:** "Budget changed to 5000.0 GB. Effective budget is *y* GB — capped by 5%
   of current free disk." Just above it, in a different colour: "You set 5000.0 GB, but the
   effective budget is capped at *y* GB — 5% of current free disk (*z* GB)." *y* is about one
   twentieth of *z*. This is `cappedByFreeDisk`, from `lib/storage.test.ts`.

7. Type `0.1` in the same box and click **Change budget**. ☐

   **You should see:** "Budget changed to 0.1 GB." with **no** "capped" sentence, and the
   coloured "You set …" line gone. 0.1 GB is below 5% of any real disk's free space, so nothing
   caps it. If current use is already over 100 MB, the confirmation also says to export or
   prune. That is correct.

8. Put the budget back to what it was before step 6. If you did not note it, type `2` and click
   **Change budget**. ☐

   **You should see:** "Budget changed to 2.0 GB." with or without the capped sentence,
   depending on how much disk is free.

9. Click **Ask** in the left column. Type
   `What is Meridian Loom's standard product return window?` and click **Ask**. Wait for the
   answer to finish. ☐

   **You should see:** an answer that sets the two positions apart rather than blending them
   into one sentence. There is one boxed position citing `conflict_2025.pdf` (thirty days) and
   one citing `conflict_2026.pdf` (forty-five days), each with its own citation marker, and no
   marker text such as `[1]` left loose inside the position's sentence. No line of the answer
   reads "Not covered:", "Conflicting sources on …:" or "Resolved by memory:" as raw text: those
   are annotation lines the model writes, and the screen should have turned them into layout. This is `lib/answer-annotations.test.ts`.

   The local model decides whether to flag a conflict at all. If it answers with only one of
   the two figures and cites it, that is a model-quality result for the `conflicting_sources`
   eval suite, **not** a defect in this ticket. Note it and move on. If it shows a conflict and
   the layout is wrong (one position swallowing the other, a loose `[1]`, an empty box), that is
   a defect.

10. Type `What is Meridian Loom's policy on gift wrapping?` and click **Ask**. ☐

    **You should see:** Askwell says your files do not answer this and names what would need
    adding. It does not make up a policy (C5). Any "Not covered by your files" section shows as
    its own quiet block, not as a raw "Not covered:" line in the prose. It does **not** search
    the web on its own. Any web search is only offered, for you to choose (C10).

---

## What a pass looks like

- Part A: every step shows the result described. Web: 39 files, 592 or more tests, `# fail 0`,
  `# skipped 0`, and the canary is caught. API: each named module passes alone and in its
  issue's order. `check`'s only skip is #806, and `test-db` has none.
- Part B: every screen reached by clicking, with sizes in readable units, the capped line
  appearing only when the budget is above 5% of free disk, and annotation lines laid out rather
  than printed.

A failure becomes a GitHub issue before the walkthrough continues (`AGENTS.md` §8).

---

## Known gaps

These are deliberate or tracked elsewhere. Do not report them as defects of this ticket.

- **`test_extract_common.py` skips as root (#806).** Every run inside the image is root, so
  `scripts/dev.sh check` reports `1 skipped`. It is contrary to `AGENTS.md` §6, it was found
  during this ticket, and it is filed separately because it is out of this ticket's scope.
- **The web tests cover the pure helpers only.** `lib/*.ts` is unit-tested. The components that
  use those helpers (`components/welcome/welcome-screen.tsx`, `components/settings/storage.tsx`,
  `components/ask/ask-screen.tsx`) have no automated browser test. Part B is their check.
- **The glob matches every `*.test.ts` outside `node_modules`.** Today all 39 are in `web/lib/`.
  If a vendored tree with its own `.test.ts` files is ever added under `web/`, the pattern will
  need narrowing (`docs/decisions.md`, 2026-09-28, *Consequences*).
- **No other test module was found writing the clarification cap.** The audit #706 asked for
  found only `test_clarify.py`, which already clears `settings`, and `test_schema_introspect.py`,
  fixed here. A future module that sets the cap has to clear `settings` itself. Nothing enforces
  that.
- **Whether the local model flags the return-window conflict** (Part B step 9) is measured by
  the `conflicting_sources` eval suite, not by this ticket.
- **The model download step** (Part B step 2) only appears when the model is not already in
  place. On the build host it usually is, so the download-size check may not be reachable by
  clicking there.
