# Architecture

Technical decisions and structure. `PRD.md` is the business case and deliberately carries none of this.

**Context that drives everything below:** one user, one machine, no team, no server, free to install. There is no cluster, no tenancy, no horizontal scale, and no operations team. The hardware is somebody's laptop, and it is also running their browser and everything else.

---

## 1. Decisions (locked — do not re-litigate during implementation)

| Layer | Choice | Why |
| ----- | ------ | --- |
| Backend | **Python 3.12 + FastAPI** | The whole AI toolchain — llama-cpp bindings, whisper.cpp wrappers, TTS, `sqlglot`, OCR, embeddings — is Python-native. A second backend language buys nothing and costs integration surface. |
| Frontend | **Next.js 16 + React 19 + TypeScript + Tailwind 4 + shadcn/ui**, built to **static assets served by the API container** | Pinned as one verified set at scaffold — shadcn/ui tracks a React and Tailwind pairing, not a version range. Built rather than served: there is no server, no session to protect and no SEO, so a permanent Node process on the user's laptop buys nothing. |
| Database | **PostgreSQL + pgvector**, single instance | One system for relational state, vectors and full-text. No separate vector database. |
| Cache / queue | **Redis + arq** | Ingestion, embedding batches, clarification jobs. |
| Inference | **llama.cpp server** (OpenAI-compatible), **native host process**, not a container | GPU acceleration is the reason. A Linux container on Apple Silicon runs inside a VM with no Metal passthrough, so containerised inference would make the accelerated profiles unreachable on the platform most target users carry. Also serves embeddings and the reranker. |
| Object storage | **Local filesystem volume** | No cloud storage, no MinIO. There is one machine. |
| Auth | **Local single-user session** | See §3 — this is a large departure from the previous design. |
| Data access | **SQLAlchemy 2.0 async + Alembic + pgvector** | The only mature option that handles the vector column, autogenerates migrations, and lets the raw invariants ride along in the creating migration. |
| Database | **PostgreSQL 18 + pgvector** (17 if a maintained 18 image is not available at scaffold) | Sandbox uses the same image — one thing to bundle, update and learn. |
| Streaming | **Server-sent streaming** for answers, step labels and ingestion progress; **WebSocket only for voice** | One-way streaming reconnects on its own and covers everything up to Phase 5. A bidirectional channel in Phase 0 is complexity carried for five phases before anything needs it. |
| Egress | **Default-deny egress proxy container** | See §5.1. Every service routes through it. |
| Package manager | **pnpm** | Lockfile determinism and disk behaviour on a laptop. |
| Packaging | **Tauri desktop shell + container bundle**, distributed **unsigned** with published checksums | Rust shell around the system webview, ~10 MB against Electron's ~150. Chosen for the **native file picker**: Askwell indexes in place, so nominating root directories and relocating a moved file are core flows and both are poor in a browser tab. It does not remove the container stack. Signing is deferred on cost — see `installing.md`. |
| Web search | **`ddgs`** (MIT, keyless) behind an interface, called only on explicit request | No key, no account, no extra container. Per question, never per conversation. See §5.2. |

## 2. Topology

One machine. A **Tauri desktop shell** owns the window and the native file dialogs; most services are containers; **inference runs natively on the host** so it can reach the GPU. Only the API is reachable, bound to localhost, never to the network interface.

```
   Tauri shell (window, native file dialogs)
        │  localhost only
        ▼
   api (FastAPI, serves the built web assets)
                             │
        ┌────────────┬───────┼─────────┬──────────────┐
        │            │       │         │              │
   postgres      redis    voice     worker      egress-proxy ──▶ online AI (per conversation)
   +pgvector             stt/tts    (arq)       default-deny    └─▶ web search (per question)
        │
   sandbox postgres  (imported dumps, restricted role, no egress)

   llama.cpp server  ── native host process, GPU-capable, serves
                        generation + embeddings + reranking
```

**Seven containers plus one native process.** `api`, `postgres`, `redis`, `voice`, `worker`, `sandbox`, `egress-proxy`. The web container is gone (assets are built and served by `api`) and inference left the container set to reach the GPU.

