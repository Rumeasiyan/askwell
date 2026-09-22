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

# --- secrets: the #584 fix ------------------------------------------------------
# The bug: install.sh copied .env.example straight to .env, leaving every
# POSTGRES_*/SANDBOX_*/ASKWELL_SANDBOX_* password as the literal change-me
# placeholder from the checked-in template, on every fresh install.
fresh
out1="$(random_hex 32)"
out2="$(random_hex 32)"
case "$out1" in [0-9a-f]*) ok "random_hex produces lowercase hex" ;; *) bad "random_hex produces lowercase hex (got '$out1')" ;; esac
check "random_hex(32) is 64 hex characters" "${#out1}" "64"
[ "$out1" != "$out2" ] && ok "two calls to random_hex do not repeat" || bad "two calls to random_hex do not repeat"

fresh
env_file="$TMP/env-under-test"
cat > "$env_file" <<'EOF'
POSTGRES_PASSWORD=change-me
POSTGRES_APP_PASSWORD=change-me-too
POSTGRES_READONLY_PASSWORD=change-me-as-well
SANDBOX_POSTGRES_PASSWORD=change-me-in-the-sandbox-too
SANDBOX_OWNER_PASSWORD=change-me-sandbox-owner
SANDBOX_READONLY_PASSWORD=change-me-sandbox-readonly
ASKWELL_SANDBOX_OWNER_PASSWORD=change-me-sandbox-owner
ASKWELL_SANDBOX_READONLY_PASSWORD=change-me-sandbox-readonly
EOF
generate_env_passwords "$env_file"

grep -q 'change-me' "$env_file" && r=0 || r=1
check "no change-me placeholder survives generation" "$r" 1

pg_pw="$(grep '^POSTGRES_PASSWORD=' "$env_file" | cut -d= -f2)"
pg_app_pw="$(grep '^POSTGRES_APP_PASSWORD=' "$env_file" | cut -d= -f2)"
pg_ro_pw="$(grep '^POSTGRES_READONLY_PASSWORD=' "$env_file" | cut -d= -f2)"
sbx_pg_pw="$(grep '^SANDBOX_POSTGRES_PASSWORD=' "$env_file" | cut -d= -f2)"
sbx_owner_pw="$(grep '^SANDBOX_OWNER_PASSWORD=' "$env_file" | cut -d= -f2)"
sbx_ro_pw="$(grep '^SANDBOX_READONLY_PASSWORD=' "$env_file" | cut -d= -f2)"
askwell_owner_pw="$(grep '^ASKWELL_SANDBOX_OWNER_PASSWORD=' "$env_file" | cut -d= -f2)"
askwell_ro_pw="$(grep '^ASKWELL_SANDBOX_READONLY_PASSWORD=' "$env_file" | cut -d= -f2)"

check "SANDBOX_OWNER_PASSWORD and ASKWELL_SANDBOX_OWNER_PASSWORD stay the same credential" "$sbx_owner_pw" "$askwell_owner_pw"
check "SANDBOX_READONLY_PASSWORD and ASKWELL_SANDBOX_READONLY_PASSWORD stay the same credential" "$sbx_ro_pw" "$askwell_ro_pw"

all_pw="$pg_pw $pg_app_pw $pg_ro_pw $sbx_pg_pw $sbx_owner_pw $sbx_ro_pw"
distinct="$(printf '%s\n' $all_pw | sort -u | wc -l | tr -d ' ')"
check "the six stored passwords are all distinct from each other" "$distinct" "6"

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
case "$out" in *"Wants=askwell-stack.service askwell-inference.service"*) ok "shell unit wants the platform-level stack and inference units" ;;
               *) bad "shell unit wants the platform-level stack and inference units" ;; esac

# --- M7-PACK-DEPLOY-142: stack + inference supervision units ------------------
out="$(systemd_stack_unit_contents "/data/compose.yaml" "/data/.env" "/data")"
case "$out" in *"ExecStart=podman compose -f /data/compose.yaml --env-file /data/.env up --abort-on-container-exit"*)
                 ok "stack unit runs compose in the foreground so systemd can supervise it" ;;
               *) bad "stack unit runs compose in the foreground so systemd can supervise it" ;; esac
case "$out" in *"ExecStop=podman compose -f /data/compose.yaml --env-file /data/.env down"*)
                 ok "stack unit stops by tearing the compose stack down" ;;
               *) bad "stack unit stops by tearing the compose stack down" ;; esac
case "$out" in *"Restart=on-failure"*) ok "stack unit restarts on failure" ;;
               *) bad "stack unit restarts on failure" ;; esac
case "$out" in *"StartLimitIntervalSec=300"*"StartLimitBurst=5"*)
                 ok "stack unit caps restarts (StartLimitIntervalSec/StartLimitBurst)" ;;
               *) bad "stack unit caps restarts (StartLimitIntervalSec/StartLimitBurst)" ;; esac

out="$(systemd_inference_unit_contents "/data/askwell-inference")"
case "$out" in *"ExecStart=/data/askwell-inference"*) ok "inference unit execs the real supervisor script" ;;
               *) bad "inference unit execs the real supervisor script" ;; esac
case "$out" in *"After=askwell-stack.service"*"Wants=askwell-stack.service"*)
                 ok "inference unit orders itself after the stack, without requiring it" ;;
               *) bad "inference unit orders itself after the stack, without requiring it" ;; esac
case "$out" in *"StartLimitIntervalSec=300"*"StartLimitBurst=5"*)
                 ok "inference unit caps restarts (StartLimitIntervalSec/StartLimitBurst)" ;;
               *) bad "inference unit caps restarts (StartLimitIntervalSec/StartLimitBurst)" ;; esac

printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
