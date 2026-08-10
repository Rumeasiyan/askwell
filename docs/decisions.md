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

**Decision:** `Rumeasiyan/vaultq` (private) is the tracker. Anything raised in conversation that a future reader would need becomes an issue at the moment it is found. Work happens on a branch off `main` and lands through a PR, not by committing to `main` directly.

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

**Decision:** VaultQ ships as self-hosted software with an offline signed JWT licence, machine-bound to a hardware fingerprint. There is no multi-tenant hosted plane holding customer data. Ever.

**Why:** Data sovereignty is the entire value proposition. The target customers — ministries, hospitals, banks — cannot use cloud AI at all; that inability is the reason they are reachable. A hosted plane holding their content would destroy the only thing distinguishing VaultQ from a frontier model they already cannot buy. The recurring-revenue argument for SaaS was considered and rejected on those grounds; the subscription is attached to the licence and the update stream instead.

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
