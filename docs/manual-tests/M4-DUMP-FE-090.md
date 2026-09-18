# Manual test — M4-DUMP-FE-090, the dump route: the calm warning and the refusal with routes out

**Ticket:** `M4-DUMP-FE-090` — the database-dump route on the add-source screen: the once-only
sandbox statement, engine detection with a refusal that always names both routes out, and
progress/abort/failure rendering for the import.
**Version under test:** `0.4.7`
**Time:** about 40 minutes, plus a first stack build.
**Who can run it:** a browser and a terminal. One `psql` query, to confirm the record left
behind by a successful import.

**What is being checked.** `web/components/add/add-screen.tsx`'s `DumpRoute` and `DumpQueued`;
`web/lib/dump-source.ts`; `POST /sources/dump` in `api/src/askwell/sources.py`; the dump
branch of `askwell.filetypes.detect`. Before this ticket there was no screen that reached
`dump_import` at all — `M4-DUMP-ING-088`'s manual test ran every import from inside the
container with a Python one-liner. This is the first walkthrough that starts cold, in a
browser, and reaches the same code by clicking.

**Where this stops on purpose — read before reporting anything below as a defect.**

- **No connect-a-database route.** §4 of `docs/ux/add-source.md` is a separate ticket. "Connect
  live" in the MySQL/SQL Server refusal is copy naming a route that exists in the document, not
  yet in the app — do not click looking for it.
- **No schema introspection surfaced on the screen.** A successful import shows *Imported*;
  what tables it found is a database row (`M4-DUMP-ING-088`), not yet rendered anywhere.
- **Compressed dumps are always refused.** `docs/ux/add-source.md` §5 allows a recognised
  compressed format through; v1 recognises none, so every `.sql.gz` is refused. That is
  `filetypes.REFUSED_DUMP_COMPRESSED`, not a bug in this ticket.

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

### 1. Make files to test with

```
mkdir -p ~/askwell-test/dumps
cd ~/askwell-test/dumps

cat > good.sql <<'EOF'
--
-- PostgreSQL database dump
--
CREATE TABLE customers (id integer primary key, name text);
INSERT INTO customers VALUES (1, 'Ravenholt Textiles');
EOF

cat > mysql-export.sql <<'EOF'
-- MySQL dump 10.13  Distrib 8.0.35, for Linux (x86_64)
/*!40101 SET NAMES utf8 */;
CREATE TABLE `customers` (`id` int, `name` varchar(255));
INSERT INTO `customers` VALUES (1,'Ravenholt Textiles');
EOF

cat > unknown-engine.sql <<'EOF'
CREATE TABLE customers (id INT PRIMARY KEY, name TEXT);
INSERT INTO customers VALUES (1, 'Ravenholt Textiles');
EOF

echo "Dear Ravenholt Textiles, thank you for your order." > letter.sql

gzip -k good.sql
```

That gives you: a real PostgreSQL dump, a real MySQL dump, a plain SQL script with no engine
marker at all, a plain-text letter renamed `.sql`, and a gzip-compressed dump.

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

### 4. Open Askwell

`http://127.0.0.1:8000`. **You should see:** the shell load with no alarm banner.

### 5. Navigate to Add a source, by clicking

Find and click into **Add a source** from wherever the shell offers it (library, empty state,
or first-run). **You should see:** the "Add a source" heading, the indexing statement, a
**Files** route, and below it a **Database dump** card headed "Database dump" with the line
"PostgreSQL .sql, .dump and .backup files. MySQL and SQL Server are not imported as dumps —
connect live, or export as CSV."

---

## 1. The calm statement — before anything is picked

### 6. Read the statement without touching the file picker

**You should see**, directly under the route's own heading, before any file is chosen:

> **This file contains commands, not just data.** Askwell runs it inside a sealed database
> that cannot reach your other sources, the internet, or Askwell's own files. If the dump is
> broken or malicious, only that sealed copy is affected.

**Confirm, by looking, not by reading the code:**

- It is plain paragraph text, not inside a dialog, popup or overlay.
- There is no checkbox, "I understand" button, or any control that has to be acknowledged
  before **Choose a dump file** becomes clickable.
- It appears exactly once on the card — it does not repeat after a file is picked or after an
  import starts.

---

## 2. A PostgreSQL dump imports, with progress through to done

### 7. Pick the good dump

Click **Choose a dump file** and select `~/askwell-test/dumps/good.sql`.

**You should see:** the filename `good.sql` appear beside the button, and — because
`good.sql` looks like a dump from its own header — a field appear below asking "Which folder
is "good.sql" in?", with an **Import** button.

### 8. Answer the folder question

Type the absolute path `/home/<you>/askwell-test/dumps` into the field and click **Import**.

**You should see** one of two things, and either is correct on a first run:
- If this folder has never been nominated, a note appears asking Askwell to be told about it,
  with a **Nominate `/home/<you>/askwell-test/dumps`** button. Click it, and the import
  continues on its own — you do not need to click Import again.
