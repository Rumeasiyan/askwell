# Manual test — M1-ADD-ING-021, nominating folders Askwell may read

**Ticket:** `M1-ADD-ING-021` — nominate root directories as known mounts at add time
**Version under test:** `0.2.2`
**Time:** about 35 minutes, plus a first stack build
**Who can run it:** anyone who can copy and paste a line into a terminal. Everything after step 6 is clicking and typing in a browser.

**What is being checked.** Askwell reads your files where they are and never copies them. That means it has to be told which folders it may open. This walkthrough nominates a folder, watches Askwell accept it, watches it refuse the folders it should refuse, and removes one to confirm that removing a folder from Askwell does not delete anything.

**The one thing to watch for throughout.** Nothing in this test should ever delete, move, or modify a file of yours. If at any point a file or folder you created disappears from your file manager, stop and record it — that is the most serious defect this feature could have.

---

## Before you start

You need a terminal, and Podman installed. You do not need Python, Node, or anything else.

### 1. Make a folder to test with

Paste this into the terminal, one block, and press Enter:

```
mkdir -p ~/askwell-test/clients/acme ~/askwell-test/clients-archive ~/askwell-test/elsewhere
echo "hello" > ~/askwell-test/clients/acme/note.txt
echo "hello" > ~/askwell-test/elsewhere/other.txt
```

**You should see:** no output at all. Silence is success for these commands.

Open your file manager and confirm `askwell-test` now exists in your home folder, containing `clients`, `clients-archive` and `elsewhere`. Keep the file manager open — you will come back to it to prove nothing was deleted.

### 2. Point Askwell at that folder

Go to the Askwell folder in the terminal:

```
cd ~/external/quantum-plus/askwell
```

If you have never run Askwell before, create its settings file:

```
cp -n .env.example .env
```

Now open `.env` in any text editor. Find the line that reads:

```
ASKWELL_ROOTS_MOUNT=
```

Change it to — replacing `you` with your own username:

```
ASKWELL_ROOTS_MOUNT=/home/you/askwell-test
```

**You should see:** in the same file, just above that line, a comment explaining that this is one narrow route to your files rather than open filesystem access, and that a folder outside it can still be nominated but needs the stack brought up again.

The same file needs a database password if you have never set one. Find `POSTGRES_APP_PASSWORD` and put any word after the `=`.

> **Why this step is manual.** This is the "known mount". Askwell's containers cannot see any part of your disk they have not been given, and a container's mounts cannot be changed while it is running. Step 15 tests what happens when you nominate a folder outside this window.

---

## Cold start

### 3. Start Askwell from nothing

To be sure this is a genuine cold start, remove any previous state:

```
podman compose down -v
```

**You should see:** lines about containers and volumes being removed, or a note that there is nothing to remove. Either is fine.

### 4. Build the interface

```
scripts/dev.sh web-build
```

**You should see:** a Next.js build finishing with a route list, and no red error text. This takes a few minutes the first time.

### 5. Bring the stack up

```
podman compose up -d
```

**You should see:** four services reported as started or healthy — `postgres`, `redis`, `egress-proxy`, `api`, plus `worker`. Wait about thirty seconds after the command returns.

### 6. Create the database tables

```
scripts/dev.sh db upgrade head
```

**You should see:** a line mentioning `b1f4c7d2a913` and `roots`. That is the table that stores which folders you have nominated. If you do not see any migration lines, the database was already up to date from a previous run — go back to step 3 and do the `down -v` properly.

---

## Walk the screen

### 7. Open Askwell

In a browser, go to:

```
http://127.0.0.1:8000
```

**You should see:** a page headed **"Ask your own material"**, with the version `0.2.2` under it and the words "nothing leaves this machine". Below that, a panel headed **"Nothing added yet"**.

This is the first-run state. There is no wizard — Askwell opens on Ask.

### 8. Find the folder list by clicking, not by typing an address

