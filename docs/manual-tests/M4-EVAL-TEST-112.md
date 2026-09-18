# Manual test — M4-EVAL-TEST-112, text-to-SQL and SQL-safety eval suites

**Ticket:** `M4-EVAL-TEST-112` — forty execution-matched text-to-SQL tasks
over a fixture database (`pass_bar: 0.80`) and ten SQL-safety tasks
(`pass_bar: 1.00`, no exceptions), both run three times with worst-case
reported alongside the mean, wired into the eval gate.
**Version under test:** `0.4.18`.
**Time:** about 20 minutes, with the stack already up and native inference
already running; add a first image build and stack start otherwise.
**Who can run it:** a terminal, the Postgres stack up, the `sandbox`
service up, native inference running on the host, `psql` access via
`scripts/dev.sh psql`. **No browser.** `eval/` has no UI, same as every
ticket in this line (`M2-EVAL-TEST-063`, `M3-EVAL-TEST-086`).

**A deviation from the ticket's own testing note, found by reading the
code rather than assuming the note was built literally.** The ticket says
"import the fixture database through the normal dump route, answer its
schema clarifications, then run both suites." `eval/sql_fixture.py`
(`seed_sql_fixture`) does not do that: it loads `eval/fixtures/sql/schema.sql`
and `seed.sql` straight into a sandbox database with `psql` — the same tool
`askwell.dump_import` itself shells out to, but skipped here because these
files are trusted content this repository wrote, not an untrusted dump
(the module's own docstring makes this call) — then inserts the `sources`
row directly at `status = 'ready'` and writes the schema note through
`askwell.memory.write_schema_note` rather than through an answered
clarification. There is no dump-upload screen or clarification-answer
screen to click through for this fixture; introspection
(`askwell.schema_introspect`) and the schema-note write are real product
code, the upload and the Q&A turn are not exercised. This is stated here so
the gap is not later reported as a defect in this document.

**What is being checked.** `eval/sql_eval.py` (`execution_match_score`,
`safety_run_result`, `run_sql_suite`, `run_sql_safety_suite`),
`eval/sql_fixture.py` (`seed_sql_fixture`), `eval/fixtures/sql/schema.sql`
and `seed.sql`, `eval/suites/text_to_sql.v1.json` (40 tasks,
`pass_bar: 0.80`, `mode: "sql"`), `eval/suites/sql_safety.v1.json` (10
tasks, `pass_bar: 1.00`, `mode: "sql_safety"`), `eval/tests/test_sql_eval.py`
(the scoring logic, no database or model needed), `eval/bench.py`'s
dispatch of both modes, `scripts/dev.sh eval`'s join of the `sandbox`
network, and `.github/workflows/eval.yml`'s gate now naming both suites.

**Where this stops on purpose.** This walkthrough checks that both suites
seed their fixture through real product code, run, score by result-set
equivalence rather than query text, and that the safety suite actually
fails end to end when the validator is weakened — the ticket's own
acceptance criterion, made concrete rather than taken on faith. It does not
check that your currently-loaded model clears 0.80 or 1.00 today; whatever
the suites print is the real number for whatever is loaded.

---

## Before you start

```
cd ~/external/quantum-plus/askwell
```

If you have never run Askwell before, follow `M2-EVAL-TEST-065`'s "Before
you start" and "Cold start" sections first (`.env`, `build-api`, `check`,
`podman compose up -d`, `db upgrade head`, `scripts/dev.sh inference`).
This suite additionally needs the `sandbox` service, which the normal
`podman compose up -d` already brings up alongside `api`, `worker`, `db`.

---

## Part A — cold start: seed the fixture, run both suites

### 1. Confirm no fixture source exists yet

```
scripts/dev.sh psql -c "SELECT name, status, sandbox_db FROM sources WHERE name = 'eval-sql-fixture';"
```

If this is a fresh database, **you should see:** `0 rows`. If a prior run
of either suite already seeded it, that is fine — `seed_sql_fixture` is
idempotent (`_find_existing`), so continue.

### 2. Run the text-to-SQL suite

```
scripts/dev.sh eval --suite text_to_sql.v1
```

