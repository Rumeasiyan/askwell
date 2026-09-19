# Manual test — M5-TOOLS-BE-113, tool registry with the five exposed tools

**Ticket:** `M5-TOOLS-BE-113` — the agent's tool registry: `document_search`, `database_query`,
`schema_lookup`, `document_listing`, `current_date`, behind one shared contract (declared
`pydantic` arguments, a bounded result that states its own truncation, a trace step with a
duration, and every failure turned into a recoverable `ToolResult` rather than an exception).
**Version under test:** `0.4.27` (check `cat VERSION`).
**Time:** about 50 minutes, plus a first stack build and native inference running.
**Who can run it:** a browser, a terminal, `podman compose exec` access to the `api` container,
native `llama.cpp` inference running on the host (`scripts/dev.sh inference`).

**What is being checked.** `api/src/askwell/agent/tools.py` — `TOOLS`, `call_tool`, and the five
handlers — backed by `api/tests/test_tools.py` (pure: registry shape, argument validation, the
"a handler that raises becomes `failed`" guarantee) and `api/tests/test_tools_db.py`
(`requires_db`: `schema_lookup`/`document_listing`/`database_query` against real rows). This
document repeats that behaviour against a cold-started stack with real inference and a real
sandbox database, which the automated suite fakes or skips.

**Where this stops on purpose — read before reporting anything below as a defect.**

- **Nothing calls this registry from `POST /ask` or anywhere in `web/`.** `grep -rn
  "agent.tools\|agent\.tools" api/src web/` finds only the module and its own tests. The
  module's own docstring says the same: `M5-LOOP-BE-115` (the multi-step loop) is what will
  call a tool more than once per turn and feed a result back to the model — the same "do not
  wire ahead of the caller that does not exist yet" posture `M4-SQL-DB-107` and `M4-SQL-BE-103`
  both took about themselves. **There is no chat-style screen where typing a question causes a
  tool to run.** The Ask screen (`M1-ASK-FE-039a`) exists and answers normally through document
  retrieval and, since `M4-SQL-BE-108a`, the single-shot SQL turn — neither of those code paths
  goes through `askwell.agent.tools` at all; they are the pipelines this registry's own
  `document_search` and `database_query` handlers wrap a second time, for a caller that does not
  exist yet. This document calls `askwell.agent.tools.call_tool` directly inside the running
  `api` container, the same way `docs/manual-tests/M4-SQL-DB-107.md` and
  `docs/manual-tests/M4-SQL-BE-103.md` called their own not-yet-wired modules directly.
- **`database_query` is exercised against the sandbox (dump-backed) path only.** No live MySQL,
  MariaDB, or SQL Server connection runs in this stack — the same standing limitation
  `docs/manual-tests/M4-SQL-DB-107.md` and `M4-SQL-BE-103.md` both name for their own database
  sections.
- **Real inference is required** for `document_search` and `database_query` (both call
  `retrieve()`/`generate_candidate_query()`, which embed or generate with the real model). The
  exact passage ranking and generated query text are not guaranteed to be byte-identical between
  runs — what matters is that the right document and the right table/column are used, not exact
  wording.
- **The "enormous result, truncation stated" edge case is not reproduced live here.** Producing
  more than 50 schema notes or 50 documents by hand adds nothing this document's reader can see
  that the automated suite does not already assert exactly
  (`test_schema_lookup_states_its_own_truncation`,
  `test_document_listing_states_its_own_truncation` in `api/tests/test_tools_db.py`, both
  passing per the version under test). Named again in Known gaps rather than skipped silently.

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

### 1. Make a note to search and a dump to query

```
mkdir -p ~/askwell-test/material ~/askwell-test/dumps
cat > ~/askwell-test/material/lease-note.txt <<'EOF'
The Acme office lease renews on 2026-11-01. Rent is 4,200 per month.
Meridian Supplies has a separate, unrelated services agreement.
EOF

cat > ~/askwell-test/dumps/orders.sql <<'EOF'
--
-- PostgreSQL database dump
--
CREATE TABLE orders (
    id integer primary key,
    status text not null,
    total numeric
);
INSERT INTO orders VALUES
    (1, 'shipped', 100),
    (2, 'late', 250),
    (3, 'late', 90);
EOF
```

