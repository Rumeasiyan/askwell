# Manual test — M7-SET-FE-146, Settings → Model and speed

**Ticket:** `M7-SET-FE-146`. This is the first settings section. It covers the hardware profile, what that profile means in plain terms, and a re-probe. It shows the model in use, marked **Validated** or **Unverified**, with its measured memory and speed. It includes a swap that says the assistant will be briefly unavailable before anything happens, and the retrieval threshold with the same warning the trace panel uses.
**Version under test:** `0.7.27`. Run `cat VERSION` and update this line if the version has moved on.
**Time:** 45 to 60 minutes. Most of it is waiting for answers and for models to load. On this development machine one answer took about 200 seconds.
**Who can run it:** anyone with a browser and a terminal who can copy a file into a folder. You do not need a second real model. Part E makes one by copying the model you already have.

**What is being checked.** The screen is `web/components/settings/model-and-speed.tsx`, and its wording lives in `web/lib/model.ts`. The backend is `askwell.model_select`. The swap runs on the host, in `deploy/inference/askwell-inference`. Speed is llama.cpp's own timing of real answers, and memory is the resident size of the running `llama-server`. The terminal is used only to start Askwell and to place model files, which is how a real user adds a model. Every screen is reached by clicking.

---

## Before you start

In a terminal:

```
cd ~/external/quantum-plus/askwell
cp -n .env.example .env
scripts/dev.sh build-api
scripts/dev.sh web-build
podman compose up -d
scripts/dev.sh db upgrade head
```

**You should see:** the API image build finishes without an error. The web build finishes with a route list and no red error text. Compose reports `postgres`, `redis`, `egress-proxy`, `api` and `worker` as started. The migration ends without an error.

Do not skip `build-api`. The API's code is baked into its image, not mounted, so without a rebuild the running API is the old one and the **Model** part of the section cannot load. This ticket also adds a read-only mount of the models folder into the API, which `podman compose up -d` applies by recreating the container.

In a **second** terminal, start the model on the host and leave it running:

```
scripts/dev.sh inference
```

**You should see:** the supervisor logs that the generation model is ready. Leave this terminal open for the whole test.

In a **third** terminal, start the hardware probe watcher. Step 4's re-probe button needs it:

```
scripts/dev.sh probe --watch
```

Keep one document ready that states a fact you can ask about, such as a PDF or `.txt` with a date or a number in it.

Find your models folder. It is `ASKWELL_MODELS_DIR` in `.env`, and by default `~/.local/share/askwell/models`. List it:

```
ls -la ~/.local/share/askwell/models
```

**You should see:** the answer model (on this machine `Qwen3.5-4B-Q4_K_M.gguf`), the embedding model `bge-m3-FP16.gguf` and the reranker `bge-reranker-v2-m3-FP16.gguf`. If anything else is in the folder, move it out for now, because Part C needs a folder with no spare model in it.

---

## Part A — cold start, and reaching Settings by clicking

### 1. Open Askwell

Open a **private or fresh-profile** browser window, so no earlier session carries over. Go to `http://127.0.0.1:8000`. This is the landing address, the one a user starts from.

**You should see one of two screens:**

- **A fresh install, with nothing added yet:** the welcome screen, "Welcome to Askwell", with four steps: *What this is*, *Check the machine*, *Get the model* and *Add something and ask*.
- **Sources already added:** the **Ask** screen, with a line at the top reading "Askwell 0.7.27 · nothing leaves this machine" and a rail on the left with **Ask**, **Library**, **Clarifications**, **Memory** and **Settings**.

### 2. Get past first run (fresh install only)

Click **Get started** and go through the steps. On *Add something and ask*, add your document.

**You should see:** each step moves to the next without a dead end. Once the document has finished indexing you arrive on **Ask**, with the rail on the left.

If you already had sources, click **Library** in the rail, then the **Add a source** button below the list. Add your document, and wait until **Library** shows it as indexed rather than indexing. **Add a source** is not in the rail itself.

### 3. Open Settings

Click **Settings** in the left rail.

**You should see:** the **Settings** heading. The first section below the introductory text is headed **Model and speed**. It comes before **Folders**, **Storage**, **Privacy and security**, **Your data** and **About**. It has three sub-headings, in this order: **Hardware profile**, **Model**, **Retrieval threshold**.

---

## Part B — what the section says before any question

### 4. Read the hardware profile

Under **Hardware profile**:

**You should see:**

