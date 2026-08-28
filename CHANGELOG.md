# Changelog

Notable changes per released version. Newest first. Versions follow `AGENTS.md` §7; the canonical version is in `VERSION`.

Categories: `Added`, `Changed`, `Fixed`, `Removed`, `Security`.

## 0.2.24 — 2026-08-28

The provenance margin renders, for the first time. `M1-CITE-FE-043`.

### Added

- **The provenance margin** (`web/components/ask/provenance-margin.tsx`) — one card per cited passage, filename, page or anchor, and the exact retrieved passage, entering the margin as claims are cited during streaming rather than waiting for the answer to finish. Replaces `Shell`'s static placeholder text with a live view of `AskProvider`'s own turn state.
- **`lib/citations.ts`'s `applyCitation`** — groups `citation` events by `chunk_id` rather than by event, so two claims citing the same passage produce one card carrying two claim ordinals, not a duplicate card.
- **A hairline leader** (`web/components/ask/leader.tsx`) joining each claim's rendered text to its card, drawn in `--rule-strong`. A registry, not a prop, because the claim (centre column) and the card (margin rail) are DOM siblings under `ShellFrame`; a short poll keeps it tracking reflow while a turn streams, and falls back to resize/scroll recompute once it settles.
- **`lib/claims.ts`'s `segmentClaims`** — a client-side mirror of `askwell.agent.claims.segment_claims`, run against the same growing answer text so the two sides agree on claim ordinals without either telling the other.
- **The `citation` SSE event now carries `filename`, `anchor_kind`, `heading` and `passage`** (`api/src/askwell/ask.py`, `askwell.retrieve.Candidate`) — the citations table is unchanged; this is display data the browser had no route to before, joined in from `documents` alongside the chunk already being fetched.

### Changed

- `web/lib/ask.ts`'s `AskTurnState`/`applyAskEvent` no longer track a citation count — `AskTurn.citations: CitationCard[]` (`ask-state.tsx`) is the real data the margin renders, kept in its own module rather than folded into `applyAskEvent`.

### Known gaps

