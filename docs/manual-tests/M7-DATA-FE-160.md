# Manual test — M7-DATA-FE-160, Settings → Your data

**Ticket:** `M7-DATA-FE-160`. It covers the six actions in **Settings → Your data**: export everything, export the log, delete a source, delete all memory, verify the log, and reset Askwell.

**Version under test:** `0.7.29`. Run `cat VERSION` and update this line if the version has moved on.

**Time:** about 60 minutes. Most of it is waiting for documents to index and for a question to be answered.

**Who can run it:** anyone with a browser, an ordinary text editor and a terminal. The terminal is used only to start Askwell, to make the test files, and to check those files afterwards. Every Askwell screen is reached by clicking.

**What is being checked.** The screen is `web/components/settings/your-data.tsx`. Its wording lives in `web/lib/data-export.ts`, `web/lib/reset.ts` and `web/lib/memory.ts`. Export is `askwell.log_export` with `scope: "everything"` or `"log"`. Reset is `askwell.reset`. Verification is `M7-LOG-FE-156`'s `verify-log.tsx`, placed here unchanged.

> **Warning: Part F deletes everything Askwell holds on the machine you run it on.** That means sources, memory, conversations, the audit log, settings and the passphrase. Your original files are not touched, and this test checks that. Run it on a test install. On the shared development machine, do not run it if anyone needs what that stack currently holds. Export first (Part B does this) if you are unsure.

---

## Before you start

### Test files

Askwell can only read folders inside `ASKWELL_ROOTS_MOUNT` in `.env`. On this machine it is `/tmp`. Check it:

```
cd ~/external/quantum-plus/askwell
grep ASKWELL_ROOTS_MOUNT .env
```

If it is empty, or does not contain `/tmp`, set `ASKWELL_ROOTS_MOUNT=/tmp` before starting the stack.

Make a folder with two small text files. Each states one fact you can ask about:

```
mkdir -p /tmp/askwell-test-160
printf 'The Meridian supply agreement has a notice period of ninety days.\n' > /tmp/askwell-test-160/meridian.txt
printf 'All RFQs over 5,000 dollars need two quotes.\n' > /tmp/askwell-test-160/procurement.txt
```

Part F also needs a file that takes a while to index, so the reset happens while it is still indexing. Keep a large PDF ready, 50 pages or more, **outside** the test folder for now. Any long report or manual will do.

Record the checksums of the test folder now. Part F compares against them:

```
sha256sum /tmp/askwell-test-160/* > /tmp/before-160.sha
cat /tmp/before-160.sha
```

**You should see:** two lines, one per file.

### Start Askwell

```
scripts/dev.sh build-api
scripts/dev.sh web-build
podman compose up -d
scripts/dev.sh db upgrade head
```

**You should see:** the builds finish without red error text. Compose reports `postgres`, `redis`, `egress-proxy`, `api` and `worker` as started. The migration ends without an error. This ticket adds migration `c8f2a61d4b90`. Without `db upgrade head`, export fails.

Do not skip `build-api`. The API's code is baked into its image, so without a rebuild the running API is the old one and **Export everything** is refused.

In a **second** terminal, start the model on the host and leave it running:

```
scripts/dev.sh inference
```

**You should see:** the supervisor logs that the generation model is ready.

---

## Part A — cold start, and something to export

### 1. Open Askwell

Open a **private or fresh-profile** browser window, so no earlier session carries over. Open `http://127.0.0.1:8000`. This is where a user starts.

**You should see one of two screens:**

- **Fresh install:** the welcome screen, "Welcome to Askwell", with a **Get started** button.
- **Sources already added:** the **Ask** screen, with a rail on the left: **Ask**, **Library**, **Clarifications**, **Memory**, **Settings**.

### 2. Add the test folder

- **Fresh install:** click **Get started** and follow the steps. On the step that adds material, go on to step 2b below.
- **Sources already there:** click **Library** in the rail, then **Add a source** below the list.

