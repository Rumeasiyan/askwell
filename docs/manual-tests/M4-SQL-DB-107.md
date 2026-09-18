# Manual test — M4-SQL-DB-107, independent read-only role and statement timeout

**Ticket:** `M4-SQL-DB-107` — every query against the sandbox executes as
`askwell_sandbox_readonly`, a role distinct from the import owner, and every session carries a
30-second `statement_timeout`, independently of `sqlglot` validation. A timeout is reported
with the query and a suggestion to narrow it. Startup refuses to run if the readonly role is
misconfigured to be writable, rather than falling back to the owner role.
**Version under test:** `0.4.12` (check `cat VERSION`).
**Time:** about 45 minutes, plus a first stack build.
**Who can run it:** a browser, a terminal, `podman compose exec` access to the `sandbox`,
`worker` and `redis` containers.

**What is being checked.** `api/src/askwell/sql_execute.py` (`execute_sandbox_query`,
`_execute_postgresql_blocking`, `StatementTimedOut`, `_record_timeout`) and
`api/src/askwell/sandbox.py` (`READONLY_ROLE`, `verify_readonly_role`,
`SandboxRoleMisconfigured`), wired into `worker.py`'s `startup` (`worker.py:257-267`).
`api/tests/test_sql_execute.py` (pure, the timeout message) and
`api/tests/test_sql_execute_db.py` (`requires_db`, against a real sandbox instance) are the
authoritative automated proof; this document repeats the role-refusal, timeout and
startup-refusal behaviour against a cold-started stack, and adds what a pytest run does not
show — the database's own refusal seen directly, and what actually happens to the `worker`
container when the role is misconfigured.

**Where this stops on purpose — read before reporting anything below as a defect.**

- **Nothing in `web/` or the API calls `execute_sandbox_query` or `execute_connection_query`
  yet.** `grep -rn "sql_execute" api/src web/` finds only the module and its own tests. This
  ticket's dependents that would wire it into asking a question — `sqlglot` validation
  (`M4-SQL-VAL-104`), `LIMIT` injection (`M4-SQL-VAL-105`), the `EXPLAIN` dry-run
  (`M4-SQL-VAL-106`), and result rendering (`M4-SQL-RESULT-FE-109`/`110`) — are later, dependent
  tickets, not yet built. The ticket's own module docstring says the same thing. There is no
  "ask a question against this database" screen to click through, so §§2–3 below call the
  module directly inside the running `worker` container, the same way
  `docs/manual-tests/M4-SCHEMA-ING-100.md` drove `POST /sources/{id}/reintrospect` with `curl`
  before its own screen existed — except here there is not even a route to call, only the
  Python function.
- **The sandbox database this document exercises is a real one**, reached the same way
  `M4-DUMP-FE-090`'s manual test reached its own: importing a small dump through **Add a
  source** and reading `sources.sandbox_db` back with `psql`, since that column is never
  returned to the browser (confirmed: `DumpAddResult.as_dict()`, `api/src/askwell/sources.py`,
  returns only `id`, `name`, `status`).
