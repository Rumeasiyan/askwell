# Manual test — M4-CONN-SEC-097, the write-permission probe that refuses write-capable credentials

**Ticket:** `M4-CONN-SEC-097` — after connecting, the wizard probes whether the credentials can
write. If they can, the connection is refused — not warned, not overridable — naming the
permission detected and the object it applies to, and offering copyable SQL to create a
read-only user for the detected engine.
**Version under test:** `0.4.9` (check `cat VERSION`).
**Time:** about 40 minutes, plus a first stack build.
**Who can run it:** a browser, a terminal, and `podman compose exec` access to the `sandbox`
container to stand up a database and test roles to connect *to*.

**What is being checked.** `api/src/askwell/connections.py` (`probe_connection`,
`_probe_postgresql_blocking`, `_write_capable_outcome`, `_probe_unreliable_outcome`,
`read_only_user_sql`, `record_write_probe_refusal`); `add_connection` in
`api/src/askwell/sources.py`; `web/components/add/add-screen.tsx`'s `ConnectionRoute` (the
`write_capable` heading and `ReadOnlyUserSql`); `web/components/settings/connections.tsx`.
`api/tests/test_connections.py` and `api/tests/test_connections_write_probe_db.py` are the
authoritative automated proof — the latter against a real Postgres, the same shape this
document exercises through the running application instead of `probe_connection` directly.

**Where this stops on purpose — read before reporting anything below as a defect.**

- **PostgreSQL only, exercised live.** MySQL/MariaDB and SQL Server write-permission parsing
  (`_find_mysql_write_grant`, `_find_sqlserver_write_permission`) has no engine in this stack to
  connect to — `api/tests/test_connections.py` covers both as pure parsing against fixed grant
  text, which this document does not repeat. Nothing about those two engines' UI path differs
  from PostgreSQL's; only the driver-level probe query differs.
- **`probe_unreliable` is not reproduced live.** It fires when the privilege-introspection query
  itself raises — Postgres exposes `information_schema` to any role that can connect, so there
  is no ordinary grant configuration that reproduces this by hand. `test_probe_unreliable_outcome_is_a_refusal_not_a_warning`
  in `api/tests/test_connections.py` is the authoritative proof that the outcome is a refusal,
  not a pass, when it does fire.
- **A real external database is not what this document connects to**, for the same reason
  `M4-CONN-FE-096`'s manual test names: no permit mechanism exists yet for a live connection's
  destination through the egress proxy. This walkthrough stands up disposable databases and
  roles inside the `sandbox` container, which `api`/`worker` already reach by name on the
  `sandbox` Compose network.
- **No credential encryption** (`M4-CONN-SEC-098`) and **no full schema introspection**
  (`M4-SCHEMA-ING-100`) — both already named as out of scope by `M4-CONN-FE-096`'s manual test
  and unchanged here.
- **Known bug, filed separately, not this ticket's fault to fix:** `web/components/library/
  library-screen.tsx` still tells the user "Write permissions have not been checked — that
  refusal is not wired up yet" for every connection source, which was true before this ticket
  and is now false — a write-capable credential never reaches a `connection` source at all. Filed
  as issue #349. §6 below walks past it and says what you should actually see there today.

---

## Before you start

```
cd ~/external/quantum-plus/askwell
```

If you have never run Askwell before:

```
cp -n .env.example .env
```

Open `.env` and confirm every `?set ... in .env` placeholder has a real value. Note the value of
`SANDBOX_POSTGRES_USER` (default `askwell_sandbox`) — you will use it once to create a test
database.

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

### 3. Stand up a test database and roles inside `sandbox`

This plays "a database the user already runs" — reachable from `api`/`worker` by name, the same
way `M4-CONN-FE-096`'s manual test used it.

```
podman compose exec sandbox psql -U "$(grep ^SANDBOX_POSTGRES_USER .env | cut -d= -f2)" -d postgres <<'SQL'
CREATE DATABASE sec_test OWNER askwell_sandbox_owner;
SQL
```

**You should see:** `CREATE DATABASE`.

```
podman compose exec sandbox psql -U askwell_sandbox_owner -d sec_test <<'SQL'
CREATE TABLE orders (id integer primary key, customer text);
INSERT INTO orders VALUES (1, 'Ravenholt Textiles');

CREATE SCHEMA archive;
CREATE TABLE archive.customers (id integer primary key, name text);

-- Read-only: SELECT on orders only.
CREATE ROLE sec_reader LOGIN PASSWORD 'reader-test-pw';
GRANT CONNECT ON DATABASE sec_test TO sec_reader;
GRANT USAGE ON SCHEMA public TO sec_reader;
GRANT SELECT ON orders TO sec_reader;

