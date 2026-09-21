# Manual test — M7-PROBE-FE-138, warn and continue below the floor, and when the probe fails

**Ticket:** `M7-PROBE-FE-138` — a machine below the hardware floor is warned with concrete
expectations and allowed to continue; a failed probe states the `standard` fallback and
continues; the profile can be changed afterwards in Settings, with the consequence stated.
Nothing refuses to run on hardware grounds.
**Version under test:** `0.6.1`
**Time:** about 20 minutes.
**Who can run it:** anyone who can open a browser and edit a text file — no account, no
special hardware needed, because the below-floor and probe-failure states are fabricated
by editing the same JSON file the real host probe writes to.

**What is being checked.** `web/components/welcome/welcome-screen.tsx`'s `StepMachineCheck`
(first-run step 2) and `web/components/settings/hardware-profile.tsx` (Settings), both fed
by `GET /setup` and `GET /probe` (`api/src/askwell/setup.py`, `api/src/askwell/probe.py`).
Below the `light` floor, both surfaces warn and let the user continue. When the host probe
has never run and the in-container fallback fails to read memory, both surfaces name it as a
probe failure, distinct from a below-floor reading, and state the `standard` fallback. In
Settings, the profile can be overridden to any of the four tiers, with the consequence stated
before the change and recorded as a hash-chained decision afterwards.

This machine's real probe has already run and lands well above the floor (check
`.run/probe.json` — `accelerated`, ~31 GB RAM), so Parts B and C below fabricate a
below-floor and a failed reading by editing that same file, the seam `askwell.probe` reads.
This is not a shortcut around the ticket: `read_probe_result` cannot tell a genuine host
reading from a hand-edited one, which is exactly why it is a plain JSON file rather than
something only the host script can produce.

---

## Before you start

Bring the stack up and make sure the interface being served is the one under test — the API
serves `web/out`, built ahead of time, not live from source:

```
podman compose up -d
scripts/dev.sh db upgrade head
scripts/dev.sh web-build
podman compose restart api
```

Confirm the real probe result already on this machine, so you know what to restore afterward:

```
cat .run/probe.json
```

**Expect:** a JSON object with a real `profile` (this machine: `accelerated`) and
`probed_at` some time in the past. Keep this output around — Part D restores it.

---

## Part A — cold start on this machine's real, above-floor hardware

### 1. Open the welcome screen fresh

In a browser, go to `http://localhost:8000/welcome`.

**Expect:** "Welcome to Askwell", the four-step list (What this is / Check the machine / Get
the model / Add something and ask), and step 1's text: "Askwell reads your files and answers
questions about them, on this machine. Nothing is uploaded."

### 2. Continue to the machine check

Click **Get started**.

**Expect:** step 2, "Check the machine", shows a plain sentence naming this machine's real
RAM and accelerator (e.g. "31.2 GB RAM with an accelerator, 8.0 GB VRAM.") with no warning
text beneath it — this machine is above every floor, so neither the below-floor nor the
probe-failure paragraph should appear. A **Continue** button is present and enabled.

Do not click **Continue** yet — leave the browser on this step; Parts B and C reload it after
editing the probe file.

---

## Part B — below the floor: warned, not refused

### 3. Fabricate a below-floor reading

```
python3 - <<'EOF'
import json, time
path = ".run/probe.json"
result = {
    "profile": "light",
    "reason": "4.0 GB is below the 8 GB floor. Askwell will run, but slowly.",
    "detection_failed": False,
    "below_floor": True,
    "ram_gb": 4.0,
    "ram_source": "/proc/meminfo",
    "cpu": {"processor": "x86_64", "machine": "x86_64", "cores": 2},
    "accelerator": {"present": False, "kind": None, "vram_gb": None, "source": "not detected"},
    "disk_free_gb": 50.0,
    "disk_path": "/home/user",
    "platform": "Linux",
    "probed_at": time.time(),
}
with open(path, "w", encoding="utf-8") as f:
    json.dump(result, f)
EOF
```

