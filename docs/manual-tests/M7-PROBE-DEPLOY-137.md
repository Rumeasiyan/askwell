# Manual test — M7-PROBE-DEPLOY-137, host-side hardware probe and profile selection

**Ticket:** `M7-PROBE-DEPLOY-137` — the probe runs on the host, reports real machine
values, selects one of four profiles, and records the selection with its evidence.
**Version under test:** `0.6.0`
**Time:** about 15 minutes.
**Who can run it:** anyone who can paste a line into a terminal — this ticket ships no
screen. `M7-PROBE-FE-138` (a separate ticket, out of scope here) is what puts any of
this in front of a user visually; today the only surfaces are a terminal command and
two JSON endpoints.

**What is being checked.** `deploy/probe/askwell-probe` runs on the host (never in a
container), measures RAM, CPU, accelerator and free disk, selects `light` / `standard`
/ `accelerated` / `workstation` against the thresholds in `docs/architecture.md` §6,
and writes the result to a file. `askwell.probe` on the API side reads that file,
exposes it at `GET /probe`, and records the selection plus its evidence as a
tamper-evident decisions record the first time it sees a given `probed_at`. `POST
/probe/rerun` asks the host script (running with `--watch`) to probe again.

---

## Before you start

Bring the stack up so the API is reachable, and confirm nothing has probed yet:

```
podman compose up -d
scripts/dev.sh db upgrade head
curl -s localhost:8000/probe | python3 -m json.tool
```

**Expect:** `"recorded": false`, and `probe.reason` starting with "The hardware probe
has not run yet." followed by `scripts/dev.sh probe`. The rest of the body (`profile`,
`ram_gb`, etc.) comes from `askwell.hardware.probe()` — the cruder in-container
fallback that has shipped since M1 — not from the host script this ticket adds. That
fallback existing is expected, not a defect: it is what a screen has to show before
anyone has run the real probe at all.

---

## Part A — the probe runs on the host and reports real values

### 1. Run the probe

```
scripts/dev.sh probe
```

**Expect:** it prints a JSON object to the terminal and exits. Compare the values
against what you actually know about this machine:

- `ram_gb` — close to the machine's real installed RAM (check with `free -g` on Linux,
  "About This Mac" on a Mac, Task Manager on Windows), **not** a container's cgroup
  ceiling. If you have a `podman compose` container running with a memory limit, this
  number should be the host's total, not that limit — that is the whole point of the
  ticket.
- `ram_source` — `/proc/meminfo` on Linux, `sysctl hw.memsize` on a Mac,
  `GlobalMemoryStatusEx` on Windows.
- `cpu.cores` — matches `nproc` (Linux) or the machine's real core count.
- `accelerator` — if the machine has an NVIDIA GPU, `present: true`, `kind: "nvidia"`,
  and a `vram_gb` figure close to the card's real VRAM (cross-check with
  `nvidia-smi --query-gpu=memory.total --format=csv`). On a Mac with Apple silicon,
  `present: true`, `kind: "apple-silicon"`, `vram_gb` equal to `ram_gb` (unified
  memory — there is no separate figure). On a machine with no GPU Askwell recognises,
  `{"present": false, "kind": null, "vram_gb": null, "source": "not detected"}`.
- `disk_free_gb` — close to `df -h ~` on Linux/Mac for the home directory (the probe's
  default disk path).
- `platform` — `Linux`, `Darwin`, or `Windows`, matching this machine.

### 2. Confirm the selected profile matches the thresholds

Using the `ram_gb` and `accelerator` values from step 1 and the table in
`docs/architecture.md` §6:

- `ram_gb < 8` → `light`
- `8 ≤ ram_gb < 16` → `light` still (below the standard floor)
- `ram_gb ≥ 16`, no usable accelerator → `standard`
- `ram_gb ≥ 16`, accelerator present with ≥ 8 GB VRAM (or VRAM unmeasured) →
  `accelerated`