The count went down by one despite adding the egress proxy. Every container is still something a non-technical user must have working unaided, so the rule stands: **resist an eighth, and if one is added, say here why it earned its place.**

### 2.1 Platform support

**Linux, Windows and macOS from v1.** Native inference is what makes that possible — the alternative, containerised inference everywhere, would have left the `accelerated` and `workstation` profiles unreachable on Apple Silicon, where a Linux container runs inside a VM with no Metal passthrough.

The cost is accepted deliberately: the installer manages a native process alongside a container stack, and *"the assistant is unavailable"* now has two distinct causes to diagnose and report separately.

**Speech-to-text stays containerised, on CPU.** Whisper `small` is the smallest useful model in the line and the latency budget it must meet is 8s to first audio on `standard`, which is a CPU-only profile by definition — so the profile that constrains the design cannot use a GPU anyway. Moving STT native would buy speed only on profiles that already have headroom, at the cost of a second native process for the installer to supervise on three platforms.

Revisit if the `standard` profile misses its budget in Phase 5 measurement. That is the trigger; nothing before it.

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

## 5. Egress control — how C1 is actually enforced

C1 is the reason the product can exist for its users, so it is enforced structurally rather than by convention.

**Every container routes outbound traffic through a default-deny egress proxy.** Nothing else has a route out. In local mode the proxy permits nothing and counts the requests it refused — which is what makes the live outbound-request count in `ux/settings.md` §4 a *measured* zero rather than an assertion the application makes about itself.

**Two paths may be opened, both narrowly and both on request.**

*Online AI* authorises exactly one destination, for one conversation's traffic.

*Web search* authorises the search provider for **one question**. It closes immediately afterwards. The proxy is what makes "per question" enforceable rather than an intention in application code — and it is what lets the settings screen keep showing a real count of what was refused.

Neither is sticky, and the proxy is the thing that guarantees it.

This costs a container on someone's laptop, which the topology rule otherwise resists. It earns its place because the alternatives make the product's central claim something the user has to take on trust:

- **Container network policy alone** leaves nothing in the path to produce the count, and makes per-conversation authorisation coarse.
- **Application-level enforcement** is defeated by one dependency making an unexpected call — which is the realistic threat, not deliberate code.

The sandbox Postgres has no route to the proxy at all (C3).

**One container is outside this, and it is named rather than glossed.** The inference bridge runs with host networking, because inference is a native process and SELinux refuses a `container_t` process connecting to a socket owned by an `unconfined_t` one. It can therefore reach the internet, and no network rule stops it — what stops it is that its entire program connects to `127.0.0.1` and nothing else, which is a guarantee you get by reading fifty lines. Every service that touches the user's material stays internal. See `docs/decisions.md`.

### 5.0 Reachability, and how it is checked

The API publishes to `127.0.0.1` and no other service publishes at all. `"8000:8000"` and `"127.0.0.1:8000:8000"` differ by nine characters and produce the same working product on the developer's machine — the first one puts the user's entire corpus on whatever network they are on. Nothing about that difference is visible from inside Askwell, which is why `scripts/verify-localhost-binding.sh` checks from outside it and is part of the release checklist.

It checks three things, and the order is deliberate:

1. **What the port is bound to**, read from `ss`. This is what decides.
2. **What each container publishes**, distinguishing a published mapping (`127.0.0.1:8000->8000/tcp`) from an `EXPOSE` in the image (`5432/tcp`), which has no host binding at all.
3. **Whether the machine answers on its own addresses from another network namespace.**

The third is corroboration rather than the primary check, and that ordering was earned. With the API deliberately bound to every interface, the namespace probe found it reachable on this machine's Tailscale address and **refused on its LAN address** — whether a rootless container can route to a given host address depends on the container network, the host firewall and the interface. A check relying on that probe alone would have passed a machine with no Tailscale.

### 5.1 How it is built, and how a destination would be authorised

