# Manual test — M7-OFFLINE-DEPLOY-144, offline model bundle and manual model placement

**Ticket:** `M7-OFFLINE-DEPLOY-144` — the offline path: a user places a model file themselves,
Askwell finds and validates it, a corrupt file is named rather than crashing, and settings
names the expected file and location when a model is missing.
**Version under test:** `0.7.15` (`docs/BRAIN.md`).
**Time:** about 90 minutes if the light-tier model is already on disk (a prior session's
download); add 15–25 minutes for the light-tier download itself if not, and **up to an hour
more** for the wrong-profile step, which needs the 9B model (6.2 GB) — see step 12, which is
the one step you may reasonably skip on a slow connection.
**Who can run it:** anyone who can paste a line into a terminal and use a file manager.

**What is being checked.** This ticket's own scope has two halves, and only one landed —
`docs/decisions.md`, 2026-09-23, is explicit about this, and it is worth reading before you
start. **Built:** manual placement at a named path, checksum-based discovery and validation
(at boot and on demand), a corrupt file named by path rather than crashing, a wrong-profile
file accepted with the profile adjusted and stated, and several present files listed as
swap candidates. **Not built:** the bundle itself — "images, the native binary and the
profile's models" — which stays on issue #559 (no packaging pipeline yet produces the images
or shell binary a bundle would sit beside). This walkthrough tests the built half only. Do not
report the absence of an installable bundle as a defect in this ticket; it is issue #559.

**The one thing to watch for throughout.** Nothing here may cause Askwell itself to make a
network request for a model. The one legitimate model fetch is the button you press in step 6;
every other model file this test uses arrives by a `curl`/file-manager action *you* perform
outside Askwell, exactly the way an air-gapped user's file would have arrived on a USB stick.
If anything in the API or web containers tries to reach the network on its own, the egress
proxy's `/network` counter (checked throughout) is what will catch it.

---

## Before you start

You need a terminal and Podman.

### 1. Set up

```
cd ~/external/quantum-plus/askwell
cp -n .env.example .env
```

Open `.env`, find `POSTGRES_APP_PASSWORD`, and put any word after the `=` if it is blank.

Note the model path this build expects, from the same file:

```
grep ASKWELL_INFERENCE_MODEL_PATH .env.example
```

**You should see:** `ASKWELL_INFERENCE_MODEL_PATH=~/.local/share/askwell/models/Qwen3.5-4B-Q4_K_M.gguf`.
That expanded path — with your own username in place of `~` — is the one named location this
whole ticket is about. Write it down; you will move a file in and out of it repeatedly below.

### 2. Bring the stack up

```
podman compose up -d
scripts/dev.sh db upgrade head
```

**You should see:** services started, and migration output ending with no error.

### 3. Start native inference on the host, in its own terminal

```
scripts/dev.sh inference
```

Leave this running for the whole test — it is the host-side process that actually loads
whatever file sits at the path from step 1, and it is what step 8's cited answer depends on.
Do not close this terminal.

---

## Cold start: launch and see the first-run sequence

### 4. Open Askwell

In a browser, go to:

```
http://127.0.0.1:8000
```

**You should see:** the page redirect itself to a **Welcome to Askwell** screen — nothing was
clicked to get there; a fresh install with no source ever indexed lands here automatically. A
row of four numbered steps runs across the top: **1 What this is · 2 Check the machine · 3 Get
the model · 4 Add something and ask**, with step 1 highlighted.

**You should also see:** a paragraph stating Askwell reads your files on this machine, nothing
is uploaded, and two bolded facts — **it works offline** and **your files stay where they
are**. Click **Get started**.

### 5. The machine check

**You should see:** a sentence describing this machine's hardware and what to expect from it —
something like *"16 GB, no GPU. Answers in about 15 seconds. Voice will work."* — and, below
it, an offer to **Set a passphrase?** with **Set a passphrase** and **Not now** buttons. Click
**Not now**.

**You should see:** the passphrase offer disappear (it is only ever shown once). Click
**Continue**.

---

