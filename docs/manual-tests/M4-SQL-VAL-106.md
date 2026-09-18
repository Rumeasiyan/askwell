# Manual test — M4-SQL-VAL-106, plan a query before it ever executes

**Ticket:** `M4-SQL-VAL-106` — an already-validated, already-limited query is planned
(`EXPLAIN` on Postgres/MySQL/MariaDB, `SET SHOWPLAN_ALL ON` on SQL Server) against the target
database's own current schema before it is ever executed, under the same read-only role and
statement timeout execution itself uses. A query the planner rejects (a dropped column, a
renamed table) never runs. A planning failure is recorded distinctly from a validation
rejection.
**Version under test:** `0.4.21` (check `cat VERSION`).
**Time:** about 40 minutes, plus a first stack build.
**Who can run it:** a terminal, `podman compose exec` access to the `worker` container.

**What is being checked.** `api/src/askwell/sql/dry_run.py` (`dry_run_sandbox_query`,
`dry_run_connection_query`, `DryRunResult`, `DryRunReason`), backed by
`api/tests/test_sql_dry_run.py` (pure, the result shape) and `api/tests/test_sql_dry_run_db.py`
(`requires_db`, real Postgres — a nonexistent column failing planning without running, a valid
query passing, and issue #382's connect-failure handling). This document repeats the planning
failure, the pass case and the audit recording against a cold-started stack, which the
automated suite proves without ever starting a container.

**Where this stops on purpose — read before reporting anything below as a defect.**

- **Nothing in `web/` or `POST /ask` calls `dry_run_sandbox_query`/`dry_run_connection_query`
  yet.** `grep -rn "dry_run_sandbox_query\|dry_run_connection_query" api/src web/` finds only
  the module and its own tests. `api/src/askwell/sql/__init__.py`'s own docstring says so
  directly: none of validation, limit injection or this dry run are wired into `POST /ask`'s
  turn flow — issue #375. `docs/states-and-edge-cases.md` §4's "`EXPLAIN` dry-run fails" row
  describes a screen this ticket has nothing to plug into yet. This document calls
  `askwell.sql.dry_run.dry_run_sandbox_query` directly inside the running `worker` container,
  the same way `docs/manual-tests/M4-SQL-VAL-105.md` did for `inject_limit` before it was wired
  anywhere.
- **A query is never itself generated or validated here.** This ticket only plans an
  already-accepted, already-limited query — the queries below are typed by hand to stand in for
  whatever `validate_query` (`M4-SQL-VAL-104`) and `inject_limit` (`M4-SQL-VAL-105`) would
  already have passed and shaped.
- **SQL Server's `UNSUPPORTED` path and the `TIMEOUT` reason are not exercised against a real
  database here.** No SQL Server instance is part of this stack — the automated suite covers
  `_dry_run_sqlserver_blocking`'s `SHOWPLAN_ALL` refusal in isolation; this document only proves
  the Postgres sandbox path and the connection path's connect-failure handling (issue #382)
  against real servers.

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

## 1. A valid query plans and is not recorded

### 4. Create a sandbox database, a small table, then plan a valid and an invalid query

```
podman compose exec worker python3 -c "
import asyncio
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory
from askwell.sandbox import OWNER_ROLE, create_database, generate_name
from askwell.sql.dry_run import dry_run_sandbox_query
import psycopg

async def main():
    settings = Settings()
    engine = build_engine(settings)
    async with session_factory(engine)() as session:
        name = generate_name()
        admin_url = settings.sandbox_database_url.get_secret_value()
        await create_database(session, admin_url, name)
        await session.commit()
        with open('/tmp/dry-run-db.txt', 'w') as f:
            f.write(name)

        owner_dsn = admin_url.rsplit('/', 1)[0] + f'/{name}'
        with psycopg.connect(owner_dsn, autocommit=True) as conn:
            conn.execute('CREATE TABLE t (x int)')
            conn.execute('INSERT INTO t VALUES (1), (2)')

        ok = await dry_run_sandbox_query(session, settings, database=name, query='SELECT x FROM t')
        print('valid:', ok.passed, ok.reason, ok.detail)

        bad = await dry_run_sandbox_query(
            session, settings, database=name, query='SELECT does_not_exist FROM t'
        )
        print('bad:', bad.passed, bad.reason, bad.detail)
        await session.commit()

        with psycopg.connect(owner_dsn, autocommit=True) as conn:
            rows = conn.execute('SELECT count(*) FROM t').fetchone()
            print('row count still:', rows[0])
    await engine.dispose()

asyncio.run(main())
"
```

**You should see:** `valid: True None None`, then `bad: False DryRunReason.PLANNING_FAILED ...`
with `does_not_exist` in the detail, then `row count still: 2` — the bad query never executed
(the table still has exactly the two rows Step 4 inserted, never touched by the planning
attempt), and it never ran to change anything either.

---

## 2. A planning failure is recorded distinctly from a validation rejection

### 5. Confirm the failure landed in `audit_interactions` as `sql_dry_run`

```
scripts/dev.sh psql -c "SELECT kind, payload->>'reason' AS reason, payload->>'query' AS query FROM audit_interactions WHERE kind = 'sql_dry_run' ORDER BY occurred_at DESC LIMIT 3;"
```

**You should see:** one row, `kind` = `sql_dry_run`, `reason` = `planning_failed`, `query` =
`SELECT does_not_exist FROM t` — the query from Step 4's second call.

### 6. Confirm this is a different kind from a validation rejection

```
scripts/dev.sh psql -c "SELECT DISTINCT kind FROM audit_decisions WHERE kind = 'sql_rejected';"
scripts/dev.sh psql -c "SELECT DISTINCT kind FROM audit_interactions WHERE kind = 'sql_dry_run';"
```

**You should see:** `sql_rejected` lives in `audit_decisions` (`validate.py`'s own kind, from
`M4-SQL-VAL-104`); `sql_dry_run` lives in `audit_interactions` — two different stores, two
different kinds, so a "the parser wouldn't accept this SQL at all" fact and a "the database's
own planner rejected this SQL against its real schema" fact never collapse into one log line.
This is the ticket's own Acceptance Criteria made concrete.

### 7. Confirm the valid query from Step 4 was not recorded

```
scripts/dev.sh psql -c "SELECT count(*) FROM audit_interactions WHERE kind = 'sql_dry_run' AND payload->>'query' = 'SELECT x FROM t';"
```

**You should see:** `0` — a query that plans successfully is never written to the audit log by
this module.

---

## 3. A connection failure during planning fails safely, not with a crash (issue #382)

### 8. Plan a query against a connection with nothing listening on the port

```
podman compose exec worker python3 -c "
import asyncio, uuid
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory
from askwell.sql.dry_run import dry_run_connection_query

async def main():
    settings = Settings()
    engine = build_engine(settings)
    async with session_factory(engine)() as session:
        result = await dry_run_connection_query(
            session, settings, source_id=uuid.uuid4(), engine='postgresql',
            host='127.0.0.1', port=1, database='orders',
            user='reader', password='whatever', query='SELECT 1',
        )
        print(result.passed, result.reason, result.detail)
        await session.commit()
    await engine.dispose()

asyncio.run(main())
"
```

**You should see:** `False DryRunReason.PLANNING_FAILED ...` with a connection-refused-shaped
detail — never a Python traceback. This is issue #382's exact regression: an earlier version of
this module only caught `OSError` and let `psycopg.OperationalError` (a driver-specific class,
not an `OSError` subclass) propagate unhandled instead of coming back as a `DryRunResult`.

---

## 4. Planning runs as the read-only role, like execution

### 9. Confirm the sandbox dry run used the readonly role, not the owner

The dry run's own connection is short-lived and closed by the time you could inspect
`pg_stat_activity`, so the durable proof is in the source:

```
podman compose exec worker grep -n "readonly_url" /app/api/src/askwell/sql/dry_run.py
```

**You should see:** `dry_run_sandbox_query` builds its DSN through `readonly_url(...)`, the
same helper `askwell.sql_execute.execute_sandbox_query` uses — planning and execution connect
through the identical restricted, non-superuser role (C3), never the owner that created the
database and table in Step 4.

---

## 5. Clean up

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
        with open('/tmp/dry-run-db.txt') as f:
            name = f.read().strip()
        await drop_database(session, settings.sandbox_database_url.get_secret_value(), name)
        await session.commit()
    await engine.dispose()
"
```

**You should see:** no error. `podman compose down -v` (Step 1's command) resets the rest of
the stack if you intend to run other manual tests afterwards.

---

## Known gaps

Not defects — deliberately not built by this ticket, or not built at all yet:

- **No UI or API route reaches either dry-run function.** Asking a database question in the
  browser's ask screen never plans, executes, or shows a candidate SQL query today — it always
  answers from document retrieval, or abstains. `docs/states-and-edge-cases.md` §4's "`EXPLAIN`
  dry-run fails" row has nothing to render from yet: wiring `generate_candidate_query` →
  `validate_query` → `inject_limit` → this dry run → execution → the ask screen is later work,
  tracked by issue #375.
- **SQL Server's `SHOWPLAN_ALL` refusal (`UNSUPPORTED`) is not exercised against a real SQL
  Server here.** No SQL Server instance exists in this stack; the automated suite is the only
  proof of that path today.
- **The `TIMEOUT` reason is not triggered here.** Forcing a real planner timeout needs a query
  expensive enough to plan slowly, which is awkward to construct reliably by hand; the automated
  suite's `psycopg.errors.QueryCanceled`/driver-timeout handling is the authoritative proof.
- **No cost-based refusal of an expensive-but-plannable query.** Out of scope for this ticket;
  the statement timeout is what actually stops a runaway query, whether at planning or at
  execution.
- **Real query execution is separate, later work** (`askwell.sql_execute`) and is not exercised
  here — this document tests the plan-only gate alone.
