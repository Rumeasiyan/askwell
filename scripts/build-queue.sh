#!/usr/bin/env bash
# Work the backlog until it is finished, the budget runs out, or something
# needs a person.
#
# One ticket per subprocess, deliberately. `build-runner.sh` does one ticket
# correctly and knows nothing about queues; this knows about queues and nothing
# about building. A fresh process per ticket also means no state leaks from one
# to the next — the property the runner already buys by never resuming a build
# session.
#
# Each ticket gets its own branch off main and its own pull request. Three
# independent things have to agree before anything reaches main: the gate, the
# audit, and CI. The audit is the one that matters, because it is the only one
# that did not write the code.
#
#   SPEND_CEILING=200 scripts/build-queue.sh
#   SPEND_CEILING=200 scripts/build-queue.sh --milestone M1
#
# Stop it at any time:
#   touch .build-runner/STOP        finishes the ticket in flight, then stops

set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1

SELF="scripts/build-queue.sh"
RUNNER="scripts/build-runner.sh"
STATE=".build-runner"
MAIN="main"

BOLD=$'\033[1m'; DIM=$'\033[2m'; RESET=$'\033[0m'
say()  { printf '%s\n' "$*"; }
head1() { printf '\n%s== %s ==%s\n' "$BOLD" "$*" "$RESET"; }
die()  { printf '\n%sSTOP:%s %s\n' "$BOLD" "$RESET" "$*" >&2; exit 1; }

MILESTONE_FILTER=""
[ "${1:-}" = "--milestone" ] && { MILESTONE_FILTER="${2:-}"; shift 2; }

[ -n "${SPEND_CEILING:-}" ] || die "SPEND_CEILING is not set. A queue with no ceiling is the case the guard exists for."
# Start from a clean main, and say so rather than discovering it later. Two
# overlapping queues race over the same working tree: the second sees the
# first's half-finished build and reports a preflight refusal that names a
# dirty tree without saying whose. This is the same mistake made once already.
[ "$(git rev-parse --abbrev-ref HEAD)" = "$MAIN" ] || die \
  "Not on $MAIN. The queue branches per ticket and returns here between them,
       so it has to start from a known place. If another queue is running,
       this one would fight it for the working tree."
[ -z "$(git status --porcelain)" ] || die \
  "The working tree is dirty. Either something is mid-build — check for
       another queue before starting a second — or there is work here that
       would be swept into the first ticket's branch."

command -v gh >/dev/null || die "gh is not on PATH."
gh auth status >/dev/null 2>&1 || die "gh is not authenticated."

# --- what is ready ------------------------------------------------------------
next_ticket() {
  local id status listing
  # Not silenced. `--list` runs the runner's preflight, so a dirty tree or a
  # detached HEAD makes it fail — and swallowing that turns "I could not ask"
  # into "nothing is ready", which reads as a finished backlog and stops the
  # queue with everything still to do.
  if ! listing="$(SPEND_CEILING="$SPEND_CEILING" "$RUNNER" --list 2>&1)"; then
    # Returned, not died. `next_ticket` is called inside $(...), and a `die`
    # there kills only the substitution — the parent carried on, found no
    # ticket, reported "nothing left that is ready" and exited 0 having built
    # nothing. A queue that silently does nothing and calls it success is
    # worse than one that crashes.
    printf '%s\n' "$listing" >&2
    return 1
  fi

  printf '%s\n' "$listing" \
    | while read -r id status; do
        case "$id" in ''|'=='|Queue) continue ;; esac
        [ "$status" = "ready" ] || continue
        [ -z "$MILESTONE_FILTER" ] || case "$id" in "$MILESTONE_FILTER"-*) ;; *) continue ;; esac
        printf '%s\n' "$id"
        break
      done
}

branch_for() { printf 'feat/%s' "$(printf '%s' "$1" | tr 'A-Z' 'a-z')"; }

# --- one ticket ---------------------------------------------------------------
build_one() {   # build_one <ticket>
  local ticket="$1" branch; branch="$(branch_for "$ticket")"

  git checkout -q "$MAIN" && git pull -q || return 1
  git checkout -q -B "$branch" || return 1

  if ! SPEND_CEILING="$SPEND_CEILING" "$RUNNER" "$ticket"; then
    # The runner refuses to record a ticket its audit rejected, so an
    # unfinished branch is left exactly where it stopped. Parked rather than
    # deleted: the work and the audit that rejected it are the two things a
    # person needs, and deleting the branch throws away both.
    say ""
    say "  ${BOLD}$ticket was not accepted.${RESET} Its branch is $branch and the"
    say "  audit is in $STATE/logs/$ticket.audit.log"
    say "  Anything depending on it stays blocked, so the queue moves on."
    return 1
  fi

  git add -A
  git commit -q -m "feat: $ticket

Built by $RUNNER. Gate passed and the audit accepted it; CI is the third
check and gates the merge.

See docs/manual-tests/$ticket.md for what to try by hand." || return 1

  git push -q -u origin "$branch" || return 1
  gh pr create --fill --base "$MAIN" >/dev/null 2>&1 || return 1

  # CI is the third opinion, and the one that runs on a machine that is not
  # this one. Merging before it answers would make the other two decorative.
  local run=""
  local sha; sha="$(git rev-parse HEAD)"
  while [ -z "$run" ]; do
    run="$(gh run list --branch "$branch" --limit 1 --json databaseId,headSha \
            --jq ".[0] | select(.headSha==\"$sha\") | .databaseId" 2>/dev/null)"
    [ -n "$run" ] || sleep 10
  done
  while [ "$(gh run view "$run" --json status --jq .status 2>/dev/null)" != "completed" ]; do
    sleep 20
  done

  if [ "$(gh run view "$run" --json conclusion --jq .conclusion)" != "success" ]; then
    say "  ${BOLD}CI rejected $ticket.${RESET} The branch and its PR are left open."
    return 1
  fi

  gh pr merge --squash --delete-branch >/dev/null 2>&1 || return 1
  git checkout -q "$MAIN" && git pull -q
  say "  merged."
  return 0
}

# --- the queue ----------------------------------------------------------------
built=0; parked=""
head1 "Working the backlog"
say "  ceiling: ${SPEND_CEILING}h${MILESTONE_FILTER:+   milestone: $MILESTONE_FILTER}"
say "  ${DIM}touch $STATE/STOP to stop after the ticket in flight${RESET}"

while :; do
  if [ -f "$STATE/STOP" ]; then
    say ""
    say "  stop file present — stopping. Remove $STATE/STOP to continue."
    break
  fi

  if ! ticket="$(next_ticket)"; then
    die "Could not read the queue — the runner's preflight refused, above.
       Nothing was built. This is not an empty backlog."
  fi
  [ -n "$ticket" ] || { say ""; say "  Nothing left that is ready."; break; }

  head1 "$ticket"
  if build_one "$ticket"; then
    built=$((built + 1))
  else
    parked="$parked $ticket"
    git checkout -q "$MAIN" 2>/dev/null
  fi
done

head1 "Done"
say "  merged:  $built"
if [ -n "$parked" ]; then
  say "  parked: $parked"
  say ""
  say "  Each is on its own branch with its audit beside it. Nothing depending"
  say "  on a parked ticket has been built, because a ticket the audit rejected"
  say "  is not recorded as done and its dependents never became ready."
fi
