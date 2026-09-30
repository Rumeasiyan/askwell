#!/usr/bin/env bash
# Askwell's Linux installer. M7-PACK-DEPLOY-139.
#
# One command, run by someone who has never used a container: check for or
# install Podman, place the stack, the native inference binary, the probe and
# the desktop shell, create the data directories, register Askwell to start
# with the session, and open the Askwell window — never a browser tab
# (docs/backlog/M7-someone-else-can-install-it.md, this ticket).
#
# What this script needs beside itself, and where it expects to find it:
#
#   REPO_ROOT (two directories above this script)/
#     compose.yaml, .env.example, deploy/postgres, deploy/sandbox, deploy/redis — the stack
#     deploy/probe/askwell-probe                                    — the host probe (M7-PROBE-DEPLOY-137)
#     deploy/inference/askwell-inference                             — native inference (M0-MODEL-DEPLOY-018)
#     deploy/inference/llama.cpp/{gpu,cpu}/                            — llama.cpp's Vulkan and CPU builds
#                                                                      (a release only; M10-FIX-DEPLOY-222)
#     web/src-tauri/target/release/askwell-shell                      — the desktop shell binary (M7-TAURI-DEPLOY-181)
#     web/out/                                                         — the built interface compose.yaml mounts (#766)
#     images/*.tar                                                     — the container images, saved (optional)
#
# A release tarball ships this same layout (a trimmed export of the
# repository, not a separate bundle format), assembled by
# scripts/release-artefact.sh in .github/workflows/release.yml
# (M9-REL-DEPLOY-214). `images/` is what a release adds that a source
# checkout lacks: without it, compose would have to build the API image from
# source the tarball does not carry. A checkout has no `images/` and uses
# the images already built on this machine. The one artefact this
# script cannot produce itself is the compiled shell binary: building it needs
# the Rust toolchain, which a non-technical installing user must never be
# asked for, so its absence is a refusal naming the missing file and the
# build command that produces it — never a silent fall back to a browser tab,
# which is exactly the thing M7-TAURI-DEPLOY-181 exists to make unnecessary.
#
# Never fetches a model. Podman itself may need the network to install and
# `podman compose` may need it to pull or build container images — the same
# class of install-time exception `scripts/dev.sh lock`/`web-install` already
# name (AGENTS.md §5) — but nothing here ever reaches out for model weights.

set -Eeuo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
# shellcheck source=./lib.sh
. "$HERE/lib.sh"

VERSION="$(cat "$REPO_ROOT/VERSION" 2>/dev/null || echo "0.0.0")"

DATA_DIR="$(data_dir_default)"
INSTALL_PREFIX="$(install_prefix_default)"
BIN_DIR="$(bin_dir_default)"
DESKTOP_DIR="$(desktop_dir_default)"
SYSTEMD_USER_DIR="$(systemd_user_dir_default)"
ASSUME_YES=0

usage() {
  cat <<EOF
Usage: install.sh [options]

  --data-dir PATH     Where Askwell keeps its data (default: $DATA_DIR)
  --prefix PATH        Where Askwell's application files are placed (default: $INSTALL_PREFIX)
  -y, --yes            Do not prompt for confirmation
  -h, --help           Show this help
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --data-dir) DATA_DIR="$2"; shift 2 ;;
    --prefix) INSTALL_PREFIX="$2"; shift 2 ;;
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

# ---------------------------------------------------------------- 1. runtime

