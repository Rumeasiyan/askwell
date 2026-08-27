# Manual test — M1-ADD-BE-023, Askwell notices it already has your file

**Ticket:** `M1-ADD-BE-023` — source and document records, with content-hash duplicate detection
**Version under test:** `0.2.4`
**Time:** about 50 minutes, plus a first stack build
**Who can run it:** anyone who can paste a line into a terminal. Steps 1–13 are clicking and dragging in a browser; steps 14–24 are pasting whole blocks into a terminal and reading what comes back.

**What is being checked.** Someone has the same contract in three folders. Askwell should notice — by the file's *contents*, not its name — index it once, and say plainly which copy it kept, so answers never cite the same passage three times.

**The one thing to watch for throughout.** Nothing in this test may delete, move, modify or copy a file of yours. Askwell reads your files where they are. If a file you created changes or disappears, stop and record it. Equally: nothing may leave this machine. If your browser's network view, or `curl -s localhost:8000/network`, ever shows traffic to the internet, stop.

**Read this before you start, or step 14 will look like a defect.**
The add-source screen does **not** yet send anything to the part of Askwell this ticket built. The screen ends a drop at its own **Queued** card, kept in your browser; the records this ticket creates are made by a separate route that nothing on screen calls yet. That wiring is a gap, listed under **Known gaps** at the end. So this walkthrough does both halves honestly: it walks the screen by clicking, shows you that the screen records nothing, and then exercises the record-keeping the only way it can be reached today.

---

## Before you start

You need a terminal and Podman. You do not need Python, Node, or anything else.

### 1. Make the files to test with

Paste this whole block into the terminal and press Enter:

```
mkdir -p ~/askwell-test/material/clients ~/askwell-test/material/archive ~/askwell-test/outside
cd ~/askwell-test/material

printf '%s\n' '%PDF-1.7' 'Acme supply agreement, 2024, signed 4 January.' > clients/contract.pdf

cp clients/contract.pdf archive/contract.pdf
cp clients/contract.pdf 'clients/contract copy.pdf'
cp clients/contract.pdf archive/acme-agreement-FINAL-v3.pdf

printf '%s\n' '%PDF-1.7' 'Globex lease, 2025. A different document entirely.' > clients/lease.pdf
printf '%s\n' '%PDF-1.7' 'Not the Acme agreement at all — same name, other content.' > archive/lease.pdf

: > clients/empty.pdf

printf '%s\n' '%PDF-1.7' 'a contract in a folder Askwell was never given' > ~/askwell-test/outside/stray.pdf
cd ~
```

**You should see:** no output at all. Silence is success.

Open your file manager at `~/askwell-test/material` and confirm two folders, `clients` and `archive`. `clients` holds four files, `archive` holds three.

What each file is for:

| File | Why it is here |
| ---- | -------------- |
| `clients/contract.pdf` | The original. This is the one that should end up indexed |
| `archive/contract.pdf` | **Same name, same bytes, other folder.** The ticket's own case |
| `clients/contract copy.pdf` | **Same bytes, different name.** Duplicate by content, and both paths must be shown |
| `archive/acme-agreement-FINAL-v3.pdf` | Same bytes again, a name that looks like a newer version but is not |
| `clients/lease.pdf` | An ordinary second document |
| `archive/lease.pdf` | **Same name, different bytes.** Must *not* be a duplicate |
| `clients/empty.pdf` | Zero bytes. Must be refused with a reason |
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

Open `.env` in any text editor. Find `ASKWELL_ROOTS_MOUNT=` and set it, replacing `you` with your own username:

```
ASKWELL_ROOTS_MOUNT=/home/you/askwell-test/material
```

This deliberately points at `material` and **not** at `askwell-test`, which is what makes `outside/stray.pdf` a genuinely unknown folder in step 22.

Find `POSTGRES_APP_PASSWORD` and put any word after the `=` if it is blank.

> **Why this is manual.** Askwell's containers cannot see any part of your disk they have not been given, and a container's mounts cannot be changed while it runs. The folder is mounted **read-only** — which is the mechanical reason nothing in this test can alter your files.

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

