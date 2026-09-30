#!/usr/bin/env bash
# Pure(ish) logic for the Linux installer (M7-PACK-DEPLOY-139). Sourced, never
# forked, by install.sh and uninstall.sh, and by install.test.sh in isolation.
#
# Every function here either returns a value on stdout or a status code with
# no side effect beyond what its name says — that is what makes them testable
# without a real machine to install onto. install.sh does the actual copying,
# process management and privilege escalation; this file decides *what* it
# should do. generate_env_passwords is the one function here with a real side
# effect (it rewrites a file) rather than only stdout, because the thing it
# tests — "does the written .env still have every change-me placeholder" — has
# no other observable shape.
#
# Targets bash 3.2 conventions (see scripts/guards.sh) even though Linux is
# the only platform this ships on today, so a shared style holds across
# deploy/*.

: "${ASKWELL_MIN_PODMAN_VERSION:=4.3}"
# `podman compose` is only a front end for an external provider (issue #767).
# The stack relies on docker-compose behaviour — `--no-attach` on the session
# units, `service_completed_successfully` for the `migrate` service — and
# `--no-attach` arrived in Docker Compose 2.20.
: "${ASKWELL_MIN_COMPOSE_VERSION:=2.20}"

# ---------------------------------------------------------------- messaging

askwell_die() { printf 'askwell-install: %s\n' "$*" >&2; return 1; }
askwell_say() { printf '%s\n' "$*"; }

# ---------------------------------------------------------------- runtime

# Which package manager owns this machine. Order matters only in that a
# machine never has two of these as the primary manager, so first match wins.
detect_pkg_manager() {
  if command -v dnf >/dev/null 2>&1; then echo dnf; return 0; fi
  if command -v apt-get >/dev/null 2>&1; then echo apt; return 0; fi
  if command -v zypper >/dev/null 2>&1; then echo zypper; return 0; fi
  if command -v pacman >/dev/null 2>&1; then echo pacman; return 0; fi
  echo unknown
  return 1
}

# The command that installs Podman on a given package manager, as a single
# string install.sh passes to `sh -c`. Never invoked from here — this only
# names the command so it can be shown to the user and unit-tested without
# actually installing anything.
#
# Further package names after the manager are installed in the same command,
# so one `sudo` confirmation covers Podman, Docker Compose and the OpenMP
# runtime together (M11-FIX-DEPLOY-225).
runtime_install_cmd() {
  local mgr="$1"
  shift
  pkg_install_cmd "$mgr" podman "$@"
}

# The command that installs the named packages with a given manager.
pkg_install_cmd() {
  local mgr="$1"
  shift
  case "$mgr" in
    dnf) echo "dnf install -y $*" ;;
    apt) echo "apt-get update && apt-get install -y $*" ;;
    zypper) echo "zypper install -y $*" ;;
    pacman) echo "pacman -Sy --noconfirm $*" ;;
    *) return 1 ;;
  esac
}

# /etc/os-release's text, or nothing. ASKWELL_OS_RELEASE is for tests.
os_release_text() {
  cat "${ASKWELL_OS_RELEASE:-/etc/os-release}" 2>/dev/null || true
}

# Whether /etc/os-release names Ubuntu or a distribution built on it (Mint,
# Pop!_OS and the like say so in ID_LIKE). Takes the file's text so tests
# need no Ubuntu. Debian itself has no `docker-compose-v2` in any suite
# (packages.debian.org, 2026-09-30), so apt alone does not settle the name.
is_ubuntu_family() {
  printf '%s\n' "$1" | grep -qE '^(ID|ID_LIKE)="?([a-z]+ )*ubuntu( [a-z]+)*"?$'
}

# Whether this process can reach root, one way or another. Deliberately does
# NOT use `sudo -n true`: that only ever succeeds for passwordless sudo
# (cached credential or a NOPASSWD rule), so a normal desktop user — sudo
# configured to prompt, the default on Fedora/Ubuntu — was told they had no
# administrative rights at all when they simply hadn't been asked for a
# password yet (issue #503). The real source of truth for whether sudo will
# grant access is sudo itself, invoked where it can prompt; this function only
# checks that the *door exists* to knock on. `install.sh` runs the privileged
# command directly through `sudo`, letting sudo prompt normally or refuse with
# its own honest message ("not in the sudoers file") if it must.
have_admin_path() {
  [ "$(id -u)" -eq 0 ] && return 0
  command -v sudo >/dev/null 2>&1
}

