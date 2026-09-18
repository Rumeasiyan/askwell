# Manual test — M4-CSV-ING-093, never infer silently between date formats

**Ticket:** `M4-CSV-ING-093` — a date-shaped column whose numeric values do
not disambiguate DD/MM from MM/DD raises a two-option clarification, every
time. Where a value's own shape rules one format out (a day/month position
above 12), the format is inferred silently and recorded with its evidence.
A column mixing both directions within itself is reported as malformed,
never asked about as if one format fit every row.
**Version under test:** `0.4.2` (check `cat VERSION`).
**Time:** about 30 minutes, plus a first image build and stack start.
**Who can run it:** a terminal, the Postgres stack up, and a browser. Native
inference is not needed — nothing here embeds or answers a question.

**What is being checked.** `api/src/askwell/table_infer.py`'s
`detect_date_format`, `DateFormatVerdict`, the `date_format` field on
`ColumnInference`, `build_candidates`'s `date_format`-trigger candidate, and
`raise_table_inference`'s schema-note description for an inferred format.
`api/src/askwell/clarify.py`'s `_TRIGGER_PRIORITY` placing `date_format`
second, ahead of `document_identity` and `abbreviation`. `api/tests/
test_table_infer.py`, `api/tests/test_table_infer_db.py` and `api/tests/
test_clarify.py` cover the same ground under `scripts/dev.sh test` and
`test-db`; this walkthrough exercises it live instead of reading assertions.

