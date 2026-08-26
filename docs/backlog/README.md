# Askwell — engineering execution package

The full ordered backlog: nine milestones, thirty-one epics, **176 tickets**, none longer than six hours.

This is PART 1 — the master execution document. Each milestone is also written up as a standalone file that can be handed to someone on its own:

| Milestone | File | Tickets | Estimate |
| --------- | ---- | ------- | -------- |
| M0 — It runs | [`M0-it-runs.md`](M0-it-runs.md) | 20 | 56–81 h |
| M1 — It answers from my documents | [`M1-it-answers-from-my-documents.md`](M1-it-answers-from-my-documents.md) | 32 | 102–148 h |
| M2 — It says when it doesn't know | [`M2-it-says-when-it-doesnt-know.md`](M2-it-says-when-it-doesnt-know.md) | 15 | 42–58 h |
| M3 — It learns my material | [`M3-it-learns-my-material.md`](M3-it-learns-my-material.md) | 19 | 56–78 h |
| M4 — It answers from my data | [`M4-it-answers-from-my-data.md`](M4-it-answers-from-my-data.md) | 26 | 80–115 h |
| M5 — It handles harder questions | [`M5-it-handles-harder-questions.md`](M5-it-handles-harder-questions.md) | 12 | 34–48 h |
| M6 — I can speak to it | [`M6-i-can-speak-to-it.md`](M6-i-can-speak-to-it.md) | 12 | 30–43 h |
| M7 — Someone else can install it | [`M7-someone-else-can-install-it.md`](M7-someone-else-can-install-it.md) | 32 | 97–141 h |
| M8 — The paid upgrade | [`M8-the-paid-upgrade.md`](M8-the-paid-upgrade.md) | 8 | 17–25 h unblocked |
| **Total** | | **176** | **514–737 h** |

**Apply the rework multiplier.** Estimates are optimistic by construction; past M1, multiply by 1.3–1.5. That gives roughly **670–1,050 hours** to the end of M7, before the two blocked decisions are answered. A plan quoting a number without a rework multiplier is a number nobody should plan against.

Ticket identifiers follow `[MILESTONE]-[EPIC]-[DOMAIN]-[###]`, with the numeric part running sequentially from 001 to 176 across the whole backlog so no identifier is ambiguous.

---

## 1. Finalized technical baseline

These are decisions, not options. Where one reverses something the documentation previously stated, that is deliberate and is recorded in `../decisions.md`.

### Topology

**Seven containers plus one native host process**, on one machine, for one user.

| Component | Kind | Why it exists |
| --------- | ---- | ------------- |
| `api` | container | The only reachable service; also serves the built frontend assets |
| `postgres` | container | Relational state, vectors and full-text in one system |
| `redis` | container | Queue only in v1 — ingestion, embedding batches, clarification and export jobs |
| `worker` | container | Background jobs; ingestion is never a request |
| `voice` | container | Transcription, voice activity detection, synthesis (arrives M6) |
| `sandbox` | container | A second PostgreSQL instance, one database per imported source, no egress route at all |
| `egress-proxy` | container | Default-deny; every service routes through it; nothing else has a route out |
| llama.cpp server | **native host process** | Generation, embeddings and reranking, with GPU access on all three platforms |

**There is no `web` container.** The frontend is built to static assets served by the API — no server, no session to protect, no search indexing to serve, so a permanent Node process on a laptop bought nothing.

**Inference is native because containerised inference silently excluded macOS.** A Linux container on Apple Silicon runs inside a virtual machine with no Metal passthrough, which would have made the accelerated profiles unreachable on the platform most target users carry. The accepted cost is that the installer supervises a process alongside a container stack, and that *"the assistant is unavailable"* has two distinct causes that must be diagnosed and reported separately.

### Platforms

**Linux, Windows and macOS from v1.** Each gets its own installer ticket because each has its own genuinely different failure modes: runtime prerequisites and virtualisation on Windows, signing and folder permissions on macOS, packaging conventions on Linux.

### Stack

| Layer | Decision |
| ----- | -------- |
| Backend | Python 3.12, pinned in the API image with `uv`, `ruff`, `mypy` and `pytest` inside it, so the host needs only Podman |
| Frontend | Next.js 16 + React 19 + Tailwind 4 + shadcn/ui, pinned as **one verified set** at scaffold, built to static assets, managed with pnpm |
| Data access | SQLAlchemy 2.0 async + Alembic + pgvector; raw invariants ride along in the creating migration |
| Database | PostgreSQL 18 with pgvector, 17 if no maintained 18 image with the extension exists at scaffold; the sandbox uses the same image |
| Streaming | Server-sent streaming for answers, retrieval step labels and ingestion progress. **WebSocket only for voice**, in M6 |
| Models | One native process serves generation, `bge-m3` embeddings and `bge-reranker-v2-m3` reranking. Whisper `small` plus Silero voice activity detection for transcription; **Kokoro-82M** for synthesis |
| Documents | **pypdfium2** for PDF — not PyMuPDF, which is AGPL and would force the project off Apache-2.0. Tesseract for OCR with orientation detection. Format libraries for Word, spreadsheets and slide decks. Locally bundled pdf.js for the viewer |
| Retrieval | Hybrid dense plus lexical, fused with reciprocal rank fusion, then a reranking pass. Structure-aware chunking |
| Operations | Host-side hardware probe at install. GitHub Actions for lint, typecheck and tests on every push; the 155-task eval gate on a self-hosted or manually dispatched runner with a cached model |

### Constraint enforcement points

Every constraint has a mechanism. A rule with no enforcement point is a wish, and the security review in M7 treats a constraint enforced only by convention as a release blocker.

