# Manual test — M10-FIX-DEPLOY-222, a machine with a GPU gets a GPU build of llama.cpp

**Ticket:** `M10-FIX-DEPLOY-222` (issues #810, #841, #831). Before this ticket, the build host's
hardware probe said `accelerated` (it has an 8 GB RTX 3050), yet every answer ran on the
processor. The `llama.cpp` it ran had no GPU backend. Nothing on screen showed this. The ticket
also found that no installer put any `llama.cpp` on a user's machine at all (#810). What changed:

- A release now carries `llama.cpp` build `b10645`, pinned by checksum in
  `deploy/inference/llama-cpp.lock`. Linux and Windows get two builds: `gpu/` (Vulkan, which
  covers NVIDIA, AMD and Intel) and `cpu/` (processor only). Macs with Apple silicon get one
  build, `gpu/`, with Metal. The release workflow fetches and checks them. Nothing is downloaded
  on the user's machine (C1).
- All three installers place that folder next to `askwell-inference`, and say so.
- At each start, the inference supervisor asks the GPU build which graphics devices it can use
  (`llama-server --list-devices`).
  - If there is a device, it starts the GPU build with `--n-gpu-layers auto`. `llama.cpp` puts as
    much of the model on the card as fits and the rest on the processor.
  - If there is no device, or the GPU build crashes just listing them (a driver too old or
    broken), it starts the CPU build with exactly the command it always had.
  - If the card cannot load the model, it switches to the processor at once and keeps the
    card's error as the reason.
- It reads where the model actually went from `llama.cpp`'s own log (`offloaded N/M layers to
  GPU`). It reports `acceleration` (`gpu` or `cpu`), plus `acceleration_reason` whenever that
  is not "the whole model on the card".
- The answering model starts first, and the two search models start after it has settled. So
  the answering model gets first claim on the card's memory (#841).
- **Settings → Model and speed → Hardware profile** has a new line saying where answers really
  run, and why when that is not the whole model on the card.
- `NOTICES.md` and the licence gate list `llama.cpp` (MIT) and, for Windows, `libomp`
  (`Apache-2.0 WITH LLVM-exception`) (C9).

**Version under test:** `0.9.9`. Run `cat VERSION` and update this line if the version has moved
on.

**Time:** about 40 minutes for Part 1, most of it asking the same question several times and
timing it. Part 2 takes about 30 minutes. Part 3 cannot be run yet (see Known gaps).

**Who can run it:** Part 1 is written for someone who can paste a command into a terminal and
use a stopwatch. Part 2 needs a developer, because it edits `.env` to force the processor path.
Steps that check something a user would never look at are marked **Stand-in**.

---

## Read this first

**What you need**

- **The build host**: the machine with the NVIDIA GeForce RTX 3050 (8 GB), driver 580.178.04.
  Any other Linux machine with an NVIDIA, AMD or Intel graphics card and a working Vulkan driver
  will do, but the reference numbers below were measured on this one.
- A stopwatch (a phone is fine).
- The fixture document `eval/fixtures/corpus/handbook_a.pdf` in Askwell's **Library**. Page 2
  reads "The standard notice period for resignation at Meridian Loom is sixty-three days."

**Reference numbers** (measured 2026-09-30, `docs/decisions.md`; same question, same model,
Qwen3.5-4B-Q4_K_M, `balanced`):

| | Graphics card | Processor |
| --- | --- | --- |
| First answer after start (cold) | 82 s | 272 s |
| Later answers, median | **34 s** | **171 s** |
| Writing the answer | about 55 tokens per second | about 8 tokens per second |

Your numbers do not have to match. The graphics-card column must be clearly faster: several
times, not a few percent.

**A trap in the throughput figures.** Settings → **Model** shows speed figures over the last 20
answers *from this model*. They do not separate answers run on the card from answers run on the
processor. After Part 2, those figures blend both runs. Use your stopwatch readings, not the
Settings figures, to compare the two.

---

## Part 1 — cold start on the build host, on the graphics card

### Start Askwell

1. **Stand-in:** check that the bundled `llama.cpp` builds are in place. In a terminal, in the
   repository folder, paste:

   ```
   ls deploy/inference/llama.cpp/gpu/llama-server deploy/inference/llama.cpp/cpu/llama-server
   ```

   ☐ **You should see:** both paths printed back, with no `No such file or directory`.

   If either is missing, place them the way the release workflow does:

   ```
   scripts/fetch-llama-cpp.sh linux x86_64 deploy/inference/llama.cpp
   ```

   This uses the internet. It runs on the build side only; a user's machine never does this.
   ☐ It must finish without an error. A checksum mismatch stops it, and that is correct.

2. **Stand-in:** check that `.env` does not point Askwell at some other `llama.cpp`:

   ```
   grep ASKWELL_INFERENCE_BINARY .env
   ```

   ☐ **You should see:** nothing, or `ASKWELL_INFERENCE_BINARY=llama-server`. Any other value is
   a path to someone's own build, and Askwell uses that instead of the bundled pair. Comment it
   out for this test.

3. If Askwell's inference is already running in another terminal, stop it with **Ctrl+C** in
   that terminal. Then start it fresh, so you watch a cold start:

   ```
   scripts/dev.sh inference
   ```

   Leave this terminal open. In a second terminal, bring the rest of Askwell up:

   ```
   podman compose up -d
   ```

   ☐ **You should see:** in the first terminal, the lines
   `inference supervisor, on the host (not a container)` and `socket: …/.run/inference.sock`,
   then `llama.cpp` load output. There should be no `could not load the model; retrying on the
   processor` line. That line would mean the card failed to load the model.

4. **Stand-in:** check that the answering model loads before the other two (#841). In the second
   terminal, within the first minute:

   ```
   ps -eo args | grep '[l]lama-server' | cut -c1-160
   ```

   ☐ **You should see:** eventually three `…/deploy/inference/llama.cpp/gpu/llama-server`
   lines, each with `--n-gpu-layers auto`. The one with `Qwen3.5-4B-Q4_K_M.gguf` appears first.
   The `bge-m3` and `bge-reranker` ones appear only once it is ready. The path must be `gpu/`,
   not `cpu/`.

### Open Askwell and look at Settings

5. Open a browser at `http://localhost:8000/`. This is Askwell's front page, where a user
   starts. Everything after this is by clicking.

   ☐ **You should see:** the **Ask** screen, with the rail on the left (**Ask**, **Library**,
   **Clarifications**, **Memory**, **Settings**). If this browser has never opened Askwell, you
   see **Welcome to Askwell** instead. Click **Skip setup** at the top right to reach Ask.

   ☐ **You should not see** a banner saying the assistant is not answering. If you do, wait a
   minute; the models may still be loading. If it stays, the ticket has failed. Copy the first
   terminal's last lines into your report.

6. Click **Settings** in the rail. The first section is **Model and speed**. Under it, read the
   **Hardware profile** block.

   ☐ **You should see**, in this order:
   - `Current profile: Accelerated`
   - `16 GB or more with a graphics card. Fast, and voice works fully.`
   - The probe's own sentence about this machine.
   - **`Answers run on the graphics card.`** with nothing after it. Nothing after it means the
     whole model is on the card.

   ☐ **You should not see** `Answers run on the processor.` on this machine. Before this
   ticket, the profile said Accelerated while the answers really ran on the processor. That is
   the defect this line exists to expose.

   The line refreshes every 15 seconds. If the block has no such line at all, the assistant is
   not running yet. Wait 15 seconds and look again.

7. Scroll to the **Model** block just below. Read its memory line.

   ☐ **You should see:** a line that ends `The part of the model on the graphics card is not
   included.` That wording appears only when the model reports `gpu`. The memory figure is
   small (well under 1 GB), because most of the model is in the card's memory, not the
   computer's.

   Write down the speed lines too (`Writing the answer: … tokens per second`), if any are shown.
   They describe earlier answers, which may have run on the processor. Step 11 checks them
   again.

8. **Stand-in:** confirm what `/health` reports, which the ticket's acceptance names directly:

   ```
   curl -s -c /tmp/askwell.cookies -H 'Accept: text/html' localhost:8000/ -o /dev/null
   curl -s -b /tmp/askwell.cookies localhost:8000/health | python3 -m json.tool | grep -A1 '"acceleration"'
   ```

   ☐ **You should see:** `"acceleration": "gpu"` followed by `"acceleration_reason": null`, four
   times: once for the assistant, and once each for generation, embedding and reranking.

9. **Stand-in:** confirm that the card really holds the models:

   ```
   nvidia-smi --query-compute-apps=process_name,used_memory --format=csv
   ```

   ☐ **You should see:** three `llama-server` rows. On the build host they were about 3150 MiB
   (the answering model) and about 600 MiB each for the other two.

### Ask a question and time it

10. Click **Library** in the rail.

    ☐ **You should see:** `handbook_a.pdf`, marked **ready**. If it is not there, click **Add a
    source**, choose `eval/fixtures/corpus` (or a folder holding a copy of `handbook_a.pdf`),
    and wait until it shows **ready**.

11. Click **Ask** in the rail. Type the question below. Start the stopwatch as you press
    **Enter**, and stop it when the last word of the answer appears.

    ```
    What is the standard resignation notice period at Meridian Loom?
    ```

    ☐ **You should see:** an answer saying **sixty-three days**, with a citation to
    `handbook_a.pdf`, page 2. Clicking the citation opens that page.

    Write down the time. This is the cold figure; compare it with about 82 s.

12. Type the same question into the question box again, press **Enter**, and time it. Repeat
    until you have three more times.

    ☐ **You should see:** the same cited answer each time. The middle of your three times should
    be in the region of 34 s. It must be far below the processor figure of about 171 s.

    ☐ **You should not see** an answer without a citation, or one that says something other
    than sixty-three days. Faster is no use if it is wrong. Report that as a defect, whatever
    the timing.

13. Click **Settings** in the rail again and look at the **Model** block.

    ☐ **You should see:** `Writing the answer:` now at tens of tokens per second (about 55 on the
    build host), once most of the last 20 answers ran on the card. If older processor answers
    still dominate the window, the figure sits between the two. That is expected (see the trap
    under "Read this first").

---

## Part 2 — the same host, on the processor, and when the card cannot be used

This is the other half of the comparison, and the edge cases a user can hit. Each forces a path
by changing how inference starts, then checks the result by clicking, as in Part 1. **Put
`.env` back at the end** (step 21).

### The processor, for comparison

14. In the first terminal, stop inference with **Ctrl+C**. Add this line to `.env` (use the
    repository's real absolute path):

    ```
    ASKWELL_INFERENCE_BINARY=/home/sshroot/external/quantum-plus/askwell/deploy/inference/llama.cpp/cpu/llama-server
    ```

    Start inference again with `scripts/dev.sh inference`.

    ☐ **You should see:** step 4's `ps` check now lists `…/cpu/llama-server` lines **without**
    `--n-gpu-layers`. That is the command a machine without a card has always run, unchanged.

15. In the browser, click **Settings** in the rail and read **Hardware profile**. Wait up to 15
    seconds for the line to refresh.

    ☐ **You should see:** `Answers run on the processor. llama.cpp found no graphics device it
    can use: this build of it has no GPU backend, or the graphics driver is too old for the one
    it has. Answers run on the processor.` `Current profile` still says Accelerated, because
    the probe found a card. The two lines disagreeing, with a reason, is the correct result.

    ☐ In the **Model** block, the memory line no longer mentions the graphics card, and the
    figure is several GB.

16. Click **Ask** in the rail. Ask step 11's question four times, and time each one as before.

    ☐ **You should see:** the same cited answer, sixty-three days, `handbook_a.pdf` page 2. The
    times are in the region of 270 s for the first and 120–240 s after that.

    Record both columns (card and processor) in your report. The ticket's acceptance requires
    both numbers.

### A graphics card whose driver cannot be used

This is what a user with a card but an old or broken Vulkan driver gets. It is faked by hiding
the Vulkan driver from `llama.cpp`.

17. Stop inference with **Ctrl+C**. Remove the `ASKWELL_INFERENCE_BINARY` line you added in step
    14. Start inference with the Vulkan driver hidden:

    ```
    VK_ICD_FILENAMES=/nonexistent.json scripts/dev.sh inference
    ```

    ☐ **You should see:** step 4's `ps` check lists `…/cpu/llama-server`. The supervisor chose
    the processor build **by itself**, without any setting pointing it there.

18. Click **Settings** in the rail and read **Hardware profile**.

    ☐ **You should see:** the same `Answers run on the processor. llama.cpp found no graphics
    device it can use: …` line as step 15. The assistant is ready, and it is not reported as
    failed or restarting.

19. Click **Ask** and ask step 11's question once.

    ☐ **You should see:** the same cited answer, at processor speed. Askwell still answers when
    the card cannot be used.

### Back to normal

20. Stop inference with **Ctrl+C**. Start it the plain way:

    ```
    scripts/dev.sh inference
    ```

21. **Stand-in:** confirm `.env` is as it was in step 2 (`grep ASKWELL_INFERENCE_BINARY .env`).
    Then click **Settings** and confirm step 6 again: **`Answers run on the graphics card.`**

---

## Part 3 — an installed release (cannot be run yet, see Known gaps)

This is the path a real user takes. It is written out so the next person can run it once
`0.9.9` is published. It follows `docs/manual-tests/M9-FIX-DEPLOY-200.md` Part 1, on a clean
Linux account, with these additions.

22. Download `askwell-0.9.9-linux-x86_64.tar.gz` and `SHA256SUMS` from the repository's
    **Releases** page, check and unpack as in M9-FIX-DEPLOY-200 step 1a. Then, in the unpacked
    folder:

    ```
    ls deploy/inference/llama.cpp
    ```

    ☐ **You should see:** `cpu  gpu`. The download carries both builds.

23. Run `./deploy/linux/install.sh`.

    ☐ **You should see**, among the other lines:
    `llama.cpp placed under /home/<you>/.local/share/askwell/app/llama.cpp. Answers run on the
    graphics card where llama.cpp can use it, and on the processor otherwise.`

    ☐ **You should not see** `No llama.cpp build is bundled here; Askwell will run llama-server
    from PATH.` In a release download, that line means the artefact was built without
    `llama.cpp`.

24. When the Askwell window opens, finish first-run as in M9-FIX-DEPLOY-200 steps 3 to 7. Then
    click **Settings** in the rail.

    ☐ **On a machine with a supported card:** `Answers run on the graphics card.` If the card is
    small, the line continues with something like `20 of 33 layers are on NVIDIA GeForce … and
    the rest on the processor: its free memory does not hold all of the model.` That is a
    partial offload, and it is correct, not a failure.

    ☐ **On a machine without a card:** `Answers run on the processor. llama.cpp found no
    graphics device it can use: …`. Answers behave exactly as before this ticket. The only
    difference is that Settings now says where they run.

    ☐ **On a Mac with Apple silicon** (installed with `deploy/macos/install.sh`): the installer
    line reads `… Answers run on the graphics side of this Mac's chip where llama.cpp can use it,
    and on the processor otherwise.` Settings shows `Answers run on the graphics card.`

25. Run the installer again (an upgrade).

    ☐ **You should see:** the `llama.cpp placed under …` line again, and Askwell answering
    afterwards. The folder is replaced, not merged, so no older build's files are left behind.

---

## Part 4 — automated, every push

| Command | What it covers |
| --- | --- |
| `scripts/dev.sh test tests/test_inference_acceleration_host.py` | The supervisor: reading `--list-devices`; the command with and without a device; full, partial and zero offload, each with its reason; the card failing to load and switching to the processor at once; readiness waiting for `/health` 200 rather than an open port; a model that never finishes loading being stopped; the answering model starting before the other two |
| `bash scripts/fetch-llama-cpp.test.sh` | Fetching each platform's builds against the pins; a checksum mismatch refused; `LICENSE` placed beside the Windows builds |
| `bash scripts/release-artefact.test.sh` | An artefact is refused without its platform's `llama.cpp` builds, and carries them at `deploy/inference/llama.cpp` |
| `bash deploy/linux/install.test.sh`, `bash deploy/macos/install.test.sh` | The installers place the folder, replace it on upgrade, and say so. A source checkout says there is none |
| `deploy/windows/install.test.ps1` (in `api/tests/test_windows_scripts.py` and the Windows workflow) | The same on Windows, plus stopping a running `llama-server` before its folder is replaced or removed |
| `scripts/dev.sh test tests/test_notices.py` | `llama.cpp` (MIT) and `libomp` (`Apache-2.0 WITH LLVM-exception`) pass the licence gate; any other `WITH` exception stays unclear |
| `scripts/dev.sh web-check` | `accelerationLine`: card, processor, a reason appended, and nothing claimed while the assistant is not running |
| `scripts/dev.sh check` | All of the above that run in the API image |

---

## Known gaps

These are not built yet, or not verified. Do not report them as defects of this ticket.

- **Part 3 has not been run.** `0.9.9` is not published yet, and the walkthrough needs its
  download. A fresh install also still needs `ASKWELL_ROOTS_MOUNT` set by hand before it can
  read a folder (#771, escalated as a product decision).
- **An installed Askwell still cannot answer out of the box.** The installers now place
  `llama.cpp`, but not the embedding and reranking models (#810, still open for that half).
- **Real Windows and macOS graphics cards are untested** (#590, #592). The Windows installer's
  stop-before-replace of a running `llama-server` is covered only by tests. It is not known
  whether macOS quarantines a `llama-server` unpacked with `tar` in Terminal. If it does, the
  installer stops and names it, and the fix is the `xattr` step `docs/installing.md` already
  gives for the app.
- **A partial offload and a card that fails to load the model have not been seen on real
  hardware.** The build host's 8 GB card holds all three models, and its driver works. Both
  paths are covered by `test_inference_acceleration_host.py` only. The text in Part 3 step 24 is
  the wording the code produces, not a screen someone has seen.
- **A card that fails after loading, or during a model swap, does not fall back to the
  processor** (#843). The fallback in this ticket covers failure while loading only.
- **Upgrading on Windows with the Askwell window open can fail to replace `llama.cpp`** (#842).
  The window restarts inference, and Windows locks the DLLs it has loaded.
- **The throughput figures in Settings mix card and processor answers.** They are a median over
  the model's last 20 answers, whichever build ran them. Use a stopwatch to compare the two.
- **CUDA was not tried.** Vulkan works on the build host's NVIDIA 580 driver, so the ticket's
  "prefer Vulkan unless measurement shows a reason not to" held. The CUDA runtime cannot be
  redistributed under C9 anyway (`docs/decisions.md`, 2026-09-30).
- **A bigger model is out of scope.** Trying the 9B model on the card is the abstention work
  (#769, #814), after this lands.
