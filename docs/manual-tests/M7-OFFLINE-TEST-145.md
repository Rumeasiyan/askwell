# Manual test — M7-OFFLINE-TEST-145, the cable-unplugged release test

**Ticket:** `M7-OFFLINE-TEST-145` — build the documented, partly-automated offline release
gate itself (`docs/offline-release-test.md`, `scripts/verify-no-egress.sh`), and record a real
run in `docs/offline-test-log.md`.
**Version under test:** `0.7.16`, dev stack on this build host (`podman compose ps` shows all
nine services `Up`/`healthy`).
**This run is the gate's own first execution, not yet a release run against it.** No second
machine and no way to physically disconnect this host exist here (issues #590, #592, #598 —
the same gap `M7-BACKUP-TEST-159` and the restore gate already carry). This document walks
every clickable step of `docs/offline-release-test.md` §3 against the *running dev stack, on
the network*, reading the real screens as they exist in `web/` today, so that a genuine
cold-cable release run has a verified script and a verified set of on-screen expectations to
follow — rather than discovering broken navigation or a missing screen for the first time on
the one machine that cannot be un-disconnected to fix it.

---

## What was actually run

1. `scripts/verify-no-egress.sh` against the running dev stack — the automatable half
   (`docs/offline-release-test.md` §2). Recorded in `docs/offline-test-log.md`, `0.7.16` entry:
   `permitted` unchanged across the run (4 → 4); a pre-existing nonzero baseline predates this
   run and is not egress this script caused.
2. Steps 1–14 below: the manual walkthrough, clicked through in a browser against
   `http://localhost:3000` (the web container), reading `web/` on disk rather than assuming the
   ticket's own step list matches what was built.

---

## Before you start

1. Open a terminal and confirm the stack is up: `podman compose ps` should show `api`,
   `worker`, `postgres`, `redis`, `sandbox`, `voice`, `inference-bridge`, `egress-proxy` all
   `Up`. **Expect:** all healthy, none restarting.
2. In the same terminal, run `curl -s localhost:8000/network | python3 -m json.tool`.
   **Expect:** a JSON object with `permitted` and `refused` counts — note the numbers down,
   this is the baseline you compare against after every step below.

---

## The walkthrough

### 1. Cold start — the welcome screen

Open a browser to the Askwell address and load the page fresh (a new tab, not a reload of one
already signed in).

**Expect:** a screen headed **"Welcome to Askwell"** — not a blank page, not a login form
(there is no login; a session is established the moment the page loads). The first step's
body ends in a button reading **"Get started"**.

Re-check the network baseline (`curl .../network`). **Expect:** unchanged.

### 2. Add the first source

Click **"Get started"** and proceed to the add-a-source step. The screen is headed
**"Add a source"**, with two buttons in the files box: **"Choose files"** and
**"Choose a folder"**.

Click **"Choose a folder"** and pick a folder containing a handful of documents (the eval
fixture corpus at `eval/fixtures/corpus/` if the machine under test has it mounted; any small
folder of PDFs/text files otherwise).

**Expect:** the chosen files list under the box you clicked. If any file is a format Askwell
does not yet ingest (a CSV, for instance), it appears separately under a heading reading
**"{n} file(s) for a later milestone"** rather than silently vanishing — that is expected
behaviour, not a bug, for CSV specifically (`table_infer` clarification is not wired into this
screen yet — see Known gaps).

Submit the add. **Expect:** the step-4 ("ask") screen becomes reachable, with body text
**"Ready. Add something to ask about — the previous step's add box is still open above, or
open Add a source any time from the rail."** while indexing is still in progress, and an
**"Ask a question"** button once at least one source exists.

Re-check the network baseline. **Expect:** unchanged.

### 3. A SQL dump import

From the left rail, click **Library**, then find the control to add a database dump (same
add-source screen, dump route). **Expect:** a screen headed **"Database dump"**, a
**"Choose a dump file"** button, a field asking **"Which folder is "{name}" in?"**, and a
submit button reading **"Import"**.

Pick a small `.sql` dump file and submit. **Expect:** the import proceeds without asking for
network access of any kind, and the resulting source shows up in **Library** once ready.

