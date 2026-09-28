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
        ASKWELL_REQUIRED_INSTALL_BYTES ASKWELL_PODMAN
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

# --- M8-FIX-SEC-177: Redis passwords, fresh and on upgrade -----------------------
fresh
env_file="$TMP/env-redis-fresh"
cat > "$env_file" <<'EOF'
REDIS_API_PASSWORD=change-me-redis-api
REDIS_WORKER_PASSWORD=change-me-redis-worker
REDIS_PROXY_PASSWORD=change-me-redis-proxy
OTHER=kept
EOF
ensure_redis_passwords "$env_file"
grep -q 'change-me' "$env_file" && r=0 || r=1
check "a fresh .env keeps no Redis placeholder" "$r" 1
api_pw="$(grep '^REDIS_API_PASSWORD=' "$env_file" | cut -d= -f2)"
worker_pw="$(grep '^REDIS_WORKER_PASSWORD=' "$env_file" | cut -d= -f2)"
proxy_pw="$(grep '^REDIS_PROXY_PASSWORD=' "$env_file" | cut -d= -f2)"
check "a generated Redis password is 64 hex characters" "${#api_pw}" "64"
distinct="$(printf '%s\n' "$api_pw" "$worker_pw" "$proxy_pw" | sort -u | wc -l | tr -d ' ')"
check "the three Redis passwords are distinct" "$distinct" "3"
check "other lines survive" "$(grep -c '^OTHER=kept$' "$env_file")" "1"
check "each Redis password appears once" "$(grep -c '^REDIS_' "$env_file")" "3"

# An install from before Redis had users: none of the three lines exist, and
# Compose would refuse to start. The upgrade must add them, not refuse.
fresh
env_file="$TMP/env-redis-upgrade"
printf 'POSTGRES_PASSWORD=already-real\nOTHER=kept' > "$env_file"
ensure_redis_passwords "$env_file"
for name in REDIS_API_PASSWORD REDIS_WORKER_PASSWORD REDIS_PROXY_PASSWORD; do
  value="$(grep "^$name=" "$env_file" | cut -d= -f2)"
  check "an upgrade generates $name" "${#value}" "64"
done
check "an upgrade leaves the database password alone" "$(grep '^POSTGRES_PASSWORD=' "$env_file")" "POSTGRES_PASSWORD=already-real"
check "an upgrade keeps a last line that had no newline" "$(grep -c '^OTHER=kept$' "$env_file")" "1"

# A password someone already has is theirs: a second install run changes nothing.
before="$(cat "$env_file")"
ensure_redis_passwords "$env_file"
check "a second run changes no existing Redis password" "$(cat "$env_file")" "$before"

# An empty value is as unusable as a missing one.
fresh
env_file="$TMP/env-redis-empty"
printf 'REDIS_API_PASSWORD=\nREDIS_WORKER_PASSWORD=mine\nREDIS_PROXY_PASSWORD=change-me-redis-proxy\n' > "$env_file"
ensure_redis_passwords "$env_file"
value="$(grep '^REDIS_API_PASSWORD=' "$env_file" | cut -d= -f2)"
check "an empty Redis password is generated" "${#value}" "64"
check "a real Redis password is kept" "$(grep '^REDIS_WORKER_PASSWORD=' "$env_file")" "REDIS_WORKER_PASSWORD=mine"
value="$(grep '^REDIS_PROXY_PASSWORD=' "$env_file" | cut -d= -f2)"
check "a placeholder Redis password is generated" "${#value}" "64"

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
case "$out" in *"up --abort-on-container-exit --no-attach migrate"*)
                 ok "stack unit does not let migrate's successful exit stop the stack" ;;
               *) bad "stack unit does not let migrate's successful exit stop the stack" ;; esac
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

