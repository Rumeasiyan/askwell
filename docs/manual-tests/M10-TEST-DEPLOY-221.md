# Manual test — M10-TEST-DEPLOY-221, CI compiles the desktop shell on every push that touches it

**Ticket:** `M10-TEST-DEPLOY-221`, issue #821.

Before this ticket, no automated check compiled the desktop shell (`web/src-tauri`). The first
compile was the `0.9.0` release build. It failed on all three platforms, three different ways,
and each attempt took a 30–60 minute build (#821). This ticket adds two things:

1. **A GitHub Actions workflow, "Desktop shell"** (`.github/workflows/shell.yml`). It runs
   `cargo check --locked` in `web/src-tauri` on `ubuntu-22.04`, with the same system packages
   `release.yml` installs. It runs only on a push that touches `web/src-tauri/**`, `VERSION`
   or the workflow file itself.
2. **A consistency check inside `web/src-tauri/build.rs`.** The build fails, with a message
   naming the command, when the command list in `build.rs` and `generate_handler!` in
   `web/src-tauri/src/main.rs` differ in either direction. That mismatch was the first of the
   three `0.9.0` failures. Because `cargo check` runs `build.rs`, the workflow runs this check
   too, and so does every local build.

**What differs from the ticket's wording, by decision.** The ticket says "a `cargo check` job in
`ci.yml`". The job is in its own workflow file, `shell.yml`, instead. A job skipped inside
`ci.yml` would show up as a **skipping** check on every pull request that does not touch the
shell, and `scripts/watchdog.sh` merges a pull request only when every check is **pass**. That
would stop almost every pull request from merging unattended. A workflow with a `paths` filter
creates no check at all when nothing matches. The ticket also asks for "a test". The check
lives in `build.rs` instead of a separate `#[test]`, so it runs on every build, not only when
someone runs tests. Both choices are recorded in `docs/decisions.md`, 2026-09-29. Neither is
a defect.

**Version under test:** `0.9.1`. This ticket does not change the version, because it adds CI
and a build-time check and nothing a user of Askwell sees (`AGENTS.md` §7). Run `cat VERSION`
and update this line if the version has moved on.

**Time:** about 30 minutes, mostly waiting for four workflow runs of a few minutes each.

**Who can run it:** anyone with a GitHub account that has write access to
`Rumeasiyan/askwell`, using a web browser. Every step in Parts 1–4 is done by clicking on
github.com, including the edits. You do not need a terminal. Part 5 is an optional local
reproduction for someone who wants one. It is labelled **Stand-in**.

**Who the "user" is here.** This ticket has no screen inside Askwell. Its user is whoever next
changes the desktop shell, and the surface they see is the list of checks on their pull request
and the **Actions** tab. So the cold start here is arriving at the repository on GitHub, not
launching Askwell.

| Piece | File |
| ----- | ---- |
| The workflow | `.github/workflows/shell.yml` |
| The command list and the check | `web/src-tauri/build.rs`, `COMMANDS` and `check_commands_match_main` |
| The registered handlers | `web/src-tauri/src/main.rs`, `generate_handler![...]` (nine commands) |
| Note pointing from the main CI to the new workflow | `.github/workflows/ci.yml`, header comment |

---

## Read this first

> **Warning: never open a pull request from a throwaway branch in this test.**
> `scripts/watchdog.sh` runs every fifteen minutes and merges **any** open pull request whose
> checks all pass. In Part 4, the throwaway change touches only documentation, so its checks
> will pass. If that change has a pull request open, the watchdog will merge it into `main`.
> Parts 2–4 therefore push **branches only**. GitHub will offer you a pull request form after
> each edit. Leave that page without clicking **Create pull request**.

**The throwaway branches are meant to fail.** In Parts 2 and 3, a red cross is the pass
result. A green tick there is the defect.

**Record what you saw.** Note the run duration and the exact error line each time. The
numbers below were measured when the ticket landed. A slower run is fine as long as it stays
well inside the job's 20-minute limit.

---

## Before you start

1. Sign in to github.com in a web browser, as an account with write access to
   `Rumeasiyan/askwell`. ☐

2. Confirm that this ticket's pull request exists. Open `https://github.com/Rumeasiyan/askwell`,
   click the **Pull requests** tab, and find the pull request for `M10-TEST-DEPLOY-221`, from
   the branch `feat/m10-test-deploy-221`. If it is already merged, click **Closed** above the
   list to find it. ☐

   **You should see:** a pull request whose **Files changed** tab lists
   `.github/workflows/shell.yml` (new), `.github/workflows/ci.yml`, `web/src-tauri/build.rs`,
   `docs/decisions.md` and `docs/BRAIN.md`.

   If there is no such pull request, stop. Nothing in this test can be walked until the branch
   has been pushed. Before this document was written, the branch had not been pushed yet.

---

## Part 1 — a push that touches the shell runs the job, and it passes

This is the ticket's own cold-start walkthrough: a pull request that touches `build.rs`,
watched as its checks run.

3. On the pull request page, scroll to the box near the bottom that lists the checks. If it is
   collapsed, click **Show all checks**. ☐

   **You should see:** a check named **Desktop shell / Desktop shell — cargo check (push)**,
   alongside the usual **CI** checks. While it runs it shows a yellow dot. When it finishes it
   shows a green tick.

4. Click **Details** beside **Desktop shell — cargo check**. ☐

   **You should see:** the job page, with these steps in order: **Set up job**,
   **Run actions/checkout@v4**, **Install the WebView and GTK build dependencies**,
   **cargo check**, then the post and complete steps. Each has a green tick. The job summary
   shows a total time of a few minutes. The cold `cargo check` alone took 70 seconds when it
   was measured locally, and installing the packages adds time. Write the total down.

5. Click the **cargo check** step to expand it, then scroll to its last lines. ☐

   **You should see:** many `Compiling …` or `Checking …` lines, then a line starting
   `Finished` that mentions the `dev` profile. There is no line starting `error`, and no
   `panicked`.

6. Click the **Install the WebView and GTK build dependencies** step to expand it. ☐

   **You should see:** `apt-get` install the packages without an error. The list includes
   `libwebkit2gtk-4.1-dev` and `libgtk-3-dev`. Nothing in the log asks for, or prints, a
   token, password or secret (C8). The only credential in play is GitHub's own read-only
   checkout token, which GitHub masks as `***`.

7. After the pull request has merged, check that the job also passes on `main`. At the top of
   the repository, click the **Actions** tab. In the list of workflows on the left, click
   **Desktop shell**. ☐

   **You should see:** a run for the merge commit on the `main` branch, with a green tick. The
   merge touched `web/src-tauri/build.rs`, so the workflow ran. This is the ticket's
   "it passes on current `main`".

   If the pull request has not merged yet, come back to this step after it has.

---

## Part 2 — dropping a command from `build.rs` makes the job fail

The ticket requires this to be proved on a throwaway branch, not assumed. This is the exact
shape of the `0.9.0` failure: a command still registered in `main.rs` but missing from
`build.rs`.

8. Click the **Code** tab. Make sure the branch selector above the file list says `main`. Click
   `web`, then `src-tauri`, then `build.rs`. ☐

   **You should see:** the file. Around line 41 is a list headed `const COMMANDS: &[&str] = &[`
   with nine names, ending in `"supervision_log_location",`. Just below it is the line
   `check_commands_match_main(COMMANDS);`.

9. Click the pencil icon (**Edit this file**) at the top right of the file. Find the line
   `"supervision_log_location",` inside `COMMANDS` and delete that whole line. Change nothing
   else. ☐

10. Click **Commit changes…**. In the dialog, type the commit message
    `throwaway: drop a command from build.rs (M10-TEST-DEPLOY-221 manual test)`. Choose
    **Create a new branch for this commit and start a pull request**, and name the branch
    `throwaway/221-build-rs-drop`. Click **Propose changes**. ☐

    **You should see:** GitHub move to a page headed **Open a pull request**.
    **Do not click Create pull request.** Leave the page (see *Read this first*).

11. Click the **Actions** tab, then **Desktop shell** in the list on the left. ☐

    **You should see:** a new run at the top of the list, for the branch
    `throwaway/221-build-rs-drop`. It shows a yellow dot, and after a few minutes a
    **red cross**.

12. Click that run, then the job **Desktop shell — cargo check**, then the **cargo check**
    step. Scroll to the end of the step's log. ☐

    **You should see:** a line `error: failed to run custom build command for
    `askwell-shell v0.0.0 …``, followed by the build script's own output. That output
    contains `panicked` and this message:

    ```
    build.rs's command list and `generate_handler!` in src/main.rs differ.
      registered in main.rs but not listed in build.rs: ["supervision_log_location"]
      listed in build.rs but not registered in main.rs: []
    Keep the two identical: a command missing from build.rs has no permission a capability can grant.
    ```

    It names the missing command. It does **not** say `allow-supervision-log-location not found`.
    That permission error is what `0.9.0` said, and it did not name the real cause. Seeing the
    permission error instead of the message above is a defect: it means the check did not run
    first.

13. Go back to the run's summary page. ☐

    **You should see:** the run marked **Failure**, and the failure attributed to the
    **cargo check** step. The install step before it has a green tick.

---

## Part 3 — the other direction: a command listed in `build.rs` but no longer registered

tauri-build would never catch this direction. Only this ticket's check does.

14. Return to the **Code** tab and make sure the branch selector says `main`, not the throwaway
    branch. Click `web`, `src-tauri`, `src`, then `main.rs`. ☐

    **You should see:** around line 53, `.invoke_handler(tauri::generate_handler![`, followed by
    nine names, one per line, ending in `supervision_log_location` and then `])`.

15. Click the pencil icon. Inside `generate_handler![ … ]`, delete the line `read_head,`.
    Change nothing else. ☐

16. Click **Commit changes…**, use the message
    `throwaway: unregister a command in main.rs (M10-TEST-DEPLOY-221 manual test)`, choose
    **Create a new branch…**, name it `throwaway/221-main-rs-drop`, and click
    **Propose changes**. Leave the **Open a pull request** page without creating one. ☐

17. Click **Actions**, then **Desktop shell**, then the new run for
    `throwaway/221-main-rs-drop`. Wait for it to finish. Open the **cargo check** step's log. ☐

    **You should see:** a **red cross**, and near the end of the log:

    ```
      registered in main.rs but not listed in build.rs: []
      listed in build.rs but not registered in main.rs: ["read_head"]
    ```

---

## Part 4 — a push touching nothing in the shell does not run the job

This is the ticket's edge case. It also confirms that no **skipping** check appears, which is
the reason the job lives in its own workflow.

18. Return to the **Code** tab, with the branch selector on `main`. Click `README.md`, then the
    pencil icon. Add one blank line at the very end of the file. ☐

19. Click **Commit changes…**, use the message
    `throwaway: docs-only push (M10-TEST-DEPLOY-221 manual test)`, choose
    **Create a new branch…**, name it `throwaway/221-docs-only`, and click **Propose changes**.
    Leave the **Open a pull request** page without creating one. ☐

20. Click **Actions**. In the list on the left, click **All workflows**. ☐

    **You should see:** a new **CI** run for `throwaway/221-docs-only`. `ci.yml` runs on every
    push, as it always has. There is **no** **Desktop shell** run for that branch. To be sure,
    click **Desktop shell** in the list on the left. Its newest runs are the two red ones from
    Parts 2 and 3, and none is for `throwaway/221-docs-only`.

21. Click the **Code** tab. Open the branch selector and choose `throwaway/221-docs-only`. Next
    to the latest commit message above the file list, there is a small status icon. Click it. ☐

    **You should see:** a list of checks for that commit that contains only **CI** checks. There
    is no **Desktop shell** entry, and nothing marked **Skipped** or **skipping**. Once CI
    finishes, every entry has a green tick.

---

## Clean up

22. Click the **Code** tab, then the branch count beside the branch selector (it reads
    something like **N Branches**). Find `throwaway/221-build-rs-drop`,
    `throwaway/221-main-rs-drop` and `throwaway/221-docs-only`. Click the trash-can icon on each
    row. ☐

    **You should see:** each row disappear. None of the three appears under **Pull requests**,
    open or closed. If one does, a pull request was opened by mistake. Close it without merging
    before the watchdog's next run, and check that `main`'s history on the **Code** tab does
    not contain any commit whose message starts with `throwaway:`.

---

## Part 5 (optional) — reproduce the check locally (Stand-in)

**Stand-in**, because the user of this ticket meets it on GitHub. This is for someone who wants
to see the same failure on their own machine before pushing. This Fedora host does **not** have
the WebKitGTK development package (`pkg-config` does not find `webkit2gtk-4.1`), so
`scripts/dev.sh tauri` cannot compile the shell here. The command below runs the same check in a
Debian container instead. It downloads the Rust image, the system packages and the crates, which
is build-time network use, the same kind as `scripts/dev.sh lock`. Nothing checked reaches the
network.

23. In a terminal: ☐

    ```
    cd ~/external/quantum-plus/askwell
    podman run --rm -v "$PWD/web/src-tauri:/src:Z" -w /src docker.io/library/rust:1-bookworm \
      bash -c 'apt-get update -qq && apt-get install -y -qq libwebkit2gtk-4.1-dev libgtk-3-dev \
        librsvg2-dev libayatana-appindicator3-dev libxdo-dev libssl-dev build-essential >/dev/null \
        && CARGO_TARGET_DIR=/tmp/target cargo check --locked'
    echo "exit: $?"
    ```

    **You should see:** the check end with a `Finished` line, then `exit: 0`. The run took
    70 seconds for `cargo check` when measured, plus the package download.

24. Remove `"supervision_log_location",` from `COMMANDS` in `web/src-tauri/build.rs` in your
    editor, run step 23's command again, and then put the line back. ☐

    **You should see:** the same message as in step 12, then `exit: 101`. After you put the line
    back, `git status --short web/src-tauri` shows nothing, or only changes you already had.

---

## What a pass looks like

| # | Check | Pass |
| - | ----- | ---- |
| 3–6 | Shell-touching pull request | **Desktop shell — cargo check** runs and passes; no secret requested |
| 7 | `main` after merge | Green **Desktop shell** run for the merge commit |
| 11–13 | Command missing from `build.rs` | Red, and the message names `supervision_log_location` |
| 17 | Command missing from `main.rs` | Red, and the message names `read_head` |
| 20–21 | Docs-only push | No **Desktop shell** run, and no skipping check |
| 22 | Clean up | Three throwaway branches deleted; no pull request opened; nothing merged |

Any other result is a defect. File it per `AGENTS.md` §8 before continuing.

---

## Known gaps

These are deliberately not built. Do not report them as defects.

- **The shell's own unit tests run in no CI job.** `cargo test` (the navigation guard and the
  supervisor tests) is still run only by hand with `scripts/dev.sh tauri test`. This ticket
  checks that the shell compiles, not that it behaves. Tracked as #829.
