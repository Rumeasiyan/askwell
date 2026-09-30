# Manual test — M11-FIX-BE-227, Askwell reads your home folder, and Windows paths work

**Ticket:** `M11-FIX-BE-227`. Two defects, both found on the Windows 11 test VM, fixed:

- **A new install could read nothing.** Every installer left `ASKWELL_ROOTS_MOUNT` empty in
  `.env`, so any folder a user added was recorded and shown as not readable, with *"Askwell has
  no window onto your filesystem yet. Set ASKWELL_ROOTS_MOUNT in .env …"* (#771). Now every
  installer sets it to the user's home folder, on install and on upgrade when it is empty. A
  value already there is left alone.
- **Windows folders were refused.** Adding a folder answered *"Askwell needs the whole path,
  starting with a slash - 'C:\Users\askwell\Documents\corpus' is relative to something"*. Now
  `C:\...` paths are accepted when the home folder is a Windows path. Inside the containers the
  home folder is at `/host/c/Users/<you>`, and `askwell.paths` translates every read. The
  database and the interface keep the Windows path.

What changed on disk: `api/src/askwell/paths.py` (new), `roots.py`, `sources.py`, `ingest.py`,
the extractors, `documents.py`, `table_load.py`, `worker.py`, `config.py`, `app.py`;
`compose.yaml` (the roots mount's container side is `ASKWELL_ROOTS_TARGET` when set);
`.env.example`; `deploy/{linux,macos}/lib.sh` (`ensure_roots_mount`) and `install.sh`;
`deploy/windows/lib.ps1` (`Get-AskwellRootsTarget`, `Set-AskwellRootsMount`) and
`install.ps1`. The reasoning is in `docs/decisions.md`, 2026-09-30, "Askwell may read the
user's whole home folder".

This walkthrough also settles #498 on Windows: whether a path from the native folder dialog
reaches the containers.

**Version under test:** `0.9.15`. Run `cat VERSION` and update this line if the version has
moved on.

**Who runs it:** the orchestrating session, on the Windows 11 test VM (`scripts/winvm.sh`) and
the Ubuntu 24.04 VM used for `M11-FIX-DEPLOY-225`. The build agent does not run this
walkthrough.

**Time:** about ninety minutes for Part 1 on a clean snapshot, most of it Setup's downloads
and the WSL restart. Part 2 takes fifteen minutes, Part 3 about forty.

---

## Read this first

**What you need**

- The build host, with the Windows 11 test VM already created (`scripts/winvm.sh create`), on
  its clean snapshot. The VM's user is `askwell`; if yours differs, read your user name
  everywhere this document says `askwell` inside a path. **Do not start the VM while an eval
  is running**; the two together do not fit on this machine.
- The clean Ubuntu 24.04 desktop VM from `docs/manual-tests/M11-FIX-DEPLOY-225.md`, with its
  snapshot taken right after first sign-in.
- Release artefacts built from this branch: `Askwell-Setup-0.9.15.exe` and
  `askwell-0.9.15-linux-x86_64.tar.gz`. Only the release workflow builds them. Run **Release**
  from the Actions tab on this branch with a throwaway tag such as `v0.9.15-m11-227`, download
  both from the draft it creates, and **delete the draft when you are done**.
- The three model files on the build host in `~/.local/share/askwell/models/`:
  `Qwen3.5-4B-Q4_K_M.gguf`, `bge-m3-FP16.gguf`, `bge-reranker-v2-m3-FP16.gguf`. They are
  placed by hand, as in `M11-FIX-DEPLOY-225`, because of #802 and #810.
- Two fixtures from `eval/fixtures/corpus/`:
  - `handbook_a.pdf` — page 2 reads "The standard notice period for resignation at Meridian
    Loom is sixty-three days."
  - `handbook_b.pdf` — says Meridian Loom VPN access tokens expire after fourteen days of
    inactivity.
- A VNC viewer (`127.0.0.1:5905` for the Windows VM).

**What "Stand-in" means below.** A step marked **Stand-in** is a terminal command or file copy
a user would never do. It either puts a test file in place or confirms something the screen
cannot show. Every other step is done by clicking and typing in Askwell or Windows, the way a
user would.

**What proves this ticket.**

1. After Setup, `.env` names the home folder and its container side, with nothing edited by
   hand (Part 1 step 5).
2. `C:\Users\askwell\Documents\corpus`, chosen in the desktop app, is accepted, reaches
   **Ready**, and the question is answered citing `handbook_a.pdf` (steps 9–14).
3. A folder on another drive and a network share are refused, each saying why; a folder on C:
   outside the home folder is accepted with a reason (steps 18–20).
4. An upgrade over an install with an empty value fills it; a value the user set survives
   (Part 2).

---

## Part 1 — a clean Windows 11 PC

### Install

1. **Stand-in:** in a terminal on the build host, in the repository folder, reset the VM and
   boot it:

   ```
   scripts/winvm.sh reset && scripts/winvm.sh start
   ```

   ☐ **You should see:** `up (ssh on 127.0.0.1:…)`, and in VNC the Windows desktop, signed in.

2. **Stand-in:** put Setup on the desktop, the models where Askwell reads them, and the
   handbook in a folder under Documents:

   ```
   scripts/winvm.sh put Askwell-Setup-0.9.15.exe 'C:/Users/Public/Desktop/Askwell-Setup-0.9.15.exe'
   scripts/winvm.sh ssh 'New-Item -ItemType Directory -Force $env:USERPROFILE\.local\share\askwell\models, $env:USERPROFILE\Documents\corpus | Out-Null'
   for f in Qwen3.5-4B-Q4_K_M.gguf bge-m3-FP16.gguf bge-reranker-v2-m3-FP16.gguf; do
     scripts/winvm.sh put ~/.local/share/askwell/models/$f "C:/Users/askwell/.local/share/askwell/models/$f"
   done
   scripts/winvm.sh put eval/fixtures/corpus/handbook_a.pdf 'C:/Users/askwell/Documents/corpus/handbook_a.pdf'
   ```

   ☐ **You should see:** **Askwell-Setup-0.9.15** on the VM's desktop.

3. In the VM, double-click **Askwell-Setup-0.9.15**. In **Install Askwell 0.9.15**, click
   **Next**, and follow Setup. On a clean VM it enables WSL and asks for one restart; restart,
   sign back in, and Setup carries on by itself.

   ☐ **You should see:** Setup's finish page, **Askwell is installed**.

4. Askwell's window opens by itself. If it does not, click **Start**, type `Askwell`, and click
   **Askwell**.

   ☐ **You should see:** **Starting Askwell** for a while, then **Welcome to Askwell**.

5. **Stand-in:** read what Setup wrote, and what the API said about it when it started:

   ```
   scripts/winvm.sh ssh 'Select-String -Path $env:LOCALAPPDATA\Askwell\app\.env -Pattern "^ASKWELL_ROOTS_"'
   scripts/winvm.sh ssh 'podman logs askwell-api-1 2>&1 | Select-String roots_mount'
   ```

   ☐ **You should see:**
   - `ASKWELL_ROOTS_MOUNT=C:\Users\askwell` and `ASKWELL_ROOTS_TARGET=/host/c/Users/askwell`.
   - One `roots_mount` log line with `"mount": "C:\\Users\\askwell"`,
     `"container_path": "/host/c/Users/askwell"` and `"visible": true`, at level `info`.

   ☐ **Likely instead, if Podman on WSL refuses a Windows bind source** (the ticket's one
   assumption): the stack did not start, or the line is at level `error` with
   `"visible": false` and a `hint`. Record the `podman compose` error in the result and stop;
   everything after this depends on it.

### First run, adding the folder

6. In **Welcome to Askwell**, step 1 **What this is**, click **Get started**.

7. Step 2, **Check the machine**. Under **Set a passphrase?**, click **Not now**, then
   **Continue**.

   ☐ **You should see:** step 3, **Get the model**, showing **Ready.** — the model is in
   place. Below it, the **Add a source** box with **Files**, **Choose files** and **Choose a
   folder**.

8. Look at the top of the window, at the status line beside the coloured dot. Give it up to
   three minutes.

   ☐ **You should see:** a green dot and **Ready**. (Not this ticket's; if it never gets
   there, record it and carry on — indexing does not need the answering model.)

9. In the **Add a source** box, click **Choose a folder**. In the Windows dialog, go to
   **Documents**, click **corpus** once, and click **Select Folder**.

   ☐ **You should see:** a card saying one file, **From 1 folder.**, then a question: **Which
   folder is “corpus” in?**, with an empty field and an **Add them** button.

   (The desktop app knows the path but still asks — #869. Not this ticket's defect.)

10. Type `C:\Users\askwell\Documents` in the field and click **Add them**.

    ☐ **You should see:** a note headed **Askwell has not been given this folder yet.**, whose
    text says nominating `C:\Users\askwell\Documents\corpus` lets it read anything inside it,
    and a button **Nominate C:\Users\askwell\Documents\corpus**.

    ☐ **You should not see:** *"starting with a slash"* or *"is relative to something"*. That
    is the defect this ticket fixes.

11. Click **Nominate C:\Users\askwell\Documents\corpus**.

    ☐ **You should see:** the card move on to **Recording 1 file from
    `C:\Users\askwell\Documents`**, then **Queued**, with indexing progress under it. The path
    is written with backslashes, never `/host/...`.

12. Click **Continue**. Step 4, **Add something and ask**. Wait for indexing to finish (a few
    minutes on the VM's processor).

    ☐ **You should see:** **Ready. Here is a question drawn from what you just added**, with
    one or more suggested questions, or an **Ask a question** button.

### Ask, and open the citation

13. Click **Ask a question** (or any suggested question; it only fills the box). In the ask
    box, clear what is there, type **What is the standard resignation notice period at
    Meridian Loom?** and press **Enter**.

    ☐ **You should see:** an answer saying **sixty-three days**, with a citation to
    `handbook_a.pdf`, page 2.

14. Click the citation.

    ☐ **You should see:** the handbook open inside Askwell at page 2, with the sentence about
    sixty-three days visible. This read goes through the translation in `documents.py`; if
    it says the file cannot be found, that is this ticket's defect.

15. Click **Library** in the rail on the left.

    ☐ **You should see:** a source named **corpus**, marked **Ready**.

16. Click **Settings** in the rail and scroll to **Folders Askwell may read**.

    ☐ **You should see:** one entry, `C:\Users\askwell\Documents\corpus`, labelled
    **Readable**.

### Spaces and non-ASCII letters

17. Open **File Explorer** from the taskbar, go to **Documents**, right-click an empty area,
    **New** → **Folder**, and name it `Client Files – Zoë` (the dash is an en dash; the ë can
    be typed by holding **e** on the touch keyboard, or copied from this line). **Stand-in:**
    put the second handbook in it:

    ```
    scripts/winvm.sh put eval/fixtures/corpus/handbook_b.pdf 'C:/Users/askwell/Documents/handbook_b.pdf'
    ```

    Then in File Explorer drag `handbook_b.pdf` from **Documents** into `Client Files – Zoë`.

    Back in Askwell, click **Library**, then **Add a source**, then **Choose a folder**, pick
    `Client Files – Zoë`, click **Select Folder**. In **Which folder is “Client Files – Zoë”
    in?** type `C:\Users\askwell\Documents`, click **Add them**, then click the **Nominate …**
    button.

    ☐ **You should see:** the source queued and, after a few minutes, **Ready** in the Library
    under the name `Client Files – Zoë`, spelled exactly so. Click **Ask**, type **After how
    many days of inactivity do Meridian Loom VPN access tokens expire?**, press **Enter**: the
    answer says **fourteen**, citing `handbook_b.pdf`. Click the citation; it opens.

### Folders Askwell cannot read

Typed into the field under **Nominate a folder** in **Settings → Folders Askwell may read**.
That field exists for typing a whole path, which is the only way to name a drive the VM does
not have.

18. Click **Settings**, scroll to **Folders Askwell may read**. In the field under **Nominate a
    folder**, type `D:\corpus` and click **Nominate**.

    ☐ **You should see:** a red note headed **That folder was not accepted**, saying
    `D:\corpus is on drive D:, and Askwell can read only your home folder, C:\Users\askwell,
    which is on drive C:.` and suggesting copying the files into a folder under the home
    folder. Nothing is added to the list.

19. Clear the field, type `\\server\share\corpus`, click **Nominate**.

    ☐ **You should see:** **That folder was not accepted**, saying `\\server\share\corpus is a
    network share. Askwell reads only your own home folder, read-only, and cannot reach a
    share from inside its containers.` Nothing is added.

20. **Stand-in:** make a folder on C: outside the home folder:
    `scripts/winvm.sh ssh 'New-Item -ItemType Directory -Force C:\Data | Out-Null'`. Then
    type `C:\Data` in the field and click **Nominate**.

    ☐ **You should see:** `C:\Data` added to the list, labelled **Needs a restart**, with the
    reason: `This folder is outside C:\Users\askwell, your home folder, which is the only part
    of this machine Askwell may read. Move or copy the material into a folder under it and add
    that instead.` This is the one place the "not mounted" state still appears. Click
    **Remove**, then confirm, to take it out again.

21. Type `c:/Users/askwell/Documents/corpus` (lower-case drive letter, forward slashes) and
    click **Nominate**.

    ☐ **You should see:** the field clear, no refusal, and still only one entry,
    `C:\Users\askwell\Documents\corpus`. The typed path was recognised as the folder already
    nominated, not added a second time.

---

## Part 2 — upgrading, on the same VM

Carries on from Part 1, with Askwell installed.

1. Close Askwell's window. **Stand-in:** make the install look like one from before this
   ticket, with the value empty and no container side:

   ```
   scripts/winvm.sh ssh '$f = "$env:LOCALAPPDATA\Askwell\app\.env"; (Get-Content $f) -replace "^ASKWELL_ROOTS_MOUNT=.*","ASKWELL_ROOTS_MOUNT=" | Where-Object { $_ -notmatch "^ASKWELL_ROOTS_TARGET=" } | Set-Content $f -Encoding UTF8'
   ```

2. Double-click **Askwell-Setup-0.9.15** on the desktop again and go through it to **Askwell
   is installed**.

3. **Stand-in:** `scripts/winvm.sh ssh 'Select-String -Path $env:LOCALAPPDATA\Askwell\app\.env -Pattern "^ASKWELL_ROOTS_"'`

   ☐ **You should see:** `ASKWELL_ROOTS_MOUNT=C:\Users\askwell` and
   `ASKWELL_ROOTS_TARGET=/host/c/Users/askwell` back again.

4. Open Askwell from the Start menu, click **Library**.

   ☐ **You should see:** **corpus** and **Client Files – Zoë** still **Ready**. Nothing
   re-indexes.

5. Close Askwell. **Stand-in:** set a narrower folder by hand, as a user might:

   ```
   scripts/winvm.sh ssh '$f = "$env:LOCALAPPDATA\Askwell\app\.env"; (Get-Content $f) -replace "^ASKWELL_ROOTS_MOUNT=.*","ASKWELL_ROOTS_MOUNT=C:\Users\askwell\Documents" | Set-Content $f -Encoding UTF8'
   ```

   Run Setup a third time, to **Askwell is installed**, and read `.env` as in step 3.

   ☐ **You should see:** `ASKWELL_ROOTS_MOUNT=C:\Users\askwell\Documents` — left alone — and
   `ASKWELL_ROOTS_TARGET=/host/c/Users/askwell/Documents`, recomputed to match it.

6. Open Askwell, click **Ask**, and ask the resignation question from Part 1 step 13.

   ☐ **You should see:** sixty-three days, citing `handbook_a.pdf`. The corpus folder is
   under the narrower mount, so it still reads.

7. **Stand-in:** put the value back and shut down:

   ```
   scripts/winvm.sh ssh '$f = "$env:LOCALAPPDATA\Askwell\app\.env"; (Get-Content $f) -replace "^ASKWELL_ROOTS_MOUNT=.*","ASKWELL_ROOTS_MOUNT=C:\Users\askwell" | Set-Content $f -Encoding UTF8'
   scripts/winvm.sh stop
   ```

---

## Part 3 — a clean Ubuntu 24.04 desktop

On Linux the mount is the identity — the path inside the containers is the same as outside —
so this part checks only that a fresh install can read the home folder without editing `.env`.

1. **Stand-in:** restore the Ubuntu VM to its clean snapshot, boot it and sign in. Copy
   `askwell-0.9.15-linux-x86_64.tar.gz` into its **Downloads**, the three models into
   `~/.local/share/askwell/models/`, and `handbook_a.pdf` into `~/Documents/corpus/`.

2. Open **Terminal** from the applications grid and install with the two commands
   `docs/installing.md` gives for Linux, using the 0.9.15 archive. Enter your password once
   when asked.

   ☐ **You should see:** the installer finish, and the Askwell window open on **Starting
   Askwell**, then **Welcome to Askwell**.

3. **Stand-in**, in the same terminal:

   ```
   grep '^ASKWELL_ROOTS_' ~/.local/share/askwell/app/.env; podman logs askwell-api-1 2>&1 | grep roots_mount
   ```

   ☐ **You should see:** `ASKWELL_ROOTS_MOUNT=/home/<you>`, no `ASKWELL_ROOTS_TARGET` value,
   and a `roots_mount` line with `container_path` equal to `mount` and `"visible": true`. (If
   the app folder is elsewhere, the installer's last lines name it.)

4. Go through first run as in Part 1 steps 6–7. At step 3, click **Choose a folder**, pick
   **Documents → corpus**, answer **Which folder is “corpus” in?** with `/home/<you>/Documents`,
   click **Add them**, then **Nominate /home/<you>/Documents/corpus**.

   ☐ **You should see:** the file queued, then **Ready** in step 4 after a few minutes.

5. Ask the resignation question.

   ☐ **You should see:** sixty-three days, citing `handbook_a.pdf`, page 2. The citation
   opens.

6. **Settings → Folders Askwell may read**, type `/tmp` under **Nominate a folder**, click
   **Nominate**.

   ☐ **You should see:** `/tmp` listed as **Needs a restart**, with the reason that it is
   outside `/home/<you>`, your home folder. Remove it again.

---

## Part 4 — automated, every push

Not walked; confirm in CI on the pull request.

- `scripts/dev.sh test`: `api/tests/test_paths.py` (the translation both ways, case-insensitive
  drive letters, both separators, a name with a space and an accent), `test_roots.py` (the
  exact old 400 now accepted, `D:\` and UNC refused, outside-home `not_mounted`).
- `scripts/dev.sh test-db`: `test_ingest_records.py` and `test_sources_api.py` add a
  Windows-shaped folder through the translation and index it.
- `deploy/linux/install.test.sh`, `deploy/macos/install.test.sh`,
  `deploy/windows/install.test.ps1` (Windows CI): `.env` filled when empty, left alone when set,
  and the Windows container side computed.

---

## Known gaps

These are not built yet, or not verified. Do not report them as defects of this ticket.

- **macOS is not walked** (#592). The macOS installer sets `/Users/<you>` the same way Linux
  sets `$HOME`, and the mount is the identity there, but no Mac is available. Covered only by
  `deploy/macos/install.test.sh`.
- **Fedora with SELinux enforcing may still refuse the home mount** (#107). Part 3 uses Ubuntu.
- **The desktop app asks "Which folder is … in?" after a folder was chosen in its own dialog**
  (#869). The native dialog already gave the full path; the add screen does not use it. This
  walkthrough types the answer.
- **A refusal reached through Add a source is shown under the heading "Askwell is not
  answering"** (#870). Typing `D:\...` into **Which folder is … in?** and clicking
  **Nominate** shows the right refusal text under the wrong heading. That is why steps 18–19
  use Settings, where the heading is **That folder was not accepted**.
- **Windows paths are compared case-sensitively after the drive letter.** A folder typed as
  `c:\users\askwell\documents\corpus` is stored as `C:\users\askwell\documents\corpus` and
  compared against the home folder as spelled in `.env`. The folder dialog returns canonical
  case, so this does not arise by clicking. Recorded in `docs/decisions.md`; step 21 records
  what actually happens.
- **A folder outside the home folder on drive C:** (`C:\Data`) is accepted as **Needs a
  restart**, not refused, because a wider `ASKWELL_ROOTS_MOUNT` set by hand can make it
  readable.
- **The models are placed by hand** (#802, #810), as in `M11-FIX-DEPLOY-225`.

---

## Result

| Part | Date | Version | Who | Result | Notes |
| ---- | ---- | ------- | --- | ------ | ----- |
| 1 — Windows, clean install | | | | | |
| 2 — Windows, upgrade | | | | | |
| 3 — Ubuntu 24.04 | | | | | |
| 4 — CI | | | | | |