**You should see:** a Next.js build finishing with a route list and no red error text. The list must include **`/sources/add`**. If it does not, stop — the screen you walk in steps 9–13 was not built.

This takes a few minutes the first time.

### 5. Run the backend checks

```
scripts/dev.sh check
```

**You should see:** stages for format, lint, typecheck and tests, finishing without red error text. The test summary must be a count of **passed** tests with **no skips**. A skipped test here means a suite decided it could not run and said so quietly.

These are the tests that do not need a database. The ones that do come in step 8.

### 6. Bring the stack up

```
podman compose up -d
```

**You should see:** services reported as started — `postgres`, `redis`, `egress-proxy`, `api`, `worker`. Wait about thirty seconds after the command returns.

### 7. Create the database tables

```
scripts/dev.sh db upgrade head
```

**You should see:** a run of migration lines. The **last** one must mention `c3a5e91b6d47` or `queued_status`. That migration is what makes `queued` a status a row is allowed to be in; without it every add in this test fails on a database constraint.

### 8. Run the database-backed tests

```
scripts/dev.sh test-db
```

**You should see:** passing tests and, again, **no skips**. Named among them should be lines close to:

- `test_the_identical_file_added_again_links_to_the_existing_document`
- `test_the_same_content_under_two_names_in_one_drop`
- `test_a_different_file_with_the_same_name_is_not_a_duplicate`
- `test_the_database_refuses_a_second_live_row_with_the_same_hash`
- `test_a_zero_byte_file_is_rejected_and_the_rest_of_the_drop_proceeds`

That last-but-one is the database enforcing the rule on its own, independently of the code. The rest of this walkthrough checks the same behaviours by hand, which is worth doing separately: a test proves the function works, and this proves the running system does.

---

## Walk to the add screen by clicking

### 9. Nominate the folder your material is in

Open a browser at:

```
http://127.0.0.1:8000
```

**You should see:** the Askwell shell, with a strip of links on the left — **Ask**, **Library**, **Memory**, **Settings**.

Click **Settings**, scroll to **Folders Askwell may read**, type this into the **Nominate a folder** field, with your own username —

```
/home/you/askwell-test/material
```

— and click **Nominate**.

**You should see:** a box appear showing that path, marked **Readable** in grey.

If it says **Not permitted** or **Needs a restart**, the mount in step 2 did not take. Fix that before going on: nothing in this test can be read otherwise.

### 10. Get to the add screen the way a user would

Click **Ask** in the left strip.

**You should see:** a page headed **"Ask your own material"**, a panel headed **"Nothing added yet"**, and a button reading **Add a source**.

Click **Add a source**.

**You should see:** the page change to one headed **"Add a source"**, with the address in the browser bar ending `/sources/add/`.

### 11. Drop the `clients` folder

Open your file manager at `~/askwell-test/material`. Drag the **`clients`** folder over the browser window — **do not release yet**.

**You should see, while it is still held:** the window tints and a box with a dashed border appears reading **"Drop to add"**, and under it **"Files or whole folders. Askwell reads them where they are and copies nothing."**

Release.

**You should see:** a card appear, moving through **Detecting** to **Where are these?**. It should report **4 files** — `contract.pdf`, `contract copy.pdf`, `lease.pdf`, `empty.pdf` — and ask **"Which folder is “clients” in?"**.

Type, with your own username:

```
/home/you/askwell-test/material
```

and click **Add them**.

**You should see:** the card move to **Queued**, and the small grey line under the heading count the files as added on this machine.

### 12. Look at what was actually recorded

Click **Library** in the left strip.

**You should see:** **"Nothing has been added yet."**

**This is the gap, not a defect.** The screen's **Queued** card lives in your browser only; it did not create a source or a document. Confirm that directly:

```
scripts/dev.sh psql
```

At the `askwell=#` prompt, paste:

```
SELECT count(*) FROM sources;
SELECT count(*) FROM documents;
```