- `ram_gb ≥ 32`, accelerator present with ≥ 16 GB VRAM → `workstation`

**Expect:** the `profile` field in step 1's output matches what this arithmetic gives
for your machine's real numbers, and `reason` states the figures it used in plain
language, e.g. "16.0 GB RAM, no usable accelerator."

### 3. Confirm the result file exists where the API expects it

```
cat .run/probe.json
```

**Expect:** the same JSON `scripts/dev.sh probe` printed, byte-identical (the write is
atomic — there is no partial file left behind; confirm with `ls .run/*.partial` finding
nothing).

### 4. Confirm the probe refuses to run inside a container

```
podman compose exec api python3 /dev/stdin <<'EOF'
import sys
sys.path.insert(0, "/app")
EOF
scripts/dev.sh run "python3 deploy/probe/askwell-probe" 2>&1 || true
```

If `scripts/dev.sh run` does not mount `deploy/` into the image, instead confirm this
by reading `deploy/probe/askwell-probe`'s `in_container()` and `main()`: it checks
`/.dockerenv`, `/run/.containerenv`, and `/proc/1/cgroup` for `docker`/`containerd`/
`kubepods`/`libpod`, and refuses with a stderr message naming
`scripts/dev.sh probe` before writing anything if any of those match. This is exercised
directly in `api/tests/test_probe_host.py::test_main_refuses_and_writes_nothing_inside_a_container`
— run it to confirm without needing a container mount:

```
scripts/dev.sh test api/tests/test_probe_host.py -k refuses
```

**Expect:** all matched tests pass.

---

## Part B — the API reads the result and records it

### 5. Fetch the probe state now that a real probe has run

```
curl -s localhost:8000/probe | python3 -m json.tool
```

**Expect:** `"recorded": true`, and `probe` matching step 1's values exactly (same
`ram_gb`, `profile`, `accelerator`, `disk_free_gb`, `platform`). `probe.stale` is
`false` — you just probed.

### 6. Confirm the selection was recorded as evidence, not just as a setting

```
scripts/dev.sh psql -c "SELECT kind, payload FROM audit_decisions WHERE kind = 'profile_probed' ORDER BY occurred_at DESC LIMIT 1;"
```

**Expect:** one row. `payload` is JSON containing `profile` matching what you saw in
step 1, `ram_mb` (RAM in fixed-unit megabytes, not the float `ram_gb` — floats are
never stored in an audit payload), and the same `accelerator` fields with `vram_mb`
instead of `vram_gb`. Confirm the chain is intact:

```
podman compose exec api askwell-verify
```

**Expect:** the decisions store reports intact, no tampering found.

### 7. Confirm the setting itself was written

```
scripts/dev.sh psql -c "SELECT value FROM settings WHERE key = 'hardware.profile';"
```

**Expect:** the same profile name as step 1 and step 5.

---

## Part C — re-run on demand

### 8. Start the probe in watch mode

```
scripts/dev.sh probe --watch
```

**Expect:** it prints the same JSON as a one-shot run, then a line like "askwell-probe:
watching for rerun requests at .run/probe-rerun-request", and stays running. Leave it
running for the next step.

### 9. Ask for a re-run from the API, the way a settings screen would

In a second terminal:

```
curl -s -X POST localhost:8000/probe/rerun | python3 -m json.tool
```

**Expect:** in the first terminal, within about a second, a line "askwell-probe:
re-probed — `<profile>`". The `curl` response is the state *before* that re-probe
lands, since it returns immediately — that is expected (the endpoint's own docstring
says the settings screen re-polls `GET /probe` afterwards); confirm the fresh result
landed with a second poll a moment later:

```
sleep 2 && curl -s localhost:8000/probe | python3 -m json.tool
```

**Expect:** `probe.probed_at` is newer than the value from step 5.

### 10. Confirm a re-run confirming the same profile is still recorded

```
scripts/dev.sh psql -c "SELECT count(*) FROM audit_decisions WHERE kind = 'profile_probed';"
```

