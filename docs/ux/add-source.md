# Screen: Add source

Four ways material gets in. Specified in `../data-sources.md`; this is what the user sees.

> **This document is the specification. Any mockup is a reference.**

**Route:** `/sources/add`
**Entry points:** library, first run, empty states, drag-and-drop anywhere in the app.
**Phase:** 1 (files, CSV) · 3 (dumps, connections)

---

## 1. Shape

One screen, four routes, chosen by what the user has:

| Route | For |
| ----- | --- |
| **Files** | PDF, Word, Excel, PowerPoint, text, images. Drag or browse |
| **Spreadsheet or CSV** | Tabular exports |
| **Database dump** | `.sql`, `.dump`, `.backup` — PostgreSQL only in v1 |
| **Connect a database** | PostgreSQL, MySQL/MariaDB, SQL Server |

Drag-and-drop is the primary path and works anywhere in the app, not just here. Askwell picks the route from the file type; the user should rarely need to choose.

**The type comes from the file's contents, not its name.** The first 4 KB decide it; the extension is consulted only to tell the four zipped Office formats apart — they are all a zip and share their first bytes — and to say what the file was *called* when the two disagree. A `.pdf` that is really a PNG is indexed as a PNG and the screen says so, because the user learning that one of their documents is not what its name says is worth more than a silent correction.

**Indexing is in place.** Files are read where they are, not copied into a library. Stated once, because someone about to add 40 GB of case files needs to know before they start, not after.

That promise has a consequence the user meets on their first file: Askwell has to be told which folders it may open. §7 covers it.

---

## 2. Files and CSV

Add → detect → extract → OCR where needed → chunk → embed → index.

- Progress per file. Navigating away does not cancel it; ingestion is a background job.
- **The source becomes askable before ingestion finishes**, with partial coverage shown. Waiting for a 500-file import before allowing a single question is how someone gives up.
- A queue estimate that is honest about CPU embedding taking hours on a large corpus.

CSV additionally raises clarifications for what it cannot infer (`clarifications.md`). Type and header detection are shown for review, not applied silently — **especially date format, which Askwell never guesses** because guessing wrong produces answers that look reasonable and are wrong by up to eleven months.

---

## 3. Database dump — the warning that has to land

A `.sql` dump is a program, not data. Importing runs it (`../data-sources.md` §3).

The screen states this plainly, once, without theatre:

> **This file contains commands, not just data.** Askwell runs it inside a sealed database that cannot reach your other sources, the internet, or Askwell's own files. If the dump is broken or malicious, only that sealed copy is affected.

Not a modal, not a red warning triangle, not a checkbox to accept. A calm statement of what happens. The people who understand the risk will recognise the mitigation; the people who do not are protected anyway, which is the point of the sandbox.

**MySQL or SQL Server dump offered:** refused with both routes out, never a bare rejection —

> Askwell imports PostgreSQL dumps. For MySQL, either connect to the database directly or export the tables as CSV; both work, and CSV usually gives better answers because Askwell will ask about anything ambiguous.

A dead end with no way forward is how someone concludes the product does not handle their data.

---

## 4. Connect a database

Host, port, database, user, password. Then:

1. **Connect.**
2. **Write-permission probe.** If the credentials can write, the connection is **refused**, naming the permission found. Not a warning, not an override. Askwell does not hold credentials that can damage the user's database.
3. Introspect schema, index table and column names.
4. Raise clarifications for unguessable columns.

Copy on refusal:

> These credentials can modify `orders`. Askwell only connects with read-only access. Create a read-only user and try again — here is the SQL for it.

**Give them the SQL.** Telling someone to create a read-only user without showing how is where the flow dies for anyone who is not a DBA — and a large share of this product's users are not.

---

## 5. States

