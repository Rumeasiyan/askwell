# Manual test — M11-FIX-DEPLOY-236, the databases survive a stray process dying

**Ticket:** `M11-FIX-DEPLOY-236`. Follow-up: #888 (the installer naming `catatonit`).

Postgres reset every connection several times: four times on the build machine
(2026-09-28 15:17:41, 2026-09-29 14:59:46, 2026-09-30 08:46:31 and 14:42:25 UTC) and once on the
Windows test VM (2026-09-30 08:43). Whatever was using the database failed. An eval died at task
50 of 120, and a question returned 500. Each time the log said:

```
LOG:  untracked child process (PID …) was terminated by signal 13: Broken pipe
LOG:  terminating any other active server processes
LOG:  all server processes terminated; reinitializing
```

**What changed.** `postgres`, `sandbox` and `redis` run with `init: true` in `compose.yaml`.
Podman's `catatonit` is now PID 1 in each of them. It reaps any orphaned process, so the server
never sees one. The orphan was the health check's `pg_isready`, not a piped `psql`. The reasoning
is in `docs/decisions.md`, 2026-10-01.

| Piece | File |
| ----- | ---- |
| `init: true` on `postgres`, `sandbox`, `redis`; none on `migrate` | `compose.yaml` |
| The pin, read as text | `api/tests/test_compose_init.py` |
| Why, what execs into these containers, what was rejected | `docs/decisions.md`, 2026-10-01 |

**Version under test:** `0.9.19`. Run `cat VERSION` and update this line if the version has moved
on.

**Time:** about 40 minutes. Most of it is the builds, indexing, and the `test-db` run in Part E.

**Who can run it:** anyone with a browser and a terminal on the build host. Every Askwell screen
is reached by clicking, starting from Askwell's front page. The fix has no screen of its own: when
it works, nothing happens. So the terminal is used to make the test files, start Askwell, cause
the stray processes, and read the database logs. Those steps are labelled **Stand-in**. A person
using Askwell never does them; the stray processes they stand in for come from the health checks.

---

## Read this first

**Nothing leaves this machine during this test.** No online AI, no web search.

**Run no eval, `test-db` or build queue on this stack at the same time.** Part C creates stray
processes in the database containers on purpose. On this build they are harmless. On a build
without the fix, each one resets every database connection, and whatever else is running fails.

**Record what you see.** The recorded results below were true when this ticket landed. A later
ticket may add tests, so a higher test count is fine. A lower one, or any failure, is not.

---

## Before you start

> **Warning: the cold start below deletes everything this Askwell stack holds.** That means
> sources, memory, conversations, the audit log, settings and any stored provider key, and every
> database on the sandbox. Your original files are not touched. On the shared development
> machine, check first that nobody needs what the stack holds. If you are unsure, open
> **Settings → Your data → Export everything** first.

### 1. The test files (Stand-in)

Askwell can only read folders inside `ASKWELL_ROOTS_MOUNT` in `.env`. Check it, and check that
Redis has its three passwords:

```
cd ~/external/quantum-plus/askwell
grep ASKWELL_ROOTS_MOUNT .env
grep -c '^REDIS_\(API\|WORKER\|PROXY\)_PASSWORD=.' .env
```

**You should see:** a mount that contains `/tmp` (if it does not, set `ASKWELL_ROOTS_MOUNT=/tmp`),
then `3`.

The folder holds two files. `lease-notes.txt` gives the question in Part A an answer with a
source to cite, and it is stored in Askwell's own database (`postgres`). `orders.xlsx` is loaded
into the **sandbox** as a table, so both database containers hold real data. Save this as
`.run/make-236.py` in the repository folder (`.run/` is ignored by git):

```python
from pathlib import Path
import openpyxl

OUT = Path("/app/.run/m11-236/askwell-test-236")
OUT.mkdir(parents=True, exist_ok=True)

(OUT / "lease-notes.txt").write_text(
    "Lease notes\n\n"
    "The Harbour Street lease renews on 14 March 2027. "
    "The deposit is 4,200 dollars and is held by Marlow Lettings.\n"
)

book = openpyxl.Workbook()
sheet = book.active
sheet.title = "North"
for row in [["Customer", "Units"], ["Anna", 4], ["Ben", 7], ["Cara", 2]]:
    sheet.append(row)
book.save(OUT / "orders.xlsx")
print(sorted(p.name for p in OUT.iterdir()))
```

