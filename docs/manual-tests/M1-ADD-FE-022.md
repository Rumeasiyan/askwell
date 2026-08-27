# Manual test — M1-ADD-FE-022, adding material by dropping it on the window

**Ticket:** `M1-ADD-FE-022` — add-source screen, files route, drag-and-drop anywhere
**Version under test:** `0.2.3`
**Time:** about 45 minutes, plus a first stack build
**Who can run it:** anyone who can paste a line into a terminal. Everything from step 9 onward is dragging, clicking and typing in a browser.

**What is being checked.** Askwell reads your files where they are and never copies them. This walkthrough drops files onto the window from wherever you happen to be, watches Askwell work out what each one is from its contents rather than its name, and confirms that a folder of sixty contracts is one gesture rather than a wizard.

**The one thing to watch for throughout.** Nothing in this test may delete, move, modify or copy a file of yours. If a file you created changes or disappears, stop and record it — that is the most serious defect this feature could have. Equally: if your browser's network activity ever shows a file being sent anywhere, stop. This is not an upload control and must never become one.

**Where this stops on purpose.** Nothing is extracted, indexed or searchable yet. A batch of files ends at **Queued** and the screen says so. That is not a defect — see **Known gaps** at the end.

---

## Before you start

You need a terminal and Podman. You do not need Python, Node, or anything else.

### 1. Make files to test with

Paste this whole block into the terminal and press Enter:

```
mkdir -p ~/askwell-test/material/contracts ~/askwell-test/outside
cd ~/askwell-test/material

printf '%s\n' '%PDF-1.7' 'a pretend contract' > contract.pdf
printf '\x89PNG\r\n\x1a\nnot really a picture, but the first bytes say PNG' > logo.png
cp logo.png photo-of-a-scan.pdf
printf '%s\n' 'client,amount,signed' 'acme,1200,2026-01-04' 'globex,900,2026-02-11' > invoices.csv
printf '%s\n' 'A plain text note about the Acme lease.' > note.txt
: > empty.txt
cp /bin/ls a-program
gzip -c note.txt > bundle.gz

for n in $(seq -w 1 60); do printf '%s\n' '%PDF-1.7' "contract number $n" > contracts/contract-$n.pdf; done

printf '%s\n' '%PDF-1.7' 'a contract in a folder Askwell was never given' > ~/askwell-test/outside/stray.pdf
cd ~
```

**You should see:** no output at all. Silence is success.

Open your file manager and confirm `askwell-test/material` now holds nine items plus a `contracts` folder containing 60 PDFs. Keep the file manager open — you will come back to it to prove nothing was touched.

What each file is for:

| File | Why it is here |
| ---- | -------------- |
| `contract.pdf` | An ordinary supported file |
| `logo.png` | An image, supported |
| `photo-of-a-scan.pdf` | **Named `.pdf`, contains a PNG.** The honesty test |
| `invoices.csv` | A route that arrives in M4 |
| `note.txt` | Plain text |
| `empty.txt` | Nothing in it |
| `a-program` | A real Linux program. Must be refused **by name** |
| `bundle.gz` | An archive. Must be refused with what to do instead |
| `contracts/` | 60 files — the folder drop from the ticket's own scenario |
| `../outside/stray.pdf` | A file in a folder Askwell was never given |

### 2. Point Askwell at your files

Go to the Askwell folder:

```
cd ~/external/quantum-plus/askwell
```

If you have never run Askwell before, create its settings file:

```
cp -n .env.example .env
```

Open `.env` in any text editor. Find `ASKWELL_ROOTS_MOUNT=` and set it — replacing `you` with your own username:

```
ASKWELL_ROOTS_MOUNT=/home/you/askwell-test/material
```

Note that this deliberately points at `material` and **not** at `askwell-test`. That is what makes `outside/stray.pdf` a genuinely unknown folder in step 20.

Find `POSTGRES_APP_PASSWORD` and put any word after the `=` if it is blank.

> **Why this is manual.** Askwell's containers cannot see any part of your disk they have not been given, and a container's mounts cannot be changed while it runs.

---

## Cold start

### 3. Remove any previous state

```
podman compose down -v
```

