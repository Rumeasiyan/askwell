# Manual test — M4-SQL-VAL-105, inject a row limit and make it visible in the shown SQL

**Ticket:** `M4-SQL-VAL-105` — a validated query with no top-level aggregate and no limit of its
own gets a row cap (`Settings.sql_row_limit`, default 1000) injected on the parsed tree, marked
in the disclosed SQL as added by Askwell and distinguishable from a limit the model wrote. A
result landing on or over the limit is labelled as showing the first N of possibly more.
**Version under test:** `0.4.20` (check `cat VERSION`).
**Time:** about 35 minutes, plus a first stack build.
**Who can run it:** a terminal, `podman compose exec` access to the `worker` container.

**What is being checked.** `api/src/askwell/sql/limit.py` (`inject_limit`, `_inject_limit_sync`,
`result_was_truncated`), backed by `api/tests/test_sql_limit.py` (pure, every shape the ticket
names) and `api/tests/test_sql_limit_db.py` (`requires_db`, the audit recording). This document
repeats the injection rules and the audit recording against a cold-started stack, which the
automated suite proves without ever starting a container.

**Where this stops on purpose — read before reporting anything below as a defect.**

- **Nothing in `web/` or `POST /ask` calls `inject_limit` yet.** `grep -rn "inject_limit"
  api/src web/` finds only the module and its own tests. `docs/ux/ask.md` §4's "Expand SQL"
  row and `docs/states-and-edge-cases.md` §4's "`LIMIT` auto-injected" row both describe a
  screen this ticket has nothing to plug into yet — issue #375 already tracks that no SQL
  execution path exists in `POST /ask` at all. This document calls
  `askwell.sql.limit.inject_limit` directly inside the running `worker` container, the same way
  `docs/manual-tests/M4-SQL-VAL-104.md` did for `validate_query` before it was wired anywhere.
- **A query is never itself generated here.** This ticket only caps and labels an
  already-`sqlglot`-accepted query — the queries below are typed by hand to stand in for
  whatever `validate_query` (`M4-SQL-VAL-104`) would have already passed.
- **No result set is actually fetched or truncated here.** `result_was_truncated` takes a row
  count and a limit as plain numbers — this document calls it with numbers chosen by hand, since
  the `EXPLAIN` dry run and real execution (`M4-SQL-VAL-106`, `sql_execute`) are separate,
  later work.
- **The setting is adjusted by editing `.env` and restarting, not from a settings screen.** No
  settings UI exposes `ASKWELL_SQL_ROW_LIMIT` yet — the ticket's "adjustable" acceptance
  criterion is satisfied at the configuration layer today.

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

### 4. Confirm the default row limit

```
grep ASKWELL_SQL_ROW_LIMIT .env
```

