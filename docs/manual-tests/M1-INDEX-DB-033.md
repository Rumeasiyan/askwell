# Manual test — M1-INDEX-DB-033, full-text column population and index

**Ticket:** `M1-INDEX-DB-033` — every indexed chunk gets a populated `content_tsv` value, a reference number like `INV-2024-0917` is found by a lexical query including just its trailing digit group, the query plan uses the GIN index rather than scanning at corpus scale, and re-indexing a document repopulates rather than duplicating.
**Version under test:** `0.2.14`
**Time:** about 30 minutes.
**Who can run it:** a terminal and a browser. No embedding model needed — this ticket is about the lexical column, not vectors.

**What is being checked.** `chunks.content_tsv` is a generated `STORED` column (`api/src/askwell/db/models.py`) that Postgres populates on every write with no application code — `a8208099ef38` created it, `c7e2f814a5b3` (this ticket) fixed its expression so a hyphen directly before a digit run tokenises as a separator, not a sign. This walkthrough proves the population and the reference-number fix by hand through a real add-source run, then confirms the index is actually used at scale and that the automated corpus-scale check (`api/tests/test_index_db_records.py`) passes — a 300,000-row seed is impractical to click through by hand.

**Where this stops on purpose.** Nothing yet *queries* `content_tsv` from the product surface. There is no library screen and no search box — `web/app/library/page.tsx` is still the placeholder empty state, and fusion with dense results is `M1-ASK-RET-035`, still unbuilt. This walkthrough gets a document to `ready` by clicking, the same as `M1-INDEX-ING-032`'s manual test did, then reads the lexical column the only way currently possible: directly, with `psql`.

---

## Before you start

You need a terminal and Podman. No embedding model weights are required for this ticket.

### 1. Build a small test file with a distinctive reference number

```
cd ~/external/quantum-plus/askwell
mkdir -p askwell-test-material
```

```bash
scripts/dev.sh run python3 - <<'PY'
text = (
    "Invoice INV-2024-0917 is due at the end of the quarter. "
    "This is filler text to make the file long enough to chunk into more than one row. "
) * 40
with open("/app/askwell-test-material/invoice-notes.txt", "w") as f:
    f.write(text)
print("done")
PY
```

**You should see:** the script print `done` with no traceback.

```
ls -la askwell-test-material
```

**You should see:** `invoice-notes.txt`, a few KB.

### 2. Point Askwell at your files

If you have never run Askwell before:

```
cp -n .env.example .env
```

Open `.env`. Find `ASKWELL_ROOTS_MOUNT=` and set it to the folder you just created, with your own path:

```
ASKWELL_ROOTS_MOUNT=/home/you/external/quantum-plus/askwell/askwell-test-material
```

Find `POSTGRES_APP_PASSWORD` and put any word after the `=` if it is blank.

---

## Cold start

### 3. Remove any previous state

```
podman compose down -v
```

**You should see:** lines about containers and volumes being removed, or a note that there was nothing to remove.

### 4. Build the interface

```
scripts/dev.sh web-build
```

**You should see:** a Next.js build finishing with a route list and no red error text.

### 5. Run the checks

```
scripts/dev.sh check
```

**You should see:** lint, format, typecheck and test stages finish without red error text.

### 6. Bring the stack up

```
podman compose up -d
```

**You should see:** `postgres`, `redis`, `egress-proxy`, `api`, `worker` reported as started. Wait about thirty seconds.

### 7. Create the database tables

```
scripts/dev.sh db upgrade head
```

**You should see:** migration lines finish with no error, including `c7e2f814a5b3` in the printed chain.

### 8. Nominate the folder your material is in

Open a browser at:

```
http://127.0.0.1:8000
```

Click **Settings** in the left strip, scroll to **Folders Askwell may read**, type this into the **Nominate a folder** field — with your own path —

```
/home/you/external/quantum-plus/askwell/askwell-test-material
```

— and click **Nominate**.

**You should see:** a box appear showing that path, marked **Readable**.

---

## Part A — a chunk gets a populated full-text value, by clicking

### 9. Get to the add screen by clicking

Click **Ask** in the left strip.

**You should see:** the "Ask your own material" page, with an **Add a source** button.

Click **Add a source**.

**You should see:** the "Add a source" page, address bar ending in `/sources/add/`.

### 10. Drop the file

Open your file manager at `~/external/quantum-plus/askwell/askwell-test-material`. Drag `invoice-notes.txt` onto the window and release, type the folder with your own path when asked, and click **Add it**.

**You should see:** the card move to **Queued**, then a progress line as extraction and chunking run underneath it, then the card settle without red text (embedding will fail if no inference process is running — that is fine and expected here; extraction and chunking, which populate `content`, still complete first).

### 11. Confirm the chunks exist and carry a full-text value

```
scripts/dev.sh psql
```

```sql
SELECT count(*) AS total, count(content_tsv) AS with_tsv
FROM chunks
WHERE document_id = (SELECT id FROM documents WHERE filename = 'invoice-notes.txt');
```

**You should see:** `total` and `with_tsv` equal, both greater than zero — every chunk has a non-null full-text value, populated with no application code involved.

---

## Part B — the reference number, findable by its own trailing group

### 12. Query for the whole reference number