**Where this stops on purpose.** Same as `M4-CSV-ING-092`: `sources.py`'s
routing is untouched, so this rule is not reachable by dropping a CSV on the
running app — no route calls `table_infer` yet (`M4-CSV-ING-094`'s own job).
Part A confirms that is still true, then Part B exercises the module
directly, the same way `M4-CSV-ING-092`'s own manual test did. Timezones are
out of scope and not exercised here.

---

## Before you start

```
cd ~/external/quantum-plus/askwell
mkdir -p askwell-test-material
```

If you have never run Askwell before:

```
cp -n .env.example .env
```

Open `.env`. Find `ASKWELL_ROOTS_MOUNT=` and set it to the folder above,
with your own path:

```
ASKWELL_ROOTS_MOUNT=/home/you/external/quantum-plus/askwell/askwell-test-material
```

Find `POSTGRES_APP_PASSWORD` and put any word after the `=` if it is blank.

---

## Cold start

### 1. Remove any previous state

```
podman compose down -v
```

**You should see:** lines about containers and volumes being removed, or a
note there was nothing to remove.

### 2. Run the checks

```
scripts/dev.sh check
```

**You should see:** lint, format, typecheck and test stages finish without
red error text — including `api/tests/test_table_infer.py`'s date-format
section and `api/tests/test_clarify.py`'s ranking tests.

```
scripts/dev.sh build-api
podman compose up -d
```

**You should see:** `postgres`, `redis`, `egress-proxy`, `api`, `worker`
reported as started. Wait about thirty seconds.

### 3. Create the database tables

```
scripts/dev.sh db upgrade head
```

**You should see:** migration lines finish with no error.

### 4. Run the database-backed tests too

```
scripts/dev.sh test-db
```

**You should see:** `api/tests/test_table_infer_db.py`'s date-format tests
pass — a disambiguated column recorded with its evidence, and an ambiguous
column raising a two-option clarification.

---

## Part A — cold start through the app: confirm a CSV is still not ingested today

### 5. Open the app and nominate the test folder

Open a browser at:

```
http://127.0.0.1:8000
```

**You should see:** the Askwell shell load with no sign-in prompt.

Click **Settings** in the left rail, scroll to **Folders Askwell may read**,
type your own path into the **Nominate a folder** field —

```
/home/you/external/quantum-plus/askwell/askwell-test-material
```

— and click **Nominate**. **You should see:** a box appear showing that
path, marked **Readable**.

### 6. Write a CSV whose registration dates do not disambiguate

```bash
scripts/dev.sh run python3 - <<'PY'
import os
os.makedirs("/app/askwell-test-material/registrations", exist_ok=True)
with open("/app/askwell-test-material/registrations/regs.csv", "w") as f:
    f.write("dt_reg\n01/02/2026\n03/04/2026\n05/06/2026\n")
print("done")
PY
```

**You should see:** the script print `done`. Every value in `dt_reg` has
both positions at or below 12, so nothing in the file itself says whether
it is day-first or month-first.

### 7. Add the folder by clicking through the app

Click **Library** in the left rail, then **Add source**. Choose **Files**,
click **Browse**, and select the `registrations` folder under your
nominated test folder (or drag the folder onto the screen).

**You should see:** the file listed as `regs.csv`, with a **later** state
— something naming that Askwell reads CSVs from a later milestone (`M4`)
and that nothing was added for it now. It is **not** shown as ingesting,
queued, or ready, and clicking it does not open a preview. This confirms
`sources.py`'s routing is still untouched — do not report this "later"
state as a defect; it is `M4-CSV-ING-094`'s own job to change it.

### 8. Confirm nothing landed in the database from that click

```
scripts/dev.sh psql -c "SELECT count(*) FROM sources WHERE kind = 'csv';"
```

**You should see:** `0`. The UI action in step 7 did not create a `sources`
row — there is no ingestion path for it yet.

---

## Part B — the module itself: the three date-format cases, exercised directly

### 9. Open a psql session and keep it open

```
scripts/dev.sh psql
```

Keep this terminal open for the rest of the walkthrough.

### 10. Insert a source row by hand (the only thing the UI would otherwise do)

`scripts/dev.sh run` has no network (`AGENTS.md` §5's `--network=none`
rule), so anything touching Postgres runs instead with
`podman compose exec api`, exec'ing into the already-running, already
networked `api` container.

In a second terminal:

```bash
podman compose exec api python3 - <<'PY'
import asyncio, os, uuid
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def main():
    url = os.environ["ASKWELL_DATABASE_URL"].replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        source_id = uuid.uuid4()
        await conn.execute(
            text("INSERT INTO sources (id, kind, name) VALUES (:id, 'csv', 'regs.csv')"),
            {"id": source_id},
        )
        print(source_id)
    await engine.dispose()

asyncio.run(main())
PY
```

**You should see:** one UUID printed — note it down as `SOURCE_ID`, used
below.

### 11. Case one — ambiguous: a column that never disambiguates raises a two-option question

```bash
scripts/dev.sh run python3 - <<'PY'
from askwell.table_infer import infer_csv

raw = b"dt_reg\n01/02/2026\n03/04/2026\n05/06/2026\n"
inference = infer_csv("regs.csv", raw)
col = inference.columns[0]
print("type:", col.inferred_type, "ambiguous:", col.ambiguous)
print("date_format verdict:", col.date_format.verdict if col.date_format else None)
print("candidates:", [(c.trigger, c.question, c.options) for c in inference.candidates])
PY
```

**You should see:** `type: date ambiguous: True`, `date_format verdict:
ambiguous`, and one candidate with `trigger = date_format`, a question
naming `dt_reg` and quoting sample values, and
`options = ['DD/MM/YYYY (day first)', 'MM/DD/YYYY (month first)']` — exactly
two discrete options, never a free-text prompt.

### 12. Case two — disambiguating: a day value above twelve is inferred silently, no question

```bash
scripts/dev.sh run python3 - <<'PY'
from askwell.table_infer import infer_csv

raw = b"dt_reg\n25/12/2026\n03/04/2026\n05/06/2026\n"
inference = infer_csv("regs2.csv", raw)
col = inference.columns[0]
print("ambiguous:", col.ambiguous)
print("date_format verdict:", col.date_format.verdict)
print("evidence value:", col.date_format.evidence_value)
print("evidence reason:", col.date_format.evidence_reason)
print("date_format candidates:", [c for c in inference.candidates if c.trigger == "date_format"])
PY
```

**You should see:** `ambiguous: False`, `date_format verdict: day_first`,
`evidence value: 25/12/2026`, `evidence reason: the first value, 25, cannot
be a month`, and an empty list of `date_format` candidates — `25` in the
first position rules out month-first, so the file disambiguates itself and
nothing is asked.

### 13. Case three — mixed: a column disambiguating in both directions is reported as malformed, not asked

```bash
scripts/dev.sh run python3 - <<'PY'
from askwell.table_infer import infer_csv

raw = b"dt_reg\n25/12/2026\n12/25/2026\n03/04/2026\n"
inference = infer_csv("regs3.csv", raw)
col = inference.columns[0]
print("type:", col.inferred_type, "ambiguous:", col.ambiguous)
print("reason:", col.ambiguity_reason)
print("date_format candidates:", [c for c in inference.candidates if c.trigger == "date_format"])
malformed = [c for c in inference.candidates if "dt_reg" in c.question]
print("malformed candidate options:", malformed[0].options if malformed else None)
PY
```

**You should see:** `type: string ambiguous: True` (the column falls back
out of `date` typing), a reason mentioning it mixes date formats
inconsistently because some values are only valid day-first and others only
valid month-first, zero `date_format` candidates, and one malformed-column
candidate whose `options` is `None` — this is the plain ambiguous-column
question, not a two-button date choice, because no single format fits every
row here.

### 14. Write case one to the database and confirm the clarification row

```bash
podman compose exec api python3 - <<'PY'
import asyncio, os, uuid
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from askwell.table_infer import infer_csv, raise_table_inference

SOURCE_ID = uuid.UUID("PASTE-YOUR-SOURCE-ID-HERE")

async def main():
    url = os.environ["ASKWELL_DATABASE_URL"].replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    raw = b"dt_reg\n01/02/2026\n03/04/2026\n05/06/2026\n"
    inference = infer_csv("regs.csv", raw)
    async with factory() as session:
        result = await raise_table_inference(session, SOURCE_ID, inference)
        await session.commit()
    print("raised:", result.raised, "capped:", result.capped)
    await engine.dispose()

asyncio.run(main())
PY
```

Paste the `SOURCE_ID` from step 10 in place of the placeholder.
**You should see:** `raised: 1 capped: 0`.

In the still-open psql session:

```sql
SELECT subject, question, options, status FROM clarifications WHERE source_id = 'PASTE-YOUR-SOURCE-ID-HERE';
```

**You should see:** one row, `status = pending`, `options` an array of the
two DD/MM/MM/DD strings, and `subject` naming `dt_reg`.

### 15. Open the app's clarifications screen and confirm the question ranks correctly

Click **Clarifications** in the left rail (or navigate there directly —
this is the same screen every other source's clarifications land on;
`regs.csv`'s question arrived through step 14, not through ingestion, and
the screen has no way to tell the difference).

**You should see:** a group for `regs.csv` with the `dt_reg` question shown
as two clickable buttons, `DD/MM/YYYY (day first)` and `MM/DD/YYYY (month
first)`, with an evidence block underneath showing the sample values and
their counts (`column_distribution` evidence, the kind that renders
correctly — unlike `M4-CSV-ING-092`'s own `table_preview` gap, issue #325,
which does not apply here). Answer the question by clicking one of the two
buttons.

**You should see:** the question move out of the pending list — the answer
was recorded the same way any other clarification answer is (a `memory`
row via `askwell.review.answer_clarification`).

### 16. Confirm ranking: a date-format question outranks an abbreviation question

```bash
scripts/dev.sh run python3 - <<'PY'
from askwell.clarify import Candidate, _rank_candidates

candidates = [
    Candidate(
        trigger="abbreviation",
        subject="doc.pdf",
        question="Does 'Q3' mean the third quarter?",
        passes=True,
        reason="abbreviation seen 4 times",
    ),
    Candidate(
        trigger="date_format",
        subject="t.csv: dt_reg",
        question="dt_reg looks like a date in DD/MM/YYYY or MM/DD/YYYY — which is it?",
        passes=True,
        reason="date format could not be determined",
        options=["DD/MM/YYYY (day first)", "MM/DD/YYYY (month first)"],
        evidence={"row_count": 10},
    ),
]
ranked = _rank_candidates(candidates)
print([c.trigger for c in ranked])
PY
```

**You should see:** `['date_format', 'abbreviation']` — the date question
sorts first, matching the priority table in `api/src/askwell/clarify.py`
(second only to `contradiction`, ahead of `document_identity` and
`abbreviation`).

### 17. Confirm the inferred format is recorded with its evidence, not just decided silently in memory

Repeat step 14's write, this time with case two's disambiguating file
(`raw = b"dt_reg\n25/12/2026\n03/04/2026\n05/06/2026\n"`, `name = "regs2.csv"`,
a fresh `SOURCE_ID` from a second run of step 10), then in psql:

```sql
SELECT column_name, origin, description FROM schema_notes WHERE source_id = 'PASTE-YOUR-SECOND-SOURCE-ID-HERE';
```

**You should see:** one row, `origin = inferred`, `description` containing
both `DD/MM/YYYY` and `25/12/2026` — the inferred label and the exact value
that ruled out the other format, together, so the inference can be checked
later against the evidence that produced it.

---

## Cleanup

```
podman compose down -v
```

Restore `.env` if you changed anything beyond what **Before you start** asked
for.

---

## Known gaps

- **Not wired to ingestion.** No route in `sources.py` calls `table_infer`
  yet — a CSV dropped through the app still shows the `later` state
  (Part A). This is `M4-CSV-ING-094`'s own scope, not a defect here.
- **Timezones are not handled.** Out of scope per the ticket; a date column
  is treated as a bare calendar date, never a timestamp with an offset.
- **Only two format options are offered.** DD/MM and MM/DD cover the
  realistic cases per the ticket's own assumption; any other date
  convention in a numeric column is handled as free text (typed `string`,
  not `date`), not as a third option.
- **No answer path applies the choice back onto a table.** Same gap
  `M4-CSV-ING-092`'s manual test recorded: answering the two-option
  question writes a `memory` row via the generic clarification-answer path,
  but there is no table yet (`M4-CSV-ING-094`) for the chosen format to be
  applied to. Step 15's "ask a question involving those dates and confirm
  the answer uses the chosen interpretation" from the ticket's own testing
  notes cannot be exercised today for that reason — not a defect of this
  ticket.
</content>
</invoke>
