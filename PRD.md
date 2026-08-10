# VaultQ — Product Requirements Document

**Version:** 0.1 (draft for build)
**Owner:** Suseenthiran Arulraj Rumeasiyan (Rumeasiyan)
**Status:** Approved for Phase 0 implementation
**Last updated:** 2026-08-10

---

## 1. What VaultQ is

VaultQ is a **sovereign AI workspace**: an AI assistant that reads an organisation's documents, queries its databases, and answers questions by text or voice — running entirely on the organisation's own hardware, with no data leaving the building.

**Positioning line:** _Ask your organisation anything. Nothing leaves the building._

The wedge is not model quality. Frontier cloud models will always be smarter. The wedge is **the set of customers who cannot use cloud AI at all** — government ministries, hospitals, banks, legal firms, NGOs handling sensitive case data — and who currently have no AI option whatsoever. For them the alternative to VaultQ is not ChatGPT; it is a filing cabinet.

Secondary wedge: **bilingual English/Tamil** operation. No cloud vendor serves Tamil-first government workflows in Sri Lanka well, and no local vendor ships a private deployment.

### 1.1 Non-goals

VaultQ is explicitly **not**:

- A chatbot builder or prompt-management platform.
- A coding assistant.
- A cloud service. There is no multi-tenant hosted plane holding customer data. Ever.
- A model trainer. VaultQ runs existing open-weight models; it does not fine-tune them in v1.
- A replacement for the customer's BI tool. It answers questions; it does not build dashboards.

---

## 2. The commercial model (resolve this before writing code)

"Local AI" and "SaaS" are in tension. VaultQ resolves it as **self-hosted software with a subscription licence**, not as a hosted service:

| Layer                                              | Where it runs                                 | Commercial                        |
| -------------------------------------------------- | --------------------------------------------- | --------------------------------- |
| Inference, documents, database, voice, audit log   | 100% customer hardware                        | —                                 |
| Software licence + updates + model packs + support | Signed offline licence key                    | Annual subscription per seat-band |
| Optional: fleet telemetry, remote health checks    | Customer opt-in, metadata only, never content | Included in higher tiers          |

**Licence enforcement is offline-first.** A signed JWT licence file, machine-bound to a hardware fingerprint, with an expiry date and a seat cap. The product degrades gracefully at expiry (read-only mode, 30-day grace) rather than hard-failing — a ministry losing AI access mid-week because a renewal PO was slow is how you lose the account.

**Tiers (indicative, LKR):**

| Tier        | Seats     | Deployment                     | Annual    |
| ----------- | --------- | ------------------------------ | --------- |
| Department  | up to 25  | Single node, CPU or 1 GPU      | 850,000   |
| Institution | up to 150 | Single node + GPU              | 2,400,000 |
| Ministry    | unlimited | HA pair, dedicated support SLA | Quoted    |

Implementation charges (data connection, document migration, on-site training) are billed separately as project work — this is where Quantum Plus makes margin in year one.

---

## 3. Users

| Persona                     | What they do                                                                                          | Success looks like                                                                      |
| --------------------------- | ----------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| **Officer** (primary)       | Asks questions in Tamil or English, by keyboard or voice. Reads answers with citations.               | Gets a correct, sourced answer in under 20 seconds without opening a single file.       |
| **Analyst**                 | Asks questions that require the database. Checks the SQL VaultQ generated before trusting the number. | Never has to write SQL for a routine question, but can always see and correct what ran. |
| **Administrator**           | Connects data sources, manages users and roles, watches the audit log.                                | Can prove to an auditor exactly who asked what and which records were touched.          |
| **Deployer** (Quantum Plus) | Installs on customer hardware, often air-gapped.                                                      | Full install from a USB drive in under two hours, no internet.                          |

---

## 4. Core capabilities

### 4.1 Document intelligence

Ingest, index, and answer questions over the organisation's document corpus.

**Formats:** PDF (native + scanned), DOCX, XLSX, PPTX, TXT, MD, HTML, images (JPG/PNG).

**Pipeline:** upload → type detection → extraction → OCR fallback for scanned pages → layout-aware chunking → embedding → pgvector index.

**Requirements:**

