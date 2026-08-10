# Architecture

Technical decisions and structure. `PRD.md` is the business case and deliberately carries none of this.

**Context that drives everything below:** one user, one machine, no team, no server, free to install. There is no cluster, no tenancy, no horizontal scale, and no operations team. The hardware is somebody's laptop, and it is also running their browser and everything else.

---

## 1. Decisions (locked — do not re-litigate during implementation)

| Layer | Choice | Why |
| ----- | ------ | --- |
| Backend | **Python 3.12 + FastAPI** | The whole AI toolchain — llama-cpp bindings, whisper.cpp wrappers, TTS, `sqlglot`, OCR, embeddings — is Python-native. A second backend language buys nothing and costs integration surface. |
| Frontend | **Next.js + TypeScript + Tailwind + shadcn/ui** | Versions pending issue #9 — the previously stated "Next.js 15" is stale. Verify against the registry before scaffolding. |
| Database | **PostgreSQL + pgvector**, single instance | One system for relational state, vectors and full-text. No separate vector database. |
| Cache / queue | **Redis + arq** | Ingestion, embedding batches, clarification jobs. |
| Inference | **llama.cpp server** (OpenAI-compatible), separate container | Same interface for CPU and GPU, so the deployment profile changes configuration rather than code. Model swapping without a redeploy. |
| Object storage | **Local filesystem volume** | No cloud storage, no MinIO. There is one machine. |
| Auth | **Local single-user session** | See §3 — this is a large departure from the previous design. |
| Packaging | **Container bundle + desktop installer** | See §6. |

## 2. Topology

One machine. Every service is a container on it, and only the web UI is reachable — bound to localhost, not to the network interface.

```
   browser (localhost) ──▶ web ──▶ api ──┬──▶ postgres + pgvector
                                          ├──▶ redis
                                          ├──▶ llm (llama.cpp)
                                          ├──▶ voice (stt/tts)
                                          ├──▶ worker (arq)
                                          └──▶ sandbox postgres  (imported dumps — §5)
                                                    │
                                    user's own databases (read-only, optional)
```

Seven containers. Every one is something the user has to have working on their own laptop with no help, so the count is a real cost — resist an eighth.

