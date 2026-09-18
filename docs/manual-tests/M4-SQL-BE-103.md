# Manual test — M4-SQL-BE-103, schema retrieval and SQL generation

**Ticket:** `M4-SQL-BE-103` — retrieve the relevant schema subset, notes and memory for a
question, then generate one candidate query with a versioned prompt file. Picks the right
source when several databases are connected, asks rather than guesses when the choice is
ambiguous, and never runs anything against a database.
**Version under test:** `0.4.15` (check `cat VERSION`).
**Time:** about 60 minutes, plus a first stack build and native inference running.
**Who can run it:** a browser, a terminal, `podman compose exec` access to the `worker`
container, native `llama.cpp` inference running on the host (`scripts/dev.sh inference`).

**What is being checked.** `api/src/askwell/agent/sql_generate.py`
(`generate_candidate_query`, `select_database_source`, `compose_sql_generation`) and
`api/src/askwell/agent/prompts/sql_generation.v1.md`, backed by `api/tests/test_sql_generate.py`
(pure compose/extract tests, plus `requires_db` tests for selection and end-to-end generation
against real `schema_notes` rows). This document repeats the schema-selection and
generation behaviour against a cold-started stack with real inference, which the automated
suite does not exercise (it fakes the inference client).

**Where this stops on purpose — read before reporting anything below as a defect.**

- **Nothing in `web/` or `askwell.ask` calls `generate_candidate_query` yet.** `grep -rn
  "sql_generate" api/src web/` finds only the module and its own tests. The module's own
  docstring says the same: `sqlglot` validation (`M4-SQL-VAL-104`), `LIMIT` injection
  (`M4-SQL-VAL-105`), the dry run (`M4-SQL-VAL-106`) do not exist yet, so wiring generation into
  `POST /ask`'s turn flow before they exist would mean a model-written query reaching the
  database with nothing between — the one thing C2 exists to prevent. There is no "ask a
  database question" screen to click through for this specific step; the ask screen itself
  exists (`M1-ASK-FE-039a`) and can be used up through Step 4 below, but its answer today comes
  from document retrieval only, never SQL generation, regardless of what is asked. This
  document calls the module directly inside the running `worker` container, the same way
  `docs/manual-tests/M4-SQL-DB-107.md` did for `execute_sandbox_query`.
- **This exercises the sandbox (dump-backed) path only.** No live MySQL, MariaDB, or SQL Server
  connection runs in this stack, so `DatabaseSource.engine` values other than `postgresql` are
  not exercised end to end here — `test_a_connection_sources_engine_is_read_from_its_own_encrypted_config`
  in the automated suite is what proves that half.
- **Real inference is required**, unlike the automated suite (which passes a fake client
  returning a fixed string). The exact query text the model returns in Steps 10–14 is not
  guaranteed to be byte-identical between runs or model versions — what matters is that it
  references the right tables and columns, not its exact spelling.

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

### 1. Make two small dumps to import

```
mkdir -p ~/askwell-test/dumps
cd ~/askwell-test/dumps
cat > orders.sql <<'EOF'
--
-- PostgreSQL database dump
--
CREATE TABLE orders (
    id integer primary key,
    status text not null,
    shipped_at date
);
INSERT INTO orders VALUES
    (1, 'shipped', '2026-06-01'),
    (2, 'late', '2026-06-15'),
    (3, 'late', '2026-06-20'),
    (4, 'shipped', '2026-07-01');
EOF
cat > inventory.sql <<'EOF'
--
-- PostgreSQL database dump
--
CREATE TABLE widgets (
    id integer primary key,
    sku text not null,
    quantity integer
);
INSERT INTO widgets VALUES
    (1, 'WID-001', 40),
    (2, 'WID-002', 12);
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

### 3. Bring the stack up, migrate, and start native inference

```
podman compose up -d
scripts/dev.sh db upgrade head
```

In a separate terminal, on the host:

```
scripts/dev.sh inference
```

**You should see:** `postgres`, `sandbox`, `redis`, `egress-proxy`, `api`, `worker` all
reported created and started; migration finishing with no error; the inference process
logging that it is listening on its socket.

### 4. Open Askwell and add the first dump, by clicking

Open a browser at `http://127.0.0.1:8000`. **You should see:** the shell load with no alarm
banner.

Click **Add a source**, then click into the **Database dump** card. Click **Choose a dump
file** and select `~/askwell-test/dumps/orders.sql`. Type the absolute path
`/home/<you>/askwell-test/dumps` when asked which folder it is in, and click **Import** (click
**Nominate** if asked to nominate the folder).

**You should see:** **Queued**, then within well under a minute, **Imported**.