### 4. Reload the welcome screen at step 2

Reload `http://localhost:8000/welcome` in the browser, click **Get started** again to reach
step 2.

**Expect:** the same plain sentence now reads "4.0 GB is below the 8 GB floor. Askwell will
run, but slowly." beneath it, a second paragraph in a distinct (warning) colour: "This is
below what Askwell is built for. It will still run — nothing is refused — but expect it to be
slow. If the assistant cannot load at all on this machine, document indexing and search will
still work; you can change the profile in Settings any time." **Continue is still enabled** —
confirm by clicking it and reaching step 3 (the model download step) without any blocking
dialog or refusal.

### 5. Confirm Settings shows the same below-floor state

Navigate to Settings from the app (the rail/nav present in the running app — do not type the
URL directly; use whatever link the shell exposes to get there, confirming the path is not
dead). Under **Hardware profile**:

**Expect:** "Current profile: **Light**", the reason sentence matching step 4's, and beneath
it, in the warning colour: "Below what Askwell is built for. It runs, but slowly, and voice
will likely not work." No probe-failure sentence is shown (that is Part C, not this state).

---

## Part C — the probe fails to detect memory at all

### 6. Fabricate a detection failure

```
python3 - <<'EOF'
import json, time
path = ".run/probe.json"
result = {
    "profile": "standard",
    "reason": "Memory could not be measured on this machine. Defaulting to the standard profile.",
    "detection_failed": True,
    "below_floor": False,
    "ram_gb": None,
    "ram_source": "",
    "cpu": {},
    "accelerator": {"present": False, "kind": None, "vram_gb": None, "source": "not detected"},
    "disk_free_gb": 50.0,
    "disk_path": "/home/user",
    "platform": "Linux",
    "probed_at": time.time(),
}
with open(path, "w", encoding="utf-8") as f:
    json.dump(result, f)
EOF
```

### 7. Reload the welcome screen at step 2 again

**Expect:** the plain sentence now reads "Memory could not be measured on this machine.
Defaulting to the standard profile.", and beneath it, in the warning colour: "Askwell's
hardware probe could not measure this machine, so it is running on the standard profile as a
fallback. Nothing is refused — you can change the profile in Settings once Askwell is
running." This is visibly different wording from Part B's below-floor paragraph — confirm
they are not the same sentence reused. **Continue is still enabled**; click it and confirm
step 3 still loads.

### 8. Confirm Settings distinguishes the same failure from a below-floor reading

Back in Settings, under **Hardware profile**:

**Expect:** "Current profile: **Standard**", the same reason sentence as step 7, and beneath
it: "The probe could not measure this machine, so Askwell is running on the standard profile
as a fallback." — not the "Below what Askwell is built for" sentence from step 5.

---

## Part D — overriding the profile in Settings

Still on the fabricated probe-failure state from Part C.

### 9. State the consequence before changing anything

In the **Override the profile** control, change the dropdown to **Workstation** (a profile
this machine may or may not actually support — that is the point of the edge case).

**Expect:** before clicking anything else, the sentence next to the dropdown already reads:
"Override the profile. Askwell will run as workstation without checking whether this machine
can actually support it. If it cannot load a model at that level, the assistant will report
the failure clearly — document search and indexing keep working either way. Recorded in the
decisions log." — stated beside the control, not behind a confirm dialog.

### 10. Apply the override

Click **Change profile**.

**Expect:** "Current profile: **Workstation** (measured as Standard)" — the parenthetical
naming what was actually detected, distinct from what is now in effect — and a confirmation
line: "Profile changed to Workstation. Recorded in the decisions log."

### 11. Confirm the override is honoured everywhere, not just in Settings

Reload `http://localhost:8000/welcome`.

**Expect:** step 2's machine check now names the overridden profile's tier rather than
`standard` — the welcome screen and Settings never disagree about which profile is live.

