#!/usr/bin/env bash
# Recreate `.build-runner/` on a fresh clone, or snapshot it before leaving one.
#
#   scripts/setup-build-state.sh          restore: build .build-runner/ from the repo
#   scripts/setup-build-state.sh --save   snapshot: write this machine's done
#                                         markers into docs/backlog/built.txt
#
# Why this exists. `.build-runner/` is gitignored, and until 2026-09-25 the only
# copy of two things the build depends on lived in it: the done markers — one
# empty file per ticket that has landed on main — and the supervisor. A fresh
# clone had neither. The runner decides what to build by which markers are
# missing, so a clone with no markers would have scheduled every ticket in the
# backlog again: 213 of them, each opening a duplicate pull request against
# work already on main.
#
# Rebuilding the markers from merged pull requests was tried first and is not
# exact: the M0 tickets predate the `feat/<ticket>` branch convention, a few
# later ones merged under a different branch name, and a PR can merge for a
# ticket that is still [BLOCKED]. So the markers are snapshotted into a tracked
# file instead, which is exact by construction.
#
# Run --save on the old machine before moving, commit, then run this with no
# argument on the new one.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1

LIST="docs/backlog/built.txt"
STATE=".build-runner"

if [ "${1:-}" = "--save" ]; then
  [ -d "$STATE/done" ] || { echo "no $STATE/done here to snapshot" >&2; exit 1; }
  ls "$STATE/done" | sort > "$LIST"
  echo "wrote $(wc -l < "$LIST" | tr -d ' ') ticket ids to $LIST — commit it"
  exit 0
fi

[ -f "$LIST" ] || { echo "no $LIST — run --save on the machine that has the markers" >&2; exit 1; }

# Refuse to run under a live queue. Rewriting markers under a queue that is
# reading them is how a ticket gets built twice or skipped.
# Scoped to this working tree: another clone of the repository on the same
# machine may legitimately be running its own queue.
here="$(pwd -P)"
for pid in $(pgrep -f 'bash scripts/build-queue\.sh' 2>/dev/null || true); do
  if [ "$(readlink -f "/proc/$pid/cwd" 2>/dev/null)" = "$here" ]; then
    echo "a build queue is running in this tree — stop it first" >&2
    exit 1
  fi
done

mkdir -p "$STATE/done" "$STATE/logs" "$STATE/prompts"
cp scripts/supervise.sh "$STATE/supervise.sh"
cp scripts/watchdog.sh  "$STATE/watchdog.sh"
chmod +x "$STATE/supervise.sh" "$STATE/watchdog.sh"

added=0
while IFS= read -r id; do
  [ -n "$id" ] || continue
  if [ ! -e "$STATE/done/$id" ]; then : > "$STATE/done/$id"; added=$((added + 1)); fi
done < "$LIST"

echo "$STATE ready: $(ls "$STATE/done" | wc -l | tr -d ' ') done markers ($added added), supervisor and watchdog in place"
