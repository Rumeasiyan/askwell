# Manual test — M7-PACK-DEPLOY-142, the container stack and native inference run as their own platform services

**Ticket:** `M7-PACK-DEPLOY-142` — the container stack and the native `askwell-inference`
process each get registered as their own OS-native service (systemd `--user` on Linux, a
LaunchAgent on macOS, a Scheduled Task on Windows), independent of the desktop shell, so both
start with the session and survive the shell being closed. `M7-TAURI-DEPLOY-183`'s in-process
supervisor keeps running while the shell is open and now attaches to whatever these services
already have up, via the same `state.json` heartbeat it already reads.

**Version under test:** `0.7.13`
**Time:** logic and unit-syntax checks run in minutes on this Linux build host; a full
cold-start-through-the-desktop-shell walkthrough needs a machine with the desktop shell built
(see **Known gaps**).

**Where this stops on purpose.** This ticket only registers and supervises; it does not build
the desktop shell binary (`M7-TAURI-DEPLOY-181`/`-183`), the repair surface with buttons
(`M7-PACK-FE-143`), or an offline install bundle (`M7-OFFLINE-DEPLOY-144`). Corrupted-container-
volume recovery stays manual, per this ticket's own Testing Notes.

---

## Before you start

This build host has systemd, Podman, and a lingering user session (`loginctl show-user`
reports `Linger=yes`), but **no desktop-shell binary** — `web/src-tauri/target/release/
askwell-shell` does not exist here, the same webview-toolchain gap `M7-TAURI-FE-182`/
`M7-TAURI-DEPLOY-183` hit and filed as issue #497 (still open). Steps 1–6 below are the real,
non-technical cold-start path a user follows and are written to be run as-is once that binary
exists. Everything that does not need the shell binary — the two platform units themselves,
their syntax, and their restart-cap behaviour — **was run for real on this host** and is
reported as such under each step and in **Verified on this machine** below.

```
cd ~/external/quantum-plus/askwell
podman compose down 2>/dev/null || true
pkill -f askwell-inference 2>/dev/null || true
systemctl --user list-units 'askwell-*' --no-pager
```

**You should see:** nothing named `askwell-*` running yet (a clean machine, or one where a
previous manual test cleaned up after itself).

---

## Part A — cold start, as a user would do it

### 1. Run the installer

```
./deploy/linux/install.sh -y --data-dir /tmp/askwell-manualtest-data --prefix /tmp/askwell-manualtest-app
```

