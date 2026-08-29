# Manual test — M3-STORE-BE-076, memory and schema notes: origin, confidence, supersession

**Ticket:** `M3-STORE-BE-076` — two stores (`memory`, general facts; `schema_notes`, tied to a source/table/column) that both carry origin, confidence and creation time, where a correction supersedes rather than overwrites, an inference never displaces a user-supplied fact, and deleting a source removes its schema notes while leaving general memory untouched.
**Version under test:** `0.3.2`
**Time:** about 45 minutes, plus a first stack build.
**Who can run it:** a terminal and a browser. No native inference needed — nothing here asks a question or generates an answer.

**What is being checked.** `api/src/askwell/memory.py`'s six functions against the real `memory` and `schema_notes` tables: `write_memory_fact` / `write_schema_note` (insert active, or discard an inference that arrives for a subject/position an active user-origin row already covers), `correct_memory_fact` / `correct_schema_note` (insert a new row, point the old one's `superseded_by` at it, leave the old row's own columns untouched), and `get_active_memory_facts` / `get_active_schema_notes` (only `superseded_by IS NULL` rows, user-origin before inferred, newer before older within each). `askwell.clarify.raise_candidates` already calls `write_memory_fact` for real, automatically, when an unreadable-scan trigger's inferred guess falls below the materiality bar — that is exercised here as ingestion, not as a direct function call. The `memory.source_id` column and its "learned from a deleted source" label (the 2026-08-30 migration `2ae457a0587a`) is this ticket's own addition to a table `M3-RAISE-BE-068` created.

**Where this stops on purpose.** There is no HTTP route for any of this. `api/src/askwell/app.py` and every module that calls `@app.get/post/delete` (`documents.py`, `sources.py`, `ask.py`, `ingest.py`, `retrieve.py`, `roots.py`, `setup.py`, `suggestions.py`) were grepped for this walkthrough — there is no `/memory`, `/schema-notes` or `/clarifications` endpoint anywhere, and `web/app/memory/page.tsx` is a placeholder empty state, not a screen (`M3-MEM-FE-083`, not built). Confirmed by grep: `correct_memory_fact`, `correct_schema_note`, `write_schema_note` and both `get_active_*` readers have **no caller anywhere in the running application** — only `clarify.raise_candidates` calls `write_memory_fact`, and only for the automatic `inferred` path. There is also no clarification-*answering* endpoint yet, so "answering a clarification" cannot be driven by clicking anything; this walkthrough calls the same function such an endpoint would call, the same way `M2-DELETE-BE-061`'s manual test drove deletion with `curl` and `M2-PARTIAL-BE-059`'s drove supersession with `psql`, before either had a caller.

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

**You should see:** lint, format, typecheck and test stages finish without red error text, including `api/tests/test_memory.py` (`test-db`, run separately below).

```
scripts/dev.sh test-db
```

**You should see:** `api/tests/test_memory.py`'s cases pass, alongside the rest of the database-backed suite.

### 4. Bring the stack up

```
podman compose up -d
```

**You should see:** `postgres`, `redis`, `egress-proxy`, `api`, `worker` reported as started. Wait about thirty seconds.

### 5. Create the database tables

```
scripts/dev.sh db upgrade head
```

**You should see:** migration lines finish with no error, including `2ae457a0587a` (`memory_source_id`).

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

### 7. Look at the Memory screen as it stands today

Click **Memory** in the left strip.

**You should see:** the placeholder empty state — a heading "Memory", one line saying what this screen is for, and a box reading "Empty until Askwell has asked you something. Every fact here will say whether you supplied it or Askwell inferred it." Nothing on this page is wired to the real `memory` table yet; the rest of this walkthrough reads the table directly.

---

## Part A — add a source, "answer a clarification" the only way it can be done today

### 8. Add a file, to get a real `source_id` through the normal path

```bash
scripts/dev.sh run python3 - <<'PY'
with open("/app/askwell-test-material/tender-files.txt", "w") as f:
    f.write("RFQ deadline is thirty days from the notice date.\n")
print("done")
PY
```

Click **Ask** in the left strip.

