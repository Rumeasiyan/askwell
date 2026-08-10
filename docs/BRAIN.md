# BRAIN.md — VaultQ build state

> Mutable. Updated at the end of every session.
> If this file is stale, the next session starts from confusion.

---

## Current phase

**Phase 0 — Skeleton. Not started.** Repository is documentation only: no application code, no manifests, no tests, no CI.

**Version:** `0.1.0` (see `VERSION`). Phase 0 landing takes it to `0.2.0`.
**Tracker:** `Rumeasiyan/vaultq` (private). Working agreements in `AGENTS.md`.

## Next task

[#7](https://github.com/Rumeasiyan/vaultq/issues/7) — scaffold the Compose stack and the FastAPI skeleton:

- `compose.yaml` with `api`, `web`, `postgres` (pgvector), `redis`
- FastAPI app with `/health`, config via Pydantic Settings
- Alembic initialised, first migration
- CI: ruff + mypy + pytest on push

Do **not** add `llm`, `voice`, `worker` or the `sandbox` Postgres yet — they arrive in later phases (`build-plan.md`).

**Blocked on [#9](https://github.com/Rumeasiyan/vaultq/issues/9)** for the `web/` half: PRD-era stack versions are stale and `create-next-app` would contradict them on the first commit.

The first migration no longer creates `organisations` and `users` — those tables are gone with the repositioning. See `architecture.md` §7 for the current data model.

---

## The repositioning — read this before anything else

On **2026-08-10** the product was redefined. The previous documentation described a materially different product and much of it was wrong, not merely outdated.

| Was | Is |
| --- | --- |
| Sold to government ministries, hospitals, banks | Free download for one individual professional |
| Organisations, four roles, RBAC, seat tiers, LKR pricing | **Single user, single machine.** No roles, no tenancy, no licence |
| Quantum Plus product with a "Deployer" persona | Standalone venture by Suseenthiran Arulraj Rumeasiyan; users install it themselves |
| Air-gapped, no network calls, ever | Local by default; **online AI is an explicit per-conversation opt-in**, and it is the only revenue line |
| Documents + live database connections | Also **CSV and SQL dump import**, with a sandbox for dumps |
| Ingest silently | **Clarification loop and memory** — the differentiator |
| Multi-node HA for the top tier | Single machine only, permanently |

If you find text about ministries, organisations, roles, licences or seats anywhere, it is leftover and wrong. Fix it.

Note that "Quantum Plus" and the ministry framing were in the original `PRD.md` (commit `dcd12cf`), not introduced later.

## Documentation map

`PRD.md` is now **business only** — shareable with users and investors. Technical content moved out:

| Doc | Holds |
| --- | ----- |
| `PRD.md` | Business case, positioning, pricing, roadmap |
| `architecture.md` | Stack, topology, auth, data model, retrieval, security |
| `data-sources.md` | Files, CSV, dumps + sandbox, live connections |
| `memory-and-clarification.md` | The clarification loop and memory |
| `audit-log.md` | Three stores, retention, hash chain |
| `build-plan.md` | Phases, acceptance criteria, quality gate, repo layout |

## Open blockers

| # | Question | Blocks |
| - | -------- | ------ |
| [#9](https://github.com/Rumeasiyan/vaultq/issues/9) | Stack versions stale — Next 15→16, Tailwind 4, Postgres 18 | **Phase 0 `web/`** |
| [#6](https://github.com/Rumeasiyan/vaultq/issues/6) | Pin Python 3.12; dev machine has 3.14, no `podman-compose` | Phase 0 |

All product decisions are currently answered. New ones raised in the rewrite and **not yet filed**:

- Per-source clarification cap and its ranking function (`memory-and-clarification.md` §8) — determines whether the differentiator is delightful or intolerable.
- Default log budget and interaction retention window (`audit-log.md` §8).
- MySQL / SQL Server dump support, which would need an eighth container or a translation layer (`data-sources.md` §7).
- Whether opt-in telemetry ships at all — without it, none of `success-metrics.md` §1 is observable.
- What online mode transmits (`audit-log.md` §6). Needed before Phase 7.

## Build procedure

Running the concept-to-build procedure over the existing docs. **Its phase numbers are not `build-plan.md` phase numbers.**

| Step | State |
| ---- | ----- |
| P0/P1 — spec, metrics, states | **done**, then redone after the repositioning |
| P2 — design the screens, in `docs/ux/` | next |
| Review the data model against what the screens need | after P2 |
| P6 — user-story backlog, vertical slices ≤ 3h | after that |
| Scaffold (Phase 0, #7) | blocked on #9 |

Screens before schema is deliberate: drawing a screen surfaces the missing button and the number with nowhere to come from.

## Eval baseline

Not yet established. First run at the end of Phase 1.

| Model | Suite | Overall | Worst-case | Date |
| ----- | ----- | ------- | ---------- | ---- |
| —     | —     | —       | —          | —    |

## Session log

**2026-08-10 (rewrite)** — Product repositioned; see the table above. Rewrote `PRD.md` as a business-only document and split all technical content into `architecture.md`, `data-sources.md`, `memory-and-clarification.md`, `audit-log.md` and `build-plan.md`. Rewrote `success-metrics.md` (no pilot exists, so every number was re-derived) and `states-and-edge-cases.md` (licence, seat, RBAC and permission states deleted). `AGENTS.md` §1–§3 rewritten: constraints renumbered, old C7 (column access control) removed, new C3 (dump sandbox) added, C1 now allows explicit online opt-in, C6 restated as tamper-evident rather than immutable. Closed #3, #4, #5, #10, #11, #12, #13, #14, #15.

**2026-08-10 (earlier)** — Closed the P0/P1 gaps: added `success-metrics.md` and `states-and-edge-cases.md`. Filed #9 after verifying stack versions against registries.

**2026-08-10** — Set up agent working documentation: `AGENTS.md`, decision log, versioning, tracker conventions, issue templates, labels.

## Notes for the next session

- Dev machine runs Python **3.14.6**; the project targets **3.12**. `podman-compose` is not installed — use `podman compose`. Tracked in [#6](https://github.com/Rumeasiyan/vaultq/issues/6).
- `bench.py` exists in draft form outside this repo — port it to `eval/bench.py` in Phase 1 rather than rewriting it.
- `decisions.md` is append-only. Entries written before 2026-08-10 describe the organisation-era product and are historically accurate for that time; the repositioning entry supersedes their framing rather than editing them.
