# Build runner

**Specification only. Nothing here is built.** No script, no state directory, no configuration exists yet — this document is what the session that writes the runner must follow.

Where this document and an implementer's instinct disagree, **this document is what was decided**. If a decision here is wrong, change it here and record why in `decisions.md`; do not diverge in the script.

| | |
| --- | --- |
| Rulebook the runner defers to | [`../AGENTS.md`](../AGENTS.md) — declares itself the single source of truth |
| Work items | [`backlog/`](backlog/) — 198 tickets across 10 milestone files |
| Plan and gate definition | [`build-plan.md`](build-plan.md) |
| Decision log | [`decisions.md`](decisions.md) — append-only, newest first |
| Current state | [`BRAIN.md`](BRAIN.md) |

---

## 1. The problem this solves, and the one it does not

Askwell has **198 tickets and zero lines of application code**. The tickets are unusually complete — each carries acceptance criteria, edge cases, dependencies, and a cold-start manual test. What does not exist is anything that turns one into a commit without a human driving every step.

**The runner is a driver, not a second rulebook.** Everything it tells a session must either come from the files above or be about running the pipeline itself. The moment it starts restating a constraint, that constraint has two homes and the copies drift.

### The chicken-and-egg this repo has and most do not

**There is no gate.** Verified: no `pyproject.toml`, no `package.json` at the root, no `Makefile`, no `compose.yaml`, no `.github/workflows/`, no git hooks, no `.pre-commit-config.yaml`. The only manifest in the tree is `design-lab/package.json`, which belongs to a design tool that never ships and must never be mistaken for the product's gate.

The gate is *built by* the first milestone. `M0-FOUND-DEPLOY-001` pins Python 3.12 in the API image with `uv`, `ruff`, `mypy` and `pytest` inside it; later M0 tickets add the Compose stack and CI.

**So the runner cannot gate M0 the way it gates everything after it.** Section 7 says what to do about that. An implementer who writes the gate as though it already exists will produce a runner that cannot run its own first ticket.

---

## 2. The pipeline

```
BUILD ──▶ GATE ──▶ AUDIT ──▶ MANUAL-TEST DOC ──▶ PR ──▶ STOP
          (repair ≤N)   (independent session)
```

| Phase | Who runs it | Produces | Proof it succeeded |
| --- | --- | --- | --- |
| **Build** | Fresh agent session, one per ticket | Working-tree changes, tests | A non-empty diff *and* the gate passing |
| **Gate** | The runner, deterministically | Pass/fail per command | The success line for each command (§7.3) — never the exit code |
| **Repair** | Same lineage as build, resumed | Fixes | Gate passes, or attempts exhausted → stop |
| **Audit** | Separate session, resumed across the run | A verdict and any filed issues | Final line is exactly `AUDIT: PASS` or `AUDIT: FAIL` |
| **Manual-test doc** | Separate session, resumed across the run | A cold-start walkthrough file | File exists and starts at launch, not at a route |
| **PR** | The runner | Branch, commit, pull request | PR URL printed |
| **Stop** | The runner | A summary a human reads | Process exits; the queue does not advance |

**Default batch size is one ticket per invocation, and `STOP_AFTER_EACH` defaults on.** N tickets built unattended is N *untested* tickets, and a defect in the first invalidates everything stacked on it — which is the same reason `AGENTS.md` §4 already says "one task at a time". Running the queue should be a deliberate act, not the default behaviour of the command.

---

## 3. What already exists that the runner must not rebuild

