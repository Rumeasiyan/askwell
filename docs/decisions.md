# Decision log

Append-only. **Newest first.** Never edit an entry to change its meaning — if a decision is reversed, add a new entry that says so and link back.

**Bar for an entry:** something a competent person would later ask *"why is it like this?"* about. Architecture changes, dependency choices, resolved `docs/PRD.md` §11 questions, reversals. **Not** routine implementation choices — those are visible in the diff.

**The *Why* should be longer than the *Decision*.** What was built is readable from the code. What was rejected, and the trade-off accepted, is not, and is exactly what gets lost. Name the rejected option.

Template:

```markdown
## YYYY-MM-DD — Title

**Decision:** one or two sentences.

**Why:** the reasoning. What alternatives were considered and why they lost. What trade-off is being accepted knowingly.

**Consequences:** what this now forces, forbids, or costs. What would have to change to reverse it.

**Refs:** PRD sections, issues, commits, files.
```

---

## 2026-08-10 — Renamed to Askwell; Apache-2.0 with a proprietary credit service

**Decision:** VaultQ becomes **Askwell**. The application is open source under **Apache-2.0**; the online-AI credit service stays proprietary. Repository renamed to `Rumeasiyan/askwell`.

**Why the name:** The Q was dropped on the owner's call. Askwell was chosen over Marginalis and Gleanly. Marginalis was the more coherent choice on paper — it names the design signature, the permanent provenance margin — and was rejected for being four syllables that need spelling out loud, which is a real cost for a project that spreads by word of mouth. Gleanly was rejected for brand adjacency to Glean, a well-funded enterprise search company in a neighbouring space. Askwell names the differentiator directly: it is the thing that *asks*.

Every real dictionary word was already taken on both npm and PyPI, so a coined name was the only option that keeps `pip install askwell` and an unscoped npm package available.

**Why open source, and why it costs less than it looks:** The product's entire claim is that nothing leaves the machine. A closed-source local AI asking to be trusted offers only a promise; an open one can be audited, and the people this product is for are precisely the ones who will want to audit it or know someone who will. **The source is the proof of the central claim**, which makes this closer to a marketing asset than a giveaway.

The business is not the code. It is the credit service — provider contracts, metering, billing. Forking the client gives none of that, and anyone who wants to compete has to build an inference business, which was never gated on the source.

Rejected alternatives. **AGPL** looks protective and mostly is not here: its network trigger rarely fires for a local desktop application, so it buys little while deterring some contributors and corporate users. **BSL / fair-source** offers real protection against a competing commercial service and forfeits the trust and contribution benefit that is the entire reason to open the source — which for this product is the point. **Staying closed** keeps every option open and gives up the auditability argument, which is the strongest thing the product has to say about itself.

**Consequences:**

- Someone can fork Askwell and point it at their own credit service. Nothing prevents that. The position is protected by the trademark, the brand and the operational reality of running paid inference — so **the trademark now needs registering**, which is a new open item.
- Free and open sets a support expectation a single maintainer cannot meet. A stated support boundary and issue triage must exist before the first public release, not after it.
- Everything shipping before Phase 7 is free and open, so v1 earns nothing. Adoption has to come first and the credit system stops being an add-on — it is the business.
- The competitive field is large and established: AnythingLLM (64k stars), private-gpt (57k), Quivr (39k), Khoj (36k), Onyx (31k), open-webui (148k). Askwell will not win generic search terms against these and should not try. **None of them asks the user about their data or remembers the answers** — that phrase is unclaimed, and discovery strategy should own it rather than compete on "local AI for documents".

**Refs:** `PRD.md` §7, §11; `LICENSE`; repository `Rumeasiyan/askwell`.

---

## 2026-08-10 — No telemetry in v1, and the metrics cost is accepted

**Decision:** Askwell ships no telemetry through Phase 6 — not anonymous, not opt-in, not off-by-default. Product understanding comes from direct contact with a small number of users, and from Phase 7 onward from paying users who are observable by necessity.

**Why:** The obvious answer was opt-in, off by default, with a screen showing exactly what would be sent. That is the ethical version and it was rejected anyway, because the target user is by definition someone who cannot upload their material and has already decided cloud tools are not for them. To that person a telemetry toggle is not a reassurance, it is the first paragraph of a story they have read before. Trust is the entire reason they installed a local product, and spending some of it on numbers is a bad trade — particularly since opt-in telemetry self-selects toward engaged users and biases every retention figure optimistically.

