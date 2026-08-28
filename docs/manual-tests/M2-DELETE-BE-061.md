# Manual test — M2-DELETE-BE-061, tombstoned deletion

**Ticket:** `M2-DELETE-BE-061` — deleting a document or a source clears content and embedding in one statement, tombstones the row with a date and reason, and leaves the row itself, general memory and the audit stores untouched.
**Version under test:** `0.2.48`
**Time:** about 40 minutes, plus a first stack build.
**Who can run it:** a terminal and a browser, plus native inference running on the host for Part A's "ask before/after" step. Parts B–D need only `psql`/`curl`.

**What is being checked.** `askwell.sources.delete_document` and `delete_source`
(`api/src/askwell/sources.py`) — a document's chunks lose `content` and
`embedding` in the same statement the database's own
`ck_chunks_cleared_content_has_no_embedding` check independently enforces,
the document row gets `deleted_at`/`deleted_reason`/`status = 'deleted'`
rather than being removed, and any queued or in-flight ingestion job for it
is cancelled. Deleting a source runs that same tombstone over every live
document under it, deletes its `schema_notes` rows outright, leaves the
`memory` table untouched, and marks the source itself `deleted`. Both are
decisions-store records (C6). Retrieval (`askwell.retrieve`,
`askwell.ask`) already filters `deleted_at IS NULL` everywhere it reads
`documents`, so a deleted document stops being retrievable as a side effect
of the same column this ticket writes, not from new filtering code.

**Where this stops on purpose.** There is no delete button anywhere in
`web/` yet — `web/components/settings/folders.tsx` has one for a *nominated
folder*, not for a source or a document, and no client of
`DELETE /documents/{id}` or `DELETE /sources/{id}` exists in `web/lib/`.
Deletion in this walkthrough is driven with `curl`, the same way
`M2-PARTIAL-BE-059` drove supersession with `psql` before its own UI
existed. The confirmation dialog and the "deleted on `<date>`" citation
card are `M2-DELETE-FE-062`'s territory, not built here.

---

## Before you start

```
cd ~/external/quantum-plus/askwell
mkdir -p askwell-test-material
```

If you have never run Askwell before:

```
cp -n .env.example .env
```

Open `.env`. Find `ASKWELL_ROOTS_MOUNT=` and set it to the folder above, with your own path:

```
ASKWELL_ROOTS_MOUNT=/home/you/external/quantum-plus/askwell/askwell-test-material
```

Find `POSTGRES_APP_PASSWORD` and put any word after the `=` if it is blank.

---

## Cold start

### 1. Remove any previous state

```
podman compose down -v
```

**You should see:** lines about containers and volumes being removed, or a note there was nothing to remove.

### 2. Build the interface

```
scripts/dev.sh web-build
```

**You should see:** a Next.js build finishing with a route list and no red error text.

### 3. Run the checks

```
scripts/dev.sh check
```

**You should see:** lint, format, typecheck and test stages finish without red error text, including the deletion cases in `api/tests/test_sources_records.py` (`test_deleting_a_document_clears_content_and_embedding_and_tombstones_the_row` and the source-level equivalents).

### 4. Bring the stack up

```
podman compose up -d
```

**You should see:** `postgres`, `redis`, `egress-proxy`, `api`, `worker` reported as started. Wait about thirty seconds.

### 5. Create the database tables

```
scripts/dev.sh db upgrade head
```

**You should see:** migration lines finish with no error.

### 6. Start native inference, on the host

```
scripts/dev.sh inference
```

