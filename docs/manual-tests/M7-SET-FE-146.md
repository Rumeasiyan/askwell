# Manual test — M7-SET-FE-146, Settings: model and speed

**Ticket:** `M7-SET-FE-146` — the model-and-speed section of Settings: hardware profile with
re-probe and override, model in use with swap and the validated/unverified distinction, memory
footprint, throughput, and the retrieval threshold with its warning.
**Version under test:** `0.7.17` (check `cat VERSION` — bump this line if it has moved on).
**Time:** about 30 minutes, plus a first stack build.
**Who can run it:** anyone who can open a browser, drag a file into a folder, and paste one line
into a terminal.

**What is being checked.** `web/components/settings/hardware-profile.tsx`,
`web/components/settings/model-swap.tsx`, `web/components/settings/retrieval-threshold.tsx`,
`web/lib/model.ts` against `GET/POST /model` and `/model/select`
(`api/src/askwell/model_select.py`, `M7-SET-BE-145a`), `GET /probe` (`M7-PROBE-FE-138`'s
backend), and `askwell.retrieve.set_retrieval_threshold`.

**Human review flag on this ticket.** It renders wording a user reads (the unverified-model
statement, the unavailability statement). Quote the exact strings you see in your run so
whoever reviews copy can check them against `docs/ux/settings.md` §2 verbatim.

---

## Before you start

Bring the stack up with the built frontend, since the API serves `web/out`, not live source:

```
podman compose up -d
scripts/dev.sh db upgrade head
scripts/dev.sh web-build
podman compose restart api
scripts/dev.sh inference
```

`scripts/dev.sh inference` runs on the host, not in a container — leave it running in its own
terminal for the whole walkthrough. Model swapping in Part C needs a real GGUF file to swap to.
If you do not have a spare one, a small one will do — any file that starts with the four bytes
`GGUF` passes validation, and a tiny/garbage GGUF is expected to fail to load, which Part C
exercises on purpose. To make a file that passes the file-type check but fails to load:

```
mkdir -p ~/askwell-test/models
printf 'GGUFnotarealmodel' > ~/askwell-test/models/fake.gguf
```

If you have access to a genuinely small real GGUF model, place it in the same folder as well —
Part C's later steps use it to confirm a real swap.

---

## Part A — cold start, asking two real questions, then reaching the section

### 1. Open the application

In a browser, go to `http://localhost:8000/`.

**Expect:** the Ask screen loads. The left rail shows **Ask**, **Library**, and **Settings**
among its entries.

### 2. Ask two questions

If no source is indexed yet, add one from **Library** first (any short PDF or text file).
Then, from the Ask screen, type a question about it and submit. Wait for the answer. Ask a
second, different question and wait for that answer too.

**Expect:** both turns produce an answer or a stated abstention — either is fine for this
ticket, since the point is only that two real turns happened before you look at settings.

### 3. Open Settings

Click **Settings** in the left rail.

**Expect:** the page loads with an **H1** reading "Settings" and, further down, an **H2**
reading "Model and speed" containing three controls in order: the hardware profile, the model
swap, and the retrieval threshold.

---

## Part B — profile, model, memory, throughput

### 4. Read the hardware profile

Under **Model and speed**, look at the first block.

**Expect:** a line reading "Current profile: **\<Profile\>**" (Light, Standard, Accelerated, or
Workstation) and a plain-terms sentence naming what it means for this machine (RAM, GPU
presence, and a rough answer-time expectation). Compare the stated expectation against how long
your two questions in step 2 actually took — write down whether it was plausible.

### 5. Re-run the probe

Click **Re-run the probe**.

**Expect:** the button reads "Re-running…" briefly, then the profile line updates (it may show
the same profile if nothing on the machine changed).

### 6. Read the model in use

Look at the next block.

**Expect:** a line reading "Model in use: **\<name\>** (Validated)" — on a fresh install with
no override, the model is one Askwell shipped for the detected profile, so it is marked
**Validated**, not **Unverified**.

### 7. Read memory footprint and throughput

Directly below.

**Expect:** "Memory footprint: **\<N.N\> GB**" — a real, plausible file size for the model on
disk, not a placeholder like `0.0 GB`. And "Throughput: not yet measured. Askwell does not yet
track tokens per second from real turns." — even though you already asked two real questions in
step 2. This is a known gap, not a bug: record the exact sentence so a later ticket that adds
real measurement can be checked against it.

---

## Part C — swapping the model

### 8. Read the unavailability and unverified statements before swapping anything

Below the model block, find the swap subsection.

**Expect:** a paragraph containing both, verbatim:

> Swapping makes the assistant briefly unavailable while the new model loads. Browsing and
> retrieval keep working during that time.

