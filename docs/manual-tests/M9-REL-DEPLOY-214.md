# Manual test — M9-REL-DEPLOY-214, downloadable releases for Linux, Windows and macOS

**Ticket:** `M9-REL-DEPLOY-214`, issue #559 (and #766, fixed alongside). A release workflow,
`.github/workflows/release.yml`, builds one download per platform on GitHub's own machines. It
attaches them, with a `SHA256SUMS`, to a **draft** pre-release. Nothing publishes it.

**Version under test:** `0.7.61`. Run `cat VERSION` and update this line if the version has
moved on. Below, `<v>` means that version, for example `0.7.61`.

**Time:** about two and a half hours. Most of it is waiting: roughly 40 minutes per workflow run
(there are three), the model download, and the first document indexing.

**Who can run it:** someone who can sign in to GitHub as a member of `Rumeasiyan/askwell` and
use a Linux desktop. Parts 1–3 are done by clicking on the GitHub website. Part 4 is done as a
brand-new person on a clean Linux account, mostly by clicking in the Askwell window. Every
terminal step is labelled **Terminal**. Steps labelled **Stand-in** do by hand something a
real user would not have to do. Each one names the issue that will remove it.

**What is being checked.**

| Piece | File |
| ----- | ---- |
| The workflow: tag check, three platform jobs, the draft job | `.github/workflows/release.yml` |
| One artefact per platform, in the layout its installer expects | `scripts/release-artefact.sh` |
| Checksums | `scripts/release-checksums.sh` |
| Bundling switched on (only macOS actually bundles) | `web/src-tauri/tauri.conf.json` |
| The installers load the bundled images and place the interface | `deploy/{linux,macos}/install.sh`, `deploy/windows/install.ps1` |
| What a downloading user is told to do | `docs/installing.md` |

**Already verified on the build host, before merge** (`docs/decisions.md`, 2026-09-28):
`bash scripts/release-artefact.test.sh` (33 passed), including that each unpacked artefact
passes its own installer's `check_artefacts`. The installer suites passed: Linux 63, macOS 58,
and Windows 47 (run under `pwsh` in a container). `api/tests/test_release_workflow.py` passed
(10). A real-size Linux artefact was assembled from the real images (705 MB), and its checksum
verified. **Not verified before merge:** the workflow itself. It can only run once it is on
`main`. This walkthrough is that verification.

---

## Read this first

**The workflow has to be on `main` before Part 1.** GitHub offers **Run workflow** only for a
workflow that exists on the default branch. Merge the ticket's pull request first.

**Nothing here publishes anything.** Every release this test creates is a **draft**, which only
members of the repository can see. Do not click **Publish release** on any of them. Clean up
removes them all.

**A clean Linux account will not reach a cited answer by clicking alone.** Five gaps stand in
the way. All five are filed, none is this ticket's code, and Part 4 works around each at the
step where it bites. Do not report them as failures of this ticket:

| Issue | What happens on a clean account | Stand-in in this test |
| ----- | -------------------------------- | --------------------- |
| #767 | The stack needs a `podman compose` provider, and no installer installs one | Step 13 |
| #810 | Nothing installs `llama-server` or places the embedding and reranker models | Step 14 |
| #771 | The installed `.env` gives Askwell no view of any folder, so an added file cannot be read | Step 20 |
| #802 | The first-run download saves the model under a name the supervisor does not load | Step 26 |
| #811 | The installed inference service starts without its settings (found by reading code; check it) | Step 21 |

If any of these has been fixed by the time you run this, skip its stand-in and confirm the
screen behaves without it. That is a good result. Note it on the issue.

---

## Before you start

### A. A clean Linux account

A virtual machine with a fresh Fedora or Ubuntu desktop is best. There, Podman is not yet
installed, so the installer's "install Podman" path runs too. A new account on this machine is
enough otherwise. It shares the machine's Podman program but has its own images and data.