| Asset | Path | The runner's relationship to it |
| --- | --- | --- |
| Constraints C1–C10 | `AGENTS.md` §3 | **Reference by name. Never restate.** A copy in the runner is a copy that drifts |
| Conventions, commit format, branch policy | `AGENTS.md` §6, §8 | Cite; the build prompt points the session at them |
| Ticket bodies | `backlog/M*.md` | Paste **verbatim and whole**. Do not summarise — a summarised ticket is a ticket whose edge cases were dropped |
| Ordering | Ticket IDs plus a **`Dependencies:` field on every ticket** | §5 |
| Definition of done, per ticket | The ticket's own `Acceptance Criteria` and `Testing Notes` | Do not invent additional criteria |
| Decision log | `decisions.md`, 21 entries | Sessions read it before changing anything that looks wrong, and append to it |
| Deferred work | GitHub issues on `Rumeasiyan/askwell` | §8, injected into the ticket that owns it |
| Open questions | `PRD.md` §11 (4 items) and issues labelled `blocked:decision` | §9 |
| Version and changelog rules | `AGENTS.md` §7 — bump per completed change | Named in the build prompt; the runner checks the pair in §9 |

---

## 4. What carries over, with the failure that produced it

No prior-art runner was supplied for this project. Everything below is stack-independent and each row is a real, repeated failure mode. **A rule without its scar is a rule that gets optimised away**, so the scar is stated.

### 4.1 Absence of a success line is failure, never success

Exit codes lie. Test runners exit `0` after a fatal collection error with the suite never run. Bundlers print an error and exit `0`. An agent session that ends waiting on a background task loses its final verdict line entirely.

**Match the summary line, not `$?`.** Per-command signals in §7.3.

### 4.2 An empty diff is a failure, not a pass

A session that died on an API error changes nothing. Nothing breaks nothing, so the gate goes green and the ticket ships unimplemented.

**`git diff --quiet` after a build means fail, always.**

### 4.3 Decolour before matching, and use POSIX classes

Runners emit ANSI escapes even when redirected, so an anchored match never fires. And `\s` is a GNU extension — to BSD grep it is a literal `s`. **Strip escapes, then match with `[[:space:]]`.**

### 4.4 Run from an immutable copy of the script

Bash reads a script incrementally by byte offset. Editing it mid-run resumes mid-token, in a way that looks like data corruption rather than a self-inflicted wound.

**Re-exec from a `mktemp` copy**, and carry the real root in an environment variable — `BASH_SOURCE` then points at the temp file.

### 4.5 Prompt-integrity sentinels

An unescaped backtick in an unquoted heredoc is command substitution. Bash runs it and substitutes an **empty string** into the prompt. The ticket then builds from a prompt quietly missing whatever those backticks wrapped, and `bash -n` does not catch it.

This repo's tickets are *dense* with backticks — table names, tokens, file paths, `sqlglot`, `--ask-provenance`. **Grep the rendered prompt for phrases that must survive and refuse to run if any is missing.** Suggested sentinels: the ticket ID, the string `AGENTS.md`, and the ticket's `Acceptance Criteria` heading.

### 4.6 Deferred work is injected into the ticket that owns it

A ledger entry that never reaches the session that owns it is a nicer place to lose the work.

**Query the tracker for issues naming the current ticket ID and paste them under a heading saying they are part of the definition of done.**

### 4.7 A named owner beats an accurate one

A misassigned item is cheap — that session reads it, sees it does not fit, and re-points it. An unassigned item is inert.

**`unassigned` is not the cautious choice; it guarantees nothing happens.**

### 4.8 Formatters write, they do not fail the gate

Run the formatter, then the checks. **Never fail a ticket for formatting alone** — it is noise that trains a reader to ignore gate failures.

### 4.9 Session lineages, not sessions-per-ticket

| Lineage | Policy | Why |
| --- | --- | --- |
| **Build** | Fresh session per ticket | Each is a new implementation problem; stale build context misleads |
| **Audit** | One session, resumed across the run | Keeps the property that matters — *the auditor did not write the code* — and drops the one that only costs tokens, relearning conventions. It also makes the auditor consistent across tickets |
| **Manual-test writer** | One session, resumed | Same reasoning |

Persist session ids in ignored files. **Deleting one restarts that lineage** — that is the intended reset mechanism.

