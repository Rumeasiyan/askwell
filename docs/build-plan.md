# Build plan

Phases, acceptance criteria and the quality gate. `PRD.md` §10 gives the user-facing version of this.

Each phase ends in something demonstrable. Do not begin a phase before the previous one's acceptance criteria pass.

**Acceptance is a manual walkthrough from a cold start, not a green test suite.** Typecheck, lint and tests passing means the code is well-formed, not that it does anything.

---

## Phase 0 — Skeleton (1 week)

Compose stack up, migrations, local session, health checks, CI running lint and tests.

*Accept when:* `podman compose up -d` works from a clean clone and an authenticated endpoint responds.

Blocked on issue #9 (stack versions) for the `web/` half. Issue #6 (pin Python 3.12) applies.

## Phase 1 — Ask your documents (2 weeks)

Add files → extract → OCR → chunk → embed → hybrid retrieve → rerank → cited answer. Chat UI with streaming and the abstention state.

*Accept when:* a scanned English PDF is added and a question about it returns a correct cited answer; the abstention eval subset scores ≥ 0.90.

## Phase 2 — It learns your material (2 weeks)

The clarification loop and memory (`memory-and-clarification.md`). Pending-clarification review, memory inspection and editing, correction from inside an answer, re-processing on answer.

*Accept when:* adding a source with a genuine ambiguity raises a question, answering it visibly changes a subsequent answer, and the fact is inspectable and deletable.

**Deliberately before database work.** Memory shapes ingestion and the data model, and the database path is where it pays off most — building databases first means rebuilding the schema-notes path afterwards.

## Phase 3 — Ask your data (2.5 weeks)

CSV import, SQL dump import with the sandbox (`data-sources.md` §3), live connections, schema introspection, text-to-SQL with the full validation chain, result rendering, SQL disclosure.

*Accept when:* the SQL-safety eval subset scores 1.00, execution-match ≥ 0.80, and a hostile dump destroys only its own sandbox database.

Half a week over the old estimate: the sandbox and dump import did not exist in the previous plan.

## Phase 4 — Harder questions (1.5 weeks)

Tool registry, multi-step loop with the 8-call ceiling, parallel calls, trace capture, trace UI.

*Accept when:* a question needing both a document lookup and a database query is answered correctly in one turn with a readable trace.

## Phase 5 — Speak to it (1.5 weeks)

WebSocket audio, VAD, STT (whisper `small`, English), sentence-streamed TTS, mode toggle, stop control (issue #13), latency indicator past budget (issue #15).

*Accept when:* the `accelerated` profile meets 3.5s to first audio and `standard` meets 8s.

No barge-in, no language detection.

## Phase 6 — Ready to hand out (2.5 weeks)

Installer with hardware probe, desktop packaging, offline model bundle, update mechanism, log budget and export, backup and **tested restore**, data export and deletion, settings.

*Accept when:* a clean machine installs and runs with the network cable unplugged, and a backup taken on one machine restores onto another with corpus and memory intact.

**Restore must be tested, not just implemented.** An untested restore is a backup that does not exist.

## Phase 7 — Online AI credits

Account, credit purchase, usage limits, the provider abstraction, admin. Requires decisions deferred throughout (`audit-log.md` §6; `PRD.md` §11 items 1 and 2).

The revenue line. Everything before it is free.

## Phase 8 — Hardening

Driven by what breaks for real users, not by this document.

---

## Estimates

Roughly 13 weeks to end of Phase 6, before rework. Testing finds defects and defects become work — **assume 1.3–1.5× on anything past Phase 1.** A plan quoting 13 weeks and delivering in 13 weeks has not been written yet.

---

## Quality gate

No model becomes a profile default without passing this suite.

| Category | Count | Pass bar |
| -------- | ----- | -------- |
| Grounded document QA | 40 | ≥ 0.85 mean, ≥ 0.70 worst-of-3 |
| Abstention (unanswerable) | 15 | ≥ 0.90 — hallucination here is disqualifying |
| Conflicting-source handling | 10 | ≥ 0.75 |
| Text-to-SQL (execution-matched) | 40 | ≥ 0.80 mean |
| SQL safety (write attempts, injection) | 10 | 1.00 — no exceptions |
| Tool selection incl. parallel | 25 | ≥ 0.85 |
| Memory application | 15 | ≥ 0.85 |

155 tasks, all English.

The memory category is new: it verifies that a stored clarification actually changes a later answer, and that a superseded fact stops applying. Without it, the differentiator has no test.

Each task runs three times and **worst-case is reported alongside mean** — a single malformed tool call fails an entire agent turn and errors compound. A model at 0.90 mean with 0.55 worst-case is worse in production than a steady 0.80.

The suite runs in CI on every prompt change. Prompt engineering without an eval gate is guessing, and small models are where guessing fails.

---

## Repository layout

Root holds only what a tool or convention requires. Prose lives in `docs/`.

```
askwell/
├── AGENTS.md, CLAUDE.md, README.md, VERSION, CHANGELOG.md
├── .github/ISSUE_TEMPLATE/
└── docs/
    ├── PRD.md                        # business case
    ├── architecture.md               # technical decisions
    ├── data-sources.md               # ingestion, sandbox, connections
    ├── memory-and-clarification.md   # the differentiator
    ├── audit-log.md                  # what is recorded
    ├── build-plan.md                 # this file
    ├── success-metrics.md
    ├── states-and-edge-cases.md
    ├── BRAIN.md
    └── decisions.md
```

Planned, created phase by phase — **do not scaffold ahead**:

| Path | Arrives |
| ---- | ------- |
| `compose.yaml`, `api/` (main, config, db), `.github/workflows/` | Phase 0 |
| `api/ingest/`, `api/retrieval/`, `web/`, `worker/`, `eval/` | Phase 1 |
| `api/memory/` | Phase 2 |
| `api/sql/`, sandbox container | Phase 3 |
| `api/agent/` | Phase 4 |
| `api/voice/` | Phase 5 |
| `deploy/` | Phase 6 |
