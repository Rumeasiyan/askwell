#!/usr/bin/env bash
# Askwell's macOS installer. M7-PACK-DEPLOY-141.
#
# Same shape and the same nine steps as deploy/linux/install.sh and
# deploy/windows/install.ps1: check for or install Podman, place the stack,
# the native inference binary, the probe and the desktop shell, create the
# data directories, register Askwell to start with the session, and open the
# Askwell window — never a browser tab.
#
# What this script needs beside itself, and where it expects to find it:
#
#   REPO_ROOT (two directories above this script)/
#     compose.yaml, .env.example, deploy/postgres, deploy/sandbox, deploy/redis — the stack
#     deploy/probe/askwell-probe                                    — the host probe (M7-PROBE-DEPLOY-137)
#     deploy/inference/askwell-inference                             — native inference (M0-MODEL-DEPLOY-018)
#     deploy/inference/llama.cpp/gpu/                                  — llama.cpp's Metal build
#                                                                      (a release only; M10-FIX-DEPLOY-222)
#     web/src-tauri/target/release/bundle/macos/Askwell.app           — the desktop shell,
#                                                                       already bundled (M7-TAURI-DEPLOY-181)
#     web/out/                                                         — the built interface compose.yaml mounts (#766)
#     images/*.tar                                                     — the container images, saved (optional)
#
# Three things are specific to this platform and have no Linux or Windows
# equivalent:
#
#   1. Podman has no native macOS runtime; every container runs inside a
#      small VM ("the Podman machine"), the same shape as Windows' WSL2.
#      `ensure_machine` creates and starts one if neither exists.
#   2. That machine only sees paths under this account's home directory by
#      default — `check_roots_mount` says so, rather than silently letting a
#      folder outside it register and fail invisibly later. This is the
#      installer's half of the design `docs/decisions.md` (2026-08-27,
#      "Nominated folders are mounted at their own paths") already accepted
#      for every platform: `not_mounted` is a recorded, explained state, not
#      a defect, and this only adds the macOS-specific cause for it.
#   3. Askwell ships **unsigned** (`docs/decisions.md`, 2026-08-26, "No
#      trademark, unsigned distribution, and Apache-2.0 stays"; also
#      `docs/installing.md`). Real code signing and notarisation
#      (`M7-TAURI-DEPLOY-184a`) are explicitly deferred, blocked on the cost
#      of an Apple Developer enrolment rather than on engineering — not a
#      gap this ticket can close. This script therefore never attempts to
#      verify a signature and never claims one exists.
#
# A release tarball ships this same layout, assembled by
# scripts/release-artefact.sh in .github/workflows/release.yml
# (M9-REL-DEPLOY-214), with the container images saved under `images/` so
# nothing is built from source or pulled here. A source checkout has no
# `images/` and uses the images already in the Podman machine.
# The one artefact this script cannot produce itself is the bundled `.app`:
# building it needs the Rust toolchain and, to actually be a `.app` rather
# than a bare binary, `cargo tauri build`'s bundling step, which a
# non-technical installing user must never be asked for — so its absence is
# a refusal naming the missing path and the build command, never a silent
# fall back to a browser tab.
#
# Never fetches a model. Homebrew and Podman's own install may need the
# network — the same class of install-time exception `scripts/dev.sh
# lock`/`web-install` already name (AGENTS.md §5) — but nothing here ever
# reaches out for model weights.

set -Eeuo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
# shellcheck source=./lib.sh
. "$HERE/lib.sh"

VERSION="$(cat "$REPO_ROOT/VERSION" 2>/dev/null || echo "0.0.0")"

DATA_DIR="$(data_dir_default)"
INSTALL_PREFIX="$(install_prefix_default)"
APP_DIR="$(app_dir_default)"
BIN_DIR="$(bin_dir_default)"
LAUNCH_AGENTS_DIR="$(launch_agents_dir_default)"
ASSUME_YES=0

