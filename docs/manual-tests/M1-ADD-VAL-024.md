# Manual test — M1-ADD-VAL-024, refusing a file by name, with what would work

**Ticket:** `M1-ADD-VAL-024` — reject unsupported formats by name with the supported list
**Version under test:** `0.2.4`
**Time:** about 40 minutes, plus a first stack build
**Who can run it:** anyone who can paste a line into a terminal. Everything from step 9 onward is dragging, clicking and reading in a browser.

**What is being checked.** A file Askwell will not take must be refused **by name**, saying what the file turned out to be, why that stops here, and what *is* read today. One bad file in a drop of sixty must not take the other fifty-nine with it. And a file whose name lies about its contents must be judged on the contents.

**The three answers, which are not two.** This walkthrough exists because "supported / unsupported" was the wrong shape. There are three outcomes and you should be able to tell them apart at a glance:

| Outcome | Card label | Meaning |
| ------- | ---------- | ------- |
| **Supported** | Where are these? → Queued | Read today |
| **Arrives later** | Arrives later | Askwell recognised it; its route is being built, and the milestone is named |
| **Refused** | Refused | Askwell will not take this file, and says why |

A CSV shown under **Refused** is a defect, not a wording preference. It tells someone whose material is mostly exports that the product is not for them, which is false.

**The one thing to watch for throughout.** Nothing in this test may delete, move, modify or copy a file of yours. A refused file in particular must be **read and not run** — one of the test files is a real program. If your machine does anything at all when that drop lands, stop immediately and record it.

**Where this stops on purpose.** Nothing is extracted, indexed or searchable. A batch of supported files ends at **Queued**. See **Known gaps** at the end.

---

## Before you start

You need a terminal and Podman. You do not need Python, Node, or anything else.

### 1. Make files to test with

Paste this whole block into the terminal and press Enter:

```
mkdir -p ~/askwell-test/material/mixed ~/askwell-test/material/nothing-here/also-empty
cd ~/askwell-test/material

printf '%s\n' '%PDF-1.7' 'a pretend contract' > contract.pdf
printf 'PK\x03\x04\x14\x00\x00\x00\x08\x00 not a document, an archive' > contracts.zip
cp contracts.zip disguised.pdf
printf '\x89PNG\r\n\x1a\nnot really a picture, but the first bytes say PNG' > logo.png
cp logo.png photo-of-a-scan.pdf
printf '%s\n' 'client,amount,signed' 'acme,1200,2026-01-04' > invoices.csv
printf '%s\n' 'A plain text note about the Acme lease.' > note.txt
printf '%s\n' '# Lease notes' '' 'Ninety days notice.' > notes.md
printf '%s\n' '<!doctype html>' '<html><body><table><tr><td>a,b,c</td></tr></table></body></html>' > saved-page.html
: > empty.txt
cp /bin/ls a-program
gzip -c note.txt > bundle.gz
head -c 64 /dev/urandom > mystery.bin

cp contract.pdf mixed/contract-a.pdf
cp contract.pdf mixed/contract-b.pdf
cp contracts.zip mixed/photos.zip
cp invoices.csv mixed/ledger.csv
cd ~
```

**You should see:** no output at all. Silence is success.

Open your file manager at `askwell-test/material` and confirm it holds thirteen files plus two folders: `mixed` (four files) and `nothing-here` (containing one empty folder and nothing else). Keep the file manager open — you will come back to prove nothing was touched.

What each file is for:

| File | What it should do |
| ---- | ----------------- |
| `contract.pdf` | An ordinary supported file. The control |
| `contracts.zip` | The ticket's own scenario. **Refused**, with "unpack it and add what is inside" |
| `disguised.pdf` | **A zip renamed `.pdf`.** Must still be refused, on content |
| `photo-of-a-scan.pdf` | Named `.pdf`, contains a PNG. Supported, but the disagreement is stated |
| `logo.png` | An image. Supported |
| `invoices.csv` | **Arrives later**, not refused |
| `note.txt`, `notes.md`, `saved-page.html` | Plain text, Markdown, HTML. All supported today |
| `empty.txt` | Nothing in it. Refused |
| `a-program` | A real Linux program. Refused **as a program**, not as "unsupported" |
| `bundle.gz` | An archive. Refused with what to do instead |
| `mystery.bin` | Random bytes. Refused as unrecognised |
| `mixed/` | Two PDFs, one zip, one CSV — all three outcomes in one drop |
| `nothing-here/` | A folder that expands to no files at all |

