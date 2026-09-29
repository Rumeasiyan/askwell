#!/usr/bin/env bash
# Tests for scripts/release-artefact.sh. M9-REL-DEPLOY-214.
#
# Builds a fake repository tree with every input the script reads, so no
# real shell, image or interface build is needed. The check that matters
# most is the last one per platform: the artefact, unpacked, passes that
# platform's own installer's `check_artefacts` — the function a user's
# machine runs before copying anything.
set -Eeuo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
PASS=0; FAIL=0

ok()   { PASS=$((PASS+1)); printf '  ok    %s\n' "$1"; }
bad()  { FAIL=$((FAIL+1)); printf '  FAIL  %s\n' "$1"; }
check(){ if [ "$2" = "$3" ]; then ok "$1"; else bad "$1 (want '$3', got '$2')"; fi; }

printf 'release-artefact\n'

# A repository tree holding what a release build has produced by the time
# release-artefact.sh runs: the real deploy/ tree, plus stand-ins for the
# built interface, the three shells and the saved images.
fake_root() {
  local root="$1"
  mkdir -p "$root"
  printf '9.8.7\n' > "$root/VERSION"
  for f in compose.yaml .env.example LICENSE NOTICES.md README.md; do printf '%s\n' "$f" > "$root/$f"; done
  mkdir -p "$root/docs"; printf 'installing\n' > "$root/docs/installing.md"
  cp -R "$REPO/deploy" "$root/deploy"
  mkdir -p "$root/deploy/inference/__pycache__"; : > "$root/deploy/inference/__pycache__/x.pyc"
  mkdir -p "$root/web/out/_next"; printf '<html>\n' > "$root/web/out/index.html"; : > "$root/web/out/_next/app.js"
  local rel="$root/web/src-tauri/target/release"
  mkdir -p "$rel/bundle/macos/Askwell.app/Contents/MacOS"
  printf '#!/bin/sh\n' > "$rel/askwell-shell"; chmod +x "$rel/askwell-shell"
  printf 'MZ\n' > "$rel/askwell-shell.exe"
  printf '#!/bin/sh\n' > "$rel/bundle/macos/Askwell.app/Contents/MacOS/askwell-shell"
  chmod +x "$rel/bundle/macos/Askwell.app/Contents/MacOS/askwell-shell"
  mkdir -p "$root/images"
  printf 'image\n' > "$root/images/localhost_askwell-api_dev.tar"
  printf 'image\n' > "$root/images/docker.io_redis_8-alpine.tar"
  # What scripts/fetch-llama-cpp.sh writes, per platform (M10-FIX-DEPLOY-222).
  local p
  for p in linux macos windows; do mkdir -p "$root/llama.cpp/$p/gpu"; done
  mkdir -p "$root/llama.cpp/linux/cpu" "$root/llama.cpp/windows/cpu"
  for f in linux/gpu/llama-server linux/cpu/llama-server macos/gpu/llama-server; do
    printf '#!/bin/sh\n' > "$root/llama.cpp/$f"; chmod +x "$root/llama.cpp/$f"
  done
  printf 'MZ\n' > "$root/llama.cpp/windows/gpu/llama-server.exe"
  printf 'MZ\n' > "$root/llama.cpp/windows/cpu/llama-server.exe"
  printf 'MIT\n' > "$root/llama.cpp/linux/gpu/LICENSE"
}

run() { ASKWELL_RELEASE_ROOT="$ROOT" "$HERE/release-artefact.sh" "$@" "$ROOT/llama.cpp/$1"; }

# The installer's own check, lifted out of install.sh and run against the
# unpacked artefact as REPO_ROOT.
installer_accepts() {
  local platform="$1" tree="$2" section
  section="$(mktemp)"
  {
    printf 'askwell_say() { :; }\naskwell_die() { return 1; }\n'
    printf 'REPO_ROOT=%q\n' "$tree"
    grep -E '^(SHELL_BIN|SHELL_BUNDLE)=' "$tree/deploy/$platform/install.sh"
    sed -n '/^check_artefacts() {/,/^}/p' "$tree/deploy/$platform/install.sh"
  } > "$section"
  ( . "$section"; check_artefacts ) >/dev/null 2>&1 && r=0 || r=1
  rm -f "$section"
  return "$r"
}