| Constraint | Enforced by | Tickets |
| ---------- | ----------- | ------- |
| C1 local by default | Default-deny egress proxy; refusal counter read from the proxy, not the application; cable-unplugged release test | 010, 011, 145, 169, 176 |
| C2 SQL never trusted | `sqlglot` parsing rejecting anything but a single read, **plus** an independent read-only database role and a statement timeout | 104, 105, 106, 107, 112 |
| C3 dumps are untrusted code | Separate sandbox instance, one database per source, restricted role, no egress route, size and time caps, hostile-fixture suite | 087, 088, 089, 091 |
| C4 every claim cited | `citations` as a real table written at composition time; the permanent provenance margin; the query that proves no claim is uncited | 042, 043, 045, 079 |
| C5 abstention over invention | Threshold applied before composition; abstention as its own milestone; the 0.90 subset with a guard against a silently lowered default | 053–056, 065 |
| C6 append-only and tamper-evident | No update or delete grant; hash chain; verification pass; staged disk budget; **never called immutable** | 014, 015, 153, 155, 156 |
| C7 retrieved content is data | Delimitation plus the standing statement in versioned prompt files, extended to tool results; injection flagged in the trace | 037, 114 |
| C8 secrets in environment | Ignore rules, an example file checked against what the code reads, log redaction, credential encryption at rest | 007, 098, 152 |
| C9 bundled model licence | Every bundled model verified redistributable, commercial-use permitted and ungated; evidenced in the notices file | 144, 146, 146a, 163 |

---

## 2. Assumptions explicitly accepted

Each is labelled where it appears in the tickets. None is a silent default.

1. **Indexing in place means nominated root directories become known mounts.** The user nominates a root at add time; the container gets a route to that tree and nothing else. Safer than open filesystem access, and the only approach that works with a virtual machine in the path on Windows and macOS. **No screen specification covers path registration** — M1-ADD-ING-021 writes it against the existing add-source shape rather than inventing a new screen, and M7's installers handle the platform half.
2. **Speech-to-text stays containerised on CPU.** Whisper `small` on CPU is likely adequate for the standard profile, but it is untested. M6-PERF-TEST-136 is what answers it; if transcription is the cause of a missed budget, it becomes a second native process and the installer changes. Flagged in M6-AUDIO-DEPLOY-125.
3. **A live database connection is an authorised outbound destination, not a violation of C1.** It is the user's own database, authorised explicitly by them at connection time, limited to that destination, and counted separately in settings so the local-mode zero stays meaningful. Stated in M4-CONN-FE-096.
4. **Passage-level highlighting on scanned pages starts at page level.** The licence decision that rules out one PDF library makes coordinate mapping harder; scans highlight the page and say so. Passage-level on scans is a later story, not a defect.
5. **One table per CSV, one table per spreadsheet sheet.** Merged headers are flagged rather than resolved, because the multi-sheet and merged-cell question is genuinely open.
6. **Cross-database questions are out of scope in v1** and are refused explicitly rather than attempted.
7. **Eval results are not reproducible across machines.** The runner is one machine; model, settings and prompt version are recorded so comparisons stay honest.
8. **Signing and notarisation credentials are available for the macOS installer.** If they are not, that is a blocking issue to raise rather than a workaround to ship.

---

## 3. Delivery milestones

Each ends in something demonstrable, and each is genuinely sequential — a later milestone's tickets cannot be reached until an earlier one has shipped. The ordering is checked against the **click-path**, not the milestone number.

| # | Milestone | Ends with | Phase |
| - | --------- | --------- | ----- |
| M0 | It runs | The stack and the native process come up on a clean machine and report their state honestly | 0 |
| M1 | It answers from my documents | Add a PDF, ask, get a cited answer, click through to the highlighted page | 1 |
| M2 | It says when it doesn't know | Abstention, partial answers, conflicts, deletion, and the eval harness that keeps them honest | 1 |
| M3 | It learns my material | Clarifications raised, answered, remembered, applied, and correctable from inside an answer | 2 |
| M4 | It answers from my data | CSV, sandboxed dumps, live read-only connections, validated SQL always shown | 3 |
| M5 | It handles harder questions | Multi-step answers across documents and data, with a readable trace | 4 |
| M6 | I can speak to it | Voice in, voice out, stop control, latency inside budget | 5 |
| M7 | Someone else can install it | Three installers, offline install, backup with a tested restore, and everything a release actually needs | 6 |
| M8 | The paid upgrade | Per-conversation online AI — **two decisions blocked** | 7 |

**M2 is deliberately its own milestone.** Abstention and the failure states are normally folded into the chat work and quietly dropped when time runs short. They are the product's central claim, and they get their own demonstrable end.

**M3 comes before M4 deliberately.** Memory shapes ingestion and the data model, and the database path is where it pays off most. Building databases first means rebuilding the schema-notes path afterwards.

---

## 4. Epics by milestone

