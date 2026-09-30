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
  # Never the test runner's own distribution.
  export ASKWELL_OS_RELEASE="$TMP/no-os-release"
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
# M11-FIX-DEPLOY-225: Docker Compose and OpenMP ride in the same command.
check "dnf installs podman, docker-compose and libgomp in one command" \
  "$(runtime_install_cmd dnf docker-compose libgomp)" "dnf install -y podman docker-compose libgomp"
check "apt installs podman, docker-compose-v2 and libgomp1 in one command" \
  "$(runtime_install_cmd apt docker-compose-v2 libgomp1)" \
  "apt-get update && apt-get install -y podman docker-compose-v2 libgomp1"

# --- the OpenMP runtime (M11-FIX-DEPLOY-225) ---------------------------------
fresh
check "dnf's OpenMP package is libgomp" "$(openmp_package dnf)" "libgomp"
check "apt's OpenMP package is libgomp1" "$(openmp_package apt)" "libgomp1"
openmp_package pacman >/dev/null 2>&1 && r=0 || r=1
check "no guessed OpenMP package elsewhere" "$r" 1
LISTING='	libgomp.so.1 (libc6,x86-64) => /lib/x86_64-linux-gnu/libgomp.so.1
	libgcc_s.so.1 (libc6,x86-64) => /lib/x86_64-linux-gnu/libgcc_s.so.1'
openmp_listed "$LISTING" && r=0 || r=1
check "libgomp.so.1 in the loader cache is found" "$r" 0
openmp_listed '	libgcc_s.so.1 (libc6,x86-64) => /lib/x86_64-linux-gnu/libgcc_s.so.1' && r=0 || r=1
check "a loader cache without it is not" "$r" 1
openmp_listed '	libgomp.so.10 (libc6,x86-64) => /opt/libgomp.so.10' && r=0 || r=1
check "a different soname is not mistaken for it" "$r" 1

# The extra packages the first install command carries: only what is missing.
extras() {
  local compose="$1" openmp="$2" os="$3" mgr="$4"
  (
    compose_provider_present() { [ "$compose" = yes ]; }
    openmp_runtime_present() { [ "$openmp" = yes ]; }
    extra_packages "$mgr" "$os" yes
  )
}
check "a new Ubuntu gets docker-compose-v2 and libgomp1" "$(extras no no 'ID=ubuntu' apt)" "docker-compose-v2 libgomp1"
check "a new Fedora gets docker-compose and libgomp" "$(extras no no 'ID=fedora' dnf)" "docker-compose libgomp"
check "a compose already here is left alone" "$(extras yes no 'ID=ubuntu' apt)" "libgomp1"
check "both already here: nothing extra" "$(extras yes yes 'ID=ubuntu' apt)" ""
check "Debian gets no guessed compose package" "$(extras no no 'ID=debian' apt)" "libgomp1"

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

# --- M11-FIX-BE-227: the home folder is the folder Askwell may read ------------
fresh
env_file="$TMP/env-roots-fresh"
printf 'OTHER=kept\nASKWELL_ROOTS_MOUNT=\nLAST=kept\n' > "$env_file"
ensure_roots_mount "$env_file" "/home/anna"
check "an empty roots mount becomes the home folder, in place" "$(tr '\n' '|' < "$env_file")" "OTHER=kept|ASKWELL_ROOTS_MOUNT=/home/anna|LAST=kept|"

fresh
env_file="$TMP/env-roots-upgrade"
printf 'OTHER=kept' > "$env_file"
ensure_roots_mount "$env_file" "/home/anna"
ensure_roots_mount "$env_file" "/home/anna"
check "an older .env without the line gains it once" "$(grep -c '^ASKWELL_ROOTS_MOUNT=/home/anna$' "$env_file")" "1"
check "an upgrade keeps a last line that had no newline" "$(grep -c '^OTHER=kept$' "$env_file")" "1"

fresh
env_file="$TMP/env-roots-mine"
printf 'ASKWELL_ROOTS_MOUNT=/srv/clients\n' > "$env_file"
ensure_roots_mount "$env_file" "/home/anna"
check "a roots mount the user chose is left alone" "$(cat "$env_file")" "ASKWELL_ROOTS_MOUNT=/srv/clients"

