# Manual test — M4-SQL-BE-108a, run the validated query and store its result with the answer

**Ticket:** `M4-SQL-BE-108a` — the last stage of the checked SQL path (generate → validate →
limit → dry run → **execute**) actually runs the query, under the read-only role and statement
timeout, and stores what it returned — columns, rows, row count, whether the row limit
truncated it, elapsed time — on the `messages` row, so a re-opened conversation shows the same
rows rather than re-running against a database that has moved on.
**Version under test:** `0.4.23` (check `cat VERSION`).
**Time:** about 45 minutes, plus a first stack build.
**Who can run it:** a browser, a terminal, `podman compose exec` access to the `postgres` and
`worker` containers.

**What is being checked.** `api/src/askwell/sql/execute.py` (`execute_checked_sandbox_query`,
`execute_checked_connection_query`, `ExecuteResult`), the `messages.sql_result` column added by
`api/src/askwell/db/migrations/versions/20260919_7f40fa52d49d_messages_sql_result.py`, and
`_run_sql_turn`/`_run_generation` in `api/src/askwell/ask.py` — the wiring that makes `POST
/ask` try a connected database before falling through to document retrieval, and that persists
`sql_result` on the assistant row so `GET /ask/{message_id}/stream` and `_load_finished` read
the same rows back rather than asking the database again. `api/tests/test_sql_execute_checked_db.py`
and `api/tests/test_ask_sql.py` (both `requires_db`) are the authoritative automated proof; this
document repeats the same shape against a real, disposable table and a real running stack.

**Where this stops on purpose — read before reporting anything below as a defect.**

- **No local model runs in this environment**, the same standing limitation every ticket since
  `M0-MODEL-BE-019` has recorded (`docs/manual-tests/M1-ASK-API-038.md` Part 2). `_run_sql_turn`'s
  first step, `generate_candidate_query`, calls the inference client to turn the question into
  SQL — with no model to answer it, that call raises `InferenceUnavailable`, `_run_sql_turn`'s
  caller catches it, and the turn falls through to document retrieval, which then fails the same
  way. What a browser *can* show today is the new step this ticket's wiring adds
  (`"Checking your connected databases."`) landing before that failure — proof the path is
  wired, not proof a query ran. To see a query actually execute and its result actually get
  stored, this document drives `askwell.ask._run_sql_turn` directly inside the `worker`
  container with a fake inference client standing in for the model, exactly as
  `api/tests/test_ask_sql.py` does — the same pattern `docs/manual-tests/M4-SQL-VAL-106.md` and
  `M4-CONN-BE-099.md` used for their own not-yet-model-reachable halves.
- **`M4-RESULT-FE-109` (rendering a result table) does not exist.** Nothing under `web/` reads
  `sql_result` — `grep -rln "sql_result" web/` finds nothing. The **Ask** screen has no path
  today that shows a returned row anywhere; this document confirms the value lands in the
  database and comes back from the stream endpoints, not that a person sees a table.
- **Only the sandbox (dump) execution path is exercised end-to-end here.** The live-connection
  half (`execute_checked_connection_query`) is proven by the automated `requires_db` suite
  against a disposable role in the same Postgres server, the same approach
  `docs/manual-tests/M4-CONN-BE-099.md` took; this document does not repeat setting up a second
  live connection on top of the sandbox one.

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
reported created and started, migration finishing with no error — including this ticket's own
`7f40fa52d49d` revision.

```
scripts/dev.sh psql -c "\d messages" | grep sql_result
```

**You should see:** `sql_result | jsonb` — the column this ticket's migration added.

### 3. Open Askwell and confirm nothing is alarmed

Open a browser at `http://127.0.0.1:8000`. **You should see:** the shell load with no alarm
banner.

---

## 1. The wiring is visible from the Ask screen, even with no model

### 4. Ask any question and watch the step sequence

Click into the ask box on the home screen (or navigate to it from the shell), type a question —
for example "What does the handbook say about notice periods?" — and submit it.

**You should see:** a step labelled **"Checking your connected databases."** appear first,
before the turn ends in a failure state naming the assistant as unavailable. That step did not
exist before this ticket wired `_run_sql_turn` into `_run_generation` — every question now
checks for a connected database before falling through to document retrieval, whether or not
one is connected.

### 5. Confirm the same thing from the stream directly

