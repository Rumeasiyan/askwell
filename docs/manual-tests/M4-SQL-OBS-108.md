# Manual test — M4-SQL-OBS-108, record executed and rejected SQL with reasons

**Ticket:** `M4-SQL-OBS-108` — every query `askwell.sql.validate.validate_query` looks at,
accepted or rejected, is one `audit_interactions` record carrying the engine, source, the
full query text, whether it validated, the rejection reason where there is one, and
`limit_injected`/`rows`/`duration_ms`. A local rejection rate is computable over a window. The
log chain still verifies.
**Version under test:** `0.4.17` (check `cat VERSION`).
**Time:** about 35 minutes, plus a first stack build.
**Who can run it:** a terminal, `podman compose exec` access to the `worker` container.

**What is being checked.** `api/src/askwell/sql/validate.py` (`validate_query`, now writing to
`Store.INTERACTIONS` under `kind = "sql_query"` instead of `M4-SQL-VAL-104`'s original
`Store.DECISIONS`/`"sql_rejected"` — `docs/decisions.md`, 2026-09-18, explains why) and
`api/src/askwell/sql/observability.py` (`sql_rejection_rate`), backed by
`api/tests/test_sql_validate_db.py` (`requires_db`: every named rejection reason recorded,
an accepted query recorded too, a very long query stored in full, a credential-looking literal
stored verbatim, the rejection rate over a window, the interaction chain still verifying). This
document repeats those against a cold-started stack, which the automated suite proves without
ever starting a container.

**Where this stops on purpose — read before reporting anything below as a defect.**