fresh
env_file="$TMP/env-roots-spaces"
printf 'ASKWELL_ROOTS_MOUNT=\n' > "$env_file"
ensure_roots_mount "$env_file" "/home/Anna Privé"
check "a home folder with a space and a non-ASCII letter is written as it is" "$(cat "$env_file")" "ASKWELL_ROOTS_MOUNT=/home/Anna Privé"

grep -q 'ensure_roots_mount "$INSTALL_PREFIX/.env" "$HOME"' "$HERE/install.sh" && r=0 || r=1
check "install.sh sets the roots mount to the home folder on every run" "$r" 0
grep -q '^ASKWELL_ROOTS_MOUNT=$' "$HERE/../../.env.example" && r=0 || r=1
check ".env.example leaves the roots mount for the installer to fill" "$r" 0

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
case "$out" in *"Requires=podman.socket"*) ok "stack unit requires Podman's API socket, which docker-compose talks to (#767)" ;;
               *) bad "stack unit requires Podman's API socket, which docker-compose talks to (#767)" ;; esac
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

out="$(systemd_inference_unit_contents "/data/askwell-inference" "/data/.env" "/data")"
case "$out" in *"ExecStart=/data/askwell-inference"*) ok "inference unit execs the real supervisor script" ;;
               *) bad "inference unit execs the real supervisor script" ;; esac
case "$out" in *"After=askwell-stack.service"*"Wants=askwell-stack.service"*)
                 ok "inference unit orders itself after the stack, without requiring it" ;;
               *) bad "inference unit orders itself after the stack, without requiring it" ;; esac
case "$out" in *"StartLimitIntervalSec=300"*"StartLimitBurst=5"*)
                 ok "inference unit caps restarts (StartLimitIntervalSec/StartLimitBurst)" ;;
               *) bad "inference unit caps restarts (StartLimitIntervalSec/StartLimitBurst)" ;; esac
# M11-FIX-DEPLOY-225: the supervisor is handed the install's .env, and not
# through EnvironmentFile=, whose socket path is the containers'.
out="$(systemd_inference_unit_contents "/data/askwell-inference" "/data/.env" "/data")"
case "$out" in *"ExecStart=/data/askwell-inference --env-file /data/.env"*)
                 ok "inference unit passes the install's .env to the supervisor" ;;
               *) bad "inference unit passes the install's .env to the supervisor (got: $out)" ;; esac
case "$out" in *"WorkingDirectory=/data"*) ok "inference unit runs in the app directory" ;;
               *) bad "inference unit runs in the app directory" ;; esac
case "$out" in *"EnvironmentFile="*) bad "inference unit does not load .env as its environment" ;;
               *) ok "inference unit does not load .env as its environment" ;; esac
case "$out" in *"StartLimitIntervalSec=300"*"StartLimitBurst=5"*)
                 ok "inference unit still caps restarts" ;;
               *) bad "inference unit caps restarts (StartLimitIntervalSec/StartLimitBurst)" ;; esac

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
check "an uninstall without --purge-data keeps every volume" "$(ls "$fp/volumes" | wc -l | tr -d ' ')" "$(printf '%s\n' $ASKWELL_VOLUMES | wc -l | tr -d ' ')"
case "$out" in *"database volumes are also left in place"*) ok "an uninstall without --purge-data says the volumes stay" ;;
               *) bad "an uninstall without --purge-data says the volumes stay" ;; esac

# --- compose provider (#767) ------------------------------------------------
fresh
check "reads docker-compose's version" "$(parse_compose_provider_version 'Docker Compose version v5.1.1')" "5.1.1"
check "reads it after podman's provider banner" \
  "$(parse_compose_provider_version "$(printf '>>>> Executing external compose provider "/usr/bin/docker-compose". <<<<\n\nDocker Compose version v2.20.2\n')")" "2.20.2"