**You should see:** lines about containers and volumes being removed, or a note that there was nothing to remove. Either is fine.

### 4. Build the interface

```
scripts/dev.sh web-build
```

**You should see:** a Next.js build finishing with a route list, and no red error text. The route list must include a line for **`/sources/add`**. If it does not, stop — the screen under test was not built.

This takes a few minutes the first time.

### 5. Run the checks

```
scripts/dev.sh web-check
```

**You should see:** four labelled stages — `typecheck`, `lint`, `tests`, `build` — then a contrast check and an offline scan, all finishing without red error text. The `tests` stage should report passing assertions about file-type detection.

The **offline scan** is the important one here: it is what proves the add screen fetches nothing from the internet.

### 6. Bring the stack up

```
podman compose up -d
```

**You should see:** services reported as started — `postgres`, `redis`, `egress-proxy`, `api`, `worker`. Wait about thirty seconds after the command returns.

### 7. Create the database tables

```
scripts/dev.sh db upgrade head
```

**You should see:** migration lines, including one mentioning `roots`.

### 8. Nominate the folder your material is in

Open a browser at:

```
http://127.0.0.1:8000
```

Click **Settings** in the left strip, scroll to **Folders Askwell may read**, type this into the **Nominate a folder** field — with your own username —

```
/home/you/askwell-test/material
```

— and click **Nominate**.

**You should see:** a box appear showing that path, marked **Readable** in grey.

This is groundwork, not the test. It is done here so that steps 10–19 exercise the ordinary case where Askwell already has permission; step 20 tests the case where it does not.

---

## Walk to the add screen by clicking

### 9. Get there the way a user would

Click **Ask** in the left strip.

**You should see:** a page headed **"Ask your own material"**, with **"Askwell 0.2.3 · nothing leaves this machine"** under it. Below that a panel headed **"Nothing added yet"**, whose text tells you that you can drop files anywhere on the window and do not have to go anywhere first, and a button reading **Add a source**.

Notice there is **no "Add" entry in the left strip**. That is deliberate: the primary path is dropping, and the button is the alternative.

Click **Add a source**.

**You should see:** the page changes to one headed **"Add a source"**, and the address in the browser bar ends in `/sources/add/`.

### 10. Read what the screen states before anything is added

**You should see**, in order down the page:

1. The heading **"Add a source"**.
2. Small grey text: **"Nothing added on this machine yet · this count is local and goes nowhere"**.
3. A full-size paragraph beginning **"Askwell indexes your files where they are."** and going on to say that nothing is copied, moved or uploaded, that adding a large library costs no disk space beyond the index, and that Askwell has to be told which folders it may open.
4. A panel with a **dashed** border headed **Files**, listing what is read today, with two buttons: **Choose files** and **Choose a folder**.
5. Under those buttons, small text saying a browser will not tell Askwell where a file lives, only what it is called, so it asks once per drop which folder they came from — and that the desktop application answers that itself.
6. A heading **"The other three routes"** with three cards: **Spreadsheet or CSV**, **Database dump**, **Connect a database**, each marked **"Arrives in M4"** in an amber-ish colour.

The statement at (3) is what someone about to add 40 GB of case files needs *before* they start. If it is missing, or reduced to a footnote, record it.

The three cards at (6) must be **present**, not hidden. A route that is absent reads as "Askwell cannot do this"; a route that is present and dated reads as "not yet".

---

## Drop a single file

### 11. Drag one PDF onto the window

Open your file manager at `~/askwell-test/material`. Drag `contract.pdf` over the browser window — **do not release yet**.

**You should see, while the file is still held over the window:** the whole window tints, and a box appears in the middle with a **dashed** border reading **"Drop to add"** and, under it, **"Files or whole folders. Askwell reads them where they are and copies nothing."**

Move the pointer around over the window without releasing.

**You should see:** the box stays put and does not flicker as you cross panels, headings or buttons.

Now release.

**You should see:** the affordance disappears, and a card appears on the add screen. It moves through **Detecting** to **Where are these?** quickly enough that you may only catch the second one.

The card should show:

