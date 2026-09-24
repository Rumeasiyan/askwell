# Screen: Settings

Everything the user controls. There is no administrator — these are their own settings.

> **This document is the specification. Any mockup is a reference.**

**Route:** `/settings`
**Phase:** 1 onward, growing per phase. Complete at 6.

---

## 1. Shape

Six sections, ordered by how often they are touched:

1. Model and speed · 2. Online AI · 3. Privacy and security · 4. Storage · 5. Your data · 6. About

No search, no sub-navigation. If this needs a search box it has too many settings.

---

## 2. Model and speed

- Current profile from the hardware probe, with what it means: *16 GB, no GPU. Answers in about 15 seconds.*
- Model in use, with swap. Swapping makes the assistant unavailable briefly; retrieval keeps working, and that is stated.
- **Validated defaults are marked as such, and a user-supplied model is marked as unverified.** The shipped model for a profile has passed the quality gate — 155 tasks, abstention ≥ 0.90, SQL safety 1.00. A model the user points Askwell at has passed none of it.

  Stated plainly at the point of swapping, not buried:

  > This model has not been tested against Askwell's checks. Citations and "I don't know" are behaviours Askwell verifies for the models it ships. With your own model, they are not guaranteed.

  Swapping is allowed. Answers produced by an unvalidated model carry a persistent marker (`ask.md`), so the state is visible where it matters rather than only in settings. Same pattern as the retrieval threshold — permit it, state the consequence, never make it frictionless.
- Memory footprint and measured tokens/second — real numbers, not a rating. Where the model runs partly on a graphics card, the memory figure says it counts system memory only and leaves out the graphics card's share, rather than presenting a partial figure as the whole footprint.
- **Retrieval threshold**, with the same warning as `trace.md` §4. Reachable here, never frictionless.

---

## 3. Online AI

Off. Everything below is inert until the user turns it on, and it stays off until they do.

- What it is, in plain terms: a larger cloud model for hard questions, using an API key from a provider the user already pays (`../decisions.md`, 2026-09-23 — the credit tier this section used to describe is cancelled).
- **Exactly what leaves the machine when it is on**, stated here and again in the conversation before the first send, never after.
- The key: set or not set, never shown again after entry; replace and remove (`M8-KEY-FE-174`).
- Per-conversation, not global. A conversation is local or online; there is no ambient setting to forget about.

> Askwell sells nothing and takes no part in what online AI costs. The account, the provider and the bill are the user's; the key is stored encrypted on this machine, never logged and never exported.

**Before M8 this section is visible and inert** (`M7-SET-FE-150`, `web/components/settings/online-ai.tsx`): what it will be, that it is per conversation, the key-and-bill statement, and a placeholder saying what leaves the machine will be stated before anything is sent. A switch reads *Off. Not available yet.*; pressing it says plainly that it cannot be turned on yet, with no waiting list and no email field — there is nothing to sign up for. No field in the section collects anything, and nothing in it makes a request. No price is described, because there is none. Hiding the feature until it exists means nobody expects it; showing it disabled sets the expectation honestly.

---

## 4. Privacy and security

- **Passphrase.** Off by default. On, it encrypts document content and stored credentials so a stolen laptop is not the same data breach it would otherwise be. Setting it explains that **losing it means losing the library** — there is no recovery, because a recovery path would defeat it. Setting, changing or removing it migrates the existing corpus — a progress figure (`GET /settings/passphrase/migration`), not an instant flip, since a large library re-encrypts one batch of passages at a time and an interrupted migration resumes rather than leaving anything half-protected. **What stays readable regardless:** the search index and the embedding vectors are derived from plaintext, always — retrieval on a single local machine needs them readable, and encrypting them would break every question asked of it. A stolen disk with a passphrase set still gives up how many documents exist, roughly how long each is, and what words they use; it does not give up their actual text. `M7-SEC-BE-152`.
- **Network activity: none.** Not a toggle — a statement, with a live count of outbound requests made in local mode, which is zero. The number is the proof of C1 and it is worth showing. A connected database is counted separately (below), never folded into this figure — it is a real, local fact about what the user connected, not the thing this zero exists to prove, and the two must not be confusable. Until an egress permit mechanism exists for a live connection's own destination (issue #345), reaching one from outside the container network fails at this same zero, which is stated on the connection wizard itself rather than left for the count to explain.
- **Connected databases**, with a count distinct from the network-activity figure above, and each one's read-only status — honestly "not yet checked" until `M4-CONN-SEC-097` (the write probe) exists, never asserted from a check that did not run.

