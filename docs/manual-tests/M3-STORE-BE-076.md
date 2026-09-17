# Manual test — M3-STORE-BE-076, memory and schema notes with origin, confidence and supersession

**Ticket:** `M3-STORE-BE-076` — a dedicated write-side module (`askwell.memory`) for the
`memory` and `schema_notes` tables: writing, superseding (never overwriting in place), origin
and confidence semantics, retrieval-time precedence (user over inferred, later over earlier),
and an inference that is discarded outright rather than stored when an active user-supplied
fact already covers the same subject or schema position.
**Version under test:** `0.3.8`
**Time:** about 30 minutes, plus a first stack build. No native inference needed — nothing here
embeds, retrieves, or asks a question.
**Who can run it:** a terminal, `scripts/dev.sh psql`, and `scripts/dev.sh run python3` to call
the module's functions directly. **No browser interaction reaches this ticket's own code** — see
"Where this stops on purpose."

**What is being checked.** `askwell.memory` (`api/src/askwell/memory.py`): `write_memory_fact`/
`write_schema_note` (an inference is discarded when an active user-origin row already covers the
subject/position; a user-origin write retires any active inference for the same one),
`correct_memory_fact`/`correct_schema_note` (supersede an active user-origin row with a new
value — the old row is never updated in place and stays readable), `get_active_memory_facts`/
`get_active_schema_notes` (retrieval precedence: user-origin before inferred, newer before
older within each). Migration `2ae457a0587a` adds `memory.source_id`, nullable, `ON DELETE SET
NULL`, so a general fact can say which source taught it and keep saying so after that source is
soft-deleted. Every write, discard and supersession is an `audit_decisions` record (C6).

**Where this stops on purpose.** Nothing in the application calls this module yet. `clarify.py`
and `review.py` still write `memory`/`schema_notes` rows through their own inline `INSERT`
statements — unchanged by this ticket, recorded as a known follow-up in
`docs/decisions.md` (2026-09-17, "`M3-STORE-BE-076` rebuilt fresh..."). There is also no memory
screen (`M3-MEM-FE-083`, not built) and no clarification-answering UI that would call
`write_memory_fact` for you (`M3-REVIEW-FE-073` renders questions but nothing saves an answer
into `memory` through this module). So this walkthrough calls `askwell.memory`'s functions
directly, inside the API container, the same way `M3-RAISE-BE-071`'s Part F exercised
`column_distribution_evidence` before anything called it either. Every `psql` query below is
read-only or a scripted setup step, never a stand-in for a UI action that exists.

---

## Before you start

```
cd ~/external/quantum-plus/askwell
```

If you have never run Askwell before:

```
cp -n .env.example .env
```

Find `POSTGRES_APP_PASSWORD` in `.env` and put any word after the `=` if it is blank.
`ASKWELL_ROOTS_MOUNT` and the inference model path are not needed for this walkthrough — nothing
here ingests a document or asks a question.

---

## Cold start

### 1. Remove any previous state

```
podman compose down -v
```

**You should see:** lines about containers and volumes being removed, or a note there was
nothing to remove.

### 2. Run the checks

```
scripts/dev.sh check
```

**You should see:** lint, format, typecheck and test stages finish without red error text,
including `api/tests/test_memory.py`'s cases (`test_answering_a_clarification_writes_a_full_confidence_user_fact`,
`test_correcting_supersedes_and_the_old_value_stays_readable`,
`test_an_inference_never_overwrites_a_user_supplied_fact`,
`test_general_memory_survives_a_deleted_source_and_says_so`, and the rest).

### 3. Bring the stack up

```
podman compose up -d
```

**You should see:** `postgres`, `redis`, `egress-proxy`, `api`, `worker` reported as started.
Wait about thirty seconds.

### 4. Create the database tables

```
scripts/dev.sh db upgrade head
```

**You should see:** migration lines finish with no error, including `2ae457a0587a` (adds
`memory.source_id`). Confirm the column exists:

```
scripts/dev.sh psql
```

```sql
\d memory
```

**You should see:** a `source_id` column (`uuid`, nullable), plus a foreign key to `sources`
and an index `ix_memory_source_id`. Keep this `psql` session open in its own terminal for the
rest of the walkthrough.

### 5. Open the app and confirm the shell still loads

Open a browser at:

```
http://127.0.0.1:8000
```

**You should see:** the Askwell shell load with no sign-in prompt. This confirms the stack is
sane before testing code no screen in it reaches yet — nothing past this step uses the browser.

---

## Part A — answering a clarification writes a full-confidence, user-supplied fact

### 6. Write a fact the way answering a clarification would