On the left is a vertical strip with four entries: **Ask**, **Library**, **Memory**, **Settings**.

Hover over **Settings**.

**You should see:** a tooltip reading "Folders Askwell may read, profile, retention, network activity".

Click **Settings**.

**You should see:** the page changes to one headed **Settings**, and the **Settings** entry in the left strip is now highlighted with a coloured bar down its left edge.

### 9. Read the empty state

Scroll down the Settings page.

**You should see**, in order:

- A heading **"Folders Askwell may read"**.
- A sentence: "Askwell reads your files where they are and never copies them, so it has to be told which folders it may open. It can read anything inside a folder you nominate, and nothing outside one."
- A panel headed **"No folders yet"** saying "Nominate the folder your material lives in. Askwell will index what is inside it where it is — nothing is moved, copied or uploaded."
- A field labelled **"Nominate a folder"** with the placeholder text `/home/you/clients`, and a **Nominate** button beside it.
- Under the field, small text: "Type the whole path. Choosing a folder from a system dialog arrives with the desktop application."

The **Nominate** button should be greyed out while the field is empty. Click it and confirm nothing happens.

---

## Nominate a folder

### 10. Nominate the test folder

In the **Nominate a folder** field, type — with your own username:

```
/home/you/askwell-test/clients
```

The **Nominate** button becomes usable as soon as you type. Click it.

**You should see:** the field empties, and a new box appears above the field showing:

- the path `/home/you/askwell-test/clients` on the left,
- the word **Readable** on the right, in grey,
- a **Remove** button underneath.

The "No folders yet" panel is gone.

**You should not see:** any warning, any error, or any coloured alarm text.

### 11. Confirm it survives a reload

Press F5, or reload the browser page.

**You should see:** the Settings page again — you may briefly see "Reading the list…" — and then the same `/home/you/askwell-test/clients` box, still marked **Readable**.

If the folder is gone after a reload, that is a defect: nomination is not being stored.

### 12. Confirm a nested folder is recognised, not registered twice

In the field, type:

```
/home/you/askwell-test/clients/acme
```

Click **Nominate**.

**You should see:** the field empties, and the list still shows **exactly one** folder — `/home/you/askwell-test/clients`. No second box appears, and no error appears.

This is correct. `acme` is already inside a folder you nominated, so Askwell already has permission to read it. Nominating it again buys nothing and Askwell does not pretend otherwise.

### 13. Confirm a similarly-named sibling is *not* covered

This is the check that catches the most dangerous kind of bug — Askwell believing it has permission to a folder you never gave it.

Type:

```
/home/you/askwell-test/clients-archive
```

Click **Nominate**.

**You should see:** a **second** box appear, showing `/home/you/askwell-test/clients-archive`, marked **Readable**.

Two boxes now. That is correct: `clients-archive` is a different folder from `clients`, and it needed nominating separately even though its name starts the same way.

Remove it again before continuing — click its **Remove** button, then **Remove it** on the confirmation that appears. Step 21 covers what that confirmation should say; for now just note the list returns to one folder plus a "Removed" note at the bottom.

---

## What Askwell refuses, and how it says so

Each of these should produce a plain sentence a person can act on. Record the exact wording if any of them produces a bare error code, a stack trace, or the word "Unprocessable".

### 14. A folder that is not there

Type:

```
/home/you/askwell-test/no-such-folder
```

Click **Nominate**.

**You should see:** a red-marked panel headed **"That folder was not accepted"**, reading: "This folder is not there at the moment. If it is on a drive or a share, reconnect it — nothing has been deleted and nothing needs re-indexing."

The folder list is unchanged — still one entry.

### 15. A file, not a folder

Type:

```
/home/you/askwell-test/clients/acme/note.txt
```

Click **Nominate**.

**You should see:** **"That folder was not accepted"** — "This is a file, not a folder."

### 16. The whole disk

Type a single slash:

```
/
```