# --- Linux ------------------------------------------------------------------
T="$(mktemp -d)"; ROOT="$T/root"; fake_root "$ROOT"
run linux x86_64 "$ROOT/images" "$T/out" >/dev/null && r=0 || r=1
check "assembles the Linux artefact" "$r" 0
A="$T/out/askwell-9.8.7-linux-x86_64.tar.gz"
[ -f "$A" ] && r=0 || r=1
check "names it askwell-<VERSION>-linux-<arch>.tar.gz" "$r" 0
mkdir -p "$T/x"; tar -xzf "$A" -C "$T/x"
X="$T/x/askwell-9.8.7-linux-x86_64"
[ -x "$X/web/src-tauri/target/release/askwell-shell" ] && r=0 || r=1
check "the shell keeps its executable bit" "$r" 0
[ -f "$X/web/out/_next/app.js" ] && r=0 || r=1
check "the whole interface ships, not only index.html" "$r" 0
check "both image archives ship" "$(find "$X/images" -name '*.tar' | wc -l | tr -d ' ')" 2
[ -f "$X/deploy/linux/install.sh" ] && r=0 || r=1
check "the Linux installer ships" "$r" 0
[ -e "$X/deploy/linux/install.test.sh" ] && r=0 || r=1
check "the installer's own tests do not ship" "$r" 1
[ -e "$X/deploy/windows" ] || [ -e "$X/deploy/macos" ] && r=0 || r=1
check "other platforms' installers do not ship" "$r" 1
[ -e "$X/web/src-tauri/target/release/askwell-shell.exe" ] && r=0 || r=1
check "other platforms' shells do not ship" "$r" 1
[ -e "$X/deploy/inference/__pycache__" ] && r=0 || r=1
check "no __pycache__ ships" "$r" 1
[ -f "$X/LICENSE" ] && [ -f "$X/NOTICES.md" ] && r=0 || r=1
check "the licence and notices ship (C9)" "$r" 0
[ -x "$X/deploy/inference/llama.cpp/gpu/llama-server" ] && [ -x "$X/deploy/inference/llama.cpp/cpu/llama-server" ] && r=0 || r=1
check "both llama.cpp builds ship beside askwell-inference, executable" "$r" 0
[ -f "$X/deploy/inference/llama.cpp/gpu/LICENSE" ] && r=0 || r=1
check "with llama.cpp's own licence (C9)" "$r" 0
installer_accepts linux "$X" && r=0 || r=1
check "deploy/linux/install.sh's check_artefacts accepts the unpacked artefact" "$r" 0
rm "$X/web/out/index.html"
installer_accepts linux "$X" && r=0 || r=1
check "and refuses it once the interface is removed (the check is live)" "$r" 1
rm -rf "$T"

# --- macOS ------------------------------------------------------------------
T="$(mktemp -d)"; ROOT="$T/root"; fake_root "$ROOT"
run macos aarch64 "$ROOT/images" "$T/out" >/dev/null && r=0 || r=1
check "assembles the macOS artefact" "$r" 0
A="$T/out/askwell-9.8.7-macos-arm64.tar.gz"
[ -f "$A" ] && r=0 || r=1
check "normalises aarch64 to arm64 in the name" "$r" 0
mkdir -p "$T/x"; tar -xzf "$A" -C "$T/x"
X="$T/x/askwell-9.8.7-macos-arm64"
[ -x "$X/web/src-tauri/target/release/bundle/macos/Askwell.app/Contents/MacOS/askwell-shell" ] && r=0 || r=1
check "the .app ships whole, executable intact" "$r" 0
[ -x "$X/deploy/inference/llama.cpp/gpu/llama-server" ] && [ ! -e "$X/deploy/inference/llama.cpp/cpu" ] && r=0 || r=1
check "the Metal build ships, and no CPU build beside it" "$r" 0
installer_accepts macos "$X" && r=0 || r=1
check "deploy/macos/install.sh's check_artefacts accepts the unpacked artefact" "$r" 0
rm -rf "$T"

