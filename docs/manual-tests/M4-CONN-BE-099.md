# Manual test — M4-CONN-BE-099, connection health and three distinguishable failures

**Ticket:** `M4-CONN-BE-099` — a live connection is health-checked periodically and on demand.
At query time, a dead database produces "the database is unreachable", distinct from a
zero-row result and from a query the database itself refused. Credentials revoked since the
connection was set up are reported as a credential problem, not a generic failure. The state
shown reflects the latest check rather than flapping on every render.
**Version under test:** `0.4.19` (check `cat VERSION`).
**Time:** about 40 minutes, plus a first stack build.
**Who can run it:** a browser, a terminal, `podman compose exec` access to the `postgres` and
`worker` containers.

**What is being checked.** `api/src/askwell/connections.py` (`check_connection_health`,
`_record_health_transition`, `run_introspection`'s `credentials_locked` path) and
`api/src/askwell/sql_execute.py` (`execute_connection_query`, `ConnectionUnreachable`,
`CredentialsRejected`, `QueryRejected`), the `check_connections_health` cron in `worker.py`, and
`POST /sources/{id}/reconnect` in `sources.py`. `api/tests/test_connections_db.py` and
`api/tests/test_sql_execute_connection_db.py` (both `requires_db`) are the authoritative
automated proof; this document repeats the three failures against a real, disposable Postgres
database standing in for a customer's, and shows what a pytest run does not — the periodic cron
actually firing, and what a person watching the stack would see.

**Where this stops on purpose — read before reporting anything below as a defect.**

- **The library screen does not yet render any of this.** `docs/ux/library.md` §5 and this
  ticket's own AC ask for "the last successful check, the error and a reconnect" action on the
  library row. Read `web/components/library/library-screen.tsx` and `web/lib/library.ts`
  end to end: `SourceRow` shows `status` and, for `attention`, only document-shaped causes from
  `attentionCauses` (failed extraction, poor OCR) — nothing reads `source.last_error` or
  `source.last_healthy_at`, and there is no reconnect button anywhere under `web/`
  (`grep -rln "reconnect" web/app web/components` finds nothing). `web/lib/ingest.ts` already
  carries `last_error` and `last_healthy_at` on the wire type, so the backend is ready for this
  and the frontend has not caught up. This is filed as its own gap below, not fixed here — it
  is out of scope for a `-BE-` ticket to also build the `-FE-` rendering, and no companion
  `M4-CONN-FE-*` ticket for this rendering exists yet in the tracker at the time of this test.
  Steps 8, 11 and 14 below use `POST /sources/{id}/reconnect` and `psql` directly because there
  is no screen to click for them — the same pattern `docs/manual-tests/M4-SQL-DB-107.md` used
  for its own not-yet-wired module.
- **Asking a question never reaches a live connection yet.** `sqlglot` validation
  (`M4-SQL-VAL-104`), `LIMIT` injection (`M4-SQL-VAL-105`), the `EXPLAIN` dry-run
  (`M4-SQL-VAL-106`) and result rendering (`M4-SQL-RESULT-FE-109`/`110`) are later tickets, and
  `M4-SQL-DB-107`'s own manual test already confirmed `grep -rn "sql_execute" api/src web/`
  finds only the module and its tests. The three query-time failures this ticket names are
  therefore exercised the same way that document exercised the timeout: calling
  `askwell.sql_execute.execute_connection_query` directly inside the running `worker` container.
- **No MySQL, MariaDB or SQL Server instance runs in this stack.** Only the PostgreSQL path is
  exercised here, the same standing limitation `docs/manual-tests/M4-CONN-SEC-097.md` and
  `M4-SQL-DB-107.md` both name for their own live-connection halves.

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

**You should see:** `postgres`, `sandbox`, `redis`, `egress-proxy`, `api`, `worker` all reported
created and started, migration finishing with no error.

### 3. Open Askwell and confirm nothing is alarmed

Open a browser at `http://127.0.0.1:8000`. **You should see:** the shell load with no alarm
banner.

---

## 1. Set up a disposable target database

There is no second real customer database available in this environment, so this test builds
one inside the same Postgres server Askwell already runs, in its own role and table, entirely
separate from Askwell's own schema — the same approach `api/tests/test_sql_execute_connection_db.py`
takes for its own automated version of this scenario.

### 4. Create a role and a table to connect to

```
podman compose exec postgres psql -U "$(grep ^POSTGRES_USER .env | cut -d= -f2)" -d askwell -c "
CREATE ROLE conn_manual_test LOGIN PASSWORD 'orig-password';
CREATE SCHEMA IF NOT EXISTS conn_manual_test_schema AUTHORIZATION conn_manual_test;
CREATE TABLE conn_manual_test_schema.widgets (id integer primary key, name text);
INSERT INTO conn_manual_test_schema.widgets VALUES (1, 'sprocket'), (2, 'cog');
GRANT USAGE ON SCHEMA conn_manual_test_schema TO conn_manual_test;
GRANT SELECT ON conn_manual_test_schema.widgets TO conn_manual_test;
"
```

**You should see:** `CREATE ROLE`, `CREATE SCHEMA`, `CREATE TABLE`, `INSERT 0 2`, `GRANT`,
`GRANT`.

### 5. Connect Askwell to it, by clicking

Click **Add a source**, then click into the **Connect a database** card. Fill in:

- Engine: **PostgreSQL**
- Host: `postgres`
- Port: `5432`
- Database: `askwell`
- User: `conn_manual_test`
- Password: `orig-password`

Click **Connect**.

**You should see:** the form replaced with a confirmation that the connection was queued, and
within a few seconds the library (`http://127.0.0.1:8000/library/`) lists a new source named
`askwell on postgres` with status **indexed**.

### 6. Read back the source id

There is no screen showing this. Note it for the steps below:

```
scripts/dev.sh psql -c "SELECT id, status, last_healthy_at, last_error FROM sources WHERE name = 'askwell on postgres';"
export SOURCE_ID=<the id you just read>
```

**You should see:** one row, `status = ready`, `last_healthy_at` set to a recent timestamp,
`last_error` null.

---

## 2. Connection dead at query time — three distinguishable failures

Every step below calls `execute_connection_query` directly inside the `worker` container, for
the reason given above. Each one is checked two ways: the exception text returned, and the row
in `sources` it leaves behind — the AC's own "the state reflects the latest check", proven by
reading the same column `_record_health_transition` writes.

### 7. Unreachable — the database did not answer at all

```
podman compose exec worker python3 -c "
import asyncio
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory
from askwell.sql_execute import execute_connection_query, ConnectionUnreachable

async def main():
    settings = Settings()
    engine = build_engine(settings)
    async with session_factory(engine)() as session:
        try:
            await execute_connection_query(
                session, settings, source_id='${SOURCE_ID}', engine='postgresql',
                host='postgres', port=1, database='askwell',
                user='conn_manual_test', password='orig-password',
                query='SELECT 1',
            )
        except ConnectionUnreachable as error:
            print('UNREACHABLE:', error)
        await session.commit()
    await engine.dispose()

asyncio.run(main())
"
```

**You should see:** `UNREACHABLE:` followed by *"The database is unreachable. It may be down,
or the network between here and it may be down. This is not the same as a query returning no
rows — Askwell could not reach the database at all."* — visibly distinct from an empty result,
which is the ticket's own headline requirement.

```
scripts/dev.sh psql -c "SELECT status, last_error FROM sources WHERE id = '${SOURCE_ID}';"
```

**You should see:** `status = attention`, `last_error` set to the message above — the query-time
failure already flipped the library state, without waiting for the next periodic check
(the ticket's dependency the module docstring names: "query-time is a health signal too").

```
scripts/dev.sh psql -c "SELECT kind, payload FROM audit_decisions WHERE kind = 'connection_health_lost' ORDER BY occurred_at DESC LIMIT 1;"
```

**You should see:** one row naming `reason_code` consistent with an unreachable host (typically
`connection_refused`) — the health transition is a decisions record, this ticket's own
"Audit / Logging Requirements: health transitions are logged."

### 8. Reconnect — restore normal operation without recreating the connection

The database was never actually down; step 7 only pointed at a wrong port. Confirm reconnect
sees this:

```
curl -s -X POST http://127.0.0.1:8000/sources/${SOURCE_ID}/reconnect | python3 -m json.tool
```

**You should see:** `"ok": true`, `"reason_code": null`, `"message": "Connected."` — status 200.

```
scripts/dev.sh psql -c "SELECT status, last_error, last_healthy_at FROM sources WHERE id = '${SOURCE_ID}';"
```

**You should see:** `status = ready` again, `last_error` cleared to null, `last_healthy_at`
updated to now — the ticket's own AC: "Recovering the database restores normal operation
without recreating the connection." Nothing about the `sources` row's `id` or `config_encrypted`
changed; only its health fields did.

```
scripts/dev.sh psql -c "SELECT kind FROM audit_decisions WHERE kind = 'connection_health_recovered' ORDER BY occurred_at DESC LIMIT 1;"
```

**You should see:** one row — the recovery is logged too, same as the loss.

### 9. Credentials rejected — a connection whose credentials were revoked

```
podman compose exec postgres psql -U "$(grep ^POSTGRES_USER .env | cut -d= -f2)" -d askwell -c "
ALTER ROLE conn_manual_test PASSWORD 'changed-password';
"
```

**You should see:** `ALTER ROLE`.

```
podman compose exec worker python3 -c "
import asyncio
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory
from askwell.sql_execute import execute_connection_query, CredentialsRejected

async def main():
    settings = Settings()
    engine = build_engine(settings)
    async with session_factory(engine)() as session:
        try:
            await execute_connection_query(
                session, settings, source_id='${SOURCE_ID}', engine='postgresql',
                host='postgres', port=5432, database='askwell',
                user='conn_manual_test', password='orig-password',
                query='SELECT 1',
            )
        except CredentialsRejected as error:
            print('CREDENTIALS REJECTED:', error)
        await session.commit()
    await engine.dispose()

asyncio.run(main())
"
```

**You should see:** `CREDENTIALS REJECTED:` followed by *"The database refused these
credentials. They may have been changed or revoked since this connection was set up — re-enter
them to reconnect."* — a different sentence from the unreachable one in step 7, and one that
correctly tells the person the fix is re-entering a password, not restarting a server.

```
scripts/dev.sh psql -c "SELECT status, last_error FROM sources WHERE id = '${SOURCE_ID}';"
```

**You should see:** `status = attention` again, `last_error` now the credentials-rejected
message from above.

Put the correct password back so later steps are unaffected:

```
podman compose exec postgres psql -U "$(grep ^POSTGRES_USER .env | cut -d= -f2)" -d askwell -c "
ALTER ROLE conn_manual_test PASSWORD 'orig-password';
"
curl -s -X POST http://127.0.0.1:8000/sources/${SOURCE_ID}/reconnect | python3 -m json.tool
```

**You should see:** `"ok": true` again, and `status = ready` in `sources`.

### 10. Query rejected — the database accepts connections but refuses this query

```
podman compose exec postgres psql -U "$(grep ^POSTGRES_USER .env | cut -d= -f2)" -d askwell -c "
REVOKE SELECT ON conn_manual_test_schema.widgets FROM conn_manual_test;
"
```

**You should see:** `REVOKE`.

```
podman compose exec worker python3 -c "
import asyncio
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory
from askwell.sql_execute import execute_connection_query, QueryRejected

async def main():
    settings = Settings()
    engine = build_engine(settings)
    async with session_factory(engine)() as session:
        try:
            await execute_connection_query(
                session, settings, source_id='${SOURCE_ID}', engine='postgresql',
                host='postgres', port=5432, database='askwell',
                user='conn_manual_test', password='orig-password',
                query='SELECT * FROM conn_manual_test_schema.widgets',
            )
        except QueryRejected as error:
            print('QUERY REJECTED:', error)
        await session.commit()
    await engine.dispose()

asyncio.run(main())
"
```

**You should see:** `QUERY REJECTED:` followed by *"The database accepted the connection but
refused this query. This is a permissions problem, not a connectivity one: ..."* naming
Postgres's own `permission denied for table widgets` (or similarly worded) detail — a third,
distinct sentence from both step 7 and step 9. The connection itself succeeded; only this
specific query was refused, which is exactly the edge case the ticket names by name.

```
scripts/dev.sh psql -c "SELECT status, last_error FROM sources WHERE id = '${SOURCE_ID}';"
```

**You should see:** `status = attention`, `last_error` the permission-denied message.

Restore the grant and reconnect so the connection is left healthy:

```
podman compose exec postgres psql -U "$(grep ^POSTGRES_USER .env | cut -d= -f2)" -d askwell -c "
GRANT SELECT ON conn_manual_test_schema.widgets TO conn_manual_test;
"
curl -s -X POST http://127.0.0.1:8000/sources/${SOURCE_ID}/reconnect | python3 -m json.tool
```

**You should see:** `"ok": true`, `status = ready`.

### 11. A zero-row result is not confused with any of the above

```
podman compose exec worker python3 -c "
import asyncio
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory
from askwell.sql_execute import execute_connection_query

async def main():
    settings = Settings()
    engine = build_engine(settings)
    async with session_factory(engine)() as session:
        result = await execute_connection_query(
            session, settings, source_id='${SOURCE_ID}', engine='postgresql',
            host='postgres', port=5432, database='askwell',
            user='conn_manual_test', password='orig-password',
            query=\"SELECT * FROM conn_manual_test_schema.widgets WHERE name = 'nonexistent'\",
        )
        print(result.columns, result.rows)
        await session.commit()
    await engine.dispose()

asyncio.run(main())
"
```

**You should see:** `('id', 'name') ()` — a successful `QueryResult` with zero rows, not any of
`ConnectionUnreachable`, `CredentialsRejected` or `QueryRejected`. This is the AC's own explicit
line: "Unreachable and empty must never share a message" — confirmed by the fact that no
exception was raised at all here.

```
scripts/dev.sh psql -c "SELECT status, last_healthy_at FROM sources WHERE id = '${SOURCE_ID}';"
```

**You should see:** `status = ready`, `last_healthy_at` freshly updated — a successful query is
also a health signal.

---

## 3. The periodic health check runs on its own

### 12. Confirm the cron is configured

```
grep -n "connection_health_check_seconds" .env
```

If absent, the default (`60` seconds) applies — `api/src/askwell/config.py`. A shorter interval
for this test can be set with `ASKWELL_CONNECTION_HEALTH_CHECK_SECONDS=15` in `.env`, followed
by `podman compose up -d worker` to pick it up.

### 13. Break the connection without touching it through the API, and wait

```
podman compose exec postgres psql -U "$(grep ^POSTGRES_USER .env | cut -d= -f2)" -d askwell -c "
ALTER ROLE conn_manual_test PASSWORD 'broken-again';
"
```

Wait for one full `connection_health_check_seconds` interval (60s by default, or the shortened
value from step 12), then:

```
scripts/dev.sh psql -c "SELECT status, last_error FROM sources WHERE id = '${SOURCE_ID}';"
```

**You should see:** `status = attention`, `last_error` the credentials-rejected message — set by
the periodic cron, `worker.check_connections_health`, without any click or `curl` from you.
Confirm it in the worker's own logs:

```
podman compose logs worker --tail 100 | grep connection_health
```

**You should see:** a `connection_health_lost` log line naming the source id, from the cron, not
from any of the manual calls above.

### 14. Repeated failures do not create a new decisions row every cycle

```
scripts/dev.sh psql -c "SELECT count(*) FROM audit_decisions WHERE kind = 'connection_health_lost' AND payload->>'source_id' = '${SOURCE_ID}';"
```

Wait for one more health-check interval without changing anything, then run the same count
again.

**You should see:** the same count both times — the transition is recorded once, on
`ready`→`attention`, never on a repeat of the same state (issue #360, named directly in
`connections.py`'s own comment above `_record_health_transition`). This is also the AC's
"intermittent connectivity — the state reflects the latest check rather than flapping in the
interface on every render": `last_error`/`last_healthy_at` update every cycle regardless, but
the decisions store does not grow per cycle.

Repair it and confirm the cron recovers the source on its own:

```
podman compose exec postgres psql -U "$(grep ^POSTGRES_USER .env | cut -d= -f2)" -d askwell -c "
ALTER ROLE conn_manual_test PASSWORD 'orig-password';
"
```

Wait one more interval, then:

```
scripts/dev.sh psql -c "SELECT status, last_error FROM sources WHERE id = '${SOURCE_ID}';"
```

**You should see:** `status = ready`, `last_error` null — recovered by the cron, no click
needed.

---

## 4. Clean up

### 15. Remove the disposable role, table and source

```
scripts/dev.sh psql -c "SELECT id FROM sources WHERE name = 'askwell on postgres';"
curl -s -X DELETE http://127.0.0.1:8000/sources/${SOURCE_ID} | python3 -m json.tool
podman compose exec postgres psql -U "$(grep ^POSTGRES_USER .env | cut -d= -f2)" -d askwell -c "
DROP TABLE IF EXISTS conn_manual_test_schema.widgets;
DROP SCHEMA IF EXISTS conn_manual_test_schema;
DROP ROLE IF EXISTS conn_manual_test;
"
```

**You should see:** `"deleted": true` from the API, then `DROP TABLE`, `DROP SCHEMA`,
`DROP ROLE` from Postgres.

---

## Known gaps

Not defects — deliberately not built by this ticket, or not built at all yet:

- **The library screen does not render connection health.** No last-successful-check time, no
  error message and no reconnect button appear anywhere under `web/` for a `connection`-kind
  source in `attention` — confirmed by reading `library-screen.tsx` and `web/lib/library.ts`
  end to end, and by `grep -rln "reconnect" web/app web/components` finding nothing. The
  `SourceRow` for a connection instead shows a static, unrelated sentence about write
  permissions ("Read access confirmed at connection time... that refusal is not wired up yet")
  which is itself stale now that `M4-CONN-SEC-097`'s write probe has since landed — worth its
  own issue, filed separately from this ticket. `POST /sources/{id}/reconnect` and the
  `last_error`/`last_healthy_at` columns this document exercises are real and correct; there is
  simply no click path to either of them yet.
- **No route or screen runs a generated query against a live connection.** Same standing gap
  `docs/manual-tests/M4-SQL-DB-107.md` names for the sandbox half: `sqlglot` validation, `LIMIT`
  injection, the `EXPLAIN` dry-run and result rendering are later, dependent tickets. Sections 2
  and 3 above call `execute_connection_query` directly because there is nothing else to click or
  curl yet.
- **MySQL, MariaDB and SQL Server are untested here.** Only the PostgreSQL path is exercised;
  the other three engines' distinct failure classification (`_execute_connection_mysql_blocking`,
  `_execute_connection_sqlserver_blocking`) is proven only by `api/tests/test_sql_execute.py`'s
  pure-Python assertions, not against a live server of any of those engines.
- **Health check frequency is fixed, not per-source.** Named in the ticket's own Testing Notes
  as a known gap — `connection_health_check_seconds` applies to every live connection equally.
