# Manual test — M1-ADD-BE-023, records, and the file Askwell already has

**Ticket:** `M1-ADD-BE-023` — source and document records with content-hash duplicate detection
**Version under test:** `0.2.5`
**Time:** about 30 minutes, plus a first stack build
**Who can run it:** anyone who can paste a line into a terminal. Everything from step 6 onward is dragging, clicking and reading, with two `psql` queries to confirm what was written.

**What is being checked.** Adding a file has to leave something behind — a source row and a document row carrying the path, the name, the media type and a hash of the contents. Adding the *same contents* again, under a different name or from a different folder, has to be recognised and linked to what is already there rather than stored twice. And the status has to describe what is actually happening, which today is *queued* and not *indexing*.

**Why the duplicate rule matters more than it sounds.** Three copies of one contract become three identical passages in retrieval. An answer then cites the same sentence three times from three "different" documents, and there is no way for the reader to tell that it is one document. That is a citation problem, not a tidiness problem.

**The one thing to watch for throughout.** Nothing here may copy, move, modify or delete a file of yours. Askwell opens your files where they are and reads them; if anything appears in a new place on disk, stop and record it.

**Where this stops on purpose.** Nothing is extracted, embedded or searchable. Documents sit at **queued** and the screen says so. Per-file progress and everything past `queued` is `M1-ADD-ING-025`.

---

## Before you start

You need a terminal and Podman. You do not need Python, Node, or anything else.

### 1. Make files to test with

Paste this whole block into the terminal and press Enter:

```
mkdir -p ~/askwell-test/material/clients ~/askwell-test/material/archive
cd ~/askwell-test/material

printf '%s\n' '%PDF-1.7' 'Either party may terminate on ninety days written notice.' > clients/contract.pdf
cp clients/contract.pdf 'clients/contract copy.pdf'
cp clients/contract.pdf archive/contract.pdf
printf '%s\n' '%PDF-1.7' 'The tenant shall pay rent monthly in advance.' > clients/lease.pdf
: > clients/nothing.pdf
```

That gives you: one contract, an identical copy of it beside the original, a third identical copy in another folder, one genuinely different PDF, and one empty file. Note that `contract copy.pdf` and `archive/contract.pdf` have **different names, different folders and different timestamps** from the original, and identical contents. That is the whole point.

### 2. Point Askwell at the folder

In `.env`, set:

```
ASKWELL_ROOTS_MOUNT=/home/<you>/askwell-test/material
```

Use the real absolute path. Then:

```
podman compose up -d
scripts/dev.sh db upgrade head
```

The `upgrade` step is not optional for this ticket — it adds the `queued` status, and without it every insert here fails on a check constraint.

### 3. Open Askwell

`http://127.0.0.1:8000`. Go to **Add a source** and nominate the folder if it asks you to.

---

## The walkthrough

### 4. Add the contract on its own

Drag `clients/contract.pdf` onto the window. Answer the folder question with the absolute path to `clients`.

**Expect:** the card moves *Detecting → Where are these? → Recording → Queued*, and Queued says one file is queued from that folder, with the sentence that reading and indexing them is the next piece of work.

**Record:** did **Recording** appear at all, and for how long? For one small file it may be too fast to see. That is fine — write down what you saw.

### 5. Confirm something was actually written

```
scripts/dev.sh psql
```

```sql
SELECT kind, name, root_path, status FROM sources;
SELECT filename, path, mime, status, left(sha256, 12) AS hash FROM documents;
```

**Expect:** one source, `kind = file`, named after the folder, `status = queued`. One document, with the **full path** of the file on your disk, `mime = application/pdf`, `status = queued`, and a hash.

**The check that matters:** the `path` column is the file where it already lives. If it points anywhere inside a container's own storage, Askwell has copied something and this is a failure of the whole product promise, not of this ticket.

### 6. Add the copy that sits beside it

Drag `clients/contract copy.pdf` in, same folder answer.

**Expect:** a block saying Askwell already had this file, naming **both** paths — the copy you just dropped, and `clients/contract.pdf`, which is the one indexed. The batch does not report a file queued; it says *Nothing new here*.

**Record:** does the message make it clear *which* of the two files Askwell is actually reading? If you have to guess, that is the defect this ticket exists to prevent.

### 7. Add the same contents from a different folder

Drag `archive/contract.pdf` in and answer with the path to `archive`.

**Expect:** recognised as already present, linked to `clients/contract.pdf`. And in `psql`:

```sql
SELECT count(*) FROM documents;
SELECT count(*) FROM sources;
```

**Expect:** still **one** document. The source count may still be one — a folder where nothing was added does not get a source row.

**Record:** this is the ticket's cold-start scenario. If the document count is 2, the duplicate rule is not global and the acceptance criterion has failed.

### 8. Add a genuinely different PDF

Drag `clients/lease.pdf` in.

**Expect:** added. Two documents now, both under the `clients` source, no second source created for the same folder.

### 9. Add the empty file

Drag `clients/nothing.pdf` in.

**Expect:** refused by name, with the reason that there is nothing in it to index and that nothing was changed on disk. No row is created for it.

### 10. Confirm the audit says what you did

```sql
SELECT kind, payload->>'path' AS path FROM audit_decisions ORDER BY occurred_at;
```

**Expect:** a `source_added` for the folder and a `document_added` for each file that was actually stored, each naming the path. **No** record for the duplicates and **none** for the empty file — nothing changed, so nothing is recorded as a decision.

Then:

```
podman compose exec api askwell-verify
```

**Expect:** both chains intact.

### 11. Confirm a refusal reached the log

```
podman compose logs api | grep file_refused
```

**Expect:** a line naming the empty file's path and the reason. This is the durable record of a refusal that the browser's local counter is not.

### 12. The file that changes while it is read

This one needs two terminals and is the hardest to see. In one:

```
cd ~/askwell-test/material/clients
while true; do printf '%s\n' '%PDF-1.7' "$RANDOM" > moving.pdf; done
```

Drag `moving.pdf` in from the file browser, then stop the loop with Ctrl-C.

**Expect:** either it is added (the loop happened to be idle across the whole read) or it is refused per file, saying it kept changing and something else is still writing to it. **Not expected:** a document stored with a hash of bytes that no longer exist, and not a hang.

**Record:** which of the two happened, and how long it took.

---

## Known gaps — not defects

1. **Nothing is extracted, embedded or searchable.** Every document sits at `queued`. The statuses past that — `indexing`, `ready`, `attention` — belong to `M1-ADD-ING-025` and are not reachable from this build.
2. **A changed version of a file already added is recorded as a new document, not a supersession.** Edit `contract.pdf` and add it again and you will get a second document rather than a version. `M1-INDEX-BE-034`.
3. **Hashing happens inside the request.** A large drop is a long request with no progress while it runs, and nothing can be cancelled. Recorded as an open item in `docs/BRAIN.md`.
4. **A file under two nominated folders appears under only one source.** That is the deliberate consequence of global recognition (`docs/decisions.md`, 2026-08-28) and will look like a missing file once the library screen exists. Recorded as an open item.
5. **The browser still decides what is sent.** A `.txt` or `.md` file whose first line has two commas is still routed to the table route client-side and never reaches the server, which would have kept it. The server half is fixed; the client half is an open item.