Re-check the network baseline. **Expect:** unchanged — the sandbox container that receives
this dump has no route to the egress proxy at all (`docs/architecture.md` §5), so this step is
also a check that isolation itself has not regressed.

### 4. A live database connection — named separately, not folded into the zero-outbound figure

Still on the add-source screen, switch to the connection route. **Expect:** a screen headed
**"Connect a database"** with fields labelled **Engine**, **Host**, **Port**, **Database**,
**User**, **Password**, and a submit button reading **"Connect"**.

If a database is available to connect to on this run, do so and note its destination in the
log entry as a named, permitted connection — per `docs/offline-release-test.md` §3.2's own
rule, this is the one destination excluded from the "zero outbound" figure because the user
configured it deliberately. If none is available, skip this step and record the skip; do not
invent a connection to exercise this path.

### 5. Ask a grounded question

Click **Ask** in the left rail. Click into the composer (placeholder text
**"Ask about your own files and databases"**) and type a question the corpus you added in
step 2 can answer. Submit.

**Expect:** streamed progress text naming what is happening (searching, reading sources),
then the answer streams in token by token with citation cards appearing as they are emitted —
not appended all at once at the end. Click a citation card; **expect:** it opens to the cited
page of the source document.

Re-check the network baseline. **Expect:** unchanged.

### 6. Ask an unanswerable question — abstention

In the same composer, ask something the added corpus cannot possibly answer (e.g., a fact
about a topic unrelated to anything added).

