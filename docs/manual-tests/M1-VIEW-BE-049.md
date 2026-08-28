# Manual test — M1-VIEW-BE-049, the moved-or-renamed file state, distinct from deleted

**Ticket:** `M1-VIEW-BE-049` — when a document's recorded path no longer resolves, mark it
missing (`missing_since`), never deleted; name the old path in the viewer and offer manual
relocation; verify the new file's hash before trusting it.
**Version under test:** `0.2.33`
**Time:** about 20 minutes, no inference required (nothing here asks a question).
**Who can run it:** anyone who can rename a file and paste a line into a terminal.

**What is being checked.** `api/src/askwell/documents.py`'s `_availability` (the open-time
check shared by `GET /documents/{id}` and `GET /documents/{id}/file`) and the
`POST /documents/{id}/relocate` endpoint it adds; `askwell.ingest.sweep_missing`, the same
decision run on a timer by `worker.py`'s `check_missing` cron (default every
`ASKWELL_MISSING_CHECK_SECONDS=300` seconds); and the viewer's two new states,
`MovedFileNotice` and `RootUnavailableNotice` in `web/components/documents/viewer-shared.tsx`,
wired into `document-viewer.tsx`.

**Where this stops on purpose.** Automatic folder watching is not built — the periodic sweep
still requires a click or a timer tick, never a filesystem event. Relocation is a plain text
field, not a native file-picker (that is `M7-TAURI-FE-182`). Bulk relocation of an entire
moved root is not built.

---

## Before you start

### 1. Make a folder and a real PDF in it

```
mkdir -p ~/askwell-test/moved-file
cd ~/askwell-test/moved-file
python3 - <<'EOF'
from reportlab.pdfgen import canvas
c = canvas.Canvas("contract.pdf", pagesize=(612, 792))
c.drawString(72, 700, "The notice period under this agreement is ninety days.")
c.showPage()
c.save()
EOF
```

### 2. Point Askwell at the folder and bring up the stack

In `.env`:

```
ASKWELL_ROOTS_MOUNT=/home/<you>/askwell-test/moved-file
```

```
podman compose up -d
scripts/dev.sh db upgrade head
scripts/dev.sh inference
```

---

## Part A — cold start, add the file, ask about it, open the citation

### 3. Open Askwell and add the file

Go to `http://127.0.0.1:8000`. Click **Add a source**. Drop `contract.pdf`. Answer the
folder question with the folder's absolute path if asked.

**Expect:** a card for `contract.pdf` moves through *Detecting → Where are these? →
Recording → Queued*.

### 4. Wait for indexing

Go to **Library** and wait (refresh as needed).

**Expect:** `contract.pdf`'s source reaches **indexed**.

### 5. Ask about it

Go to **Ask** and ask:

```
What is the notice period?
```

**Expect:** the answer states ninety days, with a citation card for `contract.pdf`.

### 6. Open the citation

Click the citation card.

**Expect:** the viewer opens `contract.pdf` at page 1, the ninety-days sentence marked. This
is the state you will compare against once the file moves.

---

## Part B — rename the file, click the same citation, confirm "moved" not "deleted"

### 7. Quit the stack and rename the file on disk

```
podman compose down
```

```
mv ~/askwell-test/moved-file/contract.pdf ~/askwell-test/moved-file/agreement.pdf
```

### 8. Bring the stack back and click the same card again

```
podman compose up -d
scripts/dev.sh inference
```

Go back to the same Ask conversation (or ask the same question again) and click the
`contract.pdf` citation card again — same document, same URL as step 6.

**Expect:**
- A message naming the file has moved and stating the **old** path
  (`.../moved-file/contract.pdf`) — the exact text is *"contract.pdf has moved. Askwell last
  found it at `<old path>`, but that path no longer resolves. Nothing was deleted."*
