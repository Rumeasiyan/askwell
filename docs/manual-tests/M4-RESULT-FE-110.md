# Manual test — M4-RESULT-FE-110, SQL disclosure, collapsed by default, always available

**Ticket:** `M4-RESULT-FE-110` — every database-answered turn carries its generated query,
collapsed by default, expandable with the injected `LIMIT` marked, present as much on a
rejection or a timeout as on a successful result, and copyable.
**Version under test:** `0.4.25` (check `cat VERSION`).
**Time:** about 35 minutes, plus a first stack build.
**Who can run it:** a browser, a terminal, `podman compose exec` access to the `worker`
container.

**What is being checked.** `web/lib/sql-result.ts` (`segmentInjectedLimit`,
`recordSqlDisclosureExpanded`, `SqlQueryDisclosure`), `web/components/ask/sql-result-table.tsx`
(`QueryDisclosure` — now exported, shared by both `SqlResultTable` and the new `SqlQueryCard`),
`api/src/askwell/ask.py` (`_sql_query_disclosure`, `_sql_query_from_trace`, the `sql_query` field
on the `done` event), and the wiring in `web/components/ask/ask-state.tsx` (`AskTurn.sqlQuery`)
and `web/components/ask/ask-screen.tsx` (`AnsweredContent`, line ~1324).
`web/lib/sql-result.test.ts` is the authoritative automated proof for `segmentInjectedLimit`'s
splitting logic; this document checks the same logic actually rendering in a browser, and checks
the parts that logic-level test cannot: the highlighted `<mark>`, the copy button's clipboard
behaviour, and the `sql_query` wire field surviving a reopen.

**Where this stops on purpose — read before reporting anything below as a defect.**

- **No local model runs in this environment**, the same standing limitation
  `docs/manual-tests/M4-SQL-BE-108a.md` and `docs/manual-tests/M4-RESULT-FE-109.md` already
  recorded. Asking a real question and clicking **Send** never reaches a live `_run_sql_turn`
  outcome: `generate_candidate_query` needs the model, that call fails with no model loaded, and
  the turn falls through to document retrieval and then to a generic failure. There is no
  click-only path in this environment that produces a rejection, a dry-run failure, a timeout, or
  an executed result the way a real question would.
- **This document substitutes a direct database write for the missing model-driven turn**,
  exactly the substitution `M4-RESULT-FE-109` made: inserting a `messages` row with a `trace`
  payload already shaped the way `_run_sql_turn`'s own branches write it — `{"kind": "sql",
  "outcome": ..., "query": ...}` — for the four outcomes this ticket's own scope names
  (rejection, dry-run failure, timeout, source vanished) plus one executed result carrying an
  injected limit. What is then genuinely exercised end-to-end is everything downstream of that row
  existing: `GET /ask/{message_id}/stream` reading it back and reconstructing `sql_query`
  (`_sql_query_from_trace`), and `QueryDisclosure`'s rendering once a turn carries either
  `sqlResult` or `sqlQuery`.
- **`SqlQueryCard` itself — the card wrapping `QueryDisclosure` for a rejected/timed-out/failed
  turn — has no click-only or URL-only path to see rendered in this environment.** It only ever
  mounts from `turn.sqlQuery` on a *live* turn inside `AskProvider` (`ask-screen.tsx`'s
  `AnsweredContent`), which requires a turn that actually streamed through the provider — the same
  gap `M4-RESULT-FE-109` named for `SqlResultTable`'s own inline placement, and for the same
  reason `web/components/documents/database-result-view.tsx` (the source viewer) only ever reads
  `sql_result`, never `sql_query` — there is no "open this refusal in the source viewer" surface,
  by design, since `SqlQueryCard` carries no such link. Section 1 below visually verifies
  `QueryDisclosure` itself (the shared control both `SqlResultTable` and `SqlQueryCard` render) by
  reaching it through an executed result opened in the source viewer, exactly as `M4-RESULT-FE-109`
  did; Section 2 verifies the `sql_query` wire field the card would consume, by curling the stream
  endpoint directly; Section 3 confirms the mounting code by inspection. Nothing about
  `QueryDisclosure`'s own rendering differs between the two callers — `SqlQueryCard` passes it
  nothing `SqlResultTable` does not already pass it.

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

### 4. Add a placeholder source so the library has an entry

Click **Add a source**, choose a document upload, and add any small file you have to hand (a
one-page PDF or text file is enough). Wait for it to finish ingesting. **You should see:** the
source appear in the library as ready. The scenarios below attach a database result to a
*separate* source record created directly in the database — this step only confirms the shell
and library navigate correctly before that.

---

## 1. `QueryDisclosure` itself — expand, the injected limit marked, copy — opened through an executed result

### 5. Register a sandbox-backed source

```
podman compose exec worker python3 -c "
import asyncio, uuid
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory
from sqlalchemy import text