Then:

```
cd ~/external/quantum-plus/askwell
rm -rf .run/m11-236 /tmp/askwell-test-236
scripts/dev.sh run python /app/.run/make-236.py
cp -r .run/m11-236/askwell-test-236 /tmp/
ls /tmp/askwell-test-236
```

**You should see:** the script print `['lease-notes.txt', 'orders.xlsx']`, then the same two
names.

### 2. Start Askwell from nothing (Stand-in)

```
cd ~/external/quantum-plus/askwell
podman compose down -v
scripts/dev.sh build-api
scripts/dev.sh web-build
podman compose up -d
scripts/dev.sh db upgrade head
```

**You should see:** the volumes removed, both builds finish with no red error text, the
containers start, and the migration end without an error. If `podman compose up -d` stops with
`container-init binary not found on the host`, this machine has no `catatonit`. That is the gap
in *Known gaps*, not a failure of this walkthrough. Install `catatonit` and run `up -d` again.

In a **second** terminal, start the model on the host and leave it running:

```
cd ~/external/quantum-plus/askwell
scripts/dev.sh inference
```

**You should see:** the supervisor report the model and the embedding model ready.

---

## Part A — cold start, first run, and a question that works

1. Open a **private or fresh-profile** browser window. Type `http://127.0.0.1:8000` in the
   address bar and press **Enter**. ☐

   **You should see:** the welcome screen, **Welcome to Askwell**, with a **Get started** button.
   If you see the **Ask** screen instead, the stack was not cleared. Go back to *Before you
   start*, step 2.

2. Click **Get started** and follow the steps until one offers to add material. Set a passphrase
   if asked, and write it down. ☐

   **You should see:** a step with an **Add a source** box, offering **Choose files** and
   **Choose a folder**.

3. Click **Choose a folder**. In the folder picker, go to `/tmp`, select `askwell-test-236`, and
   confirm. If the browser asks whether to let the site see the files, allow it. ☐

   **You should see:** a card counting two files, and the question **Which folder is
   “askwell-test-236” in?** with an empty field and an **Add them** button.

4. Type `/tmp` in the field and click **Add them**. If a note says **Askwell has not been given
   this folder yet.** and offers a **Nominate …** button, click it, then click **Add them** again
   if the button is still there. ☐

   **You should see:** the card move on to recording the files, then **Queued**, then indexing
   progress. There should be no red **Not added** note.

5. Finish the welcome steps. Skipping optional steps is fine. Click **Library** in the left
   column. ☐

   **You should see:** a source named **askwell-test-236**. Wait until it, `lease-notes.txt` and
   `orders.xlsx` all say **ready**. This takes a few minutes on CPU.

6. Click **Ask** in the left column. Type **When does the Harbour Street lease renew?** and press
   **Enter**. Wait for the answer. ☐

   **You should see:** an answer saying **14 March 2027**, with **lease-notes.txt** named as its
   source. No error.

   Leave this browser window open on the **Ask** screen.

## Part B — the init is in place (Stand-in)

7. Check what runs as PID 1 in each container, and that the one-shot migration is unchanged: ☐

   ```
   for c in postgres sandbox redis; do
     echo "$c: $(podman exec askwell-$c-1 cat /proc/1/cmdline | tr '\0' ' ') init=$(podman inspect askwell-$c-1 --format '{{.HostConfig.Init}}')"
   done
   podman inspect askwell-migrate-1 --format 'migrate exit={{.State.ExitCode}} init={{.HostConfig.Init}}'
   ```

   **You should see:** each of the three lines start with `/run/podman-init --` and end with
   `init=true`, then `migrate exit=0 init=false`. `/run/podman-init` is Podman's name for
   `catatonit` inside the container. If a line starts with `docker-entrypoint.sh` instead, the
   container is from before this change. Run `podman compose up -d` and check again.

   **Recorded 2026-09-30 18:31 UTC:**

   ```
   postgres: /run/podman-init -- docker-entrypoint.sh postgres  init=true
   sandbox: /run/podman-init -- docker-entrypoint.sh postgres  init=true
   redis: /run/podman-init -- sh /askwell-redis/start.sh redis-server --aclfile /tmp/askwell-redis/users.acl --appendonly yes --save   init=true
   migrate exit=0 init=false
   ```

