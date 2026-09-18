# Manual test — M4-SCHEMA-BE-102, stale annotations when the schema drifts

**Ticket:** `M4-SCHEMA-BE-102` — on re-introspection, a schema note whose table or column position
no longer exists is flagged `stale` (not deleted, since the object may return), carries *why*
(`'dropped'` vs `'possibly_invisible'` for a Postgres permission change) and, for a column, an
unambiguous reattach suggestion when exactly one column vanished from its table while exactly one
new one appeared. A stale note is excluded outright from generation. A source with any active
stale notes shows `attention` with a summarised reason. The fix path is edit, delete or reattach.
**Version under test:** `0.4.14`
**Time:** about 45 minutes, plus a first stack build.
**Who can run it:** a browser, a terminal, `podman compose exec` access to the `sandbox`
container, `scripts/dev.sh psql`.

**What is being checked.** `api/src/askwell/schema_introspect.py` —
`write_schema_inventory`'s stale-flagging branch (now carrying `stale_reason` and
`reattach_suggestion`) and the new `refresh_schema_attention` — plus `api/src/askwell/memory.py`'s
`retrieve_relevant_facts` (`AND NOT stale`, tightening `M4-SCHEMA-ING-101`'s in-prompt caveat to an
outright exclusion) and the three fix-path functions, `correct_schema_note`, `delete_schema_note`,
`reattach_schema_note`. `api/tests/test_schema_introspect.py` and `api/tests/test_memory.py` are
the authoritative automated proof, including the fabricated-rows edge cases for `stale_reason`/
`reattach_suggestion`; this document walks the same behaviour from a cold stack against a real
sandbox database.

**Where this stops on purpose — read before reporting anything below as a defect.**

