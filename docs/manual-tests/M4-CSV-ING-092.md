# Manual test — M4-CSV-ING-092, parse spreadsheets and CSVs with type and header inference

**Ticket:** `M4-CSV-ING-092` — parse `.csv`/`.tsv`/`.xlsx`, detect delimiter
and encoding, decide whether the first row is a header, infer a type and
confidence per column, and raise a real clarification for anything that
cannot be resolved — a missing header, an ambiguous header vote, a blank
header cell, a column mixing two number formats, a merged `.xlsx` header
cell. Nothing is applied silently.
**Version under test:** `0.4.1` (check `cat VERSION`).
**Time:** about 45 minutes, plus a first image build and stack start.
**Who can run it:** a terminal, the Postgres stack up, and a browser. Native
inference is not needed — nothing here embeds or answers a question.

**What is being checked.** `api/src/askwell/table_infer.py` end to end:
`sniff_encoding`, `sniff_delimiter`, `parse_rows`/`MalformedTable`,
`detect_header`, `infer_column_types`, `build_candidates`, `infer_csv`,
`infer_xlsx`, and `raise_table_inference` (real `schema_notes` and
`clarifications` rows, idempotent per source, capped the same way document
candidates are). `api/tests/test_table_infer.py` (pure functions, no
database) and `api/tests/test_table_infer_db.py` (`raise_table_inference`
against real Postgres) cover the same ground under `scripts/dev.sh test`
and `test-db`; this walkthrough exercises it live instead of reading
assertions.

**Where this stops on purpose.** `docs/BRAIN.md` is explicit that this
ticket is **not wired to ingestion**: `sources.py`'s routing is untouched,
so dropping a CSV or `.xlsx` on the running app today still reports it as
arriving in a later milestone (`M4-CSV-ING-094`'s own job) — nothing about
that is a defect of this ticket. Part A below confirms that is still true.
Because no route reaches this module yet, Part B exercises it directly
through `scripts/dev.sh run python3`, the same way `M3-RAISE-BE-071`'s own
Part F exercised `column_distribution_evidence` before anything called it —
inserting one `sources` row by hand and calling `infer_csv`/`infer_xlsx`/
`raise_table_inference` against the real database, never a paraphrase of
what the functions return. The date-format rule (DD/MM vs MM/DD,
`M4-CSV-ING-093`) and loading the inferred table as a queryable sandbox
table (`M4-CSV-ING-094`) are out of scope and not exercised here.

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
red error text — including `api/tests/test_table_infer.py`.

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

**You should see:** `api/tests/test_table_infer_db.py`'s three tests pass —
columns landing in `schema_notes`, an unresolvable column raising a real
`clarifications` row, and a source that already has one not being re-scanned.

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

### 6. Write a small CSV with a missing header and an ambiguous amount column

```bash
scripts/dev.sh run python3 - <<'PY'
import os
os.makedirs("/app/askwell-test-material/finance", exist_ok=True)
with open("/app/askwell-test-material/finance/ledger.csv", "w") as f:
    f.write("Anna;1,200.00;2026-01-01\nBen;1200.5;2026-01-02\nCleo;980.25;2026-01-03\n")
print("done")
PY
```

**You should see:** the script print `done`. This file is semicolon-delimited
(so the thousands separator inside the amount column is never mistaken for
the column separator itself), has no header row, and its second column
mixes a thousands-separated amount (`1,200.00`) with plain decimals
(`1200.5`, `980.25`) — the ticket's own ambiguous-column example.

### 7. Add the folder by clicking through the app

Click **Library** in the left rail, then **Add source**. Choose **Files**,
click **Browse**, and select the `finance` folder under your nominated test
folder (or drag the folder onto the screen).

**You should see:** the file listed as `ledger.csv`, with a **later** state
— something naming that Askwell reads CSVs from a later milestone (`M4`)
and that nothing was added for it now. It is **not** shown as ingesting,
queued, or ready, and clicking it does not open a preview. This confirms
`docs/BRAIN.md`'s own note that `sources.py`'s routing is untouched by this
ticket — do not report this "later" state as a defect; it is `M4-CSV-ING-094`'s
own job to change it.

### 8. Confirm nothing landed in the database from that click

```
scripts/dev.sh psql -c "SELECT count(*) FROM sources WHERE kind = 'csv';"
```

**You should see:** `0`. The UI action in step 7 did not create a `sources`
row — there is no ingestion path for it yet.

---

## Part B — the module itself: parsing, inference and clarifications, exercised directly

### 9. Open a psql session and keep it open

```
scripts/dev.sh psql
```

Keep this terminal open for the rest of the walkthrough.

### 10. Insert a source row by hand (the only thing the UI would otherwise do)

`scripts/dev.sh run` deliberately has no network (`AGENTS.md` §5's own
`--network=none` rule), so anything touching Postgres runs instead with
`podman compose exec api`, the same way `AGENTS.md` §5 runs
`askwell-verify` — exec'ing into the already-running, already-networked
`api` container, not a fresh egress path.

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
            text("INSERT INTO sources (id, kind, name) VALUES (:id, 'csv', 'ledger.csv')"),
            {"id": source_id},
        )
        print(source_id)
    await engine.dispose()