| State | What is shown |
| ----- | ------------- |
| **Idle** | Four routes, drop target, supported formats |
| **Dropped, detecting** | Per-file type detection |
| **Indexing** | Per-file progress, running count, already-askable marker |
| **Partly indexed** | Askable now, with what is still processing |
| **Extraction failed** | Per-file reason and retry. Never silently dropped |
| **Password-protected PDF** | Prompt for the password; not stored unless the user asks |
| **Poor OCR** | Ingested, flagged, clarification raised |
| **Recording** | The count and the folder, with the fact that each file is being read to work out what it is and whether Askwell already has it. Nothing is copied |
| **Duplicate** | Recognised by content hash, linked to the existing source, not re-ingested |
| **The same content under two names** | Both paths named — the one indexed and the one recognised — and the reason recognition is by content rather than by name |
| **An empty file** | Refused by name with the reason. The rest of the drop carries on |
| **A file still being written** | Re-read; if it never settles, named per file with what to do — close it, or wait for whatever is producing it |
| **A drop Askwell already had, all of it** | Said as *nothing new here*, not as "0 files queued". Nothing needed doing, and a count of zero beside the word Queued reads as a failure |
| **New version** | Offered as superseding, not duplicating. Old version stays queryable for history |
| **Unsupported format** | Named per file — the file, then what its contents turned out to be, then why — with the supported list once beneath the block. The rest of the drop carries on |
| **A format arriving in a later milestone** | Named as arriving, with the milestone, in its own block and its own colour. Never listed under "not added", never queued |
| **A drop with no files in it** | Said plainly, with the supported list. An empty folder is a gesture that deserves an answer; a cancelled file dialog is not |
| **Dump too large / too slow** | Aborted at 5 GB or 10 minutes, sandbox dropped, reason given |
| **Connection unreachable** | Distinguish wrong host from wrong credentials from firewall — three different fixes |
| **Write-capable credentials** | Refused, with the SQL to create a read-only user |
| **Disk budget reached** | Refused before starting, with what to free |
| **Detecting** | The count and total size straight away, then per-file type detection with a running "N of M so far". Only the first 4 KB of each file is read, and the screen says so |
| **Named one thing, contains another** | Routed by its contents and the disagreement stated — *named `.pdf`, contents are a PNG image*. Never silently re-routed |
| **A program dropped** | Refused by name — a Linux, macOS or Windows program, or a script — with the fact that nothing was run and nothing was read past its first bytes |
| **An archive dropped** | Refused with what to do instead: unpack it and add the files, so each document keeps its own name in citations |
| **More files than one drop will take** | The first 5,000 are taken and the screen says the rest were left. A cap that truncates without saying so is worse than no cap |
| **A drop while another is being read** | Queued behind it with its own count, never rejected. Detection runs one batch at a time so the window stays responsive |
| **Queued, nothing indexed yet** | Said plainly, with what has to arrive before the files are searchable. Not a progress bar that never moves |
| **The browser will not say where a file is** | One question per drop, not per file: which folder these came from, typed. The desktop shell answers it itself (§7 known gap) |
| **File outside every nominated folder** | The folder to nominate, and why Askwell needs telling. Not a bare rejection (§7) |
| **Folder nominated but not yet mounted** | Accepted, with the line to add and that the stack has to come up again. Said now, not discovered later |
| **Nominated folder not connected** | Its sources report unavailable — a drive unplugged, a share disconnected. **Never** rendered as deleted or as moved |
| **Nominated folder cannot be read** | Named, with permissions and SELinux labelling as the two causes |

---

## 6. Open

1. **Settled: no folder watching in v1.** It is an obvious want and it collides with supersession — a file saved five times in a minute would produce five superseding versions, and deciding when a change has "settled" is a heuristic that gets it wrong on somebody's workflow. v1 re-indexes on an explicit action. Revisit with real usage, once there is evidence about how people actually add material.
2. **Settled: one table per sheet; merged headers raise a clarification** (`../data-sources.md` §7).

---

## 7. Nominating a folder

> Numbered after Open rather than before it because §6 is referenced by number from the backlog and from `../decisions.md`. A renumber would silently redirect those to the wrong paragraph.

