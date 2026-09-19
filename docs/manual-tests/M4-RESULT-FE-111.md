# Manual test — M4-RESULT-FE-111, database states: no connections, unreachable, zero rows, timeout, rejected

**Ticket:** `M4-RESULT-FE-111` — five distinct database question-answering states, each with its
own message and next action: no connections configured, connection unreachable, zero rows,
statement timeout, and SQL validation rejection. Plus three named edge cases: a database-shaped
question a document actually answers falls back to it; a relevant source still importing says so
rather than "unreachable"; several connections with one down names which one.
**Version under test:** `0.4.26` (check `cat VERSION`).
**Time:** about 45 minutes, plus a first stack build.
**Who can run it:** a browser, a terminal, `podman compose exec` access to the `worker` container.
**Human review required:** every piece of user-facing wording this ticket renders is collected
verbatim in **§0, Copy to review** below, for the reviewer this ticket names to check before merge.

**What is being checked.** `api/src/askwell/ask.py` (`_looks_database_shaped`,
`_no_database_answer`, `_non_ready_sql_sources`, the `db_state` field on the `done` event, and
`_run_sql_turn`'s own text for `unreachable`/`rejected`/`timeout`/zero rows), `api/src/askwell/sql_execute.py`
(`UNREACHABLE_MESSAGE`, `StatementTimedOut`), `web/lib/ask.ts` (`addSourceActionLabel`),
`web/components/ask/ask-screen.tsx` (`AbstentionState`, `AnsweredContent`), and
`web/components/settings/connections.tsx` (the database connections empty state,
`docs/states-and-edge-cases.md` §7).

**Where this stops on purpose — read before reporting anything below as a defect.**

- **No local model runs in this environment**, the same standing limitation
  `docs/manual-tests/M4-SQL-BE-108a.md`, `docs/manual-tests/M4-RESULT-FE-109.md` and
  `docs/manual-tests/M4-RESULT-FE-110.md` already recorded. Every one of this ticket's five states
  is decided only after retrieval — either a document match (the SQL-branch states) or an
  abstained document search (the "no connections" state and its two edge cases) — and retrieval
  itself calls the embedding model. With no model loaded, a real question asked through the
  composer never reaches any of the five states: it fails earlier, on `InferenceUnavailable`. There
  is no click-only path in this environment that produces a live, streamed `done` event carrying
  any of `no_connections`/`source_importing`/`source_attention`/`unreachable`/`timeout`/`rejected`.
- **This document substitutes direct calls into the real backend functions, and direct database
  writes, for the missing model-driven turn** — the same substitution the three documents above
  made for the same reason. Two kinds are used here:
  - `_no_database_answer` and `_looks_database_shaped` are called directly, inside the `worker`
    container, against the real database — this is the actual function `_run_generation` calls,
    not a reimplementation, so §2 and §3 genuinely exercise the backend logic end to end. Only the
    surrounding turn (retrieval, streaming) is skipped.
  - The SQL-branch states (`unreachable`, `timeout`, `rejected`, zero rows, §4) are verified by
    writing a `messages` row with `trace`/`sql_result` shaped exactly as `_run_sql_turn`'s own
    branches write it, then reading it back through the real `GET /ask/{message_id}/stream`
    endpoint — proving the wire format and the stored text, not a mock of either.
- **Inline rendering on a live, just-streamed turn** (`AbstentionState`'s **Connect a database**
  button, `AnsweredContent`'s `SqlQueryCard`) has no click-only path to reach in this environment
  either, for the same reason. §2–§5 verify the underlying data each renders from — the `done`
  event's `db_state` and message text — and confirm the rendering code by inspection, the approach
  `M4-RESULT-FE-110`'s own §3 already used.
- **§1 (the connections empty state) and §6 (adding a connection) are genuine click-through** —
  neither needs the model or a database question, only the Settings screen and the add-source
  form.

---

## 0. Copy to review

Every user-facing string this ticket renders, collected in one place for the reviewer to check
before merge (ticket's own "Human review: copy" line). Each is also verified in context further
down, cited by section.

| State | Exact text | Verified in |
| ----- | ---------- | ----------- |
| No connections configured | *"No database is connected. Connect one to answer questions like this from your own data, not just your documents."* | §3 |
| — its action | *"Connect a database"* | §3 |
| Source still importing | *"`<name>` is still importing. Try again once it finishes."* | §3 |
| Source needs attention | *"`<name>` needs attention and can't answer questions right now. Check its connection in the library."* | §3 |
| Several sources needing attention | *"`<name>`, `<name>` need attention and can't answer questions right now. Check its connection in the library."* | §3 |
| Connection unreachable | *"The database is unreachable. It may be down, or the network between here and it may be down. This is not the same as a query returning no rows — Askwell could not reach the database at all."* | §4 |
| Zero rows | *"No matching records."* | §4 |
| Statement timeout | *"This query took longer than `<n>`s and was stopped. Try narrowing it — a smaller date range or an added filter usually helps. The timeout is adjustable in settings (ASKWELL_SQL_STATEMENT_TIMEOUT_SECONDS) if this legitimately needs more time.\nQuery: `<sql>`"* | §4 |
| SQL rejected | *"Askwell could not safely run the query it generated for your database: `<detail>`."* | §4 |
| Connections empty state | *"None connected. Connecting a database lets Askwell answer questions straight from your own data — counts, totals, records — not just your documents. It only ever asks for read-only credentials, and refuses anything that can write. …"* | §1 |
| Connect-a-database form | *"PostgreSQL, MySQL, MariaDB or SQL Server. Connect with a read-only user — a write-capable credential is refused, naming the permission found."* | §6 |

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

### 2. Bring the stack up

```
podman compose up -d
scripts/dev.sh db upgrade head
```

**You should see:** `postgres`, `sandbox`, `redis`, `egress-proxy`, `api`, `worker` all reported
created and started, migration finishing with no error.

### 3. Open Askwell as a first-time user

Open a browser at `http://127.0.0.1:8000`. **You should see:** the shell load with no alarm
banner, and — since nothing has been added yet — the first-run empty state on the Ask screen
rather than a composer.

---

## 1. The database connections empty state (`docs/states-and-edge-cases.md` §7)

Genuine click-through — no model needed.

### 4. Navigate to Settings by clicking

In the left rail, click **Settings**. **You should see:** a page headed **Settings**, a **Folders**
section, and below it a section headed **Connected databases**.

### 5. Confirm the empty-state copy

Since nothing has been connected yet, **you should see** under **Connected databases**:

> None connected. Connecting a database lets Askwell answer questions straight from your own
> data — counts, totals, records — not just your documents. It only ever asks for read-only
> credentials, and refuses anything that can write.

Confirm both of the ticket's own required facts appear in that sentence: **what connecting
enables** ("answer questions straight from your own data") and **that credentials must be
read-only** ("only ever asks for read-only credentials, and refuses anything that can write").

---

## 2. `_looks_database_shaped` — the routing signal, checked directly

### 6. Confirm the narrow keyword match, against the real function

```
podman compose exec worker python3 -c "
from askwell.ask import _looks_database_shaped

cases = [
    ('Is my database connected?', True),
    ('Can you run a SQL query for me?', True),
    ('DATABASE status?', True),
    ('Show me the SQL.', True),
    (\"What is Meridian Loom's policy on sick leave?\", False),
    (\"What was Meridian Loom's total revenue in Q2?\", False),
    (\"What was Meridian Loom's headcount in the Support department?\", False),
]
for question, expected in cases:
    actual = _looks_database_shaped(question)
    mark = 'OK' if actual == expected else 'MISMATCH'
    print(f'{mark}: {question!r} -> {actual}')
"
```

**You should see:** every line prefixed `OK` — in particular, both near-miss business questions
("total revenue", "headcount") print `OK: ... -> False`. This is the reason a manual walkthrough
must ask something literally containing "database" or "sql" to reach §3 below — ordinary tabular
questions ("how many rows", "total sales") do **not** trigger the no-connections message, by
design (issue #400).

---

## 3. The "no connections configured" state and its two edge cases

Exercised via `_no_database_answer`, the exact function `_run_generation`'s document-abstention
branch calls, run directly against the real database.

### 7. Confirm "nothing connected at all"

```
podman compose exec worker python3 -c "
import asyncio
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory
from askwell.ask import _no_database_answer

async def main():
    settings = Settings()
    engine = build_engine(settings)
    async with session_factory(engine)() as session:
        answer = await _no_database_answer(session, settings, 'what does my database say about sales?')
        print(answer)
    await engine.dispose()

asyncio.run(main())
"
```

**You should see:** a tuple whose first element is exactly:

> No database is connected. Connect one to answer questions like this from your own data, not
> just your documents.

and whose second element is `{'kind': 'sql', 'outcome': 'no_connections'}`. That `outcome` value
is what `web/lib/ask.ts`'s `addSourceActionLabel` reads to render the **Connect a database**
button — confirm by inspection:

```
grep -n "no_connections" web/lib/ask.ts
```

**You should see:** `if (dbState === "no_connections") return "Connect a database";` — the one
case, of the three abstention-branch outcomes, that offers the connect action at all.

### 8. Confirm a question that is not database-shaped gets nothing back

```
podman compose exec worker python3 -c "
import asyncio
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory
from askwell.ask import _no_database_answer

async def main():
    settings = Settings()
    engine = build_engine(settings)
    async with session_factory(engine)() as session:
        answer = await _no_database_answer(session, settings, 'what is the sick leave policy?')
        print(answer)
    await engine.dispose()

asyncio.run(main())
"
```

**You should see:** `None` — an ordinary document question never gets database-routing copy
grafted onto its abstention, even with zero sources connected.

### 9. Register a source still importing, and confirm the distinct message

```
podman compose exec worker python3 -c "
import asyncio, uuid
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory
from askwell.ask import _no_database_answer
from sqlalchemy import text

async def main():
    settings = Settings()
    engine = build_engine(settings)
    async with session_factory(engine)() as session:
        await session.execute(text(
            \"INSERT INTO sources (id, kind, name, status) VALUES (:id, 'connection', 'Warehouse', 'indexing')\"
        ), {'id': uuid.uuid4()})
        await session.commit()
        answer = await _no_database_answer(session, settings, 'run a sql query for me')
        print(answer)
    await engine.dispose()

asyncio.run(main())
"
```

**You should see:** the message

> Warehouse is still importing. Try again once it finishes.

with `outcome: 'source_importing'` — distinct wording from both "no connections" and "needs
attention", and no add-source action (confirm: `addSourceActionLabel` returns `null` for
`source_importing` — `grep -n "source_importing" web/lib/ask.ts`).

### 10. Add a second source needing attention, and confirm it is named — the "one down" edge case

```
podman compose exec worker python3 -c "
import asyncio, uuid
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory
from askwell.ask import _no_database_answer
from sqlalchemy import text

async def main():
    settings = Settings()
    engine = build_engine(settings)
    async with session_factory(engine)() as session:
        await session.execute(text(
            \"INSERT INTO sources (id, kind, name, status, last_error) \"
            \"VALUES (:id, 'connection', 'Billing', 'attention', 'connection refused')\"
        ), {'id': uuid.uuid4()})
        await session.commit()
        answer = await _no_database_answer(session, settings, 'query my database please')
        print(answer)
    await engine.dispose()

asyncio.run(main())
"
```

**You should see:** now that both `Warehouse` (importing) and `Billing` (attention) exist, the
message names **Billing specifically**, not both and not generically:

> Billing needs attention and can't answer questions right now. Check its connection in the
> library.

This is the ticket's own "several connections where one is down — the message names which" edge
case: `attention` is checked and reported before `indexing`, so a mix of the two states resolves
to the one that actually blocks answering.

### 11. Connect a ready source, and confirm the override stops firing

```
podman compose exec worker python3 -c "
import asyncio, uuid
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory
from askwell.ask import _no_database_answer
from sqlalchemy import text

async def main():
    settings = Settings()
    engine = build_engine(settings)
    async with session_factory(engine)() as session:
        await session.execute(text(
            \"INSERT INTO sources (id, kind, name, status, sandbox_db) \"
            \"VALUES (:id, 'dump', 'Ledger', 'ready', 'placeholder')\"
        ), {'id': uuid.uuid4()})
        await session.commit()
        answer = await _no_database_answer(session, settings, 'does my database have anything about the weather?')
        print(answer)
    await engine.dispose()

asyncio.run(main())
"
```

**You should see:** `None` — a database is connected, so a question it does not happen to match
is a genuine "not about your data" case, never reported as a connection problem. This is the
ticket's own "database question that could be answered from documents falls back to them" spirit
applied to the sibling case: once something is actually connected, silence, not a false alarm.

### 12. Confirm the override reaches the browser on a live `done` event — through the real stream endpoint

```
podman compose exec worker python3 -c "
import asyncio, json, uuid
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory
from sqlalchemy import text

async def main():
    settings = Settings()
    engine = build_engine(settings)
    async with session_factory(engine)() as session:
        conversation_id = uuid.uuid4()
        message_id = uuid.uuid4()
        await session.execute(text(\"INSERT INTO conversations (id) VALUES (:id)\"), {'id': conversation_id})
        trace = {
            'status': 'completed',
            'steps': [{'kind': 'sql', 'outcome': 'no_connections'}],
        }
        content = (
            'No database is connected. Connect one to answer questions like this '
            'from your own data, not just your documents.'
        )
        await session.execute(text(
            \"INSERT INTO messages (id, conversation_id, role, content, trace) \"
            \"VALUES (:id, :cid, 'assistant', :content, CAST(:trace AS jsonb))\"
        ), {'id': message_id, 'cid': conversation_id, 'content': content, 'trace': json.dumps(trace)})
        await session.commit()
        print('message:', message_id)
    await engine.dispose()

asyncio.run(main())
"
```

Take the printed id, get a session cookie, and read it back:

```
curl -s -c /tmp/cookies.txt -o /dev/null -H "accept: text/html" http://127.0.0.1:8000/
curl -s -b /tmp/cookies.txt "http://127.0.0.1:8000/ask/<message-id-from-above>/stream"
```

**You should see:** a `token` event whose text is the no-connections message, and a terminal
`done` event whose `reason` is `null`. Read the endpoint's own replay code:

```
grep -n "async def replay" -A 24 api/src/askwell/ask.py
```

**You should see** the `replay()` generator (`GET /ask/{id}/stream`'s branch for a turn no longer
held in memory) sending the stored text as a `token` event and hard-coding `"reason": None` on its
`done` event — it never reads `db_state` back either, and `_FinishedTurn`'s own tuple
(`content, status, summary, source_count, conversation_id, sql_result, sql_query`) has no slot for
either field. **This is expected, not a defect this ticket introduces**: `_load_finished` and
`replay()` are `M1-ASK-API-038`'s code, unchanged by this ticket. But it has a real consequence for
every one of this ticket's three abstention-branch states (and for an ordinary document
abstention, equally): `isAbstained` (`web/lib/ask.ts`) requires `answer === "" && reason !== null`.
A *live* turn satisfies that — the document-abstention branch deliberately never streams a `token`
event for its composed text (`turn.text = reason`, not `turn.emit("token", ...)`, confirmed at
`api/src/askwell/ask.py` around line 1306 — "streamed as a token event is M2-ABSTAIN-FE-055's call
to make, not this ticket's"), so `answer` stays empty and `reason` carries the message. A *replayed*
turn does the opposite: `content` arrives as a `token` (so `answer` becomes the abstention text,
non-empty) and `reason` is hard-coded `null`. `isAbstained` therefore returns **`false`** on a
reopened conversation's abstained turn, including all three of this ticket's own states — it
renders through `AnsweredContent` as ordinary prose instead of through `AbstentionState`, losing
the muted secondary-line styling, the extra vertical rhythm, and — the detail this ticket actually
owns — the **Connect a database** / **Add a source** button entirely, since `AnsweredContent` never
renders one. **File this as a follow-up if it is not already tracked** — it is a real, pre-existing
gap in `M1-ASK-API-038`'s replay path (not something this ticket's own code caused or can fix
inside its own scope), but this ticket's "Connect a database" action is one of the things it costs
on every reopened conversation.

---

## 4. The SQL-branch states: unreachable, timeout, rejected, zero rows

These come from `_run_sql_turn` once a database connection actually exists and answers (or fails
to), never through the abstention branch above — `db_state` stays `None` on every one of them
(confirmed in §5). Written directly as `messages` rows, the same substitution
`M4-RESULT-FE-110`'s §2 made for the same four-outcome shape.

### 13. Write one message per state

```
podman compose exec worker python3 -c "
import asyncio, json, uuid
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory
from askwell.sql_execute import UNREACHABLE_MESSAGE
from sqlalchemy import text

async def main():
    settings = Settings()
    engine = build_engine(settings)

    timeout_text = (
        'This query took longer than 30s and was stopped. Try narrowing it — a smaller '
        'date range or an added filter usually helps. The timeout is adjustable in settings '
        '(ASKWELL_SQL_STATEMENT_TIMEOUT_SECONDS) if this legitimately needs more time.\n'
        'Query: SELECT * FROM invoices i JOIN invoices j ON true'
    )
    rejected_text = (
        'Askwell could not safely run the query it generated for your database: '
        'not a single SELECT.'
    )

    scenarios = {
        'unreachable': {
            'content': UNREACHABLE_MESSAGE,
            'trace': {'status': 'completed', 'steps': [
                {'kind': 'sql', 'outcome': 'ConnectionUnreachable', 'query': 'SELECT * FROM invoices'},
            ]},
            'sql_result': None,
        },
        'timeout': {
            'content': timeout_text,
            'trace': {'status': 'completed', 'steps': [
                {'kind': 'sql', 'outcome': 'timeout', 'query': 'SELECT * FROM invoices i JOIN invoices j ON true'},
            ]},
            'sql_result': None,
        },
        'rejected': {
            'content': rejected_text,
            'trace': {'status': 'completed', 'steps': [
                {'kind': 'sql', 'outcome': 'rejected', 'reason': 'not_a_select',
                 'query': \"DELETE FROM invoices WHERE status = 'unpaid'\"},
            ]},
            'sql_result': None,
        },
        'zero_rows': {
            'content': 'No matching records.',
            'trace': {'status': 'completed', 'steps': [
                {'kind': 'sql', 'outcome': 'executed', 'rows': 0, 'truncated': False,
                 'query': \"SELECT id FROM invoices WHERE status = 'overdue'\"},
            ]},
            'sql_result': {
                'engine': 'postgresql', 'source_id': str(uuid.uuid4()),
                'query': \"SELECT id FROM invoices WHERE status = 'overdue'\",
                'columns': ['id'], 'rows': [], 'row_count': 0,
                'truncated': False, 'duration_ms': 4,
            },
        },
    }

    async with session_factory(engine)() as session:
        conversation_id = uuid.uuid4()
        message_ids = {}
        await session.execute(text(\"INSERT INTO conversations (id) VALUES (:id)\"), {'id': conversation_id})
        for key, scenario in scenarios.items():
            message_id = uuid.uuid4()
            await session.execute(text(
                \"INSERT INTO messages (id, conversation_id, role, content, trace, sql_result) \"
                \"VALUES (:id, :cid, 'assistant', :content, CAST(:trace AS jsonb), CAST(:sql_result AS jsonb))\"
            ), {
                'id': message_id, 'cid': conversation_id,
                'content': scenario['content'],
                'trace': json.dumps(scenario['trace']),
                'sql_result': json.dumps(scenario['sql_result']) if scenario['sql_result'] is not None else None,
            })
            message_ids[key] = str(message_id)
        await session.commit()
        with open('/tmp/db-states-manual-messages.json', 'w') as f:
            json.dump(message_ids, f)
        print(json.dumps(message_ids, indent=2))
    await engine.dispose()

asyncio.run(main())
"
```

**You should see:** a JSON object with four keys — `unreachable`, `timeout`, `rejected`,
`zero_rows` — each a message UUID, no error.

### 14. Read each one back and confirm the four states share no wording

```
podman compose exec -T worker cat /tmp/db-states-manual-messages.json
```

For each id printed above:

```
curl -s -b /tmp/cookies.txt "http://127.0.0.1:8000/ask/<message-id>/stream"
```

**You should see, for every one of the four:** a `token` event whose text matches §0's table
exactly for that state, and a `done` event. Read all four side by side and confirm — the ticket's
own Validation Rule — that no two share so much as a sentence: `unreachable` names the database
itself as unreachable, `timeout` names the query as having taken too long and shows it,
`rejected` names the query as unsafe to run and shows it, `zero_rows` says only that nothing
matched. Each names a different next action: re-check the connection, narrow the query, nothing
(rejection is the model's fault, not the user's to fix by rephrasing), or trust the query ran
correctly and reconsider the question.

### 15. Open the zero-rows result in the source viewer and confirm the query is shown

```
http://127.0.0.1:8000/documents/?result=<message-id-for-zero_rows>
```

**You should see:** a page headed **Database result**, the muted text **No matching records.**
(distinct in both wording and color from an error), and a **Show query** control beneath it.
Click it. **You should see:** the exact query from step 13 —
`SELECT id FROM invoices WHERE status = 'overdue'` — confirming the ticket's own acceptance
criterion: "Zero rows shows the query so the analyst can see whether the question or the query was
wrong."

---

## 5. `db_state` stays `None` on every SQL-branch outcome — the code that guarantees it

### 16. Confirm by reading the comment and the code together

```
grep -n '"db_state": None' -B 6 api/src/askwell/ask.py
```

**You should see:** the comment "`M4-RESULT-FE-111`: always `None` here — the routing override
this field exists for only ever fires from the document turn's own abstention branch below, never
from a turn `_run_sql_turn` itself answered" directly above the literal `"db_state": None` on the
SQL-branch `done` event. This is what keeps `AbstentionState`'s **Connect a database** button from
ever appearing on an `unreachable`/`timeout`/`rejected`/zero-rows turn — those render through
`AnsweredContent` instead (confirm: `isAbstained` requires `answer === ""`, and every SQL-branch
text above is non-empty), which has no such button at all.

---

## 6. Connecting a database — genuine click-through, confirming the empty state's own promise

### 17. Navigate to add a source

From the Ask screen (click **Ask** in the rail if you followed §1 away from it), click
**Add a source** — or, from **Settings → Connected databases**, there is no direct link, so use
the rail: click **Library**, then **Add a source** from there.

**You should see:** the **Add a source** screen with three sections stacked: file upload, database
dump, and — the one this ticket's empty state promises — **Connect a database**, with the copy:

> PostgreSQL, MySQL, MariaDB or SQL Server. Connect with a read-only user — a write-capable
> credential is refused, naming the permission found.

This is the empty state's own promise from §5 ("credentials must be read-only") made concrete:
confirm the form has no field for anything except host, port, database name, user and password —
nothing that would let a write-capable role be entered as anything other than a plain credential
subject to the same refusal named here. Actually submitting a working connection needs a reachable
Postgres/MySQL/MariaDB/SQL Server instance, which is `M4-CONN-FE-096`'s and `M4-CONN-SEC-097`'s own
manual test territory, not this ticket's — stop here once the form and its copy are confirmed.

---

## 7. Run the automated suite for everything above

### 18. Backend

```
scripts/dev.sh test -k "no_database_answer or looks_database_shaped or database_shaped_question or share_a_message"
```

**You should see:** all matched tests pass, including
`test_no_two_of_the_five_states_share_a_message`,
`test_a_database_shaped_question_with_no_sources_at_all_reports_no_connection`, and
`test_a_database_shaped_question_that_documents_actually_cover_is_answered_from_them` — the last
one being the ticket's own "falls back to documents" edge case, exercised end to end with a fake
inference client, which is the one thing this document could not click through directly.

---

## 8. Clean up

```
podman compose down -v
```

**You should see:** no error.

---

## Known gaps

Not defects — deliberately not built by this ticket, or not demonstrable in this environment:

- **No local model runs in this environment.** No question typed into the Ask composer can reach
  any of the five states here — every one was reached either by calling the real backend function
  directly (`_no_database_answer`, `_looks_database_shaped`) or by writing a `messages` row
  shaped exactly as the real code writes it and reading it back through the real stream endpoint.
  The one edge case with no non-model verification path at all in this document — a
  database-shaped question that documents actually cover — is exercised instead by the automated
  suite (§7, step 18), which already tests it end to end with a fake embedding/generation client.
- **`AbstentionState`'s "Connect a database" button and `AnsweredContent`'s `SqlQueryCard` mounted
  inline on a live, just-streamed turn** are confirmed by code inspection (§3 step 7, §5 step 16),
  not by clicking through a real question — the same gap `M4-RESULT-FE-109` and `M4-RESULT-FE-110`
  named for their own inline placements, for the same reason.
- **A reopened conversation's abstained turn stops being recognised as abstained at all** (§3, step
  12) — `M1-ASK-API-038`'s replay path (`_load_finished`/`replay()`) streams the stored text as a
  `token` and hard-codes `reason: null`, so `isAbstained` (which needs `answer === "" && reason !==
  null`) returns `false` on replay. This affects every abstention, not only this ticket's three —
  it renders as ordinary prose (`AnsweredContent`) instead of `AbstentionState` on reopen, which
  for this ticket specifically means the **Connect a database** / **Add a source** button is
  missing entirely on a reopened no-connections/still-importing/needs-attention turn, not merely
  relabelled. A real, pre-existing gap this document surfaced rather than one this ticket's own
  code caused; flag as a follow-up against `M1-ASK-API-038`/`M2-ABSTAIN-FE-055` rather than treating
  it as this ticket's own defect.
- **Actually completing a working database connection** (§6) needs a reachable
  PostgreSQL/MySQL/MariaDB/SQL Server instance and is `M4-CONN-FE-096`'s/`M4-CONN-SEC-097`'s own
  manual test territory — this document confirms the form and its read-only-credentials copy only.
- **Voice, and every other surface `docs/states-and-edge-cases.md` covers**, are out of this
  ticket's scope and untouched here.
