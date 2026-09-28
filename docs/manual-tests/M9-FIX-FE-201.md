# Manual test — M9-FIX-FE-201, Add a source is reachable after the first one

**Ticket:** `M9-FIX-FE-201`, issue #712. Before this change, once anything had been added,
no button or link opened the **Add a source** screen. The Library showed **Add a source**
only while it was empty. The welcome screen told people to open it "from the rail", and the
rail has no such item. The only ways to add a second source were dragging files onto the
window, or asking a question Askwell could not answer and using the offer under that answer.
A database connection has no file to drag, so it could not be reached on purpose.

Now a populated Library has **Add a source** in its header, top right, beside the word
**Library**. The welcome screen says to open **Library** in the rail and choose **Add a
source**.

**Version under test:** `0.7.49`. Run `cat VERSION` and update this line if the version has
moved on.

**Time:** about 35 minutes. Most of it is waiting for two small files to index.

**Who can run it:** anyone with a browser and a terminal. Every Askwell screen is reached by
clicking, starting from the address Askwell opens at. The terminal only starts Askwell and
runs the automated checks. Those steps are labelled **Stand-in**.

**What is being checked.**

- `web/components/library/library-screen.tsx`: `AddSourceLink`, shown in the header whenever
  the library lists at least one source, and still inside the empty library's invitation.
- `web/components/welcome/welcome-screen.tsx`: step 4's sentence when nothing has been added.
- Unchanged, re-walked because the new route depends on them: the rail
  (`web/components/shell/rail.tsx`) and the narrow-window drawer
  (`web/components/shell/rail-drawer.tsx`, `M7-FIX-FE-173`).

**The one rule of this test.** Never type an address into the browser bar except the first
one in step 1 and step 17. If you can only reach a screen by typing its address, that is the
defect this ticket exists to fix. Record it.

---

## Before you start

> **Warning: the cold start below deletes everything this Askwell stack holds.** That means
> sources, memory, conversations, the audit log and settings. Your original files are not
> touched. On the shared development machine, check that nobody needs what the stack holds
> now. If you are unsure, use **Settings → Your data → Export everything** first.

### A. Two folders to add

Askwell can only read folders inside `ASKWELL_ROOTS_MOUNT` in `.env`. Check it:

```
cd ~/external/quantum-plus/askwell
grep ASKWELL_ROOTS_MOUNT .env
```

If it is empty, or does not cover `/tmp`, set `ASKWELL_ROOTS_MOUNT=/tmp`. Then make two
folders, each holding one file from the fixture corpus:

```
rm -rf /tmp/askwell-test-201
mkdir -p /tmp/askwell-test-201/first-folder/handbooks /tmp/askwell-test-201/second-folder/store-hours
cp eval/fixtures/corpus/handbook_a.pdf /tmp/askwell-test-201/first-folder/handbooks/
cp eval/fixtures/corpus/store_hours_2026.pdf /tmp/askwell-test-201/second-folder/store-hours/
find /tmp/askwell-test-201 -type f
```

**You should see:** two lines, one ending `handbooks/handbook_a.pdf` and one ending
`store-hours/store_hours_2026.pdf`.

The two folders sit under **different** parents on purpose. Askwell keeps one source per
folder, and a folder you add again is added to the source it already has. Two folders under
one parent would give one Library row, not two, and the test would prove nothing.

### B. Start Askwell from nothing

```
podman compose down -v
scripts/dev.sh web-build
scripts/dev.sh build-api
podman compose up -d
scripts/dev.sh db upgrade head
```

**You should see:** the volumes removed, both builds finish with no red error text, the
containers start, and the migration finish with no error. Do not skip either build. The
interface is built into `web/out` and served from the API image. Without both builds you
will be testing the old screens.

In a **second** terminal, start the model on the host and leave it running:

```
scripts/dev.sh inference
```

**You should see:** the supervisor report that the model and the embedding model are ready.
Welcome step 3 will not let you continue until the model is ready, so do not skip this.

---

## Part A — first run, nothing added yet

This is the ticket's first edge case: with no sources at all, the first-run path must still
work, and the welcome sentence must name a place that exists.

1. Open a **private or fresh-profile** browser window at full width, so no earlier session
   carries over. Go to `http://127.0.0.1:8000`. ☐

   **You should see:** **Welcome to Askwell**, with *"A personal AI over your own files, on
   this machine."* under it, a **Skip setup** button top right, and a **Get started** button.
   Down the left, a column listing **Ask, Library, Clarifications, Memory, Settings**. There
   is **no Add a source** in that column. That is by design (see *Known gaps*). If you see
   the Ask screen instead of the welcome screen, the stack was not cleared. Go back to
   *Before you start*, B.

2. Click **Get started**. ☐

   **You should see:** step 2, about checking this machine and an optional passphrase.

3. Click **Not now** for the passphrase, then **Continue**. ☐

   **You should see:** step 3, about the model, with an add box below it showing **Choose
   files** and **Choose a folder**, and a line saying *"You do not have to wait — add sources
   now and they will be ready as soon as the model is."*

