# Changelog

Notable changes per released version. Newest first. Versions follow `AGENTS.md` §7; the canonical version is in `VERSION`.

Categories: `Added`, `Changed`, `Fixed`, `Removed`, `Security`.

## 0.1.0 — 2026-08-10

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
