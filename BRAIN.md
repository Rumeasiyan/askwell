# BRAIN.md — VaultQ build state

> Mutable. Claude Code updates this at the end of every session.
> If this file is stale, the next session starts from confusion.

---

## Current phase

**Phase 0 — Skeleton.** Nothing implemented yet. Repository is documentation only.

## Next task

Scaffold the Compose stack and the FastAPI skeleton:

- `compose.yaml` with `api`, `web`, `postgres` (pgvector), `redis`
- FastAPI app with `/health`, config loading via Pydantic Settings
- Alembic initialised, first migration creating `organisations` and `users`
- CI: ruff + mypy + pytest on push

Do **not** add the `llm`, `voice`, or `worker` services yet. They arrive in Phases 1 and 4.

---

## Decisions log

| Date       | Decision                                                                        | Rationale                                                                                                      |
| ---------- | ------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| 2026-08-10 | All-Python backend (FastAPI), no second backend language                        | Entire AI toolchain is Python-native; a Go/Rust service would add integration surface for no gain              |
| 2026-08-10 | Postgres + pgvector, no separate vector DB                                      | One system for relational, vector, and full-text; fewer containers for deployers to debug on customer sites    |
| 2026-08-10 | llama.cpp server as the inference layer                                         | OpenAI-compatible, model-agnostic, identical interface for CPU and CUDA                                        |
| 2026-08-10 | Hybrid retrieval (dense + lexical + RRF) from the start, not as an optimisation | Dense-only fails on circular numbers, form codes, and proper nouns — which is most real queries in this domain |
| 2026-08-10 | Self-hosted licence model, not hosted SaaS                                      | Data sovereignty is the entire value proposition; a hosted plane holding customer data would destroy it        |

## Open blockers

Waiting on Rumeasiyan for PRD §11:

1. Tamil scope in v1 — full parity or comprehension-only? **Blocks Phase 4 estimation and the `edge` profile's STT model size.**
2. Sinhala — v1, v2, or never?
3. First pilot customer — government or commercial?
4. Multi-node HA at launch — in or out? **Decides whether Phase 0 provisions a single Postgres or an HA pair (PRD §11.4).**
5. Brand relationship — Quantum Plus product or standalone entity?

Item 4 touches Phase 0 — the current task assumes a single Postgres; revisit if HA lands in scope. Item 1 must be resolved before Phase 4.

## Eval baseline

Not yet established. First run happens at the end of Phase 1, against `eval/suites/documents.jsonl`.

| Model | Suite | Overall | Worst-case | Date |
| ----- | ----- | ------- | ---------- | ---- |
| —     | —     | —       | —          | —    |

## Notes for the next session

- The hardware specs for the target laptop have not yet been collected (`get-specs.ps1` not yet run). Deployment profile floors in PRD §5.3 are estimates and should be revised once real numbers exist.
- `bench.py` exists in draft form outside this repo — port it to `eval/bench.py` during Phase 1 rather than rewriting it. PRD §7 assumes that path.
