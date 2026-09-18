# Manual test — M4-SCHEMA-ING-101, schema notes from the clarification loop

**Ticket:** `M4-SCHEMA-ING-101` — an unguessable column (`st_cd`-shaped: any token three characters
or fewer outside a small common-word allowlist) raises a clarification with its value distribution
and row count as evidence. Answering writes a `schema_notes` row that outranks the inferred,
type-only note at the same position, and that row is retrieved — with the rest of the schema —
the next time a question touches it. A user-supplied note is never overwritten by a later
inference, and one whose table or column position disappears from a re-introspection is flagged
`stale` rather than silently kept or silently dropped.
**Version under test:** `0.4.13`
**Time:** about 40 minutes, plus a first stack build.
**Who can run it:** a browser, a terminal, `podman compose exec` access to the `sandbox`
container, browser devtools (Network tab) for one step.

**What is being checked.** `api/src/askwell/schema_introspect.py` —
`_is_unguessable_column_name`, `raise_unguessable_column_clarifications`,
`_sample_postgresql_column_distribution`, and `write_schema_inventory`'s stale-flagging branch —
wired into the same three call sites `M4-SCHEMA-ING-100` already wired `write_schema_inventory`
into (a live connection's initial introspection, a dump import, and on-demand re-introspection).
The answer path is `api/src/askwell/review.py:answer_clarification` →
`api/src/askwell/reapply.py:resolve_dependencies`/`_promote_schema_note`, unchanged by this
ticket. Retrieval and citation are `askwell.memory.retrieve_relevant_facts`,
`askwell.agent.conflict._delimit_schema_notes`, and `askwell.ask._cite_claim`.
`api/tests/test_schema_introspect.py` is the authoritative automated proof, including the ranking
and cap edge cases with fabricated data; this document walks the same behaviour from a cold
stack, through the browser, with a real sandbox database.

**Where this stops on purpose — read before reporting anything below as a defect.**

- **There is no natural-language-to-SQL path yet.** `M4-SQL-BE-103` and `M4-SQL-VAL-104`–`106`
  (the sqlglot-validated query generator, C2) do not exist — `CHANGELOG.md`'s own `0.4.12` entry
  says so directly: `M4-SQL-DB-107`'s execution layer is built "once `M4-SQL-BE-103`/`VAL-104`–`106`
  exist to produce one". The ticket's own cold-start walkthrough ("ask a question that depends on
  knowing what the codes mean... confirm the query visibly uses the right values") cannot be run
  literally — there is no generated query to look at. What this document exercises instead is the
  half that does exist end to end: the clarification raised from real column data, the note it
  writes, and that note being retrieved and cited the next time a question touches the same
  column — which is the acceptance criterion's own wording, "query generation retrieves the note
  with the schema", minus a query generator to hand it to. **Issue needed** once `M4-SQL-BE-103`
  lands: re-run this scenario end to end with a generated query and confirm it uses the answer's
  values, not just that the note was retrieved.
- **The `stale` flag has no visible treatment in the UI.** `grep -rn "stale" web/` finds it nowhere
  in `web/components/` or `web/lib/` — `agent/conflict.py`'s caveat only ever reaches the model's
  own prompt, and `ask.py`'s `fact_citation` SSE event carries `"stale": true` (`ask.py:445`) with
  nothing in `web/` reading that field. A person cannot see a note is stale by looking at the
  citation chip; §4 below reads it from the raw SSE stream in devtools instead, and from
  `schema_notes` directly. **Issue needed** — a visible caveat on the schema-note detail popover
  (`web/components/ask/ask-screen.tsx:1660`) when `stale` is true.
- **No schema/table/column viewer exists** — the same standing gap `M4-SCHEMA-ING-100`'s manual
  test named. Steps that need to see `schema_notes` directly read it with `scripts/dev.sh psql`.
- **MySQL and SQL Server never raise a column clarification** — `sample=None` for both engines
  (module docstring, `schema_introspect.py`), a named gap (issue #362), not tested here: no MySQL
  or SQL Server instance runs in this stack.

None of the above is a defect in `M4-SCHEMA-ING-101` — its scope is the trigger and the retrieval
path, not a query generator or a stale badge. Sections below say which is which.

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
`SANDBOX_READONLY_PASSWORD` — you will use it below.

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
created and started, migration finishing with no error — including `1e6f3b9c4a72_schema_note_stale`.

### 3. Stand up a database with one unguessable column, one clear one, and two tables of very
different size

```
podman compose exec sandbox psql -U "$(grep ^SANDBOX_POSTGRES_USER .env | cut -d= -f2)" -d postgres <<'SQL'
CREATE DATABASE schema_notes_test OWNER askwell_sandbox_owner;
SQL
podman compose exec sandbox psql -U askwell_sandbox_owner -d schema_notes_test <<'SQL'
CREATE TABLE customers (id integer primary key, name text not null, email text not null);
CREATE TABLE orders (
  id integer primary key,
  customer_id integer references customers(id),
  st_cd text,
  total numeric
);
CREATE TABLE returns (
  id integer primary key,
  order_id integer references orders(id),
  rma_cd text
);
INSERT INTO customers SELECT g, 'Customer ' || g, 'c' || g || '@example.test' FROM generate_series(1, 5) g;
INSERT INTO orders
  SELECT g, ((g - 1) % 5) + 1,
    CASE WHEN g % 10 = 0 THEN 'C' WHEN g % 3 = 0 THEN 'P' ELSE 'O' END,
    (g * 9.5)::numeric(10,2)
  FROM generate_series(1, 240) g;
INSERT INTO returns SELECT g, g, 'RQ' FROM generate_series(1, 6) g;
GRANT CONNECT ON DATABASE schema_notes_test TO askwell_sandbox_readonly;
GRANT USAGE ON SCHEMA public TO askwell_sandbox_readonly;
GRANT SELECT ON customers, orders, returns TO askwell_sandbox_readonly;
SQL
```

**You should see:** `CREATE DATABASE`, `CREATE TABLE` ×3, `INSERT 0 5`, `INSERT 0 240`,
`INSERT 0 6`, then three `GRANT`s. `orders.st_cd` and `returns.rma_cd` are both unguessable by
name; `orders` has 240 rows and `returns` has 6 — the ticket's own "forty thousand rows outranks
twelve" edge case, at a scale a manual pass can insert in one statement. `customers.name` and
`customers.email` are ordinary words; `orders.total` is a plain word; every `id`/`customer_id`/
`order_id` column is a primary or foreign key, skipped regardless of name.

### 4. Open Askwell and confirm nothing is alarmed

Open a browser at `http://127.0.0.1:8000`. **You should see:** the shell load with no alarm
banner — `database`, `sandbox`, `queue`, `egress_proxy` and `inference` all reachable.

---

## 1. Connecting raises a clarification for each unguessable column, ranked by row count

### 5. Connect to the throwaway database, by clicking

Click **Library** in the rail, then **Add a source**, then click into the **Connect a database**
card. Engine `PostgreSQL`, Host `sandbox`, Port `5432`, Database `schema_notes_test`, User
`askwell_sandbox_readonly`, Password the value of `SANDBOX_READONLY_PASSWORD` from `.env`. Click
**Connect**.

**You should see:** the form replaced by a **Connected** block, then — within a few seconds — a
**Ready** block reading "`schema_notes_test on sandbox` is listed in the library."

### 6. Notice the clarifications prompt

**You should see:** shortly after the Ready block, the banner named in
`web/components/shell/clarifications-prompt.tsx` appear, reading something like "2 questions came
up while adding sources", with a **Review** action. (If you miss the banner's window, the rail's
**Clarifications** entry carries the same count as a badge — click that instead.)

### 7. Open Clarifications and read both questions

Click **Review** (or **Clarifications** in the rail). **You should see:** a group for
`schema_notes_test on sandbox` containing exactly two pending questions, in this order:

1. **`orders.st_cd` — what does this column mean?**, with an evidence line reading close to `240
   rows. Values: O (168) · P (56) · C (16)` — a plain-language reading of the `CASE` statement
   above (`% 3 = 0` is roughly a third, `% 10 = 0` a tenth, the rest fall to `O`; exact counts may
   differ by a few from integer rounding, the shape will not).
2. **`returns.rma_cd` — what does this column mean?**, with an evidence line reading `6 rows.
   Values: RQ (6)`.

`orders.st_cd` (240 rows) appears **before** `returns.rma_cd` (6 rows) — this is the ticket's own
ranking edge case ("a column across forty thousand rows outranking one across twelve") made
visible in which order the questions are presented, not just in a database column nobody looks
at.

### 8. Confirm the clear-named columns and the customers table raised nothing

Scroll the group. **You should see:** no question naming `customers`, `customers.name`,
`customers.email`, or `orders.total` — the ticket's own "a column with a clear name — no
question" edge case, for three different clear names at once (a table name, two ordinary
columns, and a unit-suffixed number).