check_runtime() {
  if command -v podman >/dev/null 2>&1; then
    local reported
    reported="$(podman --version)"
    if podman_meets_minimum "$reported"; then
      askwell_say "Podman found: $reported"
      return 0
    fi
    askwell_die "Podman is installed but too old ($reported). Askwell needs Podman $ASKWELL_MIN_PODMAN_VERSION or newer. Upgrade it with your package manager, then run this installer again."
    exit 1
  fi

  local mgr cmd extras
  mgr="$(detect_pkg_manager)" || {
    askwell_die "Podman is not installed and this installer does not recognise your package manager. Install Podman $ASKWELL_MIN_PODMAN_VERSION or newer yourself (podman.io/docs/installation), then run this installer again."
    exit 1
  }
  # Docker Compose and the OpenMP runtime in the same command, so this is
  # the one `sudo` a new machine is asked for (M11-FIX-DEPLOY-225).
  extras="$(extra_packages "$mgr" "$(os_release_text)" yes)"
  # shellcheck disable=SC2086 # package names, split on purpose
  cmd="$(runtime_install_cmd "$mgr" $extras)"

  if ! have_admin_path; then
    askwell_die "Podman is not installed, and this account has no path to root (no 'sudo' on this machine and not running as root). Ask whoever administers this machine to run: sudo $cmd — then run this installer again."
    exit 1
  fi

  askwell_say "Podman is not installed. This installer needs to run:"
  askwell_say "  sudo $cmd"
  confirm "Install Podman${extras:+ and $extras} now?" || { askwell_die "Podman is required. Install it and re-run this installer."; exit 1; }
  # Real sudo, not `sudo -n`: it prompts for a password like any other command
  # on a normal desktop account, which is the whole fix for issue #503.
  if [ "$(id -u)" -eq 0 ]; then
    sh -c "$cmd"
  else
    sudo sh -c "$cmd"
  fi
  command -v podman >/dev/null 2>&1 || { askwell_die "Podman install command finished but 'podman' is still not on PATH. Something about that install did not work as expected."; exit 1; }
  askwell_say "Podman installed: $(podman --version)"
}

# ---------------------------------------------------------------- 1a. compose provider

# Issue #767: `podman compose` runs an external provider and the Podman
# package brings none, so a machine where the step above has just installed
# Podman can have no `podman compose` at all. Checked before anything is
# copied, and by name: docker-compose is the one provider this stack is
# verified with.
check_compose_provider() {
  ensure_podman_socket
  local reported
  reported="$(podman compose version 2>/dev/null || true)"
  if compose_provider_meets_minimum "$reported"; then
    askwell_say "Compose provider found: $(printf '%s\n' "$reported" | grep -m1 'Docker Compose version')"
    return 0
  fi

  local found="none"
  [ -n "$reported" ] && found="$(printf '%s\n' "$reported" | head -n1)"
  local mgr cmd openmp=""
  mgr="$(detect_pkg_manager)" || mgr=unknown
  openmp_runtime_present || openmp="$(openmp_package "$mgr" || true)"
  # shellcheck disable=SC2086 # empty, or one package name
  if ! cmd="$(compose_install_cmd "$mgr" "$(os_release_text)" $openmp)" || ! have_admin_path; then
    askwell_die "Askwell runs its containers through 'podman compose', which needs Docker Compose $ASKWELL_MIN_COMPOSE_VERSION or newer installed as its provider (podman-compose is not supported). Found: $found. Install Docker Compose (docs.docker.com/compose/install/linux), then run this installer again. Nothing has been copied."
    exit 1
  fi

  askwell_say "Askwell runs its containers through 'podman compose', which needs Docker Compose $ASKWELL_MIN_COMPOSE_VERSION or newer (found: $found). This installer needs to run:"
  askwell_say "  sudo $cmd"
  confirm "Install Docker Compose now?" || { askwell_die "Docker Compose is required. Install it and re-run this installer. Nothing has been copied."; exit 1; }
  if [ "$(id -u)" -eq 0 ]; then
    sh -c "$cmd"
  else
    sudo sh -c "$cmd"
  fi
  reported="$(podman compose version 2>/dev/null || true)"
  compose_provider_meets_minimum "$reported" || {
    askwell_die "The Docker Compose install finished, but 'podman compose version' still does not report Docker Compose $ASKWELL_MIN_COMPOSE_VERSION or newer (it said: ${reported:-nothing}). Nothing has been copied."
    exit 1
  }
  askwell_say "Compose provider installed: $(printf '%s\n' "$reported" | grep -m1 'Docker Compose version')"
}

# ---------------------------------------------------------------- 1b. OpenMP runtime