asyncio.run(main())
PY
```

**You should see:** one UUID printed — note it down as `SOURCE_ID`, used
below.

### 11. Parse the file with the missing header and ambiguous amount column, and inspect what was inferred before anything is written

```bash
scripts/dev.sh run python3 - <<'PY'
from askwell.table_infer import infer_csv

with open("/app/askwell-test-material/finance/ledger.csv", "rb") as f:
    raw = f.read()

inference = infer_csv("ledger.csv", raw)
print("header verdict:", inference.header.verdict)
print("header confidence:", inference.header.confidence)
print("column names:", [c.name for c in inference.columns])
for c in inference.columns:
    print(f"  {c.name}: type={c.inferred_type} confidence={c.confidence:.2f} ambiguous={c.ambiguous} reason={c.ambiguity_reason}")
print("candidates raised:", len(inference.candidates))
for cand in inference.candidates:
    print(" -", cand.trigger, "|", cand.question)
PY
```

**You should see:** `header verdict: absent` (`HeaderDetection.verdict` is a
`StrEnum` and prints as its value — the first row's own cells classify the
same way the data rows beneath them do, a decimal-shaped amount and a
date-shaped date in both, so it reads as one more data row, not names),
`delimiter: ;`, column names `Column 1`, `Column 2`, `Column 3`; `Column 1`
(name) reported as `type=string confidence=1.00 ambiguous=False` (a text
column resolved with full confidence, not an unresolved guess), `Column 3`
(date) as `type=date confidence=1.00 ambiguous=False`, and `Column 2`
(amount) as `type=string confidence=1.00 ambiguous=True` with a reason
naming the thousands-separator/plain-decimal mix — every value individually
parses as a decimal (hence the full confidence), but not as the *same
shape* of decimal, which is exactly what `_mixed_number_format` exists to
catch. Two candidates: one `table_header` question (no header row detected,
asking what the three columns should be called) and one `table_column`
question about `Column 2` asking about currency and units. This is the
type and header information sitting for review, unapplied — nothing in
this step wrote to the database.

### 12. Write the inference to the database, the way `raise_table_inference` does

`ledger.csv` was written in step 6 through `scripts/dev.sh run`, which
bind-mounts the whole repo at `/app` — so on the host it landed at
`ASKWELL_ROOTS_MOUNT/finance/ledger.csv` (the same path you nominated in
step 5, since your `askwell-test-material` folder is both). The `api`
container mounts `ASKWELL_ROOTS_MOUNT` read-only **at that same absolute
host path**, not under `/app`, so this step reads it from there instead:

```bash
podman compose exec api python3 - <<'PY'
import asyncio, os, uuid
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from askwell.table_infer import infer_csv, raise_table_inference