---

## 5. Storage

- Index size, per source.
- **Log budget** — 2 GB or 5% of free disk by default (`../audit-log.md` §8), adjustable, showing current use.
- Interaction retention window, 12 months by default.
- Export and prune, which is the archive path.
- What happens at the limit, stated before it happens: **ingestion stops first, asking keeps working.**

---

## 6. Your data

The section that proves the product means what it says.

| Action | Behaviour |
| ------ | --------- |
| **Export everything** | Sources list, memory, conversations, logs with the hash chain and a verifier. Open formats. Background job |
| **Export the log** | Alone, for showing someone else what was asked |
| **Delete a source** | Tombstone (`library.md` §4) |
| **Delete all memory** | Confirms with the count and that it cannot be undone |
| **Reset Askwell** | Everything Askwell holds. **Original files are never touched**, stated plainly |
| **Verify the log** | Runs the hash chain check and reports where it breaks if it does |

Export must be genuinely complete and genuinely open. A free, open-source, local product with a lock-in export is a contradiction, and the users who chose it for sovereignty are exactly the ones who will check.

---

## 7. About

Version, licence, link to the source, and how to report a problem.

**Report a problem** leads with the support boundary (the repository's own `SUPPORT.md`, bundled so it reads offline): what one maintainer will and will not answer, and what a report needs — version, platform, profile and a copied trace. Then the link that opens an issue, through templates that ask for exactly those. **Crash reports** sit under it: any Askwell saved on this machine, listed by time with a Download link, and one sentence stating what a report holds, what it leaves out (the error message and anything from the person's files, questions or databases) and that it is never sent. There is no send button; attaching the file is the person's act (`docs/rollback-and-incidents.md` §3). **A security problem is a separate, named row** pointing at `SECURITY.md`, never folded into general reporting: a vulnerability filed as a public issue is already disclosed.

**Update checking is off by default.** Checking for updates is a network call, and C1 says local means local. Offered as an opt-in with the honest trade: *"Askwell can check for updates once a week. That is one request for a static file, carrying your version number and nothing else. Off by default."*

It reads a **static version file**, not an endpoint — there is no server that could log who asked, which is a stronger statement than a promise not to log.

An open-source product whose users never learn about a security fix is a real problem, and the honest resolution is an explicit opt-in with the payload stated — not a silent check because it is "only metadata".

---

## 8. States

| State | What is shown |
| ----- | ------------- |
| **Passphrase being set** | Strength, and the no-recovery warning before confirming |
| **Passphrase forgotten** | No recovery. Reset destroys the library. Said clearly, with export offered while still unlocked |
| **Model swapping** | Progress; retrieval unaffected |
| **No other model present** | That there is none, and the folder to place a `.gguf` file in |
| **Model swap failed** | The failure named; the previous model restored and in use |
| **Throughput not yet measured** | Says so. Never a zero |
| **Model file missing** | Which file, where it should be, manual install path (`first-run.md` §6) |
| **Log over budget** | Prominent, with prune and export |
| **Export running** | Background, with progress and a download when ready |
| **Hash chain broken** | Where it breaks and what it means: the application never rewrites history, so this indicates something outside Askwell changed the file (`../audit-log.md` §4) |
| **Online AI, before M8** | Visible, disabled, explaining what it will do. Pressing the switch shows that it is not available yet — never a form, a waiting list or an email field |

---

## 9. Open

1. **Settled: an opt-in weekly check against a static version file.** Off by default; the request carries the version number and nothing else. Recorded in `../decisions.md`.
2. **Settled: a backup taken from a passphrase-protected install is encrypted with that passphrase, and restore refuses clearly without it.** The alternative — writing an unencrypted backup from an encrypted install — would silently produce the one artefact that defeats the passphrase entirely, and it would do so at the moment the user was being careful. Restore states plainly that the passphrase from the source machine is required and that there is no recovery path, which is the same honesty the passphrase screen already uses.

   The tested restore in Phase 6 must cover **both** cases: passphrase set and not set. A restore path tested only in the easy direction is not tested.
3. **Settled: the abstention surface's "Ask a larger model" offer names a provider key, never credits** (`../decisions.md`, 2026-09-23; `M7-FIX-FE-174`). With no key configured — true today, since M8 has not built anywhere to set one — it says the capability is not set up yet rather than a balance of zero. §3 above was rewritten to the key model by `M7-SET-FE-150` (issue #658), which had to build the section against it; the entry, masking and removal details stay with `M8-KEY-FE-174`.
