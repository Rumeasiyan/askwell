# Manual test — M9-FIX-DEPLOY-211, the model settings see the real models folder, and first run names your own path

**Ticket:** `M9-FIX-DEPLOY-211`, issues #660 and #668. Askwell's own program runs inside a
container, and that container sees folders under names that do not exist on your machine. Two
things went wrong because of it:

- **First run** ("Welcome to Askwell", step 3 *Get the model*) told you to place the model
  file at a path starting `/root/…` or `/models/…`. There is no such folder on your computer.
  Worse, it then looked for the file somewhere it could not see, so a file placed in the right
  folder was never found.
- **Settings → Model and speed** was fixed for listing and swapping models by an earlier ticket
  (`M7-SET-FE-146`). This ticket keeps that working and proves it again from a cold start.

Now first run looks for the model file inside the real models folder and names it the way you
know it: `~/.local/share/askwell/models/<file name>`. The models folder is visible to Askwell
**read-only** — Askwell can look at your model files but can never change or delete them.

**Version under test:** `0.7.59`. Run `cat VERSION` and update this line if the version has
moved on.

**Time:** about 45 minutes. Most of it is waiting for builds and for the model to load.

**Who can run it:** anyone with a browser and a terminal who can copy a file into a folder.
Every Askwell screen is reached by clicking, starting from Askwell's front page. The terminal is
used to start Askwell, to move model files in and out of the folder (which is how a real person
places a model), and in steps clearly marked **Terminal** to look at something no screen shows.

**What is being checked.**

| Piece | File |
| ----- | ---- |
| The models folder mounted read-only into the API; the host's model name passed in | `compose.yaml`, service `api` |
| The model file first run looks for, and how it names it to you | `generation_model_file`, `generation_model_file_shown` in `api/src/askwell/config.py` |
| First run's check and its messages | `ModelDownloadManager.verify_manual` in `api/src/askwell/model_download.py` |
| First run built from the above | `register_setup` in `api/src/askwell/setup.py` |
| The download's request, progress and cancel files moved out of the read-only folder | `watch_for_fetch_requests`, `_fetch_once` in `deploy/inference/askwell-inference` |
| The screen | `StepModel` in `web/components/welcome/welcome-screen.tsx`; `web/components/settings/model-and-speed.tsx` |

The automated proof is in `api/tests/test_model_download.py`, `api/tests/test_model_fetch_host.py`
and `api/tests/test_setup_api.py` — among them
`test_verify_manual_names_the_folder_on_the_users_machine`,
`test_a_placed_file_is_found_through_the_mounted_directory`,
`test_no_models_folder_yet_says_where_to_create_it`,
`test_the_disk_check_never_creates_the_models_folder`,
`test_the_fetch_signals_go_through_the_run_directory_only` and
`test_first_run_finds_a_file_placed_in_the_mounted_folder`. The reasoning is in
`docs/decisions.md`, 2026-09-28.

> **Nothing in this test makes a network request.** Do **not** press **Download** on the
> welcome screen. It is the one button in Askwell that fetches from the internet, and it is not
> what this ticket changed.

---

## Before you start

> **Warning — this deletes Askwell's data on this machine.** Step 3 below removes Askwell's
> database, so you see the welcome screen a brand-new user sees. Your sources list,
> conversations, memory and settings are gone afterwards. Your own files and your model files
> are **not** touched. Run this on a test machine, or on one whose Askwell data you do not need.

1. **Terminal:** find your models folder and note what is in it. ☐

   ```
   cd ~/external/quantum-plus/askwell
   cp -n .env.example .env
   grep -E '^ASKWELL_(MODELS_DIR|INFERENCE_MODEL_PATH)=' .env
   ls -la ~/.local/share/askwell/models
   ```

   **You should see:** two lines,
   `ASKWELL_MODELS_DIR=~/.local/share/askwell/models` and
   `ASKWELL_INFERENCE_MODEL_PATH=~/.local/share/askwell/models/Qwen3.5-4B-Q4_K_M.gguf`, then a
   listing with at least `Qwen3.5-4B-Q4_K_M.gguf`, `bge-m3-FP16.gguf` and
   `bge-reranker-v2-m3-FP16.gguf`.

   If your `.env` names a different folder or file, use yours everywhere this document says
   `~/.local/share/askwell/models` or `Qwen3.5-4B-Q4_K_M.gguf`. Write both down — this test is
   about whether Askwell names exactly this folder.

   If any other `.gguf` file is in the folder, move it somewhere else for now. Part D needs a
   folder with no spare model in it.

