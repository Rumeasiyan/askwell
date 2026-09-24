# Release walkthrough — the manual regression, from a cold install

`M7-QA-TEST-168`. This is gate G11 of `docs/release-checklist.md`. One person works through
the product the way a user would: install it, start it with no network, and follow each
milestone's headline path end to end. **This walkthrough is deliberately manual.** Automating
it would defeat its purpose, because what it tests is that a person can actually use the
product.

It differs from two nearby documents:

- The **per-ticket manual tests** in `docs/manual-tests/` each prove one ticket.
- **`docs/manual-tests/master-sheet.md`** walks every row of every screen, including failure
  paths. It is the depth check.

This walkthrough is the breadth check. It follows every milestone's headline path, in the
order a real first session runs them, on the release artefact rather than on a dev stack.

---

## How to run it

1. **Copy this file** to `docs/release-evidence/<version>/walkthrough-<platform>.md`, and fill
   in the copy. Leave this file blank. One copy per platform walked.
2. **Record the machine at the top of the copy:** OS and version, CPU, RAM, GPU if any, the
   tier Settings reports, and whether the machine is clean. A clean machine has never had
   Askwell installed and has no Podman images from this project.
3. **Work in order.** Each step builds on the one before it. If you run a step out of order to
   re-test it, say so in its notes.
4. **Click everything.** Reach every screen the way a user would. Never type an inner URL.
5. **Mark every step** in its Status column:

| Mark | Means |
| ---- | ----- |
| `PASS` | You saw it do what the Expect column says, on this build |
| `FAIL` | It did not. Put the issue number in Notes, and file the issue before you continue (`AGENTS.md` §8) |
| `BLOCKED` | The step could not be done: missing hardware, a second machine not available, a dependency not working. Put the reason in Notes |

A step that fails and then passes on a retry is marked **`FAIL`**. `docs/release-checklist.md`,
rule 2: an intermittent failure is a failure. `FAIL` and `BLOCKED` both block the release. No
step can be marked "not verifiable". Either you verified it, or the release waits.

**The outbound count is part of the evidence, not a side note.** At the points marked
**[net]**, open Settings → Privacy and security → Network activity and write down both numbers
on its line "… outbound requests permitted · … refused". (A bare `curl` of `/network` answers
`No session.`; the count is read where a user reads it.) Apart from the one web search you accept in W8, `permitted` must
never move. It must also not move while a live connection is added in W5. That connection is
a local database, and its traffic does not go through the egress proxy.

**Fixtures.** Use your own small corpus, not `eval/fixtures/`: the eval suites already cover
the fixtures, and this walkthrough exists to try material nothing was tuned against. You need:

- a text PDF of several pages;
- a scanned PDF, an image of text with no text layer;
- a CSV with at least one ambiguous column, such as a bare `status` or `amount`;
- a `.sql` dump of a small database;
- a local Postgres you control, for the live connection. It must not be the sandbox.

---

## W0 — Install from the release artefact (M7)

The network is **disconnected** from here until W8. Pull the cable or turn off Wi-Fi, and
confirm the machine really is offline before you start.

| # | Do | Expect | Status | Notes |
| - | -- | ------ | ------ | ----- |
| W0.1 | Verify the downloaded artefact against `SHA256SUMS`, as `docs/installing.md` says | Checksum matches. The instructions are correct as written | | |
| W0.2 | Install exactly as `docs/installing.md` describes for this platform | Installs. The unsigned-app warning appears where `docs/installing.md` says it will, and the bypass it describes works | | |
| W0.3 | Launch Askwell | It starts. Nothing asks for a network connection or an account | | |

## W1 — It runs (M0)

| # | Do | Expect | Status | Notes |
| - | -- | ------ | ------ | ----- |
| W1.1 | Wait for startup, then run `curl -s localhost:8000/health` | No status banner across the top of the page ("Askwell is not running", "Model unavailable"). `/health` lists every component as `reachable` and its `version` matches `VERSION`. No offline banner appears anywhere (`docs/states-and-edge-cases.md` §1) | | |
| W1.2 | On Linux, run `scripts/verify-localhost-binding.sh`. On other platforms, list the listening ports with the OS's own tool | Only loopback is bound. It is not on the network | | |
| W1.3 | **[net]** Read `/network` | Baseline recorded. On a clean machine, `permitted` is 0 | | |

## W2 — First run, offline, with a model placed by hand (M7)

Screen: `docs/ux/first-run.md`.