**You should see:** Podman detected, disk space checked, application files placed, and — new in
this ticket — a line reading *"Askwell's container stack and native inference process
registered to run with your session, independent of the app window (systemd --user)."*
immediately followed by *"Askwell registered to start with your session (systemd --user)."*
(the shell's own registration, unchanged from `M7-PACK-DEPLOY-139`). The installer then tries to
launch the shell binary and — on a machine without it built — reports the missing-artefact
refusal from `check_artefacts` instead of reaching this point; on a machine with a built shell,
its window opens.

### 2. Confirm both services exist and are enabled

```
systemctl --user status askwell-stack.service askwell-inference.service --no-pager
```

**You should see:** both units `loaded` and `enabled`, `askwell-stack.service` showing
`Active: active (running)` with a `podman compose ... up --abort-on-container-exit` process, and
`askwell-inference.service` showing `Active: active (running)` running
`/tmp/askwell-manualtest-app/askwell-inference`.

### 3. Confirm both halves came up

```
podman compose -f /tmp/askwell-manualtest-app/compose.yaml --env-file /tmp/askwell-manualtest-app/.env ps
cat /tmp/askwell-manualtest-data/askwell-inference/state.json   # or wherever ASKWELL_STATE_PATH points
```

**You should see:** every container from `compose.yaml` listed as running, and the inference
state file reporting `"ready"`.

### 4. Open Askwell from the applications menu

**You should see:** the desktop entry installed at step 1 opens the shell, which shows the
"Starting Askwell" page only briefly — both halves are already up from the platform services,
so the shell's own supervisor (`M7-TAURI-DEPLOY-183`) attaches rather than starting a second
copy — then hands off to the real application. Ask a question and see it answered with a
citation, confirming both halves are genuinely reachable, not just reported as running.

### 5. Close the shell window (not "stop Askwell")

**You should see:** the shell window closes, but `systemctl --user status askwell-stack.service
askwell-inference.service` still shows both `active` — closing the window is not the same as
stopping Askwell, and the stack is meant to survive it.

### 6. Reopen the shell

**You should see:** the window returns to the running application almost immediately, with no
re-indexing or lost conversation — the next launch finds the two services already up rather
than a half-state, which is this ticket's own "shell closed but session still running" edge
case.

---

## Part B — killing either half gets a supervised restart

### 7. Kill the native inference process from outside

```
pkill -f askwell-inference
journalctl --user -u askwell-inference.service --no-pager | tail -10
```

**You should see:** the unit restart within `RestartSec=5`, the log showing the process exit
and a fresh start, and — asking a question again a few seconds later — the assistant answers
once `state.json` reports `"ready"` again.

### 8. Kill a container from outside

```
podman stop askwell_api_1   # the real container name from `podman compose ps`
journalctl --user -u askwell-stack.service --no-pager | tail -10
```

**You should see:** `askwell-stack.service` exit non-zero the moment the container dies
(`--abort-on-container-exit` is what turns "a container was killed" into "the foreground compose
process exits"), then restart — `podman compose ... ps` shows every container running again
within a few seconds, with no manual intervention.

---

## Part C — stopping Askwell leaves nothing running

### 9. Stop Askwell

```
systemctl --user stop askwell.service askwell-stack.service askwell-inference.service
podman compose -f /tmp/askwell-manualtest-app/compose.yaml --env-file /tmp/askwell-manualtest-app/.env ps
pgrep -f askwell-inference
```

**You should see:** the compose `ps` table empty and `pgrep` finding nothing — stopping the
stack unit runs its own `ExecStop` (`podman compose ... down`), so no container or process is
left behind.

---

## Part D — starting Askwell twice attaches, it does not duplicate

### 10. Start the stack service twice in a row

```
systemctl --user start askwell-stack.service
systemctl --user start askwell-stack.service
podman compose -f /tmp/askwell-manualtest-app/compose.yaml --env-file /tmp/askwell-manualtest-app/.env ps
```

**You should see:** one set of containers, not two — `systemctl start` on an already-running
unit is a no-op at the systemd level, so a second click of "start Askwell" (or a second login on
a machine already up) never races a second `podman compose up`.

---

## Part E — sleep and wake

### 11. Sleep and wake the machine while Askwell is running

**You should see:** after wake, `podman compose ps` and `systemctl --user status
askwell-inference.service` both show everything still running (or, if the containers were
paused/killed by the sleep, restarted automatically per Part B) — and a question asked a few
seconds after wake gets an answer without any manual restart.

---

## Part F — a restart loop hits its cap and reports failed

### 12. Point the stack unit at a broken install and watch it give up

```
mkdir -p /tmp/askwell-manualtest-broken
cat > ~/.config/systemd/user/askwell-manualtest-broken.service <<'EOF'
[Unit]
Description=askwell manual-test broken stack (safe to delete)
StartLimitIntervalSec=10
StartLimitBurst=3

[Service]
Type=simple
ExecStart=/bin/false
Restart=on-failure
RestartSec=1
EOF
systemctl --user daemon-reload
systemctl --user start askwell-manualtest-broken.service
sleep 8
systemctl --user status askwell-manualtest-broken.service --no-pager
```

**You should see** — and this is what was actually run on this build host, standing in for the
real stack unit with a broken `compose.yaml` (this build host has no `pwsh`/Mac to exercise the
platform-specific units directly, but the underlying systemd behaviour is identical regardless
of which command is inside `ExecStart`):

```
Active: failed (Result: exit-code)
...
Scheduled restart job, restart counter is at 3.
Start request repeated too quickly.
Failed with result 'exit-code'.
```

Three attempts (`StartLimitBurst=3`), then systemd stops trying and the unit settles into
`failed` rather than restarting forever — the same shape the real `askwell-stack.service` and
`askwell-inference.service` use with `StartLimitBurst=5`/`StartLimitIntervalSec=300`. The last
failure reason (`Result: exit-code`, `ExecStart=/bin/false`) stays visible in `systemctl status`
after the unit gives up, matching this ticket's "backoff caps and the state becomes failed with
the last reason" edge case.

Clean up the scratch unit:

```
systemctl --user stop askwell-manualtest-broken.service
rm -f ~/.config/systemd/user/askwell-manualtest-broken.service
systemctl --user daemon-reload
systemctl --user reset-failed askwell-manualtest-broken.service 2>/dev/null || true
```

---

## Part G — uninstall leaves nothing behind

### 13. Uninstall

```
./deploy/linux/uninstall.sh -y --data-dir /tmp/askwell-manualtest-data
systemctl --user status askwell.service askwell-stack.service askwell-inference.service 2>&1
```

**You should see:** all three `systemctl status` calls report the unit is not found (or
inactive/dead with no unit file), the stack's own `ExecStop` having already run `podman compose
down` before the unit files were disabled and removed, and `podman compose ps` (against the
now-deleted compose file) has nothing to show.

---

## Verified on this machine (no shell binary available — see Known gaps)

- `bash deploy/linux/install.test.sh` — **46 passed, 0 failed**, including the six tests added
  for this ticket: `systemd unit wants the platform-level stack and inference units`, `stack
  unit runs compose in the foreground so systemd can supervise it`, `stack unit stops by
  tearing the compose stack down`, `stack unit restarts on failure`, `stack unit caps restarts
  (StartLimitIntervalSec/StartLimitBurst)`, `inference unit execs the real supervisor script`,
  `inference unit orders itself after the stack, without requiring it`, `inference unit caps
  restarts (StartLimitIntervalSec/StartLimitBurst)`.
- `bash deploy/macos/install.test.sh` — **41 passed, 0 failed**, including the matching
  LaunchAgent-plist tests (`stack agent runs compose in the foreground with an absolute podman
  path`, `stack agent restarts on a non-zero exit`, `stack agent has its own label, distinct
  from the app`, `inference agent execs the real supervisor script`, `inference agent has its
  own label, distinct from the app`).
- Generated the real `askwell-stack.service`/`askwell-inference.service`/`askwell.service`
  content from `deploy/linux/lib.sh` against a scratch prefix and ran `systemd-analyze --user
  verify` on this host's real systemd (258): no unit-syntax errors, only the expected "command
  not executable" complaints for the scratch prefix's nonexistent `askwell`/`askwell-inference`
  binaries — confirming the units are well-formed, not merely that they parse in isolation.
  This host's own unrelated `askwell-watchdog.service` surfaced a pre-existing `KillMode=none`
  deprecation warning during the same verify run; it is not from this ticket's units and is not
  this ticket's to fix.
- Ran a real systemd-user restart-loop-and-cap cycle (Part F above) and confirmed the exact
  wording (`Failed with result 'exit-code'`, `restart counter is at N`, `Start request repeated
  too quickly`) systemd produces once `StartLimitBurst` is exceeded, on this host's real
  systemd — not asserted from documentation.
- `xmllint --noout` against the macOS plist templates was not re-run this session (`.plist`
  generation and its `xmllint` check were verified in the same session that wrote
  `deploy/macos/lib.sh`, per `docs/BRAIN.md`'s `0.7.13` entry) — not repeated here since the
  plist-generating functions were not touched by this walkthrough.

---

## Known gaps

- **No end-to-end run through the desktop shell.** This build host has no
  `webkit2gtk4.1-devel`/`gtk3-devel`/`atk-devel`/`cairo-gobject-devel` and no root to install
  them, so `web/src-tauri/target/release/askwell-shell` cannot be built here — the same gap
  `M7-TAURI-FE-182` and `M7-TAURI-DEPLOY-183` recorded as issue #497, still open. Steps 1, 4, 5
  and 6 above (which need the shell binary to open a window) are written from the code and from
  the unit-level verification above, not from an observed window. Whoever next has the missing
  packages should run this document for real and close #497.
- **macOS's `KeepAlive` has no restart cap.** Unlike systemd's `StartLimitBurst` or Windows'
  `RestartCount`, launchd retries a permanently failing `LaunchAgent` indefinitely — accepted in
  `docs/decisions.md` (2026-09-23) rather than patched with a wrapper script. Part F's
  "restart loop hits a cap and reports failed" therefore has **no macOS equivalent** — issue
  #607 is open, re-owned, tracking `state.json` heartbeat age as the cross-platform detection
  path `M7-PACK-FE-143`'s repair surface should read instead.
- **Windows' restart semantics are unverified against a real Windows session.** `Register-
  ScheduledTask`'s `RestartCount`/`RestartInterval` behaviour (in particular whether a
  non-zero *process* exit is treated as the task-level failure that triggers a restart) was
  checked against documentation only — no Windows host or `pwsh` was available on this build
  host either. Issue #606 is open, re-owned, unchanged from the prior `M7-TAURI-DEPLOY-183`
  session's identical gap.
- **Corrupted container volume recovery is manual**, as scoped by this ticket's own Testing
  Notes — not exercised here.
- **No repair surface.** A capped failure currently requires a manual `systemctl --user
  restart`/`launchctl load`/`Start-ScheduledTask` (or reinstalling); the buttons belong to
  `M7-PACK-FE-143`, not this ticket.