# ---------------------------------------------------------------- versions

# Compares two dotted version strings a and b. Echoes -1, 0 or 1 for a<b,
# a==b, a>b. Missing components compare as 0, so "5" == "5.0.0".
version_compare() {
  local a="$1" b="$2"
  local IFS=.
  # shellcheck disable=SC2206
  local -a av=($a) bv=($b)
  local i n
  n=${#av[@]}
  [ ${#bv[@]} -gt "$n" ] && n=${#bv[@]}
  i=0
  while [ "$i" -lt "$n" ]; do
    local x="${av[$i]:-0}" y="${bv[$i]:-0}"
    x=$((10#${x:-0})); y=$((10#${y:-0}))
    if [ "$x" -gt "$y" ]; then echo 1; return 0; fi
    if [ "$x" -lt "$y" ]; then echo -1; return 0; fi
    i=$((i + 1))
  done
  echo 0
}

version_ge() {
  [ "$(version_compare "$1" "$2")" != "-1" ]
}

# Parses `podman --version`'s "podman version 4.9.4" into "4.9.4". Accepts the
# raw output as an argument so tests never have to have podman installed.
parse_podman_version() {
  printf '%s\n' "$1" | grep -oE '[0-9]+(\.[0-9]+){1,2}' | head -n1
}

podman_meets_minimum() {
  local reported parsed
  reported="$1"
  parsed="$(parse_podman_version "$reported")"
  [ -n "$parsed" ] || return 1
  version_ge "$parsed" "$ASKWELL_MIN_PODMAN_VERSION"
}

# ---------------------------------------------------------------- compose provider

# Parses `podman compose version`'s "Docker Compose version v5.1.1" into
# "5.1.1". Prints nothing for any other provider (podman-compose says
# "podman-compose version …"), because only docker-compose is verified with
# this stack (issue #767). Takes the raw output so tests need no podman.
parse_compose_provider_version() {
  printf '%s\n' "$1" | sed -nE 's/^Docker Compose version v?([0-9]+(\.[0-9]+){1,2}).*/\1/p' | head -n1
}

compose_provider_meets_minimum() {
  local parsed
  parsed="$(parse_compose_provider_version "$1")"
  [ -n "$parsed" ] || return 1
  version_ge "$parsed" "$ASKWELL_MIN_COMPOSE_VERSION"
}

# The docker-compose package, where it has been checked against the
# distribution's own repository: Fedora's `docker-compose` (5.5.1 on
# 2026-09-28), and Ubuntu's `docker-compose-v2` (2.40.3 in 22.04, 24.04 and
# 26.04 updates, 2026-09-30), which `podman compose` finds as a Docker CLI
# plugin. Elsewhere the name or its version differs by release — Debian's
# `docker-compose` was the old 1.x line for years and it has no
# `docker-compose-v2` — so the installer names the upstream instructions
# instead of guessing. The second argument is /etc/os-release's text.
compose_package() {
  case "$1" in
    dnf) echo docker-compose ;;
    apt) is_ubuntu_family "$2" && echo docker-compose-v2 ;;
    *) return 1 ;;
  esac
}

# The command that installs docker-compose, and any further packages named
# after the os-release text, in one go.
compose_install_cmd() {
  local mgr="$1" os_release="${2:-}" package
  shift
  [ "$#" -gt 0 ] && shift
  package="$(compose_package "$mgr" "$os_release")" || return 1
  pkg_install_cmd "$mgr" "$package" "$@"
}

# Whether some docker-compose is already on this machine, asked without
# Podman, which the runtime step may not have installed yet: the standalone
# binary, or the CLI plugin in any directory Docker's own documentation
# names. Installing Ubuntu's `docker-compose-v2` over Docker's own
# `docker-compose-plugin` would conflict, so a present one is left alone;
# `check_compose_provider` still checks its version.
compose_provider_present() {
  command -v docker-compose >/dev/null 2>&1 && return 0
  local dir
  for dir in /usr/libexec/docker/cli-plugins /usr/lib/docker/cli-plugins \
             /usr/local/lib/docker/cli-plugins "$HOME/.docker/cli-plugins"; do
    [ -x "$dir/docker-compose" ] && return 0
  done
  return 1
}

# ---------------------------------------------------------------- OpenMP runtime

# llama.cpp's Linux builds link libgomp.so.1, which a minimal install does
# not have: on a clean Ubuntu 24.04 every bundled llama-server stopped with
# "libgomp.so.1: cannot open shared object file" (M11-FIX-DEPLOY-225). The
# package that holds it, where checked: Debian and Ubuntu's `libgomp1`,
# Fedora's `libgomp`.
openmp_package() {
  case "$1" in
    dnf) echo libgomp ;;
    apt) echo libgomp1 ;;
    *) return 1 ;;
  esac
}

