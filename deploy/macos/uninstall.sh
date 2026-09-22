#!/usr/bin/env bash
# Uninstalls Askwell (M7-PACK-DEPLOY-141). Mirrors deploy/linux/uninstall.sh
# and deploy/windows/uninstall.ps1: removes the application bundle, the
# session-start LaunchAgent and the CLI symlink. Leaves the data directory —
# and therefore every document Askwell indexed, in place on the user's own
# disk untouched by Askwell — alone unless --purge-data is given, which
# still asks for confirmation before deleting anything.

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
  --purge-data      Also delete the data directory (indexed corpus stays where it lives; only Askwell's own copy is removed)
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
  launchctl unload "$plist" >/dev/null 2>&1 || true
  rm -f "$plist"
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
    if [ -d "$DATA_DIR" ]; then
      confirm "Delete Askwell's data directory ($DATA_DIR)? This removes your corpus's index, memory and settings — not the files themselves, which live where you put them." || {
        askwell_say "Data directory left in place: $DATA_DIR"
        exit 0
      }
      rm -rf "$DATA_DIR"
      askwell_say "Data directory removed: $DATA_DIR"
    fi
  else
    [ -d "$DATA_DIR" ] && askwell_say "Data directory left in place: $DATA_DIR (use --purge-data to remove it)"
  fi
}

main "$@"