SOURCE_ID = uuid.UUID("PASTE-YOUR-SOURCE-ID-HERE")
LEDGER_PATH = "/home/you/external/quantum-plus/askwell/askwell-test-material/finance/ledger.csv"  # your own ASKWELL_ROOTS_MOUNT path

async def main():
    url = os.environ["ASKWELL_DATABASE_URL"].replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    with open(LEDGER_PATH, "rb") as f:
        raw = f.read()
    inference = infer_csv("ledger.csv", raw)
    async with factory() as session:
        result = await raise_table_inference(session, SOURCE_ID, inference)
        await session.commit()
    print("raised:", result.raised, "capped:", result.capped)
    await engine.dispose()

asyncio.run(main())
PY
```

Paste the `SOURCE_ID` from step 10, and your own `ASKWELL_ROOTS_MOUNT` path,
in place of the placeholders.
**You should see:** `raised: 2 capped: 0`.

### 13. Confirm the schema notes, in the still-open psql session

```sql
SELECT column_name, origin, confidence, description FROM schema_notes WHERE source_id = 'PASTE-YOUR-SOURCE-ID-HERE' ORDER BY column_name;
```

**You should see:** three rows, one per column, every `origin` reading
`inferred`. `Column 2`'s `description` states the thousands/plain-decimal
mix reason; the other two columns' types match whatever step 11 printed for
them. The point is that every row carries a real confidence number, never
a blank or a silently-picked type.

### 14. Confirm the real clarification rows

```sql
SELECT subject, question, status, evidence->>'kind' AS evidence_kind FROM clarifications WHERE source_id = 'PASTE-YOUR-SOURCE-ID-HERE' ORDER BY rank;
```

**You should see:** two rows, both `status = pending`: the header question
with `evidence_kind = table_preview` (the raw first-three-rows preview
`build_candidates` attaches to header questions), and the `Column 2`
question with `evidence_kind = column_distribution` (the value/count
distribution `column_distribution_evidence` builds). Same source, two
different evidence shapes — this pair is what step 15 checks on screen.

### 15. Open the app's clarifications screen and find both questions

Click **Clarifications** in the left rail (or navigate there directly —
this is the same screen every other source's clarifications land on;
`ledger.csv`'s two questions arrived through step 12, not through
ingestion, and the screen has no way to tell the difference).

**You should see:** a group for `ledger.csv` with two pending questions —
one asking whether the file has a header row and what to call the columns,
one asking about `Column 2`'s currency/units.

**Look at the evidence block under each of the two.** The `Column 2`
question shows real values with their counts (the `column_distribution`
evidence from step 14) — this one renders correctly. The header question's
evidence block instead reads **"No evidence available."**, even though
step 14 confirmed a real `table_preview` row exists with the file's first
three rows in it. This is a real, confirmed gap, not something wrong with
this ticket's own data: `web/lib/clarifications.ts`'s `evidenceDisplay`
has a case for `column_distribution` but none for `table_preview`, so it
falls through to `null` and the screen shows the same message it uses for
a genuinely missing evidence column. Filed as issue #325 — do not report
this again as a new finding.

---

## Part C — encoding, delimiter and malformed-row edge cases, exercised directly

### 16. A semicolon-delimited file in a non-UTF-8 encoding

Plain ASCII text decodes as valid UTF-8 regardless of what it was authored
in, so this needs a byte that is only meaningful in `windows-1252` — the
same curly quotes `test_windows_1252_is_named_rather_than_reported_as_latin1`
uses:

```bash
scripts/dev.sh run python3 - <<'PY'
from askwell.table_infer import infer_csv