- Scanned Tamil and English documents must OCR correctly. This is non-negotiable for the government segment, where a large share of circulars exist only as scans. Use Tesseract with `tam` + `eng` traineddata; evaluate PaddleOCR as a fallback for tables.
- Chunking is **structure-aware**, not fixed-size. Respect headings, table boundaries, and list items. A chunk that splits a table row from its header is a defect.
- Every chunk retains: source document, page number, section heading, ingestion timestamp.
- Re-ingesting a changed document supersedes the old version rather than duplicating it. Answers must be able to say "as of the June revision".
- Retrieval is **hybrid**: dense (pgvector, cosine) + lexical (Postgres full-text with a Tamil-aware configuration), fused with Reciprocal Rank Fusion. Dense-only retrieval fails badly on circular numbers, form codes, and proper nouns — which is most of what these users search for.
- A reranker pass over the top 20 candidates before they reach the model. Start with `bge-reranker-v2-m3`; it fits CPU and materially improves grounding.

**Citation is mandatory.** Every factual claim in an answer carries a chunk reference the UI renders as a clickable source showing document name, page, and the exact retrieved passage. An answer without citations is a bug, not a style choice.

### 4.2 Database question-answering

Let non-technical users ask questions of operational databases in natural language.

**Connectors (v1):** PostgreSQL, MySQL/MariaDB, SQL Server. Read-only credentials only — the connection wizard refuses credentials that pass a write-permission probe.

**Flow:** question → schema retrieval (only tables relevant to the question, via embedded table/column descriptions) → SQL generation → static validation → dry-run `EXPLAIN` → execution under limits → result formatting → natural-language answer.

**Safety layers, all mandatory:**

1. Database role is `SELECT`-only, enforced at the database, not in application code.
2. Generated SQL is parsed with `sqlglot`. Anything that is not a single `SELECT`/`WITH` is rejected before it reaches the driver. Regex filtering alone is not acceptable.
3. Automatic `LIMIT` injection (default 1000) when the query has no aggregate and no explicit limit.
4. `statement_timeout` of 30s, enforced per-session.
5. Column-level access control: an administrator can mark columns as restricted per role, and restricted columns are stripped from the schema shown to the model. The model cannot select what it cannot see.
6. Every executed query is written to the audit log with the user, the question, the SQL, the row count, and the duration.

**The generated SQL is always shown to the user**, collapsed by default, expandable. Analysts do not trust a number they cannot trace, and they are right not to.

**Schema documentation.** Administrators can annotate tables and columns with plain-language descriptions. These annotations are embedded and retrieved alongside the schema. This single feature moves text-to-SQL accuracy more than any model upgrade — a column called `st_cd` is unguessable, and `st_cd — student status code: A=active, T=transferred, D=dropped` is trivial.

### 4.3 Agent loop

The reasoning layer that decides which tools to call and composes the final answer.

**Tools exposed in v1:**

| Tool                                      | Purpose                               |
| ----------------------------------------- | ------------------------------------- |
| `search_documents(query, top_k, filters)` | Hybrid retrieval over the corpus      |
| `query_database(connection_id, sql)`      | Validated read-only SQL execution     |
| `get_schema(connection_id, hint)`         | Relevant table/column definitions     |
| `list_documents(filters)`                 | Corpus browsing and existence checks  |
| `get_current_date()`                      | Grounding for relative-time questions |

**Loop constraints:**

- Hard ceiling of 8 tool calls per turn. On reaching it, VaultQ returns what it has plus an explicit note that it stopped early. Unbounded agent loops on a CPU-only box are how you get a 12-minute response.
- Parallel tool calls are supported and preferred where the model emits them.
- Every step is recorded in a trace. The UI exposes the trace behind a "how did you get this?" toggle.

**Abstention is a first-class behaviour.** When retrieval returns nothing above the relevance threshold, VaultQ says it does not know and suggests what would need to be ingested. It never falls back to model world-knowledge for organisation-specific questions. The system prompt must enforce this, and the eval suite must test it explicitly (see §7).

### 4.4 Voice

Speak to VaultQ, hear the answer back.

**Pipeline:** browser mic → WebSocket audio stream → Silero VAD for turn detection → STT → agent → TTS → streamed audio back.

**STT:** `whisper.cpp`. Model size selected per deployment profile — `small` for English-only CPU deployments, `medium` or `large-v3-turbo` where Tamil is required, since Tamil accuracy degrades sharply below `medium`.

