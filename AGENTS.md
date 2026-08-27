# AGENTS.md — Askwell

Single source of truth for how work happens in this repository. Read this before writing anything.

Companion files:

| File | What it holds | Mutable? |
| ---- | ------------- | -------- |
| `AGENTS.md` (this file) | How to work here: constraints, commands, workflow, versioning, tracker | Yes, but changes are decisions — log them |
| `docs/PRD.md` | **Business case only.** What the product is, who for, what it costs. Pitch-ready, no technical detail | Yes |
| `docs/architecture.md` | Technical decisions, topology, data model, security | Yes — changes are decisions, log them |
| `docs/data-sources.md` | Files, CSV, SQL dumps and the sandbox, live connections | Yes |
| `docs/memory-and-clarification.md` | The clarification loop and memory — the differentiator | Yes |
| `docs/audit-log.md` | The three stores, retention, tamper-evidence | Yes |
| `docs/web-search.md` | Web search: escalation not fallback, and how results stay separate | Yes |
| `docs/build-plan.md` | Phases, acceptance criteria, quality gate, repo layout | Yes |
| `docs/BRAIN.md` | Where the build stands right now: phase, next task, blockers | Yes — update every session |
| `docs/decisions.md` | Why things are the way they are | Append-only, newest first |
| `docs/states-and-edge-cases.md` | Every state a user can be in: empty, loading, partial, failed | Yes — grows as states are found |
| `docs/success-metrics.md` | What "working" means in numbers | Yes |
| `README.md` | What the product is, for a human arriving cold | Yes |
| `CLAUDE.md` | Shim that imports this file | Do not add rules here |

**Where things live:** root holds only what a tool or convention requires there — `AGENTS.md` and `CLAUDE.md` (agents discover them at root and will not find them in `docs/`), `README.md`, `VERSION`, `CHANGELOG.md`, `.github/`. All prose lives in `docs/`. Full layout and what arrives in which phase: `docs/build-plan.md`.

**`docs/PRD.md` is shared with users and investors.** Keep implementation detail out of it. If you find yourself writing a table name or a library in there, it belongs in `docs/architecture.md`.

---

## 1. What this project is

Askwell is a **personal AI over your own files and databases**, running entirely on one person's own machine. Add documents, spreadsheets, database dumps or live connections; ask questions in English; get answers with sources attached.

Four facts shape almost every decision here:

1. **One user, one machine.** No teams, no roles, no tenancy, no server, no high availability. The hardware is somebody's laptop, which is also running their browser. Anything assuming an operator, an administrator or a second machine is wrong.
2. **The competitor is opening files one at a time**, not ChatGPT. The target user cannot upload their material — client confidentiality, unpublished research, privilege. Local execution is not a feature, it is why the product can exist for them at all.
3. **It asks and remembers.** The clarification loop (`docs/memory-and-clarification.md`) is the differentiator. Local RAG tools exist; one that gets better at *your* data because it asked you does not. Protect this in scope discussions.
4. **It is free.** Revenue comes only from optional online-AI credits, which is the last thing built. No licence key, no seat cap, no trial. A free download has no sunk cost holding anyone — the first ten minutes decide everything.

**v1 is English-only.** Tamil, then possibly Sinhala, come later. Three hedges are kept so Tamil is later work rather than a re-index of everyone's corpus — multilingual `bge-m3` embeddings, a Tamil-aware Postgres full-text config, `tam` OCR traineddata bundled. Hedges, not features: not tested, not in the quality gate, not advertised.

> **History worth knowing.** Until 2026-08-10 this repository described a different product: an on-premise system sold to government ministries, with seat tiers, four user roles, an offline licence and a "Deployer" persona. It was repositioned to the above. Text about ministries, organisations, roles, licences or seats is leftover from that draft and is **wrong** — fix it rather than working around it.

**Current state: Phase 0, not started.** The repository is documentation only — no application code, no manifests, no tests, no CI. Section 5 reflects that honestly.

---

## 2. Where to look