2. **Terminal:** build both halves. ☐

   ```
   scripts/dev.sh build-api
   scripts/dev.sh web-build
   ```

   **You should see:** both builds finish with no red error text. Do not skip `build-api`: the
   API's code is baked into its image, so without it you are testing the old code.

3. **Terminal:** start from an empty Askwell, then bring it up. ☐

   ```
   podman compose down -v
   podman compose up -d
   scripts/dev.sh db upgrade head
   ```

   **You should see:** Compose removes the containers and volumes, then reports `postgres`,
   `redis`, `egress-proxy`, `api` and `worker` (and the other services) as started. The
   migration ends without an error.

4. **Terminal, a second window:** start the model on the host and leave it running for the
   whole test. If it is already running from an earlier session, stop it with **Ctrl-C** first
   and start it again — this ticket changed it, and an old copy watches the wrong folder. ☐

   ```
   cd ~/external/quantum-plus/askwell
   scripts/dev.sh inference
   ```

   **You should see:** the supervisor reports the generation model as ready after a short wait.

---

## Part A — cold start, and what first run names

1. Open a **private or fresh-profile** browser window and go to `http://127.0.0.1:8000`. This
   is the only address you type in this test. ☐

   **You should see:** the page moves by itself to **Welcome to Askwell**. Across the top, four
   numbered steps: **What this is · Check the machine · Get the model · Add something and ask**,
   with the first highlighted.

2. Click **Get started**. ☐

   **You should see:** step 2, *Check the machine*: a sentence describing this computer's memory
   and graphics card, and an offer **Set a passphrase?** with two buttons.

3. Click **Not now**, then **Continue**. ☐

   **You should see:** step 3, *Get the model*, highlighted. A box with a model name at the top
   (for example **Qwen3.5 9B (Q4_K_M)** on a machine with a graphics card, or **Qwen3.5 4B
   (Q4_K_M)** on one without). Below the box, an **Add a source** area and a **Continue** button.

4. Read the box. What it says depends on the model file you already have. ☐

   **On this development machine** (its `Qwen3.5-4B-Q4_K_M.gguf` is not byte-for-byte the file
   Askwell ships — `docs/BRAIN.md`), you should see a red message:

   > The file at **~/.local/share/askwell/models/Qwen3.5-4B-Q4_K_M.gguf** does not match any
   > model Askwell recognises — it may be corrupt, incomplete, or the wrong file. Re-download it,
   > or replace it with the correct file.

   and two buttons, **Retry** and **Use a file instead**.

   **On a machine that has the genuine shipped file**, you should see **Ready.** instead, and
   **Continue** can be clicked.

   **Either way, check:** the text names `~/.local/share/askwell/models/…` — your folder. It
   must **not** say `/models/…` or `/root/…`. Before this ticket it said
   "No file found at /root/.local/share/askwell/models/model.gguf" even though the file was
   there. That the file is now *found* (it is being checked, not reported missing) is the fix.

5. If you saw the red message, click **Use a file instead**. ☐

   **You should see:** below a thin line, "On a slow or air-gapped connection: download <model
   name> yourself and place it at exactly this path, then verify it —" followed by a grey box
   holding **~/.local/share/askwell/models/Qwen3.5-4B-Q4_K_M.gguf**, and a **Verify the file**
   button.

6. **Terminal:** check that the path on screen is a real place on your machine. Type exactly
   what the grey box shows. ☐

   ```
   ls -la ~/.local/share/askwell/models/Qwen3.5-4B-Q4_K_M.gguf
   ```

   **You should see:** one line listing the file, about 2.7 GB. Not "No such file or directory".
   This is the ticket's acceptance criterion: first run names a folder that exists on your
   machine.

7. Click **Verify the file**. ☐

   **You should see:** the button reads "Checking…" for several seconds (it is reading the whole
   file), then **Verify the file** again. The box shows the same result as step 4 — the red
   "does not match" message on this machine, **Ready.** on one with the shipped file — still
   naming `~/.local/share/askwell/models/…`.

## Part B — no model file yet

A new user who has not placed a model yet lands here too. This part takes the file away.