# Whether `ldconfig -p`'s listing (passed as text, so tests need no loader
# cache) has libgomp.so.1.
openmp_listed() {
  printf '%s\n' "$1" | grep -qE '^[[:space:]]*libgomp\.so\.1[[:space:]]'
}

# The dynamic loader's cache. ldconfig lives in /sbin, which is not on a
# normal account's PATH on Debian.
ldconfig_listing() {
  local ldconfig
  for ldconfig in "$(command -v ldconfig 2>/dev/null)" /sbin/ldconfig /usr/sbin/ldconfig; do
    [ -n "$ldconfig" ] && [ -x "$ldconfig" ] && { "$ldconfig" -p 2>/dev/null; return 0; }
  done
  return 1
}

openmp_runtime_present() {
  openmp_listed "$(ldconfig_listing)"
}

# The packages the runtime and compose steps add to their own install
# command, so the person confirms one `sudo` rather than three: Docker
# Compose unless one is already here, and OpenMP unless it is. Each only
# where its name is known for this manager.
extra_packages() {
  local mgr="$1" os_release="$2" with_compose="$3" package
  local -a packages=()
  if [ "$with_compose" = yes ] && ! compose_provider_present \
    && package="$(compose_package "$mgr" "$os_release")"; then
    packages+=("$package")
  fi
  if ! openmp_runtime_present && package="$(openmp_package "$mgr")"; then
    packages+=("$package")
  fi
  echo "${packages[*]}"
}

# ---------------------------------------------------------------- disk space

# Bytes required for one profile's images, native binaries and working room.
# Deliberately a named constant rather than a measurement of the bundle: the
# bundle for a given profile is a fixed, known size at release time, and
# checking "does this machine have room" must happen before anything is
# copied, not discovered mid-copy (AGENTS.md edge case: "insufficient disk —
# refused before copying, naming the space needed").
required_install_bytes() {
  echo "${ASKWELL_REQUIRED_INSTALL_BYTES:-8000000000}"
}

# Available bytes on the filesystem holding `path`, via `df -B1`'s POSIX
# output. `path`'s parent must exist even if `path` itself does not yet.
available_bytes() {
  local path="$1"
  local probe="$path"
  while [ ! -d "$probe" ] && [ "$probe" != "/" ]; do
    probe="$(dirname "$probe")"
  done
  df -B1 --output=avail "$probe" 2>/dev/null | tail -n1 | tr -d ' '
}

human_bytes() {
  local bytes="$1"
  awk -v b="$bytes" 'BEGIN {
    split("B KB MB GB TB", units, " ")
    u = 1
    while (b >= 1024 && u < 5) { b /= 1024; u++ }
    printf "%.1f %s", b, units[u]
  }'
}

# ---------------------------------------------------------------- bundled images

