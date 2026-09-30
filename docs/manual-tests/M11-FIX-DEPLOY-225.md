# Manual test — M11-FIX-DEPLOY-225, the AI starts on an installed Askwell

**Ticket:** `M11-FIX-DEPLOY-225`. Before this ticket, an installed `0.9.11` brought its stack
up and `/health` answered, but the assistant never started, on Linux or Windows (and very likely
macOS). The window's status line said **The assistant is not running.** or **The assistant has
no model file.** and nothing on screen said why. What changed:

- **The AI supervisor is given the install's settings.** Every installer now starts
  `askwell-inference --env-file <app>/.env`: the systemd unit on Linux (which also sets
  `WorkingDirectory=<app>`), the LaunchAgent on macOS (with `WorkingDirectory`), and the
  `AskwellInference` scheduled task on Windows. The supervisor reads the file's `ASKWELL_`
  settings below its own environment, ignores the file's `ASKWELL_INFERENCE_SOCKET` (that is
  the containers' path), and writes its socket and `state.json` in `ASKWELL_RUN_DIR` resolved
  against the app folder, `<app>/.run` by default. Its first log line names the file and the
  state folder, and never a value from the file.
- **Windows: Setup installs Microsoft's Visual C++ runtime** when `vcruntime140.dll`,
  `vcruntime140_1.dll` or `msvcp140.dll` is missing from System32. It downloads
  `https://aka.ms/vs/17/release/vc_redist.x64.exe`, logs its version, signature status and
  signer, and runs it with `/install /quiet /norestart` only if the signature is `Valid` and the
  signer begins `CN=Microsoft Corporation,`. Codes 0, 3010 and 1638 count as success. Anything
  else, or a refused signature, stops Setup with the new code 28 and a report.
- **Linux: the installer installs Docker Compose and the OpenMP runtime** in the same command,
  with the same one password prompt, as Podman: `docker-compose-v2 libgomp1` on Ubuntu (and
  distributions that say `ID_LIKE=ubuntu`), `docker-compose libgomp` on Fedora. A machine that
  already had Podman and Docker Compose but no `libgomp.so.1` is offered `libgomp1`/`libgomp` on
  its own. Debian has no `docker-compose-v2`, so on Debian it still stops and names what to
  install.

**Version under test:** `0.9.13`. Run `cat VERSION` and update this line if the version has
moved on.

**Who runs it:** the orchestrating session, on the Windows 11 test VM (`scripts/winvm.sh`) and
a clean Ubuntu 24.04 VM. The build agent does not run this walkthrough.

**Time:** about ninety minutes for Part 1, most of it Setup's downloads and the WSL restart.
About forty minutes for Part 2. Part 3 takes ten minutes.

---

## Read this first

**What you need**

- The build host, with the Windows 11 test VM already created (`scripts/winvm.sh create`), on
  its clean snapshot. The VM needs 8 GB of memory. **Do not start it while an eval is
  running**; the two together do not fit on this machine.
- A clean Ubuntu 24.04 desktop VM, with a snapshot taken right after its first sign-in: no
  Podman, no Docker Compose, nothing installed by hand. The account must be able to use
  `sudo`.
