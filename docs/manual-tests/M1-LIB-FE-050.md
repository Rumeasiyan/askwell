# Manual test — M1-LIB-FE-050, the library list

**Ticket:** `M1-LIB-FE-050` — library list with status and needs-attention expansion
**Version under test:** `0.2.26`
**Time:** about 25 minutes, plus a first stack build
**Who can run it:** anyone who can paste a line into a terminal and use a browser.

**What is being checked.** The library is a scannable inventory of every source: name,
kind, added date, status as a word plus a shape, and — for a source that needs attention —
an expansion naming the specific broken document with a fix action. This walkthrough adds
a mixed folder with one corrupt file, watches it turn into a needs-attention row, fixes it
from that row, and checks the three filters.

**Where this stops on purpose.** Deletion, non-zero clarification counts and connection
statuses are out of scope (see Known gaps).

---

## Before you start

### 1. Make files to test with

```
mkdir -p ~/askwell-test/library
cd ~/askwell-test/library

printf '%s\n' '%PDF-1.7' 'Either party may terminate on ninety days written notice.' > contract.pdf
printf '%s\n' '%PDF-1.7' 'The tenant shall pay rent monthly in advance.' > lease.pdf
printf 'this is not a pdf at all' > broken.pdf
```

`broken.pdf` has a `.pdf` extension but no PDF content — Askwell will accept it into the
queue and then fail to extract it, which is what a needs-attention row is for.

### 2. Point Askwell at the folder and bring up the stack

In `.env`:

```
ASKWELL_ROOTS_MOUNT=/home/<you>/askwell-test/library
```

```
podman compose up -d
scripts/dev.sh db upgrade head
```

---

## The walkthrough

### 3. Open Askwell and add the folder

Go to `http://127.0.0.1:8000`. You land on **Ask**, which — with nothing added yet — shows
"Nothing added yet" and a link into **Add a source**.

**Expect:** clicking that link takes you to `/sources/add/`, titled "Add a source".

### 4. Add the mixed folder

Drag the whole `library` folder onto the window (or drop the three files onto it). Answer
the folder question with the absolute path to `~/askwell-test/library` if asked.

**Expect:** a card moves through *Detecting → Where are these? → Recording → Queued*,
ending with a sentence that three files are queued from that folder.

### 5. Go to the library

Click **Library** in the left rail.

**Expect:** the page title reads "Library", with the subtitle "Every source you have
added, and what state it is in." One row appears, named after the folder (`library`),
kind "Files", and "Added" followed by today's date.

### 6. Watch it index

Wait, or refresh the page, until indexing finishes.

**Expect while it runs:** the row's status word reads **Indexing**, with a hollow-ring,
half-filled shape next to it (not a colour alone). Below the added line, a sentence such
as "1 of 3 indexed. You can ask about those now; the rest are still being read." appears,
naming which file is being read right now and, if Askwell reports a percentage, that
percentage.

### 7. Confirm the needs-attention status appears

Once indexing settles (two files succeed, `broken.pdf` fails).

**Expect:** the row's status word changes to **Needs attention**, with a filled triangle
next to it. The coverage sentence reads "2 of 3 indexed. You can ask about those now; the
rest are still being read." (or similar, depending on timing). A button labelled
"Show detail (1)" appears below it.

### 8. Expand the row

Click **Show detail (1)**.

**Expect:** the button's label flips to "Hide detail". A list appears underneath naming
`broken.pdf` specifically, with a sentence describing what went wrong while reading it
(for example "Could not be read while extracting: …"), coloured with the alarm colour, and
a **Try again** button beside it.

### 9. Use the fix action

Click **Try again**.

**Expect:** the button's label changes to "Trying again…" and is disabled while the retry
runs. On success, no error line appears beneath the entry — `broken.pdf` will still fail
again on retry since its content is genuinely not a PDF, so **Expect instead**: an error
line appears in the alarm colour underneath the entry with a "read poorly" or extraction
failure message from the server, proving the retry action reached the backend and reported
back in place rather than silently doing nothing.

### 10. Confirm re-index has a warning before it starts

Click **Re-index**, at the bottom of the row.

**Expect:** the button is replaced by a paragraph naming the source and stating that
Askwell "reads every file in it again from scratch — extracting, chunking and embedding,"
that on a large source "this can take hours," and that answers may be thin until it
finishes. Two buttons appear: **Re-index it** and **Not now**.

Click **Not now**.

**Expect:** the warning collapses back to the plain **Re-index** button — nothing started.

Click **Re-index** again, then **Re-index it**.

**Expect:** the button reads "Starting…" briefly, then the whole control is replaced by a
one-line result such as "Re-indexing 3 documents."

### 11. Filter by kind

In the filter bar above the list, open the **Kind** dropdown.

**Expect:** it lists "All" and "Files" (the only kind reachable before `M4`). Selecting
"Files" keeps the row visible; there is nothing else to filter it out.

### 12. Filter by status

Open the **Status** dropdown and select whichever status the row currently shows (for
example "Needs attention" if it has not finished re-indexing, or "Indexing" if the
re-index is still running).

**Expect:** the row stays visible. Switch to a status the row does not have (for example
"Ready" while it is still indexing).

**Expect:** the list narrows to "No sources match these filters."

Set **Status** back to "All".

### 13. Filter by open clarifications

Tick **Has open clarifications**.

**Expect:** the list narrows to "No sources match these filters." — every source's open
clarification count is `0` in `M1` (clarifications land in `M3`), so this filter always
empties the list today. Untick it to bring the row back.

---

## What was checked against the ticket's acceptance criteria

- Added source appears with name, kind, added date and status — step 5.
- A source with a failed document shows needs attention and expands to name that document
  with a retry — steps 7–9.
- Re-index confirms before starting, and states the duration warning — step 10.
- Filters work (kind, status, open-clarifications) — steps 11–13.
- Status is never colour alone: each status pairs a word with a distinct shape
  (`web/components/library/status-mark.tsx`) — solid circle (ready), half-filled ring
  (indexing), dashed ring (queued), filled triangle (attention) — observable in
  greyscale or with the browser's colour filters on.

## Known gaps

Do not report these as defects — they are out of scope for this ticket:

- **No deletion.** There is no way to remove a source from this screen (`M2`).
- **Clarification counts are always zero**, so the "Has open clarifications" filter can
  never show a match today (`M3`).
- **No connections.** Kind is effectively always "Files" — the dropdown lists the other
  three kinds by name because the filter is built against the schema's own enum, but none
  are reachable until `M4`.
- **No per-source storage size.** The row does not show file size — this is an explicit
  open question, `docs/ux/library.md` §6.
- **A source with a hundred documents** was not separately tested here (this walkthrough
  used three files); the row's summarising behaviour — one coverage sentence rather than
  an inline per-file list — is the same code path regardless of count, driven by
  `coverageSentence()` in `web/lib/ingest.ts`.
- **The empty-library copy** ("Nothing has been added yet…") is deliberately plain
  placeholder text; the taught, reviewed version is `M1-LIB-FE-051`, not this ticket.