# The container images a release artefact carries (M9-REL-DEPLOY-214), one
# path per line, sorted. A release saves every image compose.yaml names into
# `images/`, so the installer loads them instead of building from source it
# does not ship or pulling from a registry. A source checkout has no
# `images/` and prints nothing: its images are the ones already built on
# this machine.
bundled_image_archives() {
  local root="$1" f
  [ -d "$root/images" ] || return 0
  for f in "$root/images"/*.tar; do
    if [ -f "$f" ]; then printf '%s\n' "$f"; fi
  done | sort
}

# ---------------------------------------------------------------- paths

data_dir_default() {
  echo "${ASKWELL_DATA_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/askwell}"
}

install_prefix_default() {
  echo "${ASKWELL_INSTALL_PREFIX:-${XDG_DATA_HOME:-$HOME/.local/share}/askwell/app}"
}

bin_dir_default() {
  echo "${ASKWELL_BIN_DIR:-$HOME/.local/bin}"
}

desktop_dir_default() {
  echo "${ASKWELL_DESKTOP_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/applications}"
}

systemd_user_dir_default() {
  echo "${ASKWELL_SYSTEMD_USER_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user}"
}

install_record_path() {
  echo "$1/install.json"
}

# ---------------------------------------------------------------- state

is_previous_install() {
  [ -f "$(install_record_path "$1")" ]
}

previous_install_version() {
  local record
  record="$(install_record_path "$1")"
  [ -f "$record" ] || return 1
  grep -o '"version" *: *"[^"]*"' "$record" | head -n1 | sed -E 's/.*"([^"]+)"$/\1/'
}

write_install_record() {
  local data_dir="$1" version="$2" method="$3"
  mkdir -p "$data_dir"
  cat > "$(install_record_path "$data_dir")" <<EOF
{
  "version": "$version",
  "method": "$method",
  "installed_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "data_dir": "$data_dir"
}
EOF
}

# ---------------------------------------------------------------- secrets

# A random hex string, `bytes` bytes (so twice that many hex characters).
# `openssl` is already a runtime dependency of every distro's Podman/Postgres
# tooling and is preferred; `/dev/urandom` read directly through `od` is the
# fallback so a machine without `openssl` on PATH still gets a real secret
# rather than a refusal (nothing about generating a database password
# requires the openssl binary specifically, only a source of randomness).
random_hex() {
  local bytes="${1:-32}"
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex "$bytes"
  else
    head -c "$bytes" /dev/urandom | od -An -tx1 | tr -d ' \n'
  fi
}

# Replaces every literal `change-me*` placeholder in a freshly-copied .env
# with a generated random value (issue #584: the installer was shipping the
# literal placeholders from .env.example — a fixed, publicly-known credential
# on every install — because the target user this ticket is for will never
# open .env in an editor to follow its own "then set the three passwords"
# instruction).
#
# SANDBOX_OWNER_PASSWORD/ASKWELL_SANDBOX_OWNER_PASSWORD and
# SANDBOX_READONLY_PASSWORD/ASKWELL_SANDBOX_READONLY_PASSWORD are the same
# credential named twice in .env.example (Compose builds the app-side value
# from the Compose-side one) and must keep matching after generation, or the
# sandbox roles Compose creates and the passwords Askwell connects with go out
# of sync on every fresh install. The other four passwords are independent.
#
# Only ever called against a .env this run just created — never against an
# existing one, matching the "never touch an existing .env" upgrade rule
# install.sh's place_files already enforces by only copying when no .env is
# present yet.
generate_env_passwords() {
  local env_file="$1"
  local postgres_password postgres_app_password postgres_readonly_password \
        sandbox_postgres_password sandbox_owner_password sandbox_readonly_password
  postgres_password="$(random_hex 32)"
  postgres_app_password="$(random_hex 32)"
  postgres_readonly_password="$(random_hex 32)"
  sandbox_postgres_password="$(random_hex 32)"
  sandbox_owner_password="$(random_hex 32)"
  sandbox_readonly_password="$(random_hex 32)"

  sed -i \
    -e "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$postgres_password/" \
    -e "s/^POSTGRES_APP_PASSWORD=.*/POSTGRES_APP_PASSWORD=$postgres_app_password/" \
    -e "s/^POSTGRES_READONLY_PASSWORD=.*/POSTGRES_READONLY_PASSWORD=$postgres_readonly_password/" \
    -e "s/^SANDBOX_POSTGRES_PASSWORD=.*/SANDBOX_POSTGRES_PASSWORD=$sandbox_postgres_password/" \
    -e "s/^SANDBOX_OWNER_PASSWORD=.*/SANDBOX_OWNER_PASSWORD=$sandbox_owner_password/" \
    -e "s/^SANDBOX_READONLY_PASSWORD=.*/SANDBOX_READONLY_PASSWORD=$sandbox_readonly_password/" \
    -e "s/^ASKWELL_SANDBOX_OWNER_PASSWORD=.*/ASKWELL_SANDBOX_OWNER_PASSWORD=$sandbox_owner_password/" \
    -e "s/^ASKWELL_SANDBOX_READONLY_PASSWORD=.*/ASKWELL_SANDBOX_READONLY_PASSWORD=$sandbox_readonly_password/" \
    "$env_file"
}

