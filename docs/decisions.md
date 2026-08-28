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

## 2026-08-28 — The one download in the product runs on the host, not through the proxy

**Decision:** Model acquisition does not become a third exception to C1's default-deny egress. The API writes a request file into the models directory and reads progress back; the host supervisor that already runs `llama.cpp` performs the fetch, verifies the published sha256, and discards a file that does not match. No container gains a route out.

**Why:** `M1-LIB-FE-052` shipped a download that ran inside the `api` container and was refused by Askwell's own egress proxy — `403 Forbidden`, logged, exactly as designed. That is C1 working against a call the architecture never authorised, not a bug in the download code.

The obvious repair is an allowlist entry for `huggingface.co`. It was rejected because it costs the property that makes the proxy worth having. `egress.py` says it plainly: the proxy "cannot leak by misconfiguration because there is no configuration that would let it." Add one allowlist and that sentence becomes false — the proxy joins the ordinary category of things that are safe when configured correctly, and the audit question changes from "can it forward?" to "is the list right today?" for the rest of the product's life. One feature is not worth that trade.

A dedicated fetcher container on both networks was also weighed. It is narrow and auditable, but it is still an `internal`→`egress` bridge, which is the shape the topology exists to forbid, and it is new infrastructure to keep correct.

The host already has the precedent and the machinery. Inference runs natively because GPU acceleration only works from the host; the supervisor already writes a state file the API reads across the container boundary. The download is the same shape of problem and gets the same shape of answer.

**Consequences:** The wizard's download step needs the host supervisor running — the same process the user already starts for inference — and says so when it is not. The request carries the checksum rather than the host looking it up, so a fetcher deciding for itself what "correct" means is not possible. Two filenames are now contract between the container and the host, `fetch-request.json` and `fetch-progress.json`, and drift in either is a silent failure — `test_model_fetch_host.py` exercises the host side directly against a stubbed `urlopen` so nothing in that path is only reasoned about.

An air-gapped install writes no request and makes no network call at all, which was already the manual-file path and is now the only difference between the two.

**Refs:** issue 192; `docs/architecture.md` §5.1; `api/src/askwell/model_download.py`; `deploy/inference/askwell-inference`; `api/tests/test_model_fetch_host.py`.

## 2026-08-28 — The welcome sequence's model download writes inside the API container; it does not (yet) reach the host path the inference supervisor reads

**Decision:** `M1-LIB-FE-052`. `askwell.model_download.ModelDownloadManager` downloads the generation model to `Settings.inference_model_path` — real progress, `Range`-based resume from whatever `<target>.part` already holds, sha256 verification, a manual-file path for an air-gapped machine — and stops there. It does not attempt to place the file anywhere the host-side `llama-server` supervisor (`M0-MODEL-DEPLOY-018`) would find it, because as configured today it cannot: `.env.example`'s own comment on the model-path variables says "Read by the host-side supervisor only. The containers never see these," `compose.yaml`'s `api` service has no volume mount for the models directory, and `Path.expanduser()` resolves `~` against whichever process calls it — `/root` inside the container, the real user's home on the host. Passing the same env var into the container would not fix this; it would make the mismatch silent instead of absent.

**Why:** three options existed once the mismatch was found mid-session (verified live: `POST /setup/model/verify-manual` against the running stack reported `/root/.local/share/askwell/models/model.gguf`, not the `.env`-configured host path). Bridging it immediately — an identity-mounted models directory using `${HOME}`-interpolated compose variables, the same pattern `ASKWELL_ROOTS_MOUNT` already established for user files — was rejected for *this* ticket specifically because it touches deployment topology (`compose.yaml`, `.env.example`, and the installer across three platforms) that a welcome-screen ticket has no mandate to decide unreviewed, and `AGENTS.md` §4 asks that a change touching more than three files get agreement first. Silently declaring the container's own copy "the" model file and leaving the supervisor unaware was rejected outright — that is exactly the kind of guess-and-continue `AGENTS.md` §4 forbids. Filing it and shipping the welcome screen against the API surface that exists today (which is honest: `GET /health` already reports `inference: unreachable` independently of anything this ticket touches, and the Ask screen already renders that state) was the only option that neither guesses at an infrastructure decision nor blocks a frontend ticket on one.

**Consequences:** as deployed today, a user who completes the model-download step in the browser sees a verified, `ready` file — but the assistant remains `inference: unreachable` until the host supervisor is separately pointed at wherever that file actually landed. Closing the gap (issue #191) is a deployment-topology decision, not a `M1-LIB-FE-052` follow-up in the ordinary sense — it likely lands before this feature is truly end-to-end for a real installer, and whoever picks it up should read this entry and issue #191 before choosing a mount strategy.

**Refs:** `api/src/askwell/model_download.py`, `api/src/askwell/config.py` (`_expand`), `compose.yaml` (`api` service, ~lines 140-211), `.env.example` (~lines 140-165), `docs/decisions.md`'s roots-mount entry (identity-mount precedent), issue #191.

**Addendum, same day:** a live walkthrough surfaced a second, more fundamental block on top of the one above — `docs/architecture.md` §5.1 states the egress proxy grants *no* destinations in local mode, only two named, scoped, per-use exceptions (online AI, web search), and asserts a test prevents a third from being added informally. The model download this ticket built calls out from inside the `api` container, which the proxy correctly refused (`model_download_failed error='403 Forbidden'`, live log, 2026-08-28). This is C1 working as designed against a call the architecture never authorised, not a bug in the download code. Filed separately as issue #192 rather than folded into the entry above: the fix shapes are different (that one is a compose/volume topology question; this one is whether the model download becomes a third egress-proxy exception or moves to the browser, which decides whether `askwell.model_download`'s server-side fetch survives at all). Recommendation there is to keep the browser as the actual downloader and reduce the API's role to verification — see the issue for the reasoning.

---

## 2026-08-28 — Expanding a past turn gets its own inline margin; paging is a client-side reveal, not a network read

**Decision:** `M1-CONV-FE-179` (expanding a collapsed turn, its source count, and paging older turns) is built entirely on data `AskProvider` already holds in memory. Two consequences of that: (1) an expanded past turn's provenance cards render with `InlineSourceCards` (`M1-CITE-FE-044`'s below-breakpoint variant) unconditionally, at every width, rather than borrowing the shared `<aside>` (`ProvenanceMargin`) that the live turn already owns; (2) "older turns page in on scroll" (`conversation.md` §5, §7) is implemented as `conversationWindow` (`web/lib/ask.ts`) revealing more of the same in-memory `turns` array, never a request that can fail.