check "podman-compose is not read as a supported provider" "$(parse_compose_provider_version 'podman-compose version 1.5.0')" ""
compose_provider_meets_minimum 'Docker Compose version v5.1.1' && r=0 || r=1
check "docker-compose 5.1.1 meets the minimum" "$r" 0
compose_provider_meets_minimum 'Docker Compose version v2.20.0' && r=0 || r=1
check "docker-compose 2.20.0 meets the minimum (--no-attach)" "$r" 0
compose_provider_meets_minimum 'Docker Compose version v2.19.1' && r=0 || r=1
check "docker-compose 2.19 is refused" "$r" 1
compose_provider_meets_minimum 'podman-compose version 1.5.0' && r=0 || r=1
check "podman-compose is refused" "$r" 1
compose_provider_meets_minimum '' && r=0 || r=1
check "no provider at all is refused" "$r" 1
check "dnf installs Fedora's docker-compose" "$(compose_install_cmd dnf)" "dnf install -y docker-compose"
check "dnf adds libgomp to the same command" "$(compose_install_cmd dnf '' libgomp)" "dnf install -y docker-compose libgomp"
check "Ubuntu installs docker-compose-v2, with libgomp1" \
  "$(compose_install_cmd apt 'ID=ubuntu' libgomp1)" "apt-get update && apt-get install -y docker-compose-v2 libgomp1"
check "a distribution built on Ubuntu counts (ID_LIKE)" \
  "$(compose_install_cmd apt "$(printf 'ID=linuxmint\nID_LIKE="ubuntu debian"')")" \
  "apt-get update && apt-get install -y docker-compose-v2"
compose_install_cmd apt 'ID=debian' >/dev/null && r=0 || r=1
check "Debian gets no guessed package name (it has no docker-compose-v2)" "$r" 1
compose_install_cmd apt '' >/dev/null && r=0 || r=1
check "no os-release: apt gets no guessed package name" "$r" 1

# install.sh refuses, by name, before copying anything, when there is no
# provider and no verified way to install one.
fresh; fake_podman
out="$(
  cd "$TMP" && MIGRATE_OUTPUT='podman-compose version 1.5.0\n' PATH="$(fake_path_with):$FP:/usr/bin:/bin" bash -c '
    set -Eeuo pipefail
    . "'"$HERE"'/install.sh"
    detect_pkg_manager() { echo apt; }
    podman() { "$ASKWELL_PODMAN" "$@"; }
    check_compose_provider
    echo REACHED_NEXT_STEP
  ' 2>&1
)" && r=0 || r=1
check "install.sh stops without a supported compose provider" "$r" 1
case "$out" in *REACHED_NEXT_STEP*) bad "no provider never lets the install carry on" ;; *) ok "no provider never lets the install carry on" ;; esac
case "$out" in *"Docker Compose 2.20 or newer"*"Found: podman-compose version 1.5.0"*"Nothing has been copied"*)
                 ok "the refusal names what is needed and what was found" ;;
               *) bad "the refusal names what is needed and what was found (got: $out)" ;; esac

fresh; fake_podman
out="$(
  cd "$TMP" && MIGRATE_OUTPUT='Docker Compose version v5.1.1\n' PATH="$FP:$PATH" bash -c '
    set -Eeuo pipefail
    . "'"$HERE"'/install.sh"
    podman() { "$ASKWELL_PODMAN" "$@"; }
    check_compose_provider
  ' 2>&1
)" && r=0 || r=1
check "install.sh carries on with docker-compose 5.1.1" "$r" 0
case "$out" in *"Compose provider found: Docker Compose version v5.1.1"*) ok "the provider found is named" ;;
               *) bad "the provider found is named (got: $out)" ;; esac

# Podman's API socket: docker-compose cannot reach Podman without it.
socket_systemctl() {
  cat > "$FP/systemctl" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$(dirname "$0")/systemctl.calls"
case "$*" in
  *is-enabled*|*is-active*) [ "${SOCKET_ON:-0}" = 1 ] ;;
  *"enable --now"*) [ "${ENABLE_FAILS:-0}" = 0 ] ;;
  *) exit 0 ;;
esac
SH
  chmod +x "$FP/systemctl"
}
run_ensure_socket() {
  PATH="$FP:$PATH" bash -c '
    set -Eeuo pipefail
    . "'"$HERE"'/install.sh"
    ensure_podman_socket
    echo REACHED_NEXT_STEP
  ' 2>&1
}

