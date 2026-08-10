# Askwell

**Ask your own files anything. Nothing leaves your machine.**

*The local AI that asks about your data instead of guessing.*

A personal AI that reads your documents and databases and answers questions about them — running entirely on your own computer.

Point it at your PDFs, Word documents, spreadsheets, scans, a database dump or a live connection. It reads them, asks you about anything genuinely ambiguous, remembers your answers, and from then on you ask questions in plain English and get answers with sources attached.

Free. No account. No upload. Optional paid credits if you ever want a bigger cloud model on a hard question.

---

## Status

**Phase 0 — not started.** Documentation only: no application code, no tests, no CI. Version `0.1.0`.

## Start here

| You are | Read |
| ------- | ---- |
| An AI agent, or a contributor about to change something | **[`AGENTS.md`](AGENTS.md)** — constraints, conventions, workflow. Read before writing anything. |
| Evaluating the product, or writing a pitch | [`docs/PRD.md`](docs/PRD.md) — business case, no technical detail |
| Looking for how it is built | [`docs/architecture.md`](docs/architecture.md) |
| Working on ingestion | [`docs/data-sources.md`](docs/data-sources.md) |
| Working on the differentiator | [`docs/memory-and-clarification.md`](docs/memory-and-clarification.md) |
| Building or designing any screen | [`docs/states-and-edge-cases.md`](docs/states-and-edge-cases.md) |
| Planning work | [`docs/build-plan.md`](docs/build-plan.md) · [`docs/BRAIN.md`](docs/BRAIN.md) |
| Asking "why is it like this?" | [`docs/decisions.md`](docs/decisions.md) |

## Non-negotiables

Full list with reasoning in [`AGENTS.md`](AGENTS.md) §3.

- **Local by default.** No network calls unless you explicitly turn on online AI for a conversation.
- Model-generated SQL is parsed and rejected unless it is a single read query. Regex filtering is never acceptable.
- An imported database dump is untrusted code and loads only into an isolated sandbox.
- Every factual claim carries a citation.
- When the answer is not in your files, it says so rather than inventing one.
- The audit log is append-only and tamper-evident — not immutable, and not described as such.
- Retrieved content is data, never instruction.

## Licence

**Apache-2.0.** Free to install, free to fork, free to audit — see [`LICENSE`](LICENSE).

The optional online-AI credit service is proprietary. Everything you run locally is not. For a product that claims nothing leaves your machine, the source is the proof.