- **Linux only.** The workflow does not check the Windows or macOS build. The source is the same
  on every platform except the `cfg(unix)` `libc` dependency, and `release.yml` still builds all
  three before anything ships (`docs/decisions.md`, 2026-09-29).
- **No installers on every push.** Out of scope by the ticket. `release.yml` builds them.
- **Pull requests from forks do not run the workflow.** It listens to `push` only. There is one
  maintainer, and every branch lives in this repository.
- **No cache.** Every run compiles from cold. It fits well inside the 20-minute limit, and a
  restored `target/` could hide a failure (`docs/decisions.md`, 2026-09-29).
- **The apt package list exists in two places**, `shell.yml` and `release.yml`'s Linux job. A
  comment in each says to change both. Nothing enforces it.
- **The check reads `generate_handler!` as a flat list of names.** A module path such as
  `foo::bar` inside the macro would fail the comparison loudly, not silently. That is intended
  until the shell needs one.
- **No regression walk of the desktop app on this host.** `build.rs` passes the same nine
  commands to tauri-build as before, so the window's behaviour is unchanged. This Fedora host
  cannot build the shell (no `webkit2gtk-4.1` development package), so the app is not relaunched
  here. On a machine that can build it, `docs/manual-tests/M7-TAURI-FE-182.md` walks the native
  **Choose a folder** dialog (reached from **Ask** → **Add a source**) and the
  **Open Supervision…** button, which are the commands whose permissions this list controls.
