#!/usr/bin/env bash
# Assembles one platform's release artefact from what the release workflow
# has already built. M9-REL-DEPLOY-214.
#
# Usage: scripts/release-artefact.sh <linux|windows|macos> <arch> <images-dir> <out-dir>
#
# Writes <out-dir>/askwell-<VERSION>-<platform>-<arch>.tar.gz (.zip for
# Windows). Inside is one directory with the layout deploy/<platform>/'s
# installer already expects of REPO_ROOT (see the header of
# deploy/linux/install.sh): a trimmed export of the repository, not a new
# bundle format, plus two things the repository does not hold —
#
#   web/out/            the built interface, which compose.yaml mounts (#766)
#   images/*.tar        every container image compose.yaml names, saved, so
#                       the installer loads them rather than building from
#                       source or pulling from a registry
#
# and the platform's shell at the path its installer looks for it.
#
# Builds nothing. Every input is checked before anything is copied, and every
# missing one is named, so a failed release job says what it lacked rather
# than producing an artefact an installer will refuse on someone's machine.
#
# Runs on the release host (the workflow's Linux job), not inside a container
# image, and needs only coreutils, tar, gzip and — for Windows — zip or 7z.
# `<arch>` is passed rather than read from `uname -m` because the shells for
# all three platforms are built elsewhere and assembled here.

set -Eeuo pipefail

die() { printf 'release-artefact: %s\n' "$1" >&2; exit 1; }

[ $# -eq 4 ] || die "usage: release-artefact.sh <linux|windows|macos> <arch> <images-dir> <out-dir>"

PLATFORM="$1"
ARCH="$2"
IMAGES="$3"
OUT="$4"
ROOT="${ASKWELL_RELEASE_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

# GitHub refuses a release asset of 2 GiB or more. Failing here names the
# platform; failing at upload leaves a half-uploaded draft.
MAX_ASSET_BYTES="${ASKWELL_RELEASE_MAX_ASSET_BYTES:-2147483647}"

case "$PLATFORM" in
  linux)   SHELL_REL="web/src-tauri/target/release/askwell-shell";                EXT="tar.gz" ;;
  windows) SHELL_REL="web/src-tauri/target/release/askwell-shell.exe";            EXT="zip" ;;
  macos)   SHELL_REL="web/src-tauri/target/release/bundle/macos/Askwell.app";     EXT="tar.gz" ;;
  *) die "unknown platform '$PLATFORM' (use linux, windows or macos)" ;;
esac

case "$ARCH" in
  x86_64|amd64) ARCH="x86_64" ;;
  arm64|aarch64) ARCH="arm64" ;;
  *) die "unknown architecture '$ARCH' (use x86_64 or arm64)" ;;
esac

[ -f "$ROOT/VERSION" ] || die "no VERSION at $ROOT"
VERSION="$(tr -d '[:space:]' < "$ROOT/VERSION")"
[ -n "$VERSION" ] || die "VERSION at $ROOT is empty"

NAME="askwell-$VERSION-$PLATFORM-$ARCH"

# What the installer reads from REPO_ROOT, plus what a person reading the
# download needs: the licence and notices it ships under (C9), and how to
# install and verify it.
REQUIRED="VERSION compose.yaml .env.example LICENSE NOTICES.md README.md docs/installing.md
deploy/postgres deploy/sandbox deploy/redis
deploy/probe/askwell-probe deploy/inference/askwell-inference
deploy/$PLATFORM web/out/index.html $SHELL_REL"

missing=0
for rel in $REQUIRED; do
  if [ ! -e "$ROOT/$rel" ]; then
    printf 'release-artefact: missing %s\n' "$ROOT/$rel" >&2
    missing=1
  fi
done

images_found=0
if [ -d "$IMAGES" ]; then
  for f in "$IMAGES"/*.tar; do
    [ -f "$f" ] && images_found=$((images_found + 1))
  done
fi
if [ "$images_found" -eq 0 ]; then
  printf 'release-artefact: no container images (*.tar) in %s\n' "$IMAGES" >&2
  missing=1
fi

[ "$missing" -eq 0 ] || die "$PLATFORM artefact not assembled: inputs missing (listed above)"

mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
T="$STAGE/$NAME"

# The web/out entry names index.html only so its absence is caught; the
# whole directory ships.
for rel in $REQUIRED; do
  [ "$rel" = "web/out/index.html" ] && rel="web/out"
  mkdir -p "$T/$(dirname "$rel")"
  cp -Rp "$ROOT/$rel" "$T/$rel"
done

# The installers' own logic tests are not something a user runs.
find "$T/deploy" \( -name '*.test.sh' -o -name '*.test.ps1' \) -exec rm -f {} +
find "$T" -name __pycache__ -type d -prune -exec rm -rf {} +

# Hard links where the filesystem allows: the images are most of the
# artefact's size, and the stage is deleted as soon as it is packed.
mkdir -p "$T/images"
for f in "$IMAGES"/*.tar; do
  ln "$f" "$T/images/" 2>/dev/null || cp -p "$f" "$T/images/"
done

DEST="$OUT/$NAME.$EXT"
rm -f "$DEST"
case "$EXT" in
  tar.gz)
    (cd "$STAGE" && tar -czf "$DEST" "$NAME")
    ;;
  zip)
    if command -v 7z >/dev/null 2>&1; then
      (cd "$STAGE" && 7z a -tzip -bd "$DEST" "$NAME" >/dev/null)
    elif command -v zip >/dev/null 2>&1; then
      (cd "$STAGE" && zip -qr "$DEST" "$NAME")
    else
      die "neither 7z nor zip is on PATH; cannot write $DEST"
    fi
    ;;
esac

size="$(wc -c < "$DEST" | tr -d '[:space:]')"
if [ "$size" -gt "$MAX_ASSET_BYTES" ]; then
  rm -f "$DEST"
  die "$PLATFORM artefact is $size bytes, over the $MAX_ASSET_BYTES-byte release-asset limit"
fi

printf 'wrote %s (%s bytes, %d image archive(s))\n' "$DEST" "$size" "$images_found"
