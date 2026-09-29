#!/usr/bin/env bash
# Fetches the llama.cpp builds one platform's release artefact carries.
# M10-FIX-DEPLOY-222.
#
# Usage: scripts/fetch-llama-cpp.sh <linux|windows|macos> <arch> <dest>
#
# Writes <dest>/gpu/ and, where one is pinned, <dest>/cpu/: each the whole
# unpacked release archive, with llama-server (llama-server.exe on Windows)
# at its top and llama.cpp's own LICENSE beside it. scripts/release-artefact.sh
# ships <dest> as deploy/inference/llama.cpp, the installers place it next to
# askwell-inference, and the supervisor chooses between the two builds at
# every start (see that script's `_binaries`).
#
# Every archive is checked against deploy/inference/llama-cpp.lock before it
# is unpacked, and <dest> is replaced only once every build for the platform
# has been fetched and checked — a failed run leaves whatever was there.
#
# Runs in the release workflow, on the network, like `scripts/dev.sh lock`:
# this is build time. Nothing it fetches is fetched on a user's machine (C1).
# Needs curl, tar, unzip, and sha256sum or shasum.

set -Eeuo pipefail

die() { printf 'fetch-llama-cpp: %s\n' "$1" >&2; exit 1; }

[ $# -eq 3 ] || die "usage: fetch-llama-cpp.sh <linux|windows|macos> <arch> <dest>"

PLATFORM="$1"
ARCH="$2"
DEST="$3"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCK="${ASKWELL_LLAMA_CPP_LOCK:-$ROOT/deploy/inference/llama-cpp.lock}"
# Overridable so the tests can serve archives from a directory (file://).
RELEASES="${ASKWELL_LLAMA_CPP_RELEASES_URL:-https://github.com/ggml-org/llama.cpp/releases/download}"
SOURCE="${ASKWELL_LLAMA_CPP_SOURCE_URL:-https://raw.githubusercontent.com/ggml-org/llama.cpp}"

case "$PLATFORM" in
  linux|macos) EXE="llama-server" ;;
  windows)     EXE="llama-server.exe" ;;
  *) die "unknown platform '$PLATFORM' (use linux, windows or macos)" ;;
esac

case "$ARCH" in
  x86_64|amd64) ARCH="x86_64" ;;
  arm64|aarch64) ARCH="arm64" ;;
  *) die "unknown architecture '$ARCH' (use x86_64 or arm64)" ;;
esac

[ -f "$LOCK" ] || die "no pin file at $LOCK"

sha256() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | cut -d' ' -f1
  else
    shasum -a 256 "$1" | cut -d' ' -f1
  fi
}

fetch() {
  curl -fsSL --retry 3 -o "$2" "$1" || die "could not download $1"
}

# Downloads $1 to $2 and refuses it unless its digest is $3.
fetch_checked() {
  local url="$1" file="$2" want="$3" got
  fetch "$url" "$file"
  got="$(sha256 "$file")"
  [ "$got" = "$want" ] || die "$(basename "$file") does not match its pin: expected sha256 $want, got $got. Nothing was placed."
}

TAG="$(awk '$1 == "tag" { print $2 }' "$LOCK")"
LICENSE_SHA="$(awk '$1 == "license" { print $3 }' "$LOCK")"
[ -n "$TAG" ] || die "$LOCK names no tag"
[ -n "$LICENSE_SHA" ] || die "$LOCK pins no LICENSE digest"

ROWS="$(awk -v p="$PLATFORM" -v a="$ARCH" '$1 == p && $2 == a { print $3, $4, $5 }' "$LOCK")"
[ -n "$ROWS" ] || die "no llama.cpp build is pinned for $PLATFORM $ARCH in $LOCK"
case "$ROWS" in
  "gpu "*|*$'\n'"gpu "*) ;;
  *) die "no gpu build is pinned for $PLATFORM $ARCH in $LOCK" ;;
esac

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/out"

while read -r variant asset want; do
  [ -n "$variant" ] || continue
  archive="$WORK/$asset"
  fetch_checked "$RELEASES/$TAG/$asset" "$archive" "$want"

  unpacked="$WORK/unpacked-$variant"
  mkdir -p "$unpacked"
  case "$asset" in
    *.tar.gz) tar -xzf "$archive" -C "$unpacked" ;;
    *.zip)    unzip -q "$archive" -d "$unpacked" ;;
    *) die "do not know how to unpack $asset" ;;
  esac

  # The Linux and macOS tarballs hold one top-level directory; the Windows
  # zips are flat. Either way the build's own files end up at the top.
  top="$unpacked"
  entries="$(find "$unpacked" -mindepth 1 -maxdepth 1)"
  if [ "$(printf '%s\n' "$entries" | wc -l | tr -d ' ')" -eq 1 ] && [ -d "$entries" ]; then
    top="$entries"
  fi
  [ -f "$top/$EXE" ] || die "$asset has no $EXE at its top; the pinned build is not what this script expects"
  chmod +x "$top/$EXE"
  mv "$top" "$WORK/out/$variant"

  if [ ! -f "$WORK/out/$variant/LICENSE" ]; then
    [ -f "$WORK/LICENSE" ] || fetch_checked "$SOURCE/$TAG/LICENSE" "$WORK/LICENSE" "$LICENSE_SHA"
    cp "$WORK/LICENSE" "$WORK/out/$variant/LICENSE"
  fi
  printf 'fetch-llama-cpp: %s %s %s: %s (sha256 ok)\n' "$PLATFORM" "$ARCH" "$variant" "$asset"
done <<EOF_ROWS
$ROWS
EOF_ROWS

rm -rf "$DEST"
mkdir -p "$(dirname "$DEST")"
mv "$WORK/out" "$DEST"
printf 'fetch-llama-cpp: llama.cpp %s for %s %s placed in %s\n' "$TAG" "$PLATFORM" "$ARCH" "$DEST"
