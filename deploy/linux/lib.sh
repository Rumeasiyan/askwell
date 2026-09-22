#!/usr/bin/env bash
# Pure(ish) logic for the Linux installer (M7-PACK-DEPLOY-139). Sourced, never
# forked, by install.sh and uninstall.sh, and by install.test.sh in isolation.
#
# Every function here either returns a value on stdout or a status code with
# no side effect beyond what its name says — that is what makes them testable
# without a real machine to install onto. install.sh does the actual copying,
# process management and privilege escalation; this file decides *what* it
# should do.
#
# Targets bash 3.2 conventions (see scripts/guards.sh) even though Linux is
# the only platform this ships on today, so a shared style holds across
# deploy/*.

: "${ASKWELL_MIN_PODMAN_VERSION:=4.3}"

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
runtime_install_cmd() {
  case "$1" in
    dnf) echo "dnf install -y podman" ;;
    apt) echo "apt-get update && apt-get install -y podman" ;;
    zypper) echo "zypper install -y podman" ;;
    pacman) echo "pacman -Sy --noconfirm podman" ;;
    *) return 1 ;;
  esac
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
systemd_unit_contents() {
  local exec_path="$1"
  cat <<EOF
[Unit]
Description=Askwell

[Service]
Type=simple
ExecStart=$exec_path
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF
}
