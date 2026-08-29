# Manual test — M2-EVAL-DEPLOY-067, the eval gate on a capable runner

**Ticket:** `M2-EVAL-DEPLOY-067` — run the 165-task eval gate somewhere a model can actually be loaded: a self-hosted runner, triggered by a prompt or retrieval-configuration change or by hand, that self-heals its model cache, publishes comparable results, and blocks a prompt change that has no recorded run.
**Version under test:** `0.3.0`.
**Time:** about 30 minutes if you already have GitHub CLI (`gh`) authenticated against this repo and the stack has run before; add a first image build otherwise.
**Who can run it:** a terminal, `gh` authenticated as a collaborator on `Rumeasiyan/askwell`, and — for Part C only — the Compose stack and native inference, the same as any other eval-suite manual test.

**What is being checked.** `.github/workflows/eval.yml`: its trigger paths (a prompt file under `api/src/askwell/agent/prompts/`, `retrieve.py`, `config.py`, a suite file, or a suite-mode module, plus manual dispatch), its self-hosted `[self-hosted, askwell]` runner label, its generation-model self-heal against `api/src/askwell/models_catalog.py`'s registry-verified spec, its 30-minute timeout for an unresponsive runner, its `eval` job running `grounded_qa.v1`, `abstention.v1` and `conflicting_sources.v1` through `scripts/dev.sh eval`, and its distinction — in the job log — between a suite that failed for an infrastructure reason and one that ran and scored below `docs/build-plan.md`'s bar. Only three of the gate's eight categories exist yet; that is this ticket's own stated scope, not a gap found here.

**Where this stops on purpose, before you start.** Two pieces of this ticket are **not yet in place on this repository**, and no amount of correct workflow YAML changes that — this is stated up front so Part B and Part D read as "confirmed absent" rather than "found broken":

