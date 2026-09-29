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
        ASKWELL_LAUNCH_AGENTS_DIR ASKWELL_REQUIRED_INSTALL_BYTES ASKWELL_PODMAN
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
case "$out" in *"<string>--abort-on-container-exit</string>"*"<string>--no-attach</string>"*"<string>migrate</string>"*)
                 ok "stack agent does not let migrate's successful exit stop the stack" ;;
               *) bad "stack agent does not let migrate's successful exit stop the stack" ;; esac
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

# --- bundled images (M9-REL-DEPLOY-214) --------------------------------------
fresh
check "a source checkout has no bundled images" "$(bundled_image_archives "$TMP")" ""
mkdir -p "$TMP/images"
check "an empty images/ lists nothing" "$(bundled_image_archives "$TMP")" ""
: > "$TMP/images/redis.tar"; : > "$TMP/images/api.tar"; : > "$TMP/images/notes.txt"
check "lists only *.tar, sorted" "$(bundled_image_archives "$TMP" | tr '\n' ' ')" "$TMP/images/api.tar $TMP/images/redis.tar "

# --- database migration and purge (M9-FIX-DEPLOY-200, #698, #700) -----------
# A fake podman that records its arguments and keeps "volumes" as files, so
# these run with no podman and no stack. The real thing — a fresh install,
# an upgrade, a purge and a reinstall — is the manual walkthrough in
# docs/manual-tests/M9-FIX-DEPLOY-200.md (Linux only: this host has no Mac).
#
# Sets FP to its directory, which also holds a launchctl that does nothing:
# a test must never unload an agent on the machine running it.
fake_podman() {
  local dir="$TMP/fakepodman"
  FP="$dir"
  mkdir -p "$dir/volumes"
  printf '#!/bin/sh\nexit 0\n' > "$dir/launchctl"; chmod +x "$dir/launchctl"
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
mkdir -p "$HOME/Library/Application Support/Askwell/models"
out="$(PATH="$fp:$PATH" bash "$HERE/uninstall.sh" --purge-data --yes 2>&1)" && r=0 || r=1
check "uninstall --purge-data succeeds" "$r" 0
check "uninstall --purge-data removes the database volumes" "$(ls "$fp/volumes" | wc -l | tr -d ' ')" "0"
[ -d "$HOME/Library/Application Support/Askwell" ] && r=1 || r=0
check "uninstall --purge-data removes the data directory" "$r" 0
case "$out" in *"Database volumes removed"*"Data directory removed"*"All of Askwell's data has been removed"*)
                 ok "uninstall --purge-data says what it removed" ;;
               *) bad "uninstall --purge-data says what it removed (got: $out)" ;; esac

fresh; fake_podman; fp="$FP"
for v in $ASKWELL_VOLUMES; do : > "$fp/volumes/$v"; done
mkdir -p "$HOME/Library/Application Support/Askwell"
out="$(PATH="$fp:$PATH" STUCK="askwell_postgres-data" bash "$HERE/uninstall.sh" --purge-data --yes 2>&1)" && r=0 || r=1
check "a purge that could not remove a volume exits non-zero" "$r" 1
case "$out" in *"All of Askwell's data has been removed"*) bad "a partial purge never claims everything was removed" ;;
               *) ok "a partial purge never claims everything was removed" ;; esac
case "$out" in *"askwell_postgres-data"*) ok "a partial purge names the volume left behind" ;;
               *) bad "a partial purge names the volume left behind" ;; esac

fresh; fake_podman; fp="$FP"
for v in $ASKWELL_VOLUMES; do : > "$fp/volumes/$v"; done
mkdir -p "$HOME/Library/Application Support/Askwell"
out="$(PATH="$fp:$PATH" bash "$HERE/uninstall.sh" 2>&1)" && r=0 || r=1
check "an uninstall without --purge-data keeps every volume" "$(ls "$fp/volumes" | wc -l | tr -d ' ')" "4"
case "$out" in *"database volumes are also left in place"*) ok "an uninstall without --purge-data says the volumes stay" ;;
               *) bad "an uninstall without --purge-data says the volumes stay" ;; esac