---

## 5. What must **not** carry over

No reference implementation was supplied, so this section lists the **plausible wrong defaults** an implementer would otherwise reach for here. Each row is derived from something verified in this repository.

| Tempting default | Why it is wrong here | Do instead |
| --- | --- | --- |
| Commit straight to `main` | `AGENTS.md` §6 requires a branch and a PR, and `main` stays releasable. Git history confirms: every recent commit is a squash-merged PR | Branch, commit, open PR, stop |
| Trust branch protection to enforce it | **`main` is not protected** — verified, the API returns 404. The policy is convention only | **The runner is the enforcement.** Refuse to run on `main`; never push to it |
| Read work items from an issue tracker | Tickets are **markdown sections** in `backlog/M*.md`. Issues are used for *deferred work and open questions*, not for the backlog | Parse the milestone files; query issues only for §4.6 and §9 |
| Order by file position | Every ticket carries an explicit **`Dependencies:`** field, and `backlog/README.md` warns that a ticket is only correctly placed if everything needed to reach it has shipped | Order by dependency; use ID sequence only to break ties |
| Skip permission prompts globally | The gate touches containers and a database. A runner that can do anything unattended will eventually do something unattended at 3am | Allow only what the gate needs |
| Auto-commit and continue to the next ticket | `AGENTS.md` §4: finish, verify, update `BRAIN.md`, then take the next | Stop after each; advancing is a deliberate act |
| Maintain a parallel notes file for the agent | This repo deliberately has **one** rulebook; `CLAUDE.md` exists only to import it and says so | Point at `AGENTS.md`. Add nothing beside it |
| Treat `design-lab/` as the product | It is a design tool that never ships, with its own manifest and its own lint config | Exclude it from the gate entirely |
| Bump the version because the ticket says so | `AGENTS.md` §7: documentation, tests and refactoring do **not** bump | Let the session decide from §7; the runner only checks bump-and-changelog agree (§9) |

---

## 6. Files and layout

```
scripts/
  build-runner.sh          # the runner; re-execs from a temp copy (§4.4)
  guards.sh                # stop file + budget ceiling; separately testable (§11)
.build-runner/             # state — git-ignored in full
  prompts/<TICKET>.build.txt      # rendered prompts, kept
  prompts/<TICKET>.audit.txt
  prompts/<TICKET>.doc.txt
  logs/<TICKET>.<phase>.log
  session/audit.id                # resumed lineages (§4.9)
  session/doc.id
  ledger.jsonl                    # spend per ticket, append-only
  STOP                            # presence halts between tickets
docs/manual-tests/<TICKET>.md     # committed — the walkthrough is a deliverable
```

**Keep the rendered prompts on disk.** When a ticket goes wrong the first question is always *what was it actually told?* — and without the prompt that question is unanswerable.

`.build-runner/` is ignored because it is machine-local and full of session ids. `docs/manual-tests/` is committed because the walkthrough is part of what the ticket delivers, and because re-walking it on the next ticket is how upstream regressions surface (§10).

---

## 7. The gate, exactly

### 7.1 It does not exist yet

Nothing in §7.2 runs today. The commands are created by M0 — principally `M0-FOUND-DEPLOY-001`, which puts `uv`, `ruff`, `mypy` and `pytest` inside the API image so the host needs only Podman.

**Consequence for the first tickets:** M0 must be built with the gate reduced to what exists at that moment — the tree is non-empty, the commit builds, and the manual walkthrough passes. The runner must therefore treat **a missing gate command as a skip with a printed warning, not as a pass and not as a crash** — and must print, at the end of every run, which gate commands were absent. A silently shrinking gate is how a green run stops meaning anything.

### 7.2 Commands, in order

Exact invocations are fixed by M0 and must be read from what M0 produced rather than assumed here. The order is not negotiable:

