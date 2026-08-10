# BRAIN.md — Askwell build state

> Mutable. Updated at the end of every session.
> If this file is stale, the next session starts from confusion.

---

## Current phase

**Phase 0 — Skeleton. Not started.** Repository is documentation only: no application code, no manifests, no tests, no CI.

**Version:** `0.1.0` (see `VERSION`). Phase 0 landing takes it to `0.2.0`.
**Tracker:** `Rumeasiyan/askwell` (private). Working agreements in `AGENTS.md`.

## Next task

[#7](https://github.com/Rumeasiyan/askwell/issues/7) — scaffold the Compose stack and the FastAPI skeleton:

- `compose.yaml` with `api`, `web`, `postgres` (pgvector), `redis`
- FastAPI app with `/health`, config via Pydantic Settings
- Alembic initialised, first migration
- CI: ruff + mypy + pytest on push

Do **not** add `llm`, `voice`, `worker` or the `sandbox` Postgres yet — they arrive in later phases (`build-plan.md`).

**Blocked on [#9](https://github.com/Rumeasiyan/askwell/issues/9)** for the `web/` half: PRD-era stack versions are stale and `create-next-app` would contradict them on the first commit.

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
| [#9](https://github.com/Rumeasiyan/askwell/issues/9) | Stack versions stale — Next 15→16, Tailwind 4, Postgres 18 | **Phase 0 `web/`** |
| [#6](https://github.com/Rumeasiyan/askwell/issues/6) | Pin Python 3.12; dev machine has 3.14, no `podman-compose` | Phase 0 |

**All product decisions are answered.** Every decision issue #1–#5 and #10–#15 is closed. The three open issues are engineering tasks, not questions.

Questions raised by the rewrite were settled as defaults rather than handed back, since none needed a product call:

| Settled | Value | Where |
| ------- | ----- | ----- |
| Clarification cap per source | **5**, adjustable, with a documented ranking for what makes the cut | `memory-and-clarification.md` §8 |
| Log storage budget | **2 GB or 5% of free disk**, whichever smaller; 12-month interaction retention | `audit-log.md` §8 |
| Dump engines in v1 | **PostgreSQL only.** MySQL/SQL Server via live connection or CSV | `data-sources.md` §7 |
| Sandbox caps | 5 GB, 10 minutes per import | `data-sources.md` §7 |
| Telemetry | **None, not even opt-in**, through Phase 6 | `success-metrics.md` §6 |

Still genuinely open, and deferred rather than forgotten:

- **What online mode transmits** (`audit-log.md` §9). Needed before Phase 7, which is where the revenue is.
- **Excel multi-sheet and merged-cell handling** (`data-sources.md` §8). Common in real files.
- **Memory import/export** across machines (`memory-and-clarification.md` §9). Not v1.

## Build procedure

Running the concept-to-build procedure over the existing docs. **Its phase numbers are not `build-plan.md` phase numbers.**

| Step | State |
| ---- | ----- |
| P0/P1 — spec, metrics, states | **done**, then redone after the repositioning |
| P2 — design the screens, in `docs/ux/` | **done** — design system + 10 screens |
| Review the data model against what the screens need | **done** — #20 closed |
| P6 — user-story backlog, vertical slices ≤ 3h | **next** |
| Scaffold (Phase 0, #7) | blocked on #9 |

Screens before schema is deliberate: drawing a screen surfaces the missing button and the number with nowhere to come from.

## Eval baseline

Not yet established. First run at the end of Phase 1.

| Model | Suite | Overall | Worst-case | Date |
| ----- | ----- | ------- | ---------- | ---- |
| —     | —     | —       | —          | —    |

## Session log

**2026-08-10 (data model)** — Reviewed `architecture.md` §7 against all ten screens and rewrote it. Four changes: `documents.path`/`missing_since` so a moved file is distinguishable from a deleted one (indexing in place makes stale paths normal, not exceptional); **`citations` promoted to a real table** because C4 cannot be enforced or measured while citations live in a jsonb blob — `success-metrics.md` tracks uncited claims at 100% and that query has to be possible; `fact_usage` join table for "used in N answers"; `clarifications.rank`/`evidence` for the cap and the value distributions. Dropped `collections` — a flat list is right until someone needs grouping, and documents hang off `sources` now. Specified the shape of `messages.trace`, with scores and the threshold **stored not recomputed**, since recomputing gives a different number after any threshold change and breaks the explanation exactly when someone is investigating an old answer. Listed the constraints the ORM will not express, to go in the same migration that creates the tables. Closed #20.

**2026-08-10 (P2 complete)** — Remaining 8 screens written: first-run, add-source, library, source-viewer, memory, trace, voice, settings. Decisions taken while specifying, each recorded in its screen doc: PDFs render **in-app** rather than handing off to the OS viewer, because handing off loses the highlight and the way back and the citation loop has to be cheap or people stop checking; the file-moved state is distinct from deleted, since indexing in place makes stale paths inevitable; the retrieval threshold is adjustable only **from an abstention trace, with the consequence stated**, never as a frictionless slider; memory sorts inferred facts first and shows "used in N answers", which is the number that makes a wrong belief noticeable; update checking is **off by default** with the payload stated, because a silent check contradicts C1. Next: review `architecture.md` §7 data model against what the screens actually need.

**2026-08-10 (rename)** — VaultQ → **Askwell**, repo renamed to `Rumeasiyan/askwell`. Apache-2.0 for the application, proprietary credit service. Marginalis was more coherent with the design signature but lost on four syllables that need spelling aloud; Gleanly lost on brand adjacency to Glean. Every dictionary word was taken on npm and PyPI. Surveyed the field before choosing a discovery strategy: open-webui 148k stars, AnythingLLM 64k, private-gpt 57k, Quivr 39k, Khoj 36k, Onyx 31k — **the name will not win search against these and should not try**; none of them asks about your data or remembers the answers, and that phrase is unclaimed.

**2026-08-10 (P2 start)** — Design system and the two highest-value screens. Direction: **instrument, not chatbot** — the templated centred-chat-column with sources behind a toggle was rejected because it makes citations a disclosure you click, contradicting the product's central claim. Signature is the **permanent provenance margin**: source cards aligned to the claim they support, joined by a hairline leader, never collapsible. An uncited claim is visibly wrong because nothing sits beside it — the layout enforces C4 rather than trusting the model to. Palette encodes epistemics: green means traceable and is spent on nothing else, ochre means Askwell guessed. Serif for language, mono for machinery. Wrote `design-system.md`, `ask.md`, `clarifications.md`, and an HTML visual reference.

**2026-08-10 (rewrite)** — Product repositioned; see the table above. Rewrote `PRD.md` as a business-only document and split all technical content into `architecture.md`, `data-sources.md`, `memory-and-clarification.md`, `audit-log.md` and `build-plan.md`. Rewrote `success-metrics.md` (no pilot exists, so every number was re-derived) and `states-and-edge-cases.md` (licence, seat, RBAC and permission states deleted). `AGENTS.md` §1–§3 rewritten: constraints renumbered, old C7 (column access control) removed, new C3 (dump sandbox) added, C1 now allows explicit online opt-in, C6 restated as tamper-evident rather than immutable. Closed #3, #4, #5, #10, #11, #12, #13, #14, #15.

**2026-08-10 (earlier)** — Closed the P0/P1 gaps: added `success-metrics.md` and `states-and-edge-cases.md`. Filed #9 after verifying stack versions against registries.

**2026-08-10** — Set up agent working documentation: `AGENTS.md`, decision log, versioning, tracker conventions, issue templates, labels.

## Notes for the next session

- Dev machine runs Python **3.14.6**; the project targets **3.12**. `podman-compose` is not installed — use `podman compose`. Tracked in [#6](https://github.com/Rumeasiyan/askwell/issues/6).
- `bench.py` exists in draft form outside this repo — port it to `eval/bench.py` in Phase 1 rather than rewriting it.
- `decisions.md` is append-only. Entries written before 2026-08-10 describe the organisation-era product and are historically accurate for that time; the repositioning entry supersedes their framing rather than editing them.
