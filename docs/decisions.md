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