- **Click-through has no landing yet.** The card links to `/documents/{id}?page=N`, a route `M1-VIEW-FE-048` has not built — the click is wired to where the viewer will live, per this ticket's own Out of Scope line, and 404s until then.
- **No hover pairing or narrow-window fallback** (`M1-CITE-FE-044`) — the leader is always visible, not raised on hover, and the margin is hidden below the three-column breakpoint rather than reflowing inline (unchanged from `Shell`'s existing behaviour, since that reflow is that ticket's own scope).
- **Deleted-source rendering waits for deletion to exist** (`M2`) — nothing here renders a moved or deleted document differently; a card for either still renders normally.
- **Not exercised against a real model or a real browser** in this environment — verified by `scripts/dev.sh test`, `test-db` (`api/tests/test_ask_api.py`'s wire-format assertions now include the new citation fields) and `scripts/dev.sh web-check` (typecheck, lint, the new `lib/claims.test.ts`/`lib/citations.test.ts`, build, contrast, offline-check), the same limits `M1-ASK-BE-040`/`M1-CITE-BE-042` already recorded.

## 0.2.23 — 2026-08-28

Claim-level citations, as data rather than as prose. `M1-CITE-BE-042`.

### Added

- **`askwell.agent.claims.segment_claims`** — reads the model's own answer text as sentences, each one a claim only if it carries a citation marker `[index]` immediately before its closing punctuation. A sentence with no marker (a restatement of the question, a transition) is not a claim, and is never counted as an uncited one.
- **`askwell.agent.claims.locate_quoted_span`** — the claim's own words, if they occur verbatim (case-insensitive) in the source chunk; `None`, never a dropped citation, when they do not.
- **`citations.quoted_span` is written for the first time** — left `null` since `M1-ASK-API-038`. A claim citing two passages now produces two citation rows sharing one `claim_ordinal`, rather than one row per unique index across the whole answer.
- **The `citation` SSE event carries `claim_ordinal` and `quoted_span`** alongside the chunk it already named, so a card can render per claim as it is emitted rather than only once at the end.

### Changed

- `answer_composition.v1.md`'s Citing section now states the convention `segment_claims` reads back: one factual claim per sentence, markers immediately before the sentence's own closing punctuation, no marker at all on a sentence that asserts nothing from the retrieved content.

## 0.2.22 — 2026-08-28

Generation continues server-side when the user navigates away, made a fully closed loop. `M1-ASK-BE-040`.

### Added

- **The assistant `messages` row is written `running` before generation starts**, not after it finishes — `POST /ask` inserts it in the same request that starts the background task. A message can no longer exist only in memory: the row `reconcile_interrupted` needs to find is there from the first instant.
- **`askwell.ask.reconcile_interrupted`**, run once at startup (`api/src/askwell/app.py`, gated on Postgres being reachable) — fails every assistant row still `running`, which can only mean the previous process died mid-answer. The stated edge case: the stack restarts mid-generation, the answer is lost, and the message is marked failed rather than left pending forever.
- **`Settings.generation_max_concurrent`** (default 2, `ASKWELL_GENERATION_MAX_CONCURRENT`) bounds how many turns retrieve-and-generate at once. Several abandoned questions queue behind the limit rather than each starting a full inference pass immediately — the same reasoning `ingest_concurrency` already applies to ingestion.
- **`GET /ask/counts`** gained `abandoned` — turns `reconcile_interrupted` failed on the machine's behalf, kept separate from an ordinary inference failure. C1: read from this machine's own `messages` rows, nothing transmitted.

## 0.2.21 — 2026-08-28

The mic control, reserved and disabled. `M1-ASK-FE-039a`.

### Added

- **Mic control in the composer** (`web/components/ask/ask-screen.tsx`) — present beside "Ask" from Phase 1, at its final position and size (`docs/ux/voice.md` §2), so M6 enables it in place rather than reflowing the composer around it. Disabled with `aria-disabled` rather than the `disabled` attribute, so it stays reachable by keyboard and a screen reader announces it as disabled with its reason — a tooltip on hover and on focus — instead of an unlabelled dead stop. No audio work of any kind: no microphone permission is requested, clicking it does nothing.

## 0.2.20 — 2026-08-28

The Ask screen, for the first time. `M1-ASK-FE-039`.

### Added

- **The Ask screen** (`web/components/ask/ask-screen.tsx`) — the composer (`Enter` submits, `Shift+Enter` newlines), named step labels ahead of the first token, and tokens streamed into the live turn as `POST /ask` (`M1-ASK-API-038`) produces them.
- **`AskProvider`** (`web/components/ask/ask-state.tsx`) — the conversation held once above the router, matching `AddProvider`'s own reasoning, so a completed answer survives navigating away and back. A question asked while one is running is queued, not interleaved — one answer at a time, nothing silently dropped.
- **`⌘K` / `Ctrl+K`** reaches the Ask screen and focuses the composer from anywhere in the shell.
- **`web/lib/ask.ts`** — the SSE parser and `streamAsk`/`stopAsk` client for `POST /ask`, `POST /ask/{message_id}/stop`.
- A non-Latin-script question gets Askwell's English-only statement instead of a poor answer — a heuristic, not language detection; documented as such (`web/lib/ask.ts`).

### Known gap

- **`conversation_id` is not threaded across turns.** `askwell.ask` never returns the id it resolved or created, so every question opens its own conversation server-side. Filed as issue [#156](https://github.com/Rumeasiyan/askwell/issues/156) rather than worked around; does not affect this ticket's own acceptance criteria.

## 0.2.19 — 2026-08-28

A question gets an answer, over the wire, for the first time. `M1-ASK-API-038`.

### Added

- **`POST /ask`** — starts a turn: resolves or opens a conversation, records the user's question, and returns a server-sent stream over the same background generation a browser can drop and reconnect to. Runs retrieval (`M1-ASK-RET-035`/`036`) and composition (`M1-ASK-BE-037`) for the first time against a real question, then streams the model's own tokens as `InferenceClient.stream_generate` produces them (new — see below).
- **`GET /ask/{message_id}/stream`** — reconnects to a turn still running, or replays a finished one from `messages` once it has left memory (a retired turn, or this process having restarted). A turn's own event history is small enough to replay in full rather than tracking what a given browser has already seen; `docs/decisions.md` records why this departs from the ticket's stated "does not replay tokens already sent" and what the alternative design's bug was.
- **`POST /ask/{message_id}/stop`** — ends generation early; the stored answer is marked partial (`messages.trace.stopped_early`).
- **`askwell.inference.client.InferenceClient.stream_generate`** — generation as an async stream of `StreamChunk`s over llama.cpp's own SSE `/completion` response, instead of `generate`'s one round trip. Raises the same `InferenceUnavailable`/`InferenceFailed` distinction as every other method, wherever in the stream the failure happens — including after tokens have already been sent, the "inference process dies mid-stream" edge case.
- **Citations, for the first time.** The model is asked to cite by the same `index` `compose()` delimits candidates with; `askwell.ask` resolves `[index]` references out of the streamed text as they complete and writes them to the real `citations` table (`docs/architecture.md` §7) — C4 having somewhere to attach to, not just `messages.trace`.
- **`ASKWELL_GENERATION_MAX_TOKENS`** (default 1024) — the ceiling on one answer's length. Reaching it is stated (`trace.reason`), never silent.
- **`api/tests/conftest.py::drive_and_disconnect`** — the raw-ASGI streaming-test helper issue #110 predicted this ticket would need, extracted so a third streaming endpoint does not rediscover the pattern `test_ingest_api.py` found the hard way.

### Verified

- `scripts/dev.sh test` — 425 passed, 1 skipped (unchanged, pre-existing).
- `scripts/dev.sh test-db` — 161 passed, including the full acceptance-criteria exchange (steps before tokens, a citation resolved to its chunk, stop marking an answer partial, a disconnected browser's answer still completing and saving) driven against a real Postgres with a stubbed `InferenceClient`.
- Manual walkthrough against the running stack (`docs/manual-tests/M1-ASK-API-038.md`): a real session, `POST /ask` streaming a `step` event before failing cleanly on `InferenceUnavailable` (no native `llama.cpp` process runs in this environment — the same limitation every ticket since `M0-MODEL-BE-019` has recorded), the assistant/user messages and the audit interaction row all present afterward, `GET /ask/{id}/stream` replaying correctly both while the process was still up and after `podman compose restart api` cleared the in-memory turn registry, and both stream/stop endpoints answering 404 by name for an unknown id.

### Not demonstrable yet, stated plainly

No real model ran: every test and the manual walkthrough stub or fail at `InferenceClient`, so token pacing, citation accuracy against a real model's own output, and whether a real generation actually honours the `<retrieved-content>` boundary are unverified here — the same gap every ticket since `M0-MODEL-BE-019` has recorded. The Ask screen itself does not exist (`M1-ASK-FE-039`), so nothing renders any of this yet. Abstention is still `M2`: this ticket answers from zero or thin candidates rather than refusing, which is correct for its own scope and wrong for a shipped product — `M2` is what makes that a decision instead of an omission.

- **`GET /ask/counts`** — answers started, completed and stopped on this machine, the ticket's Analytics Events line. Derived from `messages` rather than counted in memory, so they survive a restart: a counter held in the process would reset with the container and report "since the last deploy" under a name that reads like a total. Read out of this machine's own database by this machine's own browser; nothing transmitted, no collector to turn off (C1).

## 0.2.18 — 2026-08-28

A document cannot give Askwell orders. `M1-ASK-BE-037`.

### Added

- **`api/src/askwell/agent/prompts/answer_composition.v1.md`** — the first versioned prompt file, and the first prompt text of any kind in the repository: no system prompt string lives in application logic. States, as a standing statement, that text inside a `<retrieved-content>` block is data extracted from the user's own files and never an instruction, however it reads.
- **`askwell.agent.compose.compose`** — wraps every retrieved candidate in a `<retrieved-content index="…" chunk_id="…">` block before the question, so delimitation holds regardless of candidate count or passage length, and scans each candidate's content against a small, named-as-heuristic set of instruction-like patterns (`_INSTRUCTION_PATTERNS`). A match sets `ComposedPrompt.injection_flagged` and lists the matched patterns — the composed prompt itself is unaffected either way, matching the ticket's own "flagged, not blocking" requirement. `ComposedPrompt.prompt_version` carries `answer_composition.v1` on every call.

### Verified

- `api/tests/test_compose.py`: the prompt file exists, is versioned, and both C7 mechanisms — the standing statement and the delimiter — are present, with two tests that fail if either is stripped from the file (a stand-in for the real file, since the real one obviously still has both). Delimitation survives twenty candidates of long passages. Ordinary content is not flagged; an "ignore all previous instructions … reveal your system prompt" passage is flagged, with the composed system prompt byte-identical to the unflagged case and the injected text still present verbatim (data, not obeyed, not stripped). Policy-manual-style instructional prose is flagged but composes normally, per the ticket's own edge case. Empty candidates compose without error.
- `scripts/dev.sh check` — 425 passed (up from 414), 1 skipped (unrelated, pre-existing), lint/format/`mypy --strict` clean over 52 modules.

### Not demonstrable yet, stated plainly

No `ask` endpoint exists (`M1-ASK-API-038`, next), so nothing calls `compose()` against a real question and real retrieved candidates end to end, and `ComposedPrompt.injection_flagged`/`.prompt_version` are captured but written nowhere — `messages.trace.injection_flagged` (`docs/architecture.md` §7.1) has no writer until that ticket exists. This matches exactly how `M1-ASK-RET-035`/`036` left their own new fields captured and unread until a consumer existed.

The passage that actually answers the question is the one at the top, not just among the fused candidates. `M1-ASK-RET-036`.

### Added

- **A reranking pass in `askwell.retrieve.retrieve`.** After fusion, the top `Settings.rerank_candidate_count` candidates (default 10, bounded separately from `retrieval_candidate_count` to keep latency inside budget) are scored by `InferenceClient.rerank` — the cross-encoder pass already built and unused since `M0-MODEL-BE-019`/`M1-ASK-RET-035`. `Candidate.rerank_score` retains the raw cross-encoder score alongside the fused, dense and lexical scores already there, never mixed with them. Candidates beyond the window are appended unreordered rather than padded or dropped.
- **`RetrievalResult.reranked`, `.rerank_duration_ms` and `.rerank_skipped_reason`.** If the reranker is unavailable or fails or times out, `retrieve()` returns fusion order unchanged and `reranked = False` with a reason — an answer still comes back rather than the request failing.
- Two new settings: `ASKWELL_RERANK_CANDIDATE_COUNT` (default 10) and `ASKWELL_RERANK_TIMEOUT_SECONDS` (default 10.0).

### Verified

- `api/tests/test_rerank.py`: `_rerank` in isolation against a real Unix socket stub — reordering happens and both scores are retained; fewer candidates than the window needs no padding; candidates beyond the window are appended unreordered; an unavailable or failing reranker degrades to fusion order with a stated reason; no candidates skips reranking without asking the assistant; tied scores keep a stable order.
- `api/tests/test_retrieve_records.py`, against real Postgres: on five chunks scoring identically under fusion, the right supplier's passage is promoted to the top by reranking; with the reranker unavailable, `retrieve()` still returns the fusion-ordered result.
- On the running stack, rebuilt to `0.2.17`, against real Postgres: a fake client promoting the Meridian passage produced `reranked=True` with the right passage first and both score sets populated; the real `InferenceClient.rerank` against the actual absent inference socket in this environment produced `reranked=False`, `rerank_skipped_reason='reranker unavailable: The assistant is stopped.'`, and the fusion-ordered candidate still came back. A live walkthrough with a real reranker model actually scoring was not run — no native `llama.cpp` process is available in this environment, the same limitation every ticket since `M0-MODEL-BE-019` has recorded.

## 0.2.17 — 2026-08-28

The passage that actually answers the question is the one at the top, not just among the fused candidates. `M1-ASK-RET-036`.

### Added

- **A reranking pass in `askwell.retrieve.retrieve`.** After fusion, the top `Settings.rerank_candidate_count` candidates (default 10, bounded separately from `retrieval_candidate_count` to keep latency inside budget) are scored by `InferenceClient.rerank` — the cross-encoder pass already built and unused since `M0-MODEL-BE-019`/`M1-ASK-RET-035`. `Candidate.rerank_score` retains the raw cross-encoder score alongside the fused, dense and lexical scores already there, never mixed with them. Candidates beyond the window are appended unreordered rather than padded or dropped.
- **`RetrievalResult.reranked`, `.rerank_duration_ms` and `.rerank_skipped_reason`.** If the reranker is unavailable or fails or times out, `retrieve()` returns fusion order unchanged and `reranked = False` with a reason — an answer still comes back rather than the request failing.
- Two new settings: `ASKWELL_RERANK_CANDIDATE_COUNT` (default 10) and `ASKWELL_RERANK_TIMEOUT_SECONDS` (default 10.0).

### Verified

- `api/tests/test_rerank.py`: `_rerank` in isolation against a real Unix socket stub — reordering happens and both scores are retained; fewer candidates than the window needs no padding; candidates beyond the window are appended unreordered; an unavailable or failing reranker degrades to fusion order with a stated reason; no candidates skips reranking without asking the assistant; tied scores keep a stable order.
- `api/tests/test_retrieve_records.py`, against real Postgres: on five chunks scoring identically under fusion, the right supplier's passage is promoted to the top by reranking; with the reranker unavailable, `retrieve()` still returns the fusion-ordered result.
- On the running stack, rebuilt to `0.2.17`, against real Postgres: a fake client promoting the Meridian passage produced `reranked=True` with the right passage first and both score sets populated; the real `InferenceClient.rerank` against the actual absent inference socket in this environment produced `reranked=False`, `rerank_skipped_reason='reranker unavailable: The assistant is stopped.'`, and the fusion-ordered candidate still came back. A live walkthrough with a real reranker model actually scoring was not run — no native `llama.cpp` process is available in this environment, the same limitation every ticket since `M0-MODEL-BE-019` has recorded.

## 0.2.16 — 2026-08-28

A question mixing a name and a concept returns candidates found by either. `M1-ASK-RET-035`.

### Added

- **`askwell.retrieve.retrieve`** — dense search (pgvector cosine, `chunks.embedding`) and lexical search (`chunks.content_tsv`, hyphen-normalised query text to match `c7e2f814a5b3`'s own tokenising) run independently, each bounded to `Settings.retrieval_candidate_count`, and are fused with Reciprocal Rank Fusion (`RRF_K = 60`). Every candidate retains its own dense score, lexical score (either nullable, if only one search found it) and the fused score it was ranked by — nothing is recomputed from the fused list alone. `Settings.retrieval_score_threshold` is captured on the result as configured at call time, for the trace to show a near-miss later, without applying it — abstaining on it is `M2`.
- **`source_id` scopes both searches to one source.** Both queries exclude superseded (`superseded_by IS NOT NULL`) and deleted (`deleted_at IS NOT NULL`) documents at the query itself.
- Two new settings: `ASKWELL_RETRIEVAL_CANDIDATE_COUNT` (default 40) and `ASKWELL_RETRIEVAL_SCORE_THRESHOLD` (default 0.65, matching `docs/architecture.md` §7.1's own example).

### Verified

- `api/tests/test_retrieve.py`: `_fuse` in isolation — a hit in both lists outranks a hit in only one, a missing side keeps a null score, the fused score is the reciprocal-rank sum, no hits returns nothing, identical content from two documents is never deduplicated, the result is truncated to the candidate count.
- `api/tests/test_retrieve_records.py`, against real Postgres: a reference number (`INV-2024-0917`) retrieves the chunk that contains it by lexical search alone; a paraphrase with no shared wording retrieves the right chunk by dense search alone; scores and threshold land on the result as configured; a superseded document and a deleted document are both excluded while the live one is returned; an empty corpus returns cleanly; a one-word query does not error; a one-document corpus still fuses; identical content in two documents returns both; scoping to a source excludes a matching chunk in another source.
- `scripts/dev.sh check` — 407 passed, 1 skipped. `scripts/dev.sh test-db` — 150 passed, up from 141, 10 of them new.

### Deferred

- No caller exists yet — nothing in the repository invokes `retrieve()`. The `ask` endpoint, streaming, and writing `messages.trace` are `M1-ASK-RET-036` (reranking) and later M1/M2 tickets; this ticket's own scope is the two searches and their fusion, not the surface that calls them.
- No vector index (`ivfflat`/`hnsw`) on `chunks.embedding` — both searches are sequential scans. Not needed yet at the corpus sizes this milestone targets; worth revisiting once a real corpus makes `_dense_search` measurably slow.

## 0.2.15 — 2026-08-28

Re-adding a changed document offers to replace the old version rather than duplicating it. `M1-INDEX-BE-034`.

### Added

- **A file at an already-indexed path with different content is offered as a new version, not silently duplicated or silently inserted.** `POST /sources` gains `version_decisions`, a map from relative path to `"supersede"` or `"keep_both"`; a path with no entry that turns out to be a changed revision comes back as `new_version` with nothing recorded, so declining costs nothing to reverse. `"supersede"` retires the old document (`documents.superseded_by`) and records the new one at `version + 1` in the same transaction — never both or neither. `"keep_both"` inserts the new file as an ordinary independent document; the schema's own uniqueness (`uq_documents_live_source_id_sha256`) is keyed on content, not path, so two live documents at one path was already a state it permitted.
- **A decisions-store record naming both versions**, `document_superseded`, alongside the ordinary `document_added` for the new row — so a later audit read can answer "what replaced what" without inferring it from two independent rows.

### Verified

- `api/tests/test_sources_records.py`: a changed file at the same path is offered, not duplicated, and nothing is recorded until decided; accepting sets `superseded_by` and bumps `version` without touching `deleted_at`; declining leaves both live; superseding a document that is itself already-superseded chains through the current live tip rather than orphaning; a new path with identical content is still recognised as a plain duplicate before the path-based version check ever runs.
- `scripts/dev.sh check` — 401 passed, 1 skipped (unmarked suite; supersession tests are `requires_db`). `scripts/dev.sh test-db` — 141 passed, up from 136, all 5 new tests among them.
- On the running stack (`ASKWELL_ROOTS_MOUNT` set to a temporary directory for the session): added a `.txt` file, edited it on disk, re-added it and received `new_version` with nothing changed in the database; re-added with `version_decisions: {"file.txt": "supersede"}` and confirmed via `psql` that the old row's `superseded_by` now points at the new row, the new row is `version` 2, and the old row's `deleted_at` is still null.

### Deferred

- The superseded banner the source viewer would render (`docs/ux/source-viewer.md` §4) has nowhere to attach yet — no document-detail or citation-resolution endpoint exists in the repository. Filed as [#141](https://github.com/Rumeasiyan/askwell/issues/141), owned by whichever ticket builds that surface.
- Retrieval excluding superseded versions is not yet exercisable — no retrieval component exists (`M1-ASK-RET-035`/`036`). The requirement is recorded in `docs/decisions.md` so the retrieval ticket filters `superseded_by IS NULL` rather than rediscovering the need.

## 0.2.14 — 2026-08-28

A reference number is findable by the part someone actually remembers. `M1-INDEX-DB-033`.

### Fixed

- **`content_tsv` no longer buries a reference number's sign inside its own lexeme.** Postgres's default parser reads a hyphen before a digit run as a minus sign, so `INV-2024-0917` tokenised as `inv`, `-2024`, `-0917` — a search for just `0917` never matched. `chunks.content_tsv`'s generated-column expression now replaces hyphens with spaces before tokenising, so each group indexes independently and matches alone. Migration `c7e2f814a5b3`; reasoning in `docs/decisions.md`.

### Verified

- The column and its GIN index (`ix_chunks_content_tsv`) already existed and already auto-populated on every write (`a8208099ef38`) — nothing new to build there. `api/tests/test_index_db_records.py` proves: every written chunk gets a populated value; a chunk with no content gets an empty, non-null vector rather than dropping out of the index; a reference number matches both in full and by its trailing group; a pure-numeric or very long chunk indexes without error; re-chunking a document leaves exactly one row, not two; and, seeded to 300,000 chunks, a lexical query's `EXPLAIN` plan uses `ix_chunks_content_tsv` rather than a sequential scan.

## 0.2.13 — 2026-08-28

Chunks are actually embedded — the last stage of the ingestion pipeline, and the first thing that makes anything searchable. `M1-INDEX-ING-032`.

### Added

- **An `embed` stage, real for the first time.** `api/src/askwell/embed.py` sends every un-embedded chunk of a document to the native inference process in bounded batches (`ASKWELL_EMBEDDING_BATCH_SIZE`, default 16), retrying a failing batch with backoff before giving up on the document. Wired into `ingest.STAGES`; a document now reaches `ready` only once every one of its chunks has an embedding — never partially.
- **A batch failure retries; exhaustion is visible and retryable.** A transient inference blip (the process restarting mid-batch, a slow request) retries up to three times with a short linear backoff inside this stage; if that is exhausted, the whole document fails through the pipeline's existing per-document retry and failure surface (`GET /ingest`, `POST /ingest/documents/{id}/retry`) — nothing is silently dropped.
- **The embedding dimension is checked once, at worker startup.** `askwell.worker.startup` refuses to start — rather than failing one opaque batch at a time — if `ASKWELL_EMBEDDING_DIMENSIONS` does not match the width `chunks.embedding` was actually migrated at.
- **An empty chunk is refused as a second line of defence.** `askwell.chunk` already guarantees this cannot happen; `embed` checks anyway, so a defect upstream surfaces as a named failure rather than a citation pointing at nothing.

## 0.2.12 — 2026-08-28

Chunking respects structure instead of cutting at a fixed length. `M1-INDEX-ING-031`.

### Added

- **A `chunk` stage, real for the first time.** `api/src/askwell/chunk.py` parses `document_pages.text` back into the headings, `[TABLE]`/`[/TABLE]` markers and list items the extractors already left in it, merges them into `chunks` rows up to a target size without ever crossing a hard maximum, and writes `document_id`, `ordinal`, `page_from`/`page_to`, `heading` and `content` — `embedding` stays null for `M1-INDEX-ING-032`. Wired into `ingest.STAGES`; a document now parks at `embed` instead of `chunk`.
- **A table is never split from its header.** A table longer than the hard maximum is split by row with the header repeated on every part; a heading is carried as every following chunk's `heading` column until the next one; a single paragraph longer than the maximum splits at sentence boundaries with overlap so a sentence is never orphaned; a slide (`documents.anchor_kind = 'slide'`) is never merged with another slide into one chunk.

## 0.2.11 — 2026-08-28

Extraction failures are named individually, and a password-protected PDF prompts rather than just failing. `M1-EXTRACT-VAL-030`.

### Added

- **Extraction failures classified by cause**: a file missing from disk (`MissingSource`), unreadable due to permissions (`UnreadableSource`), corrupt (`CorruptDocument`), or password-protected (`PasswordProtected`/`WrongPassword`) each carry their own reason naming the file, instead of a raw library exception surfacing as the message. `MissingSource`/`UnreadableSource` are checked once, ahead of every format's own parser, so a file that vanished between add and extraction reads distinctly from one that opened and turned out broken.
- **A password-protected PDF prompts for its password.** `POST /ingest/documents/{id}/password` retries a failed document with a password for that one attempt — never written to a database row or a log line, since storage needs the credential encryption path M4 adds and is not offered until then. A wrong password is reported as wrong and the file stays listed as failed, not dropped; the right one completes ingestion.

## 0.2.10 — 2026-08-28

Low-confidence OCR is flagged rather than silently indexed. `M1-EXTRACT-ING-029`.

### Added

- **OCR confidence, measured and stored.** Every OCR'd page's Tesseract confidence is kept (`document_pages.ocr_confidence`), and `documents.ocr_confidence` is their mean. A text-layer page or document carries no confidence at all — nothing to be false about, since Tesseract was never asked.
- **A source shows `needs attention` for poor OCR, with a specific reason.** Below `ASKWELL_OCR_CONFIDENCE_THRESHOLD` (default `0.60`, configuration), a document is flagged — never a failure, and never removed from the index. A mixed document names the specific pages that read worst. The `/ingest` snapshot carries a `flagged` list and a local `documents_flagged` counter (C1: nothing transmitted).

### Changed

- **`sources.last_error` now names both causes when both are true** — failed files and flagged files in the same sentence, rather than one overwriting the other.

## 0.2.9 — 2026-08-28

A scanned PDF with no text layer is now actually read. `M1-EXTRACT-ING-028`.

### Added

- **OCR fallback with orientation detection.** A page whose text layer fails extraction's usability check is rendered to an image and read by Tesseract — orientation and script detected first, so an upside-down or sideways scan still reads correctly. Runs per page, so a mixed document only pays the OCR cost on the pages that actually need it.
- **`documents.ocr_derived`**, so the source viewer can later show the scanned image beside the text for a document that used OCR.
- **Tamil OCR as the same hedge everywhere else in the product**: the bundled `tam` traineddata recognises Tamil script when Tesseract's own script detection identifies it, but the language is never presented as supported.

### Changed

- **A PDF that never gets any text — not from a text layer, not from OCR — now fails with a reason**, the same C5 failure every other extractor already reports, instead of parking forever awaiting a ticket that has now landed.

## 0.2.8 — 2026-08-28

Word, PowerPoint, spreadsheet, plain text, Markdown and HTML now extract for real. `M1-EXTRACT-ING-027`.

### Added

- **`.docx`, `.pptx` and `.xlsx` extraction**, via `python-docx`, `python-pptx` and `openpyxl` — all MIT-licensed. Headings, list items and table boundaries survive as structural markers; a slide's speaker notes are included and labelled; a spreadsheet is read document-style, one row per anchor, across every sheet.
- **Plain text, Markdown and HTML extraction**, sectioned by heading where one exists. A Markdown file's YAML front matter is excluded from the indexed prose. An HTML page has its navigation chrome and `<title>` discarded, keeping only what a reader actually sees.
- **`documents.anchor_kind` and `document_pages.anchor_label`**, so the source viewer knows what a document's page-equivalent ordinal means — a PDF page, a slide, a spreadsheet row, or a heading — and can render the right pointer next to it.
- **A document with nothing extractable in it fails with a reason**, never reaching `ready` empty — the same C5 failure a PDF with no text layer already produces, for every new format.
- **A legacy binary Office file (`.doc`, `.xls`, `.ppt`) fails by name**, retryable, rather than crashing unreadably or being silently skipped — a known gap, tracked as issue #121.

## 0.2.7 — 2026-08-28

The ingestion pipeline's first real stage. `M1-EXTRACT-ING-026`.

### Added

- **PDF text-layer extraction, page by page.** `pypdfium2` reads each page of a digital PDF and records its text with a page number that matches what a person sees at the bottom of the printed page. `documents.page_count` is set from the real page count, not a guess.
- **`document_pages`, one row per page whether or not it has text.** A blank page is recorded rather than skipped, so the OCR ticket (`M1-EXTRACT-ING-028`) can find exactly the pages it owns without extraction having decided anything on its behalf.
- **A PDF with no usable text layer anywhere parks naming `M1-EXTRACT-ING-028`**, the same way a document waiting on chunking parks naming that ticket — not indexed empty, not failed. A document with a text layer on some pages and not others is not this case: it proceeds, with its blank pages on record.
- **A document parked before this version is revived, not stranded.** Anything added before this ticket landed was sitting `parked` waiting for `extract`; the worker now returns those to the queue at startup instead of leaving them parked forever. Issue [#109](https://github.com/Rumeasiyan/askwell/issues/109).

### Changed

- A pipeline stage now receives a database session of its own, not only the file and a progress callback — the shape every real stage needs, `extract` being the first to use it.

## 0.2.6 — 2026-08-28

Indexing stops belonging to the page you are looking at. `M1-ADD-ING-025`.

Three defects the audit found before this shipped are fixed here rather than filed for later: the browser opened one event stream per drop and stalled the tab after six, a failed file reached the screen as a bare count, and a queue that had lost a worker could not restart itself for an hour.

### Added

- **Ingestion is a background job.** Recording a drop now writes a queue row per document in the same transaction as the document itself, and a worker picks them up. The add request ends; the work does not. Navigating away, closing the tab and restarting the browser leave the import running.
- **A durable queue, not just a Redis one.** `ingest_jobs` is the record and Redis is the transport. A worker killed mid-job has its work returned to the queue at startup; a Redis that was flushed, unreachable, or asleep with the laptop is repaired by a reconcile that runs every half minute. Nothing that was committed is lost by the queue being unavailable — it is delayed.
- **Progress per file and inside a file.** `GET /ingest` is a snapshot and `GET /ingest/stream` is the same payload as server-sent events, pushed only when something changes. Both carry the running count, each queued file's position, and the bytes done and total for whatever is being read — so one 900-page scan shows movement rather than an untimed spinner.
- **An estimate that says what it is based on, or refuses to give one.** Before anything has finished indexing on this machine there is no throughput history, so the answer is no number and a sentence saying why. A measured estimate carries the count and average it was extrapolated from.
- **Partial coverage, so a source is askable early.** Every source reports how many of its documents are indexed and whether it can be asked about at all. Eighty of five hundred papers is eighty papers' worth of answers, not a wait.
- **A failed document is visible with its reason and a retry.** Three attempts, then it rests as failed with the error stored where the library can render it — in Postgres, so it survives the queue. `POST /ingest/documents/{id}/retry` forgives the attempts and puts it back.
- **Concurrency is configuration and defaults to two.** `ASKWELL_INGEST_CONCURRENCY`, because this laptop is also running the user's browser. `ASKWELL_INGEST_JOB_TIMEOUT_SECONDS` defaults to an hour: OCR over a long scan is genuinely that slow, and the queue's five-minute default would call a slow file a failed one.
- Documents recorded before this version — by `M1-ADD-BE-023`, when there was no queue — are enqueued by the migration. They would otherwise have waited forever for a worker that had nothing to tell it they existed.

### Changed

- The add screen's *Queued* panel is live. It says what the queue is doing, what position a file is in, and — while the pipeline is incomplete — what has to arrive before anything is searchable, instead of promising that background ingestion is coming.
- A source's status is derived from its documents rather than set by hand, and a change is a decisions record naming what moved and how much of the source was ready at the time.

### Known gaps

- **Nothing is extracted, chunked or embedded yet, so no document reaches `ready` on its own.** Those three stages are declared in the pipeline, named with their tickets, and not built: `M1-EXTRACT-ING-026`, `M1-INDEX-ING-031`, `M1-INDEX-ING-032`. A job runs, reaches extraction, finds nothing installed and parks there saying so. The queue, the progress, the failure handling and the resume are real and are exercised by tests that install a stage of their own; what a fresh install sees today is an honest "recorded and waiting", not a progress bar.
- Documents already parked when a stage is later installed are not automatically re-queued. Issue [#109](https://github.com/Rumeasiyan/askwell/issues/109).
- Hashing still happens inside the add request. The queue that would move it now exists — issue [#105](https://github.com/Rumeasiyan/askwell/issues/105).
- Disk budget refusal is not implemented. M7.

## 0.2.5 — 2026-08-28

Askwell remembers what it was given, and notices when it has been given it before. `M1-ADD-BE-023`.

### Added

- **A queued batch becomes records.** `POST /sources` creates one source for the folder and one document per file, carrying the path, the filename, the media type, a SHA-256 of the contents and when it arrived. The add screen no longer ends at a sentence about work that has not started — it ends at rows.
- **The same file is recognised rather than indexed twice.** By content hash, across every source: `contract.pdf` and `contract copy.pdf` in one drop, or the same PDF added later from a different folder, are recognised and linked to the document that already holds those bytes. Both paths are shown, so it is clear which copy Askwell is reading. Duplicate passages in retrieval are what make a citation ambiguous, which is the cost this avoids.
- The partial unique index that enforces one live version per source and hash — which has existed in every database since the first migration and in no model — is now **declared in the model**, so it stops being an invariant an autogenerated migration would propose dropping.
- **`queued` is a status of its own**, for both sources and documents, and it is the default. A row that has been recorded and is waiting is not a row being read, and storing it as `indexing` is what a progress bar that never moves is rendered from.
- **The server decides what a file is, from its own read of the bytes.** Detection also runs in the browser and always did; that answer is what the user watches during a drop and is now explicitly a courtesy rather than a boundary. Nothing the client says about a file's type is stored.
- **Adding is a decisions record.** One for the source and one per document, each naming the path — carried forward from `M1-ADD-FE-022`, which stated the requirement and could not meet it from a screen. A refusal and a duplicate are logged instead: nothing changed, and the decisions store is kept forever.
- **Refusals now reach the operational log**, which is the durable record the browser's local counter was not. Carried forward from `M1-ADD-VAL-024`.

### Changed

- The local "files added" counter follows what the server actually added, not what the screen sent. Re-adding a folder no longer inflates it.

### Known gaps

- Nothing extracts, embeds or indexes these documents yet — that is `M1-ADD-ING-025`. The status transitions past `queued` belong to the ingester and are not exercised here.
- A changed version of a file already indexed is recorded as a new document rather than as a supersession. `M1-INDEX-BE-034`.
- Hashing happens inside the request. For a large drop of large files that is a long request, and there is no progress while it runs.

## 0.2.4 — 2026-08-27

An unsupported file is refused by name, and a CSV is told when its turn comes. `M1-ADD-VAL-024`.

### Added

- **Markdown and HTML are read.** `docs/data-sources.md` §1 has listed both since it was written and detection had neither: an HTML page is recognised by its opening rather than its name — before this a saved page full of tables was read as a CSV — and Markdown is named from its extension, which is the one place the name is better evidence than the bytes.
- **A refusal names the file, what its contents turned out to be, and what would work.** Per file, with the supported list once beneath the block rather than repeated after each of five.
- **A drop that expands to no files says so** — an empty folder, nothing changed. A cancelled file dialog still says nothing.
- A local counter of files turned away, beside the one for files added. Same store, same absence of a wire (C1).

### Changed

- **A CSV or a dump is named as *arriving*, not as unsupported, and is no longer queued.** Detection now answers three ways — indexed today, arriving in a later milestone, refused — where it answered two. The screen previously said "Arrives in M4" in one panel while queueing a CSV as though it worked in another; the file's own route is what decides, read from the same table the panel is rendered from, so M4 flips both at once.
- Rejection is per file throughout: one archive among sixty contracts refuses the archive and queues the contracts.

### Known gaps

- Detection still runs in the browser, and it is a courtesy rather than a boundary. `M1-ADD-BE-023` must re-detect server-side from the same signature table and treat anything the client says as a hint for the message only.
- Rejections are counted locally but not written to the operational log — nothing is sent to the API for a file that was refused, and this ticket adds no endpoint to send it to.

## 0.2.3 — 2026-08-27

Material can be handed to Askwell. `M1-ADD-FE-022`.

The add-source screen and its files route, and drag-and-drop that works anywhere in the application rather than only on that screen.

### Added

- **`/sources/add/`** — four routes, one working. Files is functional; spreadsheet-or-CSV, database dump and connect-a-database are shown with the milestone they arrive in rather than hidden, so someone whose material is a MySQL export can see it has a home here.
- **Drop anywhere.** A folder of contracts dropped onto the Ask screen is taken and the flow follows it; the user does not navigate first. A folder is expanded, counted and shown before anything starts, and a drop that arrives while another is being read is **queued, never rejected**.
- **Type detection by contents, not by name.** A `.pdf` that is really a PNG is indexed as a PNG and the disagreement is said out loud; a program is refused by name with the fact that nothing was run; an archive is refused with what to do instead. Only the first 4 KB of any file is read.
- **The in-place statement**, once and at full size: nothing is copied, moved or uploaded — which is what someone about to add 40 GB of case files needs before they start.
- A local counter of files added, in `localStorage`. There is no path for it to take off this machine and none is being built (C1).

### Known gaps

- **Nothing is extracted, embedded or searchable yet.** A batch ends at *queued* and says so plainly rather than showing progress that will not move. Records are `M1-ADD-BE-023`; background ingestion and per-file progress are `M1-ADD-ING-025`.
- **A browser will not say where a file lives.** The ticket assumed the drop event gives usable paths; no browser gives them on any platform, so the screen asks once per drop which folder the files came from — the same typed path used to nominate a folder. `M7-TAURI-FE-182` removes the question rather than improving it.
- The estimate is a count and a size, not a duration. Nothing here has yet measured how long embedding takes on a CPU, and an invented number is the one someone plans their afternoon around.

## 0.2.2 — 2026-08-27

Askwell can be told which folders it may read. `M1-ADD-ING-021`.

Askwell indexes in place and copies nothing, so the containers need a route to the user's own files — and this is one narrow, explicit route rather than open filesystem access.

### Added

- **A registry of nominated root directories.** `roots`, its own table, tombstoned on removal so a source underneath can say *why* it stopped being readable rather than merely being unreadable. A path no root covers is never read, and that check resolves symlinks so one link inside a nominated folder cannot stand in for the whole disk.
- `GET /roots`, `POST /roots`, `GET /roots/covering`, `GET /roots/{id}/removal`, `DELETE /roots/{id}`. Registering and removing a folder are decisions records.
- **`ASKWELL_ROOTS_MOUNT`** — one directory bind-mounted read-only into the API and worker at the *same absolute path* it has on the host, so a path means one thing on both sides and needs no translation layer.
- Four reasons a folder can be unreadable, kept apart because they have four different fixes: `not_mounted`, `unavailable` (a drive unplugged — never "deleted"), `unreadable`, `available`.
- **Folders Askwell may read**, in settings: listed with their state, nominated by path, removed against a consequence the API computed rather than one the interface guessed.
- Network shares are permitted, with a warning that indexing will be slow and the share must be connected for a citation to reopen its page.

### Known gaps

- A folder is selected by typing its path. A browser cannot offer a directory dialog; the desktop shell provides one in `M7-TAURI-FE-182`, and only the selection step changes.
- Nominating a folder outside `ASKWELL_ROOTS_MOUNT` is recorded and reports what to set and that the stack must come up again — a container's mounts cannot be changed while it runs. Stated at the moment of registration rather than discovered later.

## 0.2.1 — 2026-08-28

Inference is three processes, not one. [#89](https://github.com/Rumeasiyan/askwell/issues/89), which blocked M1 retrieval.

### Added

- The supervisor manages generation, embedding and reranking independently. One model missing does not stop the others — a user with no reranker can still ask questions.
- `bge-m3` for embeddings (MIT) and `bge-reranker-v2-m3` for ranking (Apache-2.0), both verified against the registry before their names were written down (C9).
- The bridge routes by path, so the containers reach all three through one socket and never learn how many there are.

### Fixed

- **Embeddings were 2560 dimensions where the schema is `vector(1024)`.** They would not have been merely poor for retrieval; the database would have refused them.

## 0.2.0 — 2026-08-27 — M0 lands: it runs

Askwell starts on a clean machine and says it is ready.

```
podman compose up -d      four containers, plus a bridge
scripts/dev.sh inference  llama.cpp, natively, on the host
http://127.0.0.1:8000     the shell, on loopback and nowhere else

database      reachable      assistant: ready
queue         reachable      model:     Qwen3.5-4B-Q4_K_M.gguf
worker        reachable
inference     reachable
egress_proxy  reachable
```

### Added in this release

`M0-SHELL-FE-017a` — the left rail becomes a reachable drawer below the breakpoint, with a scrim that dismisses on click and on Escape, and focus that returns to the control on close. The rail is the only route to sources, memory and settings; hiding it without a way back strands the user.

### What M0 leaves behind

Twenty-one tickets, 216 tests, and a stack whose central claims are checked rather than asserted: an attempt to reach the internet is refused and counted, the API answers on loopback and nowhere else, the audit log cannot be rewritten by the application because it lacks the grant, and every schema invariant is enforced by the database rather than by remembering.

### Known, and written down rather than discovered later

- Inference needs three native processes, not one ([#89](https://github.com/Rumeasiyan/askwell/issues/89)) — embeddings from the generation model are the wrong dimension for the schema, and reranking needs its own model. Blocks M1 retrieval.
- One container, the inference bridge, has host networking. `docs/architecture.md` §5 names it rather than glossing it.
- The 8 GB "slow but usable" claim is still unmeasured ([#49](https://github.com/Rumeasiyan/askwell/issues/49)).

## 0.1.20 — 2026-08-27

`M0-SHELL-FE-017`. The application shell.

### Added

- The three-column layout: left rail, centre column, and the provenance margin **reserved even when empty** — its permanence is what makes an uncited claim visibly wrong.
- Route stubs for Library, Memory and Settings, each with its empty state rather than a blank page.
- A status banner that distinguishes Askwell not answering from the assistant not answering, names what still works, and says so plainly when health cannot be read at all.

### Changed

- The "interface not built" page now also covers the case where it *was* built and the container is holding a replaced directory — which is what actually happens when you rebuild the frontend with the stack up.

## 0.1.19 — 2026-08-27

`M0-MODEL-BE-020`. The two causes of "the assistant is unavailable", kept apart.

### Added

- `GET /assistant` — whether the assistant can answer, the cause when it cannot, the likely fix, and **what still works**. No two causes share a headline, and a test asserts it.
- The supervisor heartbeats while it runs, and handles `SIGTERM`.

### Fixed

- **A killed supervisor left the API reporting the assistant available.** The state file said `ready` and nothing was keeping it current. `SIGTERM` now writes `stopped`; a state older than three missed heartbeats is treated as stopped rather than believed, which covers `SIGKILL` and a machine losing power.

## 0.1.18 — 2026-08-27

`M0-MODEL-BE-019`. The inference client.

### Added

- `askwell.inference.client` — generation, embedding and reranking over the Unix socket, with `InferenceUnavailable` and `InferenceFailed` as separate exceptions so callers can degrade to search rather than showing an error.
- Availability is checked against the supervisor's state file before the request, so the caller gets "no model file at /x.gguf" rather than a connection error.

### Changed

- The supervised process now runs with `--embeddings --pooling mean`.

### Found

- **One process cannot serve all three.** Reranking needs `--reranking` and a reranker model; embeddings from the generation model are 2560 dimensions where the schema is `vector(1024)`. Askwell needs three native processes. Filed as [#89](https://github.com/Rumeasiyan/askwell/issues/89), blocking M1 retrieval.

## 0.1.17 — 2026-08-27

`M0-MODEL-DEPLOY-018`. Native inference, supervised on the host.

### Added

- `deploy/inference/askwell-inference` — a standalone, standard-library-only supervisor. It starts llama.cpp, restarts it with backoff, stops trying after five consecutive failures, and publishes what it knows to a state file.
- `askwell.inference.bridge` — the Unix socket the containers reach inference through, owned by a container because SELinux refuses `container_t` connecting to an `unconfined_t` listener.
- The health surface now reports the loaded model and whether acceleration is in use, which a socket that opens cannot say.
- `scripts/dev.sh inference`.

### Changed

- `ASKWELL_INFERENCE_SOCKET` replaces `ASKWELL_INFERENCE_HOST` and `ASKWELL_INFERENCE_PORT`. Every service is on a network with no route off the machine, so there is no address to dial.
- One container — the inference bridge — runs with host networking, and `docs/architecture.md` §5 now names it rather than glossing it.

## 0.1.16 — 2026-08-27

`M0-SHELL-SESS-016`. The local session — which is not a login and must never become one.

### Added

- A signed session cookie established silently when the interface loads. No password, no roles, no recovery, **no sign-in screen anywhere**.
- The signing secret lives in the `settings` table, generated on first use, so a session survives a stack restart and travels with the data it protects.
- Cross-origin requests refused: another site's page reaching into Askwell with the user's own cookie is the reason the check exists.
- `/health` is exempt and it is the only exemption — a test keeps the list at one entry.

## 0.1.15 — 2026-08-27

`M0-STACK-SEC-012`. Loopback-only, proved from outside the machine.

### Added

- `scripts/verify-localhost-binding.sh` — part of the release checklist. Checks what the port is bound to, what each container publishes, and whether the machine answers on its own addresses from another network namespace.
- A static check on `compose.yaml`, so this runs on every push without a stack being up.
- `docs/architecture.md` §5.0 records what the check does and why its three parts are in that order.

## 0.1.14 — 2026-08-27

`M0-STACK-SEC-011`. The refusal count, as a fact rather than a reassurance.

### Added

- `GET /network` — the proxy's own counters, the recent refusals with their destinations, and the cap on that list stated rather than implied.
- The proxy establishes both counters at startup and records that it is reporting, so an absent counter means "the proxy has never run" rather than "nothing has been refused".

### Changed

- If the counters cannot be read the answer is **unavailable**, never zero. Zero and unknown look identical to a reader and mean opposite things, and "nothing has tried to leave this machine" is the strongest claim the product makes.

## 0.1.13 — 2026-08-27

`M0-STACK-SEC-010`. The default-deny egress proxy — C1's enforcement point.

### Added

- `askwell.egress` and an `egress-proxy` service. It never forwards anything: in local mode there are no allowed destinations, and a test asserts no allowlist has been added.
- A Compose network declared `internal`, so every service but the proxy has **no route off the machine**. Bypassing the proxy finds nothing rather than finding another way out.
- Refusals logged with the destination and the originating service, resolved to a container name, and counted in Redis for the settings surface.
- `docs/architecture.md` §5.1 — how it is built, and how a destination *would* be authorised without authorising any.

### Fixed

- **The health probe was counted as a refused egress attempt.** Askwell checks the proxy by opening a connection and closing it, which added one to the refusal figure every few seconds — turning a number that means "something tried to phone home" into one that means "Askwell is running".

## 0.1.12 — 2026-08-27

`M0-FOUND-DOC-008`. Version and changelog discipline, enforced rather than practised.

### Added

- The frontend reads the version from the repository's `VERSION` file at build time and renders it, so the About screen has something to derive rather than repeat.
- `web/scripts/check-version.mjs` and six tests: the changelog must have an entry for the current version, entries must be newest-first, no version may appear twice, and `web/package.json` must declare no version of its own.

### Fixed

- `0.1.0` had **two** changelog headings — the rewrite and the initial state, both legitimately at that version because no code existed. One version is one entry; a reader looking up `0.1.0` should find all of it in one place. Merged.

## 0.1.11 — 2026-08-27

`M0-FOUND-SEC-007`. The example environment file, and the check that keeps it true.

### Added

- A test that fails when a variable is read by the application, or referenced by `compose.yaml`, and is missing from `.env.example` — and in the other direction, when the file lists something nothing reads.
- Ignore rules for real environment files in every shape people write them, and for generated credential material that does not exist yet. The alternative is adding the rule in the same commit that first writes a key, which is the commit most likely to be in a hurry.

### Changed

- `.env.example` now lists all 23 variables with what each is for. It listed five.

## 0.1.10 — 2026-08-27

`M0-FOUND-DEPLOY-006`. Continuous integration.

### Added

- `.github/workflows/ci.yml` — three jobs on every push and pull request: the API's checks, the database-backed suite, and the frontend. Everything runs through `scripts/dev.sh` inside the same images used locally, so a green run means the same thing in both places.
- `scripts/dev.sh build-api` / `build-web`, and `ASKWELL_CONTAINER` to select podman or docker.

### Changed

- `_env_value` reads the process environment before `.env`, so CI supplies credentials without writing a file it would have to clean up.
- The database host is a value rather than the literal Compose service name.

## 0.1.9 — 2026-08-27

`M0-FOUND-TEST-005`. The test harness, and what it guarantees.

### Added

- A disposable database per run: created, migrated from empty, dropped. Two runs cannot collide, and a database orphaned by a crashed run is swept up by the next one — by age read from its name, so a live run is never taken.
- `api/tests/test_harness.py` — the harness asserts its own promises, including that the migration chain applied from empty **with its invariants**, which creating the schema from model metadata would silently skip.
- `AGENTS.md` §6 records the test convention.

### Fixed

- **`scripts/dev.sh` mounted the repository with `:Z`**, a *private* SELinux relabel, so two containers sharing it relabelled it out from under each other. Two test runs at once failed with a permission error naming a file neither test had touched. Now `:z`.
- **A migration read configuration at import time**, which turned "enumerate the revisions" into "fail because the database password is not set". It is read inside `upgrade()`, where it is used.

## 0.1.8 — 2026-08-27

`M0-DATA-OBS-015`. Hash-chained audit stores, and the trace ring buffer.

### Added

- `askwell.audit` — both database-backed stores chain each record to the hash of the previous one, written in the caller's transaction so a decision that cannot be recorded does not happen. Verification walks the chain and names the record where it breaks.
- `askwell.traces` — a capped file ring buffer that never fails an action. Losing a trace costs nothing visible, because citations are a real table and do not rotate.
- `askwell-verify` — runs the chain check across both stores and exits non-zero on a break. The settings surface arrives in M7.
- 28 database-backed tests and 15 pure ones, including the `jsonb` round trip, racing writes, and a guard that the word "immutable" is only ever used to deny it.

### Fixed

- **A chain whose first record was deleted reported as intact.** `MISSING_GENESIS` has no single record to name, `first_break` was therefore `None`, and `intact` was derived from it. A verifier that says "fine" about a chain whose start was removed is worse than no verifier.
- **Verification read the chain in timestamp order** and reported perfectly good chains as broken when two records landed close together. It follows the links now: a chain defines its own order, and every available ordering column is worse.

## 0.1.7 — 2026-08-27

`M0-DATA-DB-014`. The invariants, in the migration that creates the tables.

### Added

- Five invariants the ORM will not express: no `UPDATE`/`DELETE`/`TRUNCATE` grant on either audit table (C6); one live version per `(source_id, sha256)`; a chunk with cleared content cannot keep its embedding; a clarification marked answered must carry an answer; and the non-cascading citation foreign key.
- `deploy/postgres/10-roles.sh` — creates `askwell_app` and `askwell_readonly`. Askwell connects as `askwell_app`, which owns nothing.
- `scripts/dev.sh test-db` — 18 database-backed tests, deselected from the default run and failing rather than skipping when the database is absent.

### Changed

- **The application no longer connects as the table owner.** An owner bypasses its own grants, so the append-only guarantee would have been decorative — the `REVOKE` succeeds, the privilege listing looks right, and the application can still rewrite every audit record. See `docs/decisions.md`.
- `.env.example` carries `POSTGRES_APP_PASSWORD` and `POSTGRES_READONLY_PASSWORD`.

## 0.1.6 — 2026-08-27

`M0-DATA-DB-013`. The whole v1 schema in one reversible migration.

### Added

- `askwell.db` — the declarative base, the engine, and the thirteen tables of `docs/architecture.md` §7. No `organisations`, no `users`, no roles.
- One migration creating all of it, hand-edited after autogeneration for the vector extension, the configured embedding dimension, `content_tsv` as a generated column, and the Tamil text search configuration kept as a hedge.
- `ASKWELL_EMBEDDING_DIMENSIONS` — the width of every embedding column, so changing model is a configuration change plus a re-embed rather than a schema edit.
- `scripts/dev.sh db` and `scripts/dev.sh psql`.
- Fourteen model tests asserting the properties §7 calls load-bearing, without needing a database.

### Fixed

- **Column defaults were Python-side only.** They applied to rows the ORM inserted and to nothing else, so a migration, a `psql` session or a repair script hit a `NOT NULL` violation on a column that appeared to have a default. Found by inserting a document by hand. They are `server_default` now, and a test asserts it.

### Changed

- psycopg 3 is the database driver for both the async application and Alembic's synchronous path. asyncpg is faster on paper but cannot do the sync half, and two drivers means two sets of type adapters and two failure modes on a machine where nobody is watching.

## 0.1.5 — 2026-08-27

`M0-STACK-DEPLOY-009`. The stack comes up with one command.

### Added

- `compose.yaml` — `api`, `postgres` (pgvector, PG 18.6), `redis` and `worker`, with named volumes, health declarations and startup ordering. The egress proxy, sandbox database and voice are deliberately absent; they arrive in their own tickets.
- `askwell.worker` — the arq worker and a `ping` job, which is the cheapest end-to-end proof the queue is wired up.
- `.env.example` — the variables the stack needs. `M0-FOUND-SEC-007` completes it.

### Fixed

- **The worker was reported unreachable while running.** It was probed by opening a TCP socket, and an arq worker consumes a queue without listening on anything — so a healthy worker read as down, every time. It is now probed through the health record arq publishes into Redis, which distinguishes "the queue is down" from "the queue is up and the worker is not running". Those need different actions from the user.

### Changed

- `ASKWELL_WORKER_HOST` and `ASKWELL_WORKER_PORT` are gone, replaced by `ASKWELL_WORKER_HEALTH_KEY`.

## 0.1.4 — 2026-08-27

`M0-FOUND-DEPLOY-004`. The API serves the interface. The `web` container is gone from the topology.

### Added

- `askwell.interface` — static asset serving with a deliberate route fallback, per-file cache behaviour, and containment checked after `resolve()` so `..` and symlinks are already collapsed.
- `ASKWELL_WEB_ASSETS_DIR` — where the built interface lives.
- `web/app/not-found.tsx` — the product's own not-found page. Next's default is hardcoded black-on-white and drops the user out of the interface entirely.
- Fourteen tests covering the two requirements that pull against each other, five path-escape attempts and a symlink, cache headers per file kind, and the missing-build case.

### Changed

- Content-hashed assets are cached for a year and marked immutable; HTML is `no-cache`. The HTML is what points at the hashed filenames, so caching both the same way leaves a user on the old bundle after an update with no reason to suspect it.
- A missing build returns a readable page naming the directory and the command, at HTTP 503 — not a blank page. `/health` keeps working, which is what someone with a broken install actually needs.

## 0.1.3 — 2026-08-26

`M0-FOUND-FE-003`. The frontend, pinned as one verified set.

### Added

- `web/` — Next.js 16.3.3, React 19.2.8, Tailwind 4.3.3, pnpm 11.24.0, built to static assets in `web/out`. Every dependency is an exact version; there is not a single range operator in `package.json`.
- `web/app/globals.css` — the design tokens from `docs/ux/design-system.md` §2–§4, defined once. `--rule-strong` is its own token, not an alias of `--rule`. Depth is `--inset` and `--drop`, per theme.
- `web/scripts/contrast.mjs` — measures all 19 token pairs in both themes and fails below 4.5:1 for text or 3:1 for UI lines. Figures recorded in `docs/ux/design-system.md` §8.
- `web/scripts/check-tokens.mjs` — fails on a literal colour or a literal shadow anywhere outside the token definition, and on a depth token that does not differ between themes.
- `web/scripts/check-offline.mjs` — scans the built output for anything that would reach the network, by position rather than by pattern (C1).
- `web/Dockerfile` and `scripts/dev.sh web-*` — the Node toolchain lives in an image, like the Python one. Every frontend command runs with `--network=none` except `web-install`.

### Changed

- `docs/ux/design-system.md` §8 now records measured contrast figures rather than asserting a floor.

## 0.1.2 — 2026-08-26

`M0-FOUND-BE-002`. The API application, its configuration, its logging and its health surface.

### Added

- `askwell.config` — typed settings from `ASKWELL_*` environment variables. Refuses to start on unusable configuration and names every offending variable at once, by the name a person actually typed. An unknown `ASKWELL_*` variable is reported rather than ignored, because a typo otherwise leaves the setting it was meant to change silently on its default.
- `askwell.logging` — structlog, JSON to stderr, ISO-8601 UTC timestamps. Redaction is a processor, not a convention: anything whose key looks like a credential, and every `SecretStr` whatever its key is called, is replaced at any depth. Standard-library logs — uvicorn's included — are rendered by the same renderer, so the stream is parseable throughout.
- `askwell.health` — five components probed independently and concurrently. Name resolution is separate from connection so that "does not resolve" and "is not answering yet" are different messages, because they need different actions from the user.
- `askwell.app` — FastAPI application, `GET /health`, startup and shutdown logging with resolved profile and component states, and an error handler that shows the exception in development and a stated reason otherwise.
- `askwell-api` console entry point.

### Changed

- Logger caching is off. structlog binds a cached logger to whatever configuration was live at first use, and modules take their loggers at import time — before configuration is read — so a cached logger silently ignores it.

## 0.1.1 — 2026-08-26

First product code. `M0-FOUND-DEPLOY-001`.

### Added

- `api/Dockerfile` — API image pinned to Python 3.12, carrying `uv`, `ruff`, `mypy` and `pytest` inside it. The host needs Podman and nothing else. The build fails loudly if the base image ever drifts off 3.12.
- `api/pyproject.toml`, `api/uv.lock` — dependency manifest and lockfile. The lockfile is the pin; the manifest holds only bounds.
- `api/hatch_build.py` — reads the package version from the repository's `VERSION` file, so there is no second version to maintain.
- `api/src/askwell/` — the package, with version resolution that prefers the `VERSION` file over stamped metadata so a bump is visible without reinstalling.
- `api/tests/test_version.py` — five tests, including one that scans the tree for a second declared version string.
- `scripts/dev.sh` — runs lint, format, typecheck and tests inside the image against the working tree. Every command runs with `--network=none` except `lock`, which needs an index and says so.

### Changed

- `AGENTS.md` §5 — the commands table now lists commands that have been run, not commands that are intended.
- `AGENTS.md` §7 — tickets inside a phase are `PATCH`; the phase landing is the `MINOR`. Previously the two rules in that section contradicted each other for any phase with more than one ticket.

## 0.1.0 — 2026-08-10

Two things happened at this version and the number did not move, deliberately:
no application code existed, so no user-visible behaviour changed. They are
recorded here as one entry rather than two headings, because one version is
one entry — a reader looking up `0.1.0` should find all of it in one place.

### The rewrite

Product repositioned. The previous documentation described on-premise software sold to government ministries; Askwell is a free local install for one individual professional. Version unchanged — no code exists, so no user-visible behaviour changed.

### Added

- `docs/architecture.md` — technical decisions, topology, auth, data model, retrieval, security. Split out of the PRD.
- `docs/data-sources.md` — files, CSV, SQL dump import with sandbox isolation, live connections.
- `docs/memory-and-clarification.md` — the clarification loop and permanent memory. New capability and the product's differentiator.
- `docs/audit-log.md` — three separate stores with different retention and failure behaviour; hash-chained.
- `docs/build-plan.md` — phases, acceptance criteria, quality gate, repo layout.
- Constraint C3: an imported dump is untrusted code and loads only into an isolated sandbox Postgres.
- Quality-gate category for memory application (15 tasks) — without it the differentiator has no test.

### Changed

- `docs/PRD.md` rewritten as a **business-only** document, shareable as a pitch. All implementation detail moved out.
- Single user, single machine. No organisations, users, roles, RBAC, seat tiers, licence keys or high availability.
- C1 now permits an explicit per-conversation online-AI opt-in instead of forbidding all egress.
- C6 restated as **tamper-evident, not immutable** — the user owns the disk, and any stronger claim is false.
- Authentication reduced to a local session plus an optional at-rest passphrase. JWT/Argon2id/TOTP/blacklist removed.
- Deployment profiles rebuilt around personal hardware; floor drops to 8GB and the installer warns rather than refuses.
- `docs/success-metrics.md` fully re-derived — there is no pilot. Adds clarification-loop metrics.
- `docs/states-and-edge-cases.md` — licence, seat-cap, session-expiry and permission-denial states removed; disk-budget, online-mode and clarification states added.
- Issue templates and labels updated to the new constraint numbering.

### Settled defaults

- Clarification cap of 5 questions per source, with a documented ranking for what makes the cut.
- Log budget 2 GB or 5% of free disk, whichever smaller; 12-month interaction retention; decisions never pruned.
- Sandbox caps of 5 GB and 10 minutes per import.
- v1 imports PostgreSQL dumps only — MySQL and SQL Server via live connection or CSV.
- No telemetry through Phase 6, accepting that primary retention metrics become unobservable.

### Removed

- Constraint C7-as-was (column-level access control per role) — it protected one role from another, and there are no roles.
- Multi-node high availability, permanently (#4).

### The initial state

First versioned state. No application code — the repository is documentation only, Phase 0 not yet started.

### Added

- `AGENTS.md` — working agreements, hard constraints, commands, conventions, versioning, tracker and session workflow.
- `docs/decisions.md` — append-only decision log, seeded from git history and `docs/PRD.md` §5.1.
- `VERSION` — canonical application version, single source of truth.
- `CHANGELOG.md` — this file.
- `.github/ISSUE_TEMPLATE/` — issue templates for tasks, bugs, and blocked decisions.
- `README.md` — was missing; the repository had no entry point for a human arriving cold.
- `docs/success-metrics.md` — what "working" means in numbers in production, distinct from the model eval gate. Abstention rate reframed as a 5–20% band with a citation-correctness counter-metric, because it is trivially gamed by lowering the retrieval threshold.
- `docs/states-and-edge-cases.md` — every state a user can be in across chat, ingestion, database QA, voice, admin, plus collected empty states. Surfaced six product decisions with no PRD answer (issues #10–#15).
- Repository labels for build phase (`phase:0`…`phase:6`) and hard constraints (`constraint:*`).

### Changed

- `CLAUDE.md` reduced to a shim importing `AGENTS.md`; its rules now live in `AGENTS.md`.
- **v1 scope is now English-only.** Tamil and Sinhala moved out of the phase list to v2 (`docs/PRD.md` §1.2). Resolves §11 items 1 and 2, closing issues #1 and #2.
  - Phase 4 estimate 2 weeks → 1.5; acceptance is an English round trip only, no language detection.
  - `edge` profile no longer degraded for voice — whisper `small` serves all three profiles.
  - Eval gate 160 → 140 tasks; Tamil category removed, `eval/suites/tamil.jsonl` not created.
  - Phase 1 acceptance changed from a scanned Tamil PDF to a scanned English one.
  - Hedges kept so Tamil is later work rather than a corpus migration: `bge-m3` embeddings, Tamil-aware Postgres FTS config, `tam` OCR traineddata, pluggable TTS interface.
  - Label `tamil` replaced by `v2:language`.
- `PRD.md` and `BRAIN.md` moved into `docs/`. Root now holds only what a tool or convention requires there.
- `docs/PRD.md` §10 split into what exists and what is planned, with a table of which directory arrives in which phase — the previous single tree described almost nothing that existed, with no marker saying so.

### Fixed

- `docs/PRD.md` §5.2 container count: six → seven.
- `docs/PRD.md` §5.3 deployment-profile models: `Qwen3.5 4B` → `Qwen3 4B`, `Qwen3.6 27B` → `Qwen3 32B` (neither original was a real release).
- `docs/PRD.md` §7 eval harness path: `bench/` → `eval/bench.py`, matching §10.
- `docs/PRD.md` owner name, and `Rumesh` → `Rumeasiyan` in `docs/PRD.md` §11 and `docs/BRAIN.md`.
- `docs/BRAIN.md` blocker 4 no longer contradicts `docs/PRD.md` §11.4 about whether it affects Phase 0.
- `prd.md` renamed to `PRD.md` (the reference in §10 was already capitalised), then moved with `BRAIN.md` into `docs/`.