Implemented in M0-STACK-SEC-010. Two halves, and both are needed:

**The network makes bypassing impossible.** Every service except the proxy sits on a Compose network declared `internal`, which has no route off the machine. A container that ignores `HTTP_PROXY` does not find another way out — it finds nothing. That is an absence of routing rather than a rule that could be relaxed by accident, and it is why the proxy being *down* does not open a route: verified by stopping it and watching a direct connection to `1.1.1.1` return `Network is unreachable` and a DNS lookup fail.

**The proxy makes attempts visible.** Anything that respects the proxy variables is refused with an explanation and logged with its destination and the service that tried — resolved to a container name, because "something on 10.89.2.6" sends whoever reads it to work out what that address was on a machine where it will be something else tomorrow. Anything that ignores them is refused by the network, silently. Both are refusals; only the first is diagnosable, and a dependency phoning home is exactly the thing worth seeing.

**The proxy never forwards.** In local mode there are no allowed destinations, so it is not a proxy configured strictly — it is a service whose entire job is to refuse and say what it refused. There is no allowlist to misconfigure, and a test asserts that no such thing has been added.

**A liveness probe is not an egress attempt.** Askwell's own health surface checks the proxy by opening a connection and closing it. Counting that would add one to the refusal figure every few seconds, turning a number that means *something tried to phone home* into a number that means *Askwell is running* — worse than not having the number. A connection that sends nothing is logged at debug and not counted.

**How a destination would be authorised — and none is.** The mechanism is deliberately not a configuration file, because a file is edited once and stays edited. An authorisation is a **decision the user makes**, recorded in the decisions store, scoped to one conversation (online AI) or one question (web search), and time-bound. The proxy holds it in memory for that scope and drops it; there is no persistent form of it and no setting that creates one. Until M8 there is no code path that grants one at all, and the count on the settings screen is therefore a measured zero.

**The model download is not an exception, because it does not happen here.** Askwell fetches one thing over the network in its life: the model, once, at install, when the user asks. That could have been a third allowlist entry, and it is not — an allowlist would take away the property that makes the proxy trustworthy, which is that no configuration exists that would let it forward. Instead the fetch runs on the host, in the same supervisor that runs `llama.cpp`, for the same reason: the host is where host things belong.

The API never opens a socket. It writes `fetch-request.json` into the models directory — url, filename, size and the sha256 the registry published — and reads `fetch-progress.json` back. The host verifies the checksum and discards a file that does not match, because a half-right model fails later as bad answers rather than as a bad download. An air-gapped machine simply never writes a request and uses the manual-file path, and makes no network request at all.

What this buys: the containers holding the user's entire corpus keep zero route to the internet, the proxy keeps its one job, and the only egress in the product is a separate process the user started, fetching a file whose bytes are known in advance.

## 5.2 Web search

Full behaviour in `web-search.md`. The architectural points:

**It is an escalation, never a fallback.** Retrieval runs against the user's own material and abstains when nothing clears the threshold. Only then, and only if the user asks, does a search happen. Nothing in the answer path may reach the web because retrieval came back thin (C10) — that rule is what keeps abstention meaningful (C5).

**Web content is the most untrusted input Askwell handles.** C7 governs it as it governs a document, but the user chose their documents and did not choose a page written to contain instructions. Fetched content is delimited identically, the trace flags instruction-like patterns, and the retrieval is capped in count and size.

**Results are structurally separate from the corpus.** Web results are not chunked into `chunks`, not embedded, and never enter the provenance margin. They live on the turn that fetched them and are cited with their URL and retrieval date, because a page can change after the answer and a document on disk cannot.

The provider sits behind an interface, like the TTS engine, so it can be swapped without touching the answer path.

## 5.1 Data source isolation

Full detail in `data-sources.md`. The architectural point:

**A `.sql` dump is a program, not data.** Importing one means executing arbitrary DDL and DML from a file the user supplied. `sqlglot` validation governs *querying* and cannot govern *loading* — a dump that cannot write is a dump that cannot import.

