#!/usr/bin/env bash
# Tests for the macOS installer's logic (M7-PACK-DEPLOY-141). See
# scripts/guards.test.sh for the pattern this follows, and
# deploy/linux/install.test.sh / deploy/windows/install.test.ps1 for the
# same suite on the other two platforms.
#
# These test lib.sh's pure functions only — never a real Homebrew, a real
# Podman machine, or a real launchd. A machine that could exercise the whole
# installer (no Podman, a disposable data directory, a real .app bundle) is
# exactly the "clean Mac" the ticket's own manual walkthrough requires
# (docs/manual-tests/M7-PACK-DEPLOY-141.md) and is not this suite's job to
# fake convincingly. Deliberately runs under Linux's bash and GNU coreutils
# (this build host has no Mac) — every function under test is pure string
# handling with no macOS-only syscall, which is what makes that possible;
# `available_bytes` and `generate_env_passwords` were written to avoid the
# two real BSD/GNU divergences (`df` column layout is the same on both with
# `-k`; `sed -i` is not, so lib.sh never uses it).
set -Eeuo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PASS=0; FAIL=0

ok()   { PASS=$((PASS+1)); printf '  ok    %s\n' "$1"; }
bad()  { FAIL=$((FAIL+1)); printf '  FAIL  %s\n' "$1"; }
check(){ if [ "$2" = "$3" ]; then ok "$1"; else bad "$1 (want '$3', got '$2')"; fi; }

fresh() {
  TMP="$(mktemp -d)"
  export HOME="$TMP/home"
  unset ASKWELL_DATA_DIR ASKWELL_INSTALL_PREFIX ASKWELL_APP_DIR ASKWELL_BIN_DIR \
        ASKWELL_LAUNCH_AGENTS_DIR ASKWELL_REQUIRED_INSTALL_BYTES
  mkdir -p "$HOME"
  # shellcheck source=./lib.sh
  . "$HERE/lib.sh"
}

fake_path_with() {
  local dir="$TMP/fakebin"
  rm -rf "$dir"; mkdir -p "$dir"
  for cmd in "$@"; do : > "$dir/$cmd"; chmod +x "$dir/$cmd"; done
  echo "$dir"
}

printf 'macos installer\n'

# --- install command ---------------------------------------------------------
fresh
check "names brew as the install command" "$(runtime_install_cmd)" "brew install podman"

# --- version comparison, identical rule to the other two platforms -----------
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

# --- the podman machine -------------------------------------------------------
fresh
fake_podman_dir="$TMP/fakebin"; rm -rf "$fake_podman_dir"; mkdir -p "$fake_podman_dir"
cat > "$fake_podman_dir/podman" <<'EOF'
#!/usr/bin/env bash
if [ "$1" = "machine" ] && [ "$2" = "list" ]; then
  echo "podman-machine-default*  applehv  2 weeks ago  Currently running  4  2GiB  100GiB"
fi
EOF
chmod +x "$fake_podman_dir/podman"
PATH="$fake_podman_dir:$PATH" has_podman_machine && r=0 || r=1
check "a machine in the table is detected" "$r" 0
PATH="$fake_podman_dir:$PATH" podman_machine_running && r=0 || r=1
check "'Currently running' in the table means running" "$r" 0

fresh
fake_podman_dir="$TMP/fakebin"; rm -rf "$fake_podman_dir"; mkdir -p "$fake_podman_dir"
cat > "$fake_podman_dir/podman" <<'EOF'
#!/usr/bin/env bash
if [ "$1" = "machine" ] && [ "$2" = "list" ]; then
  : # no machine at all
fi
EOF
chmod +x "$fake_podman_dir/podman"
PATH="$fake_podman_dir:$PATH" has_podman_machine && r=0 || r=1
check "no rows means no machine" "$r" 1

fresh
fake_podman_dir="$TMP/fakebin"; rm -rf "$fake_podman_dir"; mkdir -p "$fake_podman_dir"
cat > "$fake_podman_dir/podman" <<'EOF'
#!/usr/bin/env bash
if [ "$1" = "machine" ] && [ "$2" = "list" ]; then
  echo "podman-machine-default*  applehv  2 weeks ago  3 hours ago  4  2GiB  100GiB"
fi
EOF
chmod +x "$fake_podman_dir/podman"
PATH="$fake_podman_dir:$PATH" podman_machine_running && r=0 || r=1
check "a stopped machine (no 'Currently running') is not running" "$r" 1

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
check "data dir defaults under Library/Application Support" "$(data_dir_default)" "$HOME/Library/Application Support/Askwell"
ASKWELL_DATA_DIR="/custom/data" out="$(data_dir_default)"
check "data dir honours override" "$out" "/custom/data"

fresh
check "app dir defaults under ~/Applications" "$(app_dir_default)" "$HOME/Applications/Askwell.app"

