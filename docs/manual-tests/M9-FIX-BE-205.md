# Manual test — M9-FIX-BE-205, a passphrase does not stop new files being indexed

**Ticket:** `M9-FIX-BE-205`, issue #508 (and the same root cause as #504). Askwell runs as two
processes: the one the browser talks to, and a background indexer that reads and indexes files.
Once a passphrase was set, only the first could ever be unlocked. Every file added afterwards
stopped part-way and was eventually marked **Needs attention**, even after the passphrase had
been entered. Now:

- Unlocking Askwell unlocks the background indexer too, so an added folder indexes normally.
- While Askwell is locked, a new file waits, and the queue says it is waiting for your
  passphrase. It is not marked as failed, and it carries on by itself once you unlock.
- Restarting Askwell locks everything again until the passphrase is entered.
- A wrong passphrase unlocks nothing.

**Version under test:** `0.7.53`. Run `cat VERSION` and update this line if the version has
moved on.

**Time:** about 45 minutes. Most of it is waiting for files to index and for the model to answer
on CPU.

**Who can run it:** anyone with a browser and a terminal. You reach every Askwell screen by
clicking, starting from the address in step 1. The terminal only starts and restarts Askwell and
makes the test folders. It also runs a few checks that cannot be done by looking at the screen.
Those are labelled **Stand-in**.

**What is being checked.**

- `api/src/askwell/worker_unlock.py` (new). The indexer listens on a private local socket. The
  API hands it the unlocked key after every unlock, set, change, remove and reset, and every 5
  seconds. It can push a key or tell the indexer to lock. Nothing can ask the indexer for a key.
- `api/src/askwell/passphrase.py`: `adopt_key`, where the indexer checks a key before it accepts
  it, and `_holds_current_key`, where an old key counts as locked.
- `api/src/askwell/ingest.py`: `_wait_for_unlock` and `revive_unlocked`. A locked stage parks
  the file with `awaiting = 'unlock'` and gives the attempt back, and unlocking puts it back on
  the queue.
- `api/src/askwell/worker.py` and `app.py`: the indexer starts listening, and the API keeps the
  two in step.
- `web/lib/ingest.ts`, `queueSentence`: the new *"waiting for your passphrase"* sentence.

**The one rule of this test.** Never type an address into the browser bar except the one in
step 1. Reach every screen by clicking. Reloading the tab is allowed where a step says so.

**Read this before Part D.** In Askwell today, **Settings → Privacy and security → Passphrase
has no Unlock button**. The queue tells you to *"Unlock Askwell in Settings"*, but the only
place in the interface that asks for the passphrase is **Settings → Online AI → Your key → Add a
key**. This test uses that route because it is the only one. The dead end is filed as #784. It
is not a defect of this ticket, and you do not need to report it again.

---

## Before you start

> **Warning: the cold start below deletes everything this Askwell stack holds.** That means
> sources, memory, conversations, the audit log and settings. Your original files are not
> touched. On the shared development machine, check that nobody needs what the stack holds
> now. If you are unsure, use **Settings → Your data → Export everything** first.

> **Warning: pick a passphrase you will not reuse anywhere.** Part H searches Askwell's logs
> for it, so you will type it into a terminal command. This walkthrough uses
> `violet harbour lantern ninety`.

### A. Folders to add

Askwell can only read folders inside `ASKWELL_ROOTS_MOUNT` in `.env`. Check it:

```
cd ~/external/quantum-plus/askwell
grep ASKWELL_ROOTS_MOUNT .env
```

If it is empty, or does not cover `/tmp`, set `ASKWELL_ROOTS_MOUNT=/tmp`. Then make four
folders, one per part of the test, each holding one file from the fixture corpus:

```
rm -rf /tmp/askwell-test-205
mkdir -p /tmp/askwell-test-205/{unlocked,locked,worker-restart,api-restart}
cp eval/fixtures/corpus/handbook_a.pdf       /tmp/askwell-test-205/unlocked/
cp eval/fixtures/corpus/store_hours_2026.pdf /tmp/askwell-test-205/locked/
cp eval/fixtures/corpus/handbook_b.pdf       /tmp/askwell-test-205/worker-restart/
cp eval/fixtures/corpus/spec.docx            /tmp/askwell-test-205/api-restart/
chcon -R -t container_file_t /tmp/askwell-test-205
find /tmp/askwell-test-205 -type f
```

**You should see:** four lines, one file in each folder. The `chcon` line lets the containers
read `/tmp` on this machine, which has SELinux turned on. If it says `Operation not supported`,
your machine does not use SELinux and you can ignore it.

What the files say, so you can check the answers:

| File | Says |
| ---- | ---- |
| `handbook_a.pdf` | The standard resignation notice period at Meridian Loom is **sixty-three days** |
| `store_hours_2026.pdf`, page 1 | *"Meridian Loom retail stores close at **9 PM** on weekdays."* |
| `handbook_b.pdf`, page 4 | Production database credentials are rotated every **forty-five days** |

### B. Start Askwell from nothing

```
podman compose down -v
scripts/dev.sh web-build
scripts/dev.sh build-api
podman compose up -d
scripts/dev.sh db upgrade head
```

**You should see:** the volumes removed, both builds finish with no red error text, the
containers start, and the migration finish with no error. Do not skip the API build. This fix
is in the API and the indexer, and without the build you are testing the old code.

**Stand-in:** check that the indexer opened its socket, and that only its owner can use it:

```
podman compose logs worker 2>&1 | grep worker_unlock_listening
ls -l .run/worker-unlock.sock
```

**You should see:** one `worker_unlock_listening` line naming `/run/askwell/worker-unlock.sock`,
and a file listing that starts `srw-------`. If you see `worker_unlock_unavailable` instead,
stop: the rest of this test cannot pass, and the reason is on that log line.

In a **second** terminal, start the model on the host and leave it running:

```
scripts/dev.sh inference
```

**You should see:** the supervisor report that the model and the embedding model are ready.
Indexing needs the embedding model, so every file in this test stays **Indexing** without it.

---

## Part A — first run

1. Open a **private or fresh-profile** browser window at full width, so no earlier session
   carries over. Go to `http://127.0.0.1:8000`. ☐

   **You should see:** **Welcome to Askwell**, a **Skip setup** button top right, and a **Get
   started** button. Down the left is a column listing **Ask, Library, Clarifications, Memory,
   Settings**. If you see the Ask screen instead, the stack was not cleared. Go back to *Before
   you start*, B.

2. Click **Get started**. At **Set a passphrase?**, click **Not now**, then **Continue**. ☐

   **You should see:** the next step, about the model.

   Do not choose **Set a passphrase** here. On this screen it only records a preference, and
   the text under it still says encryption *"is not enforced yet"*. That text is out of date
   (see *Known gaps*). You set the real passphrase in Part B.

3. Wait until the model section says the model is ready, then click **Continue** without
   adding anything. ☐

   **You should see:** a step beginning *"Ready. Add something to ask about"*.

---

## Part B — set a passphrase

4. Click **Settings** in the left column. Scroll down to the heading **Privacy and security**.
   ☐

   **You should see:** a **Passphrase** block reading *"Off. A stolen laptop is readable
   as-is. Setting a passphrase encrypts your library and stored credentials."*, with a **Set a
   passphrase** button.

5. Click **Set a passphrase**. Type `violet harbour lantern ninety` into both boxes. Tick **I
   understand there is no recovery**, then click **Set passphrase**. ☐

   **You should see:** the no-recovery warning above the boxes before you submit. The button
   reads **Setting…** for a moment. Then the block reads *"On. The library and stored
   credentials are encrypted with it."*, with **Change passphrase** and **Remove passphrase**
   buttons.

   Setting a passphrase also unlocks Askwell for this session. You do not need to type it again
   until Askwell restarts.

---

## Part C — unlocked: an added folder indexes

This is the main acceptance criterion. Before this fix, the file below stopped part-way and
ended at **Needs attention**.

6. Click **Library** in the left column, then **Add a source**. ☐

   **You should see:** a screen headed **Add a source**, with a **Files** panel holding
   **Choose files** and **Choose a folder**.

7. Click **Choose a folder**. Open `/tmp/askwell-test-205`, select `unlocked` and confirm. If
   the browser asks whether to upload the files, confirm. Nothing leaves this machine. When
   asked *"Which folder is “unlocked” in?"*, type `/tmp/askwell-test-205` and click **Add
   them**. If a note offers **Nominate**, click it, then **Add them** again. ☐

   **You should see:** a note headed **Queued** with no red **Not added** note. Under it, a
   line about the queue, such as *"Indexing handbook_a.pdf…"*. It must **not** say anything
   about a passphrase.

8. Wait up to two minutes, then click **Library** in the left column. ☐

   **You should see:** `handbook_a.pdf` marked **Ready**. If it says **Needs attention**, open
   it and note the reason. That is the #508 failure, and this ticket has not fixed it.

9. Click **Ask**. Type `What is the standard resignation notice period at Meridian Loom?` and
   press Enter. ☐

   **You should see:** an answer saying **sixty-three days**, cited to `handbook_a.pdf`. This
   shows the passages were stored encrypted and read back with the key.

**Stand-in:** check that the passages really were stored encrypted:

```
scripts/dev.sh psql -c "SELECT d.filename, c.content_encrypted, count(*) FROM chunks c JOIN documents d ON d.id = c.document_id GROUP BY 1, 2;"
```

**You should see:** one row, `handbook_a.pdf | t | <some number>`. No row with `f`.

---

## Part D — restart: locked, and a new file waits

10. In the first terminal, restart both Askwell processes:

    ```
    podman compose restart api worker
    ```

    Wait about 20 seconds, then **reload the browser tab**. ☐

    **You should see:** Askwell opens again. You may land back on the screen you were on.

11. Click **Settings** and scroll to **Privacy and security**. ☐

    **You should see:** the **Passphrase** block reads *"A passphrase is set for this install
    but this session has not unlocked it yet."* This is the restart edge case: locked again
    until the passphrase is entered. There is no Unlock button here. That is #784.

12. Click **Library**, then **Add a source**, then **Choose a folder**. Add the `locked` folder
    the same way as step 7: its parent is `/tmp/askwell-test-205`. ☐

    **You should see:** the **Queued** note. Within a few seconds the queue line under it
    reads:

    > *1 file is waiting for your passphrase. Unlock Askwell in Settings and indexing carries
    > on by itself.*

    Before this fix, this line named a stage or said nothing useful, and the file eventually
    failed.

13. Wait **two full minutes**, then click **Library**. ☐

    **You should see:** `store_hours_2026.pdf` still **Queued**, **not** **Needs attention**. A
    locked file must wait, however long you leave it.

**Stand-in:** check that the file is parked for the passphrase and has used no attempt:

```
scripts/dev.sh psql -c "SELECT d.filename, j.state, j.awaiting, j.attempts FROM ingest_jobs j JOIN documents d ON d.id = j.document_id WHERE d.filename = 'store_hours_2026.pdf';"
```

**You should see:** `store_hours_2026.pdf | parked | unlock | 0`.

---

## Part E — a wrong passphrase unlocks nothing

14. Click **Settings**. Scroll to the heading **Online AI**. Under **Your key**, click **Add a
    key**. ☐

    **You should see:** *"Your passphrase is needed first. The key is encrypted with it, like
    everything else you have protected, and Askwell cannot encrypt a new key until you enter
    it."*, a **Passphrase** box, and **Unlock** and **Cancel** buttons. You are not adding an
    online AI key. This is only the one place the interface asks for the passphrase.

15. Type `violet harbour lantern ninetyone` (wrong on purpose) and click **Unlock**. ☐

    **You should see:** the button reads **Unlocking…**, then a red line: *"Incorrect
    passphrase."* The passphrase box stays.

16. Click **Library**, then open the `store_hours_2026.pdf` source. Wait 30 seconds and look
    again. ☐

    **You should see:** still **Queued**. Nothing was decrypted and nothing moved.

**Stand-in:**

```
podman compose logs --since 3m worker 2>&1 | grep -E "passphrase_unlocked_by_api|ingest_revived_after_unlock"
```

**You should see:** no output. The indexer was never handed a key.

---

## Part F — the right passphrase: the waiting file carries on by itself

17. Click **Settings**, scroll to **Online AI**, and click **Add a key** again. Type
    `violet harbour lantern ninety` and click **Unlock**. ☐

    **You should see:** the passphrase prompt replaced by the key form (provider, model, key
    fields). Click **Cancel**. You do not need to add a key.

18. Scroll to **Privacy and security**. ☐

    **You should see:** the **Passphrase** block may **still** say *"…has not unlocked it
    yet"*. It reads the status once, when the page opens, and does not refresh. Reload the tab
    and scroll back down.

    **After reloading, you should see:** *"On. The library and stored credentials are
    encrypted with it."*

19. Click **Library**. Do not add anything or press any button. Wait up to two minutes. ☐

    **You should see:** `store_hours_2026.pdf` moves from **Queued** through **Indexing** to
    **Ready** on its own. It is not **Needs attention**.

20. Click **Ask**. Type `What time do Meridian Loom retail stores close on weekdays?` and
    press Enter. ☐

    **You should see:** an answer saying **9 PM**, cited to `store_hours_2026.pdf`, page 1.

**Stand-in:**

```
podman compose logs --since 5m api worker 2>&1 | grep -E "worker_unlocked|passphrase_unlocked_by_api|ingest_revived_after_unlock"
```

**You should see:** all three names, in that order. `ingest_revived_after_unlock` shows
`documents=1`.

---

## Part G — the indexer restarts on its own: no need to type the passphrase again

A background process crashing is not the person locking Askwell. The indexer should be unlocked
again within about 5 seconds, without asking.

21. In the first terminal:

    ```
    podman compose restart worker
    ```

    Wait 20 seconds. Do **not** reload the browser. ☐