# The three Redis passwords (`M8-FIX-SEC-177`, issue #730), one per service
# that connects. Unlike generate_env_passwords this runs on every install,
# upgrades included: an install from before Redis had users has a .env with
# none of these lines, and Compose refuses to start the stack without them —
# the right refusal for a person editing .env by hand, the wrong one for an
# upgrade. So a missing, empty or `change-me*` value is replaced with a
# generated one and a real value is left alone.
#
# Replacing one is always safe: Redis keeps no users of its own between
# starts — deploy/redis/start.sh renders them from .env every time — so a new
# password here is the password from the next start on, with nothing stored
# anywhere to fall out of step with it.
#
# A temp file and a move, not `sed -i`, for the BSD/GNU reason
# generate_env_passwords gives.
ensure_redis_passwords() {
  local env_file="$1" name value tmp_file appended=""
  for name in REDIS_API_PASSWORD REDIS_WORKER_PASSWORD REDIS_PROXY_PASSWORD; do
    value="$(grep -E "^${name}=" "$env_file" | tail -1 | cut -d= -f2-)" || value=""
    case "$value" in
      ''|change-me*) ;;
      *) continue ;;
    esac
    if grep -q -E "^${name}=" "$env_file"; then
      tmp_file="$(mktemp "${TMPDIR:-/tmp}/askwell-env.XXXXXX")"
      sed -e "s/^${name}=.*/${name}=$(random_hex 32)/" "$env_file" > "$tmp_file"
      mv "$tmp_file" "$env_file"
    else
      appended="${appended}${name}=$(random_hex 32)\n"
    fi
  done
  if [ -n "$appended" ]; then
    tmp_file="$(mktemp "${TMPDIR:-/tmp}/askwell-env.XXXXXX")"
    # shellcheck disable=SC2059  # `appended` is our own NAME=hex lines
    { cat "$env_file"; printf '\n\n# Redis, one user per service — generated by the installer (M8-FIX-SEC-177).\n'; printf "$appended"; } > "$tmp_file"
    mv "$tmp_file" "$env_file"
  fi
}

# ---------------------------------------------------------------- database

# The named volumes `compose.yaml` declares, as Podman names them (the
# project is `name: askwell`). Everything Askwell keeps outside the data
# directory lives in these: the database (index, extracted text, memory,
# conversations, audit log), the imported-database sandbox, the queue, and
# `/var/lib/askwell` (stored backups, crash reports, traces), and the sockets
# volume (empty here; Windows uses it, M11-FIX-DEPLOY-223). install.test.sh
# checks this list against compose.yaml so the two cannot drift.
ASKWELL_VOLUMES="askwell_postgres-data askwell_sandbox-data askwell_redis-data askwell_askwell-state askwell_askwell-sockets"