Open `.env`, find `ASKWELL_ROOTS_MOUNT=`, and set it to `~/askwell-test/material` (with your
real username in place of `~`).

---

## Cold start

### 2. Remove any previous state

```
podman compose down -v
```

**You should see:** containers and volumes reported removed, or a note there was nothing to
remove.

### 3. Bring the stack up, migrate, and start native inference

```
podman compose up -d
scripts/dev.sh db upgrade head
```

In a separate terminal, on the host:

```
scripts/dev.sh inference
```

**You should see:** `postgres`, `sandbox`, `redis`, `egress-proxy`, `api`, `worker` all reported
created and started; migration finishing with no error; the inference process logging that it
is listening on its socket.

### 4. Open Askwell and add the note, by clicking

Open a browser at `http://127.0.0.1:8000`. **You should see:** the shell load with no alarm
banner.

Click **Add a source**, drag `~/askwell-test/material/lease-note.txt` onto the window (or use
the browse button), and nominate `~/askwell-test/material` if asked. **You should see:**
**Queued**, then **Ready** within well under a minute — the note is short and needs no OCR.

### 5. Read back the document's source id

There is no screen showing this directly — see "Where this stops on purpose" above.

```
scripts/dev.sh psql -c \
  "SELECT s.id AS source_id, d.id AS document_id, d.filename, d.status FROM sources s JOIN documents d ON d.source_id = s.id WHERE d.filename = 'lease-note.txt';"
```

**You should see:** one row, `status = ready`. Note `source_id` — call it `$DOC_SOURCE_ID`
below.

```
export DOC_SOURCE_ID=<the source_id you just read>
```

---

## 1. `current_date` — no database or model needed

### 6. Call it with the wrong things passed for session/settings/client

```
podman compose exec api python3 -c "
import asyncio
from askwell.agent.tools import call_tool

async def main():
    result, step = await call_tool('current_date', {}, session=None, settings=None, client=None)
    print(result.ok, result.content)
    print(step.tool, step.outcome, step.duration_ms >= 0)

asyncio.run(main())
"
```

**You should see:** `True {'date': '...', 'datetime': '...'}` with today's real date, and
`current_date ok True` — the ticket's own point that this tool touches neither the database nor
the model, proven here by passing `None` for both and it still working.

---

## 2. `document_search` — finds the note, cites it, states its threshold

### 7. Ask a question the note answers

```
podman compose exec api python3 -c "
import asyncio
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory
from askwell.inference.client import InferenceClient
from askwell.agent.tools import call_tool

async def main():
    settings = Settings()
    engine = build_engine(settings)
    client = InferenceClient(settings)
    async with session_factory(engine)() as session:
        result, step = await call_tool(
            'document_search', {'query': 'when does the Acme lease renew?'},
            session=session, settings=settings, client=client,
        )
        print(result.ok, result.truncated)
        for p in result.content['passages']:
            print(p['filename'], p['page_from'], round(p['score'], 3), p['content'][:60])
        print('threshold', result.content['threshold'], 'reranked', result.content['reranked'])
        print(step.tool, step.outcome, step.duration_ms)
    await engine.dispose()

asyncio.run(main())
"
```

**You should see:** `True False`, at least one passage naming `lease-note.txt`, its `content`
containing the renewal date text, a `threshold` (the same `Settings.retrieval_score_threshold`
value, `0.65` unless changed), and `document_search ok` with a nonzero duration — the ticket's
own "declared shape, bounded result, trace step with duration" acceptance criterion.

### 8. Scope the same search to a source with nothing in it

```
podman compose exec api python3 -c "
import asyncio, uuid
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory
from askwell.inference.client import InferenceClient
from askwell.agent.tools import call_tool

async def main():
    settings = Settings()
    engine = build_engine(settings)
    client = InferenceClient(settings)
    async with session_factory(engine)() as session:
        result, step = await call_tool(
            'document_search', {'query': 'lease', 'source_id': str(uuid.uuid4())},
            session=session, settings=settings, client=client,
        )
        print(result.ok, result.content['passages'], result.content['total_candidates'])
    await engine.dispose()

asyncio.run(main())
"
```

**You should see:** `True [] 0` — scoping to a source with no indexed content returns an empty,
still-`ok` result rather than an error; `document_search` never raises for "nothing found".