```
curl -s -c /tmp/cookies.txt -o /dev/null -H "accept: text/html" http://127.0.0.1:8000/
curl -s -b /tmp/cookies.txt -X POST http://127.0.0.1:8000/ask \
  -H 'content-type: application/json' \
  -d '{"question":"What does the handbook say about notice periods?"}'
```

**You should see:** an `event: step` line with `"label": "Checking your connected databases."`,
`"kind": "sql"`, ahead of the terminal `event: done` whose `status` is `"failed"`.

---

## 2. A real query executes and its result is stored

There is no dump-import or live-connection UI path in this environment that ends with a model
generating a query (see "Where this stops on purpose" above), so this section builds a sandbox
database exactly as ingestion would have left one, and drives the checked path with a query
standing in for what the model would have generated — the same substitution
`api/tests/test_ask_sql.py` makes.

### 6. Create a sandbox database with data to query

```
podman compose exec worker python3 -c "
import asyncio
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory
from askwell.sandbox import OWNER_ROLE, create_database, generate_name
import psycopg

async def main():
    settings = Settings()
    engine = build_engine(settings)
    async with session_factory(engine)() as session:
        name = generate_name()
        admin_url = settings.sandbox_database_url.get_secret_value()
        await create_database(session, admin_url, name)
        await session.commit()
        with open('/tmp/exec-manual-db.txt', 'w') as f:
            f.write(name)

        owner_dsn = admin_url.rsplit('/', 1)[0] + f'/{name}'
        with psycopg.connect(owner_dsn, autocommit=True) as conn:
            conn.execute('CREATE TABLE invoices (id int, status text)')
            conn.execute(
                \"INSERT INTO invoices VALUES (1,'unpaid'),(2,'paid'),(3,'unpaid'),(4,'unpaid')\"
            )
        print('sandbox database:', name)
    await engine.dispose()

asyncio.run(main())
"
```

**You should see:** `sandbox database: <name>` with no error.

### 7. Register it as a `dump` source, the same shape a real import leaves

```
podman compose exec worker python3 -c "
import asyncio, uuid
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory
from askwell.memory import write_schema_note
from sqlalchemy import text

async def main():
    settings = Settings()
    engine = build_engine(settings)
    async with session_factory(engine)() as session:
        with open('/tmp/exec-manual-db.txt') as f:
            db_name = f.read().strip()
        source_id = uuid.uuid4()
        await session.execute(text(
            \"INSERT INTO sources (id, kind, name, sandbox_db, status) \"
            \"VALUES (:id, 'dump', 'invoices', :db, 'ready')\"
        ), {'id': source_id, 'db': db_name})
        await write_schema_note(
            session, source_id=source_id, table_name='invoices', column_name=None,
            description='Table invoices. Columns: id, status.', origin='inferred',
        )
        await session.commit()
        with open('/tmp/exec-manual-source.txt', 'w') as f:
            f.write(str(source_id))
        print('source:', source_id)
    await engine.dispose()

asyncio.run(main())
"
```

**You should see:** `source: <uuid>`, no error.

```
scripts/dev.sh psql -c "SELECT id, kind, name, status FROM sources WHERE name = 'invoices';"
```

**You should see:** one row, `kind = dump`, `status = ready` — the library would show this
source as ready to query, same as a real dump import leaves it.

### 8. Run `_run_sql_turn` with a query standing in for the model, and inspect the stored answer

```
podman compose exec worker python3 -c "
import asyncio, json
from dataclasses import dataclass
from askwell import ask as ask_module
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory

@dataclass
class _Completion:
    text: str

@dataclass
class _FakeClient:
    text: str
    async def generate(self, _prompt, *, max_tokens=512, temperature=0.2):
        return _Completion(text=self.text)

async def main():
    settings = Settings()
    engine = build_engine(settings)
    with open('/tmp/exec-manual-source.txt') as f:
        source_id = f.read().strip()
    async with session_factory(engine)() as session:
        client = _FakeClient(text=\"SELECT id FROM invoices WHERE status = 'unpaid'\")
        answer = await ask_module._run_sql_turn(
            settings, session, client,
            question='how many invoices are unpaid?', source_id=source_id,
        )
        await session.commit()
        print('status:', answer.status)
        print('text:', answer.text)
        print('sql_result:', json.dumps(answer.sql_result, indent=2))
    await engine.dispose()

asyncio.run(main())
"
```

