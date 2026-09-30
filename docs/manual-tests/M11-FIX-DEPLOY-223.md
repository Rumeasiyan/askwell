# Manual test — M11-FIX-DEPLOY-223, the containers reach the AI on Windows

**Ticket:** `M11-FIX-DEPLOY-223` (issue #845). Before this ticket, Askwell installed on Windows,
opened, and downloaded its model, and then could not answer anything. `llama-server` runs on
Windows itself, for the graphics card, and listens on `127.0.0.1`. The inference bridge runs
inside Podman's WSL machine and also dials `127.0.0.1`. Under WSL's default NAT networking, that
address is the VM's own loopback, so the dial is refused. What changed:

- **Setup turns on WSL's mirrored networking.** Before Podman's machine is created or started,
  Setup makes sure `%USERPROFILE%\.wslconfig` has `networkingMode=mirrored` under `[wsl2]`. It
  edits the file rather than replacing it, keeps its encoding (UTF-16 included), and writes one
  line in its log saying exactly what it did. If it changed the file while Podman's machine was
  running, it runs `wsl --shutdown` and starts the machine again.
- **Setup refuses Windows older than build 22621** (Windows 11 22H2) with code 26, before it
  installs anything. If it cannot write `.wslconfig`, it stops with code 27.
- **On Windows, the two Unix sockets moved to a Podman volume.** `inference.sock` and
  `worker-unlock.sock` now live on the `askwell-sockets` volume, at `/run/askwell-sockets`.
  `install.ps1` writes `ASKWELL_SOCKET_DIR=/run/askwell-sockets` into the installed `.env` on
  every install and upgrade. The host supervisor's `state.json` stays on the run-directory bind
  mount, because Windows has to reach it.
- **The bridge logs its socket path before it binds** (`inference_bridge_starting`). A socket
  directory that cannot hold a socket is then named in the log next to the error.
- **`install.ps1` run from a terminal does not touch `.wslconfig`.** It only warns if mirrored
  networking is missing.
- **Linux and macOS are unchanged.** `ASKWELL_SOCKET_DIR` stays empty, and the sockets stay in
  `/run/askwell` on the bind mount. The bridge still dials only `127.0.0.1` everywhere (C1).

**Version under test:** `0.9.11`. Run `cat VERSION` and update this line if the version has
moved on.

**Who runs it:** the orchestrating session, on the Windows 11 test VM (`scripts/winvm.sh`,
#836). The build agent does not run this walkthrough.

**Time:** about two hours for Part 1, most of it Setup's downloads, the WSL restart and the
model download. Part 2 takes about 20 minutes, and Part 3 about 15.

---

## Read this first

**What you need**

- The build host, with the Windows 11 test VM already created (`scripts/winvm.sh create`, #836).
  The VM needs 8 GB of memory. **Do not start it while an eval is running**, because the two
  together do not fit on this machine.
- A VNC viewer on the build host. You use it to see and click inside the VM, at
  `127.0.0.1:5905`.
- A Setup built from this branch: `Askwell-Setup-0.9.11.exe`. Only the release workflow can
  build it, because it needs the cross-built Windows shell. Run **Release** from the Actions tab
  on this branch, with a throwaway tag such as `v0.9.11-m11-223`, and download the `.exe` from
  the draft it creates. Delete that draft when you are done.
- These two model files on the build host, in `~/.local/share/askwell/models/`:
  `bge-m3-FP16.gguf` and `bge-reranker-v2-m3-FP16.gguf`. They are needed because of #810 (see
  Known gaps). Setup's model download fetches only the answering model.
- `eval/fixtures/corpus/handbook_a.pdf`. Page 2 reads "The standard notice period for
  resignation at Meridian Loom is sixty-three days."

**What "Stand-in" means below.** A step marked **Stand-in** is a terminal check on the build host.
It confirms something the screen cannot show, or it works around a gap that is not this
ticket's. A user never does these steps. Every other step is done by clicking inside the VM.

**Which evidence proves this ticket.** A green `/health` is **not** enough. It only shows that
the socket opens and that the supervisor's `state.json` says ready, and neither needs the bridge
to reach `llama.cpp`. Only two things prove the fix: a document reaching **ready** in the Library
(indexing embeds through the bridge), and a question being answered. Step 17 is a fallback check
through the bridge, for the case where #771 stops a document being added.

---

## Part 1 — a fresh Windows 11 PC, end to end

### Install

1. **Stand-in:** in a terminal on the build host, in the repository folder, reset the VM to its
   clean snapshot and boot it:

   ```
   scripts/winvm.sh reset && scripts/winvm.sh start
   ```

   ☐ **You should see:** the command return without an error. Open the VNC viewer at
   `127.0.0.1:5905`. You should see the Windows desktop, signed in as the VM's administrator.

2. **Stand-in:** confirm the starting point. The VM has no `.wslconfig` and the right Windows
   build:

   ```
   scripts/winvm.sh ssh 'Test-Path $env:USERPROFILE\.wslconfig; (Get-CimInstance Win32_OperatingSystem).BuildNumber'
   ```

   ☐ **You should see:** `False`, then a build number of `22621` or higher (the VM was `26200`
   on 2026-09-30).

3. **Stand-in:** put the Setup on the VM's desktop. Put the two search models in the folder
   Askwell reads models from, which works around #810:

   ```
   scripts/winvm.sh put Askwell-Setup-0.9.11.exe 'C:/Users/Public/Desktop/Askwell-Setup-0.9.11.exe'
   scripts/winvm.sh ssh 'New-Item -ItemType Directory -Force $env:USERPROFILE\.local\share\askwell\models | Out-Null'
   scripts/winvm.sh put ~/.local/share/askwell/models/bge-m3-FP16.gguf 'C:/Users/<vm-user>/.local/share/askwell/models/bge-m3-FP16.gguf'
   scripts/winvm.sh put ~/.local/share/askwell/models/bge-reranker-v2-m3-FP16.gguf 'C:/Users/<vm-user>/.local/share/askwell/models/bge-reranker-v2-m3-FP16.gguf'
   ```

   Replace `<vm-user>` with the VM's user name (`scripts/winvm.sh ssh '$env:USERNAME'`).

   ☐ **You should see:** `Askwell-Setup-0.9.11` appear on the VM's desktop, in the VNC viewer.

4. In the VM, double-click **Askwell-Setup-0.9.11** on the desktop.

   ☐ **You should see:** Windows' **"Windows protected your PC"** screen, because Setup is not
   code-signed. Click **More info**, then **Run anyway**. Next comes the User Account Control
   prompt. Click **Yes**.

5. ☐ **You should see:** a window titled **Install Askwell 0.9.11**, which says Setup installs
   Podman, Docker Compose and the Windows Subsystem for Linux if they are missing. Click
   **Next**. On the licence page, click **I Agree**.

6. Setup's progress page opens, with the details list showing below the bar. Watch the first
   lines.

   ☐ **You should see:** Setup check the PC and start installing. There must **not** be a line
   saying `Askwell needs Windows 11, version 22H2 (build 22621) or newer`. That line would mean
   the build check refused a supported PC.

7. On a clean VM, Setup enables WSL and needs one restart.

   ☐ **You should see:** the finish page titled **One restart to finish**, with **Restart now**
   selected. Click **Finish**. The VM restarts.

   If instead the finish page says **Askwell is installed**, WSL was already there. Skip to
   step 9, and look for the `.wslconfig` line in that same details list.

8. Sign in again in the VNC viewer, if Windows asks.

   ☐ **You should see:** a window open by itself and carry on with the install, as it did in
   `0.9.10`. Do not run Setup again.

9. **The line this ticket adds.** In that window's text, find the one line about `.wslconfig`.
   It comes before `Starting Podman's machine...`.

   ☐ **You should see**, on a clean VM:
   `Created C:\Users\<vm-user>\.wslconfig with [wsl2] networkingMode=mirrored, so Askwell's services can reach its AI on this PC.`

   ☐ **You should not see:** `Setup could not update ...` (code 27). There should also be no
   `Restarting WSL and Podman's machine` line on a clean VM. There was no machine running to
   restart.

   The same lines are in `%TEMP%\AskwellSetup.log`, if the window closes before you read it.

10. **Stand-in:** read the file Setup wrote:

    ```
    scripts/winvm.sh ssh 'Get-Content $env:USERPROFILE\.wslconfig'
    ```

    ☐ **You should see** exactly two lines: `[wsl2]` and `networkingMode=mirrored`.

### First run

11. The install finishes and Askwell's window opens by itself. If it does not, click **Start**,
    type `Askwell`, and click **Askwell**.

    ☐ **You should see:** **Starting Askwell** with "Waiting for the local application to come
    up." for a while, then **Welcome to Askwell**.

    **This checks the ticket's assumption.** The window can only get past **Starting Askwell** if
    Podman's port publishing (`127.0.0.1:8000`) still reaches Windows in mirrored mode. If it
    stays on **Starting Askwell** for more than five minutes, the assumption is false. Stop and
    record it. Copy the last lines of `podman logs askwell-api-1` into the result.

12. **Stand-in:** confirm the sockets are on the volume and that nothing hit `Errno 95`:

    ```
    scripts/winvm.sh ssh 'podman volume ls; podman logs askwell-inference-bridge-1 2>&1 | Select-String inference_bridge_; podman logs askwell-worker-1 2>&1 | Select-String "worker_unlock_listening|Errno 95"'
    ```

    ☐ **You should see:**
    - `askwell_askwell-sockets` among the volumes.
    - `inference_bridge_starting` and `inference_bridge_listening`, both with
      `socket=/run/askwell-sockets/inference.sock`.
    - `worker_unlock_listening` with `socket=/run/askwell-sockets/worker-unlock.sock`.

    ☐ **You should not see** `Errno 95` or `Operation not supported` anywhere. Either one means a
    socket is still on the Windows bind mount.

13. In **Welcome to Askwell**, step 1, **What this is**, click **Get started**.

    ☐ **You should see:** step 2, **Check the machine**, with a sentence about what to expect from
    this PC. Under it is **Set a passphrase?**. Click **Not now**, then click **Continue**.

14. Step 3, **Get the model**, shows the model's name and its size, with a **Download** button.
    Click **Download**.

    ☐ **You should see:** a progress bar and `… of … — about … left`, rising. When it finishes, it
    shows `— checking the download…` and then **Ready.** This takes a while: about 3 GB comes
    over the VM's network.

    ☐ **You should not see** the download fail. That is not this ticket's defect, but it blocks
    the rest of Part 1. If it fails, record the message and click **Retry**.

15. Wait one or two minutes after **Ready.**, while the AI loads on Windows. Then click
    **Continue**.

    ☐ **You should see:** step 4, **Add something and ask**. It says "Ready. Add something to ask
    about".

### Add a document and ask

16. Copy the handbook into the VM. **Stand-in:**

    ```
    scripts/winvm.sh put eval/fixtures/corpus/handbook_a.pdf 'C:/Users/<vm-user>/Documents/handbook_a.pdf'
    ```

    Then, in Askwell's window, click **Library** in the rail on the left, then **Add a source**.
    Under **Files**, click **Choose files**. Pick `Documents\handbook_a.pdf`, then click
    **Open**.

    ☐ **You should see:** `handbook_a.pdf` in the Library. It goes through indexing to **ready**
    within a few minutes. **This is the first proof of the fix.** Indexing embeds the text
    through the bridge, so a document that reaches **ready** means the bridge reached
    `llama.cpp` on Windows.

    ☐ **Likely instead, on a fresh install:** the file is recorded but shown as not readable, with
    the message `Askwell has no window onto your filesystem yet. Set ASKWELL_ROOTS_MOUNT in .env
    …`. That is #771 (and #498 for Windows paths), not this ticket. Record it in the result, and
    go to step 17 for this ticket's own proof. Do not edit `.env` to get past it, because the
    Windows path translation is unverified (#498). A result reached that way would not say what
    a user gets.

17. **Stand-in, only if step 16 could not index the document.** Dial `llama.cpp` through the
    bridge, from inside the API container, over the socket on the volume:

    ```
    scripts/winvm.sh ssh 'podman exec askwell-api-1 python -c "import socket,os;s=socket.socket(socket.AF_UNIX);s.connect(os.environ[''ASKWELL_INFERENCE_SOCKET'']);s.sendall(b''GET /health HTTP/1.0\r\n\r\n'');print(os.environ[''ASKWELL_INFERENCE_SOCKET''], s.recv(200).splitlines()[0])"'
    ```

    (The doubled `''` is how PowerShell writes a `'` inside a quoted string.) If the quoting
    gives trouble, run the `podman exec …` part in a PowerShell window inside the VM instead.

    ☐ **You should see:** `/run/askwell-sockets/inference.sock b'HTTP/1.1 200 OK'`.

    ☐ **You should not see:** `Connection refused` or a reset. That is exactly the failure this
    ticket fixes, and it would mean mirrored networking is not in effect. Run
    `wsl --shutdown`, click **Askwell** in the Start menu, and try again once. If it still fails,
    the ticket has failed. Record it.

18. Only if step 16 reached **ready**: click **Ask** in the rail. Type
    **What is the notice period in handbook A?** and press **Enter**.

    ☐ **You should see:** an answer saying **sixty-three days**, with a citation to
    `handbook_a.pdf`, page 2. Click the citation. It opens that page. The first answer after
    start can take a few minutes on the VM's processor.

    ☐ **You should not see** the banner saying the assistant is not answering, an answer with no
    citation, or a number other than sixty-three days.

19. Click **Settings** in the rail. Read the **Hardware profile** block under **Model and speed**.

    ☐ **You should see:** a line `Answers run on the processor.` or `Answers run on the graphics
    card.`. The VM has no graphics card passed through, so expect the processor. The line
    appearing at all means the supervisor on Windows is running and publishing its state
    through the bind mount, which this ticket kept in place.

---

## Part 2 — an existing `.wslconfig`, on a PC where Askwell is running

Run this on the same VM, straight after Part 1, with Askwell still installed and Podman's machine
running. This covers the path that Part 1 cannot: Setup changing the file while the machine is
up, and so restarting WSL.

1. **Stand-in:** replace `.wslconfig` with a UTF-16 file that sets NAT and has one other setting:

   ```
   scripts/winvm.sh ssh 'Set-Content -Encoding Unicode $env:USERPROFILE\.wslconfig "[wsl2]`r`nmemory=6GB`r`nnetworkingMode=nat"'
   scripts/winvm.sh ssh '(Get-Content -Encoding Byte -TotalCount 2 $env:USERPROFILE\.wslconfig) -join " "'
   ```

   ☐ **You should see:** `255 254`, the UTF-16 byte-order mark.

2. In the VM, double-click **Askwell-Setup-0.9.11** on the desktop again. Go through the same
   screens as in Part 1, steps 4 and 5.

3. Read the details list as it runs.

   ☐ **You should see**, in this order:
   - `Changed networkingMode from nat to mirrored in C:\Users\<vm-user>\.wslconfig, so Askwell's services can reach its AI on this PC. Its other settings are unchanged.`
   - `Restarting WSL and Podman's machine so the new networking setting takes effect...`
   - `Starting Podman's machine...`

   ☐ **You should see:** the finish page titled **Askwell is installed**. Askwell's window opens
   again and gets past **Starting Askwell**.

4. **Stand-in:** check the file.

   ```
   scripts/winvm.sh ssh 'Get-Content $env:USERPROFILE\.wslconfig; (Get-Content -Encoding Byte -TotalCount 2 $env:USERPROFILE\.wslconfig) -join " "'
   ```

   ☐ **You should see:** `[wsl2]`, `memory=6GB`, `networkingMode=mirrored`, in that order, then
   `255 254`. The file is still UTF-16, it still has the memory setting, and there is only one
   `networkingMode` line.

   To check by clicking instead: open the file in Notepad and choose **File → Save As**. The
   **Encoding** box at the bottom shows **UTF-16 LE**. Click **Cancel**.

5. In Askwell's window, click **Ask** in the rail and ask
   **What is the notice period in handbook A?** again. If step 16 of Part 1 could not index the
   document, repeat Part 1 step 17 instead.

   ☐ **You should see:** the same cited answer as in Part 1 step 18, or `200 OK` from step 17.
   Mirrored networking survived the WSL restart.

6. Run Setup a third time, as in step 2.

   ☐ **You should see:** `WSL already uses mirrored networking (C:\Users\<vm-user>\.wslconfig);
   left unchanged.`, and **no** `Restarting WSL` line.

---

## Part 3 — Linux is unchanged

On the build host, from the repository, on this branch.

1. Build and start Askwell the way development does. In one terminal, start the inference
   supervisor and leave it running:

   ```
   scripts/dev.sh inference
   ```

   In a second terminal, rebuild the image and bring the stack up:

   ```
   scripts/dev.sh build-api && podman compose up -d
   ```

   ☐ **You should see:** in the first terminal, `socket: …/.run/inference.sock`, as before this
   ticket.

2. **Stand-in:** confirm nothing moved.

   ```
   grep '^ASKWELL_SOCKET_DIR' .env; ls .run/; podman logs askwell-inference-bridge-1 2>&1 | grep inference_bridge_
   ```

   ☐ **You should see:** either no `ASKWELL_SOCKET_DIR` line, or an empty one. Then
   `inference.sock`, `worker-unlock.sock` and `state.json`, all in `.run/`. Then
   `inference_bridge_starting` and `inference_bridge_listening` with
   `socket=/run/askwell/inference.sock`.

3. Open a browser at `http://localhost:8000/`. This is where a Linux user starts. From here on,
   everything is by clicking.

   ☐ **You should see:** the **Ask** screen. If this browser has never opened Askwell, you see
   **Welcome to Askwell** instead. Click **Skip setup** at the top right.

4. Click **Library** in the rail.

   ☐ **You should see:** `handbook_a.pdf` marked **ready**. If it is not there, click
   **Add a source**, choose the `eval/fixtures/corpus` folder, and wait until it shows
   **ready**.

5. Click **Ask**, type **What is the notice period in handbook A?**, and press **Enter**.

   ☐ **You should see:** **sixty-three days**, cited to `handbook_a.pdf`, page 2.

6. Click **Settings** in the rail. Under **Model and speed**, the **Hardware profile** block
   should show `Answers run on the graphics card.` This proves `state.json` is still found where
   the supervisor writes it (`ASKWELL_SUPERVISOR_DIR`).

---

## Part 4 — automated, every push

| Command | What it covers |
| --- | --- |
| `scripts/dev.sh test tests/test_compose_sockets.py` | The bridge, `api` and `worker` all name the same socket paths from one variable. `ASKWELL_SUPERVISOR_DIR` stays on the bind mount. `inference-bridge` dials only `127.0.0.1` (C1) |
| `scripts/dev.sh test tests/test_config.py tests/test_inference_client.py` | `supervisor_dir` unset falls back to the socket's directory. Set, `state.json` is read from it and not from the socket volume |
| `deploy/windows/install.test.ps1` (in `api/tests/test_windows_scripts.py` and the Windows workflow) | The `.wslconfig` merge: created, section added, key added, `nat` changed, already mirrored, other keys and comments kept, line endings kept, idempotent, and UTF-16 (with and without a byte-order mark) and UTF-8 with a mark written back as they were read. `ASKWELL_SOCKET_DIR` written on install and upgrade. The build minimum (22621 in, 22000 and 19045 out), and the report meanings for codes 26 and 27 |
| `deploy/windows/setup/setup-bootstrap.test.ps1` | "Mirrored set, machine restarted" (`wsl --shutdown` then `podman machine start`), `nat` changed with other keys kept, already mirrored with no restart, a stopped machine started once, and "Windows too old: refused" (code 26, nothing installed; 21H2 refused, 22H2 installs) |
| `bash deploy/linux/install.test.sh`, `bash deploy/macos/install.test.sh` | An uninstall keeps every volume, counted from the list rather than a fixed four |
| `scripts/dev.sh check`, `scripts/dev.sh test-db` | Everything else, unchanged |

---

## Known gaps

These are not built yet, or not verified. Do not report them as defects of this ticket.

- **A fresh install cannot read a file the user adds** (#771). The installers leave
  `ASKWELL_ROOTS_MOUNT` empty, so Part 1 step 16 will most likely show the file as not readable.
  On Windows, translating a picked `C:\…` path into the containers is also unverified (#498).
  This is why step 17 exists. Until #771 is fixed, "a question answered with a citation on
  Windows" cannot be shown by clicking alone.
- **The search models are not installed by anything** (#810). Setup's model download fetches
  only the answering model. Part 1 step 3 copies `bge-m3` and the reranker in by hand.
- **Windows older than build 22621 is refused, and that is tested only in
  `setup-bootstrap.test.ps1`.** The test VM is Windows 11 `26200`, and there is no Windows 10
  VM. The same goes for code 27, a `.wslconfig` that cannot be written.
- **The WSL restart stops every other WSL distribution the person has running.** This is by
  design, because all distributions share one VM. Setup's log says so, and so does
  `docs/installing.md`. There is no prompt first.
- **`install.ps1` run from a terminal does not set mirrored networking.** It only warns. Only
  Setup changes the person's WSL configuration.
- **A graphics card on Windows is untested** (#590). The VM has none, so Part 1 step 19 shows the
  processor.
- **macOS has no verified answer yet** (#854, #592). Its sockets stay on the bind mount, as on
  Linux, and whether its containers reach `llama.cpp` is a separate ticket.
- **An earlier try at mirrored mode on this VM did not start Podman's machine**
  (`dial tcp 127.0.0.1:62525 ... actively refused`, first comment on #845). The later test on
  2026-09-30 did start it and returned `200`. If Part 1 step 11 or step 17 fails, check first
  whether the machine actually came up under mirrored mode.

---

## Result

| Part | Date | Version | Who | Result | Notes |
| ---- | ---- | ------- | --- | ------ | ----- |
| 1 | | | | | |
| 2 | | | | | |
| 3 | | | | | |