| You need | Go to |
| -------- | ----- |
| What the product is, for a user or investor | `docs/PRD.md` — **business only, keep it that way** |
| Technical decisions, topology, data model | `docs/architecture.md` |
| How files, CSV, dumps and connections are ingested | `docs/data-sources.md` |
| The clarification loop and memory | `docs/memory-and-clarification.md` |
| What is logged, retention, tamper-evidence | `docs/audit-log.md` |
| How web search works and why it never auto-fires | `docs/web-search.md` |
| Phase scope, acceptance criteria, quality gate, repo layout | `docs/build-plan.md` |
| What a screen must handle beyond the happy path | `docs/states-and-edge-cases.md` — **read before designing or building any surface** |
| Whether the product is succeeding, in numbers | `docs/success-metrics.md` |
| Current phase, next task, blockers | `docs/BRAIN.md` |
| Why a choice was made | `docs/decisions.md` |
| Current application version | `VERSION` |
| What shipped in each version | `CHANGELOG.md` |
| A cold introduction | `README.md` |
| Exploring a UI direction before building it | `design-lab/` — a tool, never shipped |

Paths under `api/`, `web/`, `eval/`, `deploy/` appear in `docs/build-plan.md` as **planned** and **do not exist yet**. Do not link to them as if they do. When you create one, move it out of the planned list in the same change, or that section stops being trustworthy and gets ignored.

---

## 3. Constraints — never violate

Each is load-bearing. Enforcement points are listed because a rule with no enforcement point is a wish.

Rewritten 2026-08-10 with the repositioning. The old C7 (column-level access control per role) is **gone** — it protected one role from another, and there are no roles.

| # | Rule | Why | Enforced at |
| - | ---- | --- | ----------- |
| C1 | **Local by default. No outbound network calls** — not models, fonts, telemetry or CDNs — unless the user has explicitly enabled online AI **for that conversation**, or asked for a web search **for that question**. Both are deliberate acts, per-unit, and never sticky. | Disconnect the machine and it must work identically. The target user cannot upload their material at all; a single unexpected runtime URL breaks the only promise that makes the product usable to them. Two egress paths now exist, so the rule names both — an unnamed exception is how a constraint quietly stops being one. | Default-deny egress proxy; release test with the cable unplugged (`docs/architecture.md` §5) |
| C2 | **Model-generated SQL is never trusted.** Parse with `sqlglot`; reject anything that is not a single `SELECT`/`WITH`. Regex filtering is not sufficient and is not acceptable even temporarily, even in a branch. | Regex misses nested statements, comment tricks and dialect quirks. The user's real database is on the other side of this check. | `api/src/askwell/sql/` (Phase 3) **plus** a read-only database role, independently |
| C3 | **An imported dump is untrusted code.** It loads only into the isolated sandbox Postgres, one database per source, under a restricted non-superuser role. Never into Askwell's own database. | A `.sql` dump is a program. Importing means executing arbitrary DDL/DML from a file the user probably did not read. C2 governs querying and cannot govern loading — a dump that cannot write cannot import. | `docs/data-sources.md` §3; sandbox container with no egress |
| C4 | **Every factual claim carries a citation** — document and page, or the memory fact it came from. | The user has no external source to catch a wrong answer against; the citation is the only check they have. An uncited claim is a bug to fix, not a limitation to document. | Answer composition + quality gate (`docs/build-plan.md`) |
| C5 | **Abstention over invention.** When retrieval returns nothing above threshold, say so and name what would need adding. Never fall back on general knowledge for questions about the user's own material. | One confident fabrication about their own contract and the product is uninstalled. Abstention rate is also the signal that the corpus has gaps. | System prompt + abstention subset, pass bar ≥ 0.90. **Do not weaken those tests to make a change pass** — and do not lower the retrieval threshold to improve the abstention number (`docs/success-metrics.md` §2) |
| C6 | **The audit log is append-only and tamper-evident.** No `UPDATE`/`DELETE` grant for the app role; hash-chained records. **Do not call it immutable.** | The user owns the machine and can always delete a file. The honest guarantee is that the application never rewrites history and that manual tampering is detectable — which is genuinely useful and is all that is available. Overclaiming here is the same error the prompt-injection section warns about. | `docs/audit-log.md` §4 |
| C7 | **Retrieved content is data, never instruction.** Keep it delimited and keep the system prompt's statement to that effect intact. | Prompt injection via an ingested document otherwise drives real tool calls against the user's real database. | Prompt templates in `api/src/askwell/agent/prompts/` + trace flagging |
| C8 | **Secrets are environment variables, never committed.** `.env.example` updated in the same change that introduces a variable. | A committed connection string is a breach, not a bug. | `.gitignore` + review |
| C9 | **A bundled model's licence must permit redistribution and commercial use, and must not be access-gated.** Verified against the registry before the name is written into configuration. | Askwell ships weights inside a redistributable offline installer under Apache-2.0. A model under restrictive or manually-gated terms cannot ship however well it performs — and an installer cannot click through an access agreement. Discovering this at packaging time in Phase 7 would be phase-blocking. | Model selection; the offline bundle build (`docs/build-plan.md` Phase 7) |
| C10 | **Web results are never your material.** A web-sourced claim never enters the provenance margin, is always marked as not-your-material with its retrieval date, and web search is offered only *after* Askwell has abstained — never as an automatic fallback when retrieval comes back thin. | The margin is for documents the user owns and can open; a URL can change or vanish after the answer. And if the web is reachable automatically, "nothing in your files answers this" stops being true, which removes the behaviour the whole product is built to protect (C5). Escalation the user asks for keeps abstention meaningful; a fallback destroys it. | Answer composition; the abstention surface (`docs/ux/ask.md`); trace flagging |