Still in `psql`:

```sql
SELECT id FROM chunks
WHERE document_id = (SELECT id FROM documents WHERE filename = 'invoice-notes.txt')
  AND content_tsv @@ plainto_tsquery('english', regexp_replace('INV-2024-0917', '-', ' ', 'g'));
```

**You should see:** one or more rows returned — the chunk containing the invoice sentence matches.

### 13. Query for just the trailing digit group someone would actually remember

```sql
SELECT id FROM chunks
WHERE document_id = (SELECT id FROM documents WHERE filename = 'invoice-notes.txt')
  AND content_tsv @@ plainto_tsquery('english', regexp_replace('0917', '-', ' ', 'g'));
```

**You should see:** the same row(s) as step 12. This is the exact fix `c7e2f814a5b3` made: before it, the parser read `-0917` as a signed lexeme and a bare `0917` never matched. Also try the middle group:

```sql
SELECT id FROM chunks
WHERE document_id = (SELECT id FROM documents WHERE filename = 'invoice-notes.txt')
  AND content_tsv @@ plainto_tsquery('english', regexp_replace('2024', '-', ' ', 'g'));
```

**You should see:** the same row(s) again.

### 14. See the tokenising directly

```sql
SELECT content_tsv FROM chunks
WHERE document_id = (SELECT id FROM documents WHERE filename = 'invoice-notes.txt')
LIMIT 1;
```

**You should see:** a `tsvector` printout containing `'0917':N`, `'2024':N` and `'inv':N` as separate lexemes (positions `N` vary) — never a single `'-0917'` token.

---

## Part C — re-indexing repopulates rather than duplicating

### 15. Re-add the same file to force a re-chunk

Back in the browser, on the add-source page, drag `invoice-notes.txt` onto the window a second time and click **Add it** again (or use **Try again** on the existing card if it is still visible and failed).

**You should see:** the card re-run extraction and chunking.

### 16. Confirm exactly one set of chunks for the document, not two

```sql
SELECT count(*) FROM chunks
WHERE document_id = (SELECT id FROM documents WHERE filename = 'invoice-notes.txt');
```

**You should see:** the same `total` as step 11, not double it. `chunk.py`'s own re-run behaviour (`M1-INDEX-ING-031`) deletes and reinserts a document's chunks rather than appending, and `content_tsv` — being generated — keeps up with that automatically.

---

## Part D — the index is actually used at scale, and the edge cases pass

A 300,000-row seed to make the planner prefer the index over a sequential scan is impractical to build by hand in this walkthrough. It is exactly what the automated suite does — run it and read its result:

### 17. Run the database-backed suite

```
scripts/dev.sh test-db
```

**You should see:** `api/tests/test_index_db_records.py` pass, including:

- `test_a_lexical_query_at_scale_uses_the_index` — seeds 300,000 filler chunks, runs `EXPLAIN`, and asserts `ix_chunks_content_tsv` appears in the plan and `Seq Scan` does not.
- `test_a_chunk_of_pure_numbers_or_codes_still_tokenises` — the pure-numbers-and-codes edge case.
- `test_a_very_long_chunk_indexes_without_error` — the very-long-chunk edge case, at the chunker's own 2,400-word bound.
- `test_a_chunk_with_no_content_is_not_considered_indexed` — a `NULL`-content chunk gets an empty, non-null vector rather than silently vanishing from every scan for the wrong reason.
- `test_reindexing_repopulates_rather_than_duplicating` — the same property Part C checked by hand, asserted directly against the database.

If any of these fail, the failure names which acceptance criterion broke — do not treat a passing `scripts/dev.sh check` (unmarked tests only, no database) as covering this ticket; `content_tsv` behaviour needs a real Postgres, hence `test-db`.

---

## Known gaps

- **No library screen and no search box.** `web/app/library/page.tsx` is still the placeholder empty state. There is no product surface yet where a person types a query and sees a matching chunk — this ticket's own acceptance criteria are about the column and the index, not a UI, and none exists to click through. Verification above stops at `psql`, the same as `M1-INDEX-ING-032`'s manual test did for embedding.
- **No lexical query in the running application.** Nothing in `api/` or `worker` yet issues a `plainto_tsquery` against `content_tsv` — that query only exists inside this document's own `psql` steps and inside the test suite's `_matches` helper. The real lexical half of hybrid retrieval, and its fusion with dense results, is `M1-ASK-RET-035`.
- **The corpus-scale index check is not walked through by hand.** Seeding 300,000 rows through the browser is not a reasonable manual step; Part D relies on the automated test instead, which is what actually proves the acceptance criterion ("the query plan uses the index rather than scanning at corpus scale").
- **The Tamil-aware full-text configuration is not exercised.** `c7e2f814a5b3` and the generated column both hardcode the `english` configuration, matching the ticket's own assumption — Tamil is a hedge, untested and unadvertised in v1.
- **The `well-known`-style compound-word cost is not demonstrated here.** `docs/decisions.md` (2026-08-28) records that the hyphen-to-space fix loses the single compound lexeme for a genuine hyphenated English word, keeping only its two halves indexed separately. This is an accepted trade-off, not a defect, and is not something this walkthrough reproduces since it does not change any pass/fail step above.
