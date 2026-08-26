# Support

**Askwell is maintained by one person.** This page says what that means in practice, so expectations are set before you need help rather than after.

## Status

There is no released version yet. The repository holds the specification and the build backlog; implementation has not started. Most questions right now are about the plan rather than the product.

## Where to go

| You want to | Go to |
|---|---|
| Report a bug | Open an issue with the Bug template |
| Ask whether something is intended | Open an issue with the Question label |
| Suggest a feature | Open an issue — read `docs/PRD.md` §8 first, which lists what Askwell deliberately is not |
| Report a security problem | **Not an issue.** See `SECURITY.md` |
| Understand a decision | `docs/decisions.md` — it records what was rejected and why |

## What is promised

- Issues are read. All of them.
- Security reports are acknowledged within a week.
- Bugs that break one of the nine constraints in `AGENTS.md` §3 are treated as serious, because those constraints are the reason the product exists.

## What is not promised

- **A response time on ordinary issues.** One maintainer, no company, no support contract.
- **Help with your specific machine, corpus or database.** Askwell runs locally on hardware nobody else can see, which makes remote diagnosis genuinely hard. Include your deployment profile, your platform and what the trace showed.
- **Backwards compatibility before 1.0.** The version is `0.1.0` and the data model will change.
- **Support for a model you supplied yourself.** Askwell verifies citation and abstention behaviour for the models it ships. Anything else is unverified, and the interface says so.

This is a free, Apache-2.0 project. If that boundary does not work for your situation, forking is explicitly fine — that is what the licence is for.
