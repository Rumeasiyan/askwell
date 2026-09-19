# Manual test — M5-EVAL-TEST-124, tool selection eval suite, including parallel calls

**Ticket:** `M5-EVAL-TEST-124` — twenty-five `tool_selection.v1` tasks (`pass_bar: 0.85`) driven
against the real `askwell.agent.loop.run_tool_loop`, scoring tool choice and the final answer
separately, three runs with worst-case reported, wired into the eval gate.
**Version under test:** check `cat VERSION`.
**Time:** about 25 minutes, with the stack already up and native inference already running; add
a first image build and stack start otherwise.
**Who can run it:** a terminal, the Postgres stack up, the `sandbox` service up, native
inference running on the host, `psql` access via `scripts/dev.sh psql`. **No browser.**
`eval/` has no UI, same as every ticket in this line (`M2-EVAL-TEST-063`, `M3-EVAL-TEST-086`,
`M4-EVAL-TEST-112`).

**What is being checked.** `eval/tool_selection.py` (`tool_choice_score`, `parallel_achieved`,
`combined_tool_score`, `run_tool_selection_suite`), `eval/suites/tool_selection.v1.json` (25
tasks, `mode: "tool_selection"`, `pass_bar: 0.85`), `eval/tests/test_tool_selection.py` (the
scoring logic, no database or model needed), `eval/bench.py`'s dispatch of the new mode, and
`.github/workflows/eval.yml`'s gate naming a seventh suite. The suite seeds both fixtures this
ticket depends on — `eval.grounded.seed_corpus` (the Meridian Loom document corpus) and
`eval.sql_fixture.seed_sql_fixture` (the customers/products/orders/support_tickets sandbox
database) — together, so a task can need either, both, or neither, per the module's own
docstring.

**Where this stops on purpose — read before reporting anything below as a defect.**

- **No UI walkthrough exists for this ticket, and none should be written for it.** `eval/` is a
  CLI harness with no screen, the same standing note `M4-EVAL-TEST-112.md` and
  `M3-EVAL-TEST-086.md` already recorded for this whole line of tickets.
- **Model quality is not asserted by this document.** This walkthrough confirms the suite seeds
  both fixtures, runs all 25 tasks through the real loop, scores tool choice and the final
  answer separately, and that removing parallel dispatch fails the parallel tasks specifically —
  the ticket's own acceptance criteria, made concrete rather than taken on faith. Whether your
  currently loaded model actually clears 0.85 today is whatever the suite prints, not a
  pass/fail this document enforces.
- **Latency is out of scope**, by the ticket's own line — nothing here times a call.
- **One fixture pair, English only, 25 tasks over one model** — the ticket's own stated known
  gap, repeated at the end of this document rather than treated as a defect found here.

---

## Before you start

```
cd ~/external/quantum-plus/askwell
```

If you have never run Askwell before, follow `M2-EVAL-TEST-065`'s "Before you start" and "Cold
start" sections first (`.env`, `build-api`, `check`, `podman compose up -d`, `db upgrade head`,
`scripts/dev.sh inference`). This suite additionally needs the `sandbox` service, which the
normal `podman compose up -d` already brings up alongside `api`, `worker`, `db`.

---

## Part A — the offline scoring tests

### 1. Run the new test module on its own

```
scripts/dev.sh run pytest /app/eval/tests/test_tool_selection.py -v
```

**You should see:** all thirteen tests pass with no database or model touched — `tool_choice_score`
matching a single accepted route, matching either of two accepted routes (the "two acceptable
tool routes" edge case), accepting no tool at all (the "correct behaviour is no tool" edge
case), rejecting a missing tool, and rejecting the tempting unnecessary extra call;
`parallel_achieved` true only when two fresh calls share one iteration, false when they land in
separate iterations, and unmoved by a deduplicated repeat; `combined_tool_score` unaffected when
parallel is not required, zeroed when required but not achieved, passing when required and
achieved, and not letting achieved parallelism paper over the wrong tools.

### 2. Confirm `scripts/dev.sh check` also covers it

```
scripts/dev.sh check
```

