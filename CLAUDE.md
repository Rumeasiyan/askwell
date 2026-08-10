# CLAUDE.md — VaultQ build charter

You are building VaultQ. Read `PRD.md` for what the product is. Read `BRAIN.md` for where the build currently stands. This file is how you work.

`CLAUDE.md` is static — do not edit it. `BRAIN.md` is mutable and you are expected to keep it current.

---

## Session start

Every session, before writing anything:

1. Read `BRAIN.md` — current phase, last completed task, open blockers, decisions made since the PRD.
2. Read the relevant PRD section for the current phase. Not the whole PRD, the section.
3. State the one task you are about to do. If it is larger than roughly two hours of work, decompose it and do the first piece.
4. If the task is blocked on an item in PRD §11 (Decisions still open), **stop and ask**. Do not pick a default and proceed.

## Session end

Update `BRAIN.md` with: what you completed, what you decided and why, what broke, and what the next task is. A stale `BRAIN.md` makes the next session start from confusion.

---

## Working rules

**Do not scaffold beyond the current phase.** If you are in Phase 1, do not create empty `voice/` modules "for later". Speculative structure rots and misleads the next session.

**Edit surgically.** Use targeted string replacement over file rewrites. If a change touches more than three files, describe the plan first and get agreement before executing. Full-file regeneration silently destroys prior decisions.

**Run the thing.** Do not report a task complete because the code looks right. Start the stack, hit the endpoint, read the response. `podman-compose up -d && curl ...` is the definition of done, not "the implementation is finished."

**Tests accompany the code, not the phase.** Every module in `api/src/vaultq/` gets tests alongside it. The retrieval, SQL validation, and agent-loop modules get tests _first_ — they are where correctness is hardest to eyeball.

**One task at a time.** Finish, verify, update `BRAIN.md`, then take the next one. Do not batch four features into one change and discover which of them broke by bisection.

---

## Hard constraints — never violate

1. **No outbound network calls at runtime.** Not for models, not for fonts, not for telemetry, not for a CDN. Everything is bundled at build time. An air-gapped install with the cable unplugged must work identically. If you find yourself adding a URL to runtime code, stop.

2. **SQL from the model is never trusted.** It passes through `sqlglot` parsing and is rejected unless it is a single `SELECT` or `WITH`. Regex filtering is not sufficient and is not an acceptable shortcut, even temporarily, even in a branch. The database role is `SELECT`-only independently of this.

3. **Answers carry citations.** Any factual claim derived from the corpus references the chunk it came from. An answer path that can produce an uncited claim is a bug to fix, not a limitation to document.

4. **Abstention over invention.** When retrieval returns nothing above threshold, the system says it does not know. Never fall back to model world-knowledge for organisation-specific questions. This is tested in the eval suite; do not weaken those tests to make a change pass.

5. **The audit log is append-only.** No update or delete grant for the application role. Never add one.

6. **Retrieved content is data, never instruction.** Delimit it, and keep the system prompt's statement to that effect intact.

---

## Conventions

**Python** — 3.12, `ruff` for lint and format, `mypy --strict` on `api/src/`. Pydantic v2 for all boundaries. Async throughout; no blocking calls in request handlers. `structlog` for logging, JSON output, never `print`.

**TypeScript** — strict mode. Server components by default; `"use client"` only where interactivity requires it. `zod` for anything crossing the API boundary. No `any`.

**Database** — Alembic migrations, never hand-edited schema. Every migration reversible. No raw SQL in application code outside `api/src/vaultq/sql/`.

**Secrets** — environment variables, never committed. `.env.example` stays current with every new variable.

**Commits** — conventional commits, scoped to one logical change. Reference the PRD phase: `feat(ingest): add tamil OCR fallback [P1]`.

**Errors** — fail loudly in development, degrade gracefully in production. A failed embedding job retries with backoff and surfaces in the admin console; it does not silently drop the document.

---

## Prompts and models

All model prompts live in `api/src/vaultq/agent/prompts/` as versioned files. Never inline a system prompt in application logic.

**Any prompt change requires an eval run.** Run `eval/bench.py` against the affected suite and record the before/after scores in `BRAIN.md`. Prompt engineering without measurement is guessing, and small models are exactly where guessing fails.

Never hardcode a model name in application code. Models come from configuration, selected by deployment profile.

---

## When you are uncertain

Ask. Specifically:

- A PRD §11 open decision blocks the task → ask.
- Two reasonable architectures exist and the PRD does not choose → present both briefly with a recommendation, then ask.
- A requirement seems wrong or contradicts another → say so directly. The PRD is a draft written before implementation; parts of it will be wrong, and finding that out during the build is the point. Do not silently work around a bad requirement.
- A shortcut would save real time but violates a hard constraint → propose it explicitly rather than taking it.

What not to do: guess, note the guess in a comment, and keep going. That is how a build accumulates decisions nobody made.