### 12. Confirm the override was recorded as a tamper-evident decision

```
scripts/dev.sh psql -c "SELECT kind, payload FROM audit_decisions WHERE kind = 'profile_overridden' ORDER BY occurred_at DESC LIMIT 1;"
podman compose exec api askwell-verify
```

**Expect:** one row with `payload` containing `"detected": "standard"` and `"chosen":
"workstation"`; `askwell-verify` reports the decisions store intact.

### 13. Confirm an override to an unknown string is rejected, not silently accepted

```
curl -s -X POST localhost:8000/probe/override -H 'content-type: application/json' -d '{"tier":"turbo"}'
```

**Expect:** HTTP 400 with `{"error": "'turbo' is not a profile Askwell knows."}` — this is
the one case the ticket does still reject: a string that names no profile at all, never a
profile the machine cannot support.

---

## Part E — restore this machine's real state

### 14. Re-run the real probe and clear the override

```
scripts/dev.sh probe
```

**Expect:** prints a fresh JSON result close to the values captured in "Before you start".

### 15. Confirm the override no longer applies

```
curl -s localhost:8000/probe | python3 -m json.tool
```

**Expect:** `"overridden": false`, `"profile"` back to this machine's real tier
(`accelerated`) — a genuine re-probe overwrites a stale override, per the ticket's own
"Assumptions".

---

## What was checked against the ticket's acceptance criteria

- Below-floor hardware produces a warning naming what will be slow, and the user can
  continue — Part B, steps 3–5.
- A failed probe states the fallback and continues, distinguishable from the below-floor
  case — Part C, steps 6–8.
- The profile can be changed afterwards in Settings, with the consequence stated before the
  change — Part D, steps 9–10.
- The change is honoured on the welcome screen too, not just where it was made — Part D,
  step 11.
- Nothing refuses to run on hardware grounds — Parts B, C, D throughout: every **Continue**
  and **Change profile** button stayed enabled regardless of the fabricated reading.
- The warning and the override are decisions records — Part D, step 12 (`profile_overridden`);
  `profile_probed` is exercised in `M7-PROBE-DEPLOY-137`'s own manual test.
- Only an unrecognised tier string is refused, never a profile the machine cannot support —
  Part D, step 13.

## Known gaps

Do not report these as defects — they are out of scope for this ticket or not practical to
exercise live:

- **The below-floor and probe-failure states were fabricated by editing `.run/probe.json`,
  not produced by real under-powered hardware or a genuine measurement failure.** No
  environment variable or flag makes `deploy/probe/askwell-probe` misreport memory on
  request (confirmed by reading `detect_memory` and `select_profile` in
  `deploy/probe/askwell-probe`); editing the file it writes to is the documented seam and is
  what the ticket's own testing notes ("or constrain the probe's reported memory") point at.
- **The edge case "hardware so limited the smallest model cannot load" is not exercised
  here.** Forcing an actual model load failure means either a genuinely underpowered machine
  or corrupting a downloaded model file, neither of which this walkthrough attempts; the
  ticket's requirement is that the assistant reports such a failure clearly and that document
  indexing and search keep working regardless, which is a model-loading concern
  (`askwell.inference`), not this ticket's own code path.
- **No settings navigation link was hardcoded in this document** — the walkthrough assumes
  whatever link the app shell already exposes to Settings; if that link does not exist or is
  dead, that is itself a finding, not something this document can specify in advance since the
  shell's own navigation is out of this ticket's scope.
- **`scripts/dev.sh probe --watch` and `POST /probe/rerun`** (the "Re-run the probe" button in
  Settings) are `M7-PROBE-DEPLOY-137`'s own surface and are exercised there, not repeated here
  — this document uses the direct `scripts/dev.sh probe` one-shot instead, in Part E, since
  restoring real values does not need the watch/rerun round trip.