1. **Format** — writes, never fails the gate (§4.8)
2. **Lint**
3. **Typecheck** — `mypy --strict` over the application source, per `AGENTS.md` §6
4. **Tests**
5. **Build** — the container image, and the frontend where the ticket touches it

`design-lab/` is excluded from all five.

### 7.3 Success signals, per command

Fill this table from the real output of each command once M0 lands. **Every row must be a summary line, not an exit code** (§4.1).

| Command | Match on | Not |
| --- | --- | --- |
| Lint | The tool's own "no issues" summary line | `$?` |
| Typecheck | The "no issues found in N source files" line | `$?` — it exits 0 on some internal errors |
| Tests | The pass/fail summary line, **and** a collected-count greater than zero | `$?` — a collection error exits 0 with nothing run |
| Build | The final success line | `$?` |

### 7.4 Preconditions, verified before any ticket runs

Each failure prints the fix command with it.

| Precondition | Failure message must include |
| --- | --- |
| Working tree clean | `git status --short`, and that the runner will not build on top of uncommitted work |
| Not on `main` | The branch to create instead |
| Container runtime present | `podman compose` — **not** `podman-compose`, which `AGENTS.md` §5 records as absent on the dev machine |
| Stack up and healthy | The bring-up command |
| Datastore reachable **at the configured URL** | The URL actually being used |
| Migrations applied | The migrate command |
| Tracker credentials present | The auth command |
| Spend ceiling set | §11 — unset refuses to start |

**The local trap this repo will hit.** `architecture.md` §2 puts inference in a **native host process** while everything else is a container. A native service bound to `127.0.0.1:PORT` shadows a container's `0.0.0.0:PORT` mapping: the container reports healthy, the port answers, and the answer comes from the wrong server. **Check the identity of what answers, not that something answers.**

---

## 8. The prompts

The rendered prompt is the whole product; everything else is plumbing. Three prompts share **one common block** so they cannot drift.

### 8.1 Shared block

- **`AGENTS.md` is authoritative. Read it before deciding anything.** Its §3 holds constraints **C1–C10**; breaking one does not fail a test — it destroys something or creates exposure. C2 (SQL through `sqlglot`, never regex), C3 (dumps are untrusted code), C5 (abstention over invention) and C10 (web search is an escalation, never a fallback) are the ones a passing gate will not catch.
- **Read `decisions.md` before changing anything that looks wrong.** Odd-looking code is often a recorded decision. Disagreement gets recorded, not silently reversed.
- **Log what you do not fix now** — as a GitHub issue, in the house format from `AGENTS.md` §8: what · why it matters · where it surfaced · options with a recommendation. A closing summary is discarded and the work is lost.
- **Write new decisions back to `decisions.md`**, with the *why* longer than the *what*.
- **Resolve any open question naming this ticket as owner** before it closes — answered, re-owned, or escalated.
- **Your training data may be older than this stack.** The installed majors are read from the manifest at render time and pasted here. An API you cannot confirm against what is installed is an API you do not use. `AGENTS.md` §4 requires registry verification for model, weight and traineddata names — that rule exists because it was broken twice.
- **Prefer what exists**, in order: something already in this repo; an already-installed package; the framework natively; then a new maintained package, version looked up from the registry and checked for **compatibility, not just currency**.
- **Never hand-roll authentication, cryptography, or permission checks.**

### 8.2 Build prompt adds

- The ticket body **verbatim and whole**.
- Every open issue and open question naming this ticket, under a heading stating they are part of the definition of done (§4.6, §9).
- The workflow from `AGENTS.md` §9, and the commit format from §6 including the phase marker.
- Tests covering the ticket's stated acceptance criteria — `AGENTS.md` §4 requires them **first** for retrieval, SQL validation and the agent loop.
- Version and changelog impact per `AGENTS.md` §7.
- **Implement only this ticket. If it depends on something unbuilt, say so and stop — do not silently stub.**