**You should see:** the lint/format/typecheck/test stages finish without red error text,
including `eval/tests/test_tool_selection.py` — runs unmarked, no network or database, same
discipline as every other eval scoring-logic test.

---

## Part B — cold start: seed both fixtures, run the suite for real

### 3. Confirm no fixture sources exist yet

```
scripts/dev.sh psql -c "SELECT name, status FROM sources WHERE name IN ('eval-sql-fixture') OR name LIKE '%.pdf' OR name LIKE '%.docx' OR name LIKE '%.xlsx';"
```

If this is a fresh database, **you should see:** `0 rows`. If a prior eval run already seeded
either fixture, that is fine — both seed functions are idempotent, so continue.

### 4. Run the tool-selection suite

```
scripts/dev.sh eval --suite tool_selection.v1
```

This indexes the nine-file Meridian Loom document corpus through the real `add()` →
`ingest.process()` path, loads the customers/products/orders/support_tickets sandbox database
and its one schema note the same way `M4-EVAL-TEST-112` did, then for each of the 25 tasks runs
the real `run_tool_loop` three times, scoring the distinct tools actually called against the
task's accepted routes and the final answer text separately, combining the two evenly.

**You should see:** a summary block ending with something like:

```
suite: tool_selection.v1 (tool_selection)
model: <the model name the supervisor loaded>  profile: balanced
runs per task: 3
pass_bar: 0.85  mean: <a number>  worst-of-3: <a number>
  tool-doc-password: mean: <n>  worst-of-3: <n>
  tool-doc-bluetooth: mean: <n>  worst-of-3: <n>
  ... (25 lines total)

written to /app/eval/results/tool_selection.v1-<timestamp>.json
```

### 5. Confirm both fixtures actually landed, through the real path

```
scripts/dev.sh psql -c "SELECT name, status FROM sources WHERE name = 'eval-sql-fixture';"
```

**You should see:** one row, `status = ready`.

```
scripts/dev.sh psql -c "SELECT COUNT(*) FROM sources WHERE name IN ('handbook_a.pdf','handbook_b.pdf','spec.docx','figures.xlsx','notice_scan.pdf','conflict_2025.pdf','conflict_2026.pdf','store_hours_2025.pdf','store_hours_2026.pdf');"
```

**You should see:** `9` — the whole Meridian Loom corpus, not only the two files this suite's
own tasks name (`handbook_a.pdf` for the listing task, `spec.docx` for the Loomwear Sensor
questions).

### 6. Read a task's own two scores, not only the combined number

```
cat eval/results/tool_selection.v1-*.json | python3 -c "
import json, sys
report = json.load(sys.stdin)
for task in report['task_results']:
    if task['task_id'] == 'tool-doc-password':
        for run in task['runs']:
            print(run['score'], run['error'])
"
```

**You should see:** for any run scoring below `1.0`, the `error` field's detail text naming
`tool_score=` and `answer_score=` separately with the tools actually called listed — the
ticket's own acceptance criterion ("tool choice and final answer are scored separately, so a
right answer by the wrong route is visible") checked directly. A run scoring `1.0` prints
`None` for `error`, which is also correct — nothing to explain about a clean pass.

### 7. Confirm the two-acceptable-routes and no-tool-at-all edge cases are in the suite, not just the code

```
grep -n "tool-schema-or-query-columns\|tool-listing-or-search-sensor-doc\|tool-no-tool-arithmetic\|tool-current-date" eval/suites/tool_selection.v1.json
```

**You should see:** `tool-schema-or-query-columns` and `tool-listing-or-search-sensor-doc` each
naming two `expected_tools` routes (`schema_lookup` or `database_query`; `document_listing` or
`document_search`) — the "two acceptable tool routes" edge case; `tool-no-tool-arithmetic`
naming an empty route (`[[]]`) — the "correct behaviour is to use no tool at all" edge case;
`tool-current-date` naming `current_date` alone — a question about the current date, the
ticket's own named example of a no-database-needed task.

### 8. Confirm the "tempted by an unnecessary database call" tasks are in the suite

```
grep -n "tool-tempt" eval/suites/tool_selection.v1.json
```

