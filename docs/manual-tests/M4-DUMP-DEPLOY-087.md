# Manual test — M4-DUMP-DEPLOY-087, the sandbox Postgres instance for untrusted dumps

**Ticket:** `M4-DUMP-DEPLOY-087` — a second, separate Postgres instance (`sandbox`) that a dump import will one day load into, with its own network (no route to Askwell's own database or the egress proxy) and two fixed roles with superuser, `CREATEDB`, `COPY ... TO PROGRAM` and large-object rights all removed. One database per imported source, created and dropped through `askwell.sandbox`, each a decisions record. An orphaned sandbox database from a crashed import is reclaimed at worker startup.
**Version under test:** `0.4.3`
**Time:** about 40 minutes, plus a first stack build.
**Who can run it:** a browser, a terminal, `podman compose exec`, `scripts/dev.sh psql`, and `.env` open in a text editor (two passwords are read from it directly — see step 6).

**What is being checked.** `compose.yaml`'s `sandbox` service and `sandbox` network; `deploy/sandbox/10-roles.sh`; `api/src/askwell/sandbox.py` (`create_database`, `drop_database`, `reclaim_orphans`); `api/src/askwell/health.py`'s `sandbox` component. `api/tests/test_sandbox.py` is the authoritative automated proof of every role restriction below; this document repeats the same checks against the real, cold-started stack rather than a disposable test database, plus the network topology and the worker's own crash-recovery behaviour, neither of which a pytest run can exercise.

**Where this stops on purpose — read before reporting anything below as a defect.**

- **Nothing imports a dump yet.** `M4-DUMP-ING-088` has not landed, so there is no **Add a source** flow that reaches the sandbox at all — a `.sql`/`.dump`/`.backup` file still shows as not-yet-supported at add time. Every sandbox database created in this document is created directly, by calling `askwell.sandbox.create_database` from a Python one-liner inside the running `api` container, because that is the only way to reach this ticket's code today.
- **There is no dedicated "sandbox unavailable" message in the library.** `docs/states-and-edge-cases.md` §1 describes a future state where dump-backed sources show "needs attention" naming the sandbox, in the library screen specifically (`ux/library.md` §5) — that section does not exist yet in `ux/library.md`, and there are no dump-backed sources to show it against regardless, since nothing imports one. What exists today is generic: `web/components/shell/status-banner.tsx` treats every unreachable health component the same way, including `sandbox`, and shows a global alarm banner rather than a library-scoped notice. §5 below shows exactly what that looks like today.
- **`web/lib/health.ts`'s `COMPONENT_LABELS` has no entry for `sandbox`.** The banner in §5 below reads "sandbox is not available", the raw component name, rather than a name a non-technical user would recognise (compare `database` → "Your data"). Worth flagging (see Known gaps) but not a regression this ticket introduced — the map simply has not been extended yet.

None of this is a defect in `M4-DUMP-DEPLOY-087` itself — its scope is the container, the network boundary, the two roles, and the create/drop/reclaim functions, not the import flow or its UI. Sections below say which is which.

---

## Before you start

```
cd ~/external/quantum-plus/askwell
```

If you have never run Askwell before:

```
cp -n .env.example .env
```

Open `.env` and confirm every `?set ... in .env` placeholder has a real value, in particular `SANDBOX_POSTGRES_PASSWORD`, `SANDBOX_OWNER_PASSWORD` and `SANDBOX_READONLY_PASSWORD`. **Note the values of `SANDBOX_OWNER_PASSWORD` and `SANDBOX_READONLY_PASSWORD`** — steps 6–10 below type them in directly, since the running `api` and `worker` containers are only ever given the sandbox instance's *superuser* connection (`ASKWELL_SANDBOX_DATABASE_URL`), never the two fixed roles' own passwords (`compose.yaml`, `api`/`worker` services).

---

## Cold start

### 1. Remove any previous state

```
podman compose down -v
```

**You should see:** lines about containers and volumes being removed, or a note there was nothing to remove. This also destroys any previous `sandbox-data` volume, so the sandbox starts genuinely empty.

### 2. Run the checks

```
scripts/dev.sh check
```

**You should see:** lint, format, typecheck and unmarked tests finish without red error text.

### 3. Bring the stack up and migrate

```
podman compose up -d
scripts/dev.sh db upgrade head
```

**You should see:** `postgres`, `sandbox`, `redis`, `egress-proxy`, `api`, `worker` all reported as created and started, then migration lines finishing with no error.

### 4. Confirm the sandbox is its own service, separate from the main database

```
podman compose ps
```

**You should see:** `sandbox` listed as its own row, `Up (healthy)`, alongside — not merged into — `postgres`. Two independent Postgres containers.

```
podman volume ls | grep askwell
```

**You should see:** `askwell_sandbox-data` as its own volume, separate from `askwell_postgres-data` — the edge case in the ticket ("the sandbox volume filling") is only possible to bound separately because this volume is separate to begin with.

### 5. Open the app and confirm the shell reports the sandbox as healthy

Open a browser at `http://127.0.0.1:8000`. **You should see:** the Askwell shell load with no alarm banner across the top — every component, `sandbox` included, is reachable.

```
curl -s http://127.0.0.1:8000/health | python3 -m json.tool
```

**You should see:** a `components` array containing an entry with `"component": "sandbox"` and `"state": "reachable"`, alongside `database`, `queue`, `egress_proxy` and `inference`. This is `_targets()` in `api/src/askwell/health.py` doing exactly what the ticket's own acceptance criterion asks: the sandbox is probed and reported independently of Postgres.

---

## 1. A sealed database, created and audited

### 6. Create one sandbox database directly

There is no UI path yet (see "Where this stops on purpose"), so call the function this ticket built, from inside the already-running `api` container:

```
podman compose exec api python3 -c "
import asyncio
from askwell.config import load_settings
from askwell.db.engine import build_engine, session_factory
from askwell import sandbox

async def main():
    settings = load_settings()
    engine = build_engine(settings)
    factory = session_factory(engine)
    name = sandbox.generate_name()
    async with factory() as session:
        await sandbox.create_database(
            session, settings.sandbox_database_url.get_secret_value(), name
        )
        await session.commit()
    print(name)
    await engine.dispose()

asyncio.run(main())
"
```

**You should see:** one line of output, a name starting `askwell_sbx_` followed by 32 hex characters. **Write this name down** — every step below uses it. Call it `<NAME>`.

### 7. Confirm it exists, and confirm the creation was recorded as a decision

```
podman compose exec sandbox psql -U askwell_sandbox -d postgres -c "SELECT datname FROM pg_database WHERE datname = '<NAME>';"
```

**You should see:** one row naming `<NAME>`.

```
scripts/dev.sh psql <<'SQL'
SELECT kind, payload FROM audit_decisions WHERE kind = 'sandbox_database_created' ORDER BY occurred_at DESC LIMIT 1;
SQL
```

**You should see:** one row, `kind = sandbox_database_created`, `payload` naming `<NAME>` — the ticket's own audit requirement ("sandbox database creation... are decisions records") made visible. This query runs against Askwell's own database via `scripts/dev.sh psql`, not the sandbox instance — a decisions record about the sandbox lives in Askwell's own audit log, not inside the sandbox itself.

---

## 2. What the restricted roles can and cannot do

Replace `<OWNER_PW>` and `<READONLY_PW>` below with the values you noted from `.env` in step 6 of "Before you start". Each command connects straight to the sandbox container's own Postgres over TCP, as one of the two fixed roles, against the database created in step 6.

### 8. The owner role can connect and use its own database

```
podman compose exec -e PGPASSWORD='<OWNER_PW>' sandbox \
  psql -h localhost -U askwell_sandbox_owner -d <NAME> -c "SELECT 1;"
```

**You should see:** a one-row, one-column result of `1` — the owner role, the one dump content will eventually run as, can reach the database made for it.

### 9. The owner role cannot make itself a superuser

```
podman compose exec -e PGPASSWORD='<OWNER_PW>' sandbox \
  psql -h localhost -U askwell_sandbox_owner -d <NAME> -c "CREATE ROLE hacker SUPERUSER;"
```

**You should see:** `ERROR: permission denied to create role` (or equivalent `InsufficientPrivilege` wording) — not a created role.

### 10. The owner role cannot create a second database to hide in

```
podman compose exec -e PGPASSWORD='<OWNER_PW>' sandbox \
  psql -h localhost -U askwell_sandbox_owner -d <NAME> -c "CREATE DATABASE escape;"
```

**You should see:** `ERROR: permission denied to create database`. This is the ticket's own stated reasoning made concrete: a dump that could create a database could make itself a second, unmonitored one.

### 11. The owner role cannot run a program via `COPY`

This is the ticket's own real-world example — a dump containing a command to read a file from the host.

```
podman compose exec -e PGPASSWORD='<OWNER_PW>' sandbox \
  psql -h localhost -U askwell_sandbox_owner -d <NAME> -c "COPY (SELECT 1) TO PROGRAM 'cat > /tmp/pwned';"
```

**You should see:** `ERROR: must be superuser or a member of the pg_execute_server_program role to COPY to or from an external program`. No file is created — the failure is reported, not silently absorbed.

### 12. The owner role cannot use large objects, either API

```
podman compose exec -e PGPASSWORD='<OWNER_PW>' sandbox \
  psql -h localhost -U askwell_sandbox_owner -d <NAME> -c "SELECT lo_import('/etc/passwd');"
podman compose exec -e PGPASSWORD='<OWNER_PW>' sandbox \
  psql -h localhost -U askwell_sandbox_owner -d <NAME> -c "SELECT lo_creat(-1);"
```

**You should see:** both refused — `permission denied for function lo_import` and `permission denied for function lo_creat` (or Postgres's own superuser-only wording on the first, since that API is superuser-restricted by Postgres itself; `deploy/sandbox/10-roles.sh` explains why the two are handled differently). Neither succeeds.

### 13. The owner role cannot reach any other database on the instance

```
podman compose exec -e PGPASSWORD='<OWNER_PW>' sandbox \
  psql -h localhost -U askwell_sandbox_owner -d postgres -c "SELECT 1;"
```

**You should see:** `psql: error: connection to server ... failed: FATAL: permission denied for database "postgres"` — `10-roles.sh` revoked `PUBLIC`'s default `CONNECT` on `postgres` and `template1`, and neither role was ever granted it back.

### 14. The readonly role can read what the owner created, and nothing more

```
podman compose exec -e PGPASSWORD='<OWNER_PW>' sandbox \
  psql -h localhost -U askwell_sandbox_owner -d <NAME> -c "CREATE TABLE t (x int); INSERT INTO t VALUES (1);"

podman compose exec -e PGPASSWORD='<READONLY_PW>' sandbox \
  psql -h localhost -U askwell_sandbox_readonly -d <NAME> -c "SELECT x FROM t;"
```

**You should see:** the second command returns the row `1` — the default-privilege grant this ticket sets up (`ALTER DEFAULT PRIVILEGES ... GRANT SELECT`) means the readonly role sees a table the owner created after the database existed, with nobody granting it by hand.

```
podman compose exec -e PGPASSWORD='<READONLY_PW>' sandbox \
  psql -h localhost -U askwell_sandbox_readonly -d <NAME> -c "INSERT INTO t VALUES (2);"
```

**You should see:** `ERROR: permission denied for table t`.

---

## 3. No route anywhere else — the network boundary, not a promise

### 15. The sandbox container cannot resolve Askwell's own database

```
podman compose exec sandbox getent hosts postgres
```

**You should see:** no output and a non-zero exit (`getent` prints nothing and fails) — the name does not resolve at all, because `sandbox` is not on the `internal` network `postgres` lives on. This is stronger than a permission refusal: there is no route to attempt one over.

### 16. The sandbox container cannot resolve the egress proxy

```
podman compose exec sandbox getent hosts egress-proxy
```

**You should see:** the same — no resolution. The sandbox has no path to the proxy, let alone through it to the internet (C1, C3 together).

### 17. Askwell's own database cannot resolve the sandbox either

```
podman compose exec postgres getent hosts sandbox
```

**You should see:** no resolution — confirming the isolation runs both directions, not just "the sandbox can't get out."

### 18. Confirm nothing beyond the API is published on the host

```
scripts/verify-localhost-binding.sh
```

**You should see:** the script reports success — `sandbox`, like every other service, has no published port; `127.0.0.1:8000` (the API) is the only thing anything outside the containers can reach.

---

## 4. A crash mid-import leaves nothing behind

### 19. Create a database and deliberately do not register it against a source

Repeat step 6 to create a second sandbox database — call it `<ORPHAN>` — but this time do **not** insert any `sources` row naming it. This reproduces exactly what a process killed between `create_database` and the `sources` row committing leaves behind.

```
podman compose exec sandbox psql -U askwell_sandbox -d postgres -c "SELECT datname FROM pg_database WHERE datname = '<ORPHAN>';"
```

**You should see:** one row — the orphan exists, unclaimed by anything.

### 20. Restart the worker and let it reclaim on startup

```
podman compose restart worker
```

Give it a few seconds, then:

```
podman compose exec sandbox psql -U askwell_sandbox -d postgres -c "SELECT datname FROM pg_database WHERE datname = '<ORPHAN>';"
```

**You should see:** no rows — `<ORPHAN>` is gone. `<NAME>` from step 6, if you inserted a `sources` row claiming it, would still be present; this document did not, so drop it by hand in the cleanup section below rather than relying on reclaim to distinguish a real gap from an untracked test artefact.

### 21. Confirm the reclaim wrote its own decisions record, naming the reason

```
scripts/dev.sh psql <<'SQL'
SELECT payload FROM audit_decisions
WHERE kind = 'sandbox_database_dropped' AND payload->>'database' = '<ORPHAN>';
SQL
```

**You should see:** one row, `payload->>'reason'` equal to `orphaned_at_startup` — distinguishable from an ordinary, requested drop.

---

## 5. The sandbox failing to start does not read as "Askwell is broken"

### 22. Stop the sandbox and reload the app

```
podman compose stop sandbox
```

Reload `http://127.0.0.1:8000` in the browser.

**You should see:** an alarm banner reading **"sandbox is not available"** (the raw component name — see "Where this stops on purpose" and Known gaps) with a reason naming the connection failure. The rest of the shell still renders; nothing else about the page suggests the whole application is down.

```
curl -s http://127.0.0.1:8000/health | python3 -m json.tool
```

**You should see:** `sandbox` reported `"state": "unreachable"` while `database`, `queue` and `egress_proxy` still report `"reachable"` — the per-component health model this ticket's own acceptance criterion asks for, proven against the real running app rather than only `_targets()`'s source.

Click into an existing screen that has nothing to do with dumps — **Library**, if you have a document source added, or **Settings**. **You should see:** it works exactly as before. A document source's own material is untouched by the sandbox being down, which is the whole point of the edge case in the ticket ("document sources keep working").

### 23. Bring it back

```
podman compose start sandbox
```

Reload the app. **You should see:** the alarm banner is gone.

---

## Clean up

```
podman compose exec sandbox psql -U askwell_sandbox -d postgres -c "DROP DATABASE IF EXISTS \"<NAME>\" WITH (FORCE);"
scripts/dev.sh psql <<'SQL'
DELETE FROM audit_decisions WHERE payload->>'database' IN ('<NAME>', '<ORPHAN>');
SQL
```

Deleting from `audit_decisions` here is only ever appropriate for this document's own throwaway test data on a machine you control (C6 says the application never rewrites history — this is you, by hand, cleaning up a manual test, not the application). Do not do this against any database holding real material.

---

## Known gaps

- **No import exists.** `M4-DUMP-ING-088` has not landed — every sandbox database in this document was created by calling `askwell.sandbox.create_database` directly; there is no **Add a source** flow that reaches this code yet, and no dump file was ever actually loaded into anything.
- **No size or time cap.** `M4-DUMP-VAL-089` has not landed — nothing in this document bounds how large a sandbox database can grow or how long an import can run. The edge case ("the sandbox volume filling") is only structurally *possible* to bound (separate volume, confirmed in step 4) — it is not yet bounded.
- **`web/lib/health.ts`'s `COMPONENT_LABELS` has no `sandbox` entry**, so the alarm banner in §5 reads the raw component name rather than a name a non-technical user recognises. Not a regression from this ticket — the map simply predates it — but worth fixing before this state is one a real user hits.
- **No library-scoped "needs attention" message exists.** `docs/states-and-edge-cases.md` §1 names a future state, referencing `ux/library.md` §5, where dump-backed sources show a specific notice naming the sandbox as down. That UX section is not written and there are no dump-backed sources to show it against — today, a sandbox outage surfaces only as the generic, app-wide alarm banner exercised in §5 above.
- **The two fixed roles' `CONNECT` grant accumulates across every sandbox database ever created**, rather than being scoped to only the databases a role currently has reason to reach. Filed as issue #330 against `M4-DUMP-ING-088`, which is where a real caller granting/revoking per-import will matter; not exercised or fixed in this document.
