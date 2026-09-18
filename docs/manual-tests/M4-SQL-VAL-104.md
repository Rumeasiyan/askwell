# Manual test — M4-SQL-VAL-104, parse generated SQL and reject anything that is not a single read

**Ticket:** `M4-SQL-VAL-104` — every candidate query is parsed with `sqlglot` and rejected
unless it is a single `SELECT`/`WITH` read, walking the whole parsed tree (not just the top
level) so a data-modifying CTE or a comment-hidden statement is caught the same way an
outright `DELETE` is. Every rejection is recorded with its reason. No regex anywhere in the
path.
**Version under test:** `0.4.16` (check `cat VERSION`).
**Time:** about 40 minutes, plus a first stack build.
**Who can run it:** a terminal, `podman compose exec` access to the `worker` container.

**What is being checked.** `api/src/askwell/sql/validate.py` (`validate_query`,
`_validate_sync`, `_check_parsed`), backed by `api/tests/test_sql_validate.py` (pure, every
hostile shape the ticket names, plus the regex-absence check) and
`api/tests/test_sql_validate_db.py` (`requires_db`, the audit recording). This document
repeats the hostile-shape rejections and the audit recording against a cold-started stack,
which the automated suite proves without ever starting a container.

**Where this stops on purpose — read before reporting anything below as a defect.**

- **Nothing in `web/` or `askwell.agent.sql_generate` calls `validate_query` yet.** `grep -rn
  "validate_query\|sql\.validate" api/src web/` finds only the module, its own tests, and a
  comment in `api/src/askwell/config.py` describing the setting this module reads. The module
  a candidate query already comes from, `askwell.agent.sql_generate.generate_candidate_query`
  (`M4-SQL-BE-103`), does not call this one — its own docstring says validation, `LIMIT`
  injection (`M4-SQL-VAL-105`) and the dry run (`M4-SQL-VAL-106`) come later. There is no "ask
  a database question" screen that produces a query for this module to reject; the ask screen
  (`M1-ASK-FE-039a`) exists and answers only from document retrieval today. This document calls
  `askwell.sql.validate.validate_query` directly inside the running `worker` container, the
  same way `docs/manual-tests/M4-SQL-DB-107.md` and `M4-SQL-BE-103.md` did for their own
  not-yet-wired modules.
- **A generated statement is never itself produced or run here.** This ticket is the gate, not
  the generator or the executor — the hostile SQL strings below are typed by hand to stand in
  for whatever a model might produce, exactly as the ticket's own Testing Notes describe
  ("through the eval fixtures or a test harness, submit each hostile statement shape").
- **Function side effects are only partly detectable.** `SELECT pg_terminate_backend(123)` is
  rejected because it is on the module's own denylist; a side-effecting function outside that
  list is not caught by this layer at all — the module's own docstring states this is the
  honest limit, not a gap in this ticket.

---

## Before you start

```
cd ~/external/quantum-plus/askwell
```

If you have never run Askwell before:

```
cp -n .env.example .env
```

Open `.env` and confirm every `?set ... in .env` placeholder has a real value.

---

## Cold start

### 1. Remove any previous state

```
podman compose down -v
```

**You should see:** containers and volumes reported removed, or a note there was nothing to
remove.

### 2. Bring the stack up and migrate

```
podman compose up -d
scripts/dev.sh db upgrade head
```

**You should see:** `postgres`, `sandbox`, `redis`, `egress-proxy`, `api`, `worker` all
reported created and started, migration finishing with no error.

### 3. Open Askwell and confirm nothing is alarmed

Open a browser at `http://127.0.0.1:8000`. **You should see:** the shell load with no alarm
banner. There is nothing to click for the rest of this document — see "Where this stops on
purpose" above.

---

## 1. A normal read passes

### 4. Submit a plain SELECT

```
podman compose exec worker python3 -c "
import asyncio
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory
from askwell.sql.validate import validate_query

async def main():
    settings = Settings()
    engine = build_engine(settings)
    async with session_factory(engine)() as session:
        result = await validate_query(
            session, settings, engine='postgresql',
            query='SELECT id, status FROM orders WHERE status = \'open\'',
        )
        print(result.accepted, result.reason, result.detail)
        await session.commit()
    await engine.dispose()

asyncio.run(main())
"
```

