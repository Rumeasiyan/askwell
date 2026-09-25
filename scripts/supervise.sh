#!/usr/bin/env bash
# Relaunch the queue if it dies from a signal rather than a decision.
#
# The queue stops for good reasons (backlog empty, ceiling reached, STOP file)
# and it exits 0 for those. It also gets killed — OOM, session teardown — and
# that leaves the backlog half-worked with nobody to notice. This tells the two
# apart and only restarts the second.
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1
MAX_RESTARTS=25
n=0

# Reap before starting, not only between restarts. A runner whose parent session
# ended is reparented to systemd and keeps going — one was found still editing
# this repository seven hours after the session that started it, and another had
# been running since a session that ended earlier the same evening. Both were
# writing into the same working tree as a live queue.
#
# Matched by the temp-script name the runner is copied to, plus the print-mode
# agents such a runner spawns. A queue started from this script has not spawned
# anything yet, so nothing here can kill the run it is about to begin.
# Only genuine orphans: a process whose parent is PID 1 has been reparented,
# which is exactly what happens when the session that started it ends. A runner
# belonging to a queue that is still alive has that queue as its parent and is
# left alone — otherwise starting a second supervisor would kill the first one's
# work, which is a worse bug than the one this fixes.
# Matched on the ticket argument, not on "a bash script in /tmp". This machine
# runs another project whose build system also stages scripts there, and an
# earlier version of this loop would have killed it — the reparenting guard
# below saved it by luck rather than by design. Askwell's runner is always
# invoked with a ticket id as argv[1], which nothing else here does.
#
# Reparented to PID 1 as well: a runner whose parent is alive belongs to a queue
# that is still working, and killing it would destroy the run this script is
# about to join rather than an abandoned one.
for pid in $(pgrep -f 'bash /tmp/tmp\..* M[0-9]-[A-Z]' 2>/dev/null); do
  parent=$(ps -o ppid= -p "$pid" 2>/dev/null | tr -d ' ')
  [ "$parent" = "1" ] || continue
  for child in $(pgrep -P "$pid" 2>/dev/null); do kill "$child" 2>/dev/null; done
  kill "$pid" 2>/dev/null && echo "SUPERVISOR: reaped orphaned runner $pid from an ended session."
done
while :; do
  scripts/build-queue.sh "$@"
  rc=$?
  # Clean exit, or a stop the operator asked for: done either way.
  [ "$rc" -eq 0 ] && { echo "SUPERVISOR: queue finished cleanly (exit 0)."; break; }
  [ -f .build-runner/STOP ] && { echo "SUPERVISOR: STOP file present, not restarting."; break; }
  n=$((n + 1))
  [ "$n" -gt "$MAX_RESTARTS" ] && { echo "SUPERVISOR: $MAX_RESTARTS restarts used, giving up."; break; }
  # Killing the queue does not kill the agent it spawned. The agent is a
  # separate detached process and carries on editing the working tree, so a
  # restart puts a second agent into the same checkout as the first. That
  # happened: an agent verifying M1-ADD-BE-023 and one building M1-ADD-ING-025
  # wrote into one tree at once, and the second noticed only because the first
  # left files it did not recognise. Reap them before restarting.
  for pid in $(pgrep -f 'claude --print' 2>/dev/null); do
    kill "$pid" 2>/dev/null && echo "SUPERVISOR: reaped orphaned agent $pid."
  done
  sleep 2

  # A killed build can leave its work uncommitted on whatever branch was
  # checked out. Park it rather than let the next run trip over a dirty tree.
  if [ -n "$(git status --porcelain)" ]; then
    git stash push -q -u -m "supervisor: interrupted build, restart $n" || true
    echo "SUPERVISOR: stashed an interrupted build's working tree."
  fi
  git checkout -q main 2>/dev/null || true
  echo "SUPERVISOR: queue exited $rc, restart $n of $MAX_RESTARTS."
  sleep 10
done