**Consequences, stated rather than buried:** none of `success-metrics.md` §1 is observable. Retention, second-source rate and clarification dismissal rate cannot be measured. The product is built on reasoning and a handful of real conversations instead of a dashboard, and that is a genuine handicap. The dismissal-rate ceiling in §3 exists to catch the clarification loop being annoying, and it now has no instrument — so that risk is carried by the per-source cap being conservative instead.

Revisit at Phase 6, when there are users to ask.

**Refs:** `success-metrics.md` §5, §6; constraint C1.

---

## 2026-08-10 — v1 imports PostgreSQL dumps only

**Decision:** SQL dump import supports PostgreSQL. MySQL and SQL Server dumps are not supported as dumps; those users connect live or export CSV.

**Why:** A MySQL dump cannot load into a Postgres sandbox. Supporting it means either a second sandbox engine — a ninth container on somebody's laptop, for a free product — or a dialect translation layer, which is large, permanently leaky, and fails on exactly the vendor-specific constructs that make dumps worth importing.

Neither is justified when two adequate paths already exist. Live connections already cover MySQL and SQL Server and need no dump. CSV export exists in every database tool ever written, lands in the same sandbox, and actually produces *better* results because the ambiguity of an untyped CSV is what the clarification loop is best at.

The cost is a real dead end for someone holding a `.sql` file from MySQL, which is why the rejection message must name both alternatives rather than simply refusing. A dead end with no route out is how someone concludes the product does not handle their data.

**Consequences:** the sandbox container is Postgres-only, which keeps it identical to the main database image and saves bundle size in the offline installer. Revisit if real users turn out to arrive holding MySQL dumps and nothing else.

**Refs:** `data-sources.md` §7; constraint C3.

---

## 2026-08-10 — Repositioned: single-user personal product, free, local-first

**Decision:** Askwell is a free local install for **one individual professional**, not on-premise software sold to organisations. No teams, roles, tenancy, seats, licence keys or high availability. Revenue comes only from optional online-AI credits, which is the last thing built. `PRD.md` becomes a business-only document; all technical content moves to `architecture.md`, `data-sources.md`, `memory-and-clarification.md`, `audit-log.md` and `build-plan.md`.

Two capabilities are added: **CSV and SQL dump import**, and a **clarification loop with permanent memory**.

**Why:** The previous documentation described a product the owner did not intend to build. It targeted Sri Lankan government ministries with seat-banded LKR pricing, an offline signed licence, four RBAC roles and a "Deployer" persona flying to customer sites — none of which was wanted. That framing originated in the initial `PRD.md` (commit `dcd12cf`) and every later document inherited it, including two written during this work.

The new positioning is narrower and more defensible. The people who genuinely cannot upload their material — client confidentiality, unpublished research, legal privilege — are reachable as individuals without a procurement cycle, and free removes the last obstacle for someone who cannot evaluate the product on anything but their own real files.

Rejected alternatives: **self-hosted subscription** keeps the pricing question that made the old design heavy, and charging upfront for something the user cannot trial on their real data is the wrong order. **One-time purchase** gives no recurring line at all. Free-plus-credits was chosen knowing the trade: v1 earns nothing, so adoption must come first and the credit system stops being a nice-to-have and becomes the business.

The clarification loop is the reason to prefer Askwell over the local RAG tools that already exist. It also fixes something the old design asserted and never solved — that schema annotations matter more than a model upgrade, while relying on an administrator volunteering to write hundreds of them, which nobody does. Asking at the moment of ambiguity, about one thing, with the file open, is the only version that gets populated.

**Consequences:**