usage() {
  cat <<EOF
Usage: install.sh [options]

  --data-dir PATH   Where Askwell keeps its data (default: $DATA_DIR)
  --prefix PATH      Where Askwell's application files are placed (default: $INSTALL_PREFIX)
  --app-dir PATH      Where the Askwell.app bundle is placed (default: $APP_DIR)
  -y, --yes           Do not prompt for confirmation
  -h, --help          Show this help
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --data-dir) DATA_DIR="$2"; shift 2 ;;
    --prefix) INSTALL_PREFIX="$2"; shift 2 ;;
    --app-dir) APP_DIR="$2"; shift 2 ;;
    -y|--yes) ASSUME_YES=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) askwell_die "unknown option: $1"; usage >&2; exit 1 ;;
  esac
done

confirm() {
  [ "$ASSUME_YES" -eq 1 ] && return 0
  local prompt="$1" reply
  printf '%s [y/N] ' "$prompt" > /dev/tty
  read -r reply < /dev/tty || reply=""
  case "$reply" in [yY]|[yY][eE][sS]) return 0 ;; *) return 1 ;; esac
}

# ---------------------------------------------------------------- 1. runtime + machine

check_runtime() {
  if ! command -v podman >/dev/null 2>&1; then
    if ! command -v brew >/dev/null 2>&1; then
      askwell_die "Podman is not installed, and Homebrew (brew) is not either. Install Homebrew yourself (brew.sh — its own installer needs to run with your permission, which this script will not do on your behalf), then run: brew install podman, then run this installer again."
      exit 1
    fi
    askwell_say "Podman is not installed. This installer needs to run:"
    askwell_say "  $(runtime_install_cmd)"
    confirm "Install Podman now?" || { askwell_die "Podman is required. Install it and re-run this installer."; exit 1; }
    brew install podman
    command -v podman >/dev/null 2>&1 || { askwell_die "Homebrew finished but 'podman' is still not on PATH. Something about that install did not work as expected."; exit 1; }
  fi

  local reported
  reported="$(podman --version)"
  if ! podman_meets_minimum "$reported"; then
    askwell_die "Podman is installed but too old ($reported). Askwell needs Podman $ASKWELL_MIN_PODMAN_VERSION or newer. Upgrade it with: brew upgrade podman — then run this installer again."
    exit 1
  fi
  askwell_say "Podman found: $reported"

  if ! has_podman_machine; then
    askwell_say "No Podman machine found; creating one (this downloads a small VM image and needs the network once)..."
    podman machine init || { askwell_die "Could not create a Podman machine. Run 'podman machine init' yourself to see the full error, fix it, then run this installer again."; exit 1; }
  fi
  if ! podman_machine_running; then
    askwell_say "Starting the Podman machine..."
    podman machine start || { askwell_die "Could not start the Podman machine. Run 'podman machine start' yourself to see the full error, fix it, then run this installer again."; exit 1; }
  fi
  askwell_say "Podman machine is running."
}

# ---------------------------------------------------------------- 1a. compose provider

# Issue #767: `podman compose` runs an external provider and Homebrew's
# podman brings none. Checked before anything is copied, and by name:
# docker-compose is the one provider this stack is verified with.
check_compose_provider() {
  local reported found="none"
  reported="$(podman compose version 2>/dev/null || true)"
  if compose_provider_meets_minimum "$reported"; then
    askwell_say "Compose provider found: $(printf '%s\n' "$reported" | grep -m1 'Docker Compose version')"
    return 0
  fi
  [ -n "$reported" ] && found="$(printf '%s\n' "$reported" | head -n1)"
  if ! command -v brew >/dev/null 2>&1; then
    askwell_die "Askwell runs its containers through 'podman compose', which needs Docker Compose $ASKWELL_MIN_COMPOSE_VERSION or newer installed as its provider (podman-compose is not supported). Found: $found. Install it (with Homebrew: $(compose_install_cmd)), then run this installer again. Nothing has been copied."
    exit 1
  fi
  askwell_say "Askwell runs its containers through 'podman compose', which needs Docker Compose $ASKWELL_MIN_COMPOSE_VERSION or newer (found: $found). This installer needs to run:"
  askwell_say "  $(compose_install_cmd)"
  confirm "Install Docker Compose now?" || { askwell_die "Docker Compose is required. Install it and re-run this installer. Nothing has been copied."; exit 1; }
  brew install docker-compose
  reported="$(podman compose version 2>/dev/null || true)"
  compose_provider_meets_minimum "$reported" || {
    askwell_die "Homebrew finished, but 'podman compose version' still does not report Docker Compose $ASKWELL_MIN_COMPOSE_VERSION or newer (it said: ${reported:-nothing}). Nothing has been copied."
    exit 1
  }
  askwell_say "Compose provider installed: $(printf '%s\n' "$reported" | grep -m1 'Docker Compose version')"
}

