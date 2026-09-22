#!/usr/bin/env bash
# Askwell's Linux installer. M7-PACK-DEPLOY-139.
#
# One command, run by someone who has never used a container: check for or
# install Podman, place the stack, the native inference binary, the probe and
# the desktop shell, create the data directories, register Askwell to start
# with the session, and open the Askwell window — never a browser tab
# (docs/backlog/M7-someone-else-can-install-it.md, this ticket).
#
# What this script needs beside itself, and where it expects to find it:
#
#   REPO_ROOT (two directories above this script)/
#     compose.yaml, .env.example, deploy/postgres, deploy/sandbox   — the stack
#     deploy/probe/askwell-probe                                    — the host probe (M7-PROBE-DEPLOY-137)
#     deploy/inference/askwell-inference                             — native inference (M0-MODEL-DEPLOY-018)
#     web/src-tauri/target/release/askwell-shell                      — the desktop shell binary (M7-TAURI-DEPLOY-181)
#
# A release tarball ships this same layout (a trimmed export of the
# repository, not a separate bundle format) — there is no packaging step yet
# that produces anything else, and inventing one is out of this ticket's
# scope (see docs/decisions.md, this date; issue #559). The one artefact this
# script cannot produce itself is the compiled shell binary: building it needs
# the Rust toolchain, which a non-technical installing user must never be
# asked for, so its absence is a refusal naming the missing file and the
# build command that produces it — never a silent fall back to a browser tab,
# which is exactly the thing M7-TAURI-DEPLOY-181 exists to make unnecessary.
#
# Never fetches a model. Podman itself may need the network to install and
# `podman compose` may need it to pull or build container images — the same
# class of install-time exception `scripts/dev.sh lock`/`web-install` already
# name (AGENTS.md §5) — but nothing here ever reaches out for model weights.

set -Eeuo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
# shellcheck source=./lib.sh
. "$HERE/lib.sh"

VERSION="$(cat "$REPO_ROOT/VERSION" 2>/dev/null || echo "0.0.0")"

DATA_DIR="$(data_dir_default)"
INSTALL_PREFIX="$(install_prefix_default)"
BIN_DIR="$(bin_dir_default)"
DESKTOP_DIR="$(desktop_dir_default)"
SYSTEMD_USER_DIR="$(systemd_user_dir_default)"
ASSUME_YES=0

usage() {
  cat <<EOF
Usage: install.sh [options]

  --data-dir PATH     Where Askwell keeps its data (default: $DATA_DIR)
  --prefix PATH        Where Askwell's application files are placed (default: $INSTALL_PREFIX)
  -y, --yes            Do not prompt for confirmation
  -h, --help           Show this help
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --data-dir) DATA_DIR="$2"; shift 2 ;;
    --prefix) INSTALL_PREFIX="$2"; shift 2 ;;
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

# ---------------------------------------------------------------- 1. runtime

check_runtime() {
  if command -v podman >/dev/null 2>&1; then
    local reported
    reported="$(podman --version)"
    if podman_meets_minimum "$reported"; then
      askwell_say "Podman found: $reported"
      return 0
    fi
    askwell_die "Podman is installed but too old ($reported). Askwell needs Podman $ASKWELL_MIN_PODMAN_VERSION or newer. Upgrade it with your package manager, then run this installer again."
    exit 1
  fi

  local mgr cmd
  mgr="$(detect_pkg_manager)" || {
    askwell_die "Podman is not installed and this installer does not recognise your package manager. Install Podman $ASKWELL_MIN_PODMAN_VERSION or newer yourself (podman.io/docs/installation), then run this installer again."
    exit 1
  }
  cmd="$(runtime_install_cmd "$mgr")"

  if ! have_admin_path; then
    askwell_die "Podman is not installed, and this account has no path to root (no 'sudo' on this machine and not running as root). Ask whoever administers this machine to run: sudo $cmd — then run this installer again."
    exit 1
  fi

  askwell_say "Podman is not installed. This installer needs to run:"
  askwell_say "  sudo $cmd"
  confirm "Install Podman now?" || { askwell_die "Podman is required. Install it and re-run this installer."; exit 1; }
  # Real sudo, not `sudo -n`: it prompts for a password like any other command
  # on a normal desktop account, which is the whole fix for issue #503.
  if [ "$(id -u)" -eq 0 ]; then
    sh -c "$cmd"
  else
    sudo sh -c "$cmd"
  fi
  command -v podman >/dev/null 2>&1 || { askwell_die "Podman install command finished but 'podman' is still not on PATH. Something about that install did not work as expected."; exit 1; }
  askwell_say "Podman installed: $(podman --version)"
}

# ---------------------------------------------------------------- 2. disk space

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

# ---------------------------------------------------------------- 3. previous install

check_previous_install() {
  if is_previous_install "$DATA_DIR"; then
    local prev
    prev="$(previous_install_version "$DATA_DIR" || echo unknown)"
    askwell_say "Existing Askwell installation found (version $prev) at $DATA_DIR. Its data is left untouched; upgrading application files in place."
  fi
}

# ---------------------------------------------------------------- 4. required artefacts

SHELL_BIN="$REPO_ROOT/web/src-tauri/target/release/askwell-shell"