**Terminal**, as your usual account, only if you are using a new account on this machine:

```
sudo useradd -m askwell-test
sudo passwd askwell-test
```

Choose a password and write it down. **Do not** switch to it with `su` or `sudo -u`: Askwell
registers itself with the account's login session, which only exists after a real login at the
desktop's sign-in screen. You will do that in Part 4.

### B. A test document

**Terminal**, as your usual account, from the repository:

```
mkdir -p /tmp/askwell-214 && chmod 755 /tmp/askwell-214
cp eval/fixtures/corpus/conflict_2025.pdf /tmp/askwell-214/
chmod 644 /tmp/askwell-214/*
```

Page 1 of `conflict_2025.pdf` says that the return window at Meridian Loom is **thirty days**,
"as of March 2025". Part 4 asks about that.

---

## Part 1 — a draft appears, with one artefact per platform

1. In a browser, open `https://github.com/Rumeasiyan/askwell` and sign in if asked. Click the
   **Actions** tab along the top. In the list on the left, click **Release**. ☐

   **You should see:** a page headed **Release**, and a grey bar saying "This workflow has a
   `workflow_dispatch` event trigger", with a **Run workflow** button on its right.

2. Click **Run workflow**. Leave **Use workflow from** on `main`. In the box labelled **Tag for
   the draft**, type `v<v>-test.1` (for example `v0.7.61-test.1`). Click the green **Run
   workflow** button. ☐

   **You should see:** after a few seconds (reload the page if not), a new run at the top of
   the list with a yellow spinning circle.

3. Click the new run. ☐

   **You should see:** a diagram of five boxes. **Tag matches VERSION** comes first. Three
   boxes run side by side: **Linux — desktop shell**, **Windows — desktop shell** and
   **macOS — desktop shell**. **Draft release** comes last.

4. Wait for the run to finish (about 40 minutes). You do not need to watch it. ☐

   **You should see:** all five boxes with a green tick, and "Success" at the top.

   **If Windows or macOS never starts**, the box stays grey or yellow with a message such as
   "no runner available" or a billing notice. That answers the ticket's assumption that
   GitHub's Windows and macOS machines are available to this repository. Take a screenshot,
   record it on #559, and stop here. Do not work around it by removing a platform. Also check
   that **Draft release** is red and that no draft appeared (step 5). That is the correct
   behaviour.

5. Click the **Code** tab, then **Releases** on the right-hand side of the page. ☐

   **You should see:** a release titled **Askwell `<v>`** with two badges, **Draft** and
   **Pre-release**. Under **Assets**, four files:

   - `askwell-<v>-linux-x86_64.tar.gz` (roughly 700 MB)
   - `askwell-<v>-windows-x86_64.zip` (similar size)
   - `askwell-<v>-macos-arm64.tar.gz` (similar size)
   - `SHA256SUMS` (a few hundred bytes)

   There may also be "Source code" links. GitHub adds those itself. Nothing else should be
   listed. No file should be under a few hundred MB: each one carries the container images.

6. Click `SHA256SUMS` to download it, then click `askwell-<v>-linux-x86_64.tar.gz`. Save both
   in `/tmp/askwell-214`. ☐

   **Terminal:**

   ```
   cd /tmp/askwell-214
   sha256sum -c SHA256SUMS --ignore-missing
   chmod 644 /tmp/askwell-214/*
   ```

   **You should see:** `askwell-<v>-linux-x86_64.tar.gz: OK`. Open `SHA256SUMS` in a text editor
   as well. It should have exactly **three** lines, one per platform file, each a 64-character
   code followed by the file name.

7. Optional, if you have the disk space: also download the Windows and macOS files into the
   same folder and run `sha256sum -c SHA256SUMS` without `--ignore-missing`. ☐

   **You should see:** three lines ending `OK`.

## Part 2 — running it again replaces the draft