**You should see:** the "Ask your own material" page's empty-corpus state, and an **Add a source** button. Click it.

**You should see:** the "Add a source" page. Open your file manager at `~/external/quantum-plus/askwell/askwell-test-material`, drag `tender-files.txt` onto the window, confirm the folder, and click **Add it**.

**You should see:** the card move through **Queued**, extraction, chunking and embedding, and settle with no red error text.

### 9. Find the source id

```
scripts/dev.sh psql
```

```sql
SELECT id AS source_id, name FROM sources WHERE name = 'tender-files.txt';
```

**You should see:** one row. Copy `source_id` — you need it for the rest of Part A and Part C. Keep this `psql` session open in its own terminal.

### 10. "Answer a clarification" — write a full-confidence, user-origin fact

Nothing in the running product raises a real clarification for "RFQ" today (`M3-RAISE-BE-068`'s abbreviation trigger needs the token to repeat at least twice in the material, and this file uses it once). To exercise `write_memory_fact` exactly as a future "answer this clarification" endpoint would call it, run:

```bash
scripts/dev.sh run python3 - <<'PY'
import asyncio, uuid
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from askwell.config import get_settings
from askwell.memory import write_memory_fact, FULL_CONFIDENCE

SOURCE_ID = uuid.UUID("<source_id-from-step-9>")

async def main():
    settings = get_settings()
    engine = create_async_engine(settings.database_url.get_secret_value().replace("postgresql://", "postgresql+psycopg://", 1))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        fact_id = await write_memory_fact(
            session, subject="rfq", fact="Request for Quotation",
            origin="clarification", confidence=FULL_CONFIDENCE, source_id=SOURCE_ID,
        )
        await session.commit()
        print("fact_id:", fact_id)
    await engine.dispose()

asyncio.run(main())
PY
```

Replace `<source_id-from-step-9>` with the value from step 9.

**You should see:** `fact_id: <a uuid>`, not `None`.

### 11. Confirm it in the database

Back in the `psql` session:

```sql
SELECT subject, fact, origin, confidence, source_id, superseded_by FROM memory WHERE subject = 'rfq';
```

**You should see:** one row — `fact = 'Request for Quotation'`, `origin = 'clarification'`, `confidence = 1.000`, `source_id` matching step 9, `superseded_by = NULL`.

Also check the decision log (C6):

```sql
SELECT kind, payload FROM audit_decisions WHERE kind = 'memory_written' ORDER BY occurred_at DESC LIMIT 1;
```

**You should see:** one row, `payload` naming `subject: rfq`, `origin: clarification`.

---

## Part B — correcting supersedes; the old value stays readable

### 12. Correct the fact

```bash
scripts/dev.sh run python3 - <<'PY'
import asyncio, uuid
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from askwell.config import get_settings
from askwell.memory import correct_memory_fact

FACT_ID = uuid.UUID("<fact_id-from-step-10>")

async def main():
    settings = get_settings()
    engine = create_async_engine(settings.database_url.get_secret_value().replace("postgresql://", "postgresql+psycopg://", 1))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        new_id = await correct_memory_fact(session, fact_id=FACT_ID, fact="Request for Proposal, not Quotation")
        await session.commit()
        print("new_id:", new_id)
    await engine.dispose()

asyncio.run(main())
PY
```

**You should see:** `new_id: <a different uuid>`.

### 13. Confirm the old row is unchanged and the new one is active

```sql
SELECT id, fact, origin, superseded_by FROM memory WHERE subject = 'rfq' ORDER BY created_at;
```

**You should see:** two rows — the original, `fact = 'Request for Quotation'`, `superseded_by` = the new id (not `NULL` anymore, but its own `fact` text is unchanged); the new one, `fact = 'Request for Proposal, not Quotation'`, `origin = 'correction'`, `superseded_by = NULL`. Both rows are still there — this is supersession, not an overwrite.

### 14. Confirm a second correction resolves the chain to the newest

Repeat step 12 once more with `FACT_ID` set to the `new_id` from step 12 and a third value, e.g. `"Request for Proposal"`. Then in `psql`:

```sql
SELECT id, fact, superseded_by FROM memory WHERE subject = 'rfq' ORDER BY created_at;
```

**You should see:** three rows, chained (`superseded_by` of the first points to the second, the second to the third, the third `NULL`) — all three values still readable, and the third is the only one with no `superseded_by`.

---

## Part C — an inference never overwrites a user-supplied fact

### 15. Try to write an inferred fact for the same subject

```bash
scripts/dev.sh run python3 - <<'PY'
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from askwell.config import get_settings
from askwell.memory import write_memory_fact

async def main():
    settings = get_settings()
    engine = create_async_engine(settings.database_url.get_secret_value().replace("postgresql://", "postgresql+psycopg://", 1))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        result = await write_memory_fact(
            session, subject="rfq", fact="a low-confidence guess", origin="inferred", confidence=0.3,
        )
        await session.commit()
        print("result:", result)
    await engine.dispose()

asyncio.run(main())
PY
```

**You should see:** `result: None` — the write was discarded, not stored as a second, competing row.

### 16. Confirm nothing new landed, and the discard was logged

```sql
SELECT count(*) FROM memory WHERE subject = 'rfq' AND fact = 'a low-confidence guess';
```

**You should see:** `0`.

```sql
SELECT kind, payload FROM audit_decisions WHERE kind = 'memory_discarded' ORDER BY occurred_at DESC LIMIT 1;
```

**You should see:** one row, `payload` naming `subject: rfq`, `reason: active user-supplied fact already exists`.

### 17. Confirm retrieval-time precedence: user-origin before inferred, regardless of recency

```bash
scripts/dev.sh run python3 - <<'PY'
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from askwell.config import get_settings
from askwell.memory import write_memory_fact

async def main():
    settings = get_settings()
    engine = create_async_engine(settings.database_url.get_secret_value().replace("postgresql://", "postgresql+psycopg://", 1))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        # A fresh subject: no competing user fact, so this one is stored.
        result = await write_memory_fact(
            session, subject="quote-window", fact="a guess about the quote window", origin="inferred", confidence=0.3,
        )
        await session.commit()
        print("result:", result)
    await engine.dispose()

asyncio.run(main())
PY
```

**You should see:** `result: <a uuid>`, not `None` — a fresh subject with no user-origin fact stores an inference normally.

```sql
SELECT subject, origin FROM memory WHERE superseded_by IS NULL ORDER BY (origin != 'inferred') DESC, created_at DESC;
```

**You should see:** the `rfq` row (`origin = 'correction'`) listed before the `quote-window` row (`origin = 'inferred'`) even though `quote-window` was written later — user-origin sorts first regardless of recency.

---

## Part D — deleting the source: schema notes go, general memory survives and says so

### 18. Give the source a schema note directly

Nothing in this milestone produces a real schema note yet — Phase 3's SQL sandbox ingestion is what will actually write `schema_notes` rows (C2, C3). Insert one by hand, the same way `M2-DELETE-BE-061`'s manual test did, to exercise this ticket's own deletion handling of the table:

```sql
INSERT INTO schema_notes (source_id, table_name, column_name, description, origin)
VALUES ('<source_id-from-step-9>', 'invoices', 'due_date', 'When payment is expected.', 'user');
```

### 19. Delete the source through the running endpoint

```bash
curl -s -X DELETE "http://127.0.0.1:8000/sources/<source_id-from-step-9>" | python3 -m json.tool
```

**You should see:** `{"deleted": true, "source_id": "<source_id>", "documents_deleted": 1}`.

### 20. Confirm the schema note is gone and general memory survives, labelled

```sql
SELECT count(*) FROM schema_notes WHERE source_id = '<source_id-from-step-9>';
SELECT status, deleted_at FROM sources WHERE id = '<source_id-from-step-9>';
```

**You should see:** the schema-note count `0`; the source `status = 'deleted'` with `deleted_at` set.

Now confirm the memory fact whose `source_id` pointed at this source still resolves to a name and says the source is gone — this is `get_active_memory_facts`'s own join, so read it through the function rather than a raw `SELECT`:

```bash
scripts/dev.sh run python3 - <<'PY'
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from askwell.config import get_settings
from askwell.memory import get_active_memory_facts

async def main():
    settings = get_settings()
    engine = create_async_engine(settings.database_url.get_secret_value().replace("postgresql://", "postgresql+psycopg://", 1))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        for f in await get_active_memory_facts(session, subject="rfq"):
            print(f.subject, f.fact, f.source_name, f.source_deleted)
    await engine.dispose()

asyncio.run(main())
PY
```

**You should see:** `rfq Request for Proposal tender-files.txt True` — the fact still names the source it came from and now says it is deleted, rather than reading identically to a fact with no source at all.

### 21. Confirm a fact with no source at all is not mislabelled

```sql
SELECT count(*) FROM memory WHERE subject = 'quote-window';
```

Confirm via the same script pattern as step 20, subject `quote-window`: **you should see** `source_name = None`, `source_deleted = False` — never `True` for a fact that never had a source.

---

## Part E — an inference arriving for a schema position with an active user note is discarded

### 22. Add a second source and note, then try to write a competing inference

```sql
INSERT INTO sources (id, kind, name) VALUES (gen_random_uuid(), 'file', 'second-source') RETURNING id;
```

Copy the returned id as `<second_source_id>`, then:

```sql
INSERT INTO schema_notes (source_id, table_name, column_name, description, origin)
VALUES ('<second_source_id>', 'students', 'st_cd', 'Student status code.', 'user');
```

```bash
scripts/dev.sh run python3 - <<'PY'
import asyncio, uuid
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from askwell.config import get_settings
from askwell.memory import write_schema_note

SOURCE_ID = uuid.UUID("<second_source_id>")

async def main():
    settings = get_settings()
    engine = create_async_engine(settings.database_url.get_secret_value().replace("postgresql://", "postgresql+psycopg://", 1))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        result = await write_schema_note(
            session, source_id=SOURCE_ID, table_name="students", column_name="st_cd",
            description="a guess", origin="inferred", confidence=0.3,
        )
        await session.commit()
        print("result:", result)
    await engine.dispose()

asyncio.run(main())
PY
```

**You should see:** `result: None`.

```sql
SELECT count(*) FROM schema_notes WHERE source_id = '<second_source_id>' AND description = 'a guess';
```

**You should see:** `0` — discarded, not stored as a competing low-confidence entry.

---

## Cleanup

```
podman compose down -v
```

Restore `.env` if you changed anything beyond what **Before you start** asked for.

---

## Known gaps

- **Nothing in the running product calls most of this module.** `correct_memory_fact`, `correct_schema_note`, `write_schema_note`, `get_active_memory_facts` and `get_active_schema_notes` have no caller anywhere in `api/src/askwell/` outside `memory.py` itself and `api/tests/test_memory.py`. Only `write_memory_fact` is called for real, by `askwell.clarify.raise_candidates`, and only for the automatic `inferred` path. There is no "answer this clarification", "correct this fact", "add a schema note" or "view my memory" endpoint yet. This is expected — the memory screen is `M3-MEM-FE-083` and the clarification-answering endpoint is not this ticket's scope — but it means Parts A, B, C and E above call `askwell.memory` functions directly rather than through anything a user can click, which is the most this ticket's own scope can be exercised as of this version.
- **No real trigger in this walkthrough produced a genuine automatic inference.** The unreadable-scan trigger (`askwell.clarify._detect_unreadable_scans`) is the one path that calls `write_memory_fact` with `origin="inferred"` for real, and it needs a scanned PDF with `document_pages.ocr_confidence` set below threshold on a small fraction of pages — not practical to construct reliably in this walkthrough. Part C exercises the discard rule by calling `write_memory_fact` directly instead, which is the same code path `raise_candidates` calls internally.
- **The memory screen itself renders none of this.** `web/app/memory/page.tsx` is the fixed empty-state placeholder shown in step 7; it does not read the `memory` table, does not distinguish origins, and shows no history. That is `M3-MEM-FE-083`.
- **Export and cross-machine import are not exercised** — out of v1 scope per the ticket, and no code exists to test.