**TTS:** engine is pluggable behind an interface, because the English and Tamil answers are different problems.

- English: Kokoro-82M (Apache-2.0, ~327MB, comfortable on CPU).
- Tamil: MMS-TTS `tam` or IndicTTS. Quality will be noticeably below the English voice; the UI must not pretend otherwise, and the roadmap should assume this improves via model swap, not via VaultQ code.

**Latency budget** (from end of user speech to first audio out): 3.5s on the GPU profile, 8s on the CPU profile. Miss these and users abandon voice permanently after two tries. Mitigations: stream TTS sentence-by-sentence rather than waiting for the full answer; begin STT on VAD-detected pause rather than on a stop button.

**Voice is a mode, not a separate product.** Same agent, same tools, same audit log. The only difference is transport.

### 4.5 Administration

- User management with RBAC: `admin`, `analyst`, `officer`, `auditor`.
- Data source management: document collections, database connections, per-role visibility on both.
- Model management: which model is loaded, swap without redeploying, see current memory footprint and measured tokens/sec.
- **Audit log:** append-only, exportable, covering every question, every retrieved chunk, every executed query, and every administrative change. For the government segment this is not a feature, it is the reason procurement approves the purchase.
- Usage dashboard: questions per department, most-asked topics, abstention rate. Abstention rate is the key operational metric — a rising rate means the corpus has gaps.

---

## 5. Architecture

### 5.1 Decisions (locked — do not re-litigate during implementation)

| Layer          | Choice                                                                    | Why                                                                                                                                                                                               |
| -------------- | ------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Backend API    | **Python 3.12 + FastAPI**                                                 | The whole AI toolchain — llama-cpp bindings, whisper.cpp wrappers, Kokoro, sqlglot, OCR, embeddings — is Python-native. A second backend language would buy nothing and cost integration surface. |
| Frontend       | **Next.js 15 (App Router) + TypeScript + Tailwind + shadcn/ui**           | Server components for the document browser, client components for chat and voice streaming.                                                                                                       |
| Database       | **PostgreSQL 17 + pgvector**                                              | One system for relational state, vectors, and full-text. Do not add a separate vector database in v1.                                                                                             |
| Cache / queue  | **Redis + arq**                                                           | Ingestion jobs, embedding batches, scheduled re-indexing.                                                                                                                                         |
| Inference      | **llama.cpp server** (OpenAI-compatible), separate container              | Model-agnostic, swappable, runs CPU or CUDA from the same interface.                                                                                                                              |
| Object storage | **Local filesystem volume**, S3-compatible interface behind it            | Air-gapped installs cannot assume MinIO; keep the abstraction, default to disk.                                                                                                                   |
| Auth           | **JWT RS256, Argon2id password hashing, TOTP MFA, Redis token blacklist** | Reuse the established Auth-System-Design pattern.                                                                                                                                                 |
| Packaging      | **Podman/Docker Compose bundle**, offline image tarballs                  | Single-host install from USB with no registry access.                                                                                                                                             |

### 5.2 Service topology

```
                        ┌──────────────────┐
   browser ──HTTPS/WS──▶│   web (Next.js)  │
                        └────────┬─────────┘
                                 │ REST + WS
                        ┌────────▼─────────┐
                        │   api (FastAPI)  │──┐
                        └────────┬─────────┘  │
                                 │            │
        ┌────────────┬───────────┼────────────┼──────────────┐
        │            │           │            │              │
   ┌────▼────┐  ┌────▼────┐ ┌────▼─────┐ ┌────▼────┐  ┌──────▼──────┐
   │ postgres│  │  redis  │ │  llm     │ │ voice   │  │  worker     │
   │+pgvector│  │         │ │llama.cpp │ │stt/tts  │  │ (arq)       │
   └─────────┘  └─────────┘ └──────────┘ └─────────┘  └─────────────┘
                                 │
                        ┌────────▼─────────┐
                        │ customer DBs     │  read-only, network-restricted
                        └──────────────────┘
```

Seven containers (`web`, `api`, `postgres`, `redis`, `llm`, `voice`, `worker`). Resist adding an eighth without a strong reason — every service is one more thing a deployer has to debug on a ministry's network at 4pm on a Friday.

### 5.3 Deployment profiles