**Expect:** a screen state visually distinct from an answer, reading **"Nothing in your files
answers this."** followed by a line naming what was searched and the closest material found
(or, on a genuinely empty corpus, **"Nothing in your files answers this — nothing is indexed
yet. Add a source, and ask again."**). This must **not** read as an offline or network-failure
message — abstention and "no network" are different states
(`docs/states-and-edge-cases.md` §1) and this screen must not conflate them. A button reading
**"Add a source"** (or **"Connect a database"**, depending on what would plausibly help)
follows.

**Since M6.5:** the abstention screen also offers **"Search the web"**. Click it.
**Expect:** with the network disconnected (on a real cold-cable run) or via the egress proxy
denying it (on this dev-stack run), the result is the copy **"I can't reach the web right
now."** — the abstention answer already given stands; this must not read as a failed turn.
Re-check `curl .../network`: **expect** either a new `refused` entry naming the web-search
provider, or no new attempt at all — never a `permitted` increase.

Re-check the network baseline after the non-web parts of this step. **Expect:** unchanged.

### 7. Answer an inline clarification

Trigger a clarification — adding a source with an ambiguous detail, or asking a question where
Askwell needs to confirm which of two similarly-named things you mean, usually raises one
inline in the conversation, with its supporting evidence shown alongside the question.

**Expect:** the clarification renders as part of the conversation itself, not a popup and not
a redirect to a separate queue. Pick one of the offered answers (buttons under a group labelled
"Choose an answer"), or type a free-text answer and click **"Save"**. **Expect:** the paused
answer resumes and completes using what you gave it. If you instead click **"Skip"**,
**expect:** the answer completes anyway, stating plainly which assumption it used in place of
your answer.

Re-check the network baseline. **Expect:** unchanged.

### 8. Correct a memory fact

Click **Memory** in the left rail. **Expect:** a list of facts Askwell has recorded, including
any surfaced by the clarification in step 7.

Find a fact and use its correction control. **Expect:** if Askwell already holds a fact for the
same subject, a prompt reading **"Askwell already knows {subject}: {value}. Correct it
instead?"** with a button reading **"Correct it"**. Confirm; **expect:** the fact's value
updates and is reflected the next time it is cited in an answer.

Re-check the network baseline. **Expect:** unchanged.

### 9. Query a database

Ask a question in the composer that can only be answered by querying the dump or connection
added in steps 3–4 (e.g., "how many rows are in the X table").

**Expect:** the answer includes a disclosed, human-readable version of the generated query
(never raw SQL presented as if it were the user's own words) and a result table
(`sql-result-table.tsx`) rather than prose alone. This query is validated through `sqlglot`
before it ever runs (C2) — nothing on screen proves that directly, but a malformed or
non-`SELECT` question should visibly fail rather than silently run.

Re-check the network baseline. **Expect:** unchanged; the sandbox stays isolated regardless of
what is asked of it.

### 10. Use voice

In the composer, find the microphone control (**"Voice input — press and hold to speak"**).
Press and hold, speak a question out loud, and release.

**Expect:** the control shows **"Listening…"** while you speak, then a transcribing state
showing the live or completed transcript in an editable field (**"Transcript — edit before
confirming"**). Confirm it. **Expect:** the question submits as if typed, generates an answer,
and the answer is spoken back sentence by sentence as it streams, not read all at once after
the full answer completes.

Re-check the network baseline. **Expect:** unchanged — transcription and speech synthesis run
against the local `voice` container only.

### 11. Take a backup

**No UI exists for this.** `web/app/settings/page.tsx` has a Storage section and a
"Your data" section, but neither has a backup control — only `POST /backup` exists, at the API
layer. Run, from the same terminal used at the start:

```
curl -s -b <cookie jar from the browser session, or a fresh curl session> \
  -X POST localhost:8000/backup -H 'content-type: application/json' -d '{}'
```

poll the returned job id until `status: "done"`, and download the artefact. **Expect:**
`status: "done"` with non-zero `tables_total` and `file_bytes`.

Re-check the network baseline. **Expect:** unchanged — a backup is a local file write only.
Filed as issue #615 (no clickable path for this step — see Known gaps).

### 12. Export the audit log

**No UI exists for this either**, for the same reason as step 11 — `storage.tsx`'s own export
control is rendered `disabled` with the copy "Not built yet — this is where it will be reached
from once it is." Run `POST /log-export`, poll to `done`, download, the same way as step 11.

Re-check the network baseline. **Expect:** unchanged.

### 13. Confirm no offline indicator appeared, anywhere

Across every screen visited in steps 1–12, **expect:** no banner, badge or warning anywhere
reading anything like "offline" or "no connection" — `docs/states-and-edge-cases.md` §1's rule
that this state renders **nothing**, because working with no network is the product working
exactly as promised, not a degraded state. Finding one on any screen is itself a release
blocker independent of anything the proxy or a packet capture shows.

### 14. Final counters

`curl -s localhost:8000/network | python3 -m json.tool` one more time. **Expect:** `permitted`
identical to the very first check in "Before you start." Any `refused` entries gained across
steps 1–13 are investigated individually per `docs/offline-release-test.md` §4 — named by
service, destination and cause — before this run can be called a pass.

---

## Result

**Not a pass/fail run of the gate itself** — this dev stack is on the network throughout, so
it cannot stand in for §1's physical disconnect, and matches the `0.7.16` entry already in
`docs/offline-test-log.md` ("fail (partial — the automated half only)"). What this document
adds to that entry: every step in `docs/offline-release-test.md` §3 was walked against the
real `web/` UI as it exists today, and two of them — backup (§11) and log export (§12) — have
no clickable path at all, only an API call. That gap is filed as issue #615 rather than left
for whoever runs the first real cold-cable release test to discover on hardware that, by
definition, cannot be un-disconnected to go check the code.

**Before the first real release run of this gate:** get a genuinely disconnectable machine
(issues #590/#592/#598), and either build the backup/log-export UI or accept API-only steps
for those two and say so plainly in `docs/offline-release-test.md` rather than implying a
click path exists (issue #615's own recommendation).

---

## Known gaps

- **No backup or log-export UI** (steps 11–12) — API-only today. Issue #615.
- **CSV / `table_infer` clarification** is not wired into the add-source screen yet; a CSV
  added in step 2 lands under "for a later milestone" rather than raising the clarification
  `docs/offline-release-test.md` §3.2 describes. Not re-filed here — this is scope for the CSV
  ingestion milestone itself, not an offline-test defect.
- **Physical disconnect (§1) and a genuinely clean machine** were not exercised — no second or
  disconnectable machine exists on this build host (issues #590, #592, #598).
- **The independent packet capture (`docs/offline-release-test.md` §5)** was not run — this
  walkthrough ran with the network up, so a capture would show real traffic and prove nothing
  about the offline claim.
- **Voice (step 10)** depends on a working browser microphone; not exercised headlessly, per
  `docs/offline-release-test.md` §2's own disclosed limit.
