# Changelog

Notable changes per released version. Newest first. Versions follow `AGENTS.md` §7; the canonical version is in `VERSION`.

Categories: `Added`, `Changed`, `Fixed`, `Removed`, `Security`.

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
