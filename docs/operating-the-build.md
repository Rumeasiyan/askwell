# Operating the build

How the unattended build actually runs, what breaks it, and how to move it to
another machine. Written 2026-09-25 from running it end to end — M0 through M8,
213 tickets — so that a session starting on a fresh clone begins with what the
last one learned instead of rediscovering it one stall at a time.

`AGENTS.md` says what the rules are. This says what happens when you run them.

---

## 1. The pieces

| Piece | Where | What it does |
| ----- | ----- | ------------ |
| Runner | `scripts/build-runner.sh` | One ticket: build → six-row gate → audit → doc. Never merges |
| Queue | `scripts/build-queue.sh` | Picks the next ready ticket, branches, runs the runner, opens the PR, waits for CI, merges, repeats |
| Supervisor | `scripts/supervise.sh` | Restarts the queue if it dies from a signal; leaves it alone if it exits by decision |
| Watchdog | `scripts/watchdog.sh` | Every 15 minutes: brings the stack up, merges green orphan PRs, audits done markers, restarts a dead queue |
| Done markers | `.build-runner/done/<ticket>` | One empty file per ticket on `main`. **How the queue knows what not to build** |
| Snapshot | `docs/backlog/built.txt` | The done markers, tracked, so a fresh clone can recreate them |

`.build-runner/` is gitignored. The supervisor and watchdog *run* from there
(a copy survives branch checkouts; the tracked file does not), but the tracked
copies in `scripts/` are the source. `scripts/setup-build-state.sh` builds
`.build-runner/` from the repository.

**The queue builds `docs/backlog/*.md`. It never reads the issue tracker.** An
issue is a note to a person. A finding that must be built has to become a
ticket, or it will sit in the tracker while the queue reports the product
finished. Several screen bugs very nearly did.

---

## 2. Moving to another machine

On the machine you are leaving:

1. Stop the queue and the watchdog so nothing is mid-ticket:
   `systemctl --user stop askwell-watchdog.timer`, then stop the
   `supervise.sh` and `build-queue.sh` processes.
2. `scripts/setup-build-state.sh --save`, then commit and push
   `docs/backlog/built.txt`.
3. **Never run two queues against the same repository**, on one machine or
   two. They open competing branches and pull requests for the same ticket.

On the new machine:

1. Clone, then `scripts/setup-build-state.sh`. Without this the queue sees no
   done markers and schedules every ticket again.
2. Create `.env` from `.env.example`. Secrets are never committed (C8); the
   installers generate real passwords.
3. Put the model files in the models directory. They are several GB and are
   not in the repository.
4. Bring the stack up, run `scripts/dev.sh check`, then start the queue.

### Windows specifically

Everything under `scripts/` is bash, the stack is Podman, and the watchdog is a
systemd **user** timer. On Windows run the whole build inside **WSL2** — a
Linux shell with Podman — not in PowerShell or Git Bash. The watchdog has no
Windows equivalent; inside WSL2 a systemd user timer works if systemd is
enabled, or a cron entry does. Native inference (`scripts/dev.sh inference`)
runs on the host for GPU access.

The self-hosted GitHub runner that the eval workflow targets is registered on
the Linux build machine. It does not move with the repository.

---

## 3. What stops the build, and how it looks

The build has stopped silently more times than anything else has cost. Every
stop had a different cause and the same shape: it died, nobody noticed. Each
row here is one that happened.

| Symptom | Cause | Fix |
| ------- | ----- | --- |
| A ticket halts with "changed nothing" and is retried every restart | **The backend it needs was never written as a ticket.** The backlog was written screen-first in M3, M4, M5 and M6: a frontend ticket assumes an endpoint, a column or a client that no ticket builds. The agent is right to halt rather than stub | Read the halt log — the agent usually states exactly what is missing and has filed an issue. Write that as a ticket before the halted one and add it to its dependencies |
| "Nothing left that is ready" with tickets still unbuilt | A dependency names **a ticket id that does not exist**, or two tickets depend on each other | Run the dependency check below. Both have happened; one cycle came from the original backlog, three missing ids from tickets written in a hurry |
| The queue loops over the same tickets, zero merges for hours | A built ticket's pull request sat open while others merged, and now **conflicts with `main`** — every ticket bumps `VERSION` and `CHANGELOG.md`. The watchdog removes its done marker, the queue rebuilds it onto the same stale branch, and it conflicts again | Close the PR **and delete its branch**, and remove the done marker if it is still set. The rebuild then starts clean |
| The watchdog logs "queue failed to start" every 15 minutes | Usually the queue ran out of ready work in the pinned milestone. A `[BLOCKED]` ticket once kept a milestone open forever | `scripts/build-runner.sh --list` shows ready, waiting and blocked for every ticket |
| The watchdog logs "needs a person" | It refuses a working tree that is not clean `main`. An untracked leftover used to be enough | It now steps over untracked files; a tracked change or a non-`main` branch still stops it, correctly |
| The watchdog silently does nothing when run by hand | Its "is a queue already running?" check is `pgrep -f`, and **a shell command that merely contains the text `build-queue` matches it** — including the one you just typed to check | Never combine a status check naming the queue with a watchdog run in one command. This produced three queues in one tree once |
| The interface says "has not been built" | `scripts/dev.sh web-build` replaces `web/out`, and the API container still holds the old directory | `podman compose up -d --force-recreate api`. Pause the queue while recording or demoing — its tickets rebuild the frontend underneath you |
| An API change does not show up | `api/src` is baked into the image, not mounted | `scripts/dev.sh build-api`, then recreate `api` and `worker` |

### Checking the backlog's dependencies

A dependency on a ticket that does not exist can never be satisfied, and the
queue does not say so — it waits. Run this after writing any ticket:

```bash
python3 - <<'PY'
import re, pathlib, glob
ids=set(); deps={}
for f in glob.glob('docs/backlog/M*.md'):
    for b in re.split(r'\n### ', pathlib.Path(f).read_text())[1:]:
        t=b.split(' ')[0]; ids.add(t)
        m=re.search(r'\*\*Dependencies:\*\*([^\n]*)', b)
        deps[t]=re.findall(r'M\d(?:\.5)?-[A-Z]+-[A-Z]+-\d+[a-z]?', m.group(1)) if m else []
print("missing:", [(t,d) for t,ds in deps.items() for d in ds if d not in ids] or "none")
PY
```

---

## 4. How the product owner wants this run

Two standing instructions, learned the hard way:

- **Decide engineering questions; escalate only product ones.** Pricing, scope,
  positioning, licence, and copy a user relies on to decide what leaves their
  machine are his. Everything else — log budget, retry counts, which fix — is
  decided, written into `docs/decisions.md` with the reasoning, and mentioned in
  one line. Listing decidable items back to him reads as handing work back.
- **Run the loop without asking between tickets.** Find or write the ticket,
  build, run it, verify, PR, wait for CI, merge, update `docs/BRAIN.md`. Report
  at the end of a batch. Stop only for a product decision or something that
  consumes his machine — multi-GB downloads, native installs, system changes.
  Never merge on red CI.

And one that cost a day to learn: **a decision made in conversation is lost
unless it is written down in the same breath.** The credit tier was dropped in
conversation and the backlog, the business case and the interface all went on
describing it for most of a day.

---

## 5. Models

The build agents run on `opus` (currently Opus 5.5) with `sonnet` as the
fallback, set in `scripts/watchdog.sh`. The fallback is what makes that safe: an
overloaded or exhausted primary degrades one agent to Sonnet rather than failing
the ticket and parking everything behind it. `opus` is an alias for the latest
Opus; pin a full model id there if a later release should not be picked up
automatically.
