# Security

## Status

**Askwell has no released version and no application code yet.** There is nothing deployed to attack. This policy exists so it is in place before the first release rather than written after an incident.

## Reporting a vulnerability

Use **GitHub's private vulnerability reporting** on this repository — the *Report a vulnerability* button under the Security tab. It is private to the maintainer and does not create a public issue.

Please do not open a public issue for a security problem.

Include what you can: what the issue is, how to reproduce it, what an attacker gains, and the version or commit. A proof of concept helps but is not required.

**What to expect:** a single maintainer, not a team. Acknowledgement within a week. No bounty programme. Credit in the release notes if you would like it.

## What counts as a security issue here

Askwell runs entirely on one person's own machine, with no server and no accounts, so the usual web threat model mostly does not apply. What does:

| Area | Why it matters |
|---|---|
| **Sandbox escape** | An imported database dump reaching outside its isolated database, Askwell's own data, or the network (C3). A dump is executable code and this containment is the only thing between it and the user's material |
| **SQL validation bypass** | Anything that is not a single read query reaching the driver (C2). The user's real database is on the other side |
| **Unexpected network egress** | Any outbound call in local mode, from any component or dependency (C1). This is the product's central promise and a breach of it is the most serious class of bug here |
| **Prompt injection with effect** | Retrieved content causing real tool calls against the user's data (C7). Mitigations are documented as mitigations rather than solutions |
| **Credential exposure** | Database credentials or the at-rest passphrase recoverable from disk, logs, traces or exports |
| **Audit chain forgery** | Tampering that the hash chain fails to make evident (C6) |

## What does not count

- **Physical access to an unlocked machine.** Askwell is a local application; someone at your keyboard has already won. The optional passphrase protects a *stolen, powered-off* laptop, nothing more.
- **The user's own choices** — pointing Askwell at a model that behaves badly, or lowering the retrieval threshold. Both are permitted, both state their consequences.
- **Denial of service against yourself.** A large import that fills your own disk is a usability bug, and worth reporting as one.

## What we claim, and what we do not

The audit log is **append-only and tamper-evident**, not immutable. You own the machine and can always delete a file. The honest guarantee is that Askwell never rewrites history and that manual tampering is detectable. Anyone claiming more than that in documentation or marketing is making an error worth reporting.