8. Repeat steps 1–4 with the **same** tag, `v<v>-test.1`. ☐

   **You should see:** the run succeed as before. Click **Draft release**, then the step
   **Replace any earlier draft for this tag**. Its log contains one line,
   `Deleting earlier draft <number> for v<v>-test.1`.

9. Go to **Code → Releases** again. ☐

   **You should see:** **one** draft titled **Askwell `<v>`** for this tag, not two. Hover over
   an asset's date: it is from the second run.

## Part 3 — one platform failing leaves no draft

10. **Terminal** (**Stand-in**: this is a deliberate break, which no user would make). On a
    throwaway branch, make the Windows build fail: ☐

    ```
    git switch -c chore/break-windows-214 main
    ```

    Open `.github/workflows/release.yml`. In the **windows** job, find the step
    `- name: Build the shell`, and change its `run:` line to `run: exit 1`. Save, then:

    ```
    git commit -am "chore: break the Windows release job on purpose (throwaway)"
    git push -u origin chore/break-windows-214
    ```

11. On the website, go to **Actions → Release → Run workflow**. Set **Use workflow from** to
    `chore/break-windows-214`, type the tag `v<v>-test.2`, and click **Run workflow**. Open the
    run and wait for it to finish. ☐

    **You should see:** **Windows — desktop shell** red. **Draft release** also red, having
    stopped at its first step, **Every platform built**. On the run's summary page, under
    **Annotations**, an error titled **No draft release** reading
    **"Not every platform built, so no draft was created or replaced: Windows (failure)"**.
    Linux and macOS may be green. That is expected, and it is exactly the partial set that
    must not be released.

12. Go to **Code → Releases**. ☐

    **You should see:** no release for `v<v>-test.2`. The `v<v>-test.1` draft from Part 2 is
    still there, untouched.

    **Terminal:** delete the throwaway branch.

    ```
    git switch main
    git branch -D chore/break-windows-214
    git push origin --delete chore/break-windows-214
    ```

## Part 4 — the Linux download installs on a clean account and answers a question

