# VaultQ

**Ask your organisation anything. Nothing leaves the building.**

A sovereign AI workspace: an assistant that reads an organisation's documents, queries its databases, and answers by text or voice — running entirely on the organisation's own hardware, air-gapped if required.

Built for the customers who cannot use cloud AI at all — government ministries, hospitals, banks, legal firms, NGOs holding sensitive case data. For them the alternative is not ChatGPT; it is a filing cabinet.

Bilingual English/Tamil. Self-hosted with an offline signed licence — there is no hosted plane holding customer data.

---

## Status

**Phase 0 — not started.** This repository is documentation only: no application code, no manifests, no tests, no CI. Version `0.1.0`.

## Start here

| You are | Read |
| ------- | ---- |
| An AI agent, or a contributor about to change something | **[`AGENTS.md`](AGENTS.md)** — constraints, commands, conventions, workflow. Read before writing anything. |
| Trying to understand the product | [`docs/PRD.md`](docs/PRD.md) |
| Picking up where the last session stopped | [`docs/BRAIN.md`](docs/BRAIN.md) |
| Asking "why is it like this?" | [`docs/decisions.md`](docs/decisions.md) |
| Looking for what changed | [`CHANGELOG.md`](CHANGELOG.md) |

## Non-negotiables

Full list with reasoning in [`AGENTS.md`](AGENTS.md) §3. In short:

- No outbound network calls at runtime. An air-gapped install with the cable unplugged behaves identically.
- Model-generated SQL is parsed with `sqlglot` and rejected unless it is a single `SELECT`/`WITH`. Regex filtering is never acceptable.
- Every factual claim from the corpus carries a citation.
- Abstention over invention — no fallback to model world-knowledge for organisation-specific questions.
- The audit log is append-only.
- Retrieved content is data, never instruction.

## Licence

Proprietary. Self-hosted software under a subscription licence — see [`docs/PRD.md`](docs/PRD.md) §2.