check_artefacts() {
  local missing=0
  [ -f "$REPO_ROOT/compose.yaml" ] || { askwell_say "Missing: $REPO_ROOT/compose.yaml"; missing=1; }
  [ -f "$REPO_ROOT/deploy/probe/askwell-probe" ] || { askwell_say "Missing: $REPO_ROOT/deploy/probe/askwell-probe"; missing=1; }
  [ -f "$REPO_ROOT/deploy/inference/askwell-inference" ] || { askwell_say "Missing: $REPO_ROOT/deploy/inference/askwell-inference"; missing=1; }
  if [ ! -f "$SHELL_BIN" ]; then
    askwell_say "Missing: $SHELL_BIN"
    askwell_say "  The desktop shell has not been built. Build it first with:"
    askwell_say "    cd $REPO_ROOT/web/src-tauri && cargo tauri build --no-bundle"
    missing=1
  fi
  if [ "$missing" -eq 1 ]; then
    askwell_die "One or more required files are missing (listed above). This installer places what a release build produces; it does not build them. Nothing has been copied."
    exit 1
  fi
}

# ---------------------------------------------------------------- 5. place files

place_files() {
  mkdir -p "$INSTALL_PREFIX" "$BIN_DIR" "$DESKTOP_DIR" "$SYSTEMD_USER_DIR"
  mkdir -p "$INSTALL_PREFIX/deploy/postgres" "$INSTALL_PREFIX/deploy/sandbox"

  cp "$REPO_ROOT/compose.yaml" "$INSTALL_PREFIX/compose.yaml"
  if [ ! -f "$INSTALL_PREFIX/.env" ]; then
    cp "$REPO_ROOT/.env.example" "$INSTALL_PREFIX/.env"
    generate_env_passwords "$INSTALL_PREFIX/.env"
    askwell_say "Generated database credentials in $INSTALL_PREFIX/.env"
  fi
  cp -r "$REPO_ROOT/deploy/postgres/." "$INSTALL_PREFIX/deploy/postgres/"
  cp -r "$REPO_ROOT/deploy/sandbox/." "$INSTALL_PREFIX/deploy/sandbox/"
  cp "$REPO_ROOT/deploy/probe/askwell-probe" "$INSTALL_PREFIX/askwell-probe"
  cp "$REPO_ROOT/deploy/inference/askwell-inference" "$INSTALL_PREFIX/askwell-inference"
  chmod +x "$INSTALL_PREFIX/askwell-probe" "$INSTALL_PREFIX/askwell-inference"

  cp "$SHELL_BIN" "$INSTALL_PREFIX/askwell"
  chmod +x "$INSTALL_PREFIX/askwell"
  ln -sf "$INSTALL_PREFIX/askwell" "$BIN_DIR/askwell"

  askwell_say "Application files placed under $INSTALL_PREFIX"
}

# ---------------------------------------------------------------- 6. data dirs

create_data_dirs() {
  mkdir -p "$DATA_DIR" "$DATA_DIR/models" "$DATA_DIR/logs"
  askwell_say "Data directory: $DATA_DIR"
}

# ---------------------------------------------------------------- 7. probe

run_probe() {
  askwell_say "Probing this machine's hardware..."
  ASKWELL_PROBE_RESULT_PATH="$DATA_DIR/probe.json" python3 "$INSTALL_PREFIX/askwell-probe" || \
    askwell_say "Probe did not complete; Askwell will fall back to the standard profile on first launch."
}

# ---------------------------------------------------------------- 8. desktop entry + session start

register_desktop_entry() {
  desktop_entry_contents "$BIN_DIR/askwell" "askwell" > "$DESKTOP_DIR/askwell.desktop"
  askwell_say "Applications-menu entry installed: $DESKTOP_DIR/askwell.desktop"
}

register_session_start() {
  systemd_unit_contents "$BIN_DIR/askwell" > "$SYSTEMD_USER_DIR/askwell.service"
  if command -v systemctl >/dev/null 2>&1 && systemctl --user daemon-reload 2>/dev/null && systemctl --user enable askwell.service 2>/dev/null; then
    askwell_say "Askwell registered to start with your session (systemd --user)."
  else
    askwell_say "Wrote $SYSTEMD_USER_DIR/askwell.service but could not enable it (no systemd --user session available right now). Askwell will not start automatically with your session until you run: systemctl --user enable askwell.service"
  fi
}

# ---------------------------------------------------------------- 9. install record + launch

record_install() {
  local method="install"
  is_previous_install "$DATA_DIR" && method="upgrade"
  write_install_record "$DATA_DIR" "$VERSION" "$method"
  askwell_say "Install record written: $(install_record_path "$DATA_DIR")"
}

launch() {
  askwell_say "Starting Askwell..."
  ASKWELL_DATA_DIR="$DATA_DIR" "$INSTALL_PREFIX/askwell" &
  disown || true
  askwell_say "Askwell is starting. Its window will open shortly."
}

main() {
  askwell_say "Installing Askwell $VERSION"
  check_runtime
  check_disk_space
  check_previous_install
  check_artefacts
  place_files
  create_data_dirs
  run_probe
  register_desktop_entry
  register_session_start
  record_install
  launch
  askwell_say "Done. Askwell is also available any time from your applications menu."
}

main "$@"
