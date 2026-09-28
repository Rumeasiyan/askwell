#!/usr/bin/env bash
# Uninstalls Askwell (M7-PACK-DEPLOY-141). Mirrors deploy/linux/uninstall.sh
# and deploy/windows/uninstall.ps1: removes the application bundle, the
# session-start LaunchAgent and the CLI symlink. Leaves the data directory —
# and therefore every document Askwell indexed, in place on the user's own
# disk untouched by Askwell — alone unless --purge-data is given, which
# still asks for confirmation before deleting anything.
#
# --purge-data removes both places Askwell keeps data (issue #700): the data
# directory and the Podman volumes that hold the database. See the Linux
# uninstaller for why removing only the directory was wrong.

set -Eeuo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./lib.sh
. "$HERE/lib.sh"

DATA_DIR="$(data_dir_default)"
INSTALL_PREFIX="$(install_prefix_default)"
APP_DIR="$(app_dir_default)"
BIN_DIR="$(bin_dir_default)"
LAUNCH_AGENTS_DIR="$(launch_agents_dir_default)"
PURGE_DATA=0
ASSUME_YES=0

usage() {
  cat <<EOF
Usage: uninstall.sh [options]

  --data-dir PATH   Data directory to consider for --purge-data (default: $DATA_DIR)
  --purge-data      Also delete Askwell's data: the data directory and the database volumes (your own files stay where they live)
  -y, --yes         Do not prompt for confirmation
  -h, --help        Show this help
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --data-dir) DATA_DIR="$2"; shift 2 ;;
    --purge-data) PURGE_DATA=1; shift ;;
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

main() {
  local plist="$LAUNCH_AGENTS_DIR/com.askwell.app.plist"
  local plist_stack="$LAUNCH_AGENTS_DIR/com.askwell.stack.plist"
  local plist_inference="$LAUNCH_AGENTS_DIR/com.askwell.inference.plist"
  # M7-PACK-DEPLOY-142: unload the stack and inference LaunchAgents before the
  # shell's own, and before the `podman compose down` fallback below — that
  # fallback exists for the case where these were never loaded at all, not as
  # the primary stop path.
  launchctl unload "$plist_inference" >/dev/null 2>&1 || true
  launchctl unload "$plist_stack" >/dev/null 2>&1 || true
  launchctl unload "$plist" >/dev/null 2>&1 || true
  rm -f "$plist" "$plist_stack" "$plist_inference"
  rm -f "$BIN_DIR/askwell"
  rm -rf "$APP_DIR"

  if [ -d "$INSTALL_PREFIX" ]; then
    if command -v podman >/dev/null 2>&1 && [ -f "$INSTALL_PREFIX/compose.yaml" ]; then
      (cd "$INSTALL_PREFIX" && podman compose down >/dev/null 2>&1) || true
    fi
    rm -rf "$INSTALL_PREFIX"
  fi
  askwell_say "Askwell application files removed."

  if [ "$PURGE_DATA" -eq 1 ]; then
    confirm "Delete all of Askwell's data? This removes its database (your corpus's index and extracted text, memory, conversations and audit log), imported databases, stored backups and crash reports, and the data directory ($DATA_DIR: settings, models, logs). Your own files are not touched; they stay where you put them. Copy out any backup you want to keep first — there is no undo." || {
      askwell_say "Askwell's data left in place: the data directory $DATA_DIR and the database volumes ($ASKWELL_VOLUMES)."
      exit 0
    }
    purge_data
  else
    [ -d "$DATA_DIR" ] && askwell_say "Data directory left in place: $DATA_DIR (use --purge-data to remove it)"
    askwell_say "Askwell's database volumes are also left in place, so reinstalling keeps your index and memory (use --purge-data to remove them)."
  fi
}

# Says only what it did: each half is reported from what is on disk afterwards,
# not from what was asked for, and a volume that would not go is named with
# the command that removes it.
purge_data() {
  local remaining="" failed=0
  if command -v "${ASKWELL_PODMAN:-podman}" >/dev/null 2>&1; then
    if remaining="$(purge_stack_volumes)"; then
      askwell_say "Database volumes removed: $ASKWELL_VOLUMES"
    else
      askwell_say "Could not remove these volumes: $(echo $remaining). Stop anything still using them, then run: podman volume rm -f $(echo $remaining)"
      failed=1
    fi
  else
    askwell_say "Podman is not on PATH, so the database volumes ($ASKWELL_VOLUMES) could not be checked or removed. If they exist, remove them with: podman volume rm -f $ASKWELL_VOLUMES"
    failed=1
  fi
  if [ -d "$DATA_DIR" ]; then
    rm -rf "$DATA_DIR"
    if [ -d "$DATA_DIR" ]; then
      askwell_say "Could not remove the data directory: $DATA_DIR"
      failed=1
    else
      askwell_say "Data directory removed: $DATA_DIR"
    fi
  fi
  if [ "$failed" -eq 1 ]; then
    askwell_die "Askwell's data was not fully removed (see above)."
    exit 1
  fi
  askwell_say "All of Askwell's data has been removed."
}


main "$@"
