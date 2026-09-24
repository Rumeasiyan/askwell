# Rollback, crash reports and incidents

What the maintainer does when a released version turns out to be broken, and what a user does to get back to one that works. `M7-OPS-DOC-165`.

Written before it is needed, because rollback preparedness discovered during an incident is not preparedness. **Read §0 first.** Parts of this procedure cannot run on a real install yet, and each of those parts says so where it appears.

---

## 0. What is and is not possible today

| | Status on 2026-09-24 |
| --- | --- |
| Schema rollback, current migration chain | **Rehearsed on Linux**, against a scratch database: head → two back → head, and head → empty → head. Every one of the 27 migrations has a working `downgrade()`. Record: `docs/manual-tests/M7-OPS-DOC-165.md` §A |
| Rollback on an installed copy, any platform | **Not possible yet.** The installers never run migrations (issue #698). An installed user has no way to downgrade, or even upgrade, the schema. The dev stack is the only place the steps in §1.1 run |
| macOS, Windows rehearsal | **Not run.** There is no test hardware (#590, #592), and each depends on #698 |
| A previous release to roll back to | **None exists.** `gh release list` is empty. The first rehearsal against two real releases happens after the first two are published |
| Local crash reports | **Built and tested.** §3 |
| Telling users a release is broken | **Only partly possible, and not for everyone.** §4.3 states exactly who can be reached |

An honest halt here is worth more than a procedure that reads as finished. Until #698 is fixed, a user reporting a broken release gets §4.2's reply. That reply is a workaround, not a rollback.

---

## 1. Returning to a previous version

There are two paths. **Path A** keeps the data and rolls the database schema back. **Path B** starts from an empty database and restores a backup. Use path A when it applies. Path B is the only option when path A cannot work, and it loses everything done since the backup.

**Whichever path, take a backup first.** There is no backup button yet (issue #615). Run `curl -s -X POST localhost:8000/backup`, poll `GET /backup/<id>` until `done`, then fetch `GET /backup/<id>/download` (`docs/manual-tests/M7-BACKUP-BE-157.md`). A backup made by the newer version **cannot** be restored into the older one: `askwell.restore._check_version` refuses a backup newer than the install, by name, before touching a row. It is still the only way to get back to where you started if the rollback itself goes wrong.

### 1.1 Path A — keep the data, roll the schema back

**Which revision to roll back to.** Each release records its schema revision (`docs/release-procedure.md` §1). Roll back to the revision the *older* release names. If the two releases name the same revision, skip step 2: the schema did not change between them.

**Order matters.** The downgrade must run with the **newer** build still installed. The older build does not know the newer migrations exist, so it cannot undo them. The steps below run on the dev stack today. On an installed copy they wait on #698. The installed form is shown so that it exists when #698 lands. It has been run against the dev stack, not against an install.

1. **Stop the app processes, leave Postgres running.**

   ```
   podman compose stop api worker
   ```

2. **Downgrade the schema with the newer build.**

   Dev stack:

   ```
   scripts/dev.sh db downgrade <older-release-revision>
   scripts/dev.sh db current        # must print <older-release-revision>
   ```

   Installed copy (after #698). This runs as the **owner** role, whose password is already in the install's own `.env`. The app role has no DDL grant, and must not get one (C6):

   ```
   cd <install prefix>              # Linux: ~/.local/share/askwell/app
                                    # macOS: ~/Library/Application Support/Askwell/app
                                    # Windows: %LOCALAPPDATA%\Askwell\app
   podman compose --env-file .env run --rm --no-deps -w /app/api \
     -e ASKWELL_DATABASE_URL="postgresql://askwell:<POSTGRES_PASSWORD from .env>@postgres:5432/askwell" \
     api alembic downgrade <older-release-revision>
   ```

3. **Install the older release over the newer one.** Run the older release's own installer. It keeps the data directory and `.env` ("Existing Askwell installation found … Its data is left untouched") and replaces the application files.

   | Platform | Command |
   | --- | --- |
   | Linux | `./deploy/linux/install.sh` from the older release's tarball |
   | macOS | `./deploy/macos/install.sh` from the older release's tarball |
   | Windows | `.\deploy\windows\install.ps1` from the older release's zip |

4. **Confirm.** `curl -s localhost:8000/health` reports the older version, and every component is reachable. Ask a question you know the answer to, and check that it cites the right page.

### 1.2 Path B — restore a backup into the older version

Use this path when path A does not apply: a migration that cannot be reversed (§2), a failed downgrade, or a database that is itself damaged.

It needs a backup made by **the older version or earlier**. A newer backup is refused. Anything added after that backup was taken is lost: sources added, questions asked, memory confirmed.

1. **Uninstall the newer version, and remove its database volumes.** The volumes hold the index, memory, settings and both audit logs. **This cannot be undone.** Removing them is what makes the target empty, and restore refuses to merge into a database that already has data. `uninstall --purge-data` does **not** remove them today (issue #700), so remove them by name:

   ```
   cd <install prefix>
   podman compose --env-file .env down -v
   ```

   Keep `.env`. A new install that finds it reuses its passwords. If `.env` is deleted while the volumes survive, the next install cannot log in to its own database (#700).

2. **Install the older release** (the table in §1.1 step 3).

3. **Bring the schema to the older release's head.** Restore refuses otherwise (`SchemaNotCurrent`). On an install this also waits on #698.

4. **Restore** with `POST /restore/inspect` and then `POST /restore` (`docs/manual-tests/M7-BACKUP-BE-158.md`). There is no restore screen yet (#615). Inspect states the version, chunk count and re-embedding time before anything is written.

5. **Confirm** as in §1.1 step 4, then run `podman compose exec api askwell-verify`. Both audit chains must verify.

---

## 2. What survives a downgrade

A downgrade runs each migration's `downgrade()` in reverse order. The general rule: **whatever a newer migration added is removed, with its contents.** Rows in tables that existed in both versions are untouched. The audit tables are never rewritten by any downgrade (C6). The chain the older version reads is the chain the newer one wrote.

Cases that need saying plainly:

| Migration | What a downgrade across it does |
| --- | --- |
| `b7e91a4c3f65` — encrypted chunk content (`M7-SEC-BE-152`) | **Remove the passphrase first.** With a passphrase set, chunk text is stored encrypted. The downgrade turns `content_tsv` back into a column generated from that stored text, which then indexes the ciphertext. Keyword search returns garbage. Nothing errors, and the migration does not detect or refuse this (its own comment says so). Remove the passphrase in the newer version before step 1 of §1.1 |
| `c8f2a61d4b90` — export scope | Export jobs lose their scope. Finished export files stay on disk |
| `b5d09e3c71a8` — audit reset function | The guarded function that empties the audit tables is dropped. The older version cannot reset, which is correct for a version that never could |
| `bb5cfc0e8e91`, `c4a1f8d02e77`, `e8b3f61a92d4`, `f2c7d4e1a683` — export, backup, restore and prune job tables | Job history is dropped. Artefacts already written to `/var/lib/askwell` stay |
| `d3e6b1a94f02` — web citations | Web-sourced citations on past answers are dropped. Answers from the person's own material keep theirs (C10 kept the two separate, which is what makes this clean) |
| `7f40fa52d49d`, `a1c2e5f6b3d4` — SQL result, model identity on messages | Past answers lose their stored SQL result table and the "which model answered" marker. The answer text stays |
| Any other `add_column`/`create_table` | That column or table, and what was in it |

**A migration that cannot be reversed.** `AGENTS.md` §6 requires every migration to be reversible, and today every one is (§0). If one ever cannot be, because it transforms data in a way that loses information, that release's notes must say, above the changelog: *"You cannot roll back past this version except by restoring a backup taken before you upgraded."* From then on path B is the only path back. Askwell does not take a backup automatically before an upgrade, so the person has to have taken one.

---

## 3. Crash reports

**When Askwell fails in a way it did not expect, it writes one small file on this machine. It never sends one — not automatically, not on a prompt, not ever.** A crash report reaches the maintainer only if the person downloads it and attaches it to an issue themselves. There is no setting that changes this. Crash reporting that phones home would break C1.

**When one is written.**
- The API hits an unhandled error while answering a request.
- The API or worker process dies from an uncaught exception, on its main thread or another thread (`sys.excepthook`, `threading.excepthook`).

A failed ingest job or a refused query is not a crash. Those already have their own stated failure in the product.

**Where.** `/var/lib/askwell/crash-reports/` inside the `askwell-state` volume (`Settings.crash_report_dir`). The API lists them and the worker's are visible to it, because both containers mount that volume. The newest 20 are kept. File names look like `crash-20260924T101500Z-api-1a2b3c4d.json`.

**How the person gets one.** Settings → About → Report a problem → **Crash reports**. Each report is listed with its time and component, and a **Download** link. Without the interface: `podman compose cp api:/var/lib/askwell/crash-reports ./crash-reports`.

**What is in it.** An allow-list, not a scrubbed copy:

| Field | Example |
| --- | --- |
| `format` | `askwell-crash-report/1` |
| `askwell_version`, `component`, `occurred_at` | `0.7.33`, `api`, ISO 8601 UTC |
| `platform` | OS name, release, CPU architecture, Python version |
| `profile` | `balanced` |
| `route` | The route **template**, e.g. `/documents/{document_id}`, never the path that was requested |
| `exception` | The exception's **type** and the types in its cause chain, e.g. `builtins.ValueError` ← `builtins.FileNotFoundError` |
| `frames` | `(location, function, line)` for each stack frame. The location is Askwell's own file (`askwell/ask.py`), a dependency's path below `site-packages`, a standard-library module, or `<other>` |
| `excluded` | One sentence saying what was left out, and that nothing was sent |

**What is never in it.** The error message. Local variables. Request bodies, paths and query strings. Any file name, question, SQL string or row. Any of these can carry the person's own material, and a report must be safe to attach to a public issue without reading it first. The report is less useful for missing them, and that trade is deliberate. `api/tests/test_crash_report.py` plants a file name, a question and a row of data in the error message, the cause, local variables and the request, then asserts none of them reaches the file or the log line. It also asserts that the module imports no network client.

**Logged locally.** Each report writes one `crash_report_written` line to the application log, with the component, the exception type and the file path, but not the message. If the directory cannot be written, `crash_report_not_written` is logged instead, and the original failure proceeds as it would have. Writing a report never raises.

---

## 4. Incident procedure — a released version is broken

For the maintainer, from the first credible report.

### 4.1 Confirm and scope (first 30 minutes)

1. Reproduce on the reported platform and version, or get the reporter's crash report (§3) and trace. `SUPPORT.md` already asks for version, platform, profile and a copied trace.
2. Decide the scope. Which platforms? Does it lose data or only fail? Is it a security problem? A security problem follows `SECURITY.md`, not this page.
3. Open or pin a GitHub issue titled `Known problem in <version>: <one line>`. State what breaks, who is affected, and what to do now.

### 4.2 Give reporters a working path (within the hour)

Reply to each report with the pinned issue and the first of these that applies:

1. **A fixed release exists:** install it over the broken one. The installer keeps the data.
2. **Path A applies and the reporter can run it** (§1.1, today only from a source checkout, #698): the exact older revision and commands.
3. **Otherwise:** stop using the affected part. Do not uninstall and do not delete anything. If backup still works, take one now (§1). Wait for the fixed release. Say which part is affected, and that nothing about their files on disk is at risk, since Askwell indexes them in place and never modifies them.

### 4.3 How users learn a release is broken — and who cannot

**This is the real limitation, stated rather than glossed over.** Askwell has no server, no account and no telemetry, so there is no list of who installed which version and no way to contact them. That follows directly from C1, and it is the cost of the product's central promise.

| Who | How they learn |
| --- | --- |
| People who said yes to update checks at install (`docs/decisions.md` 2026-09-21) | Within a week of a **newer version being published**, Settings shows that one exists. It says "newer version", not "your version is broken". The feed carries a version number and nothing else, by design. **So the fix is a new release, never a re-published old one.** The check only ever reports a *higher* version (`update_check._version_gt`). Rolling back is therefore announced by releasing the old code under a new patch number |
| People who said no, or were never asked | **Not at all, from inside the product.** Only if they look at the repository, its release page, or the pinned issue |
| People who reported the problem | Directly, in reply to their issue (§4.2) |

A known defect makes the first row weaker than it reads. The feed is `main/VERSION`, which moves on every merged ticket, not on every release. So "a newer version exists" is already true most of the time, whether or not a release was published (issue #699). Until #699 is fixed, the update check cannot be relied on to carry an incident, and the pinned issue and release page are the only channels that do.

### 4.4 Fix and publish

1. Fix on a branch. Bump `PATCH`. Run the full release gate (`docs/release-procedure.md` §§3–3c). An incident does not skip the restore or offline gate: a fix that breaks restore turns one incident into two.
2. Publish. At the **top** of the release notes, above the checksum link, add: *"Fixes a problem in `<broken version>`: `<one line>`. Install this over `<broken version>`; your data is kept."*
3. Edit the broken release's notes to begin: *"Known problem — do not install. Use `<fixed version>`."* Leave its artefacts up. Someone may need them to roll back to, and deleting a published file makes `SHA256SUMS` on existing downloads unverifiable.
4. Update the pinned issue, then close it after a week with no new reports.

### 4.5 Record

Per `AGENTS.md` §8: the pinned issue is the record of the incident. Anything the procedure lacked becomes an issue at the time it is found, and changes to this page are logged in `docs/decisions.md`.

---

## 5. Rehearsal

Run on each platform before each release. This is a gate on the page itself, not only on a single build. The walkthrough and its results live in `docs/manual-tests/M7-OPS-DOC-165.md`. As of 2026-09-24, only the Linux schema rehearsal and the crash-report checks have run (§0).
