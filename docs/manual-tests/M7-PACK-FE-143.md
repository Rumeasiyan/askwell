# Manual test — M7-PACK-FE-143, a supervision surface: start, stop, repair, and what is wrong

**Ticket:** `M7-PACK-FE-143` — a small native window showing the container stack and the native
inference process, their state and last failure reason, with start/stop/restart per half and
the log-file location, reachable from a native menu item and from the running application's
"assistant unavailable" banner, and working while the API is down.
**Version under test:** `0.7.14`
**Time:** about 25 minutes.
**Who can run it:** a machine with the Rust toolchain, the system webview libraries
(`webkit2gtk4.1-devel`/`libwebkit2gtk-4.1-dev`, `gtk3-devel`, `atk-devel`, `cairo-gobject-devel`
on Linux, or their Windows/macOS equivalents) **and root/administrator access to install them**,
and Podman. **Neither is true of the session that wrote this document** — the same gap
`M7-TAURI-DEPLOY-183`'s and `M7-TAURI-FE-182`'s manual tests hit and filed as issue #497, still
open. `cargo build`/`cargo check` fail on `gdk-pixbuf-sys`'s `pkg-config` step before reaching
any code this ticket adds, and there is no `sudo` available to close it. This document is
therefore written from the code and from a throwaway scratch crate that exercised
`web/src-tauri/src/supervisor.rs`'s new pure logic (`stack_status_now`, `inference_status_now`,
`log_location`, `resolve_data_dir` — 9 unit tests, all passing, no Tauri dependency, same
approach as `M7-TAURI-DEPLOY-183`'s own manual test) rather than from an actual run. `tsc`,
`eslint` and `next build` **did** run for the frontend half (`scripts/dev.sh web-check` /
`web-build`), since those need no system webview. Every step below involving the actual shell
window is unverified until a session with those libraries runs it.

**What is being checked.** `web/src-tauri/src/supervisor.rs`'s new `Handle::status`/
`Handle::control`, the manual-stop tracking that keeps a deliberately stopped half out of the
auto-restart loop, `main.rs`'s native "Askwell" → "Supervision…" menu item and the
`open_supervision_window`/`supervision_status`/`supervision_control`/`supervision_log_location`
commands, `shell-assets/supervision.html`, `shell-assets/starting.html`'s new repair button, and
`web/components/shell/status-banner.tsx`'s "Open Supervision…" button.

**Where this stops on purpose.** No repair of a corrupted container volume or of the container
runtime itself (this ticket's own stated Out of Scope). No restart history from before the shell
was opened when a component was already running as an OS-level service
(`M7-PACK-DEPLOY-142`) — the surface reports what the shell's own loop currently believes, not a
full history (`docs/decisions.md`, 2026-09-23). No log file written yet on Linux or Windows for
the stack/inference services — the log-location action says so rather than pointing at an empty
folder (issue #609, filed this session).

---

## Before you start

```
cd ~/external/quantum-plus/askwell
scripts/dev.sh tauri build
```

**You should see:** a clean `cargo build --release`, ending with an `askwell-shell` binary under
`web/src-tauri/target/release/`.

Make sure nothing is already running:

```
podman compose down
pkill -f askwell-inference || true
```

---

## Part A — reachable from the desktop entry point, API down

### 1. Launch the shell with nothing running

```
web/src-tauri/target/release/askwell-shell
```

**You should see:** the "Starting Askwell" page. Before the API answers, open the native
application menu ("Askwell") and click "Supervision…".

**You should see:** a second, small window opens immediately — "Askwell — Supervision" — showing
both halves as `Starting`, independent of whether the main window has handed off yet.

### 2. Watch it recover on its own

**You should see:** as the stack and inference process come up, both rows move to `Running` and
the banner at the top reads "Both are running. Nothing needs your attention." No button invites
action once healthy — Start is disabled on both halves, Stop remains available.

---

## Part B — manual stop stays stopped

### 3. Stop the inference process from the surface

Click **Stop** under "Inference process".

**You should see:** the row moves to `Stopped` within about 1.5s (the poll interval), Start
becomes enabled, Stop becomes disabled. Ask a question in the main window — the assistant should
report unavailable, and it should **stay** stopped rather than the loop bringing it back up on
its own (this is the point of `inference_manual_stopped` — distinct from a capped failure).

### 4. Start it again

Click **Start**.

**You should see:** the row returns to `Starting` then `Running`, and the assistant answers
again in the main window without a restart of the shell itself.

---

## Part C — a real failure names its reason

### 5. Force a stack failure

```
mv compose.yaml compose.yaml.bak   # or otherwise make `podman compose up -d` fail
```

Click **Restart** under "Container stack".

**You should see:** after the five-step backoff exhausts (up to ~53s), the row moves to `Failed`
with the actual error text shown beneath it — not a generic message. Restore the file
(`mv compose.yaml.bak compose.yaml`) and click **Restart** again to confirm recovery.

### 6. Container runtime not running

```
podman machine stop   # or otherwise make the container runtime unreachable
```

Click **Restart** under "Container stack".

**You should see:** the state reads `Container runtime not running` (distinct from `Failed`),
with the reason naming what to start — matching this ticket's own edge case that Askwell cannot
start Podman itself.

---

## Part D — reachable from the running application, and the log location

### 7. From the real app's own banner

With the API reachable but inference stopped (repeat step 3, then close the supervision window),
load the main application. **You should see:** the "assistant unavailable" banner, with an "Open
Supervision…" button beneath it. Click it.

**You should see:** the same supervision window opens (or focuses, if already open) — confirming
the second entry point named in this ticket's own scope line.

### 8. Plain browser, no shell

Open `http://127.0.0.1:8000/` directly in an ordinary browser tab (not through the shell).

**You should see:** the same banner, with **no** "Open Supervision…" button — there is nothing
for a plain tab to open, and `window.__TAURI_INTERNALS__` is absent there.

### 9. The log location

In the supervision window, read the "Logs, for a bug report" section.

**You should see (Linux):** `$XDG_DATA_HOME/askwell/logs` (or `~/.local/share/askwell/logs`)
with a note that output isn't written there yet and the `journalctl --user -u askwell-stack
-u askwell-inference` equivalent. **On macOS:** the same folder under `~/Library/Application
Support/Askwell/logs`, with a note that `askwell-stack.log`/`askwell-inference.log` are written
there — open the folder and confirm those two files exist and contain recent output.