**You should see:** `status: completed`, `text: Found 3 rows.`, and a `sql_result` block whose
`columns` is `["id"]`, whose `rows` is `[[1], [3], [4]]` (order may vary), whose `row_count` is
`3`, whose `truncated` is `false`, and whose `duration_ms` is a small positive number — the
ticket's headline acceptance criterion, produced by exactly the code path `POST /ask` uses.

### 9. Confirm the execution was recorded to the interactions store, distinctly from validation and dry run

```
scripts/dev.sh psql -c "SELECT kind, payload->>'rows' AS rows, payload->>'truncated' AS truncated FROM audit_interactions WHERE kind = 'sql_execute' ORDER BY occurred_at DESC LIMIT 1;"
```

**You should see:** one row, `kind = sql_execute`, `rows = 3`, `truncated = false` — a third,
distinct kind from `sql_query` (validation, `M4-SQL-VAL-104`) and `sql_dry_run` (planning,
`M4-SQL-VAL-106`), matching the module's own reasoning for keeping the three stages separately
auditable.

```
scripts/dev.sh psql -c "SELECT count(*) FROM audit_interactions WHERE kind IN ('sql_query','sql_dry_run');"
```

**You should see:** `0` — this question was never rejected and never failed planning, so
neither of the earlier stages' own kinds fired.

### 10. Zero rows is stored as a result, not an error

```
podman compose exec worker python3 -c "
import asyncio, json
from dataclasses import dataclass
from askwell import ask as ask_module
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory

@dataclass
class _Completion:
    text: str

@dataclass
class _FakeClient:
    text: str
    async def generate(self, _prompt, *, max_tokens=512, temperature=0.2):
        return _Completion(text=self.text)

async def main():
    settings = Settings()
    engine = build_engine(settings)
    with open('/tmp/exec-manual-source.txt') as f:
        source_id = f.read().strip()
    async with session_factory(engine)() as session:
        client = _FakeClient(text=\"SELECT id FROM invoices WHERE status = 'overdue'\")
        answer = await ask_module._run_sql_turn(
            settings, session, client,
            question='how many invoices are overdue?', source_id=source_id,
        )
        await session.commit()
        print('text:', answer.text)
        print('row_count:', answer.sql_result['row_count'])
        print('rows:', answer.sql_result['rows'])
    await engine.dispose()

asyncio.run(main())
"
```

**You should see:** `text: No matching records.`, `row_count: 0`, `rows: []` — a successful,
stored zero-row result, not an exception and not a missing `sql_result`.

### 11. A result at the row limit is flagged truncated

```
podman compose exec worker python3 -c "
import asyncio
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory
from askwell.sql.execute import execute_checked_sandbox_query

async def main():
    settings = Settings()
    engine = build_engine(settings)
    with open('/tmp/exec-manual-db.txt') as f:
        db_name = f.read().strip()
    async with session_factory(engine)() as session:
        result = await execute_checked_sandbox_query(
            session, settings, database=db_name,
            query='SELECT id FROM invoices ORDER BY id LIMIT 2', row_limit=2,
        )
        await session.commit()
        print('row_count:', result.row_count, 'truncated:', result.truncated)
    await engine.dispose()
"
```

**You should see:** `row_count: 2 truncated: True` — reaching the row limit exactly is reported
as possibly-more, `askwell.sql.limit.result_was_truncated`'s own `>=` edge case, exercised here
through the caller that actually decides what the screen would need to say.

---

## 3. A stored result is reachable when the conversation is re-opened, without a second query

The point of this ticket is that the rows are a snapshot, not a live view — re-opening the
conversation a week later must show the same rows even if the source database has moved on
since. Section 2 called `_run_sql_turn` directly, so nothing has been written to `messages` or
inserted into the live turn registry yet. This section writes the answer through the same
`INSERT` `_run_generation`'s own SQL-answered branch (`api/src/askwell/ask.py`, the `sql_answer
is not None` block) uses, then confirms the ordinary read-back endpoint returns it.

### 12. Write a completed turn carrying a `sql_result`, the way `_run_generation` would

```
podman compose exec worker python3 -c "
import asyncio, json, uuid
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory
from sqlalchemy import text