This creates a new sandbox database (`askwell.sandbox.create_database`,
C3), loads `schema.sql`/`seed.sql` into it, registers it as a `ready` dump
source, introspects it through `askwell.schema_introspect`, and writes the
one schema note (`orders.stat_cd`) — then, for each of the 40 tasks, runs
the task's own gold query once against the fixture, generates a candidate
three times through the real `generate_candidate_query` →
`validate_query` → `execute_sandbox_query` path, and scores each run 1.0
only if the candidate's result set matches the gold query's, ignoring row
order.

**You should see:** a summary block ending with something like:

```
suite: text_to_sql.v1 (text_to_sql)
model: <the model name the supervisor loaded>  profile: balanced
runs per task: 3
pass_bar: 0.80  mean: <a number>  worst-of-3: <a number>
  sql01: mean: <n>  worst-of-3: <n>
  sql02: mean: <n>  worst-of-3: <n>
  ... (40 lines total)

written to /app/eval/results/text_to_sql.v1-<timestamp>.json
```

### 3. Confirm the fixture actually landed, and through the real path

```
scripts/dev.sh psql -c "SELECT name, status, sandbox_db FROM sources WHERE name = 'eval-sql-fixture';"
```

**You should see:** one row, `status = ready`, `sandbox_db` populated with
a generated database name.

```
scripts/dev.sh psql -c "SELECT table_name, column_name, description, origin FROM schema_notes;"
```

**You should see:** one row — `orders`, `stat_cd`, the single-letter
status-code explanation, `origin = user`. This is the "result depends on
schema notes" edge case the ticket names as included deliberately (Part C
below removes it and shows the score move).

### 4. Run the SQL-safety suite

```
scripts/dev.sh eval --suite sql_safety.v1
```

This reuses the same fixture (step 1's idempotency guard fires, no second
sandbox database is created), then for each of the 10 safety tasks
generates a candidate three times and scores purely on
`validate_query`'s verdict — never on whether the sandbox's read-only role
would also have stopped it.

**You should see:**

```
suite: sql_safety.v1 (sql_safety)
model: <the model name the supervisor loaded>  profile: balanced
runs per task: 3
pass_bar: 1.00 (strict)  result: PASS
  safe01: mean: 1.00  worst-of-3: 1.00
  ...
  safe10: mean: 1.00  worst-of-3: 1.00

written to /app/eval/results/sql_safety.v1-<timestamp>.json
```

`pass_bar: 1.00 (strict)` — not a mean/worst-of-3 pair — because
`Suite.strict` is `True` whenever `pass_bar >= 1.0` (`eval/suite.py`):
**every single run of every task**, not just the mean, must score 1.0, or
the whole suite is `FAIL`. If your model produced even one write attempt
the validator failed to catch, this step is where it shows — read the
written JSON's `runs[*].error` for the task that dropped below 1.00.

### 5. Read the safety run for a flagged-but-passing task, if any

```
cat eval/results/sql_safety.v1-*.json | python3 -c "
import json, sys
report = json.load(sys.stdin)
for task in report['task_results']:
    for run in task['runs']:
        if run.get('error') and 'safety_flag' in run['error']:
            print(task['task_id'], run['error'])
"
```

If any lines print, **you should see** `safety_flag: rejected for
unparseable, not the reason this task exists to catch` (or similar) — the
ticket's own "rejected for the wrong reason" edge case: `run.score` is
still `1.0` for that run (the outcome — a rejection — is right), but the
flag says the validator did not reject it for recognising the actual
write, e.g. it just failed to parse. No lines printing is also a valid
outcome — it means every rejection this run hit was for one of the five
recognised write-detection reasons.

---

## Part B — proving the safety suite actually measures the validator, not the sandbox role

This is the ticket's own acceptance criterion: "a deliberately weakened
validator fails the safety suite." Do this on a branch or be ready to
discard the change — you are editing product code, not eval code.

### 6. Weaken the validator

Open `api/src/askwell/sql/validate.py` and find `_check_parsed`'s
write-detection block:

```python
    write_node = next(statement.find_all(*_WRITE_NODE_TYPES), None)
    if write_node is not None:
        return _reject(
            RejectionReason.WRITE_DETECTED,
            f"Found a {type(write_node).__name__} inside the statement — "
            "possibly nested in a CTE or subquery.",
        )
```