---

## 3. `document_listing` — lists what was actually added

### 9. List documents for the note's source

```
podman compose exec api python3 -c "
import asyncio
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory
from askwell.agent.tools import call_tool

async def main():
    settings = Settings()
    engine = build_engine(settings)
    async with session_factory(engine)() as session:
        result, step = await call_tool(
            'document_listing', {'source_id': '$DOC_SOURCE_ID'},
            session=session, settings=settings, client=None,
        )
        print(result.ok, result.content['documents'], result.truncated)
        print(step.tool, step.outcome)
    await engine.dispose()

asyncio.run(main())
"
```

**You should see:** `True [{'filename': 'lease-note.txt', 'source_name': ..., 'status':
'ready', 'added_at': '...'}] False` — `document_listing` needs no inference client (`client=
None` above works, matching `_document_listing`'s signature never touching it).

---

## 4. `database_query` before any database is connected — `no_connection`

### 10. Ask a data question with nothing connected yet

```
podman compose exec api python3 -c "
import asyncio
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory
from askwell.inference.client import InferenceClient
from askwell.agent.tools import call_tool

async def main():
    settings = Settings()
    engine = build_engine(settings)
    client = InferenceClient(settings)
    async with session_factory(engine)() as session:
        result, step = await call_tool(
            'database_query', {'question': 'how many orders are late?'},
            session=session, settings=settings, client=client,
        )
        print(result.ok, result.error.code, result.error.message)
        print(step.tool, step.outcome)
    await engine.dispose()

asyncio.run(main())
"
```

**You should see:** `False no_connection No connected database can answer this question.` and
`database_query no_connection` — the ticket's own edge case, "the database query tool called
with no connection — returns the no-connection outcome", proved before any database exists at
all rather than only by a mocked test.

---

## 5. Import a dump, then `schema_lookup` and `database_query` succeed

### 11. Import the dump, by clicking

Back in the browser, click **Add a source**, then the **Database dump** card. Choose
`~/askwell-test/dumps/orders.sql`, nominate `~/askwell-test/dumps` if asked, and click
**Import**.

**You should see:** **Queued**, then **Imported** within well under a minute.

### 12. Answer the schema clarification, if one appears

Introspection (`M4-SCHEMA-ING-100`) may ask you to confirm the `orders.status` column. Click
through and confirm it as shown — this is what puts a real `schema_notes` row in the database
for `schema_lookup` to find.

### 13. Read back the dump's source id

```
scripts/dev.sh psql -c "SELECT id, status FROM sources WHERE name = 'orders.sql';"
```

**You should see:** one row, `status = ready`. Note the `id` — call it `$DB_SOURCE_ID`.

```
export DB_SOURCE_ID=<the id you just read>
```

### 14. `schema_lookup` returns the real notes

```
podman compose exec api python3 -c "
import asyncio
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory
from askwell.agent.tools import call_tool

async def main():
    settings = Settings()
    engine = build_engine(settings)
    async with session_factory(engine)() as session:
        result, step = await call_tool(
            'schema_lookup', {'source_id': '$DB_SOURCE_ID'},
            session=session, settings=settings, client=None,
        )
        print(result.ok, result.content['total_notes'])
        for n in result.content['notes']:
            print(n['table_name'], n['column_name'], n['description'])
    await engine.dispose()

asyncio.run(main())
"
```

**You should see:** `True` and a nonzero note count, with rows naming the `orders` table and its
columns (`status`, `total`, and whatever else introspection recorded) — real rows, not a
fixture.

### 15. `database_query` runs the full checked chain

```
podman compose exec api python3 -c "
import asyncio
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory
from askwell.inference.client import InferenceClient
from askwell.agent.tools import call_tool

async def main():
    settings = Settings()
    engine = build_engine(settings)
    client = InferenceClient(settings)
    async with session_factory(engine)() as session:
        result, step = await call_tool(
            'database_query', {'question': 'how many orders are late?'},
            session=session, settings=settings, client=client,
        )
        print(result.ok, result.truncated)
        print(result.content['engine'], result.content['query'])
        print(result.content['columns'], result.content['rows'], result.content['row_count'])
        print(step.tool, step.outcome, step.duration_ms)
    await engine.dispose()

asyncio.run(main())
"
```

**You should see:** `True False`, `postgresql`, a single `SELECT` referencing `orders` and
`status = 'late'` (or equivalent), and a result whose row count is `2` — the two rows this
dump's `orders` table actually has with `status = 'late'`. This is the full chain the ticket's
own docstring describes: generation → C2 validation → limit injection → dry run → execution,
called once as one `ToolResult` rather than five separate steps the caller has to assemble.

### 16. Confirm the query was recorded to the decisions log, and the turn to `audit_interactions`

```
scripts/dev.sh psql -c "SELECT payload FROM audit_decisions WHERE kind = 'sql_generated' ORDER BY occurred_at DESC LIMIT 1;"
scripts/dev.sh psql -c "SELECT engine, accepted FROM audit_interactions WHERE query_engine IS NOT NULL ORDER BY occurred_at DESC LIMIT 1;"
```

**You should see:** the same query text in both places — the ticket's own "Audit / Logging
Requirements: database calls also produce interaction records", not just a trace step in
memory.

---

## 6. Invalid arguments and an unknown tool name are structured errors, never a crash

### 17. Call `document_search` with a malformed `source_id`

```
podman compose exec api python3 -c "
import asyncio
from askwell.agent.tools import call_tool

async def main():
    result, step = await call_tool(
        'document_search', {'query': 'terms', 'source_id': 'not-a-uuid'},
        session=None, settings=None, client=None,
    )
    print(result.ok, result.error.code, 'errors' in result.error.detail)
    print(step.outcome)

asyncio.run(main())
"
```

**You should see:** `False invalid_arguments True` and `step.outcome == 'invalid_arguments'` —
never a traceback. This is the ticket's own edge case: "a tool called with invalid arguments —
returns a structured error the model can react to, rather than failing the turn."

### 18. Call a tool name that does not exist

```
podman compose exec api python3 -c "
import asyncio
from askwell.agent.tools import call_tool

async def main():
    result, step = await call_tool('delete_everything', {}, session=None, settings=None, client=None)
    print(result.ok, result.error.code)
    print(step.outcome)

asyncio.run(main())
"
```

**You should see:** `False not_found` and `step.outcome == 'not_found'` — the registry itself is
the boundary that refuses a sixth, unregistered tool, not something a caller has to check for
separately.

---

## 7. Clean up

### 19. Remove the throwaway files

```
rm -rf ~/askwell-test/material ~/askwell-test/dumps
```

---

## Known gaps

Not defects — deliberately not built by this ticket, or not built at all yet:

- **No caller reaches any of these five tools yet.** Typing a question into the Ask screen never
  goes through `askwell.agent.tools` — it uses the older, separate document-retrieval and
  single-shot SQL pipelines this registry's own handlers wrap a second time for a caller
  (`M5-LOOP-BE-115`) that does not exist yet. Every step above calls `call_tool` directly inside
  the `api` container because there is nothing to click or curl that reaches this module.
- **No loop, so no multi-tool turn.** A question needing both `document_search` and
  `database_query` in the same turn (the ticket's own real-world example, "overdue invoices for
  a named supplier") cannot be demonstrated end to end — each tool above is called once, on its
  own, by hand.
- **`database_query`'s live-connection path (MySQL/MariaDB/SQL Server) is untested here.** No
  instance of any of those three engines runs in this stack; this document exercises the sandbox
  (dump-backed) path only, the same standing gap named in `docs/manual-tests/M4-SQL-DB-107.md`
  and `M4-SQL-BE-103.md`.
- **The "enormous result, truncation stated" edge case for `schema_lookup`/`document_listing`
  is proven by the automated suite only** (`api/tests/test_tools_db.py`), not reproduced by hand
  above — see "Where this stops on purpose".
- **Local per-tool counters (the ticket's own "Analytics Events") do not exist yet.** `grep -rn
  "tool_call" api/src/askwell/agent/tools.py` finds the `log.warning` on a handler failure and
  nothing else — no Redis counter is incremented per tool call the way `M4-SQL-DB-107`'s
  `askwell:sql:statement_timeouts` is for a timeout. Filed as
  [#404](https://github.com/Rumeasiyan/askwell/issues/404) rather than fixed informally here.