# --- compose provider (#767) ------------------------------------------------
fresh
check "reads docker-compose's version" "$(parse_compose_provider_version 'Docker Compose version v5.1.1')" "5.1.1"
check "podman-compose is not read as a supported provider" "$(parse_compose_provider_version 'podman-compose version 1.5.0')" ""
compose_provider_meets_minimum 'Docker Compose version v2.19.1' && r=0 || r=1
check "docker-compose 2.19 is refused" "$r" 1
compose_provider_meets_minimum 'Docker Compose version v2.20.0' && r=0 || r=1
check "docker-compose 2.20.0 meets the minimum" "$r" 0
check "Homebrew installs docker-compose" "$(compose_install_cmd)" "brew install docker-compose"

fresh; fake_podman
out="$(
  cd "$TMP" && MIGRATE_OUTPUT='podman-compose version 1.5.0\n' PATH="$FP:/usr/bin:/bin" bash -c '
    set -Eeuo pipefail
    . "'"$HERE"'/install.sh"
    podman() { "$ASKWELL_PODMAN" "$@"; }
    command() { [ "$2" = brew ] && return 1; builtin command "$@"; }
    check_compose_provider
    echo REACHED_NEXT_STEP
  ' 2>&1
)" && r=0 || r=1
check "install.sh stops without a supported compose provider" "$r" 1
case "$out" in *REACHED_NEXT_STEP*) bad "no provider never lets the install carry on" ;; *) ok "no provider never lets the install carry on" ;; esac
case "$out" in *"Docker Compose 2.20 or newer"*"Found: podman-compose version 1.5.0"*"brew install docker-compose"*)
                 ok "the refusal names what is needed, what was found and the install command" ;;
               *) bad "the refusal names what is needed, what was found and the install command (got: $out)" ;; esac

# --- an upgrade stops the old version before migrating (#768) --------------
fresh; fake_podman; fp="$FP"
printf '#!/bin/sh\nprintf "%%s\\n" "$*" >> "$(dirname "$0")/launchctl.calls"\n' > "$fp/launchctl"; chmod +x "$fp/launchctl"
out="$(
  cd "$TMP" && PATH="$fp:$PATH" bash -c '
    set -Eeuo pipefail
    . "'"$HERE"'/install.sh"
    DATA_DIR="'"$TMP"'/data"; INSTALL_PREFIX="/p"; LAUNCH_AGENTS_DIR="/la"
    stop_previous_stack
  ' 2>&1
)" && r=0 || r=1
check "a fresh install has nothing to stop" "$r" 0
check "a fresh install touches no container" "$(cat "$fp/calls" 2>/dev/null)" ""

fresh; fake_podman; fp="$FP"
printf '#!/bin/sh\nprintf "%%s\\n" "$*" >> "$(dirname "$0")/launchctl.calls"\n' > "$fp/launchctl"; chmod +x "$fp/launchctl"
write_install_record "$TMP/data" 0.7.0 install
out="$(
  cd "$TMP" && PATH="$fp:$PATH" bash -c '
    set -Eeuo pipefail
    . "'"$HERE"'/install.sh"
    DATA_DIR="'"$TMP"'/data"; INSTALL_PREFIX="/p"; LAUNCH_AGENTS_DIR="/la"
    stop_previous_stack
  ' 2>&1
)" && r=0 || r=1
check "an upgrade stops the running version" "$r" 0
check "the stack LaunchAgent is unloaded first, so KeepAlive cannot restart it" "$(cat "$fp/launchctl.calls")" "unload /la/com.askwell.stack.plist"
check "then its containers are taken down by the install's own files" "$(cat "$fp/calls")" "compose -f /p/compose.yaml --env-file /p/.env down"
case "$out" in *"Stopped the running Askwell"*) ok "an upgrade says it stopped the old version" ;;
               *) bad "an upgrade says it stopped the old version (got: $out)" ;; esac