**You should see:** `True None None` — accepted, no rejection reason, nothing recorded.

---

## 2. Multiple statements: always rejected

### 5. Submit a read followed by a delete

```
podman compose exec worker python3 -c "
import asyncio
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory
from askwell.sql.validate import validate_query

async def main():
    settings = Settings()
    engine = build_engine(settings)
    async with session_factory(engine)() as session:
        result = await validate_query(
            session, settings, engine='postgresql',
            query='SELECT id FROM orders; DELETE FROM orders',
        )
        print(result.accepted, result.reason, result.detail)
        await session.commit()
    await engine.dispose()

asyncio.run(main())
"
```

**You should see:** `False RejectionReason.MULTIPLE_STATEMENTS ...` with a detail naming two
statements found — this is the ticket's own scenario: "a model produces a read followed by a
delete; the parser rejects the whole statement."

---

## 3. Data-modifying and definition statements: always rejected

### 6. Submit a bare DELETE

```
podman compose exec worker python3 -c "
import asyncio
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory
from askwell.sql.validate import validate_query

async def main():
    settings = Settings()
    engine = build_engine(settings)
    async with session_factory(engine)() as session:
        result = await validate_query(
            session, settings, engine='postgresql', query='DELETE FROM orders',
        )
        print(result.accepted, result.reason, result.detail)
        await session.commit()
    await engine.dispose()

asyncio.run(main())
"
```

**You should see:** `False RejectionReason.NOT_A_SINGLE_READ ...`.

### 7. Submit a DROP TABLE

Repeat Step 6's script with `query='DROP TABLE orders'`.

**You should see:** `False RejectionReason.NOT_A_SINGLE_READ ...`.

---

## 4. Nesting used to disguise a modification

### 8. Submit a data-modifying CTE with a SELECT on top

```
podman compose exec worker python3 -c "
import asyncio
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory
from askwell.sql.validate import validate_query

async def main():
    settings = Settings()
    engine = build_engine(settings)
    async with session_factory(engine)() as session:
        result = await validate_query(
            session, settings, engine='postgresql',
            query='WITH d AS (DELETE FROM orders RETURNING *) SELECT * FROM d',
        )
        print(result.accepted, result.reason, result.detail)
        await session.commit()
    await engine.dispose()

asyncio.run(main())
"
```

**You should see:** `False RejectionReason.WRITE_DETECTED ...`, mentioning a `Delete` found
inside the statement — this is the ticket's "nesting to disguise a modification" edge case made
concrete: the top-level node here genuinely is a `SELECT`, and it is still rejected because the
whole tree is walked, not just the top.

---

## 5. A comment cannot hide a second statement

### 9. Submit a read with a line comment that looks like it hides a drop

```
podman compose exec worker python3 -c "
import asyncio
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory
from askwell.sql.validate import validate_query

async def main():
    settings = Settings()
    engine = build_engine(settings)
    async with session_factory(engine)() as session:
        result = await validate_query(
            session, settings, engine='postgresql',
            query=\"SELECT * FROM orders WHERE 1 = 1 -- ; DROP TABLE orders\",
        )
        print(result.accepted, result.reason, result.detail)
        await session.commit()
    await engine.dispose()

asyncio.run(main())
"
```

**You should see:** `True None None` — accepted. This is correct, not a bypass: the text after
`--` is a genuine SQL comment to both `sqlglot` and any real database, so there was only ever
one statement here. Confirm the actually hostile shape — a real second statement after a
comment — is still caught:

```
podman compose exec worker python3 -c "
import asyncio
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory
from askwell.sql.validate import validate_query

async def main():
    settings = Settings()
    engine = build_engine(settings)
    async with session_factory(engine)() as session:
        result = await validate_query(
            session, settings, engine='postgresql',
            query='SELECT 1 /* looks harmless */; DELETE FROM orders',
        )
        print(result.accepted, result.reason, result.detail)
        await session.commit()
    await engine.dispose()

asyncio.run(main())
"
```