| # | Do | Expect | Status | Notes |
| - | -- | ------ | ------ | ----- |
| W2.1 | Open Askwell | The welcome screen, step 1, not an empty chat box. It promises three things: nothing uploaded, works offline, files stay where they are | | |
| W2.2 | Passphrase step: `Not now` | Continues. It does not ask a second time | | |
| W2.3 | Model step: do not press `Download`. Copy a model file brought on a USB stick to the exact path the step shows under "On a slow or air-gapped connection", then press `Verify the file` | The file is verified by checksum, not by its name. Setup completes with no network attempt (`M7-OFFLINE-DEPLOY-144`) | | |
| W2.4 | Settings → Model and speed (`docs/ux/settings.md` §2) | The probed tier and the model are shown, and match the machine | | |
| W2.5 | **[net]** Read `/network` | `permitted` unchanged | | |

## W3 — It answers from my documents (M1)

Screens: `docs/ux/add-source.md`, `docs/ux/library.md`, `docs/ux/ask.md`,
`docs/ux/source-viewer.md`, `docs/ux/conversation.md`.

| # | Do | Expect | Status | Notes |
| - | -- | ------ | ------ | ----- |
| W3.1 | Ask, before anything is added | Not an empty chat box. It says nothing is indexed yet and offers a way to add the first thing | | |
| W3.2 | Add source → nominate a folder that holds the text PDF and the scan (`docs/ux/add-source.md` §7) | The folder is accepted. Both files are listed | | |
| W3.3 | Library: watch both files index | Progress is visible. Both reach indexed. The scan's text is extracted by OCR, not left empty | | |
| W3.4 | Ask a question that the text PDF answers | The answer streams in. Every claim carries a citation, and the provenance margin names the document and page (C4) | | |
| W3.5 | Ask a question that only the scan answers | Answered and cited to the scan | | |
| W3.6 | Click a citation | The source viewer opens at the cited page, with the passage highlighted | | |
| W3.7 | Back to the answer | You return to the same answer, in the same place | | |
| W3.8 | Rename the cited PDF on disk, then open its citation again | The moved state from `docs/ux/source-viewer.md` §4. It is not a broken viewer or a crash, and the answer's history is kept | | |
| W3.9 | Scroll back up the conversation to the earlier answers | Earlier turns are shown as summaries and expand on request (`docs/ux/conversation.md`). There is no list of past conversations to reopen yet, and a reload starts a new one (#199) | | |

## W4 — It says when it doesn't know (M2)

| # | Do | Expect | Status | Notes |
| - | -- | ------ | ------ | ----- |
| W4.1 | Ask a question that nothing in the corpus covers | Abstention (`docs/ux/ask.md` §6): it says there is nothing, shows what it searched, and names what would need to be added. No general-knowledge answer (C5) | | |
| W4.2 | Ask a question the corpus half-covers | A partial answer. The grounded part is cited, and the missing part is named rather than filled in | | |
| W4.3 | Add two documents that disagree on one fact, then ask about that fact | Both positions are shown, each cited. Neither is silently preferred | | |
| W4.4 | Library: delete one of those two documents | The confirmation states the three facts before it commits. With `Show deleted` on, the source stays listed and greyed out. Its citation in W4.3's answer now shows as deleted (`docs/ux/library.md` §4) | | |
| W4.5 | **[net]** Read `/network` | `permitted` unchanged | | |

## W5 — It learns my material; it answers from my data (M3, M4)

Screens: `docs/ux/clarifications.md`, `docs/ux/memory.md`, `docs/ux/add-source.md` §3–§4.

| # | Do | Expect | Status | Notes |
| - | -- | ------ | ------ | ----- |
| W5.1 | Add the CSV | It is imported. A clarification is raised about the ambiguous column | | |
| W5.2 | Add the `.sql` dump | The dump warning from `docs/ux/add-source.md` §3 appears before anything happens. The dump loads into the sandbox only (C3) | | |
| W5.3 | Clarifications: answer the raised questions | Each answer is stored. The question leaves the queue and does not come back | | |
| W5.4 | Add a live connection to your own local Postgres (`docs/ux/add-source.md` §4) | The wizard connects read-only. Its tables are listed | | |
| W5.5 | Ask a data question that the CSV or the dump answers | A correct answer, with the SQL shown alongside it, always. The result can be traced to the query | | |
| W5.6 | Ask a data question that depends on your clarified column | The answer uses your clarification and cites it as a memory fact | | |
| W5.7 | From inside that answer, correct the memory fact | Corrected without leaving the answer. Ask again: the new fact is applied and the old one is not | | |
| W5.8 | Memory screen | The corrected fact is listed with its history. The superseded version is not applied | | |
| W5.9 | **[net]** Read `/network` | `permitted` unchanged, including after the live connection in W5.4 | | |

## W6 — It handles harder questions (M5)

Screen: `docs/ux/trace.md`.

| # | Do | Expect | Status | Notes |
| - | -- | ------ | ------ | ----- |
| W6.1 | Ask a question that needs both a document and the database | One answer, citing both the document and the query | | |
| W6.2 | Open that answer's trace | The trace is readable: each step, each tool call, what it returned, and how long it took. Nothing is left as raw JSON | | |

## W7 — I can speak to it (M6)

Screen: `docs/ux/voice.md`. Microphone and speakers needed. If this machine has none, mark
`BLOCKED`.

| # | Do | Expect | Status | Notes |
| - | -- | ------ | ------ | ----- |
| W7.1 | Ask a document question by voice | The level meter moves while you speak. The pause closes the turn, and your transcript appears as text before any answer. The answer streams on screen with citations and is spoken sentence by sentence (`docs/ux/voice.md` §3) | | |
| W7.2 | Ask again, and press Stop while it is speaking | Speech stops at once. The conversation shows the turn as stopped, not as failed, and the next question works normally | | |
| W7.3 | **[net]** Read `/network` | `permitted` unchanged | | |

## W8 — It can look outside (M6.5)

Screen: `docs/ux/web-search.md`. **Reconnect the network for this section only.** A real web
search needs a real network, and the provider must be configured
(`ASKWELL_WEB_SEARCH_PROVIDER`). If it is not configured, W8.3–W8.5 are `BLOCKED`.

| # | Do | Expect | Status | Notes |
| - | -- | ------ | ------ | ----- |
| W8.1 | **[net]** Read `/network` | Record the count before the escalation | | |
| W8.2 | Ask a question that nothing in the corpus covers | The abstention comes first. The web search offer appears **below** it, and has not run (C10) | | |
| W8.3 | Accept the web search once | The results appear in their own marked region, each labelled as not your material and dated with when it was retrieved. **None appears in the provenance margin** | | |
| W8.4 | **[net]** Read `/network` | `permitted` moved only by the escalation you accepted, and by nothing else | | |
| W8.5 | Ask a second uncovered question in the same conversation | It starts local again: an abstention with a fresh offer. It does not search automatically | | |
| W8.6 | **[net]** Read `/network` | `permitted` unchanged since W8.4 | | |

Disconnect the network again.

## W9 — Someone else can install it (M7)

Screens: `docs/ux/settings.md`, all sections.

| # | Do | Expect | Status | Notes |
| - | -- | ------ | ------ | ----- |
| W9.1 | Settings: open every section | Each section renders with real content, with no placeholder text and no dead controls | | |
| W9.2 | Settings → Online AI | Visible, switched off, and states that it is not available yet. Pressing the switch makes no network request | | |
| W9.3 | Settings → About | The version matches `VERSION`. The licence, notices and security policy open in the page, with the network off. The support boundary is shown before the issue address. Update checking is off | | |
| W9.4 | Take a backup. Settings has no backup control yet (#615), so follow `docs/restore-release-test.md` §1.3 | It completes, and the backup file exists at the path the response names | | |
| W9.5 | On a **second machine**, install fresh (W0), then restore that backup per `docs/restore-release-test.md` §3 | The inspect call (§3.1) states the re-embed cost, `estimated_reembed_seconds`, before anything is committed. Afterwards the sources, memory facts and conversations are all back. W3.4's question gets the same cited answer. If no second machine is available, mark `BLOCKED` | | |
| W9.6 | Settings → Your data → Export everything | The export completes. Open the files: they are in open formats, and hold the sources list, memory, conversations and the log with its hash chain | | |
| W9.7 | Settings → Your data → Verify the log | Both audit chains verify, with no break reported | | |
| W9.8 | `podman compose exec api askwell-verify` | Agrees with W9.7 | | |
| W9.9 | **[net]** Read `/network` | `permitted` is the W1.3 baseline plus W8's escalation only. Every `refused` entry is explained | | |

---

## Recording the result

The filled-in copy is the evidence. In `docs/release-log.md`, gate G11's line records the
following for each platform: `PASS` if every step is `PASS`; otherwise the failing or blocked
step numbers and the issues filed for them. The release entry also names every platform that
was not walked.

## Keeping this current

When a milestone lands, its headline path is added here in the same change. M8, per-conversation
online AI, is not yet built, and its steps are appended when it lands. A step describing
behaviour that has since changed is corrected when the change lands. If it is left stale,
the next release fails on a step that is no longer true, or passes on one that no longer
tests anything.