4. **Do not add anything yet.** Wait until the model section says the model is ready, then
   click **Continue** at the bottom. ☐

   **You should see:** step 4, reading exactly:

   *"Ready. Add something to ask about — the previous step's add box is still open above, or
   open `Library` in the rail and choose `Add a source` any time."*

   If it still says *"… any time from the rail"*, the new interface was not built or not
   served. Stop and repeat *Before you start*, B.

5. Do what that sentence says. Click **Library** in the left column. ☐

   **You should see:** the Library screen, headed **Library**, with *"Every source you have
   added, and what state it is in."* under it. Below that, a panel beginning *"A source is
   anything Askwell can read and answer questions about …"*, a list of four ways to add one,
   and an **Add a source** button at the bottom of that panel.

   There is **no** Add a source button top right beside the heading. With nothing added, the
   button belongs in the panel, and one button is enough.

   Write down whether the first click on **Library** worked or whether you had to click
   twice. A second click being needed is issue #665, not this ticket. Add a comment there
   with your browser and version.

6. Click **Add a source** in that panel. ☐

   **You should see:** a screen headed **Add a source**, with *"Nothing added on this machine
   yet · these counts are local and go nowhere"* under it. Below that, a paragraph beginning
   **"Askwell indexes your files where they are."**, then three panels: **Files** (with
   **Choose files** and **Choose a folder**), **Database dump**, and **Connect a database**.

   Part A passes: with nothing added, first run still reaches the add screen by clicking.

---

## Part B — add the first folder

7. On the **Add a source** screen, in the **Files** panel, click **Choose a folder**. In the
   browser's folder picker, open `/tmp/askwell-test-201/first-folder`, select the
   `handbooks` folder and confirm. If the browser asks whether to upload the files, confirm.
   The browser uses that word, but nothing is sent anywhere. Askwell reads only the file
   names and the first few kilobytes of each file, on this machine. ☐

   **You should see:** a box asking *"Which folder is “handbooks” in?"*, with a text field
   and an **Add them** button.

8. Type `/tmp/askwell-test-201/first-folder` and click **Add them**. If a note offers
   **Nominate** with a folder path, click it, then click **Add them** again. ☐

   **You should see:** a note headed **Queued**. No red note headed **Not added**.

9. Click **Library** in the left column. ☐

   **You should see:** one row, named **first-folder**, with **Files** and **Added …** under
   it and a status word on the right. Wait until the status reads **Ready**. On a CPU-only
   machine this can take a minute or two.

   Now look top right, beside the **Library** heading. **You should see:** an **Add a
   source** button. This is the change under test. Before `0.7.49` it was not there.

10. Above the row, find the filters. Tick **Has open clarifications**. ☐

    **You should see:** *"No sources match these filters."* in place of the row, and the
    **Add a source** button **still there** top right. Filtering the list must never hide
    the way to add. Untick the box afterwards.

    If the row stays, check whether it says *"· 1 open clarification"* (or more) under its
    name. If it does, the filter is working as intended and this step cannot empty the
    list. Mark it not applicable. The **Status** and **Kind** filters cannot be used here
    instead: they only list the values the library actually holds.

---

## Part C — from the landing page, add a second folder by clicking only

This is the ticket's acceptance criterion and its cold-start scenario.

11. Close the browser tab. Open a new tab in the same private window and go to
    `http://127.0.0.1:8000`. ☐

    **You should see:** the **Ask** screen. It does **not** go back to the welcome screen,
    because something is now indexed. The composer at the bottom reads **Ask about your own
    files and databases**.

    There is no **Add a source** link on this screen now that something has been added. That
    is by design: the Ask screen offers it only while nothing has been added (see *Known
    gaps*).

12. Click **Library** in the left column. ☐

    **You should see:** the **first-folder** row, **Ready**, and **Add a source** top right.

13. Click **Add a source** top right. ☐

    **You should see:** the **Add a source** screen from step 6. The small text under the
    heading now counts what has been added, for example *"1 file added on this machine"*.
    The **Library** item in the left column is **not** highlighted any more. The new screen
    is its own place.

14. Click **Choose a folder**. Open `/tmp/askwell-test-201/second-folder`, select
    `store-hours` and confirm. When asked *"Which folder is “store-hours” in?"*, type
    `/tmp/askwell-test-201/second-folder` and click **Add them**. If a note offers
    **Nominate**, click it, then **Add them** again. ☐

    **You should see:** a note headed **Queued**.

15. Click **Library** in the left column. ☐

    **You should see:** **two** rows, **first-folder** and **second-folder**. Wait until both
    read **Ready**. **Add a source** is still top right.

16. Click **Ask** in the left column. Type
    `What time do Meridian Loom retail stores close on weekdays?` and press **Enter**. Wait
    for the answer. On CPU this can take a minute or two. ☐

    **You should see:** an answer saying 9 PM, with a source card naming
    `store_hours_2026.pdf`, page 1. This proves the second source is not just listed but
    searchable. That file is a single sentence, so page 1 is the only page it can cite.

Part C passes if you never typed an address after step 11.

---

