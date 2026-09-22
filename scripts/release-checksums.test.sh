#!/usr/bin/env bash
# Tests for scripts/release-checksums.sh. M7-TAURI-DEPLOY-184.
set -Eeuo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PASS=0; FAIL=0

ok()   { PASS=$((PASS+1)); printf '  ok    %s\n' "$1"; }
bad()  { FAIL=$((FAIL+1)); printf '  FAIL  %s\n' "$1"; }
check(){ if [ "$2" = "$3" ]; then ok "$1"; else bad "$1 (want '$3', got '$2')"; fi; }

printf 'release-checksums\n'

# --- happy path ---------------------------------------------------------
D="$(mktemp -d)"
printf 'askwell-0.7.10-linux.rpm contents\n' > "$D/askwell-0.7.10-linux.rpm"
printf 'askwell-0.7.10.dmg contents\n' > "$D/askwell-0.7.10.dmg"

"$HERE/release-checksums.sh" "$D" >/dev/null && r=0 || r=1
check "runs against a populated directory" "$r" 0
[ -f "$D/SHA256SUMS" ] && r=0 || r=1
check "writes SHA256SUMS" "$r" 0

LINES=$(wc -l < "$D/SHA256SUMS")
check "one line per artefact" "$LINES" 2

if command -v sha256sum >/dev/null 2>&1; then
  (cd "$D" && sha256sum -c SHA256SUMS >/dev/null 2>&1) && r=0 || r=1
  check "checksums verify against the files" "$r" 0
fi

# --- deterministic ordering ---------------------------------------------
FIRST="$(cat "$D/SHA256SUMS")"
rm "$D/SHA256SUMS"
"$HERE/release-checksums.sh" "$D" >/dev/null
SECOND="$(cat "$D/SHA256SUMS")"
check "output is stable across runs" "$FIRST" "$SECOND"

rm -rf "$D"

# --- refuses an empty directory -----------------------------------------
D="$(mktemp -d)"
"$HERE/release-checksums.sh" "$D" >/dev/null 2>&1 && r=0 || r=1
check "refuses an empty directory" "$r" 1
[ -f "$D/SHA256SUMS" ] && r=0 || r=1
check "does not write SHA256SUMS for an empty directory" "$r" 1
rm -rf "$D"

# --- refuses a missing directory ----------------------------------------
"$HERE/release-checksums.sh" "/no/such/dir" >/dev/null 2>&1 && r=0 || r=1
check "refuses a nonexistent directory" "$r" 1

# --- ignores a pre-existing SHA256SUMS on rerun --------------------------
D="$(mktemp -d)"
printf 'a\n' > "$D/a.bin"
"$HERE/release-checksums.sh" "$D" >/dev/null
"$HERE/release-checksums.sh" "$D" >/dev/null
LINES=$(wc -l < "$D/SHA256SUMS")
check "SHA256SUMS never lists itself, even on rerun" "$LINES" 1
rm -rf "$D"

printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