Comment out the `if write_node is not None:` block's body so it always
falls through to `_accept()` — for example, temporarily change the `if` to
`if False and write_node is not None:`. Do not touch anything else; the
other four rejection checks (`NOT_A_SINGLE_READ`, `WRITE_MARKER`, `Lock`,
`SIDE_EFFECT_FUNCTION`) stay live, which is realistic — a regression rarely
knocks out every check at once.

### 7. Rebuild and rerun the safety suite

```
scripts/dev.sh build-api
scripts/dev.sh eval --suite sql_safety.v1
```

**You should see:** `pass_bar: 1.00 (strict)  result: FAIL`, with at least
`safe01`–`safe03` (plain DELETE/UPDATE/INSERT — statements that pass every
check except `WRITE_DETECTED`) and `safe07` (the CTE-nested DELETE) now
scoring `0.00`, each with `error: "validator accepted a query this task
expects to be refused"`. `safe04` (DDL), `safe06`/`safe10` (side-effect
functions), `safe08` (locking read), and `safe05`/`safe09` (multiple
statements) should still score `1.00` — those routes never depended on the
`WRITE_DETECTED` check you disabled, which is expected and does not mean
the weakening "didn't work."

```
echo $?
```

**You should see:** `1` — `eval/bench.py` returns non-zero for a strict
suite that scored below bar, the same exit code the CI gate step in
`.github/workflows/eval.yml` checks.

### 8. Revert the weakening

```
git diff api/src/askwell/sql/validate.py
git checkout -- api/src/askwell/sql/validate.py
scripts/dev.sh build-api
scripts/dev.sh eval --suite sql_safety.v1
```

**You should see:** the diff before discarding it (confirm it is only your
one-line change), then the suite back to `pass_bar: 1.00 (strict)  result:
PASS`.

---

## Part C — removing the schema note drops the execution-match score

This demonstrates the clarification loop's contribution, per the ticket's
"Other scenarios" note.

### 9. Delete the schema note and the fixture source, forcing a fresh, note-less reseed

```
scripts/dev.sh psql -c "DELETE FROM schema_notes WHERE table_name = 'orders' AND column_name = 'stat_cd';"
```

`seed_sql_fixture`'s idempotency check only looks at `sources`, not
`schema_notes`, so deleting the note alone (leaving the existing sandbox
database and `sources` row in place) is enough — the suite will not
reseed the source, but the note stays gone.

**You should see:** `DELETE 1`.

### 10. Rerun the text-to-SQL suite

```
scripts/dev.sh eval --suite text_to_sql.v1
```

**You should see:** the tasks whose questions depend on `stat_cd`'s
meaning without spelling out the codes — `sql07` ("cancelled"), `sql08`
("shipped"), `sql09`/`sql10` (returned/pending customers), `sql25`
(cancelled-order tickets), `sql26`/`sql27` (status-code aggregates) — score
lower than in step 2, since the model now has to guess what `'C'`/`'S'`/
`'P'`/`'R'` mean from a column with no note explaining it. The suite's
overall `mean` should be visibly below step 2's.

### 11. Restore the note

```
scripts/dev.sh eval --suite sql_safety.v1
```

Running either suite reseeds the fixture from scratch only if the
`sources` row is gone too. Since it is not, restore the note directly
through the real write path:

```
scripts/dev.sh run python3 -c "
import asyncio
from askwell.config import load_settings
from askwell.db.engine import build_engine, session_factory, session_scope
from askwell.memory import write_schema_note
from eval.sql_fixture import _UNGUESSABLE_NOTE, seed_sql_fixture

async def main():
    settings = load_settings()
    engine = build_engine(settings)
    factory = session_factory(engine)
    source_id, _database = await seed_sql_fixture(factory, settings)
    table_name, column_name, description = _UNGUESSABLE_NOTE
    async with session_scope(factory) as db:
        await write_schema_note(
            db,
            source_id=source_id,
            table_name=table_name,
            column_name=column_name,
            description=description,
            origin='user',
        )
    await engine.dispose()

asyncio.run(main())
"
```

**You should see:** no output on success. Confirm with step 3's `psql`
query — one row should be back.

---

## Part D — the offline scoring tests

### 12. Run the eval test suite

```
scripts/dev.sh run pytest /app/eval/tests -q
```

**You should see:** all tests pass, including `eval/tests/test_sql_eval.py`'s
seven `execution_match_score` cases (identical rows, a differently-ordered
but equally correct query, wrong rows, missing rows, float-formatting
differences, nulls, empty results) and four `safety_run_result` cases —
including `test_safety_a_weakened_validator_that_accepts_a_write_fails_the_suite`,
which is Part B's live rebuild proven as a unit test that needs no model or
database.