fresh; fake_podman; socket_systemctl
out="$(run_ensure_socket)" && r=0 || r=1
check "a disabled socket is enabled and the install carries on" "$r" 0
case "$(cat "$FP/systemctl.calls")" in *"--user enable --now podman.socket"*) ok "the socket is enabled for every login, not only started" ;;
                                       *) bad "the socket is enabled for every login, not only started" ;; esac
case "$out" in *"API socket enabled"*) ok "enabling the socket is reported" ;; *) bad "enabling the socket is reported (got: $out)" ;; esac

fresh; fake_podman; socket_systemctl
out="$(SOCKET_ON=1 run_ensure_socket)" && r=0 || r=1
check "an enabled, listening socket is left alone" "$r" 0
case "$(cat "$FP/systemctl.calls")" in *"enable --now"*) bad "nothing is enabled that already is" ;; *) ok "nothing is enabled that already is" ;; esac
case "$out" in *"API socket enabled"*) bad "no claim to have enabled what already was" ;; *) ok "no claim to have enabled what already was" ;; esac

fresh; fake_podman; socket_systemctl
out="$(ENABLE_FAILS=1 run_ensure_socket)" && r=0 || r=1
check "a socket that cannot be enabled stops the install" "$r" 1
case "$out" in *REACHED_NEXT_STEP*) bad "it never carries on without the socket" ;; *) ok "it never carries on without the socket" ;; esac
case "$out" in *"podman.socket"*"Nothing has been copied"*) ok "the failure names the socket" ;; *) bad "the failure names the socket (got: $out)" ;; esac

# --- an upgrade stops the old version before migrating (#768) --------------
# A systemctl that records what it was asked and answers is-active from
# $STACK_ACTIVE.
recording_systemctl() {
  cat > "$FP/systemctl" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$(dirname "$0")/systemctl.calls"
case "$*" in *is-active*) [ "${STACK_ACTIVE:-0}" = 1 ] ;; *) exit 0 ;; esac
SH
  chmod +x "$FP/systemctl"
}

fresh; fake_podman; recording_systemctl; fp="$FP"
out="$(
  cd "$TMP" && PATH="$fp:$PATH" bash -c '
    set -Eeuo pipefail
    . "'"$HERE"'/install.sh"
    DATA_DIR="'"$TMP"'/data"; INSTALL_PREFIX="/p"
    stop_previous_stack
  ' 2>&1
)" && r=0 || r=1
check "a fresh install has nothing to stop" "$r" 0
check "a fresh install touches no container" "$(cat "$fp/calls" 2>/dev/null)" ""
case "$out" in *"Stopped the running Askwell"*) bad "a fresh install never says it stopped anything" ;;
               *) ok "a fresh install never says it stopped anything" ;; esac

fresh; fake_podman; recording_systemctl; fp="$FP"
write_install_record "$TMP/data" 0.7.0 install
out="$(
  cd "$TMP" && STACK_ACTIVE=1 PATH="$fp:$PATH" bash -c '
    set -Eeuo pipefail
    . "'"$HERE"'/install.sh"
    DATA_DIR="'"$TMP"'/data"; INSTALL_PREFIX="/p"
    stop_previous_stack
  ' 2>&1
)" && r=0 || r=1
check "an upgrade stops the running version" "$r" 0
case "$(cat "$fp/systemctl.calls")" in *"--user stop askwell-stack.service"*) ok "the stack unit is stopped first, so Restart= cannot bring it back" ;;
                                       *) bad "the stack unit is stopped first, so Restart= cannot bring it back" ;; esac
check "then its containers are taken down by the install's own files" "$(cat "$fp/calls")" "compose -f /p/compose.yaml --env-file /p/.env down"
case "$out" in *"Stopped the running Askwell"*) ok "an upgrade says it stopped the old version" ;;
               *) bad "an upgrade says it stopped the old version (got: $out)" ;; esac