- the phase label **Where are these?** at the top left, and a **Cancel** button at the top right,
- the line **"1 file, 22 bytes."** or similar — a count and a size,
- a line reading **"1 × a PDF document"**,
- a label **"Which folder are these files in?"**, a text field with the placeholder `/home/you/clients`, and an **Add them** button,
- small text: **"The whole path. Askwell needs it because it opens the file where it is rather than keeping a copy."**

That question is the honest consequence of a browser rule: no browser, on any platform, will tell a web page where a file actually lives.

### 12. Answer the question

Type into the field, with your own username:

```
/home/you/askwell-test/material
```

Click **Add them**.

**You should see:** the phase label change to **Queued**, and a note headed **Queued** reading close to: "1 file is queued from `/home/you/askwell-test/material`. Reading and indexing them is the next piece of work — it arrives with background ingestion, and nothing in your material is searchable until it does. Nothing has been copied."

**You should also see:** the small grey line under the heading change from "Nothing added on this machine yet" to **"1 file added on this machine"**.

**You should not see:** a progress bar, a spinner, or a percentage. There is nothing running to measure, and a bar that never moves is a bug report waiting to be filed.

### 13. Confirm the counter is local and survives a reload

Reload the page (F5).

**You should see:** the count still reads **"1 file added on this machine"**, and the queued card is **gone**.

Both halves are correct. The count is kept on this machine, in this browser, and goes nowhere. The queue is not kept, because nothing has been recorded yet — that arrives with `M1-ADD-BE-023`.

### 14. Confirm the file was not touched

Switch to your file manager and look at `~/askwell-test/material/contract.pdf`.

**You should see:** the same file, same size, same modification time. Open it in a text editor if you like — it still says `a pretend contract`.

No copy of it should have appeared anywhere. Askwell read its first few kilobytes and nothing more.

---

## Drop a folder

### 15. Drag the whole `contracts` folder onto the window

This is the ticket's own scenario, and it starts from the **Ask** screen so the flow has to take over.

Click **Ask** in the left strip first.

**You should see:** the "Ask your own material" page.

Now drag the `contracts` folder from your file manager onto the window and release.

**You should see:**

- the same **"Drop to add"** affordance while it is held,
- and on release, the page **navigates by itself** to the add screen — you did not click anything.

The card should show:

- **"60 files, 1.4 KB."** or similar — a real count, and the count must be **60**, not some round number below it,
- **"From 1 folder."**,
- **"60 × a PDF document"**,
- the question **"Which folder is “contracts” in?"** — naming the folder you dropped, not asking sixty times.

If the count is anything other than 60, record it. A folder of 200 contracts quietly becoming 100 is the classic failure here, and the number looks plausible when it happens.

Type your path and click **Add them**:

```
/home/you/askwell-test/material
```

**You should see:** **Queued** — "60 files are queued from `/home/you/askwell-test/material`…" — and the counter rise to **"61 files added on this machine"**.

---

## Drop while another drop is being read

### 16. Two drops in quick succession

Click **Clear** on any cards still on screen so the list is empty.

Now drop the `contracts` folder onto the window, and **without waiting**, drop `contract.pdf` onto the window as well.

**You should see:** **two** cards, each with its own count. Neither is rejected. One may briefly read **Detecting** with a line like **"Working out what each one is — 25 of 60 so far. Only the first few kilobytes of each file are read."** while the other waits its turn.

**You should not see:** an error, a refusal, a message about being busy, or the first drop being replaced by the second.

**You should also not see:** the window stop responding. While detection is running, click **Ask** and then **Library** in the left strip and confirm the pages change. Then come back to the add screen.

Click **Clear** on both cards when done.

---

## What Askwell says about files it will not take

Each of these should be a plain sentence a person can act on. Record it if any produces a bare error code, a stack trace, or the word "Unprocessable".

### 17. A file named one thing that contains another

Drop `photo-of-a-scan.pdf` onto the window.

**You should see:** the card lists it as **"1 × a PNG image"** — not a PDF — and a note headed **"Named one thing, contains another"** reading:

> photo-of-a-scan.pdf — Named .pdf, but the contents are a PNG image. Askwell goes by the contents.

