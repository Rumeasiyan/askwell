# Manual test — M1-INDEX-BE-034, supersede a changed document rather than duplicating it

**Ticket:** `M1-INDEX-BE-034` — a file re-added at a path that already holds a live document, with different content, is offered as a new version rather than silently duplicated; accepting retires the old document (`superseded_by`) rather than deleting it, and declining leaves both live.
**Version under test:** `0.2.15`
**Time:** about 40 minutes.
**Who can run it:** a terminal and a browser. No embedding model needed — this ticket is about what gets recorded, not about retrieval.

**What is being checked.** `api/src/askwell/sources.py`'s `add` recognises a third case beyond duplicate and new document: a file whose path matches a live document but whose content hash does not. `Outcome.NEW_VERSION` is returned with nothing recorded. A second call answers via `version_decisions: {relative_path: "supersede" | "keep_both"}` on `POST /sources` — `"supersede"` inserts the new document at `version + 1` and sets the old row's `superseded_by`, in one transaction, alongside a `document_superseded` decisions record naming both; `"keep_both"` inserts it as an ordinary independent document with no link.

**Where this stops on purpose.** There is **no screen for this at all**. `web/lib/sources.ts`'s `Outcome` type is `"added" | "duplicate" | "later" | "refused"` — it does not know `new_version` or `superseded` exist. `web/components/add/add-screen.tsx`'s `Recorded` component only renders the `duplicate` and `refused` buckets; a file that comes back with outcome `new_version` matches none of the buckets the screen looks for and **renders nowhere** — it is present in the raw JSON the browser receives and invisible on the page. There is also still no library screen or source viewer (`web/app/library/page.tsx` is the placeholder empty state), so "the old document keeps its citations" and "retrieval prefers the live version" — both named in this ticket's own scope — have nothing to click through either; neither retrieval (`M1-ASK-RET-035`/`036`) nor a document-detail/citation endpoint exists yet (tracked as issue #141). This walkthrough therefore uses the browser for everything it can — nominating a folder, dropping the first version of a file — and drops to a terminal `curl` for the two things the interface has no way to do: answering the supersession offer, and observing that it happened.

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

**You should see:** lint, format, typecheck and test stages finish without red error text, including `api/tests/test_sources_records.py`.

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

### 6. Nominate the folder your material is in

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

## Part A — add the original version, through the browser

### 7. Write the first revision

```bash
scripts/dev.sh run python3 - <<'PY'
with open("/app/askwell-test-material/supplier-agreement.txt", "w") as f:
    f.write("Payment terms: net 30 days from invoice date.\n")
print("done")
PY
```

**You should see:** the script print `done`.

### 8. Get to the add screen by clicking

Click **Ask** in the left strip.

**You should see:** the "Ask your own material" page, with an **Add a source** button.

Click **Add a source**.

**You should see:** the "Add a source" page, address bar ending in `/sources/add/`.

### 9. Drop the file

Open your file manager at `~/external/quantum-plus/askwell/askwell-test-material`. Drag `supplier-agreement.txt` onto the window and release, type the folder with your own path when asked, and click **Add it**.

**You should see:** the card move to **Queued**, then settle with no red error text — a plain-text file has nothing to extract or chunk that would fail here.

### 10. Confirm it landed as a live document, version 1

```
scripts/dev.sh psql
```

```sql
SELECT id, filename, version, superseded_by, deleted_at
FROM documents WHERE filename = 'supplier-agreement.txt';
```

**You should see:** one row, `version` = `1`, `superseded_by` and `deleted_at` both null. Keep this session open, or reopen it later — the next parts check the same row.

---

## Part B — a changed file at the same path is offered, not duplicated

This is the part the interface cannot show. Confirm that first, then do from a terminal what a screen would otherwise do.

### 11. Change the file on disk

```bash
scripts/dev.sh run python3 - <<'PY'
with open("/app/askwell-test-material/supplier-agreement.txt", "w") as f:
    f.write("Payment terms: net 45 days from invoice date, revised June.\n")
print("done")
PY
```