**Expect:** the count increased by one from step 6's single row — every probe run is a
decisions record, not only ones that change the profile.

Stop the watcher with `Ctrl-C` in the first terminal.

**Expect:** it prints "askwell-probe: stopped" and exits cleanly (no traceback).

---

## Part D — detection failure falls back to standard, stated

This is the ticket's own edge case: memory could not be measured at all.
`docs/architecture.md` §6 requires falling back to `standard` with a stated reason,
distinct from a genuine reading under the `light` floor (which stays `light`). This is
exercised directly rather than by breaking your own machine's memory reporting:

```
scripts/dev.sh test api/tests/test_probe_host.py -k detection_failure
```

**Expect:** the test passes, asserting `profile == "standard"`, `detection_failed is
True`, and the reason contains "could not be measured".

### 11. Confirm an unrecognised accelerator is treated as absent, not guessed at

```
scripts/dev.sh test api/tests/test_probe_host.py -k unrecognised_accelerator
```

**Expect:** passes — an accelerator this probe cannot name comes back
`{"present": false, "kind": null, "vram_gb": null, "source": "not detected"}` rather
than a guess.

### 12. Confirm the full threshold table

```
scripts/dev.sh test api/tests/test_probe_host.py -k profile_thresholds
scripts/dev.sh test api/tests/test_probe_records.py
```

**Expect:** all pass — this is the automated coverage for every RAM/VRAM boundary in
`docs/architecture.md` §6, and for the recording behaviour (evidence shape, rerun
recording, sync-only-on-newer-`probed_at`) that steps 5–10 above spot-checked live.

---

## What was checked against the ticket's acceptance criteria

- The probe runs on the host, reports real machine values (not a container's view) —
  Part A, steps 1–4.
- A profile is selected according to the documented thresholds — Part A, step 2; Part
  D, step 12.
- Failed detection falls back to `standard` with a stated reason — Part D, step 10.
- An unrecognised accelerator is treated as absent, stated, with the user free to
  override the profile later (`M7-PROBE-FE-138`, not yet built) — Part D, step 11.
- A VM reporting the host's memory dishonestly: the value is used and the source is
  stated — covered by
  `api/tests/test_probe_host.py::test_a_vm_reported_value_is_used_and_the_source_is_stated`,
  not independently reproducible without an actual VM; read rather than re-run live.
- The selection and its evidence are recorded, hash-chained and verifiable — Part B,
  steps 6–7; Part C, step 10.
- Re-run on demand from settings — the `/probe/rerun` half of it, Part C. The settings
  screen itself does not exist yet (see Known gaps).
- The probe never runs inside a container — Part A, step 4.

## Known gaps

Do not report these as defects — they are out of scope for this ticket:

- **No settings screen exists yet.** `docs/ux/settings.md` §2's "current profile" and
  "re-run" card, and `docs/ux/first-run.md` §2 step 2's "Check the machine" screen, are
  both `M7-PROBE-FE-138` — a separate ticket. This ticket is the API and host script
  only; every step above uses a terminal and `curl` because that is the only surface
  that exists.
- **No warn-and-continue interface for an under-floor or unrecognised-accelerator
  machine.** The host script states the fact in `reason`; presenting it and letting
  the user override the profile is `M7-PROBE-FE-138`.
- **Disk-free re-check before the model download step does not exist yet** — that is
  the first-run model-download sequence (`M0-MODEL-DEPLOY-018` and later), not this
  ticket. `disk_free_gb` here is a point-in-time reading only.
- **Windows and Mac paths in this document are described, not run** — this walkthrough
  was executed on Linux. `detect_memory`'s `Darwin` and `Windows` branches and
  `detect_accelerator`'s Apple-silicon branch are covered by
  `api/tests/test_probe_host.py` (`test_apple_silicon_is_reported_as_unified_memory`),
  not by a live run on that hardware in this pass.