async def main():
    settings = Settings()
    engine = build_engine(settings)
    async with session_factory(engine)() as session:
        conversation_id = uuid.uuid4()
        message_id = uuid.uuid4()
        sql_result = {
            'engine': 'postgresql', 'source_id': None,
            'query': \"SELECT id FROM invoices WHERE status = 'unpaid'\",
            'columns': ['id'], 'rows': [[1], [3], [4]],
            'row_count': 3, 'truncated': False, 'duration_ms': 7,
        }
        await session.execute(text(\"INSERT INTO conversations (id) VALUES (:id)\"), {'id': conversation_id})
        await session.execute(text(
            \"INSERT INTO messages (id, conversation_id, role, content, trace, summary, source_count, sql_result) \"
            \"VALUES (:id, :cid, 'assistant', 'Found 3 rows.', CAST(:trace AS jsonb), 'Answered from your database.', NULL, CAST(:sql_result AS jsonb))\"
        ), {
            'id': message_id, 'cid': conversation_id,
            'trace': json.dumps({'status': 'completed', 'steps': []}),
            'sql_result': json.dumps(sql_result),
        })
        await session.commit()
        with open('/tmp/exec-manual-message.txt', 'w') as f:
            f.write(str(message_id))
        print('message:', message_id)
    await engine.dispose()

asyncio.run(main())
"
```

**You should see:** `message: <uuid>`, no error.

### 13. Re-open it through the stream endpoint, as a browser reconnecting would

```
MSG=$(podman compose exec -T worker cat /tmp/exec-manual-message.txt)
curl -s -b /tmp/cookies.txt "http://127.0.0.1:8000/ask/$MSG/stream"
```

**You should see:** a `token` event carrying `"text": "Found 3 rows."`, then a `done` event
whose `sql_result` block matches Step 12 exactly — `row_count: 3`, `rows: [[1],[3],[4]]`,
`truncated: false` — read back from the database by `_load_finished`, with no query run against
the sandbox a second time. This message was never added to the in-memory `_turns` registry, so
this response can only have come from the `messages.sql_result` column itself — the ticket's own
Assumption made concrete: "a stored result is a snapshot ... the number in an old answer must
not change under them."

---

## 4. Clean up

```
podman compose exec worker python3 -c "
import asyncio
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory
from askwell.sandbox import drop_database

async def main():
    settings = Settings()
    engine = build_engine(settings)
    async with session_factory(engine)() as session:
        with open('/tmp/exec-manual-db.txt') as f:
            name = f.read().strip()
        await drop_database(session, settings.sandbox_database_url.get_secret_value(), name)
        await session.commit()
    await engine.dispose()
"
podman compose down -v
```

**You should see:** no error.

---

## Known gaps

Not defects — deliberately not built by this ticket, or not built at all yet:

- **No screen renders a returned row anywhere.** `M4-RESULT-FE-109` — the rendering ticket this
  one exists to unblock — has not started; `grep -rln "sql_result" web/` finds nothing under
  `web/`. Sections 2 and 3 above prove the value is computed, stored and reads back correctly;
  none of it is visible to a person using the Ask screen yet.
- **No local model runs in this environment**, so no real `POST /ask` conversation in this test
  ever gets far enough for `generate_candidate_query` to produce SQL of its own — Section 1
  proves the wiring lands before generation; Section 2 stands in for the model with a fixed
  query, the same substitution the automated suite makes.
- **The live-connection execution path (`execute_checked_connection_query`) is not exercised
  here.** Only the sandbox/dump half is driven end-to-end by hand; the connection half is proven
  by `api/tests/test_sql_execute_connection_db.py` and by the same disposable-role pattern
  `docs/manual-tests/M4-CONN-BE-099.md` already walked for query-time failures on a live
  connection.
- **A statement timeout mid-execution is not triggered here.** Forcing the sandbox's real
  statement timeout (`sql_statement_timeout_seconds`) needs a query expensive enough to run
  past it, which is awkward to construct reliably by hand against three rows; the automated
  suite's `StatementTimedOut` coverage is the authoritative proof of that branch.
- **A connection dying mid-query is not exercised here** for the same reason `M4-CONN-BE-099.md`
  names for its own live-connection failures — no way to kill a connection mid-flight from
  outside the process without a second live database standing by.
- **SQL Server and MySQL/MariaDB execution are untested here.** Only the PostgreSQL sandbox path
  runs against a real server in this environment.