### 2. Point Askwell at your files

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

**You should see:** a Next.js build finishing with a route list and no red error text. The route list must include a line for **`/sources/add`**. If it does not, stop — the screen under test was not built.

This takes a few minutes the first time.

### 5. Run the checks

```
scripts/dev.sh web-check
```

**You should see:** four labelled stages — `typecheck`, `lint`, `tests`, `build` — then a contrast check and an offline scan, all finishing without red error text.

The `tests` stage runs the detection unit tests. Read its output: it must report passing assertions naming archives, programs, empty files and a file whose extension disagrees with its contents. If that stage says `0 tests` or is skipped, stop — the rest of this walkthrough would be checking a screen against untested logic.

The **offline scan** matters here too: refusal is entirely local, and nothing about a refused file may leave the machine (C1).

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

This is groundwork, not the test. It is done here so that a supported file has somewhere to go and the refusals are the only thing under examination.

---

## Walk to the add screen by clicking

### 9. Get there the way a user would

Click **Ask** in the left strip.

**You should see:** a page headed **"Ask your own material"** with a panel headed **"Nothing added yet"** and a button reading **Add a source**.

Click **Add a source**.

**You should see:** a page headed **"Add a source"**, and the address in the browser bar ending in `/sources/add/`.

### 10. Read what the screen says before anything is dropped

**You should see**, in order down the page:

1. The heading **"Add a source"**.
2. Small grey text: **"Nothing added on this machine yet · these counts are local and go nowhere"**. Note the plural — **counts** — there are two, and the second appears once something is turned away.
3. A paragraph beginning **"Askwell indexes your files where they are."**
4. A dashed-bordered panel headed **Files**, and directly under that heading, in small text, the supported list:

   > PDF, Word, Excel, PowerPoint, plain text, Markdown, HTML and images are read today. CSV, database dumps and live connections arrive in M4.

   Read that sentence carefully. It is one sentence doing two jobs, and both halves must be present: what works now, and what is coming with a date. If the second half is missing, or says "unsupported", record it.
5. Two buttons: **Choose files** and **Choose a folder**.
6. A heading **"The other three routes"** with three cards — **Spreadsheet or CSV**, **Database dump**, **Connect a database** — each marked **"Arrives in M4"** in amber.

---

## The ticket's own scenario

### 11. Drop a zip and a PDF together

Open your file manager at `~/askwell-test/material`. Select **both** `contracts.zip` and `contract.pdf`, drag them onto the browser window and release.

**You should see** a card appear, moving through **Detecting** to **Where are these?**. On the card:

- the line **"2 files, ..."** with a size,
- a line reading **"1 × a PDF document"** — the tally counts only what is being added, so the zip is **not** in it,
- a note with a red-ish left edge headed **"1 file not added"**, containing:

  > contracts.zip — a zip archive. Askwell does not open archives. Unpack it and add what is inside — that way each document keeps its own name in your citations.

  and, one line below with a gap above it:

  > PDF, Word, Excel, PowerPoint, plain text, Markdown, HTML and images are read today. CSV, database dumps and live connections arrive in M4.

- and below all that, the question **"Which folder are these files in?"** with a text field and an **Add them** button.

Three things to check deliberately, because they are the whole ticket:

- The refusal **names the file** — `contracts.zip`, not "a file" and not "1 item".
- It **names what it turned out to be** — "a zip archive".
- It **names the way out** — unpack it. If the message is "unsupported format" with no next action, record it. That is the exact failure this ticket exists to prevent.

**You should also see:** the small grey line under the heading now reads **"Nothing added on this machine yet, 1 file turned away · these counts are local and go nowhere"**. The refusal is counted at the moment it is detected, before you answer anything.

### 12. The PDF proceeds

Type into the field, with your own username:

```
/home/you/askwell-test/material
```

