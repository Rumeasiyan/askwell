#!/usr/bin/env bash
# Tests for the build runner's gate.
#
# The gate decides whether a ticket's work is acceptable, so a gate that
# returns success when it should not is worse than having none: it converts
# "nobody checked" into "something checked and approved". Before this file
# existed, `run_gate` returned 0 unconditionally.
#
#   bash scripts/gate.test.sh

set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1

PASSED=0; FAILED=0
ok()   { PASSED=$((PASSED+1)); printf '  \033[32mpass\033[0m  %s\n' "$1"; }
bad()  { FAILED=$((FAILED+1)); printf '  \033[31mFAIL\033[0m  %s\n' "$1"; }
check() { if [ "$2" = "$3" ]; then ok "$1"; else bad "$1 (expected '$3', got '$2')"; fi; }

# The gate's own functions, without the runner's ticket machinery.
BOLD=""; RESET=""; DIM=""
say() { :; }
sed -n '/^# --- gate ---/,/^# --- main ---/p' scripts/build-runner.sh | head -n -1 > /tmp/askwell-gate-section.sh
# shellcheck disable=SC1091
. /tmp/askwell-gate-section.sh

log() { printf '%s\n' "$1" > /tmp/askwell-gate-log.txt; printf '/tmp/askwell-gate-log.txt'; }

printf '\nA summary line with a count\n'

check "216 passed is positive" \
  "$(gate_count_is_positive "$(log '216 passed, 36 deselected in 8.4s')" && echo yes || echo no)" yes

# The failure most likely to look like a success: a collection error means
# nothing ran, and pytest still exits 0 in some versions.
check "0 passed is not positive" \
  "$(gate_count_is_positive "$(log '0 passed, 3 warnings in 0.1s')" && echo yes || echo no)" no

check "no tests ran is not positive" \
  "$(gate_count_is_positive "$(log 'no tests ran in 0.01s')" && echo yes || echo no)" no

check "a failure line is not positive" \
  "$(gate_count_is_positive "$(log '3 failed, 0 passed in 1.2s')" && echo yes || echo no)" no

check "some passing alongside failures is still positive" \
  "$(gate_count_is_positive "$(log '2 failed, 14 passed in 1.2s')" && echo yes || echo no)" yes

printf '\nEvery gate row is a real command with a real expectation\n'

rows=$(printf '%s' "$GATE_ROWS" | grep -c '|' || true)
check "there are gate rows at all" "$([ "$rows" -ge 5 ] && echo yes || echo no)" yes

while IFS='|' read -r name command expect forbid needs_stack; do
  [ -n "${name:-}" ] || continue
  case "$command" in
    scripts/dev.sh*) ok "$name runs a project command" ;;
    *) bad "$name runs '$command', which is not a scripts/dev.sh entry point" ;;
  esac
  [ -n "$expect" ] && ok "$name has a summary line to match" || bad "$name matches nothing"
  # `forbid` may legitimately be empty — not every tool prints a failure line
  # that contains its success line.
  case "$needs_stack" in
    yes|no) : ;;
    *) bad "$name does not say whether it needs the stack" ;;
  esac
done <<< "$(printf '%s' "$GATE_ROWS" | grep '|')"

printf '\nThe trap that put main red on 2026-08-27\n'

# `scripts/dev.sh check` prints ruff's "All checks passed!" several steps
# before it finishes. Matching that as the whole-suite result reports success
# while format, typecheck and tests are still to run.
check "no row shells out to the aggregate 'check'" \
  "$(printf '%s' "$GATE_ROWS" | grep -cE '\|scripts/dev\.sh check\|' || true)" 0

check "the tests row does not match on ruff's message" \
  "$(printf '%s' "$GATE_ROWS" | grep '^tests|' | grep -c 'All checks passed' || true)" 0

printf '\nDatabase-backed checks are their own row\n'

# `test` deselects them, so a green `test` says nothing about the tests that
# assert what the database refuses.
check "there is a row needing the stack" \
  "$(printf '%s' "$GATE_ROWS" | grep -c '|yes$' || true)" 1

check "the plain tests row does not need the stack" \
  "$(printf '%s' "$GATE_ROWS" | grep '^tests|' | grep -c '|no$' || true)" 1

printf '\nA passing line can be a substring of a failing one\n'

# ruff prints "2 files would be reformatted, 50 files already formatted" when
# it fails. A gate matching only "files already formatted" passes a tree the
# same tool would reject — which is exactly what let M1-ADD-BE-023 through the
# local gate and into a CI failure.
check "the format row forbids the failure text" \
  "$(printf '%s' "$GATE_ROWS" | grep '^format|' | grep -c 'would be reformatted' || true)" 1

check "the tests row forbids a failure count" \
  "$(printf '%s' "$GATE_ROWS" | grep '^tests|' | grep -c '|failed|' || true)" 1

check "every row has five fields" \
  "$(printf '%s' "$GATE_ROWS" | grep -c '|' || true)" \
  "$(printf '%s' "$GATE_ROWS" | awk -F'|' 'NF==5' | grep -c . || true)"

printf '\n%d passed, %d failed\n' "$PASSED" "$FAILED"
[ "$FAILED" -eq 0 ]
