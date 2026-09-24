# Manual test — M7-DOC-DOC-164, stated support boundary and issue triage

**Ticket:** `M7-DOC-DOC-164` — a published support boundary (`SUPPORT.md`) reachable from
Settings → About, issue templates for a bug, a question and a feature request that ask for
version, platform, profile and trace, a triage convention with labels and a stated cadence, and
a security route that is separate and named.
**Version under test:** `0.7.30`
**Time:** about 25 minutes. No native inference process required for Parts A–C. Part D (copying
a real trace) needs an answered question, so it needs inference running — skip it if inference
is not available and say so in your result.

**What is being checked.**

- `web/components/settings/about.tsx` — the About section, now with **Support**, **Report a
  problem** and **Security problem** rows.
- `web/scripts/copy-support.mjs` — copies the repository's `SUPPORT.md` and `SECURITY.md` into
  `web/public/support.txt` and `web/public/security-policy.txt` at build time, so both open with
  no network.
- `SUPPORT.md`, `SECURITY.md` — the boundary and the separate security route.
- `.github/ISSUE_TEMPLATE/bug.yml`, `question.yml`, `feature.yml`, `config.yml` — the issue
  forms GitHub shows when someone opens an issue.

**Read before Part C.** GitHub builds its "new issue" page from the templates on the `main`
branch only. Until this ticket's pull request is merged, Part C shows the *old* templates and
will fail. Run Parts A, B and D against the branch; run Part C after merge.

**Human review required.** This ticket is wording a user reads before asking for help. Read
`SUPPORT.md` in full as the reviewer, not just the parts the steps below point at (step 9).

---

## Before you start

Open a terminal in the project folder:

```
cd ~/external/quantum-plus/askwell
```

If you have never run Askwell on this machine before:

```
cp -n .env.example .env
```

Open `.env`, find `POSTGRES_APP_PASSWORD`, and put any word after the `=` if it is blank.

---

## Cold start

### 1. Build the interface

```
scripts/dev.sh web-build
```

**You should see:** two lines among the output —

```
copy-support.mjs: public/support.txt written from SUPPORT.md
copy-support.mjs: public/security-policy.txt written from SECURITY.md
```

— and the build finishing with no error. If either line is missing, stop: the About links
below will lead nowhere.

### 2. Bring the stack up

```
podman compose up -d
```

If the stack was already running before step 1, restart the API so it serves the new build:

```
podman compose restart api
```

**You should see:** `postgres`, `redis`, `egress-proxy`, `api`, `worker` reported as started.
Wait about thirty seconds.

### 3. Create the database tables

```
scripts/dev.sh db upgrade head
```

**You should see:** migration lines finish with no error.

### 4. Open Askwell in a browser

Type this address into the browser's address bar:

```
http://127.0.0.1:8000
```

**You should see:** Askwell loads — first-run, or the question box if a source has been added
before. This is the only address you type in the whole test. Everything after this is reached
by clicking.

---

## Part A — the support boundary is reachable from the product

### 5. Open Settings by clicking

Click **Settings** in the navigation on the left (the last item, below **Ask**, **Library**,
**Clarifications** and **Memory**). If the window is narrow and the navigation is hidden, open
the menu button first, then click **Settings**.

**You should see:** a page titled **Settings**.

### 6. Scroll to About

Scroll to the bottom of Settings.

**You should see:** a section headed **About** with seven rows, in this order:

| Row | What it shows |
| --- | ------------- |
| **Version** | `0.7.30` |
| **Licence** | `Apache-2.0` |
| **Source** | a link reading `https://github.com/Rumeasiyan/askwell` |
| **Support** | a link reading "What one maintainer can and cannot answer" |
| **Report a problem** | a link reading "Open an issue", followed by grey text "— include the version above and a copied trace" |
| **Security problem** | a link reading "Report privately, not as an issue" |
| **Notices** | a link reading "Third-party notices and licences" |

Check two things by looking:

- **Support comes before Report a problem.** Someone reads what is answered before the link
  that files an issue.
- **Security problem is its own row**, with its own name, not part of the Report a problem row.

In the terminal, `cat VERSION` should print the same `0.7.30` the Version row shows.

### 7. Open the support boundary

Click **"What one maintainer can and cannot answer"**.

**You should see:** a new tab showing plain text (not a download prompt, not a blank page),
beginning:

```
# Support

**Askwell is maintained by one person.** No company, no team, no support contract.
```

### 8. Check the boundary has every part the ticket asks for

Scroll through the tab. **You should see** these headings, in this order:

1. `## Where to go`
2. `## What is answered`
3. `## What is promised`
4. `## What is not promised`
5. `## What a good report contains`
6. `## How issues are triaged`

And, reading under them:

- **Where to go** — the first row is "Report a security problem", and it says **Not an issue**,
  pointing at `SECURITY.md`.
- **What is promised** — three lines. The only one with a time in it is "Security reports are
  acknowledged within a week."
- **What is not promised** — the first line is "A response time on ordinary issues." Another
  line names "your own database, your own documents or your own hardware" and says they
  "belong with whoever runs that database or supports that machine" — out of scope, with a
  pointer to where they belong.
- **What a good report contains** — a table with **Version**, **Platform**, **Profile** and
  **Trace**, each with where to find it. Below it, a warning to check the trace before pasting,
  because it contains passages from your own files and an issue is public.
- **How issues are triaged** — says issues are sorted "in batches, not as they arrive", "roughly
  weekly", and "an aim rather than a deadline". A table of outcomes and labels, including
  `needs-info` (what to ask for when a report has no version or trace) and `out-of-scope`.

### 9. Read it as someone new

Read the whole tab once from top to bottom, as someone who has never seen Askwell and has a
problem.

**You should be able to answer, without guessing:**

- Is there a company or team behind this? (*No — one person.*)
- Will I get an answer within a set time? (*No, except a security acknowledgement within a
  week.*)
- Will they help with my database refusing a connection? (*No — that belongs with whoever runs
  it.*)
- Where does a security problem go? (*Not an issue — `SECURITY.md`.*)

If any answer is ambiguous or you had to infer it, record the sentence that confused you.

### 10. Check the served copy is the repository's copy

Close the tab. In the terminal:

```
diff SUPPORT.md web/public/support.txt && diff SECURITY.md web/public/security-policy.txt && echo same
```

**You should see:** `same` and nothing else. The page the user reads is the repository's own
file, not a second copy someone maintains by hand.

---

## Part B — the security route is separate

### 11. Open the security policy

Back on Settings → About, click **"Report privately, not as an issue"**.

**You should see:** a new tab showing plain text beginning `# Security`. Near the top, a bold
line: "**This is a separate route from ordinary support, on purpose.**" Under
`## Reporting a vulnerability`: use GitHub's private vulnerability reporting (the *Report a
vulnerability* button under the Security tab), and "Please do not open a public issue for a
security problem." Under **What to expect**: acknowledgement within a week.

### 12. Check the security policy opens with no network

Disconnect this machine from the network (turn off Wi-Fi or unplug the cable). On Settings →
About, click **"What one maintainer can and cannot answer"**, then
**"Report privately, not as an issue"**.

**You should see:** both still open, with the same text as steps 7 and 11. Only **Open an
issue** and **Source** need the network — clicking them now shows the browser's ordinary
"can't reach this page" in the new tab, and the Askwell tab is unaffected.

Reconnect the network before Part C.

---

## Part C — the issue templates (after merge to `main`)

You need a GitHub account for this part. Use one that is **not** a collaborator on the
repository if you have one — a collaborator is offered extra options a user would not see.

### 13. Follow Report a problem

On Settings → About, click **Open an issue**.

**You should see:** a GitHub page in a new tab, titled something like "Create new issue", listing
choices. Among them:

- **Bug report** — "Askwell did something wrong. Not for security problems — see SECURITY.md."
- **Question** — "Is this meant to happen? How does this work? Not for help with your own
  database or hardware."
- **Feature request** — "Suggest something Askwell does not do yet."
- **Report a security problem (private — not an issue)** — a link, not a template.
- **Read the support boundary first** — a link to `SUPPORT.md`.

There is **no** "Blank issue" option (for a non-collaborator). **Open decision** and **Task** also
appear — those are the maintainer's own templates, kept on purpose (see Known gaps).

### 14. Check the security link on this page goes somewhere private

Click **Report a security problem (private — not an issue)**.