fresh; fake_podman; recording_systemctl; fp="$FP"
write_install_record "$TMP/data" 0.7.0 install
out="$(
  cd "$TMP" && MIGRATE_EXIT=125 PATH="$fp:$PATH" bash -c '
    set -Eeuo pipefail
    . "'"$HERE"'/install.sh"
    DATA_DIR="'"$TMP"'/data"; INSTALL_PREFIX="/p"
    stop_previous_stack
    echo REACHED_NEXT_STEP
  ' 2>&1
)" && r=0 || r=1
check "an upgrade that cannot stop the old containers stops" "$r" 1
case "$out" in *REACHED_NEXT_STEP*) bad "it never goes on to migrate under running code" ;; *) ok "it never goes on to migrate under running code" ;; esac
case "$out" in *"Stopped the running Askwell"*) bad "it never claims the old version stopped" ;; *) ok "it never claims the old version stopped" ;; esac

fresh; fake_podman; recording_systemctl; fp="$FP"
PATH="$fp:$PATH" bash -c '
  set -Eeuo pipefail
  . "'"$HERE"'/install.sh"
  INSTALL_PREFIX="'"$TMP"'/p"; SYSTEMD_USER_DIR="'"$TMP"'/units"; mkdir -p "$SYSTEMD_USER_DIR"
  register_stack_and_inference
' >/dev/null 2>&1 && r=0 || r=1
check "registering the stack succeeds" "$r" 0
case "$(cat "$fp/systemctl.calls")" in
  *"--user restart askwell-stack.service"*"--user restart askwell-inference.service"*) ok "the units are restarted, so an upgrade runs the new version" ;;
  *) bad "the units are restarted, so an upgrade runs the new version (got: $(cat "$fp/systemctl.calls"))" ;; esac
case "$(cat "$fp/systemctl.calls")" in *"enable --now"*) bad "no enable --now, a no-op on an active unit" ;; *) ok "no enable --now, a no-op on an active unit" ;; esac

# The order in main: stop, then migrate, then start the new version.
order="$(sed -n '/^main() {/,/^}/p' "$HERE/install.sh" | grep -E '^  (stop_previous_stack|migrate_database|register_stack_and_inference|place_files|check_compose_provider|check_runtime)$' | sed 's/^ *//' | tr '\n' ' ')"
check "main checks the provider, places files, stops, migrates, then starts" "$order" \
  "check_runtime check_compose_provider place_files stop_previous_stack migrate_database register_stack_and_inference "

# --- a plain uninstall keeps the credentials the kept volumes need (#765) --
fresh
check "the kept .env lives in the data directory" "$(kept_env_path /d)" "/d/askwell.env"

fresh; fake_podman; fp="$FP"
for v in $ASKWELL_VOLUMES; do : > "$fp/volumes/$v"; done
prefix="$HOME/.local/share/askwell/app"; mkdir -p "$prefix"
printf 'POSTGRES_PASSWORD=original\n' > "$prefix/.env"
out="$(PATH="$fp:$PATH" bash "$HERE/uninstall.sh" 2>&1)" && r=0 || r=1
kept="$HOME/.local/share/askwell/askwell.env"
check "a plain uninstall succeeds" "$r" 0
[ -d "$prefix" ] && r=1 || r=0
check "a plain uninstall still removes the application files" "$r" 0
check "a plain uninstall keeps the database credentials" "$(cat "$kept" 2>/dev/null)" "POSTGRES_PASSWORD=original"
check "the kept credentials are readable by this account only" "$(stat -c %a "$kept" 2>/dev/null)" "600"
case "$out" in *"Database credentials kept at $kept"*) ok "a plain uninstall says where the credentials are kept" ;;
               *) bad "a plain uninstall says where the credentials are kept (got: $out)" ;; esac

fresh; fake_podman; fp="$FP"
for v in $ASKWELL_VOLUMES; do : > "$fp/volumes/$v"; done
prefix="$HOME/.local/share/askwell/app"; mkdir -p "$prefix"
printf 'POSTGRES_PASSWORD=original\n' > "$prefix/.env"
PATH="$fp:$PATH" bash "$HERE/uninstall.sh" --purge-data --yes >/dev/null 2>&1 && r=0 || r=1
check "a purge succeeds" "$r" 0
[ -e "$HOME/.local/share/askwell/askwell.env" ] && r=1 || r=0
check "a purge keeps no credentials for a database it removed" "$r" 0

