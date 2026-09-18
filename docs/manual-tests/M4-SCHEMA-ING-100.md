# Manual test — M4-SCHEMA-ING-100, introspect and index the schema

**Ticket:** `M4-SCHEMA-ING-100` — on connect or import, Askwell reads every table and view's
columns, types, primary keys and foreign keys, and writes them as `schema_notes` rows the
existing lexical retrieval already ranks by relevance. Foreign keys let Askwell infer a
relationship instead of asking about it. Re-introspection, on demand or on reconnect, updates
the inventory rather than duplicating it. A table the read-only role cannot see is omitted,
with a count of how many were.
**Version under test:** `0.4.11`
**Time:** about 30 minutes, plus a first stack build.
**Who can run it:** a browser, a terminal, `podman compose exec` access to the `sandbox`
container.

**What is being checked.** `api/src/askwell/schema_introspect.py` — `_introspect_postgresql_blocking`,
`write_schema_inventory`, `dispatch_reintrospection`, `reintrospect_sandbox_source` — wired
into `connections.py`'s `dispatch_introspection` → `run_introspection` → `_run_deep_introspection`
(the automatic run right after a connection is created) and into `worker.py`'s
`reintrospect_source_job` (the on-demand run behind `POST /sources/{id}/reintrospect`,
`sources.py:1260`). `api/tests/test_schema_introspect.py` is the authoritative automated proof
(pure-Python row-grouping for all three engines, plus `requires_db` cases against a real
sandbox instance for the omitted-object edge case); this document repeats the connect,
inspect, add-a-table, re-introspect path against a cold-started stack, and adds the one thing
a pytest run does not show — what a person actually sees in the browser at each stage.

**Where this stops on purpose — read before reporting anything below as a defect.**

- **There is no schema/table/column viewer in the library.** `docs/ux/library.md` §2 specifies
  only the row shape (name, kind, status, coverage, clarification count) — no source-detail
  screen exists in that document or in `web/`, and `web/components/library/library-screen.tsx`
  confirms it: a source is a single collapsible row, never a drill-in page. What this ticket
  produces (table and column descriptions, foreign keys) lives only in the `schema_notes`
  table and is surfaced today through retrieval when a question is asked about the data — never
  through a page that lists them. Steps below that need to see the inventory itself read it
  with `scripts/dev.sh psql`, not by clicking, because there is nowhere to click.
- **There is no "re-introspect" button anywhere in `web/`.** `grep -rn "reintrospect" web/`
  finds nothing. `POST /sources/{id}/reintrospect` (`sources.py:1260`) exists and is exercised
  below with `curl`, the same way `M2-DELETE-BE-061`'s manual test drove `DELETE /sources/{id}`
  before its own screen existed.
- **A real external database is still not what this document connects to** — the same standing
  limitation `M4-CONN-FE-096` and `M4-CONN-SEC-098`'s manual tests name: no permit mechanism
  exists yet for a live connection's destination through the egress proxy. This walkthrough
  connects to a throwaway database inside the `sandbox` container, which `api`/`worker` already
  reach on the `sandbox` Compose network.
- **Stored procedures and functions are not introspected.** Named in the ticket's own Testing
  Notes as a known gap, not a defect.
