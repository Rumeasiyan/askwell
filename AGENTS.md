# AGENTS.md — VaultQ

Single source of truth for how work happens in this repository. Read this before writing anything.

Companion files:

| File | What it holds | Mutable? |
| ---- | ------------- | -------- |
| `AGENTS.md` (this file) | How to work here: constraints, commands, workflow, versioning, tracker | Yes, but changes are decisions — log them |
| `docs/PRD.md` | What the product is: capabilities, architecture, phases, open questions | Yes, it is a draft and parts will prove wrong |
| `docs/BRAIN.md` | Where the build stands right now: phase, next task, blockers, eval scores | Yes — update every session |
| `docs/decisions.md` | Why things are the way they are | Append-only, newest first |
| `README.md` | What the product is, for a human arriving cold | Yes |
| `CLAUDE.md` | Shim that imports this file | Do not add rules here |

**Where things live:** root holds only what a tool or convention requires there — `AGENTS.md` and `CLAUDE.md` (agents discover them at root and will not find them in `docs/`), `README.md`, `VERSION`, `CHANGELOG.md`, `.github/`. All prose lives in `docs/`. See `docs/PRD.md` §10 for the full layout, including which directories arrive in which phase.

---

## 1. What this project is

VaultQ is a **sovereign AI workspace** for organisations that cannot use cloud AI at all — Sri Lankan government ministries, hospitals, banks, legal firms, NGOs holding sensitive case data. It ingests their documents, queries their operational databases in natural language, and answers by text or voice, entirely on their own hardware.

Two facts shape almost every technical decision here:

1. **The competitor is a filing cabinet, not ChatGPT.** These customers have no AI option today. So model quality is not the wedge — the fact that data never leaves the building is. Anything that weakens that guarantee destroys the product's reason to exist.
2. **The deployer installs it from a USB drive on a ministry network with no internet.** That is why there are no runtime network calls, no CDNs, no hosted control plane, and why the container count is treated as a cost.

Secondary wedge: bilingual English/Tamil. No cloud vendor serves Tamil-first Sri Lankan government workflows well.

Commercially it is self-hosted software with an offline signed licence, not SaaS. See `docs/PRD.md` §2.

**Current state: Phase 0, not started.** The repository is documentation only — no application code, no manifests, no tests, no CI. Section 5 reflects that honestly.

---

## 2. Where to look

| You need | Go to |
| -------- | ----- |
| What a capability is supposed to do | `docs/PRD.md` §4 (documents, database QA, agent loop, voice, admin) |
| Locked architecture choices | `docs/PRD.md` §5.1 — do not re-litigate these during implementation |
| Database tables | `docs/PRD.md` §6 |
| Eval categories and pass bars | `docs/PRD.md` §7 |
| Security requirements | `docs/PRD.md` §8 |
| Phase scope and acceptance criteria | `docs/PRD.md` §9 |
| Planned repository layout | `docs/PRD.md` §10 |
| Questions nobody has answered yet | `docs/PRD.md` §11 — **stop and ask; do not pick a default** |
| Current phase, next task, blockers | `docs/BRAIN.md` |
| Why a choice was made | `docs/decisions.md` |
| Current application version | `VERSION` |
| What shipped in each version | `CHANGELOG.md` |
| A cold introduction to the product | `README.md` |

Paths under `api/`, `web/`, `eval/`, `deploy/` appear in `docs/PRD.md` §10 under **Planned** and **do not exist yet**. Do not link to them as if they do. When you create one, move it out of the planned tree in the same change, or §10 stops being trustworthy and gets ignored.

---

## 3. Constraints — never violate

Each is load-bearing for the product's reason to exist. Where enforcement lives is listed because a rule with no enforcement point is a wish.

| # | Rule | Why | Enforced at |
| - | ---- | --- | ----------- |
| C1 | **No outbound network calls at runtime.** Not models, fonts, telemetry, or CDNs. Everything bundled at build time. | An air-gapped install with the cable unplugged must behave identically. A single runtime URL turns a working ministry install into a support call nobody can debug on site. | Container network policy; release test with the cable physically unplugged (`docs/PRD.md` §8) |
| C2 | **Model-generated SQL is never trusted.** Parse with `sqlglot`; reject anything that is not a single `SELECT`/`WITH`. Regex filtering is not sufficient and is not acceptable even temporarily, even in a branch. | Regex misses nested statements, comment tricks, and dialect quirks. The customer's production database is on the other side of this check. | `api/src/vaultq/sql/` (Phase 2) **plus** a `SELECT`-only database role, independently |
| C3 | **Every factual claim from the corpus carries a citation** — document, page, and the exact retrieved passage, rendered clickable. | Officers and auditors cannot act on a number they cannot trace. An uncited claim is a bug to fix, not a limitation to document. | Answer composition + eval suite (`docs/PRD.md` §7) |
| C4 | **Abstention over invention.** When retrieval returns nothing above threshold, say so and name what would need ingesting. Never fall back to model world-knowledge for organisation-specific questions. | One confident fabrication about a circular ends the pilot. Abstention rate is also the operational signal that the corpus has gaps. | System prompt + abstention eval subset, pass bar ≥ 0.90. **Do not weaken those tests to make a change pass.** |
| C5 | **The audit log is append-only.** No `UPDATE` or `DELETE` grant for the application role, ever. | For the government segment the audit log is why procurement approves the purchase. A mutable log is worth nothing to an auditor. | Database grants on `audit_events` (`docs/PRD.md` §6) |
| C6 | **Retrieved content is data, never instruction.** Keep it delimited and keep the system prompt's statement to that effect intact. | Prompt injection via an ingested document otherwise drives real tool calls against real customer databases. | Prompt templates in `api/src/vaultq/agent/prompts/` + trace flagging (`docs/PRD.md` §8) |
| C7 | **Restricted columns are stripped from the schema shown to the model.** | The model cannot select what it cannot see. Filtering results after generation leaks the column's existence and is bypassable. | `docs/PRD.md` §4.2 safety layer 5 |
| C8 | **Secrets are environment variables, never committed.** `.env.example` updated in the same change that introduces a variable. | A committed DSN in a repo shipped to customers is a breach, not a bug. | `.gitignore` + review |

