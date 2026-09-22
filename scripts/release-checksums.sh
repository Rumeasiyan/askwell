#!/usr/bin/env bash
# Generates SHA256SUMS for a directory of release artefacts. M7-TAURI-DEPLOY-184.
#
# Runs on the host, not inside a container image — it is a release-time step,
# not part of the application toolchain, and needs nothing beyond coreutils
# (sha256sum on Linux, shasum on macOS), which every release host already has.
#
# Usage: scripts/release-checksums.sh <artefact-dir>
#
# Writes <artefact-dir>/SHA256SUMS, one line per file in the directory
# (excluding SHA256SUMS itself), sorted by filename so the output is
# deterministic and diffable across runs. Refuses to run against an empty
# directory rather than silently publishing an empty file — an empty
# SHA256SUMS looks identical to "everything verified" and to "nothing was
# built", and only one of those is safe to publish.

set -Eeuo pipefail

die() { printf 'release-checksums: %s\n' "$1" >&2; exit 1; }

[ $# -eq 1 ] || die "usage: release-checksums.sh <artefact-dir>"

DIR="$1"
[ -d "$DIR" ] || die "no such directory: $DIR"

if command -v sha256sum >/dev/null 2>&1; then
  HASH_CMD=(sha256sum)
elif command -v shasum >/dev/null 2>&1; then
  HASH_CMD=(shasum -a 256)
else
  die "neither sha256sum nor shasum is on PATH"
fi

cd "$DIR"

mapfile -t FILES < <(find . -maxdepth 1 -type f ! -name SHA256SUMS ! -name '.*' -exec basename {} \; | sort)

[ "${#FILES[@]}" -gt 0 ] || die "no artefacts in $DIR — refusing to publish an empty SHA256SUMS"

"${HASH_CMD[@]}" "${FILES[@]}" > SHA256SUMS

printf 'wrote %s/SHA256SUMS covering %d artefact(s):\n' "$DIR" "${#FILES[@]}"
cat SHA256SUMS