| Milestone | Epic | Code | Covers |
| --------- | ---- | ---- | ------ |
| M0 | Repository and toolchain | `FOUND` | Images, scaffolds, tests, CI, secrets, versioning |
| M0 | Stack and egress | `STACK` | Compose topology, default-deny proxy, localhost binding |
| M0 | Database groundwork | `DATA` | Migrations, raw invariants, hash-chained audit stores |
| M0 | Shell and session | `SHELL` | Local session, navigation, health |
| M0 | Native inference | `MODEL` | Provisioning, supervision, client, the two failure causes |
| M1 | Adding a source | `ADD` | Path registration, add-source, duplicates, background ingestion |
| M1 | Extraction | `EXTRACT` | PDF, Office, text, OCR, failure states |
| M1 | Indexing | `INDEX` | Chunking, embedding, full-text, supersession |
| M1 | Asking | `ASK` | Retrieval, reranking, streaming, prompts, interaction records |
| M1 | Citations | `CITE` | Citation rows, the provenance margin, the uncited-claim query |
| M1 | Source viewer | `VIEW` | In-app rendering, navigation, moved files |
| M1 | Library and first run | `LIB` | Inventory, statuses, empty states, the first ten minutes |
| M2 | Abstention | `ABSTAIN` | Threshold, copy, rendering, recording |
| M2 | Partial and conflicting | `PARTIAL` | Grounded-part answers, conflict presentation and detection |
| M2 | Failure states | `FAIL` | Degrading to search |
| M2 | Deletion | `DELETE` | Tombstones, confirmation copy, deleted citations |
| M2 | Evaluation | `EVAL` | Harness, three suites, the gate |
| M3 | Raising | `RAISE` | The three tests, ranking, the cap, evidence, memory-first checking |
| M3 | Reviewing | `REVIEW` | The clarifications screen and its states |
| M3 | Storing | `STORE` | Memory, schema notes, supersession, decisions records |
| M3 | Applying | `APPLY` | Retrieval of facts, citation of facts, re-processing |
| M3 | Correcting | `CORRECT` | Chips in an answer, the memory screen, inline clarification |
| M4 | CSV | `CSV` | Parsing, inference, the date rule, loading, review |
| M4 | Dumps | `DUMP` | Sandbox, import, caps, the calm warning, containment |
| M4 | Connections | `CONN` | Wizard, write probe, credential encryption, health |
| M4 | Schema | `SCHEMA` | Introspection, notes from clarifications, drift |
| M4 | SQL safety | `SQL` | Generation, parsing, limits, dry run, roles, recording |
| M4 | Results | `RESULT` | Rendering, disclosure, the five states |
| M5 | Tools | `TOOLS` | The registry, results as data |
| M5 | The loop | `LOOP` | Multi-step, parallel, the ceiling, step capture |
| M5 | Trace | `TRACE` | Panel, contents, interactions, threshold control, states |
| M6 | Audio | `AUDIO` | The voice service and the bidirectional channel |
| M6 | Transcription | `STT` | Transcription, turn detection, low confidence |
| M6 | Synthesis | `TTS` | Sentence streaming, text fallback |
| M6 | Voice interface | `VUI` | Composer control, stop, latency indicator, states |
| M7 | Probe | `PROBE` | Host-side detection, warn and continue |
| M7 | Packaging | `PACK` | Three installers, supervision, the repair surface |
| M7 | Offline | `OFFLINE` | Bundle, manual placement, the cable-unplugged test |
| M7 | Settings | `SET` | The six sections completed |
| M7 | Security | `SEC` | Passphrase, encryption at rest, security review |
| M7 | Logs | `LOG` | Budget, retention, export, verification |
| M7 | Backup | `BACKUP` | Backup, restore, tested restore |
| M7 | Data ownership | `DATA` | Export everything, delete, reset |
| M7 | Update delivery | `UPDATE` | **Blocked** |
| M7 | Release readiness | `QA`, `DOC`, `OPS`, `PERF` | Checklist, notices, support boundary, rollback, performance |
| M8 | Online routing | `ONLINE` | Authorisation, provider, marker, logging |
| M8 | Credits | `CREDIT` | Purchase, limits, exhaustion |

---

## 5. Full ordered ticket backlog, grouped by domain

Every ticket, in dependency order within each domain. Full text lives in the milestone files.

### Deployment and configuration

| ID | Title | Priority | Est. |
| -- | ----- | -------- | ---- |
| M0-FOUND-DEPLOY-001 | Pin Python 3.12 in the API image with the toolchain inside it | Critical | 3–4 h |
| M0-FOUND-DEPLOY-004 | Serve the built frontend assets from the API | High | 2–3 h |
| M0-FOUND-DEPLOY-006 | Continuous integration for lint, typecheck and tests | High | 2–3 h |
| M0-STACK-DEPLOY-009 | Compose stack bringing up API, database, queue and worker | Critical | 4–6 h |
| M0-MODEL-DEPLOY-018 | Provision and supervise the native inference process | Critical | 4–6 h |
| M2-EVAL-DEPLOY-067 | Run the eval gate on a capable runner | High | 3–4 h |
| M4-DUMP-DEPLOY-087 | Sandbox Postgres with a restricted role and no egress | Critical | 4–6 h |
| M6-AUDIO-DEPLOY-125 | Voice container with transcription and synthesis | Critical | 3–4 h |
| M7-PROBE-DEPLOY-137 | Host-side hardware probe and profile selection | Critical | 4–6 h |
| M7-PACK-DEPLOY-139 | Linux installer | Critical | 4–6 h |
| M7-PACK-DEPLOY-140 | Windows installer | Critical | 4–6 h |
| M7-PACK-DEPLOY-141 | macOS installer | Critical | 4–6 h |
| M7-PACK-DEPLOY-142 | Supervise the container stack and the native process together | Critical | 4–6 h |
| M7-PACK-FE-143 | A supervision surface: start, stop, repair | High | 3–4 h |
| M7-OFFLINE-DEPLOY-144 | Offline model bundle and manual model placement | Critical | 4–6 h |
| M7-UPDATE-BLOCKED-161 | Update delivery mechanism **[BLOCKED]** | High | — |

### Security and hardening

