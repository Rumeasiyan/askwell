# Manual test — M2-FAIL-FE-060, degrade to search when the assistant is unavailable

**Ticket:** `M2-FAIL-FE-060` — Ask states plainly that the assistant is down, with a fix path, and offers keyword/hybrid search across sources instead of going blank.
**Version under test:** `0.2.47`
**Time:** about 30 minutes, plus a first stack build
**Who can run it:** anyone who can paste a line into a terminal and stop/restart a process. Everything from step 5 onward is clicking and reading.

**What is being checked.** When the native inference process dies, Askwell should say so plainly on the Ask screen, offer a way to keep working (search), and recover on its own once the process comes back — no reload, no manual "retry" click. Search during the outage has to actually search the indexed corpus and return real filenames and pages, not a placeholder.

**Where this stops on purpose.** Nothing here repairs the assistant automatically, and nothing swaps in a different model — both are out of scope for this ticket. The "embedding queues rather than fails" bullet in the ticket's scope is **not built**: see Known gaps.

---

## Before you start

You need a terminal and Podman, and a document already indexed so there is something to search. If you already have a working Askwell install with at least one indexed file, skip to step 4.

### 1. Make a file to test with

```
mkdir -p ~/askwell-test/material
cd ~/askwell-test/material
printf '%s\n' '%PDF-1.7' 'The Meridian agreement renews automatically every twelve months unless either party gives ninety days notice.' > meridian-contract.pdf
```

### 2. Point Askwell at the folder and bring the stack up

In `.env`, set `ASKWELL_ROOTS_MOUNT` to the absolute path of `~/askwell-test/material`, then:

```
podman compose up -d
scripts/dev.sh inference
```

The last command starts native inference on the host — leave that terminal open, since stopping it later (`Ctrl+C`) is how this test simulates the assistant dying.

### 3. Open Askwell and index the file

Open `http://127.0.0.1:8000`. Go to **Add a source**, add the `~/askwell-test/material` folder, and wait until the **Library** screen shows `meridian-contract.pdf` as indexed rather than queued or indexing. This can take a minute the first time a model loads.

---

## The walkthrough

### 4. Confirm the assistant is healthy before breaking anything

Go to **Ask**. **Expect:** no banner across the top of the screen — the shell only shows one when something is wrong. Type "What is the notice period for the Meridian agreement?" and send it. **Expect:** a normal answer streams in, citing `meridian-contract.pdf` in the margin beside it.

### 5. Stop the assistant

Go back to the terminal running `scripts/dev.sh inference` and press `Ctrl+C` to stop it. Wait about ten seconds — Askwell polls status roughly every five seconds.

**Expect, without reloading the page:**
- A banner appears at the top of the shell with a heading naming the assistant specifically (e.g. "The assistant is not running.") and a fix — for this stopped-process case, the instruction to run `scripts/dev.sh inference` again — plus a line starting "Still works:" listing that you can still open, browse and search your documents.
- On the Ask screen itself, a new panel appears above the question box reading **"Search your files while the assistant is unavailable"**, with its own search box and a **Search** button.
- The question box is still there and still usable — nothing about the composer is disabled.

### 6. Search during the outage

In the new search panel, type `Meridian` and click **Search**.

**Expect:**
- Briefly, "Searching…".
- A line reading **"Keyword-only while the assistant is unavailable."** — dense search needs the model to embed the query, so this is the tell that only lexical matching ran.
- Below it, one result: `meridian-contract.pdf` with a page number, and a passage of text containing "Meridian agreement" and "ninety days notice."
- Clicking the filename opens the source viewer at that page.

### 7. Search for something that is not in your files

Type `xylophone` and click **Search** again. **Expect:** "Nothing in your files matched that search." — not an error, not a blank panel.

### 8. Add a document while the assistant is still down

Still with inference stopped, go to **Add a source** and add a second file to the same folder (e.g. copy `meridian-contract.pdf` to `second-contract.pdf` first and add that file, or drag a new one in). **Expect:** the card still runs through its normal *Detecting → Recording → Queued* sequence and the file appears in the **Library** — extraction is not blocked by the assistant being down.

**Record what actually happens next**, since the ticket's stated behaviour ("embedding queues rather than fails, and resumes once the assistant returns") is not what is implemented today — see Known gaps. Watch the Library entry's status: if it reaches a permanent failure rather than sitting at a state that says it is waiting on the assistant, that is the gap, not a new defect to file.

### 9. Restart the assistant and confirm recovery with no reload

Go back to the terminal and run `scripts/dev.sh inference` again. Wait for it to finish loading (the terminal output says the model is ready).

**Expect, without touching the browser at all:**
- Within about ten seconds, the top banner disappears.
- The "Search your files while the assistant is unavailable" panel disappears from the Ask screen.
- Typing a question in the composer and sending it now produces a normal, cited answer again — confirming the recovery is real, not just cosmetic.

### 10. Confirm the restarting state reads differently from stopped

This is harder to catch by hand since a restart is quick, but worth one attempt: stop inference again, and this time watch the banner heading in the few seconds after Askwell notices. If the process is restarting under the supervisor (rather than simply not running), the heading should read something like "The assistant stopped and is restarting." rather than "The assistant is not running." — two different sentences for two different situations, never collapsed into one generic "unavailable."

---

## Known gaps

- **Embedding does not queue-and-resume across an assistant outage.** The ticket's scope calls for extraction and chunking to continue while embedding waits for the assistant and resumes automatically when it returns. What is actually implemented (`M1-INDEX-ING-032`) is a bounded retry: `InferenceUnavailable` during embedding is retried a fixed number of times with backoff and then the document is marked failed, needing a manual retry from the Library screen — the same behaviour as any other stage failure. If step 8 above shows a file failing outright rather than waiting indefinitely, that is this gap, tracked as issue #227, not a new bug.
- **Outages are not logged with cause and duration**, as the ticket's audit requirement asks for. Today `askwell.assistant.read` logs an `assistant_state_changed` line with the cause whenever it changes, but nothing computes or records how long the assistant was down — there is no duration on that log line and nothing queryable elsewhere for outage length.
- **No repair button.** The fix path in the banner is instructional text only (e.g. "run `scripts/dev.sh inference`"); nothing in the interface restarts the process for you. This is explicitly out of scope (automatic repair of the process).
- **No model swap.** Also explicitly out of scope (`M7`).
- Search during an outage is keyword-oriented only, as the ticket itself notes — this is expected, not a defect, and is what the "Keyword-only" line in step 6 exists to say plainly.
