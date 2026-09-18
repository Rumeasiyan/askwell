# Manual test — M4-CONN-FE-096, the connection wizard for a live database

**Ticket:** `M4-CONN-FE-096` — the wizard that connects Askwell to a database the user
already runs: host/port/database/user/password, connect, a minimal read check, schema
introspection, listing in the library and settings.
**Version under test:** `0.4.8`
**Time:** about 35 minutes, plus a first stack build.
**Who can run it:** a browser and a terminal, with `podman compose exec` access to the
`sandbox` container to stand up a database to connect *to*.

**What is being checked.** `web/components/add/add-screen.tsx`'s `ConnectionRoute` and
`ConnectionQueued`; `web/lib/connection-source.ts`; `web/components/settings/connections.tsx`;
`POST /sources/connection` in `api/src/askwell/sources.py`; `api/src/askwell/connections.py`.

**Where this stops on purpose — read before reporting anything below as a defect.**

- **No write-permission probe.** `docs/ux/add-source.md` §4 step 2 refuses a write-capable
  credential, naming the permission found. That refusal is `M4-CONN-SEC-097` and is not wired
  up — a write-capable credential connects successfully today, and the wizard says so once, in
  prose, rather than implying a check that has not run.
- **No credential encryption.** `M4-CONN-SEC-098`. `config_encrypted` holds the credential as
  plain JSON bytes today.
- **No full schema introspection.** Table names only. Column types, keys and relationships are
  `M4-SCHEMA-ING-100`.
- **No "Network activity" counter on the settings screen.** `docs/ux/settings.md` §4 names a
  separate egress-proxy-refusal figure; nothing on `/settings/` renders it yet, so §5 below
  checks only the "Connected databases" count, not a side-by-side comparison against it.
- **A real external database is not what this document connects to.** No permit mechanism
  exists yet for a live connection's destination through the egress proxy (`api/src/askwell/
  connections.py`'s own module docstring, and `docs/decisions.md`). This walkthrough instead
  stands up a throwaway database inside the `sandbox` container, which `api`/`worker` already
  have a route to on the `sandbox` Compose network — that is not a real live-connection
  destination in production terms, but it is real Postgres, reached by a real socket, through
  the real wizard, which is what this ticket built.

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
of `SANDBOX_READONLY_PASSWORD` and `SANDBOX_POSTGRES_USER` — you will type one of them into the
wizard later.

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

### 3. Stand up a database to connect to

This plays the part of "a database the user already runs" — inside `sandbox`, which is the
only Postgres instance `api`/`worker` can reach by name.

```
podman compose exec sandbox psql -U "$(grep ^SANDBOX_POSTGRES_USER .env | cut -d= -f2)" -d postgres <<'SQL'
CREATE DATABASE conn_test OWNER askwell_sandbox_owner;
SQL
```

**You should see:** `CREATE DATABASE`.

```
podman compose exec sandbox psql -U askwell_sandbox_owner -d conn_test <<SQL
CREATE TABLE customers (id integer primary key, name text);
INSERT INTO customers VALUES (1, 'Ravenholt Textiles');
GRANT CONNECT ON DATABASE conn_test TO askwell_sandbox_readonly;
GRANT USAGE ON SCHEMA public TO askwell_sandbox_readonly;
GRANT SELECT ON customers TO askwell_sandbox_readonly;
CREATE ROLE conn_test_noselect LOGIN PASSWORD 'noselect-test-pw';
GRANT CONNECT ON DATABASE conn_test TO conn_test_noselect;
GRANT USAGE ON SCHEMA public TO conn_test_noselect;
SQL
```

**You should see:** `CREATE TABLE`, `INSERT 0 1`, two `GRANT`s, `CREATE ROLE`, two more
`GRANT`s. `conn_test_noselect` can connect and see the table exists but was never granted
`SELECT` on it — that is deliberate, for §4 below.

Note the readonly password:

```
grep ^SANDBOX_READONLY_PASSWORD .env
```

### 4. Open Askwell

`http://127.0.0.1:8000`. **You should see:** the shell load with no alarm banner.

### 5. Navigate to Add a source, by clicking

Click **Library** in the rail, then click **Add a source** in the empty-library card.
**You should see:** the "Add a source" heading, the indexing statement, a **Files** route, a
**Database dump** card, and below both a **Connect a database** card reading "PostgreSQL,
MySQL, MariaDB or SQL Server. Connect with a read-only user — the refusal for a write-capable
credential is not wired up yet." with an **Engine** dropdown and Host/Port/Database/User/
Password fields.

---

## 1. A wrong host is a distinct failure from a wrong password

### 6. Type a host that cannot resolve

In the **Connect a database** card: Engine `PostgreSQL`, Host `no-such-host.askwell-test`,
Port `5432` (unchanged), Database `conn_test`, User `askwell_sandbox_readonly`, Password (the
value you noted in step 3). Click **Connect**.

**You should see:** the button read "Connecting…" briefly, then a marked note headed
**"Host not found"** reading "Askwell could not resolve that host name. Check it for a typo."

---

## 2. Wrong credentials are a different message again

### 7. Fix the host, break the password

Change Host to `sandbox`, leave everything else, but change Password to something wrong, e.g.
`definitely-wrong`. Click **Connect**.

**You should see:** a note headed **"Credentials not accepted"** reading "That user name or
password was not accepted." — a different heading and a different sentence than step 6's,
confirming the two are distinguishable rather than a shared "could not connect".