> This model has not been tested against Askwell's checks. Citations and "I don't know" are
> behaviours Askwell verifies for the models it ships. With your own model, they are not
> guaranteed.

Both sentences are shown together, before any swap is requested — not only after you commit to
one.

### 9. No alternative present

If you have not yet placed a file in the expected models directory, look at the line below the
statements.

**Expect:** "No alternative model found. Place a GGUF file at **\<path\>** or elsewhere in the
same directory to swap to it." — with a real absolute path, matching the directory
`~/.local/share/askwell/models/` maps to inside the container (check your `.env`/compose mount
if unsure).

### 10. Place the broken file and find it listed

Copy `fake.gguf` from the setup step into that models directory (on the host path that mounts
into it), then reload Settings.

**Expect:** "Found in the models directory:" appears with a row for `fake.gguf` and a **Swap to
this model** button. The "No alternative model found" line is gone.

### 11. Swap to the broken file

Click **Swap to this model** next to `fake.gguf`.

**Expect:** the button area shows "Swapping…", and — while it is in progress — open a second
browser tab to the Ask screen and submit a question. **Confirm retrieval still answers or
abstains normally during the swap** rather than hanging or erroring; this is the ticket's own
acceptance criterion, not incidental. Once the swap call resolves, expect an error line naming
the failure: "The swap failed: **\<reason\>**. The previous model is still in use." Confirm the
model-in-use line still names the original, previously-working model, not `fake.gguf`.

### 12. Swap to a real user-supplied model (if you have one)

If you placed a genuine small GGUF alongside `fake.gguf`, click **Swap to this model** next to
it instead.

**Expect:** after the swap resolves, a confirmation line reading "Swapped to **\<path\>**.
Recorded in the decisions log." and the model-in-use line now reads "Model in use: **\<name\>**
(**Unverified**)" with the unverified statement shown directly beneath it — this time as a
standing fact about the model in use, not only inside the swap subsection. Ask a question from
the Ask screen and confirm it still answers.

### 13. Swap by typing a path

In the "Or give a full path to a model file" field, type a path to a model file you know
exists (the same real one from step 12, or back to the original shipped model's path if you
noted it from step 6/9), and click **Swap**.

**Expect:** the same swap behaviour as above — busy state, then either a success confirmation
or a named failure, never a silent no-op.

### 14. Swap with an empty path

Clear the path field and click **Swap**.

**Expect:** "Give the full path to a model file." appears without any request being sent (no
busy state).

---

## Part D — retrieval threshold

### 15. Read the current threshold and warning

Scroll to the last control in the section.

**Expect:** the same warning text `docs/ux/trace.md` §4 and the abstention trace panel use —
confirm it explicitly rather than reading it as "similar": open a conversation that has
abstained (or trigger one with an obscure question) to see the trace panel's own threshold
control, and compare the warning sentence word-for-word against this one. There is no slider —
a number field and a **Change threshold** button.

### 16. Change the threshold

Enter a different value (e.g. current + 0.05) and click **Change threshold**.

**Expect:** "Threshold changed from **\<old\>** to **\<new\>**. Recorded in the decisions log."
Reload the page and confirm the new value is what now shows as current.

### 17. Enter an invalid value

Enter `2` (outside 0–1) and click **Change threshold**.

**Expect:** "Enter a number between 0 and 1." with no request sent and the previous valid value
unchanged.

---

## Known gaps

Do not report these as defects — they are stated in the code's own comments as deliberately
not built yet, or out of scope for this ticket:

- **Throughput is never shown as a number, not even a rolling average.** `web/lib/model.ts` and
  `api/src/askwell/model_select.py` both say plainly that nothing in the backend yet records a
  turn's token count or duration anywhere `GET /model` can read it back from. The ticket's own
  "known gap" line anticipated this; it is filed as a follow-up rather than invented here.
- **Memory footprint is file size on disk, not resident RAM.** `llama-server`'s actual RAM use
  once a model is loaded is not readable from this process, and the code says so. Do not expect
  the figure to match what a process monitor shows for `llama-server`.
- **Model download is out of scope.** There is no in-product fetch-a-model control on this
  screen; placing a file by hand (Part C) is the only supported path, per the ticket's own Out
  of Scope line.
- **The size-warning path (`_size_warning` in `model_select.py`, model too large for probed
  RAM) was not exercised.** It requires a model file large enough relative to this machine's
  RAM to trigger, which is impractical to stage in a general walkthrough — if you have such a
  file, confirm the warning names both the model size and the machine's RAM and that the swap
  still proceeds rather than being blocked.
- **Hardware profile override to an unsupported tier** (e.g. forcing Workstation on a Light
  machine) was not driven to the point of a subsequent model load failure — `hardware-profile.tsx`
  states the consequence before the change, but confirming the failure path after choosing an
  unsupportable override was not part of this run.