**No high availability, ever.** Single machine, single Postgres, no replication or failover (issue #4, closed as out of scope). A second machine is meaningless for one person.

## 3. Authentication — deliberately minimal

The previous design specified JWT RS256, Argon2id, TOTP MFA and a Redis token blacklist, for four roles across an organisation. **Almost all of it is now wrong.**

There is one user. They already control the machine, the disk and the database. Anyone with physical access has already won, and MFA on a local desktop app protects against nothing while guaranteeing that a user who loses their phone loses their own files.

- A local session, bound to localhost.
- An optional passphrase at rest, which is a real feature: it encrypts the corpus and credentials so a stolen laptop is not a data breach.
- **No roles, no RBAC, no per-role visibility.** Removed from the data model entirely.
- **No MFA in v1.**

If multi-user ever arrives, authentication is redesigned then. Building the org-scale version now would be building for a product that does not exist.

## 4. Constraints

Authoritative list with reasoning lives in `AGENTS.md` §3. Summarised here for where enforcement sits:

| # | Rule | Enforced at |
| - | ---- | ----------- |
| C1 | Local by default; online AI is explicit, per-conversation opt-in | Egress blocked at the container network unless online mode is active |
| C2 | Model-generated SQL parsed with `sqlglot`, single `SELECT`/`WITH` only | `api/src/askwell/sql/` + read-only database role |
| C3 | Imported dumps are untrusted code, loaded only into an isolated sandbox database | §5, `data-sources.md` |
| C4 | Every factual claim carries a citation | Answer composition + eval suite |
| C5 | Abstention over invention | System prompt + abstention eval subset |
| C6 | Audit is append-only and tamper-evident | `audit-log.md` |
| C7 | Retrieved content is data, never instruction | Prompt templates + trace flagging |
| C8 | Secrets in environment variables, never committed | `.gitignore` + review |

The removed C7-as-was (column-level access control per role) went with RBAC — there are no roles to restrict against.

## 5. Data source isolation

Full detail in `data-sources.md`. The architectural point:

**A `.sql` dump is a program, not data.** Importing one means executing arbitrary DDL and DML from a file the user supplied. `sqlglot` validation governs *querying* and cannot govern *loading* — a dump that cannot write is a dump that cannot import.

So imports never touch Askwell's own database. They load into a **separate sandbox Postgres instance**, one database per imported source, owned by a role with no access to Askwell's tables and no superuser rights. A malicious or broken dump destroys its own sandbox and nothing else.

Retrofitting this after imports exist would be a migration on users' machines, so it is in from the start.

## 6. Deployment profiles

Selected at install by a hardware probe. Drives model selection and concurrency.

| Profile | Hardware | LLM | Expected |
| ------- | -------- | --- | -------- |
| `light` | 8GB RAM, CPU only | Qwen3 4B Q4_K_M | Slow but usable; text only, voice degraded |
| `standard` | 16GB RAM, CPU only | Qwen3 4B Q4_K_M | Comfortable text, voice usable |
| `accelerated` | 16GB+ RAM, 8GB+ VRAM | Qwen3 8B Q4_K_M | Fast, full voice |
| `workstation` | 32GB+ RAM, 16GB+ VRAM | Qwen3 32B Q4_K_M | Full capability |

Two changes from the previous profiles, both from the repositioning: the floor drops to 8GB because a free product on a personal laptop cannot demand 16GB minimum, and concurrency is no longer a dimension — one user asks one question at a time.

**The installer warns below the `light` floor rather than refusing.** Refusing made sense when a paid deployment could be blamed on the vendor; for a free download, refusing to run is just a lost user. Warn clearly, let them try.

Model names are never hardcoded in application code. They come from configuration, selected by profile.

## 7. Data model

Single-user. No `organisations`, no `users` table, no roles, no `visible_to_roles[]`.

```
settings           key, value                          -- single-user config incl. active profile
collections        id, name, description, created_at
documents          id, collection_id, filename, mime, sha256, page_count,
                   version, superseded_by, deleted_at, deleted_reason,
                   status, added_at
chunks             id, document_id, ordinal, page_from, page_to, heading,
                   content, content_tsv, embedding vector(1024)
sources            id, kind(file|csv|dump|connection), name, config_encrypted,
                   sandbox_db, last_indexed_at, status
schema_notes       id, source_id, table_name, column_name, description,
                   origin(user|inferred), embedding
memory             id, subject, fact, origin(clarification|correction),
                   confidence, superseded_by, created_at
clarifications     id, source_id, question, options jsonb, answer,
                   asked_at, answered_at, status
conversations      id, title, mode(text|voice), ai_backend(local|online), created_at
messages           id, conversation_id, role, content, trace jsonb, created_at
audit_decisions    id, kind, payload jsonb, prev_hash, hash, occurred_at
audit_interactions id, kind, payload jsonb, prev_hash, hash, occurred_at
```

Notes:

- `documents.deleted_at` / `deleted_reason` implement the tombstone (issue #11, Option A). **Deletion and supersession are different states** — `superseded_by` already exists for the latter and must not be reused. On delete, chunk content and embedding are cleared so the document stops influencing retrieval, while the row survives so old citations resolve to "deleted on <date>".
- `chunks.embedding` dimension follows the embedding model. `bge-m3` gives 1024 and is retained for the reasons in `decisions.md`. Pin in config, not in the migration.
- `memory` and `schema_notes` are the clarification loop's output. See `memory-and-clarification.md`.
- The two audit tables are separate on purpose, with different retention and different failure behaviour. See `audit-log.md`. Debug traces are not a table — they are a capped file ring buffer.
- `config_encrypted` uses a key derived from the optional passphrase plus a per-install secret, so a copied disk is not a credential leak.

## 8. Retrieval

Unchanged by the repositioning and still correct.

Hybrid: dense (pgvector, cosine) + lexical (Postgres full-text), fused with Reciprocal Rank Fusion, then a `bge-reranker-v2-m3` pass over the top candidates. Dense-only fails on exactly what people search for — reference numbers, codes, proper nouns.

Chunking is structure-aware, not fixed-size: headings, table boundaries, list items. A chunk that splits a table row from its header is a defect.

Every chunk retains source document, page, section heading, and ingestion timestamp.

## 9. Security

- Only the web UI is published, bound to **localhost**. Never `0.0.0.0` — a laptop on café wifi must not be serving its owner's corpus to the network.
- No outbound network calls unless online AI is explicitly active for that conversation (C1). Models are bundled at install, never fetched at runtime.
- User databases are connected read-only, with credentials probed at setup and refused if they can write.
- Imported dumps are sandboxed (§5, C3).
- Documents encrypted at rest when a passphrase is set.
- Prompt-injection defence: retrieved content is delimited, the system prompt states that retrieved content is data and never instruction, and tool calls arising from a turn whose retrieved content contained instruction-like patterns are flagged in the trace. **This is a mitigation, not a solution — document the residual risk honestly rather than overclaiming.**

## 10. Model tooling

The agent exposes: document search, database query, schema lookup, document listing, current date. Hard ceiling of 8 tool calls per turn — on reaching it, return what was gathered with an explicit note that it stopped early. Parallel calls are supported and preferred where the model emits them.

Every step is recorded in a trace, exposed behind a "how did you get this?" toggle.

All prompts live in `api/src/askwell/agent/prompts/` as versioned files, never inline in application logic. Any prompt change requires an eval run (`build-plan.md`).