**You should see:** `0` for both.

Type `\q` and press Enter to leave psql.

Record this once, against **Known gap 1** at the end — not as a new finding each time you meet it.

### 13. Confirm nothing was uploaded

Reload the add screen (F5).

**You should see:** the queued card **gone**, and the counter still showing what it counted. Nothing was sent anywhere; nothing was kept but a number in your own browser.

Now check what Askwell's egress proxy has refused:

```
curl -s localhost:8000/network
```

**You should see:** a JSON reply. What matters is that it shows no successful outbound connection to the internet during this test.

---

## The part this ticket built

The steps below reach the record-keeping directly, because nothing on screen calls it yet (**Known gap 1**). Everything is a block to paste; you do not need to understand the JSON to read the answers, which are written in ordinary sentences.

### 14. Establish a session, the same way opening the page does

```
cd ~/external/quantum-plus/askwell
curl -s -c /tmp/askwell-cookies -o /dev/null -H 'accept: text/html' http://127.0.0.1:8000/
```

**You should see:** no output. That is success — Askwell handed out a session, the same one your browser was given when the page loaded. There is nothing to sign in to.

### 15. Add the `clients` folder for real

Paste this whole block, **replacing `you` with your own username in all five places**:

```
curl -s -b /tmp/askwell-cookies -X POST http://127.0.0.1:8000/sources \
  -H 'content-type: application/json' \
  -d '{"root_path":"/home/you/askwell-test/material/clients",
       "name":"Clients",
       "files":[{"path":"/home/you/askwell-test/material/clients/contract.pdf","mime":"application/pdf"},
                {"path":"/home/you/askwell-test/material/clients/contract copy.pdf","mime":"application/pdf"},
                {"path":"/home/you/askwell-test/material/clients/lease.pdf","mime":"application/pdf"},
                {"path":"/home/you/askwell-test/material/clients/empty.pdf","mime":"application/pdf"}]}'
```

**You should see:** one reply covering the whole batch. Read four things out of it:

1. `"added": 2` — `contract.pdf` and `lease.pdf`.
2. `"duplicates": 1` — `contract copy.pdf`.
3. `"rejected": 1` — `empty.pdf`.
4. A `"source"` with a name of `Clients`.

**Read the duplicate's `reason` in full.** It should be a sentence close to:

> Askwell already has this, byte for byte — the same content under another name. It is indexed as /home/you/askwell-test/material/clients/contract.pdf, in Clients, so /home/you/askwell-test/material/clients/contract copy.pdf was not indexed again and answers will cite the copy that was. Nothing was deleted: both files are still where you put them.

Three things must be true of that sentence, and each is worth recording if it is not:

- **Both paths appear.** The one indexed and the one skipped. "Already present" without a path sends the user hunting through their own filing.
- **It says the content matched, not the name.** These two files have different names. The recognition is over the bytes.
- **It says nothing was deleted.** A user who has just been told a file was skipped needs to know their file is still there.

**Read the rejection's `reason`:**

> /home/you/askwell-test/material/clients/empty.pdf is empty — 0 bytes. There is nothing in it to read, so nothing was added. If it should have content, whatever wrote it did not finish.

**You should not see:** the whole batch refused because one file was empty. One bad file must not reject the drop it arrived in.

**You should also not see:** `empty.pdf` reported as a duplicate. Every empty file has the same hash as every other empty file, which is true of the bytes and misleading about the documents — so it is refused before the hash is ever compared.

### 16. Check what is on disk now

```
scripts/dev.sh psql
```

At the prompt:

```
SELECT s.name, d.filename, d.status, left(d.sha256, 12) AS hash FROM documents d JOIN sources s ON s.id = d.source_id ORDER BY d.added_at;
```

**You should see:** exactly **two** rows — `contract.pdf` and `lease.pdf` — both in `Clients`, both with status **`queued`**, and with **different** hashes.

**`queued` is the right answer, not a stuck one.** The row exists and nothing is looking at it yet. There is no worker to read these files — that arrives with `M1-ADD-ING-025`. A status of `indexing` here would be a claim that something is happening.