# Brings the schema to the image's migration head by running compose's own
# one-shot `migrate` service (M9-FIX-DEPLOY-200, issue #698), which starts
# Postgres first if it is not already up. The same service runs on every
# stack start; the installer runs it here as well so that it can wait for
# the result and stop on a failure, rather than register a stack that will
# never serve and then say it is done. A schema already at head is a no-op.
#
# Output goes to `log_file`, whose "Running upgrade" lines are Alembic's
# own record of what it applied. Returns the migration's exit status.
run_database_migration() {
  local compose_path="$1" env_path="$2" log_file="$3"
  mkdir -p "$(dirname "$log_file")"
  "${ASKWELL_PODMAN:-podman}" compose -f "$compose_path" --env-file "$env_path" \
    run --rm migrate > "$log_file" 2>&1
}

# How many migrations a run applied, read from its log. 0 is "already at
# head", which the installer reports as exactly that.
migrations_applied() {
  grep -c 'Running upgrade' "$1" 2>/dev/null || true
}

# Where a plain uninstall keeps `.env` (issue #765). The default install
# prefix is inside the data directory but is removed with the application
# files, and `.env` holds the passwords the kept `postgres-data` volume was
# initialised with. A reinstall that generated new ones could not log in to
# its own database, so the uninstaller moves `.env` here and `place_files`
# moves it back. `--purge-data` removes it with the rest of the data
# directory, because by then the database it opens is gone too.
kept_env_path() {
  printf '%s/askwell.env\n' "$1"
}

# Stops the stack's containers, by the install's own compose files. Used
# before an upgrade migrates (issue #768), so the old version's `api` and
# `worker` are never serving against a schema newer than their own.
stop_stack_containers() {
  local compose_path="$1" env_path="$2"
  "${ASKWELL_PODMAN:-podman}" compose -f "$compose_path" --env-file "$env_path" down >/dev/null 2>&1
}

# Removes every volume in ASKWELL_VOLUMES (issue #700), by name rather than
# through `compose down -v`, so it works whether or not compose.yaml is
# still on disk — the uninstaller has removed it by the time it asks. `-f`
# also removes a stopped container still holding one. Prints each volume it
# could not remove and returns 1 if there was any, so the caller reports
# only what actually happened.
purge_stack_volumes() {
  local podman_bin="${ASKWELL_PODMAN:-podman}" volume failed=0
  for volume in $ASKWELL_VOLUMES; do
    "$podman_bin" volume exists "$volume" 2>/dev/null || continue
    "$podman_bin" volume rm -f "$volume" >/dev/null 2>&1 || true
    if "$podman_bin" volume exists "$volume" 2>/dev/null; then
      printf '%s\n' "$volume"
      failed=1
    fi
  done
  return "$failed"
}

# ---------------------------------------------------------------- generated files

desktop_entry_contents() {
  local exec_path="$1" icon_path="$2"
  cat <<EOF
[Desktop Entry]
Type=Application
Name=Askwell
Comment=Ask questions of your own files and databases, locally
Exec=$exec_path
Icon=$icon_path
Terminal=false
Categories=Office;Utility;
StartupWMClass=Askwell
EOF
}

# A user (not system) unit: a system unit cannot exec files under $HOME on
# Fedora with SELinux enforcing, the same reason the watchdog timer is a user
# unit (AGENTS.md §5). `WantedBy=default.target` is the user-session
# equivalent of "start with the session" for a graphical login where
# `graphical-session.target` is the more precise target but is not reliably
# reached on every desktop environment this ships to; `default.target` is the
# one every systemd --user instance has.
#
# `Wants=`/`After=` the two platform-level services below (M7-PACK-DEPLOY-142)
# so a session login starts the stack and inference first — the shell's own
# supervisor (`M7-TAURI-DEPLOY-183`, `web/src-tauri/src/supervisor.rs`) then
# adopts whatever is already up via `state.json`'s heartbeat rather than
# racing to spawn a second copy. `Wants=`, not `Requires=`: the shell must
# still open (to show the starting page and its own causes) even if one of
# the platform services has already hit its restart cap.
systemd_unit_contents() {
  local exec_path="$1"
  cat <<EOF
[Unit]
Description=Askwell
Wants=askwell-stack.service askwell-inference.service
After=askwell-stack.service askwell-inference.service

[Service]
Type=simple
ExecStart=$exec_path
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF
}

