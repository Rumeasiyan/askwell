#!/usr/bin/env bash
# Tests for the Linux installer's logic (M7-PACK-DEPLOY-139). See
# scripts/guards.test.sh for the pattern this follows.
#
# These test lib.sh's pure functions only — never a real sudo, a real
# package manager, or a real podman. A machine that could exercise the whole
# installer (no podman, real root, a disposable data directory) is exactly
# the "clean Linux virtual machine" the ticket's own manual walkthrough
# requires (docs/manual-tests/M7-PACK-DEPLOY-139.md) and is not this suite's
# job to fake convincingly.
set -Eeuo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PASS=0; FAIL=0

ok()   { PASS=$((PASS+1)); printf '  ok    %s\n' "$1"; }
bad()  { FAIL=$((FAIL+1)); printf '  FAIL  %s\n' "$1"; }
check(){ if [ "$2" = "$3" ]; then ok "$1"; else bad "$1 (want '$3', got '$2')"; fi; }

fresh() {
  TMP="$(mktemp -d)"
  export HOME="$TMP/home"
  unset XDG_DATA_HOME XDG_CONFIG_HOME ASKWELL_DATA_DIR ASKWELL_INSTALL_PREFIX \
        ASKWELL_BIN_DIR ASKWELL_DESKTOP_DIR ASKWELL_SYSTEMD_USER_DIR \
        ASKWELL_REQUIRED_INSTALL_BYTES
  mkdir -p "$HOME"
  # shellcheck source=./lib.sh
  . "$HERE/lib.sh"
}

# A fake PATH directory containing only the named commands, so
# detect_pkg_manager and have_admin_path see exactly one thing on the
# machine rather than whatever happens to be installed on the test runner.
fake_path_with() {
  local dir="$TMP/fakebin"
  rm -rf "$dir"; mkdir -p "$dir"
  for cmd in "$@"; do : > "$dir/$cmd"; chmod +x "$dir/$cmd"; done
  echo "$dir"
}

printf 'linux installer\n'

# --- package manager detection ----------------------------------------------
fresh
out="$(PATH="$(fake_path_with dnf)" detect_pkg_manager)"
check "detects dnf" "$out" "dnf"

fresh
out="$(PATH="$(fake_path_with apt-get)" detect_pkg_manager)"
check "detects apt" "$out" "apt"

fresh
out="$(PATH="$(fake_path_with pacman)" detect_pkg_manager)"
check "detects pacman" "$out" "pacman"

fresh
PATH="$(fake_path_with)" detect_pkg_manager >/dev/null 2>&1 && r=0 || r=1
check "unknown package manager is a refusal, not a guess" "$r" 1

# --- install command ---------------------------------------------------------
fresh
check "dnf install command names podman" "$(runtime_install_cmd dnf)" "dnf install -y podman"
runtime_install_cmd nosuchmanager >/dev/null 2>&1 && r=0 || r=1
check "unrecognised manager has no install command" "$r" 1

# --- sudo access: the #503 fix -----------------------------------------------
# The bug: `sudo -n true` only succeeds for passwordless sudo, so a normal
# desktop account (sudo present, configured to prompt) was told it had no
# administrative rights at all. have_admin_path must say yes whenever sudo
# exists on PATH, regardless of whether it would prompt or succeed silently —
# the actual prompt/refusal is sudo's job at the point of use, not this
# check's.
fresh
fakebin="$(fake_path_with sudo)"; cp "$(command -v id)" "$fakebin/id"
PATH="$fakebin" have_admin_path && r=0 || r=1
check "sudo present (even password-prompting) counts as an admin path" "$r" 0

fresh
fakebin="$(fake_path_with)"; cp "$(command -v id)" "$fakebin/id"
PATH="$fakebin" have_admin_path && r=0 || r=1
check "no sudo and not root has no admin path" "$r" 1

# --- version comparison ------------------------------------------------------
fresh
check "equal versions compare 0" "$(version_compare 4.3.0 4.3.0)" "0"
check "shorter version pads with zero (4.3 == 4.3.0)" "$(version_compare 4.3 4.3.0)" "0"
check "4.9.4 > 4.3" "$(version_compare 4.9.4 4.3)" "1"
check "3.4 < 4.3" "$(version_compare 3.4 4.3)" "-1"
version_ge 4.9.4 4.3 && r=0 || r=1
check "version_ge true case" "$r" 0
version_ge 3.4 4.3 && r=0 || r=1
check "version_ge false case" "$r" 1

# --- podman version parsing ---------------------------------------------------
fresh
check "parses podman's own version banner" "$(parse_podman_version 'podman version 4.9.4')" "4.9.4"
podman_meets_minimum "podman version 5.8.4" && r=0 || r=1
check "5.8.4 meets the default minimum" "$r" 0
podman_meets_minimum "podman version 3.4.0" && r=0 || r=1
check "3.4.0 does not meet the default minimum" "$r" 1
podman_meets_minimum "not even a version string" >/dev/null 2>&1 && r=0 || r=1
check "unparseable version string is a refusal, not a guess" "$r" 1

# --- disk space ---------------------------------------------------------------
fresh
check "human_bytes renders GB" "$(human_bytes 8000000000)" "7.5 GB"
check "human_bytes renders MB" "$(human_bytes 5000000)" "4.8 MB"

fresh
mkdir -p "$TMP/existing-parent/nested-not-yet-created"
avail="$(available_bytes "$TMP/existing-parent/nested-not-yet-created/deeper")"
case "$avail" in ''|*[!0-9]*) bad "available_bytes returns a plain integer for a not-yet-created path" ;;
                   *) ok "available_bytes returns a plain integer for a not-yet-created path" ;; esac

# --- paths ---------------------------------------------------------------------
fresh
check "data dir defaults under HOME" "$(data_dir_default)" "$HOME/.local/share/askwell"
ASKWELL_DATA_DIR="/custom/data" out="$(data_dir_default)"
check "data dir honours override" "$out" "/custom/data"

fresh
XDG_DATA_HOME="$HOME/xdg-data" out="$(data_dir_default)"
check "data dir honours XDG_DATA_HOME" "$out" "$HOME/xdg-data/askwell"

# --- previous install state ----------------------------------------------------
fresh
is_previous_install "$TMP/nowhere" && r=0 || r=1
check "no install record means no previous install" "$r" 1

write_install_record "$TMP/data" "0.6.5" "install"
is_previous_install "$TMP/data" && r=0 || r=1
check "a written record is detected as a previous install" "$r" 0
check "the recorded version reads back" "$(previous_install_version "$TMP/data")" "0.6.5"

# --- generated files -------------------------------------------------------------
fresh
out="$(desktop_entry_contents "/home/x/.local/bin/askwell" "askwell")"
case "$out" in *"Exec=/home/x/.local/bin/askwell"*) ok "desktop entry names the real executable" ;;
               *) bad "desktop entry names the real executable" ;; esac
case "$out" in *"Type=Application"*) ok "desktop entry declares an application" ;;
               *) bad "desktop entry declares an application" ;; esac

out="$(systemd_unit_contents "/home/x/.local/bin/askwell")"
case "$out" in *"WantedBy=default.target"*) ok "systemd unit starts with the user session" ;;
               *) bad "systemd unit starts with the user session" ;; esac
case "$out" in *"ExecStart=/home/x/.local/bin/askwell"*) ok "systemd unit execs the real binary" ;;
               *) bad "systemd unit execs the real binary" ;; esac

printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
