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
- An upgrade stops the running Askwell before it changes the database, and starts the new version
  afterwards (#768).
- A plain uninstall keeps the database credentials next to the database it keeps, and the next
  install uses them (#765).
- The installers check for Docker Compose 2.20 or newer, the one compose provider this stack is
  verified with, before copying anything. On Fedora and macOS they offer to install it. On Linux
  they also turn on Podman's API socket, which Docker Compose needs (#767).
- Only one migration runs at a time (`0.9.8`, #813). If the Askwell window is open during an
  upgrade, its supervisor can start the stack while the installer is migrating. The second
  migration now waits for the first, finds nothing left to do, and succeeds, instead of failing
  on a table the first had just made.

**Version under test:** `0.9.8`. Run `cat VERSION` and update this line if the version has moved
on.

**Time:** about 45 minutes for Part 1, most of it waiting for container images and the first
index. Parts 2 and 3 take about 20 minutes.

**Who can run it:** Part 1 is written for someone who has never used a terminal beyond pasting
a command. Parts 2 and 3 need a developer. Steps that check something the user would never
look at are marked **Stand-in**.

**Part 1 cannot be completed today** (see Known gaps: #771). It is written out in full
anyway. It is the acceptance walkthrough for this ticket, and it is the path a real user
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
- The Linux download for this version, `askwell-0.9.8-linux-x86_64.tar.gz`, and the
  `SHA256SUMS` file beside it, from the repository's **Releases** page on GitHub. `0.9.6` is the
  newest one published on 2026-09-29; `0.9.8` appears there once it is released.
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

1a. Open the repository's **Releases** page in your browser. Click **Askwell 0.9.8 (beta)**,
    then click `askwell-0.9.8-linux-x86_64.tar.gz` and `SHA256SUMS` to download both into
    `~/Downloads`. In the terminal, paste:

    ```
    cd ~/Downloads
    sha256sum -c --ignore-missing SHA256SUMS
    tar -xzf askwell-0.9.8-linux-x86_64.tar.gz
    ```

    ☐ **You should see:** `askwell-0.9.8-linux-x86_64.tar.gz: OK`, and a new folder
    `askwell-0.9.8-linux-x86_64` in Downloads. `FAILED` means the download is damaged; download
    it again.

2. In the terminal, go into the release folder and start the installer:

   ```
   cd ~/Downloads/askwell-0.9.8-linux-x86_64
   ./deploy/linux/install.sh
   ```

   If Podman is missing, the installer asks `Install Podman now? [y/N]`. Type `y` and give your
   password when asked.

   ☐ **You should see**, in this order among the other lines:
   - `Installing Askwell 0.9.8`
   - `Podman found: podman version …` (or `Podman installed: …`)
   - On a new account: `Podman's API socket enabled for this account (podman.socket), …`
   - `Compose provider found: Docker Compose version v…`. If it is missing, the installer asks
     `Install Docker Compose now? [y/N]` on Fedora. Type `y`. On other distributions it stops
     and names what to install, before copying anything.
   - `Generated database credentials in /home/<you>/.local/share/askwell/app/.env`
   - `Bringing Askwell's database up to date (the first run also starts the database)...`. The
     first time, this can take several minutes while container images are prepared.
   - `Database schema up to date: applied 30 migration(s).` The number must be greater than 0.
     30 is the count in this version.
   - `Starting Askwell...`, then `Askwell is starting. Its window will open shortly.`
   - `Done. Askwell is also available any time from your applications menu.`

   ☐ **You should not see** `askwell-install:` followed by an error, or `FAILED`. If you do,
   the install has stopped. Copy the text above the error into your report.

### First launch

3. Wait for the Askwell window to open by itself. If it does not open within a minute, open
   your applications menu, search for **Askwell** and click it.

   ☐ **You should see:** a desktop window titled Askwell, not a browser tab. It shows the
   welcome screen, **Welcome to Askwell**, with a **Get started** button. An error page, a blank
   window, or text mentioning a database, table or relation is a failure of this ticket. So is
   landing straight on the **Ask** screen with a banner saying Askwell is not answering: the
   window only shows the welcome screen once the database has answered, so a missing schema
   looks like this rather than like an error.

4. Click **Get started**. Do **not** click **Skip setup** at the top right.

   ☐ **You should see:** a row of four numbered steps, **What this is**, **Check the machine**,
   **Get the model**, **Add something and ask**, with **Check the machine** now in bold. It asks
   **Set a passphrase?** Click **Set a passphrase**, choose one and write it down (or decline —
   either is fine for this test). Then click **Continue**.

   ☐ **You should see:** **Get the model** in bold. The page names the model, with a
   **Download** button, and below it a box headed **Add a source** containing **Files**,
   **Choose files** and **Choose a folder**.

5. Click **Download**. This is the one step that uses the internet, and it takes a while.
   While it runs, click **Choose a folder** in the box below, pick `~/Documents/askwell-test`
   in the folder picker, and confirm.

   ☐ **You should see:** a progress bar filling for the model, and the folder accepted with no
   red note under the box.
   **Known today:** you will instead see a note saying "Askwell has no window onto your
   filesystem yet. Set ASKWELL_ROOTS_MOUNT in .env …". A fresh install has no readable folders
   (#771). Record it, and stop Part 1 here until #771 is fixed.

   ☐ **You should not see** any message about a database, a table or a relation. That would
   mean the schema was never created, which is the #698 failure this ticket fixes.

5a. When the progress bar finishes, click **Continue** (it stays greyed out until the model is
    ready).

    ☐ **You should see:** **Add something and ask** in bold, the line "Ready. Here is a question
    drawn from what you just added …", and one or more suggested questions as buttons. If it
    says "Ready. Add something to ask about …" instead, the folder is not indexed yet — wait a
    minute and carry on to step 6.

6. Click **Library** in the rail on the left. Wait until the file shows **ready**.

   ☐ **You should see:** `handbook_a.pdf`, ready.

7. Click **Ask** in the rail. Type
   `What is the notice period for resigning at Meridian Loom?` and press **Enter**.

   ☐ **You should see:** an answer saying sixty-three days, with a citation to
   `handbook_a.pdf`, page 2. Clicking the citation opens that page.

### Upgrade with nothing pending

8. Leave the Askwell window open. This is on purpose: the window may start Askwell again while
   the installer is upgrading the database, and since `0.9.8` that must not break anything
   (#813). Back in the terminal, run the same installer again:

   ```
   ./deploy/linux/install.sh
   ```

   ☐ **You should see:**
   - `Existing Askwell installation found (version 0.9.8) at /home/<you>/.local/share/askwell. Its data is left untouched; upgrading application files in place.`
   - `Stopped the running Askwell so its database can be upgraded; the new version starts once the upgrade is done.`
   - `Database schema already up to date; no migrations to apply.`
   - `Done. …` at the end, with no error.
   - **No** `The database migration … failed`, `DuplicateTable` or `already exists`. Any of
     those means two migrations collided, which is the #813 failure.
   - **No** `Generated database credentials` line. The existing credentials are kept.

9. The window opens again (or open it from the applications menu).

   ☐ **You should see:** the **Ask** screen, not the welcome screen. **Library** still lists
   `handbook_a.pdf` as ready, and asking step 7's question again gives the same cited answer.

### Uninstall without purging, then install again

9a. Close the Askwell window. In the terminal:

    ```
    ./deploy/linux/uninstall.sh
    ```

    ☐ **You should see:** `Database credentials kept at /home/<you>/.local/share/askwell/askwell.env, so a reinstall can open the database that stays behind.`,
    `Askwell application files removed.`, and `Askwell's database volumes are also left in place, so reinstalling keeps your index and memory …`

9b. Install again, exactly as in step 2.

    ☐ **You should see:** `Restored the database credentials the previous uninstall kept, …`
    and **no** `Generated database credentials` line. Then `Database schema already up to date`,
    **not** `password authentication failed` (#765). When the window opens, it shows the **Ask**
    screen and **Library** still lists `handbook_a.pdf`.

### Purge, then install again

10. Close the Askwell window. In the terminal:

    ```
    ./deploy/linux/uninstall.sh --purge-data
    ```

    ☐ **You should see:** `Database credentials kept at …` and `Askwell application files removed.`, then the question
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
    credentials` (new ones) and `Database schema up to date: applied 30 migration(s).` again.
    **Not** `password authentication failed`, which was the #700 failure.

15. When the window opens:

    ☐ **You should see:** the welcome screen, **Welcome to Askwell**, not the Ask screen. The
    old install's memory and conversations are gone. Repeat steps 4 to 7. The model has to be
    downloaded again in step 5, because the purge removed it with the data directory. They
    should work the same way, with the new credentials.

### When a migration fails

A user cannot cause this on purpose. It was checked in Part 2, rows B6, B7 and B10. What the user
sees is an `askwell-install:` line saying `The database migration … failed with exit status …`,
with the last 20 lines of the migration's output above it, `The install stopped at this step and
is not complete`, and no `Done.` line. The full output is in
`~/.local/share/askwell/logs/migrate.log`.

---

## Part 2 — the real stack, isolated from the dev data

### Rerun on `0.9.8` (2026-09-29): two migrations at once (#813)

Scratch prefix `/tmp/m9lock` with this branch's `compose.yaml`, `deploy/` and an `.env` from
`generate_env_passwords`, `COMPOSE_PROJECT_NAME=m9lock`, `ASKWELL_PORT=8011`, the API image
rebuilt with the advisory lock (`scripts/dev.sh build-api`).

| # | Step | Seen |
| - | ---- | ---- |
| L1 | `up -d --wait postgres`, then two `podman compose --env-file .env run --rm migrate` started together on empty volumes | One log has 30 `Running upgrade` lines, the other none. Both rc 0. `alembic current` prints `f4b8d2c6a915 (head)` |
| L2 | `test-db tests/test_migrations_env.py` with `env.py`'s lock removed (stashed) | 2 failed: the concurrent upgrade fails, and an upgrade runs straight through a held lock |
| L3 | The same, with the lock | 4 passed |
| L4 | Dev stack, `podman compose run --rm migrate` | No `Running upgrade` line, head `f4b8d2c6a915` |

The scratch project was removed with `down -v` (0 `m9lock_` volumes left).

### Rerun on `0.7.62` (2026-09-28)

The first build of this ticket (`0.7.49`, PR #772) never merged: it conflicted with `main` and
failed CI. It was re-applied onto `0.7.61`, and the steps below were run again against the
current code, with the #765 and #768 changes. Same isolation as the first run below: scratch
prefix `/tmp/m9v/app`, `COMPOSE_PROJECT_NAME=m9verify`, `ASKWELL_PORT=8010`, `systemctl` shadowed
by a no-op so no unit on the host is touched. The functions are the real ones from
`deploy/linux/install.sh`, sourced, including the real `place_files`.

| # | Step | Seen |
| - | ---- | ---- |
| V1 | `place_files`, `create_data_dirs`, `stop_previous_stack`, `migrate_database` on empty volumes | No "Stopped" line (a fresh install has nothing to stop). `Database schema up to date: applied 30 migration(s).` rc 0 |
| V2 | `up -d`, then `/memory`, `/roots`, `/clarifications`, `/setup`, `/log-verify` with a session | All 200. `GET /` 200 `text/html`. `migrate` exited 0, the other eight services running |
| V3 | Install record written, then `stop_previous_stack`, `migrate_database` | `Stopped the running Askwell …`, 0 project containers running after it, then `already up to date; no migrations to apply.` rc 0 |
| V4 | `up -d`, `run --rm migrate alembic downgrade -2`, then `stop_previous_stack`, `migrate_database`, `up -d` | `applied 2 migration(s).` rc 0, then all five routes 200 |
| V5 | Plain uninstall: `.env` copied to `data/askwell.env`, prefix removed; then `place_files`, `migrate_database`, `up -d` | `Restored the database credentials …`, `already up to date`, rc 0, all five routes 200 against the kept database |
| V6 | Same, **without** the kept `.env` (the #765 trap) | New passwords generated. The migration fails, `askwell-install: The database migration … failed with exit status 1 … The install stopped at this step and is not complete`, rc 1 |
| V7 | `purge_stack_volumes` on the `m9verify_*` names, data directory removed, fresh install | `purge rc=0`, 0 `m9verify_` volumes left, `applied 30 migration(s).`, all five routes 200 with new passwords |

The scratch project was removed with `down -v` (0 volumes left). The dev stack then took the new
`compose.yaml` with `podman compose up -d`: `migrate` exited 0 with no `Running upgrade` line, and
`alembic current` printed `f4b8d2c6a915 (head)`.

**Podman's API socket (#767).** With `podman.socket` stopped, `podman compose ps` failed with
`Cannot connect to the Docker daemon at unix:///run/user/1000/podman/podman.sock`. That is why
the Linux installer now enables the socket, and why the stack unit requires it. The socket was
started again afterwards, and was left disabled-but-active as it was found.

### First run on `0.7.49`

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
| `bash deploy/linux/install.test.sh` | `151 passed, 0 failed` (again on 2026-09-29, `0.9.8`) |
| `bash deploy/macos/install.test.sh` (runs under Linux bash) | `112 passed, 0 failed` (again on 2026-09-29, `0.9.8`) |
| `scripts/dev.sh test-db tests/test_migrations_env.py` (2026-09-29, `0.9.8`) | `4 passed`. Two real `alembic upgrade head` processes on one empty database both succeed; an upgrade waits while the lock is held |
| `deploy/windows/install.test.ps1`, in `mcr.microsoft.com/powershell` with `--network=none` | `62 passed, 0 failed`. The three `.ps1` files also parse with no errors. PowerShell on Linux, not Windows |
| `scripts/dev.sh check` | `all checks passed` (1337 passed) |

The shell suites use a fake `podman` that records its arguments and keeps "volumes" as files,
plus a no-op `systemctl` or `launchctl`. A test must never disable a unit or remove a volume on
the machine that runs it.

## Known gaps

These are not built yet, or not verified. Do not report them as defects of this ticket.

- **Part 1 has not been run, and it cannot be run end to end yet.**
  - Releases are published now (#559 is closed, `0.9.6` is the newest), but `0.9.8` is not
    released yet, and the walkthrough needs this version's download.
  - A fresh install leaves `ASKWELL_ROOTS_MOUNT` empty, so step 5 cannot read the folder
    without editing `.env` by hand (#771). How wide the default read-only view should be is a
    product decision, and it is escalated on that issue.
  - This host has no spare user account to install into without root.

  Part 2 exercises the same functions against the same stack.
- **Windows and macOS are unverified on their own systems.** The Windows tests ran under
  PowerShell on Linux, which checks the logic but not `Stop-ScheduledTask`, `Start-Process` or
  winget. The macOS scripts ran only under Linux bash (no Mac, #592; no Windows machine, #590).
- **Compose providers other than Docker Compose.** The installers now refuse `podman-compose` by
  name instead of trying it (#767). On Linux distributions other than Fedora, the installer names
  the upstream instructions rather than installing Docker Compose itself, because the package
  name and version there differ by release. On Windows it names the winget command and stops,
  because winget does not refresh the running session's `PATH`.
- **The desktop shell during an upgrade stays open.** The installer does not close the Askwell
  window before it upgrades (#813 option 2, not taken). The window may show Askwell as not
  answering for a moment while the stack restarts; that is expected. The race itself is fixed by
  the database lock (row L1), and #813 closes with this ticket.
- **An upgrade from an older release with pending migrations** is covered only by Part 2 (V4,
  B5). `0.9.6` and `0.9.8` have the same schema head (`f4b8d2c6a915`), so installing `0.9.8`
  over `0.9.6` applies nothing.