- **Nothing in `web/` or `askwell.agent.sql_generate` calls `validate_query` yet.** `grep -rn
  "validate_query\|sql\.validate" api/src web/` finds only the module, its own tests, and a
  comment in `api/src/askwell/config.py`. There is no "ask a database question" screen that
  produces a candidate query for this module to record — the ask screen (`M1-ASK-FE-039a`)
  answers only from document retrieval or abstains today, and `messages.trace` has no `"sql"`
  step yet (`docs/decisions.md`, this date, files that gap as
  [#373](https://github.com/Rumeasiyan/askwell/issues/373)). This document calls
  `askwell.sql.validate.validate_query` and `askwell.sql.observability.sql_rejection_rate`
  directly inside the running `worker` container, the same way `M4-SQL-VAL-104.md` did for the
  same not-yet-wired module.
- **A generated statement is never itself produced or run here.** The queries below are typed
  by hand to stand in for whatever a model might produce — the gate and its recording are what
  this ticket adds, not the generator.
- **This is inspectable only through the log.** No trace screen exists until M5; the ticket's
  own "Known gaps" says so.

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

## 1. A handful of generated-question stand-ins: two accepted, one rejected

### 4. Submit two plain reads and one crafted rejection

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
        for query in (
            'SELECT id, status FROM orders WHERE status = \'open\'',
            'SELECT customer_id, sum(total) FROM orders GROUP BY customer_id',
            'SELECT id FROM orders; DELETE FROM orders',
        ):
            result = await validate_query(
                session, settings, engine='postgresql', query=query,
            )
            print(query, '->', result.accepted, result.reason, result.detail)
        await session.commit()
    await engine.dispose()

asyncio.run(main())
"
```

**You should see:** the first two lines print `True None None`; the third prints
`False RejectionReason.MULTIPLE_STATEMENTS ...` — this is the ticket's own scenario, a
question crafted to produce a rejection alongside ordinary answered ones.

---

## 2. Every outcome landed in the interaction log, not just the rejection

### 5. Confirm all three rows are in `audit_interactions`

```
scripts/dev.sh psql -c "SELECT payload ->> 'query' AS query, payload ->> 'validated' AS validated, payload ->> 'rejection_reason' AS reason FROM audit_interactions WHERE kind = 'sql_query' ORDER BY id;"
```

**You should see:** three rows — the two accepted queries with `validated = true` and
`reason` empty, the third with `validated = false` and `reason = multiple_statements`. This is
the ticket's headline change from `M4-SQL-VAL-104`: an **accepted** query is now recorded too,
not only a rejection.

### 6. Confirm the rejected row's reason and query text are both present

```
scripts/dev.sh psql -c "SELECT payload ->> 'query', payload ->> 'detail' FROM audit_interactions WHERE kind = 'sql_query' AND payload ->> 'validated' = 'false';"
```

**You should see:** the full `SELECT id FROM orders; DELETE FROM orders` text and a non-empty
detail naming two statements found — the ticket's "confirm a rejected query's text and reason
are both present" testing note.

### 7. Confirm the fields not yet wired are recorded honestly, not invented

```
scripts/dev.sh psql -c "SELECT payload ->> 'limit_injected', payload ->> 'rows', payload ->> 'duration_ms' FROM audit_interactions WHERE kind = 'sql_query' ORDER BY id;"
```

**You should see:** `null` in all three columns, all three rows — limit injection
(`M4-SQL-VAL-105`) and execution are not wired to a live turn, so this stage records what it
actually knows rather than a guessed `0`.

---

## 3. A very long query is stored in full

### 8. Submit a query with a long `IN (...)` list

```
podman compose exec worker python3 -c "
import asyncio
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory
from askwell.sql.validate import validate_query

async def main():
    settings = Settings()
    engine = build_engine(settings)
    long_list = ', '.join(str(n) for n in range(20000))
    query = f'SELECT id FROM orders WHERE id IN ({long_list})'
    async with session_factory(engine)() as session:
        result = await validate_query(session, settings, engine='postgresql', query=query)
        print(result.accepted, len(query))
        await session.commit()
    await engine.dispose()

asyncio.run(main())
"
```

**You should see:** `True` and the query's character length printed (a large number).

### 9. Confirm the stored text is the same length, not truncated

```
scripts/dev.sh psql -c "SELECT length(payload ->> 'query') FROM audit_interactions WHERE kind = 'sql_query' ORDER BY id DESC LIMIT 1;"
```

**You should see:** the same length step 8 printed — the ticket's own "truncating the thing
you are trying to diagnose defeats the purpose" edge case, checked, not assumed.

---

## 4. A query containing a credential-looking literal is stored verbatim

### 10. Submit a query with a fake token in a literal

```
podman compose exec worker python3 -c "
import asyncio
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory
from askwell.sql.validate import validate_query

async def main():
    settings = Settings()
    engine = build_engine(settings)
    query = \"SELECT * FROM api_tokens WHERE token = 'sk-ABC123XYZ-not-a-real-secret'\"
    async with session_factory(engine)() as session:
        result = await validate_query(session, settings, engine='postgresql', query=query)
        print(result.accepted)
        await session.commit()
    await engine.dispose()

asyncio.run(main())
"
```

**You should see:** `True`.

### 11. Confirm the literal was not redacted or scrubbed

```
scripts/dev.sh psql -c "SELECT payload ->> 'query' FROM audit_interactions WHERE kind = 'sql_query' ORDER BY id DESC LIMIT 1;"
```

**You should see:** the query printed with `sk-ABC123XYZ-not-a-real-secret` in place, exactly
as submitted. This is not the same claim as "a real credential can appear here" — generation
only ever draws on schema notes and memory, which never contain a connection's own stored
credential; this step confirms the storage layer does not scrub a literal that merely looks
like one.

---

## 5. The local rejection rate reflects what actually happened

### 12. Compute the rate over everything recorded so far

```
podman compose exec worker python3 -c "
import asyncio
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory
from askwell.sql.observability import sql_rejection_rate

async def main():
    settings = Settings()
    engine = build_engine(settings)
    async with session_factory(engine)() as session:
        print(await sql_rejection_rate(session))
    await engine.dispose()

asyncio.run(main())
"
```

**You should see:** `SqlRejectionRate(covered=5, rejected=1)` — the five queries submitted
across steps 4, 8 and 10, one of which was rejected. This is the ticket's own worked example in
miniature: a rejection rate that reflects real recorded outcomes, not an assumption.

### 13. Push the rate toward the ticket's own "2% to 18%" scenario

Submit four more rejections of the same shape as step 4's third query:

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
        for _ in range(4):
            await validate_query(
                session, settings, engine='postgresql', query='DROP TABLE orders',
            )
        await session.commit()
    await engine.dispose()

asyncio.run(main())
"
```

Then repeat step 12's command.

**You should see:** `SqlRejectionRate(covered=9, rejected=5)` — a visibly worse rate than
step 12's, the same shape as the ticket's "after a prompt change the rejection rate goes from
two percent to eighteen" example: the number moved because real rejections were recorded, not
because anything was recomputed against today's rules.

### 14. Compute the rate over a narrower window

```
podman compose exec worker python3 -c "
import asyncio
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory
from askwell.sql.observability import sql_rejection_rate

async def main():
    settings = Settings()
    engine = build_engine(settings)
    async with session_factory(engine)() as session:
        print(await sql_rejection_rate(session, window=3))
    await engine.dispose()

asyncio.run(main())
"
```

**You should see:** `SqlRejectionRate(covered=3, rejected=3)` — the three most recent rows
(the last three of step 13's `DROP TABLE` submissions), all rejected. `covered=3` tells you
plainly that only 3 of the 9 recorded rows were actually read for this call.

### 15. Confirm the rate reports nothing, not zero, with an empty log

```
scripts/dev.sh psql -c "TRUNCATE audit_interactions, audit_decisions CASCADE;"
```

```
podman compose exec worker python3 -c "
import asyncio
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory
from askwell.sql.observability import sql_rejection_rate

async def main():
    settings = Settings()
    engine = build_engine(settings)
    async with session_factory(engine)() as session:
        print(await sql_rejection_rate(session))
    await engine.dispose()

asyncio.run(main())
"
```

**You should see:** `SqlRejectionRate(covered=0, rejected=0)`, and `.rate` on that value is
`None` (checked directly by `test_rejection_rate_is_none_with_nothing_validated_yet`, not
observable from this printed form) — a `0.0` here would wrongly claim a healthy prompt that
was never exercised.

---

## 6. The log chain still verifies

### 16. Submit a fresh mix and verify

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
        for query in ('SELECT id FROM orders', 'DELETE FROM orders', 'SELECT 1'):
            await validate_query(session, settings, engine='postgresql', query=query)
        await session.commit()
    await engine.dispose()

asyncio.run(main())
"
```

```
podman compose exec api askwell-verify
```

**You should see:** both chains reported intact — the interactions chain covering the new
`sql_query` rows just written alongside anything else in the log, not a separate or weaker
store for this path.

---

## 7. Clean up

Nothing was imported or connected for this document; `podman compose down -v` (Step 1's
command) is sufficient if you want to reset the stack afterwards. No manual cleanup is
required otherwise.

---

## Known gaps

Not defects — deliberately not built by this ticket, or not built at all yet:

- **No UI or API route reaches `validate_query` or `sql_rejection_rate`.** Asking a database
  question in the browser's ask screen never produces, rejects, or shows a candidate SQL query
  today — it always answers from document retrieval, or abstains. This document calls both
  functions directly inside the running `worker` container, the same posture
  `M4-SQL-VAL-104.md` took for the same not-yet-wired module.
- **No `"sql"` trace step exists on `messages.trace`.** The ticket's Scope names "the same
  fields in the trace for the trace screen in M5"; `docs/decisions.md` (2026-09-18) records why
  that half is deferred — `askwell.ask._run_generation` never calls `sql_generate`/`validate`
  today, so there is no live turn to attach a trace step to — and files the gap as
  [#373](https://github.com/Rumeasiyan/askwell/issues/373). There is no trace screen to look at
  yet regardless (M5); this is inspectable only through the log, exactly as the ticket's own
  Known Gaps note says.
- **`limit_injected`, `rows` and `duration_ms` are always recorded as `null`.** Limit injection
  (`M4-SQL-VAL-105`) and execution (`askwell.sql_execute`) are not wired to a live turn yet, so
  this ticket honestly records what it knows at the validation stage rather than inventing
  values for stages that have not run.
- **A generated statement is never itself produced here.** The hostile and benign query strings
  above stand in for whatever a model might produce; generation itself is `M4-SQL-BE-103`'s
  concern, already covered by its own manual test.
