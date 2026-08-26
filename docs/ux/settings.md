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
- Memory footprint and measured tokens/second — real numbers, not a rating.
- **Retrieval threshold**, with the same warning as `trace.md` §4. Reachable here, never frictionless.

---

## 3. Online AI

Off. Everything below is inert until the user turns it on, and it stays off until they do.

- What it is, in plain terms: a larger cloud model for hard questions, paid by credit.
- **Exactly what leaves the machine when it is on**, before purchase, not after.
- Credit balance, purchase, and a spending limit the user sets.
- Per-conversation, not global. A conversation is local or online; there is no ambient setting to forget about.

> Askwell never asks for an API key from another provider and never will. Credits are bought here; we hold the provider relationship and the limits.

**This section ships in Phase 7 and is visible before then**, off, explaining what it will be. Hiding the paid feature until launch means nobody expects it; showing it disabled sets the expectation honestly.

---

## 4. Privacy and security

- **Passphrase.** Off by default. On, it encrypts the library and stored credentials so a stolen laptop is not a data breach. Setting it explains that **losing it means losing the library** — there is no recovery, because a recovery path would defeat it.
- **Network activity: none.** Not a toggle — a statement, with a live count of outbound requests made in local mode, which is zero. The number is the proof of C1 and it is worth showing.
- Connected databases, with their read-only status.

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
| **Model file missing** | Which file, where it should be, manual install path (`first-run.md` §6) |
| **Log over budget** | Prominent, with prune and export |
| **Export running** | Background, with progress and a download when ready |
| **Hash chain broken** | Where it breaks and what it means: the application never rewrites history, so this indicates something outside Askwell changed the file (`../audit-log.md` §4) |
| **Online AI, pre-Phase 7** | Visible, disabled, explaining what it will do |

---

## 9. Open

1. **Settled: an opt-in weekly check against a static version file.** Off by default; the request carries the version number and nothing else. Recorded in `../decisions.md`.
2. **Settled: a backup taken from a passphrase-protected install is encrypted with that passphrase, and restore refuses clearly without it.** The alternative — writing an unencrypted backup from an encrypted install — would silently produce the one artefact that defeats the passphrase entirely, and it would do so at the moment the user was being careful. Restore states plainly that the passphrase from the source machine is required and that there is no recovery path, which is the same honesty the passphrase screen already uses.

   The tested restore in Phase 6 must cover **both** cases: passphrase set and not set. A restore path tested only in the easy direction is not tested.
