# Manual test — M11-FIX-SHELL-226, one AI supervisor, and "is it alive" on one clock

**Ticket:** `M11-FIX-SHELL-226`. Two defects, both found on the Windows 11 test VM, fixed:

- **A second supervisor, with a console window.** At sign-in the desktop app and the
  `AskwellInference` scheduled task start together. The app saw no heartbeat yet and started a
  second `askwell-inference` of its own. On Windows that was a plain `python.exe` with a
  console window, and closing the window stopped Askwell's AI. Now the app waits **20 seconds**
  from its own launch (`INFERENCE_SPAWN_GRACE`: the supervisor's 10 s `HEARTBEAT_SECONDS` plus
  10 s) for a supervisor to appear before starting one. When it does start one on Windows, it
  starts it with `CREATE_NO_WINDOW`, and it picks the first real `python.exe` (then `py.exe`)
  on PATH, never the Microsoft Store placeholder under `WindowsApps`.
- **Two clocks.** The API used to call the AI dead when *its own* time minus the `updated_at`
  in `state.json` exceeded 35 s. `updated_at` is written with the host's clock; the API runs in
  Podman's VM, with a different clock. On the Windows VM the WSL clock ran about seven hours
  ahead, and a working AI read as stopped. Now the API calls it dead only when `updated_at` has
  **not changed** for more than 35 s, measured on the API's own clock. `updated_at` stays in the
  file for people reading it.

What changed on disk: `web/src-tauri/src/supervisor.rs` (`start_action`, `bring_up_inference`,
`windows_python_candidates`, `is_store_python_stub`, `spawn_inference`) and
`api/src/askwell/inference/state.py` (`_Observed`, `read`, `_fresh`). The reasoning, and the
alternatives rejected, are in `docs/decisions.md`, 2026-09-30.

**Version under test:** `0.9.14`. Run `cat VERSION` and update this line if the version has
moved on.

**Who runs it:** the orchestrating session, on the Windows 11 test VM (`scripts/winvm.sh`), and
on the Linux build host. The build agent does not run this walkthrough.

**Time:** about sixty minutes for Part 1 if the VM already has Askwell installed from an
earlier ticket's walk, ninety if it must be installed. About twenty minutes for Part 2, ten for
Part 3.

---

## Read this first

**What you need**

- The build host, with the Windows 11 test VM already created (`scripts/winvm.sh create`). The
  VM needs 8 GB of memory. **Do not start it while an eval is running**; the two together do
  not fit on this machine.
- `Askwell-Setup-0.9.14.exe`, built from this branch. Only the release workflow builds it. Run
  **Release** from the Actions tab on this branch with a throwaway tag such as
  `v0.9.14-m11-226`, download the installer from the draft it creates, and delete the draft
  when you are done.
- The three model files on the build host in `~/.local/share/askwell/models/`:
  `Qwen3.5-4B-Q4_K_M.gguf`, `bge-m3-FP16.gguf` and `bge-reranker-v2-m3-FP16.gguf`.
- A VNC viewer, to see and click inside the VM (`127.0.0.1:5905`).

**What "Stand-in" means below.** A step marked **Stand-in** is a terminal command a user would
never run. Each one either counts something no screen shows (how many supervisors are running)
or sets up a condition a user cannot make on purpose (a clock seven hours wrong, a missing
supervisor). Every other step is done by clicking, the way a user would.

**What the status line looks like.** At the top-left of Askwell's window, right of the word
**Askwell**, there is a small coloured dot and a few words. These are the only states this test
looks at:

| Dot | Words | Meaning |
| --- | --- | --- |
| green | **Ready** | The AI is running and answering. |
| amber | **The assistant is starting.** | Loading the model. Normal for up to three minutes on the VM. |
| amber | **The assistant is not running.** | The AI is not running, *or* Askwell has decided it has stopped reporting. |

When the words are **The assistant is not running.**, a box also appears at the top of the main
area with the same heading. If its text contains **The inference supervisor stopped reporting.
Its last state is too old to trust**, Askwell has judged the AI *stale*. That sentence is the
one this ticket is about: before the fix it appeared on the VM while the AI was running.

**What proves this ticket.**

1. After signing in to Windows and opening Askwell, **exactly one** `askwell-inference`
   process runs, and **no console window** appears (Part 1, steps 6–8).
2. With the WSL clock pushed seven hours ahead, the status line **stays** on **Ready** (Part 1,
   steps 10–12). Before this ticket it went to **The assistant is not running.** within a
   minute.