Indexing in place means Askwell reads the user's own directories. The API and the worker run in containers, so a nominated folder becomes a **known mount** — one narrow route to that tree — rather than the containers having open filesystem access. That is safer, and it is the only approach that works at all when there is a virtual machine in the path, which there is on macOS and Windows.

### The prompt

Adding a file that lies outside every nominated folder does not fail. It asks:

> **Askwell has not been given this folder yet.**
> Askwell reads your files where they are and never copies them, so it needs to be told which folders it may open. Nominating `/home/anna/clients` lets it read anything inside it, and nothing outside it.

Accept, and the file continues to indexing. A second file from the same folder asks nothing — that is what nominating once buys, and it is the whole point of nominating a tree rather than a file.

### What is refused, and what is not

| Situation | What happens |
| --------- | ------------ |
| A folder that is not there | Refused, naming it. A path that cannot be read now will not start working on its own |
| A file given as a folder | Refused, said plainly |
| A folder Askwell may not read | Refused with the two causes: its permissions, or SELinux labelling on the mount |
| `/` | **Refused.** Nominating the whole disk is the exact thing nominating a folder exists to avoid |
| A folder already inside a nominated one | Recognised, not registered twice. Reported as already covered, because it is — files under it can be added, which is all the user was asking |
| A folder containing ones already nominated | Registered. Both stay: two rules that permit the same path permit it once, and removing one the user chose would be a decision taken on their behalf |
| A folder outside the mount window | **Accepted**, with the configuration line to add and that the stack has to come up again. A container's mounts cannot be changed while it runs, so refusing would make a fresh install unable to nominate anything |
| A network share | **Permitted**, with a warning: indexing will be considerably slower, and the share has to be connected whenever a citation is opened — a source viewer cannot render a page it cannot reach |

### Removing one

Stated before it happens, from a count the API computed rather than one the screen guessed:

> **4 sources under `/home/anna/clients` will stop being readable.** They stay in your library with that reason shown, their answers keep their citations, and nothing is deleted — not the sources and not your files. Nominate the folder again to restore them.

The words that must survive every future edit of that string are **nothing is deleted**. Someone removing a folder from a list has every reason to fear they are deleting their own material, and Askwell never held a copy of it.

Removal is a tombstone, not an erase, for a reason that only shows up afterwards: a source under a removed folder has to be able to say *why* it became unreadable. "You removed this folder" and "no folder ever covered this path" are the same silence to a registry that deleted the row, and only one of them is an answer.

### Four ways a folder can be unreadable

They have four different fixes and are never collapsed into one message.

| State | Means | The fix |
| ----- | ----- | ------- |
| **Needs a restart** | The containers have no window onto this path | A line in `.env`, then bring the stack up again |
| **Not connected** | The window is there, the folder is not | Reconnect the drive or the share. **Nothing has been deleted and nothing needs re-indexing** |
| **Not permitted** | It is there and Askwell may not read it | Its permissions, or SELinux labelling |
| **Readable** | — | — |

**Not connected** is distinct from a file having *moved* (`source-viewer.md` §4) and from a document being *deleted*. A whole folder being absent is not forty files having been moved, and offering to relocate each of them would be forty wrong questions.

### Known gap

Selection is by typed path — and this is true of **adding files**, not only of nominating a folder. No browser reveals a file's absolute path, on any platform: it gives the name and the path *within* a dropped folder, and that is a sandbox rule rather than a missing API. So a drop is expanded and counted first, and then asked one question — *which folder is `clients` in?* — once for the whole drop rather than once per file. A root is a permission over a tree, so one answer settles all of them.

Until the desktop shell ships `M7-TAURI-FE-182` a folder the browser will not surface has to be typed. The screen says so rather than leaving it to be discovered. It is deliberately **not** a file-upload control: that copies bytes, and Askwell copies nothing.

The flow is shaped so the picker replaces the selection step alone. The registry, the validation, and what removing a folder does are untouched by that change.