Now check the paths were kept:

```
SELECT filename, path FROM documents ORDER BY added_at;
```

**You should see:** each file's **whole path**, on your own disk, exactly where you left it. Askwell indexes in place; this column is a location in your filing, not a handle into a store Askwell owns.

Leave psql open — the next step uses it.

### 17. Confirm the hash is over the contents and not the name

Still at the `askwell=#` prompt:

```
SELECT filename, sha256 FROM documents ORDER BY added_at;
```

Copy the `sha256` for `contract.pdf`. Type `\q` to leave psql, then:

```
sha256sum ~/askwell-test/material/clients/contract.pdf
```

**You should see:** the same long string. It is the hash of the bytes in the file — nothing about the name, the folder or the modification time went into it.

### 18. Confirm it was recorded as a decision, with the path

```
scripts/dev.sh psql
```

```
SELECT kind, payload->>'path' AS path FROM audit_decisions ORDER BY occurred_at;
```

**You should see:** a `source_added` record, and a `document_added` record **for each of the two documents, each carrying its full path**. "When did this contract enter Askwell, and from where" is the question this store exists to answer, and an identifier alone answers neither half.

**You should not see:** a record for `contract copy.pdf` or for `empty.pdf`. Nothing changed for either, and a store of decisions that also holds non-events stops being a record of what you chose.

Now confirm the record has not been tampered with. Type `\q`, then:

```
podman compose exec api askwell-verify
```

**You should see:** the chains reported as intact.

### 19. The same contract in another folder — the ticket's own case

This is the whole point of the ticket. Paste, replacing `you`:

```
curl -s -b /tmp/askwell-cookies -X POST http://127.0.0.1:8000/sources \
  -H 'content-type: application/json' \
  -d '{"root_path":"/home/you/askwell-test/material/archive",
       "name":"Archive",
       "files":[{"path":"/home/you/askwell-test/material/archive/contract.pdf","mime":"application/pdf"},
                {"path":"/home/you/askwell-test/material/archive/acme-agreement-FINAL-v3.pdf","mime":"application/pdf"},
                {"path":"/home/you/askwell-test/material/archive/lease.pdf","mime":"application/pdf"}]}'
```

**You should see:** `"added": 1`, `"duplicates": 2`, `"rejected": 0`.

Read each of the three:

- `archive/contract.pdf` — a duplicate, described as **"the same file in another folder"**, pointing at `clients/contract.pdf` in **Clients**.
- `archive/acme-agreement-FINAL-v3.pdf` — a duplicate, described as **"the same content under another name"**, pointing at the same file. A name that looks like a later version is not one; only the bytes decide.
- `archive/lease.pdf` — **added**. Same name as `clients/lease.pdf`, different contents, different document. If this comes back as a duplicate, stop and record it — that is the most serious failure this feature has, because it means a real document was silently dropped.

**Recognition reached across two different sources**, which is what the ticket is for: three folders is three sources, and a rule that only looked inside one folder would recognise nothing.

### 20. Confirm the library still holds one copy of the contract

```
scripts/dev.sh psql
```

```
SELECT s.name, d.filename, d.status FROM documents d JOIN sources s ON s.id = d.source_id ORDER BY d.added_at;
```

**You should see:** **three** rows, not six — `contract.pdf` and `lease.pdf` in `Clients`, and `lease.pdf` in `Archive`. Exactly one row has the contract's contents.

Then:

```
SELECT sha256, count(*) FROM documents WHERE deleted_at IS NULL AND superseded_by IS NULL GROUP BY sha256 HAVING count(*) > 1;
```

**You should see:** **no rows**. No content is held twice.

Type `\q`.

### 21. A file that is still being written

The ticket's edge case: a file that changes while Askwell is reading it must not be filed under a hash it does not have.

Start a file that keeps growing:

```
( for i in $(seq 1 200000); do printf '%s\n' "line $i"; sleep 0.0002; done > ~/askwell-test/material/clients/still-arriving.pdf ) &
```