| ID | Title | Priority | Est. |
| -- | ----- | -------- | ---- |
| M0-FOUND-SEC-007 | Secrets as environment variables, example file kept current | High | 1–2 h |
| M0-STACK-SEC-010 | Default-deny egress proxy with every service routed through it | Critical | 4–6 h |
| M0-STACK-SEC-011 | Expose the refused-outbound-request count to the application | High | 2–3 h |
| M0-STACK-SEC-012 | Bind the API to localhost and prove it is unreachable | Critical | 2–3 h |
| M4-DUMP-SEC-091 | Containment test: a hostile dump destroys only its own database | Critical | 4–6 h |
| M4-CONN-SEC-097 | Write-permission probe that refuses write-capable credentials | Critical | 4–6 h |
| M4-CONN-SEC-098 | Encrypt stored credentials at rest | Critical | 3–4 h |
| M7-SEC-BE-151 | Passphrase: set, unlock, and no recovery | High | 3–4 h |
| M7-SEC-BE-152 | Encryption at rest for documents and credentials | High | 4–6 h |
| M7-SEC-TEST-166 | Security review before public release | Critical | 4–6 h |
| M8-ONLINE-SEC-169 | Per-conversation egress authorisation for one destination | Critical | 4–6 h |

### Database

| ID | Title | Priority | Est. |
| -- | ----- | -------- | ---- |
| M0-DATA-DB-013 | First migration creating the v1 schema | Critical | 4–6 h |
| M0-DATA-DB-014 | Raw invariants in the creating migration | Critical | 3–4 h |
| M1-INDEX-DB-033 | Full-text column population and index | High | 2–3 h |
| M4-SQL-DB-107 | Independent read-only role and statement timeout | Critical | 3–4 h |

### Backend and API

| ID | Title | Priority | Est. |
| -- | ----- | -------- | ---- |
| M0-FOUND-BE-002 | Scaffold the API with configuration and structured logging | Critical | 3–4 h |
| M0-SHELL-SESS-016 | Local single-user session bound to localhost | High | 3–4 h |
| M0-MODEL-BE-019 | Inference client with model names from configuration only | High | 2–3 h |
| M0-MODEL-BE-020 | Report the two distinct causes of assistant unavailability | High | 2–3 h |
| M1-ADD-BE-023 | Source and document records with content-hash duplicates | High | 2–3 h |
| M1-INDEX-BE-034 | Supersede a changed document rather than duplicating it | High | 3–4 h |
| M1-ASK-BE-037 | Answer prompt as a versioned file, retrieved content delimited | Critical | 3–4 h |
| M1-ASK-API-038 | Server-sent answer streaming with named retrieval steps | Critical | 4–6 h |
| M1-ASK-BE-040 | Generation continues when the user navigates away | High | 2–3 h |
| M1-CITE-BE-042 | Claim-level citation extraction into the citations table | Critical | 4–6 h |
| M1-VIEW-BE-049 | The moved-or-renamed file state, distinct from deleted | High | 3–4 h |
| M2-ABSTAIN-BE-054 | Abstention copy that proves the search happened | Critical | 3–4 h |
| M2-PARTIAL-BE-057 | Partial answers: answer the grounded part, name the gap | Critical | 3–4 h |
| M2-PARTIAL-BE-059 | Detect conflicting sources rather than choosing one | High | 3–4 h |
| M2-DELETE-BE-061 | Tombstoned deletion clearing content and embedding | Critical | 3–4 h |
| M3-RAISE-BE-068 | Ambiguity detection with the three tests for asking | Critical | 4–6 h |
| M3-RAISE-BE-069 | Ranking and the cap of five per source | Critical | 3–4 h |
| M3-RAISE-BE-070 | Check memory before raising any question | High | 2–3 h |
| M3-RAISE-BE-071 | Capture the evidence that makes a question answerable | High | 3–4 h |
| M3-STORE-BE-076 | Memory and schema notes with origin and supersession | Critical | 3–4 h |
| M3-APPLY-BE-079 | Cite memory facts and record fact usage | Critical | 3–4 h |
| M3-CORRECT-BE-082 | Correction path: supersede, re-process, record | High | 2–3 h |
| M4-CONN-BE-099 | Connection health and three distinguishable failures | High | 2–3 h |
| M4-SCHEMA-BE-102 | Detect stale annotations when the schema drifts | Medium | 2–3 h |
| M4-SQL-BE-103 | Schema retrieval and SQL generation | Critical | 4–6 h |
| M5-TOOLS-BE-113 | Tool registry with the five exposed tools | Critical | 3–4 h |
| M5-TOOLS-BE-114 | Tool results delimited as data, never instruction | Critical | 2–3 h |
| M5-LOOP-BE-115 | Multi-step loop with parallel calls | Critical | 4–6 h |
| M5-LOOP-BE-116 | The eight-call ceiling, with what was gathered and Continue | Critical | 3–4 h |
| M5-LOOP-BE-117 | Capture the step sequence into the trace | Critical | 3–4 h |
| M6-AUDIO-API-126 | Bidirectional audio transport, for voice only | Critical | 4–6 h |
| M6-STT-BE-127 | English transcription | Critical | 3–4 h |
| M6-STT-BE-128 | Turn detection and the silent timeout | High | 3–4 h |
| M6-TTS-BE-130 | Sentence-streamed speech synthesis | Critical | 3–4 h |
| M6-TTS-BE-131 | Fall back to text when synthesis is unavailable | High | 1–2 h |
| M7-LOG-BE-153 | Log storage budget with staged degradation | Critical | 3–4 h |
| M7-LOG-BE-154 | Interaction retention window and prune | High | 2–3 h |
| M7-LOG-BE-155 | Log export as a background job, with the chain and a verifier | High | 4–6 h |
| M7-BACKUP-BE-157 | Backup that excludes what can be regenerated | Critical | 4–6 h |
| M7-BACKUP-BE-158 | Restore, with the re-embed cost stated | Critical | 4–6 h |
| M8-ONLINE-BE-170 | Provider abstraction behind the inference client | High | 4–6 h |