### 9. Confirm the same, and the ranking, from the source of truth

```
scripts/dev.sh psql
```

```sql
SELECT subject, question, rank, evidence->>'row_count' AS row_count
FROM clarifications
WHERE source_id = (SELECT id FROM sources WHERE name = 'schema_notes_test on sandbox')
ORDER BY rank;
```

**You should see:** exactly two rows, `st_cd` at `rank` 1 with `row_count` 240, `rma_cd` at
`rank` 2 with `row_count` 6.

```sql
SELECT payload FROM audit_decisions
WHERE kind = 'schema_column_clarification_raised' ORDER BY created_at;
```

**You should see:** two payloads, `table_name: orders, column_name: st_cd, row_count: 240, rank: 1`
first, `table_name: returns, column_name: rma_cd, row_count: 6, rank: 2` second — the "Audit /
Logging Requirements: answers are decisions records" line, satisfied for the raise itself as well
as the eventual answer (§2 below covers the answer).

---

## 2. Answering writes a schema note that outranks the inferred one

### 10. Ask about `st_cd` before answering, and note the poor answer

Click **Ask** in the rail. In the box (`placeholder="Ask about your own files and databases"`),
type:

```
What does the st_cd column mean on the orders table in schema_notes_test?
```

Press Enter. **You should see:** an answer that is vague or hedged — at best repeating what the
inferred note already says (`orders.st_cd — text.`, the bare type `write_schema_inventory` wrote
at connect time), never what the codes actually mean, because nothing has told Askwell that yet.
If a citation chip labelled **Schema note** appears under the answer, click it — the popover
reads the same bare-type description. This is the ticket's own "ask a question... and note the
poor answer" step, run against the retrieval path that exists rather than a SQL query that does
not (see "Where this stops on purpose" above).

