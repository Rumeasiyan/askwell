# Changelog

Notable changes per released version. Newest first. Versions follow `AGENTS.md` §7; the canonical version is in `VERSION`.

Categories: `Added`, `Changed`, `Fixed`, `Removed`, `Security`.

## 0.1.0 — 2026-08-10

First versioned state. No application code — the repository is documentation only, Phase 0 not yet started.

### Added

- `AGENTS.md` — working agreements, hard constraints, commands, conventions, versioning, tracker and session workflow.
- `docs/decisions.md` — append-only decision log, seeded from git history and `PRD.md` §5.1.
- `VERSION` — canonical application version, single source of truth.
- `CHANGELOG.md` — this file.
- `.github/ISSUE_TEMPLATE/` — issue templates for tasks, bugs, and blocked decisions.
- Repository labels for build phase (`phase:0`…`phase:6`) and hard constraints (`constraint:*`).

### Changed

- `CLAUDE.md` reduced to a shim importing `AGENTS.md`; its rules now live in `AGENTS.md`.

### Fixed

- `PRD.md` §5.2 container count: six → seven.
- `PRD.md` §5.3 deployment-profile models: `Qwen3.5 4B` → `Qwen3 4B`, `Qwen3.6 27B` → `Qwen3 32B` (neither original was a real release).
- `PRD.md` §7 eval harness path: `bench/` → `eval/bench.py`, matching §10.
- `PRD.md` owner name, and `Rumesh` → `Rumeasiyan` in `PRD.md` §11 and `BRAIN.md`.
- `BRAIN.md` blocker 4 no longer contradicts `PRD.md` §11.4 about whether it affects Phase 0.
- `prd.md` renamed to `PRD.md`, matching the reference in `PRD.md` §10.