- **This ticket has no reachable UI surface of its own, at all.** `M4-SCHEMA-BE-102` is labelled
  `backend`; the frontend work its own acceptance criteria describe ("surfaced in the library... a
  needs-attention reason", "expand it, and read which note is stale", "use the fix path to
  reattach it") was never built and no ticket for it exists in `docs/backlog/`. Confirmed by
  reading the code, not assumed: `web/lib/library.ts`'s `attentionCauses()` reads only
  `state.failures`/`state.flagged`, never `source.last_error` (where this ticket's own
  "Schema drifted: N schema notes..." sentence lives), so a source in `attention` purely because
  of stale notes shows the **Needs attention** badge with no **Show detail** button at all —
  `causes.length` is always `0` for that case. `web/lib/memory.ts`'s `MemoryRow` carries no
  `stale`/`stale_reason`/`reattach_suggestion` fields even though `GET /memory` already returns
  all three, so the memory screen shows a stale note exactly like an active one. And
  `POST /memory/facts/schema_note/{id}/reattach` and `POST /sources/{id}/reintrospect` have no
  caller anywhere in `web/`. Filed as **issue #366** rather than worked around. §1–§5 below reach
  the backend behaviour by clicking as far as the running app allows, then read the rest with
  `scripts/dev.sh psql` and one `curl` (re-introspect) exactly the way `M4-SCHEMA-ING-101`'s own
  manual test already did for the identical trigger.
- **Edit and Delete are reachable through the Memory screen; Reattach is not** (part of the same
  gap above). §5 below uses Edit and Delete by clicking, and reattach with `curl` against the real
  route, since there is no button.
- **No schema/table/column viewer exists anywhere in `web/`** — the same standing gap
  `M4-SCHEMA-ING-100` and `M4-SCHEMA-ING-101`'s own manual tests named. Every inventory read below
  goes through `scripts/dev.sh psql`.
- **MySQL and SQL Server are not exercised** — no instance of either runs in this stack (issue
  #353, pre-existing). `omitted_tables`/`possibly_invisible` is a PostgreSQL-only capability by the
  module's own docstring; on the other two engines every stale note is unconditionally `'dropped'`.

None of the above is a defect in `M4-SCHEMA-BE-102` itself — its scope is the detection, the
reason, the suggestion and the fix-path functions, not the screens that would display them.
Sections below say which is which.

---

## Before you start

```
cd ~/external/quantum-plus/askwell
```

If you have never run Askwell before:

```
cp -n .env.example .env
```

Open `.env` and confirm every `?set ... in .env` placeholder has a real value. Note the values of
`SANDBOX_POSTGRES_USER` and `SANDBOX_READONLY_PASSWORD` — you will use both below.

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
created and started, migration finishing with no error — including `3f7c1a9e5d20_schema_note_
stale_reason`, this ticket's own migration adding `stale_reason` and `reattach_suggestion`.

### 3. Stand up a throwaway database with three drift scenarios

```
podman compose exec sandbox psql -U "$(grep ^SANDBOX_POSTGRES_USER .env | cut -d= -f2)" -d postgres <<'SQL'
CREATE DATABASE drift_test OWNER askwell_sandbox_owner;
SQL
podman compose exec sandbox psql -U askwell_sandbox_owner -d drift_test <<'SQL'
CREATE TABLE orders (
  id integer primary key,
  status_col text
);
CREATE TABLE shipments (
  id integer primary key,
  order_id integer references orders(id),
  carrier_cd text
);
CREATE TABLE audit_log (
  id integer primary key,
  event text
);
INSERT INTO orders SELECT g, CASE WHEN g % 2 = 0 THEN 'paid' ELSE 'open' END FROM generate_series(1, 20) g;
INSERT INTO shipments SELECT g, g, 'UPS' FROM generate_series(1, 20) g;
INSERT INTO audit_log SELECT g, 'created' FROM generate_series(1, 5) g;
GRANT CONNECT ON DATABASE drift_test TO askwell_sandbox_readonly;
GRANT USAGE ON SCHEMA public TO askwell_sandbox_readonly;
GRANT SELECT ON orders, shipments, audit_log TO askwell_sandbox_readonly;
SQL
```

**You should see:** `CREATE DATABASE`, `CREATE TABLE` ×3, three `INSERT`s, then three `GRANT`s.
`orders.status_col` will be **dropped entirely** below (the "dropped" case), `shipments.carrier_cd`
will be **renamed** (the "reattach suggestion" case), and `audit_log`'s `SELECT` grant will be
**revoked** (the "possibly invisible" case) — three different drift shapes in one pass, plus a
fourth scenario (all three at once) to check the library's needs-attention reason is a summary,
not three sentences.

### 4. Open Askwell and confirm nothing is alarmed

Open a browser at `http://127.0.0.1:8000`. **You should see:** the shell load with no alarm
banner — `database`, `sandbox`, `queue`, `egress_proxy` and `inference` all reachable.

---

## 1. Connect, and turn each inferred note into a user-supplied one

### 5. Connect to the throwaway database, by clicking

Click **Library** in the rail, then **Add a source**, then click into the **Connect a database**
card (the same wizard `M4-CONN-FE-096` built — ignore the empty-library screen's own "arriving
later" note next to "Connect a database"; that copy is stale, a pre-existing drift unrelated to
this ticket, not re-checked here). Engine `PostgreSQL`, Host `sandbox`, Port `5432`, Database
`drift_test`, User `askwell_sandbox_readonly`, Password the value of `SANDBOX_READONLY_PASSWORD`
from `.env`. Click **Connect**.

**You should see:** the form replaced by a **Connected** block, then — within a few seconds — a
**Ready** block reading "`drift_test on sandbox` is listed in the library."

### 6. Turn the three columns' inferred notes into user-supplied ones

Click **Memory** in the rail. Filter to this source (the **Source** dropdown, `drift_test on
sandbox`). **You should see:** rows including `orders.status_col`, `shipments.carrier_cd` and
`audit_log.event`, each labelled **I guessed** — the bare-type description
`write_schema_inventory` wrote at connect time.

For each of the three, click **Edit**, replace the text, and click **Save**:

- `orders.status_col` → `Order status: open or paid.`
- `shipments.carrier_cd` → `Shipping carrier, always UPS today.`
- `audit_log.event` → `What happened, one word per row.`

**You should see:** after each save, the row's label change from **I guessed** to **You told
me** — `correct_fact`'s "an inferred row has nothing to correct... so the chip's Correct is really
assert this instead" promoting each to a real `origin = 'user'` row, the same effect answering a
clarification would have had, reached the faster way since the columns' names are not themselves
unguessable (`status_col`, `carrier_cd` and `event` are all longer than three characters or plain
English, so none of them would have raised a clarification in the first place).

### 7. Confirm all three are active, user-origin, and not stale yet

```
scripts/dev.sh psql
```

```sql
SELECT table_name, column_name, origin, stale, stale_reason, reattach_suggestion
FROM schema_notes
WHERE source_id = (SELECT id FROM sources WHERE name = 'drift_test on sandbox')
  AND column_name IN ('status_col', 'carrier_cd', 'event')
  AND superseded_by IS NULL
ORDER BY table_name;
```

**You should see:** exactly three rows, all `origin = user`, all `stale = false`,
`stale_reason`/`reattach_suggestion` both `NULL`.

---

## 2. A dropped column is flagged stale with reason `dropped`, and excluded from generation

### 8. Ask a question that relies on the note, and note the correct answer

Click **Ask** in the rail. Type:

```
What does status_col mean on the orders table in drift_test?
```

Press Enter. **You should see:** an answer stating the open/paid mapping, with a citation chip
reading **Schema note** — the user-supplied note from step 6, retrieved and cited normally.

### 9. Drop the column entirely

```
podman compose exec sandbox psql -U askwell_sandbox_owner -d drift_test -c \
  "ALTER TABLE orders DROP COLUMN status_col;"
```

**You should see:** `ALTER TABLE`.

### 10. Re-introspect

There is no button for this (see "Where this stops on purpose" above).

```
SOURCE_ID=$(scripts/dev.sh psql -tAc \
  "SELECT id FROM sources WHERE name = 'drift_test on sandbox'")
curl -s -c /tmp/askwell-cookies -H "Accept: text/html" http://127.0.0.1:8000/ -o /dev/null
curl -s -b /tmp/askwell-cookies -X POST \
  "http://127.0.0.1:8000/sources/${SOURCE_ID}/reintrospect" | python3 -m json.tool
```

**You should see:** `{"source_id": "<the same id>", "queued": true}`. Wait a few seconds for the
worker to pick it up.

### 11. Confirm the note is flagged, not deleted, with reason `dropped`

```
scripts/dev.sh psql -c \
  "SELECT table_name, column_name, origin, stale, stale_reason, reattach_suggestion, \
   superseded_by IS NULL AS active \
   FROM schema_notes WHERE source_id = '${SOURCE_ID}' AND column_name = 'status_col'"
```

**You should see:** exactly one row — `origin = user`, `stale = true`, `stale_reason = dropped`,
`reattach_suggestion` is `NULL` (nothing new appeared in `orders` to suggest), `active = true`
(`superseded_by` still `NULL`) — the ticket's own "stale notes are not silently deleted."

### 12. Confirm it is excluded outright from generation, not merely caveated

Ask the identical question again:

```
What does status_col mean on the orders table in drift_test?
```

**You should see:** Askwell no longer answers from the stale note — either it abstains for that
part of the question, or it answers from whatever else it can (the bare column no longer exists to
describe at all, so there is nothing left to say about it), but it never repeats the "open or
paid" mapping with a **Schema note** citation the way step 8 did. This is the tightened behaviour
this ticket adds over `M4-SCHEMA-ING-101`: that ticket kept a stale note in the prompt with an
in-line caveat (`agent/conflict.py`'s `_delimit_schema_notes`); this ticket's own Validation Rule
— "a stale note is never used in generation" — removes it from `retrieve_relevant_facts`
(`memory.py`'s `AND NOT stale`) instead, so there is no caveat to read correctly in the first
place. Confirm from the source of truth:

```
scripts/dev.sh psql -c \
  "SELECT payload FROM audit_decisions \
   WHERE kind = 'schema_note_marked_stale' ORDER BY created_at DESC LIMIT 1"
```

**You should see:** a payload naming `table_name: orders, column_name: status_col,
stale_reason: dropped` and this note's id — the ticket's own "staleness detection is logged."

---

## 3. A renamed column gets an unambiguous reattach suggestion

### 13. Rename the shipments column

```
podman compose exec sandbox psql -U askwell_sandbox_owner -d drift_test -c \
  "ALTER TABLE shipments RENAME COLUMN carrier_cd TO carrier_code;"
```

**You should see:** `ALTER TABLE`.

### 14. Re-introspect again

```
curl -s -b /tmp/askwell-cookies -X POST \
  "http://127.0.0.1:8000/sources/${SOURCE_ID}/reintrospect" | python3 -m json.tool
```

Wait a few seconds.

### 15. Confirm the old note is stale with a reattach suggestion naming the new column

```
scripts/dev.sh psql -c \
  "SELECT column_name, stale, stale_reason, reattach_suggestion \
   FROM schema_notes WHERE source_id = '${SOURCE_ID}' \
   AND description = 'Shipping carrier, always UPS today.'"
```

**You should see:** `column_name = carrier_cd` (the position the user's answer is still attached
to — a rename does not rewrite it), `stale = true`, `stale_reason = dropped` (the table itself is
fully visible; only the column moved), `reattach_suggestion = carrier_code` — the ticket's own
edge case verbatim: "a column renamed rather than removed — a suggestion to reattach where a close
match exists." This is the *one* unambiguous case per the ticket's own Assumption: exactly one
column vanished from `shipments` (`carrier_cd`) while exactly one new one appeared
(`carrier_code`) in the same re-introspection pass.

---

## 4. A permission change is reported as possibly invisible, not gone

### 16. Revoke the readonly role's access to `audit_log`

```
podman compose exec sandbox psql -U askwell_sandbox_owner -d drift_test -c \
  "REVOKE SELECT ON audit_log FROM askwell_sandbox_readonly;"
```

**You should see:** `REVOKE`.

### 17. Re-introspect once more

```
curl -s -b /tmp/askwell-cookies -X POST \
  "http://127.0.0.1:8000/sources/${SOURCE_ID}/reintrospect" | python3 -m json.tool
```

Wait a few seconds.

### 18. Confirm the table's own note is stale with reason `possibly_invisible`

```
scripts/dev.sh psql -c \
  "SELECT table_name, column_name, stale, stale_reason \
   FROM schema_notes WHERE source_id = '${SOURCE_ID}' AND table_name = 'audit_log'"
```

**You should see:** two rows — the table-level note (`column_name IS NULL`) and the
`audit_log.event` column note both `stale = true`, both `stale_reason = possibly_invisible` — the
ticket's own edge case verbatim: "a table temporarily invisible because of a permission change —
reported as possibly invisible rather than definitely gone." This is only possible because
PostgreSQL's `pg_catalog.pg_class` still lists `audit_log` for a role that can no longer `SELECT`
it (`schema_introspect.py`'s own module docstring); the table genuinely still exists, unlike
`orders.status_col` above.

---

## 5. Many notes going stale at once are summarised, and the fix path works

### 19. Confirm the source now shows `attention` with a summarised reason naming the count

```
scripts/dev.sh psql -c \
  "SELECT status, last_error FROM sources WHERE id = '${SOURCE_ID}'"
```

**You should see:** `status = attention`, `last_error` reading exactly `Schema drifted: 4 schema
notes refer to a table or column Askwell can no longer find.` — one sentence naming the count of
active stale *notes*, not stale *tables*: `orders.status_col`, `shipments.carrier_cd`, and two for
`audit_log` (its table-level note and its `event` column note both went stale in the same
re-introspection). Confirm the count directly:

```
scripts/dev.sh psql -c \
  "SELECT count(*) FROM schema_notes WHERE source_id = '${SOURCE_ID}' \
   AND stale AND superseded_by IS NULL"
```

**You should see:** `4`, matching `last_error` exactly. The ticket's own edge case: "many notes
going stale at once — summarised in one needs-attention reason with a count," confirmed rather
than assumed.

```
scripts/dev.sh psql -c \
  "SELECT payload FROM audit_decisions WHERE kind = 'schema_source_attention_changed' \
   ORDER BY created_at"
```

**You should see:** at least one row with `status: attention` and a `stale_count` matching the
number above.

### 20. See the gap directly: the library shows the badge, with nothing to expand

Click **Library** in the rail. Find `drift_test on sandbox`. **You should see:** the status badge
reads **Needs attention** — but there is **no "Show detail" button** anywhere on the row, unlike
a source with a failed document (which does show one). This is the issue #366 gap named at the
top of this document, seen directly rather than only read about: the row's own attention cause
(a stale schema note) has no code path into `attentionCauses()`, so the row has nothing to expand
even though the ticket's own acceptance criterion is "surfaced in the library... expand it, and
read which note is stale."

### 21. Fix path, part one: edit a stale note by clicking (Memory screen)

Click **Memory** in the rail, filtered to `drift_test on sandbox` as in step 6. **You should see:**
the `orders.status_col` row still present and still labelled **You told me** — a stale note is
"still active, still retrieved" for a person to see, per this ticket's own module docstring, even
though step 12 confirmed it is no longer fed to generation. Nothing on the row shows it is stale
(the other half of issue #366). Click **Edit**, change the text to
`Order status, before the column was dropped — kept for history.`, click **Save**.

```
scripts/dev.sh psql -c \
  "SELECT stale, stale_reason FROM schema_notes WHERE source_id = '${SOURCE_ID}' \
   AND column_name = 'status_col' AND superseded_by IS NULL"
```

**You should see:** `stale = false`, `stale_reason = NULL` — editing supersedes the stale row with
a brand-new active one (`correct_schema_note`'s own `INSERT ... origin = 'user'`), and a freshly
inserted `schema_notes` row is never stale by default. Editing genuinely clears the flag, even
though nothing about the dropped column itself changed.

### 22. Fix path, part two: delete a stale note by clicking (Memory screen)

Filter still on `drift_test on sandbox`. Find `audit_log.event` (still labelled **You told me**,
still stale per step 18). Click **Delete**, confirm. **You should see:** the row disappear from
the list.

```
scripts/dev.sh psql -c \
  "SELECT count(*) FROM schema_notes WHERE source_id = '${SOURCE_ID}' \
   AND table_name = 'audit_log' AND column_name = 'event'"
```

**You should see:** `0` — deleted outright (`delete_schema_note`'s own `DELETE FROM schema_notes`),
unlike editing, which supersedes rather than removes.

### 23. Fix path, part three: reattach the renamed column's note

No button exists for this (see "Where this stops on purpose"). Find the note id and call the
route directly, using the suggestion step 15 already confirmed:

```
NOTE_ID=$(scripts/dev.sh psql -tAc \
  "SELECT id FROM schema_notes WHERE source_id = '${SOURCE_ID}' \
   AND description = 'Shipping carrier, always UPS today.' AND superseded_by IS NULL")
curl -s -b /tmp/askwell-cookies -X POST \
  "http://127.0.0.1:8000/memory/facts/schema_note/${NOTE_ID}/reattach" \
  -H "Content-Type: application/json" \
  -d '{"table_name": "shipments", "column_name": "carrier_code"}' | python3 -m json.tool
```

**You should see:** a JSON body with a new `fact_id` different from `NOTE_ID`.

```
scripts/dev.sh psql -c \
  "SELECT column_name, stale, origin FROM schema_notes \
   WHERE source_id = '${SOURCE_ID}' AND description = 'Shipping carrier, always UPS today.' \
   AND superseded_by IS NULL"
```

**You should see:** `column_name = carrier_code` — moved to the renamed position —
`stale = false`, `origin = user`. Reload **Ask** and confirm queries use it again:

```
What is the shipping carrier for shipment 1 in drift_test?
```

**You should see:** an answer naming UPS with a **Schema note** citation — the ticket's own
"confirm queries use it again," the reattach's `_reprocess_subject` call having nothing to
re-embed here (a schema note is not chunked text) but the note itself being active and retrievable
at its new, correct position again, exactly as step 8 demonstrated for the position before it went
stale.

---

## 6. Clean up

### 24. Drop the throwaway database

```
podman compose exec sandbox psql -U "$(grep ^SANDBOX_POSTGRES_USER .env | cut -d= -f2)" -d postgres -c \
  "DROP DATABASE drift_test;"
rm -f /tmp/askwell-cookies
```

**You should see:** `DROP DATABASE`. This is cleanup, not part of the acceptance criteria.

---

## Known gaps

Not defects in `M4-SCHEMA-BE-102` — deliberately not built by this ticket, filed rather than
guessed at:

- **No UI surface exists for anything this ticket built** (issue #366, filed while writing this
  document): the library never shows *why* a source needs attention when the cause is a stale
  schema note (`attentionCauses()` ignores `source.last_error`), the memory screen shows no stale
  badge or reason for a schema note despite `GET /memory` already returning one, there is no
  reattach button anywhere in `web/`, and there is no re-introspect button anywhere in `web/` —
  the last of these pre-dates this ticket (`M4-SCHEMA-ING-100`) but is exercised here for the
  first time by every re-introspection this document runs, all via `curl`.
- **MySQL and SQL Server never distinguish `possibly_invisible` from `dropped`** — both engines'
  `SchemaInventory.omitted_tables` is always `None` (no privilege-independent catalog either
  engine's own restricted role can read), so every stale note on those two engines is
  unconditionally `stale_reason = 'dropped'`, a real, named gap in the module's own docstring, not
  tested here — no MySQL or SQL Server instance runs in this stack (issue #353, pre-existing).
- **No automatic rename detection beyond exact one-for-one column matching** — the ticket's own
  named Out of Scope and Known gap. Two columns renamed in the same table in one pass, or a rename
  alongside an unrelated new column, produces no suggestion at all (`_reattach_suggestion` requires
  exactly one removed and exactly one added) rather than a best guess — not exercised here since
  step 13 already demonstrates the one case the function does handle, and a second scenario adding
  a false-suggestion check would duplicate what `test_schema_introspect.py`'s own fabricated-rows
  tests already cover directly.