This is the point of judging by content. The file is still added — it is routed as the image it is, and the disagreement is stated rather than silently corrected. Someone learning that one of their documents is not what its name says is worth more than a tidy screen.

Clear the card.

### 18. A program, an archive and an empty file

Drop `a-program`, `bundle.gz` and `empty.txt` together — select all three and drag them at once.

**You should see:** the phase label **Refused**, and a note headed **"3 files not added"** listing each with its own reason:

- `a-program` — "Askwell indexes documents, and this is a program. Nothing has been run and nothing has been read past its first few bytes."
- `bundle.gz` — "Askwell does not open archives. Unpack it and add what is inside — that way each document keeps its own name in your citations."
- `empty.txt` — "There is nothing in this file to index. Nothing was changed on disk."

Below that, a note headed **"Nothing here could be added"** repeating what is read today.

**You should not see:** the word "unsupported" used for the program. It is named as a program, which is the more useful fact. And **nothing was run** — if your machine does anything at all when this drop lands, stop the test immediately and record it.

**You should also see:** the counter unchanged. Nothing was added.

Clear the card.

---

## The browse alternative

### 19. Use the buttons instead of dragging

On the add screen, click **Choose files**.

**You should see:** your system's file chooser open.

Pick `note.txt` and `logo.png` together, and confirm.

**You should see:** exactly the same behaviour as a drop — a card, a count of 2, the folder question, and after answering, **Queued**.

Now click **Choose a folder**.

**You should see:** the chooser open in *directory* mode — it lets you pick a folder rather than a file, and your browser will likely warn you that you are about to give the site the folder's contents.

Pick `contracts` and confirm.

**You should see:** a card counting **60 files**, and the question **"Which folder is “contracts” in?"** — the same result as dragging it.

> **What this button is and is not.** It is a way to *name* files. Nothing is uploaded and nothing is copied; only the first few kilobytes of each file are read, in your own browser, to work out what it is. The native folder picker arrives with the desktop application (`M7-TAURI-FE-182`) and replaces this step alone.

Clear the cards.

---

## A file from a folder Askwell was never given

### 20. Drop `stray.pdf`

Drag `~/askwell-test/outside/stray.pdf` onto the window.

Answer the folder question with:

```
/home/you/askwell-test/outside
```

Click **Add them**.

**You should see:** the card stays on **Where are these?** and a note appears — amber-marked, not red — headed close to **"Askwell has not been given this folder yet"**, explaining that Askwell reads your files where they are and never copies them, so it needs to be told which folders it may open. Under the explanation, a button reading **Nominate /home/you/askwell-test/outside**.

**You should not see:** a bare rejection, and you should not see the file silently accepted.

Click the **Nominate** button.

**You should see:** the card move to **Queued**, and the counter go up by one. Askwell nominated the folder and then carried on with what you were already doing — you did not have to go to Settings and come back.

Confirm it really registered: click **Settings**, scroll to **Folders Askwell may read**.

**You should see:** two boxes now — `/home/you/askwell-test/material` and `/home/you/askwell-test/outside`, both **Readable**.

> **This folder is outside `ASKWELL_ROOTS_MOUNT`.** It may instead be marked **Needs a restart**, with a sentence naming the `.env` line to widen and the fact that the stack has to come up again. That is correct behaviour for a folder outside the mount, not a defect — see `docs/manual-tests/M1-ADD-ING-021.md` step 18.

---

## When Askwell is not answering

### 21. Stop the API and try to add something

In the terminal:

```
podman compose stop api
```

The browser page is already loaded, so leave it where it is. Drop `contract.pdf` onto the window, type the folder path, and click **Add them**.

**You should see:** a red-marked note on the card headed **"Askwell is not answering"**, with a reason.

**You should not see:** the file reported as queued, and you should not see the counter go up. "I could not check that folder" and "these files are added" are different statements and the screen must not substitute one for the other.

Start it again:

```
podman compose start api
```

Wait a few seconds, then click **Add them** again on the same card.

**You should see:** the note disappear and the card move to **Queued**. The drop did not have to be repeated.

---

## Tidy up

```
rm -rf ~/askwell-test
podman compose down -v
```

