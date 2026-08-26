#!/usr/bin/env bash
# Tests for the build runner's guards. See docs/build-runner.md §11.
#
# These exist before the runner does, deliberately: the guards are what stop an
# unattended run from burning budget or refusing to die, so they must be provable
# on their own. Wired into the repo gate once one exists (M0).
set -Eeuo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PASS=0; FAIL=0

ok()   { PASS=$((PASS+1)); printf '  ok    %s\n' "$1"; }
bad()  { FAIL=$((FAIL+1)); printf '  FAIL  %s\n' "$1"; }
check(){ if [ "$2" = "$3" ]; then ok "$1"; else bad "$1 (want '$3', got '$2')"; fi; }

fresh() {                       # fresh sandbox per test
  RUNNER_STATE="$(mktemp -d)"
  export RUNNER_STATE
  unset SPEND_CEILING
  # shellcheck source=/dev/null
  . "$HERE/guards.sh"
}

printf 'guards\n'

# --- init -------------------------------------------------------------------
fresh
guard_init >/dev/null 2>&1 && r=0 || r=1
check "init creates state and an empty ledger" "$r" 0
[ -f "$RUNNER_STATE/ledger.jsonl" ] && r=0 || r=1
check "init leaves a readable ledger" "$r" 0

# --- stop file --------------------------------------------------------------
fresh; guard_init >/dev/null 2>&1
guard_stop_requested >/dev/null 2>&1 && r=0 || r=1
check "no stop file means no stop" "$r" 1

printf 'disk is full\n' > "$RUNNER_STATE/STOP"
guard_stop_requested >/dev/null 2>&1 && r=0 || r=1
check "stop file halts" "$r" 0
out="$(guard_stop_requested 2>&1)"
case "$out" in *"disk is full"*) ok "stop file contents are printed as the reason" ;;
               *) bad "stop file contents are printed as the reason" ;; esac

: > "$RUNNER_STATE/STOP"
out="$(guard_stop_requested 2>&1)"
case "$out" in *"no reason written"*) ok "empty stop file still halts, and says so" ;;
               *) bad "empty stop file still halts, and says so" ;; esac

# --- budget: unset ceiling refuses ------------------------------------------
fresh; guard_init >/dev/null 2>&1
guard_budget_allows 3 >/dev/null 2>&1 && r=0 || r=1
check "unset SPEND_CEILING refuses to run" "$r" 1

# --- budget: boundary -------------------------------------------------------
fresh; guard_init >/dev/null 2>&1; export SPEND_CEILING=10
guard_budget_allows 10 >/dev/null 2>&1 && r=0 || r=1
check "estimate exactly at the ceiling is allowed" "$r" 0
guard_budget_allows 10.01 >/dev/null 2>&1 && r=0 || r=1
check "estimate one step past the ceiling is refused" "$r" 1

# --- budget: accumulates ----------------------------------------------------
fresh; guard_init >/dev/null 2>&1; export SPEND_CEILING=10
guard_record_spend T-1 6 >/dev/null 2>&1
check "spend accumulates across calls" "$(guard_spent_total)" "6.00"
guard_budget_allows 4 >/dev/null 2>&1 && r=0 || r=1
check "6 spent + 4 estimate reaches the ceiling and is allowed" "$r" 0
guard_budget_allows 5 >/dev/null 2>&1 && r=0 || r=1
check "6 spent + 5 estimate crosses the ceiling and is refused" "$r" 1
guard_record_spend T-2 3 >/dev/null 2>&1
check "second record adds to the total" "$(guard_spent_total)" "9.00"

# --- fail closed ------------------------------------------------------------
fresh; guard_init >/dev/null 2>&1; export SPEND_CEILING=100
printf 'this is not a ledger line\n' >> "$RUNNER_STATE/ledger.jsonl"
guard_spent_total >/dev/null 2>&1 && r=0 || r=1
check "corrupt ledger halts rather than reading as zero" "$r" 1
guard_budget_allows 1 >/dev/null 2>&1 && r=0 || r=1
check "corrupt ledger also refuses the budget check" "$r" 1

fresh
RUNNER_STATE="$RUNNER_STATE/nope"; export RUNNER_STATE
GUARD_LEDGER="$RUNNER_STATE/ledger.jsonl"
guard_spent_total >/dev/null 2>&1 && r=0 || r=1
check "missing ledger halts rather than reading as zero" "$r" 1

# --- input validation -------------------------------------------------------
fresh; guard_init >/dev/null 2>&1; export SPEND_CEILING=abc
guard_budget_allows 1 >/dev/null 2>&1 && r=0 || r=1
check "non-numeric ceiling is refused" "$r" 1
export SPEND_CEILING=10
guard_budget_allows "lots" >/dev/null 2>&1 && r=0 || r=1
check "non-numeric estimate is refused" "$r" 1
guard_record_spend T-3 "lots" >/dev/null 2>&1 && r=0 || r=1
check "non-numeric spend is refused" "$r" 1

printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