**You should see:** a job number printed, like `[1] 12345`.

Immediately, while it is still writing, paste (replacing `you`):

```
curl -s -b /tmp/askwell-cookies -X POST http://127.0.0.1:8000/sources \
  -H 'content-type: application/json' \
  -d '{"root_path":"/home/you/askwell-test/material/clients",
       "files":[{"path":"/home/you/askwell-test/material/clients/still-arriving.pdf","mime":"application/pdf"}]}'
```

**You should see one of two things, and both are correct:**

- **Refused**, with a reason close to: *"… kept changing while Askwell was reading it, so the copy it read was not one version of the file. It was not indexed. This usually means something is still writing it — a download, a sync client, or a save in progress. Add it again once it has settled."*
- Or **added**, if the file happened to finish between Askwell's attempts. Askwell re-reads it up to three times, so on a fast machine it may well catch a settled copy.

**What must not happen:** it is added, and its stored hash does not match the finished file. Check that, after waiting for the writing to finish:

```
wait
sha256sum ~/askwell-test/material/clients/still-arriving.pdf
```

```
scripts/dev.sh psql
```

```
SELECT filename, sha256 FROM documents WHERE filename = 'still-arriving.pdf';
```

**You should see:** either **no row** (it was refused) or a row whose hash **matches** what `sha256sum` printed. A row with a different hash is a defect — every future duplicate check about that document would be wrong, silently, for as long as the row survives.

Type `\q`.

> If the refusal is what you got, try the same request again now that the file has settled. **You should see** it added.

### 22. A file in a folder Askwell was never given

Replacing `you`:

```
curl -s -b /tmp/askwell-cookies -X POST http://127.0.0.1:8000/sources \
  -H 'content-type: application/json' \
  -d '{"root_path":"/home/you/askwell-test/outside",
       "files":[{"path":"/home/you/askwell-test/outside/stray.pdf","mime":"application/pdf"}]}'
```

**You should see:** a refusal of the whole request, with a sentence close to: *"No folder you have nominated covers /home/you/askwell-test/outside. Askwell reads your files where they are and never copies them, so it has to be told which folders it may open. Nominate this one first."*

**You should not see:** a stack trace, a bare code, or the word "Unprocessable".

Now confirm nothing was read. `stray.pdf` is outside the mount from step 2, so the container cannot see it at all — the refusal came from the rule, and the mount is the second, independent reason. Both must hold.

```
scripts/dev.sh psql
```

```
SELECT count(*) FROM documents WHERE path LIKE '%outside%';
```

**You should see:** `0`. Type `\q`.

### 23. Nothing to add means no empty folder in the library

Add only files Askwell already has (replacing `you`):

```
curl -s -b /tmp/askwell-cookies -X POST http://127.0.0.1:8000/sources \
  -H 'content-type: application/json' \
  -d '{"root_path":"/home/you/askwell-test/material/archive",
       "name":"Archive again",
       "files":[{"path":"/home/you/askwell-test/material/archive/contract.pdf","mime":"application/pdf"}]}'
```

**You should see:** `"duplicates": 1`, `"added": 0`, and `"source": null`.

```
scripts/dev.sh psql
```

```
SELECT name, status FROM sources ORDER BY added_at;
```

**You should see:** `Clients` and `Archive` only. **No** `Archive again`. A folder in the library with nothing in it is something the user has to work out the meaning of, and the meaning is "nothing happened".

Look at the `status` column too.

**You should see:** both sources at **`queued`** — every document in them is queued and nothing is running.

### 24. Confirm the files on your disk are untouched

Switch to your file manager and look through `~/askwell-test/material`.

**You should see:** every file exactly as step 1 created it — same names, same sizes, same modification times. No file added by Askwell, none removed, none renamed.

This is the check that matters most. Everything else in this test is behaviour; this is the promise.

---

## Tidy up

```
rm -rf ~/askwell-test /tmp/askwell-cookies
podman compose down -v
```