## Part C — stray processes while you ask

This is the ticket's reproduction. Step 8 creates the same kind of stray process the health check
left behind, many times, in both databases. Step 9 asks a question while that is happening.

8. **Stand-in.** In the terminal, note the time and start the stray processes: ☐

   ```
   since=$(date -u +%Y-%m-%dT%H:%M:%SZ); echo "$since"
   # The ticket's form, 20 at once.
   for i in $(seq 1 20); do podman exec askwell-postgres-1 sh -c 'yes | head -1' >/dev/null & done; wait
   # The form that actually orphans, 60 times on each database, over about a minute.
   for i in $(seq 1 60); do
     podman exec askwell-postgres-1 sh -c 'yes | head -1 >/dev/null &'
     podman exec askwell-sandbox-1  sh -c 'yes | head -1 >/dev/null &'
     sleep 1
   done
   ```

   Keep the terminal and the time it printed. Go straight on to step 9 while the loop runs.

   Why two forms: in the ticket's form, `sh` waits for `yes` and cleans it up itself, so nothing
   is orphaned. It did not reset Postgres even before the fix (see the appendix). In the second
   form, the `&` is inside the quotes. `sh` exits at once, so `yes` and `head` are orphaned to
   PID 1, and `yes` dies of a broken pipe, just like the health check's `pg_isready` did.

9. While the loop is running, go back to the browser. In **Ask**, type **How much is the deposit,
   and who holds it?** and press **Enter**. Wait for the answer. ☐

   **You should see:** an answer saying **4,200 dollars**, held by **Marlow Lettings**, with
   **lease-notes.txt** named as its source. No error message, and the answer is not cut off
   partway.

10. Click **Library** in the left column, then click **Ask** again, and ask **When does the
    Harbour Street lease renew?** once more. ☐

    **You should see:** the Library still lists **askwell-test-236** with both files **ready**,
    and the answer is **14 March 2027** again, from **lease-notes.txt**.

11. **Stand-in.** When the loop in step 8 has finished, wait five seconds, then read both
    database logs since the time it printed, and count leftover processes: ☐

    ```
    for c in postgres sandbox; do podman logs --since "$since" askwell-$c-1 2>&1 | grep -cE "untracked child|reinitializing"; done
    podman exec askwell-postgres-1 sh -c 'grep -l "^State:.*Z" /proc/[0-9]*/status 2>/dev/null | wc -l'
    ```

    **You should see:** `0`, `0`, then `0`. No reset on either database, and no zombie process
    left behind.

    **Recorded 2026-09-30 18:31 UTC** (20 of each form, no browser): `0`, `0`, `0`. The same kind
    of orphan that reset Postgres in the appendix was cleaned up silently.

## Part D — health checks, exit codes and stopping still behave

12. **Stand-in.** Health checks still report, and failures still fail: ☐

    ```
    for c in postgres sandbox redis; do podman healthcheck run askwell-$c-1; echo "$c rc=$?"; done
    podman exec askwell-postgres-1 sh -c 'exit 3'; echo "exec rc=$?"
    podman exec askwell-postgres-1 pg_isready -h /nonexistent >/dev/null; echo "pg_isready rc=$?"
    ```

    **You should see:** `postgres rc=0`, `sandbox rc=0`, `redis rc=0`, `exec rc=3`,
    `pg_isready rc=2`. A health check runs as its own exec session, not under PID 1, so the init
    does not change its exit code.

    **Recorded 2026-09-30:** exactly these.

13. **Stand-in.** Stopping the sandbox is still a clean database shutdown, not a kill: ☐

    ```
    since=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    time podman stop askwell-sandbox-1
    podman logs --since "$since" askwell-sandbox-1 2>&1 | grep -E "shutdown|shut down"
    podman compose up -d sandbox
    ```

    **You should see:** the stop return in about a second, not ten. The log shows `received fast
    shutdown request` and then `database system is shut down`. `catatonit` passes the stop signal
    on to Postgres.

    **Recorded 2026-09-30:** exactly these, stop exit code 0.