### 12. Re-add it through the browser, and watch nothing happen

Go back to `/sources/add/`, drag `supplier-agreement.txt` onto the window again, type the same folder path, click **Add it**.

**You should see:** the card briefly show a queued/recording state, then **nothing lands anywhere on the page** — it does not appear under "files Askwell already had" (that bucket is for identical content, not this), does not appear as refused, does not appear as added. This is the gap named above: the API answered with outcome `new_version` and the screen has no bucket for it.

### 13. Confirm the API actually said something, from a terminal

```bash
curl -s -X POST http://127.0.0.1:8000/sources \
  -H 'content-type: application/json' \
  -d '{"folder": "/home/you/external/quantum-plus/askwell/askwell-test-material", "files": ["supplier-agreement.txt"]}' \
  | python3 -m json.tool
```

(Use the same folder path you nominated in step 6.)

**You should see:** `"outcome": "new_version"` for `supplier-agreement.txt`, `"existing"` naming the version-1 document's ID and `"version": 2`, and nothing else changed — `"added": 0`, `"superseded": 0` in the summary counts.

### 14. Confirm nothing was recorded for the offer

```sql
SELECT count(*) FROM documents WHERE filename = 'supplier-agreement.txt';
```

**You should see:** `1` — still only the original row. Declining costs nothing to reverse because nothing happened yet.

---

## Part C — accept the offer: supersede

### 15. Answer the offer

```bash
curl -s -X POST http://127.0.0.1:8000/sources \
  -H 'content-type: application/json' \
  -d '{"folder": "/home/you/external/quantum-plus/askwell/askwell-test-material", "files": ["supplier-agreement.txt"], "version_decisions": {"supplier-agreement.txt": "supersede"}}' \
  | python3 -m json.tool
```

**You should see:** `"outcome": "superseded"` for the file, and `"superseded": 1` in the summary counts.

### 16. Confirm the database agrees

```sql
SELECT id, version, superseded_by, deleted_at FROM documents
WHERE filename = 'supplier-agreement.txt' ORDER BY version;
```

**You should see:** two rows. Version 1 has `superseded_by` set to version 2's `id` and `deleted_at` still **null** — supersession is not deletion, and the ticket's own validation rule (`superseded_by` for versions, `deleted_at` for the tombstone) holds. Version 2 has `superseded_by` null.

### 17. Confirm the decision was recorded, and check the audit chain

```sql
SELECT kind, payload FROM audit_decisions
WHERE kind = 'document_superseded' ORDER BY recorded_at DESC LIMIT 1;
```

**You should see:** one row naming both document IDs from step 16.

```
podman compose exec api askwell-verify
```

**You should see:** both audit chains reported intact.

---

## Part D — decline the offer: keep both

### 18. Change the file again, and this time keep both

```bash
scripts/dev.sh run python3 - <<'PY'
with open("/app/askwell-test-material/supplier-agreement.txt", "w") as f:
    f.write("Payment terms: net 60 days from invoice date, revised August.\n")
print("done")
PY
```

```bash
curl -s -X POST http://127.0.0.1:8000/sources \
  -H 'content-type: application/json' \
  -d '{"folder": "/home/you/external/quantum-plus/askwell/askwell-test-material", "files": ["supplier-agreement.txt"], "version_decisions": {"supplier-agreement.txt": "keep_both"}}' \
  | python3 -m json.tool
```

**You should see:** `"outcome": "added"` for the file (an ordinary independent document, not a version), and `"added": 1` in the summary counts.

### 19. Confirm both versions are still live

```sql
SELECT id, version, superseded_by, deleted_at FROM documents
WHERE filename = 'supplier-agreement.txt' ORDER BY added_at;
```

**You should see:** three rows now. The version-2 document from Part C still has `superseded_by` null and `deleted_at` null — declining left it exactly as live as it was. The new document has no link to any of the others at all (`version` = `1` again, its own independent lineage) — `"keep_both"` inserts a plain document, not a chained version.

---

