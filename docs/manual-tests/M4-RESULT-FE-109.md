# Manual test — M4-RESULT-FE-109, render results with counts, pagination and the truncation label

**Ticket:** `M4-RESULT-FE-109` — a database-answered turn renders as a table with its row count,
paginates a large result, labels a truncated one, and reads distinctly as a single number, a
zero-row message, or a table depending on what actually came back. Clicking through opens the
database row of the source viewer, showing the same rows and the query.
**Version under test:** `0.4.24` (check `cat VERSION`).
**Time:** about 40 minutes, plus a first stack build.
**Who can run it:** a browser, a terminal, `podman compose exec` access to the `worker`
container.

**What is being checked.** `web/lib/sql-result.ts` (`isSingleValue`, `truncationLabel`,
`formatCell`, `columnAlign`, `paginateSqlRows`, `sqlResultHref`), `web/components/ask/sql-result-table.tsx`
(`SqlResultTable`, the four states), `web/components/documents/database-result-view.tsx` (the
source viewer's database row), and the wiring in `web/components/ask/ask-screen.tsx`
(`AnsweredContent`, line ~1321) and `web/components/ask/ask-state.tsx` (`AskTurn.sqlResult`,
carried from the `done` event's `sql_result` field, `web/lib/ask.ts`). `web/lib/sql-result.test.ts`
is the authoritative automated proof for the pure display logic (pagination clamping, null vs.
empty, column alignment, the truncation label's wording); this document checks the same logic
actually rendering in a browser, against real stored rows.

**Where this stops on purpose — read before reporting anything below as a defect.**

- **No local model runs in this environment**, the standing limitation `docs/manual-tests/M4-SQL-BE-108a.md`
  already recorded for this same reason. Asking a real question and clicking "Send" never reaches
  a `sql_result`: `generate_candidate_query` needs the model to turn the question into SQL, that
  call fails with no model loaded, and the turn falls through to document retrieval and then to a
  generic failure. There is no click-only path in this environment that produces a live, streamed
  `done` event carrying `sql_result` — the same gap M4-SQL-BE-108a named for itself.
- **This document substitutes a direct database write for the missing model-driven turn**, the
  same substitution M4-SQL-BE-108a made for `_run_sql_turn` — here, inserting a `messages` row
  with a `sql_result` payload already attached, exactly the shape `_run_generation`'s SQL-answered
  branch writes once a real query executes. What is then genuinely exercised end-to-end is
  everything downstream of that row existing: `GET /ask/{message_id}/stream` reading it back, and
  `DatabaseResultView` (`M1-VIEW-FE-046`'s source viewer) rendering it — the actual component this
  ticket built. What is **not** exercised is a turn's answer rendering `SqlResultTable` inline in
  the live conversation the moment it finishes (`AnsweredContent`, `ask-screen.tsx`), since that
  needs a turn that streamed through `AskProvider`'s own in-memory state, which nothing in this
  environment can produce without a model. That inline placement is checked by code inspection
  instead (Part 3) and is a known gap here, not a defect.
- **Opening a specific message's source-view URL directly, rather than by clicking a citation.**
  A provenance card ordinarily supplies this link (`sqlResultHref`, "View full result and query"),
  but nothing in this environment produces a live card to click for the reason above. This
  document opens the same URL a click on that card would produce, in the address bar, and says so
  at that step rather than pretending it was reached by clicking.

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
rather than a composer, matching `corpus === "none"` in `ask-screen.tsx`.

This confirms the ordinary cold start still works; the scenarios below need a source in the
library to click through to, so the next step adds one.

### 4. Add a placeholder source so the library has an entry to click into

Click **Add a source**, choose a document upload, and add any small file you have to hand (a
one-page PDF or text file is enough). Wait for it to finish ingesting.

**You should see:** the source appear in the library as ready. The scenarios below attach a
database result to a *separate* source record created directly in the database (a dump source,
as M4-SQL-BE-108a's own cold-start section built one) — this step only confirms the library and
the shell navigate correctly before that.

---

## 1. Four database result scenarios, written directly and opened in the browser

### 5. Register a sandbox-backed source, the same shape a real dump import leaves

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
            \"VALUES (:id, 'dump', 'shipments', 'placeholder', 'ready')\"
        ), {'id': source_id})
        await session.commit()
        with open('/tmp/result-manual-source.txt', 'w') as f:
            f.write(str(source_id))
        print('source:', source_id)
    await engine.dispose()

asyncio.run(main())
"
```

**You should see:** `source: <uuid>`, no error.

### 6. Write four completed messages, one per state this ticket owns

```
podman compose exec worker python3 -c "
import asyncio, json, uuid
from askwell.config import Settings
from askwell.db.engine import build_engine, session_factory
from sqlalchemy import text

async def main():
    settings = Settings()
    engine = build_engine(settings)
    with open('/tmp/result-manual-source.txt') as f:
        source_id = f.read().strip()

    scenarios = {}

    # A large, paginated result: 120 rows, wide enough for horizontal
    # scroll, with a null and an empty string both present so they render
    # distinguishably, and a numeric column so it right-aligns.
    wide_rows = []
    for i in range(1, 121):
        status = None if i % 17 == 0 else ('' if i % 23 == 0 else ('late' if i % 3 == 0 else 'on_time'))
        wide_rows.append([i, status, f'SHIP-{i:04d}', f'2026-0{(i % 9) + 1}-0{(i % 8) + 1}', 'Warehouse ' + str(i % 5), i * 1.5])
    scenarios['paginated'] = {
        'engine': 'postgresql', 'source_id': source_id,
        'query': 'SELECT id, status, tracking_code, ship_date, warehouse, weight_kg FROM shipments ORDER BY id',
        'columns': ['id', 'status', 'tracking_code', 'ship_date', 'warehouse', 'weight_kg'],
        'rows': wide_rows, 'row_count': 120, 'truncated': False, 'duration_ms': 34,
    }

    # A truncated result: the injected LIMIT was actually reached.
    scenarios['truncated'] = {
        'engine': 'postgresql', 'source_id': source_id,
        'query': 'SELECT id, status FROM shipments WHERE status = \'late\' LIMIT 200',
        'columns': ['id', 'status'],
        'rows': [[i, 'late'] for i in range(1, 201)],
        'row_count': 200, 'truncated': True, 'duration_ms': 41,
    }

    # A zero-row result: distinct from an error and from abstention.
    scenarios['zero'] = {
        'engine': 'postgresql', 'source_id': source_id,
        'query': \"SELECT id FROM shipments WHERE status = 'lost'\",
        'columns': ['id'], 'rows': [], 'row_count': 0, 'truncated': False, 'duration_ms': 9,
    }

    # A single-value result: one row, one column.
    scenarios['single'] = {
        'engine': 'postgresql', 'source_id': source_id,
        'query': \"SELECT count(*) FROM shipments WHERE status = 'late'\",
        'columns': ['count'], 'rows': [[42]], 'row_count': 1, 'truncated': False, 'duration_ms': 6,
    }

    async with session_factory(engine)() as session:
        conversation_id = uuid.uuid4()
        message_ids = {}
        for key, sql_result in scenarios.items():
            message_id = uuid.uuid4()
            await session.execute(text(\"INSERT INTO conversations (id) VALUES (:id) ON CONFLICT DO NOTHING\"), {'id': conversation_id})
            await session.execute(text(
                \"INSERT INTO messages (id, conversation_id, role, content, trace, summary, source_count, sql_result) \"
                \"VALUES (:id, :cid, 'assistant', :content, CAST(:trace AS jsonb), :summary, NULL, CAST(:sql_result AS jsonb))\"
            ), {
                'id': message_id, 'cid': conversation_id,
                'content': f'Found {sql_result[\"row_count\"]} rows.',
                'summary': 'Answered from your database.',
                'trace': json.dumps({'status': 'completed', 'steps': []}),
                'sql_result': json.dumps(sql_result),
            })
            message_ids[key] = str(message_id)
        await session.commit()
        with open('/tmp/result-manual-messages.json', 'w') as f:
            json.dump(message_ids, f)
        print(json.dumps(message_ids, indent=2))
    await engine.dispose()

asyncio.run(main())
"
```

**You should see:** a JSON object with four keys — `paginated`, `truncated`, `zero`, `single` —
each a message UUID, no error.

```
podman compose exec worker cat /tmp/result-manual-messages.json
```

Keep this output; the next steps use each id.

### 7. Open the paginated result in the browser

Take the `paginated` id from step 6 and open, in the browser's address bar:

```
http://127.0.0.1:8000/documents/?result=<paginated-id>
```

(As noted above, this is the same URL a click on a live "View full result and query" link would
open — there is no way to produce that click in this environment, see "Where this stops on
purpose".)

**You should see:**

- A page headed **Database result**.
- A table showing **120 rows**, with no truncation phrase next to the count (this result was not
  truncated).
- Six columns: `id`, `status`, `tracking_code`, `ship_date`, `warehouse`, `weight_kg`.
- The `id` and `weight_kg` columns right-aligned (numeric); the rest left-aligned.
- Some `status` cells reading `NULL` in italics (rows where `i % 17 == 0`), and others visibly
  blank rather than `NULL` (rows where `i % 23 == 0`) — the null-vs-empty distinction this
  ticket's own edge case names.
- Pagination controls reading **Page 1 of 3** (120 rows over the 50-row page size), with
  **Previous** disabled and **Next** enabled.
- Click **Next** twice: the page label updates to **Page 2 of 3** and then **Page 3 of 3**, the
  row values change each time, **Next** disables on the last page, and **Previous** re-enables
  after the first click.
- Widen and narrow the browser window, or check on a narrow viewport: the table scrolls
  horizontally inside its own bordered box rather than squeezing columns or breaking the page
  layout — the wide-result edge case.
- A **Show query** control below the table; clicking it reveals the exact `SELECT` text from step
  6 and **Hide query** replaces the button label; clicking again collapses it.

### 8. Open the truncated result

```
http://127.0.0.1:8000/documents/?result=<truncated-id>
```

**You should see:** **200 rows · First 200 rows shown — there may be more.** directly under the
table heading, on the same line as the count — the truncation label tied to the injected limit,
present here and absent in step 7's untruncated result. Pagination still works (**Page 1 of 4**).

### 9. Open the zero-row result

```
http://127.0.0.1:8000/documents/?result=<zero-id>
```

**You should see:** no table at all — the text **No matching records.** in place of it, with no
row count line above it and no pagination controls. **Show query** is still present below it and,
expanded, shows the `WHERE status = 'lost'` query — so it is possible to see the question was
answerable in principle, the query just found nothing, distinct in wording from an error page and
from an abstention message (neither of which appears here).

### 10. Open the single-value result

```
http://127.0.0.1:8000/documents/?result=<single-id>
```

**You should see:** the number **42**, rendered as a large standalone figure — not a one-cell
table, no header row, no row count line, no pagination. **Show query** is still present below it.

### 11. Confirm the "back to answer" link is present in every case

On any of the four pages above, on a wide-enough window (`@3xl` breakpoint), **you should see:**
a right-hand rail with a **Back to answer** link. Click it. **You should see:** the browser
return to the Ask screen (`/`).

---

## 2. Re-opening after a reload replays the stored snapshot, not a fresh query

### 12. Reload the paginated result page directly

With the `paginated` URL from step 7 still in the address bar, refresh the browser (F5 / Cmd-R).

**You should see:** the same 120-row table reappear after a brief **Opening…** message — this
page has no live turn in `AskProvider` (a hard reload clears that in-memory state), so this
confirms the fallback path in `DatabaseResultView` — fetching `GET /ask/{message_id}/stream` and
reading its `done` event's `sql_result` — actually works, not only the in-memory path.

### 13. Confirm a bad message id fails honestly

```
http://127.0.0.1:8000/documents/?result=00000000-0000-0000-0000-000000000000
```

**You should see:** **This result could not be opened.** — not a blank page, not a crash, not the
zero-rows message (which is a different, honest thing: a real query that found nothing, versus no
such stored answer at all).

---

## 3. Inline rendering in the live conversation — checked by code, not by clicking

Section 1 proves `SqlResultTable` renders correctly once a `sql_result` exists; what it cannot
prove in this environment is the same component appearing *inside* a just-answered turn on the
Ask screen itself, since that requires a turn that actually streamed through `AskProvider`, which
needs a model this environment does not have (see "Where this stops on purpose").

### 14. Confirm the wiring by reading the two files that connect them

```
grep -n "sqlResult" web/components/ask/ask-state.tsx web/components/ask/ask-screen.tsx
```

**You should see:** `ask-state.tsx` carrying `sqlResult: SqlResultData | null` on `AskTurn`, set
from `event.data.sql_result` on the `done` event (the same field `web/lib/ask.ts`'s `AskDoneData`
declares); and `ask-screen.tsx`'s `AnsweredContent` rendering
`<SqlResultTable result={turn.sqlResult} messageId={turn.serverId} turnId={turn.id} />` whenever
`turn.sqlResult !== null`, immediately after the answer prose and before the partial/conflict
annotations. This is the same component exercised by clicking through in Section 1 — nothing
about how it is invoked differs between the inline and source-viewer placements.

### 15. Run the automated unit suite for the pure logic underneath

```
scripts/dev.sh web-run node --test --experimental-strip-types lib/sql-result.test.ts
```

**You should see:** all tests pass — pagination clamping, the null/empty distinction, column
alignment, and the truncation label's exact wording, the same logic Section 1 exercised visually.

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
  a real `sql_result` here — every scenario above was written directly into `messages.sql_result`,
  the same substitution `docs/manual-tests/M4-SQL-BE-108a.md` made for the query-execution half of
  this same path.
- **The inline placement inside a live, just-streamed answer (`AnsweredContent`, `ask-screen.tsx`)
  is confirmed by code inspection (step 14) and the pure-logic unit suite (step 15), not by
  clicking through a real answer** — there is no click-only path in this environment that produces
  one. The rendering itself is proven end-to-end through the source viewer in Section 1, which
  uses the identical `SqlResultTable` component with the identical props shape.
- **Charts are out of scope** (the ticket's own Out of Scope line) — nothing above should be
  reported as missing for lacking one.
- **Export of a result set is out of scope** (M7) — there is no download or copy control on any
  of these pages, and that is expected.
- **Only PostgreSQL-shaped rows were exercised.** The rendering logic (`formatCell`, `columnAlign`)
  is engine-agnostic — it only ever sees JSON values — so this is a low-risk gap, not an untested
  code path, but no SQL Server or MySQL/MariaDB result was actually pushed through this document.
