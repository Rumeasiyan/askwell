#!/usr/bin/env bash
# Tests for scripts/fetch-llama-cpp.sh. M10-FIX-DEPLOY-222.
#
# Serves stand-in archives from a directory over file://, shaped like the
# real release assets — the Linux and macOS tarballs with one top-level
# directory and a LICENSE, the Windows zips flat and without one — and pins
# their digests in a stand-in lock. No network.
set -Eeuo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PASS=0; FAIL=0

ok()   { PASS=$((PASS+1)); printf '  ok    %s\n' "$1"; }
bad()  { FAIL=$((FAIL+1)); printf '  FAIL  %s\n' "$1"; }
check(){ if [ "$2" = "$3" ]; then ok "$1"; else bad "$1 (want '$3', got '$2')"; fi; }

printf 'fetch-llama-cpp\n'

sha() { sha256sum "$1" | cut -d' ' -f1; }

T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
SERVE="$T/serve/b1"; SOURCE="$T/source/b1"
mkdir -p "$SERVE" "$SOURCE"
printf 'MIT License\n' > "$SOURCE/LICENSE"

tarball() {
  local name="$1" stage="$T/stage-$1"
  mkdir -p "$stage/llama-b1"
  printf '#!/bin/sh\necho %s\n' "$name" > "$stage/llama-b1/llama-server"
  chmod -x "$stage/llama-b1/llama-server"
  printf 'MIT License\n' > "$stage/llama-b1/LICENSE"
  tar -czf "$SERVE/$name" -C "$stage" llama-b1
}

zipfile() {
  local name="$1" stage="$T/stage-$1"
  mkdir -p "$stage"
  printf 'MZ\n' > "$stage/llama-server.exe"
  printf 'Apache\n' > "$stage/LICENSE-LLVM-OpenMP"
  (cd "$stage" && zip -q "$SERVE/$name" llama-server.exe LICENSE-LLVM-OpenMP)
}

tarball linux-cpu.tar.gz
tarball linux-gpu.tar.gz
tarball mac.tar.gz
zipfile win-cpu.zip
zipfile win-gpu.zip

LOCK="$T/llama-cpp.lock"
{
  printf 'tag b1\n'
  printf 'license LICENSE %s\n' "$(sha "$SOURCE/LICENSE")"
  printf 'linux x86_64 cpu linux-cpu.tar.gz %s\n' "$(sha "$SERVE/linux-cpu.tar.gz")"
  printf 'linux x86_64 gpu linux-gpu.tar.gz %s\n' "$(sha "$SERVE/linux-gpu.tar.gz")"
  printf 'windows x86_64 cpu win-cpu.zip %s\n' "$(sha "$SERVE/win-cpu.zip")"
  printf 'windows x86_64 gpu win-gpu.zip %s\n' "$(sha "$SERVE/win-gpu.zip")"
  printf 'macos arm64 gpu mac.tar.gz %s\n' "$(sha "$SERVE/mac.tar.gz")"
} > "$LOCK"

run() {
  ASKWELL_LLAMA_CPP_LOCK="$LOCK" \
  ASKWELL_LLAMA_CPP_RELEASES_URL="file://$T/serve" \
  ASKWELL_LLAMA_CPP_SOURCE_URL="file://$T/source" \
    "$HERE/fetch-llama-cpp.sh" "$@"
}

# --- Linux: both builds, flattened, executable, licensed ----------------------
run linux amd64 "$T/out/linux" >/dev/null && r=0 || r=1
check "fetches the Linux builds (amd64 read as x86_64)" "$r" 0
[ -x "$T/out/linux/gpu/llama-server" ] && [ -x "$T/out/linux/cpu/llama-server" ] && r=0 || r=1
check "llama-server is at the top of each build, executable" "$r" 0
check "the GPU build is the GPU archive" "$(sh "$T/out/linux/gpu/llama-server")" "linux-gpu.tar.gz"
[ -f "$T/out/linux/gpu/LICENSE" ] && r=0 || r=1
check "the archive's own LICENSE is kept" "$r" 0

# --- Windows: flat zips, LICENSE fetched from the tag ---------------------------
run windows x86_64 "$T/out/windows" >/dev/null && r=0 || r=1
check "fetches the Windows builds" "$r" 0
[ -f "$T/out/windows/gpu/llama-server.exe" ] && [ -f "$T/out/windows/cpu/llama-server.exe" ] && r=0 || r=1
check "llama-server.exe is at the top of each build" "$r" 0
[ -f "$T/out/windows/gpu/LICENSE" ] && [ -f "$T/out/windows/cpu/LICENSE" ] && r=0 || r=1
check "llama.cpp's LICENSE is placed beside a build that lacks it (C9)" "$r" 0
[ -f "$T/out/windows/gpu/LICENSE-LLVM-OpenMP" ] && r=0 || r=1
check "the OpenMP runtime's licence stays with it" "$r" 0

# --- macOS: the Metal build only ------------------------------------------------
run macos aarch64 "$T/out/macos" >/dev/null && r=0 || r=1
check "fetches the macOS build (aarch64 read as arm64)" "$r" 0
[ -x "$T/out/macos/gpu/llama-server" ] && [ ! -e "$T/out/macos/cpu" ] && r=0 || r=1
check "one build, no CPU build beside it" "$r" 0

# --- refusals -------------------------------------------------------------------
mkdir -p "$T/out/kept/gpu"; printf 'old\n' > "$T/out/kept/gpu/marker"
cp "$SERVE/linux-cpu.tar.gz" "$T/good.tar.gz"
printf 'tampered\n' >> "$SERVE/linux-cpu.tar.gz"
out="$(run linux x86_64 "$T/out/kept" 2>&1)" && r=0 || r=1
check "refuses an archive that does not match its pin" "$r" 1
case "$out" in *"linux-cpu.tar.gz does not match its pin"*) r=0 ;; *) r=1 ;; esac
check "and names it" "$r" 0
[ -f "$T/out/kept/gpu/marker" ] && r=0 || r=1
check "and leaves what was already there untouched" "$r" 0
cp "$T/good.tar.gz" "$SERVE/linux-cpu.tar.gz"

out="$(run linux arm64 "$T/out/arm" 2>&1)" && r=0 || r=1
check "refuses a platform and architecture with no pin" "$r" 1
case "$out" in *"no llama.cpp build is pinned for linux arm64"*) r=0 ;; *) r=1 ;; esac
check "and says which" "$r" 0

run solaris x86_64 "$T/out/x" >/dev/null 2>&1 && r=0 || r=1
check "refuses an unknown platform" "$r" 1

printf 'macos arm64 cpu mac.tar.gz %s\n' "$(sha "$SERVE/mac.tar.gz")" > "$T/cpu-only.lock"
sed -n '1,2p' "$LOCK" | cat - "$T/cpu-only.lock" > "$T/no-gpu.lock"
out="$(ASKWELL_LLAMA_CPP_LOCK="$T/no-gpu.lock" ASKWELL_LLAMA_CPP_RELEASES_URL="file://$T/serve" \
  "$HERE/fetch-llama-cpp.sh" macos arm64 "$T/out/y" 2>&1)" && r=0 || r=1
check "refuses a pin set with no GPU build" "$r" 1

printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
