# Manual test — M9-FIX-DEPLOY-200, a fresh install has a schema, an upgrade migrates, purge purges

**Ticket:** `M9-FIX-DEPLOY-200` (issues #698, #700). Before this ticket, no installer set up
Askwell's database. A fresh install started with an empty database, so it could not store or
answer anything, and an upgrade left the database on the old version. `uninstall --purge-data`
removed the data directory and said it had removed the index and memory, but it left the
database behind. That broke the next install's login to its own database. What changed:

- `compose.yaml` has a new `migrate` service. It runs once, brings the database up to date
  (`alembic upgrade head`, as the owner role) and exits. The API and the worker do not start
  until it has succeeded. So every way the stack starts also updates the database first.
- All three installers run that service themselves before they register the stack. They say how
  many migrations they applied, or that none were pending. If a migration fails, the installer
  stops, shows the migration's own error and does not report success.
- `--purge-data` removes the four database volumes as well as the data directory. It reports
  each one from what is actually gone afterwards, not from what it tried to do.

**Version under test:** `0.7.49`. Run `cat VERSION` and update this line if the version has moved
on.

**Time:** about 45 minutes for Part 1, most of it waiting for container images and the first
index. Parts 2 and 3 take about 20 minutes.

**Who can run it:** Part 1 is written for someone who has never used a terminal beyond pasting
a command. Parts 2 and 3 need a developer. Steps that check something the user would never
look at are marked **Stand-in**.

**Part 1 cannot be completed today** (see Known gaps: #559, #766, #771). It is written out in
full anyway. It is the acceptance walkthrough for this ticket, and it is the path a real user
takes. The steps after the blocked one also show what a working install should look like. Part 2
is the evidence that stands in for it until then.

---

## Read this first

> **Warning: step 12 deletes everything this Askwell install holds.** That means the index,
> memory, conversations, audit log, settings and backups. Your own files are not touched. Run
> Part 1 only on a Linux user account made for this test. Do **not** run it on the shared
> development account. There, the volume names are the same (`askwell_*`), and a purge
> destroys the development data.

**What you need**

- A Linux user account that has never had Askwell on it. You can check this in step 1.
- An unpacked Askwell release folder for this version. It contains `deploy/linux/install.sh`.
- A folder of your own with one or two documents in it, for example `~/Documents/askwell-test`
  with `handbook_a.pdf` from the fixture corpus (`eval/fixtures/corpus/handbook_a.pdf`). Page 2
  of that file reads "The standard notice period for resignation at Meridian Loom is sixty-three
  days."

---

## Part 1 — cold start on a clean Linux account (not run, see Known gaps)

### Install

1. **Stand-in:** check that the account really is clean. Open a terminal and paste:

   ```
   ls ~/.local/share/askwell; podman volume ls | grep askwell_
   ```

   ☐ **You should see:** `No such file or directory` for the first part and nothing from the
   second. If either prints something, this account has had Askwell before. Use another one.

2. In the terminal, go into the release folder and start the installer:

   ```
   cd ~/Downloads/askwell-0.7.49
   ./deploy/linux/install.sh
   ```

   If Podman is missing, the installer asks `Install Podman now? [y/N]`. Type `y` and give your
   password when asked.

   ☐ **You should see**, in this order among the other lines:
   - `Installing Askwell 0.7.49`
   - `Podman found: podman version …` (or `Podman installed: …`)
   - `Generated database credentials in /home/<you>/.local/share/askwell/app/.env`
   - `Bringing Askwell's database up to date (the first run also starts the database)...`. The
     first time, this can take several minutes while container images are prepared.
   - `Database schema up to date: applied 28 migration(s).` The number must be greater than 0.
     28 is the count in this version.
   - `Askwell is starting. Its window will open shortly.`
   - `Done. Askwell is also available any time from your applications menu.`

   ☐ **You should not see** `askwell-install:` followed by an error, or `FAILED`. If you do,
   the install has stopped. Copy the text above the error into your report.

### First launch

3. Wait for the Askwell window to open by itself. If it does not open within a minute, open
   your applications menu, search for **Askwell** and click it.

   ☐ **You should see:** a desktop window titled Askwell, not a browser tab. It shows the
   welcome screen, **Welcome to Askwell**, with a **Get started** button. An error page, a blank
   window, or text mentioning a database, table or relation is a failure of this ticket.

4. Click **Get started** and follow the steps. Set a passphrase if asked, and write it down.
   Stop when a step offers to add material.

   ☐ **You should see:** a step headed **Add a source**, with **Choose files** and
   **Choose a folder**.

5. Click **Choose a folder**, pick `~/Documents/askwell-test` in the folder picker, and confirm.
   Finish the remaining welcome steps. Skipping an optional step is fine.

   ☐ **You should see:** the folder accepted, with no red "Not added" note.
   **Known today:** you will instead see "Askwell has no window onto your filesystem yet. Set
   ASKWELL_ROOTS_MOUNT in .env …". A fresh install has no readable folders (#771). Record it,
   and stop Part 1 here until #771 is fixed.

6. Click **Library** in the rail on the left. Wait until the file shows **ready**.

   ☐ **You should see:** `handbook_a.pdf`, ready.

7. Click **Ask** in the rail. Type
   `What is the notice period for resigning at Meridian Loom?` and press **Enter**.

   ☐ **You should see:** an answer saying sixty-three days, with a citation to
   `handbook_a.pdf`, page 2. Clicking the citation opens that page.

### Upgrade with nothing pending

8. Close the Askwell window. Back in the terminal, run the same installer again:

   ```
   ./deploy/linux/install.sh
   ```

   ☐ **You should see:**
   - `Existing Askwell installation found (version 0.7.49) at /home/<you>/.local/share/askwell. Its data is left untouched; upgrading application files in place.`
   - `Database schema already up to date; no migrations to apply.`
   - `Done. …` at the end, with no error.
   - **No** `Generated database credentials` line. The existing credentials are kept.

9. The window opens again (or open it from the applications menu).

   ☐ **You should see:** the **Ask** screen, not the welcome screen. **Library** still lists
   `handbook_a.pdf` as ready, and asking step 7's question again gives the same cited answer.

### Purge, then install again

10. Close the Askwell window. In the terminal:

    ```
    ./deploy/linux/uninstall.sh --purge-data
    ```

    ☐ **You should see:** `Askwell application files removed.`, then the question
    `Delete all of Askwell's data? This removes its database (your corpus's index and extracted text, memory, conversations and audit log), … there is no undo. [y/N]`

11. Type `n` and press **Enter**.

    ☐ **You should see:** `Askwell's data left in place: the data directory … and the database volumes (askwell_postgres-data askwell_sandbox-data askwell_redis-data askwell_askwell-state).`
    Nothing has been deleted yet.

12. Run the command from step 10 again, and this time type `y`.

    ☐ **You should see**, in this order:
    - `Database volumes removed: askwell_postgres-data askwell_sandbox-data askwell_redis-data askwell_askwell-state`
    - `Data directory removed: /home/<you>/.local/share/askwell`
    - `All of Askwell's data has been removed.`

    ☐ Your folder `~/Documents/askwell-test` and `handbook_a.pdf` are still there, unchanged.

13. **Stand-in:** check the purge really happened:

    ```
    podman volume ls | grep askwell_; ls ~/.local/share/askwell
    ```

    ☐ **You should see:** nothing from the first part and `No such file or directory` from the
    second. A volume listed here, after step 12 said it was removed, is a failure of this
    ticket.

14. Install again, exactly as in step 2.

    ☐ **You should see:** the same lines as step 2. In particular, `Generated database
    credentials` (new ones) and `Database schema up to date: applied 28 migration(s).` again.
    **Not** `password authentication failed`, which was the #700 failure.

15. When the window opens:

    ☐ **You should see:** the welcome screen, **Welcome to Askwell**, not the Ask screen. The
    old install's memory and conversations are gone. Repeat steps 4 to 7. They should work the
    same way, with the new credentials.

### When a migration fails

A user cannot cause this on purpose. It was checked in Part 2, rows B6, B7 and B10. What the user
sees is an `askwell-install:` line saying `The database migration … failed with exit status …`,
with the last 20 lines of the migration's output above it, `The install stopped at this step and
is not complete`, and no `Done.` line. The full output is in
`~/.local/share/askwell/logs/migrate.log`.

---

## Part 2 — the real stack, isolated from the dev data (run 2026-09-28)

This stands in for Part 1. A scratch prefix, `/tmp/m9verify/app`, holds `compose.yaml`,
`deploy/{postgres,sandbox,redis}`, `web/out` (copied by hand, #766) and a `.env` made by the
installer's own `generate_env_passwords` and `ensure_redis_passwords`. It uses `ASKWELL_PORT=8010`
and `COMPOSE_PROJECT_NAME=m9verify`, so its volumes are `m9verify_*` and never the dev stack's
`askwell_*`. `migrate_database` is the real function from `deploy/linux/install.sh`, sourced.

| # | Step | Expected | Seen |
| - | ---- | -------- | ---- |
| B1 | `migrate_database` on empty volumes | Schema created, count reported | `Database schema up to date: applied 28 migration(s).` (28 = files in `versions/`) |
| B2 | `podman compose --env-file .env up -d` | Every service up, `migrate` exited 0 as a no-op | `migrate exited 0`, eight services `running`. Its log has no `Running upgrade` line |
| B3 | `GET /memory`, `/roots`, `/ingest`, `/clarifications`, `/setup`, `/log-verify` with a session | 200 from database-backed routes | All 200. `/log-verify` reports both chains intact |
| B4 | `migrate_database` again | No-op, not an error | `Database schema already up to date; no migrations to apply.` rc 0 |
| B5 | `run --rm migrate alembic downgrade -2`, then `migrate_database` | Upgrade applies what is pending | `applied 2 migration(s).` rc 0 |
| B6 | `alembic_version` set to `ffffffffffff`, then `migrate_database` | Install stops and names it | `FAILED: Can't locate revision identified by 'ffffffffffff'`, then `askwell-install: The database migration … failed with exit status 255 … The install stopped at this step and is not complete`. rc 1 |
| B7 | Same state, `up -d` (a restart) | `api` and `worker` do not start | `service "migrate" didn't complete successfully: exit 255`, `up` rc 1, `api`/`worker` `exited`, `curl :8010/health` refused |
| B8 | Foreground, as the systemd unit runs it: `up --abort-on-container-exit --no-attach migrate` for 80 s | Stays up after `migrate` exits | Still serving at the timeout (rc 124). `api` shows `Uvicorn running` |
| B9 | Same, **without** `--no-attach migrate` | — | `migrate-1 exited with code 0`, then `Aborting on container exit…`, and the whole stack stopped. Reproduced twice. This is why the flag is there |
| B10 | Same as B8 with the version broken | Unit exits non-zero, `api` never starts | rc 1, `service "migrate" didn't complete successfully: exit 255`. `api`/`worker` only `created` |
| B11 | Old behaviour: new `.env` passwords against the kept volumes, then `migrate_database` | — | `FATAL: password authentication failed for user "askwell"`, installer stops. The #700 trap, now loud rather than silent |
| B12 | `purge_stack_volumes` with `ASKWELL_VOLUMES` set to the `m9verify_*` names | All four gone | rc 0. `podman volume ls` shows no `m9verify_` volume |
| B13 | `migrate_database` and `up -d` with the new passwords | Clean reinstall works | `applied 28 migration(s).` New session. `/memory`, `/roots` return 200 |

B6 and B10 restored `alembic_version` to `d4a7e92b1f35` afterwards. The scratch project was
removed with `down -v`.

**Clicking through the stand-in.** Steps 3 to 7 of Part 1 can be walked against this scratch
stack in a fresh-profile browser at `http://127.0.0.1:8010`, with `ASKWELL_ROOTS_MOUNT` set by
hand in its `.env` (#771). This was **not** done on 2026-09-28. B3 and B13 checked the
database-backed routes directly instead.

**The dev stack (a real upgrade with nothing pending).** `podman compose up -d` from the
repository with the new `compose.yaml` recreated `api` and `worker` behind `migrate`. The
`migrate` log shows no `Running upgrade` line, and `podman compose exec api alembic current`
prints `d4a7e92b1f35 (head)`.

`uninstall.sh --purge-data` itself was **not** run against a real Podman on this host. Its volume
names are the dev stack's (`askwell_*`), so running it would destroy the development data. It is
covered by Part 3 against the fake `podman`, and by B12 for the removal it performs.

## Part 3 — automated, every push

| Command | Result on 2026-09-28 |
| --- | --- |
| `bash deploy/linux/install.test.sh` | `93 passed, 0 failed` |
| `bash deploy/macos/install.test.sh` (runs under Linux bash) | `88 passed, 0 failed` |
| `scripts/dev.sh test tests/test_compose_migrate.py` | `7 passed` |
| `scripts/dev.sh check` | `all checks passed` (1244 passed) |
| `deploy/windows/install.test.ps1` | **Not run.** No `pwsh` on this host (#606) |

The shell suites use a fake `podman` that records its arguments and keeps "volumes" as files,
plus a no-op `systemctl` or `launchctl`. A test must never disable a unit or remove a volume on
the machine that runs it.

## Known gaps

These are not built yet, or not verified. Do not report them as defects of this ticket.

- **Part 1 has not been run, and it cannot be run end to end yet.**
  - No release tree exists: there is no shell binary and no image bundle (#559).
  - The installers do not place `web/out`, so an installed API has no interface to serve even
    with a schema. Step 3 shows no welcome screen (#766).
  - A fresh install leaves `ASKWELL_ROOTS_MOUNT` empty, so step 5 cannot read the folder
    without editing `.env` by hand (#771, found while writing this document).
  - This host has no spare user account to install into without root.

  Part 2 exercises the same functions against the same stack.
- **Windows and macOS are unverified.** The new functions in `deploy/windows/lib.ps1` have never
  run (no `pwsh`, #606; no Windows machine, #590). The macOS scripts ran only under Linux bash
  (no Mac, #592).
- **The compose provider.** Everything above ran on docker-compose v5.1.1 through `podman
  compose`. `podman-compose` is unverified, and the installers do not check which provider they
  get (#767).
- **Upgrade over a running stack.** The installer migrates, but it does not restart a stack that
  is already running. The old containers keep serving against the new schema until the next
  start (#768). In step 8, close the window first. The session units keep the stack running
  anyway, so this does not avoid #768.
- **A plain uninstall still breaks a reinstall.** It deletes `.env` and keeps the volumes (#765).
  The installer now stops on this with the authentication error (B11) instead of reporting
  success. Part 1 uses `--purge-data` only, so it does not hit this.