# Every bundled llama-server links libgomp.so.1, and a minimal Ubuntu has
# none (M11-FIX-DEPLOY-225): the stack came up and the assistant never did.
# Usually installed by one of the two steps above; this catches a machine
# that already had Podman and Docker Compose.
check_openmp_runtime() {
  if openmp_runtime_present; then
    askwell_say "OpenMP runtime found (libgomp.so.1)"
    return 0
  fi
  local mgr package cmd
  mgr="$(detect_pkg_manager)" || mgr=unknown
  if ! package="$(openmp_package "$mgr")" || ! have_admin_path; then
    askwell_die "Askwell's AI runs llama.cpp, which needs the OpenMP runtime (libgomp.so.1), and this machine has none. Install your distribution's libgomp package, then run this installer again. Nothing has been copied."
    exit 1
  fi
  cmd="$(pkg_install_cmd "$mgr" "$package")"
  askwell_say "Askwell's AI needs the OpenMP runtime (libgomp.so.1), which is not installed. This installer needs to run:"
  askwell_say "  sudo $cmd"
  confirm "Install it now?" || { askwell_die "The OpenMP runtime is required. Install it and re-run this installer. Nothing has been copied."; exit 1; }
  if [ "$(id -u)" -eq 0 ]; then
    sh -c "$cmd"
  else
    sudo sh -c "$cmd"
  fi
  openmp_runtime_present || {
    askwell_die "The install finished, but libgomp.so.1 is still not in the loader's cache. Nothing has been copied."
    exit 1
  }
  askwell_say "OpenMP runtime installed (libgomp.so.1)"
}

# docker-compose reaches Podman through its API socket, which Podman ships
# as a systemd --user socket unit that a fresh account has disabled. Without
# it every `podman compose` command fails with "Cannot connect to the Docker
# daemon". Enabled, not only started, because the stack unit needs it at
# every login.
ensure_podman_socket() {
  command -v systemctl >/dev/null 2>&1 || return 0
  if systemctl --user is-enabled --quiet podman.socket 2>/dev/null && systemctl --user is-active --quiet podman.socket 2>/dev/null; then
    return 0
  fi
  systemctl --user enable --now podman.socket 2>/dev/null || {
    askwell_die "Could not enable Podman's API socket (systemctl --user enable --now podman.socket failed), which docker-compose needs to reach Podman. Run that command yourself to see why, then run this installer again. Nothing has been copied."
    exit 1
  }
  askwell_say "Podman's API socket enabled for this account (podman.socket), so docker-compose can reach Podman."
}

# ---------------------------------------------------------------- 2. disk space

check_disk_space() {
  local needed have
  needed="$(required_install_bytes)"
  have="$(available_bytes "$INSTALL_PREFIX")"
  if [ -z "$have" ]; then
    askwell_say "Could not determine free disk space at $INSTALL_PREFIX; continuing without the check."
    return 0
  fi
  if [ "$have" -lt "$needed" ]; then
    askwell_die "Not enough disk space at $INSTALL_PREFIX: need $(human_bytes "$needed"), have $(human_bytes "$have"). Free up space and run this installer again — nothing has been copied."
    exit 1
  fi
  askwell_say "Disk space OK: $(human_bytes "$have") available, $(human_bytes "$needed") needed."
}

# ---------------------------------------------------------------- 3. previous install

check_previous_install() {
  if is_previous_install "$DATA_DIR"; then
    local prev
    prev="$(previous_install_version "$DATA_DIR" || echo unknown)"
    askwell_say "Existing Askwell installation found (version $prev) at $DATA_DIR. Its data is left untouched; upgrading application files in place."
  fi
}

# ---------------------------------------------------------------- 4. required artefacts

SHELL_BIN="$REPO_ROOT/web/src-tauri/target/release/askwell-shell"

check_artefacts() {
  local missing=0
  [ -f "$REPO_ROOT/compose.yaml" ] || { askwell_say "Missing: $REPO_ROOT/compose.yaml"; missing=1; }
  [ -f "$REPO_ROOT/deploy/probe/askwell-probe" ] || { askwell_say "Missing: $REPO_ROOT/deploy/probe/askwell-probe"; missing=1; }
  [ -f "$REPO_ROOT/deploy/inference/askwell-inference" ] || { askwell_say "Missing: $REPO_ROOT/deploy/inference/askwell-inference"; missing=1; }
  if [ ! -f "$SHELL_BIN" ]; then
    askwell_say "Missing: $SHELL_BIN"
    askwell_say "  The desktop shell has not been built. Build it first with:"
    askwell_say "    cd $REPO_ROOT/web/src-tauri && cargo tauri build --no-bundle"
    missing=1
  fi
  if [ ! -f "$REPO_ROOT/web/out/index.html" ]; then
    askwell_say "Missing: $REPO_ROOT/web/out/index.html"
    askwell_say "  The interface has not been built. Build it first with: scripts/dev.sh web-build"
    missing=1
  fi
  if [ "$missing" -eq 1 ]; then
    askwell_die "One or more required files are missing (listed above). This installer places what a release build produces; it does not build them. Nothing has been copied."
    exit 1
  fi
}