Then blank the `ASKWELL_ROOTS_MOUNT=` line in `.env` if you do not want to keep it.

To reset the add screen's local counter, open the browser's developer tools, go to **Application → Local Storage**, and delete the key `askwell.sources.added`. It is only ever stored there and it is never sent anywhere.

---

## Known gaps

These are deliberately not built, or are already recorded. Do not report them as defects.

1. **The add-source screen does not create these records** (steps 12 and 14). The screen ends a drop at a **Queued** card held in your browser, and the record-keeping this ticket built is reached only by the route steps 15 onward use. Until the two are joined, dropping files creates nothing and the Library stays empty. `M1-ADD-FE-022` shipped the screen and `M1-ADD-BE-023` shipped the records; neither owned the wiring. Recorded under Open in `docs/BRAIN.md`.

2. **Nothing is extracted, embedded or searchable.** Every document ends at **`queued`** and stays there. There is no worker reading them and no way to ask a question about them yet — that is `M1-ADD-ING-025`. A document never reaches `ready` in this walkthrough, and the code path that moves it is exercised only by the tests in step 8.

3. **A changed file is a new document, not a newer version of the old one.** Edit `contract.pdf` and add it again and Askwell will treat it as a document it has never seen, alongside the original. Supersession — recognising that this is the same document, changed — is `M1-INDEX-BE-034`, and it needs a rule about when a change has settled that does not exist yet.

4. **Deletion is M2.** Nothing added in this test can be removed through Askwell. Dropping the database (`podman compose down -v`) is the only way to clear it today.

5. **Unsupported formats are not rejected here.** A program, an archive or a `.zip` renamed to `.pdf` is accepted by this ticket and recorded. Rejection by format, with the supported list, is `M1-ADD-VAL-024`. The add screen already refuses some of these in the browser (see `docs/manual-tests/M1-ADD-FE-022.md` step 18), which is a courtesy to the user and not a boundary.

6. **The type Askwell stores is the one the caller reported.** `documents.mime` holds whatever was sent — in step 15, whatever you typed. Nothing re-detects it and nothing reads it. Server-side content detection is `M1-ADD-VAL-024`, which must also decide what to do about values stored today. Recorded under Open in `docs/BRAIN.md`.

7. **Two adds at exactly the same moment can both succeed.** Two browser tabs, or a double-submitted drop, can each create their own source and each insert the same content, because the database's backstop index is per-folder while the rule in code is global. The library would then hold the same document twice. This walkthrough adds one batch at a time. Recorded under Open in `docs/BRAIN.md`.

8. **A file edited between being added and being read will be indexed under the wrong hash.** Step 21 covers a file changing *during* hashing, which is caught. A file changed *after* the row is written and *before* `M1-ADD-ING-025` reads it is not, because nothing yet records what the file looked like when it was hashed. Recorded under Open in `docs/BRAIN.md`.

9. **A file may be filed under a folder it does not live in.** The check is that some folder you nominated covers the file, not that *this* source's folder does. Sending a file from `archive` in a request whose folder is `clients` succeeds and the document appears under `Clients`. Nothing over-permissive happens — every accepted path is still inside a folder you nominated — but the library would show a source containing a file from somewhere else. Recorded under Open in `docs/BRAIN.md`. This walkthrough keeps each batch to its own folder.

10. **A failed document has nowhere to record why.** A document can be moved to `attention`, and the reason goes only to the log — not to the screen the user is looking at. Recorded under Open in `docs/BRAIN.md`; the column arrives with the ticket that first produces a reason to put in it.

11. **There is no screen for any of this.** The Library page is still its empty state. Steps 16–23 use `psql` because there is nowhere in the interface to look yet.

12. **A folder reached through a symbolic link** can be nominated but files under it will not be readable. Recorded under Open in `docs/BRAIN.md`. Avoid symlinked paths in this test.

13. **SELinux behaviour of the mount is unverified.** If the folder in step 9 reports **Not permitted**, that is the open item in `docs/BRAIN.md`, not a new finding.