22. Click **Library**, then **Add a source**, and add the `worker-restart` folder the same way
    as step 7. ☐

    **You should see:** the **Queued** note and a queue line about indexing `handbook_b.pdf`.
    It must **not** say it is waiting for your passphrase.

23. Wait up to two minutes, then click **Library**. ☐

    **You should see:** `handbook_b.pdf` **Ready**.

**Stand-in:**

```
podman compose logs --since 3m worker 2>&1 | grep -E "worker_unlock_listening|passphrase_unlocked_by_api"
```

**You should see:** `worker_unlock_listening` first, then `passphrase_unlocked_by_api` a few
seconds later.

---

## Part H — the API restarts on its own: locked again

The API holds nothing after a restart. The indexer must be locked too, even though it did not
restart.

24. In the first terminal:

    ```
    podman compose restart api
    ```

    Wait 20 seconds, then reload the tab. ☐

25. Click **Settings** and scroll to **Privacy and security**. ☐

    **You should see:** *"A passphrase is set for this install but this session has not
    unlocked it yet."*

26. Click **Library**, **Add a source**, and add the `api-restart` folder the same way as step
    7. ☐

    **You should see:** *"1 file is waiting for your passphrase. Unlock Askwell in Settings and
    indexing carries on by itself."* If `spec.docx` indexes instead, the indexer kept a key the
    API no longer holds. That would be a real defect: report it.

27. Unlock again as in step 17 (**Settings → Online AI → Add a key**, the right passphrase,
    **Unlock**, then **Cancel**). Then click **Library** and wait up to two minutes. ☐

    **You should see:** `spec.docx` reaches **Ready** on its own.

**Stand-in:** check that the indexer was locked, and that the passphrase appears in no log:

```
podman compose logs worker 2>&1 | grep worker_locked_by_api
podman compose logs api worker 2>&1 | grep -c "violet harbour"
podman compose logs api worker 2>&1 | grep -cE "gAAAAA[A-Za-z0-9_-]{20,}"
```

**You should see:** at least one `worker_locked_by_api` line, then `0`, then `0`. The second
command searches for the passphrase, and the third for anything that looks like an encrypted
token. If either count is above zero, stop and report it: the passphrase or key material has
reached a log (C8).

---

## Part I — put the machine back

28. Click **Settings**, scroll to **Privacy and security**, and click **Remove passphrase**.
    Type `violet harbour lantern ninety` into **Current passphrase** and confirm. ☐

    **You should see:** the warning that removing it makes a stolen laptop a data breach
    again. Then the block reads *"Off. A stolen laptop is readable as-is…"*.

29. Click **Library** and delete the four test sources. In the first terminal:

    ```
    rm -rf /tmp/askwell-test-205
    ```

    ☐

---

## Known gaps

None of these are defects of this ticket. Do not report them against `M9-FIX-BE-205`.

- **There is no Unlock button in Settings → Privacy and security.** The new queue sentence
  sends people to Settings, but the only field that takes the passphrase is inside **Online AI
  → Your key → Add a key** (steps 14 and 17). Filed as #784.
- **Nothing prompts for the passphrase after a restart.** `docs/states-and-edge-cases.md` asks
  for a prompt *"before anything decrypts"*. Today Askwell stays locked, which is correct, but
  says so only in Settings and in the queue line. It is part of #784.
- **The Passphrase block does not refresh after unlocking elsewhere** (step 18). It reads the
  status once when Settings opens. It is part of the same surface as #784.
- **The first-run passphrase step says encryption "is not enforced yet".** That was true
  before `M7-SEC-BE-152` and is not true now. Choosing **Set a passphrase** there only records
  a preference; the real one is set in Settings. This walkthrough avoids it in step 2.
- **Asking a question while locked** fails with a generic error instead of saying Askwell is
  locked. Already noted in `docs/manual-tests/M7-SEC-BE-152.md`, *Known gaps*. Not this
  ticket.
- **Live database connections.** The same fix should make a connection's background re-check
  and health check work again once unlocked (#504), but nobody has tried it with a live
  connection. #504 stays open until someone does. This walkthrough does not add a connection.
- **After a worker restart, allow up to 5 seconds.** A file added in the first 5 seconds after
  the indexer restarts on its own can briefly show *"waiting for your passphrase"*. It carries
  on by itself at the next sync (`ASKWELL_WORKER_UNLOCK_SYNC_SECONDS`). That is by design, not
  a stuck file. It is a stuck file if it still waits after a minute while Askwell is unlocked.
- **A restore from a passphrase-protected backup** takes its passphrase through a separate path
  (`askwell.restore`), which this ticket did not change and this walkthrough does not exercise.