# --- database migration and purge (M9-FIX-DEPLOY-200, #698, #700) -----------
# A fake podman that records its arguments and keeps "volumes" as files, so
# these run with no podman and no stack. The real thing — a fresh install,
# an upgrade, a purge and a reinstall — is the manual walkthrough in
# docs/manual-tests/M9-FIX-DEPLOY-200.md.
#
# Sets FP to its directory, which also holds a systemctl that does nothing:
# uninstall.sh talks to the real user manager otherwise, and a test must
# never disable a unit on the machine running it.
fake_podman() {
  local dir="$TMP/fakepodman"
  FP="$dir"
  mkdir -p "$dir/volumes"
  printf '#!/bin/sh\nexit 0\n' > "$dir/systemctl"; chmod +x "$dir/systemctl"
  cat > "$dir/podman" <<'SH'
#!/usr/bin/env bash
dir="$(dirname "$0")"
printf '%s\n' "$*" >> "$dir/calls"
case "$1 $2" in
  "volume exists") [ -e "$dir/volumes/$3" ] ;;
  "volume rm") v="$4"; case " ${STUCK:-} " in *" $v "*) exit 1 ;; esac; rm -f "$dir/volumes/$v" ;;
  compose*) printf '%b' "${MIGRATE_OUTPUT:-}"; exit "${MIGRATE_EXIT:-0}" ;;
  *) exit 99 ;;
esac
SH
  chmod +x "$dir/podman"
  export ASKWELL_PODMAN="$dir/podman"
}

fresh; fake_podman; fp="$FP"
log="$TMP/data/logs/migrate.log"
MIGRATE_OUTPUT='INFO  [alembic.runtime.migration] Running upgrade  -> a1, first\nINFO  [alembic.runtime.migration] Running upgrade a1 -> b2, second\n' \
  run_database_migration /p/compose.yaml /p/.env "$log" && r=0 || r=1
check "a successful migration returns success" "$r" 0
check "the migration runs compose's own migrate service against the install's files" \
  "$(cat "$fp/calls")" "compose -f /p/compose.yaml --env-file /p/.env run --rm migrate"
check "its output is kept in the log, creating the logs directory" "$(grep -c 'Running upgrade' "$log")" "2"
check "a fresh schema reports each migration applied" "$(migrations_applied "$log")" "2"

fresh; fake_podman
log="$TMP/migrate.log"
MIGRATE_OUTPUT='INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.\n' \
  run_database_migration /p/compose.yaml /p/.env "$log" && r=0 || r=1
check "an upgrade with nothing pending is a success, not an error" "$r" 0
check "an upgrade with nothing pending reports zero applied" "$(migrations_applied "$log")" "0"

fresh; fake_podman
log="$TMP/migrate.log"
MIGRATE_EXIT=1 MIGRATE_OUTPUT='sqlalchemy.exc.ProgrammingError: boom\n' \
  run_database_migration /p/compose.yaml /p/.env "$log" && r=0 || r=1
check "a failed migration is a failure the installer sees" "$r" 1
check "a failed migration's error is in the log" "$(grep -c 'boom' "$log")" "1"

# install.sh must act on that failure: stop, and never reach the steps that
# say Askwell is installed. Run the real function with the real script's
# definitions, the install steps after it replaced by markers.
fresh; fake_podman
out="$(
  cd "$TMP" && MIGRATE_EXIT=1 MIGRATE_OUTPUT='boom: relation already exists\n' bash -c '
    set -Eeuo pipefail
    . "'"$HERE"'/install.sh"
    DATA_DIR="'"$TMP"'/data"; INSTALL_PREFIX="/p"
    migrate_database
    echo REACHED_NEXT_STEP
  ' 2>&1
)" && r=0 || r=1
check "install.sh stops when the migration fails" "$r" 1
case "$out" in *REACHED_NEXT_STEP*) bad "a failed migration never lets the install carry on" ;;
               *) ok "a failed migration never lets the install carry on" ;; esac
case "$out" in *"database migration"*"failed"*"not complete"*) ok "the failure is named, and the install says it is not complete" ;;
               *) bad "the failure is named, and the install says it is not complete (got: $out)" ;; esac
case "$out" in *"boom: relation already exists"*) ok "the migration's own error is shown" ;;
               *) bad "the migration's own error is shown" ;; esac
case "$out" in *"schema already up to date"*|*"schema up to date"*) bad "a failed migration never reports the schema as up to date" ;;
               *) ok "a failed migration never reports the schema as up to date" ;; esac

fresh; fake_podman
out="$(
  cd "$TMP" && MIGRATE_OUTPUT='' bash -c '
    set -Eeuo pipefail
    . "'"$HERE"'/install.sh"
    DATA_DIR="'"$TMP"'/data"; INSTALL_PREFIX="/p"
    migrate_database
  ' 2>&1
)" && r=0 || r=1
check "install.sh carries on when nothing is pending" "$r" 0
case "$out" in *"already up to date"*) ok "nothing pending is reported as already up to date" ;;
               *) bad "nothing pending is reported as already up to date (got: $out)" ;; esac