3. Killing the AI still makes the status line leave **Ready** within about a minute — the
   staleness check still works, it just no longer compares two clocks (Part 2, steps 4–5).

---

## Part 1 — Windows 11: sign-in, one supervisor, a skewed clock

### Get to a signed-in desktop with Askwell installed

1. **Stand-in:** on the build host, in the repository folder, boot the VM:

   ```
   scripts/winvm.sh start
   ```

   ☐ **You should see:** `up (ssh on 127.0.0.1:…)`. In the VNC viewer, the Windows desktop.

2. **Stand-in:** find out whether this VM already has Askwell `0.9.14`:

   ```
   scripts/winvm.sh ssh 'Get-Content $env:LOCALAPPDATA\Askwell\app\VERSION -ErrorAction SilentlyContinue'
   ```

   ☐ **You should see:** `0.9.14`. If it prints nothing or an older version, install it: put
   the installer and the models on the VM exactly as in
   `docs/manual-tests/M11-FIX-DEPLOY-225.md`, Part 1 steps 3–7 (with `0.9.14` in place of
   `0.9.13`), then double-click **Askwell-Setup-0.9.14** on the VM's desktop and follow Setup to
   **Askwell is installed**. If Setup opens Askwell at the end, close Askwell's window.

3. Make sure Askwell is not already open. Look at the taskbar. If an Askwell window is open,
   close it with the **×** in its top-right corner.

   ☐ **You should see:** no Askwell window.

### Sign out and in — the moment the defect happened

4. Sign out of Windows: click **Start**, click your account picture or name, click **Sign
   out**.

   ☐ **You should see:** the Windows sign-in screen.

5. Sign in again. As soon as the desktop appears — do not wait — click **Start**, type
   `Askwell`, and click **Askwell**. Opening it quickly is the point: the scheduled task is
   starting the AI at this same moment, which is when the app used to start a second one.

   ☐ **You should see:** Askwell's window, showing **Starting Askwell** and then its main
   screen (or **Welcome to Askwell** if first run was never finished on this VM — finish it by
   clicking **Get started**, **Not now**, **Continue**, **Continue**, as in
   `M11-FIX-DEPLOY-225.md` Part 1 step 9).

6. **Watch the screen for the next 60 seconds.** Do not click anything.

   ☐ **You should see:** Askwell's window, and nothing else new on the desktop.

   ☐ **You should not see:** a black console window, titled with a path ending in
   `python.exe`, appear at any point. That window is the defect. If one appears, do **not**
   close it (closing it stops the AI); take a screenshot
   (`scripts/winvm.sh screenshot /tmp/226-console.png` on the build host) and record it.

7. Look at the status line at the top-left of Askwell's window. Give it up to three minutes.

   ☐ **You should see:** the amber dot with **The assistant is starting.** for a while, then
   the green dot with **Ready**.

8. **Stand-in:** count the AI supervisors. On the build host:

   ```
   scripts/winvm.sh ssh 'Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*askwell-inference*" } | Select-Object ProcessId, Name, CommandLine | Format-List'
   ```

   ☐ **You should see:** **exactly one** entry. Its `Name` is `pythonw.exe` and its
   `CommandLine` ends in `--env-file "…\Askwell\app\.env"` — that is the scheduled task's
   supervisor, adopted by the app.

   ☐ **You should not see:** a second entry named `python.exe` (with no `w`) whose command line
   has no `--env-file`. That is a supervisor the app started itself: the defect.

   Run the command again two minutes later. ☐ Still exactly one.

9. Repeat steps 3–8 once more (close Askwell, sign out, sign in, open Askwell straight away,
   count). A race can pass once by luck.

   ☐ **You should see:** the same result: one supervisor, no console window, **Ready**.

### Push the VM's Linux clock seven hours ahead

This reproduces the condition from the original report: the clock inside WSL, where Askwell's
containers run, seven hours ahead of Windows, where the AI writes its heartbeat.

10. **Stand-in:** find Podman's WSL machine and push its clock ahead:

    ```
    scripts/winvm.sh ssh 'wsl.exe -l -v'
    ```

    Note the name of the Podman machine (usually `podman-machine-default`). Then, using that
    name:

    ```
    scripts/winvm.sh ssh 'wsl.exe -d podman-machine-default -u root date -s "+7 hours"; wsl.exe -d podman-machine-default date; Get-Date'
    ```

    ☐ **You should see:** two times printed, the WSL one about seven hours later than the
    Windows one. If they are within a few minutes of each other, the skew did not take (WSL may
    have resynchronised at once); run the `date -s` command again and check before going on.
    This step is not valid without the seven-hour gap.