13. Sign out of your desktop. At the sign-in screen, sign in as `askwell-test` (or the VM's
    user). Open a terminal. **Terminal:** ☐

    ```
    podman --version
    podman compose version
    ```

    **You should see:** on a clean VM, `command not found` for both. That is fine: the
    installer installs Podman. On a shared machine, a Podman version.

    **Stand-in (#767):** if `podman compose version` fails (after Podman is installed, in a VM),
    install a compose provider with the package manager, for example
    `sudo dnf install docker-compose` or `sudo apt install docker-compose`. Note on #767 that
    you had to.

14. **Stand-in (#810).** Askwell's native inference needs `llama-server`, plus two small
    search models, and nothing installs them yet. ☐

    - Install llama.cpp so that `llama-server --version` prints a version. Use your package
      manager, or unpack a release from the llama.cpp project into `~/.local/bin`.
    - Copy the two search models from an account that already runs Askwell (your usual
      account on the build host has them):

      ```
      mkdir -p ~/.local/share/askwell/models
      # from the other account, or a USB stick:
      #   bge-m3-FP16.gguf
      #   bge-reranker-v2-m3-FP16.gguf
      ls -la ~/.local/share/askwell/models
      ```

    **You should see:** `llama-server --version` prints a version, and the folder lists both
    `.gguf` files. It holds no `Qwen…` file yet. First run fetches that.

15. **Terminal.** Copy the download and the test document into this account, and check the
    download again, the way `docs/installing.md` tells a user to: ☐

    ```
    mkdir -p ~/Downloads ~/Documents
    cp /tmp/askwell-214/askwell-*-linux-x86_64.tar.gz /tmp/askwell-214/SHA256SUMS ~/Downloads/
    cp /tmp/askwell-214/conflict_2025.pdf ~/Documents/
    cd ~/Downloads
    shasum -a 256 askwell-*-linux-x86_64.tar.gz
    grep linux SHA256SUMS
    ```

    **You should see:** the same 64-character code on both lines. If they differ, stop. That is
    the "do not install it" case in `docs/installing.md`, and it is a defect.

16. **Terminal.** Follow `docs/installing.md` §Linux exactly: ☐

    ```
    tar -xzf askwell-<v>-linux-x86_64.tar.gz
    askwell-<v>-linux-x86_64/deploy/linux/install.sh
    ```

    **You should see**, in this order, answering **y** and giving your password if asked:

    - `Installing Askwell <v>`
    - In a VM without Podman: `Podman is not installed. This installer needs to run:`, the
      command, then `Install Podman now?`. After you answer **y** and give your password:
      `Podman installed: podman version …`. Elsewhere: `Podman found: …`.
    - `Disk space OK: …`
    - `Generated database credentials in /home/askwell-test/.local/share/askwell/app/.env`
    - `Application files placed under /home/askwell-test/.local/share/askwell/app`
    - Three lines `Loading container image …`, one each for `localhost_askwell-api_dev.tar`,
      `docker.io_pgvector_pgvector_pg18.tar` and `docker.io_redis_8-alpine.tar`, then
      `Container images loaded.`
    - `Probing this machine's hardware...`
    - `Applications-menu entry installed: …`
    - `Askwell registered to start with your session (systemd --user).`
    - `Askwell's container stack and native inference process registered to run with your
      session, independent of the app window (systemd --user).`
    - `Starting Askwell...`, `Askwell is starting. Its window will open shortly.`, and
      `Done. Askwell is also available any time from your applications menu.`

    It must **not** print `Missing: …`, `One or more required files are missing`, or anything
    about building the shell or the interface. That would mean the artefact is incomplete.

17. Look at the screen. ☐

    **You should see:** a window titled **Askwell** (not a browser tab) saying **Starting
    Askwell** and "Waiting for the local application to come up." Within a minute or two it
    changes to **Welcome to Askwell**.

18. **Terminal.** Confirm nothing was pulled from a registry or built: ☐

    ```
    podman images --format '{{.Repository}}:{{.Tag}}'
    ```

    **You should see:** three images: `localhost/askwell-api:dev`,
    `docker.io/pgvector/pgvector:pg18` and a `redis:8-alpine` image. Nothing else.

19. Close the Askwell window. You will open it again from the menu shortly. ☐

20. **Stand-in (#771).** Give Askwell read-only access to `~/Documents`. Open
    `~/.local/share/askwell/app/.env` in a text editor. Find the line `ASKWELL_ROOTS_MOUNT=`
    and change it to `ASKWELL_ROOTS_MOUNT=/home/askwell-test/Documents` (use the account's real
    home folder). Save. **Terminal:** ☐

    ```
    systemctl --user restart askwell-stack.service
    ```

    On Fedora, if the file later shows as not readable, that is SELinux (#107). Run
    `chcon -R -t container_file_t ~/Documents` and try again. Note it on #107.

21. **Terminal.** Check the two background services (#811): ☐

    ```
    systemctl --user status askwell-stack.service askwell-inference.service --no-pager
    ```

    **You should see:** `askwell-stack.service` **active (running)**. Write down what
    `askwell-inference.service` shows. #811 expects it to be **failed**, with a permission error
    about `/run/askwell`, because it starts without its settings. Record the result on #811
    either way. This does not block the rest of this test: the window starts its own inference
    correctly while it is open.

22. Open your desktop's applications menu (the **Activities** or **Show Applications** view)
    and type `Askwell`. Click the Askwell icon. ☐

    **You should see:** the Askwell window again, **Starting Askwell**, then **Welcome to
    Askwell**. Across the top, four numbered steps: **What this is · Check the machine · Get the
    model · Add something and ask**, with the first highlighted. There is a paragraph saying
    Askwell reads your files on this machine and nothing is uploaded.

23. Click **Get started**. ☐

    **You should see:** step 2, *Check the machine*. There is a sentence describing this
    computer's memory and graphics card and what to expect from it, and an offer **Set a
    passphrase?** with **Set a passphrase** and **Not now**.

24. Click **Not now**, then **Continue**. ☐

    **You should see:** step 3, *Get the model*. There is a box with a model name, for example
    **Qwen3.5 4B (Q4_K_M)**, and "*N* GB to download once. This is the one download Askwell makes,
    and only because you started it." There are two buttons, **Download** and **I already have
    the file**. **Continue** is greyed out.

25. Click **Download**. This is the one network request in this test that you choose to make. ☐

    **You should see:** a progress bar and a growing count in GB, such as "1.2 GB of 2.7 GB",
    with a **Cancel** button. When it finishes: **Ready.**, and **Continue** can now be clicked.
    Do not click it yet.

26. **Stand-in (#802).** The download is saved under a different name from the one Askwell
    loads. **Terminal:** ☐

    ```
    grep ASKWELL_INFERENCE_MODEL_PATH ~/.local/share/askwell/app/.env
    ls ~/.local/share/askwell/models
    ```

    The first line names the file Askwell loads, for example `Qwen3.5-4B-Q4_K_M.gguf`. The
    folder holds the download under a name starting `Qwen_`, for example
    `Qwen_Qwen3.5-4B-Q4_K_M.gguf`. Rename it to the name from the first line:

    ```
    cd ~/.local/share/askwell/models
    mv Qwen_Qwen3.5-4B-Q4_K_M.gguf Qwen3.5-4B-Q4_K_M.gguf
    ```

    If the two sizes differ (a 9B download against a 4B name in `.env`), record that on #802
    and set `ASKWELL_INFERENCE_MODEL_PATH` in `.env` to the downloaded size's name instead.
    Then close the Askwell window and open it again from the applications menu, as in step 22.
    Click through steps 23–24 again.

    **You should see:** step 3 now shows **Ready.** straight away.

27. Click **Continue**. ☐

    **You should see:** step 4, with an **Add a source** area and a **Choose files** button.

28. Click **Choose files**. In the file picker, open **Documents**, select
    `conflict_2025.pdf`, and confirm. If Askwell asks **"Which folder is “conflict_2025.pdf”
    in?"**, type `/home/askwell-test/Documents` and click **Add them**. ☐

    **You should see:** the file accepted, with no red **Not added** note and no message saying
    "Askwell has no window onto your filesystem yet". If you see that message, step 20 did not
    take effect, and #771 is what it describes.

29. Finish the welcome steps. Skipping anything optional is fine. ☐

    **You should see:** the **Ask** screen, with a left-hand column that includes **Ask**,
    **Library** and **Settings**.

30. Click **Library**. Wait until `conflict_2025.pdf` says **ready** (a minute or two on CPU). ☐

    **You should see:** one row, `conflict_2025.pdf`, marked **ready**. Not **failed**. A
    failure mentioning embedding usually means step 14's search models are missing.

31. Click **Settings**, and scroll to **Privacy and security**. Under **Network activity**, note
    the two numbers, "*x* outbound requests permitted · *y* refused". ☐

    **You should see:** two numbers, not "Unavailable". Write them down.

32. Click **Ask** in the left column. Type
    `What was Meridian Loom's product return window as of March 2025?` and click **Ask**. Wait
    for the answer to finish. ☐

    **You should see:** an answer saying **thirty days**, with a citation that names
    `conflict_2025.pdf`, **page 1**. Click the citation. The source opens at that page, and the
    thirty-day sentence is on it.

    If the screen instead says the assistant is not ready, check step 14 (`llama-server`) and
    step 26 (the model's name). Neither is this ticket's defect.

33. Type `What is Meridian Loom's policy on gift wrapping?` and click **Ask**. ☐

    **You should see:** Askwell says your files do not answer this and names what would need
    adding. It does not invent a policy (C5). It does **not** search the web on its own. At
    most it offers a web search for you to choose, and you should not choose it (C10).

34. Click **Settings** and look at **Network activity** again. ☐

    **You should see:** the same **permitted** number as in step 31. Asking questions made no
    outbound request. The ticket requires that the built app still makes no outbound call. A
    higher **refused** number means something tried and was stopped. Record which service it
    names, and file an issue.

This is the ticket's acceptance criterion: a download from the draft, checked against its
`SHA256SUMS`, installed on a clean account with `deploy/linux/install.sh`, reaches a working
Ask screen and answers with a citation.

---

## Clean up

35. Delete every throwaway draft. On the website, go to **Code → Releases**, click the
    **Askwell `<v>`** draft, click the **pencil (Edit)** icon, then **Delete** (the red button
    at the bottom), and confirm. Repeat for any other draft whose tag contains `-test`. ☐

    **You should see:** no draft for `v<v>-test.1` remaining. Drafts do not own a tag, so there
    is no tag to delete. Check under **Tags** that no `v<v>-test.*` tag exists.

36. As `askwell-test`, uninstall with the script that shipped in the download, including its
    data: ☐

    ```
    ~/Downloads/askwell-<v>-linux-x86_64/deploy/linux/uninstall.sh --purge-data
    podman rmi --all
    ```

    Answer **y**. Sign out.

37. Back in your usual account, remove the test account and the shared folder: ☐

    ```
    sudo userdel -r askwell-test
    rm -rf /tmp/askwell-214
    ```

38. Comment on #559 with what you saw: whether all three platform jobs ran, the step 5 asset
    list, the step 11 annotation, and whether step 32 answered with a citation. List every
    stand-in you needed. Then close #559. ☐

---

## What a pass looks like

- Part 1: one **Draft · Pre-release** titled **Askwell `<v>`**, with the three platform files and
  a three-line `SHA256SUMS` that checks `OK`.
- Part 2: running again leaves one draft, not two.
- Part 3: a broken Windows build gives no draft at all, and an error that names Windows.
- Part 4: the Linux download installs from its own files (no image built or pulled), opens the
  Askwell window, and after the listed stand-ins answers a question about the user's own
  document with a citation, making no outbound request.

A failure becomes a GitHub issue before the walkthrough continues (`AGENTS.md` §8).

---

## Known gaps

These are deliberate or tracked elsewhere. Do not report them as defects of this ticket.

- **Windows and macOS downloads are built but not shown to install.** That is the product
  owner's own testing, on their own hardware (#590, #592). This test only checks that those
  files exist and match their checksums.
- **The Windows installer never creates a Podman machine** (#808). On a fresh Windows machine,
  loading the images fails, with a message naming the machine as a likely cause.
- **The container images are x86_64 on every platform**, including the `macos-arm64` download
  (#809). Whether they run on Apple silicon is unknown until #592.
- **Nothing is signed.** That was decided on 2026-09-28. The macOS `.app` carries an ad-hoc
  signature, which names no developer. Gatekeeper and SmartScreen still warn, exactly as
  `docs/installing.md` describes.
- **Nothing publishes.** Turning a draft into a release is a person's step
  (`docs/release-procedure.md` §5).
- **Model weights are not in the download.** First run fetches the generation model, or the user
  places it (`M7-OFFLINE-DEPLOY-144`).
- **The five stand-ins in Part 4** — #767 (compose provider), #810 (`llama-server` and the search
  models), #771 (folder access), #802 (download file name), #811 (inference service settings).
  Until all five are fixed, a non-technical person cannot get from the download to an answer on
  their own.
- **Each run costs paid macOS and Windows runner minutes**, about an hour in total
  (`docs/decisions.md`, 2026-09-28).