```bash
scripts/dev.sh run python3 - <<'PY'
import asyncio
from askwell.config import Settings
from askwell.db import build_engine, session_factory
from askwell.db.engine import session_scope
from askwell.memory import FULL_CONFIDENCE, write_memory_fact

async def main() -> None:
    engine = build_engine(Settings())
    factory = session_factory(engine)
    async with session_scope(factory) as session:
        fact_id = await write_memory_fact(
            session,
            subject="rfq",
            fact="Request for Quotation",
            origin="clarification",
            confidence=FULL_CONFIDENCE,
        )
        print(fact_id)
    await engine.dispose()

asyncio.run(main())
PY
```

**You should see:** a printed UUID — no error.

### 7. Confirm it in the database directly

```sql
SELECT subject, fact, origin, confidence, superseded_by FROM memory WHERE subject = 'rfq';
```

**You should see:** one row — `fact = 'Request for Quotation'`, `origin = 'clarification'`,
`confidence = 1.00` (or `1`), `superseded_by` = `NULL`.

```sql
SELECT event_type, payload FROM audit_decisions WHERE payload->>'subject' = 'rfq';
```

**You should see:** one row, `event_type = 'memory_written'` — the write is itself a
decisions-store record (C6), whether or not anything downstream ever displays it.

---

## Part B — correcting supersedes; the old value stays readable

### 8. Correct the fact just written

```bash
scripts/dev.sh run python3 - <<'PY'
import asyncio
import uuid
from askwell.config import Settings
from askwell.db import build_engine, session_factory
from askwell.db.engine import session_scope
from askwell.memory import correct_memory_fact

FACT_ID = uuid.UUID("<the-id-from-step-6>")

async def main() -> None:
    engine = build_engine(Settings())
    factory = session_factory(engine)
    async with session_scope(factory) as session:
        new_id = await correct_memory_fact(
            session, fact_id=FACT_ID, fact="the acronym used on the tender forms for Request for Quotation"
        )
        print(new_id)
    await engine.dispose()

asyncio.run(main())
PY
```

Fill in `<the-id-from-step-6>` with the UUID step 6 printed. **You should see:** a new, different
UUID printed.

### 9. Confirm the old row is unchanged and the new one is active

```sql
SELECT id, fact, origin, superseded_by FROM memory WHERE subject = 'rfq' ORDER BY created_at;
```