# ---------------------------------------------------------------- 2. roots-mount window

# Not a gate — informational, printed once, matching the accepted design in
# docs/decisions.md (2026-08-27): a folder outside the mounted window is
# registered anyway and reports `not_mounted` rather than being refused, so
# there is nothing here for this installer to enforce. What it can do is
# name the platform-specific cause before the user meets it as a surprise.
check_roots_mount() {
  askwell_say "Podman's machine can only see folders under your home directory ($HOME) by default. If the material you plan to add lives outside it — an external drive, a second volume — nominating that folder will report 'not mounted' until the machine is recreated with that path added (podman machine init --volume <path>:<path>, after stopping the current machine). See docs/data-sources.md."
}

# ---------------------------------------------------------------- 3. disk space

check_disk_space() {
  local needed have
  needed="$(required_install_bytes)"
  have="$(available_bytes "$INSTALL_PREFIX")"
  if [ -z "$have" ]; then
    askwell_say "Could not determine free disk space at $INSTALL_PREFIX; continuing without the check."
    return 0
  fi
  if [ "$have" -lt "$needed" ]; then
    askwell_die "Not enough disk space at $INSTALL_PREFIX: need $(human_bytes "$needed"), have $(human_bytes "$have"). Free up space and run this installer again — nothing has been copied."
    exit 1
  fi
  askwell_say "Disk space OK: $(human_bytes "$have") available, $(human_bytes "$needed") needed."
}

# ---------------------------------------------------------------- 4. previous install

check_previous_install() {
  if is_previous_install "$DATA_DIR"; then
    local prev
    prev="$(previous_install_version "$DATA_DIR" || echo unknown)"
    askwell_say "Existing Askwell installation found (version $prev) at $DATA_DIR. Its data is left untouched; upgrading application files in place."
  fi
}

# ---------------------------------------------------------------- 5. required artefacts

SHELL_BUNDLE="$REPO_ROOT/web/src-tauri/target/release/bundle/macos/Askwell.app"

check_artefacts() {
  local missing=0
  [ -f "$REPO_ROOT/compose.yaml" ] || { askwell_say "Missing: $REPO_ROOT/compose.yaml"; missing=1; }
  [ -f "$REPO_ROOT/deploy/probe/askwell-probe" ] || { askwell_say "Missing: $REPO_ROOT/deploy/probe/askwell-probe"; missing=1; }
  [ -f "$REPO_ROOT/deploy/inference/askwell-inference" ] || { askwell_say "Missing: $REPO_ROOT/deploy/inference/askwell-inference"; missing=1; }
  if [ ! -d "$SHELL_BUNDLE" ]; then
    askwell_say "Missing: $SHELL_BUNDLE"
    askwell_say "  The desktop application bundle has not been built. Build it first with:"
    askwell_say "    cd $REPO_ROOT/web/src-tauri && cargo tauri build"
    missing=1
  fi
  if [ ! -f "$REPO_ROOT/web/out/index.html" ]; then
    askwell_say "Missing: $REPO_ROOT/web/out/index.html"
    askwell_say "  The interface has not been built. Build it first with: scripts/dev.sh web-build"
    missing=1
  fi
  if [ "$missing" -eq 1 ]; then
    askwell_die "One or more required files are missing (listed above). This installer places what a release build produces; it does not build them. Nothing has been copied."
    exit 1
  fi
}

# ---------------------------------------------------------------- 6. place files