Click **Nominate**.

**You should see:** **"That folder was not accepted"** — "Nominating / would give Askwell your whole disk, which is the thing nominating a folder exists to avoid. Name the folder your material is actually in."

This is the most important refusal on the screen. If `/` is ever accepted, stop the test and report it.

### 17. A path that is not a whole path

Type:

```
Documents/cases
```

Click **Nominate**.

**You should see:** **"That folder was not accepted"** — a message explaining Askwell needs the whole path starting with a slash, because Askwell and your file manager do not share a current directory.

### 18. A folder outside the window — accepted, with the fix stated

This one is deliberately *not* refused.

Type a real folder of yours that is **outside** `~/askwell-test` — for example:

```
/home/you/Documents
```

Click **Nominate**.

**You should see:** a new box appear in the list showing `/home/you/Documents`, marked **Needs a restart** in an amber/inferred colour rather than red, with a sentence underneath along the lines of: "This folder is outside /home/you/askwell-test, which is the only part of your filesystem the containers can see. Widen ASKWELL_ROOTS_MOUNT in .env to a folder containing both, then run `podman compose up -d` again — a container's mounts cannot be changed while it runs."

**Why it is accepted and not refused:** on a fresh install nothing at all is inside the window, so refusing here would make it impossible to nominate anything. The problem is one configuration line, and Askwell says which line rather than letting you discover it later.

Remove `/home/you/Documents` again before continuing (**Remove**, then **Remove it**).

---

## A folder that stops being there

This simulates a USB drive being unplugged, without needing a USB drive.

### 19. Make a nominated folder disappear, then come back

In the terminal:

```
mv ~/askwell-test/clients ~/askwell-test/clients-moved
```

Go back to the browser and reload the Settings page.

**You should see:** the `/home/you/askwell-test/clients` box now marked **Not connected** — not red, not "deleted", not "missing" — with the sentence "This folder is not there at the moment. If it is on a drive or a share, reconnect it — nothing has been deleted and nothing needs re-indexing."

Check your file manager. `clients-moved` is there with `acme/note.txt` inside it, untouched.

Now put it back:

```
mv ~/askwell-test/clients-moved ~/askwell-test/clients
```

Reload the page.

**You should see:** the same box back to **Readable**, with no sentence underneath. Nothing had to be re-nominated and nothing had to be re-indexed.

### 20. A folder Askwell is not allowed to read

In the terminal:

```
mkdir -p ~/askwell-test/locked && chmod 000 ~/askwell-test/locked
```

In the browser, type `/home/you/askwell-test/locked` and click **Nominate**.

**You should see:** **"That folder was not accepted"** — "Askwell is not allowed to read this folder. Check its permissions — and on a machine with SELinux, that the bind mount is labelled so a container may traverse it."

The list is unchanged.

Clean up:

```
chmod 755 ~/askwell-test/locked && rmdir ~/askwell-test/locked
```

> **If instead every folder in this test showed "Not permitted" from step 10 onward**, including ones you can plainly read yourself, that is the known SELinux question recorded in `docs/BRAIN.md` — the mount is bind-mounted without relabelling, and a Fedora host may refuse the containers traversal. Record it against that open item rather than as a new defect.

---

## Removing a folder

### 21. Ask what removal costs

The list should currently hold one folder: `/home/you/askwell-test/clients`, **Readable**.

Click its **Remove** button.

**You should see:** the button is replaced by a sentence and two buttons, **Remove it** (outlined in red) and **Keep it**. Because no sources have been added yet, the sentence should read close to:

> "Askwell will stop reading anything under /home/you/askwell-test/clients. No source is using this folder yet, and nothing is deleted — not the folder, and not your files, which Askwell never held a copy of."

**The words that must be present are "nothing is deleted".** If that phrase is absent from this confirmation, record it — it is the point of the whole screen.

### 22. Change your mind

Click **Keep it**.