## Part E — superseding a document that is itself superseded chains, rather than orphaning

### 20. One more revision, superseding the version-2 document from Part C

```bash
scripts/dev.sh run python3 - <<'PY'
with open("/app/askwell-test-material/supplier-agreement.txt", "w") as f:
    f.write("Payment terms: net 45 days from invoice date, revised June, corrected typo.\n")
print("done")
PY
```

Offer first (no `version_decisions`), to see which document it is offered against:

```bash
curl -s -X POST http://127.0.0.1:8000/sources \
  -H 'content-type: application/json' \
  -d '{"folder": "/home/you/external/quantum-plus/askwell/askwell-test-material", "files": ["supplier-agreement.txt"]}' \
  | python3 -m json.tool
```

**You should see:** `"outcome": "new_version"`, `"existing"` naming the version-2 document's ID from Part C — **not** the version-1 document, which is already superseded. This is the chaining rule: the candidate lookup only considers documents with `superseded_by IS NULL`.

Accept it:

```bash
curl -s -X POST http://127.0.0.1:8000/sources \
  -H 'content-type: application/json' \
  -d '{"folder": "/home/you/external/quantum-plus/askwell/askwell-test-material", "files": ["supplier-agreement.txt"], "version_decisions": {"supplier-agreement.txt": "supersede"}}' \
  | python3 -m json.tool
```

### 21. Confirm the chain

```sql
SELECT id, version, superseded_by, deleted_at FROM documents
WHERE filename = 'supplier-agreement.txt' ORDER BY added_at;
```

**You should see:** four rows total. Version 1 still points at version 2. Version 2 now points at the newest document. The `keep_both` document from Part D is untouched and still stands alone, `superseded_by` null. Nothing is orphaned — every superseded row names exactly the document that replaced it.

---

## Part F — a new path with the same content is still a duplicate, not a version offer

### 22. Copy the current live text to a new filename

```bash
scripts/dev.sh run python3 - <<'PY'
import shutil
shutil.copyfile(
    "/app/askwell-test-material/supplier-agreement.txt",
    "/app/askwell-test-material/supplier-agreement-copy.txt",
)
print("done")
PY
```

### 23. Add it through the browser

Go to `/sources/add/`, drag `supplier-agreement-copy.txt` in, click **Add it**.

**You should see:** it appear under **"files Askwell already had"** — the ordinary duplicate note, same as any other duplicate — not silently dropped, and not offered as a version. Content-hash duplicate recognition runs ahead of the path-based version check, exactly as the ticket's edge case requires.

---

## Known gaps

- **No interface for any of this.** `web/lib/sources.ts`'s `Outcome` type does not include `new_version` or `superseded`, and `web/components/add/add-screen.tsx`'s `Recorded` component has no bucket for either. A file offered as a new version renders on no part of the add-source screen — confirmed by reading the code, not assumed — so every decision in this document was made with `curl`, not a click. `docs/ux/add-source.md` §5's "new version" state and `docs/ux/source-viewer.md` §4's "superseded banner" describe a screen that does not exist yet; filed as issue #141 rather than built against a guessed shape.
- **Retrieval preferring the live version is not exercisable.** No component reads `chunks.embedding` or `content_tsv` for a real question yet (`M1-ASK-RET-035`/`036`). The requirement that retrieval exclude a superseded document is recorded in `docs/decisions.md` for that ticket to pick up; this document cannot ask a question and show the new figure winning.
- **An old citation resolving to the old version is not exercisable either.** There is no document-detail or citation-resolution endpoint to open a stale citation against, and no source viewer to show the banner on. Both are named in this ticket's own Real-World Example Scenario and neither has anywhere to attach yet.
- **Answer wording naming the revision** ("as of the June revision") is explicitly out of scope for this ticket (M2-PARTIAL, answer composition) and was not attempted here.
- **No automatic detection of a changed file on disk.** Askwell only notices a revision when the file is re-added through `POST /sources`; nothing watches the filesystem. Named as a known gap in the ticket itself.
