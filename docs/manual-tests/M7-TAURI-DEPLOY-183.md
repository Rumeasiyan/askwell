# Manual test — M7-TAURI-DEPLOY-183, the shell supervises the stack and the inference process

**Ticket:** `M7-TAURI-DEPLOY-183` — the shell starts the container stack and the native
`askwell-inference` process on launch, watches both with a capped restart backoff, stops both
cleanly on quit, and reports the two shell-level unavailability causes this adds (the container
runtime missing/not running, and the stack failing to come up) distinctly on the starting page.
**Version under test:** `0.7.12`
**Time:** about 30 minutes.
**Who can run it:** a machine with the Rust toolchain, the system webview libraries
(`webkit2gtk4.1-devel`/`libwebkit2gtk-4.1-dev`, `gtk3-devel`, `atk-devel`, `cairo-gobject-devel`
on Linux, or their Windows/macOS equivalents) **and root/administrator access to install them**,
and Podman. **Neither is true of the session that wrote this document** — the same gap
`M7-TAURI-FE-182` hit and filed as issue #497, still open. `cargo build`/`cargo check` fail on
`gdk-pixbuf-sys`'s `pkg-config` step before reaching any code this ticket adds, and there is no
`sudo` available to close it. This document is therefore written from the code and from a
throwaway scratch crate that exercised `web/src-tauri/src/supervisor.rs`'s pure logic (9 unit
tests, all passing, no Tauri dependency — see `docs/decisions.md`, 2026-09-23) rather than from
an actual run. Every step below is unverified until a session with those libraries runs it.

**What is being checked.** `web/src-tauri/src/supervisor.rs`: `RestartPolicy` (a five-step
capped backoff, `1, 2, 5, 15, 30`s), `resolve_install_root` (reads `ASKWELL_INSTALL_PREFIX` and
its per-platform defaults, matching `deploy/*/lib.*`), the stack half (`podman compose up -d`/
`down`, reachability via `{api}/health`), the inference half (spawning
`<install-prefix>/askwell-inference`, adoption/readiness via its `state.json` heartbeat), and
`shell-assets/starting.html`'s new `window.askwellReportCause` handler.

**Where this stops on purpose.** No repair buttons (`M7-PACK-FE-143`). No start-with-session
registration (`M7-PACK-DEPLOY-142` — though `deploy/linux/install.sh`'s `register_session_start`
already writes the systemd unit that runs the same shell binary this ticket changes). No warning
before stopping if ingestion is in progress — issue #581 is still open; it needs a backend
aggregate this ticket does not build. No repair of a corrupted container volume.

---

## Before you start

```
cd ~/external/quantum-plus/askwell
scripts/dev.sh tauri build
```

**You should see:** a clean `cargo build --release`, ending with an `askwell-shell` binary under
`web/src-tauri/target/release/`. In a dev checkout (no installer run), the binary should find
`compose.yaml`/`askwell-inference` via the `ASKWELL_REPO_ROOT` fallback `build.rs` bakes in — no
`ASKWELL_INSTALL_PREFIX` needs to be set.

Make sure nothing is already running:

```
podman compose down
pkill -f askwell-inference || true
```

---

## Part A — cold start

### 1. Launch the shell with nothing running

```
web/src-tauri/target/release/askwell-shell
```

**You should see:** the window opens immediately showing "Starting Askwell" (the bundled
`starting.html`), not a blank window or the webview's own connection-refused page. Watch
`podman compose ps` in another terminal — containers should come up within a few seconds.

### 2. Wait for hand-off

**You should see:** once `{api}/health` answers, the window navigates to the real application
on its own. Ask a question to confirm the assistant answers — this also confirms the native
inference process came up (`ASKWELL_INFERENCE_SOCKET`'s `state.json` should show `"ready"`).

---

## Part B — supervised restart

### 3. Kill the inference process from outside

```
pkill -f askwell-inference
```

**You should see:** within a few seconds the shell respawns it (watch stdout for
`supervisor_inference_restart` then `supervisor_inference_ready`); a question asked shortly after
answers again once ready.

### 4. Kill a container

```
podman stop askwell_api_1   # or the real container name from `podman compose ps`
```

**You should see:** `supervisor_stack_restart` in the shell's stdout, `podman compose up -d` run
again, and the application recover without the window needing to be reloaded manually.

---

## Part C — the two new causes

### 5. Stop the container runtime entirely, then launch the shell

```
podman machine stop   # or however this platform's Podman is stopped
web/src-tauri/target/release/askwell-shell
```

**You should see:** the starting page names Podman specifically — "Podman isn't available" —
not a generic "still starting" message, and not the stack-down message from the next step.

### 6. Point `ASKWELL_INSTALL_PREFIX` at an empty directory and launch

```
mkdir -p /tmp/askwell-empty-prefix
ASKWELL_INSTALL_PREFIX=/tmp/askwell-empty-prefix web/src-tauri/target/release/askwell-shell
```

**You should see:** after five restart attempts (roughly 53 seconds of backoff: 1+2+5+15+30), the
starting page names the stack failure — "The container stack couldn't start" — with a reason
naming the missing `compose.yaml`, distinct from step 5's runtime message.

---

## Part D — clean shutdown, and not duplicating

### 7. With the shell open and answering, quit it (not force-kill)

**You should see:** `podman compose ps` shows nothing running, and no `askwell-inference` process
remains (`pgrep -f askwell-inference` finds nothing). Compare against `supervisor_stop` in the
shell's own stdout just before it exits.

### 8. Start the stack by hand first, then open the shell

```
podman compose up -d
web/src-tauri/target/release/askwell-shell
```

**You should see:** no duplicate containers, no second `podman compose up -d` failure — the
shell attaches to what is already running. Quitting still stops it (compose is authoritative
regardless of who started it).

### 9. Start the native inference process by hand, then open the shell

```
scripts/dev.sh inference &
web/src-tauri/target/release/askwell-shell
```

**You should see:** `supervisor_inference_adopted` in stdout, not a second `askwell-inference`
process (`pgrep -f askwell-inference` shows exactly one PID throughout). Quitting the shell in
this case is expected to leave that adopted process running — see `docs/decisions.md`'s
2026-09-23 entry for why (no PID to act on, and killing a process this shell never started risks
stopping one the user began deliberately).

---

## Part E — the shell's own unit tests

```
scripts/dev.sh tauri test
```

**You should see:** all `supervisor.rs` tests pass — `RestartPolicy`'s backoff walk and cap,
`resolve_install_root_from`'s override/fallback ordering, `looks_like_runtime_down`'s phrase
matching, `read_env_file`'s parsing, and `inference_heartbeat_fresh`/`inference_confirmed_ready`'s
staleness handling — alongside `M7-TAURI-FE-182`'s and `M7-TAURI-DEPLOY-181`'s existing tests.

---

## Known gaps

- **Not run end-to-end this session.** No system webview libraries and no `sudo` to install them
  (issue #497, still open) — every part above is an unverified walkthrough written from the code,
  not confirmed behaviour. The 9 pure-logic unit tests *were* run, in a throwaway scratch crate
  with no Tauri dependency (deleted after the run) — see `docs/decisions.md`, 2026-09-23.
- **Issue #581** (shutdown-while-ingesting warning) is unaddressed by this ticket and remains
  open — it needs a global ingestion-status aggregate the API does not expose yet.
- **No repair surface.** A capped failure currently requires quitting and relaunching the shell;
  `M7-PACK-FE-143` is where a restart button belongs.