2b. Click **Choose a folder** and pick `/tmp/askwell-test-160`. Under "Which folder are these files in?", type `/tmp/askwell-test-160` and click **Add them**. If a note offers **Nominate /tmp/askwell-test-160**, click it.

**You should see:** both files accepted, with no red "Not added" note. Click **Library** in the rail. `meridian.txt` and `procurement.txt` show as ready, not queued or indexing. Wait until they do.

### 3. Ask a question

Click **Ask** in the rail. Type `What is the notice period for the Meridian agreement?` and send it.

**You should see:** an answer saying ninety days, with a citation to `meridian.txt`. Note the wording of your question. Step 8 looks for it in the export.

### 4. Tell Askwell a fact

Click **Memory** in the rail. Click **Add a fact**. Enter **Subject** `RFQ` and **What it means** `Request for Quotation`. Click **Add**.

**You should see:** a card for `RFQ` reading `Request for Quotation`. Count the cards on the Memory screen and write the number down. Part D checks it.

---

## Part B — export everything

### 5. Find Your data

Click **Settings** in the rail. Scroll past **Model and speed**, **Folders**, **Storage** and **Privacy and security** to **Your data**.

**You should see:** six sub-headings, in this order: **Export everything**, **Export the log**, **Delete a source**, **Delete all memory**, **Verify the log**, **Reset Askwell**. None is greyed out or labelled "coming soon".

### 6. Read what the export holds

Under **Export everything**, read the description.

**You should see:** "Your sources list, memory, clarifications, conversations, and all three logs: both audit logs with their hash chain, a verifier that checks it, and the recent answer traces. Plain text: JSON Lines files and a README explaining each one. Your own files are not copied."

### 7. Run it

Click **Export everything**.

**You should see:** the button reads "Exporting…" and is disabled. A grey line below counts up: "N of M log records written…". It ends with "Writing sources, memory and conversations…", followed by "This runs in the background; you can keep using Askwell." When it finishes: "Ready, <size>. Download the export". A small install may finish in a second or two, so the progress lines can flash by.

While it runs, click **Ask** in the rail and back to **Settings**. Askwell should keep working normally. Leaving the screen stops the progress display, not the export.

**No passphrase warning appears.** None is set yet. Part C covers that case.

### 8. Open the files in an ordinary editor

Click **Download the export**. Unzip the file into a new folder, then open it in a file manager.

**You should see** these files and folders: `README.txt`, `manifest.json`, `verify.py`, `decisions.jsonl`, `interactions.jsonl`, a `data/` folder, and a `traces/` folder.

Open each of these in a plain text editor (gedit, TextEdit, Notepad or similar), **not** in Askwell:

| File | You should see |
| ---- | -------------- |
| `README.txt` | Plain English. It explains every file, and ends with a **Not included:** list giving a reason for each item: your files, chunks, connection credentials, settings, vector index, job bookkeeping |
| `data/memory.jsonl` | One line per fact. The line for `RFQ` contains `Request for Quotation`, as you typed it |
| `data/messages.jsonl` | Your question from step 3, word for word, and Askwell's answer mentioning ninety days |
| `data/sources.jsonl`, `data/documents.jsonl` | The test folder, and each file with its path `/tmp/askwell-test-160/...` |
| `data/roots.jsonl` | `/tmp/askwell-test-160` |
| `decisions.jsonl`, `interactions.jsonl` | One JSON object per line. Every line has `"prev_hash"` and `"hash"` |
| `traces/` | One `.trace.json` file per recent answer. Its name matches an `"id"` in `messages.jsonl` |

Nothing should be unreadable: no binary data, no long ciphertext strings in place of your words. Your own `.txt` files are **not** in the zip.

### 9. Check the chain without Askwell

In a terminal, `cd` into the unzipped folder and run:

```
python3 verify.py .
```

**You should see:** two lines, "decisions: N records, chain intact." and "interactions: N records, chain intact.", with N greater than 0 for each.

Optional tamper check: in `interactions.jsonl`, change one letter inside your question and save. Run `python3 verify.py .` again. **You should see:** the interactions line now says that record's contents were altered after export. Undo the edit afterwards.