14. In the browser, click **Library**. ☐

    **You should see:** **askwell-test-236** with `lease-notes.txt` and `orders.xlsx` both still
    **ready**. The sandbox came back with its table.

15. **Stand-in.** The audit chains are intact after all of this: ☐

    ```
    podman compose exec api askwell-verify
    ```

    **You should see:** every chain reported intact, exit status 0.

## Part E — the suites (Stand-in)

16. Run the checks and the database tests against the recreated stack, and then read the logs
    again: ☐

    ```
    since=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    scripts/dev.sh check
    scripts/dev.sh test-db
    for c in postgres sandbox; do podman logs --since "$since" askwell-$c-1 2>&1 | grep -cE "untracked child|reinitializing"; done
    ```

    **You should see:** both pass with no failures and no skips, then `0`, `0`. `check` includes
    the pin, `api/tests/test_compose_init.py` (7 tests).

    **Recorded when this ticket landed:** `check` 1552 passed; `test-db` 1097 passed in 3 min
    28 s; no `untracked child` or `reinitializing` line during the run.

---

## Appendix — seeing the bug on a build without the fix (optional)

Only possible on a stack whose containers were created **before** this change, where step 7 shows
PID 1 as `docker-entrypoint.sh postgres`. **This resets every database connection.** Do not run
it while anything else uses the stack.

```
podman exec askwell-postgres-1 cat /proc/1/cmdline | tr '\0' ' '; echo
since=$(date -u +%Y-%m-%dT%H:%M:%SZ)
podman exec askwell-postgres-1 sh -c 'yes | head -1 >/dev/null &'
sleep 3
podman logs --since "$since" askwell-postgres-1 2>&1 | grep -E "untracked|reinitializing|terminating any"
```

**Recorded on the build machine, 2026-09-30 18:30 UTC, before the change:**

```
LOG:  untracked child process (PID 1629963) was terminated by signal 13: Broken pipe
LOG:  terminating any other active server processes
LOG:  untracked child process (PID 1629964) exited with exit code 0
LOG:  all server processes terminated; reinitializing
```

This is the line the incidents logged. The ticket's own form, with the `&` outside the quotes,
logged nothing in ten runs against the same unfixed stack, for the reason given in step 8.

---

## Known gaps

These are deliberate or tracked elsewhere. Do not report them as defects of this ticket.

- **Podman 4.9 on Ubuntu 24.04 was not run.** The registry was checked instead. Ubuntu's podman
  `4.9.3+ds1-1ubuntu0.1` only *Recommends* `catatonit | tini | dumb-init`, and Ubuntu's
  `catatonit` ships `/usr/libexec/podman/catatonit`, the path Podman looks for. Fedora's podman
  *Requires* `catatonit`, which also covers Podman machine on Windows and macOS. Where the binary
  is missing, the three containers **do not start** (`container-init binary not found on the
  host`, exit 125). That can happen on Ubuntu with recommends turned off, or with `tini`
  installed instead. The installer naming `catatonit` is #888. Until then, on a clean Ubuntu
  24.04 VM, check `ls /usr/libexec/podman/catatonit` after the installer runs.
- **The Windows VM was not re-run.** The same `compose.yaml` runs there inside Podman machine.
  After the next Windows install, search the Postgres log for `untracked child` after an hour of
  use.
- **The health-check timeouts are still tight for a loaded machine.** A check that runs past 3 s
  is still killed. Before this change that cost a database reset; now it costs one failed check,
  and the container stays **healthy** unless it keeps failing. Timeouts were deliberately not
  changed (`docs/decisions.md`, 2026-10-01, *Rejected*).
- **`api`, `worker`, `voice` and the other Python services have no init.** Python does not reset
  on an unknown child, and those services have no shell health check to leave one. Deliberate,
  same decision entry.
- **Questions are asked of `lease-notes.txt`, not `orders.xlsx`.** A table answer has no citation
  yet (#857), so it would not show a source to check. The workbook is there so the sandbox holds
  real data during Part C.
- **Postgres configuration is unchanged.** Out of scope by ticket, and no setting turns off the
  reset for untracked children.