Click **Add them**.

**You should see:** the label change to **Queued**, and a note headed **Queued** reading close to: "1 file is queued from `/home/you/askwell-test/material`…"

**You should see:** the count line change to **"1 file added on this machine, 1 file turned away"**.

**You should not see:** the number 2 anywhere in the queued note. One file was refused; one was queued. If the queue says two, the refusal was cosmetic and nothing was actually withheld — record that as serious.

The refusal note stays on the card. It should not disappear when the batch is queued: the user needs to leave this screen knowing their zip did not go in.

Click **Clear**.

### 13. Confirm the zip was not touched

Switch to your file manager and look at `~/askwell-test/material/contracts.zip`.

**You should see:** the same file, same size, same modification time. No unpacked folder appeared beside it. Askwell read its first few bytes and stopped.

---

## A file whose name lies

### 14. A zip renamed `.pdf`

Drop `disguised.pdf` onto the window.

**You should see:** the card label go to **Refused**, and a note headed **"1 file not added"**:

> disguised.pdf — a zip archive. Askwell does not open archives. Unpack it and add what is inside — that way each document keeps its own name in your citations.

Below it, a note headed **"Nothing here could be added"**: "Each file is listed above with the reason, and nothing was added for any of them. Nothing on disk was changed."

**You should not see:** the words "a PDF document" anywhere on this card. The extension said PDF; the bytes said zip; the bytes win. If it is accepted as a PDF, record it — that is the acceptance criterion "a file whose extension lies about its content is judged on content", failing.

**You should also not see:** the count of added files go up.

Clear the card.

### 15. A PNG named `.pdf` — the same rule, opposite result

Drop `photo-of-a-scan.pdf` onto the window.

**You should see:** **"1 × a PNG image"** — not a PDF — and an amber-edged note headed **"Named one thing, contains another"**:

> photo-of-a-scan.pdf — Named .pdf, but the contents are a PNG image. Askwell goes by the contents.

This file is **not** refused. It reaches **Where are these?** and can be added, as the image it actually is. That is the point: judging by content is not a way of turning files away, it is a way of being right about them. Someone learning that one of their documents is not what its name says is worth more than a tidy screen.

> **Why step 14 shows no "Named one thing" note and this one does.** A zip could legitimately be a `.docx`, so Askwell reports the disagreement only where it can say what the file honestly is. This is a known rough edge, listed under **Known gaps**, not a defect to file.

Click **Cancel**.

---

## One drop, all three outcomes

### 16. Drop the `mixed` folder

Drag the whole `mixed` folder onto the window and release.

**You should see** one card showing:

- **"4 files, ..."** and **"From 1 folder."**,
- a tally reading **"2 × a PDF document"**,
- a red-edged note headed **"1 file not added"**:

  > mixed/photos.zip — a zip archive. Askwell does not open archives. …

  with the supported list once beneath it,
- an **amber**-edged note headed **"1 file for a later milestone"**:

  > mixed/ledger.csv — a CSV file. Askwell reads these from M4; nothing was added for it now.

- and the question **"Which folder is “mixed” in?"**.

Check these four things:

1. Each refused file is named with its **path inside the drop** — `mixed/photos.zip`, so you can find it in a folder of sixty.
2. The CSV is under **"for a later milestone"** and **not** under "not added". Different heading, different colour, different words. If the CSV appears in the refusal list, record it.
3. The CSV line names **M4**. "Unsupported" for a CSV is the wrong answer to a user whose material is exports.
4. The supported list appears **once** on the card, under the refusals — not once per refused file.

Now answer the folder question with `/home/you/askwell-test/material` and click **Add them**.

**You should see:** **Queued**, saying **2 files are queued** — the two PDFs. The zip and the CSV are not in that number, and the count line goes up by **2**, not 4.

That is the scope line of this ticket, visible: one bad file in a drop does not reject the batch.

Clear the card.

---

## Everything Askwell will not take, at once

### 17. Four refusals in one drop

Select `a-program`, `bundle.gz`, `empty.txt` and `mystery.bin` together and drag them onto the window.

**You should see:** the label **Refused**, and one note headed **"4 files not added"** listing each with its own reason:

- `a-program` — a Linux program. "Askwell indexes documents, and this is a program. Nothing has been run and nothing has been read past its first few bytes."
- `bundle.gz` — a gzip archive. "Askwell does not open archives. Unpack it and add what is inside — that way each document keeps its own name in your citations."
- `empty.txt` — an empty file. "There is nothing in this file to index. Nothing was changed on disk."
- `mystery.bin` — an unrecognised file. "Askwell could not tell what this file is from its contents."

Then, once, the supported list. Then a second note headed **"Nothing here could be added"**.

**You should not see:** the word "unsupported" used for the program. It is named as a **program**, which is the more useful fact, and the message states that nothing was run.

**Nothing was run.** If your machine opens a window, plays a sound, or does anything at all when this drop lands, stop the test and record it immediately. That is the most serious defect this feature could have.

**You should see:** the turned-away count rise by 4.

**You should not see:** a folder question. There is nothing to locate.

Clear the card.

---

## A route that arrives later, on its own

### 18. Drop the CSV by itself

Drop `invoices.csv` onto the window.

**You should see:**

- the card label **"Arrives later"** — not "Refused",
- an amber note headed **"1 file for a later milestone"**: "invoices.csv — a CSV file. Askwell reads these from M4; nothing was added for it now.",
- and a second amber note headed **"Askwell recognised these, and cannot read them yet"**: "Nothing was added, and nothing on disk was changed. These are not the wrong kind of file — their route is being built, and the date is above."

**You should not see:** the turned-away count go up. A CSV was not turned away; it was recognised and dated.

**You should not see:** a folder question, or **Queued**. Nothing is queued for a route that does not exist. If this file reaches Queued, record it — a file counted as added that will never be read is worse than a refusal, because the user believes it is in there.

Cross-check the screen against itself: the **"Spreadsheet or CSV"** card near the bottom says **"Arrives in M4"**, and this card says M4. Those two numbers come from one place and must agree. If they ever disagree, record it.

Clear the card.

---

## Files that look like something else but are not

### 19. Markdown and a saved web page

Select `note.txt`, `notes.md` and `saved-page.html` together and drop them.

**You should see:** a tally reading **"1 × plain text · 1 × a Markdown document · 1 × an HTML page"**, in some order, and the card reaching **Where are these?**.

**You should not see:** any of these three under refusals, and you should not see any of them described as a CSV or a SQL dump. `saved-page.html` contains a table with commas in it, and it is the one most likely to be misread.

All three are on the supported list at step 10, item 4. A file named there that is not accepted here is a direct contradiction on one screen.

Click **Cancel**.

---

## A drop with nothing in it

### 20. Drop an empty folder

Drag the `nothing-here` folder onto the window and release.

**You should see:** a card labelled **Empty**, saying **"0 files, 0 bytes."** and **"From 2 folders."**, with a grey note headed **"Nothing in that drop"**:

> Askwell found no files — an empty folder, or one holding only other empty folders. Nothing was changed on disk. PDF, Word, Excel, PowerPoint, plain text, Markdown, HTML and images are read today. CSV, database dumps and live connections arrive in M4.

**You should not see:** the label **Refused**. Nothing was judged, so nothing was refused.

**You should not see:** silence. A drop that produces no card at all leaves the user wondering whether the gesture registered.

Clear the card.

### 21. Cancel a file dialog, and get nothing

Click **Choose files**, then close the dialog with **Cancel** or Escape without picking anything.

**You should see:** nothing at all — no new card, no message.

Both this and step 20 hand the screen an empty list, and the two must behave differently: an empty folder is a gesture that deserves an answer, and a cancelled dialog is not.

---

## The counters

### 22. Check what is counted, and that it goes nowhere

Look at the small grey line under **"Add a source"**.

**You should see:** something like **"3 files added on this machine, 6 files turned away · these counts are local and go nowhere"**. The exact numbers depend on how many times you repeated a step; what matters is that both numbers are present and the added number never includes a refused or a later file.

Reload the page (F5).

**You should see:** both counts unchanged, and all cards gone.

Now prove nothing was transmitted. Open your browser's developer tools, go to the **Network** tab, clear it, and drop `bundle.gz` onto the window.