### 8.3 Audit prompt adds

- It **did not write this code** and must not assume it is correct.
- Check against **the ticket's own** acceptance criteria, edge cases and constraint checklist — not a generic review.
- Hunt: reinvention of something already in the repo, stale APIs, missing tests, silent stubs, and any constraint in `AGENTS.md` §3 that a passing gate would not catch.
- **Do not run the full suite, and do not end the turn waiting on a background task.** That ends the session and loses the verdict.
- **End the final message with exactly `AUDIT: PASS` or `AUDIT: FAIL`.**

### 8.4 Manual-test prompt adds

- Start from a **cold start** and walk the whole path as a user would — launch the application, complete first-run if needed, navigate by clicking.
- **Never "go to /settings". Never "call this endpoint".** Direct-jump testing never catches broken navigation, lost session state, or dead ends — and re-walking the path each ticket surfaces upstream regressions on the *next* ticket rather than in production.
- Expand the ticket's own `Cold-start manual walkthrough` into something a non-technical person can follow.
- **Read the code on disk.** Test what exists, not what the ticket assumed would be built.
- End with **known gaps** — what is deliberately unbuilt, so it is not reported as a defect.

---

## 9. The stop gate

End-of-ticket sequence: create branch `feat/<slug>` (or the matching prefix from `AGENTS.md` §6) → commit with the phase marker and `Refs #N` → push → open PR with `gh pr create --fill` → print summary → **exit**. The runner never merges and never advances on its own.

Conditions that must print **unmissably**:

| Condition | Why it stops a human |
| --- | --- |
| `AUDIT: FAIL` | The obvious one |
| **The auditor filed a high-severity issue against *this* ticket** | The auditor saying *what I was asked to review is not there*. It is the one signal the empty-diff guard cannot catch, because both sessions did write something |
| An open issue naming this ticket is still open | **Check the code first** — the work is often done and the bookkeeping forgotten |
| An open question in `PRD.md` §11 or a `blocked:decision` issue names this ticket | An answered question that never got recorded means the next session re-derives a different answer |
| The ticket is marked `[BLOCKED]` | 17 tickets carry this today, in M6.5, M7 and M8. **A blocked ticket must never be built** — it waits on a decision, and building it guesses the answer |
| `VERSION` changed without a `CHANGELOG.md` entry, or the reverse | `AGENTS.md` §7 pairs them |
| The ticket contains user-facing copy | See below |

### Detecting a copy review from the ticket itself

Several tickets specify exact user-facing wording — refusal messages, the abstention statement, the dump-sandbox warning. **Detect this from the ticket body, never from a list in the script.** A list is a second source of truth that drifts the moment someone adds another ticket.

**No marker exists today.** This is a gap, and the recommendation is a single line in the ticket header — for example `**Human review:** copy` — added by whoever writes the runner, to the tickets that need it. Until that exists, the runner cannot detect this condition and must say so in its summary rather than implying it checked.

**Quote the copy into the runner's own output.** A gate that requires opening a file is a gate that gets skipped on the twentieth ticket.

---

## 10. Configuration

| Variable | Default | Notes |
| --- | --- | --- |
| `AGENT_BIN` | *(unset — required)* | The agent CLI. **Not hardcoded to a vendor** |
| `BUILD_MODEL` / `BUILD_EFFORT` | *(unset)* | Build carries the design work |
| `AUDIT_MODEL` / `AUDIT_EFFORT` | *(unset)* | Audit is read-and-check |
| `DOC_MODEL` / `DOC_EFFORT` | *(unset)* | Doc writing is read-and-check |
| `MAX_REPAIR` | `2` | Then stop |
| `RUN_AUDIT` | `1` | |
| `RUN_DOC` | `1` | |
| `STOP_AFTER_EACH` | `1` | **On by default** — running the queue is a deliberate act |
| `SPEND_CEILING` | *(unset — refuses to start)* | §11 |
| `DRY_RUN` | `0` | Renders prompts, calls nothing |
| `FORCE` | `0` | Rebuild a ticket already marked done |