fresh
check "install prefix nests under the data dir" "$(install_prefix_default)" "$HOME/Library/Application Support/Askwell/app"

# --- previous install state ----------------------------------------------------
fresh
is_previous_install "$TMP/nowhere" && r=0 || r=1
check "no install record means no previous install" "$r" 1

write_install_record "$TMP/data" "0.6.5" "install"
is_previous_install "$TMP/data" && r=0 || r=1
check "a written record is detected as a previous install" "$r" 0
check "the recorded version reads back" "$(previous_install_version "$TMP/data")" "0.6.5"

# --- secrets: same #584 fix as the other two platforms --------------------------
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

sbx_owner_pw="$(grep '^SANDBOX_OWNER_PASSWORD=' "$env_file" | cut -d= -f2)"
askwell_owner_pw="$(grep '^ASKWELL_SANDBOX_OWNER_PASSWORD=' "$env_file" | cut -d= -f2)"
check "SANDBOX_OWNER_PASSWORD and ASKWELL_SANDBOX_OWNER_PASSWORD stay the same credential" "$sbx_owner_pw" "$askwell_owner_pw"

pg_pw="$(grep '^POSTGRES_PASSWORD=' "$env_file" | cut -d= -f2)"
pg_app_pw="$(grep '^POSTGRES_APP_PASSWORD=' "$env_file" | cut -d= -f2)"
pg_ro_pw="$(grep '^POSTGRES_READONLY_PASSWORD=' "$env_file" | cut -d= -f2)"
sbx_pg_pw="$(grep '^SANDBOX_POSTGRES_PASSWORD=' "$env_file" | cut -d= -f2)"
sbx_ro_pw="$(grep '^SANDBOX_READONLY_PASSWORD=' "$env_file" | cut -d= -f2)"
all_pw="$pg_pw $pg_app_pw $pg_ro_pw $sbx_pg_pw $sbx_owner_pw $sbx_ro_pw"
distinct="$(printf '%s\n' $all_pw | sort -u | wc -l | tr -d ' ')"
check "the six stored passwords are all distinct from each other" "$distinct" "6"

fresh
env_file2="$TMP/env-preserves-other-lines"
cat > "$env_file2" <<'EOF'
SOME_OTHER_SETTING=untouched
POSTGRES_PASSWORD=change-me
EOF
generate_env_passwords "$env_file2"
grep -q '^SOME_OTHER_SETTING=untouched$' "$env_file2" && r=0 || r=1
check "a line generate_env_passwords does not own survives untouched" "$r" 0

# --- generated files -------------------------------------------------------------
fresh
out="$(launch_agent_plist_contents "/Users/anna/Applications/Askwell.app/Contents/MacOS/askwell-shell")"
case "$out" in *"<string>/Users/anna/Applications/Askwell.app/Contents/MacOS/askwell-shell</string>"*) ok "plist names the real executable" ;;
               *) bad "plist names the real executable" ;; esac
case "$out" in *"<key>RunAtLoad</key>"*"<true/>"*) ok "plist starts at login" ;;
               *) bad "plist starts at login" ;; esac
case "$out" in *"com.askwell.app"*) ok "plist uses the app's bundle identifier as its label" ;;
               *) bad "plist uses the app's bundle identifier as its label" ;; esac

out="$(quarantine_message "Askwell.app")"
case "$out" in *"Askwell.app"*) ok "quarantine message names the missing file" ;;
               *) bad "quarantine message names the missing file" ;; esac

# --- M7-PACK-DEPLOY-142: stack + inference LaunchAgents ------------------------
out="$(launch_agent_stack_plist_contents "/opt/homebrew/bin/podman" "/data/compose.yaml" "/data/.env" "/data" "/data/logs")"
case "$out" in *"<string>/opt/homebrew/bin/podman</string>"*"<string>compose</string>"*"<string>up</string>"*"<string>--abort-on-container-exit</string>"*)
                 ok "stack agent runs compose in the foreground with an absolute podman path" ;;
               *) bad "stack agent runs compose in the foreground with an absolute podman path" ;; esac
case "$out" in *"<key>KeepAlive</key>"*"<key>SuccessfulExit</key>"*"<false/>"*)
                 ok "stack agent restarts on a non-zero exit" ;;
               *) bad "stack agent restarts on a non-zero exit" ;; esac
case "$out" in *"com.askwell.stack"*) ok "stack agent has its own label, distinct from the app" ;;
               *) bad "stack agent has its own label, distinct from the app" ;; esac

out="$(launch_agent_inference_plist_contents "/data/askwell-inference" "/data/logs")"
case "$out" in *"<string>/data/askwell-inference</string>"*) ok "inference agent execs the real supervisor script" ;;
               *) bad "inference agent execs the real supervisor script" ;; esac
case "$out" in *"com.askwell.inference"*) ok "inference agent has its own label, distinct from the app" ;;
               *) bad "inference agent has its own label, distinct from the app" ;; esac

printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