---

## 4. Working rules

- **`design-lab/` is a tool, not the product.** It never ships, `web/` never imports from it, and the external AI providers its scripts call are **not precedent for runtime network calls** — C1 is absolute in the product. Its `src/tokens.css` is seeded from `docs/ux/design-system.md`, which stays the source of truth.
- **Do not scaffold beyond the current phase.** In Phase 0, do not create empty `voice/` modules "for later". Speculative structure rots and misleads the next session into thinking work exists.
- **Edit surgically.** Targeted string replacement over file rewrites. If a change touches more than three files, describe the plan and get agreement first. Full-file regeneration silently destroys prior decisions.
- **Run the thing.** A task is not complete because the code looks right. Start the stack, hit the endpoint, read the response. `podman compose up -d && curl ...` is the definition of done.
- **Tests accompany the code, not the phase.** Retrieval, SQL validation, and the agent loop get tests *first* — they are where correctness is hardest to eyeball.
- **A surface is not finished until its states are.** Before building or designing any screen, read the matching section of `docs/states-and-edge-cases.md`. A happy path with no empty, loading, denied, or failed state is a demo. When you find a state that document does not list, add it there in the same change.
- **One task at a time.** Finish, verify, update `docs/BRAIN.md`, then take the next. Batching four features means discovering which broke by bisection.
- **Never hardcode a model name in application code.** Models come from configuration, selected by deployment profile.
- **Verify every model, weight and traineddata name against the registry before writing it down** — name, current version, licence, and whether access is gated. Do not assert a model does or does not exist from memory. This rule exists because it was broken twice: correct model names in the original PRD were replaced with older ones, and a correctly-chosen Apache-2.0 voice model was swapped for one with per-voice licensing (issues #24, #25).
- **All prompts live in `api/src/askwell/agent/prompts/` as versioned files.** Never inline a system prompt in application logic.
- **Any prompt change requires an eval run.** Run `eval/bench.py` against the affected suite and record before/after in `docs/BRAIN.md`. Prompt engineering without measurement is guessing, and small models are exactly where guessing fails.

### When to stop and ask

- A `docs/PRD.md` §11 open decision blocks the task → **stop and ask.** Do not pick a default.
- Two reasonable architectures exist and the PRD does not choose → present both briefly with a recommendation, then ask.
- A requirement seems wrong or contradicts another → say so directly. The PRD was written before implementation; parts of it are wrong, and finding that out during the build is the point. Do not silently work around a bad requirement.
- A shortcut would save real time but violates a constraint in §3 → propose it explicitly rather than taking it.

What not to do: guess, note the guess in a comment, keep going. That is how a build accumulates decisions nobody made.

---

## 5. Commands

**The host needs Podman and nothing else.** Python, Node, pnpm, the dependency resolvers, the linters, the type checkers and the test runner all live inside the API and web images. Do not install them on the host and do not invoke the host's Python — it is 3.14, the project targets 3.12, and the AI toolchain has no 3.14 wheels.

Everything runs through one entry point:

| Purpose | Command | Status |
| ------- | ------- | ------ |
| All read-only checks, in order | `scripts/dev.sh check` | **Verified** |
| Lint | `scripts/dev.sh lint` (`--fix` to repair) | **Verified** |
| Format | `scripts/dev.sh format` / `scripts/dev.sh fmt-check` | **Verified** |
| Typecheck (`mypy --strict`) | `scripts/dev.sh typecheck` | **Verified** |
| Python tests | `scripts/dev.sh test` | **Verified** |
| Database-backed tests | `scripts/dev.sh test-db` (needs the stack up) | **Verified** |
| Alembic against the stack | `scripts/dev.sh db upgrade head` | **Verified** |
| A psql shell | `scripts/dev.sh psql` | **Verified** |
| Verify the audit chains | `podman compose exec api askwell-verify` | **Verified** |
| Rebuild the image | `scripts/dev.sh build` | **Verified** |
| Anything else inside the image | `scripts/dev.sh run <cmd>` / `scripts/dev.sh shell` | **Verified** |
| Regenerate the lockfile | `scripts/dev.sh lock` | **Verified** |
| All frontend checks | `scripts/dev.sh web-check` | **Verified** |
| Build the frontend to `web/out` | `scripts/dev.sh web-build` | **Verified** |
| Install frontend dependencies | `scripts/dev.sh web-install` | **Verified** |
| Anything else in the frontend image | `scripts/dev.sh web-run <cmd>` / `web-shell` | **Verified** |
| Build-runner guard tests | `bash scripts/guards.test.sh` | **Verified** |
| Bring up the stack | `podman compose up -d` | **Verified** |
| Eval suite | `python eval/bench.py --suite <name>` | M1 |

Two things about `scripts/dev.sh` that are deliberate:

- **Every command runs with `--network=none` unless it demonstrably needs a network**, and the exceptions are named rather than assumed. C1 is cheapest to enforce where the toolchain runs, and a linter has no business reaching an index. Four commands opt back in explicitly: `lock` and `web-install` resolve from a package registry, and `db`, `psql` and `test-db` join the stack's own network to reach Postgres — which is the local machine talking to itself, not egress.
- **The lockfile is the pin, `pyproject.toml` holds only bounds.** The image installs with `uv sync --locked`, not `--frozen`: `--frozen` never reads `pyproject.toml`, so adding a dependency and forgetting to relock produces a build that succeeds while missing it, surfacing much later as an `ImportError` with no obvious cause. Widening a bound changes no build until you run `lock` deliberately and review the diff.

Do not add a command to this table until it has been run and its output read.

### Local machine facts that will bite you

Verified on this machine, 2026-08-10:

| Thing | Reality | Consequence |
| ----- | ------- | ----------- |
| System `python3` | **3.14.6** | The project targets **3.12**. Do not build against system Python — pin 3.12 in the container image and in any local virtualenv, or you will hit dependency wheels (llama-cpp bindings, OCR, embeddings) that have no 3.14 build and fail at install time with an unhelpful error. |
| `podman-compose` | **not installed** | `podman compose` works, routed through an external `docker-compose` provider (v5.1.1). Use `podman compose`. `docs/PRD.md` §9 Phase 0 acceptance says `podman-compose up`; treat that as meaning "the Compose stack comes up", not as a literal binary requirement. |
| `docker` | not installed | Podman only. Do not write instructions that assume a Docker daemon or Docker socket mount. |
| `ruff`, `mypy`, `uv` | not installed | Phase 0 must install them, ideally inside the api container so the deployer's machine needs nothing. |
| Node / pnpm | node 22.22.2, pnpm 11.5.2, npm 10.9.7 | pnpm available; pick one and record it in `docs/decisions.md`. |
| Markdown linter | none | Markdown is not linted. Do not claim it is. |

---

## 6. Conventions

Derived from `docs/PRD.md` §5.1 and the two commits in history. Where the repo has no precedent yet, that is stated rather than invented.

**Python** — 3.12. `ruff` for lint and format. `mypy --strict` on `api/src/`. Pydantic v2 at every boundary. Async throughout; no blocking calls in request handlers. `structlog`, JSON output, never `print`.

**TypeScript** — strict mode. Server components by default; `"use client"` only where interactivity requires it. `zod` for anything crossing the API boundary. No `any`.

**Database** — Alembic migrations, never hand-edited schema. Every migration reversible. No raw SQL in application code outside `api/src/askwell/sql/`.

**Commits** — Conventional Commits, scoped to one logical change, with the PRD phase in brackets:

```
feat(ingest): add scanned-pdf OCR fallback [P1]
fix(sql): reject CTE with trailing DELETE [P2]
docs: correct container count in architecture §2
chore(release): 0.2.0
```

Existing history uses `feat:` and `docs:`-style subjects, so this is an extension of what is already there, not a new imposition. Reference the issue number in the body: `Refs #12`.

**Branches and PRs** — Work happens on a branch off `main` and lands through a PR. Branch names: `feat/<short-slug>`, `fix/<short-slug>`, `chore/<short-slug>`, `docs/<short-slug>`. `main` is the default branch and should stay releasable.

**Errors** — fail loudly in development, degrade gracefully in production. A failed embedding job retries with backoff and surfaces in the admin console; it does not silently drop the document.

**Tests** — no framework in the repo yet; `pytest` is the intent for Python. Retrieval, SQL validation, and agent-loop modules get tests before their implementation.

---

## 7. Versioning

**Canonical source of truth: `VERSION` at the repo root. Current value: `0.1.0`.**

There is exactly one manually maintained version value. When `api/pyproject.toml` and `web/package.json` appear in Phase 0, they **read** from `VERSION` rather than declaring their own — a second hand-edited version is how a build ships with a number that matches nothing.

Format: `MAJOR.MINOR.PATCH`. No fourth component. A hotfix is a `PATCH` release, not `1.4.2.1`.

**Build number:** none. This is a server-side Compose deployment with no app-store build counter. If the offline install bundle in Phase 5 needs a unique build identifier, add it then as an always-increasing integer and represent it as `1.4.2+57` — the semantic version identifies the release, the build number identifies the exact generated build. Never reset or decrease it.

**Cadence: bump on every completed change**, in the same commit as the work. Not batched at release time — the point is that a `docs/BRAIN.md` entry, a closing issue comment, and a version all line up.

**Within a phase, a completed ticket is a `PATCH`. The phase landing is the `MINOR`.** M0 has 21 tickets; bumping `MINOR` per ticket would land Phase 0 at `0.22.0` and contradict the `0.1.0` → `0.2.0` line below. So tickets walk `0.1.1`, `0.1.2`, … and the milestone completing takes the `MINOR`. This applies to the `0.x` series; once `1.0.0` ships, the table above governs on its own and a feature is a `MINOR` regardless of which ticket carried it.

| Change | Action |
| ------ | ------ |
| Breaking change | `MAJOR`, reset the rest: `1.4.2` → `2.0.0` |
| Backward-compatible feature | `MINOR`, reset `PATCH`: `1.4.2` → `1.5.0` |
| Bug fix | `PATCH`: `1.4.2` → `1.4.3` |
| Emergency hotfix | `PATCH`: `1.4.3` → `1.4.4` |
| Non-breaking security fix | `PATCH` |
| Docs, comments, tests, refactoring, formatting, internal maintenance with no user-visible behaviour change | **no change** |
| Build-only change | semantic version unchanged; increment the build number only if one exists and a new distributable build is produced |

If one change spans several types, the highest applicable wins: `MAJOR` > `MINOR` > `PATCH`.

While the version is `0.x`, a phase completing counts as a `MINOR` bump — Phase 0 landing takes `0.1.0` → `0.2.0`. `1.0.0` is the first pilot-ready build (end of Phase 5).

**Verify:** `cat VERSION`. Once the version is surfaced in the API or admin console, it must be derived from this file, never re-typed.

**Changelog:** every version bump adds an entry to `CHANGELOG.md` under the new version heading.

**Do not publish a release, push a version tag, deploy, or upload a build unless explicitly asked.**

---

## 8. Issues and the decision log

### The core rule

**An item raised only in conversation is lost.** A chat transcript is not a record anyone will read again. Anything a future reader would need — an open question, a deferred fix, a discovered bug, a risky assumption, a TODO you are about to write into code — becomes a GitHub issue **at the moment it is found**, not in a closing summary.

Tracker: `Rumeasiyan/askwell` (private). Issues are assigned to `Rumeasiyan`.

### Issues must be self-contained

The reader has not seen the conversation. No "as discussed", no "the thing we talked about". Every issue states:

- **What** it is, in a sentence.
- **Why it matters** — the concrete consequence of ignoring it, not "this is important".
- **Where it surfaced** — file paths, PRD section numbers, commit SHAs.
- **For decisions:** the realistic options, a recommendation, and the reasoning behind the recommendation.

### The work loop

1. Check for an existing open issue covering the work: `gh issue list --search "<terms>"`.
2. If none, create one and assign it: `gh issue create --assignee Rumeasiyan --label <labels>`.
3. Branch: `git checkout -b feat/<slug>`.
4. Work. Bump `VERSION` and add a `CHANGELOG.md` entry per §7.
5. Commit referencing the issue in the body: `Refs #12`.
6. Open a PR: `gh pr create --fill`.
7. Comment the outcome on the issue and close it.

The **closing comment** records: what was built, what was actually verified (the command run and what it returned — not "looks correct"), the resulting version, and anything deliberately deferred with a link to the follow-up issue.

### Too small for an issue

Typos, formatting, renaming a local variable, a one-line correction to a document you are already editing. Filing these fills the tracker with noise until nobody reads it. If it takes longer to describe than to fix, and nothing downstream depends on knowing about it, just fix it.

### Labels

| Label | Use for |
| ----- | ------- |
| `phase:0` … `phase:8` | Which build phase the work belongs to (`docs/build-plan.md`) |
| `blocked:decision` | Waiting on a `docs/PRD.md` §11 answer. Do not start work on these. |
| `constraint:local-first` | Touches C1 — network access, bundling, online opt-in |
| `constraint:sql-safety` | Touches C2 — SQL validation, read-only roles |
| `constraint:sandbox` | Touches C3 — dump import isolation |
| `constraint:grounding` | Touches C4/C5 — citations, abstention, retrieval thresholds |
| `constraint:audit` | Touches C6 — audit stores, retention, hash chain |
| `constraint:injection` | Touches C7 — retrieved-content-as-data boundary |
| `constraint:web-escalation` | Touches C10 — web search stays an escalation the user performs, and its results stay separate from the user's own material |
| `eval` | Changes eval suites, pass bars, or requires an eval run to land |
| `v2:language` | Tamil or Sinhala work. Out of v1 scope — do not start without a scope decision. |
| `deploy` | Install bundle, hardware probe, deployment profiles, licensing |
| `bug`, `documentation`, `question` | GitHub defaults, kept |

**Any issue carrying a `constraint:*` label must state, before it is closed, how the constraint was preserved.** That is the whole point of the label — it forces the check to be written down where an auditor can find it.

### Decision log

`docs/decisions.md`, append-only, newest first.

Bar for an entry: **something a competent person would later ask "why is it like this?" about.** Architecture changes, dependency choices, resolved §11 questions, reversals of earlier decisions. Not routine implementation choices — those are visible in the diff.

Each entry: date, title, **Decision**, **Why**, **Consequences**, **Refs**. The *why* should be longer than the *what*, and must include what was rejected and the trade-off accepted. The what is visible in the code; the why is not, and is exactly what gets lost.

When a `docs/PRD.md` §11 question is answered, the answer becomes a decision-log entry **and** the §11 item is struck from the PRD **and** `docs/BRAIN.md`'s blocker list is updated. All three, same change, or the next session gets a different answer depending on which file it reads.

---

## 9. Session workflow

1. Read `docs/BRAIN.md` — current phase, last completed task, open blockers, decisions since the PRD.
2. Read the relevant `docs/PRD.md` section for the current phase. The section, not the whole PRD.
3. State the one task you are about to do. If it is larger than roughly two hours, decompose it and do the first piece.
4. If the task is blocked on a `docs/PRD.md` §11 item → **stop and ask.**
5. Find or create the GitHub issue (§8). Branch off `main`.
6. Do the work. Tests alongside the code.
7. **Run it.** Start the stack, hit the endpoint, read the response.
8. Decide the version impact (§7). Bump `VERSION` and update `CHANGELOG.md` if the change is user-visible.
9. If a decision was made, append to `docs/decisions.md`.
10. Commit (Conventional Commits, `Refs #N`), push, open a PR.
11. Comment the outcome on the issue and close it.
12. Update `docs/BRAIN.md`: what completed, what was decided and why, what broke, what is next. **A stale `docs/BRAIN.md` makes the next session start from confusion.**