### Ingestion

| ID | Title | Priority | Est. |
| -- | ----- | -------- | ---- |
| M1-ADD-ING-021 | Nominate root directories as known mounts at add time | Critical | 4–6 h |
| M1-ADD-ING-025 | Background ingestion with per-file progress surviving navigation | Critical | 4–6 h |
| M1-EXTRACT-ING-026 | PDF text-layer extraction | Critical | 3–4 h |
| M1-EXTRACT-ING-027 | Word, slide, spreadsheet, text, Markdown and HTML extraction | High | 4–6 h |
| M1-EXTRACT-ING-028 | OCR fallback with orientation detection | Critical | 4–6 h |
| M1-EXTRACT-ING-029 | Flag low-confidence OCR as needs attention | High | 2–3 h |
| M1-INDEX-ING-031 | Structure-aware chunking | Critical | 4–6 h |
| M1-INDEX-ING-032 | Embedding batches with retry and visible failure | Critical | 3–4 h |
| M3-APPLY-ING-080 | Re-process what depends on an answered clarification | Critical | 4–6 h |
| M4-DUMP-ING-088 | Import a PostgreSQL dump into a per-source sandbox database | Critical | 4–6 h |
| M4-CSV-ING-092 | Parse spreadsheets and CSVs with type and header inference | Critical | 4–6 h |
| M4-CSV-ING-093 | Never infer silently between date formats | Critical | 2–3 h |
| M4-CSV-ING-094 | Load a CSV into the sandbox as a real table | High | 3–4 h |
| M4-SCHEMA-ING-100 | Introspect and index the schema | Critical | 3–4 h |
| M4-SCHEMA-ING-101 | Schema notes from the clarification loop | Critical | 3–4 h |

### Retrieval

| ID | Title | Priority | Est. |
| -- | ----- | -------- | ---- |
| M1-ASK-RET-035 | Hybrid retrieval with reciprocal rank fusion | Critical | 4–6 h |
| M1-ASK-RET-036 | Reranking pass over the top candidates | High | 2–3 h |
| M2-ABSTAIN-RET-053 | Retrieval threshold and the abstention decision | Critical | 3–4 h |
| M3-APPLY-RET-078 | Retrieve memory and schema notes alongside document chunks | Critical | 3–4 h |

### Validation

| ID | Title | Priority | Est. |
| -- | ----- | -------- | ---- |
| M1-ADD-VAL-024 | Reject unsupported formats by name with the supported list | High | 1–2 h |
| M1-EXTRACT-VAL-030 | Extraction failures: corrupt, encrypted, password-protected | High | 3–4 h |
| M4-DUMP-VAL-089 | Size and time caps that abort and drop the sandbox | Critical | 3–4 h |
| M4-SQL-VAL-104 | Parse generated SQL and reject anything not a single read | Critical | 4–6 h |
| M4-SQL-VAL-105 | Inject a row limit and make it visible in the shown SQL | Critical | 2–3 h |
| M4-SQL-VAL-106 | Dry run before execution | High | 2–3 h |

### Frontend