Leave this running in its own terminal for the rest of this document. Wait for it to report both the embedding and generation roles `ready` on their configured ports. (Only needed for Part A's ask-before/ask-after step — skip starting it if you only intend to run Parts B–D.)

### 7. Nominate the folder your material is in

Open a browser at:

```
http://127.0.0.1:8000
```

Click **Settings** in the left strip, scroll to **Folders Askwell may read**, type your own path into the **Nominate a folder** field —

```
/home/you/external/quantum-plus/askwell/askwell-test-material
```

— and click **Nominate**.

**You should see:** a box appear showing that path, marked **Readable**.

---

## Part A — the ticket's own walkthrough: add, ask, delete, ask again, check the old citation

### 8. Write a file with one fact to ask about

```bash
scripts/dev.sh run python3 - <<'PY'
with open("/app/askwell-test-material/exit-agreement.txt", "w") as f:
    f.write(
        "Client Exit Agreement. Section 3, Confidentiality. "
        "All client materials must be destroyed within thirty days of engagement end.\n"
    )
print("done")
PY
```

**You should see:** the script print `done`.

### 9. Get to the add screen by clicking

Click **Ask** in the left strip.

**You should see:** the "Ask your own material" page's first-run, empty-corpus state — no chat box, a statement that no documents are indexed yet, and an **Add a source** button.

Click **Add a source**.

**You should see:** the "Add a source" page, address bar ending in `/sources/add/`.

### 10. Add the file

Open your file manager at `~/external/quantum-plus/askwell/askwell-test-material`. Drag `exit-agreement.txt` onto the window and release, type the folder with your own path when asked, and click **Add it**.

**You should see:** the card move to **Queued**, then progress through extraction, chunking and embedding, and settle with no red error text.

### 11. Confirm it reached `ready` and note its id

```
scripts/dev.sh psql
```

```sql
SELECT id, filename, status FROM documents WHERE filename = 'exit-agreement.txt';
```

**You should see:** one row, `status = ready`. Copy the `id` — you need it for the rest of Part A. Keep this `psql` session open in its own terminal.

### 12. Ask about it and note the answer and its citation

Click **Ask** and type:

```
How soon must client materials be destroyed after engagement end?
```

**You should see:** an answer stating thirty days, with a citation card to `exit-agreement.txt`. Click the citation card.

**You should see:** the source viewer opens the file at the cited passage. Go back to the answer.

### 13. Delete the document

In a terminal (not the `psql` session):

```bash
curl -s -X DELETE "http://127.0.0.1:8000/documents/<the-id-from-step-11>?reason=client+engagement+ended" | python3 -m json.tool
```

**You should see:** `{"deleted": true, "document_id": "<the-id>", "reason": "client engagement ended"}`.

### 14. Confirm the tombstone in the database

Back in the `psql` session:

```sql
SELECT status, deleted_at, deleted_reason FROM documents WHERE filename = 'exit-agreement.txt';
```

**You should see:** `status = deleted`, `deleted_at` a real timestamp, `deleted_reason = 'client engagement ended'`. The row is still there — this is a tombstone, not a `DELETE`.

```sql
SELECT content, embedding FROM chunks WHERE document_id = '<the-id-from-step-11>';
```

**You should see:** every row for this document has `content` = `NULL` and `embedding` = `NULL`. There is no way to get this half-done — try `UPDATE chunks SET content = 'x' WHERE document_id = '<the-id>'` on a row whose `embedding` is still set (there should not be one, but if you find one) and confirm Postgres refuses it with `ck_chunks_cleared_content_has_no_embedding`; that constraint is what makes "cleared" mean the same thing everywhere, not just what this code path happens to do.

### 15. Ask the same question again and confirm Askwell no longer answers from it

Click **Ask**, start a new conversation, and ask the same question again:

```
How soon must client materials be destroyed after engagement end?
```

**You should see:** Askwell abstains — it says it has nothing in your files that answers this, rather than repeating the thirty-day figure. (If other unrelated material is in your corpus from an earlier walkthrough, confirm specifically that `exit-agreement.txt` is not cited and the thirty-day figure does not appear.)

### 16. Check the file on disk is untouched

```bash
cat ~/external/quantum-plus/askwell/askwell-test-material/exit-agreement.txt
```

**You should see:** the file, with its full original text. Deletion never touches what is on disk — Askwell only ever read it.

### 17. Scroll back to the earlier answer's citation

Go back to the conversation from step 12 (the one with the thirty-day answer) and click its citation card again.

**You should see (per the ticket's own acceptance criteria):** the card resolving to "deleted on `<date>`" rather than breaking.

**What actually happens as of this version:** clicking the card calls `GET /documents/{id}`, which now 404s with `{"error": "No such document."}` — `document_metadata`'s lookup (`api/src/askwell/documents.py`) filters `deleted_at IS NULL` and treats a tombstoned id exactly like one that never existed. Confirm this directly instead of through the (not-yet-built) citation card:

```bash
curl -s -o /dev/null -w "%{http_code}\n" "http://127.0.0.1:8000/documents/<the-id-from-step-11>"
```

**You should see:** `404`. This is a real gap against this ticket's own acceptance criteria, not expected behaviour — filed as issue [#231](https://github.com/Rumeasiyan/askwell/issues/231). It does not block the rest of this walkthrough, which is testing the database-level tombstone this ticket actually built.

---

## Part B — re-adding a previously deleted file is a new document, not a resurrection

### 18. Add `exit-agreement.txt` again

Drag it onto the **Add a source** page again, same folder answer, click **Add it**.

**You should see:** it queues and indexes as if new — no "already have this" message. Confirm in `psql`:

```sql
SELECT id, filename, status, deleted_at FROM documents WHERE filename = 'exit-agreement.txt' ORDER BY added_at;
```

**You should see:** two rows now — the original, still `status = deleted` with its `deleted_at` set, and a new one with a different `id`, `status` moving through the ordinary pipeline to `ready`, `deleted_at` = `NULL`. The deleted row never blocks re-adding, and the new row is unrelated to it (no `superseded_by` linking them).

---

## Part C — deleting a document with a pending ingestion job cancels it

### 19. Write and add a file, then delete it before it can finish

```bash
scripts/dev.sh run python3 - <<'PY'
with open("/app/askwell-test-material/pending-doc.txt", "w") as f:
    f.write("Placeholder text for a document deleted mid-ingestion.\n")
print("done")
PY
```

Drag `pending-doc.txt` onto the **Add a source** page, confirm the folder, click **Add it**. Immediately (before it settles at **Indexing** or **Ready**) find its id:

```sql
SELECT id, status FROM documents WHERE filename = 'pending-doc.txt';
```

Delete it right away:

```bash
curl -s -X DELETE "http://127.0.0.1:8000/documents/<that-id>?reason=cancelled+mid+import" | python3 -m json.tool
```

### 20. Confirm nothing is left half-indexed

```sql
SELECT status, deleted_at FROM documents WHERE filename = 'pending-doc.txt';
SELECT count(*) FROM ingest_jobs WHERE document_id = '<that-id>';
```

**You should see:** `status = deleted`, `deleted_at` set, and the `ingest_jobs` count `0` — whether the job was still `queued` or had already been claimed by the worker, `delete_document` removed its row, and `ingest._park`/`_finish`/`_fail` (which re-check `deleted_at IS NULL` before writing status back) mean a job that was mid-flight at the exact moment of deletion cannot resurrect the document to `ready` afterward.

---

## Part D — deleting a source tombstones every live document under it, and removes only its schema notes

### 21. Add a second file to make a two-document source, and give the source a schema note

```bash
scripts/dev.sh run python3 - <<'PY'
with open("/app/askwell-test-material/exit-agreement.txt", "w") as f:
    f.write("Duplicate placeholder — this file already exists from Part A if you ran it.\n")
with open("/app/askwell-test-material/second-doc.txt", "w") as f:
    f.write("A second file under the same source, for source-level deletion.\n")
print("done")
PY
```

If Part A already left a folder source in place, note its `source_id`; otherwise add `second-doc.txt` via **Add a source** the same way as before and find the source id:

```sql
SELECT s.id AS source_id, d.filename, d.status
FROM sources s JOIN documents d ON d.source_id = s.id
WHERE s.status <> 'deleted'
ORDER BY d.filename;
```

Give that source a schema note directly (nothing in this milestone produces one yet — this is exercising the deletion code's own handling of a row shape that will exist once Phase 3's SQL ingestion lands):

```sql
INSERT INTO schema_notes (source_id, table_name, description, origin)
VALUES ('<source_id>', 'invoices', 'One row per invoice.', 'inferred');
INSERT INTO memory (subject, fact, origin)
VALUES ('client', 'CDA stands for confidential disclosure agreement', 'manual');
```

### 22. Delete the source

```bash
curl -s -X DELETE "http://127.0.0.1:8000/sources/<source_id>" | python3 -m json.tool
```

**You should see:** `{"deleted": true, "source_id": "<source_id>", "documents_deleted": <n>}` with `<n>` matching how many live documents were under it.

### 23. Confirm every document under it is tombstoned, the schema note is gone, and general memory survives

```sql
SELECT filename, status, deleted_at, deleted_reason FROM documents WHERE source_id = '<source_id>';
SELECT status FROM sources WHERE id = '<source_id>';
SELECT count(*) FROM schema_notes WHERE source_id = '<source_id>';
SELECT fact FROM memory WHERE subject = 'client';
```

**You should see:** every document row `status = deleted`, `deleted_reason = 'source deleted'`; the source's own `status = deleted`; the `schema_notes` count `0`; the `memory` row for "CDA stands for confidential disclosure agreement" still present — a fact learned from the source outlives the source it came from.

### 24. Confirm deleting the same source again is refused, not silently repeated

```bash
curl -s -o /dev/null -w "%{http_code}\n" -X DELETE "http://127.0.0.1:8000/sources/<source_id>"
```

**You should see:** `404` with `{"error": "No such source."}` — unlike a document, a second delete of the same source is not treated as a harmless no-op.

---

## Cleanup

```
podman compose down -v
```

Restore `.env` if you changed anything beyond what **Before you start** asked for.

---

## Known gaps

- **No delete UI.** Nothing in `web/` calls `DELETE /documents/{id}` or `DELETE /sources/{id}` — no confirmation dialog, no delete button in the library, no "deleted" badge (`docs/ux/library.md` §2's four states, `deleted` included, is not rendered). That is `M2-DELETE-FE-062`'s scope and has not landed as of this version. This walkthrough drives deletion with `curl` for exactly that reason.
- **`GET /documents/{id}` 404s a deleted document instead of resolving its tombstone**, which is this ticket's own acceptance criterion ("old citations resolve to a deletion date rather than breaking") not yet met at the endpoint an FE citation card would call. Confirmed in Part A step 17. Filed as [#231](https://github.com/Rumeasiyan/askwell/issues/231) — not fixed here, since fixing it changes `document_metadata`'s response shape and is FE-062's dependency, not BE-061's stated scope.
- **No undo, and no schema-note-producing source exists yet to test against for real.** Phase 3's SQL sandbox ingestion (C2, C3) is what will actually write `schema_notes` rows; Part D inserts one by hand to exercise the deletion code's handling of the table, not to test schema-note *creation*.
- **No superseded-version interaction exercised.** The ticket's edge case "deleting a superseded version is permitted; the live version is unaffected" is not walked here — it requires `M1-INDEX-BE-034`'s supersession flow (set up the same way `M2-PARTIAL-BE-059`'s walkthrough does, with a direct `UPDATE ... SET superseded_by`) plus a delete of the *old* row, and was left out to keep this document to the ticket's own stated scenarios. `delete_document`'s query has no special case for `superseded_by`, so this should behave the same as any other document, but it has not been observed running.