### 10. Export the log alone

Back in **Settings → Your data**, under **Export the log**, read the description. Then click **Export the log**, and download and unzip the result.

**You should see:** the description reads "Both audit logs with their hash chain, and a verifier that checks it without Askwell, for showing someone else what was asked." The zip holds `decisions.jsonl`, `interactions.jsonl`, `verify.py` and `manifest.json`, with **no** `data/` and **no** `traces/` folder. `python3 verify.py .` reports both chains intact.

---

## Part C — export with a passphrase set

### 11. Set a passphrase

Scroll up to **Privacy and security → Passphrase**. Click **Set a passphrase**. Type the same passphrase twice, tick **I understand there is no recovery.**, and click **Set passphrase**.

**You should see:** the Passphrase section no longer says "Off". Write the passphrase down. You will not need it again, because Part F's reset forgets it.

### 12. Try to export: Cancel

Scroll down to **Your data** and click **Export everything**.

**You should see:** before any progress line appears, a panel in the warning colour: "A passphrase protects your library, but this export will not be protected. It is written as plain text, so anyone who has the file can read it. Keep it somewhere you trust." It has two buttons, **Export without protection** and **Cancel**.

Click **Cancel**. **You should see:** the panel close and the plain **Export everything** button return. No "Ready" line, and nothing to download.

### 13. Export anyway

Click **Export everything** again, then **Export without protection**.

**You should see:** the same progress, then "Ready, <size>. Download the export". Download and unzip it. `data/memory.jsonl` still shows `Request for Quotation` in plain text. That is what the warning said.

Repeat with **Export the log**. **You should see:** the same warning first.

---

## Part D — delete a source, delete all memory, verify

### 14. Delete a source is a link

Under **Delete a source**, read the text, then click **Open the Library**.

**You should see:** the text says the file on your disk is untouched and that past answers citing it show it as deleted. The link takes you to the **Library** screen, where each source has its own **Delete**. You do not need to delete anything here, because `M2-DELETE-FE-062` covers that. Click **Settings** in the rail to come back.

### 15. Delete all memory: the confirmation

Under **Delete all memory**, read the description, then click **Delete all memory**.

**You should see:** the button briefly reads "Counting…". Then a panel in the warning colour appears: "Delete all N facts Askwell has learned? This cannot be undone." N is the number you wrote down in step 4 (with one fact it reads "1 fact"). The buttons are **Delete all N** and **Cancel**.

Click **Cancel** first. **You should see:** the panel close. Nothing is deleted.

### 16. Delete it

Click **Delete all memory** again, then **Delete all N**.

**You should see:** "Memory is empty. Askwell will ask again when it needs to know." Click **Memory** in the rail. There are no fact cards. Click **Settings** to come back.

Click **Delete all memory** a third time. **You should see:** "Askwell holds no memory. There is nothing to delete." and no confirmation panel.

### 17. Verify the log

Under **Verify the log**, click **Verify the log**.

**You should see:** two reports, "Decisions — chain intact" and "Interactions — chain intact", each with "N records checked." The decisions count is higher than it was at step 9, because exporting and deleting all memory each wrote a record.

---

## Part E — ingestion running

### 18. Start something indexing

Copy the large PDF into the test folder, then update the checksum list so it includes the PDF:

```
cp ~/path/to/large.pdf /tmp/askwell-test-160/
sha256sum /tmp/askwell-test-160/* > /tmp/before-160.sha
```

In Askwell, click **Library**, then **Add a source**, then **Choose files**. Pick the PDF, type `/tmp/askwell-test-160` as its folder and click **Add them**. Click **Library** and confirm the PDF shows as queued or indexing, **not** ready. If it is already ready, use a bigger PDF.

Go straight on to Part F while it is still indexing.

---

## Part F — reset Askwell

### 19. Read the confirmation

Click **Settings** in the rail and scroll to **Reset Askwell**. The description reads "Removes everything Askwell holds and starts it fresh. Your original files are never touched." Click **Reset Askwell**.

**You should see:** the button briefly reads "Checking what would be removed…". Then a panel opens. In order:

1. **In bold, first:** "Your original files are never touched. Askwell forgets the folders you registered and everything it learned from them; the files themselves stay exactly where they are, unchanged."
2. "Reset removes:", followed by a bulleted list with real numbers:
   - "N sources and everything indexed from them"
   - "N registered folders, which Askwell forgets". The word is **forgets**, never "deletes".
   - "0 memory facts and N clarifications". Memory is 0 after Part D.
   - "N conversations"
   - "N log records, including the record of earlier exports and deletions"
   - "your settings, including any passphrase"
   - "N files Askwell wrote: answer traces, and exports or backups still held inside Askwell. Anything you already downloaded is yours and stays"
3. "Anything being added right now is stopped first, then removed with the rest."
4. "The log that records this reset is destroyed with everything else. One record survives: that a reset happened and how much it removed, as the first entry of a new log."
5. In the warning colour: "This cannot be undone. Export everything first if you may want any of it."

The buttons are **Reset Askwell** and **Cancel**. Click **Cancel** first. **You should see:** the panel close, and nothing removed. Library still lists your sources.

### 20. Reset

Click **Reset Askwell** again, then **Reset Askwell** in the panel.

**You should see:** the button reads "Resetting…". It may wait a few seconds for the indexing PDF to finish its current write. Then the panel changes to:

- "Reset. N records removed."
- The original-files statement again.
- A **Start again** link.

No line naming files that "could not be removed". If a line says "Imported database copies could not be reached just now. They are removed the next time Askwell starts.", that is acceptable. It means the sandbox was down, and this test adds no dumps.

### 21. Your files are untouched

In a terminal:

```
sha256sum -c /tmp/before-160.sha
ls -la /tmp/askwell-test-160
```

**You should see:** every file, including the PDF from step 18, reported `OK`. `ls` lists `meridian.txt`, `procurement.txt` and the PDF, with their original sizes and dates. Nothing is missing or added.

The zips you downloaded in Parts B and C are still where your browser saved them.

### 22. Start again

Click **Start again**.

**You should see:** the page reloads fully, since the address bar flickers, and you land on the welcome screen, "Welcome to Askwell". Askwell holds nothing, so it treats this as a fresh install.

Click **Skip setup**. Then click through the rail:

- **Library:** empty. Not even the PDF that was indexing reappears. Wait a minute and check again. It stays empty.
- **Memory:** no facts.
- **Settings → Privacy and security → Passphrase:** "Off". The passphrase is forgotten.
- **Settings → Folders:** no registered folders.
- **Settings → Your data → Verify the log:** "Decisions — chain intact", with a small record count: the reset record first, and any work since. "Interactions — chain intact" with 0 or very few records.

### 23. The network stayed local

In a terminal: `curl -s -c /tmp/askwell.cookies -H 'Accept: text/html' localhost:8000/ -o /dev/null && curl -s -b /tmp/askwell.cookies localhost:8000/network`

**You should see:** no refused outbound attempts from this session. Nothing in this test should try to reach the network.

---

## Known gaps

These are deliberately not built. Do not report them as defects.

- **No import of an export.** An export is for reading and keeping, not restoring. Restoring is the backup path (**Settings → Storage**), and moving memory across machines is not in v1.
- **A job already running when reset is pressed can write its zip after reset's sweep.** An export or backup started seconds before a reset may leave a file inside Askwell's own export or backup folder. Issue #686, filed and not fixed.
- **Other open sections lose their session after a reset** until the page is reloaded. They answer "No session" if clicked. **Start again** reloads the page for this reason. It is recorded in `docs/states-and-edge-cases.md` and `docs/decisions.md` (2026-09-24).
- **Chunks, the vector index, settings and job rows are not in the export.** The README says why for each. The indexed passages are text extracted from files you already have.
- **Prune has no settings-screen control yet.** Storage's combined export-and-prune stays disabled. That is separate from this ticket's **Export the log**.
- **Delete a source is not rebuilt here.** It is a link to the Library, by design (`docs/ux/library.md` §4).
