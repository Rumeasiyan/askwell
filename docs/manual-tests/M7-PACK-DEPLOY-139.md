# Manual test — M7-PACK-DEPLOY-139, the Linux installer

**Ticket:** `M7-PACK-DEPLOY-139` — one installer that checks for or installs Podman, places
the stack, the native inference binary, the probe and the desktop shell, creates the data
directories, registers Askwell to start with the session, and opens the Askwell window —
never a browser tab.
**Version under test:** `0.7.7`
**Time:** about 20 minutes on a clean Linux VM with the release artefacts already built; the
logic itself (`deploy/linux/install.test.sh`) runs in seconds with no VM at all.

**This is a rebuild of an earlier, unmerged attempt at this ticket** (PR #560, closed —
CI was green but the branch went stale against `main` before it could land). That attempt's
own fixes for issue #503 (the `sudo -n true` bug) and the shell-binary filename
(`askwell-shell`, not `askwell`) are carried forward unchanged; its audit additionally found
issue #584 after it closed — the installer copied `.env.example` to `.env` verbatim, shipping
the literal `change-me*` placeholders as real database credentials on every install — which
this rebuild fixes (`lib.sh`'s `generate_env_passwords`, called from `place_files` the moment
a fresh `.env` is written, never against an existing one).

**Where this stops on purpose.** This installer places what a release build produces — it
does not build the desktop shell binary itself, since that needs the Rust toolchain, and a
non-technical installing user must never be asked for that (`deploy/linux/install.sh`'s own
header comment). Producing that binary, and a real offline bundle of container images and
model weights, is `M7-OFFLINE-DEPLOY-144` and release packaging tooling that does not exist
yet — issue #559, still open. Windows and macOS are their own tickets. Update delivery is
blocked. The shell also does not start the containers itself (`M7-TAURI-DEPLOY-183`, not this
ticket's dependency and not built) — the installer runs `podman compose`'s images into place
but a first launch still needs `podman compose up -d` run separately until that ticket lands.

---

## Part 1 — the logic, no VM required

```
bash deploy/linux/install.test.sh
```

**Expect:** every check passes, including the package-manager detection, the version
comparison, the disk-space math, `have_admin_path` treating a machine with `sudo` on `PATH`
as having an admin path to try without requiring it to be passwordless (issue #503), and the
new secrets checks: `random_hex` produces distinct 64-character lowercase hex strings, and
`generate_env_passwords` leaves no `change-me` placeholder while keeping the sandbox-owner and
sandbox-readonly credential pairs equal to each other (issue #584).

## Part 2 — a real install, on this checkout

You do not need a second machine to prove the orchestration end to end; you need something
standing in for the desktop shell binary, since building the real one needs the Rust
toolchain this installer deliberately never invokes.

```
mkdir -p web/src-tauri/target/release
printf '#!/bin/sh\necho "fake askwell shell running"\nsleep 0.2\n' > web/src-tauri/target/release/askwell-shell
chmod +x web/src-tauri/target/release/askwell-shell

ASKWELL_DATA_DIR=/tmp/askwell-test-data \
ASKWELL_INSTALL_PREFIX=/tmp/askwell-test-app \
ASKWELL_BIN_DIR=/tmp/askwell-test-bin \
ASKWELL_DESKTOP_DIR=/tmp/askwell-test-desktop \
ASKWELL_SYSTEMD_USER_DIR=/tmp/askwell-test-systemd \
bash deploy/linux/install.sh -y
```

**Expect:** Podman is detected (already installed on a dev machine), disk space is reported
sufficient, application files land under the fake prefix, `.env` is written with "Generated
database credentials" and no `change-me` value anywhere in it, the probe runs and writes
`probe.json`, a desktop entry and a systemd user unit are written, an install record
(`install.json`) is written with the current `VERSION`, and the fake shell prints its line —
standing in for the real window opening.

**Then confirm an upgrade never touches an existing `.env` (its generated passwords must
survive):**

```
BEFORE="$(grep '^POSTGRES_PASSWORD=' /tmp/askwell-test-app/.env)"

ASKWELL_DATA_DIR=/tmp/askwell-test-data \
ASKWELL_INSTALL_PREFIX=/tmp/askwell-test-app \
ASKWELL_BIN_DIR=/tmp/askwell-test-bin \
ASKWELL_DESKTOP_DIR=/tmp/askwell-test-desktop \
ASKWELL_SYSTEMD_USER_DIR=/tmp/askwell-test-systemd \
bash deploy/linux/install.sh -y

AFTER="$(grep '^POSTGRES_PASSWORD=' /tmp/askwell-test-app/.env)"
[ "$BEFORE" = "$AFTER" ] && echo "PASS: password unchanged" || echo "FAIL: password rotated on upgrade"
```

**Expect:** `PASS: password unchanged`, and the install output says "Existing Askwell
installation found ... upgrading application files in place" rather than repeating "Generated
database credentials".

**Then confirm uninstall leaves data alone by default:**

```
ASKWELL_DATA_DIR=/tmp/askwell-test-data \
ASKWELL_INSTALL_PREFIX=/tmp/askwell-test-app \
ASKWELL_BIN_DIR=/tmp/askwell-test-bin \
ASKWELL_DESKTOP_DIR=/tmp/askwell-test-desktop \
ASKWELL_SYSTEMD_USER_DIR=/tmp/askwell-test-systemd \
bash deploy/linux/uninstall.sh -y

ls /tmp/askwell-test-app     # gone
ls /tmp/askwell-test-data    # still there — install.json, models/, logs/, probe.json
```

**Then confirm `--purge-data` removes it on explicit request:**

```
ASKWELL_DATA_DIR=/tmp/askwell-test-data bash deploy/linux/uninstall.sh -y --purge-data
ls /tmp/askwell-test-data    # gone
```

**Clean up the stand-in binary** so it is never mistaken for a real build artefact:

```
rm -rf web/src-tauri/target /tmp/askwell-test-*
```

## Part 3 — refusal without the shell binary

Without the fake binary in place (a genuinely clean checkout, or a release tree missing the
artefact), the installer must refuse before copying anything:

```
bash deploy/linux/install.sh -y
```

**Expect:** exit code 1, a message naming exactly `web/src-tauri/target/release/askwell-shell`
as missing along with the build command that produces it, and nothing written to any of the
target directories. This is the "insufficient disk / missing prerequisite" family of edge
case stated as a hard requirement — refused before copying, never a silent partial install.

## Known gaps

- **No real cold-start walkthrough.** The ticket's own acceptance test — a clean Linux VM with
  no container tooling, installing from the applications menu into the Askwell window,
  surviving a reboot, then a clean uninstall — needs two artefacts this repository does not yet
  produce: a built Tauri release binary (no CI job runs `cargo tauri build`; `bundle.active` is
  still `false`) and, per `M7-OFFLINE-DEPLOY-144`, a bundle carrying container images and model
  weights for one profile. Parts 1–3 above prove `install.sh`/`uninstall.sh`/`lib.sh`'s own
  logic end to end with a stand-in executable instead — issue #559, still open.
- **No systemd `--user` session on this host to enable against.** `register_session_start`
  wrote `askwell.service` correctly in Part 2's run but could not `systemctl --user enable` it
  (no user session bus in this environment), so it printed the documented fallback message
  instead of confirming the enable succeeded. This is an environment limitation of the checkout
  this walkthrough ran in, not a defect — the "session start registration" acceptance criterion
  needs a real desktop login session to verify the enabled path, not just the fallback one.
- **Windows and macOS are out of scope** for this ticket (`M7-PACK-DEPLOY-140`/`141`).
- **No update mechanism** — blocked, per the ticket's own Testing Notes.
- **Unsigned artefact.** Code-signing is `M7-TAURI-DEPLOY-184`, not yet built; once the shell
  binary exists, expect an OS-level unsigned-binary warning on first launch.
- **The shell does not start the containers itself** — `M7-TAURI-DEPLOY-183` (process
  supervision) is not this ticket's dependency and is not built. Until it lands, a real launch
  still needs `podman compose up -d` run once by hand alongside this installer, or the window
  will show its own "Starting Askwell" / "Still starting Askwell" state indefinitely rather
  than reaching the first-run screen.