fresh; fake_podman; fp="$FP"
write_install_record "$TMP/data" 0.7.0 install
out="$(
  cd "$TMP" && MIGRATE_EXIT=125 PATH="$fp:$PATH" bash -c '
    set -Eeuo pipefail
    . "'"$HERE"'/install.sh"
    DATA_DIR="'"$TMP"'/data"; INSTALL_PREFIX="/p"; LAUNCH_AGENTS_DIR="/la"
    stop_previous_stack
    echo REACHED_NEXT_STEP
  ' 2>&1
)" && r=0 || r=1
check "an upgrade that cannot stop the old containers stops" "$r" 1
case "$out" in *REACHED_NEXT_STEP*) bad "it never goes on to migrate under running code" ;; *) ok "it never goes on to migrate under running code" ;; esac

order="$(sed -n '/^main() {/,/^}/p' "$HERE/install.sh" | grep -E '^  (stop_previous_stack|migrate_database|register_stack_and_inference|place_files|check_compose_provider|check_runtime)$' | sed 's/^ *//' | tr '\n' ' ')"
check "main checks the provider, places files, stops, migrates, then starts" "$order" \
  "check_runtime check_compose_provider place_files stop_previous_stack migrate_database register_stack_and_inference "

# --- a plain uninstall keeps the credentials the kept volumes need (#765) --
fresh; fake_podman; fp="$FP"
for v in $ASKWELL_VOLUMES; do : > "$fp/volumes/$v"; done
data="$HOME/Library/Application Support/Askwell"; prefix="$data/app"; mkdir -p "$prefix"
printf 'POSTGRES_PASSWORD=original\n' > "$prefix/.env"
out="$(PATH="$fp:$PATH" bash "$HERE/uninstall.sh" 2>&1)" && r=0 || r=1
check "a plain uninstall succeeds" "$r" 0
check "a plain uninstall keeps the database credentials" "$(cat "$data/askwell.env" 2>/dev/null)" "POSTGRES_PASSWORD=original"
[ -n "$(find "$data/askwell.env" -perm 600 2>/dev/null)" ] && r=0 || r=1
check "the kept credentials are readable by this account only" "$r" 0

fresh; fake_podman; fp="$FP"
for v in $ASKWELL_VOLUMES; do : > "$fp/volumes/$v"; done
data="$HOME/Library/Application Support/Askwell"; prefix="$data/app"; mkdir -p "$prefix"
printf 'POSTGRES_PASSWORD=original\n' > "$prefix/.env"
PATH="$fp:$PATH" bash "$HERE/uninstall.sh" --purge-data --yes >/dev/null 2>&1 && r=0 || r=1
[ -e "$data/askwell.env" ] && r=1 || r=0
check "a purge keeps no credentials for a database it removed" "$r" 0

# M10-FIX-DEPLOY-222: the release's Metal build goes beside askwell-inference.
run_place_llama_cpp() {
  bash -c '
    set -Eeuo pipefail
    . "'"$HERE"'/install.sh"
    REPO_ROOT="'"$1"'"; INSTALL_PREFIX="'"$TMP"'/prefix"
    mkdir -p "$INSTALL_PREFIX"
    place_llama_cpp
  ' 2>&1
}
fresh
mkdir -p "$TMP/release/deploy/inference"
out="$(run_place_llama_cpp "$TMP/release")" && r=0 || r=1
check "a source checkout with no llama.cpp carries on" "$r" 0
case "$out" in *"No llama.cpp build is bundled here"*) ok "and says llama-server comes from PATH" ;;
               *) bad "and says llama-server comes from PATH (got: $out)" ;; esac
mkdir -p "$TMP/release/deploy/inference/llama.cpp/gpu" "$TMP/prefix/llama.cpp/gpu"
printf '#!/bin/sh\n' > "$TMP/release/deploy/inference/llama.cpp/gpu/llama-server"
chmod +x "$TMP/release/deploy/inference/llama.cpp/gpu/llama-server"
: > "$TMP/prefix/llama.cpp/gpu/libggml-old.dylib"
run_place_llama_cpp "$TMP/release" >/dev/null && r=0 || r=1
check "a release tree's Metal build is placed" "$r" 0
[ -x "$TMP/prefix/llama.cpp/gpu/llama-server" ] && r=0 || r=1
check "beside askwell-inference, executable" "$r" 0
[ -e "$TMP/prefix/llama.cpp/gpu/libggml-old.dylib" ] && r=1 || r=0
check "an older build's files do not linger" "$r" 0

printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
