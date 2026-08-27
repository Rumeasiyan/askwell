# Changelog

Notable changes per released version. Newest first. Versions follow `AGENTS.md` §7; the canonical version is in `VERSION`.

Categories: `Added`, `Changed`, `Fixed`, `Removed`, `Security`.

## 0.1.7 — 2026-08-27

`M0-DATA-DB-014`. The invariants, in the migration that creates the tables.

### Added

- Five invariants the ORM will not express: no `UPDATE`/`DELETE`/`TRUNCATE` grant on either audit table (C6); one live version per `(source_id, sha256)`; a chunk with cleared content cannot keep its embedding; a clarification marked answered must carry an answer; and the non-cascading citation foreign key.
- `deploy/postgres/10-roles.sh` — creates `askwell_app` and `askwell_readonly`. Askwell connects as `askwell_app`, which owns nothing.
- `scripts/dev.sh test-db` — 18 database-backed tests, deselected from the default run and failing rather than skipping when the database is absent.

### Changed

- **The application no longer connects as the table owner.** An owner bypasses its own grants, so the append-only guarantee would have been decorative — the `REVOKE` succeeds, the privilege listing looks right, and the application can still rewrite every audit record. See `docs/decisions.md`.
- `.env.example` carries `POSTGRES_APP_PASSWORD` and `POSTGRES_READONLY_PASSWORD`.

## 0.1.6 — 2026-08-27

`M0-DATA-DB-013`. The whole v1 schema in one reversible migration.

### Added

- `askwell.db` — the declarative base, the engine, and the thirteen tables of `docs/architecture.md` §7. No `organisations`, no `users`, no roles.
- One migration creating all of it, hand-edited after autogeneration for the vector extension, the configured embedding dimension, `content_tsv` as a generated column, and the Tamil text search configuration kept as a hedge.
- `ASKWELL_EMBEDDING_DIMENSIONS` — the width of every embedding column, so changing model is a configuration change plus a re-embed rather than a schema edit.
- `scripts/dev.sh db` and `scripts/dev.sh psql`.
- Fourteen model tests asserting the properties §7 calls load-bearing, without needing a database.

### Fixed

- **Column defaults were Python-side only.** They applied to rows the ORM inserted and to nothing else, so a migration, a `psql` session or a repair script hit a `NOT NULL` violation on a column that appeared to have a default. Found by inserting a document by hand. They are `server_default` now, and a test asserts it.

### Changed

- psycopg 3 is the database driver for both the async application and Alembic's synchronous path. asyncpg is faster on paper but cannot do the sync half, and two drivers means two sets of type adapters and two failure modes on a machine where nobody is watching.

## 0.1.5 — 2026-08-27

`M0-STACK-DEPLOY-009`. The stack comes up with one command.

### Added

- `compose.yaml` — `api`, `postgres` (pgvector, PG 18.6), `redis` and `worker`, with named volumes, health declarations and startup ordering. The egress proxy, sandbox database and voice are deliberately absent; they arrive in their own tickets.
- `askwell.worker` — the arq worker and a `ping` job, which is the cheapest end-to-end proof the queue is wired up.
- `.env.example` — the variables the stack needs. `M0-FOUND-SEC-007` completes it.

### Fixed

- **The worker was reported unreachable while running.** It was probed by opening a TCP socket, and an arq worker consumes a queue without listening on anything — so a healthy worker read as down, every time. It is now probed through the health record arq publishes into Redis, which distinguishes "the queue is down" from "the queue is up and the worker is not running". Those need different actions from the user.

### Changed

- `ASKWELL_WORKER_HOST` and `ASKWELL_WORKER_PORT` are gone, replaced by `ASKWELL_WORKER_HEALTH_KEY`.

## 0.1.4 — 2026-08-27

`M0-FOUND-DEPLOY-004`. The API serves the interface. The `web` container is gone from the topology.

### Added

- `askwell.interface` — static asset serving with a deliberate route fallback, per-file cache behaviour, and containment checked after `resolve()` so `..` and symlinks are already collapsed.
- `ASKWELL_WEB_ASSETS_DIR` — where the built interface lives.
- `web/app/not-found.tsx` — the product's own not-found page. Next's default is hardcoded black-on-white and drops the user out of the interface entirely.
- Fourteen tests covering the two requirements that pull against each other, five path-escape attempts and a symlink, cache headers per file kind, and the missing-build case.

### Changed

- Content-hashed assets are cached for a year and marked immutable; HTML is `no-cache`. The HTML is what points at the hashed filenames, so caching both the same way leaves a user on the old bundle after an update with no reason to suspect it.
- A missing build returns a readable page naming the directory and the command, at HTTP 503 — not a blank page. `/health` keeps working, which is what someone with a broken install actually needs.

## 0.1.3 — 2026-08-26