### 11. Go back and answer the clarification

Click **Clarifications** in the rail, find `orders.st_cd`, and type into its answer field:

```
O = open, P = paid, C = cancelled.
```

Click **Save**. **You should see:** the item leave the list with a brief "Saved" confirmation and
an Undo window, and the group's remaining count drop to 1 (`returns.rma_cd` only).

### 12. Confirm the note was written, and outranks the inferred one

```
scripts/dev.sh psql
```

```sql
SELECT table_name, column_name, description, origin, confidence, stale
FROM schema_notes
WHERE source_id = (SELECT id FROM sources WHERE name = 'schema_notes_test on sandbox')
  AND table_name = 'orders' AND column_name = 'st_cd' AND superseded_by IS NULL;
```

**You should see:** exactly one active row, `origin = user`, `confidence = 1.0`, `description`
reading `O = open, P = paid, C = cancelled.` — the answer text verbatim, `stale = false`. The
previous inferred row (`orders.st_cd — text.`) is no longer active — check with
`superseded_by IS NOT NULL` if you want to see it directly:

```sql
SELECT description, superseded_by IS NOT NULL AS superseded
FROM schema_notes
WHERE source_id = (SELECT id FROM sources WHERE name = 'schema_notes_test on sandbox')
  AND table_name = 'orders' AND column_name = 'st_cd';
```

**You should see:** two rows — the old inferred one with `superseded = true`, the new user one
with `superseded = false`.

### 13. Ask the same question again and confirm the answer is now correct

Back in **Ask**, ask the identical question from step 10 again:

```
What does the st_cd column mean on the orders table in schema_notes_test?
```