- "Current profile: **<name>**". On this machine it reads **Accelerated**.
- One line saying what that profile means. It is exactly one of these:
  - Light: "8 GB of memory, no graphics card. Slow but usable; voice will struggle."
  - Standard: "16 GB of memory, no graphics card. Comfortable for text; voice usable."
  - Accelerated: "16 GB or more with a graphics card. Fast, and voice works fully."
  - Workstation: "32 GB or more with a large graphics card. Full capability."
- The probe's own reading underneath, for example "31.2 GB RAM with an accelerator, 8.0 GB VRAM."
- If you changed the profile by hand earlier, the name is followed by "(measured as <name>)".
- Only on a machine the probe could not measure, or one below Askwell's minimum, a line in the "inferred" colour: "The probe could not measure this machine, so Askwell is running on the standard profile as a fallback." or "Below what Askwell is built for. It runs, but slowly, and voice will likely not work." Neither appears on this development machine.
- A **Re-run the probe** button, and an **Override the profile** control with **Change profile**.

Click **Re-run the probe**.

**You should see:** the button reads "Re-running…", then goes back to **Re-run the probe**. The profile and reading are refreshed. If the watcher from *Before you start* is not running, a red message names the failure. That is a setup problem, not a defect in this ticket.

### 5. Read the model in use

Under **Model**:

**You should see:**

- If the model file's bytes are the one Askwell ships: "In use: **Qwen3.5 4B (Q4_K_M)**", with a small **Validated** tag in a plain border, and below it "Validated: this model shipped with Askwell and passed its quality checks, including citations and saying when it does not know."
- If they are not — as on the development machine, whose `Qwen3.5-4B-Q4_K_M.gguf` is not byte-identical to the shipped file — "In use: **Qwen3.5-4B-Q4_K_M.gguf**" with an **Unverified** tag. That is correct: the tag is decided by the file's bytes, never its name (issue #672).
- **Memory.** One of two forms, depending on whether the model runs on a graphics card:
  - Graphics card (expected on an **Accelerated** or **Workstation** machine): "N GB of system memory in use by the model, measured now. The part of the model on the graphics card is not included. The model file is 2.6 GB." Here the memory figure can be **smaller** than the file, because most of the model sits on the graphics card.
  - Processor only: "N GB of memory in use by the model, measured now. The model file is 2.6 GB." Here the figure is usually **larger** than the file, because it is the running process and not the file.

  A figure for a graphics-card machine that does **not** say the graphics-card part is excluded is a defect. So is a processor-only figure that does say it.
- **Speed.** "Not measured yet — this model has not answered a question. Ask one, and the real figures appear here."

**Check:** the speed must **never** read `0`, `0 tokens per second` or a blank. If this model has answered questions in an earlier session, you will see real figures here instead. That is correct, because the figures come from stored answers and not from the current session.

**Check:** a copy of the in-use file, offered later as a swap target, must carry the **same** tag as the model in use. A mismatch is a defect.

---

## Part C — no other model to swap to

### 6. Read the swap area

Below the memory and speed lines is a **Swap model.** block.

**You should see:**

- "**Swap model.** Models are read from ~/.local/share/askwell/models." The folder is named as it is on **your** machine, the same path you listed in *Before you start*. It must **not** say `/models`.
- "There is no other model file in ~/.local/share/askwell/models. To try a different model, place its .gguf file in that folder and reopen this page. Askwell does not download models from here."
- No swap buttons. The embedding and reranker models are **not** offered, because they are not answer models.

---

## Part D — real numbers from real questions

### 7. Ask two questions

Click **Ask** in the rail. Ask a question your document answers and wait for the answer to finish. Use a clock and note roughly how many seconds it took from pressing Enter to the last word. Then ask a second question your document answers, and time it the same way.

**You should see:** each answer finishes with at least one citation to your document. If either question is declined ("I don't know" or an abstention), ask another. Declined questions are deliberately not counted in the figures.

### 8. Reopen Settings and read the numbers

Click **Settings** in the rail.

**You should see**, under **Speed.**:

- "A typical answer takes **N** seconds from asking to the last word." **N** should be close to your two timings. Expect it to be within about 10–20% of them. It will not match exactly, because your clock includes the browser.
- "Reading your passages: **N** tokens per second." On this machine this was about 51.
- "Writing the answer: **N.N** tokens per second." On this machine this was about 8.5.
- "Measured over the last 2 answers from this model."

**Memory.** The line still shows a measured figure. It may have grown a little since step 5, because the model pages in as it is used.

**Check for plausibility:** a slow writing rate with a long typical answer time matches a slow experience. If the answers felt fast and the page claims 200 seconds, or the reverse, that is a defect.