**You should see:** `False RejectionReason.MULTIPLE_STATEMENTS ...`.

---

## 6. A dialect-specific construct the parser cannot read

### 10. Submit a MySQL statement sqlglot cannot parse at all

```
podman compose exec worker python3 -c "
import asyncio
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory
from askwell.sql.validate import validate_query

async def main():
    settings = Settings()
    engine = build_engine(settings)
    async with session_factory(engine)() as session:
        result = await validate_query(
            session, settings, engine='mysql',
            query=\"SELECT * FROM orders INTO OUTFILE '/tmp/dump.csv'\",
        )
        print(result.accepted, result.reason, result.detail)
        await session.commit()
    await engine.dispose()

asyncio.run(main())
"
```

**You should see:** `False RejectionReason.UNPARSEABLE ...` — unparseable is treated as unsafe,
not passed through.

---

## 7. Every rejection is recorded with its reason

### 11. Confirm the last few rejections above landed in the audit log

```
scripts/dev.sh psql -c "SELECT kind, payload FROM audit_decisions WHERE kind = 'sql_rejected' ORDER BY occurred_at DESC LIMIT 5;"
```

**You should see:** five rows (Steps 5, 6, 7, 8, 10 — Step 9's accepted call recorded nothing),
each `payload` containing the offending `query` text verbatim, its `engine`, `reason` matching
what printed on screen, and a non-empty `detail` — the ticket's own Audit requirement, and the
signal a prompt regression would show up as if this were wired into generation.

### 12. Confirm the accepted query from Step 4 was not recorded

```
scripts/dev.sh psql -c "SELECT count(*) FROM audit_decisions WHERE kind = 'sql_rejected' AND payload->>'query' LIKE 'SELECT id, status FROM orders%';"
```

**You should see:** `0` — an accepted query is never written to the decisions store by this
module.

---

## 8. No regex anywhere in the path

### 13. Search the module's own source for regex use

```
podman compose exec worker grep -n "^import re\|re\.compile\|re\.match\|re\.search\|re\.fullmatch\|Pattern" /app/api/src/askwell/sql/validate.py
```

**You should see:** no output — `grep` finds nothing, confirming C2's "regex filtering is
never acceptable" holds in the shipped module, not merely in the test that checks it.

---

## 9. Clean up

Nothing was imported or connected for this document; `podman compose down -v` (Step 1's
command) is sufficient if you want to reset the stack afterwards. No manual cleanup is
required otherwise.

---

## Known gaps

Not defects — deliberately not built by this ticket, or not built at all yet:

- **No UI or API route reaches `validate_query`.** Asking a database question in the browser's
  ask screen never produces, rejects, or shows a candidate SQL query today — it always answers
  from document retrieval, or abstains. `docs/states-and-edge-cases.md`'s "Generated SQL
  rejected by `sqlglot`" row (the "I could not answer that safely" message with the SQL shown)
  has nothing to render from yet: this ticket is the gate itself, not the caller that shows the
  refusal. Wiring `generate_candidate_query` → `validate_query` → the ask screen is later work,
  gated on `M4-SQL-VAL-105`/`-106` also landing first per the module's own docstring.
- **Live-connection dialects (MySQL, MariaDB, SQL Server) are only spot-checked here.** Step 10
  exercises one MySQL-specific unparseable construct; `test_every_supported_engine_dialect_parses_a_plain_select`
  in the automated suite is the authoritative proof that a plain read parses under all four
  dialects.
- **Function side effects outside the denylist are not caught by this layer.** The module's own
  docstring names this as the honest limit, not a gap introduced by this ticket: the read-only
  database role (`M4-SQL-DB-107`) is what actually stops an unrecognised side-effecting
  function at the database, independently of this parser.
- **`LIMIT` injection and the `EXPLAIN` dry run are separate tickets** (`M4-SQL-VAL-105`,
  `-106`) and are not exercised here — this document tests the parse-and-reject gate alone.