# ---------------------------------------------------------------- 5. place files

place_files() {
  mkdir -p "$INSTALL_PREFIX" "$BIN_DIR" "$DESKTOP_DIR" "$SYSTEMD_USER_DIR"
  mkdir -p "$INSTALL_PREFIX/deploy/postgres" "$INSTALL_PREFIX/deploy/sandbox" "$INSTALL_PREFIX/deploy/redis"

  cp "$REPO_ROOT/compose.yaml" "$INSTALL_PREFIX/compose.yaml"
  local kept_env
  kept_env="$(kept_env_path "$DATA_DIR")"
  if [ ! -f "$INSTALL_PREFIX/.env" ] && [ -f "$kept_env" ]; then
    # Issue #765: the database volumes outlived a plain uninstall, and these
    # are the passwords they were initialised with.
    mv "$kept_env" "$INSTALL_PREFIX/.env"
    askwell_say "Restored the database credentials the previous uninstall kept, so this install opens the database it left in place."
  elif [ ! -f "$INSTALL_PREFIX/.env" ]; then
    cp "$REPO_ROOT/.env.example" "$INSTALL_PREFIX/.env"
    generate_env_passwords "$INSTALL_PREFIX/.env"
    askwell_say "Generated database credentials in $INSTALL_PREFIX/.env"
  fi
  # Every run, not only a fresh one: an upgrade from before Redis had users
  # needs these generated too, or the stack refuses to start.
  ensure_redis_passwords "$INSTALL_PREFIX/.env"
  cp -r "$REPO_ROOT/deploy/postgres/." "$INSTALL_PREFIX/deploy/postgres/"
  cp -r "$REPO_ROOT/deploy/sandbox/." "$INSTALL_PREFIX/deploy/sandbox/"
  cp -r "$REPO_ROOT/deploy/redis/." "$INSTALL_PREFIX/deploy/redis/"
  cp "$REPO_ROOT/deploy/probe/askwell-probe" "$INSTALL_PREFIX/askwell-probe"
  cp "$REPO_ROOT/deploy/inference/askwell-inference" "$INSTALL_PREFIX/askwell-inference"
  chmod +x "$INSTALL_PREFIX/askwell-probe" "$INSTALL_PREFIX/askwell-inference"
  place_llama_cpp

  # Replaced, not merged: a file an older interface had and this one does
  # not must not keep being served.
  rm -rf "$INSTALL_PREFIX/web/out"
  mkdir -p "$INSTALL_PREFIX/web"
  cp -r "$REPO_ROOT/web/out" "$INSTALL_PREFIX/web/out"

  cp "$SHELL_BIN" "$INSTALL_PREFIX/askwell"
  chmod +x "$INSTALL_PREFIX/askwell"
  ln -sf "$INSTALL_PREFIX/askwell" "$BIN_DIR/askwell"

  askwell_say "Application files placed under $INSTALL_PREFIX"
}

# The llama.cpp builds a release carries (M10-FIX-DEPLOY-222), placed next to
# askwell-inference, which is where it looks. Both go: the supervisor asks
# the Vulkan build at each start whether there is a graphics device it can
# use and runs the CPU build when there is not, so a card or driver added
# later is picked up without reinstalling. Replaced, not merged, so an
# older build's files never linger beside a newer one's. A source checkout
# carries none, and the supervisor runs `llama-server` from PATH as before.
place_llama_cpp() {
  local src="$REPO_ROOT/deploy/inference/llama.cpp"
  if [ ! -f "$src/gpu/llama-server" ] && [ ! -f "$src/cpu/llama-server" ]; then
    askwell_say "No llama.cpp build is bundled here; Askwell will run llama-server from PATH."
    return 0
  fi
  rm -rf "$INSTALL_PREFIX/llama.cpp"
  cp -Rp "$src" "$INSTALL_PREFIX/llama.cpp"
  askwell_say "llama.cpp placed under $INSTALL_PREFIX/llama.cpp. Answers run on the graphics card where llama.cpp can use it, and on the processor otherwise."
}