# place_files restores them. A release tree made of placeholders, enough for
# place_files to run end to end.
fake_release_tree() {
  local root="$TMP/release"
  mkdir -p "$root/deploy/postgres" "$root/deploy/sandbox" "$root/deploy/redis" \
    "$root/deploy/probe" "$root/deploy/inference" "$root/web/out" "$root/web/src-tauri/target/release"
  cp "$HERE/../../.env.example" "$root/.env.example"
  : > "$root/compose.yaml"; : > "$root/web/out/index.html"
  : > "$root/deploy/probe/askwell-probe"; : > "$root/deploy/inference/askwell-inference"
  : > "$root/web/src-tauri/target/release/askwell-shell"
  echo "$root"
}
run_place_files() {
  bash -c '
    set -Eeuo pipefail
    . "'"$HERE"'/install.sh"
    REPO_ROOT="'"$1"'"; SHELL_BIN="$REPO_ROOT/web/src-tauri/target/release/askwell-shell"
    DATA_DIR="'"$TMP"'/data"; INSTALL_PREFIX="'"$TMP"'/prefix"
    BIN_DIR="'"$TMP"'/bin"; DESKTOP_DIR="'"$TMP"'/desktop"; SYSTEMD_USER_DIR="'"$TMP"'/units"
    place_files
  ' 2>&1
}

fresh; root="$(fake_release_tree)"
mkdir -p "$TMP/data"; printf 'POSTGRES_PASSWORD=original\n' > "$TMP/data/askwell.env"
out="$(run_place_files "$root")" && r=0 || r=1
check "a reinstall over kept volumes places its files" "$r" 0
check "a reinstall uses the kept credentials, not new ones" "$(grep '^POSTGRES_PASSWORD=' "$TMP/prefix/.env")" "POSTGRES_PASSWORD=original"
[ -e "$TMP/data/askwell.env" ] && r=1 || r=0
check "the kept copy is moved, not left behind" "$r" 0
case "$out" in *"Restored the database credentials"*) ok "a reinstall says it restored the credentials" ;;
               *) bad "a reinstall says it restored the credentials (got: $out)" ;; esac
case "$out" in *"Generated database credentials"*) bad "a reinstall with kept credentials never generates new ones" ;;
               *) ok "a reinstall with kept credentials never generates new ones" ;; esac

fresh; root="$(fake_release_tree)"
out="$(run_place_files "$root")" && r=0 || r=1
check "a fresh install places its files" "$r" 0
case "$(grep '^POSTGRES_PASSWORD=' "$TMP/prefix/.env")" in
  "POSTGRES_PASSWORD="|*change-me*) bad "a fresh install generates its own credentials" ;;
  *) ok "a fresh install generates its own credentials" ;; esac

fresh; root="$(fake_release_tree)"
mkdir -p "$TMP/prefix" "$TMP/data"
printf 'POSTGRES_PASSWORD=current\n' > "$TMP/prefix/.env"; printf 'POSTGRES_PASSWORD=stale\n' > "$TMP/data/askwell.env"
run_place_files "$root" >/dev/null && r=0 || r=1
check "an upgrade never replaces the install's own credentials" "$(grep '^POSTGRES_PASSWORD=' "$TMP/prefix/.env")" "POSTGRES_PASSWORD=current"

# M10-FIX-DEPLOY-222: a release's llama.cpp builds go beside askwell-inference,
# where the supervisor looks; a source checkout has none and says so.
fresh; root="$(fake_release_tree)"
out="$(run_place_files "$root")" && r=0 || r=1
check "a tree with no llama.cpp still places its files" "$r" 0
case "$out" in *"No llama.cpp build is bundled here"*) ok "and says llama-server comes from PATH" ;;
               *) bad "and says llama-server comes from PATH (got: $out)" ;; esac
[ -e "$TMP/prefix/llama.cpp" ] && r=1 || r=0
check "and places no llama.cpp directory" "$r" 0

fresh; root="$(fake_release_tree)"
for v in gpu cpu; do
  mkdir -p "$root/deploy/inference/llama.cpp/$v"
  printf '#!/bin/sh\n' > "$root/deploy/inference/llama.cpp/$v/llama-server"
  chmod +x "$root/deploy/inference/llama.cpp/$v/llama-server"