## Step 3, "Get the model" — the part this ticket is about

You now land on the step that will occupy the rest of this test. Do not click **Continue** past
it until the final check in step 11 — you are going to drive it through several states first.

### 6. If no model file exists yet, get one the ordinary way once

Check whether the path from step 1 already holds a file:

```
ls -la ~/.local/share/askwell/models/Qwen3.5-4B-Q4_K_M.gguf
```

If it does not exist, click **Download** on the screen.

**You should see:** a progress bar, a byte count growing (*"1.2 GB of 3.0 GB — about 4 minutes
left"*), and a **Cancel** button. Let it run to completion.

**You should see, when it finishes:** the panel switches to **Ready.** in green/provenance
text.

If the file already existed from a prior session, skip the click — you should see **Ready.**
immediately on landing here.

Confirm zero outbound requests were attributed to anything except this one deliberate download:

```
curl -s -c /tmp/askwell.cookies -H 'Accept: text/html' http://127.0.0.1:8000/ -o /dev/null && curl -s -b /tmp/askwell.cookies http://127.0.0.1:8000/network | jq
```

**You should see:** a JSON body reporting outbound activity. Whatever count is there, note it —
it should not move again for the rest of this test except where a step explicitly says a
download is expected (this is the last one).

You now have a real, checksum-valid model file at the expected path. Copy it aside — you will
need clean copies to restore between the states below:

```
cp ~/.local/share/askwell/models/Qwen3.5-4B-Q4_K_M.gguf ~/askwell-model-good.gguf
```

### 7. Missing model — the file is not there at all

With the file still showing **Ready.** on screen, move it out of the way and tell the running
inference process to notice by restarting it (`Ctrl+C` the `scripts/dev.sh inference` terminal
from step 3, then re-run it):

```
mv ~/.local/share/askwell/models/Qwen3.5-4B-Q4_K_M.gguf ~/askwell-model-missing.gguf
```

Restart the API container so `run_startup_discovery` runs against the now-empty path:

```
podman compose restart api
```

**You should see, in the API's logs:**

```
podman compose logs api --since 2m | grep model_startup_discovery
```

a line with `status=idle` (or `failed`, if it re-ran fast enough to see nothing on disk yet —
either is the "no file" case) naming the target path.

Back in the browser, reload the welcome page (F5). Because the API restarted mid-session,
you land back at step 1 — click through **Get started → Continue** to reach step 3 again.

**You should see:** the **idle** state again — a **Download** button and an **I already have
the file** button, no leftover progress from the deleted file. This is the same screen a
genuinely fresh air-gapped install would show, since it has never had a file to begin with.

Click **I already have the file**.

**You should see:** a panel open stating *"On a slow or air-gapped connection: download
[model name] yourself and place it at exactly this path, then verify it —"* followed by the
exact path from step 1 in a code block, and a **Verify the file** button. **This sentence is
the acceptance criterion "settings names the expected file and location when a model is
missing", satisfied on the welcome screen** — see **Known gaps** below for where it is not yet
also satisfied.

Click **Verify the file** without placing anything.

**You should see:** the button read **Checking…** briefly, then the screen still shows the
manual-placement panel (nothing changed, because there is still nothing at the path).

### 8. Corrupt model — a file is there, but it is not right

```
cp ~/askwell-model-missing.gguf ~/.local/share/askwell/models/Qwen3.5-4B-Q4_K_M.gguf
head -c 500000000 ~/askwell-model-missing.gguf > ~/.local/share/askwell/models/Qwen3.5-4B-Q4_K_M.gguf
```

That truncates a real GGUF file to its first 500 MB — enough to still start with the right
magic bytes but fail every checksum in the catalog.

Click **Verify the file** again.

**You should see:** the panel switches to a red-marked failure message naming **the exact
path** and stating that the file *"does not match any model Askwell recognises — it may be
corrupt, incomplete, or the wrong file. Re-download it, or replace it with the correct file."*
This is the acceptance criterion "a corrupt model is named rather than crashing" — nothing in
the browser or the API logs shows a stack trace or a bare 500 for this.

Confirm the same statement is visible from the API directly:

```
curl -s -X POST http://127.0.0.1:8000/setup/model/verify-manual \
  -H 'content-type: application/json' -d '{"tier":"light"}' | jq
```

**You should see:** `"status":"failed"` and an `"error"` field with the same message,
containing the path from step 1.

### 9. Wrong profile — a real model for a different tier, placed here by mistake

This is `models_catalog.py`'s own second entry — `Qwen3.5 9B`, the model `accelerated` and
`workstation` tiers use. A person who downloaded the wrong file for their machine and put it in
place is exactly the scenario this ticket's edge case names, and it needs a second real model
to test honestly rather than faked.

**This step downloads 6.2 GB. Skip it — and say so in your results — if your connection makes
that unreasonable; every other step in this document is unaffected.**

```
curl -L -o ~/askwell-model-9b.gguf \
  https://huggingface.co/bartowski/Qwen_Qwen3.5-9B-GGUF/resolve/main/Qwen_Qwen3.5-9B-Q4_K_M.gguf
```

(This `curl` is you, not Askwell — it never touches the container network or the egress proxy,
the same way plugging a USB stick in would not.)

Put it at the expected path, *as if* it were the light-tier file someone meant to place there:

```
cp ~/askwell-model-9b.gguf ~/.local/share/askwell/models/Qwen3.5-4B-Q4_K_M.gguf
```

Click **Verify the file** on the welcome screen (still showing the light tier, since that is
the profile this machine probed to).

**You should see:** the panel switch to **Ready.**, and directly under it a sentence reading
close to *"The file you placed is Qwen3.5 9B (Q4_K_M) — Askwell adjusted your profile to match
it."* **This is the "accepted, with the profile adjusted and stated" edge case** — the file was
never refused for being the wrong tier; it was correctly identified as a real, checksum-valid
model and the profile moved to match it.

Confirm the profile change was recorded as a decision, not just shown on screen:

```
podman compose exec api askwell-verify 2>&1 | tail -5
scripts/dev.sh psql -c "select kind, payload from audit_decisions order by occurred_at desc limit 5;"
```

**You should see:** a row with `kind` `model_profile_adjusted` and a `payload` containing
`requested_tier: "light"` and `resolved_tier: "accelerated"`, and the hash-chain verifier
reporting no break.

Restore the light-tier file so the rest of the test uses the profile this machine actually
probed to:

```
cp ~/askwell-model-good.gguf ~/.local/share/askwell/models/Qwen3.5-4B-Q4_K_M.gguf
```

Click **Verify the file** once more.

**You should see:** **Ready.**, and this time no wrong-profile sentence — the resolved file
matches the tier that was actually asked for.

### 10. Several models present — the extra file is offered as an alternative

With the good light-tier file back in place, also leave the 9B one sitting in the same
directory under its own catalog filename (not overwriting anything):

```
cp ~/askwell-model-9b.gguf ~/.local/share/askwell/models/Qwen_Qwen3.5-9B-Q4_K_M.gguf
```

Ask the API directly what it now sees (there is no settings-screen swap picker yet — see
**Known gaps**):

```
curl -s http://127.0.0.1:8000/model | jq '.alternatives'
```

**You should see:** a one-item array naming the 9B file — `tier: "accelerated"`, its
`display_name`, `filename`, and full `path` — distinct from the file currently active at
`expected_path`. **This is the "several models present" edge case**: the configured file is
what loads, and the other one is named as available for swapping rather than left for you to
discover by browsing the directory.

Clean it up so later steps are not confused by it:

```
rm ~/.local/share/askwell/models/Qwen_Qwen3.5-9B-Q4_K_M.gguf
```

### 11. Continue past step 3

Back on the welcome screen, confirm it still reads **Ready.**, then click **Continue**.

**You should see:** step 4, **"Add something and ask"**, headed with a note that the previous
step's add box is still open above and an **Add a source** button/panel.

---

## Add something, ask, and confirm the citation

### 12. Add a real file while nothing is a demo corpus

```
mkdir -p ~/askwell-offline-test
printf '%s\n' '%PDF-1.4' 'Askwell manual test M7-OFFLINE-DEPLOY-144.' \
  'This document exists only to be cited.' > ~/askwell-offline-test/offline-note.pdf
```

Drag `offline-note.pdf` onto the window, or use the add panel already open on step 4. When
asked which folder it is in, answer:

```
/home/you/askwell-offline-test
```

(with your own username), and confirm the add.

**You should see:** the file queued, and — because the inference process from step 3 is up and
ingestion runs in the background — within a short wait a suggested question drawn from the
file's own content appears, or you can type your own.

### 13. Ask a question and read the citation

Ask: *"What does the manual test document say?"*

**You should see:** an answer that quotes or paraphrases the file's content, with a citation in
the provenance margin naming `offline-note.pdf`. Click the citation.

**You should see:** the source viewer open showing the file's own text, confirming the answer
is grounded in the file you added — not invented, and not fetched from anywhere.

### 14. Confirm the network count did not move

```
curl -s -c /tmp/askwell.cookies -H 'Accept: text/html' http://127.0.0.1:8000/ -o /dev/null && curl -s -b /tmp/askwell.cookies http://127.0.0.1:8000/network | jq
```

**You should see:** the same count you noted in step 6 — asking a question, adding a source and
everything in steps 7–13 made no outbound request. The one legitimate model download in step 6
remains the only network activity Askwell itself performed in this entire test.

---

## Tidy up

```
rm -rf ~/askwell-offline-test ~/askwell-model-missing.gguf ~/askwell-model-9b.gguf ~/askwell-model-good.gguf
```

Press `Ctrl+C` in the `scripts/dev.sh inference` terminal from step 3.

```
podman compose down -v
```

---

## Known gaps

Deliberately not built, or already recorded elsewhere. Do not report these as defects found by
this test.

1. **No installable bundle.** "Images, the native binary and the profile's models" — this
   ticket's own first scope line — was not attempted. Issue #559 is the tracker; this walkthrough
   ran from a source checkout with `podman compose`, not a real bundle, because nothing produces
   one yet.

2. **No settings-screen model section.** `docs/ux/settings.md` §2 and §8's "model file missing"
   state describe a screen (`M7-SET-FE-146`) that has no frontend yet — `web/app/settings/page.tsx`
   has six sections and none of them is "Model and speed". The backend it depends on
   (`GET /model`, `POST /model/select`) is built and was exercised directly by `curl` in steps
   10 and elsewhere, matching `docs/manual-tests/M7-SET-BE-145a.md`'s own precedent for the same
   gap. The "expected file and location" statement is satisfied today only on the welcome
   screen (step 7), not from Settings — a returning user whose model file goes missing *after*
   their first source was indexed will not see the welcome screen again (it only shows before a
   first source is indexed) and currently has no in-app surface naming the expected path at all.
   That is a real product gap worth its own issue if one does not already exist; check before
   filing.

3. **No real air-gapped machine.** This test proves zero outbound requests via the egress
   proxy's own counter and by sourcing every model file from outside the container network, but
   it did not run on a machine with its network interface physically disabled, the way
   `docs/manual-tests/M1-ADD-FE-022.md`'s own network-down section does for a different feature.
   The mechanism is the same either way (no route exists for the containers regardless), but a
   literal cable-out run has not been performed for this ticket.

4. **Startup discovery is logged, not surfaced.** `model_startup_discovery` (step 7) writes a
   structured log line; there is no UI or audit-log-viewer surface showing it. Confirmed by
   reading container logs directly, the same way `docs/audit-log.md`'s own tooling is read today.

5. **`workstation` tier has no model of its own.** `models_catalog.py` notes this: no
   Apache-2.0 GGUF quant of the PRD's named `workstation` model has been found by a verified
   uploader, so `workstation` falls back to the `accelerated` row's 9B. Not this ticket's gap to
   close; noted so a `workstation`-tier reading during this test is not mistaken for one.