So imports never touch Askwell's own database. They load into a **separate sandbox Postgres instance**, one database per imported source, owned by a role with no access to Askwell's tables and no superuser rights. A malicious or broken dump destroys its own sandbox and nothing else.

Retrofitting this after imports exist would be a migration on users' machines, so it is in from the start.

## 6. Deployment profiles

Selected at install by a hardware probe **run on the host**, not inside a container — a container sees the cgroup's or the VM's view of memory, and a wrong profile is worse than a missing one. Where detection fails, default to `standard` and say so.

Because inference is a native process (§2.1), GPU acceleration is available on all three platforms.

| Profile | Hardware | LLM | Expected |
| ------- | -------- | --- | -------- |
| `light` | 8GB RAM, CPU only | Qwen3.5 4B Q4_K_M | Slow but usable; text only, voice degraded |
| `standard` | 16GB RAM, CPU only | Qwen3.5 4B Q4_K_M | Comfortable text, voice usable |
| `accelerated` | 16GB+ RAM, 8GB+ VRAM | Qwen3.5 9B Q4_K_M | Fast, full voice |
| `workstation` | 32GB+ RAM, 16GB+ VRAM | Qwen3.6 27B Q4_K_M | Full capability |

Two changes from the previous profiles, both from the repositioning: the floor drops to 8GB because a free product on a personal laptop cannot demand 16GB minimum, and concurrency is no longer a dimension — one user asks one question at a time.

**The installer warns below the `light` floor rather than refusing.** Refusing made sense when a paid deployment could be blamed on the vendor; for a free download, refusing to run is just a lost user. Warn clearly, let them try.

Model names are never hardcoded in application code. They come from configuration, selected by profile.

**A model the user supplies is not a validated default.** Shipped defaults pass the 155-task quality gate, including abstention at ≥ 0.90 and SQL safety at 1.00. A user-supplied model has passed none of it and can break C4 and C5 while the interface presents its answers identically. Swapping is permitted — this is a local, open product and model choice is a legitimate reason to pick one — but the consequence is stated and answers from an unvalidated model carry a persistent marker. Same pattern as the retrieval threshold: permit the dangerous change, state the consequence, never make it frictionless.

**All four are Apache-2.0 and ungated**, verified against the model registry on 2026-08-26. That is **constraint C9**, not a coincidence — Askwell bundles weights into a redistributable installer, so a model under restrictive or manually-gated terms cannot ship however well it performs. Gemma 3 is excluded on exactly this basis: its weights are manually access-gated and carry Google's own terms rather than an OSI licence.

`Qwen3.6 35B-A3B` is worth evaluating for high-RAM CPU machines — a mixture-of-experts model with roughly 3B active parameters behaves far better on CPU than its total size suggests. Not assigned to a profile until measured.

**Profile floors remain estimates.** Nobody has measured tokens/second on real hardware, and the `workstation` VRAM floor against a 27B at Q4_K_M is tight. The eval gate, not this table, decides what actually ships as a default.

## 6.1 v2 language components need re-sourcing

Recorded here because anyone scoping v2 from the older documents would otherwise commit to a component that cannot ship. Verified 2026-08-26:

| Component | Finding |
| --------- | ------- |
| Tamil speech synthesis | `facebook/mms-tts-tam` is **CC-BY-NC-4.0**. Non-commercial, so it fails C9 and cannot be bundled by a product with a paid credit tier. IndicTTS needs the same check before it is assumed |
| Sinhala speech recognition | No production-grade option. The best available are research artefacts with double-digit download counts |
| Tamil speech recognition | Whisper handles it, but quality degrades sharply below `medium`, which does not fit the 8GB `light` floor |

This does not change v1, which is English-only and settled. It means the **v2 plan as written rests on an unusable component**, and it strengthens the original deferral — that decision was argued on schedule risk and voice quality, and the harder reasons turn out to be licensing and outright non-availability.

The three v1 hedges are unaffected and remain correct: multilingual embeddings, the Tamil-aware full-text configuration, and bundled `tam` OCR traineddata all concern indexing rather than speech.