- **The word "deleted" never appears.** This is the acceptance criterion this ticket exists
  for — compare against the pre-`M1-VIEW-BE-049` behaviour, which said only *"contract.pdf is
  no longer at its recorded path"* with no relocate offer.
- A **"Where is it now?"** text field pre-filled as a placeholder with the old path, and a
  **Relocate** button, disabled until you type something into the field.

### 9. Check the library reflects it too

Go to **Library**.

**Expect:** the source's status reads **needs attention** (`askwell.ingest.source_status`
now returns `"attention"` when any document has `missing_since` set, the same status word
used for a failed or poorly-scanned file).

---

## Part C — relocate to the correct file, hash verifies, viewing is restored

### 10. Type the new path and relocate

Back in the viewer from step 8, type the new path into **"Where is it now?"**:

```
/home/<you>/askwell-test/moved-file/agreement.pdf
```

Click **Relocate**.

**Expect:** the notice disappears and the viewer immediately re-renders `contract.pdf`'s
content normally — page 1, the ninety-days sentence still there — now served from the new
path. No page reload is needed; the component re-fetches on its own (`reloadToken`).

### 11. Confirm the path was actually updated, not just the UI

```
podman compose exec api askwell-verify
```

(Or, since this ticket adds a decisions-store record for the relocation:)

**Expect:** re-opening the document later (e.g. reload the tab, or check **Library** again)
still shows it as indexed/ready, not needs-attention — the recorded path now points at
`agreement.pdf`.

---

## Part D — relocate to the wrong file, hash mismatch is refused

### 12. Move the file again and make a decoy

```
podman compose down
mv ~/askwell-test/moved-file/agreement.pdf ~/askwell-test/moved-file/agreement-moved-again.pdf
python3 - <<'EOF'
from reportlab.pdfgen import canvas
c = canvas.Canvas("decoy.pdf", pagesize=(612, 792))
c.drawString(72, 700, "This is an entirely unrelated document.")
c.showPage()
c.save()
EOF
podman compose up -d
scripts/dev.sh inference
```

### 13. Open the citation, see "moved" again, try relocating to the decoy

Click the same citation card. **Expect:** the moved notice again, naming the
`agreement.pdf` path this time.

Type the decoy's path (`/home/<you>/askwell-test/moved-file/decoy.pdf`) and click
**Relocate**.

**Expect:** relocation is refused with a message naming the hash mismatch — *"decoy.pdf is
not the same file as contract.pdf — its content does not match."* — plus a suggestion to add
it as a new file instead if it is meant to be a new version. The moved notice remains on
screen (nothing was changed); the recorded path still points at the old, now-nonexistent
`agreement.pdf`.

### 14. Relocate to the real file this time

Type `/home/<you>/askwell-test/moved-file/agreement-moved-again.pdf` and click **Relocate**.

**Expect:** succeeds as in step 10 — the hash matches, viewing is restored.

---

## Part E — the whole root unmounted, reported as unreachable, not "every document missing"

### 15. Simulate the root itself being gone

Stop the stack and change `.env`'s `ASKWELL_ROOTS_MOUNT` to a folder that does not contain
`~/askwell-test/moved-file` at all (e.g. comment it out or point it elsewhere), then bring
the stack back up:

```
podman compose down
```

Edit `.env` — remove or change `ASKWELL_ROOTS_MOUNT` so it no longer covers
`~/askwell-test/moved-file`.

```
podman compose up -d
```

### 16. Open the citation again

**Expect:** a **different** message than Part B/D — *"Askwell cannot reach the folder that
holds this file right now,"* with the reason (`roots.source_availability`'s explanation of
why, e.g. the root is not mounted). **No relocate field appears** — relocating a
root-unavailable document is nonsensical (there is nowhere to type; the fix is reconnecting
the root, not picking a new file for it).

Restore `ASKWELL_ROOTS_MOUNT` to `~/askwell-test/moved-file` and bring the stack back up
before continuing, so the environment is clean for anyone running this test next.