`M0-FOUND-FE-003`. The frontend, pinned as one verified set.

### Added

- `web/` — Next.js 16.3.3, React 19.2.8, Tailwind 4.3.3, pnpm 11.24.0, built to static assets in `web/out`. Every dependency is an exact version; there is not a single range operator in `package.json`.
- `web/app/globals.css` — the design tokens from `docs/ux/design-system.md` §2–§4, defined once. `--rule-strong` is its own token, not an alias of `--rule`. Depth is `--inset` and `--drop`, per theme.
- `web/scripts/contrast.mjs` — measures all 19 token pairs in both themes and fails below 4.5:1 for text or 3:1 for UI lines. Figures recorded in `docs/ux/design-system.md` §8.
- `web/scripts/check-tokens.mjs` — fails on a literal colour or a literal shadow anywhere outside the token definition, and on a depth token that does not differ between themes.
- `web/scripts/check-offline.mjs` — scans the built output for anything that would reach the network, by position rather than by pattern (C1).
- `web/Dockerfile` and `scripts/dev.sh web-*` — the Node toolchain lives in an image, like the Python one. Every frontend command runs with `--network=none` except `web-install`.

### Changed

- `docs/ux/design-system.md` §8 now records measured contrast figures rather than asserting a floor.

## 0.1.2 — 2026-08-26

`M0-FOUND-BE-002`. The API application, its configuration, its logging and its health surface.

### Added

- `askwell.config` — typed settings from `ASKWELL_*` environment variables. Refuses to start on unusable configuration and names every offending variable at once, by the name a person actually typed. An unknown `ASKWELL_*` variable is reported rather than ignored, because a typo otherwise leaves the setting it was meant to change silently on its default.
- `askwell.logging` — structlog, JSON to stderr, ISO-8601 UTC timestamps. Redaction is a processor, not a convention: anything whose key looks like a credential, and every `SecretStr` whatever its key is called, is replaced at any depth. Standard-library logs — uvicorn's included — are rendered by the same renderer, so the stream is parseable throughout.
- `askwell.health` — five components probed independently and concurrently. Name resolution is separate from connection so that "does not resolve" and "is not answering yet" are different messages, because they need different actions from the user.
- `askwell.app` — FastAPI application, `GET /health`, startup and shutdown logging with resolved profile and component states, and an error handler that shows the exception in development and a stated reason otherwise.
- `askwell-api` console entry point.

### Changed

- Logger caching is off. structlog binds a cached logger to whatever configuration was live at first use, and modules take their loggers at import time — before configuration is read — so a cached logger silently ignores it.

## 0.1.1 — 2026-08-26

First product code. `M0-FOUND-DEPLOY-001`.

### Added

- `api/Dockerfile` — API image pinned to Python 3.12, carrying `uv`, `ruff`, `mypy` and `pytest` inside it. The host needs Podman and nothing else. The build fails loudly if the base image ever drifts off 3.12.
- `api/pyproject.toml`, `api/uv.lock` — dependency manifest and lockfile. The lockfile is the pin; the manifest holds only bounds.
- `api/hatch_build.py` — reads the package version from the repository's `VERSION` file, so there is no second version to maintain.
- `api/src/askwell/` — the package, with version resolution that prefers the `VERSION` file over stamped metadata so a bump is visible without reinstalling.
- `api/tests/test_version.py` — five tests, including one that scans the tree for a second declared version string.
- `scripts/dev.sh` — runs lint, format, typecheck and tests inside the image against the working tree. Every command runs with `--network=none` except `lock`, which needs an index and says so.

### Changed

- `AGENTS.md` §5 — the commands table now lists commands that have been run, not commands that are intended.
- `AGENTS.md` §7 — tickets inside a phase are `PATCH`; the phase landing is the `MINOR`. Previously the two rules in that section contradicted each other for any phase with more than one ticket.

## 0.1.0 — 2026-08-10 (rewrite)

Product repositioned. The previous documentation described on-premise software sold to government ministries; Askwell is a free local install for one individual professional. Version unchanged — no code exists, so no user-visible behaviour changed.

### Added

- `docs/architecture.md` — technical decisions, topology, auth, data model, retrieval, security. Split out of the PRD.
- `docs/data-sources.md` — files, CSV, SQL dump import with sandbox isolation, live connections.
- `docs/memory-and-clarification.md` — the clarification loop and permanent memory. New capability and the product's differentiator.
- `docs/audit-log.md` — three separate stores with different retention and failure behaviour; hash-chained.
- `docs/build-plan.md` — phases, acceptance criteria, quality gate, repo layout.
- Constraint C3: an imported dump is untrusted code and loads only into an isolated sandbox Postgres.
- Quality-gate category for memory application (15 tasks) — without it the differentiator has no test.