- **The live-connection half of this ticket** (`execute_connection_query`, MySQL/MariaDB/SQL
  Server) is not exercised here — no external database of any of those engines runs in this
  stack. `docs/manual-tests/M4-CONN-SEC-097.md` names the same standing limitation. The
  sandbox half (PostgreSQL, the only engine `sql_execute.py`'s sandbox path supports) is what
  this document proves.
- **Query cost estimation is out of scope**, per the ticket's own "Out of Scope" line — a
  query can still run to the full timeout with nothing warning beforehand. Not tested here as
  a gap; named again in Known gaps.

---

## Before you start

```
cd ~/external/quantum-plus/askwell
```

If you have never run Askwell before:

```
cp -n .env.example .env
```

Open `.env` and confirm every `?set ... in .env` placeholder has a real value. Note the values
of `SANDBOX_POSTGRES_USER` and `SANDBOX_READONLY_PASSWORD` — you will use both below.

### 1. Make a dump to import

```
mkdir -p ~/askwell-test/dumps
cd ~/askwell-test/dumps
cat > orders.sql <<'EOF'
--
-- PostgreSQL database dump
--
CREATE TABLE orders (id integer primary key, total numeric);
INSERT INTO orders VALUES (1, 100), (2, 250);
EOF
cd ~/external/quantum-plus/askwell
```

---

## Cold start

### 2. Remove any previous state

```
podman compose down -v
```

**You should see:** containers and volumes reported removed, or a note there was nothing to
remove.

### 3. Bring the stack up and migrate

```
podman compose up -d
scripts/dev.sh db upgrade head
```

**You should see:** `postgres`, `sandbox`, `redis`, `egress-proxy`, `api`, `worker` all
reported created and started, migration finishing with no error.

### 4. Open Askwell and confirm nothing is alarmed

Open a browser at `http://127.0.0.1:8000`. **You should see:** the shell load with no alarm
banner.

### 5. Import the dump, by clicking

Find and click **Add a source**, then click into the **Database dump** card. Click **Choose a
dump file** and select `~/askwell-test/dumps/orders.sql`. **You should see:** the filename
appear and a field asking "Which folder is 'orders.sql' in?".

Type the absolute path `/home/<you>/askwell-test/dumps` and click **Import**. If asked to
nominate the folder, click **Nominate**; the import continues on its own.

**You should see:** **Queued**, then within well under a minute, **Imported**: "orders.sql
loaded into its own sealed database."

### 6. Read back the sandbox database name

There is no screen showing this — see "Where this stops on purpose" above.

```
scripts/dev.sh psql
```

```sql
SELECT name, kind, status, sandbox_db FROM sources WHERE name = 'orders.sql';
```

**You should see:** one row, `kind = dump`, `status = ready`, and a non-null `sandbox_db`
looking like `askwell_sbx_<32 hex characters>`. Note this value — call it `$SANDBOX_DB` below.

```
export SANDBOX_DB=<the value you just read>
```

---

## 1. The readonly role cannot write — verified against the database directly

### 7. Attempt an insert as the readonly role

```
podman compose exec sandbox psql \
  "postgresql://askwell_sandbox_readonly:$(grep ^SANDBOX_READONLY_PASSWORD .env | cut -d= -f2)@localhost/${SANDBOX_DB}" \
  -c "INSERT INTO orders VALUES (3, 400);"
```

**You should see:** `ERROR:  permission denied for table orders` — refused by Postgres itself,
not by application code. This is the ticket's own acceptance criterion: "Execution uses a role
that cannot write, verified by attempting a write directly as that role and being refused."

### 8. Confirm the same role can still read

```
podman compose exec sandbox psql \
  "postgresql://askwell_sandbox_readonly:$(grep ^SANDBOX_READONLY_PASSWORD .env | cut -d= -f2)@localhost/${SANDBOX_DB}" \
  -c "SELECT * FROM orders ORDER BY id;"
```

**You should see:** the two rows from step 1, `(1, 100)` and `(2, 250)` — the role is
read-only, not merely broken.

### 9. Confirm the owner role, not the readonly role, is what loaded the dump

```
podman compose exec sandbox psql \
  "postgresql://askwell_sandbox_owner:$(grep ^SANDBOX_OWNER_PASSWORD .env | cut -d= -f2)@localhost/${SANDBOX_DB}" \
  -c "SELECT 1;"
```

**You should see:** `ERROR:  permission denied for database "askwell_sbx_..."` (or a
connection refusal) — `askwell.dump_import` seals the owner's own `CONNECT` the moment a load
finishes (`askwell.sandbox.seal_owner`), so by the time a source reaches `ready`, neither role
can be handed a database it still has write access to: the owner is sealed out entirely, and
the readonly role that remains cannot write. Two distinct roles, not one role wearing two
hats, which is the ticket's own point.

---

## 2. A generated query executes under the statement timeout

There is no route or screen that runs a generated query yet — see "Where this stops on
purpose" above. This section calls `askwell.sql_execute.execute_sandbox_query` directly, inside
the running `worker` container, which already holds the sandbox admin credentials and is
already on the `sandbox` network.

### 10. Run a normal query and confirm it returns rows

```
podman compose exec worker python3 -c "
import asyncio
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory
from askwell.sql_execute import execute_sandbox_query

async def main():
    settings = Settings()
    engine = build_engine(settings)
    async with session_factory(engine)() as session:
        result = await execute_sandbox_query(
            session, settings, database='${SANDBOX_DB}', query='SELECT id, total FROM orders ORDER BY id'
        )
        print(result.columns, result.rows)
    await engine.dispose()

asyncio.run(main())
"
```

**You should see:** `('id', 'total') ((1, Decimal('100')), (2, Decimal('250')))` — the query
ran as `askwell_sandbox_readonly` (the only role `execute_sandbox_query` ever connects as) and
returned the two rows.

### 11. Run a query that outruns the timeout

```
podman compose exec worker python3 -c "
import asyncio
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory
from askwell.sql_execute import execute_sandbox_query, StatementTimedOut

async def main():
    settings = Settings()
    engine = build_engine(settings)
    async with session_factory(engine)() as session:
        try:
            await execute_sandbox_query(
                session, settings, database='${SANDBOX_DB}', query='SELECT pg_sleep(40)'
            )
        except StatementTimedOut as error:
            print('TIMED OUT:', error)
        await session.commit()
    await engine.dispose()

asyncio.run(main())
"
```

**You should see** the command return after about 30 seconds (the configured
`ASKWELL_SQL_STATEMENT_TIMEOUT_SECONDS`, not the full 40s the query asked for), printing a
message that:

- names the query: contains `SELECT pg_sleep(40)`
- states it took longer than the configured timeout and was stopped
- suggests narrowing the question (a smaller date range or an added filter)
- says the timeout is adjustable, and names the variable:
  `ASKWELL_SQL_STATEMENT_TIMEOUT_SECONDS`

This is the ticket's own acceptance criterion in full: "A query exceeding 30 seconds is
terminated and reported as taking too long, with the query and a suggestion", and the
adjustable-timeout edge case in the same message.

### 12. Confirm the timeout was recorded

```
scripts/dev.sh psql -c \
  "SELECT payload FROM audit_decisions WHERE kind = 'sql_statement_timeout' ORDER BY occurred_at DESC LIMIT 1;"
```

**You should see:** a payload with `"source_kind": "sandbox"`, `"query": "SELECT pg_sleep(40)"`,
`"timeout_seconds": 30`, and a `duration_ms` a little over 30000 — the ticket's own "Audit /
Logging Requirements: timeouts are recorded with the query and duration."

### 13. Confirm the local counter moved, and nothing left this machine

```
podman compose exec redis redis-cli GET askwell:sql:statement_timeouts
```

**You should see:** `1` (or higher, if you ran step 11 more than once) — a plain integer in
the local Redis instance, never transmitted anywhere (C1). There is nothing further to check
here by design: the ticket's own "Analytics Events: Local counter of timeouts — nothing
transmitted" has no remote endpoint to inspect.

---

## 3. Startup refuses a misconfigured, writable readonly role

### 14. Grant the readonly role a privilege it must never have

```
podman compose exec sandbox psql -U "$(grep ^SANDBOX_POSTGRES_USER .env | cut -d= -f2)" -d postgres \
  -c "ALTER ROLE askwell_sandbox_readonly CREATEDB;"
```

**You should see:** `ALTER ROLE`.

### 15. Restart the worker and watch it refuse to run

```
podman compose restart worker
podman compose logs worker --tail 40
```

**You should see**, in the logs, a fatal error naming `askwell_sandbox_readonly`, stating it
"carries a privilege a read-only execution role must never have" (naming `createdb=True`
specifically), and instructing you to fix the role with `deploy/sandbox/10-roles.sh` and
restart — not a warning logged and the worker continuing. Check the container itself:

```
podman compose ps worker
```

**You should see:** the `worker` service repeatedly exiting and restarting (its
`restart: unless-stopped` policy retrying against the same misconfiguration each time) rather
than settling into a healthy running state — the ticket's own edge case: "A role
misconfiguration — startup refuses rather than falling back to a writable role", observed as
the process itself refusing to stay up, not merely an unactioned log line.

### 16. Repair the role and confirm the worker recovers

```
podman compose exec sandbox psql -U "$(grep ^SANDBOX_POSTGRES_USER .env | cut -d= -f2)" -d postgres \
  -c "ALTER ROLE askwell_sandbox_readonly NOCREATEDB;"
podman compose restart worker
podman compose logs worker --tail 20
```

**You should see:** `worker_startup` followed by `worker_resumed` — no fatal error — and
`podman compose ps worker` showing it running steadily rather than restarting.

---

## 4. Clean up

### 17. Remove the throwaway dump

```
rm -rf ~/askwell-test/dumps
```

Dropping `$SANDBOX_DB` is not necessary — deleting the `orders.sql` source through the library
(or simply leaving it) is a normal use of the product; this document created nothing that
needs manual database cleanup beyond the files above.

---

## Known gaps

Not defects — deliberately not built by this ticket, or not built at all yet:

- **No UI or API route reaches `execute_sandbox_query` or `execute_connection_query`.** Asking
  a database question does not yet run a query at all — `sqlglot` validation
  (`M4-SQL-VAL-104`), `LIMIT` injection (`M4-SQL-VAL-105`), the `EXPLAIN` dry-run
  (`M4-SQL-VAL-106`), and result rendering (`M4-SQL-RESULT-FE-109`/`110`) are later tickets.
  Section 2 above calls the module directly inside the `worker` container because there is
  nothing else to click or curl yet.
- **No query cost estimation.** Named in the ticket's own Testing Notes as a known gap: a
  query can run the full 30 seconds with no warning before the timeout fires.
- **The live-connection path (`execute_connection_query`) is untested here.** No MySQL,
  MariaDB, or SQL Server instance runs in this stack. Its statement-timeout mechanism differs
  per engine (`SET SESSION max_statement_time` for MariaDB, `MAX_EXECUTION_TIME` for MySQL, a
  connection-level `timeout` for SQL Server, per `sql_execute.py`'s own docstrings) and is
  proven only by `api/tests/test_sql_execute.py`'s pure-Python assertions on the shared
  `StatementTimedOut` message, not against a live server of any of those three engines.
- **Sandbox database name is never surfaced anywhere in `web/`.** Step 6 above reads it with
  `psql` because there is nowhere to see it by clicking — the same standing gap
  `docs/manual-tests/M4-SCHEMA-ING-100.md` names for its own source-detail view that does not
  exist yet.