---

## Part F — the file reappears on its own, missing clears without relocating

### 17. Move the file back to where it was recorded

At this point the document's recorded path is `agreement-moved-again.pdf`. Put a copy back
at exactly that path if it was moved away, or — simpler — pick any currently-missing
document from earlier steps, and place a byte-identical copy back at its exact recorded
path. Then click its citation once more.

**Expect:** the file opens normally with no moved notice — the open-time check in
`_availability` clears `missing_since` itself the moment the path resolves again, with no
relocation action needed.

---

## Part G — the periodic sweep catches a move nobody clicked

### 18. Rename the current file without opening the viewer

```
mv ~/askwell-test/moved-file/agreement-moved-again.pdf ~/askwell-test/moved-file/final-name.pdf
```

Do **not** click the citation. Wait at least `ASKWELL_MISSING_CHECK_SECONDS` (5 minutes by
default) — or temporarily set `ASKWELL_MISSING_CHECK_SECONDS=30` in `.env` and restart the
worker for a faster check.

### 19. Check the library without opening the document

Go to **Library** and refresh after the wait.

**Expect:** the source has already flipped to **needs attention** on its own —
`worker.py`'s `check_missing` cron ran `ingest.sweep_missing` and set `missing_since`
without anyone clicking anything. Click the citation to confirm the same moved notice from
Part B appears, then relocate to `final-name.pdf` to leave the environment clean.

---

## What was checked against the ticket's acceptance criteria

- Renaming a file and clicking its citation names the old path and offers relocation, never
  says deleted — Part B, step 8.
- Relocating to the correct file verifies the hash and restores normal viewing — Part C.
- Relocating to a different file is refused, naming the hash mismatch — Part D.
- Edge case: the whole root unmounted is reported as the root unavailable, not every
  document individually missing — Part E.
- Edge case: a file that returns to its original path on its own clears on next open — Part F.
- Edge case: the periodic sweep catches a move nobody opened — Part G.
- `missing_since` is set, `deleted_at` is never touched by any of the above — implicit in
  every step (the document never leaves the library, it changes status instead).
- A relocation is a decisions record naming both paths — step 11, verifiable via
  `askwell-verify` or by inspecting `audit_decisions` directly if you have `psql` access
  (`scripts/dev.sh psql`, `select * from audit_decisions where kind = 'document_relocated';`).

## Known gaps

Do not report these as defects — they are pre-existing or explicitly out-of-scope gaps this
ticket depends on or intentionally leaves open:

- **The library's "Show detail" panel does not list a moved file as a cause.** Reading
  `web/lib/library.ts`'s `attentionCauses`, it only ever inspects `failures` and `flagged` —
  nothing in the frontend fetches or surfaces the `missing` count `askwell.ingest.coverage`
  now returns. A source with only a moved document reaches **needs attention** in the status
  word (Part B, step 9) but if it has no failed or poorly-scanned files, "Show detail" does
  not even appear, since `causes.length` is 0 — there is no way to learn *which* file moved,
  or that it moved at all, from the library alone. Opening the document (Part B, step 8) is
  currently the only way to see the reason. Worth its own follow-up issue.
- **No folder watching.** A move is only caught by opening the citation or by the periodic
  sweep (default every 5 minutes); nothing reacts to the filesystem event itself.
- **Relocation is a plain text field**, not a native file-picker — you have to know and type
  the exact new path. `M7-TAURI-FE-182` is the ticket that replaces this with the platform's
  own file dialog, without changing the verification behaviour tested above.
- **No bulk relocation.** If an entire folder was moved (not just one file), each document
  under it has to be relocated individually — there is no "relocate this whole source" action.
- **Deletion and tombstones are explicitly out of scope** (M2) — a document that is actually
  gone forever still shows as "moved" indefinitely, since this ticket has no way to
  distinguish "will come back" from "gone for good." That distinction is deliberately left to
  a later milestone.