| ID | Title | Priority | Est. |
| -- | ----- | -------- | ---- |
| M0-FOUND-FE-003 | Scaffold the frontend as one pinned verified set | Critical | 4–6 h |
| M0-SHELL-FE-017 | Application shell, navigation and the ready state | High | 3–4 h |
| M1-ADD-FE-022 | Add-source screen, files route, drag-and-drop anywhere | Critical | 3–4 h |
| M1-ASK-FE-039 | Ask screen: composer, conversation, streaming, step labels | Critical | 4–6 h |
| M1-CITE-FE-043 | The provenance margin with source cards and leaders | Critical | 4–6 h |
| M1-CITE-FE-044 | Hover pairing and the narrow-window inline fallback | High | 2–3 h |
| M1-VIEW-FE-046 | Source viewer: in-app PDF at the cited page, highlighted | Critical | 4–6 h |
| M1-VIEW-FE-047 | Non-PDF renderings and OCR text beside scans | High | 4–6 h |
| M1-VIEW-FE-048 | Context rail, back to the answer, citation stepping | High | 3–4 h |
| M1-LIB-FE-050 | Library list with status and needs-attention expansion | High | 4–6 h |
| M1-LIB-FE-051 | Empty states that teach rather than say "no items" | High | 3–4 h |
| M1-LIB-FE-052 | First-run sequence | Critical | 4–6 h |
| M2-ABSTAIN-FE-055 | The abstained state on Ask | Critical | 2–3 h |
| M2-PARTIAL-FE-058 | Partial rendering and conflicting-sources presentation | High | 3–4 h |
| M2-FAIL-FE-060 | Degrade to search when the assistant is unavailable | High | 3–4 h |
| M2-DELETE-FE-062 | Deletion confirmation and the deleted-source card | High | 2–3 h |
| M3-REVIEW-FE-072 | Clarifications screen as a single reviewable list | Critical | 3–4 h |
| M3-REVIEW-FE-073 | One question's anatomy with its evidence | High | 3–4 h |
| M3-REVIEW-FE-074 | Save, skip, skip-all, undo, and the specific confirmation | Critical | 3–4 h |
| M3-REVIEW-FE-075 | Clarification states: none pending, capped, re-processing | High | 2–3 h |
| M3-CORRECT-FE-081 | Memory chips in an answer, with correct and delete | Critical | 3–4 h |
| M3-MEM-FE-083 | Memory screen: list, confidence markers, usage count | High | 3–4 h |
| M3-MEM-FE-084 | Memory interactions: edit, confirm, delete, history, add | High | 4–6 h |
| M3-INLINE-FE-085 | Inline clarification when a question blocks an answer | High | 3–4 h |
| M4-CSV-FE-095 | CSV route with type and header review | High | 3–4 h |
| M4-DUMP-FE-090 | Dump route: the calm warning and the refusal with routes out | High | 3–4 h |
| M4-CONN-FE-096 | Connection wizard for a live database | Critical | 4–6 h |
| M4-RESULT-FE-109 | Render results with counts, pagination and truncation label | High | 3–4 h |
| M4-RESULT-FE-110 | SQL disclosure, collapsed by default, always available | Critical | 2–3 h |
| M4-RESULT-FE-111 | Database states: no connections, unreachable, zero rows, timeout, rejected | High | 3–4 h |
| M5-LOOP-FE-118 | Step labels for multi-step turns | High | 2–3 h |
| M5-TRACE-FE-119 | Trace panel: readable narrative over expandable detail | High | 4–6 h |
| M5-TRACE-FE-120 | Trace contents: scores, threshold, memory, SQL, flags | High | 3–4 h |
| M5-TRACE-FE-121 | Trace interactions: expand, click through, copy | Medium | 3–4 h |
| M5-TRACE-FE-122 | Threshold adjustment from an abstention trace | High | 2–3 h |
| M5-TRACE-FE-123 | Trace states, including the rotated-away trace | Medium | 2–3 h |
| M6-VUI-FE-132 | Voice control in the composer with a live level meter | High | 3–4 h |
| M6-VUI-FE-133 | Stop control, and deliberately no barge-in | High | 2–3 h |
| M6-VUI-FE-134 | Latency indicator, only once the budget is passed | Medium | 1–2 h |
| M6-VUI-FE-135 | Voice states: permission denied, non-English, abstention in full | High | 2–3 h |
| M6-STT-FE-129 | Low confidence: show the transcript and confirm | High | 2–3 h |
| M7-PROBE-FE-138 | Warn and continue below the floor and on probe failure | High | 2–3 h |
| M7-SET-FE-146 | Settings: model and speed | High | 3–4 h |
| M7-SET-FE-147 | Settings: privacy and security with the measured count | Critical | 2–3 h |
| M7-SET-FE-148 | Settings: storage | High | 3–4 h |
| M7-SET-FE-149 | Settings: about, licence, source, reporting a problem | High | 2–3 h |
| M7-SET-FE-150 | Settings: online AI, visible and disabled | Medium | 1–2 h |
| M7-LOG-FE-156 | Verification surface reporting where the chain breaks | High | 2–3 h |
| M7-DATA-FE-160 | Export everything, delete memory, reset Askwell | Critical | 3–4 h |
| M7-UPDATE-BLOCKED-162 | Update notification surface **[BLOCKED]** | Medium | — |
| M8-ONLINE-FE-171 | Conversation marker and pre-send disclosure **[partly blocked]** | Critical | 3–4 h |
| M8-CREDIT-FE-175 | Credits exhausted falls back to local and keeps working | High | 2–3 h |

### Observability and audit

| ID | Title | Priority | Est. |
| -- | ----- | -------- | ---- |
| M0-DATA-OBS-015 | Hash-chained audit stores with fail-the-action semantics | Critical | 4–6 h |
| M1-ASK-OBS-041 | Interaction records for every question and answer | Critical | 3–4 h |
| M2-ABSTAIN-OBS-056 | Record abstentions with scores and threshold stored | High | 2–3 h |
| M3-STORE-OBS-077 | Clarification answers as decisions records in one transaction | Critical | 2–3 h |
| M4-SQL-OBS-108 | Record executed and rejected SQL with reasons | High | 2–3 h |
| M8-ONLINE-OBS-172 | Online-mode logging **[BLOCKED]** | Critical | — |

### Test, evaluation and quality

| ID | Title | Priority | Est. |
| -- | ----- | -------- | ---- |
| M0-FOUND-TEST-005 | Establish the test harness and the first meaningful tests | High | 2–3 h |
| M1-CITE-TEST-045 | The query that proves no answer contains an uncited claim | Critical | 3–4 h |
| M2-EVAL-TEST-063 | Port the eval harness and make it run offline | Critical | 3–4 h |
| M2-EVAL-TEST-064 | Grounded document QA suite | Critical | 4–6 h |
| M2-EVAL-TEST-065 | Abstention subset with the 0.90 bar | Critical | 3–4 h |
| M2-EVAL-TEST-066 | Conflicting-source subset and worst-case reporting | High | 2–3 h |
| M3-EVAL-TEST-086 | Memory application eval subset | Critical | 3–4 h |
| M4-EVAL-TEST-112 | Text-to-SQL and SQL-safety eval suites | Critical | 4–6 h |
| M5-EVAL-TEST-124 | Tool selection eval suite, including parallel calls | Critical | 3–4 h |
| M6-PERF-TEST-136 | Measure voice latency against the profile budgets | Critical | 3–4 h |
| M7-OFFLINE-TEST-145 | The cable-unplugged release test | Critical | 4–6 h |
| M7-BACKUP-TEST-159 | Tested restore, every release | Critical | 3–4 h |
| M7-PERF-TEST-167 | Measure the performance budgets on a real corpus | High | 3–4 h |
| M7-QA-TEST-168 | Release readiness checklist and manual regression walkthrough | Critical | 4–6 h |
| M8-ONLINE-TEST-176 | Online-mode release test: only the authorised destination | Critical | 4–6 h |

### Documentation and operations