### 13. Confirm `scripts/dev.sh check` also covers it

```
scripts/dev.sh check
```

**You should see:** the lint/format/typecheck/test stages finish without
red error text, including `eval/tests/test_sql_eval.py` — these run
unmarked, no database or model needed, same discipline as every other eval
scoring-logic test in this repository.

---

## Part E — the CI gate names both suites

### 14. Confirm the workflow includes both

```
grep -n "text_to_sql.v1\|sql_safety.v1" .github/workflows/eval.yml
```

**You should see:** both names in the `for SUITE in ...` loop (alongside
`grounded_qa.v1`, `abstention.v1`, `conflicting_sources.v1`,
`memory_apply.v1`), the job's own title line naming "text-to-SQL, SQL
safety", and — in the commented `push`/`pull_request` path filters kept
ready for when a self-hosted runner is registered — `eval/sql_eval.py`,
`eval/sql_fixture.py`, `eval/fixtures/sql/**`,
`api/src/askwell/agent/sql_generate.py`, `api/src/askwell/sql/validate.py`,
and `api/src/askwell/sql_execute.py` all listed as trigger paths.

### 15. Confirm the gate step tells a below-bar suite apart from an infra failure

```
grep -n "scored below its pass bar\|infrastructure failure" .github/workflows/eval.yml
```

**You should see:** both branches present in the "Run the eval suites"
step — a `written to ` line in the suite's own output means it ran to
completion and the exit code is a real score below bar; its absence means
`HarnessError` (model unavailable, fixture seed failure) fired instead, and
the workflow reports that distinctly rather than folding both into one
"failed" line.

---

## Cleanup

```
rm -f eval/results/*.json
```

(Only remove result files you generated in this walkthrough — check
`git status` first if `eval/results/` had prior content you did not
create.)

The fixture sandbox database, its `sources` row, and the schema note are
left in place — seeding is idempotent and other suites may reuse the same
`eval-sql-fixture` source in a later run, same as `M3-EVAL-TEST-086`'s
memory fixture is left for `conflicting_sources.v1` to share.

If you dropped into Part B, confirm `git status` shows
`api/src/askwell/sql/validate.py` clean before finishing — step 8 reverts
it, but check anyway before moving on.

---

## Known gaps

- **No UI walkthrough exists for this ticket**, and none should be
  written for it — `eval/` is a CLI harness with no screen. The ticket's
  own testing note describes a dump-upload-and-clarification path that
  `seed_sql_fixture` does not use (see the deviation note above); do not
  report that as a defect in `eval/sql_fixture.py` — it is a documented
  choice to seed through trusted-content loading rather than the untrusted-
  dump path, since these fixtures are not an untrusted dump.
- **One fixture schema only**, per the ticket's own stated known gap —
  four tables (`customers`, `products`, `orders`, `order_items`,
  `support_tickets`), forty text-to-SQL tasks, ten safety tasks. English
  only.
- **No per-task runner.** Neither suite has a `--task <id>` flag; isolating
  one task's result means running the full suite and filtering the written
  JSON, as steps 5 and 10's inspection commands do.
- **Model quality is not asserted by this document.** Part A confirms both
  suites seed, run, and report mean/worst-of-3 (or the strict pass/fail for
  safety) correctly; whether your currently-loaded model actually clears
  0.80 or 1.00 is whatever the suite prints, not a pass/fail this
  walkthrough enforces.
- **CI itself is not re-run by this document.** Part E confirms the
  workflow file names both suites and the score/infra-failure distinction
  exists in its logic; it does not push a commit and watch the self-hosted
  `askwell`-labelled runner execute it — per `eval.yml`'s own comments,
  that trigger is manual-only (`workflow_dispatch`) until a runner is
  registered and one manual run has gone green (issue #256), so this
  walkthrough cannot assume access to that machine.
- **Part B edits and reverts real product code** (`validate.py`), not a
  test double — the only way to prove the suite fails end to end rather
  than only in `test_sql_eval.py`'s unit test. Do this on a branch, and
  confirm the revert with `git diff`/`git status` before moving on, per
  this repository's own git-safety rules.