---

## 3. A network the egress proxy would block names that, not a wrong host

### 8. Point at an address with no route

Change Host to `203.0.113.5` (a reserved, non-routable test address — safe to use, it resolves
to nothing real), Password back to the correct readonly password. Click **Connect**.

**You should see:** a note headed **"Blocked by network policy"** whose body states plainly
that Askwell's network policy blocked the connection, that local mode has no outbound route by
default, that a live database needs its own explicitly permitted route which does not exist
yet in this build, and that this is not a wrong host or a wrong password. **Confirm:** this
reads as a fourth, distinct message — not a reworded "host not found".

---

## 4. Connects, but cannot read — named as a permissions problem

### 9. Use the no-select role

Change Host back to `sandbox`, User to `conn_test_noselect`, Password to `noselect-test-pw`.
Click **Connect**.

**You should see:** a note headed **"Connected, but cannot read"** naming the user
(`'conn_test_noselect'`) and stating it has no `SELECT` privilege on any table in the database,
with an instruction to grant `SELECT` on the tables Askwell should read. **Confirm:** this is
worded as a permissions problem, not folded into the credentials message from step 7 — a wrong
password and a connection that succeeds but cannot read are different fixes.

---

## 5. A valid read-only connection connects, introspects, and is listed

### 10. Connect for real

User `askwell_sandbox_readonly`, Password the value from step 3, Host `sandbox`, Database
`conn_test`, Port `5432`, Engine `PostgreSQL`. Click **Connect**.

**You should see:** the form replaced by a **Connected** block: "conn_test on sandbox is
recorded. Reading its tables runs in the background — you can leave this page and it carries
on." followed by "Read access confirmed at connection time. Write permissions have not been
checked — that refusal is not wired up yet." and "Reading conn_test on sandbox's schema."

### 11. Wait for introspection to finish

A single-table database finishes in well under a minute. **You should see:** the block change
to **Ready**: "conn_test on sandbox is listed in the library." with an **Add another
connection** button.

### 12. Confirm the record and the schema note

```
scripts/dev.sh psql
```

```sql
SELECT name, kind, status FROM sources WHERE kind = 'connection';
```

**You should see:** one row, `name = conn_test on sandbox`, `status = ready`.

```sql
SELECT table_name, description FROM schema_notes
WHERE source_id = (SELECT id FROM sources WHERE kind = 'connection' LIMIT 1);
```

**You should see:** one row, `table_name = customers`, `description = Table customers.` — the
introspection result `record_introspection` wrote.

### 13. Check the library, by clicking

Click **Library** in the rail. **You should see:** `conn_test on sandbox` listed with
"Connection · Added <today's date>" and, beneath it, "Read access confirmed at connection
time. Write permissions have not been checked — that refusal is not wired up yet."

### 14. Check settings, by clicking

Click **Settings** in the rail. **You should see:** a **Connected databases** section reading
"1 connected database", with `conn_test on sandbox` listed and "Read access confirmed · write
permissions not yet checked" beside it — this is the read-only status the AC requires be
visible in settings.

### 15. Add another connection

Click **Add another connection**. **You should see:** the card reset to the empty form, ready
for another attempt.

---

## 6. Invalid input is caught before anything is attempted

### 16. Leave a required field empty

Reload `/sources/add/` (a fresh form). Leave **Host** empty, type a database and user name.
**You should see:** the **Connect** button stays disabled — no request is sent, matching the
AC "Invalid input is caught before a connection attempt."

### 17. Type an out-of-range port

Fill in Host and Database and User, then set Port to `99999` in the number field and submit.

**You should see:** a note headed **"Not a valid port"** reading "Port must be between 1 and
65535." — caught by `validate_fields` before a socket was ever opened; confirm no "Connecting…"
state was shown first (there is nothing to wait for).

---

## Known gaps

Not defects — deliberately not built by this ticket or an earlier one:

- **No write-permission probe.** `docs/ux/add-source.md` §4 step 2's refusal
  ("These credentials can modify `orders`...", with the read-only-user SQL) is
  `M4-CONN-SEC-097`. A write-capable credential connects successfully today; §5 above used a
  role that happens to be read-only, but nothing in this build would have stopped a
  write-capable one.
- **No credential encryption.** `M4-CONN-SEC-098`. The credential in `sources.config_encrypted`
  is JSON, not ciphertext, for this ticket.
- **No full schema introspection.** Table names only (§5, step 12). Column names, types, keys
  and relationships, and the "raise clarifications for unguessable columns" step in the
  ticket's own Context, are `M4-SCHEMA-ING-100` — nothing on this screen or in the library asks
  a clarification about a column yet.
- **No "Network activity" counter to compare against.** `docs/ux/settings.md` §4 names a
  separate egress-proxy-refusal figure that would sit beside "Connected databases" and stay
  zero; `/settings/` does not render it yet, so step 14 checks the connection count in
  isolation.
- **No reconfigure or delete for an existing connection.** Only creation is in scope; nothing
  on the library or settings screen edits or removes a `connection` source once added.
- **A stuck `queued` connection has no reconcile sweep.** Same known gap issue #340 already
  tracks for `dump`/`table` sources (`connections.dispatch_introspection`'s own docstring) — a
  connection that queues while the worker is down stays `queued` until the worker restarts and
  a new job is dispatched by hand; this document's stack is up throughout, so it does not
  exercise that path.
