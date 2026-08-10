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

**Indexing is in place.** Files are read where they are, not copied into a library. Stated once, because someone about to add 40 GB of case files needs to know before they start, not after.

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
| **Duplicate** | Recognised by content hash, linked to the existing source, not re-ingested |
| **New version** | Offered as superseding, not duplicating. Old version stays queryable for history |
| **Unsupported format** | Named, with the supported list and the CSV fallback where relevant |
| **Dump too large / too slow** | Aborted at 5 GB or 10 minutes, sandbox dropped, reason given |
| **Connection unreachable** | Distinguish wrong host from wrong credentials from firewall — three different fixes |
| **Write-capable credentials** | Refused, with the SQL to create a read-only user |
| **Disk budget reached** | Refused before starting, with what to free |

---

## 6. Open

1. **Folder watching** — re-index when a watched folder changes. Obvious want, unspecified, and it interacts with supersession.
2. **Excel multi-sheet** — one table per sheet, and what happens to merged headers (`../data-sources.md` §8).