- A VNC viewer (or the VM's own console) to see and click inside each VM.
- Release artefacts built from this branch: `Askwell-Setup-0.9.13.exe` and
  `askwell-0.9.13-linux-x86_64.tar.gz`. Only the release workflow builds them. Run **Release**
  from the Actions tab on this branch with a throwaway tag such as `v0.9.13-m11-225`, download
  both from the draft it creates, and delete the draft when you are done.
- The three model files, on the build host in `~/.local/share/askwell/models/`:
  `Qwen3.5-4B-Q4_K_M.gguf`, `bge-m3-FP16.gguf` and `bge-reranker-v2-m3-FP16.gguf`. The ticket's
  walkthrough is "with the models placed". The first-run download is not used here, because of
  #802 and #810 (see Known gaps).
- `eval/fixtures/corpus/handbook_a.pdf`. Page 2 reads "The standard notice period for
  resignation at Meridian Loom is sixty-three days."

**What "Stand-in" means below.** A step marked **Stand-in** is a terminal check or a file copy
that a user would never do. It either confirms something the screen cannot show, or it works
around a gap that is not this ticket's. Every other step is done the way a user would: by
double-clicking, clicking, or (on Linux, where the documented install is a terminal command) by
typing the command `docs/installing.md` gives.

**What proves this ticket.** The status line at the top of Askwell's window reads **Ready**
with a green dot, *without anyone having started anything by hand*. Before this ticket it never
did on an installed Askwell. An answered question is the stronger proof, but it also needs
folder access (#771, `M11-FIX-BE-227`), which is not this ticket's.

---

## Part 1 — a clean Windows 11 PC

### Install

1. **Stand-in:** in a terminal on the build host, in the repository folder, reset the VM and
   boot it:

   ```
   scripts/winvm.sh reset && scripts/winvm.sh start
   ```

   ☐ **You should see:** the command return without an error. In the VNC viewer at
   `127.0.0.1:5905`, the Windows desktop, signed in.

2. **Stand-in:** confirm the starting point — no Visual C++ runtime:

   ```
   scripts/winvm.sh ssh 'foreach ($d in "vcruntime140.dll","vcruntime140_1.dll","msvcp140.dll") { "$d " + (Test-Path "$env:SystemRoot\System32\$d") }'
   ```

   ☐ **You should see:** at least one of the three lines end in `False`. If all three say
   `True`, this snapshot is not clean for this ticket: the runtime step will be skipped. Record
   that and carry on; step 9 still checks the skip.

3. **Stand-in:** put Setup on the VM's desktop, and the three models where Askwell reads them:

   ```
   scripts/winvm.sh put Askwell-Setup-0.9.13.exe 'C:/Users/Public/Desktop/Askwell-Setup-0.9.13.exe'
   scripts/winvm.sh ssh 'New-Item -ItemType Directory -Force $env:USERPROFILE\.local\share\askwell\models | Out-Null'
   for f in Qwen3.5-4B-Q4_K_M.gguf bge-m3-FP16.gguf bge-reranker-v2-m3-FP16.gguf; do
     scripts/winvm.sh put ~/.local/share/askwell/models/$f "C:/Users/<vm-user>/.local/share/askwell/models/$f"
   done
   ```

   Replace `<vm-user>` with the VM's user name (`scripts/winvm.sh ssh '$env:USERNAME'`).

   ☐ **You should see:** **Askwell-Setup-0.9.13** on the VM's desktop.

4. In the VM, double-click **Askwell-Setup-0.9.13**.

   ☐ **You should see:** **Windows protected your PC**, because Setup is not code-signed. Click
   **More info**, then **Run anyway**. At the User Account Control prompt, click **Yes**.

5. ☐ **You should see:** a window titled **Install Askwell 0.9.13**. Click **Next**. On the
   licence page, click **I Agree**.

6. Setup's progress page opens, with the details list below the bar. Watch it.

   ☐ **You should see**, after the line that starts `Python:`, these lines, in this order:
   - `Downloading Microsoft's Visual C++ runtime, which Askwell's AI needs (about 25 MB)...`
   - `  Installer version <n>, signature Valid, signed by: CN=Microsoft Corporation, O=Microsoft Corporation, ...`
   - `Installing Microsoft's Visual C++ runtime...`
   - `  Installed (code 0).` — or `(code 3010)`, which also counts as success.
   - `Visual C++ runtime: <a version number>`

   ☐ **You should not see:** `It is not validly signed by Microsoft, so it was not run.`, `The
   download failed`, `The installer stopped with code`, or Setup stopping with **code 28**.
   Any of these means the runtime step failed. Record the whole details list.

   If step 2 found all three DLLs, you see only the `Visual C++ runtime: <version>` line, with
   no download.

7. On a clean VM, Setup enables WSL and needs one restart.

   ☐ **You should see:** the finish page titled **One restart to finish**, with **Restart now**
   selected. Click **Finish**. The VM restarts. Sign in again if Windows asks.

   ☐ **You should see:** a window open by itself and carry on with the install. Do not run
   Setup again. When it is done, the finish page says **Askwell is installed**.

   If the first finish page already said **Askwell is installed**, WSL was already there; go on.

### First run, and the AI starting by itself

8. Askwell's window opens by itself. If it does not, click **Start**, type `Askwell`, and click
   **Askwell**.

   ☐ **You should see:** **Starting Askwell** for a while, then **Welcome to Askwell**.

9. In **Welcome to Askwell**, step 1, click **Get started**. On step 2, **Check the machine**,
   under **Set a passphrase?**, click **Not now**, then **Continue**.

   ☐ **You should see:** step 3, **Get the model**, already showing **Ready.** — because the
   model file is in place (step 3 of this Part). There is no **Download** button to press.
   Click **Continue**.

   ☐ **If instead** you see a **Download** button: the file is not where Askwell looks for it,
   or not at its full size. That is a setup mistake in step 3, not this ticket's defect. Check
   the file name and copy it again.

10. **The ticket's main check.** Look at the top of Askwell's window, at the small status line
    next to a coloured dot. Give it up to three minutes; loading a model on the VM's processor
    is slow.

    ☐ **You should see:** a green dot and **Ready**. You may first see an amber dot with
    **The assistant is starting.** — that is normal while it loads.

    ☐ **You should not see**, for more than three minutes:
    - **The assistant is not running.** — the supervisor's state never reached Askwell. This
      is the defect this ticket fixes (its state went to `C:\run\askwell`).
    - **The assistant has no model file.** — the supervisor started without the install's
      settings, so it looked for the model at `.`. Also this ticket's defect.
    - **The assistant stopped and is restarting.**, repeatedly — likely `llama-server.exe`
      exiting with `0xC0000135`, the missing Visual C++ runtime.

    Hover over the status line or move on; nothing needs clicking to make it change. Do not
    run anything by hand to get it to **Ready**: the whole point is that nobody has to.

11. **Stand-in:** confirm why it worked, and where the state went:

    ```
    scripts/winvm.sh ssh '(Get-ScheduledTask AskwellInference).Actions | Select Execute, Arguments | Format-List; Test-Path $env:LOCALAPPDATA\Askwell\app\.run\state.json; Test-Path C:\run\askwell'
    ```

    ☐ **You should see:**
    - `Execute` ending in `pythonw.exe`.
    - `Arguments` exactly `"C:\Users\<vm-user>\AppData\Local\Askwell\app\askwell-inference" --env-file "C:\Users\<vm-user>\AppData\Local\Askwell\app\.env"`, both paths in double quotes.
    - `True` — the state file is in the app's own `.run` folder.
    - `False` — nothing was written to `C:\run\askwell`.

12. Click **Settings** in the rail on the left. Find **Model and speed**, and in it the
    **Hardware profile** block.

    ☐ **You should see:** `Answers run on the processor.` (the VM has no graphics card). That
    line comes from the supervisor's `state.json`; seeing it at all means the API is reading the
    file from `<app>\.run`.

### Ask a question (only if folder access works)

13. Click **Library** in the rail, then **Add a source**. Under **Files**, click **Choose
    files**. Copy `handbook_a.pdf` in first if it is not on the VM (**Stand-in:**
    `scripts/winvm.sh put eval/fixtures/corpus/handbook_a.pdf 'C:/Users/<vm-user>/Documents/handbook_a.pdf'`),
    then pick `Documents\handbook_a.pdf` and click **Open**.

    ☐ **You should see:** `handbook_a.pdf` in the Library, going through indexing to **ready**
    within a few minutes.

    ☐ **Likely instead, until #771 / `M11-FIX-BE-227` lands:** the file is recorded but shown
    as not readable, with `Askwell has no window onto your filesystem yet. Set
    ASKWELL_ROOTS_MOUNT in .env …`. That is not this ticket. Record it and skip step 14. Do
    not edit `.env` to get past it.

14. Only if step 13 reached **ready**: click **Ask** in the rail. Type
    **What is the standard resignation notice period at Meridian Loom?** and press **Enter**.

    ☐ **You should see:** an answer saying **sixty-three days**, with a citation to
    `handbook_a.pdf`, page 2. Click the citation; that page opens.

### Setup a second time

15. Double-click **Askwell-Setup-0.9.13** on the desktop again and go through steps 4–5.

    ☐ **You should see**, in the details list: `Visual C++ runtime: <version>` and **no**
    `Downloading Microsoft's Visual C++ runtime` line. The runtime is present, so the step is
    skipped. The finish page says **Askwell is installed**.

16. Sign out of Windows (**Start** → your name → **Sign out**), and sign back in. Click
    **Start**, type `Askwell`, click **Askwell**.

    ☐ **You should see:** within three minutes, the status line reads **Ready** again. The
    scheduled task started the supervisor at sign-in, with its settings, with nobody's help.

---

## Part 2 — a clean Ubuntu 24.04 desktop

### Install

1. **Stand-in:** restore the Ubuntu VM to its clean snapshot, boot it and sign in. Copy
   `askwell-0.9.13-linux-x86_64.tar.gz` into the VM user's **Downloads** folder, and the three
   model files into `~/.local/share/askwell/models/` (make the folder first).

2. **Stand-in:** confirm the starting point, in a terminal inside the VM:

   ```
   command -v podman docker-compose; ls /usr/libexec/docker/cli-plugins 2>/dev/null; ldconfig -p | grep libgomp
   ```

   ☐ **You should see:** nothing at all. No Podman, no Docker Compose, no `libgomp.so.1`. If
   `libgomp` is listed, the image already has it; the install then leaves it out of the command
   in step 4. Record that.

3. Open **Terminal** (from the applications grid) and type the two commands
   `docs/installing.md` gives for Linux:

   ```
   cd ~/Downloads
   tar -xzf askwell-0.9.13-linux-x86_64.tar.gz
   askwell-0.9.13-linux-x86_64/deploy/linux/install.sh
   ```

4. ☐ **You should see:**

   ```
   Podman is not installed. This installer needs to run:
     sudo apt-get update && apt-get install -y podman docker-compose-v2 libgomp1
   ```

   and then the question **Install Podman and docker-compose-v2 libgomp1 now?** Answer `y`,
   and type your password when `sudo` asks. **This is the only password prompt of the whole
   install.**

   ☐ **You should not see:** a second password prompt for Docker Compose or for the OpenMP
   runtime, or the message telling you to install Docker Compose yourself
   (`docs.docker.com/compose/install/linux`). That was the `0.9.11` behaviour.

5. Let the install run.

   ☐ **You should see**, among its lines:
   - `Compose provider found: Docker Compose version v2.<n>` (or `Compose provider installed: …`)
   - `OpenMP runtime found (libgomp.so.1)`

   and then the install finishing and the Askwell window opening by itself.

   ☐ **You should not see:** `Askwell's AI runs llama.cpp, which needs the OpenMP runtime
   (libgomp.so.1), and this machine has none.` — that would mean `libgomp1` was left out of
   step 4's command.

### First run, and the AI starting by itself

6. ☐ **You should see:** the Askwell window, **Starting Askwell**, then **Welcome to Askwell**.
   If it does not open, open the applications grid, type `Askwell`, and click it.

7. Click **Get started**. On **Check the machine**, click **Not now** under **Set a
   passphrase?**, then **Continue**.

   ☐ **You should see:** **Get the model** already showing **Ready.** Click **Continue**.

8. **The ticket's main check.** Watch the status line at the top of the window, for up to three
   minutes.

   ☐ **You should see:** a green dot and **Ready**, possibly after **The assistant is
   starting.**

   ☐ **You should not see**, for more than three minutes: **The assistant is not running.**
   (in `0.9.11` the supervisor could not write its state: `Permission denied: '/run/askwell'`),
   **The assistant has no model file.** (`No model file at .`), or **The assistant stopped and
   is restarting.** over and over (`libgomp.so.1: cannot open shared object file`).

9. **Stand-in:** confirm why, in the VM's terminal:

   ```
   grep -E '^(WorkingDirectory|ExecStart|EnvironmentFile)' ~/.config/systemd/user/askwell-inference.service
   journalctl --user -u askwell-inference -n 30 --no-pager
   ls ~/.local/share/askwell/app/.run/
   ```

   ☐ **You should see:**
   - `WorkingDirectory=/home/<user>/.local/share/askwell/app`
   - `ExecStart=/home/<user>/.local/share/askwell/app/askwell-inference --env-file /home/<user>/.local/share/askwell/app/.env`
   - no `EnvironmentFile=` line.
   - in the journal: `askwell-inference: settings from /home/<user>/.local/share/askwell/app/.env, state in /home/<user>/.local/share/askwell/app/.run`.
   - `state.json` (and `inference.sock`) in the `.run` folder.

   ☐ **You should not see**, in the journal: `No model file at .`, `Permission denied:
   '/run/askwell'`, `libgomp.so.1`, or any password or other value from `.env` (C8).

10. Click **Settings** in the rail. Under **Model and speed**, in **Hardware profile**:

    ☐ **You should see:** `Answers run on the processor.` (or `on the graphics card.` if the VM
    has one passed through).

11. Try steps 13 and 14 of Part 1 here: **Library** → **Add a source** → **Choose files**,
    pick `handbook_a.pdf` (copy it into the VM's **Documents** first), then **Ask** the same
    question.

    ☐ **You should see:** **sixty-three days**, cited to `handbook_a.pdf`, page 2 — or, until
    #771 lands, the file shown as not readable. Record which.

12. **After a restart.** Restart the VM (top-right menu → **Power Off / Log Out** →
    **Restart**), sign in, and open **Askwell** from the applications grid.

    ☐ **You should see:** the status line reach **Ready** within three minutes, with nothing
    started by hand. The systemd user unit started the supervisor at sign-in, with its
    settings.

---

## Part 3 — automated, every push

| Command | What it covers |
| --- | --- |
| `scripts/dev.sh test tests/test_inference_env_file_host.py` | `--env-file`: values read; the environment always wins; `=` inside a value; quotes, comments, `export`, a byte-order mark; an empty value means the default; state in `ASKWELL_RUN_DIR` beside the file, absolute, or under `~`; the file's socket ignored; an explicit socket wins; nothing copied into `os.environ`, and no non-`ASKWELL_` name kept; a missing file stops with a reason and no traceback |
| `bash deploy/linux/install.test.sh` | Podman, `docker-compose-v2`/`docker-compose` and `libgomp1`/`libgomp` in one apt or dnf command; Ubuntu and `ID_LIKE=ubuntu` get `docker-compose-v2`, Debian gets no guessed name; a present compose or OpenMP is left out; `libgomp.so.1` read from `ldconfig -p`; `check_openmp_runtime` carries on or refuses by name; the unit's `--env-file` and `WorkingDirectory=`, and no `EnvironmentFile=` |
| `bash deploy/macos/install.test.sh` | The LaunchAgent passes `--env-file <app>/.env` and sets `WorkingDirectory` |
| `deploy/windows/install.test.ps1` (Windows workflow) | Task arguments with `--env-file`, paths quoted; the signature check accepts Microsoft's and refuses tampered, unsigned, unverifiable, someone else's, look-alike and lower-case subjects; 0/3010/1638 success, 1603 failure; the three DLLs; code 28's report meaning |
| `deploy/windows/setup/setup-bootstrap.test.ps1` (Windows workflow) | Runtime missing: downloaded, signature logged, run quietly, then Askwell. Not Microsoft's, or a broken signature: refused, never run, file deleted, code 28 with a report. Present: skipped, nothing downloaded. 1638: success. 1603: code 28 |
| `scripts/dev.sh check` | Everything else |

---

## Known gaps

These are not built yet, or not verified. Do not report them as defects of this ticket.

- **The models are placed by hand in both walkthroughs.** Nothing fetches the embedding and
  reranker models (#810), and first run's download may save the answering model under a name
  the supervisor does not load (#802). The ticket's own walkthrough is "with the models
  placed"; so is this one.
- **A fresh install cannot read a file the user adds** (#771; folder access is
  `M11-FIX-BE-227`). Part 1 step 13 and Part 2 step 11 will most likely show the file as not
  readable. The status line reaching **Ready** is this ticket's proof; the answered question
  is a bonus until that lands.
- **The desktop app does not start its own supervisor** (`M11-FIX-SHELL-226`). It relies on the
  scheduled task (Windows) or the systemd user unit (Linux) started at sign-in. If Askwell is
  opened in a session where those did not run, the status line can stay on **The assistant is
  not running.** That is 226, not this ticket.
- **macOS is not walked** (#854). The LaunchAgent change is covered only by
  `deploy/macos/install.test.sh` and an `xmllint` check of the plist.
- **Debian is still refused for Docker Compose.** It has no `docker-compose-v2` package, so the
  installer stops and names what to install, as before. Fedora's `docker-compose libgomp` path is
  covered by `install.test.sh` only; no Fedora VM walk is part of this ticket.
- **A refused Visual C++ signature, and code 1638, are tested only in
  `setup-bootstrap.test.ps1`.** A real VM always downloads Microsoft's genuine file, and a clean
  snapshot has no newer runtime installed.
- **The Visual C++ runtime is downloaded, not bundled.** Setup needs the internet for it, as it
  does for Python and WSL. An offline Windows install without the runtime stops at code 28.
- **A graphics card is untested on Windows** (#590). The VM shows the processor.

---

## Result

| Part | Date | Version | Who | Result | Notes |
| ---- | ---- | ------- | --- | ------ | ----- |
| 1 | | | | | |
| 2 | | | | | |