**You should see:** an answer that states the actual mapping — open/paid/cancelled, in
substance — with a **Schema note** citation chip. Click the chip. **You should see:** the
popover reading "Schema note" with the fact text `O = open, P = paid, C = cancelled.` — the
user-supplied note, retrieved with the rest of the schema (`askwell.memory.retrieve_relevant_facts`)
and cited the same way a document passage is (`askwell.ask._cite_claim`, `notes_start` branch).
This is the ticket's own "ask the same question again and confirm the answer is now correct" —
the retrieval-and-citation half of the acceptance criterion, run end to end.

---

## 3. A user note is never overwritten by a later inference

### 14. Re-introspect and confirm the user's answer survives untouched

Get a session cookie and re-introspect:

```
SOURCE_ID=$(scripts/dev.sh psql -tAc \
  "SELECT id FROM sources WHERE name = 'schema_notes_test on sandbox'")
curl -s -c /tmp/askwell-cookies -H "Accept: text/html" http://127.0.0.1:8000/ -o /dev/null
curl -s -b /tmp/askwell-cookies -X POST \
  "http://127.0.0.1:8000/sources/${SOURCE_ID}/reintrospect" | python3 -m json.tool
```

**You should see:** `{"source_id": "<the same id>", "queued": true}`. Wait a few seconds, then:

```
scripts/dev.sh psql -c \
  "SELECT description, origin FROM schema_notes WHERE source_id = '${SOURCE_ID}' \
   AND table_name = 'orders' AND column_name = 'st_cd' AND superseded_by IS NULL"
```

**You should see:** the same row as step 12 — `origin = user`, description unchanged. The
column's type has not changed, so this re-introspection would have written an identical inferred
description anyway; the point is that it is never even compared against a `user`-origin row
(`write_schema_inventory`'s own `if existing.origin != "inferred": ... continue`,
`schema_introspect.py`) — the ticket's own "User notes are never overwritten by inferences",
confirmed by the code path that enforces it, not just by the outcome looking right this once.

### 15. Confirm a second unanswered clarification did **not** trigger a re-raise

```
scripts/dev.sh psql -c \
  "SELECT count(*) FROM clarifications WHERE source_id = '${SOURCE_ID}'"
```

**You should see:** `2` still — re-introspection did not add a third `st_cd` question (already
answered, its clarification stays `answered`) or duplicate `rma_cd`'s still-pending one
(`raise_unguessable_column_clarifications`'s own idempotency guard: a source that already has any
clarification row is not re-scanned).

---

## 4. A note for a column that disappears is flagged stale, not silently kept or dropped

### 16. Rename the column the user just explained

```
podman compose exec sandbox psql -U askwell_sandbox_owner -d schema_notes_test -c \
  "ALTER TABLE orders RENAME COLUMN st_cd TO status_code;"
```

**You should see:** `ALTER TABLE`.

### 17. Re-introspect and confirm the old note is flagged, not deleted

```
curl -s -b /tmp/askwell-cookies -X POST \
  "http://127.0.0.1:8000/sources/${SOURCE_ID}/reintrospect" | python3 -m json.tool
```

Wait a few seconds, then:

```
scripts/dev.sh psql -c \
  "SELECT table_name, column_name, description, origin, stale, superseded_by IS NULL AS active \
   FROM schema_notes WHERE source_id = '${SOURCE_ID}' AND description LIKE '%open, P = paid%'"
```

**You should see:** exactly one row — `table_name = orders`, `column_name = st_cd` (the position
Askwell asked about and the user answered; renaming the column does not rewrite that position),
`origin = user`, `stale = true`, `active = true` (`superseded_by` is still `NULL`). This is the
ticket's own edge case verbatim: "a note for a column that later disappears — flagged as stale
rather than silently applied." It is still active and still retrieved (§18 below) — a rename is
not a deletion, and nothing here erases what the user said.

```
scripts/dev.sh psql -c \
  "SELECT payload FROM audit_decisions WHERE kind = 'schema_note_marked_stale' \
   ORDER BY created_at DESC LIMIT 1"
```

**You should see:** a payload naming the `orders`/`st_cd` position and this note's id — the
"Audit / Logging Requirements: answers are decisions records" line, extended to this ticket's own
new record kind.