---

## 4. Working rules

- **Do not scaffold beyond the current phase.** In Phase 0, do not create empty `voice/` modules "for later". Speculative structure rots and misleads the next session into thinking work exists.
- **Edit surgically.** Targeted string replacement over file rewrites. If a change touches more than three files, describe the plan and get agreement first. Full-file regeneration silently destroys prior decisions.
- **Run the thing.** A task is not complete because the code looks right. Start the stack, hit the endpoint, read the response. `podman compose up -d && curl ...` is the definition of done.
- **Tests accompany the code, not the phase.** Retrieval, SQL validation, and the agent loop get tests *first* — they are where correctness is hardest to eyeball.
- **One task at a time.** Finish, verify, update `docs/BRAIN.md`, then take the next. Batching four features means discovering which broke by bisection.
- **Never hardcode a model name in application code.** Models come from configuration, selected by deployment profile.
- **All prompts live in `api/src/vaultq/agent/prompts/` as versioned files.** Never inline a system prompt in application logic.
- **Any prompt change requires an eval run.** Run `eval/bench.py` against the affected suite and record before/after in `docs/BRAIN.md`. Prompt engineering without measurement is guessing, and small models are exactly where guessing fails.

### When to stop and ask

- A `docs/PRD.md` §11 open decision blocks the task → **stop and ask.** Do not pick a default.
- Two reasonable architectures exist and the PRD does not choose → present both briefly with a recommendation, then ask.
- A requirement seems wrong or contradicts another → say so directly. The PRD was written before implementation; parts of it are wrong, and finding that out during the build is the point. Do not silently work around a bad requirement.
- A shortcut would save real time but violates a constraint in §3 → propose it explicitly rather than taking it.

What not to do: guess, note the guess in a comment, keep going. That is how a build accumulates decisions nobody made.

---

## 5. Commands

**The repository has no application code yet.** There is no manifest, no test runner, and no CI. The only commands that currently run are git and `gh`.

Phase 0 creates the toolchain. When it does, replace this section with verified commands — do not pre-populate it with commands that fail.

Planned, per `docs/PRD.md` §5.1 and §9:

| Purpose | Command | Status |
| ------- | ------- | ------ |
| Bring up the stack | `podman compose up -d` | Phase 0 |
| Lint / format Python | `ruff check api/` / `ruff format api/` | Phase 0 |
| Typecheck | `mypy --strict api/src/` | Phase 0 |
| Python tests | `pytest api/` | Phase 0 |
| Web dev server | Next.js 15 in `web/` | Phase 1 |
| Eval suite | `python eval/bench.py --suite <name>` | Phase 1 |

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

**Database** — Alembic migrations, never hand-edited schema. Every migration reversible. No raw SQL in application code outside `api/src/vaultq/sql/`.

**Commits** — Conventional Commits, scoped to one logical change, with the PRD phase in brackets:

```
feat(ingest): add tamil OCR fallback [P1]
fix(sql): reject CTE with trailing DELETE [P2]
docs: correct container count in PRD §5.2
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

Tracker: `Rumeasiyan/vaultq` (private). Issues are assigned to `Rumeasiyan`.

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
| `phase:0` … `phase:6` | Which build phase the work belongs to (`docs/PRD.md` §9) |
| `blocked:decision` | Waiting on a `docs/PRD.md` §11 answer. Do not start work on these. |
| `constraint:sovereignty` | Touches C1 — runtime network access, bundling, air-gap behaviour |
| `constraint:sql-safety` | Touches C2/C7 — SQL validation, database roles, column access control |
| `constraint:grounding` | Touches C3/C4 — citations, abstention, retrieval thresholds |
| `constraint:audit` | Touches C5 — audit log immutability |
| `constraint:injection` | Touches C6 — retrieved-content-as-data boundary |
| `eval` | Changes eval suites, pass bars, or requires an eval run to land |
| `tamil` | Tamil-specific: OCR, STT, TTS, retrieval, evals |
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