**Why:** The shared margin `<aside>` (`shell.tsx`) is wired to exactly one turn — `useLiveTurn()` — because until this ticket only one turn was ever expanded at a time. This ticket's own scope explicitly permits several past turns expanded at once ("the user chose it"), and there is exactly one aside slot. Building a second, dynamic margin surface that could host an arbitrary number of simultaneously-expanded turns without stealing the live turn's own space is real scope beyond "one expansion, one scroll target and one paging rule, over presentation that already exists" (this ticket's own granularity note) — so each expanded past turn gets its own inline margin instead, the same component and the same `--rule-strong` edge the ticket already specifies for the narrow-window case, just used unconditionally rather than only below the breakpoint.

For paging: `docs/BRAIN.md` and issue #156 both record that `conversation_id` is not threaded across turns — nothing survives a page reload today, so there is no persisted, re-fetchable conversation history for a backend "paged read" to serve, and no such endpoint exists (`api/src/askwell/ask.py` has no `GET` for past turns at all). Building a network-shaped paging UI (a request that can fail, with retry) against data that cannot yet outlive the tab would be exactly the kind of stub the build process warns against — a state that looks handled but can never actually occur. `conversationWindow` instead treats "paging in on scroll" as revealing more of the array `AskProvider` already has, oldest last, twenty at a time (`conversation.md` §7's settled page size). The moment a past conversation can be reloaded, this same function is what a real fetched page slots into — the windowing rule does not change, only where the older turns come from.

**Consequences:** The "paging fails to load older turns, offers to retry" edge case in this ticket's own edge-case list cannot be exercised yet — it depends on conversation persistence (issue #156) existing first. Filed as issue #199 rather than silently dropped, naming both the missing `GET` endpoint and this edge case as the two things to build against once persistence lands. An expanded past turn's hover-to-raise leader line (`M1-CITE-FE-044`) does not apply to it — `useLiveLeaderPairs` only pairs the live turn's claims and cards — which is unchanged behaviour (past turns never had leader lines before this ticket either) rather than a regression.

**Refs:** `docs/ux/conversation.md` §2, §3, §5, §7; `M1-CONV-FE-179`; issue #156; issue #199; `web/components/ask/ask-screen.tsx`; `web/lib/ask.ts`.

---

## 2026-08-28 — The `done` SSE event carries the stored turn summary and source count, closing a gap `M1-CONV-BE-177` left open on purpose

**Decision:** `askwell.ask`'s `done` event (both the live path in `_run_generation` and the reconnect-replay path in `_load_finished`/`ask_stream`) now includes `summary` and `source_count` — the exact `TurnSummary` already computed and written to `messages` — rather than only `status` and `reason`.

**Why:** `M1-CONV-BE-177` deliberately stopped at storage: its own manual-test doc reads the two values back with `scripts/dev.sh psql` because "nothing renders these values on screen yet" was correctly out of that ticket's scope. But `M1-CONV-FE-178` (collapsing a past turn to its question, summary and source count) then had no route to either value at all — no conversation-history endpoint exists yet, and `conversation.md` §6 explicitly forbids re-deriving a summary from the corpus on read, so a client-side recomputation was not an option either. Two fixes were considered: build a `GET /conversations/{id}` history endpoint (real scope creep for a frontend-labelled ticket, and speculative ahead of needing to reload history across a page load, which nothing in Askwell does yet), or thread the value already computed for the row onto the wire that already carries every other per-turn fact this screen needs. The second cost two fields on an existing event and reusing a variable already in scope at the emit site.

**Consequences:** the collapsed-turn summary and count are guaranteed to match what was written to `messages` in the same request, because they are the same value, not a second computation. A future conversation-history endpoint (needed once page load restores past turns, `ask-state.tsx`'s own "not threaded across turns" note, issue #156) should read from `messages.summary`/`messages.source_count` directly rather than reintroducing a second code path.

**Refs:** `M1-CONV-FE-178`, `M1-CONV-BE-177`, `api/src/askwell/ask.py`, `docs/ux/conversation.md` §2/§6.

## 2026-08-28 — A moved file's status is carried by `missing_since` alone, never by `documents.status`; a moved-or-renamed file joins the flagged-OCR pattern rather than a new source status

**Decision:** `M1-VIEW-BE-049`. A document whose recorded path no longer resolves does not change `documents.status` — it stays whatever it was (`ready`, ordinarily) and only gains a `missing_since` timestamp. `askwell.ingest.Coverage` grew a `missing` count alongside the existing `flagged` (poor-OCR) one, and `source_status`/`_attention_reason` treat it exactly the same way flagged is treated: the source becomes `attention`, stays askable, and names how many files need relocating. Detection itself is two call sites sharing one decision — `askwell.documents._availability` at open time, `askwell.ingest.sweep_missing` on a timer (`worker.py`'s new `check_missing` cron, `ASKWELL_MISSING_CHECK_SECONDS`) — both of which check `roots.source_availability` on the document's source first and only mark it `missing_since` when that says the root itself is reachable. A whole root being unmounted, removed or unreadable is reported as `root_unavailable` and never as its documents being missing.

**Why:** a document status of `attention` or a new `moved` value was considered and rejected — `DOCUMENT_STATUSES` already means "where is this document in the pipeline," and a moved file has not lost its place there; it is fully indexed and fully askable, it just needs its path repaired. Overloading `status` for this would make every reader of `documents.status` (the library, coverage counting, retrieval) also have to know that `attention` sometimes means "re-index failed" and sometimes means "click relocate," which is exactly the kind of collapse the ticket's own "missing and deleted must never be conflated" rule warns against one level up. Following the `flagged`/OCR pattern instead — a fact `Coverage` carries separately from `status`, surfaced through the source's existing `attention` state and its `last_error` sentence — reuses a shape the library already knows how to render, rather than inventing a second one beside it. Reusing `roots.source_availability` for the root-vs-file distinction (rather than a second, narrower "is this one path reachable" check) was the only way to guarantee the two surfaces — the open-time check and the timer — cannot answer that question differently; both call the same function against the same live/removed root views.

**Consequences:** any future stage that reads `documents.status` to mean "is this document askable" continues to work unmodified for a moved document — it is still `ready`. Anything that needs to know about a moved file specifically has to read `missing_since`, which is the only place that fact lives; a query that filters on `status = 'attention'` alone will not find it. `askwell.documents._availability` and `askwell.ingest.sweep_missing` intentionally do not share code — `_availability` depends on `askwell.ingest.refresh_source`, so the reverse import would be a cycle — so a change to the missing/root-unavailable decision has to be made in both places, and each one's docstring says so.

**Refs:** `api/src/askwell/documents.py` (`_availability`, `RelocateRequest`), `api/src/askwell/ingest.py` (`Coverage.missing`, `sweep_missing`, `source_status`, `_attention_reason`), `api/src/askwell/worker.py` (`check_missing` cron), `api/src/askwell/config.py` (`missing_check_seconds`), `web/components/documents/viewer-shared.tsx` (`MovedFileNotice`, `RootUnavailableNotice`), `docs/ux/source-viewer.md` §4, `docs/ux/library.md` §5.

---

## 2026-08-28 — The context rail reads the live turn from memory, so provenance cards must navigate client-side; a scoped question survives the route change through a module-level slot, not the event alone

**Decision:** `M1-VIEW-FE-048`. The context rail's "back to answer" and "which claim" depend on `AskProvider`'s in-memory turn (`ask-state.tsx`) still existing when someone lands on the viewer — so `provenance-margin.tsx`'s card link changed from a plain `<a href>` to `next/link`'s `Link`. A full page load would drop that state entirely, same as any browser navigation drops any React tree; only a client-side route change (which App Router layouts, including `AskProvider`, survive) keeps it. Separately, "ask about this source" calls `fillComposer` and then `router.push("/")`; because the route change is not synchronous, `fillComposer` now writes to a module-level `pendingFill` slot before dispatching its event, and `Composer`'s mount effect drains that slot first, so the scope is not lost if the Ask screen has not mounted yet when the event fires.

**Why:** the `<a>` tag was not a bug introduced by this ticket — `M1-VIEW-FE-046` never needed the live turn to survive navigation, since the viewer's own read of `?turn=`/`?claim=`/`?chunk=` did not exist yet. This ticket is the first one that needs `AskProvider` state to outlive a trip to `/documents/` and back, and a plain anchor tag silently breaks that the moment it ships, with no test catching it unless the test itself asserts a client-side transition. The `pendingFill` slot was chosen over two alternatives: (1) accepting the same race `shell.tsx`'s `⌘K` shortcut already has, on the reasoning that "whichever arrives second wins" is tolerable there because the only thing at stake is keyboard focus — rejected here because losing the *scope* silently produces an unscoped question with no visible sign anything went wrong, which is a worse failure than a keystroke doing nothing; (2) `sessionStorage`, which survives a real page reload and not just a client transition — rejected as more mechanism than the actual gap needs, since the state in question is already living in a module the whole app shares, the same pattern `citations.ts`'s `cardClickCount` already uses for exactly the same reason (module state that only needs to survive within one running tab).

**Consequences:** any future control that navigates to `/documents/` from inside the Ask screen's own React tree must also use client-side navigation, or it will silently break "back to answer" the same way the old `<a>` did — there is no lint rule catching this, only this entry and the code comment beside the `Link`. `superseded_at` on `GET /documents/{id}` is derived from the superseding document's own `added_at` rather than a new column, because `sources.py`'s `supersede()` already sets `superseded_by` and inserts the new row in one transaction — resolves issue #141 without the banner endpoint of its own that issue's recommendation (1) warned against building ahead of the screen that needed it.

**Refs:** `web/components/ask/provenance-margin.tsx`, `web/components/ask/ask-screen.tsx` (`fillComposer`, `pendingFill`), `web/components/documents/context-rail.tsx`, `api/src/askwell/documents.py`, issue #141.

---

## 2026-08-28 — The uncited-claim check excludes fact-usage answers rather than counting them compliant, and re-segments instead of trusting the citations table

**Decision:** `M1-CITE-TEST-045`. `askwell.agent.citation_check.check_citations` re-runs `segment_claims` against each stored assistant message's own `content`, rather than trusting that every `citations` row it can join to still reflects a real claim. A message carrying any `fact_usage` row is excluded from the checked total and reported separately as excluded, not folded into the compliant count and not flagged a violation.

**Why:** the whole point of the ticket is that `citations` rows and the answer text can drift apart — a row can be deleted, or a chunk it points at can stop existing meaningfully, without `messages.content` changing at all — so a check that only asked "does a citation row exist for this message" would measure the write path `M1-CITE-BE-042` already guarantees, not the thing C4 actually needs proven. Re-segmenting independently is what makes "delete a citation row and the check catches it" true rather than trivially true. Counting a `fact_usage` message compliant was rejected: nothing populates `fact_usage` before `M3`, so there is no way yet to tell a claim that correctly cites a memory fact apart from one that cites nothing at all, and calling it compliant would let a real uncited claim hide behind a `fact_usage` row inserted for an unrelated reason. Counting it a violation was also rejected, for the opposite reason — it would fail messages this check cannot yet judge fairly. Exclusion, named, is the only option that does not claim more than the check currently knows.

**Consequences:** the excluded count is not zero the moment `M3` starts writing `fact_usage` rows for real, and whoever builds that ticket should re-read this check before assuming a rising excluded count is fine — it will be, once fact-usage claims are actually verified elsewhere, but that verification does not exist yet either. Recording the check's result "alongside eval runs" (the ticket's own requirement) is deferred to whenever `eval/bench.py` exists (`M2`) — filed as [#182](https://github.com/Rumeasiyan/askwell/issues/182) rather than built against a guessed shape now.

**Refs:** `api/src/askwell/agent/citation_check.py`, `api/tests/test_citation_check.py`, `docs/success-metrics.md` §2, issue #182.

---

## 2026-08-28 — The document viewer is a query string, not a dynamic route segment

**Decision:** `M1-VIEW-FE-046`. `web/app/documents/page.tsx` is one static page. A document's id, the page to land on, and the two search targets for highlighting (`span` — the claim's own quoted words, `passage` — the full retrieved chunk) travel as query parameters (`/documents/?id=...&page=...&span=...&passage=...`), read client-side with `useSearchParams`. `web/lib/citations.ts`'s `documentHref` builds this; `web/components/ask/provenance-margin.tsx`'s card link was updated in the same change. This supersedes `M1-CITE-FE-043`'s own guess (2026-08-28, below) of `/documents/{document_id}?page=...`.

**Why:** `next.config.ts` sets `output: "export"` (`M0-FOUND-DEPLOY-004`'s decision, unrelated ticket, same file) — there is no server process on the user's machine to render a page on demand, so every route is a real directory written at build time. A dynamic path segment (`/documents/[id]`) under static export must enumerate every value it will ever take via `generateStaticParams`, and a document id is created at runtime when someone adds a file; it cannot be known at build time. The `[id]` form was not merely unbuilt, as the earlier decision assumed — it cannot be built at all under this app's own architecture, a fact `M1-CITE-FE-043`'s own session did not have reason to check since it was only wiring a link, not building the landing page the link pointed at. The query-string form needed no new insight to reach once this was noticed: one static page, everything else client-side.

**Consequences:** `M1-VIEW-FE-047` and `M1-VIEW-FE-048` build on this page and this parameter set rather than inventing a route of their own — `M1-VIEW-FE-048`'s own "back to the answer" and citation-stepping controls add further query parameters (or client-side state) to the same `/documents/` page, never a new path. Any future surface that needs to link to a specific passage in a specific document should reach for `documentHref`, not construct a URL inline — that function is the one place the parameter names are allowed to be decided.

**Refs:** `web/app/documents/page.tsx`, `web/components/documents/document-viewer.tsx`, `web/lib/citations.ts`, `web/components/ask/provenance-margin.tsx`, `docs/ux/source-viewer.md` §0 (Route).

---

## 2026-08-28 — Scores in the interaction record are strings; an audit write failure gets a second, separate write to mark the turn failed

**Decision:** `M1-ASK-OBS-041`. `audit_interactions`' `retrieved_chunks` stores each candidate's score as `str(candidate.score)`, not the raw `float`. Separately, the final write (`messages` upsert, citation inserts, `record()`) stays one transaction as before, but is now wrapped in `try`/`except AuditError`: on failure, a second, independent `session_scope` writes the `messages` row to `failed` with a stated reason, and the turn still emits its `done` event.

**Why:** `askwell.audit.canonical_payload` refuses floats outright (`PayloadNotHashable`) because Postgres's `jsonb` does not preserve a float's exact textual form, so a value hashed before the round trip and recomputed after it can disagree with itself — reporting tampering that never happened. `roots.py`/`sources.py`/`ingest.py`'s own audit payloads have never carried a float, so there was no existing precedent to follow; a string is the simplest of the two options `PayloadNotHashable`'s own message names ("a string, or an integer in a fixed unit"), and a similarity score has no natural fixed unit the way milliseconds or cents do. On the second half: before this ticket, an exception from `record()` propagated straight out of the background task `asyncio.create_task` started, uncaught — the transaction rolled back correctly (nothing unlogged persisted, `session_scope`'s own guarantee), but the turn's in-memory status stayed `running` forever and no `done` event was ever emitted, so a client watching the stream would hang rather than see a failure. The alternative considered was folding the failure handling into the existing `except Exception` block around retrieval and generation, higher up the function — rejected because that block is specifically about the assistant failing to answer, and an audit-store failure is a different fact (the answer was fine; saving the record of it was not), worth its own stated reason rather than being reported as "Askwell hit an error it did not expect while answering."

**Consequences:** a real audit-store outage (the interaction table specifically, not the whole database) now surfaces as a stated failure to a live client instead of a silent hang — the manual test this ticket's own testing notes describe ("make the interaction table unwritable and ask a fourth"). If the second, separate write also fails (the messages table is unwritable too, not just the audit tables), the row is left `running` and `reconcile_interrupted`'s existing startup sweep is the backstop, unchanged from before this ticket. Reversing the string-score choice would mean picking a fixed-point encoding (e.g. score × 10,000 as an integer) instead — viable, not done here because nothing yet reads `retrieved_chunks` downstream to need it, and a string is legible in a raw `psql` query without a divide-by-10000 in your head.

**Refs:** `api/src/askwell/ask.py`, `api/src/askwell/audit.py::canonical_payload`/`PayloadNotHashable`, `api/tests/test_ask_api.py`, issue #165.

---

## 2026-08-28 — Corpus-derived suggestions get a new endpoint, computed server-side, inside a frontend ticket

**Decision:** `M1-LIB-FE-051` calls for the Ask screen's empty-with-sources state to show up to three suggested questions "generated from what was actually ingested — real filenames and real terms", assembled without a model call. No ticket anywhere in `docs/backlog/` builds a way to read that data back out: `GET /ingest` (`M1-ADD-ING-025`, widened by `M1-LIB-FE-050`) only ever carries filenames for documents in a transient or failed state — a `ready` document's filename disappears from every array in that payload the moment it finishes, which is the normal case this ticket needs to read. There is no `GET /documents` or `GET /chunks` at all. A new `GET /suggestions` (`api/src/askwell/suggestions.py`) was added rather than filing this as blocked.

The heuristic itself also runs server-side, not client-side against raw rows: a ready document's first chunk carrying a heading names the question (`"What does {filename} say about {heading}?"`); failing that, its most frequent word outside a short stopword list (`"... mention about {term}?"`); failing that, the filename alone. Postgres already has the chunk content in front of it — the API returns three finished question strings, not filenames-plus-passages for the browser to guess with a second, duplicate heuristic in TypeScript.

**Why:** the alternative considered was widening `GET /ingest` again, the way `M1-LIB-FE-050`'s own entry above did for its three fields — rejected because `ingest.snapshot`'s per-document arrays exist to describe *problems and progress*, not the steady-state "ready and fine" case, and stuffing headings and passage text into a payload that is polled by SSE while the machine is indexing (`ingest.py`'s own "cheap even while busy" reasoning) is the wrong place to add a term-frequency scan. A dedicated, request-driven endpoint that only runs when the Ask screen actually needs three suggestions is cheaper in aggregate than computing them on every progress tick nobody asked for.

Doing the heuristic in Python rather than shipping raw headings/content to the client and matching `M1-CITE-FE-043`'s `segmentClaims`-mirrored-client-side pattern was also considered and rejected: that pattern exists there because the server's own claim numbering has to be reproduced exactly on both sides for the leader lines to line up. Nothing here needs two sides to agree — only one side needs to produce a sentence, and duplicating a tokenizer and a stopword list in TypeScript to save one field in a response body is not a trade worth making.

**Consequences:** `askwell.suggestions.suggested_questions` is a second, narrower door into `chunks` and `documents` beyond `askwell.retrieve` — a future ticket touching either table's shape should grep both. The stopword list and "most frequent word" heuristic are deliberately unsophisticated (`suggestions.py`'s own docstring says so); if suggestion quality is ever complained about, the fix is a better heuristic in this one function, not a model call at load time, which is the exact softening `ask.md` §6 warns against for a different state but the same reasoning applies here — cheap and occasionally dull beats an LLM call at the moment the machine is busiest.

**Refs:** `docs/ux/ask.md` §5, §8; `docs/ux/first-run.md` §6; `docs/backlog/M1-it-answers-from-my-documents.md` (`M1-LIB-FE-051`); `api/src/askwell/suggestions.py`; `api/tests/test_suggestions.py`; `web/lib/suggestions.ts`; `web/components/ask/ask-screen.tsx` (`useCorpusState`, `SuggestedQuestions`, `IndexingNotice`).

---

## 2026-08-28 — The library's backend surface is built inside its frontend ticket, and re-index is not retry

**Decision:** `M1-LIB-FE-050`. No `docs/backlog/` ticket anywhere — under any milestone — builds a "list sources" or "re-index a source" endpoint; the whole backlog's Backend section has no `M1-LIB-BE-*` at all. Rather than stopping the ticket on a dependency the backlog itself never named, three small additive changes went into `api/src/askwell/ingest.py` and `sources.py`, all reusing infrastructure `M1-ADD-ING-025`/`M1-EXTRACT-ING-029` already built rather than inventing new plumbing:

1. `GET /ingest`'s existing `sources` array (already aggregating per-source coverage for the add screen's own progress panel) gained `kind`, `added_at`, `last_error` — plain columns already on the `sources` row, just not previously selected — and a literal `open_clarifications: 0`, stubbed rather than backed by a table, matching the ticket's own "Known gaps: clarification counts are always zero" line. The existing `failures` array gained `source_id` (`j.source_id`, already on the row, just not previously selected) so a needs-attention expansion can attribute a failed document to its source without a second endpoint — `flagged` already carried it.
2. `POST /sources/{id}/reindex` is new: `askwell.ingest.reindex_source` resets every *live* document's `ingest_jobs` row to `queued` and clears its `ocr_confidence`, regardless of current state — unlike `retry`, which only touches `failed` rows. A re-index is requested because the source changed underneath Askwell, not because one document errored, so a document already `ready` goes back through the pipeline too. It records `source_reindex_requested` to the decisions store (the ticket's own "Audit/Logging Requirements: re-index is a decisions record") independently of `refresh_source`'s own `source_status_changed` record, which still fires for the resulting `attention`/`ready` → `queued` transition.
3. The library row's "size" column, named in the ticket's own Detailed Description and in `docs/ux/library.md` §2's shape table, was **not** built. `docs/ux/library.md` §6 settles this explicitly and more recently than §2: "index size is shown per source, in Settings rather than the library" — and no `size_bytes` column exists anywhere in the schema to source a per-document figure from even if the row wanted one. §6 is followed over §2 as the more specific, explicitly-settled statement.

**Why:** the alternative was filing "library needs a list endpoint" and "library needs a re-index endpoint" as blocked-on issues and stopping. Rejected for the list endpoint the same way `M1-CITE-FE-043`'s entry above rejected a new endpoint for citation cards: `GET /ingest` already computes exactly the aggregation a source row needs (`Coverage`, `_attention_reason`, per-document `failures`/`flagged`), one call earlier in a request path that already exists, for a one-line `SELECT` change with no schema impact. Filing a blocked-on ticket for three already-selectable columns would have stopped a frontend story on a gap the story itself could close in the same diff.

Re-index is a different shape of decision: it is new business logic, not an additive field, and the case for building it here rather than escalating is narrower — accepted because the whole operation is "reset the job row and let the pipeline that already exists run again," which is `retry`'s own logic with its `WHERE state = 'failed'` removed, not a new pipeline concept. A genuinely new capability (an `ASKWELL_ROOTS_MOUNT`-style config surface, a new table, a new stage) would have been the point to stop and ask rather than build.

**Consequences:** `GET /ingest`'s `sources` array and `failures` array are now a slightly wider public shape than `M1-ADD-ING-025` defined; any future ticket touching that snapshot should read `ingest.snapshot`'s docstring rather than assume the array is add-screen-only. `POST /sources/{id}/reindex` exists with no corresponding ticket ID in `docs/backlog/`; if one is later written for symmetry with the rest of the backend section, it should point back here rather than re-deriving the design. The library's row never shows a size figure — correct per §6, but worth knowing before someone "fixes" the omission against §2's now-superseded text.

**Refs:** `docs/ux/library.md` §2, §3, §6; `api/src/askwell/ingest.py` (`reindex_source`, `Reindexed`, `SOURCE_REINDEX_REQUESTED`, `snapshot`); `api/src/askwell/sources.py` (`POST /sources/{source_id}/reindex`); `api/tests/test_ingest_records.py`, `test_ingest_api.py`.

## 2026-08-28 — The card's display data rides the citation event; no new endpoint

**Decision:** `M1-CITE-FE-043`. The ticket's own "API / Data Touchpoints" line calls for "`citations` joined to `chunks` and `documents`", but no such join was reachable from the browser: the `citation` SSE event (`M1-CITE-BE-042`) carried only `chunk_id`, `document_id`, `page_from`/`page_to` and `quoted_span` — enough to prove a citation happened, not enough to render a card naming the file or showing the passage. Rather than filing that gap as a blocked dependency, `askwell.retrieve.Candidate` gained `filename` and `anchor_kind` (joined from `documents` in the two SQL queries that already join it for the `deleted_at`/`superseded_by`/`source_id` filters), and the `citation` event gained `filename`, `anchor_kind`, `heading` and `passage` (the chunk's own `content`). The `citations` table itself is untouched — this is display data carried alongside the row, not a new column.

**Why:** the alternative was a new `GET` endpoint the browser calls once per card (or once per turn) to resolve chunk IDs to display data. Rejected: it duplicates a join the retrieval query already performs one call earlier in the same request, adds a round trip per answer for data the server already had in hand while composing it, and — the deciding factor — no such endpoint exists in `docs/backlog/` under any ticket; the only place this join is named at all is this ticket's own Touchpoints line, describing what the ticket touches, not a dependency on something else. Filing "citation card data has no route to the browser" as a separate blocked-on ticket would have stopped a *frontend* story on a *backend* gap invented by the story itself, for a one-line SQL change with no schema impact.

**Consequences:** `Candidate` now carries two fields (`filename`, `anchor_kind`) that retrieval scoring and reranking never read — they exist solely for citation rendering, which is a mild leak of a display concern into the retrieval layer. If a future ticket wants citation display data to diverge from what retrieval selects (e.g. a document's *current* filename after a rename, rather than the filename at chunk-fetch time), that will need an actual join at citation-write time instead of retrieval time — today the two are the same query. `api/tests/test_retrieve.py`'s `_row` helper and both `Candidate(...)` test constructors now require the two fields; a future field added to `Candidate` will hit the same three call sites.

**Refs:** `api/src/askwell/retrieve.py`, `api/src/askwell/ask.py`, `api/tests/test_retrieve.py`, `api/tests/test_ask_api.py`, `web/lib/citations.ts`, `web/lib/ask.ts`.

---

## 2026-08-28 — A source card's click target names a route that does not exist yet

**Decision:** `M1-CITE-FE-043`. Each provenance card links to `/documents/{document_id}?page={page_from}` — a route `M1-VIEW-FE-048` has not built. Clicking a card today lands on `web/app/not-found.tsx`.

**Why:** the ticket's own Out of Scope line is explicit that this ticket wires the click to *a* route without building the landing: "the click is wired here to the route." No route convention existed anywhere in the codebase to reuse — `web/app/library/page.tsx` is still a placeholder with no per-document path, and no backlog ticket names one. `/documents/{id}` was chosen over alternatives (`/library/{id}`, a query param on `/library`) because a document, not a source, is what a citation names, and a plain resource path leaves `M1-VIEW-FE-048` free to add its own query parameters (a highlighted span, a citation to step to) without renegotiating the base path. This is a guess, written down rather than left silent, so `M1-VIEW-FE-048` either confirms it or replaces it deliberately instead of two tickets picking different paths independently.

**Consequences:** `M1-VIEW-FE-048` must either build its route at `/documents/[id]` or, if it picks something else, update `provenance-margin.tsx`'s `href` in the same change — otherwise every card silently 404s again after the viewer ships elsewhere.

**Refs:** `web/components/ask/provenance-margin.tsx`, `docs/backlog/M1-it-answers-from-my-documents.md` (`M1-VIEW-FE-048`).

---

## 2026-08-28 — A claim is a marked sentence; the marker sits before the period, not after

**Decision:** `M1-CITE-BE-042`. `askwell.agent.claims.segment_claims` treats a sentence as a factual claim only if it carries one or more `[index]` markers immediately before its own closing punctuation — `"...forty-five days [1][2]."`, not `"...forty-five days. [1][2]"`. A sentence with no marker is not a claim: it produces no citation and is not counted anywhere, rather than being flagged as an uncited claim. `citations.claim_ordinal` increments only for marked sentences, so a claim citing two passages produces two rows sharing one ordinal instead of the pre-ticket behaviour — a flat `re.finditer(r"\[(\d+)\]")` over the whole growing answer, deduplicated globally by index — which could only ever produce one citation row per distinct index used anywhere in the answer, no matter how many separate claims reused it.

**Why:** the marker-before-punctuation placement was not a free choice — `M1-ASK-API-038`'s own test (`test_a_question_streams_steps_then_tokens_then_a_citation_then_done`) already fixed the wire format with `"is ninety days [1]."`, and moving the marker to the more conventional after-punctuation position would have meant breaking a shipped convention with no benefit, purely to match academic-citation style. Segmenting on sentences rather than parsing structured output (e.g. asking the model for JSON with claim/citation pairs) was rejected as heavier than the problem needs: `M2`'s eval suite is what will actually measure whether small models can follow either convention reliably, and a small local model already has a documented harder time producing valid structured output under load than plain prose (`docs/decisions.md` has no prior entry on this specific point, but it is the same reasoning `answer_composition.v1.md`'s existing free-text-plus-marker design already rests on). The alternative to skipping unmarked sentences — treating every sentence as a claim and flagging unmarked ones as "uncited" — was rejected because it is exactly the ticket's own stated edge case forbidding it: a restatement of the question is not a claim, and counting it as an uncited one would make the eventual `M1-CITE-TEST-045` counter-metric alarm on completely normal answers.

**Consequences:** a model that does not follow the "marker before punctuation, one claim per sentence" convention degrades silently to fewer or zero claims found, not an error — matching how injection-pattern flagging in `compose.py` already degrades rather than blocks. This is measured, not guessed at, once `M2`'s eval suite exists. Changing the marker convention later (e.g. to support markers spanning multiple sentences, or claims spanning multiple sentences) means updating both `answer_composition.v1.md`'s Citing section and `_CLAIM_RE` together, or the prompt and the parser disagree on what a claim looks like.

**Refs:** `api/src/askwell/agent/claims.py`, `api/src/askwell/agent/prompts/answer_composition.v1.md`, `api/src/askwell/ask.py`, `api/tests/test_claims.py`, `api/tests/test_ask_api.py`.

---

## 2026-08-28 — The pending answer is a row, not a promise; reconciliation happens once, at startup

**Decision:** `M1-ASK-BE-040`. `POST /ask` now writes the assistant `messages` row as `running`, content empty, in the same request that starts the background generation task — not once generation finishes, as `M1-ASK-API-038` left it. `askwell.ask.reconcile_interrupted` runs once, from `app.py`'s `lifespan`, before the first request is served, and fails every assistant row still `running`: on one worker, one machine, a `running` row a fresh process finds can only belong to the process before it, since nothing in the in-memory `_turns` registry survives a restart. The final write moved from a plain `INSERT` to `INSERT ... ON CONFLICT (id) DO UPDATE`, so a caller that drives `_generate` directly against a `_Turn` it built itself — every stop/disconnect test in `test_ask_api.py` already does this — still has somewhere to write without needing to duplicate the pending-row insert `ask()` now does.

**Why:** the alternative was a periodic reconciler, matching `askwell.ingest`'s own `reconcile` timer. Rejected: ingestion's timer exists because a *queue* can disagree with its own durable record — a failed enqueue, a flushed Redis — a disagreement that can appear at any point during a long-running process and needs re-checking. An orphaned `running` answer has exactly one possible cause, a process restart, and that can only be discovered once, at the moment a new process starts; a timer re-running the same check every thirty seconds against a table that cannot change out from under it that way buys nothing and is one more thing to explain. The harder question was whether to make the pending row's absence itself the failure signal — i.e., treat "no row for this message_id" as evidence of a crash, and let `ask()` simply not write anything until completion, as before this ticket. Rejected because that makes "message never arrived" indistinguishable from "message was never asked": a `GET /ask/{id}/stream` for an id from a truly-lost turn would 404, the same response as a garbled or fabricated id, rather than resolving to a stated, readable failure. A row that exists from the first instant, and is guaranteed to end in one of `completed`/`stopped`/`failed`, is what the ticket's own validation rule — "a message must never remain in a pending state with nothing generating it" — actually requires; there has to be a state machine with a knowable final value, and that needs a row to hold it before generation starts, not just after.

**Consequences:** every question now costs two writes instead of one before the first token (the pending insert, then the final upsert) — negligible against a retrieval-plus-generation turn, not worth measuring. `GET /ask/counts`'s `started` figure is now accurate slightly earlier (from the moment the row is written, not from completion), which does not change its meaning since it was already defined as "every assistant turn ever recorded." A new local counter, `abandoned`, distinguishes a turn `reconcile_interrupted` failed from an ordinary inference failure — same shape as `failed`, subset of it, never in `started` twice. Reversing this would mean going back to writing the assistant row only on completion, which reopens exactly the gap this decision closes.

**Refs:** `api/src/askwell/ask.py`, `api/src/askwell/app.py`, `docs/states-and-edge-cases.md` §2 ("Several abandoned generations at once" / restart edge case), issue #163.

---

## 2026-08-28 — The English-only statement is triggered by a non-Latin-script heuristic, not language detection

**Decision:** `M1-ASK-FE-039`. `web/lib/ask.ts::looksNonEnglish` flags a question for `docs/ux/ask.md` §5's English-only statement when more than 30% of its letters fall outside the Latin script (and only once there are at least four letters to judge). No language identification library is added; questions in French, German, Tagalog written in Latin script and so on pass through un-flagged, same as any other v1 gap.

**Why:** nothing in the stack does language detection yet — v1 is English-only by scope (`AGENTS.md` §1) and no dependency ticket built one — so this ticket either builds real detection, skips the ticket's own stated validation rule and testing scenario, or ships something narrower and says so plainly. Real detection means a new dependency (`AGENTS.md` §4: "prefer what exists... then a new maintained package, checked for compatibility") for a v1 surface whose own scope is "not multilingual yet," which is a heavier commitment than one ticket should make in passing. The script-based heuristic catches the unambiguous, high-value case — the same reasoning `extract_ocr.py`'s OSD-based script routing already relies on for the identical problem on the ingestion side — at zero dependency cost, and is honest about what it does not catch rather than quietly pretending to be complete.

**Consequences:** a question in a Latin-script non-English language gets a poor English answer rather than the correct statement, until real detection exists. Revisit once usage shows this matters rather than guessing at a threshold now; `30%` and `4` letters are both unmeasured starting points, matching how `retrieval_score_threshold` and `ocr_confidence_threshold` were both introduced as starting values.

**Refs:** `M1-ASK-FE-039`, `web/lib/ask.ts`, `docs/ux/ask.md` §5, `api/src/askwell/extract_ocr.py`.

---

## 2026-08-28 — Turn state lives above the router in memory; reconnect is not wired into the frontend yet

**Decision:** `M1-ASK-FE-039`. `AskProvider` (`web/components/ask/ask-state.tsx`) holds every turn in a React context mounted in `Shell`, above the router — the same placement `AddProvider` already uses and for the same reason. "Navigate away mid-answer and back — the completed answer is present" is satisfied by the component simply never unmounting, not by persisting to `sessionStorage`/`localStorage` or by calling `GET /ask/{message_id}/stream` (`M1-ASK-API-038`'s reconnect endpoint) on mount.

**Why:** the acceptance criterion is about navigating *within* the running application — to the library and back — not about a page reload or a second tab, and the in-memory placement already built for exactly this shape by `AddProvider` covers it with no new mechanism. Reaching for `sessionStorage` would duplicate state that already survives the only navigation this ticket's own testing notes exercise, and reaching for the reconnect endpoint would additionally require threading a `message_id` (fine) and, per the previous decision above, tolerating a full replay of every token on every mount (a client concern that entry already flagged for this ticket to pick up) — real work for a case ("the tab was actually closed and reopened," or "the process was restarted") this ticket's own walkthrough does not test. Deferred rather than built against a guess: reconnect-on-reload is real and worth doing, but belongs with whichever ticket first needs a page reload to survive — filed nowhere yet because nothing has asked for it.

**Consequences:** a hard reload of the tab (not a client-side navigation) loses every in-progress and completed turn from this session — the browser has genuinely forgotten, and there is currently no code path that would recover it even though the server-side `messages` rows still exist. `AskProvider` also cannot thread `conversation_id` across turns today regardless, because `askwell.ask` never returns the one it resolved (issue #156) — every question opens its own conversation server-side, so even a working reconnect would only ever recover one turn's own history, not a conversation's.

**Refs:** `M1-ASK-FE-039`, `web/components/ask/ask-state.tsx`, `web/components/add/add-state.tsx`, issue #156, the `M1-ASK-API-038` entry below.

---

## 2026-08-28 — A reconnected answer stream replays its own history in full, rather than resuming from where a previous connection left off

**Decision:** `M1-ASK-API-038`. `askwell.ask._tail` starts every connection — the original `POST /ask` response and any later `GET /ask/{message_id}/stream` reconnect — at event index 0 of the turn's own in-memory event list, and sends the whole thing before continuing live. This departs from the ticket's own stated edge case, "reconnect resumes the stream but does not replay tokens already sent."

**Why:** the literal reading — start a reconnect at wherever the turn currently is, skipping history — has a bug the ticket's own wording does not surface: a browser that reconnects *after* a turn has already finished attaches with nothing pending and the turn no longer `running`, so it receives nothing at all, not even the terminal `done` event. That is worse than replaying — a reconnect after completion is exactly the "close the tab, reopen it" scenario the ticket's own testing notes ask for, and it must not come back empty. Making replay-vs-resume conditional on whether the turn is still running is a second state to get right for a marginal saving; replaying unconditionally is one rule with no failure mode, and the cost is bounded by what it always was — one turn's own text, for one browser, never more than a few kilobytes. The alternative that preserves the literal requirement — track a per-connection cursor and mark only *token* events as non-replayable while still replaying `step`/`citation`/`done` — was considered and rejected as complexity bought for a case (a reconnect mid-answer momentarily re-rendering tokens already shown) that costs the user nothing visible.

**Consequences:** a reconnect mid-answer re-sends every token already delivered before continuing live, which a client must tolerate (re-rendering the same accumulated text is a no-op, not a duplicate-append bug, provided the client replaces rather than concatenates on reconnect — `M1-ASK-FE-039`'s own concern, noted here so it is not rediscovered there). `MAX_FINISHED` (200) still bounds how long a finished turn's history survives in memory; past that, `GET /ask/{message_id}/stream` falls back to `messages`, which never had per-token history to begin with and replays as one block.

**Refs:** `M1-ASK-API-038`, issue #152, `api/src/askwell/ask.py`, `api/tests/test_ask_api.py`, ticket testing notes' "known gaps".

---

## 2026-08-28 — Reranking window is bounded separately from the fusion candidate count, and degrades in-band rather than raising

**Decision:** `M1-ASK-RET-036`. `askwell.retrieve.retrieve` sends only the top `Settings.rerank_candidate_count` (default 10) of the fused candidates to `InferenceClient.rerank`, not the full fused list (`Settings.retrieval_candidate_count`, default 40). Candidates beyond the window are appended after the reranked ones, in their fused order, unscored. If reranking raises `InferenceUnavailable` or `InferenceFailed` — the reranker absent, refusing, or slower than `Settings.rerank_timeout_seconds` — `_rerank` catches both and returns the fused list unchanged, with a reason string; `retrieve()` never raises because reranking did not work.

**Why:** the reranker scores every candidate it is given individually — unlike fusion, which reads two already-bounded SQL result sets — so a window sized to the fusion candidate count (40) would make reranking the slowest step of every question on the `light` profile the ticket's own edge case names. Ten is a starting point, not a measured figure, matching how `retrieval_score_threshold` and `ocr_confidence_threshold` are both stated as starting points rather than benchmarked ones — nothing in this milestone's eval suite exists yet to tune it against. Catching both exception types and degrading rather than propagating follows the same shape `InferenceClient`'s own docstring establishes for embedding and generation: "the assistant being absent is not the same as a request failing," and a caller that cannot get a rerank score still has a perfectly good fusion order to fall back to — unlike embedding, where a missing vector means the query cannot run at all. Rejected: reranking the full fused list and truncating afterward — rejected because it pays the reranker's per-candidate cost for candidates that would never survive to the visible answer count anyway, with no offsetting benefit, exactly the kind of latency this ticket's own scope says to bound.

**Consequences:** `Settings.rerank_candidate_count` and `Settings.rerank_timeout_seconds` are two more numbers a hardware-probed deployment profile will eventually set differently per profile (`docs/architecture.md` §6) — no such per-profile config file exists yet, so today they are one global default like every other `Settings` field. `RetrievalResult.reranked`/`.rerank_duration_ms`/`.rerank_skipped_reason` are captured but read by nothing — no `ask` endpoint or trace writer exists yet, matching exactly how `M1-ASK-RET-035` left `RetrievalResult.threshold` captured and unread; the fields are shaped so the trace this ticket cannot write yet reads correctly once `docs/ux/trace.md` §3's "backend" and score rows have somewhere to attach.

**Refs:** `M1-ASK-RET-036`, issue #144, `api/src/askwell/retrieve.py`, `api/tests/test_rerank.py`, `api/tests/test_retrieve_records.py`, `docs/architecture.md` §8.

---

## 2026-08-28 — C7 is delimitation plus a standing statement, not detection; flagging is heuristic and never blocking

**Decision:** `M1-ASK-BE-037`. `askwell.agent.compose.compose` wraps every retrieved `Candidate` in an explicit `<retrieved-content index="…" chunk_id="…">` block and reads the system prompt from `api/src/askwell/agent/prompts/answer_composition.v1.md`, the first prompt file in the repository — no prompt text lives in Python. The prompt file states, as a standing instruction the model is given directly, that text inside a `<retrieved-content>` block is data and never an order, regardless of what it reads like. Separately, `compose()` scans each candidate's content against a small named set of instruction-like regexes (`_INSTRUCTION_PATTERNS`) and sets `ComposedPrompt.injection_flagged` on a match — but the flag changes nothing about what gets composed or sent; a flagged turn is answered exactly like an unflagged one.

**Why:** the ticket is explicit that this is a mitigation, not a solution, and the two halves do different jobs. Delimitation plus the standing statement is the actual defence — it works whether or not any pattern matches, because the model is told a plain rule about *where* text sits rather than asked to recognise *what* an attack looks like. Pattern flagging cannot be that defence: it is trivially evaded (rephrase, encode, translate) and, worse, `docs/build-plan.md`'s own edge case names a policy manual as an example of ordinary prose that will legitimately match "act as a first point of contact" or similar — a heuristic that blocked on match would refuse real answers, not just attacks. So flagging is scoped to the trace only, and the module docstring says outright that it both misses and over-flags, rather than letting a green checkmark on a trace screen imply protection the code cannot back up. Rejected: skipping pattern flagging entirely as pure noise given it cannot detect reliably — rejected because the ticket's own audit requirement wants a local, queryable signal ("how often does retrieved content look like this") even knowing the signal is noisy, and a noisy signal that is honestly labelled noisy is more useful than no signal.

**Consequences:** `ComposedPrompt.injection_flagged`/`.prompt_version`/`.injection_patterns` are captured but written nowhere yet — no `ask` endpoint exists (`M1-ASK-API-038`) to call `compose()` against a real turn or persist `messages.trace.injection_flagged` (`docs/architecture.md` §7.1). Any future widening of `_INSTRUCTION_PATTERNS`, or any edit to the prompt file's wording, is a prompt change and needs an eval run once the eval gate exists (`M2`) — this ticket's own tests only prove the mechanism, not the model's actual adherence to it, which cannot be measured without a running inference process.

**Refs:** `M1-ASK-BE-037`, issue #146, `api/src/askwell/agent/compose.py`, `api/src/askwell/agent/prompts/answer_composition.v1.md`, `api/tests/test_compose.py`, `docs/architecture.md` §9, §7.1.

---

## 2026-08-28 — Reranking window is bounded separately from the fusion candidate count, and degrades in-band rather than raising

**Decision:** `M1-ASK-RET-036`. `askwell.retrieve.retrieve` sends only the top `Settings.rerank_candidate_count` (default 10) of the fused candidates to `InferenceClient.rerank`, not the full fused list (`Settings.retrieval_candidate_count`, default 40). Candidates beyond the window are appended after the reranked ones, in their fused order, unscored. If reranking raises `InferenceUnavailable` or `InferenceFailed` — the reranker absent, refusing, or slower than `Settings.rerank_timeout_seconds` — `_rerank` catches both and returns the fused list unchanged, with a reason string; `retrieve()` never raises because reranking did not work.

**Why:** the reranker scores every candidate it is given individually — unlike fusion, which reads two already-bounded SQL result sets — so a window sized to the fusion candidate count (40) would make reranking the slowest step of every question on the `light` profile the ticket's own edge case names. Ten is a starting point, not a measured figure, matching how `retrieval_score_threshold` and `ocr_confidence_threshold` are both stated as starting points rather than benchmarked ones — nothing in this milestone's eval suite exists yet to tune it against. Catching both exception types and degrading rather than propagating follows the same shape `InferenceClient`'s own docstring establishes for embedding and generation: "the assistant being absent is not the same as a request failing," and a caller that cannot get a rerank score still has a perfectly good fusion order to fall back to — unlike embedding, where a missing vector means the query cannot run at all. Rejected: reranking the full fused list and truncating afterward — rejected because it pays the reranker's per-candidate cost for candidates that would never survive to the visible answer count anyway, with no offsetting benefit, exactly the kind of latency this ticket's own scope says to bound.

**Consequences:** `Settings.rerank_candidate_count` and `Settings.rerank_timeout_seconds` are two more numbers a hardware-probed deployment profile will eventually set differently per profile (`docs/architecture.md` §6) — no such per-profile config file exists yet, so today they are one global default like every other `Settings` field. `RetrievalResult.reranked`/`.rerank_duration_ms`/`.rerank_skipped_reason` are captured but read by nothing — no `ask` endpoint or trace writer exists yet, matching exactly how `M1-ASK-RET-035` left `RetrievalResult.threshold` captured and unread; the fields are shaped so the trace this ticket cannot write yet reads correctly once `docs/ux/trace.md` §3's "backend" and score rows have somewhere to attach.

**Refs:** `M1-ASK-RET-036`, issue #144, `api/src/askwell/retrieve.py`, `api/tests/test_rerank.py`, `api/tests/test_retrieve_records.py`, `docs/architecture.md` §8.

---

## 2026-08-28 — Fusion combines rankings, not scores; both source scores are kept, the threshold is captured but not applied

**Decision:** `M1-ASK-RET-035`. `askwell.retrieve.retrieve` runs dense search (pgvector cosine over `chunks.embedding`) and lexical search (Postgres full-text over `chunks.content_tsv`) independently, each capped at `Settings.retrieval_candidate_count`, and merges them with Reciprocal Rank Fusion (`RRF_K = 60`, the constant from Cormack, Clarke & Buettcher's paper) rather than any score-normalising blend. `Candidate` carries the fused RRF score plus the real dense and lexical scores separately — `None` on whichever side did not find it — and `RetrievalResult.threshold` is `Settings.retrieval_score_threshold` as configured at the call, stored but never compared against anything here.

**Why:** cosine similarity and `ts_rank` are different units on different scales with no principled shared zero point, so a weighted blend (`0.6 * cosine + 0.4 * ts_rank`, say) would need a normalisation step invented without the eval suite `M2` brings to justify it — exactly the "fusion weighting is tuned against the eval suite in M2, not guessed at now" assumption the ticket states. RRF sidesteps the units problem entirely by fusing rank positions, which is comparable by construction, at the cost of being a coarser signal than a tuned blend would eventually be. Rejected alternative: discard a candidate's non-fused score once fusion runs, keeping only the RRF number — rejected because `docs/architecture.md` §7.1 requires the abstention explanation (`M2`) to show a real, un-recomputed score ("the right passage scored 0.61 under a 0.65 threshold"), and an RRF value has no such interpretable unit to show a user. The threshold is captured rather than applied because deciding what to do with a sub-threshold score is the abstention decision itself, explicitly out of this ticket's scope; capturing it now means the trace this ticket writes into is correct once `M2` reads it, rather than needing a second migration of old traces later.

**Consequences:** a future reranking pass (`M1-ASK-RET-036`) receives the fused candidate list and is free to reorder it using the real dense/lexical scores already attached, without re-querying either search. No `ivfflat`/`hnsw` index exists on `chunks.embedding` yet, so dense search is a sequential scan — acceptable at the corpus sizes this milestone targets, revisit once real usage makes it slow. Changing `retrieval_score_threshold` retroactively changes nothing about past traces, because they stored the threshold that was actually in force, not a reference to the live setting.

**Refs:** `M1-ASK-RET-035`, `api/src/askwell/retrieve.py`, `api/tests/test_retrieve.py`, `api/tests/test_retrieve_records.py`, `docs/architecture.md` §7.1 and §8.

---

## 2026-08-28 — Supersession is decided per path via `version_decisions`, never inferred from a hash alone

**Decision:** `M1-INDEX-BE-034`. `askwell.sources.add` now recognises a third case beyond "duplicate" and "new document": a file at a path that already holds a *live* document, whose content hash differs. Rather than deciding for the user, `add` returns `Outcome.NEW_VERSION` and records nothing — no document row, no audit entry — until a second call answers via `version_decisions: dict[relative_path, "supersede" | "keep_both"]`. `"supersede"` inserts the new document and sets the old row's `superseded_by` to it, at `version + 1`, in one transaction; `"keep_both"` inserts it as an ordinary independent document with no link to the old one. The match is on exact `path`, not filename — `clients/contract.pdf` and `archive/contract.pdf` are unrelated paths and stay two separate documents, which is also what the ticket's own duplicate-recognition test (`test_different_content_under_the_same_name_is_two_documents`) already assumed and continues to pass.

**Why:** the ticket's own edge cases require both outcomes of the same detection to be reachable — accept and decline — and a decline has to leave both documents live and searchable ("both exist, and the user is told that answers may cite either"). Auto-superseding on hash mismatch alone would make decline unrepresentable without a second, undo-shaped code path. Two designs were rejected: (1) a stateful "pending offer" row that a separate confirm endpoint acts on later, mirroring the password-prompt flow (`M1-EXTRACT-VAL-030`) — rejected because unlike a password, which cannot be re-derived, the offer here can be regenerated for free by re-running `add` against the same file, so a row that exists purely to remember "I already asked about this path" is state with no failure mode it protects against; (2) auto-supersede whenever the path matches, with a client-side "undo" — rejected because it makes "declined" and "not yet decided" the same server-side state for a window of time, which is exactly the confusion between supersession and deletion the module's own docstring says must never happen. The chosen design's `version_decisions` is stateless on the server between the two calls, so there is nothing to reconcile if the second call never arrives.

**Consequences:** a client offering supersession has to hold the file's relative path in memory between the offer and the decision and resubmit the whole batch — acceptable because `add` is already idempotent per file (a repeat call against unchanged content is a duplicate, not a re-offer) and batches are the unit the screen already works in. `superseded_by IS NULL` is the filter any future retrieval query must apply to see only live content — no retrieval component exists yet (`M1-ASK-RET-035`/`036`, unbuilt), so this is a requirement recorded for that ticket rather than something exercised here. The superseded-banner data the source viewer needs (`docs/ux/source-viewer.md` §4) has no endpoint to attach to yet either — no document-detail or citation-resolution route exists in the repository at all — filed as issue #141 rather than guessed at.

**Refs:** `M1-INDEX-BE-034`, issue #140, issue #141, `api/src/askwell/sources.py`, `api/tests/test_sources_records.py`.

---

## 2026-08-28 — `content_tsv` normalises hyphens to spaces before tokenising, in the generated column itself

**Decision:** `M1-INDEX-DB-033`. `chunks.content_tsv`'s generated-column expression (`c7e2f814a5b3`) changed from `to_tsvector('english', coalesce(content, ''))` to `to_tsvector('english', regexp_replace(coalesce(content, ''), '-', ' ', 'g'))`. No new column, no new index, no application code — `content_tsv` and its GIN index (`ix_chunks_content_tsv`) already existed and already auto-populated on every write since `a8208099ef38`; only the expression they compute from was wrong.

**Why:** Postgres's default text search parser reads a hyphen immediately before a digit run as a sign, not a word boundary — `ts_debug('english', 'INV-2024-0917')` classifies `-2024` and `-0917` as *signed integers*, each lexeme carrying the minus sign. Confirmed against the real, running database (`scripts/dev.sh psql`, not asserted from memory): `to_tsvector('english', 'INV-2024-0917')` produced `'inv':1 '-2024':2 '-0917':3`, and a query for the reference number's own trailing group — `to_tsquery('english', '0917')`, the realistic case of someone remembering only part of it — did **not** match, because the stored lexeme was `-0917`, not `0917`. This is exactly the ticket's own scope bullet: "tokens like reference numbers that default tokenising would split badly." Two alternatives were considered and rejected: a custom parser extension (Postgres has no built-in way to change hyphen-before-digit tokenising short of swapping `pg_catalog.default_parser` for a third-party one — a new dependency for a one-line problem, and one whose licence and maintenance status nobody had verified) and a second, separately-normalised column (doubles the storage and the index, and gives the application two full-text columns to remember to query instead of one). Replacing hyphens with spaces before tokenising was chosen because it fixes the parser's actual mistake at its source: `INV-2024-0917` now tokenises as three independent, signless lexemes (`inv`, `2024`, `0917`), each one matchable alone, confirmed against the same real database.

**Consequences:** a query must apply the identical normalisation (`regexp_replace(query, '-', ' ', 'g')`) before calling `to_tsquery`/`plainto_tsquery`, or the two sides of `@@` tokenise differently and nothing matches — `M1-ASK-RET-035`, whichever ticket first builds a real lexical query, owns doing this, and `api/tests/test_index_db_records.py::_matches` is the reference for what that normalisation has to look like. The cost accepted knowingly: a genuine hyphenated English compound (`well-known`) loses the compound lexeme (`'well-known'`) the unmodified parser would have produced alongside `'well'` and `'known'` — the two parts still index and still match individually, so a search for `well-known` still finds the chunk, only the exact-phrase-as-one-token shortcut is gone. Reversing this means a new migration restoring the original expression; the old one, `a8208099ef38`, was not edited in place because it had already run against a live database and rewriting history under that is worse than a second migration (`c7e2f814a5b3`'s own docstring says the same).

**Refs:** `M1-INDEX-DB-033`, `api/src/askwell/db/migrations/versions/20260828_c7e2f814a5b3_content_tsv_hyphen_tokenising.py`, `api/tests/test_index_db_records.py`.

---

## 2026-08-28 — `StageFn` grows a fourth argument for `embed`; batch size is `Settings`, batch retry is a stage-owned inner loop

**Decision:** `M1-INDEX-ING-032`'s `embed` stage (`api/src/askwell/embed.py`) needed the inference socket and a batch size — genuinely per-install configuration, not a fact about one document — so `askwell.ingest.StageFn` grew a fourth parameter, `Settings`, threaded through `ingest.process`'s call to `stage.run`. `extract.run` and `chunk.run` both take and ignore it (`_settings: Settings`) rather than gaining a parallel untyped signature. `ASKWELL_EMBEDDING_BATCH_SIZE` (default 16) is a `Settings` field, not a module constant like `chunk.py`'s `CHUNK_TARGET_CHARS`. Within one call to `embed.run`, a failing batch retries up to three times with a short linear backoff (`embed._embed_batch`) before the whole document fails through to the pipeline's existing per-document retry (`ingest.MAX_ATTEMPTS`, `RETRY_DELAY_SECONDS`). The embedding dimension is checked once, in `askwell.worker.startup`, against `chunks.embedding`'s actual deployed width (`format_type(atttypid, atttypmod)`) — and, uniquely among the checks already living in that function's broad `except Exception: log.warning(...); return` deferral, a mismatch is re-raised and crashes worker startup rather than being swallowed as "Postgres is not up yet".

**Why:** the previous chunking decision (above) explicitly named this trade as deferred rather than avoided — *"if `M1-INDEX-ING-032` needs `Settings` inside a stage for a real reason, `StageFn` will need to change then"* — and it did: an `InferenceClient` cannot be built without the socket path, and there is no other channel a stage has to configuration. Threading it through `process()` rather than having `embed.run` call `load_settings()` itself was chosen because the latter reads the environment fresh on every document, duplicating work `process()`'s own caller already did once, and — more importantly — makes `embed.run` untestable with an injected socket path without also monkeypatching `os.environ`, unlike every other test in this pipeline. `embedding_batch_size` breaks with `chunk.py`'s "plain constant, unmeasured" precedent on purpose: chunk size is a retrieval-quality question with no eval suite yet (M2); batch size is a machine-sizing question exactly like `ingest_concurrency`, which is already a `Settings` field for the same reason — "the right number is a property of the machine," stated verbatim in `config.py` for its neighbour. A stage-owned inner retry was chosen over relying solely on the outer per-document retry because the outer retry re-runs `extract` and `chunk` from scratch for what is usually a one-off socket hiccup — cheap for a short document, wasteful for the "add several hundred papers" scenario the ticket's own user story names, where an inner retry costs a few seconds against a batch instead of re-parsing a whole PDF. The dimension check's placement — worker startup, not API startup or per-batch — follows directly from the ticket's own edge case ("refused at startup rather than per batch"): the API process never embeds anything, so checking there would prove nothing about the process that actually will, and checking per batch means an import fails midway through on a fact that was true before the first document was ever claimed.

**Consequences:** every future stage's `run` function takes `(Work, Report, async_sessionmaker, Settings)`, whether or not it needs the last one — a smaller, uniform surface was chosen over a `StageFn` that varies per stage, which `ingest.STAGES`'s tuple-of-`Stage` shape cannot express without a second dispatch mechanism. A worker that starts against a database still on an old embedding-dimension migration now crashes loudly instead of failing every document one at a time; an operator changing `ASKWELL_EMBEDDING_DIMENSIONS` must run `db upgrade head` before the worker will start again, which is the intended friction. Batch-level retry adds up to roughly `EMBED_BATCH_MAX_ATTEMPTS * EMBED_BATCH_RETRY_DELAY_SECONDS` seconds of latency inside one stage call before a document fails at all, on top of the outer retry's own delay — acceptable because the ticket's own bar is "visible with a retry," not "fails fast."

**Refs:** `api/src/askwell/embed.py`, `api/src/askwell/ingest.py` (`StageFn`, `process`), `api/src/askwell/worker.py` (`startup`), `api/src/askwell/extract.py`/`chunk.py` (the now-ignored fourth parameter), `docs/backlog` ticket `M1-INDEX-ING-032`.

## 2026-08-28 — Chunking reads the extractors' own markers rather than re-discovering structure, and sizes are plain constants

**Decision:** `M1-INDEX-ING-031`'s chunker (`api/src/askwell/chunk.py`) does not parse a document a second time or call any structure-detection library. It reads `document_pages.text` exactly as the extractors already left it — Markdown-style `#` headings, `[TABLE]`/`[/TABLE]` markers with `|`-separated rows, `-`/`1.` list items — and treats a heading as a piece of metadata (`chunks.heading`), never as a duplicated line inside a chunk's own content. Target and hard-maximum sizes (1,600/2,400 characters) are plain module constants in `chunk.py`, not `Settings` fields — `StageFn` (`askwell.ingest`) hands a stage `(Work, Report, session factory)` with no configuration object, matching `extract`'s own signature and `ingest.py`'s own precedent of plain constants (`PROGRESS_INTERVAL_SECONDS` and neighbours) for pipeline tuning nothing has measured yet.

**Why:** `M1-EXTRACT-ING-027`'s own module docstring in `extract_docx.py` already frames the markers this way — *"markers a chunker can still see as structure without needing a table type of its own"* — written specifically for this ticket to consume; re-deriving headings and tables from raw bytes a second time would duplicate logic that already exists per format (`python-docx` style names, `python-pptx` shape types) and risk disagreeing with what extraction recorded. Widening `StageFn` to carry `Settings` was considered so chunk size could be an environment variable like `ocr_confidence_threshold`; rejected because it changes a type three stages share (`extract`, `chunk`, `embed`) for one tunable nothing has evaluated against real retrieval yet — `AGENTS.md` §4 ties a prompt or retrieval change to an eval run, and the eval suite (`eval/bench.py`) does not exist until M2. A constant is honest about that: it says "unmeasured default", not "configuration a user should tune before there is anything to tune it against".

**Consequences:** raising or lowering chunk size before M2's eval suite exists means editing `CHUNK_TARGET_CHARS`/`CHUNK_HARD_MAX_CHARS` in `chunk.py` directly, not setting an environment variable — deliberate friction against guessing a number that should be measured. If `M1-INDEX-ING-032` (embed) or a later ticket needs `Settings` inside a stage for a real reason, `StageFn` will need to change then, and every installed stage's signature changes with it; that cost is deferred rather than paid now for one constant. A slide (`documents.anchor_kind = 'slide'`) is the one anchor kind chunking never merges across — every other kind (`page`, `heading`, `sheet_row`) merges freely, which is what turns a heading-free PDF into sentence-bounded chunks instead of one per page, and what would have made "one slide, one chunk" impossible to guarantee if slides merged too.

**Refs:** `api/src/askwell/chunk.py`, `api/src/askwell/extract_docx.py` (the marker convention this consumes), `api/src/askwell/ingest.py` (`StageFn`, `STAGES`), `docs/backlog/M1-it-answers-from-my-documents.md` ticket `M1-INDEX-ING-031`.

## 2026-08-28 — A document password rides the Redis job payload, never a database row

**Decision:** `M1-EXTRACT-VAL-030` adds `POST /ingest/documents/{id}/password`, which resets a failed job to `queued` (reusing `retry`'s own reset, attempts forgiven) and dispatches it with a password carried as an `arq` job argument (`ingest.dispatch`'s new `password` parameter, forwarded to `worker.ingest_document`, applied to `Work` inside `ingest.process` via `dataclasses.replace`). Nothing about the password is written to Postgres — not to `documents`, not to `ingest_jobs.error`, not anywhere — and it is never passed to `structlog` as a value (only `extract_pdf._classify_open_failure`'s *whether one was supplied* boolean crosses into a log line or an error message).

**Why:** the ticket's own assumption says storage needs the credential encryption path `M4` adds, and until then "storage is not offered" — not "offered but insecure". The natural place to stage a value between an HTTP request and a worker in another process is a database row (`ingest_jobs` already carries `error`, `stage`, `awaiting` for exactly this purpose), and that was the first design considered and rejected: a value the ticket says must not be stored cannot ride the one piece of durable state this pipeline already has, even transiently, without becoming exactly the kind of "we only kept it for a moment" claim that does not hold up to an audit. Redis's job payload is the alternative already in use for every other job argument (`document_id` itself), is not queried or displayed anywhere, and is the transport `dispatch`'s own docstring already frames as "a wake-up over a durable queue" rather than the record — the record stays Postgres, the password is deliberately never part of it.

**Consequences:** a password only ever survives for the one retry attempt it was supplied for; if that attempt also fails, the next `/password` call must supply it again. Building `M4`'s "remember this password" checkbox later means adding a genuinely new write path (through the credential encryption module, into a new column), not loosening this one. `Work.password` is a fifth field on a previously four-field frozen dataclass, defaulted to `None`, so every other caller of `Work` and every existing test is unaffected.

**Refs:** `api/src/askwell/ingest.py` (`Work.password`, `dispatch`, `process`, `PasswordRequest`, `register_ingest`'s `/password` route), `api/src/askwell/worker.py` (`ingest_document`), `api/src/askwell/extract_pdf.py` (`_classify_open_failure`), `docs/backlog/M1-it-answers-from-my-documents.md` ticket `M1-EXTRACT-VAL-030`, issue #131.

## 2026-08-28 — A flagged document is not gated on `status = 'ready'`, and `document_pages` grew its own `ocr_confidence`

**Decision:** `M1-EXTRACT-ING-029` measures OCR confidence per page (`extract_ocr._confidence`, Tesseract's own mean word confidence via `image_to_data`) and stores it two places: `documents.ocr_confidence` is the document-level mean of every OCR'd page, and the new `document_pages.ocr_confidence` keeps the per-page figures that mean was built from. `askwell.ingest.coverage`'s `flagged` count — and every query that feeds it — checks `ocr_confidence < threshold` alone, **not** `status = 'ready' AND ocr_confidence < threshold`. The threshold is `ASKWELL_OCR_CONFIDENCE_THRESHOLD` (default `0.60`), read where a source's status is computed rather than decided inside `extract_pdf`.

**Why:** the natural-looking condition is "a low-confidence *ready* document is flagged" — it is what every other coverage figure in `Coverage` does, gating on `status = 'ready'`. It is wrong here for a reason specific to where the build actually stands: `chunk` and `embed` (`M1-INDEX-ING-031`/`-032`) are not built, so today every document parks at `queued` the moment `extract` finishes successfully, and none ever reaches `ready` at all. Gating the flag on `ready` would have shipped a feature that cannot be observed until two unrelated tickets land — silently correct in the schema, silently inert in the product, and the kind of gap that is only found by someone trying the cold-start walkthrough and wondering why nothing is ever flagged. `M1-EXTRACT-ING-029`'s own dependency list names only `M1-EXTRACT-ING-028`; a flag that actually depends on `M1-INDEX-ING-032` too, without saying so, is exactly the undocumented-dependency failure `AGENTS.md` §9 exists to catch. The per-page `ocr_confidence` column was added for the same reason the ticket's own edge case demands it: "a document that is partly good and partly poor" has to name *which* pages were poor in the source's reason, and the document-level aggregate alone cannot reconstruct that once the run that computed it has finished — a second table per format was rejected as overkill for one nullable numeric column mirroring one that already exists on `documents`.

**Consequences:** `Coverage.flagged`, `source_status`'s `flagged` parameter, and the `/ingest` snapshot's `flagged` list all report on a low-confidence document regardless of whether it is `queued` (parked awaiting `chunk`), `indexing`, or `ready` — the moment `extract` finishes with a low score, the source shows `attention`, before the rest of the pipeline exists to do anything else with the document. `_park`, `_finish`, `_fail`, `retry` and the mid-loop status write inside `process` all now thread `settings.ocr_confidence_threshold` through to `refresh_source`, which did not previously need `Settings` at all. Revisit whether the `ready`-gated framing was right for `failed` too if `M1-INDEX-ING-031` reveals a similar gap there — out of scope for this ticket, not itself decided here.

**Refs:** `api/src/askwell/extract_ocr.py`, `api/src/askwell/extract_pdf.py`, `api/src/askwell/ingest.py`, `api/src/askwell/config.py`, `api/src/askwell/db/migrations/versions/20260828_9a1c6e4f2b57_page_ocr_confidence.py`, `docs/backlog/M1-it-answers-from-my-documents.md` ticket `M1-EXTRACT-ING-029`.

## 2026-08-28 — OCR runs per page, inside `extract` itself, superseding the "parks awaiting `ocr`" decision below

**Decision:** `M1-EXTRACT-ING-028` put OCR directly in `extract_pdf.run`'s per-page loop: a page whose text layer fails `_usable` is immediately rendered, oriented and recognised by the new `askwell.extract_ocr` module (Tesseract via `pytesseract`), in the same pass as every other page. `NeedsOCR` and `ingest.OCR_STAGE` — the "park naming a stage that is not a member of `STAGES`" mechanism the entry below built — are removed. A document is only `EmptyDocument` (the same C5 failure `extract_common` reports for every other format) if OCR was given every page a fair try and none of them came back with text; `documents.ocr_derived` marks a document that used OCR at all, for the source viewer.

**Why:** the entry below's own reasoning — "OCR belongs inside what extraction owns" — argued for parking only because nothing existed yet to hand the document to; `M1-EXTRACT-ING-028` is that thing, and once it exists the honest behaviour is to run it, not to keep naming it as a future stage a document is still waiting on. The ticket's own edge case, "a mixed document — OCR runs only on the pages that need it", also could not be satisfied by the old design: `NeedsOCR` only fired when *every* page had no text, so a mixed document's blank pages had no path to OCR at all short of a second, page-level mechanism. Running OCR inline, per page, the moment a page's text layer fails, satisfies both the whole-document scan and the mixed-document case with one code path instead of two. The alternative — keep `NeedsOCR` for whole-document scans and add a second, page-level OCR trigger for mixed documents — was rejected as exactly the kind of special-casing the original entry was trying to avoid, just moved one level down.

**Consequences:** `awaiting: "ocr"` can no longer appear in `askwell.ingest.snapshot` — every PDF, scanned or not, now parks at `chunk` once `extract` finishes, closing issue #118's underlying condition for this specific case (the frontend still has the general bug of not reading `state.awaiting` for other stages; unaffected). A scanned document now costs one OCR pass per page during `extract` rather than a separate wait for a ticket to land, visible as `extract` taking noticeably longer on a scan than a digital PDF. The API image gained a system dependency, `tesseract-ocr` plus the `eng`/`osd`/`tam` traineddata packages (`api/Dockerfile`), and a Python dependency, `pytesseract`.

**Refs:** `api/src/askwell/extract_pdf.py`, `api/src/askwell/extract_ocr.py`, `api/src/askwell/ingest.py`, `api/Dockerfile`, `api/src/askwell/db/migrations/versions/20260828_75db02ede131_ocr_derived.py`, issue #118.

## 2026-08-28 — `document_pages` grew an `anchor_label` and `documents` grew an `anchor_kind`, rather than a new table per format

**Decision:** `M1-EXTRACT-ING-027` reused `document_pages` for Word, PowerPoint, Excel, text, Markdown and HTML, adding two nullable columns — `documents.anchor_kind` (`page` / `slide` / `sheet_row` / `heading`) and `document_pages.anchor_label` (the human-facing pointer, e.g. "Sheet1, row 45" or a heading's own text). `page_number` keeps meaning "the ordinal `document_pages` was already keyed on" for every format; `anchor_kind`, set once per document, says what that ordinal *is* — a PDF page, a slide, a spreadsheet row, or a heading-delimited section — so `docs/ux/source-viewer.md` §2 knows how to land.

**Why:** the alternative was a table per anchor shape — `document_slides`, `document_sheet_rows`, `document_sections` — each with its own foreign key, its own `page_count`-equivalent, and its own place in every query that reads "this document's extracted units" (chunking, the source viewer, the citation resolver). That is four migrations and four query shapes for a fact that is really one thing with a label: an ordered, addressable unit of a document. `document_pages`' own uniqueness constraint (`document_id`, `page_number`) already gives every format what it needs — a stable ordinal per anchor — and the only thing missing was somewhere to put a label that is not always a plain page number. Two nullable columns is cheaper than a shape change to every downstream reader, and `document_pages` staying the name is a deliberate small cost: the table now holds slides and spreadsheet rows too, and a reader meeting it for the first time has to learn that from this decision rather than from the name.

**Consequences:** `M1-INDEX-ING-031` (chunking) reads one table for every format's addressable units rather than branching on document type to find the right one. `extract_pdf.py` was touched by exactly one line — setting `anchor_kind = 'page'` — to keep every document consistent rather than leaving PDFs as the one format with no anchor kind recorded. If a future format needs an anchor shape `document_pages` cannot express (nested headings with nesting depth, for instance), that is the point at which the "one table" bet gets revisited, not before.

**Refs:** `api/src/askwell/db/migrations/versions/20260828_f70a1c4e9d63_extraction_anchors.py`, `api/src/askwell/extract_common.py`, `docs/ux/source-viewer.md` §2.

## 2026-08-28 — Extraction is a stage that reads Postgres, so every stage now gets a session of its own

**Decision:** `StageFn` grew a third argument — a session factory — alongside `Work` and the `report` progress callback. `extract`'s real implementation (`api/src/askwell/extract_pdf.py`) needs to write pages and a page count to Postgres, and `M1-ADD-ING-025`'s pipeline gave a stage no way to reach the database at all: only a file description and a byte-progress callback. `M1-EXTRACT-ING-026`.

**Why:** the alternative was to have `extract_pdf.run` open its own engine from configuration it does not otherwise need, independent of the one `askwell.ingest.process` already holds — a second connection pool per document, and a settings dependency threaded into a module that has none today. `chunk` and `embed` will need exactly the same thing when their tickets land: chunks and embeddings are both Postgres writes. Extending the signature once, when the first real stage needed it, is cheaper than three modules each solving the same problem slightly differently, and it is a change discoverable by reading `ingest.py` rather than something a second ticket has to rediscover.

**Consequences:** every test stub that plays the part of a stage (`test_ingest_records.py` has eight) took a third parameter. None of them needed to change behaviour — the harness tests care about claim/progress/failure/resume, not about database access — so the diff is mechanical. A real `chunk` or `embed` stage can now write its own tables without inventing a new plumbing pattern.

**Refs:** `api/src/askwell/ingest.py`, `api/src/askwell/extract_pdf.py`, `api/tests/test_ingest_records.py`.

## 2026-08-28 — A whole-document OCR need parks the same way a missing stage does, without being a fourth pipeline stage

**Decision:** `extract_pdf.run` raises `NeedsOCR` when every page of a PDF comes back with no usable text. `askwell.ingest.process` catches it next to the branch that parks on a missing `Stage.run`, and parks the document naming a constant, `OCR_STAGE = Stage("ocr", "M1-EXTRACT-ING-028")`, that is not a member of `STAGES`. `M1-EXTRACT-ING-026`.

**Why:** the ticket's own scope draws OCR as something `extract` detects and hands off to, not a numbered step after `chunk` and before `embed` — chunking and embedding do not care whether a page's text came from a text layer or from OCR, so OCR belongs *inside* what extraction owns, not after it in the pipeline's spine. Making it a fourth `STAGES` entry would have meant every document passes through an "ocr" stage even when it has a perfectly good text layer, and would have required `chunk`'s dependency on "the stage before it" to skip over "ocr" for the ordinary case — two special cases instead of one exception type. A page-level partial case (some pages have text, some do not) is deliberately *not* this path: only a document with zero usable pages anywhere raises `NeedsOCR`; a mixed document proceeds with its blank pages recorded and waiting for `M1-EXTRACT-ING-028` to fill in later, per the ticket's own edge case ("mixed handling per page, not per document").

**Consequences:** `snapshot()`'s `stage_tickets` lookup has to know about `OCR_STAGE` alongside `STAGES`, or a document parked for OCR would render with an empty ticket string — done by merging `(*STAGES, OCR_STAGE)` at the one place that builds that mapping. `M1-EXTRACT-ING-028`, when it lands, either installs a `run` on `OCR_STAGE` and teaches `resume()` about it the same way `installed()` already covers `STAGES`, or the two mechanisms get unified then — deferred rather than guessed at now, since only one caller of `NeedsOCR` exists yet.

**Refs:** `api/src/askwell/extract_pdf.py`, `api/src/askwell/ingest.py`, `docs/backlog/M1-it-answers-from-my-documents.md` ticket `M1-EXTRACT-ING-026`.

## 2026-08-28 — `resume()` also revives a document parked before its stage existed (#109)

**Decision:** `askwell.ingest.resume()`, run at worker startup, now does two things instead of one: it returns `running` jobs a dead worker was holding (unchanged from `M1-ADD-ING-025`), and it also returns `parked` jobs to `queued` when the stage named in `awaiting` now has a `run` installed. `M1-EXTRACT-ING-026`.

**Why:** `M1-ADD-ING-025` shipped a pipeline with nothing installed, so anyone who added material before `M1-EXTRACT-ING-026` landed has documents sitting `parked`, `awaiting = 'extract'`. Issue [#109](https://github.com/Rumeasiyan/askwell/issues/109), filed while building that ticket, named the consequence exactly: nothing re-queues a `parked` row on its own — the reconcile timer only re-dispatches `queued` ones — so those documents stay parked *through* the very upgrade meant to fix them, discoverable only by someone noticing a library that never reaches `ready`. The issue was closed at the time citing this fix as already built; it was not — the closing comment described the intended shape of the work correctly but the code only ever handled `running` rows. This entry is also the correction of that record: `resume()` is where the fix actually lives, alongside the other "work the last process left in a state it cannot leave on its own" case it was already handling.

The filter matters as much as the revival: only rows whose `awaiting` stage is in `installed()` move. A row parked for `chunk` must stay parked — reviving it unconditionally would let `extract` re-claim a document waiting on a *later* stage, run again for no reason, and park again on the very next one, which is #109's bug reproduced one stage later rather than fixed.

**Consequences:** every future stage ticket gets this behaviour for free rather than having to remember to add it — the alternative considered and rejected was re-queuing parked rows in the migration that installs each stage, which is exactly the kind of thing a future ticket forgets. `resume()` is now the one place "a stage just became real" and "a worker just came back from being interrupted" are both handled, which is why they are documented together here rather than as two separate entries.

**Refs:** `api/src/askwell/ingest.py` (`resume`), `api/tests/test_ingest_records.py`, issue [#109](https://github.com/Rumeasiyan/askwell/issues/109).

## 2026-08-28 — Postgres is the ingestion queue's record and Redis is only its transport

**Decision:** `ingest_jobs` in Postgres holds one row per document with its state, stage, attempts, error and byte progress, written in the same transaction as the document itself. `arq` on Redis is used only to wake a worker. When the two disagree, Postgres wins: `resume()` returns interrupted jobs at worker startup, and a `reconcile` cron re-dispatches queued rows every thirty seconds. A dispatch that fails is logged and swallowed — never raised into the user's request. `M1-ADD-ING-025`.

**Why:** the obvious implementation is to let `arq` be the queue, which is what it is for, and it would have been perhaps eighty fewer lines. It was rejected because of what this queue is *for*. The user adds five hundred papers and goes to make tea; the failure modes that matter are all the ones where the process holding the work stops existing. A job that lives only in Redis is lost by `podman compose down -v` — which the compose file documents as a normal thing to run — by a worker killed mid-job, by a laptop suspended for two days, and by an enqueue that failed after the API had already committed the documents and answered 201. Each of those leaves the library saying "queued" about work nothing will ever pick up, and none of them produces an error anywhere. Redis is configured with `appendonly yes` and would survive most of that, which is exactly what makes the failure rare enough to escape testing and severe when it happens.

The second reason is that the queue has to be *readable*. "This file failed, here is why, retry" is a sentence the library renders, and per-file byte progress is what stops a 900-page scan looking hung. Both are queryable columns in Postgres and neither is a thing `arq` stores. Having built the table for the surface, making it also the record costs one insert.

What is being accepted knowingly: two systems that can disagree, and a reconcile loop as the price of that. It runs every thirty seconds and is a no-op in the ordinary case, because the enqueue at add time is what actually starts an import. The alternative — polling Postgres as the only queue with `SELECT … FOR UPDATE SKIP LOCKED` and no Redis at all — was also rejected, and less comfortably: it is a sound design and it would have contradicted `docs/architecture.md` §2, which names Redis and `arq` as the queue, without the ticket having any quarrel with that choice.

**Consequences:** anything that enqueues work must write the row and dispatch separately, in that order, with the dispatch outside the transaction — dispatching inside it asks a worker to collect rows that do not exist yet. `arq` job ids are derived from the document and its attempt, so re-dispatch is idempotent and a retry is not swallowed as a duplicate. `askwell.ingest.process` must never raise: `arq`'s retry counter lives in Redis, and a failure the user has to see cannot. Reversing this means deleting `ingest_jobs` and giving up the failure surface and the progress columns with it.

**Refs:** `api/src/askwell/ingest.py`, `api/src/askwell/worker.py`, `api/src/askwell/db/migrations/versions/20260828_d5b2e8c17f40_ingest_jobs.py`, `docs/architecture.md` §2, issues [#111](https://github.com/Rumeasiyan/askwell/issues/111), [#105](https://github.com/Rumeasiyan/askwell/issues/105).

## 2026-08-28 — The ingestion pipeline declares the stages it has not built, and parks rather than pretending

**Decision:** `askwell.ingest.STAGES` names `extract`, `chunk` and `embed` with the ticket each arrives in, and installs none of them. A job runs, reaches the first stage with no implementation, and comes to rest in a state of its own — `parked` — recording which stage it is waiting for. The document stays `queued`, the source stays `queued`, and the progress surface renders the missing stage's name and ticket. `M1-ADD-ING-025`.

**Why:** the ticket asks for the queue and puts extraction and embedding explicitly out of scope, which leaves a pipeline with nothing in it and a question about what a job should therefore *do*. Three answers were available and two of them are lies.

Marking the document `ready` when the pipeline runs out of installed stages was rejected outright: `ready` is what retrieval will read as "this document has passages", and a corpus that claims to be searchable and is not is the C4 failure with a progress bar drawn over it. Marking it `failed` was rejected too, more mildly — nothing is wrong with the file, and a fresh install whose first act is to turn the user's whole library red teaches them not to trust the status column at all.

Leaving the document at `queued` and the job at `parked` is the third answer, and it happens to be the one `docs/states-and-edge-cases.md` §3 already asked for before this ticket existed: *"files queued but nothing indexed yet — said plainly, with what has to land before they are searchable ... an honest sentence, not a progress bar that never moves"*. `awaiting` is the column that makes the second half of that sentence possible; without it the screen can say a file is waiting and cannot say what for.

The alternative considered at more length was installing a real first stage so the harness would have something to run — specifically, moving the content hashing out of `POST /sources` (issue #105) and making it the pipeline's first step. It would have made every acceptance criterion demonstrable today rather than under test. It was rejected because the per-file outcomes that add currently returns synchronously — duplicate, refused, arrives-later, each with its reason — are what the add screen renders, and moving recording onto the queue means those arrive over the progress stream instead. That is a rewrite of the add screen's result flow, inside a ticket scoped to "job enqueue per document" and labelled backend, and doing it here would have been a large change carried in behind a small one. #105 is re-owned with that reasoning rather than closed.

**Consequences:** no document reaches `ready` until `M1-EXTRACT-ING-026` and the two index tickets land, and the acceptance criteria about progress advancing per file are proved by tests that install a stage of their own rather than by a walkthrough. A stage ticket now has one job here — supply `run` — and changes nothing else. Documents parked before a stage is installed are not automatically re-queued when it appears, which is issue [#109](https://github.com/Rumeasiyan/askwell/issues/109) and must be fixed before or with `M1-EXTRACT-ING-026`. If `STAGES` is ever trimmed to only what exists, a waiting document loses the ability to say what it is waiting for and the honest sentence becomes a bare "queued".

**Refs:** `api/src/askwell/ingest.py`, `docs/states-and-edge-cases.md` §3, `docs/ux/add-source.md` §5, issues [#109](https://github.com/Rumeasiyan/askwell/issues/109), [#105](https://github.com/Rumeasiyan/askwell/issues/105), [#111](https://github.com/Rumeasiyan/askwell/issues/111).

## 2026-08-28 — SELinux does refuse the roots mount, and the answer is a consented relabel rather than disabling confinement

**Decision:** The unverified SELinux risk recorded on 2026-08-27 is now measured and confirmed: on an enforcing Fedora host, a container reaching the `ASKWELL_ROOTS_MOUNT` bind mount is refused every file under it. The mount keeps `:ro` and keeps **no** `z` flag. The supported resolution is a one-off `chcon -R -t container_file_t <folder>` that the user runs themselves, surfaced in the refusal message and at root registration. `--security-opt label=disable` is rejected.

**Why:** The 2026-08-27 entry chose to omit `z` because `z` relabels recursively and would silently rewrite SELinux labels across a user's entire material tree — slow on 40 GB, and a modification Askwell has no business making to files it only ever reads. That reasoning still holds; what was missing was whether the omission actually broke anything. It does. `podman exec askwell-api-1 ls -ln` on a mounted folder returns `-????????? ? ? ? ?` for every entry and `POST /sources` refuses all of them, so the cost of the decision is total: on the maintainer's own distribution Askwell can read zero files, and every ingestion ticket after M1-ADD-BE-023 would have been blocked by it.

Three ways out were weighed. Adding `z` back is the automatic fix and was rejected again for the original reason — a tool that relabels a user's whole home directory as a side effect of being pointed at it is doing something the user did not ask for and cannot easily see. `--security-opt label=disable` looks cheaper because it is one line in `compose.yaml` and touches none of the user's files, and it is the worse trade: it removes SELinux confinement from precisely the two containers that hold the user's entire corpus and talk to the model, in order to fix a labelling problem scoped to one directory. Narrow problem, broad remedy, and invisible afterwards. The relabel keeps the blast radius at the folder the user nominated, and — unlike `z` — it is a command they type, so it is consented to rather than done to them.

The accepted cost is a manual step on SELinux distributions. That is tolerable only if the product says so at the right moment, which is why the resolution is not "document it": the refusal message must carry the exact command with the folder substituted, and root registration should report the state before the user drops sixty contracts and watches all sixty be refused. `askwell.roots.probe()` already has an `unreadable` state to report it through.

**Consequences:** Fedora/RHEL/CentOS users need one `chcon` per nominated tree before Askwell can read it. Until #107 lands, they get a refusal that names SELinux but not the command. The offline install bundle (Phase 7) has to carry this too, or first-run on an enforcing host fails silently for a whole class of users. Reversing this means either accepting recursive relabelling of user data or dropping container confinement — both were considered and rejected here.

**Refs:** [#107](https://github.com/Rumeasiyan/askwell/issues/107); the 2026-08-27 entry on the roots mount; `compose.yaml` api and worker `volumes`; `api/src/askwell/roots.py` `probe()`; `api/src/askwell/sources.py` `UNREADABLE_REASON`.

## 2026-08-28 — Build-runner agents run with permissions bypassed, so they can run the toolchain

**Decision.** `scripts/build-runner.sh` invokes its build, fix, audit and doc agents with `--permission-mode bypassPermissions` instead of `acceptEdits`. `AGENT_PERMISSION_MODE` still overrides it.

**Why.** `acceptEdits` accepts edits and nothing else. Every Bash call remains a permission prompt, and in `--print` mode a prompt is a refusal rather than a pause — so the agent could write code and could not run a single command. No formatter, no typechecker, no test runner, no `gh`.

This stayed invisible for three tickets because the gate reports the *result*, not who produced it. It surfaced on `M1-ADD-BE-023`, which failed the gate three times on `lint` and `format` — checks its own author was structurally unable to run — and whose handover said plainly: "the sandbox refused `podman`, `node`, `python3` and `gh`. **Nothing here has been executed**." The fix agent, sandboxed identically, could not repair a formatting failure either, which is why attempt 2 failed on the same row as attempt 1.

An agent that cannot run the toolchain cannot check its own work, so every failure it could have caught in a second becomes a person reading a diff instead — the opposite of what an unattended runner is for. On the salvage, the work needed one `ruff format` run to pass the entire gate.

**What was rejected.** Keeping `acceptEdits` and having a person finish each ticket by hand. That is roughly half an hour of attention per ticket across the remaining backlog, and it makes the runner a code generator rather than a builder.

**The trade-off accepted.** `bypassPermissions` lets these agents run arbitrary commands on the machine, not merely edit files. That is a genuine loosening, and the original comment's containment argument does not cover it — but that argument never rested on the dialog. What holds is unchanged: the runner works on a branch, an audit agent that did not write the code reviews the diff, CI runs, and a person merges. Reverting is one environment variable, at the price of a gate that rejects work the agent had no way to verify.

**Consequences.** Build agents can now run `scripts/dev.sh`, so a gate failure comes to mean the agent could not fix something rather than could not attempt it. Anyone running the queue should know it executes agent-chosen commands unattended.

**Refs.** `scripts/build-runner.sh` `run_agent`; issue #102, PR #103; `.build-runner/logs/M1-ADD-BE-023.*`.


## 2026-08-28 — A duplicate is recognised by the application and made impossible by the database

**Decision:** `askwell.sources.add` looks a file's SHA-256 up across **every live document**, and a match is reported as a duplicate linked to the existing document rather than stored again. The partial unique index the v1 migration already created — `uq_documents_live_source_id_sha256`, over `(source_id, sha256) WHERE deleted_at IS NULL AND superseded_by IS NULL` — enforces a narrower rule underneath it. The two are deliberately not the same rule and neither replaces the other. `M1-ADD-BE-023`.

**Why:** The recognition has to be global because the user's problem is global: the same contract in three folders is three *sources*, and a per-source check would recognise none of them — the ticket's own cold-start walkthrough, add a PDF then add the same PDF from a different folder, would produce two documents and two identical passages in every future answer.

The index cannot be global, and that is not a compromise. A unique index over `(sha256)` alone would mean a second nominated folder containing a legitimate second copy could never be recorded at all, even by a later ticket that decides it should be — supersession (`M1-INDEX-BE-034`) and deletion (M2) both need room to move here, and an index is the wrong place to encode a product rule that is still being worked out. What the index *can* say without foreclosing anything is that one source never holds the same live content twice, which is exactly the invariant a retry, an import or a repair script would break by accident.

So: the application check is what produces a sentence for the user, and the index is the floor under it. Enforcing only in application code was rejected because a rule with one enforcement point lapses the first time a second code path forgets to ask, and this one would lapse silently — nothing looks wrong about two rows. Enforcing only in the database was rejected because an `IntegrityError` is not an explanation, and "already present, here is where" is the whole user-facing point of the ticket.

Partial over the live rows for the same reason `roots` is: a document the user deleted last week must be addable again, and a plain constraint would refuse and blame them for the deletion.

**Consequences:** Every code path that inserts a document must expect the index and handle the duplicate case, rather than assuming inserts succeed. Supersession in `M1-INDEX-BE-034` must set `superseded_by` on the old row *before* or in the same statement as inserting the new one, or the index will refuse the new version — which is the correct behaviour and will be discovered as a failing test rather than as duplicated content. The global recognition means a file present under two nominated folders is recorded once, under whichever folder was added first; the second folder's source will not list it. That is the right answer for retrieval and the wrong answer for a library that wants to show what is in each folder, and it is the thing to revisit if the library screen makes it look like files are missing.

One thing this pass *found* rather than decided: the index existed in every database and in no model, because the v1 migration created it in raw SQL. `askwell.db.models` now declares it. Nothing changes in any database — but an `--autogenerate` run compares the model to the schema, and until this it would have proposed dropping the invariant.

**Refs:** `api/src/askwell/sources.py`, `api/src/askwell/db/models.py`, migration `a8208099ef38` (`_create_invariants`), migration `c3d9e1a45b76`, `docs/ux/add-source.md` §5, `docs/states-and-edge-cases.md` §3.

---

## 2026-08-28 — `queued` is a status, and the server re-detects what the browser already detected

**Decision:** Two changes that arrived together with the record path. `queued` is added to both `SOURCE_STATUSES` and `DOCUMENT_STATUSES` and becomes the default; and `askwell.filetypes` re-implements the browser's content detection server-side, reading the file itself, with nothing the client says about a file's type ever reaching a row. `M1-ADD-BE-023`.

**Why (the status):** The vocabulary had `indexing`, `ready`, `attention` and `deleted`, and none of them was true of a row this ticket creates. Nothing is reading these files — the ingester is `M1-ADD-ING-025` — so `indexing` would be a claim that work is underway, and the library would render a progress bar from it that never moves. `docs/states-and-edge-cases.md` §3 names that exact failure and asks for an honest sentence instead. Reusing `attention` was rejected: nothing is wrong. Leaving the status null was rejected: the column is not nullable, and a null status is a row nobody can filter on.

**Why (the re-detection):** The duplication of the signature table between `web/lib/add-source.ts` and `api/src/askwell/filetypes.py` is real and is the price of a boundary that means anything. The browser is the only place with the bytes before anything is sent, so it is where the user is told what Askwell believes their files are while a drop is being read — but a record built from that answer would send a renamed executable to a document extractor, and the value of detecting by content evaporates at precisely the step where it would have had teeth. It is the same shape C2 warns about in the SQL case: a check performed where the thing being checked can influence it.

Sending no type from the client and having the screen render one the server returns was rejected — it costs a round trip per file, and on a five-thousand-file drop the screen would say nothing for minutes about files it can already describe. Having the server trust the client was rejected for the reason above.

**Consequences:** Two copies of one table, which will drift unless kept honest; `api/tests/test_filetypes.py` and `web/lib/add-source.test.ts` deliberately ask the same questions so a one-sided change fails a test rather than going unnoticed. One divergence exists already and is deliberate: the server refuses to take a file away from the files route on a delimiter or SQL-keyword heuristic when its own extension claims that route, because since `M1-ADD-VAL-024` a wrong route means a supported file is silently withheld with "arrives in M4". Fixing it server-side does not fix it for the user — the client decides what is sent at all — so the client half is an open item rather than a silent asymmetry. Anything reading `status` must now handle `queued`; the migration is reversible and moves existing `queued` rows to `indexing` on the way down, because a migration that cannot run backwards is not reversible in any sense worth the word.

**Refs:** `api/src/askwell/filetypes.py`, `api/src/askwell/db/models.py`, migration `c3d9e1a45b76`, `docs/BRAIN.md` (open items).

---

## 2026-08-27 — Detection answers three ways, because "not yet" is not "no"

**Decision:** `detect()` returns a `verdict` of `supported`, `later` or `refused` instead of a `supported` boolean, and the `later` case carries the milestone its route arrives in. A CSV or a dump is now recognised, named, dated and **not queued**; only files on the `files` route reach the queue. The verdict is derived from `ROUTES[].arrives` — the same table the screen renders the three coming-later panels from — rather than written down a second time. `M1-ADD-VAL-024`.

**Why:** The boolean was wrong in a way one viewport made visible. `M1-ADD-FE-022` shipped a screen that rendered "Spreadsheet or CSV — Arrives in M4" and, a few centimetres above it, queued a dropped CSV as though that route worked and counted it as added. Two statements contradicting each other in one glance, and the one a user believes is the one that named their file.

The two ways of resolving that contradiction with a boolean are both worse than a third value. Marking CSV `supported: false` makes the screen consistent and makes it lie in the other direction: "unsupported format" is what somebody whose material is a folder of quarterly exports reads as *this product is not for me*, and they are exactly the user M4 is being built for. Leaving detection alone and filtering at the queue boundary keeps the truth in the module but scatters the milestone knowledge into whichever caller happens to remember — and the caller that forgets is the one that ships.

Three values put the fact in the one place that has the evidence. Deriving them from `ROUTES` rather than hardcoding `"M4"` matters more than it looks: when M4 lands and `arrives` becomes null for the table and dump routes, every CSV already being detected becomes `supported` with no second edit and no chance of a stale milestone printed beside a working feature. A hardcoded date is the copy that gets forgotten.

Rejected alongside: refusing the whole drop when any file in it is unsupported. That is one line of code cheaper and it is the behaviour the ticket names as the failure — one archive among sixty contracts must not take the contracts with it.

The same pass added **Markdown and HTML**, which `docs/data-sources.md` §1 has listed as supported since it was written and which detection did not have. HTML is judged on its opening rather than its name and is checked *before* the delimiter test, because a saved page is full of rows and was being routed to the table route — which, under this decision, would have told somebody their web page arrives in M4. Markdown is the one case decided by the extension, since no byte distinguishes it from plain text; getting it wrong costs nothing, because both go to the same extractor and the user is told which one Askwell believed.

**Consequences:** `Detection.supported` is gone; anything reading it must read `verdict`. The queue has two more terminal phases — `later` and `empty` — which exist so that "your CSVs arrive in M4" and "nothing was in that folder" are not both rendered as *Refused*. `M1-ADD-BE-023` must re-detect server-side from the same signature table: this whole module runs in the browser, so it is a courtesy to the user and not a boundary, and a source record built from a client-declared type would send a renamed executable to a document extractor. When M4 lands, the only change needed here is `arrives: null` on the table and dump routes — if a second edit turns out to be needed, this decision was implemented wrongly.

Rejections are counted locally, in `localStorage`, alongside the added counter (C1: there is no transmission path and none is being built). They are **not** written to the operational log, because nothing is sent to the API for a file that was refused and this ticket adds no endpoint to send it to. That gap is tracked rather than papered over.

**Refs:** `web/lib/add-source.ts`, `web/components/add/add-state.tsx`, `web/components/add/add-screen.tsx`, `docs/ux/add-source.md` §5, `docs/states-and-edge-cases.md` §3, `docs/data-sources.md` §1. Supersedes the queue behaviour recorded in the entry below.

---

## 2026-08-27 — A dropped file is judged by its contents, and the browser is asked where it came from

**Decision:** The add flow decides what a file is from its first 4 KB, using the extension only to tell the four zipped Office formats apart and to report a disagreement in the user's own terms. And because no browser will say where a dropped file actually lives, the screen asks once per drop which folder it came from — the same typed path `docs/ux/add-source.md` §7 already uses for nominating one — rather than pretending it knows. `M1-ADD-FE-022`'s stated assumption that "the browser's drop event gives usable paths under every supported platform" is **false on every platform**, and this records that rather than working around it quietly.

**Why:**

**Contents over extension, because the extension is a claim the user did not make.** Files arrive renamed, exported by tools that guess, or saved from a browser that appended the wrong suffix. Trusting the name means a mislabelled PDF reaches a PDF extractor, which fails somewhere deep in a library and surfaces as an error about the wrong thing entirely — and the user never learns the useful fact, which is that one of their documents is not what it says it is. The ticket asks for detection "by content as well as extension" and the honest reading of "as well as" is that both are consulted and the disagreement is reported: the file is routed by its contents and the screen says *named `.pdf`, contents are a PNG image*. The rejected alternative — route by contents and stay silent — is the one that loses information the user would want.

**The extension is kept for the one job it is better at.** `.docx`, `.xlsx`, `.pptx` and every OpenDocument format are all a zip whose first four bytes are identical. Telling them apart from the bytes means reading the zip central directory, which is a real parser to maintain for a fact the filename already carries accurately in practice. The trade-off accepted: a `.docx` renamed to `.xlsx` is described wrongly. That is a narrower and less consequential error than the one being avoided, and the extractor will discover the truth in M1-EXTRACT.

**A program is refused as a program, not as "an unsupported file".** ELF, Mach-O, PE and shebang scripts are named, with the sentence that nothing was run and nothing was read past the first few bytes. Somebody who has just dropped a folder containing a binary needs to know Askwell did not execute it — this is the same instinct that makes C3 put dumps in a sandbox, applied where a sandbox is not available because nothing is being executed at all.

**Why the folder is typed, and why that is not a regression.** Browsers expose a file's name and its path *within a dropped folder*, and deliberately never its absolute path; that is a sandbox rule, not a missing API, and no flag or permission changes it. Three options existed. *Upload the bytes* — rejected outright: it is copying the user's material, which is the one thing this product promises not to do, and C1 makes the direction of travel irrelevant. *Guess the path from the file name and the nominated roots* — rejected: it produces a path that is right most of the time, and a citation that opens the wrong file is worse than one that opens nothing. *Ask once per drop* — chosen. It is one question for a whole folder of 60 contracts, it is the same field and the same seam as nominating a folder, and `M7-TAURI-FE-182` deletes the question rather than improving it, because the desktop shell already knows the path. `selection.ts` exists as its own module for exactly that swap: nothing downstream of it knows how a file was chosen.

**One covering check per drop, not one per file.** A root is a permission over a tree, so if it covers the first file under a folder it covers all of them. Asking `GET /roots/covering` per file would be several thousand requests to learn one fact.

**Why the estimate is not a duration.** The ticket asks for "an honest estimate". Nothing in this repository has yet measured embedding throughput on a CPU, so any minutes-and-hours figure here would be invented — and it would be read as measured, because it is printed next to a real count and a real size. The count and the size are shown, and the duration arrives with `M1-ADD-ING-025`, which is the first thing able to observe it.

**Consequences:** Detection is a table of magic numbers that has to grow as formats are added, and it lives in `web/lib/add-source.ts` — on the *client*, which is the only place with the bytes before anything is sent. `M1-ADD-BE-023` will need its own check server-side: the client's answer is a courtesy to the user, never a security boundary, and the extractor must not trust it. The typed folder is one more thing to get wrong on a first run, mitigated by the drop being expanded and counted before it is asked. Reversing the typed-folder decision means a host that reports real paths, which is precisely what M7 delivers.

**Refs:** `docs/backlog/M1-it-answers-from-my-documents.md` `M1-ADD-FE-022`; `web/lib/add-source.ts`, `web/lib/selection.ts`, `web/components/add/`; `docs/ux/add-source.md` §1, §2, §5, §7.

## 2026-08-27 — Nominated folders are mounted at their own paths, and mount state is never stored

**Decision:** The folders Askwell may read live in their own table, `roots`, tombstoned on removal. One host directory — `ASKWELL_ROOTS_MOUNT` — is bind-mounted read-only into the API and the worker **at the same absolute path it has on the host**, and every nominated folder must lie under it. Whether a folder is currently readable is **probed on every read and never stored**. A folder outside the window is registered anyway, reporting `not_mounted` and the line to add.

**Why:**

**Identity mounting, because the alternative is a translation layer in five places.** `sources.root_path` and `documents.path` hold host paths. That is not an implementation detail — it is what the user typed, what the source viewer displays, what the native directory picker returns in M7, and what a citation has to reopen two years later. Mounting the window at, say, `/roots` inside the container would mean converting between host and container form at every one of those points, and the failure mode of one missed conversion is a file Askwell cannot find for a reason invisible in the data. Mounting it at its own path makes the conversion the identity function, and an identity function cannot be forgotten. The cost is that the window is a real host path in configuration and cannot be a container-internal convention.

**Why probe rather than store.** A `mount_state` column is the obvious design and it is wrong on a laptop. The two things that change it — a USB drive being unplugged and `.env` being edited — both happen while nothing is watching, and there is no moment at which anything would correct the stored value. A registry that reports a drive as available an hour after it was removed is worse than one that says nothing, because the user acts on it. Probing costs one `scandir` per root per read, on a list that will hold single digits.

**Why a table rather than a key in `settings`.** `settings` is key/value and a JSON list under one key would have worked for the list. It would not have worked for removal, which is the part that matters: a source under a removed folder has to be able to say *why* it stopped being readable, and "you removed this folder" and "no folder ever covered this path" are the same silence to a registry that deleted the row. The tombstone needs somewhere to live, and so does the partial unique index that lets a folder be nominated, removed and nominated again — which is a normal sequence a plain unique constraint would refuse while blaming the user for the earlier step.

**Why an unmountable folder is accepted rather than refused.** Everything else that cannot be read is refused at registration — a folder that is not there, a file given as a folder, one Askwell may not traverse — because those are true now and will not fix themselves. `not_mounted` is different in kind: nothing is wrong with the folder, the containers simply have no window onto it, and no platform Askwell supports can add a mount to a running container. Refusing would make a fresh install, which has no window configured at all, unable to nominate anything. So it is recorded, and the reply names the variable and the command. `docs/backlog` already calls that restart a known gap rather than a defect; this makes it a stated one instead of a discovered one.

**What was rejected.** *Mounting `$HOME` by default* — it removes the restart for almost everyone, and it hands the containers every file the user owns, which is the precise thing nominating a folder exists to avoid. The default is now no window at all, which is honest about what has been granted. *Mounting each nominated folder individually* — correct in principle and impossible in practice: Compose files are static, and generating one per registration turns a user action into a rewrite of the file that defines their stack. *Storing container-relative paths* — see identity mounting above. *`z` on the roots mount* — it relabels recursively, which on a 40 GB tree is slow and changes SELinux labels on files Askwell has no business modifying; the accepted cost is that an SELinux host may refuse the mount, which surfaces as a folder in the `unreadable` state naming SELinux rather than as an empty folder. Whether it does refuse is **unverified** — see the open item in `BRAIN.md`.

**The containment check is not a string prefix, and that is not a detail.** `startswith` says that `/home/anna/clients` contains `/home/anna/clients-archive`, which is a different folder the user did not nominate. The check compares path components, and it also resolves symlinks — one link placed inside a nominated folder would otherwise stand in for the whole disk, which is exactly the permission the user declined to give.

**Consequences:** A user with material in two unrelated trees must set `ASKWELL_ROOTS_MOUNT` to a common ancestor, which is wider than either. That is a real cost of one window, accepted because the app-layer check is what actually narrows access — the mount is a route, the registry is the permission. Reversing identity mounting means adding host↔container path translation at every place a path is stored, displayed or reopened. Anything that later reads a file must go through `askwell.roots.covering()`; a path no root covers is never read, and that is the only enforcement point.

**Refs:** `docs/backlog/M1-it-answers-from-my-documents.md` `M1-ADD-ING-021`; `api/src/askwell/roots.py`; `api/src/askwell/db/models.py`; `compose.yaml`; `docs/ux/add-source.md` §7; `docs/states-and-edge-cases.md` §3.

---

## 2026-08-27 — Inference is native, supervised on the host, reached through a bridge container

**Decision:** `llama.cpp` runs natively on the host, supervised by a standalone stdlib-only script (`deploy/inference/askwell-inference`). The API and worker reach it over a **Unix domain socket**, and that socket is owned by a small **bridge container running with host networking**, not by the host supervisor. `ASKWELL_INFERENCE_SOCKET` replaces the host-and-port pair.

**Why:** Three constraints collided, and each one was only visible by running the thing.

**C1 versus GPU.** Every service sits on a Compose network declared `internal`, which has no route off the machine — that is what makes bypassing the egress proxy impossible rather than discouraged. Inference must be native so GPU acceleration works on all three platforms. Those are incompatible as stated: a container with no external route cannot reach a host process. Verified: `host.containers.internal`, `host.docker.internal` and `10.0.2.2` all return `Network is unreachable`, and the bridge gateway `podman network inspect` reports does not exist as a host interface at all, because this is **rootless** podman and that gateway lives inside a user namespace.

**The API cannot supervise it.** `M0-MODEL-DEPLOY-018` says the API starts, stops and supervises the native process. A containerised API cannot start a host process. Supervision has to live on the host regardless, which is also where M7's installer will run it — so the shape is the one that ships rather than a scaffold.

**The host's Python is not ours to choose.** The first supervisor was part of the `askwell` package; installing it failed with `Package 'askwell' requires a different Python: 3.14.6 not in '==3.12.*'`. A host-side component that dictates the host's Python version is a component that does not install. It is now standard library only and runs on whatever is there.

**And then SELinux.** The obvious arrangement — the host supervisor owns the socket, containers connect to it — is refused:

```
AVC denied { connectto } ... comm="askwell-api"
  scontext=...container_t  tcontext=...unconfined_t  tclass=unix_stream_socket
```

The *file's* label is irrelevant; the **listener's process label** decides, and the host supervisor is unconfined. Relabelling the directory changes nothing. So the socket is owned by a container instead, and `container_t` connecting to `container_t` is allowed — verified with a throwaway listener before any of this was written.

**What this costs, stated plainly.** The bridge is the one container with host networking, which means it is the one container that can reach the internet. That is a real widening of the claim in `docs/architecture.md` §5 rather than a technicality, and pretending otherwise would be the same overclaim C6's wording rules exist to prevent. It is mitigated by being fifty lines whose every connection is to `127.0.0.1` — a guarantee you get by reading it, not one the network enforces. Everything that touches the user's material — the API, the worker, the database, the queue — stays internal with no route out, and that part is still structural.

**Rejected:** running `llama.cpp` in a container on the internal network — CPU-only on every platform Askwell targets, and the accelerated profiles are the entire reason the process is native. Adding an SELinux policy module — a change to the security policy of someone else's machine to accommodate our own IPC choice. Giving the API a second non-internal network — that is the internet back, for the component that holds the user's corpus. Adding the podman bridge to firewalld's trusted zone — same objection, and it would not have helped, since the interface does not exist.

**Consequences:** The host now runs one Askwell process alongside the stack, which `AGENTS.md` §5's "Podman and nothing else" no longer covers — that claim is about the *toolchain*, and inference is native by design. Started with `scripts/dev.sh inference`. The health probe checks a socket rather than a TCP port. On Windows and macOS the SELinux constraint does not exist, so the bridge container may be unnecessary there; it is kept uniform for now and flagged for M7. Verified end to end on Linux: a completion request from inside the API container reached llama.cpp and returned an answer.

**Refs:** [#86](https://github.com/Rumeasiyan/askwell/issues/86), `docs/architecture.md` §5, `deploy/inference/askwell-inference`, `api/src/askwell/inference/bridge.py`.

---

## 2026-08-27 — Askwell does not own its own tables

**Decision:** The database has three roles. `askwell` owns the schema and runs migrations. `askwell_app` is what the application connects as, owns nothing, and has no `UPDATE`, `DELETE` or `TRUNCATE` grant on either audit table. `askwell_readonly` is independent of both and can only read. Role creation and passwords live in the Postgres initialisation hook (`deploy/postgres/10-roles.sh`); the grants live in the migration.

**Why:** C6 says the audit log is append-only and tamper-evident, and the enforcement point named for it has always been "no `UPDATE`/`DELETE` grant for the app role". The obvious implementation — connect as the database user Compose already creates, then `REVOKE UPDATE ON audit_decisions` — does nothing whatsoever, because **a table owner bypasses its own grants**. The `REVOKE` succeeds. The privilege listing afterwards looks correct. And the application can still rewrite every audit record it has ever written. It would have shipped looking exactly like a working guarantee, and the only way to find out otherwise is to try it as the role that actually runs.

So the constraint forces a second login role, which forces a second password, which is why the split exists: a password cannot go in a migration (C8), and grants belong with the schema they apply to. Both halves are idempotent, and the migration creates either role as a passwordless fallback so a database that missed the hook still gets a correct permission model — it just cannot be logged into, which is a loud failure rather than a quiet one.

`askwell_readonly` is created now and unused until M4. It is C2's second line of defence: model-generated SQL is parsed and rejected by `sqlglot` **and** executed as a role that physically cannot write. One check is not a guarantee, and the user's real database is on the other side of it.

**Rejected:** row-level security on the audit tables — the owner bypasses that too, and it is slower and harder to reason about. A `BEFORE UPDATE` trigger raising an exception — a trigger is application logic living in the database, and anyone with the owner's connection can drop it; it also cannot be described honestly as "no grant exists". Doing nothing and enforcing append-only in Python — that is precisely the thing C6 exists to not rely on.

**Consequences:** `.env` now carries three passwords rather than one. Anyone pointing Askwell at their own existing Postgres must create the two roles themselves; the migration will make them, but without a login. The initialisation hook only runs on an empty data directory, so an existing development volume needs `podman compose down -v` once. Reversing this means accepting that the audit log's guarantee is advisory.

**Refs:** [#65](https://github.com/Rumeasiyan/askwell/issues/65), `docs/architecture.md` §7, `deploy/postgres/10-roles.sh`, the `_grant_privileges` function in `api/src/askwell/db/migrations/versions/20260827_a8208099ef38_v1_schema.py`, `api/tests/test_invariants.py`.

---

## 2026-08-26 — The toolchain lives in the image; the lockfile is the pin

**Decision:** The API image pins Python 3.12 and carries `uv`, `ruff`, `mypy` and `pytest` inside it. Nothing but Podman is installed on the host, and the host's Python is never invoked. Dependency bounds live in `api/pyproject.toml`; the exact versions live in `api/uv.lock`, and the image installs with `uv sync --locked`. The package version is read from the root `VERSION` file at build time by `api/hatch_build.py` and at run time by `askwell._version`, so it is never typed twice.

**Why:** The obvious alternative — a virtualenv on the host, `pip install -r requirements.txt` — fails on this machine on the first command. The host runs Python 3.14; the project targets 3.12 because llama-cpp bindings, OCR and embeddings have no 3.14 wheels. A contributor taking the obvious path gets a wheel-build failure on day one, before they have any context to diagnose it, and the error message will be about a C compiler rather than about a version. Putting the interpreter in the image makes that class of failure impossible rather than documented.

`--locked` over `--frozen` is the part worth recording, because both look correct and only one is. `--frozen` installs whatever the lockfile says and never reads `pyproject.toml`, so adding a dependency and forgetting to relock produces a **build that succeeds while missing it** — surfacing much later as an `ImportError` in unrelated code. This was verified, not assumed: with `--frozen`, adding `httpx>=0.27` to the manifest and rebuilding succeeded; with `--locked` the same change failed the build with `To update the lockfile, run uv lock`. A silent hole in the reproducibility guarantee is worse than no guarantee, because people rely on it.

Version resolution prefers the `VERSION` file over installed metadata, which is the opposite of the usual ordering, and deliberately. Metadata is stamped once at install time. With the source mounted into a container — the normal development loop here — a `VERSION` bump would otherwise stay invisible until someone remembered to reinstall, and §7 exists precisely to stop a build reporting a number that matches nothing. Released installs have no `VERSION` file above `site-packages` and fall through to metadata, which by then holds the same value.

**Rejected:** a `requirements.txt` with `pip-compile` (no project metadata, so the single-source version trick has nowhere to live); Poetry (declares its own version in `pyproject.toml`, reintroducing the second source); a devcontainer (ties the loop to one editor, and this project's contributors have not arrived yet to have an editor in common); running tools on the host with `pipx` (the 3.14 problem again, one layer along).

**Consequences:** Every Python command now goes through `scripts/dev.sh`, which costs a container start (~1s) per invocation. That is the price of the host needing nothing, and it is paid on every lint. Adding a dependency is a two-step action — edit the bound, run `scripts/dev.sh lock`, review the diff — and the build will refuse until both are done. `scripts/dev.sh` runs everything with `--network=none` except `lock`, so a dependency that tries to reach the network during a test fails visibly rather than working on the maintainer's machine and nowhere else. Reversing this means putting a Python version constraint on every contributor's host, which is the thing being avoided.

**Refs:** [#53](https://github.com/Rumeasiyan/askwell/issues/53), `docs/backlog/M0-it-runs.md` ticket `M0-FOUND-DEPLOY-001`, `api/Dockerfile`, `api/hatch_build.py`, `api/src/askwell/_version.py`, `scripts/dev.sh`, `AGENTS.md` §5.

---

## 2026-08-26 — A ticket is a PATCH; a milestone is the MINOR

**Decision:** Inside a phase, each completed ticket bumps `PATCH`. The milestone landing takes the `MINOR`. So M0 walks `0.1.1` … `0.1.21` and then lands at `0.2.0`.

**Why:** `AGENTS.md` §7 held two rules that were individually sensible and jointly impossible: *"bump on every completed change"*, and *"a phase completing takes `0.1.0` → `0.2.0`"*. M0 has 21 tickets. Following the first rule with `MINOR` bumps lands Phase 0 at `0.22.0`; following the second means 20 completed tickets carry no version at all, which breaks the property §7 is actually protecting — that a `BRAIN.md` entry, a closing issue comment and a version line up. Treating a ticket as a `PATCH` satisfies both: every completed change still moves the number, and the milestone boundary is still visible in the version.

This is a reading of §7, not a change to it. It was written before there was a backlog, so nothing in it had to reconcile 21 tickets with one phase.

**Consequences:** `PATCH` no longer means only "bug fix" during `0.x` — a ticket that adds a feature still bumps `PATCH` until its milestone lands. That reads oddly against the table in §7, so §7 now says so explicitly rather than leaving the next person to notice the contradiction and pick a side. Once `1.0.0` ships, the table governs on its own.

**Refs:** `AGENTS.md` §7, [#53](https://github.com/Rumeasiyan/askwell/issues/53).

---

## 2026-08-26 — No trademark, unsigned distribution, and Apache-2.0 stays

**Decision:** Askwell will **not register a trademark**, and ships **unsigned** with published checksums and written bypass instructions. The licence **stays Apache-2.0**; moving to MIT was considered and rejected.

**Why MIT would not have helped, since it was the reason MIT came up.** Apache-2.0 §6 explicitly reserves trademark rights; MIT is silent on them. Silence is not a grant, so neither licence gives a trademark away and neither creates one — **the trademark question is entirely orthogonal to which permissive licence is chosen.** Switching would have cost the explicit patent grant in §3, which protects the project and its contributors from a contributor later asserting a patent, in exchange for nothing at all. Apache-2.0 stays.

**Why no trademark, and what that actually costs.** Registration is a few hundred pounds and enforcement is far more, against a project with no revenue. Most small open-source projects rely on unregistered rights arising from use, and are fine.

The real cost is that a previously-recorded claim was wrong and had to be corrected. The Apache-2.0 entry said the position against a hostile fork is protected by "the trademark and the brand" — with no registration, that sentence asserted a protection that does not exist. **A document claiming a safeguard you do not have is worse than one admitting you have none**, because the first stops anyone looking for a real one.

What actually protects the position is narrower and worth stating plainly: whoever runs the credit service holds the provider contracts, the billing relationship and the support burden. That is a business to build, not a repository to copy. Being the maintained original counts too — and counts for nothing if the original stops being maintained.

**Why unsigned, and where the honesty has to sit.** Certificates cost money every year — an Apple Developer enrolment and a Windows code-signing certificate — against no revenue. Linux is unaffected. macOS refuses first launch until the user goes through System Settings, and Windows shows SmartScreen with *Don't run* as the default button.

That is a conversion cost, not a distribution problem: `success-metrics.md` §4 targets fewer than 20% of installs never reaching a first answer, and a security warning on a free tool nobody has invested in is exactly where that number goes bad. It was accepted knowingly.

The part that must not be got wrong: **an unsigned build from a careful developer and an unsigned build from a hostile one are indistinguishable to Gatekeeper.** So a bypass instruction on its own is teaching people to click past security warnings, with nothing offered in exchange. `installing.md` therefore puts **checksum verification above the bypass**, and says why — the bypass tells the machine to stop asking, the checksum is the check that actually protects the reader. Any future edit that reorders those two sections has removed the only real safeguard in the page.

**Consequences:** `M7-TAURI-DEPLOY-184` becomes unsigned distribution with checksums; signing survives as `M7-TAURI-DEPLOY-184a`, deferred and explicitly blocked on a purchase rather than on engineering, so it is tracked rather than forgotten. `docs/installing.md` is new and is linked from the README. Phase 6's estimate no longer carries signing. Nothing in the product changes — signing was always build-time, and C1 was never involved.

**Refs:** `PRD.md` §7, §11; `installing.md`; `architecture.md` §1; `build-plan.md` Phase 6; `LICENSE`; issues #42, #47.

---

## 2026-08-26 — Web search uses a keyless library; no key means no contradiction

**Decision:** Web search uses **`ddgs`**, an MIT-licensed keyless metasearch library, behind the provider interface. No API key, no account, no cost, no additional container. `PRD.md` §6 stands unamended, and web search stays at Phase 6.5 rather than moving behind the credit service.

**Why the earlier framing was wrong.** I put three options forward — the user's own key, metering through credits, or a self-hosted SearXNG container — built on the constraint that *an open-source application cannot ship a shared API key*, because it would be lifted from the binary and the quota drained by everyone. That constraint is real. It is also irrelevant, because it presumes a key exists.

Commercial products buy search API keys because they serve many users from shared infrastructure, and that traffic is what gets rate-limited and blocked. **Askwell is the opposite case in every dimension**: one person, on their own connection, escalating a handful of questions a week. That traffic is shaped like someone browsing, because it is. The thing that breaks keyless search is volume from one address, and there is no volume here.

**What was rejected.** *CoexistAI* was raised and inspected: 521 stars, last pushed five months ago, and licensed `NOASSERTION` — not a standard OSI licence. It is a research framework that wraps SearXNG rather than a search backend, so it is a larger dependency than the problem needs, with the same class of licence question that removed PyMuPDF. *SearXNG itself* is a genuine option and remains the swap-in if `ddgs` stops being maintained; it was not chosen because it is a container on someone's laptop, and `architecture.md` §2 treats container count as a real cost.

*The user's own key* was the tempting one, and would have required narrowing §6 to say "AI provider key" — defensible, since a search key is low-cost and low-blast-radius unlike an inference key. It is unnecessary now, and a promise not narrowed is worth more than a promise narrowed with good reason.

**The cost, accepted knowingly:** a keyless metasearch depends on engines whose markup changes, so it will break and stay broken until the library is updated. That is a real dependency on someone else's maintenance, mitigated by where it sits — the unavailable state is already specified, and **the abstention still stands as the answer**. Failing to escalate is not failing to answer. The rule that must not bend when this fails: C5 does not relax because a network call did.

**Consequences:** `M6.5-WEB-BLOCKED-195` is unblocked and **no ticket in the backlog carries a `[BLOCKED]` marker any more**. The provider interface earns its place — it exists precisely so this choice can be revisited without touching the answer path.

**Refs:** `web-search.md` §6; `ux/web-search.md`; `architecture.md` §1; `PRD.md` §6, §11; issue #43.

---

## 2026-08-26 — Updates, the online payload, and credits priced per question

**Decision:** Three answers, each closing a `PRD.md` §11 item or a blocked ticket.

**Update delivery: an opt-in weekly check against a static version file.** Off by default. The request carries the version number and nothing else.

**What online mode transmits: a default-deny list of exactly four fields** — token counts, timestamp, model, and an opaque account identifier.

**Credits are priced per question, flat within a model tier**, not per token.

**Why a static file rather than an endpoint:** an endpoint could log who asked, and the only thing standing between that capability and its use is a promise. A static file has no such capability — the difference between *we do not log this* and *there is nothing here that could* is the difference between a policy and a property. C1 stays intact because the check is off unless the user turns it on, and the payload is small enough to state truthfully in one sentence rather than approximately.

The alternative — no check at all, the repository as the channel — was rejected because nobody watches a repository they installed software from. This product handles other people's confidential material, so a security fix that reaches almost nobody is not an acceptable outcome of constraint purity.

**Why default-deny on the payload:** the boundary in `audit-log.md` §6 was the right shape and was not a specification. Billing needs enough to bill; anti-abuse needs enough to detect abuse; each argues for one more field, and every one of those arguments is reasonable in isolation. Left informal, the list gets settled by whoever implements billing on the day — which is exactly how a privacy-first product ends up transmitting more than it promised. A field not on the list is now refused rather than reviewed, matching the egress proxy. Adding one is a decision recorded here first.

IP address was considered and left off. It is a genuine anti-abuse signal and it is an identifier the product promised not to collect; collecting it before an abuse problem exists trades a real promise for a hypothetical benefit.

**Why questions rather than tokens:** the spending limit in `ux/settings.md` §3 is only meaningful if the unit is one the user can picture. *About forty questions left* is a number someone can plan around; *five hundred thousand tokens* is not. The cost is that we absorb the variance when a question retrieves a lot of context — and that is the correct side to put the variance on, because a meter that only makes sense in arrears contradicts everything else in this product about not springing surprises.

**Consequences:** `M7-UPDATE-BLOCKED-161/162` and `M8-CREDIT-BLOCKED-173/174` and `M8-ONLINE-OBS-172` are unblocked and the `[BLOCKED]` markers come off. Balance is displayed in questions remaining, which the credit service must therefore compute rather than exposing a token count. The update check needs a static file hosted somewhere — trivial, and it belongs in the Phase 7 packaging work rather than being discovered there.

**Refs:** `PRD.md` §7, §11; `ux/settings.md` §3, §7; `audit-log.md` §9; issues #44, #45, #46.

---

## 2026-08-26 — Copy-review marker, and the audit lineage resets per milestone

**Decision:** Tickets that render wording a user reads carry `**Human review:** copy` under their `**Type:**` line — 26 of them. The build runner's audit and manual-test lineages reset at each milestone boundary rather than running as one session across all 198 tickets.

**Why the marker is in the ticket and not in the runner:** a list of ticket ids held in a script is a second source of truth. It drifts the moment somebody adds a ticket with the same property and does not know the list exists, and the failure is silent — the gate runs, finds nothing, and reports clean.

**What finding the right 26 actually taught, which is the part worth keeping:** the exact copy is not in the tickets. It lives in the `docs/ux/` specifications as quoted blocks, and tickets reference those by section. A detector written the obvious way — look for quoted text inside the ticket body — finds **exactly one** ticket and reports the other twenty-five as clean. That is worse than no detector, because it produces a green result for a check that never ran. The marker exists precisely because the property being detected is not visible in the thing being scanned.

**Why the audit lineage resets per milestone:** the reason for a resumed audit session was to keep the auditor from relearning conventions on every ticket, while preserving the one property that matters — that it did not write the code. Both survive a reset at a milestone boundary. What does not survive is context from work three milestones old, and that is the thing worth losing: an auditor carrying stale assumptions about a subsystem that has since changed reviews against a codebase that no longer exists. A forgetful auditor asks; a stale one is confidently wrong.

**Consequences:** session ids are keyed by milestone, so deleting one file restarts one milestone's lineage rather than all of them. The runner prints `copy review required` for the marked tickets and, per `build-runner.md` §9, must quote the wording into its own output — a gate that requires opening a file is a gate that gets skipped on the twentieth ticket.

**Refs:** `build-runner.md` §9, §13; `backlog/README.md`; `scripts/build-runner.sh`; issue #40.

---

## 2026-08-26 — Every open item resolved, deferred with a reason, or given an owner

**Decision:** A sweep of all fourteen documents found roughly thirty items sitting in "Open" sections. Each is now decided and recorded where it belongs, deferred with a stated reason, or filed as a tracked issue with an owner. **No open item lives only in a document.**

**Why this needed doing at all:** the tracker was empty and the project was reported as unblocked, repeatedly, while six backlog tickets were `[BLOCKED]`, four `PRD.md` §11 items were unanswered, and every specification carried an "Open" section nobody was assigned. Recording a question in a document felt like tracking it. It is not — `AGENTS.md` §8 says an item raised only in conversation is lost, and a doc section with no owner is the same failure with a nicer filename. The gap was invisible precisely because the tracker looked clean.

One item was in **no document and no issue at all**: code signing certificates. Twenty-one references to notarisation across the M7 tickets, and nothing anywhere saying who obtains the Apple Developer enrolment or the Windows certificate — neither of which any session can do, and both of which have lead times measured in days to weeks. That is now #42.

**The decisions worth naming, because each rejected something reasonable:**

*Speech-to-text stays containerised.* The profile that constrains the latency budget is CPU-only by definition, so moving STT native would buy speed only where there is already headroom, at the cost of a second native process on three platforms.

*Scanned pages highlight at page level.* Mapping OCR back to pixel regions and getting it slightly wrong highlights the wrong sentence — and a confident wrong highlight is a citation that lies, which is worse than a coarse one that does not.

*Audio is not kept.* Retaining it would help diagnose bad transcription and would mean the product quietly accumulates recordings of its user's voice. For something whose claim is that nothing leaves the machine, holding more than it needs is the wrong instinct even when the data never moves.

*No escalation to the web from voice.* Sending a question out is a deliberate act and a spoken command is the weakest possible confirmation of deliberateness. A misheard phrase would leak a question off the machine — the one failure this product cannot afford.

*Merged spreadsheet headers raise a clarification rather than being guessed.* A cell spanning three columns may be a group label or stray formatting, and guessing wrong mislabels every value beneath it. Same class of error as the date-format ambiguity, so it gets the same treatment: ask, never infer.

*No folder watching in v1.* It collides with supersession — a file saved five times in a minute would produce five superseding versions — and deciding when a change has settled is a heuristic that gets it wrong on somebody's workflow.

**Consequences:** seven issues now wait on the owner, three of which have external lead times and should be started before they are needed. Three items need real usage data and are marked as such rather than pretending analysis can settle them. `BRAIN.md` no longer carries an open-blockers list of its own — it points at the tracker, because two lists is how one of them goes stale.

**Refs:** issues #40, #42–#47; `PRD.md` §11; every `docs/ux/*.md` §Open; `data-sources.md`, `memory-and-clarification.md`, `web-search.md`, `architecture.md`.

---

## 2026-08-26 — Build runner: state file, hour-denominated ceiling, live runs disabled

**Decision:** Three questions `build-runner.md` §13 left open are settled by the implementation.

**A ticket is marked done by a state file** at `.build-runner/done/<ID>`, not by editing the ticket body. Editing the body would make every run produce a diff inside `docs/backlog/`, turning the backlog into a mutable log — and the durable record that a ticket finished is its merged pull request, not a marker anywhere.

**The budget ceiling is denominated in hours, and reads the high end of the range.** Every ticket carries an hour estimate; nothing in the repository carries a rate, and converting hours to money would mean inventing one. A guard built on an invented rate reports a precision it does not have. The high end rather than the low end because a ceiling that under-protects is not a ceiling — a run that stops at the cap having used the top of every estimate has already overshot.

**Live runs are disabled in the shipped runner.** It accepts `--dry` and `--list` and refuses anything else.

That last one is the substantive call. The gate does not exist — verified: no root manifest, no Compose file, no CI workflow. M0 creates it. A runner that ran live today would build a ticket, skip every gate command, find nothing wrong because nothing was checked, and open a pull request implying verification that never happened. **A runner that ships unverified work is worse than no runner**, because the pull request carries an implicit claim the pipeline did not earn.

The refusal is a single guarded exit in `main()`, removed once M0 has landed and §7.3 of the specification is filled in from real command output. Until then the dry run is genuinely useful: it renders and validates the prompt, which is the part most likely to be wrong.

**Consequences:**

- The guards ship complete and tested — 19 tests covering the stop file, budget boundaries, accumulation, and every fail-closed path. They are the parts that stop an unattended run from burning budget or refusing to die, so they exist and are proven before the thing they guard does.
- **`shellcheck` is absent on this machine**, so the runner is checked with `bash -n` only. That catches syntax, not quoting or word-splitting. Recorded as a gap in §7.0; install it with the M0 toolchain.
- The copy-review marker (§13.3) remains genuinely open and is the one that blocks unattended running of any ticket with user-facing wording. Detection is implemented and reads the ticket body, so it starts working the moment the marker is added — but no ticket carries one today.

**Refs:** `build-runner.md` §7.0, §7.1, §13; `scripts/build-runner.sh`, `scripts/guards.sh`; issue #40.

---

## 2026-08-26 — Desktop shell, and web search as an escalation the user performs

**Decision:** Two answers, recorded together because both change what leaves the machine and what the product is.

**Askwell ships as a Tauri desktop application.** Rust shell around the system webview, wrapping the interface the API already serves.

**Askwell can search the web** — per question, only when the user asks, and **never as a fallback when retrieval comes up short.** Added as constraint **C10**.

**Why a desktop shell:** the argument is the native file picker, not the icon. Askwell indexes files in place, so the user nominates root directories at add time, and the moved-file relocate flow needs a real dialog. Both are core paths and both are poor in a browser tab. Tauri over Electron on size — roughly 10 MB against 150, on an installer already carrying 2.4 GB of model weights.

The costs are real and were accepted rather than discovered: it does **not** remove the container stack, so this is a shell over the same architecture; it adds a Rust toolchain and per-platform code signing, with Apple notarisation the expensive one; and the installer now supervises a native process alongside containers, so "the assistant is unavailable" gains a third distinct cause.

**Why web search, against the earlier recommendation:** issue #38 argued for scoping it out. The owner decided otherwise, and the reasoning holds: a local AI that cannot reach past your own files is a harder product to love, the gap against Khoj is real, and the user is the one deciding what leaves.

**Why the escalation rule is the whole design.** The danger was never the network call, it was what an automatic one does to abstention. Askwell's most-tested behaviour is saying "your files do not cover this" — and that is *useful* because it is informative. If the web is reached whenever retrieval is thin, that sentence stops happening, so it stops meaning anything, and the user loses the signal that told them their corpus had a gap. The abstention rate, which `success-metrics.md` treats as the key operational number, would fall to zero for entirely the wrong reason.

So: **Askwell abstains first, exactly as before, and then offers.** The user escalates. That single rule preserves C5 while delivering the feature, and it is the reason C10 exists as a constraint rather than a note.

Two supporting rules follow from it. Web results **never enter the provenance margin** — that space is for material the user owns and can open, and a URL can change or vanish after the answer while a document on disk cannot. And web content is **the most untrusted input Askwell handles**: C7 governed documents the user chose, and a page written to contain instructions is not one of those.

Rejected: making it a conversation-level toggle. Sticky egress is how a per-unit permission quietly becomes a default, and C1 now names both paths explicitly for the same reason.

**Consequences:**

- **Phase 6 grows to 3.5 weeks** for the shell and signing. New **Phase 6.5** for web search, sequenced after the shell because it needs settings and audit to exist, and before credits because it is free and they are not.
- The quality gate gains a **web escalation discipline** category at **1.00, no exceptions** — every task presents an unanswerable question and asserts Askwell offers rather than searches. A single automatic fetch fails the suite.
- The egress proxy now authorises two narrow paths rather than one, and remains what makes "per question" enforceable rather than an intention in application code.
- Web results are **not chunked, not embedded, not persisted** into `chunks`, so a hostile page cannot influence a future answer it was not part of.
- The 390px mobile frame stops being a real target. There is no phone. Responsiveness still matters for a resized window, and the drawer stays.
- Three new screens: the escalation offer, a web-only answer, and an answer mixing both kinds of source with each claim pointing at its own kind.

**Open:** the search provider, and whether the user supplies a key or it is metered through credits. Metered is more consistent with "you never hand Askwell an API key"; a user key is cheaper to ship.

**Refs:** `AGENTS.md` §3 (C1 amended, C10 added), `docs/web-search.md`, `docs/PRD.md` §1, §4, §5, §6, `docs/architecture.md` §1, §2, §5, `docs/build-plan.md`; issues #34, #38.

---

## 2026-08-26 — C9: bundled models must be redistributable; a swapped model is marked unverified

**Decision:** Two related calls. **C9** is added to `AGENTS.md` §3: a bundled model's licence must permit redistribution and commercial use, and the weights must not be access-gated. Separately, **swapping to a user-supplied model is permitted and marked** — settings distinguishes validated defaults from unverified models, and every answer produced by one carries a persistent marker.

**Why C9:** Askwell bundles weights into a redistributable offline installer under Apache-2.0. Every model currently in the stack happens to be Apache-2.0 and ungated, which was luck rather than a requirement — nothing would have stopped a future change picking a better-performing model with terms that cannot ship, and the discovery would have come during Phase 7 packaging, which is phase-blocking.

Two near-misses had already happened before the rule existed. Gemma 3 is manually access-gated and carries Google's own terms rather than an OSI licence; an installer cannot click through an access agreement. MMS-TTS Tamil is CC-BY-NC, non-commercial, against a product with a paid credit tier. Both were caught by checking rather than by any rule.

A working rule in `architecture.md` was rejected over a constraint: constraints get enforcement points, working rules get forgotten, and the two near-misses happened precisely because there was nothing with teeth. Permitting gated models via user-initiated download was rejected because it breaks the offline install story that is central for the target user and would need an explicit C1 exception.

The accepted cost is real and permanent: Gemma is excluded, and any future model under similar terms is excluded with it, however well it performs.

**Why the marker rather than a list:** shipped defaults pass 155 eval tasks including abstention at ≥ 0.90 and SQL safety at 1.00. A user-supplied model has passed none of it and can fabricate citations or refuse to abstain while the provenance margin renders exactly as it always does. As specified before this decision, swapping silently opted the user out of both central guarantees with nothing saying so.

Restricting swaps to a validated list was rejected outright: a local, open-source product that dictates which models may run is fighting its own audience, and model choice is a legitimate reason people choose a tool like this. Running the abstention subset locally against a user-supplied model is the better answer and is deferred — it needs the eval harness to run against an arbitrary model, which is its own body of work, and it is the same mechanism `success-metrics.md` §2 already wants for citation sampling.

This follows the precedent set for the retrieval threshold in `ux/trace.md` §4: permit the dangerous change, state the consequence, never make it frictionless. A one-time warning in settings was judged insufficient because the decision is made once and its consequence persists for months — so the marker sits on the answer, where the consequence actually lands.

**Consequences:**

- Gemma 3 and any gated or non-commercial model are permanently out of the bundle. This narrows the field.
- `M7-DOC-DOC-163` (licence and notices) becomes the place C9 is **evidenced**, not merely asserted.
- New ticket `M7-SET-FE-146a` for the answer-surface marker; `M7-SET-FE-146` gains the validated/unverified distinction and a rule that the statement cannot be suppressed.
- `ux/ask.md` gains an unvalidated-model state; `ux/settings.md` §2 carries the wording.
- Running evals against a user-supplied model is now a named deferral rather than an unconsidered gap.

**Refs:** `AGENTS.md` §3 (C9), `architecture.md` §6, `ux/settings.md` §2, `ux/ask.md` §5; issues #26, #28.

---

## 2026-08-26 — Model names corrected; registry verification is now a rule

**Decision:** Supersedes the 2026-08-10 entry "`institution` profile is Qwen3 32B, not a 'Qwen3.6 27B'". That entry was **wrong**. Profiles now use Qwen3.5 4B, Qwen3.5 9B and Qwen3.6 27B. Speech synthesis reverts to **Kokoro-82M**, replacing Piper. `AGENTS.md` §4 gains a rule requiring registry verification of every model, weight and traineddata name.

**Why:** The original pre-repositioning PRD specified `Qwen3.5 4B` and `Qwen3.6 27B`, and Kokoro-82M for English speech. All three were correct. On 2026-08-10 the Qwen names were "corrected" to older releases on the stated grounds that neither existed and that 27B was "a Gemma parameter count, not a Qwen one"; in MODE A on 2026-08-26 Kokoro was swapped for Piper without adequate justification.

Verified against the model registry on 2026-08-26: `Qwen/Qwen3.5-4B` (7.7M downloads), `Qwen/Qwen3.5-9B` (13.4M), `Qwen/Qwen3.6-27B` (6.2M), `Qwen/Qwen3.6-35B-A3B` (5.4M), all Apache-2.0 and ungated. `hexgrad/Kokoro-82M` is Apache-2.0 with 12.3M downloads and a maintained ONNX build; Piper's voices are licensed individually, several are CC-BY-NC, and many carry no licence field at all — which is a distribution problem for weights bundled into a redistributable installer.

The cause is the same in both cases and is what actually needed fixing: **model availability and licensing were asserted from training-time memory rather than checked against a registry.** The identical failure was anticipated and avoided two days earlier for frontend package versions, where checking caught that the documented Next.js version was two majors stale. Models had no equivalent rule, so the same mistake ran unchecked twice.

**Consequences:**

- `AGENTS.md` §4 now requires name, current version, licence and gating status to be verified before any model name is written down. It sits alongside the existing package-version discipline rather than being a special case.
- The profile table states explicitly that all four models being Apache-2.0 and ungated is a **requirement, not a coincidence** — see the redistribution-licence constraint under discussion in #26.
- `Qwen3.6 35B-A3B` is flagged for evaluation on high-RAM CPU machines. A mixture-of-experts model with roughly 3B active parameters behaves far better on CPU than its total size implies, and no profile currently exploits that.
- The `workstation` VRAM floor against a 27B at Q4_K_M is tight and unmeasured. Profile floors remain estimates, and the eval gate rather than the table decides what ships.
- Backlog tickets naming Piper were updated in the same change.

**What this does not change:** the architecture, the profile structure, or the sizing logic. A 4B is still a 4B. Only the version line and the synthesis engine were wrong.

**Refs:** `architecture.md` §6, `AGENTS.md` §4; issues #24, #25, #26; supersedes the 2026-08-10 model entry.

---

## 2026-08-26 — Stack confirmed: all three platforms, native inference, egress proxy, no web container

**Decision:** v1 targets **Linux, Windows and macOS**. The llama.cpp server runs as a **native host process** rather than a container. The frontend is **built to static assets served by the API**, removing the `web` container. A **default-deny egress proxy** container enforces C1. PDF work uses **pypdfium2**, not PyMuPDF. Twelve further recommendations were accepted as-is: Next.js 16 / React 19 / Tailwind 4 / shadcn/ui pinned as one set, pnpm, Python 3.12 with tooling inside the API image, SQLAlchemy 2.0 async with Alembic, PostgreSQL 18 sharing its image with the sandbox, server-sent streaming with WebSocket reserved for voice, embeddings and reranking served by the same inference process, Tesseract with the Office-format libraries, locally bundled pdf.js, Piper for speech synthesis, the host-side hardware probe, GitHub Actions CI with the eval gate on a self-hosted or dispatched runner, and backups excluding weights, traces and the vector index.

**Why native inference:** containerised inference was the documented choice and it quietly excluded macOS. A Linux container on Apple Silicon runs inside a VM with no Metal passthrough, so the `accelerated` and `workstation` profiles would have been unreachable on the platform most consultants and lawyers actually carry — the product would have been worst where its target users are. Running inference natively costs the installer managing a process alongside a container stack, and gives *"the assistant is unavailable"* two distinct causes that must be diagnosed and reported separately. That was judged cheaper than shipping a product that is quietly degraded for a large share of its audience.

The alternative of Linux-first with macOS deferred was rejected for the same reason: it ships where the architecture already works rather than where the users are.

**Why the egress proxy, despite the container rule:** `ux/settings.md` promises a live count of outbound requests as the visible proof of C1, and the previous design specified only "egress blocked at the container network". Nothing in that path can count a request that was never made, so the number would have been the application asserting something about itself — precisely the "trust us" the audit-log design refuses to accept elsewhere. Network policy alone also makes per-conversation authorisation coarse, and application-level enforcement is defeated by a single dependency making an unexpected call, which is the realistic threat rather than malicious code.

**Why no web container:** there is no server, no session to protect and no SEO, so a permanent Node process on a single user's laptop bought nothing. This reverses a decision `architecture.md` had marked as locked; it was reversed deliberately rather than worked around.

**Why pypdfium2 over PyMuPDF:** PyMuPDF is the better library here — one dependency covering text extraction, page rendering for OCR, and the coordinates that citation highlighting needs. It is AGPL, and shipping it in a distributed application would have forced Askwell off Apache-2.0, which was chosen deliberately for contribution and adoption. The commercial licence was rejected as a paid dependency for a product with no revenue before Phase 7. The cost is real: passage-level highlighting and OCR coordinate mapping get harder, and scanned pages start at page-level highlighting.

**Consequences:**

- **Seven containers plus one native process**, down from eight containers despite adding the proxy.
- The installer now provisions and supervises a native process on three platforms. That is the single largest addition to the packaging milestone.
- **Open, before Phase 5:** whether speech-to-text also needs to run natively for GPU access on accelerated profiles, or stays containerised on CPU. Untested, and the answer changes the installer.
- Indexing in place means the user nominates root directories at add-time which become known mounts, rather than the container having open filesystem access. Safer, and the only thing that works with a VM in the path — but the installer and the add-source flow must handle path registration, which no screen specification currently covers.

**Refs:** `architecture.md` §1, §2, §2.1, §5, §6; issues #6, #9; MODE A analysis 2026-08-26.

---

## 2026-08-10 — Renamed to Askwell; Apache-2.0 with a proprietary credit service

**Decision:** VaultQ becomes **Askwell**. The application is open source under **Apache-2.0**; the online-AI credit service stays proprietary. Repository renamed to `Rumeasiyan/askwell`.

**Why the name:** The Q was dropped on the owner's call. Askwell was chosen over Marginalis and Gleanly. Marginalis was the more coherent choice on paper — it names the design signature, the permanent provenance margin — and was rejected for being four syllables that need spelling out loud, which is a real cost for a project that spreads by word of mouth. Gleanly was rejected for brand adjacency to Glean, a well-funded enterprise search company in a neighbouring space. Askwell names the differentiator directly: it is the thing that *asks*.

Every real dictionary word was already taken on both npm and PyPI, so a coined name was the only option that keeps `pip install askwell` and an unscoped npm package available.

**Why open source, and why it costs less than it looks:** The product's entire claim is that nothing leaves the machine. A closed-source local AI asking to be trusted offers only a promise; an open one can be audited, and the people this product is for are precisely the ones who will want to audit it or know someone who will. **The source is the proof of the central claim**, which makes this closer to a marketing asset than a giveaway.

The business is not the code. It is the credit service — provider contracts, metering, billing. Forking the client gives none of that, and anyone who wants to compete has to build an inference business, which was never gated on the source.

Rejected alternatives. **AGPL** looks protective and mostly is not here: its network trigger rarely fires for a local desktop application, so it buys little while deterring some contributors and corporate users. **BSL / fair-source** offers real protection against a competing commercial service and forfeits the trust and contribution benefit that is the entire reason to open the source — which for this product is the point. **Staying closed** keeps every option open and gives up the auditability argument, which is the strongest thing the product has to say about itself.

**Consequences:**

- Someone can fork Askwell and point it at their own credit service. Nothing prevents that. **Superseded 2026-08-26: no trademark will be registered** — see that day's entry. The protection is narrower than this line claimed.
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

> **Superseded, and wrong.** See *2026-08-26 — Model names corrected; registry
> verification is now a rule*, above. Qwen3.5 and Qwen3.6 are real releases; the
> PRD names this entry "corrected" were right, and this entry downgraded the
> generation model by a family version. Kept rather than deleted because
> `AGENTS.md` §4's registry-verification rule exists *because of* this entry, and
> deleting it would leave the rule looking arbitrary.
>
> This banner is here because the file is read by grep as often as it is read
> top-down. Newest-first ordering puts the correction above this, which protects
> a person reading the file and not an agent that searched for a model name and
> landed here.

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