Selected at install time by a hardware probe; drives model selection, whisper size, and concurrency limits.

| Profile       | Hardware              | LLM                | Concurrency | Expected                             |
| ------------- | --------------------- | ------------------ | ----------- | ------------------------------------ |
| `edge`        | 16GB RAM, CPU only    | Qwen3 4B Q4_K_M    | 2           | ~8 tok/s, text-first, voice degraded |
| `standard`    | 32GB RAM, 8–12GB VRAM | Qwen3 8B Q4_K_M    | 8           | ~40 tok/s, full voice                |
| `institution` | 64GB+, 24GB VRAM      | Qwen3 32B Q4_K_M   | 25          | Full capability                      |

The installer must **refuse to proceed** below the `edge` floor rather than deploying something that will be blamed on the product. A bad first deployment costs more than a lost sale.

---

## 6. Data model (core tables)

```
organisations      id, name, licence_tier, created_at
users              id, org_id, email, password_hash, role, totp_secret, locale, is_active
collections        id, org_id, name, description, visible_to_roles[]
documents          id, collection_id, filename, mime, sha256, page_count,
                   version, superseded_by, status, uploaded_by, uploaded_at
chunks             id, document_id, ordinal, page_from, page_to, heading,
                   content, content_tsv, embedding vector(1024)
db_connections     id, org_id, kind, dsn_encrypted, visible_to_roles[], last_probe_at
db_schema_notes    id, connection_id, table_name, column_name, description, embedding
conversations      id, org_id, user_id, title, mode(text|voice), created_at
messages           id, conversation_id, role, content, trace jsonb, created_at
audit_events       id, org_id, user_id, kind, payload jsonb, occurred_at   -- append-only
eval_runs          id, model_label, suite_version, scores jsonb, ran_at
```

Notes:

- `chunks.embedding` dimension follows the chosen embedding model; `bge-m3` gives 1024 and handles Tamil acceptably. Pin it in config, not in the migration.
- `audit_events` has no `UPDATE` or `DELETE` grant for the application role. Enforce at the database.
- `dsn_encrypted` uses a key derived from the licence file plus a per-install secret, so a copied database volume is not a credential leak.

---

## 7. Evaluation gate

VaultQ ships with a golden evaluation suite. **No model becomes the default in a deployment profile without passing it.**

Suite structure (extends the harness ported into `eval/bench.py`):

| Category                               | Count | Pass bar                                     |
| -------------------------------------- | ----- | -------------------------------------------- |
| Grounded document QA                   | 40    | ≥ 0.85 mean, ≥ 0.70 worst-of-3               |
| Abstention (unanswerable)              | 15    | ≥ 0.90 — hallucination here is disqualifying |
| Conflicting-source handling            | 10    | ≥ 0.75                                       |
| Text-to-SQL (execution-matched)        | 40    | ≥ 0.80 mean                                  |
| SQL safety (write attempts, injection) | 10    | 1.00 — no exceptions                         |
| Tool selection incl. parallel          | 25    | ≥ 0.85                                       |
| Tamil comprehension + response         | 20    | ≥ 0.75                                       |

Each task runs three times; **worst-case is reported alongside mean**, because a single malformed tool call fails an entire agent turn and errors compound across steps. A model at 0.90 mean with 0.55 worst-case is worse in production than a steady 0.80.

The suite runs in CI on every prompt change. Prompt engineering without an eval gate is guessing.

---

## 8. Security requirements

- All service-to-service traffic on an internal container network; only `web` is published.
- Customer database connections are read-only, credential-probed at setup, and network-restricted to the `api` and `worker` containers.
- Documents are encrypted at rest on the volume.
- No outbound network calls from any container by default. Model downloads happen at build/install time, not runtime. An air-gapped install must work with the network cable physically unplugged, and this must be part of the release test.
- Optional telemetry is opt-in, metadata-only, and inspectable — the customer can see exactly what would be sent before enabling it.
- Prompt-injection defence: content retrieved from documents is delimited and the system prompt states that retrieved content is data, never instruction. Tool calls arising from a turn where retrieved content contained instruction-like patterns are flagged in the trace. This is a mitigation, not a solution; document the residual risk honestly in the security appendix rather than overclaiming.

---

## 9. Build phases

Each phase ends in something demonstrable. Do not begin a phase before the previous one's acceptance criteria pass.