### 18. Confirm the caveat reaches the composed answer, in the raw response stream

The UI itself does not surface `stale` (see "Where this stops on purpose"), so read it from the
network response directly. Open browser devtools → Network, ask once more in the **Ask** screen:

```
What does the st_cd column mean on the orders table in schema_notes_test?
```

Find the `POST /ask` (or `/ask/...`) request in the Network panel, open its response/EventStream
view. **You should see:** a `fact_citation` event whose data includes `"fact_kind": "schema_note"`,
`"subject": "orders.st_cd"`, and `"stale": true` (`ask.py:445`) — the flag this ticket's migration
added, carried all the way from `schema_notes.stale` through `get_active_schema_notes` and
`retrieve_relevant_facts` (both read the new column — `memory.py`'s two diffed `SELECT`s) into
the citation the browser received. The answer text itself should still state the open/paid/
cancelled mapping — a stale note is a caveat, not a reason to abstain; `_delimit_schema_notes`
(`agent/conflict.py:126`) writes `, column no longer found in the current schema` into the
prompt precisely so the model can say the mapping while noting the column was renamed, rather
than either silently presenting it as current or refusing to answer at all.

### 19. Confirm the position reappearing clears the flag

```
podman compose exec sandbox psql -U askwell_sandbox_owner -d schema_notes_test -c \
  "ALTER TABLE orders RENAME COLUMN status_code TO st_cd;"
curl -s -b /tmp/askwell-cookies -X POST \
  "http://127.0.0.1:8000/sources/${SOURCE_ID}/reintrospect" | python3 -m json.tool
```

Wait a few seconds, then:

```
scripts/dev.sh psql -c \
  "SELECT stale FROM schema_notes WHERE source_id = '${SOURCE_ID}' \
   AND table_name = 'orders' AND column_name = 'st_cd' AND superseded_by IS NULL"
```

**You should see:** `stale = false` again — the ticket's own "a renamed-then-renamed-back column
... has its stale flag cleared again" (`schema_introspect.py`'s `write_schema_inventory`
docstring), observed rather than taken on faith.

---

## 5. Clean up

### 20. Drop the throwaway database

```
podman compose exec sandbox psql -U "$(grep ^SANDBOX_POSTGRES_USER .env | cut -d= -f2)" -d postgres -c \
  "DROP DATABASE schema_notes_test;"
rm -f /tmp/askwell-cookies
```

**You should see:** `DROP DATABASE`. This is cleanup, not part of the acceptance criteria.

---

## Known gaps

Not defects — deliberately not built by this ticket, or not built at all yet:

- **No natural-language-to-SQL path exists** (`M4-SQL-BE-103`, `M4-SQL-VAL-104`–`106`). The
  ticket's own "the resulting query is correct where it previously was not" cannot be observed
  literally until that lands — §2 above demonstrates the note being written and retrieved and
  cited correctly, which is as far as the current stack can carry the scenario. **Issue needed**
  to re-run this document's §2 with a real generated query once the SQL generator exists.
- **`stale` has no visible UI treatment.** Confirmed only through `schema_notes` (psql) and the
  raw `fact_citation` SSE payload (devtools) in §4 — nothing in `web/components/ask/ask-screen.tsx`'s
  fact-detail popover (`FactPopover`, around line 1660) reads or displays the field. **Issue
  needed** — surface it as a caveat line in that popover, and arguably in the answer text's own
  citation marker.
- **MySQL and SQL Server never raise a column clarification.** `sample=None` for both — a named
  gap in the module's own docstring, tracked as issue #362, not exercised here (no MySQL or SQL
  Server instance runs in this stack).
- **Bulk patterns across similarly-named columns are asked individually** — named in the ticket's
  own Testing Notes as a known gap, not attempted here (this walkthrough uses one unguessable
  column per table, deliberately, to keep the ranking demonstration legible).
- **No schema/table/column viewer anywhere in `web/`** — the same standing gap
  `M4-SCHEMA-ING-100`'s manual test named; every inventory read in this document goes through
  `scripts/dev.sh psql` rather than a screen, because there is no screen.
