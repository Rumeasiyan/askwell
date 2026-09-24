# Manual test — M7-OPS-DOC-165, rollback rehearsal and local crash reports

**Ticket:** `M7-OPS-DOC-165` — a written rollback procedure with a statement of what happens to data across a downgrade, crash reports that stay on this machine, and an incident procedure (`docs/rollback-and-incidents.md`).
**Version under test:** `0.7.33`
**Time:** about 60 minutes on Linux: Part A 10 minutes, Part B 30 minutes (mostly builds), Part C 15 minutes, Part D 5 minutes. Part E runs per platform, once it can.

**What is being checked.**

- `docs/rollback-and-incidents.md`: the procedure itself. **Follow only what that page says.** If a step needs something the page does not say, the page has failed. Fix the page, not the tester.
- `api/src/askwell/crash_report.py`: writes a crash report to `/var/lib/askwell/crash-reports`, lists reports, and serves downloads. The API and the worker both install it.
- `web/components/settings/about.tsx` (`CrashReportList`) and `web/lib/crash-reports.ts`: the **Crash reports** list under **Settings → About → Report a problem**.

**Why some steps use a terminal.** Two things in this test have no button in the product:

- **Rolling back.** The rollback procedure is a set of terminal commands. That is what the procedure is, and there is no downgrade button to click.
- **Making Askwell crash.** No screen crashes on demand.

Everything a *user* sees — their data after a rollback, the crash report list, the download, the network counter — is checked by clicking through the product from a cold start.

---

## Before you start

### Test files

Askwell can only read folders inside `ASKWELL_ROOTS_MOUNT` in `.env`. On this machine it is `/tmp`. Check it:

```
cd ~/external/quantum-plus/askwell
grep ASKWELL_ROOTS_MOUNT .env
```

If it is empty, or does not contain `/tmp`, set `ASKWELL_ROOTS_MOUNT=/tmp` before starting the stack.

Make a folder with one small file that states a fact you can ask about:

```
mkdir -p /tmp/askwell-test-165
printf 'The Harlow lease sets the monthly rent at 1,850 pounds, due on the first working day.\n' > /tmp/askwell-test-165/harlow-lease.txt
```

### A clean checkout

Part B switches the checkout to an older commit and back. Run this test from `main` **after this ticket has merged**, with nothing uncommitted:

```
git switch main && git pull
git status --short
```

**You should see:** `git status --short` prints nothing. If it prints anything, stop. Part B cannot switch commits safely.

### Start Askwell

```
scripts/dev.sh build-api
scripts/dev.sh web-build
podman compose up -d --force-recreate api worker
scripts/dev.sh db upgrade head
cat VERSION
```

**You should see:** the builds finish without red error text, and Compose reports the containers as started. The migration step ends without an error. `cat VERSION` prints `0.7.33` or later. Write the number down.

In a **second** terminal, start the model on the host and leave it running:

```
scripts/dev.sh inference
```

**You should see:** the supervisor logs that the generation model is ready.

---

## Part A — cold start, and data to roll back with

1. Open a **private or fresh-profile** browser window, so that no earlier session carries over. Open `http://127.0.0.1:8000`. This is the only address you type in this test. ☐

   **You should see one of two screens:**
   - **Fresh install:** a page headed **Welcome to Askwell**, with a **Get started** button.
   - **Sources already added:** the **Ask** screen, with a rail down the left side: **Ask**, **Library**, **Clarifications**, **Memory**, **Settings**.

2. Add the test folder. ☐
   - **Fresh install:** click **Get started** and follow the steps until you reach the step that adds material.
   - **Sources already there:** click **Library** in the rail, then **Add a source** below the list.

   Click **Choose a folder** and pick `/tmp/askwell-test-165`. Under "Which folder are these files in?", type `/tmp/askwell-test-165`, then click **Add them**. If a note offers **Nominate /tmp/askwell-test-165**, click it.

   **You should see:** the file accepted, with no red "Not added" note. Click **Library** in the rail. `harlow-lease.txt` shows as ready, not queued or indexing. Wait until it does.

3. Click **Ask** in the rail. Type `What is the monthly rent under the Harlow lease?` and send it. ☐

   **You should see:** an answer of 1,850 pounds, citing `harlow-lease.txt`. Under the question box there is a small line, `Askwell 0.7.33 · nothing leaves this machine`, with the number you wrote down.

