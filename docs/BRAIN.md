# docs/BRAIN.md — VaultQ build state

> Mutable. Claude Code updates this at the end of every session.
> If this file is stale, the next session starts from confusion.

---

## Current phase

**Phase 0 — Skeleton.** Nothing implemented yet. Repository is documentation only.

**Version:** `0.1.0` (see `VERSION`). Phase 0 landing takes it to `0.2.0`.
**Tracker:** `Rumeasiyan/vaultq` (private). Working agreements in `AGENTS.md`.

## Next task

[#7](https://github.com/Rumeasiyan/vaultq/issues/7) — scaffold the Compose stack and the FastAPI skeleton:

- `compose.yaml` with `api`, `web`, `postgres` (pgvector), `redis`
- FastAPI app with `/health`, config loading via Pydantic Settings
- Alembic initialised, first migration creating `organisations` and `users`
- CI: ruff + mypy + pytest on push

Do **not** add the `llm`, `voice`, or `worker` services yet. They arrive in Phases 1 and 4.

---

## Decisions log

> Moved to `docs/decisions.md`, which carries the full reasoning for each. The table below is kept as an index.

| Date       | Decision                                                                        | Rationale                                                                                                      |
| ---------- | ------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| 2026-08-10 | All-Python backend (FastAPI), no second backend language                        | Entire AI toolchain is Python-native; a Go/Rust service would add integration surface for no gain              |
| 2026-08-10 | Postgres + pgvector, no separate vector DB                                      | One system for relational, vector, and full-text; fewer containers for deployers to debug on customer sites    |
| 2026-08-10 | llama.cpp server as the inference layer                                         | OpenAI-compatible, model-agnostic, identical interface for CPU and CUDA                                        |
| 2026-08-10 | Hybrid retrieval (dense + lexical + RRF) from the start, not as an optimisation | Dense-only fails on circular numbers, form codes, and proper nouns — which is most real queries in this domain |
| 2026-08-10 | Self-hosted licence model, not hosted SaaS                                      | Data sovereignty is the entire value proposition; a hosted plane holding customer data would destroy it        |

## Open blockers

Waiting on Rumeasiyan for PRD §11. Each is a tracked issue carrying the options and a recommendation — read the issue, not this list:

| # | Question | Blocks |
| - | -------- | ------ |
| [#3](https://github.com/Rumeasiyan/vaultq/issues/3) | First pilot customer — government or commercial? | Phase 6; shapes which evals matter most |
| [#4](https://github.com/Rumeasiyan/vaultq/issues/4) | Multi-node HA at launch — in or out? | **Phase 0 — the current task.** Proceeding with a single Postgres; connection config must not hardcode a single host. |
| [#5](https://github.com/Rumeasiyan/vaultq/issues/5) | Brand relationship — Quantum Plus product or standalone entity? | Licence signing entity (Phase 5) and repo ownership |

When one is answered: entry in `docs/decisions.md`, strike the `docs/PRD.md` §11 item, update this table, close the issue. All four, same change.

**Answered 2026-08-10:** #1 Tamil scope and #2 Sinhala. **v1 is English-only; both are v2.** Three hedges kept so Tamil is later work rather than a corpus migration — multilingual `bge-m3` embeddings, Tamil-aware Postgres FTS config, `tam` OCR traineddata bundled. See `docs/PRD.md` §1.2 and `docs/decisions.md`.

## Eval baseline

Not yet established. First run happens at the end of Phase 1, against `eval/suites/documents.jsonl`.

| Model | Suite | Overall | Worst-case | Date |
| ----- | ----- | ------- | ---------- | ---- |
| —     | —     | —       | —          | —    |

## Notes for the next session

- The hardware specs for the target laptop have not yet been collected (`get-specs.ps1` not yet run). Deployment profile floors in PRD §5.3 are estimates and should be revised once real numbers exist.
- `bench.py` exists in draft form outside this repo — port it to `eval/bench.py` during Phase 1 rather than rewriting it. PRD §7 assumes that path.
- Dev machine runs Python **3.14.6**; the project targets **3.12**. `podman-compose` is not installed — use `podman compose`. Both tracked in [#6](https://github.com/Rumeasiyan/vaultq/issues/6); details in `AGENTS.md` §5.

## Session log

**2026-08-10** — Set up agent working documentation. Created `AGENTS.md` (source of truth), `docs/decisions.md` (seeded with 8 entries), `VERSION` (`0.1.0`), `CHANGELOG.md`, issue templates, and 16 repo labels. `CLAUDE.md` reduced to a shim importing `AGENTS.md` — this reverses its own "static, do not edit" rule, deliberately and with agreement, because rules living only in the Claude-specific file were invisible to every other tool. Filed issues #1–#7. Also corrected factual errors in `docs/PRD.md` (container count, non-existent Qwen model names, owner name, eval harness path) — see `CHANGELOG.md`. Next: #7, Phase 0 scaffold.