### Changed

- `docs/PRD.md` rewritten as a **business-only** document, shareable as a pitch. All implementation detail moved out.
- Single user, single machine. No organisations, users, roles, RBAC, seat tiers, licence keys or high availability.
- C1 now permits an explicit per-conversation online-AI opt-in instead of forbidding all egress.
- C6 restated as **tamper-evident, not immutable** — the user owns the disk, and any stronger claim is false.
- Authentication reduced to a local session plus an optional at-rest passphrase. JWT/Argon2id/TOTP/blacklist removed.
- Deployment profiles rebuilt around personal hardware; floor drops to 8GB and the installer warns rather than refuses.
- `docs/success-metrics.md` fully re-derived — there is no pilot. Adds clarification-loop metrics.
- `docs/states-and-edge-cases.md` — licence, seat-cap, session-expiry and permission-denial states removed; disk-budget, online-mode and clarification states added.
- Issue templates and labels updated to the new constraint numbering.

### Settled defaults

- Clarification cap of 5 questions per source, with a documented ranking for what makes the cut.
- Log budget 2 GB or 5% of free disk, whichever smaller; 12-month interaction retention; decisions never pruned.
- Sandbox caps of 5 GB and 10 minutes per import.
- v1 imports PostgreSQL dumps only — MySQL and SQL Server via live connection or CSV.
- No telemetry through Phase 6, accepting that primary retention metrics become unobservable.

### Removed

- Constraint C7-as-was (column-level access control per role) — it protected one role from another, and there are no roles.
- Multi-node high availability, permanently (#4).

## 0.1.0 — 2026-08-10 (initial)

First versioned state. No application code — the repository is documentation only, Phase 0 not yet started.

### Added

- `AGENTS.md` — working agreements, hard constraints, commands, conventions, versioning, tracker and session workflow.
- `docs/decisions.md` — append-only decision log, seeded from git history and `docs/PRD.md` §5.1.
- `VERSION` — canonical application version, single source of truth.
- `CHANGELOG.md` — this file.
- `.github/ISSUE_TEMPLATE/` — issue templates for tasks, bugs, and blocked decisions.
- `README.md` — was missing; the repository had no entry point for a human arriving cold.
- `docs/success-metrics.md` — what "working" means in numbers in production, distinct from the model eval gate. Abstention rate reframed as a 5–20% band with a citation-correctness counter-metric, because it is trivially gamed by lowering the retrieval threshold.
- `docs/states-and-edge-cases.md` — every state a user can be in across chat, ingestion, database QA, voice, admin, plus collected empty states. Surfaced six product decisions with no PRD answer (issues #10–#15).
- Repository labels for build phase (`phase:0`…`phase:6`) and hard constraints (`constraint:*`).

### Changed

- `CLAUDE.md` reduced to a shim importing `AGENTS.md`; its rules now live in `AGENTS.md`.
- **v1 scope is now English-only.** Tamil and Sinhala moved out of the phase list to v2 (`docs/PRD.md` §1.2). Resolves §11 items 1 and 2, closing issues #1 and #2.
  - Phase 4 estimate 2 weeks → 1.5; acceptance is an English round trip only, no language detection.
  - `edge` profile no longer degraded for voice — whisper `small` serves all three profiles.
  - Eval gate 160 → 140 tasks; Tamil category removed, `eval/suites/tamil.jsonl` not created.
  - Phase 1 acceptance changed from a scanned Tamil PDF to a scanned English one.
  - Hedges kept so Tamil is later work rather than a corpus migration: `bge-m3` embeddings, Tamil-aware Postgres FTS config, `tam` OCR traineddata, pluggable TTS interface.
  - Label `tamil` replaced by `v2:language`.
- `PRD.md` and `BRAIN.md` moved into `docs/`. Root now holds only what a tool or convention requires there.
- `docs/PRD.md` §10 split into what exists and what is planned, with a table of which directory arrives in which phase — the previous single tree described almost nothing that existed, with no marker saying so.

### Fixed

- `docs/PRD.md` §5.2 container count: six → seven.
- `docs/PRD.md` §5.3 deployment-profile models: `Qwen3.5 4B` → `Qwen3 4B`, `Qwen3.6 27B` → `Qwen3 32B` (neither original was a real release).
- `docs/PRD.md` §7 eval harness path: `bench/` → `eval/bench.py`, matching §10.
- `docs/PRD.md` owner name, and `Rumesh` → `Rumeasiyan` in `docs/PRD.md` §11 and `docs/BRAIN.md`.
- `docs/BRAIN.md` blocker 4 no longer contradicts `docs/PRD.md` §11.4 about whether it affects Phase 0.
- `prd.md` renamed to `PRD.md` (the reference in §10 was already capitalised), then moved with `BRAIN.md` into `docs/`.
