#!/usr/bin/env bash
# Pure(ish) logic for the macOS installer (M7-PACK-DEPLOY-141). Sourced,
# never forked, by install.sh and uninstall.sh, and by install.test.sh in
# isolation — same split as deploy/linux/lib.sh and deploy/windows/lib.ps1:
# every function here returns a value on stdout or a status code with no
# side effect beyond what its name says, so it is testable without a real
# Mac to install onto. generate_env_passwords is the one function here with
# a real side effect (it rewrites a file), for the same reason lib.sh's
# original does.
#
# Targets bash 3.2 — not because it is this platform's default shell (zsh
# has been since Catalina) but because /bin/bash on every Mac still ships at
# 3.2 for licensing reasons Apple has never revisited, and this script must
# run under whatever `#!/usr/bin/env bash` resolves to on a clean machine,
# not whatever a contributor's Homebrew happened to install. Same target as
# deploy/linux/lib.sh, for the same reason: a shared style holds across
# deploy/*.
#
# Podman has no native macOS container runtime. Every container runs inside
# a small VM ("the Podman machine") the same way Windows' WSL2 does — so, as
# on Windows, "is the runtime installed" here also has to answer "does a
# machine exist and is it running", which Linux never has to ask.

: "${ASKWELL_MIN_PODMAN_VERSION:=4.3}"

# ---------------------------------------------------------------- messaging

askwell_die() { printf 'askwell-install: %s\n' "$*" >&2; return 1; }
askwell_say() { printf '%s\n' "$*"; }

# ---------------------------------------------------------------- runtime

# The command that installs Podman via Homebrew. Named rather than invoked
# here — install.sh shows it and asks before running it, same as
# deploy/linux/lib.sh's runtime_install_cmd.
runtime_install_cmd() {
  echo "brew install podman"
}

# ---------------------------------------------------------------- versions

# Compares two dotted version strings a and b. Echoes -1, 0 or 1 for a<b,
# a==b, a>b. Identical to deploy/linux/lib.sh's version_compare — duplicated
# rather than shared, matching lib.ps1's own note that the two installers
# "refuse on the same rule" without a cross-platform module to keep in sync.
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

# Parses `podman --version`'s "podman version 4.9.4" into "4.9.4".
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

# ---------------------------------------------------------------- the machine

# Whether any Podman machine exists at all. `--noheading` is a documented,
# stable flag (same family as `podman ps --noheading`) rather than
# `--format`'s Go-template field names, which vary enough across Podman
# releases that guessing one here would be exactly the kind of unverified
# API AGENTS.md §4 warns against.
has_podman_machine() {
  [ -n "$(podman machine list --noheading 2>/dev/null)" ]
}

# Whether a machine is currently running. "Currently running" is the literal
# string `podman machine list`'s default table has printed in its LAST UP
# column for a running machine across every version this project has used;
# parsing it is more brittle than a documented flag would be, but no such
# flag is verified, so the visible, human-facing table is the honest choice
# over guessing a JSON field name from training data (AGENTS.md §4).
podman_machine_running() {
  podman machine list --noheading 2>/dev/null | grep -q "Currently running"
}

# ---------------------------------------------------------------- disk space

required_install_bytes() {
  echo "${ASKWELL_REQUIRED_INSTALL_BYTES:-8000000000}"
}

