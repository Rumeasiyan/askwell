#!/usr/bin/env bash
# Keep the build alive without anyone watching it.
#
# Written because the build does not stay running. It has stopped silently at
# least five times: two weeks in August, three times in one day on 13
# September, four days after that. Every stop had a different cause — a quota
# limit, a session ending, containers killed, podman storage wedging — and
# every one had the same shape: it died, nobody noticed, and the work sat
# still until somebody thought to ask. The fixes each took minutes. The
# noticing took days.
#
# So this does the noticing. Run from a systemd user timer every fifteen
# minutes. It is deliberately dull: check three things, repair what it can,
# write down what it did, and never do anything clever.
#
# What it will not do: touch a working tree the queue owns, merge a pull
# request CI has not passed, or start a second queue. Each of those has
# already caused a real problem in this repository, so each is checked for
# rather than assumed.

set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1

# systemd hands a user unit PATH=/usr/local/bin:/usr/bin and nothing else, so
# the agent CLI in ~/.local/bin is invisible to it. The first timer-fired run
# died on "agent CLI 'claude' not on PATH" twenty-five times while a manual run
# of this same script worked — because a manual run inherits a login shell's
# PATH and a service does not. A watchdog that only works when a human starts
# it is not a watchdog.
export PATH="$HOME/.local/bin:$HOME/bin:/usr/local/bin:/usr/bin:/bin"

REPO="$(pwd)"

# Checked rather than assumed: if the agent cannot be found there is no point
# starting a queue that will fail preflight on every restart the supervisor has.
if ! command -v claude >/dev/null 2>&1; then
  printf '%s  agent CLI not found on PATH (%s) — not starting\n' "$(date '+%Y-%m-%d %H:%M')" "$PATH" \
    >> "$(dirname "${BASH_SOURCE[0]}")/watchdog.log"
  exit 1
fi
LOG="$REPO/.build-runner/watchdog.log"
QUEUE_LOG="/tmp/askwell-queue.log"
# The first milestone with unbuilt tickets, rather than a fixed one. A pinned
# milestone means that finishing it stops the build dead: M3 completed at 02:49
# and the queue then reported "nothing left that is ready" every fifteen
# minutes until somebody noticed. Overriding with ASKWELL_MILESTONE still works
# for a deliberate re-run.
pick_milestone() {
  local m f total done_n
  for m in M0 M1 M2 M3 M4 M5 M6 M6.5 M7 M8; do
    f=$(ls docs/backlog/${m}-*.md 2>/dev/null | head -1)
    [ -n "$f" ] || continue
    # `grep -c` exits 1 when it counts zero, so a `|| echo 0` fallback
    # appends a second line and the test below sees "0\n0". Count with wc
    # instead, which always prints one number and always succeeds.
    total=$(grep -E "^### ${m}-" "$f" 2>/dev/null | wc -l | tr -d " ")
    done_n=$(ls .build-runner/done/ 2>/dev/null | grep "^${m}-" | wc -l | tr -d " ")
    if [ "$done_n" -lt "$total" ]; then
      printf '%s' "$m"
      return 0
    fi
  done
  return 1
}

MILESTONE="${ASKWELL_MILESTONE:-$(pick_milestone)}"
# 900 was set when the backlog was shorter. The ledger reads 726h spent with
# 19 tickets and ~78 estimated hours still to build, and a rebuilt ticket
# spends again — a ticket that fails its audit and is retried costs its
# estimate twice. Hitting the ceiling stops the queue, silently, which is the
# failure this whole supervisor exists to prevent, so the headroom is worth
# more than the guard's precision. The guard still exists; it is just set
# where it can only catch a runaway rather than an ordinary finish.
SPEND_CEILING="${SPEND_CEILING:-1200}"

say() { printf '%s  %s\n' "$(date '+%Y-%m-%d %H:%M')" "$*" >> "$LOG"; }

# Checked here rather than where MILESTONE is set: that happens before say()
# exists, and the first version of this called it there and died on
# "say: command not found" instead of reporting the thing it had found.
if [ -z "$MILESTONE" ]; then
  say "every milestone is complete — nothing left to build"
  exit 0
fi

# --- 1. is a queue already working? ------------------------------------------
#
# If one is, leave everything alone. Two queues in one working tree was a real
# failure here: they fight over the checkout and one silently loses its work.
# --- 1a. the stack, whether or not a queue is running -------------------------
#
# Above the early exit below, deliberately. `db-tests` is a gate row, so a stack
# that dies mid-run fails it and parks ticket after ticket that had nothing
# wrong with them — five in a row this morning while this script skipped every
# check because "a queue is already working". Bringing containers up touches no
# working tree and cannot collide with a build, so there is no reason to wait
# for the queue to exit before doing it.
up=$(podman ps --format '{{.Names}}' 2>/dev/null | grep -c askwell)
if [ "${up:-0}" -lt 6 ]; then
  say "stack was down ($up/6) — bringing it up"
  podman compose up -d >/dev/null 2>&1
  sleep 10
  up=$(podman ps --format '{{.Names}}' 2>/dev/null | grep -c askwell)
  say "stack now $up/6"
fi

if pgrep -f 'build-queue\.sh' >/dev/null 2>&1; then
  exit 0
fi