# The container stack, supervised as its own systemd --user unit so it is up
# for the session whether or not the shell is ever opened
# (M7-PACK-DEPLOY-142's "survive the shell being closed").
#
# `podman compose up -d` returns immediately once containers are started,
# which would leave `Restart=on-failure` nothing to watch — so this runs
# compose in the foreground instead. `--abort-on-container-exit` makes that
# foreground process exit non-zero the moment any container in the stack
# dies, which is what turns "a container was killed" into "the unit exited
# and systemd restarts it" — the stack half of "killing either results in a
# supervised restart".
#
# `--no-attach migrate` (M9-FIX-DEPLOY-200): `migrate` is the one service
# meant to exit, and exiting 0 is its success. Attached, that exit alone
# trips `--abort-on-container-exit` and stops the whole stack a few seconds
# after it starts — seen on the real stack with docker-compose v5.1.1. Not
# attached, it is not watched; a failed migration still stops `up`, because
# `api` and `worker` wait on it with `service_completed_successfully`.
#
# `StartLimitIntervalSec=300`/`StartLimitBurst=5` (in `[Unit]`, verified
# against `man systemd.unit` on this host's systemd 258 — the rate-limit
# keys live there, not in `[Service]`) is the backoff cap: past 5 restarts in
# 5 minutes systemd stops trying and the unit settles into `failed`,
# queryable with `systemctl --user status askwell-stack.service` — "backoff
# caps and the state becomes failed with the last reason" for the container
# half. `ExecStop` runs `compose down` explicitly so `systemctl --user stop`
# (and a session logout, which stops `WantedBy=default.target` units) leaves
# no orphaned container, matching this ticket's own Validation Rule.
# `Requires=podman.socket`: docker-compose, the provider `podman compose`
# runs (issue #767), talks to Podman through its API socket and fails with
# "Cannot connect to the Docker daemon" when the socket is not listening —
# reproduced on the build host by stopping it. The installer enables it too.
systemd_stack_unit_contents() {
  local compose_path="$1" env_path="$2" working_dir="$3"
  cat <<EOF
[Unit]
Description=Askwell container stack
After=network-online.target podman.socket
Requires=podman.socket
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=simple
WorkingDirectory=$working_dir
ExecStart=podman compose -f $compose_path --env-file $env_path up --abort-on-container-exit --no-attach migrate
ExecStop=podman compose -f $compose_path --env-file $env_path down
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF
}

# The native inference supervisor (`deploy/inference/askwell-inference`,
# M0-MODEL-DEPLOY-018), as its own systemd --user unit for the same
# survives-the-shell-closing reason as the stack unit above.
#
# That script already retries a failed llama.cpp spawn on its own five-step
# backoff and gives up with a reason recorded in `state.json` — this unit is
# a different, rarer layer above that: it restarts the *outer* Python
# process itself if something kills it outright (OOM, an uncaught
# exception), which the script's own internal backoff cannot cover because
# there is no script left running to do the retrying.
#
# `After=askwell-stack.service` orders it behind the stack (the bridge
# container the inference socket connects through needs to exist first, see
# `docs/decisions.md`), but `Wants=`, not `Requires=`, so a stack that has
# hit its own restart cap does not also block inference from being tried —
# the two failure causes stay independently reported, per this ticket's own
# Acceptance Criteria.
#
# `--env-file` and `WorkingDirectory=` are what give it Askwell's settings
# (M11-FIX-DEPLOY-225). Not `EnvironmentFile=`: the `.env`'s socket path is
# the containers' `/run/askwell/inference.sock`, which the supervisor must
# not take; given the file itself, it puts its socket and state.json in
# ASKWELL_RUN_DIR instead, the host directory mounted there.
systemd_inference_unit_contents() {
  local exec_path="$1" env_path="$2" working_dir="$3"
  cat <<EOF
[Unit]
Description=Askwell native inference supervisor
After=askwell-stack.service
Wants=askwell-stack.service
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=simple
WorkingDirectory=$working_dir
ExecStart=$exec_path --env-file $env_path
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF
}