# ---------------------------------------------------------------- 5a. container images

# Before the stack unit is enabled: `up` uses an image already present and
# builds or pulls only one that is missing, so loading first is what keeps
# an installed machine from needing the source or a registry.
load_images() {
  local archives archive
  archives="$(bundled_image_archives "$REPO_ROOT")"
  if [ -z "$archives" ]; then
    askwell_say "No bundled container images; the stack will use the images already on this machine."
    return 0
  fi
  while IFS= read -r archive; do
    askwell_say "Loading container image $(basename "$archive")..."
    podman load -q -i "$archive" >/dev/null || {
      askwell_die "Could not load the container image $archive. The download may be damaged — check it against SHA256SUMS (docs/installing.md) and run this installer again."
      exit 1
    }
  done <<EOF_ARCHIVES
$archives
EOF_ARCHIVES
  askwell_say "Container images loaded."
}

# ---------------------------------------------------------------- 6. data dirs

create_data_dirs() {
  mkdir -p "$DATA_DIR" "$DATA_DIR/models" "$DATA_DIR/logs"
  askwell_say "Data directory: $DATA_DIR"
}

# ---------------------------------------------------------------- 6a. stop the old version

# Issue #768: on an upgrade the old version's containers are still serving.
# They stop before the schema moves, and register_stack_and_inference starts
# the new ones after, so no code ever runs against a schema newer than its
# own. The unit is stopped first because Restart=on-failure would otherwise
# bring the containers straight back; `down` then also catches containers
# the desktop shell started itself. Only on an upgrade: a fresh install has
# nothing running.
stop_previous_stack() {
  is_previous_install "$DATA_DIR" || return 0
  if command -v systemctl >/dev/null 2>&1 && systemctl --user is-active --quiet askwell-stack.service 2>/dev/null; then
    systemctl --user stop askwell-stack.service 2>/dev/null || {
      askwell_die "Could not stop the running Askwell (systemctl --user stop askwell-stack.service failed), so the upgrade stopped before changing the database. The new application files are in place; run this installer again."
      exit 1
    }
  fi
  stop_stack_containers "$INSTALL_PREFIX/compose.yaml" "$INSTALL_PREFIX/.env" || {
    askwell_die "Could not stop the running Askwell's containers (podman compose down failed), so the upgrade stopped before changing the database. The new application files are in place; run this installer again."
    exit 1
  }
  askwell_say "Stopped the running Askwell so its database can be upgraded; the new version starts once the upgrade is done."
}

# ---------------------------------------------------------------- 6b. database schema

# Issue #698: before this step existed nothing ever ran a migration, so a
# fresh install started against an empty database and an upgrade ran new code
# against the old schema. Runs before the stack is registered so that a
# failure stops the install here, named, rather than after it has said done.
migrate_database() {
  local log="$DATA_DIR/logs/migrate.log" applied rc
  askwell_say "Bringing Askwell's database up to date (the first run also starts the database)..."
  if run_database_migration "$INSTALL_PREFIX/compose.yaml" "$INSTALL_PREFIX/.env" "$log"; then
    applied="$(migrations_applied "$log")"
    if [ "${applied:-0}" -eq 0 ]; then
      askwell_say "Database schema already up to date; no migrations to apply."
    else
      askwell_say "Database schema up to date: applied $applied migration(s)."
    fi
    return 0
  else
    rc=$?
  fi
  printf '\n' >&2
  tail -n 20 "$log" >&2 || true
  printf '\n' >&2
  askwell_die "The database migration (alembic upgrade head, run as the stack's migrate service) failed with exit status $rc (its last lines are above, the full output is in $log). The install stopped at this step and is not complete: nothing after it was done. The upgrade runs as one transaction, so the database is left as it was before this step. Run this installer again once the cause is fixed."
  exit 1
}

# ---------------------------------------------------------------- 7. probe