---

## Part E — swapping to a model you supplied

### 9. Place a second model file

In a terminal, copy your model under a new name. `--reflink=auto` avoids using the disk space twice where the filesystem allows it:

```
cp --reflink=auto ~/.local/share/askwell/models/Qwen3.5-4B-Q4_K_M.gguf ~/.local/share/askwell/models/my-own-model.gguf
```

If you have a genuinely different small `.gguf` answer model, you may place that instead. That is the ticket's own scenario, "places a smaller model".

### 10. Reload the section

Click **Ask** in the rail, then **Settings** again.

**You should see:** in the swap area there is one row, **my-own-model.gguf**. It has an **Unverified** tag in the "inferred" colour, the text "my-own-model.gguf · 2.6 GB", and a **Swap to this model…** button. The model already in use is **not** listed as something to swap to.

On this machine, a copy of the in-use model is **Unverified**. That is correct, because the file's bytes do not match anything Askwell ships. A file that *is* byte-identical to a shipped model would be listed under its display name, for example "Qwen3.5 4B (Q4_K_M)", with a **Validated** tag, whatever its file name. You can only see that case on a machine that has the genuine shipped file. There, the confirmation in step 11 has no "not been tested" sentence, and its button reads **Swap now** instead of **Swap to this unverified model**.

### 11. Open the swap confirmation, and cancel it

Click **Swap to this model…**.

**You should see** a box open **under that row**, before anything else happens, containing:

1. "While the new model loads, the assistant is unavailable — questions wait until it is ready, which takes up to 5 minutes. Document search, browsing and your library keep working throughout. If the new model fails to load, Askwell goes back to Qwen3.5 4B (Q4_K_M) and says why. The swap is recorded in the decisions log."
2. This sentence, in the "inferred" colour: "This model has not been tested against Askwell's checks. Citations and "I don't know" are behaviours Askwell verifies for the models it ships. With your own model, they are not guaranteed."
3. Two buttons: **Swap to this unverified model** and **Cancel**.

**Check:** there is **no** "don't show again", "remember" or checkbox of any kind. While the box is open, the **Swap to this model…** button is greyed out.

Click **Cancel**. The box closes and nothing has changed: **In use** is the same.

Click **Swap to this model…** again. **The same box, with the same statement, appears again.** It must come back every time.

### 12. Confirm the swap, and use search while it runs

Click **Swap to this unverified model**.

**You should see:** the rows are replaced by "Swapping to my-own-model.gguf. The assistant is unavailable until it has loaded — up to 5 minutes; search and browsing still work."

**Leave this tab open on Settings.** If you navigate away from it, you will not see the outcome message in step 13. Open a **new tab**, go to `http://127.0.0.1:8000`, and:

- On **Ask**, look for a panel reading "Search your files while the assistant is unavailable", with a **Search by keyword** box. It appears once the assistant reports unavailable. Type a word from your document and click **Search**.
  **You should see:** results from your document. There is normally **no** "Keyword-only while the assistant is unavailable." line: a swap restarts only the answer model, and the embedding model that powers full search keeps running. That line appearing during a swap means the embedding model went down too — note it, because it is not what a swap should do.
- Click **Library** in the rail and open your document.
  **You should see:** it opens and you can page through it.
- Back on **Ask**, type a question and send it.
  **You should see:** the question waits, and is answered once the swap finishes. It is **not** refused with an error.

The load may be quick, because the file is identical and already in the page cache. If the swap finishes before you reach the new tab, you will not see the search panel. Repeat the swap with a genuinely different model, or record it as `N/V` on this machine.

### 13. After it loads

Go back to the **Settings** tab.

**You should see:**

- "Now answering with my-own-model.gguf. Recorded in the decisions log."
- **In use:** **my-own-model.gguf**, with an **Unverified** tag in the "inferred" colour.
- Below it, in the "inferred" colour: "Unverified: you supplied this model. This model has not been tested against Askwell's checks. … Its answers are marked."
- **Speed.** "Not measured yet — this model has not answered a question." The figures are per model, so they start again. The one exception: if the question from step 12 has already been answered, it shows "Measured over the last 1 answer from this model."
- The swap area now offers **Qwen3.5 4B (Q4_K_M)** or **Qwen3.5-4B-Q4_K_M.gguf**, the model you just left. It carries the same tag it had as the model in use in step 5.
- Only if the new file is large for this machine's memory: a second line, in the "inferred" colour, beginning "This model file is N GB and this machine has N GB of RAM. It may load slowly…". A copy of the 2.6 GB model will not trigger it on a machine with 8 GB or more, so its absence here is expected.