- **Constraints renumbered** (`AGENTS.md` §3). C1 now permits an explicit per-conversation online opt-in rather than forbidding all egress — the tagline "nothing leaves the building" no longer holds unconditionally and the honest version is stated instead. Old C7 (column-level access control per role) is **deleted**: it protected one role from another and there are no roles. New C3 covers dump sandboxing. C6 is restated as **tamper-evident, not immutable**, because the user owns the disk and any stronger claim is false.
- **Authentication collapses.** JWT RS256, Argon2id, TOTP MFA and a Redis blacklist across four roles become a local session plus an optional at-rest passphrase. MFA on a single-user desktop app protects against nothing and guarantees that losing a phone loses your own files.
- **Data model loses `organisations`, `users`, roles and `visible_to_roles[]`**, and gains `memory`, `clarifications`, `sources` and two separate audit tables.
- **A dump is executable code**, so imports need an isolated sandbox Postgres — an eighth service, accepted deliberately because retrofitting isolation would mean migrating data on users' machines.
- **Every metric in `success-metrics.md` was re-derived.** There is no pilot, so retention targets are lower and, uncomfortably, **none of the primary metrics are observable without opt-in telemetry** — which is a real cost of the privacy promise, not something to design around quietly.
- Deployment profile floor drops to 8GB and the installer **warns instead of refusing** below it. Refusing suited a paid deployment that could be blamed on the vendor; for a free download it is a lost user.
- Voice survives. It was proposed for deferral in favour of memory and the owner kept both, so the plan is longer rather than one displacing the other.

**Refs:** `PRD.md`, `architecture.md`, `data-sources.md`, `memory-and-clarification.md`, `audit-log.md`, `build-plan.md`; issues #3, #4, #5, #10, #11, #12, #13, #14, #15; commit `dcd12cf`.

---

## 2026-08-10 — Abstention rate is a band with a counter-metric, not a target

**Decision:** `docs/success-metrics.md` treats abstention rate as a **5–20% band**, always reported alongside a citation-correctness counter-metric. Not as a number to minimise.

**Why:** `docs/PRD.md` §4.5 calls abstention rate the key operational metric, reasoning that a rising rate means the corpus has gaps. That is true and it is half the picture. The dangerous direction is the other one.

Abstention rate can be driven to zero by lowering the retrieval threshold — a one-line config change that makes the dashboard look excellent while breaking C4, because the system starts answering from world-knowledge instead of saying it does not know. Every incentive points that way: a customer complaining "it keeps saying it doesn't know" is a live support conversation, and the fix that ends the conversation fastest is the one that ruins the product. Nothing in the number itself reveals this happened.

Hence a band with a floor, and a paired metric that moves in the opposite direction when the threshold is gamed. A falling abstention rate with falling citation correctness is the signature; either number alone looks fine.

The 5–20% boundaries are reasoned, not measured, and are flagged as assumed in the document. They exist so the dashboard has something to alarm on from day one; they should be re-derived from the first month of pilot traffic.

**Consequences:** The usage dashboard (PRD §4.5) must show both numbers together, and the abstention threshold becomes a configuration value whose changes belong in the audit log. Sampling answers for citation correctness needs a mechanism — it is not free, and it is not yet designed.

**Refs:** `docs/success-metrics.md` §2; `docs/PRD.md` §4.5, §7; constraints C3, C4.

---

## 2026-08-10 — Product success is behavioural retention, not eval scores

**Decision:** The primary success metric is whether the pilot customer's officers are still asking questions in week 12 unprompted (`docs/success-metrics.md` §1). Eval scores (PRD §7) are a gate on shipping a model, not a measure of whether the product is succeeding.

**Why:** The two are routinely conflated, and conflating them is how a product with excellent benchmark numbers gets quietly abandoned. Askwell's competitor is a filing cabinet; the question is not whether the model is good but whether an officer reaches for Askwell instead of the cabinet on week 12, when novelty has worn off and the first wrong answer is behind them.

Measuring time-saved or productivity was rejected: it needs a baseline nobody has, and the numbers that result get quoted in sales material and cannot be defended when challenged.

A constraint shaped this: PRD §2 makes telemetry opt-in and metadata-only, and C1 forbids runtime network calls. So **every metric must be computable from the customer's own audit log and visible to them in their own admin console**. Any metric requiring content to leave the site is disqualified regardless of usefulness. That is a real limit on what can be measured, and it is the correct trade.

**Consequences:** The usage dashboard becomes the measurement instrument, not a nice-to-have, which raises its priority in §9 Phase 5. Retention cannot be measured at all until a pilot exists, so these numbers are unfalsifiable until then — they are targets to design against, not evidence.

**Refs:** `docs/success-metrics.md`; `docs/PRD.md` §2, §3, §4.5, §8; issue #3.