run_probe() {
  askwell_say "Probing this machine's hardware..."
  ASKWELL_PROBE_RESULT_PATH="$DATA_DIR/probe.json" python3 "$INSTALL_PREFIX/askwell-probe" || \
    askwell_say "Probe did not complete; Askwell will fall back to the standard profile on first launch."
}

# ---------------------------------------------------------------- 8. desktop entry + session start

register_desktop_entry() {
  desktop_entry_contents "$BIN_DIR/askwell" "askwell" > "$DESKTOP_DIR/askwell.desktop"
  askwell_say "Applications-menu entry installed: $DESKTOP_DIR/askwell.desktop"
}

register_session_start() {
  systemd_unit_contents "$BIN_DIR/askwell" > "$SYSTEMD_USER_DIR/askwell.service"
  if command -v systemctl >/dev/null 2>&1 && systemctl --user daemon-reload 2>/dev/null && systemctl --user enable askwell.service 2>/dev/null; then
    askwell_say "Askwell registered to start with your session (systemd --user)."
  else
    askwell_say "Wrote $SYSTEMD_USER_DIR/askwell.service but could not enable it (no systemd --user session available right now). Askwell will not start automatically with your session until you run: systemctl --user enable askwell.service"
  fi
}

# The platform half of M7-PACK-DEPLOY-142: the container stack and the native
# inference process are registered as their own systemd --user units, started
# and restarted independently of whether the shell (askwell.service above) is
# ever opened. The shell's own in-process supervisor (M7-TAURI-DEPLOY-183)
# still runs while the shell is open — it attaches to whatever these units
# already have running via state.json's heartbeat rather than racing them.
register_stack_and_inference() {
  systemd_stack_unit_contents "$INSTALL_PREFIX/compose.yaml" "$INSTALL_PREFIX/.env" "$INSTALL_PREFIX" \
    > "$SYSTEMD_USER_DIR/askwell-stack.service"
  systemd_inference_unit_contents "$INSTALL_PREFIX/askwell-inference" "$INSTALL_PREFIX/.env" "$INSTALL_PREFIX" \
    > "$SYSTEMD_USER_DIR/askwell-inference.service"

  if ! command -v systemctl >/dev/null 2>&1 || ! systemctl --user daemon-reload 2>/dev/null; then
    askwell_say "Wrote $SYSTEMD_USER_DIR/askwell-stack.service and askwell-inference.service but could not enable them (no systemd --user session available right now). Enable them with: systemctl --user enable --now askwell-stack.service askwell-inference.service"
    return 0
  fi

  # `restart`, not `enable --now`: on an upgrade the units are already
  # active, and `--now` on an active unit does nothing, so the old version
  # kept running (issue #768). `restart` starts a stopped unit as well.
  if systemctl --user enable askwell-stack.service askwell-inference.service 2>/dev/null \
    && systemctl --user restart askwell-stack.service 2>/dev/null \
    && systemctl --user restart askwell-inference.service 2>/dev/null; then
    askwell_say "Askwell's container stack and native inference process registered to run with your session, independent of the app window (systemd --user)."
  else
    askwell_say "Wrote the stack and inference unit files but could not enable one of them. Check with: systemctl --user status askwell-stack.service askwell-inference.service"
  fi
}

# ---------------------------------------------------------------- 9. install record + launch

record_install() {
  local method="install"
  is_previous_install "$DATA_DIR" && method="upgrade"
  write_install_record "$DATA_DIR" "$VERSION" "$method"
  askwell_say "Install record written: $(install_record_path "$DATA_DIR")"
}

launch() {
  askwell_say "Starting Askwell..."
  ASKWELL_DATA_DIR="$DATA_DIR" "$INSTALL_PREFIX/askwell" &
  disown || true
  askwell_say "Askwell is starting. Its window will open shortly."
}

main() {
  askwell_say "Installing Askwell $VERSION"
  check_runtime
  check_compose_provider
  check_openmp_runtime
  check_disk_space
  check_previous_install
  check_artefacts
  place_files
  load_images
  create_data_dirs
  stop_previous_stack
  migrate_database
  run_probe
  register_desktop_entry
  register_stack_and_inference
  register_session_start
  record_install
  launch
  askwell_say "Done. Askwell is also available any time from your applications menu."
}

# Run, not sourced: install.test.sh sources this file to exercise one step.
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  main "$@"
fi