Model and vendor names are **configuration, not prose**. Do not write one into this document or the script as though settled.

---

## 11. The guards

Both live in `scripts/guards.sh`, separate from the runner and testable before it exists.

**Stop file.** `.build-runner/STOP` halts the queue **between tickets**, and its contents print as the reason. Deliberately not checked mid-ticket: a runner killed mid-write leaves a tree somebody untangles by hand, which is worse than one more ticket finishing.

**Budget ceiling.** Refuses to **start** a ticket whose estimate would cross `SPEND_CEILING`. That ordering is the whole point — **a cap discovered after the fact is a bill, not a cap.** Every ticket carries an hour range, so the estimate is available before the work.

**Both fail closed.** A missing or unparseable `ledger.jsonl` **halts** rather than assuming zero. A guard that reads a corrupt file as `0` spent is worse than no guard, because it reports safety it is not providing.

---

## 12. What must never be automated

| Never | Why |
| --- | --- |
| Merge the PR | A human reads the diff, or nothing does |
| Push to `main` | Unprotected here, which makes the runner the only thing standing in the way |
| Publish a release, push a tag, deploy, upload a build | `AGENTS.md` §7 forbids it without an explicit request |
| Add a bot that auto-approves | It satisfies the rule and reviews nothing — **worse than no rule, because it looks like review happened** |
| Decide a business, vendor, or legal question | The search provider, credit pricing, the support boundary. Engineering runners answer engineering questions |
| Build a `[BLOCKED]` ticket | Building it guesses an answer the owner has not given |
| **Relax a constraint in `AGENTS.md` §3 to make a gate pass** | A runner that can weaken one will eventually weaken one at 3am. C5's tests are named in `AGENTS.md` as ones that must not be weakened to make a change pass — this is the automated version of that rule |

---

## 13. Genuinely open decisions

| # | Decision | Considerations | Where the answer goes |
| --- | --- | --- | --- |
| 1 | How the runner marks a ticket done | A state file is machine-local and invisible in review; a ticket-body edit is visible but makes every run a diff | `decisions.md` |
| 2 | Whether the audit lineage resets per milestone | A single lineage across 198 tickets accumulates context that may stop being relevant; per-milestone loses cross-milestone memory | `decisions.md` |
| 3 | Where the copy-review marker lives in the ticket header, and who back-fills it | §9 — required before any ticket with user-facing wording can be run unattended | The ticket format in `backlog/README.md` |
| 4 | Whether the runner may create the branch, or a human creates it | Affects whether a run can start from a clean `main` | `decisions.md` |
| 5 | What "estimate" the budget guard reads | Ticket hours are a range; the guard needs one number, and taking the low end under-protects | `decisions.md` |

**These are also filed as issues**, per `AGENTS.md` §8 — a question raised only in a document is a question with no owner.

---

## 14. Before the first run, and the first run itself

| Must close first | Who | Blocks |
| --- | --- | --- |
| M0 exists, so the gate exists | The first tickets, built manually or with a reduced gate (§7.1) | Everything |
| §7.3 filled from real command output | Whoever lands M0 | Every gate check |
| Copy-review marker decided and back-filled | Owner | Any ticket with user-facing wording |
| `SPEND_CEILING` set | Owner | The runner refuses to start without it |

**First ticket: `M0-FOUND-DEPLOY-001`.** It has no dependencies, it creates the toolchain every later gate needs, and it is small enough that a broken runner is obvious rather than subtle.

Build order for the runner itself:

> **Get the dry run printing a correct, complete prompt before it ever calls the agent.** The rendered prompt is the whole product; everything else is plumbing around it. A runner that calls an agent with a prompt nobody has read is a runner that will build the wrong thing quickly.
