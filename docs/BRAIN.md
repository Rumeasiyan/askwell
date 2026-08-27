# BRAIN.md — Askwell build state

> Mutable. Updated at the end of every session.
> If this file is stale, the next session starts from confusion.

---

## Current phase

**M0 — It runs. In progress: 14 of 21 tickets done.**

The repository is no longer documentation only. `api/` exists: an image, manifests, the application, and 54 tests. The API starts, refuses bad configuration by name, and serves `GET /health` reporting five components separately. `podman compose up -d` brings up four services, the database carries the full v1 schema, and the interface loads at `http://127.0.0.1:8000`. `web/` builds to static assets and the API serves them — the `web` container is gone from the topology. The Compose stack, the database schema and the inference process do not exist yet — so all five health components correctly report `unreachable`.

**Version:** `0.1.14` (see `VERSION`). Tickets bump `PATCH`; M0 landing takes it to `0.2.0` (`AGENTS.md` §7).
**Tracker:** `Rumeasiyan/askwell`. Working agreements in `AGENTS.md`. Backlog in `docs/backlog/`.

## Last completed

**`M0-STACK-SEC-011`** — [#80](https://github.com/Rumeasiyan/askwell/issues/80). `GET /network`: what the proxy refused, according to the proxy.

One rule shaped the whole design: **unreadable is not zero.** Zero and unknown look identical to whoever reads the settings screen and mean opposite things, and "nothing has tried to leave this machine" is the strongest claim Askwell makes.

Verified against the running stack:

| | |
| --- | --- |
| a deliberate refused request | count goes 5 → 6, destination retrievable |
| `podman compose down` then `up` | still 6 — cumulative for the install |
| permitted | 0, and it is the proxy's zero, not the API's |
| **the queue stopped** | `available: false`, `refused: null` — *"not the same as nothing having been refused"* |
| **the proxy has never reported** | `available: false` — *"unknown rather than zero"* |
| the proxy comes back | available again, count intact |

There are two distinct unavailable cases and they needed different answers. The queue being unreachable is one. The queue being fine while the proxy has never registered is the other — its counters would read as absent, and absent renders as zero. The proxy now writes a reporting marker at startup, which is what lets the API tell "reported zero" from "never reported".

**A test I had to throw away.** The first version asserted the surface contained no alarming words, and failed on the module's own docstring explaining that alarming words do not apply. A test that cannot tell a denial from a use gets deleted the first time it is wrong. Replaced with an assertion on the payload: it carries a count and nothing that classifies the count.

## Next task

**`M0-FOUND-DOC-008`** (version, changelog and release-note discipline — largely already practised, needs writing down and enforcing), then the STACK epic (`010` egress proxy, `011` refused-request count, `012` localhost binding), SHELL and MODEL.

Forward references outstanding: the configuration error message points at `.env.example` (`M0-FOUND-SEC-007`), no screen exists yet (`M0-SHELL-FE-017`), and built assets are not in the API image (M0-STACK-DEPLOY-009 / Phase 7).

## Open

- [#47](https://github.com/Rumeasiyan/askwell/issues/47) — the support boundary in `SUPPORT.md` needs the owner to read and agree it. An agent wrote promises in his name. Not blocking any ticket.
- [#49](https://github.com/Rumeasiyan/askwell/issues/49)–[#52](https://github.com/Rumeasiyan/askwell/issues/52) — contributor issues. #49 (does an 8 GB machine actually work?) is the riskiest unverified number in the project and needs hardware nobody here has.
- The build runner still refuses live runs by design. It needs a product gate to check its own work against, and M0 is what builds that gate. Unblock it when `AGENTS.md` §7.3 can be filled with commands that exist.

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

**Everything open is now a tracked issue.** Nothing lives only in a document — a doc section with no owner is the same failure as a chat message with no owner, which `AGENTS.md` §8 exists to prevent.

| Waiting on you | Issue |
| -------------- | ----- |
| Code signing certificates — Apple and Windows, with lead times | [#42](https://github.com/Rumeasiyan/askwell/issues/42) |
| Web search provider, and key-vs-credits | [#43](https://github.com/Rumeasiyan/askwell/issues/43) |
| Update delivery | [#44](https://github.com/Rumeasiyan/askwell/issues/44) |
| What online mode transmits | [#45](https://github.com/Rumeasiyan/askwell/issues/45) |
| Credit pricing | [#46](https://github.com/Rumeasiyan/askwell/issues/46) |
| Trademark, and agreeing the support boundary | [#47](https://github.com/Rumeasiyan/askwell/issues/47) |
| The copy-review marker | [#40](https://github.com/Rumeasiyan/askwell/issues/40) |

Everything else that was open in a document has been **decided and recorded where it belongs** — STT placement, PDF rendering, scan highlighting, passphrase-and-backup, trace retention and score presentation, audio retention, folder watching, Excel sheets and merged headers, clarification ranking and bulk patterns, bulk confirm, manual model install, suggested questions, margin scrolling, conversation paging, per-source storage. Four items are deferred with a reason rather than left open: voice escalation, re-asking an escalated question locally, editing a past question, and memory import/export.

Three need real data and cannot be answered by thinking: the clarification cap of 5, the retention targets, and the abstention band.

## Build procedure

Running the concept-to-build procedure over the existing docs. **Its phase numbers are not `build-plan.md` phase numbers.**

| Step | State |
| ---- | ----- |
| P0/P1 — spec, metrics, states | **done**, then redone after the repositioning |
| P2 — design the screens, in `docs/ux/` | **done** — design system + 10 screens |
| Review the data model against what the screens need | **done** — #20 closed |
| P6 — full ticket backlog | **done** — 177 tickets in `docs/backlog/`, superseding the `docs/stories/` sample format |
| Build M0 | **unblocked** — docs, specs, designs and backlog all locked to current decisions |

Screens before schema is deliberate: drawing a screen surfaces the missing button and the number with nowhere to come from.

## Eval baseline

Not yet established. First run at the end of Phase 1.

| Model | Suite | Overall | Worst-case | Date |
| ----- | ----- | ------- | ---------- | ---- |
| —     | —     | —       | —          | —    |

## Session log

**2026-08-26 (decisions locked)** — Designs approved. **Tauri desktop shell** and **web search** both decided yes, and everything reworked to match rather than left drifting. Web search is constraint **C10**: an escalation the user performs, never a fallback when retrieval is thin — because an automatic one destroys abstention, which is the behaviour the whole product protects. C1 now names both egress paths. New `docs/web-search.md`, new specs `docs/ux/conversation.md` and `docs/ux/web-search.md`, three new lab screens (40 total, swept clean across three widths and both themes). Backlog reworked to **198 tickets** across 10 milestones including a new Phase 6.5, 573–821 hours raw. Quality gate at 165 tasks with a web-escalation category at 1.00, no exceptions. Closed #34, #35, #37, #38.

**2026-08-26 (issues closed)** — Resolved every open issue before any build work. **C9 added** — a bundled model must be redistributable, commercial-use permitted and ungated; Gemma is permanently excluded on that basis. **Model swapping is permitted and marked** rather than restricted, with a persistent marker on answers from an unvalidated model, following the retrieval-threshold precedent. v2 language findings recorded in `architecture.md` §6.1 — the Tamil TTS plan rests on a non-commercial model and Sinhala ASR has no shippable option, which strengthens the deferral that was originally argued on schedule alone. Closed #6, #7, #9 as superseded by M0 tickets, and #24–#28 as resolved. Backlog updated: new ticket M7-SET-FE-146a, C9 added to the constraint coverage map.

**2026-08-26 (backlog)** — MODE B produced the full execution package in `docs/backlog/`: 9 milestones, 31 epics, **176 tickets**, 514–737 hours before the rework multiplier. Verified: IDs 001–176 with no gaps or duplicates, no ticket over 6 hours, zero code or SQL or YAML, 187 references to the existing screen specs and 65 to the state document, six tickets correctly left `blocked:decision` rather than guessed. Applied #24 and #25 in the same change — Piper reverted to Kokoro-82M, profile models corrected to the real Qwen3.5/3.6 line, and `AGENTS.md` §4 gained a registry-verification rule for model names after that mistake was made twice. #26 and #28 remain open decisions.

**2026-08-26** — Ran the backlog agent's MODE A over all documentation. It surfaced four things worth the pass on its own: **target platforms were never documented anywhere**, the C1 egress mechanism was one sentence with no way to produce the outbound counter that settings promises, containerised inference silently excluded macOS, and PyMuPDF's AGPL licence conflicts with Apache-2.0 distribution. Confirmed the stack: all three platforms with **native inference**, **egress proxy** enforcing C1, **no web container** (static assets served by the API), **pypdfium2**. Seven containers plus one native process. Also fixed documentation bugs it found — PRD §11 had lost two items and was numbered 1,3; architecture claimed seven containers and diagrammed eight; `states-and-edge-cases.md` still said "for admins" and cited the renamed `edge` profile and two stale constraint numbers. Next: MODE B, the full ticket backlog.

**2026-08-10 (P6 format)** — Story format and milestones in `docs/stories/`. Five M1 stories written in full as samples rather than generating the whole backlog against an unagreed shape. Notable: **M2 "It says when it doesn't know" is its own milestone** — abstention and the failure states normally get folded into "the chat feature" and quietly dropped when time runs short, and they are the product's central claim. M1.3 ships an ungrounded answer path and says so explicitly, with M1.4 following immediately to satisfy C4; that is a deliberate temporary state, not an oversight. Manual tests walk from a cold start every time, so an upstream regression surfaces on the next story rather than in someone's install.

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