11. In Askwell's window, look at the status line. Watch it for **two full minutes** without
    clicking. The API re-reads the AI's state every few seconds, and before this ticket a gap
    this size made it give up at the first read.

    ☐ **You should see:** the green dot and **Ready**, the whole time.

    ☐ **You should not see:** the amber dot with **The assistant is not running.**, or a box
    in the main area containing **The inference supervisor stopped reporting.** Either one,
    while step 8's supervisor is still running, is this ticket's defect.

12. Click **Settings** in the rail on the left. Scroll to **Model and speed**.

    ☐ **You should see:** the model name (for example **Qwen3.5-4B-Q4_K_M.gguf**) and, in the
    **Hardware profile** block, `Answers run on the processor.` — not **Not measured — the
    assistant is not running.**

    Click **Ask** in the rail to return to the main screen. ☐ Still **Ready**.

13. **Stand-in:** put the WSL clock back:

    ```
    scripts/winvm.sh ssh 'wsl.exe -d podman-machine-default -u root hwclock -s 2>$null; wsl.exe -d podman-machine-default -u root date -s "-7 hours"; wsl.exe -d podman-machine-default date; Get-Date'
    ```

    ☐ **You should see:** the two times within a minute of each other. If not, restart WSL
    (`scripts/winvm.sh ssh 'wsl.exe --shutdown'`), wait a minute, and open Askwell again; it
    brings the stack back up.

### The AI dies while the clock is skewed