# --- 2. merge anything already green -----------------------------------------
#
# A pull request that has passed its checks and is sitting open is finished
# work nobody collected. Three of them sat that way for a fortnight in August
# while the build was stopped. Only `CLEAN` merges: `BLOCKED` means a required
# check is unsatisfied and `DIRTY` means conflicts, and forcing either is how a
# queue lands work that was never agreed.
if command -v gh >/dev/null 2>&1; then
  while read -r pr; do
    [ -n "$pr" ] || continue
    state=$(gh pr view "$pr" --json mergeStateStatus --jq .mergeStateStatus 2>/dev/null)
    [ "$state" = "CLEAN" ] || continue
    checks=$(gh pr checks "$pr" --json bucket --jq 'if length == 0 then "none" else (map(.bucket) | unique | join(",")) end' 2>/dev/null)
    [ "$checks" = "pass" ] || continue
    if gh pr merge "$pr" --squash --delete-branch >/dev/null 2>&1; then
      say "merged #$pr (was green and unattended)"
    fi
  done < <(gh pr list --state open --json number --jq '.[].number' 2>/dev/null)
fi

# --- 2b. markers that claim work which is not on main --------------------------
#
# A done marker means "this is on main". Twice in one evening one did not:
# M3-RAISE-BE-071 carried evidence keys the next ticket renders, and
# M3-STORE-BE-076 a module that did not exist on main at all. Each time the
# queue skipped the ticket as complete, everything behind it parked, and this
# watchdog restarted into the same dead end every fifteen minutes for hours.
#
# So each marker is checked against the pull request that was supposed to carry
# it. A ticket with no merged PR and no branch left to merge is one whose work
# never landed, and its marker is removed so the next run rebuilds it.
#
# Deliberately conservative: a ticket whose PR is still open, or whose state
# cannot be read, is left alone. Removing a marker for a ticket that is merely
# mid-flight would make the queue rebuild finished work.
if command -v gh >/dev/null 2>&1; then
  git fetch -q origin main 2>/dev/null
  for marker in "$REPO"/.build-runner/done/*; do
    [ -f "$marker" ] || continue
    ticket=$(basename "$marker")
    branch=$(printf '%s' "$ticket" | tr 'A-Z' 'a-z')
    branch="feat/$branch"
    state=$(gh pr view "$branch" --json state --jq .state 2>/dev/null)
    case "$state" in
      MERGED|"") continue ;;
      CLOSED)
        rm -f "$marker"
        say "$ticket was marked done but its pull request was closed unmerged — marker removed"
        ;;
      OPEN)
        # An open PR is usually a ticket mid-flight, which must be left alone.
        # One that cannot merge is different: the queue only marks a ticket
        # done after its own merge step, so a conflicting PR under a done
        # marker means the merge never happened and never will without help.
        # M4-DUMP-SEC-091 sat exactly like that for a day — marked done, PR
        # conflicting, CI red — while the queue skipped it as complete.
        if [ "$(gh pr view "$branch" --json mergeable --jq .mergeable 2>/dev/null)" = "CONFLICTING" ]; then
          rm -f "$marker"
          say "$ticket was marked done but its pull request cannot merge — marker removed"
        fi
        ;;
    esac
  done
fi


# --- 4. start the queue ------------------------------------------------------
#
# Only from a clean `main`. The queue refuses otherwise and it is right to:
# building on top of somebody's uncommitted work is how a ticket's diff ends up
# containing a stranger's changes. If the tree is dirty, say so and stop — that
# is a person's problem, not something to tidy away automatically.
git fetch -q origin >/dev/null 2>&1
branch=$(git branch --show-current)
# Only *tracked* modifications count. An untracked leftover — a fixture a
# parked ticket generated and never committed — is not somebody's work in
# progress, and refusing to start over one has now cost two multi-hour
# stalls ("needs a person" every fifteen minutes while nothing was wrong).
# A branch is cut fresh from main anyway, so a stray untracked file cannot
# end up in a ticket's diff.
dirty=$(git status --porcelain | grep -cv '^??')
untracked=$(git status --porcelain | grep -c '^??')

if [ "$branch" != "main" ] || [ "$dirty" -ne 0 ]; then
  say "not starting: on '$branch' with $dirty modified tracked file(s) — needs a person"
  exit 0
fi
if [ "${untracked:-0}" -ne 0 ]; then
  say "starting anyway: $untracked untracked file(s) present, none of them tracked work"
fi

git reset -q --hard origin/main >/dev/null 2>&1
rm -f "$REPO/.build-runner/STOP"

# Opus for every lineage, with Sonnet underneath it. Sonnet built M0 through
# most of M7 and its audits caught real bugs — the `sudo -n true` check that
# breaks a normal Linux install, the Tauri nav-port gap, a reset that
# truncates nothing — so this is not a correction. With roughly two dozen
# tickets left, the remaining work is the fiddly end of a milestone and the
# screen fixes, which is where judgement earns more than throughput.
#
# The fallback is the part that makes it safe: an overloaded or exhausted
# primary drops to Sonnet for that agent rather than failing the ticket and
# parking everything behind it. Reverting is one word in each of these three.
setsid nohup env SPEND_CEILING="$SPEND_CEILING" \
  BUILD_MODEL=opus AUDIT_MODEL=opus DOC_MODEL=opus FALLBACK_MODEL=sonnet \
  "$REPO/.build-runner/supervise.sh" --milestone "$MILESTONE" \
  >> "$QUEUE_LOG" 2>&1 < /dev/null &
disown

sleep 20
if pgrep -f 'build-queue\.sh' >/dev/null 2>&1; then
  ticket=$(grep -oE '^== M[0-9]-[A-Z-]+[0-9]+[a-z]? ==' "$QUEUE_LOG" 2>/dev/null | tail -1 | tr -d '= ')
  say "queue restarted on ${ticket:-$MILESTONE}"
else
  say "queue failed to start — see $QUEUE_LOG"
fi
