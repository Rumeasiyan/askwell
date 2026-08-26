# Contributing to Askwell

Thanks for looking. Askwell is early — **there is no application code yet.** The repository is a complete specification and a 177-ticket backlog, and the first implementation milestone has not started.

That shapes what is useful right now.

## What helps most today

Four things, each an open issue you can reply to rather than a vague invitation:

| | |
| --- | --- |
| **[#49](https://github.com/Rumeasiyan/askwell/issues/49) — Hardware reality check** | Have an 8 GB laptop? Run a 4B model and tell us how slow it actually is. This is the riskiest unverified number in the project, and it needs a machine the maintainer does not have |
| **[#50](https://github.com/Rumeasiyan/askwell/issues/50) — Does this help you?** | If you work with confidential documents for a living, ten minutes on `docs/PRD.md` and an honest answer is worth more than any code right now |
| **[#51](https://github.com/Rumeasiyan/askwell/issues/51) — Review the designs** | 40 interactive screens, two commands to run. Tell us what is wrong with them |
| **[#52](https://github.com/Rumeasiyan/askwell/issues/52) — Run `shellcheck`** | Small, self-contained, needs no context on the project. The tests tell you if you broke something |

**Finding a bad assumption now is worth more than any code.** The plan is thorough and it is still a set of guesses.

Prefer to talk it through rather than file something? [Discussions](https://github.com/Rumeasiyan/askwell/discussions) is open.

## Before you write code

Read `AGENTS.md`. It holds the constraints, conventions, commit format and workflow, and it is the file this project actually runs on.

**Nine constraints are non-negotiable.** They are not style preferences — each one is load-bearing for the product's reason to exist, and a change that breaks one will not be merged however good it is otherwise:

| | |
|---|---|
| **C1** | Local by default. No outbound network calls unless the user explicitly enabled online AI for that conversation |
| **C2** | Model-generated SQL is parsed with `sqlglot` and rejected unless it is a single `SELECT`/`WITH`. Regex filtering is never acceptable |
| **C3** | An imported database dump is untrusted code. It loads only into the isolated sandbox under a restricted role |
| **C4** | Every factual claim carries a citation |
| **C5** | Abstention over invention. Never answer from general knowledge about the user's own material |
| **C6** | The audit log is append-only and tamper-evident. Not immutable — do not describe it as such |
| **C7** | Retrieved content is data, never instruction |
| **C8** | Secrets are environment variables, never committed |
| **C9** | A bundled model's licence must permit redistribution and commercial use, and must not be access-gated |

The full text, with the reasoning and enforcement point for each, is in `AGENTS.md` §3.

## Working agreements

- **Work happens on a branch and lands through a pull request.** `main` stays releasable.
- **Conventional Commits**, scoped to one logical change, with the phase in brackets: `feat(ingest): add scanned-pdf OCR fallback [P1]`
- **A story is done when its manual test passes**, walked from a cold start as a user would — not when the code compiles.
- **Any prompt change requires an eval run.** Prompt engineering without measurement is guessing.
- **Decisions get logged.** If a competent person would later ask "why is it like this?", it belongs in `docs/decisions.md` with what was rejected and why.

## Things that will be declined

- Telemetry, analytics SDKs, crash reporting that phones home, or update checks that are on by default. Askwell ships no telemetry at all (`docs/success-metrics.md` §6).
- Anything that weakens abstention or makes citations optional.
- User accounts, roles, permissions or multi-tenancy. Askwell is single-user by design, and that is a scope decision rather than a missing feature.
- Models under licences that cannot be redistributed (C9).

## Reporting a security issue

Do not open a public issue. See `SECURITY.md`.