async def main():
    settings = Settings()
    engine = build_engine(settings)
    async with session_factory(engine)() as session:
        source_id = uuid.uuid4()
        await session.execute(text(
            \"INSERT INTO sources (id, kind, name, sandbox_db, status) \"
            \"VALUES (:id, 'dump', 'invoices', 'placeholder', 'ready')\"
        ), {'id': source_id})
        await session.commit()
        with open('/tmp/disclosure-manual-source.txt', 'w') as f:
            f.write(str(source_id))
        print('source:', source_id)
    await engine.dispose()

asyncio.run(main())
"
```

**You should see:** `source: <uuid>`, no error.

### 6. Write an executed result whose query carries a visibly injected `LIMIT`

The literal string below is exactly the shape `askwell.sql.limit.inject_limit` renders — a
`LIMIT` clause followed by the trailing SQL comment `INJECTED_LIMIT_COMMENT` names
(`/* Added by Askwell */`) — which is what `segmentInjectedLimit` (`web/lib/sql-result.ts`)
matches to decide what to highlight.

```
podman compose exec worker python3 -c "
import asyncio, json, uuid
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory
from sqlalchemy import text

async def main():
    settings = Settings()
    engine = build_engine(settings)
    with open('/tmp/disclosure-manual-source.txt') as f:
        source_id = f.read().strip()

    sql_result = {
        'engine': 'postgresql', 'source_id': source_id,
        'query': (
            'SELECT id, customer, amount, due_date\n'
            'FROM invoices\n'
            \"WHERE status = 'unpaid'\n\"
            'ORDER BY due_date\n'
            'LIMIT 1000 /* Added by Askwell */'
        ),
        'columns': ['id', 'customer', 'amount', 'due_date'],
        'rows': [[1, 'Kestrel Ltd', 480.0, '2026-09-30']],
        'row_count': 1, 'truncated': False, 'duration_ms': 11,
    }

    async with session_factory(engine)() as session:
        message_id = uuid.uuid4()
        conversation_id = uuid.uuid4()
        await session.execute(text(\"INSERT INTO conversations (id) VALUES (:id)\"), {'id': conversation_id})
        await session.execute(text(
            \"INSERT INTO messages (id, conversation_id, role, content, trace, summary, source_count, sql_result) \"
            \"VALUES (:id, :cid, 'assistant', 'Found 1 row.', CAST(:trace AS jsonb), 'Answered from your database.', NULL, CAST(:sql_result AS jsonb))\"
        ), {
            'id': message_id, 'cid': conversation_id,
            'trace': json.dumps({'status': 'completed', 'steps': []}),
            'sql_result': json.dumps(sql_result),
        })
        await session.commit()
        print('message:', message_id)
    await engine.dispose()

asyncio.run(main())
"
```

**You should see:** `message: <uuid>`, no error. Keep this id — the next step opens it.

### 7. Open the result and confirm the query is collapsed by default

```
http://127.0.0.1:8000/documents/?result=<message-id-from-step-6>
```

**You should see:**

- A page headed **Database result**, a one-row table, and a **Show query** control below it.
- No SQL text visible yet — the disclosure is collapsed by default, the ticket's own headline
  requirement.

### 8. Expand it and confirm the injected limit is marked

Click **Show query**. **You should see:**

- The label change to **Hide query**.
- The full query text, across five lines, inside a scrollable box with its own border — not
  reflowed into the page's own width.
- The `LIMIT 1000 /* Added by Askwell */` clause rendered with a distinct highlighted background
  (a filled `<mark>`), visibly different from the plain-text `SELECT`/`FROM`/`WHERE`/`ORDER BY`
  lines around it — the ticket's own "the injected limit visible where one was added."
- A **Copy query** button beneath the text, not present while collapsed.

### 9. Copy the query and confirm it is exactly what ran

Click **Copy query**. **You should see:** the button's label change to **Copied**, then revert
to **Copy query** after a couple of seconds. Paste the clipboard contents into a text editor.
**You should see:** the five-line query from step 6 exactly, `LIMIT 1000 /* Added by Askwell */`
included — confirming what a user would paste into their own database client is the literal
query that ran, comment and all.

### 10. Collapse it again

Click **Hide query**. **You should see:** the query text, the highlighted limit, and the copy
button all disappear, leaving only the **Show query** control — collapse round-trips cleanly.

---

## 2. Disclosure on a rejection, a dry-run failure, a timeout, and a vanished source — verified on the wire

Since no click-only path reaches these outcomes (see "Where this stops on purpose"), this section
writes each one's `trace` directly — the same shape `_run_sql_turn`'s own branches write — and
reads it back through the real `GET /ask/{message_id}/stream` endpoint, the same endpoint a
browser reconnecting to a finished turn calls.

### 11. Get a session cookie

```
curl -s -c /tmp/cookies.txt -o /dev/null -H "accept: text/html" http://127.0.0.1:8000/
```

### 12. Write four messages, one per outcome this ticket's scope names

```
podman compose exec worker python3 -c "
import asyncio, json, uuid
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory
from sqlalchemy import text

async def main():
    settings = Settings()
    engine = build_engine(settings)

    scenarios = {
        'rejected': {
            'content': 'Askwell could not safely run the query it generated for your database: not a single SELECT.',
            'trace': {'status': 'completed', 'steps': [
                {'kind': 'sql', 'outcome': 'rejected', 'reason': 'not_a_select', 'query': 'DELETE FROM invoices WHERE status = \'unpaid\''},
            ]},
        },
        'dry_run_failed': {
            'content': 'Askwell could not run this query against your database: column \"custmer\" does not exist.',
            'trace': {'status': 'completed', 'steps': [
                {'kind': 'sql', 'outcome': 'dry_run_failed', 'reason': 'plan_rejected', 'query': 'SELECT custmer FROM invoices LIMIT 1000 /* Added by Askwell */'},
            ]},
        },
        'timeout': {
            'content': 'This query took too long against your database and was stopped.',
            'trace': {'status': 'completed', 'steps': [
                {'kind': 'sql', 'outcome': 'timeout', 'query': 'SELECT * FROM invoices i JOIN invoices j ON true LIMIT 1000 /* Added by Askwell */'},
            ]},
        },
        'source_gone': {
            'content': 'The database this question would have used is no longer connected.',
            'trace': {'status': 'completed', 'steps': [
                {'kind': 'sql', 'outcome': 'source_gone', 'query': 'SELECT id FROM invoices LIMIT 1000 /* Added by Askwell */'},
            ]},
        },
    }

    async with session_factory(engine)() as session:
        conversation_id = uuid.uuid4()
        message_ids = {}
        await session.execute(text(\"INSERT INTO conversations (id) VALUES (:id)\"), {'id': conversation_id})
        for key, scenario in scenarios.items():
            message_id = uuid.uuid4()
            await session.execute(text(
                \"INSERT INTO messages (id, conversation_id, role, content, trace) \"
                \"VALUES (:id, :cid, 'assistant', :content, CAST(:trace AS jsonb))\"
            ), {
                'id': message_id, 'cid': conversation_id,
                'content': scenario['content'],
                'trace': json.dumps(scenario['trace']),
            })
            message_ids[key] = str(message_id)
        await session.commit()
        with open('/tmp/disclosure-manual-messages.json', 'w') as f:
            json.dump(message_ids, f)
        print(json.dumps(message_ids, indent=2))
    await engine.dispose()

asyncio.run(main())
"
```

**You should see:** a JSON object with four keys — `rejected`, `dry_run_failed`, `timeout`,
`source_gone` — each a message UUID, no error.

### 13. Read each one back through the real stream endpoint

```
podman compose exec -T worker cat /tmp/disclosure-manual-messages.json
```

For each id printed above:

```
curl -s -b /tmp/cookies.txt "http://127.0.0.1:8000/ask/<message-id>/stream"
```

**You should see, for every one of the four:**

- A `token` event carrying the scenario's own `content` text as `"text"` — the refusal or timeout
  message a person reads.
- A terminal `done` event whose `sql_result` is `null` — confirming C2's "never executed" contract
  held even for disclosure purposes.
- The same `done` event's `sql_query` carrying `{"query": "...", "outcome": "..."}` matching
  exactly what was written in step 12 for that scenario — `_sql_query_from_trace` reconstructing
  it from `messages.trace`, not from a second stored column.
- For `dry_run_failed`, `timeout`, and `source_gone` specifically: the `query` field in `sql_query`
  contains the literal text `LIMIT 1000 /* Added by Askwell */` — the same marker Section 1 proved
  renders highlighted, confirming a query that never executed still discloses its injected limit
  exactly like one that did. `rejected`'s own query has no injected limit, since rejection happens
  before limit injection runs (`_run_sql_turn`'s own ordering) — its `sql_query.query` is the bare
  `DELETE` statement `sqlglot` refused.

### 14. Confirm a bad message id still fails honestly on this same endpoint

```
curl -s -b /tmp/cookies.txt \
  http://127.0.0.1:8000/ask/00000000-0000-0000-0000-000000000000/stream
```

**You should see:** an error response (not a `sql_query`-shaped payload, not a crash) — the same
"no such stored answer" behaviour `M4-RESULT-FE-109` verified for `sql_result`.

---

## 3. Inline mounting — `SqlQueryCard` on a live turn — checked by code, not by clicking

### 15. Confirm the wiring by reading the files that connect `sql_query` to the card

```
grep -n "sqlQuery" web/components/ask/ask-state.tsx web/components/ask/ask-screen.tsx
```

**You should see:** `ask-state.tsx` carrying `sqlQuery: SqlQueryDisclosure | null` on `AskTurn`,
set from `event.data.sql_query` on the `done` event (mutually exclusive with `sqlResult`, per its
own comment); and `ask-screen.tsx`'s `AnsweredContent` rendering
`<SqlQueryCard disclosure={turn.sqlQuery} />` whenever `turn.sqlQuery !== null`, immediately after
the `SqlResultTable` branch and the answer prose — so a rejection's plain-language explanation
(rendered by `AnswerProse`, above both) always sits directly above its own disclosed query.

### 16. Confirm `_sql_query_disclosure`'s one deliberate exception by reading it

```
grep -n "_sql_query_disclosure" -A 15 api/src/askwell/ask.py | head -20
```

**You should see:** the function returns `None` when `trace_step.get("query")` is `None` — the
`ambiguous` outcome (several candidate databases, no single query to show) is the one branch this
covers; every other outcome this ticket names always carries a `query` key.

### 17. Run the automated unit suite for the pure logic underneath

```
scripts/dev.sh web-run node --test --experimental-strip-types lib/sql-result.test.ts
```

**You should see:** all tests pass, including the new `segmentInjectedLimit` cases — splitting a
query around the injected clause, and leaving a query with no injected limit as one unmarked
segment.

### 18. Run the backend unit suite for the reconstruction logic

```
scripts/dev.sh test -k "sql_query or load_finished"
```

**You should see:** `test_sql_query_disclosure_is_none_without_a_query`,
`test_sql_query_disclosure_pairs_the_query_with_its_outcome`,
`test_sql_query_from_trace_finds_the_sql_step_among_others`,
`test_sql_query_from_trace_is_none_for_a_document_turns_trace`, and
`test_load_finished_reconstructs_a_rejected_querys_disclosure` all pass.

---

## 4. Clean up

```
podman compose down -v
```

**You should see:** no error.

---

## Known gaps

Not defects — deliberately not built by this ticket, or not demonstrable in this environment:

- **No local model runs in this environment.** No question typed into the Ask composer can reach
  a real rejection, dry-run failure, timeout, or executed result here — every scenario above was
  written directly into `messages.trace`/`messages.sql_result`, the same substitution
  `M4-SQL-BE-108a` and `M4-RESULT-FE-109` made for the same reason.
- **`SqlQueryCard` mounted inline inside a live, just-streamed answer is confirmed by code
  inspection (step 15) and the API-level wire check (Section 2), not by clicking through a real
  refusal or timeout** — there is no click-only path in this environment that produces one, and no
  URL opens it directly either, since (by design) it carries no link into the source viewer. The
  control it renders (`QueryDisclosure`) is proven end-to-end visually in Section 1, using the
  identical component both callers share.
- **Editing and re-running a query is out of scope** (the ticket's own Out of Scope line) —
  nothing above should be reported as missing for lacking it.
- **Several queries disclosed separately in one turn (multi-step, M5)** — not exercised; this
  ticket's own scope is one disclosure per outcome, and M5 has not landed.
- **Only PostgreSQL-shaped queries were exercised.** `segmentInjectedLimit` and `QueryDisclosure`
  only ever see plain query text and a trailing comment — engine-agnostic — so this is a low-risk
  gap, not an untested code path, but no SQL Server or MySQL/MariaDB query was actually pushed
  through this document.