**You should see:** two rows. The first (step 6's id): `fact = 'Request for Quotation'`,
unchanged, `superseded_by` = the second row's id. The second: `fact = 'the acronym used on the
tender forms for Request for Quotation'`, `origin = 'correction'`, `superseded_by` = `NULL`.
This is what "the old value remains readable in history" means concretely — the row was never
`UPDATE`d, only pointed past.

---

## Part C — a fact superseded twice resolves to the newest, and both prior values stay visible

### 10. Correct the same subject again

Repeat step 8's script, pointing `FACT_ID` at the id step 8 printed, with
`fact="RFQ — Request for Quotation"`.

**You should see:** a third UUID printed.

### 11. Walk the chain

```sql
SELECT id, fact, superseded_by FROM memory WHERE subject = 'rfq' ORDER BY created_at;
```

**You should see:** three rows, chained id → id → id → `NULL`. Only the last has
`superseded_by IS NULL`. All three values (`Request for Quotation`, the acronym-on-forms
sentence, `RFQ — Request for Quotation`) are still present — nothing was deleted or overwritten
at any step.

---

## Part D — an inference never overwrites a user-supplied fact

### 12. Try to write an inferred fact for the same subject

```bash
scripts/dev.sh run python3 - <<'PY'
import asyncio
from askwell.config import Settings
from askwell.db import build_engine, session_factory
from askwell.db.engine import session_scope
from askwell.memory import write_memory_fact

async def main() -> None:
    engine = build_engine(Settings())
    factory = session_factory(engine)
    async with session_scope(factory) as session:
        result = await write_memory_fact(
            session, subject="rfq", fact="a low-confidence guess", origin="inferred", confidence=0.3
        )
        print(result)
    await engine.dispose()

asyncio.run(main())
PY
```

**You should see:** `None` printed — nothing written.

### 13. Confirm nothing changed in the database and the discard was recorded

```sql
SELECT count(*) FROM memory WHERE subject = 'rfq' AND fact = 'a low-confidence guess';
```

**You should see:** `0`.

```sql
SELECT event_type, payload FROM audit_decisions WHERE payload->>'subject' = 'rfq' AND event_type = 'memory_discarded';
```

**You should see:** one row, `payload` naming the reason (`active user-supplied fact already
exists`) — the discard itself is a decisions-store record, not a silent no-op.

### 14. Confirm an inference for a genuinely new subject is stored normally

```bash
scripts/dev.sh run python3 - <<'PY'
import asyncio
from askwell.config import Settings
from askwell.db import build_engine, session_factory
from askwell.db.engine import session_scope
from askwell.memory import write_memory_fact

async def main() -> None:
    engine = build_engine(Settings())
    factory = session_factory(engine)
    async with session_scope(factory) as session:
        fact_id = await write_memory_fact(
            session, subject="cda", fact="likely a confidential disclosure agreement", origin="inferred", confidence=0.4
        )
        print(fact_id)
    await engine.dispose()

asyncio.run(main())
PY
```

**You should see:** a UUID printed — nothing already existed for `cda`, so the guess is stored.

```sql
SELECT origin, confidence FROM memory WHERE subject = 'cda';
```

**You should see:** `origin = 'inferred'`, `confidence = 0.40`.

---

## Part E — retrieval precedence: user before inferred, newer before older within each

### 15. Read every active fact back with no subject filter

```bash
scripts/dev.sh run python3 - <<'PY'
import asyncio
from askwell.config import Settings
from askwell.db import build_engine, session_factory
from askwell.db.engine import session_scope
from askwell.memory import get_active_memory_facts

async def main() -> None:
    engine = build_engine(Settings())
    factory = session_factory(engine)
    async with session_scope(factory) as session:
        for f in await get_active_memory_facts(session):
            print(f.subject, f.origin, f.fact)
    await engine.dispose()

asyncio.run(main())
PY
```

**You should see:** `rfq` (origin `correction`) listed before `cda` (origin `inferred`), even
though `cda` was written more recently — user-origin sorts first regardless of recency. If Parts
A–D above left more than these two subjects active, confirm by eye that every `correction`/
`clarification`/`manual` row precedes every `inferred` row in the printed order.

---

## Part F — general memory survives a deleted source and says so

### 16. Create a source and a fact that names it

```sql
INSERT INTO sources (id, kind, name) VALUES (gen_random_uuid(), 'file', 'tender-files') RETURNING id;
```

Note the returned id as `<source-id>`.

```bash
scripts/dev.sh run python3 - <<'PY'
import asyncio
import uuid
from askwell.config import Settings
from askwell.db import build_engine, session_factory
from askwell.db.engine import session_scope
from askwell.memory import write_memory_fact

SOURCE_ID = uuid.UUID("<source-id>")

async def main() -> None:
    engine = build_engine(Settings())
    factory = session_factory(engine)
    async with session_scope(factory) as session:
        fact_id = await write_memory_fact(
            session,
            subject="tender-close",
            fact="tenders close at noon on the stated date",
            origin="manual",
            source_id=SOURCE_ID,
        )
        print(fact_id)
    await engine.dispose()

asyncio.run(main())
PY
```

**You should see:** a UUID printed.

### 17. Soft-delete the source the way `askwell.sources.delete_source` does

```sql
UPDATE sources SET status = 'deleted', deleted_at = now() WHERE id = '<source-id>';
```

**You should see:** `UPDATE 1`.

### 18. Confirm the fact survives and now says it came from a deleted source

```bash
scripts/dev.sh run python3 - <<'PY'
import asyncio
from askwell.config import Settings
from askwell.db import build_engine, session_factory
from askwell.db.engine import session_scope
from askwell.memory import get_active_memory_facts

async def main() -> None:
    engine = build_engine(Settings())
    factory = session_factory(engine)
    async with session_scope(factory) as session:
        for f in await get_active_memory_facts(session, subject="tender-close"):
            print(f.fact, f.source_name, f.source_deleted)
    await engine.dispose()

asyncio.run(main())
PY
```

**You should see:** `tenders close at noon on the stated date tender-files True` — the fact is
still active, still names the source (`sources` rows are soft-deleted, never actually removed),
and `source_deleted` reads `True`.

---

## Part G — schema notes: writing, correcting, and inference discarded the same way

### 19. Write an inferred note, then a user note for the same position

```bash
scripts/dev.sh run python3 - <<'PY'
import asyncio
import uuid
from askwell.config import Settings
from askwell.db import build_engine, session_factory
from askwell.db.engine import session_scope
from askwell.memory import write_schema_note

SOURCE_ID = uuid.UUID("<source-id>")

async def main() -> None:
    engine = build_engine(Settings())
    factory = session_factory(engine)
    async with session_scope(factory) as session:
        inferred_id = await write_schema_note(
            session,
            source_id=SOURCE_ID,
            table_name="invoices",
            column_name="st_cd",
            description="a guess",
            origin="inferred",
            confidence=0.3,
        )
        user_id = await write_schema_note(
            session,
            source_id=SOURCE_ID,
            table_name="invoices",
            column_name="st_cd",
            description="invoice status: O=open, P=paid, W=written off",
            origin="user",
        )
        print("inferred", inferred_id)
        print("user", user_id)
    await engine.dispose()

asyncio.run(main())
PY
```

**You should see:** two different UUIDs printed.

### 20. Confirm the inferred note was retired, not left active alongside the user one

```sql
SELECT id, description, origin, superseded_by FROM schema_notes
WHERE source_id = '<source-id>' AND table_name = 'invoices' AND column_name = 'st_cd';
```

**You should see:** two rows — the inferred one with `superseded_by` pointing at the user one,
the user one with `superseded_by` = `NULL`.

### 21. Try to correct the inferred note directly — confirm it is rejected

```bash
scripts/dev.sh run python3 - <<'PY'
import asyncio
import uuid
from askwell.config import Settings
from askwell.db import build_engine, session_factory
from askwell.db.engine import session_scope
from askwell.memory import CannotCorrectInference, correct_schema_note

NOTE_ID = uuid.UUID("<the-inferred-note-id-from-step-19>")

async def main() -> None:
    engine = build_engine(Settings())
    factory = session_factory(engine)
    async with session_scope(factory) as session:
        try:
            await correct_schema_note(session, note_id=NOTE_ID, description="a better guess")
        except CannotCorrectInference:
            print("rejected, as expected")
    await engine.dispose()

asyncio.run(main())
PY
```

**You should see:** `rejected, as expected` — even a superseded inferred note (this one already
lost to the user note in step 19) cannot be "corrected"; `correct_schema_note` only accepts an
*active* `user`-origin row, and this one is neither.

---

## Part H — deleting a source removes its schema notes; general memory is untouched

This module does not delete anything itself — `askwell.sources.delete_source`
(`M2-DELETE-BE-061`) does the deleting. This part confirms the shape `get_active_schema_notes`/
`get_active_memory_facts` read back matches what that ticket's own manual test already
established, now specifically for the tables this ticket wrote to.

### 22. Delete the schema notes the way `delete_source` does

```sql
DELETE FROM schema_notes WHERE source_id = '<source-id>';
```

### 23. Confirm schema notes are gone, general memory is not

```bash
scripts/dev.sh run python3 - <<'PY'
import asyncio
import uuid
from askwell.config import Settings
from askwell.db import build_engine, session_factory
from askwell.db.engine import session_scope
from askwell.memory import get_active_memory_facts, get_active_schema_notes

SOURCE_ID = uuid.UUID("<source-id>")

async def main() -> None:
    engine = build_engine(Settings())
    factory = session_factory(engine)
    async with session_scope(factory) as session:
        notes = await get_active_schema_notes(session, source_id=SOURCE_ID)
        facts = await get_active_memory_facts(session, subject="tender-close")
        print("notes", len(notes))
        print("facts", len(facts), facts[0].fact if facts else None)
    await engine.dispose()

asyncio.run(main())
PY
```

**You should see:** `notes 0` and `facts 1 tenders close at noon on the stated date` — the
general fact from Part F is still there, still labelled as coming from the now-deleted source.

---

## Cleanup

```
podman compose down -v
```

Restore `.env` if you changed anything beyond what **Before you start** asked for.

---

## Known gaps

- **Nothing in the application calls this module.** `clarify.py` and `review.py` still write
  `memory`/`schema_notes` through their own inline `INSERT` statements, exactly as before this
  ticket (`docs/decisions.md`, 2026-09-17). Answering a real clarification on the
  `/clarifications` screen today does **not** go through `write_memory_fact` — this walkthrough
  calls it directly because nothing else does yet. Do not report that gap as a defect of this
  ticket; wiring the call sites over is explicitly named as a separate, smaller follow-up in the
  decision log, not done here.
- **No memory screen.** `M3-MEM-FE-083` (route `/memory`, `docs/ux/memory.md`) is not built.
  There is no way to see a fact, its origin marker, or its supersession history by clicking
  anything — every check above is a `psql` query or a printed value from a direct function call.
- **No import/export.** Cross-machine memory portability is explicitly out of this ticket's
  scope and not tested here.
- **No automatic expiry**, by design — `docs/memory-and-clarification.md` and the ticket's own
  description both state memory does not expire and supersession is manual. This walkthrough
  does not test for absence of expiry beyond not doing anything that would trigger it, since
  nothing in the code attempts to.