fresh
compose_volumes="$(sed -n '/^volumes:/,$p' "$HERE/../../compose.yaml" | grep -E '^  [a-z][a-z-]*:' | sed -E 's/^  ([a-z-]+):.*/askwell_\1/' | sort | tr '\n' ' ')"
lib_volumes="$(printf '%s\n' $ASKWELL_VOLUMES | sort | tr '\n' ' ')"
check "ASKWELL_VOLUMES names every volume compose.yaml declares" "$lib_volumes" "$compose_volumes"
case "$(sed -n '/^name:/p' "$HERE/../../compose.yaml")" in
  "name: askwell") ok "compose's project name is the askwell_ prefix the volume names assume" ;;
  *) bad "compose's project name is the askwell_ prefix the volume names assume" ;; esac

fresh; fake_podman; fp="$FP"
for v in $ASKWELL_VOLUMES; do : > "$fp/volumes/$v"; done
purge_stack_volumes > "$TMP/left" && r=0 || r=1
check "purge removes every volume and reports success" "$r" 0
check "no volume survives a purge" "$(ls "$fp/volumes" | wc -l | tr -d ' ')" "0"

fresh; fake_podman; fp="$FP"
purge_stack_volumes > "$TMP/left" && r=0 || r=1
check "purging volumes that were never created is not an error" "$r" 0

fresh; fake_podman; fp="$FP"
for v in $ASKWELL_VOLUMES; do : > "$fp/volumes/$v"; done
STUCK="askwell_postgres-data" purge_stack_volumes > "$TMP/left" && r=0 || r=1
check "a volume that will not go makes the purge fail" "$r" 1
check "the volume that will not go is named" "$(cat "$TMP/left")" "askwell_postgres-data"
check "the others are still removed" "$(ls "$fp/volumes")" "askwell_postgres-data"

# uninstall.sh --purge-data, end to end against the fake podman and a
# throwaway HOME: the data directory and the volumes both go, and it says so.
fresh; fake_podman; fp="$FP"
for v in $ASKWELL_VOLUMES; do : > "$fp/volumes/$v"; done
mkdir -p "$HOME/.local/share/askwell/models"
out="$(PATH="$fp:$PATH" bash "$HERE/uninstall.sh" --purge-data --yes 2>&1)" && r=0 || r=1
check "uninstall --purge-data succeeds" "$r" 0
check "uninstall --purge-data removes the database volumes" "$(ls "$fp/volumes" | wc -l | tr -d ' ')" "0"
[ -d "$HOME/.local/share/askwell" ] && r=1 || r=0
check "uninstall --purge-data removes the data directory" "$r" 0
case "$out" in *"Database volumes removed"*"Data directory removed"*"All of Askwell's data has been removed"*)
                 ok "uninstall --purge-data says what it removed" ;;
               *) bad "uninstall --purge-data says what it removed (got: $out)" ;; esac

fresh; fake_podman; fp="$FP"
for v in $ASKWELL_VOLUMES; do : > "$fp/volumes/$v"; done
mkdir -p "$HOME/.local/share/askwell"
out="$(PATH="$fp:$PATH" STUCK="askwell_postgres-data" bash "$HERE/uninstall.sh" --purge-data --yes 2>&1)" && r=0 || r=1
check "a purge that could not remove a volume exits non-zero" "$r" 1
case "$out" in *"All of Askwell's data has been removed"*) bad "a partial purge never claims everything was removed" ;;
               *) ok "a partial purge never claims everything was removed" ;; esac
case "$out" in *"askwell_postgres-data"*) ok "a partial purge names the volume left behind" ;;
               *) bad "a partial purge names the volume left behind" ;; esac

fresh; fake_podman; fp="$FP"
for v in $ASKWELL_VOLUMES; do : > "$fp/volumes/$v"; done
mkdir -p "$HOME/.local/share/askwell"
out="$(PATH="$fp:$PATH" bash "$HERE/uninstall.sh" 2>&1)" && r=0 || r=1
check "an uninstall without --purge-data keeps every volume" "$(ls "$fp/volumes" | wc -l | tr -d ' ')" "4"
case "$out" in *"database volumes are also left in place"*) ok "an uninstall without --purge-data says the volumes stay" ;;
               *) bad "an uninstall without --purge-data says the volumes stay" ;; esac

printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