| ID | Title | Priority | Est. |
| -- | ----- | -------- | ---- |
| M0-FOUND-DOC-008 | Version, changelog and release-note discipline | Medium | 1–2 h |
| M7-DOC-DOC-163 | Licence and notices covering bundled model weights | Critical | 3–4 h |
| M7-DOC-DOC-164 | Stated support boundary and issue triage | Critical | 2–3 h |
| M7-OPS-DOC-165 | Rollback, incident and crash-report readiness | High | 3–4 h |

### Blocked — do not start

| ID | Title | Blocked on |
| -- | ----- | ---------- |
| M7-UPDATE-BLOCKED-161 | Update delivery mechanism | How a free local install learns a new version exists without phoning home by default |
| M7-UPDATE-BLOCKED-162 | Update notification surface | The same decision, and 161 |
| M8-ONLINE-OBS-172 | Online-mode logging | What online mode transmits |
| M8-CREDIT-BLOCKED-173 | Credit purchase | Credit pricing — rate, minimum, margin |
| M8-CREDIT-BLOCKED-174 | Spending limit and balance | The same decision, and 173 |
| M8-ONLINE-FE-171 (disclosure half) | Pre-send payload wording | What online mode transmits |

---

## 6. Non-functional requirement coverage map

Non-functional work is mandatory here, not an optional extra. Every row names the tickets that carry it.

| Requirement | How it is met | Tickets |
| ----------- | ------------- | ------- |
| **Privacy — no outbound calls in local mode** | Default-deny proxy, refusal counter read from the proxy, cable-unplugged release test with an independent network capture, per-conversation authorisation for online | 010, 011, 145, 147, 169, 176 |
| **Privacy — no telemetry** | There is none, and none may be added. Every ticket's analytics field is a local counter or nothing. No consent dialogue exists because there is nothing to consent to | Every ticket; 052 explicitly |
| **Security — untrusted input** | Dump sandbox with a restricted role, size and time caps, hostile-fixture containment suite; SQL parsing plus an independent read-only role; retrieved content and tool output delimited as data | 087–091, 104–107, 037, 114 |
| **Security — secrets and data at rest** | Environment-only secrets with a checked example file and log redaction; credential encryption from the moment credentials exist; optional passphrase with no recovery; corpus encryption with honest documentation of what remains readable | 007, 098, 151, 152 |
| **Security — review** | A structured review against each constraint's enforcement point before public release; a constraint enforced only by convention is a release blocker | 166 |
| **Reliability — failure states** | Degrade to search when the assistant is down; the two distinct unavailability causes; staged disk degradation with ingestion refused before asking; nothing ever silently dropped | 020, 060, 143, 153, 030, 032 |
| **Reliability — data safety** | Tombstoned deletion with content and embedding cleared; supersession distinct from deletion; backup with a **tested restore** every release; original files never touched, stated repeatedly | 061, 034, 157, 158, 159, 160 |
| **Auditability** | Hash-chained stores with no update or delete grant; fail-the-action for decisions and interactions, fail-open for traces; verification naming the break; export with a standalone verifier; **never called immutable** | 014, 015, 041, 077, 108, 155, 156 |
| **Correctness — grounding** | Citations as real rows written at composition time; the permanent provenance margin; the uncited-claim query; abstention as its own milestone with a 0.90 bar and a guard against a lowered threshold | 042, 043, 045, 053–056, 065, 079 |
| **Correctness — evaluation** | Seven suites totalling 155 tasks, each run three times with worst-case reported beside mean; the gate on a capable runner; a prompt change without a run is blocked | 063–067, 086, 112, 124 |
| **Performance** | Answer budgets measured on a realistic corpus per profile with a per-stage breakdown; voice latency measured from end of speech; bounded ingestion concurrency so the laptop stays usable | 167, 136, 025 |
| **Observability** | Structured logging with no unstructured printing; component-level health; the trace with stored scores and timings; local-only counters computed on demand | 002, 017, 117, 119–123 |
| **Maintainability** | Strict typing on both sides; prompts as versioned files never inlined; model names only in configuration; one version value read by both packages; migrations never hand-edited | 001, 003, 008, 019, 037, 013 |
| **Usability — every state ships** | Every ticket's UI-states field cites the relevant screen specification and the states document. Empty, loading, partial, denied, degraded and failed states have their own tickets rather than being folded into a happy path | 051, 060, 075, 111, 123, 135 |
| **Accessibility and layout** | Status conveyed by word plus shape, never colour alone; keyboard parity for citation pairing; wide and narrow layouts both keep every source card | 050, 044 |
| **Supportability** | Stated support boundary before release; issue templates requesting version, platform, profile and trace; copyable trace; rollback rehearsed; local-only crash reports | 164, 121, 165, 149 |
| **Licence compliance** | Notices covering every dependency **and every bundled model weight**; a check that fails the release on a disallowed licence; the PDF library chosen to preserve the project's licence | 163, 026 |
| **Recoverability** | Backup excluding regenerable data with the re-embed cost stated; restore with credential re-entry and missing-original handling; a tested restore as a release gate | 157, 158, 159 |

---

## 7. Sequencing notes

### Why this order

The sequence runs: environment and foundation → repository setup → shared foundations → database groundwork → local session → core backend flows → core APIs → core frontend → ingestion → retrieval and answering → clarification and memory → database answering → the agent loop → voice → settings and operational tooling → validation and edge cases → observability → hardening → testing readiness → packaging → staging verification → release readiness → documentation.

**A ticket is only correctly placed if everything needed to reach it has already shipped.** That is checked against the click-path, not the milestone label. The reason M1-LIB-FE-052 (first run) sits at the end of M1 rather than the start is that a first-run sequence which cannot deliver a cited answer is not a first run; it needs the whole answer path behind it.