place_files() {
  mkdir -p "$INSTALL_PREFIX" "$BIN_DIR" "$LAUNCH_AGENTS_DIR" "$(dirname "$APP_DIR")"
  mkdir -p "$INSTALL_PREFIX/deploy/postgres" "$INSTALL_PREFIX/deploy/sandbox" "$INSTALL_PREFIX/deploy/redis"

  cp "$REPO_ROOT/compose.yaml" "$INSTALL_PREFIX/compose.yaml"
  local kept_env
  kept_env="$(kept_env_path "$DATA_DIR")"
  if [ ! -f "$INSTALL_PREFIX/.env" ] && [ -f "$kept_env" ]; then
    # Issue #765: the database volumes outlived a plain uninstall, and these
    # are the passwords they were initialised with.
    mv "$kept_env" "$INSTALL_PREFIX/.env"
    askwell_say "Restored the database credentials the previous uninstall kept, so this install opens the database it left in place."
  elif [ ! -f "$INSTALL_PREFIX/.env" ]; then
    cp "$REPO_ROOT/.env.example" "$INSTALL_PREFIX/.env"
    generate_env_passwords "$INSTALL_PREFIX/.env"
    askwell_say "Generated database credentials in $INSTALL_PREFIX/.env"
  fi
  # Every run, not only a fresh one: an upgrade from before Redis had users
  # needs these generated too, or the stack refuses to start.
  ensure_redis_passwords "$INSTALL_PREFIX/.env"
  cp -r "$REPO_ROOT/deploy/postgres/." "$INSTALL_PREFIX/deploy/postgres/"
  cp -r "$REPO_ROOT/deploy/sandbox/." "$INSTALL_PREFIX/deploy/sandbox/"
  cp -r "$REPO_ROOT/deploy/redis/." "$INSTALL_PREFIX/deploy/redis/"
  cp "$REPO_ROOT/deploy/probe/askwell-probe" "$INSTALL_PREFIX/askwell-probe"
  cp "$REPO_ROOT/deploy/inference/askwell-inference" "$INSTALL_PREFIX/askwell-inference"
  chmod +x "$INSTALL_PREFIX/askwell-probe" "$INSTALL_PREFIX/askwell-inference"
  place_llama_cpp

  # Replaced, not merged: a file an older interface had and this one does
  # not must not keep being served.
  rm -rf "$INSTALL_PREFIX/web/out"
  mkdir -p "$INSTALL_PREFIX/web"
  cp -R "$REPO_ROOT/web/out" "$INSTALL_PREFIX/web/out"

  rm -rf "$APP_DIR"
  cp -R "$SHELL_BUNDLE" "$APP_DIR"
  if [ ! -d "$APP_DIR" ]; then
    askwell_die "$(quarantine_message "$(basename "$APP_DIR")")"
    exit 1
  fi

  local exec_path="$APP_DIR/Contents/MacOS/askwell-shell"
  if [ -x "$exec_path" ]; then
    ln -sf "$exec_path" "$BIN_DIR/askwell"
  fi

  askwell_say "Application placed at $APP_DIR; stack files under $INSTALL_PREFIX"
}

# The llama.cpp build a release carries (M10-FIX-DEPLOY-222), placed next to
# askwell-inference, which is where it looks. On Apple silicon that is one
# build with Metal built in; the supervisor runs it on the processor
# (`--device none`) if the graphics side ever fails to load the model.
# Replaced, not merged, as on Linux. A source checkout carries none, and the
# supervisor runs `llama-server` from PATH as before. XProtect may remove an
# unfamiliar executable, so its absence afterwards is named the way the
# shell's is.
place_llama_cpp() {
  local src="$REPO_ROOT/deploy/inference/llama.cpp"
  if [ ! -f "$src/gpu/llama-server" ] && [ ! -f "$src/cpu/llama-server" ]; then
    askwell_say "No llama.cpp build is bundled here; Askwell will run llama-server from PATH."
    return 0
  fi
  rm -rf "$INSTALL_PREFIX/llama.cpp"
  cp -Rp "$src" "$INSTALL_PREFIX/llama.cpp"
  if [ -f "$src/gpu/llama-server" ] && [ ! -f "$INSTALL_PREFIX/llama.cpp/gpu/llama-server" ]; then
    askwell_die "$(quarantine_message llama-server)"
    exit 1
  fi
  askwell_say "llama.cpp placed under $INSTALL_PREFIX/llama.cpp. Answers run on the graphics side of this Mac's chip where llama.cpp can use it, and on the processor otherwise."
}