done
mkdir -p "$TMP/prefix/llama.cpp/gpu"; : > "$TMP/prefix/llama.cpp/gpu/libggml-old.so"
out="$(run_place_files "$root")" && r=0 || r=1
check "a release tree's llama.cpp is placed" "$r" 0
[ -x "$TMP/prefix/llama.cpp/gpu/llama-server" ] && [ -x "$TMP/prefix/llama.cpp/cpu/llama-server" ] && r=0 || r=1
check "both builds sit beside askwell-inference, executable" "$r" 0
[ -e "$TMP/prefix/llama.cpp/gpu/libggml-old.so" ] && r=1 || r=0
check "an older build's files do not linger (replaced, not merged)" "$r" 0

# --- one sudo for everything a new machine lacks (M11-FIX-DEPLOY-225) --------
# install.sh's own check_runtime on a new Ubuntu: no Podman, no Compose, no
# libgomp. The package manager and sudo are fakes that record what they were
# asked; PATH holds only them and the basic tools, so the runner's own podman
# is not found.
new_machine_path() {
  local dir="$TMP/newmachine" tool
  rm -rf "$dir"; mkdir -p "$dir"
  for tool in bash sh cat grep id dirname chmod printf head sed; do
    ln -s "$(command -v "$tool")" "$dir/$tool"
  done
  cat > "$dir/sudo" <<'SH'
#!/bin/sh
exec "$@"
SH
  cat > "$dir/apt-get" <<'SH'
#!/bin/sh
printf '%s\n' "$*" >> "$(dirname "$0")/apt.calls"
case "$1" in install) printf '#!/bin/sh\necho podman version 5.0.0\n' > "$(dirname "$0")/podman"; chmod +x "$(dirname "$0")/podman" ;; esac
SH
  chmod +x "$dir/sudo" "$dir/apt-get"
  echo "$dir"
}
fresh
printf 'ID=ubuntu\nVERSION_ID="24.04"\n' > "$TMP/os-release"
np="$(new_machine_path)"
out="$(
  cd "$TMP" && ASKWELL_OS_RELEASE="$TMP/os-release" PATH="$np" bash -c '
    set -Eeuo pipefail
    . "'"$HERE"'/install.sh"
    ASSUME_YES=1
    detect_pkg_manager() { echo apt; }
    compose_provider_present() { return 1; }
    openmp_runtime_present() { return 1; }
    check_runtime
  ' 2>&1
)" && r=0 || r=1
check "a new Ubuntu: check_runtime succeeds" "$r" 0
check "one install command carries podman, docker-compose-v2 and libgomp1" \
  "$(grep '^install' "$np/apt.calls" 2>/dev/null)" "install -y podman docker-compose-v2 libgomp1"
case "$out" in *"sudo apt-get update && apt-get install -y podman docker-compose-v2 libgomp1"*)
                 ok "the one command is shown before it runs" ;;
               *) bad "the one command is shown before it runs (got: $out)" ;; esac

# check_openmp_runtime on a machine that already had Podman and Compose.
fresh
out="$(PATH="$(fake_path_with):/usr/bin:/bin" bash -c '
    set -Eeuo pipefail
    . "'"$HERE"'/install.sh"
    openmp_runtime_present() { return 0; }
    check_openmp_runtime
  ' 2>&1)" && r=0 || r=1
check "OpenMP present: carries on" "$r" 0
case "$out" in *"OpenMP runtime found"*) ok "and says so" ;; *) bad "and says so (got: $out)" ;; esac
out="$(PATH="$(fake_path_with):/usr/bin:/bin" bash -c '
    set -Eeuo pipefail
    . "'"$HERE"'/install.sh"
    detect_pkg_manager() { echo pacman; }
    openmp_runtime_present() { return 1; }
    check_openmp_runtime
    echo REACHED_NEXT_STEP
  ' 2>&1)" && r=0 || r=1
check "OpenMP missing, no known package: install stops" "$r" 1
case "$out" in *REACHED_NEXT_STEP*) bad "and never carries on" ;; *) ok "and never carries on" ;; esac
case "$out" in *"libgomp.so.1"*"Nothing has been copied"*) ok "the refusal names the library" ;;
               *) bad "the refusal names the library (got: $out)" ;; esac

printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