**You should see today:** GitHub does **not** show a private report form — private vulnerability
reporting is currently switched off on the repository (issue #689, open). This is a known gap,
not a new defect. Once #689 is resolved, this link should open a private "Report a
vulnerability" form that does not create a public issue. Go back.

### 15. Open the bug report form

Click **Bug report** (the button next to it, "Get started" or similar).

**You should see**, top to bottom:

1. A note: one maintainer; a link to `SUPPORT.md`; **"A security problem does not belong
   here"** with a link to `SECURITY.md`; own database, documents or hardware out of scope unless
   Askwell itself behaved wrongly.
2. **Version** — hint "Settings → About → Version.", marked required.
3. **Platform** — hint "Operating system and its version.", marked required.
4. **Profile** — a drop-down: light, standard, accelerated, workstation, "I cannot open
   Settings". Hint "Settings → Model and speed → Current profile.", marked required.
5. **What happened** — required.
6. **Trace** — hint to press **Copy trace** under the answer, and a bold **"Read it before
   posting."** warning that it contains your question and passages from your own files and that
   the issue is public. Required.
7. **Did Askwell break one of its promises?** — eight tick boxes (network call, SQL, dump
   sandbox, uncited fact, general knowledge, audit log, document text as instruction, web result
   shown as your files).

### 16. Try to submit without a version or trace

Type a title and fill **only** Platform and What happened. Leave Version and Trace empty. Press
**Create** (or **Submit new issue**).

**You should see:** GitHub refuses, pointing at the empty required fields. No issue is created.
**Do not complete a real issue** unless you mean to — this is a public repository. Close the tab.

### 17. Look at the Question and Feature request forms

Go back to the chooser and open **Question**, then **Feature request**. Do not submit either.

**You should see:**

- **Question** — Your question (required), Version (required), Platform and Profile (optional,
  Profile starting at "not relevant"), Trace (optional, with the same read-it-first warning).
- **Feature request** — a note to read `docs/PRD.md` §8 first and that most requests are
  declined; What are you trying to do? (required), What would help, Version (required).

### 18. Check the triage labels exist

In the terminal:

```
gh label list --limit 100 | grep -E 'needs-triage|needs-info|out-of-scope|wontfix|duplicate|enhancement|question|bug'
```

**You should see:** all eight labels listed. Every public template applies `needs-triage`; a
label that did not exist would be silently dropped by GitHub.

---

## Part D — the report details are easy to find in the product

This walks the "What a good report contains" table as a user would, to prove each item is where
the boundary says.

### 19. Version

Settings → About → **Version**. Already checked in step 6.

### 20. Profile

Scroll up Settings to the section **Model and speed**. Under **Hardware profile**, read the line
beginning **Current profile:**.

**You should see:** "Current profile: **Light**" (or Standard, Accelerated, Workstation). The
bug form's drop-down uses the same four words in lower case. If the page instead says "Reading
the hardware probe…" and never changes, or shows an error, record it — the user would then pick
"I cannot open Settings" on the form.

### 21. Trace (needs inference running)

Click **Ask** in the navigation. Ask any question about material you have added and wait for the
answer. Under the answer, click **How did you get this?**. In the panel that opens, click
**Copy trace**.

**You should see:** the button label change to **Copied**. Paste into a text editor: the text
contains your question and the steps Askwell took. This is what the bug form's Trace field asks
for.

If inference is not running, write "Part D step 21 skipped — no inference" in your result.

---

## Part E — automated checks

### 22. Run the support-boundary tests

```
scripts/dev.sh test tests/test_support_boundary.py -v
```

**You should see:** 16 passed. These fail if a later edit drops the one-maintainer statement,
adds a response-time promise, stops requiring version/platform/profile/trace, or removes a row
from About.

---

## Known gaps

Deliberately not built or not yet fixed. Do not report these as new defects.

- **Private vulnerability reporting is off on the repository** — issue #689, open. Every
  security route (the About row, `SECURITY.md`, the issue chooser link) points at GitHub's
  *Report a vulnerability* button, which does not exist until the owner switches the setting on.
  Must be resolved before the first release. Step 14 failing is this.
- **No response-time commitment** on ordinary issues, deliberately. The only time commitment is
  the security acknowledgement within a week. Triage cadence is an aim ("roughly weekly"), not a
  deadline.
- **Templates only go live after merge.** Before this ticket's pull request is merged, GitHub
  still shows the old Markdown bug template and a Blank issue option (Part C).
- **Open decision and Task templates stay visible** in the issue chooser. They are the
  maintainer's own, kept as Markdown on purpose (`docs/decisions.md`, 2026-09-24).
- **Collaborators still see Blank issue.** GitHub always offers it to people with write access;
  `blank_issues_enabled: false` only affects everyone else.
- **The bug form's placeholder version (`0.7.30`) is illustrative** and is not kept in step with
  `VERSION`. It is grey hint text, not a default value.
- **Notices link may download instead of display** — `notices.md` is served as `text/markdown`
  (issue #690, from `M7-DOC-DOC-163`). The two files this ticket adds are `.txt` and do not have
  this problem.
- **The boundary opens as plain text**, not a styled page. Headings show as `#` and bold as
  `**`. Readable, but not formatted.
- **No update-check control in About** — `M7-UPDATE-FE-162`, not yet built.