# ---------------------------------------------------------------- 6a. container images

# Into the Podman machine check_runtime has already started, and before the
# stack agent is loaded: `up` uses an image already present and builds or
# pulls only one that is missing.
load_images() {
  local archives archive
  archives="$(bundled_image_archives "$REPO_ROOT")"
  if [ -z "$archives" ]; then
    askwell_say "No bundled container images; the stack will use the images already in the Podman machine."
    return 0
  fi
  while IFS= read -r archive; do
    askwell_say "Loading container image $(basename "$archive")..."
    podman load -q -i "$archive" >/dev/null || {
      askwell_die "Could not load the container image $archive. The download may be damaged — check it against SHA256SUMS (docs/installing.md) and run this installer again."
      exit 1
    }
  done <<EOF_ARCHIVES
$archives
EOF_ARCHIVES
  askwell_say "Container images loaded."
}

# ---------------------------------------------------------------- 7. data dirs

create_data_dirs() {
  mkdir -p "$DATA_DIR" "$DATA_DIR/models" "$DATA_DIR/logs"
  askwell_say "Data directory: $DATA_DIR"
}

# ---------------------------------------------------------------- 7a. stop the old version

# Issue #768: on an upgrade the old version's containers are still serving.
# They stop before the schema moves, and register_stack_and_inference loads
# the new LaunchAgent after, so no code runs against a schema newer than its
# own. The LaunchAgent is unloaded first because KeepAlive would otherwise
# restart it; `down` then also catches containers the desktop shell started
# itself. Only on an upgrade: a fresh install has nothing running.
stop_previous_stack() {
  is_previous_install "$DATA_DIR" || return 0
  launchctl unload "$LAUNCH_AGENTS_DIR/com.askwell.stack.plist" >/dev/null 2>&1 || true
  stop_stack_containers "$INSTALL_PREFIX/compose.yaml" "$INSTALL_PREFIX/.env" || {
    askwell_die "Could not stop the running Askwell's containers (podman compose down failed), so the upgrade stopped before changing the database. The new application files are in place; run this installer again."
    exit 1
  }
  askwell_say "Stopped the running Askwell so its database can be upgraded; the new version starts once the upgrade is done."
}

# ---------------------------------------------------------------- 7b. database schema

# Issue #698: before this step existed nothing ever ran a migration, so a
# fresh install started against an empty database and an upgrade ran new code
# against the old schema. Runs before the stack is registered so that a
# failure stops the install here, named, rather than after it has said done.
migrate_database() {
  local log="$DATA_DIR/logs/migrate.log" applied rc
  askwell_say "Bringing Askwell's database up to date (the first run also starts the database)..."
  if run_database_migration "$INSTALL_PREFIX/compose.yaml" "$INSTALL_PREFIX/.env" "$log"; then
    applied="$(migrations_applied "$log")"
    if [ "${applied:-0}" -eq 0 ]; then
      askwell_say "Database schema already up to date; no migrations to apply."
    else
      askwell_say "Database schema up to date: applied $applied migration(s)."
    fi
    return 0
  else
    rc=$?
  fi
  printf '\n' >&2
  tail -n 20 "$log" >&2 || true
  printf '\n' >&2
  askwell_die "The database migration (alembic upgrade head, run as the stack's migrate service) failed with exit status $rc (its last lines are above, the full output is in $log). The install stopped at this step and is not complete: nothing after it was done. The upgrade runs as one transaction, so the database is left as it was before this step. Run this installer again once the cause is fixed."
  exit 1
}

# ---------------------------------------------------------------- 8. probe

run_probe() {
  askwell_say "Probing this machine's hardware..."
  ASKWELL_PROBE_RESULT_PATH="$DATA_DIR/probe.json" python3 "$INSTALL_PREFIX/askwell-probe" || \
    askwell_say "Probe did not complete; Askwell will fall back to the standard profile on first launch."
}