raw = "name;note;date\nAnna;“paid”;2026-01-01\nBen;“pending”;2026-01-02\n".encode("windows-1252")
inference = infer_csv("legacy.csv", raw)
print("encoding:", inference.encoding.encoding, inference.encoding.confidence)
print("delimiter:", inference.delimiter.delimiter)
PY
```

**You should see:** `encoding: windows-1252 <a confidence below 1.0>`
(named, not silently treated as UTF-8 or the always-succeeding `latin-1`
fallback) and `delimiter: ;`.

### 17. A file whose row widths disagree

```bash
scripts/dev.sh run python3 - <<'PY'
from askwell.table_infer import infer_csv, MalformedTable

raw = b"name,amount\nAnna,10\nBen,20,extra\nCleo,30\n"
try:
    infer_csv("ragged.csv", raw)
    print("no error raised - this would be a bug")
except MalformedTable as e:
    print("row_numbers:", e.row_numbers)
    print("expected:", e.expected)
    print(str(e))
PY
```

**You should see:** `row_numbers: [3]`, `expected: 2`, and a message naming
row 3 as not having 2 columns — reported with the row number, never
silently padded or truncated.

### 18. A blank header cell, with value-distribution evidence

```bash
scripts/dev.sh run python3 - <<'PY'
from askwell.table_infer import infer_csv

raw = b"name,,date\nAnna,10,2026-01-01\nBen,20,2026-01-02\nCleo,30,2026-01-03\n"
inference = infer_csv("blank-header.csv", raw)
for cand in inference.candidates:
    print(cand.trigger, "|", cand.subject, "|", cand.evidence.get("kind"))
PY
```

**You should see:** one candidate naming `Column 2` with
`evidence.kind = column_distribution` — this is the evidence kind that
**does** render correctly on the clarifications screen (step 15's note).

### 19. An `.xlsx` sheet with a merged header cell

```bash
scripts/dev.sh run python3 - <<'PY'
import io
import openpyxl
from askwell.table_infer import infer_xlsx

workbook = openpyxl.Workbook()
sheet = workbook.active
sheet.append(["group", "", "amount"])
sheet.append(["Anna", "x", 10])
sheet.append(["Ben", "y", 20])
sheet.merge_cells("A1:B1")
buffer = io.BytesIO()
workbook.save(buffer)

results = infer_xlsx("report.xlsx", buffer.getvalue())
print("sheets:", len(results))
print("merged_header:", results[0].merged_header)
print([c.trigger for c in results[0].candidates])
PY
```

**You should see:** `sheets: 1`, `merged_header: True`, and a
`table_header` candidate among the trigger list, naming the merged cell —
flagged rather than guessed, `docs/data-sources.md` §8's settled default.

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
  yet — a CSV or `.xlsx` dropped through the app still shows the `later`
  state (Part A). This is `M4-CSV-ING-094`'s own scope, not a defect here.
- **Header-preview evidence does not render on the clarifications screen.**
  `evidence.kind = table_preview` (used for missing-header, ambiguous-header
  and merged-header questions) has no case in `web/lib/clarifications.ts`'s
  `evidenceDisplay`, so those two of the three candidate kinds this ticket
  raises show "No evidence available." on screen even though the row
  preview is stored correctly (Part B, steps 14–15). `column_distribution`
  evidence (blank header cells, ambiguous-type columns) renders correctly.
  Filed as issue #325.
- **No answer path for table clarifications specifically.** `Save`/`Skip`
  on the clarifications screen call `askwell.review.answer_clarification`,
  which writes a `memory` row — table clarifications raised here go through
  the same generic path, but nothing yet *applies* an answered header-name
  or column-type question back onto a table (there is no table to apply it
  to, since loading is `M4-CSV-ING-094`). Answering one of these questions
  today records the answer in `memory` and nothing else changes.
- **The date-format rule is not built.** A date-shaped column is typed
  `date` with no format decided — `M4-CSV-ING-093`'s own scope.
- **Multi-sheet and merged-cell semantics remain crude by design.** One
  sheet becomes one table; a merged header cell is flagged, never resolved
  automatically — the ticket's own stated limitation, not something this
  walkthrough should report as a defect.
</content>