# --- Windows ----------------------------------------------------------------
if command -v 7z >/dev/null 2>&1 || command -v zip >/dev/null 2>&1; then
  T="$(mktemp -d)"; ROOT="$T/root"; fake_root "$ROOT"
  run windows amd64 "$ROOT/images" "$T/out" >/dev/null && r=0 || r=1
  check "assembles the Windows artefact" "$r" 0
  A="$T/out/askwell-9.8.7-windows-x86_64.zip"
  [ -f "$A" ] && r=0 || r=1
  check "names it .zip, amd64 normalised to x86_64" "$r" 0
  listing="$(unzip -l "$A" 2>/dev/null || 7z l "$A")"
  case "$listing" in *"askwell-9.8.7-windows-x86_64/web/src-tauri/target/release/askwell-shell.exe"*) r=0 ;; *) r=1 ;; esac
  check "the .exe is where install.ps1 looks for it" "$r" 0
  case "$listing" in *"deploy/windows/install.ps1"*) r=0 ;; *) r=1 ;; esac
  check "the Windows installer ships" "$r" 0
  case "$listing" in *"install.test.ps1"*) r=1 ;; *) r=0 ;; esac
  check "its tests do not" "$r" 0
  case "$listing" in *"deploy/inference/llama.cpp/gpu/llama-server.exe"*"deploy/inference/llama.cpp/cpu/llama-server.exe"*|*"deploy/inference/llama.cpp/cpu/llama-server.exe"*"deploy/inference/llama.cpp/gpu/llama-server.exe"*) r=0 ;; *) r=1 ;; esac
  check "both llama.cpp builds ship" "$r" 0
  rm -rf "$T"
else
  bad "neither 7z nor zip is installed, so the Windows artefact was not tested"
fi

# --- refusals ---------------------------------------------------------------
T="$(mktemp -d)"; ROOT="$T/root"; fake_root "$ROOT"
rm -rf "$ROOT/web/out"
out="$(run linux x86_64 "$ROOT/images" "$T/out" 2>&1)" && r=0 || r=1
check "refuses without the built interface" "$r" 1
case "$out" in *"missing $ROOT/web/out/index.html"*) r=0 ;; *) r=1 ;; esac
check "and names the missing file" "$r" 0
[ -e "$T/out/askwell-9.8.7-linux-x86_64.tar.gz" ] && r=0 || r=1
check "and writes nothing" "$r" 1
rm -rf "$T"

T="$(mktemp -d)"; ROOT="$T/root"; fake_root "$ROOT"
rm -f "$ROOT/web/src-tauri/target/release/askwell-shell.exe"
out="$(run windows x86_64 "$ROOT/images" "$T/out" 2>&1)" && r=0 || r=1
check "refuses without the platform's shell" "$r" 1
case "$out" in *"askwell-shell.exe"*"windows artefact not assembled"*) r=0 ;; *) r=1 ;; esac
check "and names both the shell and the platform" "$r" 0
rm -rf "$T"

T="$(mktemp -d)"; ROOT="$T/root"; fake_root "$ROOT"
rm -rf "$ROOT/llama.cpp/linux/cpu"
out="$(run linux x86_64 "$ROOT/images" "$T/out" 2>&1)" && r=0 || r=1
check "refuses without a pinned llama.cpp build" "$r" 1
case "$out" in *"missing llama.cpp build $ROOT/llama.cpp/linux/cpu/llama-server"*"fetch-llama-cpp.sh linux"*) r=0 ;; *) r=1 ;; esac
check "and names the build and the command that fetches it" "$r" 0
rm -rf "$T"

T="$(mktemp -d)"; ROOT="$T/root"; fake_root "$ROOT"
rm -f "$ROOT/images/"*.tar
out="$(run linux x86_64 "$ROOT/images" "$T/out" 2>&1)" && r=0 || r=1
check "refuses with no container images" "$r" 1
case "$out" in *"no container images"*) r=0 ;; *) r=1 ;; esac
check "and says so" "$r" 0
rm -rf "$T"

T="$(mktemp -d)"; ROOT="$T/root"; fake_root "$ROOT"
out="$(ASKWELL_RELEASE_MAX_ASSET_BYTES=10 run linux x86_64 "$ROOT/images" "$T/out" 2>&1)" && r=0 || r=1
check "refuses an artefact over the release-asset limit" "$r" 1
[ -e "$T/out/askwell-9.8.7-linux-x86_64.tar.gz" ] && r=0 || r=1
check "and removes it" "$r" 1
run solaris x86_64 "$ROOT/images" "$T/out" >/dev/null 2>&1 && r=0 || r=1
check "refuses an unknown platform" "$r" 1
run linux sparc "$ROOT/images" "$T/out" >/dev/null 2>&1 && r=0 || r=1
check "refuses an unknown architecture" "$r" 1
rm -rf "$T"

printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