# ---------------------------------------------------------------- 9. session start + launch

register_session_start() {
  local plist="$LAUNCH_AGENTS_DIR/com.askwell.app.plist"
  launch_agent_plist_contents "$APP_DIR/Contents/MacOS/askwell-shell" > "$plist"
  launchctl unload "$plist" >/dev/null 2>&1 || true
  if launchctl load "$plist" >/dev/null 2>&1; then
    askwell_say "Askwell registered to start with your session (LaunchAgent)."
  else
    askwell_say "Wrote $plist but could not load it. Askwell will not start automatically with your session until you log out and back in, or run: launchctl load $plist"
  fi
}

# The platform half of M7-PACK-DEPLOY-142: the stack and native inference
# process, each as their own LaunchAgent, running for the session whether or
# not the app itself is ever opened. `podman` is resolved to its absolute
# path here rather than left as a bare command name: a LaunchAgent's default
# PATH is `/usr/bin:/bin:/usr/sbin:/sbin`, which never includes Homebrew's
# `/opt/homebrew/bin` or `/usr/local/bin` — a bare `podman` would fail to
# launch with no useful error the moment it left this script.
register_stack_and_inference() {
  local podman_bin plist_stack plist_inference
  podman_bin="$(command -v podman)"
  plist_stack="$LAUNCH_AGENTS_DIR/com.askwell.stack.plist"
  plist_inference="$LAUNCH_AGENTS_DIR/com.askwell.inference.plist"

  launch_agent_stack_plist_contents "$podman_bin" "$INSTALL_PREFIX/compose.yaml" "$INSTALL_PREFIX/.env" "$INSTALL_PREFIX" "$DATA_DIR/logs" \
    > "$plist_stack"
  launch_agent_inference_plist_contents "$INSTALL_PREFIX/askwell-inference" "$DATA_DIR/logs" \
    "$INSTALL_PREFIX/.env" "$INSTALL_PREFIX" > "$plist_inference"

  launchctl unload "$plist_stack" >/dev/null 2>&1 || true
  launchctl unload "$plist_inference" >/dev/null 2>&1 || true
  if launchctl load "$plist_stack" >/dev/null 2>&1 && launchctl load "$plist_inference" >/dev/null 2>&1; then
    askwell_say "Askwell's container stack and native inference process registered to run with your session, independent of the app window (LaunchAgent)."
  else
    askwell_say "Wrote the stack and inference LaunchAgents but could not load one of them. Load them yourself with: launchctl load $plist_stack $plist_inference"
  fi
}

record_install() {
  local method="install"
  is_previous_install "$DATA_DIR" && method="upgrade"
  write_install_record "$DATA_DIR" "$VERSION" "$method"
  askwell_say "Install record written: $(install_record_path "$DATA_DIR")"
}

launch() {
  askwell_say "Starting Askwell..."
  open "$APP_DIR"
  askwell_say "Askwell is starting. Its window will open shortly."
  # The release build is ad-hoc signed, which Apple silicon needs to run it at
  # all but which names no developer, so Gatekeeper still warns. Only a real
  # signing identity lists an Authority.
  if command -v codesign >/dev/null 2>&1 && ! codesign -dv "$APP_DIR" 2>&1 | grep -q '^Authority='; then
    askwell_say "Askwell is unsigned (docs/installing.md explains why). If macOS refuses to open it, System Settings -> Privacy & Security has an 'Open Anyway' button after the first attempt."
  fi
}

main() {
  askwell_say "Installing Askwell $VERSION"
  check_runtime
  check_compose_provider
  check_roots_mount
  check_disk_space
  check_previous_install
  check_artefacts
  place_files
  load_images
  create_data_dirs
  stop_previous_stack
  migrate_database
  run_probe
  register_stack_and_inference
  register_session_start
  record_install
  launch
  askwell_say "Done. Askwell is also available any time from $APP_DIR."
}

# Run, not sourced: install.test.sh sources this file to exercise one step.
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  main "$@"
fi