- If it was already nominated (a Files-route walkthrough on the same machine can leave it so),
  the import proceeds straight to the next step.

### 9. Watch it queue and import

**You should see** the card replace the picker with a **Queued** block: "good.sql is queued
from your machine. Indexing runs in the background — you can leave this page and it carries
on. Nothing has been copied." followed by "Importing good.sql into a sealed database. This
runs in the background and does not need this page open."

### 10. Wait for it to finish

A dump this small finishes in well under a minute. **You should see** the block change to
**Imported**: "good.sql loaded into its own sealed database." with an **Add another dump**
button.

### 11. Confirm the record left behind

```
scripts/dev.sh psql
```

```sql
SELECT name, kind, status, sandbox_db FROM sources WHERE name = 'good.sql';
```

**You should see:** one row, `kind = dump`, `status = ready`, `sandbox_db` non-null — the same
outcome `M4-DUMP-ING-088`'s manual test confirmed by calling the module directly, now reached
by clicking through the screen.

### 12. Add another dump

Click **Add another dump**. **You should see:** the card reset to the picker, the calm
statement still shown exactly once above it.

---

## 3. A MySQL dump is refused with both routes out

### 13. Pick the MySQL export

Click **Choose a dump file**, select `mysql-export.sql`.

**You should see:** a marked note appear, headed "a MySQL dump", reading:

> Askwell imports PostgreSQL dumps. For MySQL, either connect to the database directly or
> export the tables as CSV; both work, and CSV usually gives better answers because Askwell
> will ask about anything ambiguous.

**Confirm:** no folder question appears, no Import button appears — the refusal is the only
thing offered for this file. Both alternatives (connect directly, export as CSV) are named in
the same sentence; neither is missing.

---

## 4. A dump whose engine cannot be told is asked about, not guessed at

### 14. Pick the unmarked script

Click **Choose a dump file**, select `unknown-engine.sql`.

**You should see:** a note headed "a SQL dump" reading:

> Askwell could not tell which database produced this dump. If it came from PostgreSQL,
> resaving it with pg_dump's own default output usually fixes this. If it came from MySQL or
> SQL Server, connect to the database directly, or export the tables as CSV — both work, and
> CSV usually gives better answers because Askwell will ask about anything ambiguous.

**Confirm:** this reads as a question ("If it came from...") rather than a flat rejection, and
still names both live alternatives for a non-PostgreSQL origin.

---

## 5. A file with a dump extension that is not a dump

### 15. Pick the renamed letter

Click **Choose a dump file**, select `letter.sql`.

**You should see:** a note reading "This does not look like a database dump. Askwell imports
PostgreSQL .sql, .dump and .backup files." — distinct from the two messages above: this one
never mentions MySQL or SQL Server, because the file is not a dump of any kind.

---

## 6. A compressed dump is refused with the reason

### 16. Pick the gzip file

Click **Choose a dump file**, select `good.sql.gz`.

**You should see:** a note reading "Askwell does not import compressed dumps yet. Decompress
it first, or connect to the database directly, or export the tables as CSV — both work, and
CSV usually gives better answers because Askwell will ask about anything ambiguous."

---

## 7. A failed import renders its own reason, with a route back

### 17. Force a load failure

Make a dump that loads partway then breaks:

```
cat > ~/askwell-test/dumps/broken.sql <<'EOF'
--
-- PostgreSQL database dump
--
CREATE TABLE partial (id integer primary key);
INSERT INTO partial VALUES (1);
THIS LINE IS NOT VALID SQL;
EOF
```

Pick `broken.sql`, answer the folder question again if asked (same folder as before, so it
should not re-prompt), click **Import**.

**You should see:** the same Queued/Importing sequence as step 9, then the block change to
**This import did not finish**, with the reason naming the syntax error from `psql`'s own
stderr (something containing `THIS`) rather than a bare status code, and a **Try another dump**
button that returns to the picker.

---

## Known gaps

Not defects — deliberately not built by this ticket or an earlier one:

- **No connect-a-database route.** The MySQL/SQL-Server refusal names "connect to the database
  directly" as a route that exists in `docs/ux/add-source.md` §4, not yet in the app.
- **No schema introspection on screen.** `Imported` states only that loading finished; the
  table list `M4-DUMP-ING-088` introspects is a database row, not rendered here.
- **No size or time cap exercised in this document.** `M4-DUMP-VAL-089` enforces a 5 GB / 10
  minute cap; reproducing an abort by hand would mean generating a multi-gigabyte dump, which
  this document does not do. The failed-import rendering in §7 above is the same code path an
  abort uses (`status = 'attention'` with a specific `last_error`), so it is exercised
  indirectly.
- **No compressed format is ever accepted.** `docs/ux/add-source.md` §5 allows a recognised
  compressed dump through; v1 recognises none, so §6 above is unconditional, not a partial
  implementation.
- **Abort mid-import from the browser is not covered.** Nothing on the screen offers a cancel
  button for a running import; only completion, in one of its two outcomes, is rendered.