**You should see:** three tasks — `tool-tempt-db-revenue` and `tool-tempt-db-headcount` ask
about figures that live only in the document corpus (`figures.xlsx`'s Textiles/Logistics rows)
despite sounding like they belong in "the connected database"; `tool-tempt-doc-gear-products`
asks a question the suite explicitly routes to `database_query` despite naming a document-style
category count. `tool_choice_score` fails any run that calls the tempting extra tool alongside
the right one, per Part A's own test for this.

---

## Part C — a tool error mid-loop is recovered from, not fabricated past

### 9. Read back the two recovery tasks' scores

```
cat eval/results/tool_selection.v1-*.json | python3 -c "
import json, sys
report = json.load(sys.stdin)
for task in report['task_results']:
    if task['task_id'].startswith('tool-recover'):
        print(task['task_id'], [r['score'] for r in task['runs']])
"
```

**You should see:** `tool-recover-nonexistent-warehouses` and `tool-recover-nonexistent-vendors`
with scores at or near `1.0` — both ask about a table (`warehouses`, `vendors`) that does not
exist in the fixture schema, so `database_query` returns a `NOT_FOUND`-style tool error; the
`not_contains_any` scorer on digits `0`–`9` only passes if the model's final answer says it does
not know or the data is not present, rather than inventing a plausible-looking count after the
query fails. A low score here means the model fabricated a number past a real tool error, which
is this ticket's own "recovering from a tool error" behaviour failing, not an infrastructure
problem — re-read the task's `runs[*].output` in the same JSON file to see what it actually said.

---

## Part D — removing parallel dispatch fails the parallel tasks specifically

This is the ticket's own acceptance criterion, made concrete rather than taken on faith. Do this
on a branch or be ready to discard the change — you are editing product code, not eval code.

### 10. Confirm the parallel tasks currently pass, or read their state before the edit

```
cat eval/results/tool_selection.v1-*.json | python3 -c "
import json, sys
report = json.load(sys.stdin)
for task in report['task_results']:
    if task['task_id'].startswith('tool-parallel'):
        print(task['task_id'], [r['score'] for r in task['runs']])
"
```

Note these four scores (`tool-parallel-password-and-premium`,
`tool-parallel-warranty-and-cancelled`, `tool-parallel-listing-and-schema`,
`tool-parallel-bounty-and-enterprise`) before the edit below, whatever they are.

### 11. Disable parallel dispatch in the loop

Open `api/src/askwell/agent/loop.py` and find the concurrent dispatch line:

```python
            outcomes = await asyncio.gather(*(_run_one(n, a) for n, a, _ in run_now))
```

Replace it with a sequential loop that still produces one outcome per call, but never lets two
calls share an iteration:

```python
            outcomes = [await _run_one(n, a) for n, a, _ in run_now]
```

Do not touch anything else — the ceiling, deduplication and pending-call truncation above this
line stay exactly as they are; only the concurrency of dispatch changes.

### 12. Rebuild and rerun the suite

```
scripts/dev.sh build-api
scripts/dev.sh eval --suite tool_selection.v1
```

**You should see:** the overall `mean` drop, and specifically the four `tool-parallel-*` tasks
scoring `0.00` on every run — `parallel_achieved` can no longer find two fresh calls sharing one
iteration, because none are ever dispatched together anymore, so `combined_tool_score` zeroes
them out regardless of which tools were called or how correct the resulting answer text is.

```
cat eval/results/tool_selection.v1-*.json | python3 -c "
import json, sys
report = json.load(sys.stdin)
for task in report['task_results']:
    if task['task_id'].startswith('tool-parallel'):
        print(task['task_id'], [r['score'] for r in task['runs']], task['runs'][0]['error'])
"
```

**You should see:** each score `0.0` and the `error` text ending in `-- parallel dispatch
required but not achieved` for at least one run per task — the same detail string
`eval/tool_selection.py`'s `_run_tool_task` writes when `require_parallel` is true and
`achieved_parallel` is false.

### 13. Confirm the non-parallel tasks are not collaterally affected

```
cat eval/results/tool_selection.v1-*.json | python3 -c "
import json, sys
report = json.load(sys.stdin)
for task in report['task_results']:
    if not task['task_id'].startswith('tool-parallel'):
        pass
print('non-parallel tasks present:', sum(1 for t in report['task_results'] if not t['task_id'].startswith('tool-parallel')))
"
```

Compare the non-parallel tasks' scores against step 10's pre-edit run (or step 4's original
run) — they should be unchanged, since sequential dispatch still makes every call a single-tool
task needs, just not concurrently. Only the four tasks whose whole point is measuring
concurrency should have moved.

### 14. Revert the change

```
git diff api/src/askwell/agent/loop.py
git checkout -- api/src/askwell/agent/loop.py
scripts/dev.sh build-api
scripts/dev.sh eval --suite tool_selection.v1
```

**You should see:** the diff before discarding it (confirm it is only your one-line change),
then the four `tool-parallel-*` tasks scoring back near their step 10 values.

---

## Part E — the CI gate names the suite

### 15. Confirm the workflow includes it

```
grep -n "tool_selection.v1" .github/workflows/eval.yml
```

**You should see:** `tool_selection.v1` in the `for SUITE in ...` loop alongside
`grounded_qa.v1`, `abstention.v1`, `conflicting_sources.v1`, `memory_apply.v1`, `text_to_sql.v1`,
`sql_safety.v1`, and the job's own title line naming "tool selection" as the seventh suite.

### 16. Confirm each result is recorded with model and prompt version

```
cat eval/results/tool_selection.v1-*.json | python3 -c "
import json, sys
report = json.load(sys.stdin)
print('model:', report['model'])
print('prompt_versions:', report['prompt_versions'])
"
```

**You should see:** `model` naming the loaded model (not `null`), and `prompt_versions` a
non-empty mapping — this ticket's own Audit / Logging Requirement ("results recorded with model
and prompt version"), the same field every other suite in this repository already writes.

---

## Cleanup

```
rm -f eval/results/*.json
```

(Only remove result files you generated in this walkthrough — check `git status` first if
`eval/results/` had prior content you did not create.)

The Meridian Loom corpus sources and the `eval-sql-fixture` sandbox database are left in place —
seeding is idempotent and other suites (`grounded_qa.v1`, `text_to_sql.v1`, `sql_safety.v1`)
already share the same two fixtures.

If you dropped into Part D, confirm `git status` shows `api/src/askwell/agent/loop.py` clean
before finishing — step 14 reverts it, but check anyway before moving on.

---

## Known gaps

- **No UI walkthrough exists for this ticket, and none should be written for it** — `eval/` is a
  CLI harness with no screen, same as `M4-EVAL-TEST-112` and every other ticket in this line.
- **One fixture pair, English only, 25 tasks over one model** — the ticket's own stated known
  gap. This is not a defect found while writing this document.
- **Latency is not scored here**, by the ticket's own Out of Scope line — nothing above times a
  call; that belongs to the performance work.
- **Model quality is not asserted by this document.** Part B confirms the suite seeds both
  fixtures, runs all 25 tasks through the real loop, and reports mean/worst-of-3 correctly; Part
  D confirms removing parallel dispatch fails exactly the parallel tasks. Whether your currently
  loaded model clears 0.85 today is whatever the suite prints, not a pass/fail this walkthrough
  enforces.
- **No per-task runner.** Neither this suite nor `text_to_sql.v1`/`sql_safety.v1` has a `--task
  <id>` flag; isolating one task's result means running the full suite and filtering the written
  JSON, as steps 6, 8, 9, 10 and 13's inspection commands do.
- **CI itself is not re-run by this document.** Part E confirms the workflow file names the
  suite; it does not push a commit and watch the self-hosted `askwell`-labelled runner execute
  it — same standing note `M4-EVAL-TEST-112.md` recorded, since that trigger stays
  `workflow_dispatch`-only until issue #256 is resolved.
- **Part D edits and reverts real product code** (`loop.py`), not a test double — the only way
  to prove the suite fails end to end rather than only in a unit test of
  `combined_tool_score`. Do this on a branch, and confirm the revert with `git diff`/`git
  status` before moving on, per this repository's own git-safety rules.