Click **Ask** in the rail, find the answer to the question from step 12 (or ask a new one), and look at it.

**You should see:** the answer carries the **Unverified model** marker from `M7-SET-FE-146a`, and it has no close or dismiss control.

---

## Part F — a swap that fails

### 14. Place a file that claims to be a model but is not

In a terminal:

```
{ printf GGUF; head -c 4096 /dev/urandom; } > ~/.local/share/askwell/models/broken.gguf
```

Then, in the browser, click **Ask** in the rail and then **Settings**.

**You should see:** **broken.gguf** listed, tagged **Unverified**, at about "1 MB".

### 15. Swap to it

Click **Swap to this model…** next to **broken.gguf**. Read the statement, then click **Swap to this unverified model**.

**You should see:** "Swapping to broken.gguf. The assistant is unavailable until it has loaded — up to 5 minutes; search and browsing still work." for a short while. Then, at the bottom of the swap area, a message in red: "The swap to broken.gguf failed: Could not load broken.gguf. Staying on my-own-model.gguf." Higher up, the **In use** line still names my-own-model.gguf. The failure is named, and so is the model that is still in use.

- **In use** is still **my-own-model.gguf**.
- Click **Ask** in the rail and ask a question. It is answered. The previous model was restored and is working.

### 15a. Start two swaps at once (issue #675)

Open **Settings** in two browser tabs. In the first tab, swap to **Qwen3.5 4B** (or whichever other model is listed) and confirm. Within a few seconds, while the first tab still reads "Swapping to …", swap to the same model in the second tab and confirm.

**You should see:** in the second tab, straight away, a message in red: "The swap to <name> failed: Another model swap is already running. Nothing was changed by this request." The first tab finishes normally with "Now answering with …". Then click **Ask** and ask a question: it is answered. Nothing is stuck.

If the first tab has already reached "Now answering with …" before you confirm in the second, the second swap simply runs too. You were too slow for this load time, not a defect. Try again with the second tab's **Swap to this model…** box already open, so only the confirm click is left.

Close the second tab. In the first, swap back to **my-own-model.gguf** as in step 12 and wait for "Now answering with my-own-model.gguf", so the steps below read as written.

---

## Part G — the retrieval threshold

### 16. Read the threshold control

Click **Settings** in the rail and scroll to **Retrieval threshold** inside **Model and speed**.

**You should see:**

- "Lowering the threshold makes Askwell answer from weaker matches — more answers, more of them wrong. Raising it makes Askwell abstain more often — fewer answers, but every one it gives is more likely to be right. There is no automatic tuning: every change here is yours, and every change is recorded."
- "Current threshold: 0.NN".
- A number box and a **Change threshold** button. There is **no slider**. Nothing changes until you click the button.

### 17. Change it, and change it back

Note the current value. Type a value 0.05 higher and click **Change threshold**.

**You should see:** "Changing…" on the button, then "Threshold changed from 0.NN to 0.MM. Recorded in the decisions log." The **Current threshold** line shows the new value.

Type `2` and click **Change threshold**. **You should see:** "Enter a number between 0 and 1." in red, and the threshold does not change.

Put the original value back the same way.

### 18. Compare with the trace panel

Click **Ask** in the rail. Ask a question your document **nearly** answers but does not. For example, ask about a topic next to the one it covers.

If Askwell abstains, click **How did you get this?** under the answer.

**You should see:** if the trace shows a near-miss ("The closest passage scored 0.NN, just under the 0.MM threshold."), the **same** warning paragraph as step 16, word for word, and the same number box and **Change threshold** button. If Askwell abstained with nothing close, no threshold control appears there. That is correct behaviour (`M5-TRACE-FE-122`), and this step becomes `N/V`. Try a question closer to your document's content.

---

## Part H — for the checker: the decisions record

Settings has no screen yet that lists individual decision records. To confirm the swaps and threshold changes above were recorded, run this in a terminal:

```
scripts/dev.sh psql -c "SELECT occurred_at, kind, payload FROM audit_decisions WHERE kind IN ('model_swap_requested','retrieval_threshold_changed') ORDER BY occurred_at DESC LIMIT 8;"
```

**You should see** six rows, newest first:

- Two `retrieval_threshold_changed` rows from step 17, each with `"previous"` and `"new"`. There is none for the rejected `2`.
- Two `model_swap_requested` rows with `"ok": true` from step 15a: the swap back to `my-own-model.gguf`, and below it the first tab's swap. There is none for the second tab's refused swap.
- A `model_swap_requested` row for `broken.gguf` with `"validated": false`, `"ok": false` and the reason "Could not load broken.gguf. Staying on my-own-model.gguf."
- One for `my-own-model.gguf` from step 12, with `"validated": false` and `"ok": true`.

If you repeated a swap in step 12, there are more `model_swap_requested` rows than this and the oldest may fall outside the eight shown. That is expected.

Then, in the browser, click **Settings**, scroll to **Your data**, and click **Verify the log**.

**You should see:** "Checking… Ns" for a moment, then two panels: "Decisions — chain intact" and "Interactions — chain intact", each with "N records checked." A "chain broken" panel is a defect.

---

## Part I — the model file is missing

### 19. Swap back to the original model

In **Settings**, click **Swap to this model…** next to the original model (**Qwen3.5 4B (Q4_K_M)** or **Qwen3.5-4B-Q4_K_M.gguf**), read the statement, and confirm.

**You should see:** "Now answering with …" naming the original model, and **In use** shows it with the tag it had in step 5.

### 20. Take the model file away

In the **second** terminal, the one running `scripts/dev.sh inference`, press **Ctrl-C** to stop it. Then in any terminal:

```
mv ~/.local/share/askwell/models/Qwen3.5-4B-Q4_K_M.gguf ~/.local/share/askwell/models/Qwen3.5-4B-Q4_K_M.gguf.away
```

Start the model again in the second terminal with `scripts/dev.sh inference`.

**You should see:** the supervisor logs that there is no model file, and it does **not** keep restarting.

In the browser, click **Ask** in the rail, then **Settings**.

**You should see**, under **Model**, a box with a red border:

- "The model file is missing, so the assistant cannot answer."
- "No model file at …/Qwen3.5-4B-Q4_K_M.gguf. Askwell does not download models. Put one there, or set ASKWELL_INFERENCE_MODEL_PATH." The "…" is the full path on your machine, as the model supervisor sees it.
- "Place the model file in ~/.local/share/askwell/models, then restart Askwell. The manual install steps are the same as on the welcome screen. Document search keeps working meanwhile." The folder is your machine's, not `/models`.
- There is no **In use** line. The "Validated: …" or "Unverified: …" explanation from step 5 may still show under the red box, because it describes the model Askwell was last set to use. That is expected.
- **Memory.** "Not measured — the assistant is not running." There is no file size after it, because the file is gone.

### 21. Put it back

Press **Ctrl-C** in the second terminal, then:

```
mv ~/.local/share/askwell/models/Qwen3.5-4B-Q4_K_M.gguf.away ~/.local/share/askwell/models/Qwen3.5-4B-Q4_K_M.gguf
```

Start `scripts/dev.sh inference` again, wait for it to report ready, then click **Ask** and **Settings** in the rail.

**You should see:** the red box is gone, and **In use** shows the original model with its step 5 tag.

---

## Clean up

1. Check that **In use** in **Settings** is the original model. If it is not, swap back to it as in step 19 and wait for "Now answering with …".
2. In a terminal:

   ```
   rm ~/.local/share/askwell/models/my-own-model.gguf ~/.local/share/askwell/models/broken.gguf
   ```

3. Put back anything you moved out of the models folder in *Before you start*.

Do step 1 before step 2. Deleting the file that is in use leaves the assistant with a missing model after the next restart.

---

## Known gaps — not defects

- **No model download.** Models are bundled or placed by hand. The swap area says so.
- **Speed is a rolling figure, not a benchmark.** It covers the last 20 measured answers from the model in use. Declined answers and answers with no timing do not count.
- **The swap duration shown is a ceiling, not a forecast.** "Up to 5 minutes" is the backend's own timeout (`SWAP_TIMEOUT_SECONDS`), not a prediction for this machine.
- **A restarted supervisor forgets a swap** (issue #670). If `scripts/dev.sh inference` is restarted on its own, it boots the default model, and the swap is not put back until the API restarts. Settings and the answer markers name what is actually loaded in the meantime, judged by its bytes — they no longer name the swapped model.
- **Leaving Settings mid-swap loses the outcome message.** The swap still completes or rolls back, and **In use** is correct when you return, but the "Now answering…" or failure line is not shown again.
- **First run still names the container path** in its manual-install wording (issue #668). Settings does not.
- **Decision records have no viewer in the interface.** Part H uses a terminal.
- **Memory can read "Not measured"** on a platform with neither `/proc` nor `ps`, or while the assistant is not running. The model file's size is shown alongside for scale.