8. **Terminal, second window:** stop the model supervisor with **Ctrl-C**. Then, in the first
   terminal, move the model out of the folder and restart the API, so it checks again on start. ☐

   ```
   mv ~/.local/share/askwell/models/Qwen3.5-4B-Q4_K_M.gguf ~/askwell-211-model.gguf
   podman compose restart api
   ```

   Wait about 20 seconds.

9. In the browser, go back to the front page by clicking the browser's reload button (F5). ☐

   **You should see:** **Welcome to Askwell** again, on step 1. Click **Get started**, then
   **Continue** (the passphrase offer is not shown a second time).

   **On step 3 you should see:** the box with the model name, "N GB to download once. This is
   the one download Askwell makes, and only because you started it.", buttons **Download** and
   **I already have the file**, and — already open underneath — the grey box with
   **~/.local/share/askwell/models/Qwen3.5-4B-Q4_K_M.gguf** and **Verify the file**. The path
   is your folder's, not `/models/…`. **Continue** is greyed out.

   **Do not click Download.**

10. **Terminal:** check the folder the screen names exists, even though the file does not. ☐

    ```
    ls -la ~/.local/share/askwell/models
    ```

    **You should see:** the folder, with the embedding and reranker models but no
    `Qwen3.5-4B-Q4_K_M.gguf`. You would place the file here.

11. Click **Verify the file**. ☐

    **You should see:** "Checking…" briefly, then **Verify the file** again. **Nothing else on
    screen changes.** This is a known defect, #803: Askwell works out the message "No file
    found at ~/.local/share/askwell/models/Qwen3.5-4B-Q4_K_M.gguf." but the screen does not
    show it in this state. Record it as #803, not as a failure of this ticket. Step 12 proves
    the message itself is right.

12. **Terminal:** read what Askwell decided when it started. ☐

    ```
    podman compose logs api 2>&1 | grep model_startup_discovery | tail -1
    ```

    **You should see:** one line containing
    `target_path=~/.local/share/askwell/models/Qwen3.5-4B-Q4_K_M.gguf` and
    `error='No file found at ~/.local/share/askwell/models/Qwen3.5-4B-Q4_K_M.gguf.'`. Neither
    mentions `/models` or `/root`.

13. **Terminal:** place the file, the way a user would copy it off a USB stick. Then start the
    model supervisor again in the second window. ☐

    ```
    mv ~/askwell-211-model.gguf ~/.local/share/askwell/models/Qwen3.5-4B-Q4_K_M.gguf
    ```

    Second window: `scripts/dev.sh inference`, and wait for it to report ready.

14. In the browser, still on step 3, click **Verify the file**. ☐

    **You should see:** "Checking…" for several seconds, then the same result as step 4 — the
    red "does not match" message naming `~/.local/share/askwell/models/Qwen3.5-4B-Q4_K_M.gguf`
    on this machine, or **Ready.** with the shipped file. Either way the file you just placed
    was **found**. That is the ticket's cold-start promise for first run.

## Part C — Askwell can look at the models folder but not change it

15. **Terminal:** look at the folder from inside Askwell, and try to write to it. ☐

    ```
    podman compose exec api ls /models
    podman compose exec api touch /models/should-not-exist
    ```

    **You should see:** the first lists the same files as your `ls` in step 10 plus
    `Qwen3.5-4B-Q4_K_M.gguf`. The second fails with
    `touch: cannot touch '/models/should-not-exist': Read-only file system`.

16. **Terminal:** confirm Askwell left nothing of its own in your models folder. ☐

    ```
    ls -la ~/.local/share/askwell/models | grep -E 'fetch-|should-not' || echo "clean"
    ```

    **You should see:** `clean`. The download's request, progress and cancel files now live in
    Askwell's run folder (`.run/` in the repository), never among your models.

## Part D — Settings lists the files that are there, and swaps

This is the ticket's own cold-start walkthrough: place a second model file, open Settings, and
swap to it.

17. In the browser, click **Skip setup** at the top right of the welcome screen. ☐

    **You should see:** the **Ask** screen, with a column down the left: **Ask**, **Library**,
    **Clarifications**, **Memory**, **Settings**.

18. Click **Settings** in the left column. ☐

    **You should see:** **Settings**, with **Model and speed** as the first section. Under
    **Model**, "In use: **Qwen3.5-4B-Q4_K_M.gguf**" with an **Unverified** tag on this machine
    (or "Qwen3.5 4B (Q4_K_M)" and **Validated** with the shipped file). Further down, the
    **Swap model.** block:

    - "**Swap model.** Models are read from ~/.local/share/askwell/models." — your folder, not
      `/models`.
    - "There is no other model file in ~/.local/share/askwell/models. To try a different model,
      place its .gguf file in that folder and reopen this page. Askwell does not download models
      from here."
    - No swap buttons. The embedding and reranker models are not offered.