**You should see:** `ASKWELL_SQL_ROW_LIMIT=1000` (or absent, which also means 1000 — check
`.env.example`'s own comment above the line).

---

## 1. A plain read with no limit and no aggregate gets one

### 5. Submit a query with over a thousand candidate rows

```
podman compose exec worker python3 -c "
import asyncio
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory
from askwell.sql.limit import inject_limit

async def main():
    settings = Settings()
    engine = build_engine(settings)
    async with session_factory(engine)() as session:
        result = await inject_limit(
            session, settings, engine='postgresql',
            query='SELECT id, status FROM orders',
        )
        print(result.injected, result.limit)
        print(result.query)
        await session.commit()
    await engine.dispose()

asyncio.run(main())
"
```

**You should see:** `True 1000`, then the query text ending in something like
`LIMIT 1000 /* Added by Askwell */` — the injected limit is visible in the SQL, and the
trailing comment marks it as Askwell's, not the model's.

---

## 2. A query with an aggregate does not receive a limit

### 6. Submit a top-level COUNT

```
podman compose exec worker python3 -c "
import asyncio
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory
from askwell.sql.limit import inject_limit

async def main():
    settings = Settings()
    engine = build_engine(settings)
    async with session_factory(engine)() as session:
        result = await inject_limit(
            session, settings, engine='postgresql',
            query='SELECT COUNT(*) FROM orders',
        )
        print(result.injected, result.limit)
        print(result.query)
        await session.commit()
    await engine.dispose()

asyncio.run(main())
"
```

**You should see:** `False None`, and the printed query unchanged — `SELECT COUNT(*) FROM
orders` with no `LIMIT` added. This is the ticket's own "ask a counting question and confirm no
limit was added" scenario.

### 7. Confirm an aggregate nested in a subquery does not exempt the outer query

```
podman compose exec worker python3 -c "
import asyncio
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory
from askwell.sql.limit import inject_limit

async def main():
    settings = Settings()
    engine = build_engine(settings)
    async with session_factory(engine)() as session:
        result = await inject_limit(
            session, settings, engine='postgresql',
            query='SELECT * FROM (SELECT status, COUNT(*) AS n FROM orders GROUP BY status) sub',
        )
        print(result.injected, result.limit)
        await session.commit()
    await engine.dispose()

asyncio.run(main())
"
```

**You should see:** `True 1000` — the ticket's own edge case: the top-level result here is a
row set (one row per `status`), so it is limited even though the subquery aggregates.

---

## 3. An existing limit is left alone

### 8. Submit a query already limited to more than the default

```
podman compose exec worker python3 -c "
import asyncio
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory
from askwell.sql.limit import inject_limit

async def main():
    settings = Settings()
    engine = build_engine(settings)
    async with session_factory(engine)() as session:
        result = await inject_limit(
            session, settings, engine='postgresql',
            query='SELECT id FROM orders LIMIT 5000',
        )
        print(result.injected, result.limit)
        print(result.query)
        await session.commit()
    await engine.dispose()

asyncio.run(main())
"
```

**You should see:** `False 5000`, and the printed query unchanged — `LIMIT 5000` with no
`Added by Askwell` comment, because the disclosed SQL shows the model's own limit, not one
Askwell added.

### 9. Confirm the SQL:2008 `FETCH FIRST` form is also recognised as an existing limit

```
podman compose exec worker python3 -c "
import asyncio
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory
from askwell.sql.limit import inject_limit

async def main():
    settings = Settings()
    engine = build_engine(settings)
    async with session_factory(engine)() as session:
        result = await inject_limit(
            session, settings, engine='postgresql',
            query='SELECT id FROM orders ORDER BY id FETCH FIRST 10 ROWS ONLY',
        )
        print(result.injected, result.limit)
        print(result.query)
        await session.commit()
    await engine.dispose()

asyncio.run(main())
"
```

**You should see:** `False 10`, and `1000` nowhere in the printed query — this is issue #371's
regression check: an earlier version of this module recognised only `LIMIT n` and would have
silently overwritten this clause with the default, dropping the model's own cap.

---

## 4. A result landing on the limit is labelled the same as one that exceeded it

### 10. Check the boundary case by hand

```
podman compose exec worker python3 -c "
from askwell.sql.limit import result_was_truncated
print(result_was_truncated(row_count=1000, limit=1000))
print(result_was_truncated(row_count=7, limit=1000))
print(result_was_truncated(row_count=100000, limit=None))
"
```

**You should see:** `True`, `False`, `False` in that order — a result with exactly as many
rows as the limit is labelled as possibly truncated (the ticket's own "indistinguishable from
truncation" edge case), a result under the limit is not, and a result with no limit at all
(an aggregate, or one the model already capped past what disclosure needs) is never labelled.

---

## 5. Every injection is recorded; a left-alone query is not

### 11. Confirm Step 5's injection landed in the audit log

```
scripts/dev.sh psql -c "SELECT kind, payload FROM audit_interactions WHERE kind = 'sql_limit_injected' ORDER BY occurred_at DESC LIMIT 3;"
```

**You should see:** one row from Step 5 and one from Step 7, each `payload` containing the
`engine`, the fully limited `query` text, and `limit` matching what printed on screen — the
ticket's own Audit Requirement, recorded to `audit_interactions` (a per-question fact), not
`audit_decisions`.

### 12. Confirm Steps 6, 8 and 9 (left alone) were not recorded

```
scripts/dev.sh psql -c "SELECT count(*) FROM audit_interactions WHERE kind = 'sql_limit_injected' AND payload->>'query' LIKE '%COUNT%' OR payload->>'query' LIKE '%LIMIT 5000%' OR payload->>'query' LIKE '%FETCH FIRST%';"
```

**You should see:** `0` — a query left untouched (aggregate, or already limited) is never
written to the interactions store by this module.

---

## 6. The default is adjustable

### 13. Lower the limit and confirm the next query uses it

```
podman compose exec worker python3 -c "
import asyncio
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory
from askwell.sql.limit import inject_limit

async def main():
    settings = Settings(sql_row_limit=50)
    engine = build_engine(settings)
    async with session_factory(engine)() as session:
        result = await inject_limit(
            session, settings, engine='postgresql',
            query='SELECT id FROM orders',
        )
        print(result.injected, result.limit)
        print(result.query)
        await session.commit()
    await engine.dispose()

asyncio.run(main())
"
```

**You should see:** `True 50`, and `LIMIT 50` (not `1000`) in the printed query — confirming
this is read from `Settings` rather than a hardcoded constant. To exercise this the way a real
deployer would, set `ASKWELL_SQL_ROW_LIMIT=50` in `.env`, run `podman compose up -d` to restart
the `worker` container with the new value, and repeat Step 5 without passing `sql_row_limit`
explicitly — the result should be identical.

---

## 7. Injection happens on the parsed tree, never by string manipulation

### 14. Search the module's own source for string-based SQL construction

```
podman compose exec worker grep -n "query + \|f\"{query}\|query.rstrip\|query + \" LIMIT" /app/api/src/askwell/sql/limit.py
```

**You should see:** no output — the limit is set via `exp.Limit`/`statement.set("limit", ...)`
on the parsed tree and re-rendered with `.sql(dialect=...)`, never appended to the original
query text.

---

## 8. Clean up

Nothing was imported or connected for this document; `podman compose down -v` (Step 1's
command) is sufficient if you want to reset the stack afterwards. If you changed
`ASKWELL_SQL_ROW_LIMIT` in `.env` for Step 13, restore it to `1000` (or remove the line) and
restart the stack if you intend to run other manual tests afterwards.

---

## Known gaps

Not defects — deliberately not built by this ticket, or not built at all yet:

- **No UI or API route reaches `inject_limit`.** Asking a database question in the browser's
  ask screen never produces or limits a candidate SQL query today — it always answers from
  document retrieval, or abstains. `docs/ux/ask.md` §4's "Expand SQL" row and
  `docs/states-and-edge-cases.md` §4's "`LIMIT` auto-injected" row both have nothing to render
  from yet: wiring `generate_candidate_query` → `validate_query` → `inject_limit` →
  execution → the ask screen is later work, gated on `M4-SQL-VAL-106` (the `EXPLAIN` dry run)
  also landing first.
- **No settings screen exposes the row limit.** The ticket's "adjustable" criterion is met by
  `ASKWELL_SQL_ROW_LIMIT` in `.env` today; Step 13's `Settings(sql_row_limit=...)` in-process
  override stands in for a settings UI that does not exist yet.
- **No pagination beyond the limit.** A user cannot page into rows past the first N — the
  ticket's own Out of Scope, carried by `M4-RESULT-FE-109`.
- **The trace is not written here.** `askwell.traces.TraceRing.write` needs a live
  `message_id` that does not exist until a real turn calls this module; only the interactions
  record (Steps 11–12) is exercised, matching `validate.validate_query`'s own honesty about
  the same gap for `limit_injected`.
- **The `EXPLAIN` dry run and real query execution are separate, later work** (`M4-SQL-VAL-106`,
  `askwell.sql_execute`) and are not exercised here — Step 10's boundary check uses row counts
  typed by hand, not a fetched result set.