## 7. Data model

Single-user. No `organisations`, no `users`, no roles, no `visible_to_roles[]`.

Revised 2026-08-10 after specifying the screens (`ux/`). Designing screens before schema is deliberate, and it found four things this model could not store — issue #20 plus citations. They are folded in below and marked **new**.

```
settings           key, value                              -- profile, log budget, retention,
                                                              threshold, passphrase state

roots              id, path, filesystem, added_at, removed_at            -- NEW TABLE
                   -- the folders Askwell may read. Mount state is probed,
                   -- never stored; removal tombstones rather than deletes

sources            id, kind(file|csv|dump|connection), name,
                   root_path, config_encrypted, sandbox_db,
                   status(indexing|ready|attention|deleted), last_error,
                   last_indexed_at, added_at

documents          id, source_id, filename, path, mime, sha256, page_count,
                   anchor_kind, ocr_derived, version, superseded_by,
                   deleted_at, deleted_reason, status, ocr_confidence,
                   missing_since, added_at                                -- path/missing_since NEW

document_pages     id, document_id, page_number, text, has_text,
                   anchor_label, added_at                                 -- NEW TABLE
                   -- extraction's own output, one row per page whether or not
                   -- it has text; chunking reads this rather than re-parsing
                   -- the file. `M1-EXTRACT-ING-026`. `anchor_kind` on
                   -- `documents` and `anchor_label` here say what the page
                   -- number means for a given format (`M1-EXTRACT-ING-027`).
                   -- `ocr_derived` marks a document whose text came from
                   -- `M1-EXTRACT-ING-028`'s OCR pass rather than a text
                   -- layer, so the source viewer knows to show the scan
                   -- beside the text.

chunks             id, document_id, ordinal, page_from, page_to, heading,
                   content, content_tsv, embedding vector(1024)

schema_notes       id, source_id, table_name, column_name, description,
                   origin(user|inferred), confidence, superseded_by, embedding

memory             id, subject, fact, origin(clarification|correction|manual|inferred),
                   confidence, superseded_by, created_at              -- inferred origin NEW

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

**`roots`** (2026-08-27, `M1-ADD-ING-021`). Indexing in place means Askwell reads the user's own directories, so it has to be told which ones it may open. This table is that permission and nothing else reads a file without consulting it. Three properties are load-bearing and are argued in `decisions.md`: mount state is **probed on every read, never stored** — a stored value reports an unplugged drive as available for as long as nobody looks; removal is a **tombstone**, so a source underneath can say *why* it became unreadable rather than merely being unreadable; and the unique index on `path` is **partial over the live rows**, because nominating a folder, removing it and nominating it again is an ordinary sequence that a plain unique constraint would refuse. Flow and states in `ux/add-source.md` §7.

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
    { "kind": "compose",  "ms": 8200, "claims": 3,
      "partial_coverage": false, "uncovered_aspects": [] }
  ],
  "backend": { "mode": "local", "model": "qwen3-8b-q4km" },
  "stopped_early": false,
  "injection_flagged": false,
  "partial_coverage": false,          // true when part of the question went unanswered
  "uncovered_aspects": []             // named, never a generic "some information was unavailable"
}
```

**Scores and the threshold are stored, never recomputed.** The abstention trace is the most useful trace there is, and its value is showing the near-miss — "the right passage scored 0.61 under a 0.65 threshold". Recomputing later gives a different number after any model or threshold change, which makes the explanation wrong precisely when someone is trying to understand an old answer.

**A partial answer is not an abstention.** `partial_coverage` can only be `true` on a turn that already cleared the retrieval threshold and composed an answer — the branch that abstains entirely never reaches composition at all (`M2-ABSTAIN-RET-053`), so the two states cannot blur into each other. `uncovered_aspects` is read back out of the model's own answer text (`askwell.agent.partial.split_partial_answer`), the same "recompute from what the turn produced, never from a live re-check" rule the threshold and scores above already follow. `M2-PARTIAL-BE-057`.

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
