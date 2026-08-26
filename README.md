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

## How is this different from other local AI tools?

Tools that run an AI over your own documents already exist, and several are good. [AnythingLLM](https://github.com/Mintplex-Labs/anything-llm), [PrivateGPT](https://github.com/zylon-ai/private-gpt), [Khoj](https://github.com/khoj-ai/khoj), [Quivr](https://github.com/QuivrHQ/quivr), [Onyx](https://github.com/onyx-dot-app/onyx) and [Open WebUI](https://github.com/open-webui/open-webui) all cover parts of this ground, and if you want a general local chat interface today, use one of them.

Askwell is narrower and differs in three specific ways.

**It asks you about your data, and remembers what you say.** Every other tool ingests silently and does its best with whatever it inferred. When Askwell hits something it genuinely cannot know — a column called `st_cd`, a date that could be 3 April or 4 March, two documents that contradict each other, a scan it could barely read — it asks. At most five questions per source, each shown with the actual data beside it so it takes seconds to answer. Your answers are stored permanently and applied to every future question and every future file.

That compounds. Month six is better than week one on the same files, because six months of your corrections are in it. Nothing is retrained — the facts are stored, inspectable, editable and reversible.

**Every claim shows its source, in a margin that cannot be collapsed.** Not a "Sources" toggle you click. The evidence sits beside the answer permanently, so an uncited claim is visibly wrong. Database answers show the query that produced the number.

**It says when it doesn't know.** If your files do not cover the question, Askwell tells you what it searched and what would need adding, rather than falling back on general knowledge. It is the most-tested behaviour in the product, because a confident wrong answer about your own contract is worse than no answer.

## Questions

**Does anything leave my computer?**
No. By default Askwell makes no outbound network calls at all — not models, fonts, telemetry or update checks. This is enforced by a default-deny egress proxy that every component routes through, not by convention, and it is verified at each release with the network cable unplugged. Optional online AI is the one exception: it is per-conversation, off by default, and states exactly what will be sent before anything is sent.

**Is there any telemetry?**
None. Not anonymous, not opt-in, not off-by-default. The accepted cost is that we cannot measure how the product is used, which is written down in `docs/success-metrics.md` §6 rather than glossed over.

**What does it cost?**
The local product is free and unlimited — no account, no seat cap, no trial. Revenue comes only from optional online-AI credits for people who occasionally want a large cloud model on a hard question. You never hand Askwell an API key from another provider.

**What can I put into it?**
PDFs including scanned ones, Word, Excel, PowerPoint, text, Markdown, HTML and images; CSV and spreadsheet exports; PostgreSQL dumps, which are imported into an isolated sandbox because a dump is executable code; and read-only live connections to PostgreSQL, MySQL/MariaDB and SQL Server.

**Does it work offline?**
Yes. That is the design point, not a mode. Disconnect the machine and it behaves identically.

**Is it multi-user?**
No, and that is deliberate. One person, one machine, one set of files. No teams, roles or permissions — which removes a large amount of complexity a single user gains nothing from, and keeps the privacy promise simple enough to state in a sentence.

**What languages?**
English only in v1. Tamil, then possibly Sinhala, come later. Three hedges are already in place so adding Tamil later is new work rather than a re-index of everything you own.

**Can I run my own model?**
Yes. Models come from configuration and are never hardcoded. Note that the models Askwell ships have passed a 155-task quality gate including abstention and SQL safety; a model you supply has not, so answers from it are marked as unverified.

**Can I use it today?**
Not yet. There is no application code — the repository is a complete specification and a 177-ticket backlog. Watch the repo if you want to know when that changes.

## Installing

Not yet — there is no release. When there is: **[`docs/installing.md`](docs/installing.md)**.

Askwell is unsigned, so macOS and Windows will warn on first launch. That page explains the warning, how to get past it, and — more importantly — how to verify the download is the file we published. **Verify the checksum.** That is the check that protects you; the bypass only stops your computer asking.

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