### 5. Answer the schema clarifications

The import triggers schema introspection and clarification (`M4-SCHEMA-ING-100` through
`-102`). **You should see** the source's schema notes appear for review — click through to
confirm or answer whatever it asks about `orders.status` and the other columns (its exact
prompts depend on what those earlier tickets built; answering them is what puts real
`schema_notes` rows in the database for this ticket's retrieval to find).

### 6. Read back the source id

There is no screen showing this directly — see "Where this stops on purpose" above.

```
scripts/dev.sh psql -c "SELECT id, name, status FROM sources WHERE name = 'orders.sql';"
```

**You should see:** one row, `status = ready`. Note the `id` — call it `$ORDERS_ID` below.

```
export ORDERS_ID=<the id you just read>
```

---

## 1. A question against one connected database produces a query using the right table

### 7. Confirm schema notes exist for this source

```
scripts/dev.sh psql -c "SELECT table_name, column_name, description FROM schema_notes WHERE source_id = '$ORDERS_ID';"
```

**You should see:** rows describing the `orders` table and its columns, including
`status` — this is what "schema notes are included and visibly influence the query" (the
ticket's own acceptance criterion) needs in order to be checked in the next step.

### 8. Generate a candidate query from an English question

```
podman compose exec worker python3 -c "
import asyncio
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory
from askwell.inference.client import InferenceClient
from askwell.agent.sql_generate import generate_candidate_query

async def main():
    settings = Settings()
    engine = build_engine(settings)
    client = InferenceClient(settings)
    async with session_factory(engine)() as session:
        result = await generate_candidate_query(
            session, settings, client, question='how many orders shipped late?'
        )
        print(result.reason)
        if result.query is not None:
            print(result.query.query)
            print(result.query.engine, result.query.prompt_version)
            print('schema notes used:', len(result.query.schema_note_ids))
    await engine.dispose()

asyncio.run(main())
"
```

**You should see:** `GenerationReason.GENERATED`, a single `SELECT` statement referencing the
`orders` table (and its `status` or `shipped_at` columns, not an invented name), `postgresql`,
`sql_generation.v1`, and a nonzero schema-note count. Read the query text itself: it should
use the actual column name(s) from Step 7's notes, e.g. filtering `status = 'late'` — the
ticket's own "schema notes ... visibly influence the query" criterion, checked by reading, not
by a passing test.

### 9. Confirm the generated query was recorded, whether or not it runs

```
scripts/dev.sh psql -c "SELECT payload FROM audit_decisions WHERE kind = 'sql_generated' ORDER BY occurred_at DESC LIMIT 1;"
```

**You should see:** a payload containing the same query text from Step 8, the source id, the
engine, and `prompt_version = "sql_generation.v1"` — the ticket's own Audit requirement,
independent of whether anything downstream ever executes it (nothing does, yet).

---

## 2. A question that is not about data at all is not forced into SQL

### 10. Ask something with no bearing on the schema

```
podman compose exec worker python3 -c "
import asyncio
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory
from askwell.inference.client import InferenceClient
from askwell.agent.sql_generate import generate_candidate_query

async def main():
    settings = Settings()
    engine = build_engine(settings)
    client = InferenceClient(settings)
    async with session_factory(engine)() as session:
        result = await generate_candidate_query(
            session, settings, client, question='what is the capital of France?'
        )
        print(result.reason, result.query)
    await engine.dispose()

asyncio.run(main())
"
```

**You should see:** `GenerationReason.NOT_A_DATABASE_QUESTION` and `None` — no schema note
matched the question at all, so nothing was sent to the model and nothing was recorded. Confirm
nothing new landed in the audit log:

```
scripts/dev.sh psql -c "SELECT count(*) FROM audit_decisions WHERE kind = 'sql_generated';"
```

**You should see:** the same count as after Step 9 — unchanged.

---

## 3. Several databases connected: the right one is chosen, or you are asked

### 11. Import the second dump

Repeat Step 4 in the browser with `~/askwell-test/dumps/inventory.sql`, answer its schema
clarifications (Step 5), then read back its id:

```
scripts/dev.sh psql -c "SELECT id, name, status FROM sources WHERE name = 'inventory.sql';"
export INVENTORY_ID=<the id you just read>
```

### 12. Ask a question that is clearly about one of the two

```
podman compose exec worker python3 -c "
import asyncio
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory
from askwell.inference.client import InferenceClient
from askwell.agent.sql_generate import generate_candidate_query

async def main():
    settings = Settings()
    engine = build_engine(settings)
    client = InferenceClient(settings)
    async with session_factory(engine)() as session:
        result = await generate_candidate_query(
            session, settings, client, question='how many orders shipped late?'
        )
        print(result.reason)
        print(result.query.source_id if result.query else None, '$ORDERS_ID')
    await engine.dispose()

asyncio.run(main())
"
```

**You should see:** `GenerationReason.GENERATED` and the printed `source_id` matching
`$ORDERS_ID` — chosen automatically, no ambiguity, because only the orders schema's notes
matched.

### 13. Ask a question ambiguous between the two

If both dumps happen to describe similarly-worded tables, this step demonstrates the
ambiguous branch directly; otherwise call `select_database_source` with a deliberately generic
question to see the same code path the ambiguous case uses:

```
podman compose exec worker python3 -c "
import asyncio
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory
from askwell.agent.sql_generate import select_database_source

async def main():
    settings = Settings()
    engine = build_engine(settings)
    async with session_factory(engine)() as session:
        selection = await select_database_source(session, settings, question='id')
        print(selection.reason)
        print([str(c.id) for c in selection.candidates])
    await engine.dispose()

asyncio.run(main())
"
```

**You should see:** if both sources' notes match a generic word like `id`,
`SelectionReason.AMBIGUOUS` and both source ids listed as candidates — "where the choice is
ambiguous, the user is asked rather than guessed at" (the ticket's own acceptance criterion),
verified here at the selection layer since no UI surface renders the disambiguation question
yet. If only one source matches even this generic term, you will instead see `SELECTED` — that
is also correct behaviour, just not the ambiguous branch; `test_two_databases_both_relevant_asks_which_one`
in the automated suite is the authoritative proof of the ambiguous branch with schema notes
engineered to guarantee the overlap.

---

## 4. No connections configured

### 14. Confirm a database question with nothing connected says so, not a generic abstention

```
podman compose down -v
podman compose up -d
scripts/dev.sh db upgrade head
podman compose exec worker python3 -c "
import asyncio
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory
from askwell.inference.client import InferenceClient
from askwell.agent.sql_generate import generate_candidate_query

async def main():
    settings = Settings()
    engine = build_engine(settings)
    client = InferenceClient(settings)
    async with session_factory(engine)() as session:
        result = await generate_candidate_query(
            session, settings, client, question='how many orders shipped late?'
        )
        print(result.reason, result.query)
    await engine.dispose()

asyncio.run(main())
"
```

**You should see:** `GenerationReason.NO_DATABASES` and `None` — this is the reason value a
caller renders `docs/states-and-edge-cases.md` §4's "no connections configured" state from
(per the module's own `GenerationResult` docstring); there is no UI wired to render it yet
(see "Where this stops on purpose").

---

## 5. Clean up

### 15. Remove the throwaway dumps

```
rm -rf ~/askwell-test/dumps
```

Deleting the `orders.sql` and `inventory.sql` sources through the library (or leaving them) is
a normal use of the product; nothing here needs manual database cleanup beyond the files above.

---

## Known gaps

Not defects — deliberately not built by this ticket, or not built at all yet:

- **No UI or API route reaches `generate_candidate_query`.** Asking a database question in the
  browser's ask screen never produces or shows a candidate SQL query today — it always answers
  from document retrieval, or abstains. `docs/ux/ask.md` §3's "Generated SQL, always shown for
  a database answer" and "Expand SQL" states have nothing to render yet. Wiring this in is
  blocked on `M4-SQL-VAL-104` through `-106` existing first, per C2 and the module's own
  docstring.
- **The disambiguation question itself has no surface.** Step 13 above proves
  `select_database_source` returns `AMBIGUOUS` with named candidates; there is no chat prompt
  asking "which database did you mean?" for the user to answer by clicking, because there is no
  ask-a-database-question flow at all yet.
- **Cross-database questions are refused implicitly, not explained.** A question spanning two
  databases produces, at best, `AMBIGUOUS` or a query against one source with no note telling
  the user that joining across sources is unsupported in v1 — the module docstring states this
  is a deliberate simplification (asking is "the one response correct for both edge cases at
  once"), but the *wording* a user would see once this is wired up does not exist yet.
- **Live-connection engines (MySQL, MariaDB, SQL Server) are untested here.** No such server
  runs in this stack; `test_a_connection_sources_engine_is_read_from_its_own_encrypted_config`
  is the only proof of that path today.
- **The local counter for generation events is not observable by hand.** `SQL_GENERATED` is
  recorded to `audit_decisions` (Step 9) but the ticket's "Local counter only" analytics line
  has no separate Redis key the way `M4-SQL-DB-107`'s timeout counter does — `grep` for a
  counter increment in `sql_generate.py` finds none, only the audit record.