### Phase 0 — Skeleton (target: 1 week)

Compose stack up, migrations, auth (register/login/JWT/RBAC), health checks, CI running lint + tests.

_Accept when:_ a user can register, log in with TOTP, and hit an authenticated endpoint; `podman-compose up` works from a clean clone.

### Phase 1 — Document QA (target: 2 weeks)

Upload → extract → OCR → chunk → embed → hybrid retrieve → rerank → answer with citations. Chat UI with streaming.

_Accept when:_ a scanned Tamil PDF is uploaded and a question about it returns a correct cited answer; the abstention eval subset scores ≥ 0.90.

### Phase 2 — Database QA (target: 2 weeks)

Connection wizard, schema introspection and annotation, text-to-SQL with the full validation chain, result rendering, SQL disclosure UI.

_Accept when:_ the SQL-safety eval subset scores 1.00 and execution-match ≥ 0.80 on a real customer-shaped schema.

### Phase 3 — Agent loop (target: 1.5 weeks)

Tool registry, multi-step loop with the 8-call ceiling, parallel calls, trace capture, trace UI.

_Accept when:_ a question requiring both a document lookup and a database query is answered correctly in one turn, with a readable trace.

### Phase 4 — Voice (target: 2 weeks)

WebSocket audio, VAD, STT, sentence-streamed TTS, mode toggle, language detection.

_Accept when:_ the `standard` profile meets the 3.5s latency budget on an English round trip and completes a Tamil round trip correctly.

### Phase 5 — Admin, audit, packaging (target: 2 weeks)

Admin console, audit log with export, usage dashboard, licence key validation, offline install bundle with an installer script and hardware probe.

_Accept when:_ a complete install succeeds on a clean machine with the network cable unplugged.

### Phase 6 — Pilot hardening

Deploy to one real customer. Everything after this is driven by what breaks there, not by this document.

---

## 10. Repository layout

```
vaultq/
├── CLAUDE.md                  # agent charter — read this first
├── PRD.md                     # this file
├── BRAIN.md                   # mutable build state (phase, decisions, blockers)
├── compose.yaml
├── compose.gpu.yaml
├── api/
│   ├── pyproject.toml
│   └── src/vaultq/
│       ├── main.py
│       ├── config.py
│       ├── auth/              # jwt, argon2, totp, rbac
│       ├── ingest/            # extractors, ocr, chunking, embedding
│       ├── retrieval/         # dense, lexical, rrf, rerank
│       ├── sql/               # introspection, generation, sqlglot validation, execution
│       ├── agent/             # tool registry, loop, tracing, prompts
│       ├── voice/             # vad, stt, tts, ws transport
│       ├── admin/
│       ├── audit/
│       └── db/                # models, migrations
├── web/                       # Next.js 15
├── worker/                    # arq tasks
├── eval/
│   ├── bench.py
│   ├── suites/                # documents.jsonl, sql.jsonl, tools.jsonl, tamil.jsonl
│   └── results/
├── deploy/
│   ├── install.sh             # hardware probe, profile selection, offline bundle
│   └── bundle/
└── docs/
    ├── architecture.md
    ├── security.md
    └── operations.md
```

---

## 11. Decisions still open

These need Rumeasiyan's answer; Claude Code should **not** guess at them.

1. **Tamil scope in v1** — full parity (UI, STT, TTS, retrieval), or comprehension-only (understands Tamil questions, answers in Tamil text, English voice only)? This changes the Phase 4 estimate by roughly a week and changes the STT model size, which changes the `edge` profile's viability.
2. **Sinhala** — v1, v2, or never? Affects OCR traineddata, embedding model choice, and eval suite size.
3. **First pilot customer** — Ministry of Education Eastern Province, or a commercial account with a lower blast radius? A government pilot buys credibility and costs velocity.
4. **Multi-node** — is an HA pair in scope for the Ministry tier at launch, or a post-launch promise? It affects whether Phase 0 assumes a single Postgres.
5. **Brand relationship** — VaultQ as a Quantum Plus product, or a standalone venture with its own entity? Affects licensing entity, pricing authority, and whether the repo lives under the company org.

---

_Name alternatives considered, if VaultQ does not survive a trademark check: **SiloQ**, **AnchorQ**, **KeepQ**._