-- Table-level write: INSERT on orders. The UX copy's own example.
CREATE ROLE sec_writer_table LOGIN PASSWORD 'writer-table-pw';
GRANT CONNECT ON DATABASE sec_test TO sec_writer_table;
GRANT USAGE ON SCHEMA public TO sec_writer_table;
GRANT SELECT, INSERT ON orders TO sec_writer_table;

-- Database-level write: CREATE on the database, no table grants at all.
CREATE ROLE sec_writer_db LOGIN PASSWORD 'writer-db-pw';
GRANT CONNECT, CREATE ON DATABASE sec_test TO sec_writer_db;

-- Write reachable only through a second schema — the "varies by schema" edge case.
CREATE ROLE sec_writer_other_schema LOGIN PASSWORD 'writer-archive-pw';
GRANT CONNECT ON DATABASE sec_test TO sec_writer_other_schema;
GRANT USAGE ON SCHEMA public, archive TO sec_writer_other_schema;
GRANT SELECT ON orders TO sec_writer_other_schema;
GRANT SELECT, UPDATE ON archive.customers TO sec_writer_other_schema;
SQL
```

**You should see:** `CREATE TABLE`, `INSERT 0 1`, `CREATE SCHEMA`, `CREATE TABLE`, then three
`CREATE ROLE`/grant blocks for each of `sec_reader`, `sec_writer_table`, `sec_writer_db`,
`sec_writer_other_schema` with no error.

### 4. Open Askwell

`http://127.0.0.1:8000`. **You should see:** the shell load with no alarm banner.

### 5. Navigate to Add a source, by clicking

Click **Library** in the rail, then click **Add a source** in the empty-library card.
**You should see:** the "Add a source" heading, and below the Files and Database-dump cards, a
**Connect a database** card reading "PostgreSQL, MySQL, MariaDB or SQL Server. Connect with a
read-only user — a write-capable credential is refused, naming the permission found." — this
sentence itself is the change from `M4-CONN-FE-096`'s stale "the refusal ... is not wired up
yet"; **confirm it reads as a refusal, not a warning.**

---

## 1. A table-level write grant is refused, naming the permission and the table

### 6. Connect with `sec_writer_table`

Engine `PostgreSQL`, Host `sandbox`, Port `5432`, Database `sec_test`, User `sec_writer_table`,
Password `writer-table-pw`. Click **Connect**.

**You should see:** the button read "Connecting…" briefly, then a marked alarm note headed
**"These credentials can write"** reading "These credentials have INSERT on `orders`. Askwell
only connects with read-only access. Create a read-only user and try again — here is the SQL for
it." — naming both the exact permission (`INSERT`) and the exact table (`orders`), matching
`docs/ux/add-source.md` §4's own example copy almost verbatim.

### 7. Confirm there is no override

**You should see:** no button, checkbox or link anywhere on the card offering to proceed anyway.
The only actions available are editing the form fields and submitting again. **Confirm:** the
**Connect** button is still present and still submits — but resubmitting the same credentials
produces the identical refusal, not a second attempt at something else.

### 8. Confirm the SQL offered is correct for PostgreSQL

Below the alarm note, **you should see:** a read-only, selectable text box labelled "Create a
read-only user, then try again:" containing:

```
CREATE ROLE askwell_reader LOGIN PASSWORD 'choose-a-password';
GRANT CONNECT ON DATABASE sec_test TO askwell_reader;
GRANT USAGE ON SCHEMA public TO askwell_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO askwell_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO askwell_reader;
```

Click into the box. **You should see:** the full text auto-selected (click-to-select), so a
non-technical user can copy it in one action without hunting for the start and end.

---

## 2. A database-level grant is refused even with no table grants at all

### 9. Connect with `sec_writer_db`

Change User to `sec_writer_db`, Password to `writer-db-pw`. Click **Connect**.

**You should see:** the same **"These credentials can write"** heading, body reading "These
credentials have CREATE on the `sec_test` database. Askwell only connects with read-only access.
Create a read-only user and try again — here is the SQL for it." **Confirm:** this role has no
`INSERT`/`UPDATE`/`DELETE` grant on any table — the refusal fires purely from the database-level
`CREATE` privilege, proving the probe checks more than table grants.

---

## 3. Write ability reachable only through a second schema is still refused

### 10. Connect with `sec_writer_other_schema`

Change User to `sec_writer_other_schema`, Password to `writer-archive-pw`. Click **Connect**.