- **No self-hosted runner is registered.** `gh api repos/Rumeasiyan/askwell/actions/runners` returns zero runners as of this writing. A job requiring the `askwell` label has nothing to pick it up.
- **`main` has no branch protection.** `gh api repos/Rumeasiyan/askwell/branches/main/protection` returns `404 Branch not protected`. Naming `eval`'s job as a required status check is a manual, one-time repository-settings step this ticket's own scope leaves undone (`docs/decisions.md`'s entry for this ticket says so directly), so **the "blocked from merging" acceptance criterion cannot be exercised on this repository today.** Part D below tests the honest version of that: the workflow reports a clear, distinguishable non-result — never a false pass — when nothing can run it.

---

## Before you start

```
cd ~/external/quantum-plus/askwell
gh auth status
```

**You should see:** `Logged in to github.com account Rumeasiyan`. If not, run `gh auth login` first — everything below needs it.

```
git status
```

**You should see:** your working tree on some branch, ideally not `main` — Part A pushes a throwaway commit.

---

## Part A — the workflow is wired to the right triggers

### 1. Read the trigger paths back out of the file

```
sed -n '/^on:/,/^concurrency:/p' .github/workflows/eval.yml
```

**You should see:** a `push`/`pull_request` block sharing one `paths:` anchor listing `api/src/askwell/agent/prompts/**`, `api/src/askwell/retrieve.py`, `api/src/askwell/config.py`, `eval/suites/**`, `eval/scoring.py`, `eval/runner.py`, `eval/grounded.py`, `eval/abstain.py`, `eval/conflict.py`, plus a bare `workflow_dispatch: {}`.

### 2. Make a change that should trigger it, and one that should not

```
git checkout -b test/eval-gate-trigger-067
echo "" >> api/src/askwell/agent/prompts/abstention.v1.md
echo "" >> README.md
git add api/src/askwell/agent/prompts/abstention.v1.md README.md
git commit -m "test: exercise the eval-gate trigger paths (manual test, not shipped)"
git push -u origin test/eval-gate-trigger-067
```

**You should see:** the push succeed and print a "Create a pull request" URL.

### 3. Open a PR and watch the Checks list

```
gh pr create --title "test: eval gate trigger (manual test, discard after)" --body "Manual test for M2-EVAL-DEPLOY-067. Not for merge." --draft
gh pr checks --watch
```

**You should see:** `CI / api`, `CI / web` (or similar, from `ci.yml`) start immediately, and **`Eval gate / eval`** appear in the same list — proving the prompt-file touch alone was enough to queue it, even though `README.md` also changed in the same commit and is not itself a trigger path.

---

## Part B — a runner-offline change is distinguishable from a silent skip

### 4. Check the eval job's state

```
gh pr checks --json name,state,link 2>/dev/null | python3 -c "import json,sys; [print(c) for c in json.load(sys.stdin) if 'Eval' in c['name']]"
```

**You should see:** `state` reading `PENDING` (not `SUCCESS`, and not simply absent from the list) — GitHub itself shows a check that exists and has not resolved, which is the honest state of "no capable runner has picked this up," distinct from a repository where the workflow never triggered at all.

### 5. Confirm no runner will ever claim it, on this repository as configured today

```
gh api repos/Rumeasiyan/askwell/actions/runners --jq '.total_count'
```

**You should see:** `0`. This job will sit `PENDING` until the 30-minute `timeout-minutes: 30` in `eval.yml`'s `eval` job elapses, then GitHub marks it `FAILURE` with a queued-timeout reason — the workflow's own answer to the ticket's "runner is offline" edge case. Do not wait out the 30 minutes for this manual test; the mechanism (a bounded, explained failure rather than an indefinite hang) is what step 4 already demonstrates.

### 6. Confirm the honest limit: nothing here blocks the PR from merging today

```
gh pr view --json mergeable,mergeStateStatus
```

**You should see:** `mergeable: MERGEABLE` (or `UNKNOWN` while GitHub computes it) with no required-check failure preventing a merge button from being offered — because, per the note at the top of this document, `main` carries no branch protection yet. This is the one acceptance criterion this document cannot mark as met on this repository; it is a known gap, not a defect in the workflow file.

### 7. Close the throwaway PR and branch

```
gh pr close --delete-branch
```

**You should see:** the PR close and the remote branch delete. Locally:

```
git checkout feat/m2-eval-deploy-067
git branch -D test/eval-gate-trigger-067
```

---

## Part C — the three suites the workflow runs actually run, and actually publish what the ticket asks for

This is the part of the job a runner would execute, run directly so it is verified independent of whether a runner exists.

### 8. Bring the stack up, the same way the workflow's "Bring up the stack" step does

If you have never run Askwell before, follow `M2-EVAL-TEST-065`'s "Before you start" and "Cold start" sections first (`.env`, `build-api`, `podman compose up -d`, `db upgrade head`, `scripts/dev.sh inference`). Otherwise, confirm it is already up:

```
podman compose ps
scripts/dev.sh inference &
```

**You should see:** `postgres`, `redis`, `egress-proxy`, `api`, `worker` all `Up`, and, after a short wait, the inference supervisor report `ready`.

### 9. Run the same three suites the workflow's "Run the eval suites" step names, in order

```
scripts/dev.sh eval --suite grounded_qa.v1
scripts/dev.sh eval --suite abstention.v1
scripts/dev.sh eval --suite conflicting_sources.v1
```

**You should see:** each command print a summary block ending `written to /app/eval/results/<suite>-<timestamp>.json`, and each exit `0` (`echo $?` after each, if you want to confirm) whenever the suite ran to completion — regardless of whether it cleared its pass bar. This is the workflow's own exit-code contract from `eval/bench.py`: `2` for a bad suite name (never reached here), `1` for either an infrastructure failure or a score below bar, `0` otherwise.

### 10. Confirm the result file carries what the audit requirement asks for

```
python3 -c "
import json, glob
f = sorted(glob.glob('eval/results/grounded_qa.v1-*.json'))[-1]
d = json.load(open(f))
print('model:', d['model'])
print('prompt_versions:', d['prompt_versions'])
print('started_at:', d['started_at'])
print('category_mean:', d['category_mean'], 'category_worst:', d['category_worst'])
"
```

**You should see:** a real model name (read from the inference supervisor's own state, never hand-typed), a `prompt_versions` mapping naming the prompt file(s) this suite exercised and their version, a real timestamp, and both a mean and a worst-of-3 figure printed together — the ticket's "results are recorded with model, prompt version and date" criterion, and `docs/build-plan.md`'s "worst-case is reported alongside mean" rule, both directly on disk.

### 11. Confirm the pass/fail distinction the job log makes is real, not just a comment

Look at your terminal output from step 9. For `abstention.v1` (`pass_bar: 0.90`, `strict` scoring per `docs/build-plan.md`'s "hallucination here is disqualifying" line), the summary states `passed: True` or `passed: False` outright — a strict suite's pass/fail is not left for a human to eyeball against a mean the way `grounded_qa.v1`'s is.

---

## Part D — manual dispatch produces a baseline, the honest version reachable today

### 12. Dispatch the workflow by hand against `main`

```
gh workflow run eval.yml --ref main
```

**You should see:** no error. GitHub queues a run.

### 13. Confirm it queues rather than silently vanishing

```
gh run list --workflow=eval.yml --limit 3
```

**You should see:** a new row for the run you just dispatched, `push`/`workflow_dispatch` trigger, status `queued` (or `in_progress` if a runner has since been registered — unexpected per this document's "before you start" note, but not wrong if it happens). This is the manual-dispatch acceptance criterion's reachable half: the workflow accepts the dispatch and queues correctly. The other half — that the queued run actually completes and produces a baseline — needs the `askwell`-labelled runner from the "before you start" note, which this repository does not have registered yet.

### 14. Cancel the run rather than leaving it queued

```
gh run cancel $(gh run list --workflow=eval.yml --limit 1 --json databaseId --jq '.[0].databaseId')
```

**You should see:** the run move to `cancelled` rather than sitting `queued` indefinitely on the tracker.

---

## Cleanup

```
git checkout feat/m2-eval-deploy-067
```

Confirm no stray branch or open PR remains from Part A (step 7 already deletes both). No `.env` or stack state was changed by this document beyond what Part C's "Before you start" pointer already covers.

---

## Known gaps

- **No self-hosted runner is registered against this repository.** `gh api .../actions/runners` returns zero. Every job this workflow queues sits `PENDING`/`queued` until either a runner is registered with the `askwell` label (a real one-time setup step, out of this ticket's scope per `docs/decisions.md`) or the 30-minute timeout fails it. This is stated, not discovered as a defect — the ticket's own testing notes call the dispatch-a-baseline scenario out separately from the trigger scenario for exactly this reason.
- **`main` has no branch protection, so nothing actually blocks a merge yet.** Step 6 confirms this directly. `docs/decisions.md`'s entry for this ticket states the required-status-check step is a deliberate manual repository-settings action left undone by this change, "not folded into a ticket's diff" with no code-review trail. Until someone sets it by hand, the workflow **measures** every qualifying change but does not **enforce** the block the ticket's headline acceptance criterion describes.
- **Only three of the eight `docs/build-plan.md` quality-gate categories run here** — grounded QA, abstention, conflicting sources. SQL safety and text-to-SQL arrive with M4, tool selection with M5, memory application with M3, web escalation discipline with M6.5. This is the ticket's own stated scope (`"the remaining suites... arrive with their features"`), not an omission found during this test.
- **The embedding and reranker model weights have no automated fetch path.** Only the generation model self-heals from `models_catalog.py`'s registry-verified spec (Part C step 9's prerequisite). If either of the other two is missing on a runner, the workflow's "Model weights present" step fails with a named reason (`::error::... has no automated fetch yet (#244)`) rather than guessing at a download — tracked as issue #244, not fixed by this ticket.
- **This document could not observe an actual passing (or failing-on-score) `Eval gate` check on a live PR**, because no runner exists to produce one. Parts A, B and D confirm the workflow's *reachable* behaviour — trigger paths, the honest pending/timeout state, and dispatch acceptance. Part C substitutes for the unreachable part by running the same three commands the job would run, directly.