Then blank the `ASKWELL_ROOTS_MOUNT=` line in `.env` if you do not want to keep it.

To reset the local counter, open the browser's developer tools, go to **Application → Local Storage**, and delete the key `askwell.sources.added`. It is only ever stored there and it is never sent anywhere.

---

## Known gaps

These are deliberately not built, or are already recorded. Do not report them as defects.

1. **Nothing is extracted, indexed or searchable.** A batch ends at **Queued** and says so in words rather than showing a progress bar that will never move. The `sources` and `documents` records are `M1-ADD-BE-023`; background ingestion and per-file progress are `M1-ADD-ING-025`. Everything the ticket calls "Indexing", "Partly indexed", "Extraction failed", "Password-protected PDF", "Poor OCR" and "Duplicate" in `docs/ux/add-source.md` §5 belongs to those two tickets and cannot be reached from this screen.

2. **The queue does not survive a reload** (step 13). Nothing has been recorded yet, so there is nothing to restore. It becomes durable with `M1-ADD-BE-023`.

3. **The estimate is a count and a size, not a duration.** The ticket asks for "an honest estimate". Nothing in this repository has yet measured how long embedding a megabyte takes on a CPU, and a number invented here would be read as measured — it is the number someone plans their afternoon around. The duration arrives with `M1-ADD-ING-025`, which is the first thing that can observe it.

4. **A browser will not say where a file lives.** The ticket assumed "the browser's drop event gives usable paths under every supported platform". No browser gives them, on any platform; it is a sandbox rule rather than a missing API. So the folder is asked for, once per drop, as a typed path. `M7-TAURI-FE-182` deletes the question rather than improving it, and `web/lib/selection.ts` is the single seam it replaces.

5. **No system file or folder picker.** Steps 19's buttons use whatever the browser provides. The native dialogs arrive with the desktop application (`M7-TAURI-FE-182`).

6. **The other three routes do nothing** (step 10, item 6). They are shown with the milestone they arrive in, which is the requirement; CSV, dumps and connections are M4.

7. **A CSV or a `.sql` dump dropped today is queued anyway**, on the same screen that says those routes arrive in M4. Try dropping `invoices.csv` and you will see it reach **Queued** rather than being told when its route arrives. This is a **recorded defect**, listed under Open in `docs/BRAIN.md` — record it against that item rather than as a new finding.

8. **The 5,000-file cap does not stop the directory walk**, only what is kept, and the browse buttons apply no cap at all. Dropping a very large tree (a home directory) will settle on a count of 5,000 while the browser keeps reading directory entries. Both are recorded under Open in `docs/BRAIN.md`. This test deliberately uses 60 files rather than 50,000 for that reason.

9. **One covering check is made per drop, not per top-level folder.** Dragging two unrelated folders together in one gesture is checked against the first file only. Recorded under Open in `docs/BRAIN.md`; this walkthrough drops one top-level item at a time.

10. **"Source added is a decisions record" is not satisfied here.** The ticket lists it, and it cannot be met from a screen — nothing is a source until `M1-ADD-BE-023` creates one. What *is* recorded today is the folder nomination in step 20, which you can confirm in the audit log. Carried forward as an acceptance criterion of `M1-ADD-BE-023` and recorded under Open in `docs/BRAIN.md`.

11. **The type detection you are watching happens in the browser.** It is what the user is shown; it is not a boundary. `M1-ADD-BE-023` must re-detect server-side rather than trusting it. Recorded under Open in `docs/BRAIN.md`.

12. **The drop handler, the directory walk and the queue have no automated test.** File-type detection and folder expansion are unit-tested (`web/lib/add-source.test.ts`, run by `scripts/dev.sh web-check`); the browser-facing halves are covered only by this walkthrough. That is why steps 15 and 16 exist and why the count of 60 matters.

13. **A folder reached through a symbolic link** can be nominated but files under it will not be readable. Recorded under Open in `docs/BRAIN.md`. Avoid symlinked paths in this test.

14. **SELinux behaviour of the mount is unverified.** If every folder in step 8 reports **Not permitted**, that is the open item in `docs/BRAIN.md`, not a new finding.