# BSD `df` (macOS's own, distinct from Linux's GNU `df`) has no
# `--output=avail`, so this reads its fixed column order instead:
# `Filesystem 1024-blocks Used Available Capacity iused ifree %iused
# Mounted on` — Available is column 4 with `-k` forcing 1024-byte blocks
# regardless of the caller's locale-driven default block size.
available_bytes() {
  local path="$1"
  local probe="$path"
  while [ ! -d "$probe" ] && [ "$probe" != "/" ]; do
    probe="$(dirname "$probe")"
  done
  df -k "$probe" 2>/dev/null | awk 'NR==2 { printf "%d", $4 * 1024 }'
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

# ---------------------------------------------------------------- paths

# No XDG on macOS: `~/Library/Application Support` is the platform's own
# equivalent, and `~/Applications` is where a per-user (no-admin) app
# install belongs — `/Applications` needs an administrator, and the target
# user here is a consultant on their own laptop, not someone who can assume
# that access (the same reasoning Linux's `~/.local/share` and Windows'
# `%LOCALAPPDATA%` defaults already apply).
data_dir_default() {
  echo "${ASKWELL_DATA_DIR:-$HOME/Library/Application Support/Askwell}"
}

install_prefix_default() {
  echo "${ASKWELL_INSTALL_PREFIX:-$HOME/Library/Application Support/Askwell/app}"
}

app_dir_default() {
  echo "${ASKWELL_APP_DIR:-$HOME/Applications/Askwell.app}"
}

bin_dir_default() {
  echo "${ASKWELL_BIN_DIR:-$HOME/.local/bin}"
}

launch_agents_dir_default() {
  echo "${ASKWELL_LAUNCH_AGENTS_DIR:-$HOME/Library/LaunchAgents}"
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

random_hex() {
  local bytes="${1:-32}"
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex "$bytes"
  else
    head -c "$bytes" /dev/urandom | od -An -tx1 | tr -d ' \n'
  fi
}

# Same fix, same reasoning, as deploy/linux/lib.sh's generate_env_passwords
# (issue #584): a freshly-copied .env carries `change-me*` placeholders that
# nobody using this installer will ever open an editor to replace.
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

  # A temp-file-and-replace, not `sed -i`: BSD sed (macOS's own) requires
  # `-i`'s backup-suffix argument attached with no space (`-i ''` as two
  # argv tokens is a GNU/BSD split — GNU sed then reads the empty string as
  # a filename to edit, not a suffix, and fails outright). Writing to a temp
  # file and moving it over the original is the one spelling that behaves
  # identically under both, and is what this file's own tests (run under
  # Linux's GNU sed) actually exercise.
  local tmp_file
  tmp_file="$(mktemp "${TMPDIR:-/tmp}/askwell-env.XXXXXX")"
  sed \
    -e "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$postgres_password/" \
    -e "s/^POSTGRES_APP_PASSWORD=.*/POSTGRES_APP_PASSWORD=$postgres_app_password/" \
    -e "s/^POSTGRES_READONLY_PASSWORD=.*/POSTGRES_READONLY_PASSWORD=$postgres_readonly_password/" \
    -e "s/^SANDBOX_POSTGRES_PASSWORD=.*/SANDBOX_POSTGRES_PASSWORD=$sandbox_postgres_password/" \
    -e "s/^SANDBOX_OWNER_PASSWORD=.*/SANDBOX_OWNER_PASSWORD=$sandbox_owner_password/" \
    -e "s/^SANDBOX_READONLY_PASSWORD=.*/SANDBOX_READONLY_PASSWORD=$sandbox_readonly_password/" \
    -e "s/^ASKWELL_SANDBOX_OWNER_PASSWORD=.*/ASKWELL_SANDBOX_OWNER_PASSWORD=$sandbox_owner_password/" \
    -e "s/^ASKWELL_SANDBOX_READONLY_PASSWORD=.*/ASKWELL_SANDBOX_READONLY_PASSWORD=$sandbox_readonly_password/" \
    "$env_file" > "$tmp_file"
  mv "$tmp_file" "$env_file"
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

# ---------------------------------------------------------------- quarantine

# Whether a file that should exist after a plain copy is missing is, on its
# own, ambiguous — same reasoning as lib.ps1's Get-AskwellQuarantineMessage.
# On macOS the two real causes are XProtect's behavioural service quietly
# removing an unfamiliar unsigned binary, or the release tree being
# incomplete; the fix differs, so both are named rather than a generic
# "file not found".
quarantine_message() {
  local name="$1"
  cat <<EOF
$name is missing after being placed. If macOS removed it, open System
Settings -> Privacy & Security and look for a notice naming $name, or check
Console.app for XProtect entries around the time of this install — Askwell's
native inference binary and its unsigned desktop shell (docs/installing.md)
are both unfamiliar executables that heuristic scanning has never seen
before. If nothing was removed, the release tree itself is missing this
file and needs rebuilding.
EOF
}

# ---------------------------------------------------------------- generated files

# `RunAtLoad` starts Askwell once, at login, matching "start with the
# session". `KeepAlive/SuccessfulExit=false` restarts it only after a crash
# (a non-zero exit) — never after the user deliberately quits, which exits
# 0 — mirroring deploy/linux/lib.sh's `systemd_unit_contents`
# (`Restart=on-failure`), not a plain always-relaunch agent.
launch_agent_plist_contents() {
  local exec_path="$1"
  cat <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.askwell.app</string>
  <key>ProgramArguments</key>
  <array>
    <string>$exec_path</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <dict>
    <key>SuccessfulExit</key>
    <false/>
  </dict>
  <key>ProcessType</key>
  <string>Interactive</string>
</dict>
</plist>
EOF
}

# The platform half of M7-PACK-DEPLOY-142: the container stack and native
# inference process, each as their own LaunchAgent, so both are running for
# the session whether or not the app itself is ever opened — the shell's own
# supervisor (M7-TAURI-DEPLOY-183) attaches to whatever is already up via
# `state.json`'s heartbeat rather than racing to start a second copy.
#
# `podman compose up -d` returns immediately, leaving `KeepAlive` nothing to
# watch, so `ProgramArguments` runs compose in the foreground instead —
# `--abort-on-container-exit` makes that foreground process exit non-zero the
# moment any container dies, which is what `KeepAlive`/`SuccessfulExit=false`
# needs in order to restart it.
#
# Known, disclosed limitation (issue #607, decided in docs/decisions.md this
# date): unlike systemd's `StartLimitBurst`, launchd has no configurable cap
# on `KeepAlive` restarts — a permanently failing agent is retried
# indefinitely, throttled only by launchd's own undocumented back-off, and
# never reaches a distinct `failed` state the way the Linux unit or the
# Windows scheduled task does. The decision was to accept that asymmetry
# rather than add a wrapper script that duplicates the backoff logic
# `deploy/inference/askwell-inference` already has, and to let
# `state.json`'s heartbeat age be the one detection path every platform's
# repair surface (M7-PACK-FE-143) can share.
launch_agent_stack_plist_contents() {
  local podman_bin="$1" compose_path="$2" env_path="$3" working_dir="$4" log_dir="$5"
  cat <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.askwell.stack</string>
  <key>ProgramArguments</key>
  <array>
    <string>$podman_bin</string>
    <string>compose</string>
    <string>-f</string>
    <string>$compose_path</string>
    <string>--env-file</string>
    <string>$env_path</string>
    <string>up</string>
    <string>--abort-on-container-exit</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$working_dir</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <dict>
    <key>SuccessfulExit</key>
    <false/>
  </dict>
  <key>StandardOutPath</key>
  <string>$log_dir/askwell-stack.log</string>
  <key>StandardErrorPath</key>
  <string>$log_dir/askwell-stack.log</string>
</dict>
</plist>
EOF
}

# The native inference supervisor (`deploy/inference/askwell-inference`,
# M0-MODEL-DEPLOY-018) as its own LaunchAgent. That script already retries a
# failed llama.cpp spawn on its own five-step backoff and records a reason in
# `state.json` when it gives up; this agent is a different, rarer layer above
# it — restarting the outer Python process itself if something kills it
# outright, which the script's own retry loop cannot cover because there is
# no script left running to do it.
launch_agent_inference_plist_contents() {
  local exec_path="$1" log_dir="$2"
  cat <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.askwell.inference</string>
  <key>ProgramArguments</key>
  <array>
    <string>$exec_path</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <dict>
    <key>SuccessfulExit</key>
    <false/>
  </dict>
  <key>StandardOutPath</key>
  <string>$log_dir/askwell-inference.log</string>
  <key>StandardErrorPath</key>
  <string>$log_dir/askwell-inference.log</string>
</dict>
</plist>
EOF
}