19. **Terminal:** place a second model file by copying the one you have under a new name. ☐

    ```
    cp --reflink=auto ~/.local/share/askwell/models/Qwen3.5-4B-Q4_K_M.gguf ~/.local/share/askwell/models/my-second-model.gguf
    ```

    If you have a genuinely different small `.gguf` answer model, place that instead.

20. In the browser, click **Ask** in the left column, then **Settings** again. ☐

    **You should see:** the "There is no other model file" sentence is gone. In its place, one
    row: **my-second-model.gguf**, an **Unverified** tag, "my-second-model.gguf · 2.7 GB" (or
    the size of your file), and a **Swap to this model…** button. Settings now lists the file
    that is actually in your folder.

21. Click **Swap to this model…**. ☐

    **You should see:** a box opens under the row, saying the assistant is unavailable while the
    new model loads (up to 5 minutes), that document search keeps working, and — because the
    file is unverified — "This model has not been tested against Askwell's checks. …". Two
    buttons: **Swap to this unverified model** and **Cancel**.

22. Click **Swap to this unverified model**, and stay on this page. ☐

    **You should see:** "Swapping to my-second-model.gguf. The assistant is unavailable until it
    has loaded — up to 5 minutes; search and browsing still work." After a short while (seconds
    for an identical copy): "Now answering with my-second-model.gguf. Recorded in the decisions
    log." **In use** now names **my-second-model.gguf**, and the swap area offers
    **Qwen3.5-4B-Q4_K_M.gguf** (or its display name) as the model to go back to.

    In the second terminal, the supervisor's log shows it loading
    `…/.local/share/askwell/models/my-second-model.gguf` — the file in your folder.

23. Click **Swap to this model…** next to the original model, then **Swap to this unverified
    model** (or **Swap now** for a validated one). ☐

    **You should see:** "Now answering with …" naming the original model, and **In use** shows
    it again with the tag it had in step 18.

24. Click **Ask** in the left column and ask anything, such as "What can you do?". ☐

    **You should see:** an answer arrives. Nothing is stuck after two swaps. (With no source
    added, Askwell may say it has nothing of yours to answer from — that is correct.)

---

## Clean up

1. In **Settings**, check **In use** names the original model. If not, swap back as in step 23
   and wait for "Now answering with …". Do this first: deleting the model in use leaves the
   assistant with no model after the next restart.
2. **Terminal:**

   ```
   rm ~/.local/share/askwell/models/my-second-model.gguf
   ```

3. Put back anything you moved out of the models folder in *Before you start* step 1.

---

## Known gaps — not defects

- **First run's "Verify the file" shows no message when the file is missing** — #803. The
  message exists and names your folder (Part B step 12), but the screen only shows messages
  for a file that is present and wrong.
- **"No models folder yet — create it here" cannot be seen in the running stack.** The message
  exists (`test_no_models_folder_yet_says_where_to_create_it`) and is part of #803's fix. In
  practice `podman compose up` creates an empty `~/.local/share/askwell/models` if it is missing,
  so the folder always exists once Askwell is running — Part B shows that case, an empty folder.
- **The download is not walked here.** It needs the internet, and it lands the model under the
  catalogue's file name, which the model supervisor does not load — #802. What this ticket
  changed for it (the request, progress and cancel files moving to `.run/`) is covered by
  `test_model_fetch_host.py` and was checked live with a loopback-only request (#668's closing
  comment). Part C step 16 shows the models folder stays clean.
- **The model name at the top of step 3 is your profile's catalogue model**, which may differ
  from the file first run checks (a 9B name above a 4B file on an accelerated machine). The file
  it checks is the one the supervisor loads, which is what matters; the naming mismatch belongs
  with #802.
- **This development machine's model reads "does not match"** because its bytes are not the
  shipped file's. That is correct and unchanged by this ticket.
- **The decisions record still stores the API's own path** (`/models/<name>`) for a profile
  adjusted by first run. Audit payloads were out of scope (`docs/decisions.md`, 2026-09-28).
- **The model supervisor and the API must be updated together.** An older supervisor watches
  the models folder for a download request and will not see one. Before you start step 4
  restarts it for this reason.
