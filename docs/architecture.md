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

Single-user. No `organisations`, no `users`, no roles, no `visible_to_roles[]`.

Revised 2026-08-10 after specifying the screens (`ux/`). Designing screens before schema is deliberate, and it found four things this model could not store — issue #20 plus citations. They are folded in below and marked **new**.

```
settings           key, value                              -- profile, log budget, retention,
                                                              threshold, passphrase state

sources            id, kind(file|csv|dump|connection), name,
                   root_path, config_encrypted, sandbox_db,
                   status(indexing|ready|attention|deleted), last_error,
                   last_indexed_at, added_at

documents          id, source_id, filename, path, mime, sha256, page_count,
                   version, superseded_by, deleted_at, deleted_reason,
                   status, ocr_confidence, missing_since, added_at        -- path/missing_since NEW

chunks             id, document_id, ordinal, page_from, page_to, heading,
                   content, content_tsv, embedding vector(1024)

schema_notes       id, source_id, table_name, column_name, description,
                   origin(user|inferred), confidence, superseded_by, embedding

memory             id, subject, fact, origin(clarification|correction|manual),
                   confidence, superseded_by, created_at

clarifications     id, source_id, subject, question, options jsonb, evidence jsonb,
                   rank, answer, status(pending|answered|skipped|dismissed),
                   asked_at, answered_at                                   -- rank/evidence NEW

conversations      id, title, mode(text|voice), ai_backend(local|online), created_at
messages           id, conversation_id, role, content, trace jsonb, created_at

citations          id, message_id, chunk_id, claim_ordinal, quoted_span     -- NEW TABLE
fact_usage         id, message_id, fact_kind(memory|schema_note), fact_id   -- NEW TABLE

audit_decisions    id, kind, payload jsonb, prev_hash, hash, occurred_at
audit_interactions id, kind, payload jsonb, prev_hash, hash, occurred_at
```

### What the screens changed

**`documents.path` and `missing_since`** (#20). Askwell indexes files **in place** rather than copying them, so a moved or renamed file is not an edge case — it is the normal consequence of that choice. Without the original path there is no way to distinguish moved from deleted, and `ux/source-viewer.md` §4 requires that distinction because treating a moved file as deleted is both wrong and alarming.

**`citations` as a real table, not a field in `trace` jsonb.** C4 says every factual claim carries a citation. A constraint that cannot be queried cannot be enforced or measured — with citations buried in a JSON blob, "did any answer contain an uncited claim?" is unanswerable, and `success-metrics.md` §2 makes exactly that a tracked counter-metric at 100%. It also gives `ux/source-viewer.md` its next/previous-citation navigation without parsing JSON.

**`fact_usage`** (#20). Feeds the "used in N answers" count that makes `ux/memory.md` worth opening — a wrong belief used once is a nuisance, used in forty answers it has been corrupting results for weeks. A counter on `memory` would have been cheaper and would not survive a deletion or answer a "which answers used this?" question, so it is a join table.

**`clarifications.rank` and `evidence`**. The cap is 5 per source with a documented ranking (`memory-and-clarification.md` §8), so the rank has to be stored to know which questions made the cut and which were inferred instead. `evidence` holds the value distribution shown beside each question — the thing that makes it answerable in seconds rather than an exam (`ux/clarifications.md` §3).

**`collections` removed.** `ux/library.md` §6 concluded a flat list is right until someone has enough sources to need grouping, and documents now hang off `sources` directly. Grouping can be added later without moving data; a table nobody uses cannot.

**`documents.ocr_confidence`**, so a poor scan is flagged in the library, surfaced in the source viewer beside the image, and can raise a clarification.

**`sources.status` and `last_error`**, so `ux/library.md`'s single "needs attention" status can expand to a specific cause and a specific fix.

### 7.1 The shape of `messages.trace`

Left unspecified, this becomes a dumping ground that every screen parses differently. It holds the **step sequence** — what `ux/trace.md` renders — and nothing that belongs in a real table.

```jsonc
{
  "steps": [
    { "kind": "retrieve", "ms": 340, "query": "…",
      "threshold": 0.65,                    // in force at the time, not recomputed
      "hits": [ { "chunk_id": "…", "score": 0.81 } ] },
    { "kind": "schema",   "ms": 40,  "source_id": "…" },
    { "kind": "sql",      "ms": 240, "generated": "SELECT …",
      "validated": true, "rejection_reason": null,
      "limit_injected": 1000, "rows": 7 },
    { "kind": "compose",  "ms": 8200, "claims": 3 }
  ],
  "backend": { "mode": "local", "model": "qwen3-8b-q4km" },
  "stopped_early": false,
  "injection_flagged": false
}
```

**Scores and the threshold are stored, never recomputed.** The abstention trace is the most useful trace there is, and its value is showing the near-miss — "the right passage scored 0.61 under a 0.65 threshold". Recomputing later gives a different number after any model or threshold change, which makes the explanation wrong precisely when someone is trying to understand an old answer.

**Rejected SQL is stored with its reason.** It is the signal that a prompt change has degraded generation, and it is invisible unless recorded (`audit-log.md` §7).

Traces rotate — they are a capped file ring buffer, and `messages.trace` is trimmed with them. Citations and fact usage are in real tables and **do not rotate**, so an old answer keeps its sources long after its debugging detail is gone.

### Standing notes

- **Deletion and supersession are different states.** `superseded_by` is for versions; `deleted_at` is the tombstone (#11). Never reuse one for the other. On delete, chunk content and embedding are cleared so the document stops influencing retrieval, while the row survives so old citations resolve to "deleted on <date>".
- `chunks.embedding` dimension follows the embedding model — `bge-m3` gives 1024. Pin in config, not in the migration.
- User-supplied `schema_notes` and `memory` outrank inferred ones and are never silently overwritten. Correction supersedes; it does not update in place.
- The two audit tables are separate on purpose, with different retention and different write-failure behaviour (`audit-log.md`). Debug traces are not a table.
- `config_encrypted` uses a key derived from the optional passphrase plus a per-install secret, so a copied disk is not a credential leak.

### Constraints the ORM will not express

Add as raw SQL **in the same migration that creates the tables**, or there is a window where the invariant is unenforced:

- No `UPDATE`/`DELETE` grant on either audit table for the application role (C6).
- Partial unique index: one live version per `(source_id, sha256)` where `deleted_at IS NULL AND superseded_by IS NULL`.
- `CHECK`: a chunk with cleared content has a null embedding — a tombstoned document must not keep influencing retrieval.
- `CHECK`: `clarifications.answer` is non-null when `status = 'answered'`.
- Foreign key from `citations.chunk_id` is **not** cascade-delete. A deleted document's chunk row survives precisely so the citation resolves.

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