4. Click **Memory** in the rail. Click **Add a fact**. For **Subject** enter `Harlow`, and for **What it means** enter `The Harlow Road unit, leased from Pemberton Estates`. Click **Add**. ☐

   **You should see:** a card for `Harlow` with that meaning. Count the cards on the Memory screen and write the number down.

---

## Part B — roll back to an older version, keeping the data (Linux, dev stack)

This rehearses `docs/rollback-and-incidents.md` §1.1 (path A) with real data. It is a **stand-in**. On an installed copy the same steps cannot run yet (#698, see Known gaps). The dev stack is the only place they run today.

The "older release" is commit `67ab3d9d` (version `0.7.28`). Its database schema is revision `b5d09e3c71a8`, one migration behind this build's `c8f2a61d4b90`. No release has been published (`gh release list` is empty), so an older commit stands in for one.

**This touches your development database.** The page tells you to back up first. Do it.

**Open `docs/rollback-and-incidents.md` somewhere that will not change** before you start: on GitHub, or copied to `/tmp`. Step 5 switches the checkout to a commit that does not contain the page.

1. **Back up**, as `docs/rollback-and-incidents.md` §1 says. There is no backup button yet (#615), so the page gives the terminal commands. Follow them as written and keep the downloaded file. ☐

   **You should see:** a `.zip` file on disk bigger than zero bytes.

2. **Work out the revision to roll back to.** The page (§1.1) says to use the revision the *older* release names. Here it is `b5d09e3c71a8`. Check it: ☐

   ```
   git diff --name-only 67ab3d9d HEAD -- api/src/askwell/db/migrations/versions/
   ```

   **You should see:** exactly one file, `20260924_c8f2a61d4b90_export_jobs_scope.py`. It is the only migration newer than `0.7.28`, and its `down_revision` is `b5d09e3c71a8`.

3. **Follow §1.1 step 1:** stop the app processes, and leave Postgres running. ☐

   **You should see:** `api` and `worker` stopped. Back in the browser, reload the page. It fails to load. That is expected.

4. **Follow §1.1 step 2, the "Dev stack" form**, with `b5d09e3c71a8` as the revision. This runs with the **newer** build still in place, which is the order the page requires. ☐

   **You should see:** one `Running downgrade c8f2a61d4b90 -> b5d09e3c71a8` line and no error. `db current` prints `b5d09e3c71a8`.

5. **Follow §1.1 step 3 on the dev stack:** switch to the older build and rebuild it. ☐

   ```
   git switch --detach 67ab3d9d
   scripts/dev.sh build-api
   scripts/dev.sh web-build
   podman compose up -d --force-recreate api worker
   ```

   **You should see:** the builds finish without red error text, and `api` and `worker` start.

6. **Follow §1.1 step 4, by clicking.** Close the private window. Open a new one, and open `http://127.0.0.1:8000`. ☐

   **You should see:** the **Ask** screen, not the welcome page. The line under the question box reads `Askwell 0.7.28 · nothing leaves this machine`.

7. Type `What is the monthly rent under the Harlow lease?` and send it. ☐

   **You should see:** the same answer as Part A step 3, 1,850 pounds, citing `harlow-lease.txt`.

8. Click **Memory** in the rail. ☐

   **You should see:** the `Harlow` card, and the same number of cards as in Part A step 4.

9. Click **Settings** in the rail and scroll to the bottom. ☐

   **You should see:** **About** shows **Version** `0.7.28`. There is **no** Crash reports list under **Report a problem**. That is correct: `0.7.28` predates it.

10. **Read §2 of the page against what just happened.** It says `c8f2a61d4b90` removes export jobs' scope and leaves export files on disk. Nothing you created in Part A is in that table, so all of it is still there. That matches steps 7 and 8. ☐

11. **Roll forward again**, to put the machine back as it was: ☐

    ```
    git switch main
    scripts/dev.sh build-api
    scripts/dev.sh web-build
    podman compose up -d --force-recreate api worker
    scripts/dev.sh db upgrade head
    ```

    Reload the browser. **You should see:** `Askwell 0.7.33` under the question box (or the version you wrote down), and the same answer and memory card as before.

**Could someone else do this?** Record every place where you needed to know something the page did not tell you. Examples: which revision, which terminal, what "older release" meant. Each of those is a defect in the page.

**Result:** not yet run with data. Run it and record the date, the versions and the outcome here.

### B2. Schema chain only — scratch database

This proves every migration goes down and back up. It uses a throwaway database, so it touches no data. Run it only if Part B failed at step 4, to tell a broken migration from a broken procedure.

```
podman exec askwell-postgres-1 psql -U askwell -d postgres \
  -c "DROP DATABASE IF EXISTS askwell_rollback_rehearsal" \
  -c "CREATE DATABASE askwell_rollback_rehearsal"
export POSTGRES_DB=askwell_rollback_rehearsal
scripts/dev.sh db upgrade head && scripts/dev.sh db current
scripts/dev.sh db downgrade -2 && scripts/dev.sh db current
scripts/dev.sh db upgrade head && scripts/dev.sh db downgrade base && scripts/dev.sh db current
scripts/dev.sh db upgrade head && scripts/dev.sh db current
unset POSTGRES_DB
podman exec askwell-postgres-1 psql -U askwell -d postgres -c "DROP DATABASE askwell_rollback_rehearsal"
```

**You should see:** the head revision marked `(head)`, then two `Running downgrade` lines. Then every migration downgrades down to `The v1 schema, whole.`, after which `current` prints nothing. Then head again. No error at any point.

**Result, 2026-09-24, Linux (Fedora 43, this build host):** pass. Head was `c8f2a61d4b90`, and two back was `e8b3f61a92d4`. Head → base → head completed across all 27 migrations. The installed form of the downgrade command from §1.1 step 2 was run with `alembic current` against the dev stack, and answered `e8b3f61a92d4`.

---

## Part C — a crash leaves a local report, and nothing is sent (Linux, dev stack)

1. In the browser, click **Settings** in the rail. Scroll down to **Privacy and security → Network activity**. ☐

   **You should see:** a line like `N outbound requests permitted · M refused, measured by the egress proxy`. Write down both numbers.

2. Scroll down past **Your data** to **About**, then to **Report a problem**. Below the "Then open an issue…" sentence and the issue tracker address is a small heading, **Crash reports**. ☐

   **You should see:**
   - The sentence: "A crash report holds the Askwell version, your platform and profile, and where in Askwell's own code the failure happened. It leaves out the error message and anything from your files, questions or databases. It is saved on this machine and never sent: if you want to include one in an issue, download it and attach it yourself."
   - If this machine has no reports: "None. Askwell has not crashed on this machine, or its reports were removed."
   - At the bottom: "Saved in `/var/lib/askwell/crash-reports`, inside Askwell's own storage."
   - **No** button that sends, uploads or submits anything.

3. **Make Askwell crash, twice**, once in each process. Put a file name and a question in the error, the way a real failure might: ☐

   ```
   podman compose exec -T api python -c "
   from askwell.config import load_settings
   from askwell.crash_report import install_excepthook
   install_excepthook(load_settings(), 'api')
   raise RuntimeError('could not open harlow-lease.txt for What is the monthly rent under the Harlow lease')"
   podman compose exec -T worker python -c "
   from askwell.config import load_settings
   from askwell.crash_report import install_excepthook
   install_excepthook(load_settings(), 'worker')
   raise ValueError('question: what is in Pemberton-settlement-DRAFT.pdf')"
   ```

   **You should see:** for each, one `crash_report_written` log line naming the component, the `exception_type` and the report's path, followed by the usual traceback. The log line does **not** contain the message. That is the "a crash is logged locally" requirement.

4. Back in the browser, reload the page. Click **Settings**, and scroll to **About → Report a problem → Crash reports**. ☐

   **You should see:** two lines, newest first, each like `2026-09-24 10:15 UTC, worker · Download` and `… UTC, api · Download`. The times are in UTC and within a minute of now. The worker's report is listed even though you are looking at the API. Both processes write to the same storage.

5. Click **Download** on the `api` report. Open the downloaded file in a text editor. ☐

   **You should see:** readable JSON with `askwell_version` `0.7.33`, `component` `api`, a `platform` block, `profile`, an `exception` whose `type` is `builtins.RuntimeError`, a list of `frames` each with `location`, `function` and `line`, and an `excluded` sentence ending "has not been sent anywhere." Nothing else.

6. **Search the file for your material.** In the editor, search for each of `harlow`, `lease`, `rent`, `pemberton`, `settlement`. Or in a terminal: ☐

   ```
   grep -i -c "harlow\|lease\|rent\|pemberton\|settlement" ~/Downloads/crash-*-api-*.json
   ```

   **You should see:** no match in the editor, and `0` from `grep`. Repeat for the `worker` report. Any match is a defect: the report would then carry the person's own material onto a public issue.

7. Scroll up to **Privacy and security → Network activity**. ☐

   **You should see:** the same **permitted** and **refused** numbers as in step 1. Nothing was sent. (If update checking is turned on under **About**, it can move **permitted** by one on its own weekly schedule. Turn it off before this part if it is on.)

8. **Without the interface.** §3 of the page gives a terminal way to get the reports. Follow it: ☐

   **You should see:** a folder containing the same two files.

9. Clean up: ☐

   ```
   podman compose exec api sh -c 'rm -f /var/lib/askwell/crash-reports/*'
   ```

   Reload the browser and return to **Settings → About → Crash reports**. **You should see:** "None. Askwell has not crashed on this machine, or its reports were removed."

**Result, 2026-09-24, Linux (dev stack, `0.7.32` image with this change built in; checked from the terminal rather than by clicking through):** pass. Two reports were written, one per component, and both were listed. The downloaded report contained none of the planted text (`grep` count `0`). Network counters read `refused 6, permitted 7` before and after. The terminal copy retrieved both files. The built settings page contains the **Crash reports** heading and its "never sent" sentence. Rerun steps 1–9 by clicking, as written, and replace this record.

An error inside a real request (the other way a report is written) is not induced here, because no screen fails on demand. `test_unhandled_api_error_writes_a_report_without_the_request` covers it by driving the real app's error handler. `test_download_refuses_anything_but_a_report_name` covers a download name that tries to leave the folder.

---

## Part D — incident procedure, tabletop

Read `docs/rollback-and-incidents.md` §4 as if `0.7.33` had just broken ingestion on macOS. At each step, check that the page tells you what to do without asking anyone. ☐

**You should be able to answer, from the page alone:**

- What do I reply to the first person who reports it, within the hour? (§4.2: the pinned issue, plus the first working path that applies.)
- Who will find out that `0.7.33` is broken, and who will not? (§4.3: people with update checks on learn only that a *newer* version exists. Everyone else learns only from the repository. The page names issue #699 as making even that unreliable.)
- Can I pull the broken release? (§4.4: no. Mark its notes "Known problem — do not install" and leave its files up.)
- Does an urgent fix skip the release gates? (§4.4: no.)

If any answer needed guessing, record the sentence that fell short.

**Result, 2026-09-24:** run by the page's author, which is a weaker check than a second person. Rerun with someone else before the first public release.

---

## Part E — rollback on an installed copy, each platform

Follow `docs/rollback-and-incidents.md` §1.1 on a real install. Install release N−1, repeat Part A, take a backup, upgrade to N, then roll back to N−1. Then repeat from the backup using §1.2.

**You should see:** Askwell starts at N−1, the question gets the same answer and citation, and the memory card is present. For §1.2 the same holds, except for anything added after the backup.

| Platform | Status |
| --- | --- |
| Linux | **Cannot run yet.** Installers never apply migrations (#698). No release published |
| macOS | **Cannot run yet.** As Linux, and no test hardware (#590) |
| Windows | **Cannot run yet.** As Linux, and no test hardware (#592) |

Run this as soon as #698 is fixed and two releases exist, and record the result in this table.

---

## Known gaps

These are deliberately not built, or cannot be done yet. Do not report them as defects.

- **No rollback on an installed copy, on any platform.** The installers never run migrations, so an installed schema cannot move either way (#698). Part B is a dev-stack stand-in. Part E waits on #698 and on two published releases.
- **No macOS or Windows rehearsal.** No test hardware (#590, #592).
- **No way to tell every user a release is broken.** Askwell has no server, account or telemetry, so nobody knows who installed which version. This is the cost of C1, and the page states it in §4.3 rather than working around it. Update checks are opt-in and report only that a newer version exists. Even that is unreliable until #699 is fixed, because the feed advertises unreleased versions. Update *delivery* is blocked.
- **No backup or restore button** (#615). The procedure uses terminal commands for both.
- **`uninstall --purge-data` leaves the database volumes behind** (#700). §1.2 tells people to remove them by hand.
- **A backup made by the newer version cannot be restored into the older one.** Restore refuses it by name. This is by design, and stated in §1.
- **Downgrading across `b7e91a4c3f65` with a passphrase set** silently leaves keyword search indexing ciphertext. §2 says to remove the passphrase first. Part B does not cross that migration.
- **No automatic crash reporting, and no send button.** Forbidden by C1, not missing.
- **A crash report is thin on purpose.** It has no error message and no local variables. That makes it harder to diagnose, and that trade is deliberate (`api/src/askwell/crash_report.py` docstring).