14. Push the clock ahead again (repeat step 10's second command) and confirm the seven-hour gap.
    Then **Stand-in:** kill the supervisor outright, the way a crash would:

    ```
    scripts/winvm.sh ssh 'Stop-ScheduledTask AskwellInference; Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*askwell-inference*" -or $_.Name -eq "llama-server.exe" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }'
    ```

15. Watch the status line in Askwell's window for up to **one and a half minutes**.

    ☐ **You should see:** it leave **Ready**. The app notices the AI has gone and, since it is
    well past its 20-second wait, starts one of its own. You will see the amber dot and **The
    assistant is starting.** (the app's own supervisor loading the model), then, within three
    minutes, **Ready** again. Seeing **The assistant is not running.** in between is fine.

    ☐ **You should not see:** a console window appear when the app starts its own supervisor.

16. **Stand-in:** count again (step 8's command).

    ☐ **You should see:** exactly one entry. This time its `Name` is `python.exe` and its path
    is **not** under `…\Microsoft\WindowsApps\`: it is the app's own, started without a window,
    from the real Python Setup installed.

17. Put the clock back (step 13). Close Askwell's window. Sign out and sign in again, so the
    scheduled task owns the AI once more for whoever uses the VM next.

---

## Part 2 — Linux build host: the edge cases

The Linux host has one clock for everything, so the skew cannot happen here. This Part covers
the two edge cases the ticket names: **no supervisor at all** (the app still starts one, after
its wait) and **the API started before the supervisor**. It also covers the app's log line,
which on Linux can be read by opening Askwell from a terminal. (On Windows the release build has
no console to print to; see Known gaps.)

It uses an installed Askwell (`deploy/linux/install.sh`, run earlier on this host). If Askwell
is not installed here, walk `M11-FIX-DEPLOY-225.md` Part 2 on a VM instead and do steps 1–7
there.

1. **Stand-in:** build and install this branch:

   ```
   cd ~/external/quantum-plus/askwell
   deploy/linux/install.sh
   ```

   ☐ **You should see:** the installer finish without an error.

2. **Stand-in:** stop the AI supervisor the session started, so there is none at all:

   ```
   systemctl --user stop askwell-inference.service
   ```

3. **Stand-in:** open Askwell from a terminal, so its log lines are visible, and note the time:

   ```
   date +%T; askwell
   ```

   ☐ **You should see:** Askwell's window open. In the terminal, within a second or two, a line
   containing `"event":"supervisor_inference_waiting"` and `"reason":"waiting for a supervisor
   the session may be starting"` — printed **once**, not repeated every second or two.

4. In Askwell's window, look at the status line during the first 20 seconds.

   ☐ **You should see:** the amber dot and **The assistant is not running.** — there is no AI
   yet, and the app is waiting. That is expected.

5. Keep watching. About 20 seconds after the time noted in step 3, the app gives up waiting and
   starts its own supervisor.

   ☐ **You should see:** **The assistant is starting.**, then within a minute or two, the green
   dot and **Ready**.

   **Stand-in:** in a second terminal, `pgrep -af askwell-inference`.
   ☐ Exactly one line, started by the app (no `--env-file` in it).

6. Close Askwell's window. **Stand-in:** start the session's supervisor again, then open
   Askwell from the terminal once more:

   ```
   systemctl --user start askwell-inference.service; sleep 15; askwell
   ```

   ☐ **You should see:** in the terminal, `"event":"supervisor_inference_adopted"` **once**, and
   no `supervisor_inference_waiting` line. The status line reaches **Ready** without the app
   starting anything: `pgrep -af askwell-inference` shows one line, with `--env-file`.

7. **The API started before the supervisor.** Close Askwell's window. **Stand-in:**

   ```
   systemctl --user stop askwell-inference.service
   podman restart askwell-api-1
   systemctl --user start askwell-inference.service
   askwell
   ```

   ☐ **You should see:** the status line go from **The assistant is starting.** to **Ready**
   within three minutes, and stay there for two more minutes of watching. It must not settle on
   **The assistant is not running.** while `pgrep -af askwell-inference` shows the supervisor.

8. **A killed AI is still noticed.** With the status line on **Ready**, **Stand-in:**

   ```
   systemctl --user kill -s KILL askwell-inference.service; pkill -KILL -f llama-server
   ```

   ☐ **You should see:** within about 45 seconds, the status line leave **Ready**. The box in
   the main area reads **The assistant is not running.**, and its text either says the AI is
   not running or contains **The inference supervisor stopped reporting.** Staleness still
   works; it is measured by the file not changing, not by comparing clocks.

   systemd restarts the unit on its own; the status line returns to **Ready** within a few
   minutes. Close Askwell.

---

## Part 3 — automated, every push

| Command | What it covers |
| --- | --- |
| `scripts/dev.sh test tests/test_inference.py` | A `state.json` whose `updated_at` is seven hours in the future **and changing** is fresh; one **not changing** for longer than 35 s on the API's clock is stale; a supervisor that comes back is believed again; the API started before the supervisor; a stale role is not believed; the module never calls `time.time` (checked through the AST) |
| `scripts/dev.sh test tests/test_assistant.py` | A supervisor killed outright is reported unavailable once its heartbeat stops changing |
| `cd web/src-tauri && cargo test` | `HEARTBEAT_SECONDS` matches `deploy/inference/askwell-inference`; within the grace period no heartbeat means wait, a heartbeat means adopt; after it, no heartbeat means spawn; Windows candidates are every `python.exe` then every `py.exe` in PATH order, never under `WindowsApps`, only files that exist |
| `cd web/src-tauri && cargo check` | The shell builds (the Windows-only `CREATE_NO_WINDOW` branch is compiled only by the Windows workflow) |
| `scripts/dev.sh check`, `scripts/dev.sh test-db` | Everything else |

---

## Known gaps

These are not built yet, or not verified. Do not report them as defects of this ticket.

- **A supervisor the app starts itself can stall after some hours** (#866). The app pipes its
  output and never reads it; once the pipe fills, the supervisor blocks, and the status line
  will eventually show it as stopped. Part 1 step 15 and Part 2 step 5 run far too briefly to
  hit this. The scheduled task and the systemd unit are not affected.
- **The hardware probe's "stale" flag still compares two clocks** (#867). With the WSL clock
  skewed, **Settings → Model and speed** may say the hardware reading is out of date even
  though the AI is **Ready**. That is not the status line this ticket fixed.
- **The app's "waiting" and "adopted" log lines are not visible on Windows.** The release build
  is a windowed program with no console, and it prints them to standard output. They are
  checked on Linux (Part 2) only.
- **A dead AI's last `ready` is believed for up to 35 seconds after the API starts.** The API
  has no history until its first read. This is deliberate and recorded in
  `docs/decisions.md`, 2026-09-30; it is the same bound a killed supervisor always had.
- **An installation with no supervisor at all waits 20 seconds** at every launch before the app
  starts one. Deliberate: nothing distinguishes "about to appear" from "not installed" earlier.
- **macOS is not walked** (#854). The LaunchAgent starts at sign-in the same way the scheduled
  task does, and the same wait applies, but no Mac is available.
- **The Microsoft Store placeholder is covered by the Rust test only.** The test VM has a real
  Python installed by Setup; a VM with only the placeholder is not part of this walk.
- **Models are placed by hand** (#802, #810), as in `M11-FIX-DEPLOY-225.md`.

---

## Result

| Part | Date | Version | Who | Result | Notes |
| ---- | ---- | ------- | --- | ------ | ----- |
| 1 | | | | | |
| 2 | | | | | |
| 3 | | | | | |