---

## 2026-08-10 — v1 is English-only; Tamil and Sinhala move to v2

**Decision:** Resolves `docs/PRD.md` §11 items 1 and 2 (issues #1, #2). v1 ships English only — no Tamil UI, STT, TTS, or eval gate. Tamil and Sinhala leave the phase list entirely and become v2, scoped separately after the pilot rather than as numbered phases here. Sinhala does not start until Tamil has shipped.

Three hedges are kept in v1: the multilingual `bge-m3` embedding model, a Tamil-aware Postgres full-text configuration, and `tam` OCR traineddata in the offline bundle.

**Why:** Tamil carried the two largest schedule risks in the plan and neither was on the critical path to a working product. Whisper `medium`-or-larger is required for usable Tamil STT, which had to run on the 16GB CPU-only `edge` floor — that is why `edge` previously advertised "voice degraded". And Tamil TTS (MMS-TTS `tam`, IndicTTS) is a model-availability problem Askwell cannot fix in code; shipping it would have made the product's worst-sounding component the first thing a Tamil-speaking officer heard.

The alternatives were considered and rejected. **Comprehension-only Tamil** (understand Tamil questions, answer in Tamil text, English voice) keeps most of the retrieval and eval cost for a partial capability, and leaves the awkward position of a product that reads Tamil but will not speak it. **A numbered Phase 7** was rejected because a phase in this document implies its scope is understood, and Tamil scope is exactly what is not understood — what a second language actually needs should be decided with pilot evidence, not with an assumption made before the first install.

The trade-off accepted is real and should not be understated: the bilingual angle was the PRD's stated secondary wedge, and deferring it means the first pilot cannot be a Tamil-first ministry. That constrains the answer to §11's pilot-customer question (issue #3).

The hedges were kept because their cost asymmetry is extreme. Dropping `bge-m3` for an English-only embedding model saves some `edge` CPU and RAM; adding Tamil afterwards means **re-embedding every customer's entire corpus on air-gapped sites with no vendor access** — a migration, not an upgrade. The FTS configuration is a free choice at index creation whose reversal is a full reindex. `tam` traineddata costs bundle size and means Tamil scans extract text rather than failing outright. The TTS interface stays pluggable for the same reason.

**Consequences:**

- Phase 4 drops from 2 weeks to 1.5 — no Tamil STT sizing, no second TTS engine, no language detection. Acceptance is an English round trip on `standard` (3.5s) and `edge` (8s).
- The `edge` profile no longer carries a degraded-voice caveat: whisper `small` serves all three profiles.
- The eval gate is 140 tasks, all English. The Tamil category (20 tasks, ≥ 0.75) is removed and `eval/suites/tamil.jsonl` is not created — a pass bar for a capability that does not ship is a test that gets skipped, and skipped tests decay.
- Phase 1 acceptance changes from a scanned Tamil PDF to a scanned English one.
- The hedges must not be argued into "Tamil is basically supported". They are untested and unevaluated. `docs/PRD.md` §1.2 states this; keep that statement intact.
- The 2026-08-10 hybrid-retrieval entry below still says a Tamil-aware FTS configuration is "required work". That remains true as written — it is now required *as a hedge*, not for a shipping feature. That entry is not edited; this one supersedes its framing.
- §11 item numbers shifted. "§11 item 1" in anything written before today means Tamil scope, not the pilot customer.

**Refs:** `docs/PRD.md` §1, §1.1, §1.2, §4.1, §4.4, §5.3, §6, §7, §9, §11; issues #1, #2; `AGENTS.md` §1.

---

## 2026-08-10 — Prose lives in `docs/`; root holds only what tooling requires

**Decision:** `PRD.md` and `BRAIN.md` moved to `docs/`, joining `decisions.md`. Root keeps `AGENTS.md`, `CLAUDE.md`, `README.md`, `VERSION`, `CHANGELOG.md`, `.github/` and nothing else. `docs/PRD.md` §10 now separates the layout that exists from the layout that is planned, with a table of which directory arrives in which phase.

**Why:** Root was accumulating documents because the original `PRD.md` §10 put them there, and every new file made the next one easier to justify. The test applied instead: does a tool or a convention require this path? `AGENTS.md` and `CLAUDE.md` yes — agents discover them at root and will not go looking in `docs/`. `VERSION` and `CHANGELOG.md` yes — build and release tooling reads them there. `README.md` yes — it is where a human looks. `PRD.md` and `BRAIN.md`, no; nothing reads them by path except the docs that link to them.

Keeping them at root was the alternative and the cheaper one, since it required no reference rewriting. Rejected because the cost only grows: `architecture.md`, `security.md` and `operations.md` are already planned in §10, and a root directory holding eight prose files is one where nobody can tell at a glance what is entry point and what is detail.

Splitting §10 into *exists* and *planned* was the more useful half of this change. Previously it described a tree where almost nothing existed, with no marker saying so — which reads as "these paths are real" and quietly invites scaffolding ahead of the phase, exactly what `AGENTS.md` §4 forbids.

`README.md` was created in the same change. Its absence was the reason someone arriving at the repository had to open the PRD to learn what the product was.

**Consequences:** Every reference to `PRD.md` and `BRAIN.md` across `AGENTS.md`, `CLAUDE.md`, the issue templates and this log is now `docs/`-prefixed; a stale link elsewhere will 404. When a planned directory is created, it must move out of the planned tree in §10 in the same change, or the distinction rots and the section becomes noise.

**Refs:** `docs/PRD.md` §10, `AGENTS.md` §2, `README.md`.

---

## 2026-08-10 — GitHub issues are the task tracker; work lands via PR

**Decision:** `Rumeasiyan/askwell` (private) is the tracker. Anything raised in conversation that a future reader would need becomes an issue at the moment it is found. Work happens on a branch off `main` and lands through a PR, not by committing to `main` directly.

**Why:** The build is documented across three files that are read by an agent starting from zero context each session. Chat transcripts are not part of that set — an open question raised in conversation and not written down is gone by the next session, and the next session will re-derive a different answer. The tracker is the durable place for anything that is not yet a decision (which goes here) or a current task (which goes in `docs/BRAIN.md`).

Committing straight to `main` was the existing practice — both commits in history do it — and was rejected despite being faster. `main` is meant to stay releasable, PRs give the diff a place to be read as a whole before it lands, and a PR body is where an issue reference actually survives. The cost accepted is real: for a solo pre-Phase-0 build this is ceremony, and it will feel like overhead on the first three one-line changes.

Labels were derived from this project's two actual triage axes — which build phase (`phase:0`…`phase:6`) and which hard constraint is touched (`constraint:*`) — rather than importing a generic set. A `constraint:*` issue cannot close without stating how the constraint was preserved; that check is otherwise made silently or not at all.

**Consequences:** Every unit of work costs an issue and a PR. The `blocked:decision` label is now the visible queue of `docs/PRD.md` §11 items. If the tracker fills with noise the labels stop being read, so the "too small for an issue" carve-out in `AGENTS.md` §8 has to be honoured.

**Refs:** `AGENTS.md` §8, `docs/PRD.md` §9, §11.

---

## 2026-08-10 — `VERSION` file is the single source of truth; start at `0.1.0`, bump per change

**Decision:** A root `VERSION` file holds `MAJOR.MINOR.PATCH`, starting at `0.1.0`. It is bumped in the same commit as the work it describes, not batched at release time. No build number yet. No fourth component — a hotfix is a `PATCH`.

**Why:** There is nothing to hang a version on yet: no `pyproject.toml`, no `package.json`, no tags. The alternative was to wait for Phase 0 to create a manifest and use that, which was rejected because Phase 0 will create *two* manifests (`api/` and `web/`) and picking one as canonical after the fact means the other has already been hand-edited to something different. Deciding now that both read from `VERSION` avoids a second manually maintained value — which is the specific failure where a shipped bundle reports a version that matches nothing.

`0.1.0` rather than `1.0.0` because nothing is shippable; `docs/PRD.md` is itself marked v0.1 draft. Per-change bumping rather than release-only was chosen so that a `docs/BRAIN.md` entry, an issue's closing comment, and a version all name the same thing — which is what makes "what was in the pilot build?" answerable six months later.

No build number because this is a Compose deployment with no app-store build counter to satisfy. Phase 5's offline install bundle may need one; deferred rather than invented, because an always-increasing integer that nothing consumes is just another thing to forget to increment.

**Consequences:** Phase 0 manifests must read `VERSION` rather than declaring a version, which is slightly awkward in both Python packaging and `package.json` and will need a small build step. Every user-visible change now also touches `CHANGELOG.md`. `1.0.0` is reserved for the first pilot-ready build at the end of Phase 5.

**Refs:** `AGENTS.md` §7, `VERSION`, `CHANGELOG.md`, `docs/PRD.md` §9.

---

## 2026-08-10 — `AGENTS.md` is the source of truth; `CLAUDE.md` becomes a shim

**Decision:** All working rules, constraints, commands, and conventions moved from `CLAUDE.md` into `AGENTS.md`. `CLAUDE.md` is now `@AGENTS.md` plus Claude-specific notes only. This reverses `CLAUDE.md`'s own instruction that it is static and must not be edited.

**Why:** `AGENTS.md` is the cross-tool convention read natively by several agents; `CLAUDE.md` is read by one. Keeping the substance in the Claude-specific file meant any other tool used on this repository would operate with no knowledge of the six hard constraints — including that model-generated SQL must go through `sqlglot`. That is a bad failure to have depend on which editor someone happened to open.

The alternative — keep both files with full content — was rejected outright. Duplicated rules drift, and the drift is invisible until the two files disagree about something that matters.

The reversal of the "static" rule was made deliberately and with the owner's agreement rather than worked around. The intent behind that rule — that the charter is not casually rewritten mid-task — now attaches to `AGENTS.md`: changes to it are decisions and belong in this log.

**Consequences:** `CLAUDE.md` must stay thin. Anything added there rather than to `AGENTS.md` is invisible to every other tool, and the Claude-read copy will silently win when the two disagree.

**Refs:** `AGENTS.md`, `CLAUDE.md`, commit `8e1f21d`.

---

## 2026-08-10 — `institution` profile is Qwen3 32B, not a "Qwen3.6 27B"

**Decision:** Deployment profiles use `Qwen3 4B` (edge), `Qwen3 8B` (standard), `Qwen3 32B` (institution), all `Q4_K_M`.

**Why:** The PRD draft named `Qwen3.5 4B` and `Qwen3.6 27B` — neither is a real release, and 27B is a Gemma parameter count, not a Qwen one. Left in place, a deployer would have gone looking for a GGUF that does not exist, on an air-gapped install where they cannot simply search for the right name. Corrected to real models on the same family as the already-correct `standard` row, so all three profiles share one tokeniser and one prompt format — which matters because the eval suite's pass bars in `docs/PRD.md` §7 are meant to be comparable across profiles.

Model choice is not locked by this entry: `AGENTS.md` §4 forbids hardcoding model names in application code precisely so a profile's model can be swapped after the eval gate says so. This entry fixes a factual error, it does not endorse Qwen3 32B as final.

**Consequences:** Model sizing for the `institution` profile's 24GB VRAM floor should be re-checked against a real Q4_K_M 32B footprint before Phase 5 packaging.

**Refs:** `docs/PRD.md` §5.3, §7; `AGENTS.md` §4; commit `8e1f21d`.

---

## 2026-08-10 — Self-hosted licence, not hosted SaaS

**Decision:** Askwell ships as self-hosted software with an offline signed JWT licence, machine-bound to a hardware fingerprint. There is no multi-tenant hosted plane holding customer data. Ever.

**Why:** Data sovereignty is the entire value proposition. The target customers — ministries, hospitals, banks — cannot use cloud AI at all; that inability is the reason they are reachable. A hosted plane holding their content would destroy the only thing distinguishing Askwell from a frontier model they already cannot buy. The recurring-revenue argument for SaaS was considered and rejected on those grounds; the subscription is attached to the licence and the update stream instead.

Licence expiry degrades to read-only with a 30-day grace rather than hard-failing, deliberately: a ministry losing AI access mid-week because a renewal PO moved slowly is how the account is lost, and the enforcement is not what stops piracy anyway.

**Consequences:** No usage telemetry by default, so product analytics must come from the customer-side usage dashboard the administrator can see. Every support interaction is on customer hardware the vendor cannot reach. Licence key generation and signing become infrastructure that must exist before the first sale.

**Refs:** `docs/PRD.md` §2, §1.1, §8; `docs/BRAIN.md` decisions log.

---

## 2026-08-10 — Hybrid retrieval (dense + lexical + RRF) from day one

**Decision:** Retrieval is dense (pgvector, cosine) plus lexical (Postgres full-text with a Tamil-aware configuration), fused with Reciprocal Rank Fusion, with a `bge-reranker-v2-m3` pass over the top 20. Built this way from the start rather than added as an optimisation.

**Why:** The queries these users actually type are circular numbers, form codes, and proper nouns. Dense retrieval fails badly on exactly those — an embedding of "Circular 2019/14" is not reliably near the chunk containing it. Starting dense-only and adding lexical later was rejected because the failure would show up first in the Phase 1 acceptance test on a scanned Tamil PDF, and by then the chunking, indexing, and eval baselines would all be built around a retriever that has to change.

Reranking is included from the start for the same reason: it materially improves grounding, which is what `C3` (citations) and `C4` (abstention) depend on, and the abstention threshold cannot be calibrated against a retriever that is about to be replaced.

**Consequences:** The `chunks` table needs both `content_tsv` and `embedding` maintained together; a re-ingest updates both or retrieval silently goes half-blind. A Tamil-aware full-text configuration is required work, not a nice-to-have. The reranker adds CPU cost on the `edge` profile, which is where the latency budget is already tightest.

**Refs:** `docs/PRD.md` §4.1, §5.3, §7; `docs/BRAIN.md` decisions log.

---

## 2026-08-10 — llama.cpp server as the inference layer

**Decision:** Inference runs in a separate container as a llama.cpp server exposing an OpenAI-compatible API.

**Why:** The same interface serves CPU and CUDA deployments, which matters because the `edge` profile is CPU-only and the `institution` profile is not — without this, deployment profiles would fork the application code rather than just the configuration. OpenAI-compatibility means the API layer talks to it through a client that could be pointed elsewhere, and model swapping becomes a config change instead of a code change (see `AGENTS.md` §4: never hardcode a model name).

Running the model in-process via Python bindings was rejected: it couples model memory to API worker lifecycle, and reloading a model would mean restarting the API.

**Consequences:** One more container in a topology already deliberately kept small. Model files are a build/install-time artifact that must be in the offline bundle — they cannot be pulled at runtime (`C1`).

**Refs:** `docs/PRD.md` §5.1, §5.2, §5.3; `docs/BRAIN.md` decisions log.

---

## 2026-08-10 — PostgreSQL + pgvector, no separate vector database

**Decision:** One Postgres instance holds relational state, vectors, and full-text. No Qdrant/Weaviate/Milvus in v1.

**Why:** Every additional service is something a deployer has to debug on a ministry's network with no internet and no vendor access. A dedicated vector database would buy better ANN performance at corpus sizes this product will not see in v1, in exchange for a second datastore to back up, restore, migrate, and explain. Postgres also lets the lexical half of hybrid retrieval and the vector half live in one query plan, which the RRF fusion benefits from directly.

**Consequences:** Retrieval performance is bounded by pgvector's index behaviour; if a customer corpus outgrows it, that is a v2 decision requiring a new entry here. The `chunks.embedding` dimension is pinned in configuration, not in the migration, so an embedding model change does not require a schema rewrite.

**Refs:** `docs/PRD.md` §5.1, §6; `docs/BRAIN.md` decisions log.

---

## 2026-08-10 — All-Python backend, no second backend language

**Decision:** The API is Python 3.12 + FastAPI. No Go or Rust service.

**Why:** The entire AI toolchain — llama-cpp bindings, whisper.cpp wrappers, Kokoro, `sqlglot`, OCR, embeddings — is Python-native. A second backend language would have to reach all of it across a process boundary, adding integration surface for no capability gain. The usual argument for Go or Rust here is throughput, which is not the bottleneck: on the `edge` profile the constraint is ~8 tok/s of model inference, not request handling.

**Consequences:** Async discipline in Python is now load-bearing — a blocking call in a request handler stalls the event loop, and OCR and embedding work are exactly the blocking kind, so they belong in the `arq` worker. `mypy --strict` compensates for the type safety a compiled language would have given for free.

**Refs:** `docs/PRD.md` §5.1, §5.2; `AGENTS.md` §6; `docs/BRAIN.md` decisions log.
