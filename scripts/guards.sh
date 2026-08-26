#!/usr/bin/env bash
# Guards for the build runner. See docs/build-runner.md §11.
#
# Sourced, never forked: these must be able to `return` a refusal rather than
# exit the runner from a subshell.
#
# Both guards FAIL CLOSED. A missing or unparseable ledger halts rather than
# assuming zero spend — a guard that reads a corrupt file as "0 used" is worse
# than no guard, because it reports safety it is not providing.
#
# Targets bash 3.2: macOS ships it, and architecture.md §2.1 puts macOS in v1.
# No associative arrays, no ${x^^}, no mapfile.

: "${RUNNER_STATE:=.build-runner}"
GUARD_LEDGER="$RUNNER_STATE/ledger.jsonl"
GUARD_STOP="$RUNNER_STATE/STOP"

guard_die() { printf '%s\n' "GUARD: $*" >&2; return 1; }

# ---------------------------------------------------------------- init

guard_init() {
  mkdir -p "$RUNNER_STATE/prompts" "$RUNNER_STATE/logs" "$RUNNER_STATE/session" || {
    guard_die "cannot create state directory $RUNNER_STATE"; return 1; }
  if [ ! -e "$GUARD_LEDGER" ]; then
    : > "$GUARD_LEDGER" || { guard_die "cannot create ledger $GUARD_LEDGER"; return 1; }
  fi
  [ -r "$GUARD_LEDGER" ] || { guard_die "ledger $GUARD_LEDGER is not readable"; return 1; }
  guard_spent_total >/dev/null || return 1   # parse it now, not at the moment it matters
  return 0
}

# ---------------------------------------------------------------- stop file

# Halts BETWEEN tickets only. Deliberately not checked mid-ticket: a runner
# killed while writing files leaves a tree somebody untangles by hand, which is
# worse than one more ticket finishing.
guard_stop_requested() {
  [ -e "$GUARD_STOP" ] || return 1
  printf 'STOP FILE PRESENT: %s\n' "$GUARD_STOP"
  if [ -s "$GUARD_STOP" ]; then
    printf 'Reason given:\n'
    sed 's/^/  /' "$GUARD_STOP"
  else
    printf '  (no reason written in the file)\n'
  fi
  return 0
}

# ---------------------------------------------------------------- budget

# The ledger is a JSON-lines file this script writes and only this script reads,
# so it is parsed with awk rather than jq — jq is not present on a stock macOS
# and a guard that needs an optional dependency is a guard that gets skipped.
#
# Every line must look like: {"ticket":"ID","hours":N.N,"ts":"..."}
# Anything else is corruption and halts.
guard_spent_total() {
  local total
  total=$(awk '
    /^[[:space:]]*$/ { next }
    {
      if ($0 !~ /"hours"[[:space:]]*:[[:space:]]*[0-9]+(\.[0-9]+)?/) { bad=1; exit }
      line = $0
      sub(/.*"hours"[[:space:]]*:[[:space:]]*/, "", line)
      sub(/[^0-9.].*$/, "", line)
      sum += line + 0
    }
    END { if (bad) { print "CORRUPT"; exit } printf "%.2f", sum + 0 }
  ' "$GUARD_LEDGER" 2>/dev/null)

  if [ -z "$total" ] || [ "$total" = "CORRUPT" ]; then
    guard_die "ledger $GUARD_LEDGER is unreadable or contains a malformed line — refusing to run.
       Inspect it, fix or remove the bad line, then re-run. This halts rather than
       assuming zero, because assuming zero reports safety it is not providing."
    return 1
  fi
  printf '%s' "$total"
  return 0
}

# guard_budget_allows <estimate_hours>
# Refuses to START a ticket whose estimate would cross the ceiling. That ordering
# is the whole point: a cap discovered after the fact is a bill, not a cap.
guard_budget_allows() {
  local estimate="$1" spent projected
  if [ -z "${SPEND_CEILING:-}" ]; then
    guard_die "SPEND_CEILING is not set. Refusing to run.
       An unattended queue with no ceiling is the case this guard exists for."
    return 1
  fi
  case "$SPEND_CEILING" in
    ''|*[!0-9.]*) guard_die "SPEND_CEILING must be a number, got '$SPEND_CEILING'"; return 1 ;;
  esac
  case "$estimate" in
    ''|*[!0-9.]*) guard_die "estimate must be a number, got '$estimate'"; return 1 ;;
  esac

  spent=$(guard_spent_total) || return 1
  projected=$(awk -v a="$spent" -v b="$estimate" 'BEGIN{printf "%.2f", a+b}')

  if awk -v p="$projected" -v c="$SPEND_CEILING" 'BEGIN{exit !(p > c)}'; then
    guard_die "ceiling would be crossed. spent=${spent}h estimate=${estimate}h ceiling=${SPEND_CEILING}h
       Raise SPEND_CEILING deliberately, or stop here."
    return 1
  fi
  return 0
}

# guard_record_spend <ticket> <hours>
# Write-temp-and-move, so a kill mid-write cannot corrupt the ledger and halt
# every future run.
guard_record_spend() {
  local ticket="$1" hours="$2" tmp
  case "$hours" in
    ''|*[!0-9.]*) guard_die "hours must be a number, got '$hours'"; return 1 ;;
  esac
  tmp="${GUARD_LEDGER}.tmp.$$"
  cat "$GUARD_LEDGER" > "$tmp" 2>/dev/null || : > "$tmp"
  printf '{"ticket":"%s","hours":%s,"ts":"%s"}\n' \
    "$ticket" "$hours" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$tmp" || {
      rm -f "$tmp"; guard_die "could not append to ledger"; return 1; }
  mv "$tmp" "$GUARD_LEDGER" || { rm -f "$tmp"; guard_die "could not replace ledger"; return 1; }
  return 0
}