### The hard blockers

- **M0-DATA-DB-013 and 014 block everything.** The schema and its invariants land together in one migration because a window in which an invariant is unenforced is a window in which bad rows are written, and fixing that later means a migration on a user's own machine.
- **M0-STACK-SEC-010 blocks the release story, not the build.** The proxy can be added late in principle; it is early because retrofitting egress control after services exist means auditing every call path instead of one network configuration.
- **M1-CITE-BE-042 must follow M1-ASK-FE-039 immediately.** M1-ASK-FE-039 deliberately ships an ungrounded answer path and says so. That is a temporary state that must not reach a user, and the two citation tickets follow directly.
- **M2 blocks M3.** Abstention has to exist before clarifications, or a raised question about a gap is indistinguishable from a hallucination about it.
- **M3 blocks M4.** Schema notes come from the clarification loop; building the database path first means building the notes path twice.
- **M4 blocks M5.** The tool loop needs a database query tool worth calling.
- **M7-BACKUP-BE-158 blocks M7-BACKUP-TEST-159, which blocks release.** An untested restore is a backup that does not exist.

### What can run in parallel

- M0-FOUND-FE-003 (frontend scaffold) is independent of the whole backend chain and can run alongside it.
- Within M1, extraction (026–030) and the answer path (035–041) are independent until indexing joins them; two people could split there.
- Within M4, the dump epic (087–091) and the connection epic (096–099) are independent of each other and converge at schema introspection.
- The eval suites (064, 065, 066, 086, 112, 124) each attach to their feature and can be written alongside it rather than batched at the end.
- The three installers (139, 140, 141) share a design but are independently testable, though each needs its own machine.
- Documentation tickets (008, 163, 164, 165) can run at any point after the thing they document exists.

### What must be complete before each gate

**Before quality assurance can begin on a milestone:** every ticket in that milestone, plus its eval suite where it has one. A milestone with an unrun suite cannot be accepted, because acceptance is a manual walkthrough plus a measured score, not a green unit test run.

**Before staging verification (the pre-release cold-machine run):** M7-PACK-DEPLOY-139 through 142, M7-OFFLINE-DEPLOY-144, and M7-BACKUP-BE-158. Without an installer there is nothing to verify on a clean machine, and a verification that skips the installer verifies the wrong thing.

**Before release:** all seven eval categories at their bars with worst-case reported; the cable-unplugged test passed with an independent capture; the tested restore passed; the security review complete with findings fixed or explicitly accepted; the performance budgets measured; the notices file complete including model weights; the support boundary published; the version and changelog correct; and the full manual regression walkthrough completed on at least one platform per supported family, with the coverage recorded.

**A failure at any of those blocks the release.** A known issue carried into a release is recorded with its reasoning and its follow-up, never silently.

---

## 8. Release readiness notes

### The definition of done

**Acceptance is a manual walkthrough from a cold start, not a green test suite.** Lint, typecheck and tests passing means the code is well-formed, not that it does anything. Every ticket in this backlog carries a cold-start walkthrough for exactly that reason, and every one ends with a known-gaps list so a deliberate omission is not filed as a defect.

### The release checklist, in one place

| Gate | Pass condition | Ticket |
| ---- | -------------- | ------ |
| Grounded document QA | ≥ 0.85 mean, ≥ 0.70 worst-of-three | 064 |
| Abstention | ≥ 0.90 — **hallucination here is disqualifying** | 065 |
| Conflicting sources | ≥ 0.75 | 066 |
| Memory application | ≥ 0.85 | 086 |
| Text-to-SQL, execution-matched | ≥ 0.80 mean | 112 |
| SQL safety | **1.00, no exceptions** | 112 |
| Tool selection including parallel | ≥ 0.85 | 124 |
| Network calls in local mode | **0**, with the cable unplugged and an independent capture | 145 |
| Backup restored onto a clean machine | Pass, every release | 159 |
| Security review | Every constraint has a verified mechanical enforcement point | 166 |
| Answer latency | Median under 20 s, ninety-fifth under 60 s on standard | 167 |
| Voice latency | ≤ 3.5 s accelerated, ≤ 8 s standard, from end of speech | 136 |
| Licence notices | Complete, including every bundled model weight | 163 |
| Support boundary | Published and reachable from the product | 164 |
| Manual regression walkthrough | Completed from a cold install, coverage recorded | 168 |

### What is deliberately not ready at v1

Stated so it is not discovered as a surprise.

- **Update delivery does not exist.** Users learn about a new version by looking. This is a blocked decision, and M7-OPS-DOC-165 names the incident-response limitation it creates rather than glossing over it.
- **Prompt injection is mitigated, not solved.** Retrieved content is delimited, the standing statement is in the prompt, and instruction-like content is flagged in the trace. The residual risk is documented honestly, because overclaiming here would be the same error the design warns about elsewhere.
- **The abstention band and the retention targets are reasoned, not measured**, and there is no telemetry to measure them with. That is an accepted handicap, carried by conservative defaults instead.
- **Passage-level highlighting on scanned pages** starts at page level.
- **Cross-database questions, multi-sheet spreadsheet semantics, folder watching, memory import and export, bulk clarification patterns and result-set export** are all out of v1 and are named as known gaps in the tickets they touch.
- **The eval suites are small samples over single fixtures.** Bars are set high to compensate, and that is stated rather than implied.

### Support readiness

Free and open sets a support expectation a single maintainer cannot meet. The boundary, the issue templates and the triage convention exist **before** the first release, not after it — that is M7-DOC-DOC-164, and it is Critical for that reason rather than because it is difficult.