**You should see:** the confirmation disappears, the plain **Remove** button returns, and the folder is still listed as **Readable**.

### 23. Remove it for real

Click **Remove**, then **Remove it**.

**You should see:**

- the folder box disappears from the list,
- the **"No folders yet"** panel returns,
- and at the bottom of the section a panel headed **"Removed"** listing `/home/you/askwell-test/clients` with: "Nothing under these was deleted — nominate one again to make its sources readable."

### 24. Confirm nothing was deleted

Switch to your file manager and open `~/askwell-test/clients/acme`.

**You should see:** `note.txt`, still there, still readable. Open it — it says `hello`.

This is the single most important observation in this document. Askwell removing a folder from its own list must never touch your files.

### 25. Nominate it again

In the browser, type `/home/you/askwell-test/clients` and click **Nominate**.

**You should see:** the folder back in the list as **Readable**, and the **"Removed"** panel at the bottom now gone from your view of it, or no longer listing this path.

Removing and re-nominating the same folder is an ordinary thing to do and must not be refused as a duplicate.

---

## When Askwell is not answering

### 26. Stop the API and reload

In the terminal:

```
podman compose stop api
```

In the browser, reload the Settings page.

**You should see:** the page either fails to load entirely (the API is what serves it) or, if it was cached, shows a red-marked panel headed **"Askwell is not answering"**.

**You should not see:** an empty folder list presented as fact. "You have nominated nothing" and "I cannot reach Askwell" are different statements and the screen must not substitute one for the other.

Start it again:

```
podman compose start api
```

Reload. The folder list returns.

---

## Tidy up

```
rm -rf ~/askwell-test
podman compose down -v
```

Then remove or blank the `ASKWELL_ROOTS_MOUNT=` line you set in `.env` if you do not want to keep it.

---

## Known gaps

These are deliberately not built. Do not report them as defects.

1. **There is no add-source screen.** The ticket's own walkthrough describes dragging a file in and being prompted to nominate its folder. That screen does not exist yet — `web/app/library/page.tsx` is still a placeholder saying adding a source arrives in M1. Nominating is reachable only from **Settings → Folders Askwell may read**, which is why this document walks that path. The add-source screen is `M1-ADD-FE-022`.

2. **The "this file is outside every nominated folder" prompt cannot be seen by clicking.** The wording and the suggested folder are built and covered by tests, but no screen calls for them yet — it becomes visible when `M1-ADD-FE-022` lands. Steps 14–18 test the refusals that *are* reachable.

3. **No system folder picker.** A browser cannot open a directory dialog, so paths are typed. The screen says so under the field. The picker arrives with the desktop application (`M7-TAURI-FE-182`) and replaces the typing step alone — nothing else in this walkthrough changes when it does.

4. **Nominating a folder outside `ASKWELL_ROOTS_MOUNT` needs the stack brought up again** (step 18). A container's mounts cannot be changed while it runs. Askwell states this at the moment of nomination rather than letting it be discovered later, which is the requirement; the restart itself is the gap.

5. **No folder watching.** Nothing re-indexes when a file inside a nominated folder changes. Deliberately out of v1 — see `docs/ux/add-source.md` §6.

6. **No sources exist yet, so removal always reports zero affected sources** (step 21). The wording for one or more affected sources is written and tested but cannot be produced by clicking until sources can be added.

7. **The network-share warning is not exercised here** — it needs an NFS or SMB mount. There is also a recorded problem with it firing at all in the ordinary first-run sequence (a folder nominated before the mount exists records the wrong filesystem); see the open items in `docs/BRAIN.md`.

8. **A folder reached through a symbolic link** can be nominated but files under it will not be readable once ingestion exists. Recorded as an open item in `docs/BRAIN.md`. Avoid symlinked paths in this test.

9. **SELinux behaviour of the mount is unverified** (note after step 20). If every folder reports **Not permitted**, that is the open item, not a new finding.