**You should see:** **"These credentials can write"** again, naming `UPDATE` and
`` `archive.customers` `` (the schema-qualified name, not just `customers` — confirm the schema
is visible in the object named, since this role's only reachable table is outside `public`).
**Confirm:** this satisfies the ticket's own edge case — "credentials whose write ability varies
by schema — refused if they can write anywhere reachable" — this role cannot write in `public` at
all, only in `archive`, and is refused all the same.

---

## 4. A read-only credential is accepted, and only then does introspection begin

### 11. Connect with `sec_reader`

Change User to `sec_reader`, Password to `reader-test-pw`. Click **Connect**.

**You should see:** the form replaced by a **Connected** block: "sec_test on sandbox is
recorded. Reading its tables runs in the background — you can leave this page and it carries
on." followed by "Read access confirmed and write access refused if found, both at connection
time." and "Reading sec_test on sandbox's schema."

### 12. Wait for introspection to finish

A single-readable-table database finishes in well under a minute. **You should see:** the block
change to **Ready**: "sec_test on sandbox is listed in the library." with an **Add another
connection** button.

### 13. Confirm the decisions record for the accepted connection

```
scripts/dev.sh psql
```

```sql
SELECT name, kind, status FROM sources WHERE kind = 'connection';
```

**You should see:** one row, `name = sec_test on sandbox`, `status = ready` — only the accepted
`sec_reader` connection is present; none of the three refused attempts in §1–§3 created a row,
since `create_connection_source` is never reached on a `write_capable` outcome.

---

## 5. Every refusal is a decisions record naming the permission, never the credential

### 14. Query the decisions store

Still in `scripts/dev.sh psql`:

```sql
SELECT kind, payload FROM audit_decisions WHERE kind = 'connection_write_refused' ORDER BY occurred_at;
```

**You should see:** three rows, in order — one per refusal in §1–§3 above:

- `{"engine": "postgresql", "host": "sandbox", "message": "These credentials have INSERT on `orders`. ..."}`
- `{"engine": "postgresql", "host": "sandbox", "message": "These credentials have CREATE on the `sec_test` database. ..."}`
- `{"engine": "postgresql", "host": "sandbox", "message": "These credentials have UPDATE on `archive.customers`. ..."}`

**Confirm, on all three rows:** the `payload` names the engine, host and the exact permission
and object detected, and contains no `user`, `password` field or credential value anywhere —
matching the ticket's own AC, "the refusal and the detected permission are decisions records"
and this module's own rule to never log the credential.

### 15. Confirm the local refusal counter, never transmitted

```sql
\q
```

```
podman compose exec redis redis-cli GET askwell:connections:write_probe_refused
```

**You should see:** `3` — one increment per refusal in §1–§3. **Confirm:** this is a plain
`redis-cli GET` against the stack's own, `internal`-network-only Redis; nothing about reading it
crossed a network boundary, and there is no surface anywhere in the product that transmits this
figure (C1) — the ticket's own AC asks only that the counter exist, not that anything display it
yet.

---

## 6. The library and settings surfaces after a real connection

### 16. Check the library, by clicking

Click **Library** in the rail. **You should see:** `sec_test on sandbox` listed with "Connection
· Added <today's date>" and, beneath it, **"Read access confirmed at connection time. Write
permissions have not been checked — that refusal is not wired up yet."**

**This line is wrong and is not a defect in this ticket** — it is issue #349, filed above. The
write probe already ran and already refused three credentials before this source ever existed;
this card describes a build from before `M4-CONN-SEC-097` landed. Do not report it again; the
issue tracks it.

### 17. Check settings, by clicking

Click **Settings** in the rail. **You should see:** a **Connected databases** section reading "1
connected database", with `sec_test on sandbox` listed and **"Read access confirmed · write
access refused if found"** beside it. **Confirm:** this text, unlike the library card in step 16,
is current — it is the corrected copy `CHANGELOG.md`'s `0.4.9` entry names for
`connections.tsx`.

---

## Known gaps

Not defects — deliberately not built by this ticket or an earlier one:

- **MySQL/MariaDB and SQL Server write detection is untested live.** No engine for either exists
  in this stack; `_find_mysql_write_grant` and `_find_sqlserver_write_permission` are proven only
  by `api/tests/test_connections.py`'s parsing tests against fixed grant/permission text.
- **`probe_unreliable` is not reproduced live**, for the reason stated at the top of this
  document — ordinary Postgres grants cannot make `information_schema` unreadable to a
  connecting role. Covered only by the unit test named above.
- **No credential encryption** (`M4-CONN-SEC-098`). `sources.config_encrypted` still holds the
  connection configuration as plain JSON bytes.
- **No full schema introspection** (`M4-SCHEMA-ING-100`). Table names only.
- **`library-screen.tsx` renders stale write-probe copy** — issue #349, not fixed by this
  document.
- **No reconfigure or delete for an existing connection**, and **no reconcile sweep for a stuck
  `queued` connection** — both already named as known gaps by `M4-CONN-FE-096`'s manual test and
  unchanged here.