## Part D — a narrow window

The ticket's second edge case: in a narrow window, the rail is a drawer, and Add a source
must still be reachable through it.

**Setting the width.** Most desktop browsers will not let a window get narrower than about
500px, so 390 cannot be reached by dragging. Open the browser's developer tools (`F12`), turn
on the device toolbar (`Ctrl+Shift+M` in Chrome and Firefox), choose **Responsive**, and type
`390` × `844` into the size boxes. Askwell decides between rail and drawer from the width of
its own window, so this gives the same result as a real 390px window.

17. At **390 × 844**, go to `http://127.0.0.1:8000` again. ☐

    **You should see:** the **Ask** screen in one column. **No** left column. In the
    top-left corner, a small button drawn as three short lines.

18. Click the three-line button. ☐

    **You should see:** the rail slides over the content, listing **Ask, Library,
    Clarifications, Memory, Settings**, with its own close control in the same corner.

19. Click **Library** in the drawer. ☐

    **You should see:** the drawer closes by itself and the Library screen shows, with the
    two rows. **Add a source** is visible without scrolling sideways. At this width it may
    sit **below** the heading and its one-line description instead of beside them. That is
    correct. It must not be cut off at the right edge, and it must not overlap the heading.

20. Click **Add a source**. ☐

    **You should see:** the **Add a source** screen, with **Choose files** and **Choose a
    folder** reachable without scrolling sideways.

21. Set the width to **768 × 1024** and click **Library** in the left column. It is a column
    again at this width. ☐

    **You should see:** **Add a source** top right, beside the heading, not wrapped.

22. Turn off the device toolbar and close the developer tools. ☐

---

## Part E — every screen the copy names is reachable

`docs/manual-tests/master-sheet.md` Part A, row A13, re-walked because this ticket changes
what a click in the Library leads to.

23. At full width, click each item in the left column once: **Ask**, **Library**,
    **Clarifications**, **Memory**, **Settings**. ☐

    **You should see:** each one opens its screen, with the clicked item highlighted by a
    coloured bar on its left edge. None of them does nothing, and none shows a "not found"
    page.

24. From **Library**, click **Add a source**, then click **Library** in the left column to go
    back. ☐

    **You should see:** the Library with both rows, exactly as you left it.

---

## Part F — the automated checks

25. **Stand-in** — the web checks: ☐

    ```
    scripts/dev.sh web-check
    ```

    **You should see:** every stage finish with no failures. `web/lib/library.test.ts`
    includes five checks for this ticket:

    - the **Add a source** link goes to the add screen, and that screen exists;
    - a populated library carries it in the header, outside the list, so a filter cannot
      hide it;
    - the empty library still offers it;
    - **Library** is in the rail, and the narrow-window drawer is the same rail;
    - the welcome sentence no longer says *"from the rail"*, and names Library instead.

    These read the components' source code rather than rendering them. This suite has no
    component renderer. Parts A–E are what prove the screens behave.

---

## Teardown

```
podman compose exec api askwell-verify
podman compose down -v
rm -rf /tmp/askwell-test-201
```

**You should see:** both audit chains reported intact before the wipe. Stop the inference
process in the second terminal with `Ctrl+C`.

---

## Known gaps

These are deliberate or belong to other issues. Do not report them as defects of this
ticket.

- **The rail has no Add a source item.** Adding a sixth destination to the rail is a design
  change, and #712 rejected it. The route is **Library → Add a source**, which is what
  `docs/ux/add-source.md` and `docs/ux/library.md` already describe.
- **The Ask screen offers Add a source only while nothing has been added.** Once something is
  indexed, Ask shows the composer and suggested questions. It also offers **Add a source**
  under an answer where Askwell found nothing, so the user can add what the question needed.
  That offer is a response to a missing answer, not a way to reach the add screen, and the
  release walkthrough does not count it as one.
- **The empty Library calls database dumps and live connections "arriving later"** (step 5),
  although the **Add a source** screen (step 6) offers both. That is #722.
- **On the Add a source screen, Spreadsheet or CSV is still marked "Arrives in M4"** under
  *The other route*. That is the add screen's own state and is unchanged here.
- **While the Library is loading, or when Askwell is not answering, there is no Add a source
  button.** It shows only once the library is known to hold something. Otherwise the empty
  library's own button would appear alongside it. The loading state lasts a fraction of a
  second, and the failure state cannot be produced here without stopping the server that
  serves the page itself.
- **Welcome step 4's sentence appears only when the model is ready and nothing has been
  added.** When something was added in step 3, step 4 offers a question instead. That is why
  step 4 of this test adds nothing first.
- **A folder chosen in the browser is recorded under the folder you type, not the one you
  picked.** That is why the Library rows are **first-folder** and **second-folder**, not
  **handbooks** and **store-hours**. The desktop application has a real folder dialog and
  does not ask. If a row shows a different name, write it down, but it is not this ticket's
  defect.
- **The first click on a rail item sometimes does nothing** (#665). Record it there.
- **Dragging files onto the window still works** and is not re-tested here. `M1-ADD-FE-022`
  covers it.