- **MySQL and SQL Server never report an omitted-object count** — `omitted_count` is `None` for
  both, by design (see the module's own docstring): neither engine exposes a privilege-independent
  catalog a restricted role can still read. Only the PostgreSQL path (§2 below) can demonstrate
  the omitted-object edge case at all, and this document tests only PostgreSQL — Askwell has no
  running MySQL or SQL Server instance to connect to in this environment.

None of the above is a defect in `M4-SCHEMA-ING-100` — its scope is the introspection and
indexing itself, not a screen to browse the result from. Sections below say which is which.

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

### 3. Stand up a database to connect to, with related tables and one hidden table

```
podman compose exec sandbox psql -U "$(grep ^SANDBOX_POSTGRES_USER .env | cut -d= -f2)" -d postgres <<'SQL'
CREATE DATABASE schema_ing_test OWNER askwell_sandbox_owner;
SQL
podman compose exec sandbox psql -U askwell_sandbox_owner -d schema_ing_test <<'SQL'
CREATE TABLE customers (id integer primary key, name text not null);
CREATE TABLE orders (
  id integer primary key,
  customer_id integer references customers(id),
  total numeric
);
CREATE VIEW open_orders AS SELECT * FROM orders WHERE total IS NOT NULL;
CREATE TABLE payroll (id integer primary key, salary numeric);
GRANT CONNECT ON DATABASE schema_ing_test TO askwell_sandbox_readonly;
GRANT USAGE ON SCHEMA public TO askwell_sandbox_readonly;
GRANT SELECT ON customers, orders, open_orders TO askwell_sandbox_readonly;
SQL
```

**You should see:** `CREATE DATABASE`, then `CREATE TABLE` ×3, `CREATE VIEW`, and three
`GRANT`s. `payroll` is deliberately left with no `SELECT` grant to `askwell_sandbox_readonly`
— this is §2's hidden table below.

### 4. Open Askwell and confirm nothing is alarmed

Open a browser at `http://127.0.0.1:8000`. **You should see:** the shell load with no alarm
banner — `database`, `sandbox`, `queue`, `egress_proxy` and `inference` all reachable.

---

## 1. Connecting yields the table, column and relationship inventory

### 5. Navigate to Add a source, by clicking

Click **Library** in the rail. **You should see:** the empty-library card naming the four ways
to add a source. Click **Add a source**, then click into the **Connect a database** card.
**You should see:** the Engine dropdown and Host/Port/Database/User/Password fields.

### 6. Connect for real

Engine `PostgreSQL`, Host `sandbox`, Port `5432`, Database `schema_ing_test`, User
`askwell_sandbox_readonly`, Password the value of `SANDBOX_READONLY_PASSWORD` from `.env`.
Click **Connect**.

**You should see:** the form replaced by a **Connected** block reading "`schema_ing_test on
sandbox` is recorded. Reading its tables runs in the background", then — within a few seconds,
this is one small database — a **Ready** block reading "`schema_ing_test on sandbox` is listed
in the library."

### 7. Confirm the source is listed and ready

Click **Library**. **You should see:** a row for `schema_ing_test on sandbox`, kind
`Connection`, status **Ready**.

### 8. Read the inventory this run produced

There is no page for this — see "Where this stops on purpose" above. Read it directly:

```
scripts/dev.sh psql
```

```sql
SELECT table_name, column_name, description, origin
FROM schema_notes
WHERE source_id = (SELECT id FROM sources WHERE name = 'schema_ing_test on sandbox')
  AND superseded_by IS NULL
ORDER BY table_name, column_name NULLS FIRST;
```

**You should see:** one row with `column_name` NULL for each of `customers`, `orders` and
`open_orders` (table-level notes), plus one row per column of each. `payroll` is absent
entirely — it was never granted `SELECT`, so introspection could not confirm it existed as
anything other than "some object the readonly role can't read" (checked in §2, not here).

Two rows worth reading in full:

- The `orders` table-level row's `description` should read something close to: `Table orders.
  Columns: id, customer_id, total. Primary key: id. Foreign keys: customer_id ->
  customers.id.` — this is the ticket's own acceptance criterion: a relationship inferred from
  the foreign key, not asked about.
- The `open_orders` table-level row's `description` should start with `View open_orders.` —
  labelled as a view, not silently folded into "table".

All `origin` values should read `inferred` — nobody has written a schema note by hand yet.

### 9. Confirm the introspection run itself was logged

```sql
SELECT payload FROM audit_decisions WHERE kind = 'schema_introspected' ORDER BY created_at DESC LIMIT 1;
```

**You should see:** a payload naming this source's id, `"tables": 3` (`customers`, `orders`,
`open_orders` — `payroll` does not count, it was never visible), `"foreign_keys": 1`, and
`"omitted_count": 1` — the ticket's own "Audit / Logging Requirements: introspection runs are
logged", and the first confirmation that `payroll` was noticed as *existing but unreadable*
rather than simply not found (§2 confirms this distinction directly).

---

## 2. A table the readonly role cannot see is omitted, with a count — never named

### 10. Confirm `payroll` is not guessable from anything Askwell wrote

```sql
SELECT * FROM schema_notes WHERE description ILIKE '%payroll%';
```

**You should see:** no rows. This is the ticket's own edge case: "a table the read-only role
cannot see — omitted, with a note that some objects were not visible" — the note is the
`omitted_count` on the decisions record from step 9, and it is a count, never a name. Naming
`payroll` anywhere Askwell writes would defeat the entire point of introspecting as the
same role a query would run as (`docs/data-sources.md` §4).

### 11. Grant access and re-introspect on demand

```
podman compose exec sandbox psql -U askwell_sandbox_owner -d schema_ing_test -c \
  "GRANT SELECT ON payroll TO askwell_sandbox_readonly;"
```

**You should see:** `GRANT`.

Get a session cookie the way a browser tab would (opening the interface establishes one
silently — `api/src/askwell/session.py`'s own docstring: "there is nothing to sign in to"),
then use it to call the re-introspect route the library has no button for yet:

```
SOURCE_ID=$(scripts/dev.sh psql -tAc \
  "SELECT id FROM sources WHERE name = 'schema_ing_test on sandbox'")
curl -s -c /tmp/askwell-cookies -H "Accept: text/html" http://127.0.0.1:8000/ -o /dev/null
curl -s -b /tmp/askwell-cookies -X POST \
  "http://127.0.0.1:8000/sources/${SOURCE_ID}/reintrospect" | python3 -m json.tool
```

**You should see:** `{"source_id": "<the same id>", "queued": true}` with a 202 — check with
`curl -s -o /dev/null -w "%{http_code}\n" -b /tmp/askwell-cookies -X POST
"http://127.0.0.1:8000/sources/${SOURCE_ID}/reintrospect"` if you want the status code
directly.

### 12. Confirm `payroll` now appears, and nothing already there was duplicated

Wait a few seconds for the worker to pick up the job, then:

```
scripts/dev.sh psql
```

```sql
SELECT table_name, column_name FROM schema_notes
WHERE source_id = (SELECT id FROM sources WHERE name = 'schema_ing_test on sandbox')
  AND superseded_by IS NULL
ORDER BY table_name, column_name NULLS FIRST;
```

**You should see:** the same rows as step 8, plus `payroll` (table-level) and `payroll.id`,
`payroll.salary`. Nothing from step 8 appears twice — re-introspecting an unchanged table
updates nothing, it only adds what is newly visible.

```sql
SELECT payload FROM audit_decisions WHERE kind = 'schema_introspected' ORDER BY created_at DESC LIMIT 1;
```

**You should see:** `"tables": 4` now, and `"omitted_count": 0` — the ticket's own acceptance
criterion "re-introspection updates the inventory", observed as a count changing from 1 to 0
rather than inferred.

---

## 3. A new table appears after re-introspection — the ticket's own cold-start scenario

### 13. Add a table nobody has told Askwell about yet

```
podman compose exec sandbox psql -U askwell_sandbox_owner -d schema_ing_test <<'SQL'
CREATE TABLE shipments (
  id integer primary key,
  order_id integer references orders(id),
  carrier text
);
GRANT SELECT ON shipments TO askwell_sandbox_readonly;
SQL
```

**You should see:** `CREATE TABLE`, `GRANT`.

### 14. Re-introspect and confirm it appears

```
curl -s -b /tmp/askwell-cookies -X POST \
  "http://127.0.0.1:8000/sources/${SOURCE_ID}/reintrospect" | python3 -m json.tool
```

Wait a few seconds, then:

```
scripts/dev.sh psql -c \
  "SELECT description FROM schema_notes WHERE source_id = '${SOURCE_ID}' AND table_name = 'shipments' AND column_name IS NULL AND superseded_by IS NULL"
```

**You should see:** one row, description reading `Table shipments. Columns: id, order_id,
carrier. Primary key: id. Foreign keys: order_id -> orders.id.` — the ticket's own cold-start
walkthrough ("Add a table in the database, use re-introspect, and confirm it appears"),
completed end to end: connect, inspect, add a table, re-introspect, see it.

---

## 4. Clean up

### 15. Drop the throwaway database

```
podman compose exec sandbox psql -U "$(grep ^SANDBOX_POSTGRES_USER .env | cut -d= -f2)" -d postgres -c \
  "DROP DATABASE schema_ing_test;"
rm -f /tmp/askwell-cookies
```

**You should see:** `DROP DATABASE`. This is cleanup, not part of the acceptance criteria — a
live connection's own database is never Askwell's to drop in real use; this one only exists
because step 3 created it for this walkthrough.

---

## Known gaps

Not defects — deliberately not built by this ticket, or not built at all yet:

- **No schema/table/column viewer anywhere in `web/`.** Everything this ticket writes is
  visible only through `schema_notes` (read with `psql` above) or, indirectly, through
  retrieval when a question touching that table is asked. The ticket's own Real-World Example
  ("a developer connects a database and immediately sees forty tables listed with their
  relationships, without writing anything") is true at the data layer this document exercises
  and false at the screen a person actually looks at. **Issue needed** — a source-detail view
  in the library (`docs/ux/library.md` §2 has no such section to extend; it would need one)
  that lists tables, columns, keys and relationships for a connection, dump or CSV source.
- **No re-introspect control in the library.** `POST /sources/{id}/reintrospect` exists and
  works (§2, §3 above); nothing in `web/` calls it. Filed together with the gap above, since
  a schema viewer without a refresh control on it would be half the feature.
- **Stored procedures and functions are not introspected.** Out of scope per the ticket's own
  Testing Notes.
- **The omitted-object count is PostgreSQL-only.** A MySQL or SQL Server connection always
  reports `omitted_count: None` regardless of what a restricted role cannot see — a real gap
  in what "omitted, with a note" can mean for those two engines, already named in
  `schema_introspect.py`'s own module docstring as filed separately rather than guessed at.
  This document could not exercise either engine directly: no MySQL or SQL Server instance
  runs anywhere in this stack.
- **A schema with thousands of tables** is not walked here — building one is disproportionate
  to a manual pass, and the bounded-retrieval acceptance criterion is already the subject of
  `askwell.memory.get_active_schema_notes`'s own `RELEVANT_NOTE_LIMIT` tests
  (`docs/memory-and-clarification.md`), not something a person needs to watch happen by eye.
- **Schema notes from clarifications** (a human explaining what a column means beyond its
  type) and **drift detection** (noticing a schema changed without anyone asking for
  re-introspection) are both named Out of Scope in the ticket itself — `M4-SCHEMA-ING-101` and
  `M4-SCHEMA-BE-102` respectively.