**You should see:** a refusal on screen and **no network request at all** for that file — no upload, no report, no analytics call. Detection happens in your own browser, on the first few kilobytes, and there is nowhere for the count to be sent.

If you see any request leave when a file is refused, stop and record it. That is a C1 violation.

---

## Tidy up

```
rm -rf ~/askwell-test
podman compose down -v
```

Then blank the `ASKWELL_ROOTS_MOUNT=` line in `.env` if you do not want to keep it.

To reset the counters, open developer tools, go to **Application → Local Storage**, and delete the keys `askwell.sources.added` and `askwell.sources.rejected`. They are only ever stored there and are never sent anywhere.

---

## Known gaps

These are deliberately not built, or are already recorded. Do not report them as defects.

1. **A refused file is counted, but nothing durable records it.** The ticket says "rejections are logged". What exists today is a number in this browser's local storage, with no breakdown and no server-side record — detection is entirely in the browser and this ticket adds no endpoint. A user asking "why did my zip of contracts not appear" has only the screen they already closed. Recorded under Open in `docs/BRAIN.md`, carried forward to `M1-ADD-BE-023`.

2. **Detection happens in the browser and is a courtesy, not a boundary.** It is what you are shown; it is not what protects the extractor. `M1-ADD-BE-023` must re-detect server-side from the same signature table. Recorded under Open in `docs/BRAIN.md`.

3. **Prose can be misread as a CSV or a SQL dump, and since this ticket that withholds a supported file.** A `.txt` or `.md` file whose first line has two or more commas — `Dear Anna, thank you, and regards` — is routed to the table route and reported as arriving in M4, which is false about a format M1 reads today. So is a note whose first 4 KB contains a line beginning `CREATE`, `INSERT INTO`, `COPY`, `SET `, `ALTER TABLE` or `DROP TABLE`. Step 19 uses files that avoid both. This is a **recorded defect**, listed under Open in `docs/BRAIN.md` — record it against that item rather than as a new finding.

4. **A renamed zip is refused without a "Named one thing, contains another" note** (step 14). Askwell reports the disagreement only where it can say what the file honestly is, and a zip is a container that could legitimately be a `.docx`. The refusal still names the file and says it is an archive, which is what the ticket requires; the extra sentence is missing.

5. **Password-protected and corrupt files are not covered here.** A supported file that cannot be opened is an *extraction failure*, not an unsupported format, and it cannot happen on this screen because nothing is extracted yet. It arrives with `M1-EXTRACT-VAL-030`.

6. **The dump-specific refusal message is M4.** A `.sql` file today is reported as arriving in M4 like a CSV. The message about connecting to the database directly instead belongs to the dump route when it is built.

7. **Nothing is extracted, indexed or searchable.** A supported batch ends at **Queued** and says so. The records are `M1-ADD-BE-023`; background ingestion is `M1-ADD-ING-025`.

8. **The queue does not survive a reload** (step 22); the counters do. Nothing has been recorded server-side yet.

9. **The 5,000-file cap does not stop the directory walk**, only what is kept, and the browse buttons apply no cap at all. Recorded under Open in `docs/BRAIN.md`. This test uses small folders for that reason.

10. **One covering check is made per drop, not per top-level folder.** Dragging two unrelated folders together is checked against the first supported file only. Recorded under Open in `docs/BRAIN.md`; this walkthrough drops one top-level item at a time.

11. **The drop handler, the directory walk and the queue have no automated test.** Detection itself is unit-tested (`web/lib/add-source.test.ts`, run by `scripts/dev.sh web-check`); everything you do with a mouse here is covered only by this walkthrough. Recorded under Open in `docs/BRAIN.md`.

12. **A browser will not say where a file lives**, so the folder is asked for once per drop as a typed path. `M7-TAURI-FE-182` deletes the question. Refusal is unaffected — a refused file never reaches it.

13. **SELinux behaviour of the mount is unverified.** If the folder in step 8 reports **Not permitted**, that is the open item in `docs/BRAIN.md`, not a new finding. Steps 11 and 14–21 still work: refusal happens before Askwell needs to reach the disk at all.
