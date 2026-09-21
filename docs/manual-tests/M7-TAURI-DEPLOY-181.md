# Manual test — M7-TAURI-DEPLOY-181, the desktop shell window

**Ticket:** `M7-TAURI-DEPLOY-181` — a Tauri window hosting the existing web app, remembering size/position, refusing to navigate anywhere but the local API, showing Askwell's own starting state before the API answers, and focusing rather than duplicating on a second launch.
**Version under test:** `0.6.3`
**Time:** about 30 minutes.
**Who can run it:** a machine with the Rust toolchain (`cargo`, confirmed on this host: `rustc 1.97.1`) and Podman. `bundle.active` is `false` in `web/src-tauri/tauri.conf.json` and there is no code-signing yet (`M7-TAURI-DEPLOY-184`), so there is no installed `.app`/`.exe` to open from an applications menu — this walkthrough opens the built binary directly, which is the closest a pre-signing build gets to that scenario, and says so at each step where it differs.

**What is being checked.** `web/src-tauri/src/main.rs`: `is_allowed_navigation` (only the bundled `starting.html` asset origin and the local API's own origin, by full `Origin` including port, may load), `starting_page_url` + `web/src-tauri/shell-assets/starting.html` (offline starting page that polls `{api}/health` and hands off once it answers), `tauri_plugin_window_state` (size/position persistence), `tauri_plugin_single_instance` (second launch focuses the first window), `on_new_window` returning `Deny` (no popup window for `window.open()`/`target="_blank"`), and `log_event`/`spawn_api_version_watcher` (shell start/stop and API-connected lines on stdout, each carrying `shell_version` and, once known, `api_version`). Also `web/components/shell/shell.tsx`'s `RailDrawer`, mounted at `#askwell-chrome-start` in the app's own header — the narrow-window menu control from `M0-SHELL-FE-017a` that this ticket's chrome bar hosts.

**Where this stops on purpose.** No native file dialogs (`M7-TAURI-FE-182` — the browser-provided file picker is still what nominating a root or relocating a file uses). No process supervision — the API/containers/inference are started by hand exactly as in every other manual test, the shell does not start them (`M7-TAURI-DEPLOY-183`). No signing — every platform will show an unsigned-binary warning (`M7-TAURI-DEPLOY-184`); accept it, that warning is not a defect this ticket introduces.

---

## Before you start

```
cd ~/external/quantum-plus/askwell
```

If you have never run Askwell before:

```
cp -n .env.example .env
```

Open `.env`, find `POSTGRES_APP_PASSWORD`, and put any word after the `=` if it is blank.

Build the shell binary once, on the host (not in a container — Tauri links against the system's own WebKitGTK/AppKit/WebView2, which a container cannot reach):

```
scripts/dev.sh tauri build
```

**You should see:** a `cargo build --release` run finish with no error, ending with an `askwell-shell` binary under `web/src-tauri/target/release/`.

Leave the API and containers **stopped** for now — the first part of this walkthrough deliberately opens the shell before anything is answering.

---

## Part A — cold start before the API is up

### 1. Launch the shell with nothing else running

```
web/src-tauri/target/release/askwell-shell
```

(On the platform's own build, this is the step a real user does by double-clicking the app icon in their applications folder or dock — there is no terminal, no address to remember. This walkthrough runs the equivalent unsigned binary directly because no installed bundle exists yet.)

**You should see:** a window titled **Askwell** open, sized 1280×800, centred on the screen, with no address bar, no URL bar, no browser chrome of any kind — just the window and its content. Inside it: the starting page — a short dark rule with a dot, the headline "Starting Askwell", and "Waiting for the local application to come up."

### 2. Leave it running for about 3 seconds without doing anything

**You should see:** after a few polling attempts, the headline change to "Still starting Askwell" with the detail "This is taking longer than usual. It will open as soon as the application answers." — Askwell's own message, not the webview's connection-refused/"can't reach this page" error.

### 3. Bring the stack up, in a second terminal, without closing the window

```
podman compose up -d
scripts/dev.sh db upgrade head
```

**You should see:** the containers report started and the migration finish with no error, as in every other walkthrough.

### 4. Watch the shell window, without touching it

**You should see:** within a few seconds, the window replaces the starting page with the real Askwell interface on its own — no reload needed, no interaction required. It lands on the same first-run/Ask screen a browser would show at `http://127.0.0.1:8000/`.

### 5. Check the shell's own stdout, back in the terminal you launched it from

**You should see:** JSON lines including one with `"event":"shell_start"` and `"shell_version":"0.6.3"` logged at launch, and one with `"event":"shell_api_connected"` carrying the same `shell_version` plus an `"api_version"` field matching `0.6.3` — logged once the window recovered in step 4.

---

## Part B — the window is the whole application

### 6. Use Askwell normally inside the window

Add a source (drag a file onto the window, or use **Add a source**), return to **Ask**, and ask a question about it, exactly as in a browser.

**You should see:** every step behaves identically to a browser session — the composer, the turn, the citations in the right-hand margin, all present and working. Nothing about being inside the shell changes any screen's content.

### 7. Narrow the window well past a typical laptop width

Resize the window down to roughly 700px wide.

**You should see:** the left rail collapses per the existing breakpoint behaviour, and a menu control (`RailDrawer`) appears in the app's own header bar, to the left of the "Askwell" wordmark and the status dot — not a browser menu, this window's own chrome. Click it and confirm it opens the same source/navigation drawer the rail normally shows.

### 8. Move the window to a different position on screen and resize it to something distinctive, then quit

Quit the application (window close button, or the platform's usual quit shortcut).

**You should see:** in the terminal, a line with `"event":"shell_stop"` appear.

### 9. Relaunch the same binary

```
web/src-tauri/target/release/askwell-shell
```

**You should see:** the window reopens at the same position and size you left it at in step 8 — not centred, not the 1280×800 default.

---

## Part C — single instance

### 10. With the shell from step 9 still open, launch it again from a second terminal

```
web/src-tauri/target/release/askwell-shell
```

**You should see:** no second window appears. The second process exits immediately, and the *existing* window comes to the foreground and gains focus (un-minimise it first if you minimised it, to see the effect clearly).

---

## Part D — the webview cannot navigate away

### 11. Add a document containing an external link (a PDF or text file with a plain `https://` URL in it, e.g. `https://example.com`), ask a question whose answer quotes or cites that link, and click the link in the answer

**You should see:** nothing happens — no navigation inside the window, no new window, no external browser opens either (the platform's own webview might otherwise treat this as `target="_blank"`; it does not here). The window keeps showing whatever it was showing before the click.

### 12. Run the shell's own navigation-guard unit tests

```
scripts/dev.sh tauri test
```

**You should see:** `allows_same_origin`, `rejects_same_host_different_port`, `rejects_external_host`, and `allows_tauri_asset_origin` all pass — the same-origin check is keyed on full origin (scheme + host + port), so another local process on a different port cannot pass as the API either.

---

## Part E — missing/too-old webview (best-effort — skip if you cannot arrange this)

### 13. If you have access to a machine or container image missing WebKitGTK (Linux) or an equivalent way to make window creation fail

Launch `askwell-shell` there.

**You should see:** no blank window and no raw panic — a dialog titled "Askwell can't start" naming what to install (`webkit2gtk4.1` via `dnf`, or `libwebkit2gtk-4.1-0` via `apt`, per `report_webview_unavailable` in `main.rs`), and the process exits with a non-zero status. If you cannot arrange this environment, skip this part — it is reading the code path (`report_webview_unavailable`), not a defect to chase down.

---

## Known gaps

- **No installed application bundle.** `tauri.conf.json`'s `bundle.active` is `false`; there is no `.app`, `.exe`/MSI, or `.deb`/AppImage yet, so this walkthrough launches the built binary directly rather than from an applications menu or dock. That gap is real (packaging is `M7-PACK-DEPLOY-139` through `141`) and is not this ticket's scope.
- **No native file dialogs.** Adding a source or relocating a file still uses the browser-provided picker inside the webview — `capabilities/default.json` grants the webview no Tauri command at all, by design, so no native dialog could appear yet even if requested. `M7-TAURI-FE-182`.
- **No process supervision.** The shell does not start or stop the containers or the inference process — Part A above starts them by hand, exactly as in a browser-only walkthrough. `M7-TAURI-DEPLOY-183`.
- **Unsigned binary.** Expect an OS-level "unidentified developer"/SmartScreen/unsigned-binary warning on every platform when launching the release build. `M7-TAURI-DEPLOY-184`.
- **Launch counter has no display surface.** `record_launch` writes a count to the app-data directory but nothing in the interface shows it yet (tracked as issue #482 per the code comment in `main.rs`) — this is expected, not a defect to report.
- **Monitor-loss edge case (window saved on a display that is later disconnected) was not exercised end-to-end** in writing this document — `tauri_plugin_window_state` is documented to fall back to a sane default when the saved position no longer resolves to an existing monitor, but step 9's re-launch in this walkthrough was on the same display throughout. Worth a deliberate pass with an external monitor before this ticket is considered fully verified.
